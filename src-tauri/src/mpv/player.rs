use std::path::PathBuf;
use std::process::Child;

use windows::Win32::Foundation::HWND;

use crate::mpv::ipc::MpvIpc;

#[derive(Clone, Copy, Debug)]
pub struct MpvBounds {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

#[derive(Clone, Copy, Debug)]
pub struct SendHwnd(pub HWND);

// HWND is only used on the UI thread for Win32 child window placement.
unsafe impl Send for SendHwnd {}
unsafe impl Sync for SendHwnd {}

pub struct MpvSession {
    pub child_hwnd: SendHwnd,
    pub process: Child,
    pub ipc: MpvIpc,
    pub bounds: MpvBounds,
}

pub fn find_mpv_executable() -> Option<PathBuf> {
    for binary in ["mpv.exe", "mpv.com"] {
        if let Some(path) = find_on_path(binary) {
            return Some(path);
        }
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let bundled = dir.join("mpv.exe");
            if bundled.is_file() {
                return Some(bundled);
            }
            let bin_dir = dir.join("bin").join("mpv.exe");
            if bin_dir.is_file() {
                return Some(bin_dir);
            }
        }
    }

    let candidates = [
        PathBuf::from(r"C:\Program Files\mpv\mpv.exe"),
        PathBuf::from(r"C:\Program Files (x86)\mpv\mpv.exe"),
    ];
    for candidate in candidates {
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    None
}

fn find_on_path(binary: &str) -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    std::env::split_paths(&path_var).find_map(|dir| {
        let candidate = dir.join(binary);
        if candidate.is_file() { Some(candidate) } else { None }
    })
}
