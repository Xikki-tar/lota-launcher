#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter};

const API_BASES: [&str; 2] = ["https://ru.lota.work", "https://eu.lota.work"];
const CHECK_TIMEOUT: Duration = Duration::from_secs(5);
const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(300);
const SKIP_UPDATER_ARG: &str = "--skip-updater";
const LAUNCHER_EXE: &str = "lota-launcher.exe";
const BACKEND_EXE: &str = "backend.exe";
const UPDATER_EXE: &str = "updater.exe";
const VERSION_FILE: &str = "launcher.version";
const PLATFORM: &str = "windows-x86_64";
const CHANNEL: &str = "stable";

#[derive(Clone, Serialize)]
struct StatusPayload {
    text: String,
}

#[derive(Clone, Serialize)]
struct ProgressPayload {
    percent: u32,
}

#[derive(Deserialize, Clone, Default)]
struct RuntimeArtifact {
    #[serde(default)]
    version: String,
    #[serde(default)]
    sha256: String,
    #[serde(default)]
    size: u64,
    #[serde(default)]
    url: String,
}

#[derive(Deserialize, Default)]
struct RuntimeCheckResponse {
    #[serde(default)]
    ok: bool,
    #[serde(default)]
    artifacts: HashMap<String, RuntimeArtifact>,
}

fn exe_dir() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."))
}

fn read_local_version(dir: &Path) -> String {
    std::fs::read_to_string(dir.join(VERSION_FILE))
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "0.0.0".to_string())
}

fn emit_status(app: &AppHandle, text: impl Into<String>) {
    let _ = app.emit("status", StatusPayload { text: text.into() });
}

fn emit_progress(app: &AppHandle, percent: u32) {
    let _ = app.emit("progress", ProgressPayload { percent });
}

fn version_tuple(v: &str) -> Vec<u32> {
    v.trim()
        .trim_start_matches(['v', 'V'])
        .split('.')
        .map(|chunk| {
            let digits: String = chunk.chars().filter(char::is_ascii_digit).collect();
            digits.parse().unwrap_or(0)
        })
        .collect()
}

fn version_newer(remote: &str, local: &str) -> bool {
    let mut r = version_tuple(remote);
    let mut l = version_tuple(local);
    let len = r.len().max(l.len());
    r.resize(len, 0);
    l.resize(len, 0);
    r > l
}

async fn fetch_runtime_manifest() -> Option<(String, RuntimeCheckResponse)> {
    let client = reqwest::Client::builder().timeout(CHECK_TIMEOUT).build().ok()?;
    let payload = serde_json::json!({ "platform": PLATFORM, "channel": CHANNEL });

    for base in API_BASES {
        let url = format!("{base}/api/runtime/check");
        let Ok(resp) = client.post(&url).json(&payload).send().await else {
            continue;
        };
        let Ok(data) = resp.json::<RuntimeCheckResponse>().await else {
            continue;
        };
        if data.ok {
            return Some((base.to_string(), data));
        }
    }
    None
}

async fn download_artifact(
    app: &AppHandle,
    base: &str,
    artifact: &RuntimeArtifact,
    tmp_path: &Path,
    status_label: &str,
) -> Result<(), String> {
    emit_status(app, status_label);

    let client = reqwest::Client::builder()
        .timeout(DOWNLOAD_TIMEOUT)
        .build()
        .map_err(|e| e.to_string())?;
    let url = if artifact.url.starts_with("http") {
        artifact.url.clone()
    } else {
        format!("{base}{}", artifact.url)
    };
    let resp = client.get(&url).send().await.map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    let total = resp.content_length().unwrap_or(artifact.size);

    let mut file = std::fs::File::create(tmp_path).map_err(|e| e.to_string())?;
    let mut hasher = Sha256::new();
    let mut downloaded: u64 = 0;

    let mut stream = resp.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| e.to_string())?;
        file.write_all(&chunk).map_err(|e| e.to_string())?;
        hasher.update(&chunk);
        downloaded += chunk.len() as u64;
        if total > 0 {
            emit_progress(app, ((downloaded * 100) / total).min(100) as u32);
        }
    }
    drop(file);

    if downloaded == 0 {
        let _ = std::fs::remove_file(tmp_path);
        return Err("empty download".to_string());
    }

    let digest = format!("{:x}", hasher.finalize());
    if !artifact.sha256.is_empty() && digest.to_lowercase() != artifact.sha256.to_lowercase() {
        let _ = std::fs::remove_file(tmp_path);
        return Err("sha256 mismatch".to_string());
    }

    Ok(())
}

fn replace_with_retry(src: &Path, dest: &Path) -> Result<(), String> {
    let mut last_err = String::new();
    for _ in 0..10 {
        match std::fs::rename(src, dest) {
            Ok(()) => return Ok(()),
            Err(e) => {
                last_err = e.to_string();
                std::thread::sleep(Duration::from_millis(500));
            }
        }
    }
    Err(last_err)
}

async fn launch_launcher_and_exit(app: &AppHandle, dir: &Path) {
    let launcher_path = dir.join(LAUNCHER_EXE);
    let _ = Command::new(&launcher_path)
        .arg(SKIP_UPDATER_ARG)
        .current_dir(dir)
        .spawn();

    std::thread::sleep(Duration::from_millis(300));
    app.exit(0);
}

async fn run_update_flow(app: AppHandle) {
    let dir = exe_dir();
    let local_version = read_local_version(&dir);
    emit_status(&app, "Проверяю обновления...");

    let Some((base, manifest)) = fetch_runtime_manifest().await else {
        launch_launcher_and_exit(&app, &dir).await;
        return;
    };

    let Some(launcher_artifact) = manifest.artifacts.get("launcher") else {
        launch_launcher_and_exit(&app, &dir).await;
        return;
    };

    if !version_newer(&launcher_artifact.version, &local_version) {
        launch_launcher_and_exit(&app, &dir).await;
        return;
    }

    let tmp_dir = std::env::temp_dir().join(format!("lota-update-{}", std::process::id()));
    let _ = std::fs::create_dir_all(&tmp_dir);

    let targets: [(&str, PathBuf, &str); 4] = [
        ("launcher", dir.join(LAUNCHER_EXE), "Скачиваю lota-launcher.exe..."),
        ("backend", dir.join(BACKEND_EXE), "Скачиваю backend.exe..."),
        ("updater", dir.join(format!("{UPDATER_EXE}.new")), "Скачиваю updater.exe..."),
        ("version", dir.join(VERSION_FILE), "Обновляю launcher.version..."),
    ];

    let mut failed = false;
    for (name, dest, label) in targets {
        let Some(artifact) = manifest.artifacts.get(name) else {
            continue;
        };
        let tmp_path = tmp_dir.join(name);
        match download_artifact(&app, &base, artifact, &tmp_path, label).await {
            Ok(()) => {
                if replace_with_retry(&tmp_path, &dest).is_err() {
                    failed = true;
                }
            }
            Err(_) => failed = true,
        }
    }

    emit_status(
        &app,
        if failed {
            "Часть файлов не удалось обновить, запускаю..."
        } else {
            "Готово, запускаю..."
        },
    );
    let _ = std::fs::remove_dir_all(&tmp_dir);

    launch_launcher_and_exit(&app, &dir).await;
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                run_update_flow(handle).await;
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running updater");
}
