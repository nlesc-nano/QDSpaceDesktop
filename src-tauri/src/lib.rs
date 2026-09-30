use tauri::Manager;

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
      start_local_services(app.handle());
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
  // Developer override only. A downloaded installer must not search
  // %USERPROFILE%\Downloads\Desktop App or launch Python/Docker from it.
  let Ok(root) = std::env::var("QDSPACE_ROOT") else {
    return None;
  };
  let root = root.trim();
  if root.is_empty() {
    return None;
  }
  let path = std::path::PathBuf::from(root);
  let sidecar_script = path.join("sidecar").join("sidecar_app.py");
  if sidecar_script.is_file() { Some(path) } else { None }
}

fn hidden(cmd: &mut std::process::Command) {
  #[cfg(windows)]
  {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    cmd.creation_flags(CREATE_NO_WINDOW);
  }
  #[cfg(not(windows))]
  {
    let _ = cmd;
  }
}

fn bundled_python(runtime: &std::path::Path) -> Option<std::path::PathBuf> {
  if cfg!(windows) {
    let python = runtime.join("python.exe");
    return python.is_file().then_some(python);
  }
  for name in ["python", "python3"] {
    let python = runtime.join("bin").join(name);
    if python.is_file() {
      return Some(python);
    }
  }
  None
}

/// Packaged runtime from bundle.resources: resource_dir/mace-runtime.
fn bundled_runtime(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
  let resource_dir = app.path().resource_dir().ok()?;
  let runtime = resource_dir.join("mace-runtime");
  let script = runtime.join("app").join("sidecar_app.py");
  if script.is_file() && bundled_python(&runtime).is_some() {
    Some(runtime)
  } else {
    None
  }
}

fn spawn_uvicorn(python: &std::path::Path, cwd: &std::path::Path) {
  let mut cmd = std::process::Command::new(python);
  cmd
    .args(["-m", "uvicorn", "sidecar_app:app", "--host", "127.0.0.1", "--port", "8765"])
    .current_dir(cwd)
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
}

fn start_developer_services(root: &std::path::Path) {
  if !listening(8765) {
    let python = std::env::var("USERPROFILE")
      .map(std::path::PathBuf::from)
      .unwrap_or_default()
      .join(".conda")
      .join("envs")
      .join("webappdesktop")
      .join("python.exe");
    if python.is_file() {
      spawn_uvicorn(&python, &root.join("sidecar"));
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

fn start_local_services(app: &tauri::AppHandle) {
  // QDSPACE_ROOT is the developer tree (conda sidecar + Builder Docker).
  // Installers leave it unset and must not start Docker.
  if let Some(root) = project_root() {
    start_developer_services(&root);
    return;
  }

  if listening(8765) {
    return;
  }
  if let Some(runtime) = bundled_runtime(app) {
    if let Some(python) = bundled_python(&runtime) {
      spawn_uvicorn(&python, &runtime.join("app"));
    }
  }
}
