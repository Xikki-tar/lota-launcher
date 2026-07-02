use std::sync::Mutex;
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

    let mut state = BACKEND.lock().unwrap();
    state.port = Some(port);
    state.child = Some(child);

    Ok(port)
}

#[tauri::command]
pub fn backend_port() -> Option<u16> {
    BACKEND.lock().unwrap().port
}
