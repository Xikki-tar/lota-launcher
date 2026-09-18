use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

const APP_DIR_NAME: &str = "lota-launcher";
const CONFIG_FILE_NAME: &str = "config.cfg";

fn home_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        if let Ok(p) = std::env::var("USERPROFILE") {
            return PathBuf::from(p);
        }
        if let (Ok(d), Ok(p)) = (std::env::var("HOMEDRIVE"), std::env::var("HOMEPATH")) {
            return PathBuf::from(format!("{}{}", d, p));
        }
        return PathBuf::from("C:\\Users\\Default");
    }
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/tmp"))
}

fn default_config_dir() -> PathBuf {
    let home = home_dir();

    #[cfg(target_os = "windows")]
    let dir = {
        let base = std::env::var("LOCALAPPDATA")
            .unwrap_or_else(|_| home.join("AppData").join("Local").to_string_lossy().to_string());
        PathBuf::from(base).join(APP_DIR_NAME)
    };

    #[cfg(target_os = "macos")]
    let dir = home.join("Library").join("Application Support").join(APP_DIR_NAME);

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    let dir = home.join(".local").join("share").join(APP_DIR_NAME);

    dir
}

pub fn get_config_dir() -> PathBuf {
    if let Ok(v) = std::env::var("LOTA_LAUNCHER_HOME") {
        let v = v.trim().to_string();
        if !v.is_empty() {
            let p = PathBuf::from(v);
            let _ = fs::create_dir_all(&p);
            return p;
        }
    }

    let dir = default_config_dir();
    let _ = fs::create_dir_all(&dir);
    dir
}

#[cfg(target_os = "windows")]
fn install_root_data_dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let runtime_dir = exe.parent()?;
    if !runtime_dir.file_name()?.to_str()?.eq_ignore_ascii_case("runtime") {
        return None;
    }
    let install_root = runtime_dir.parent()?;
    if !install_root.file_name()?.to_str()?.eq_ignore_ascii_case(APP_DIR_NAME) {
        return None;
    }
    Some(install_root.to_path_buf())
}

const MIGRATION_MARKER: &str = ".migrated";
const MIGRATION_SKIP: [&str; 2] = ["runtime", "data"];

fn normalized(p: &Path) -> String {
    p.to_string_lossy().replace('/', "\\").trim_end_matches('\\').to_lowercase()
}

fn is_same_or_nested(a: &Path, b: &Path) -> bool {
    let (a, b) = (normalized(a), normalized(b));
    a == b || a.starts_with(&format!("{b}\\")) || b.starts_with(&format!("{a}\\"))
}

fn copy_dir_merge(src: &Path, dst: &Path, skip_top_level: &[&str]) {
    let Ok(entries) = fs::read_dir(src) else { return };
    for entry in entries.flatten() {
        let name = entry.file_name();
        if skip_top_level.iter().any(|s| name.to_string_lossy().eq_ignore_ascii_case(s)) {
            continue;
        }
        let path = entry.path();
        let target = dst.join(&name);
        if path.is_dir() {
            let _ = fs::create_dir_all(&target);
            copy_dir_merge(&path, &target, &[]);
        } else if !target.exists() {
            let _ = fs::copy(&path, &target);
        }
    }
}

fn migrate_legacy_data(legacy_dir: &Path, new_dir: &Path) {
    if !legacy_dir.is_dir() || is_same_or_nested(legacy_dir, new_dir) {
        return;
    }
    let marker = new_dir.join(MIGRATION_MARKER);
    if marker.exists() {
        return;
    }
    let _ = fs::create_dir_all(new_dir);
    copy_dir_merge(legacy_dir, new_dir, &MIGRATION_SKIP);
    let _ = fs::write(marker, "");
}

pub fn init_data_dir() {
    if let Ok(v) = std::env::var("LOTA_LAUNCHER_HOME") {
        if !v.trim().is_empty() {
            return;
        }
    }

    #[cfg(target_os = "windows")]
    {
        let Some(new_dir) = install_root_data_dir() else { return };
        let _ = fs::create_dir_all(&new_dir);
        migrate_legacy_data(&default_config_dir(), &new_dir);
        std::env::set_var("LOTA_LAUNCHER_HOME", &new_dir);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("lota-store-test-{}-{name}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn nested_dirs_are_never_migrated() {
        let legacy = scratch("nested").join("lota-launcher");
        fs::create_dir_all(legacy.join("runtime")).unwrap();
        fs::write(legacy.join("config.cfg"), "x").unwrap();
        let new_dir = legacy.join("data");

        migrate_legacy_data(&legacy, &new_dir);

        assert!(!new_dir.exists());
        assert!(legacy.join("config.cfg").exists());
    }

    #[test]
    fn disjoint_dirs_are_copied_without_deleting_or_cloning_runtime() {
        let base = scratch("disjoint");
        let legacy = base.join("old");
        let new_dir = base.join("new");
        fs::create_dir_all(legacy.join("runtime")).unwrap();
        fs::create_dir_all(legacy.join("library")).unwrap();
        fs::write(legacy.join("runtime").join("app.exe"), "x").unwrap();
        fs::write(legacy.join("library").join("a.txt"), "x").unwrap();
        fs::write(legacy.join("config.cfg"), "x").unwrap();

        migrate_legacy_data(&legacy, &new_dir);

        assert!(new_dir.join("config.cfg").exists());
        assert!(new_dir.join("library").join("a.txt").exists());
        assert!(!new_dir.join("runtime").exists());
        assert!(legacy.join("config.cfg").exists());

        fs::remove_file(new_dir.join("config.cfg")).unwrap();
        migrate_legacy_data(&legacy, &new_dir);
        assert!(!new_dir.join("config.cfg").exists());
    }
}

fn config_file() -> PathBuf {
    get_config_dir().join(CONFIG_FILE_NAME)
}

pub fn parse_ini(content: &str) -> HashMap<String, HashMap<String, String>> {
    let mut result: HashMap<String, HashMap<String, String>> = HashMap::new();
    let mut section: Option<String> = None;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with(';') {
            continue;
        }
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            let name = trimmed[1..trimmed.len() - 1].trim().to_lowercase();
            result.entry(name.clone()).or_default();
            section = Some(name);
        } else if let Some(ref sec) = section {
            if let Some(pos) = trimmed.find('=').or_else(|| trimmed.find(':')) {
                let k = trimmed[..pos].trim().to_lowercase();
                let v = trimmed[pos + 1..].trim().to_string();
                result.entry(sec.clone()).or_default().insert(k, v);
            }
        }
    }
    result
}

fn write_ini(path: &Path, sections: &HashMap<String, HashMap<String, String>>) {
    let mut ordered: Vec<(&String, &HashMap<String, String>)> = sections.iter().collect();
    ordered.sort_by_key(|(k, _)| k.as_str());
    let mut out = String::new();
    for (section, keys) in ordered {
        out.push_str(&format!("[{}]\n", section));
        let mut kv: Vec<(&String, &String)> = keys.iter().collect();
        kv.sort_by_key(|(k, _)| k.as_str());
        for (k, v) in kv {
            out.push_str(&format!("{} = {}\n", k, v));
        }
        out.push('\n');
    }
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(path, out);
}

fn load_ini() -> HashMap<String, HashMap<String, String>> {
    let path = config_file();
    if !path.exists() {
        return HashMap::new();
    }
    fs::read_to_string(&path)
        .map(|s| parse_ini(&s))
        .unwrap_or_default()
}

pub fn read_section(section: &str) -> HashMap<String, String> {
    load_ini()
        .remove(&section.to_lowercase())
        .unwrap_or_default()
}

pub fn update_section_keys(section: &str, data: &HashMap<String, String>) {
    let path = config_file();
    let mut ini = load_ini();
    let sec = ini.entry(section.to_lowercase()).or_default();
    for (k, v) in data {
        sec.insert(k.to_lowercase(), v.clone());
    }
    write_ini(&path, &ini);
}

pub fn remove_section(section: &str) {
    let path = config_file();
    let mut ini = load_ini();
    ini.remove(&section.to_lowercase());
    write_ini(&path, &ini);
}
