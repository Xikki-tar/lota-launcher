use std::process::Command;
use tauri::AppHandle;

#[tauri::command]
pub fn apply_update(app: AppHandle, path: String) -> Result<(), String> {
    Command::new(&path).spawn().map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}

// Windows-only: перезапуск через updater.exe (тот же путь, что лаунчер сам
// проходит при каждом запуске — см. app/src-tauri/src/main.rs). Вызывается
// кнопкой "Проверить обновления" из уже запущенного приложения.
#[tauri::command]
pub fn restart_to_updater(app: AppHandle) -> Result<(), String> {
    let dir = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("no parent dir")?
        .to_path_buf();

    Command::new(dir.join("updater.exe"))
        .current_dir(&dir)
        .spawn()
        .map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}
