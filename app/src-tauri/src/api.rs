use std::sync::Mutex;
use std::time::{Duration, Instant};

use reqwest::Client;
use serde_json::Value;

use crate::store;

const DEFAULT_API_BASES: &[&str] = &["https://ru.lota.work", "https://eu.lota.work"];
const PROBE_TIMEOUT_SECS: u64 = 3;
const CACHE_TTL_SECS: u64 = 300;

struct ApiCache {
    value: String,
    until: Option<Instant>,
}

static CACHE: Mutex<ApiCache> = Mutex::new(ApiCache {
    value: String::new(),
    until: None,
});

fn candidates() -> Vec<String> {
    let settings = store::read_section("client");
    let mut list: Vec<String> = Vec::new();

    for key in &["api_base_urls", "api_base_url"] {
        if let Some(v) = settings.get(*key) {
            for part in v.replace(';', ",").split(',') {
                let s = part.trim().trim_end_matches('/').to_string();
                if !s.is_empty() {
                    list.push(s);
                }
            }
        }
    }

    for key in &["LOTA_API_BASES", "LOTA_API_BASE"] {
        if let Ok(v) = std::env::var(key) {
            for part in v.replace(';', ",").split(',') {
                let s = part.trim().trim_end_matches('/').to_string();
                if !s.is_empty() {
                    list.push(s);
                }
            }
        }
    }

    for base in DEFAULT_API_BASES {
        list.push(base.to_string());
    }

    let mut seen = std::collections::HashSet::new();
    list.retain(|s| seen.insert(s.to_lowercase()));
    list
}

async fn probe(client: &Client, base: &str) -> Option<Duration> {
    let url = format!("{}/ping", base);
    let start = Instant::now();
    let ok = client
        .get(&url)
        .timeout(Duration::from_secs(PROBE_TIMEOUT_SECS))
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false);
    if ok { Some(start.elapsed()) } else { None }
}

pub async fn resolve() -> Result<String, String> {
    {
        let cache = CACHE.lock().unwrap();
        if !cache.value.is_empty() {
            if let Some(until) = cache.until {
                if Instant::now() < until {
                    return Ok(cache.value.clone());
                }
            }
        }
    }

    let list = candidates();
    if list.is_empty() {
        return Err("no_api_candidates".into());
    }

    let client = Client::new();
    let mut best: Option<(String, Duration)> = None;

    let futs: Vec<_> = list
        .iter()
        .map(|base| {
            let client = client.clone();
            let base = base.clone();
            async move {
                let d = probe(&client, &base).await;
                (base, d)
            }
        })
        .collect();

    let results = futures::future::join_all(futs).await;
    for (base, d) in results {
        if let Some(latency) = d {
            if best.as_ref().map_or(true, |(_, b)| latency < *b) {
                best = Some((base, latency));
            }
        }
    }

    let winner = best.map(|(b, _)| b).unwrap_or_else(|| list[0].clone());

    {
        let mut cache = CACHE.lock().unwrap();
        cache.value = winner.clone();
        cache.until = Some(Instant::now() + Duration::from_secs(CACHE_TTL_SECS));
    }

    Ok(winner)
}

pub async fn post(path: &str, body: Value) -> Result<(u16, Value), String> {
    let base = resolve().await?;
    let url = format!("{}{}", base, path);
    let client = Client::new();
    let resp = client
        .post(&url)
        .json(&body)
        .timeout(Duration::from_secs(15))
        .send()
        .await
        .map_err(|_| "conn_refused".to_string())?;
    let status = resp.status().as_u16();
    let data: Value = resp.json().await.unwrap_or(Value::Null);
    Ok((status, data))
}

pub async fn get(path: &str, params: &[(&str, &str)]) -> Result<(u16, Value), String> {
    let base = resolve().await?;
    let client = Client::new();
    let resp = client
        .get(format!("{}{}", base, path))
        .query(params)
        .timeout(Duration::from_secs(10))
        .send()
        .await
        .map_err(|_| "conn_refused".to_string())?;
    let status = resp.status().as_u16();
    let data: Value = resp.json().await.unwrap_or(Value::Null);
    Ok((status, data))
}
