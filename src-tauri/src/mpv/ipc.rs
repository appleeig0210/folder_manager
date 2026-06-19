use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

const IPC_READ_TIMEOUT_MS: u64 = 400;

pub struct MpvIpc {
    pipe_path: String,
}

impl MpvIpc {
    pub fn from_path(pipe_path: impl Into<String>) -> Self {
        Self {
            pipe_path: pipe_path.into(),
        }
    }

    pub fn pipe_path(&self) -> &str {
        &self.pipe_path
    }

    pub fn connect(pipe_name: &str, timeout_ms: u64) -> Result<Self, String> {
        let pipe_path = pipe_name.to_string();
        let deadline = Instant::now() + Duration::from_millis(timeout_ms);
        loop {
            if Self::probe(&pipe_path).is_ok() {
                return Ok(Self { pipe_path });
            }
            if Instant::now() >= deadline {
                return Err("連線 mpv IPC 逾時".to_string());
            }
            thread::sleep(Duration::from_millis(50));
        }
    }

    fn probe(pipe_path: &str) -> Result<(), String> {
        let mut file = open_pipe(pipe_path)?;
        writeln!(file, r#"{{"command":["get_property","mpv-version"]}}"#)
            .map_err(|error| format!("寫入 mpv IPC 失敗：{error}"))?;
        file.flush()
            .map_err(|error| format!("刷新 mpv IPC 失敗：{error}"))?;
        Ok(())
    }

    pub fn seek(&self, seconds: f64) -> Result<(), String> {
        self.send_command(&serde_json::json!({
            "command": ["seek", seconds, "absolute"]
        }))
    }

    pub fn set_paused(&self, paused: bool) -> Result<(), String> {
        self.send_command(&serde_json::json!({
            "command": ["set_property", "pause", paused]
        }))
    }

    pub fn get_time_pos(&self) -> Result<f64, String> {
        self.request_number(&serde_json::json!({
            "command": ["get_property", "time-pos"]
        }))
    }

    pub fn get_duration(&self) -> Result<f64, String> {
        self.request_number(&serde_json::json!({
            "command": ["get_property", "duration"]
        }))
    }

    pub fn quit(&self) -> Result<(), String> {
        self.send_command(&serde_json::json!({
            "command": ["quit"]
        }))
    }

    fn send_command(&self, payload: &serde_json::Value) -> Result<(), String> {
        let mut file = open_pipe(&self.pipe_path)?;
        writeln!(file, "{payload}")
            .map_err(|error| format!("寫入 mpv IPC 失敗：{error}"))?;
        file.flush()
            .map_err(|error| format!("刷新 mpv IPC 失敗：{error}"))?;
        Ok(())
    }

    fn request_number(&self, payload: &serde_json::Value) -> Result<f64, String> {
        let pipe_path = self.pipe_path.clone();
        let payload = payload.clone();
        let (tx, rx) = mpsc::sync_channel(1);
        thread::spawn(move || {
            let result = Self::request_number_blocking(&pipe_path, &payload);
            let _ = tx.send(result);
        });

        match rx.recv_timeout(Duration::from_millis(IPC_READ_TIMEOUT_MS)) {
            Ok(result) => result,
            Err(_) => Err("mpv IPC 讀取逾時".to_string()),
        }
    }

    fn request_number_blocking(
        pipe_path: &str,
        payload: &serde_json::Value,
    ) -> Result<f64, String> {
        let mut file = open_pipe(pipe_path)?;
        writeln!(file, "{payload}")
            .map_err(|error| format!("寫入 mpv IPC 失敗：{error}"))?;
        file.flush()
            .map_err(|error| format!("刷新 mpv IPC 失敗：{error}"))?;

        let reader = BufReader::new(file);
        for line in reader.lines() {
            let line = line.map_err(|error| format!("讀取 mpv IPC 失敗：{error}"))?;
            if line.trim().is_empty() {
                continue;
            }
            let value: serde_json::Value = serde_json::from_str(&line)
                .map_err(|error| format!("解析 mpv IPC 回應失敗：{error}"))?;
            if value.get("error").and_then(|entry| entry.as_str()) == Some("success") {
                if let Some(data) = value.get("data") {
                    if data.is_null() {
                        return Ok(0.0);
                    }
                    if let Some(number) = data.as_f64() {
                        return Ok(number);
                    }
                }
            }
        }
        Err("mpv IPC 未回傳有效數值".to_string())
    }
}

fn open_pipe(pipe_path: &str) -> Result<std::fs::File, String> {
    let path = Path::new(pipe_path);
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("開啟 mpv IPC pipe 失敗：{error}"))
}
