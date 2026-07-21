use std::time::Duration;
use tauri::{AppHandle, Manager};

#[tauri::command]
pub async fn close_window(app: AppHandle) {
    if crate::commands::backend::has_active_downloads().await {
        if let Some(win) = app.get_webview_window("lota-launcher") {
            let _ = win.hide();
        }
        tauri::async_runtime::spawn(wait_for_downloads_then_exit(app));
        return;
    }
    crate::commands::backend::kill_backend();
    app.exit(0);
}

async fn wait_for_downloads_then_exit(app: AppHandle) {
    while crate::commands::backend::has_active_downloads().await {
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
    crate::commands::backend::kill_backend();
    app.exit(0);
}

#[tauri::command]
pub fn minimize_window(app: AppHandle) {
    if let Some(win) = app.get_webview_window("lota-launcher") {
        let _ = win.minimize();
    }
}

#[tauri::command]
pub fn toggle_maximize(app: AppHandle) {
    if let Some(win) = app.get_webview_window("lota-launcher") {
        let maximized = win.is_maximized().unwrap_or(false);
        if maximized {
            let _ = win.unmaximize();
        } else {
            let _ = win.maximize();
        }
    }
}

#[tauri::command]
pub fn hide_window(app: AppHandle) {
    if let Some(win) = app.get_webview_window("lota-launcher") {
        let _ = win.hide();
    }
}

#[tauri::command]
pub fn show_window(app: AppHandle) {
    if let Some(win) = app.get_webview_window("lota-launcher") {
        let _ = win.show();
        let _ = win.set_focus();
    }
}
