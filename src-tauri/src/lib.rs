#[cfg(not(debug_assertions))]
use std::sync::Mutex;

#[cfg(not(debug_assertions))]
use tauri::Manager;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[cfg(not(debug_assertions))]
struct ApiSidecar(Mutex<Option<CommandChild>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_drag::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|_app| {
            #[cfg(not(debug_assertions))]
            {
                let (_rx, child) = _app.shell().sidecar("api-server")?.spawn()?;
                _app.manage(ApiSidecar(Mutex::new(Some(child))));
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app_handle, event| {
        #[cfg(not(debug_assertions))]
        if let tauri::RunEvent::Exit = event {
            if let Some(sidecar) = app_handle.try_state::<ApiSidecar>() {
                if let Ok(mut child) = sidecar.0.lock() {
                    if let Some(child) = child.take() {
                        let _ = child.kill();
                    }
                }
            }
        }

        #[cfg(debug_assertions)]
        {
            let _ = app_handle;
            let _ = event;
        }
    });
}
