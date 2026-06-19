#[cfg(not(debug_assertions))]
use std::sync::Mutex;

#[cfg(not(debug_assertions))]
use tauri::Manager;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{process::CommandChild, ShellExt};

mod mpv;

#[cfg(not(debug_assertions))]
mod sidecar_lifecycle;

#[cfg(not(debug_assertions))]
struct ApiSidecar(Mutex<Option<CommandChild>>);

#[cfg(not(debug_assertions))]
fn cleanup_api_sidecar(app_handle: &tauri::AppHandle) {
    if let Some(sidecar) = app_handle.try_state::<ApiSidecar>() {
        if let Ok(mut child) = sidecar.0.lock() {
            let tracked = child.take();
            sidecar_lifecycle::stop_tracked_sidecar(tracked);
            return;
        }
    }
    sidecar_lifecycle::cleanup_stale_api_servers();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_drag::init())
        .plugin(tauri_plugin_shell::init())
        .manage(mpv::MpvState::default())
        .setup(|_app| {
            #[cfg(not(debug_assertions))]
            {
                sidecar_lifecycle::cleanup_stale_api_servers();
                std::thread::sleep(std::time::Duration::from_millis(150));
                let (_rx, child) = _app.shell().sidecar("api-server")?.spawn()?;
                _app.manage(ApiSidecar(Mutex::new(Some(child))));
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            mpv::mpv_is_available,
            mpv::mpv_attach,
            mpv::mpv_set_bounds,
            mpv::mpv_seek,
            mpv::mpv_set_paused,
            mpv::mpv_set_volume,
            mpv::mpv_set_muted,
            mpv::mpv_get_time,
            mpv::mpv_get_duration,
            mpv::mpv_detach,
        ])
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::Exit
                | tauri::RunEvent::ExitRequested { .. }
                | tauri::RunEvent::WindowEvent {
                    event: tauri::WindowEvent::CloseRequested { .. },
                    ..
                }
        ) {
            mpv::cleanup_on_exit(app_handle);
            #[cfg(not(debug_assertions))]
            cleanup_api_sidecar(app_handle);
        }
    });
}
