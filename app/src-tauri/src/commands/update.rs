use std::process::Command;
use std::time::Duration;
use tauri::AppHandle;

#[cfg(target_os = "windows")]
fn windows_launcher_version_file() -> Option<String> {
    let dir = std::env::current_exe().ok()?.parent()?.to_path_buf();
    let v = std::fs::read_to_string(dir.join("launcher.version")).ok()?;
    let v = v.trim().to_string();
    if v.is_empty() { None } else { Some(v) }
}

#[tauri::command]
pub fn get_display_version(app: AppHandle) -> String {
    #[cfg(target_os = "windows")]
    {
        if let Some(v) = windows_launcher_version_file() {
            return v;
        }
    }
    app.package_info().version.to_string()
}

#[tauri::command]
pub fn apply_update(app: AppHandle, path: String) -> Result<(), String> {
    Command::new(&path).spawn().map_err(|e| e.to_string())?;
    crate::commands::backend::kill_backend();
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

    crate::commands::backend::kill_backend();
    app.exit(0);
    Ok(())
}
