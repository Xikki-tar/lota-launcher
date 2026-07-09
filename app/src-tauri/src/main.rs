// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

// на Windows каждый запуск лаунчера сперва отдаёт управление updater.exe
// сам себя лаунчер подменить не может пока живой а апдейтер может раз он
// не запущен из того файла, который меняем если updater.exe не нашёлся или
// обосрался при запуске похуй не блокируем юзера работаем как обычно
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

    // Апдейтер сам себя обновить не может, пока работает, поэтому новую
    // версию кладёт рядом как updater.exe.new. Только лаунчер (апдейтер в
    // этот момент точно дохлый) может её накатить.
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

    // spawn() говорит Ok, даже если процесс тут же сдох нахрен (не хватило
    // какой-нибудь системной dll, например) — Windows успевает создать
    // процесс раньше, чем он реально начинает исполняться. Даём ему долю
    // секунды и проверяем, что он ещё дышит, прежде чем отдавать управление.
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
