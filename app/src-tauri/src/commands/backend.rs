use std::sync::Mutex;
use std::time::Duration;
use tauri::AppHandle;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct BackendState {
    port: Option<u16>,
    child: Option<CommandChild>,
}

static BACKEND: Mutex<BackendState> = Mutex::new(BackendState {
    port: None,
    child: None,
});

#[tauri::command]
pub async fn backend_start(app: AppHandle) -> Result<u16, String> {
    if let Some(port) = BACKEND.lock().unwrap().port {
        return Ok(port);
    }

    let (mut rx, child) = app
        .shell()
        .sidecar("backend")
        .map_err(|e| e.to_string())?
        .spawn()
        .map_err(|e| format!("Failed to start backend: {}", e))?;

    let mut port: Option<u16> = None;
    while let Some(event) = rx.recv().await {
        if let CommandEvent::Stdout(line) = event {
            if let Some(rest) = String::from_utf8_lossy(&line).trim().strip_prefix("PORT:") {
                port = rest.parse().ok();
            }
            break;
        }
    }
    let port = port.ok_or("Bad port line")?;
    wait_for_backend_ready(port).await;

    let mut state = BACKEND.lock().unwrap();
    state.port = Some(port);
    state.child = Some(child);

    Ok(port)
}

async fn wait_for_backend_ready(port: u16) {
    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{}/settings", port);
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    loop {
        let ok = client
            .get(&url)
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
    let port = BACKEND.lock().unwrap().port;
    let Some(port) = port else { return false };
    let url = format!("http://127.0.0.1:{}/tasks/active_downloads", port);
    let resp = reqwest::Client::new()
        .get(&url)
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
