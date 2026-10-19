mod api;
mod commands;
mod store;

use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

const MAIN_WINDOW: &str = "lota-launcher";
#[cfg(target_os = "macos")]
const QUIT_MENU_ID: &str = "lota-quit";

fn request_close(app: &AppHandle) {
    tauri::async_runtime::spawn(commands::window::close_window(app.clone()));
}

#[cfg(target_os = "macos")]
fn macos_menu(app: &AppHandle) -> tauri::Result<tauri::menu::Menu<tauri::Wry>> {
    use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};

    let name = app.package_info().name.clone();
    let quit = MenuItem::with_id(app, QUIT_MENU_ID, format!("Quit {name}"), true, Some("CmdOrCtrl+Q"))?;
    let app_menu = Submenu::with_items(
        app,
        &name,
        true,
        &[
            &PredefinedMenuItem::about(app, None, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::hide(app, None)?,
            &PredefinedMenuItem::hide_others(app, None)?,
            &PredefinedMenuItem::show_all(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;
    let edit_menu = Submenu::with_items(
        app,
        "Edit",
        true,
        &[
            &PredefinedMenuItem::undo(app, None)?,
            &PredefinedMenuItem::redo(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::cut(app, None)?,
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
        ],
    )?;
    let window_menu = Submenu::with_items(
        app,
        "Window",
        true,
        &[
            &PredefinedMenuItem::minimize(app, None)?,
            &PredefinedMenuItem::maximize(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::close_window(app, None)?,
        ],
    )?;
    Menu::with_items(app, &[&app_menu, &edit_menu, &window_menu])
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    store::init_data_dir();

    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init());

    #[cfg(target_os = "macos")]
    let builder = builder.menu(macos_menu).on_menu_event(|app, event| {
        if event.id() == QUIT_MENU_ID {
            request_close(app);
        }
    });

    builder
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == MAIN_WINDOW {
                    api.prevent_close();
                    request_close(window.app_handle());
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::window::close_window,
            commands::window::minimize_window,
            commands::window::toggle_maximize,
            commands::window::show_window,
            commands::window::hide_until_game_exit,
            commands::auth::auth_load,
            commands::auth::auth_save,
            commands::auth::auth_clear,
            commands::auth::register_link_load,
            commands::auth::register_link_save,
            commands::auth::register_link_clear,
            commands::auth::api_login,
            commands::auth::api_register_telegram_link,
            commands::auth::api_register_poll,
            commands::auth::api_register_complete,
            commands::backend::backend_start,
            commands::backend::backend_port,
            commands::backend::backend_key,
            commands::update::apply_update,
            commands::update::restart_to_updater,
            commands::update::get_display_version,
        ])
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| match event {
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => commands::window::show_window(app.clone()),
            RunEvent::ExitRequested { api, code: None, .. } => {
                api.prevent_exit();
                request_close(app);
            }
            _ => {}
        });
}
