use std::process::Command;
use std::time::Duration;
use tauri::AppHandle;

#[tauri::command]
pub fn apply_update(app: AppHandle, path: String) -> Result<(), String> {
    Command::new(&path).spawn().map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}

#[tauri::command]
pub fn restart_to_updater(app: AppHandle) -> Result<(), String> {
    let dir = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("no parent dir")?
        .to_path_buf();

    let mut child = Command::new(dir.join("updater.exe"))
        .current_dir(&dir)
        .spawn()
        .map_err(|e| e.to_string())?;

    std::thread::sleep(Duration::from_millis(400));
    if let Ok(Some(status)) = child.try_wait() {
        if !status.success() {
            return Err("updater exited immediately".to_string());
        }
    }

    app.exit(0);
    Ok(())
}
