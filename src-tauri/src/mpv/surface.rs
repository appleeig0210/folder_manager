use windows::core::PCWSTR;
use windows::Win32::Foundation::HWND;
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DestroyWindow, GetWindowLongPtrW, SetWindowLongPtrW, SetWindowPos, ShowWindow,
    GWL_EXSTYLE, HWND_TOP, SWP_NOACTIVATE, SWP_SHOWWINDOW, SW_HIDE, SW_SHOW, WS_CHILD, WS_CLIPSIBLINGS,
    WS_EX_TRANSPARENT, WS_VISIBLE,
};

use crate::mpv::player::MpvBounds;

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

pub unsafe fn create_child_surface(parent: HWND, bounds: &MpvBounds) -> Result<HWND, String> {
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

pub unsafe fn hide_child_surface(hwnd: HWND) -> Result<(), String> {
    if !hwnd.0.is_null() {
        let _ = ShowWindow(hwnd, SW_HIDE);
    }
    Ok(())
}

pub unsafe fn destroy_child_surface(hwnd: HWND) -> Result<(), String> {
    if !hwnd.0.is_null() {
        let _ = ShowWindow(hwnd, SW_HIDE);
        DestroyWindow(hwnd).map_err(|error| format!("銷毀 mpv 視訊表面失敗：{error}"))?;
    }
    Ok(())
}
