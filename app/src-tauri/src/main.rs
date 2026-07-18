#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

// на Windows каждый запуск лаунчера сперва отдаёт управление updater.exe
// сам себя лаунчер подменить не может пока живой а апдейтер может раз он
// не запущен из того файла, который меняем если updater.exe не нашёлся или
// обосрался при запуске похуй не блокируем юзера работаем как обычно
#[cfg(target_os = "windows")]
fn windows_cleanup_stray_appdata_dirs() {
    use std::path::PathBuf;

    let Ok(local_appdata) = std::env::var("LOCALAPPDATA") else {
        return;
    };
    for name in ["com.lota.launcher", "com.lota.launcher.updater"] {
        let _ = std::fs::remove_dir_all(PathBuf::from(&local_appdata).join(name));
    }
}

#[cfg(target_os = "windows")]
fn windows_updater_bootstrap() -> bool {
    use std::path::PathBuf;
    use std::process::Command;
    use std::time::Duration;

    windows_cleanup_stray_appdata_dirs();

    if std::env::args().any(|a| a == "--skip-updater") {
        return false;
    }

    let dir: PathBuf = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));

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

    let mut child = match Command::new(dir.join("updater.exe")).current_dir(&dir).spawn() {
        Ok(c) => c,
        Err(_) => return false,
    };
    
    std::thread::sleep(Duration::from_millis(400));
    !matches!(child.try_wait(), Ok(Some(status)) if !status.success())
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
