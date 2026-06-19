use std::sync::mpsc::sync_channel;

use tauri::{AppHandle, Manager, State, WebviewWindow};
use windows::Win32::Foundation::HWND;

use crate::mpv::player::MpvBounds;
use crate::mpv::state::{
    create_surface_on_parent, destroy_surface, detach_session_fast, detach_session_for_ui,
    get_duration, get_time, kill_session, resolve_mpv_executable, seek, set_bounds, set_paused,
    start_mpv_process, store_session, take_session, update_surface_bounds, MpvState,
};

fn hwnd_from_isize(raw: isize) -> HWND {
    HWND(raw as *mut _)
}

fn hwnd_to_isize(hwnd: HWND) -> isize {
    hwnd.0 as isize
}

fn run_on_ui<R, F>(window: &WebviewWindow, f: F) -> Result<R, String>
where
    R: Send + 'static,
    F: FnOnce() -> R + Send + 'static,
{
    let (tx, rx) = sync_channel(1);
    window
        .run_on_main_thread(move || {
            let _ = tx.send(f());
        })
        .map_err(|error| format!("排程 UI 工作失敗：{error}"))?;
    rx.recv()
        .map_err(|_| "UI thread did not return a result".to_string())
}

#[tauri::command]
pub fn mpv_is_available() -> bool {
    resolve_mpv_executable().is_some()
}

#[tauri::command]
pub async fn mpv_attach(
    window: WebviewWindow,
    path: String,
    x: i32,
    y: i32,
    width: i32,
    height: i32,
    state: State<'_, MpvState>,
) -> Result<(), String> {
    if let Some(mut existing) = take_session(state.inner()) {
        let hwnd_raw = hwnd_to_isize(existing.child_hwnd.0);
        let _ = window.run_on_main_thread(move || destroy_surface(hwnd_from_isize(hwnd_raw)));
        kill_session(&mut existing);
    }

    let parent_raw = hwnd_to_isize(
        window
            .hwnd()
            .map_err(|error| format!("取得視窗 handle 失敗：{error}"))?,
    );
    let bounds = MpvBounds { x, y, width, height };

    let child_raw = run_on_ui(&window, move || {
        create_surface_on_parent(hwnd_from_isize(parent_raw), &bounds).map(hwnd_to_isize)
    })??;
    let child_hwnd = hwnd_from_isize(child_raw);

    let pipe_name = format!(r"\\.\pipe\pfm-mpv-{}", std::process::id());
    let (process, ipc) = start_mpv_process(&path, child_hwnd, &pipe_name)?;
    store_session(state.inner(), child_hwnd, process, ipc, bounds)
}

#[tauri::command]
pub async fn mpv_set_bounds(
    window: WebviewWindow,
    x: i32,
    y: i32,
    width: i32,
    height: i32,
    state: State<'_, MpvState>,
) -> Result<(), String> {
    let bounds = MpvBounds { x, y, width, height };
    let hwnd_raw = hwnd_to_isize(set_bounds(state.inner(), bounds)?);
    run_on_ui(&window, move || update_surface_bounds(hwnd_from_isize(hwnd_raw), &bounds))??;
    Ok(())
}

#[tauri::command]
pub async fn mpv_seek(seconds: f64, state: State<'_, MpvState>) -> Result<(), String> {
    seek(state.inner(), seconds)
}

#[tauri::command]
pub async fn mpv_set_paused(paused: bool, state: State<'_, MpvState>) -> Result<(), String> {
    set_paused(state.inner(), paused)
}

#[tauri::command]
pub async fn mpv_get_time(state: State<'_, MpvState>) -> Result<f64, String> {
    get_time(state.inner())
}

#[tauri::command]
pub async fn mpv_get_duration(state: State<'_, MpvState>) -> Result<f64, String> {
    get_duration(state.inner())
}

#[tauri::command]
pub async fn mpv_detach(window: WebviewWindow, state: State<'_, MpvState>) -> Result<(), String> {
    if let Some(hwnd) = detach_session_for_ui(state.inner()) {
        let hwnd_raw = hwnd_to_isize(hwnd);
        let _ = window.run_on_main_thread(move || destroy_surface(hwnd_from_isize(hwnd_raw)));
    }
    Ok(())
}

pub fn cleanup_on_exit(app: &AppHandle) {
    if let Some(state) = app.try_state::<MpvState>() {
        detach_session_fast(state.inner());
    }
}
