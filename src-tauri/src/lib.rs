#[cfg(not(debug_assertions))]
use std::sync::Mutex;

#[cfg(not(debug_assertions))]
use tauri::Manager;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{process::CommandChild, ShellExt};

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
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app_handle, event| {
        #[cfg(not(debug_assertions))]
        match event {
            tauri::RunEvent::Exit => cleanup_api_sidecar(app_handle),
            tauri::RunEvent::ExitRequested { .. } => cleanup_api_sidecar(app_handle),
            tauri::RunEvent::WindowEvent {
                event: tauri::WindowEvent::CloseRequested { .. },
                ..
            } => cleanup_api_sidecar(app_handle),
            _ => {}
        }

        #[cfg(debug_assertions)]
        {
            let _ = app_handle;
            let _ = event;
        }
    });
}
