#[cfg(windows)]
mod commands;
#[cfg(windows)]
mod ipc;
#[cfg(windows)]
mod player;
#[cfg(windows)]
mod state;
#[cfg(windows)]
mod surface;

#[cfg(windows)]
pub use commands::cleanup_on_exit;
#[cfg(windows)]
pub use commands::*;
#[cfg(windows)]
pub use state::MpvState;

#[cfg(not(windows))]
use tauri::ipc::InvokeError;

#[cfg(not(windows))]
#[derive(Default)]
pub struct MpvState;

#[cfg(not(windows))]
pub fn cleanup_on_exit(_app: &tauri::AppHandle) {}

#[cfg(not(windows))]
#[tauri::command]
pub fn mpv_is_available() -> bool {
    false
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_attach(_path: String) -> Result<(), InvokeError> {
    Err("mpv embedding is only supported on Windows".into())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_set_bounds(_x: i32, _y: i32, _width: i32, _height: i32) -> Result<(), InvokeError> {
    Err("mpv embedding is only supported on Windows".into())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_set_surface_visible(_visible: bool) -> Result<(), InvokeError> {
    Ok(())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_rehook_context_menu() -> Result<(), InvokeError> {
    Ok(())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_seek(_seconds: f64) -> Result<(), InvokeError> {
    Err("mpv embedding is only supported on Windows".into())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_set_paused(_paused: bool) -> Result<(), InvokeError> {
    Err("mpv embedding is only supported on Windows".into())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_get_time() -> Result<f64, InvokeError> {
    Err("mpv embedding is only supported on Windows".into())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_get_duration() -> Result<f64, InvokeError> {
    Err("mpv embedding is only supported on Windows".into())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_set_volume(_volume: f64) -> Result<(), InvokeError> {
    Err("mpv embedding is only supported on Windows".into())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_set_muted(_muted: bool) -> Result<(), InvokeError> {
    Err("mpv embedding is only supported on Windows".into())
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn mpv_detach() -> Result<(), InvokeError> {
    Ok(())
}
