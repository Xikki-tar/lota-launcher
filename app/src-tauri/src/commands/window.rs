use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tauri::{AppHandle, Manager};

static WATCHING_GAME: AtomicBool = AtomicBool::new(false);

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
pub fn show_window(app: AppHandle) {
    show_main_window(&app);
}

fn show_main_window(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("lota-launcher") {
        webview_power::wake(&win);
        let _ = win.show();
        let _ = win.set_focus();
    }
}

#[tauri::command]
pub fn hide_until_game_exit(app: AppHandle) {
    let Some(win) = app.get_webview_window("lota-launcher") else { return };
    let _ = win.hide();
    webview_power::sleep(&win);
    if !WATCHING_GAME.swap(true, Ordering::SeqCst) {
        tauri::async_runtime::spawn(watch_game_then_show(app));
    }
}

async fn watch_game_then_show(app: AppHandle) {
    let client = reqwest::Client::new();
    let mut failures = 0;
    loop {
        tokio::time::sleep(Duration::from_secs(2)).await;
        let Some(port) = crate::commands::backend::backend_port() else { break };
        let state = match client
            .get(format!("http://127.0.0.1:{port}/play/state"))
            .header("X-Lota-Key", crate::commands::backend::backend_key())
            .timeout(Duration::from_secs(3))
            .send()
            .await
        {
            Ok(resp) => resp
                .json::<serde_json::Value>()
                .await
                .ok()
                .and_then(|v| v.get("state").and_then(|s| s.as_str()).map(str::to_owned)),
            Err(_) => None,
        };
        match state.as_deref() {
            Some("launched") => failures = 0,
            Some(_) => break,
            None => {
                failures += 1;
                if failures >= 5 {
                    break;
                }
            }
        }
    }
    WATCHING_GAME.store(false, Ordering::SeqCst);
    show_main_window(&app);
}

#[cfg(windows)]
mod webview_power {
    use tauri::WebviewWindow;
    use webview2_com::Microsoft::Web::WebView2::Win32::{
        ICoreWebView2_19, ICoreWebView2_3, COREWEBVIEW2_MEMORY_USAGE_TARGET_LEVEL_LOW,
        COREWEBVIEW2_MEMORY_USAGE_TARGET_LEVEL_NORMAL,
    };
    use webview2_com::TrySuspendCompletedHandler;
    use windows_core::Interface;

    pub fn sleep(win: &WebviewWindow) {
        let _ = win.with_webview(|webview| unsafe {
            let controller = webview.controller();
            let _ = controller.SetIsVisible(false);
            let Ok(core) = controller.CoreWebView2() else { return };
            if let Ok(core19) = core.cast::<ICoreWebView2_19>() {
                let _ = core19.SetMemoryUsageTargetLevel(COREWEBVIEW2_MEMORY_USAGE_TARGET_LEVEL_LOW);
            }
            if let Ok(core3) = core.cast::<ICoreWebView2_3>() {
                let handler = TrySuspendCompletedHandler::create(Box::new(|_, _| Ok(())));
                let _ = core3.TrySuspend(&handler);
            }
        });
    }

    pub fn wake(win: &WebviewWindow) {
        let _ = win.with_webview(|webview| unsafe {
            let controller = webview.controller();
            if let Ok(core) = controller.CoreWebView2() {
                if let Ok(core3) = core.cast::<ICoreWebView2_3>() {
                    let _ = core3.Resume();
                }
                if let Ok(core19) = core.cast::<ICoreWebView2_19>() {
                    let _ = core19.SetMemoryUsageTargetLevel(COREWEBVIEW2_MEMORY_USAGE_TARGET_LEVEL_NORMAL);
                }
            }
            let _ = controller.SetIsVisible(true);
        });
    }
}

#[cfg(not(windows))]
mod webview_power {
    use tauri::WebviewWindow;

    pub fn sleep(_win: &WebviewWindow) {}

    pub fn wake(_win: &WebviewWindow) {}
}
