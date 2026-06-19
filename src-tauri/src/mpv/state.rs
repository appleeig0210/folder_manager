use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use windows::Win32::Foundation::HWND;

use crate::mpv::ipc::MpvIpc;
use crate::mpv::player::{find_mpv_executable, MpvBounds, MpvSession, SendHwnd};
use crate::mpv::surface::{
    create_child_surface, destroy_child_surface, enable_click_through, position_child_surface,
};

pub struct MpvState(pub Mutex<Option<MpvSession>>);

impl Default for MpvState {
    fn default() -> Self {
        Self(Mutex::new(None))
    }
}

pub fn resolve_mpv_executable() -> Option<std::path::PathBuf> {
    find_mpv_executable()
}

fn with_ipc<T>(state: &MpvState, op: impl FnOnce(&MpvIpc) -> Result<T, String>) -> Result<T, String> {
    let ipc = {
        let guard = state
            .0
            .lock()
            .map_err(|_| "mpv state lock poisoned".to_string())?;
        let session = guard
            .as_ref()
            .ok_or_else(|| "mpv 尚未啟動".to_string())?;
        MpvIpc::from_path(session.ipc.pipe_path())
    };
    op(&ipc)
}

pub fn take_session(state: &MpvState) -> Option<MpvSession> {
    state.0.lock().ok()?.take()
}

pub fn create_surface_on_parent(parent: HWND, bounds: &MpvBounds) -> Result<HWND, String> {
    unsafe {
        let hwnd = create_child_surface(parent, bounds)?;
        enable_click_through(hwnd)?;
        Ok(hwnd)
    }
}

pub fn update_surface_bounds(hwnd: HWND, bounds: &MpvBounds) -> Result<(), String> {
    unsafe {
        position_child_surface(hwnd, bounds)?;
        enable_click_through(hwnd)
    }
}

pub fn destroy_surface(hwnd: HWND) {
    unsafe {
        let _ = destroy_child_surface(hwnd);
    }
}

pub fn start_mpv_process(path: &str, child_hwnd: HWND, pipe_name: &str) -> Result<(Child, MpvIpc), String> {
    let mpv_path = find_mpv_executable().ok_or_else(|| {
        "找不到 mpv。請安裝 mpv（winget install mpv）或將 mpv.exe 放到 src-tauri/bin/".to_string()
    })?;

    let wid = child_hwnd.0 as isize;
    let mut command = Command::new(mpv_path);
    command
        .arg(path)
        .arg(format!("--wid={wid}"))
        .arg(format!("--input-ipc-server={pipe_name}"))
        .arg("--no-terminal")
        .arg("--osc=no")
        .arg("--input-vo-keyboard=no")
        .arg("--input-default-bindings=no")
        .arg("--input-builtin-bindings=no")
        .arg("--cursor-autohide=no")
        .arg("--keep-open=no")
        .arg("--hr-seek=yes")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let process = command
        .spawn()
        .map_err(|error| format!("啟動 mpv 失敗：{error}"))?;
    let ipc = MpvIpc::connect(pipe_name, 5000)?;
    Ok((process, ipc))
}

pub fn store_session(
    state: &MpvState,
    child_hwnd: HWND,
    process: Child,
    ipc: MpvIpc,
    bounds: MpvBounds,
) -> Result<(), String> {
    let mut guard = state
        .0
        .lock()
        .map_err(|_| "mpv state lock poisoned".to_string())?;
    *guard = Some(MpvSession {
        child_hwnd: SendHwnd(child_hwnd),
        process,
        ipc,
        bounds,
    });
    Ok(())
}

pub fn set_bounds(state: &MpvState, bounds: MpvBounds) -> Result<HWND, String> {
    let mut guard = state
        .0
        .lock()
        .map_err(|_| "mpv state lock poisoned".to_string())?;
    let session = guard
        .as_mut()
        .ok_or_else(|| "mpv 尚未啟動".to_string())?;
    session.bounds = bounds;
    Ok(session.child_hwnd.0)
}

pub fn seek(state: &MpvState, seconds: f64) -> Result<(), String> {
    with_ipc(state, |ipc| ipc.seek(seconds))
}

pub fn set_paused(state: &MpvState, paused: bool) -> Result<(), String> {
    with_ipc(state, |ipc| ipc.set_paused(paused))
}

pub fn get_time(state: &MpvState) -> Result<f64, String> {
    if !state.0.lock().map(|g| g.is_some()).unwrap_or(false) {
        return Ok(0.0);
    }
    with_ipc(state, |ipc| ipc.get_time_pos())
}

pub fn get_duration(state: &MpvState) -> Result<f64, String> {
    if !state.0.lock().map(|g| g.is_some()).unwrap_or(false) {
        return Ok(0.0);
    }
    with_ipc(state, |ipc| ipc.get_duration())
}

pub fn kill_session(session: &mut MpvSession) {
    let pipe = session.ipc.pipe_path().to_string();
    let _ = session.process.kill();
    std::thread::spawn(move || {
        let _ = MpvIpc::from_path(pipe).quit();
    });
}

/// Non-blocking detach for app exit. Never waits on mpv or destroys HWND synchronously.
pub fn detach_session_fast(state: &MpvState) {
    if let Some(mut session) = take_session(state) {
        kill_session(&mut session);
    }
}

pub fn detach_session_for_ui(state: &MpvState) -> Option<HWND> {
    take_session(state).map(|mut session| {
        kill_session(&mut session);
        session.child_hwnd.0
    })
}
