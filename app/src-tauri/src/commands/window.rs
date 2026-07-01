use tauri::{AppHandle, Manager};

#[tauri::command]
pub fn close_window(app: AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.close();
    }
}

#[tauri::command]
pub fn minimize_window(app: AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.minimize();
    }
}

#[tauri::command]
pub fn toggle_maximize(app: AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let maximized = win.is_maximized().unwrap_or(false);
        if maximized {
            let _ = win.unmaximize();
        } else {
            let _ = win.maximize();
        }
    }
}
