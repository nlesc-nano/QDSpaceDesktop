#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      start_local_services();
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while building tauri application");
}

fn listening(port: u16) -> bool {
  std::net::TcpStream::connect_timeout(
    &std::net::SocketAddr::from(([127, 0, 0, 1], port)),
    std::time::Duration::from_millis(400),
  )
  .is_ok()
}

fn project_root() -> Option<std::path::PathBuf> {
  let mut candidates = Vec::new();
  if let Ok(root) = std::env::var("QDSPACE_ROOT") {
    candidates.push(std::path::PathBuf::from(root));
  }
  if let Ok(home) = std::env::var("USERPROFILE") {
    candidates.push(std::path::PathBuf::from(home).join("Downloads").join("Desktop App"));
  }
  candidates.into_iter().find(|path| path.join("sidecar").join("sidecar_app.py").is_file())
}

fn hidden(cmd: &mut std::process::Command) {
  #[cfg(windows)]
  {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    cmd.creation_flags(CREATE_NO_WINDOW);
  }
}

fn start_local_services() {
  let Some(root) = project_root() else {
    eprintln!("QDSpace project folder was not found, so the sidecar and Builder were not started.");
    return;
  };

  if !listening(8765) {
    let python = std::env::var("USERPROFILE")
      .map(std::path::PathBuf::from)
      .unwrap_or_default()
      .join(".conda")
      .join("envs")
      .join("webappdesktop")
      .join("python.exe");
    if python.is_file() {
      let mut cmd = std::process::Command::new(&python);
      cmd
        .args(["-m", "uvicorn", "sidecar_app:app", "--host", "127.0.0.1", "--port", "8765"])
        .current_dir(root.join("sidecar"))
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
      hidden(&mut cmd);
      match cmd.spawn() {
        Ok(child) => {
          std::mem::forget(child);
        }
        Err(err) => eprintln!("could not start sidecar: {err}"),
      }
    } else {
      eprintln!("sidecar Python was not found at {}", python.display());
    }
  }

  if !listening(8000) {
    let mut cmd = std::process::Command::new("docker");
    cmd
      .args(["run", "--rm", "-p", "8000:8000", "qdspace-builder"])
      .stdin(std::process::Stdio::null())
      .stdout(std::process::Stdio::null())
      .stderr(std::process::Stdio::null());
    hidden(&mut cmd);
    match cmd.spawn() {
      Ok(child) => {
        std::mem::forget(child);
      }
      Err(err) => eprintln!("could not start Builder container: {err}"),
    }
  }
}
