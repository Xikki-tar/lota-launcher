use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

struct BackendState {
    port: Option<u16>,
    child: Option<Child>,
}

static BACKEND: Mutex<BackendState> = Mutex::new(BackendState {
    port: None,
    child: None,
});

#[tauri::command]
pub fn backend_start(backend_path: String) -> Result<u16, String> {
    let mut state = BACKEND.lock().unwrap();

    if let Some(port) = state.port {
        return Ok(port);
    }

    let mut child = Command::new(&backend_path)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to start backend: {}", e))?;

    let stdout = child.stdout.take().ok_or("No stdout")?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|e| e.to_string())?;

    let port_str = line.trim().strip_prefix("PORT:").ok_or("Bad port line")?;
    let port: u16 = port_str.parse().map_err(|_| "Invalid port")?;

    state.port = Some(port);
    state.child = Some(child);

    Ok(port)
}

#[tauri::command]
pub fn backend_port() -> Option<u16> {
    BACKEND.lock().unwrap().port
}
