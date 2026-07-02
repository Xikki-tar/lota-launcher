use std::process::Command;
use tauri::AppHandle;

#[tauri::command]
pub fn apply_update(app: AppHandle, path: String) -> Result<(), String> {
    Command::new(&path).spawn().map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}
