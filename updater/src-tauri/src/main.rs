// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

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

#[derive(Clone, Serialize)]
struct StatusPayload {
    text: String,
}

#[derive(Clone, Serialize)]
struct ProgressPayload {
    percent: u32,
}

#[derive(Deserialize, Default)]
struct CheckResponse {
    #[serde(default)]
    ok: bool,
    #[serde(default)]
    update_available: bool,
    #[serde(default)]
    version: String,
    #[serde(default)]
    url: String,
    #[serde(default)]
    sha256: String,
    #[serde(default)]
    size: u64,
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

fn write_local_version(dir: &Path, version: &str) {
    if !version.is_empty() {
        let _ = std::fs::write(dir.join(VERSION_FILE), version);
    }
}

fn emit_status(app: &AppHandle, text: impl Into<String>) {
    let _ = app.emit("status", StatusPayload { text: text.into() });
}

fn emit_progress(app: &AppHandle, percent: u32) {
    let _ = app.emit("progress", ProgressPayload { percent });
}

async fn check_update(local_version: &str) -> Option<CheckResponse> {
    let client = reqwest::Client::builder()
        .timeout(CHECK_TIMEOUT)
        .build()
        .ok()?;
    let payload = serde_json::json!({
        "platform": "windows-x86_64",
        "version": local_version,
        "channel": "stable",
    });

    for base in API_BASES {
        let url = format!("{base}/api/launcher/check");
        let Ok(resp) = client.post(&url).json(&payload).send().await else {
            continue;
        };
        let Ok(data) = resp.json::<CheckResponse>().await else {
            continue;
        };
        if data.ok {
            return Some(data);
        }
    }
    None
}

async fn download_and_verify(
    app: &AppHandle,
    url: &str,
    sha256: &str,
    expected_size: u64,
    dest_dir: &Path,
) -> Result<PathBuf, String> {
    emit_status(app, "Скачиваю обновление...");

    let client = reqwest::Client::builder()
        .timeout(DOWNLOAD_TIMEOUT)
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client.get(url).send().await.map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    let total = resp.content_length().unwrap_or(expected_size);

    let zip_path = dest_dir.join("update.zip");
    let mut file = std::fs::File::create(&zip_path).map_err(|e| e.to_string())?;
    let mut hasher = Sha256::new();
    let mut downloaded: u64 = 0;

    let mut stream = resp.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| e.to_string())?;
        file.write_all(&chunk).map_err(|e| e.to_string())?;
        hasher.update(&chunk);
        downloaded += chunk.len() as u64;
        if total > 0 {
            let pct = ((downloaded * 100) / total).min(100) as u32;
            emit_progress(app, pct);
        }
    }
    drop(file);

    if downloaded == 0 {
        let _ = std::fs::remove_file(&zip_path);
        return Err("empty download".to_string());
    }

    let digest = format!("{:x}", hasher.finalize());
    if !sha256.is_empty() && digest.to_lowercase() != sha256.to_lowercase() {
        let _ = std::fs::remove_file(&zip_path);
        return Err("sha256 mismatch".to_string());
    }

    Ok(zip_path)
}

fn extract_zip(zip_path: &Path, dest_dir: &Path) -> Result<(), String> {
    let file = std::fs::File::open(zip_path).map_err(|e| e.to_string())?;
    let mut archive = zip::ZipArchive::new(file).map_err(|e| e.to_string())?;
    archive.extract(dest_dir).map_err(|e| e.to_string())?;
    Ok(())
}

// Windows держит только что скачанный exe заблокированным ещё долю секунды
// (антивирус лезет проверять, сука, или файловая система тупит), плюс
// возможна гонка с выходом launcher.exe. Поэтому ретраи, а не одна попытка.
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

async fn run_update_flow(app: AppHandle) {
    let dir = exe_dir();
    let local_version = read_local_version(&dir);
    emit_status(&app, "Проверяю обновления...");

    if let Some(info) = check_update(&local_version).await {
        if info.update_available && !info.url.is_empty() {
            let tmp_dir = std::env::temp_dir().join(format!("lota-update-{}", std::process::id()));
            let _ = std::fs::create_dir_all(&tmp_dir);

            match download_and_verify(&app, &info.url, &info.sha256, info.size, &tmp_dir).await {
                Ok(zip_path) => {
                    emit_status(&app, "Устанавливаю...");
                    let extract_dir = tmp_dir.join("extracted");
                    if extract_zip(&zip_path, &extract_dir).is_ok() {
                        let new_launcher = extract_dir.join(LAUNCHER_EXE);
                        if new_launcher.exists() {
                            let _ = replace_with_retry(&new_launcher, &dir.join(LAUNCHER_EXE));
                        }
                        let new_backend = extract_dir.join(BACKEND_EXE);
                        if new_backend.exists() {
                            let _ = replace_with_retry(&new_backend, &dir.join(BACKEND_EXE));
                        }
                        // updater сам себя обновить не может, пока живой,
                        // так что кладём как .new. Лаунчер подхватит и
                        // переименует при следующем запуске (см. main.rs).
                        let new_updater = extract_dir.join(UPDATER_EXE);
                        if new_updater.exists() {
                            let _ = replace_with_retry(
                                &new_updater,
                                &dir.join(format!("{UPDATER_EXE}.new")),
                            );
                        }
                        write_local_version(&dir, &info.version);
                        emit_status(&app, "Готово, запускаю...");
                    } else {
                        emit_status(&app, "Не удалось распаковать обновление, запускаю текущую версию...");
                    }
                }
                Err(e) => {
                    emit_status(&app, format!("Не удалось скачать обновление ({e}), запускаю текущую версию..."));
                }
            }

            let _ = std::fs::remove_dir_all(&tmp_dir);
        }
    }
    // Нет сети или нет обновлений — да и хер с ним, продолжаем запуск как есть
    // (fail-open: апдейтер вообще никогда не должен блокировать запуск лаунчера).

    let launcher_path = dir.join(LAUNCHER_EXE);
    let _ = Command::new(&launcher_path)
        .arg(SKIP_UPDATER_ARG)
        .current_dir(&dir)
        .spawn();

    std::thread::sleep(Duration::from_millis(300));
    app.exit(0);
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
