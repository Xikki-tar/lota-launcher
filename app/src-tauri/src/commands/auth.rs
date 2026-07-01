use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::{api, store};

// ── Stored data ───────────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct AuthData {
    pub token: String,
    pub username: String,
    pub status: String,
    pub sub_level: i64,
    pub player_uuid: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RegisterLink {
    pub link_token: String,
    pub telegram_url: String,
}

// ── Config commands ───────────────────────────────────────────────────────────

#[tauri::command]
pub fn auth_load() -> Option<AuthData> {
    let s = store::read_section("auth");
    let token = s.get("token")?.to_string();
    if token.is_empty() {
        return None;
    }
    Some(AuthData {
        token,
        username: s.get("username").cloned().unwrap_or_default(),
        status: s.get("status").cloned().unwrap_or_else(|| "active".into()),
        sub_level: s.get("sub_level").and_then(|v| v.parse().ok()).unwrap_or(0),
        player_uuid: s.get("player_uuid").cloned().unwrap_or_default(),
    })
}

#[tauri::command]
pub fn auth_save(
    token: String,
    username: String,
    status: String,
    sub_level: i64,
    player_uuid: String,
) {
    let mut data = HashMap::new();
    data.insert("token".into(), token);
    data.insert("username".into(), username);
    data.insert("status".into(), status);
    data.insert("sub_level".into(), sub_level.to_string());
    data.insert("player_uuid".into(), player_uuid);
    store::update_section_keys("auth", &data);
}

#[tauri::command]
pub fn auth_clear() {
    store::remove_section("auth");
}

#[tauri::command]
pub fn register_link_load() -> Option<RegisterLink> {
    let s = store::read_section("register");
    let link_token = s.get("link_token")?.to_string();
    let telegram_url = s.get("telegram_url")?.to_string();
    if link_token.is_empty() || telegram_url.is_empty() {
        return None;
    }
    Some(RegisterLink { link_token, telegram_url })
}

#[tauri::command]
pub fn register_link_save(link_token: String, telegram_url: String) {
    let mut data = HashMap::new();
    data.insert("link_token".into(), link_token);
    data.insert("telegram_url".into(), telegram_url);
    store::update_section_keys("register", &data);
}

#[tauri::command]
pub fn register_link_clear() {
    store::remove_section("register");
}

// ── API response type ─────────────────────────────────────────────────────────

#[derive(Serialize)]
pub struct ApiResult {
    pub ok: bool,
    pub status: u16,
    pub data: Value,
}

// ── API commands ──────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn api_login(username: String, code: String) -> Result<ApiResult, String> {
    let (status, data) = api::post(
        "/api/login",
        json!({ "username": username, "code": code }),
    )
    .await?;
    let ok = status == 200 && data.get("ok").and_then(Value::as_bool).unwrap_or(false);
    Ok(ApiResult { ok, status, data })
}

#[tauri::command]
pub async fn api_register_telegram_link() -> Result<ApiResult, String> {
    let (status, data) = api::post("/api/register/telegram-link", json!({})).await?;
    let ok = status == 200 && data.get("ok").and_then(Value::as_bool).unwrap_or(false);
    Ok(ApiResult { ok, status, data })
}

#[tauri::command]
pub async fn api_register_poll(link_token: String) -> Result<ApiResult, String> {
    let lt = link_token.clone();
    let (status, data) = api::get(
        "/api/register/telegram-status",
        &[("link_token", &lt)],
    )
    .await?;
    let ok = status == 200 && data.get("ok").and_then(Value::as_bool).unwrap_or(false);
    Ok(ApiResult { ok, status, data })
}

#[tauri::command]
pub async fn api_register_complete(link_token: String, username: String) -> Result<ApiResult, String> {
    let (status, data) = api::post(
        "/api/register/complete",
        json!({ "link_token": link_token, "username": username }),
    )
    .await?;
    let ok = status == 200 && data.get("ok").and_then(Value::as_bool).unwrap_or(false);
    Ok(ApiResult { ok, status, data })
}
