#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

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

    if option_env!("LOTA_BUILD_DISABLE_UPDATES").is_some() {
        return false;
    }

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

#[cfg(target_os = "linux")]
fn linux_disable_webkit_dmabuf() {
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
}

fn main() {
    #[cfg(target_os = "linux")]
    linux_disable_webkit_dmabuf();

    #[cfg(target_os = "windows")]
    {
        if windows_updater_bootstrap() {
            return;
        }
    }

    lota_launcher_lib::run()
}
