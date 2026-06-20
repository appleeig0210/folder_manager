//! Windows shell file drag — delegates to patched `drag` crate (full taskbar drop effects).

#[cfg(windows)]
mod imp {
    use drag::{DragItem, Image, Options};
    use tauri::{Runtime, Window};

    pub fn start_shell_file_drag<R: Runtime>(
        window: &Window<R>,
        paths: Vec<String>,
        icon: Option<String>,
    ) -> std::result::Result<(), String> {
        let mut canonical_paths = Vec::with_capacity(paths.len());
        for path in paths {
            let trimmed = path.trim();
            if trimmed.is_empty() {
                continue;
            }
            canonical_paths.push(
                dunce::canonicalize(trimmed)
                    .map_err(|error| format!("無法解析路徑 {trimmed}: {error}"))?,
            );
        }
        if canonical_paths.is_empty() {
            return Err("沒有可拖曳的檔案".into());
        }

        let preview = decode_drag_icon(icon);

        drag::start_drag(
            window,
            DragItem::Files(canonical_paths),
            preview,
            |_result, _cursor| {},
            Options::default(),
        )
        .map_err(|error| error.to_string())
    }

    fn decode_drag_icon(icon: Option<String>) -> Image {
        let Some(icon) = icon else {
            return Image::Raw(Vec::new());
        };
        let Some(payload) = icon.strip_prefix("data:image/png;base64,") else {
            return Image::Raw(Vec::new());
        };
        use base64::Engine;
        match base64::engine::general_purpose::STANDARD.decode(payload) {
            Ok(bytes) => Image::Raw(bytes),
            Err(_) => Image::Raw(Vec::new()),
        }
    }
}

#[cfg(windows)]
#[tauri::command]
pub async fn start_shell_file_drag_command<R: tauri::Runtime>(
    app: tauri::AppHandle<R>,
    window: tauri::Window<R>,
    paths: Vec<String>,
    icon: Option<String>,
) -> std::result::Result<(), String> {
    let (tx, rx) = std::sync::mpsc::channel();
    app.run_on_main_thread(move || {
        let result = imp::start_shell_file_drag(&window, paths, icon);
        let _ = tx.send(result);
    })
    .map_err(|error| error.to_string())?;

    rx.recv()
        .map_err(|_| "拖曳操作已中斷".to_string())?
}

#[cfg(not(windows))]
#[tauri::command]
pub async fn start_shell_file_drag_command(
    _paths: Vec<String>,
    _icon: Option<String>,
) -> std::result::Result<(), String> {
    Err("Shell file drag is only available on Windows".into())
}
