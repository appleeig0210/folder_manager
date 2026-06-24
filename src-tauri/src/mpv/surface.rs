use std::sync::{Mutex, OnceLock};

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use windows::core::{BOOL, PCWSTR};
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, WPARAM};
use windows::Win32::Graphics::Gdi::MapWindowPoints;
use windows::Win32::UI::WindowsAndMessaging::{
    CallWindowProcW, CreateWindowExW, DefWindowProcW, DestroyWindow, EnumChildWindows, GetParent,
    GetWindowLongPtrW, IsWindow, SetWindowLongPtrW, SetWindowPos, ShowWindow, GWLP_WNDPROC,
    GWL_EXSTYLE, HWND_TOP, SWP_NOACTIVATE, SWP_SHOWWINDOW, SW_HIDE, SW_SHOW, WM_CONTEXTMENU,
    WM_RBUTTONUP, WNDPROC, WS_CHILD, WS_CLIPSIBLINGS, WS_EX_TRANSPARENT, WS_VISIBLE,
};

use crate::mpv::player::MpvBounds;

static APP_HANDLE: OnceLock<AppHandle> = OnceLock::new();
static HOOKED_WNDPROCS: Mutex<Vec<(isize, isize)>> = Mutex::new(Vec::new());

#[derive(Clone, Serialize)]
struct MpvContextMenuPayload {
    x: i32,
    y: i32,
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

pub unsafe fn create_child_surface(parent: HWND, bounds: &MpvBounds, app_handle: AppHandle) -> Result<HWND, String> {
    let _ = APP_HANDLE.set(app_handle);
    let class = wide("STATIC");
    let hwnd = CreateWindowExW(
        WS_EX_TRANSPARENT,
        PCWSTR(class.as_ptr()),
        PCWSTR::null(),
        WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS,
        bounds.x,
        bounds.y,
        bounds.width.max(1),
        bounds.height.max(1),
        Some(parent),
        None,
        None,
        None,
    )
    .map_err(|error| format!("建立 mpv 視訊表面失敗：{error}"))?;

    let _ = ShowWindow(hwnd, SW_SHOW);
    position_child_surface(hwnd, bounds)?;
    enable_click_through(hwnd)?;
    install_context_menu_hook(hwnd)?;
    Ok(hwnd)
}

pub unsafe fn enable_click_through(hwnd: HWND) -> Result<(), String> {
    let style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
    SetWindowLongPtrW(
        hwnd,
        GWL_EXSTYLE,
        style | WS_EX_TRANSPARENT.0 as isize,
    );
    Ok(())
}

pub unsafe fn position_child_surface(hwnd: HWND, bounds: &MpvBounds) -> Result<(), String> {
    SetWindowPos(
        hwnd,
        Some(HWND_TOP),
        bounds.x,
        bounds.y,
        bounds.width.max(1),
        bounds.height.max(1),
        SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )
    .map_err(|error| format!("更新 mpv 視訊表面位置失敗：{error}"))?;
    Ok(())
}

fn signed_low_word(value: isize) -> i32 {
    (value as u16) as i16 as i32
}

fn signed_high_word(value: isize) -> i32 {
    ((value >> 16) as u16) as i16 as i32
}

unsafe fn top_level_of(hwnd: HWND) -> HWND {
    let mut target = hwnd;
    while let Ok(parent) = GetParent(target) {
        if parent.0.is_null() {
            break;
        }
        target = parent;
    }
    target
}

unsafe fn emit_context_menu(point_in_target: POINT) -> bool {
    if let Some(app) = APP_HANDLE.get() {
        let _ = app.emit(
            "mpv-context-menu",
            MpvContextMenuPayload {
                x: point_in_target.x,
                y: point_in_target.y,
            },
        );
        return true;
    }
    false
}

unsafe fn emit_context_menu_from_client(hwnd: HWND, lparam: LPARAM) -> bool {
    let target = top_level_of(hwnd);
    if target == hwnd {
        return false;
    }
    let mut point = POINT {
        x: signed_low_word(lparam.0),
        y: signed_high_word(lparam.0),
    };
    let _ = MapWindowPoints(Some(hwnd), Some(target), std::slice::from_mut(&mut point));
    emit_context_menu(point)
}

unsafe fn emit_context_menu_from_screen(hwnd: HWND, lparam: LPARAM) -> bool {
    if lparam.0 == -1 {
        return false;
    }
    let target = top_level_of(hwnd);
    if target == hwnd {
        return false;
    }
    let mut point = POINT {
        x: signed_low_word(lparam.0),
        y: signed_high_word(lparam.0),
    };
    // hwndfrom = None maps from screen coordinates to target client coordinates.
    let _ = MapWindowPoints(None, Some(target), std::slice::from_mut(&mut point));
    emit_context_menu(point)
}

unsafe extern "system" fn mpv_context_menu_wndproc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    if msg == WM_RBUTTONUP && emit_context_menu_from_client(hwnd, lparam) {
        return LRESULT(0);
    }
    if msg == WM_CONTEXTMENU && emit_context_menu_from_screen(hwnd, lparam) {
        return LRESULT(0);
    }

    let old_proc = HOOKED_WNDPROCS
        .lock()
        .ok()
        .and_then(|hooks| hooks.iter().find(|(raw, _)| *raw == hwnd.0 as isize).map(|(_, proc)| *proc));

    if let Some(old_proc) = old_proc {
        let old_proc: WNDPROC = std::mem::transmute(old_proc);
        return CallWindowProcW(old_proc, hwnd, msg, wparam, lparam);
    }

    DefWindowProcW(hwnd, msg, wparam, lparam)
}

pub unsafe fn install_context_menu_hook(hwnd: HWND) -> Result<(), String> {
    if hwnd.0.is_null() {
        return Ok(());
    }

    let raw = hwnd.0 as isize;
    let mut hooks = HOOKED_WNDPROCS
        .lock()
        .map_err(|_| "mpv context hook lock poisoned".to_string())?;
    if hooks.iter().any(|(hooked, _)| *hooked == raw) {
        return Ok(());
    }

    let old_proc = SetWindowLongPtrW(hwnd, GWLP_WNDPROC, mpv_context_menu_wndproc as *const () as isize);
    hooks.push((raw, old_proc));
    Ok(())
}

unsafe extern "system" fn install_child_hook_proc(hwnd: HWND, _lparam: LPARAM) -> BOOL {
    let _ = install_context_menu_hook(hwnd);
    BOOL(1)
}

pub unsafe fn install_descendant_context_menu_hooks(hwnd: HWND) -> Result<(), String> {
    install_context_menu_hook(hwnd)?;
    let _ = EnumChildWindows(Some(hwnd), Some(install_child_hook_proc), LPARAM(0));
    Ok(())
}

unsafe fn uninstall_context_menu_hooks() {
    let hooks = HOOKED_WNDPROCS
        .lock()
        .map(|mut hooks| std::mem::take(&mut *hooks))
        .unwrap_or_default();
    for (raw, old_proc) in hooks {
        let hwnd = HWND(raw as *mut _);
        if IsWindow(Some(hwnd)).as_bool() {
            let _ = SetWindowLongPtrW(hwnd, GWLP_WNDPROC, old_proc);
        }
    }
}

pub unsafe fn destroy_child_surface(hwnd: HWND) -> Result<(), String> {
    uninstall_context_menu_hooks();
    if !hwnd.0.is_null() {
        let _ = ShowWindow(hwnd, SW_HIDE);
        DestroyWindow(hwnd).map_err(|error| format!("銷毀 mpv 視訊表面失敗：{error}"))?;
    }
    Ok(())
}

