use std::collections::HashSet;
use std::process::Command;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri_plugin_shell::process::CommandChild;

pub const API_PORT: u16 = 8765;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn quiet_command(program: &str) -> Command {
    let mut command = Command::new(program);
    command
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

/// Kill a process and all of its descendants (PyInstaller + ffmpeg children).
pub fn kill_process_tree(root_pid: u32) {
    if root_pid == 0 {
        return;
    }

    #[cfg(windows)]
    {
        let _ = quiet_command("taskkill")
            .args(["/T", "/F", "/PID", &root_pid.to_string()])
            .status();
        return;
    }

    #[cfg(not(windows))]
    kill_unix_process_tree(root_pid);
}

#[cfg(not(windows))]
fn kill_unix_process_tree(root_pid: u32) {
    let mut descendants = Vec::new();
    collect_unix_descendants(root_pid, &mut descendants);
    for pid in descendants {
        let _ = quiet_command("kill")
            .args(["-TERM", &pid.to_string()])
            .status();
    }
    let _ = quiet_command("kill")
        .args(["-TERM", &root_pid.to_string()])
        .status();
}

#[cfg(not(windows))]
fn collect_unix_descendants(parent_pid: u32, out: &mut Vec<u32>) {
    let output = match quiet_command("pgrep")
        .args(["-P", &parent_pid.to_string()])
        .output()
    {
        Ok(output) => output,
        Err(_) => return,
    };

    for line in output.stdout.split(|byte| *byte == b'\n') {
        let text = match std::str::from_utf8(line) {
            Ok(text) => text.trim(),
            Err(_) => continue,
        };
        if text.is_empty() {
            continue;
        }
        let Ok(child_pid) = text.parse::<u32>() else {
            continue;
        };
        collect_unix_descendants(child_pid, out);
        out.push(child_pid);
    }
}

pub fn pids_listening_on_port(port: u16) -> Vec<u32> {
    let mut pids = HashSet::new();

    #[cfg(windows)]
    {
        let needle = format!(":{port}");
        let output = match quiet_command("netstat").args(["-ano"]).output() {
            Ok(output) => output,
            Err(_) => return Vec::new(),
        };
        for line in String::from_utf8_lossy(&output.stdout).lines() {
            if !line.contains("LISTENING") || !line.contains(&needle) {
                continue;
            }
            if let Some(pid) = line.split_whitespace().last() {
                if let Ok(pid) = pid.parse::<u32>() {
                    if pid > 0 {
                        pids.insert(pid);
                    }
                }
            }
        }
    }

    #[cfg(not(windows))]
    {
        let output = match quiet_command("lsof")
            .args(["-ti", &format!("tcp:{port}")])
            .output()
        {
            Ok(output) => output,
            Err(_) => return Vec::new(),
        };
        for line in output.stdout.split(|byte| *byte == b'\n') {
            let text = match std::str::from_utf8(line) {
                Ok(text) => text.trim(),
                Err(_) => continue,
            };
            if text.is_empty() {
                continue;
            }
            if let Ok(pid) = text.parse::<u32>() {
                if pid > 0 {
                    pids.insert(pid);
                }
            }
        }
    }

    pids.into_iter().collect()
}

/// Remove orphaned api-server instances from previous runs.
pub fn cleanup_stale_api_servers() {
    for pid in pids_listening_on_port(API_PORT) {
        kill_process_tree(pid);
    }

    #[cfg(windows)]
    {
        let _ = quiet_command("taskkill")
            .args(["/F", "/IM", "api-server.exe", "/T"])
            .status();
    }

    #[cfg(not(windows))]
    {
        let _ = quiet_command("pkill")
            .args(["-f", "api-server"])
            .status();
    }
}

pub fn stop_tracked_sidecar(child: Option<CommandChild>) {
    if let Some(child) = child {
        let pid = child.pid();
        let _ = child.kill();
        kill_process_tree(pid);
    }
    cleanup_stale_api_servers();
}
