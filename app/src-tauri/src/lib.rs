mod api;
mod commands;
mod store;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            commands::window::close_window,
            commands::window::minimize_window,
            commands::window::toggle_maximize,
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
