// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

// На Windows каждый запуск лаунчера сперва передаёт управление updater.exe
// (сам лаунчер не может подменить себя на диске, пока запущен — updater
// может, раз он не запущен из подменяемого файла). Если updater.exe не
// нашёлся/не запустился — не блокируем пользователя, работаем как обычно.
#[cfg(target_os = "windows")]
fn windows_updater_bootstrap() -> bool {
    use std::path::PathBuf;
    use std::process::Command;
    use std::time::Duration;

    if std::env::args().any(|a| a == "--skip-updater") {
        return false;
    }

    let dir: PathBuf = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));

    // Апдейтер не может заменить сам себя во время своей же работы — новую
    // версию он кладёт как updater.exe.new. Только лаунчер (в этот момент
    // updater точно не запущен) может её применить.
    let updater_new = dir.join("updater.exe.new");
    if updater_new.exists() {
        let updater_path = dir.join("updater.exe");
        for _ in 0..5 {
            if std::fs::rename(&updater_new, &updater_path).is_ok() {
                break;
            }
            std::thread::sleep(Duration::from_millis(300));
        }
    }

    Command::new(dir.join("updater.exe"))
        .current_dir(&dir)
        .spawn()
        .is_ok()
}

fn main() {
    #[cfg(target_os = "windows")]
    {
        if windows_updater_bootstrap() {
            return;
        }
    }

    lota_launcher_lib::run()
}
