use std::sync::Mutex;

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

struct ApiSidecar(Mutex<Option<CommandChild>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_drag::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let (_rx, child) = app.shell().sidecar("api-server")?.spawn()?;
            app.manage(ApiSidecar(Mutex::new(Some(child))));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            if let Some(sidecar) = app_handle.try_state::<ApiSidecar>() {
                if let Ok(mut child) = sidecar.0.lock() {
                    if let Some(child) = child.take() {
                        let _ = child.kill();
                    }
                }
            }
        }
    });
}
