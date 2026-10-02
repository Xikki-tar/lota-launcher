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

#[cfg(all(target_os = "windows", not(debug_assertions)))]
fn exe_root_dir() -> Option<PathBuf> {
    let dir = std::env::current_exe().ok()?.parent()?.to_path_buf();
    let probe = dir.join(".write_probe");
    fs::write(&probe, b"").ok()?;
    let _ = fs::remove_file(&probe);
    Some(dir)
}

#[cfg(any(all(target_os = "windows", not(debug_assertions)), test))]
const MIGRATION_MARKER: &str = ".migrated";
#[cfg(any(all(target_os = "windows", not(debug_assertions)), test))]
const MIGRATION_SKIP: [&str; 4] = ["runtime", "data", "lota-launcher", MIGRATION_MARKER];

#[cfg(any(all(target_os = "windows", not(debug_assertions)), test))]
fn normalized(p: &Path) -> String {
    p.to_string_lossy().replace('/', "\\").trim_end_matches('\\').to_lowercase()
}

#[cfg(any(all(target_os = "windows", not(debug_assertions)), test))]
fn is_same_or_inside(inner: &Path, outer: &Path) -> bool {
    let (inner, outer) = (normalized(inner), normalized(outer));
    inner == outer || inner.starts_with(&format!("{outer}\\"))
}

#[cfg(any(all(target_os = "windows", not(debug_assertions)), test))]
fn move_legacy_entries(legacy: &Path, root: &Path) {
    if !legacy.is_dir() || is_same_or_inside(legacy, root) {
        return;
    }
    let Ok(entries) = fs::read_dir(legacy) else { return };
    for entry in entries.flatten() {
        let name = entry.file_name();
        if MIGRATION_SKIP.iter().any(|s| name.to_string_lossy().eq_ignore_ascii_case(s)) {
            continue;
        }
        let path = entry.path();
        let target = root.join(&name);
        if target.exists() || is_same_or_inside(root, &path) {
            continue;
        }
        let _ = fs::rename(&path, &target);
    }
}

#[cfg(any(all(target_os = "windows", not(debug_assertions)), test))]
fn migrate_legacy_data(legacy: &Path, root: &Path) {
    let marker = root.join(MIGRATION_MARKER);
    if marker.exists() {
        return;
    }
    move_legacy_entries(&legacy.join("data"), root);
    move_legacy_entries(legacy, root);
    let _ = fs::write(marker, "");
}

pub fn init_data_dir() {
    if let Ok(v) = std::env::var("LOTA_LAUNCHER_HOME") {
        if !v.trim().is_empty() {
            return;
        }
    }

    #[cfg(all(target_os = "windows", not(debug_assertions)))]
    {
        let Some(root) = exe_root_dir() else { return };
        migrate_legacy_data(&default_config_dir(), &root);
        std::env::set_var("LOTA_LAUNCHER_HOME", &root);
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
    fn moves_data_into_separate_install_dir_once() {
        let base = scratch("separate");
        let legacy = base.join("lota-launcher");
        let root = base.join("Lota Launcher");
        fs::create_dir_all(legacy.join("library")).unwrap();
        fs::create_dir_all(legacy.join("runtime")).unwrap();
        fs::create_dir_all(&root).unwrap();
        fs::write(legacy.join("config.cfg"), "x").unwrap();
        fs::write(legacy.join("library").join("a.txt"), "x").unwrap();
        fs::write(root.join("lota-launcher.exe"), "bin").unwrap();

        migrate_legacy_data(&legacy, &root);

        assert!(root.join("config.cfg").exists());
        assert!(root.join("library").join("a.txt").exists());
        assert!(!root.join("runtime").exists());
        assert!(legacy.join("runtime").exists());
        assert_eq!(fs::read_to_string(root.join("lota-launcher.exe")).unwrap(), "bin");

        fs::write(legacy.join("late.cfg"), "x").unwrap();
        migrate_legacy_data(&legacy, &root);
        assert!(!root.join("late.cfg").exists());
    }

    #[test]
    fn install_inside_legacy_dir_does_not_recurse() {
        let legacy = scratch("nested").join("lota-launcher");
        let root = legacy.join("runtime");
        fs::create_dir_all(&root).unwrap();
        fs::write(legacy.join("config.cfg"), "x").unwrap();

        migrate_legacy_data(&legacy, &root);

        assert!(root.join("config.cfg").exists());
        assert!(!root.join("runtime").exists());
        assert!(legacy.join("runtime").exists());
    }

    #[test]
    fn prefers_data_from_old_data_subdir_and_skips_junk() {
        let legacy = scratch("olddata").join("lota-launcher");
        let root = legacy.join("runtime");
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(legacy.join("data").join("runtime").join("lota-launcher")).unwrap();
        fs::write(legacy.join("data").join("config.cfg"), "from-data").unwrap();
        fs::write(legacy.join("config.cfg"), "from-root").unwrap();

        migrate_legacy_data(&legacy, &root);

        assert_eq!(fs::read_to_string(root.join("config.cfg")).unwrap(), "from-data");
        assert!(!root.join("runtime").exists());
        assert!(!root.join("lota-launcher").exists());
    }

    #[test]
    fn same_dir_is_untouched() {
        let legacy = scratch("same").join("lota-launcher");
        fs::create_dir_all(&legacy).unwrap();
        fs::write(legacy.join("config.cfg"), "x").unwrap();

        migrate_legacy_data(&legacy, &legacy);

        assert!(legacy.join("config.cfg").exists());
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
