use std::sync::Mutex;
use std::time::Duration;
use tauri::AppHandle;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct BackendState {
    port: Option<u16>,
    child: Option<CommandChild>,
    key: String,
}

static BACKEND: Mutex<BackendState> = Mutex::new(BackendState {
    port: None,
    child: None,
    key: String::new(),
});

fn ensure_key() -> String {
    let mut state = BACKEND.lock().unwrap();
    if state.key.is_empty() {
        let mut bytes = [0u8; 32];
        getrandom::getrandom(&mut bytes).expect("no system randomness");
        state.key = bytes.iter().map(|b| format!("{b:02x}")).collect();
    }
    state.key.clone()
}

#[tauri::command]
pub fn backend_key() -> String {
    ensure_key()
}

#[tauri::command]
pub async fn backend_start(app: AppHandle) -> Result<u16, String> {
    if let Some(port) = BACKEND.lock().unwrap().port {
        return Ok(port);
    }

    let data_dir = crate::store::get_config_dir();
    let key = ensure_key();
    let (mut rx, child) = app
        .shell()
        .sidecar("backend")
        .map_err(|e| e.to_string())?
        .env("LOTA_LAUNCHER_HOME", data_dir.to_string_lossy().to_string())
        .env("LOTA_BACKEND_KEY", &key)
        .env("LOTA_EXIT_ON_STDIN_CLOSE", "1")
        .spawn()
        .map_err(|e| format!("Failed to start backend: {}", e))?;

    let mut port: Option<u16> = None;
    let mut output: Vec<String> = Vec::new();
    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                let text = String::from_utf8_lossy(&line).trim().to_string();
                if let Some(rest) = text.strip_prefix("PORT:") {
                    port = rest.parse().ok();
                    if port.is_none() {
                        remember(&mut output, text);
                    }
                    break;
                }
                remember(&mut output, text);
            }
            CommandEvent::Stderr(line) => remember(&mut output, String::from_utf8_lossy(&line).trim().to_string()),
            CommandEvent::Error(err) => remember(&mut output, err),
            CommandEvent::Terminated(payload) => {
                remember(
                    &mut output,
                    format!("backend exited: code {:?}, signal {:?}", payload.code, payload.signal),
                );
                break;
            }
            _ => {}
        }
    }
    let Some(port) = port else {
        let _ = child.kill();
        return Err(startup_error("Backend did not report its port", &output));
    };
    wait_for_backend_ready(port, &key).await;

    let mut state = BACKEND.lock().unwrap();
    state.port = Some(port);
    state.child = Some(child);

    Ok(port)
}

const STARTUP_OUTPUT_LINES: usize = 30;

fn remember(output: &mut Vec<String>, line: String) {
    if line.is_empty() {
        return;
    }
    if output.len() == STARTUP_OUTPUT_LINES {
        output.remove(0);
    }
    output.push(line);
}

fn startup_error(message: &str, output: &[String]) -> String {
    if output.is_empty() {
        message.to_string()
    } else {
        format!("{message}\n\n{}", output.join("\n"))
    }
}

async fn wait_for_backend_ready(port: u16, key: &str) {
    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{}/settings", port);
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    loop {
        let ok = client
            .get(&url)
            .header("X-Lota-Key", key)
            .timeout(Duration::from_secs(1))
            .send()
            .await
            .is_ok();
        if ok || std::time::Instant::now() >= deadline {
            return;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

#[tauri::command]
pub fn backend_port() -> Option<u16> {
    BACKEND.lock().unwrap().port
}

pub fn kill_backend() {
    let mut state = BACKEND.lock().unwrap();
    if let Some(child) = state.child.take() {
        let _ = child.kill();
    }
    state.port = None;
}

pub async fn has_active_downloads() -> bool {
    let (port, key) = {
        let state = BACKEND.lock().unwrap();
        (state.port, state.key.clone())
    };
    let Some(port) = port else { return false };
    let url = format!("http://127.0.0.1:{}/tasks/active_downloads", port);
    let resp = reqwest::Client::new()
        .get(&url)
        .header("X-Lota-Key", key)
        .timeout(Duration::from_secs(3))
        .send()
        .await;
    match resp {
        Ok(r) => r
            .json::<serde_json::Value>()
            .await
            .ok()
            .and_then(|v| v.get("active").and_then(|a| a.as_bool()))
            .unwrap_or(false),
        Err(_) => false,
    }
}
