use tauri::Manager;

const SIDECAR_PORT: u16 = 8765;
/// Structure Builder API (src/Builder.svelte calls /builder/api/* here).
const BUILDER_PORT: u16 = 8000;

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct UserPythonInfo {
  python: String,
  device: String,
  torch: String,
  installed_mace: bool,
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct PinChange {
  /// Import / distribution name, e.g. e3nn.
  name: String,
  /// Exact version required by the packed MACE runtime.
  required: String,
  /// Version currently installed, if any.
  current: Option<String>,
  /// Human-readable warning for the install dialog.
  message: String,
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct PythonCheck {
  python: String,
  device: String,
  torch: String,
  missing: Vec<String>,
  /// Pinned MACE companions that would be installed or changed (e.g. e3nn 0.6.0 → 0.4.4).
  pin_changes: Vec<PinChange>,
}

#[derive(serde::Deserialize)]
#[allow(dead_code)]
struct Probe {
  torch: Option<String>,
  cuda: bool,
  mps: bool,
  missing: Vec<String>,
  pins: std::collections::BTreeMap<String, String>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .invoke_handler(tauri::generate_handler![pick_python_path, check_user_python, apply_user_python, cancel_python_install, python_install_status, take_sidecar_failure, library_cache_read, library_cache_write, library_cache_stat, library_cache_dir])
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

fn developer_sidecar_python() -> std::path::PathBuf {
  std::env::var("USERPROFILE")
    .map(std::path::PathBuf::from)
    .unwrap_or_default()
    .join(".conda")
    .join("envs")
    .join("webappdesktop")
    .join("python.exe")
}

fn spawn_uvicorn(python: &std::path::Path, cwd: &std::path::Path, bundled: bool) {
  let mut cmd = std::process::Command::new(python);
  cmd
    .args(["-m", "uvicorn", "sidecar_app:app", "--host", "127.0.0.1", "--port", "8765"])
    .current_dir(cwd)
    .stdin(std::process::Stdio::null())
    .stdout(std::process::Stdio::null())
    .stderr(std::process::Stdio::null());
  // Packed Windows Python does not search Lib\site-packages\torch\lib unless PATH
  // includes it. with_python_env already adds that directory for a user interpreter.
  if bundled {
    with_python_env(&mut cmd, python);
  }
  hidden(&mut cmd);
  match cmd.spawn() {
    Ok(child) => {
      std::mem::forget(child);
    }
    Err(err) => eprintln!("could not start sidecar: {err}"),
  }
}

fn start_developer_services(root: &std::path::Path) {
  if !listening(SIDECAR_PORT) {
    let python = developer_sidecar_python();
    if python.is_file() {
      spawn_uvicorn(&python, &root.join("sidecar"), false);
    } else {
      eprintln!("sidecar Python was not found at {}", python.display());
    }
  }
}

/// A Builder runtime folder from scripts/build-builder-runtime.mjs:
/// python.exe (Windows) or bin/python, plus app/builder_app.py.
fn builder_runtime_at(runtime: std::path::PathBuf) -> Option<std::path::PathBuf> {
  let script = runtime.join("app").join("builder_app.py");
  if script.is_file() && bundled_python(&runtime).is_some() {
    Some(runtime)
  } else {
    None
  }
}

/// Packed Builder from bundle.resources (resource_dir/builder-runtime).
/// Debug builds (`tauri dev`) also accept the repo's builder-runtime/ next to
/// src-tauri, so `npm run builder-runtime` is enough to get Builder in dev.
fn builder_runtime(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
  if let Ok(resource_dir) = app.path().resource_dir() {
    if let Some(runtime) = builder_runtime_at(resource_dir.join("builder-runtime")) {
      return Some(runtime);
    }
  }
  #[cfg(debug_assertions)]
  {
    let manifest = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    if let Some(repo) = manifest.parent() {
      if let Some(runtime) = builder_runtime_at(repo.join("builder-runtime")) {
        return Some(runtime);
      }
    }
  }
  None
}

fn spawn_builder(python: &std::path::Path, cwd: &std::path::Path) {
  let mut cmd = std::process::Command::new(python);
  cmd
    .args(["-m", "uvicorn", "builder_app:app", "--host", "127.0.0.1", "--port", "8000"])
    .current_dir(cwd)
    .stdin(std::process::Stdio::null());
  // Startup errors (a missing module, port clash) land here instead of vanishing.
  let log_path = std::env::temp_dir().join("qdspace-builder.log");
  match std::fs::File::create(&log_path).and_then(|file| Ok((file.try_clone()?, file))) {
    Ok((stdout, stderr)) => {
      cmd.stdout(std::process::Stdio::from(stdout)).stderr(std::process::Stdio::from(stderr));
    }
    Err(_) => {
      cmd.stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null());
    }
  }
  with_python_env(&mut cmd, python);
  // The packed interpreter must not pick up a developer's Python environment.
  cmd.env_remove("PYTHONPATH");
  cmd.env_remove("PYTHONHOME");
  cmd.env("PYTHONUNBUFFERED", "1");
  cmd.env("MPLBACKEND", "Agg");
  hidden(&mut cmd);
  match cmd.spawn() {
    Ok(child) => {
      std::mem::forget(child);
    }
    Err(err) => eprintln!("could not start Builder: {err}"),
  }
}

/// Old developer path: the qdspace-builder Docker image. Only used when
/// QDSPACE_ROOT is set and no builder-runtime was built. Installers never
/// reach this, so end users do not need Docker for Builder.
fn spawn_builder_docker() {
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

/// Start the Builder API on 127.0.0.1:8000: packed builder-runtime first
/// (installers and `tauri dev` after `npm run builder-runtime`), then Docker
/// only as a developer fallback. Leaves an existing listener on 8000 alone.
fn start_builder(app: &tauri::AppHandle) {
  if listening(BUILDER_PORT) {
    return;
  }
  if let Some(runtime) = builder_runtime(app) {
    if let Some(python) = bundled_python(&runtime) {
      spawn_builder(&python, &runtime.join("app"));
      return;
    }
  }
  if project_root().is_some() {
    spawn_builder_docker();
    return;
  }
  eprintln!("Builder runtime not found. Run `npm run builder-runtime` to build it.");
}

fn start_local_services(app: &tauri::AppHandle) {
  // Builder runs from the packed builder-runtime (no Docker for installers).
  start_builder(app);

  // QDSPACE_ROOT is the developer tree (conda sidecar).
  if let Some(root) = project_root() {
    start_developer_services(&root);
    return;
  }

  if listening(SIDECAR_PORT) {
    return;
  }
  if let Some(runtime) = bundled_runtime(app) {
    if let Some(python) = bundled_python(&runtime) {
      spawn_uvicorn(&python, &runtime.join("app"), true);
    }
  }
}

fn restart_default_sidecar(app: &tauri::AppHandle) {
  if listening(SIDECAR_PORT) {
    return;
  }
  if let Some(root) = project_root() {
    let python = developer_sidecar_python();
    if python.is_file() {
      spawn_uvicorn(&python, &root.join("sidecar"), false);
      return;
    }
  }
  if let Some(runtime) = bundled_runtime(app) {
    if let Some(python) = bundled_python(&runtime) {
      spawn_uvicorn(&python, &runtime.join("app"), true);
    }
  }
}

/// Repo sidecar next to src-tauri. Only debug builds (`tauri dev`) may use it.
/// A release installer must not fall back to a source tree on the machine.
fn dev_repo_sidecar() -> Option<std::path::PathBuf> {
  #[cfg(debug_assertions)]
  {
    let dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../sidecar");
    if dir.join("sidecar_app.py").is_file() {
      return Some(std::fs::canonicalize(&dir).unwrap_or(dir));
    }
  }
  None
}

fn sidecar_workdir(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
  if let Some(root) = project_root() {
    let dir = root.join("sidecar");
    if dir.join("sidecar_app.py").is_file() {
      return Ok(dir);
    }
  }
  // User Python does not need the packed mace-runtime. In `tauri dev` the
  // selected interpreter runs the repo sidecar (cwd / PYTHONPATH).
  if let Some(dir) = dev_repo_sidecar() {
    return Ok(dir);
  }
  if let Some(runtime) = bundled_runtime(app) {
    let dir = runtime.join("app");
    if dir.join("sidecar_app.py").is_file() {
      return Ok(dir);
    }
  }
  Err("The Predict sidecar files are not in this install.".into())
}

fn clean_python_path(raw: &str) -> String {
  raw.trim().trim_matches(|c| c == '"' || c == '\'').trim().to_string()
}

fn same_path(left: &std::path::Path, right: &std::path::Path) -> bool {
  if left == right {
    return true;
  }
  match (std::fs::canonicalize(left), std::fs::canonicalize(right)) {
    (Ok(a), Ok(b)) => a == b,
    _ => false,
  }
}


fn looks_like_bundled_runtime(python: &std::path::Path) -> bool {
  python.components().any(|component| component.as_os_str().to_string_lossy().eq_ignore_ascii_case("mace-runtime"))
}

fn is_bundled_python(app: &tauri::AppHandle, python: &std::path::Path) -> bool {
  let Some(runtime) = bundled_runtime(app) else {
    return false;
  };
  if let Some(bundled) = bundled_python(&runtime) {
    if same_path(python, &bundled) {
      return true;
    }
  }
  let python = std::fs::canonicalize(python).unwrap_or_else(|_| python.to_path_buf());
  let runtime = std::fs::canonicalize(&runtime).unwrap_or(runtime);
  python.starts_with(&runtime)
}

fn env_root_for(python: &std::path::Path) -> std::path::PathBuf {
  let Some(parent) = python.parent() else {
    return python.to_path_buf();
  };
  match parent.file_name().and_then(|name| name.to_str()) {
    Some("bin") | Some("Scripts") => parent.parent().unwrap_or(parent).to_path_buf(),
    _ => parent.to_path_buf(),
  }
}

fn augmented_path(python: &std::path::Path) -> String {
  let root = env_root_for(python);
  let mut dirs = Vec::new();
  if let Some(parent) = python.parent() {
    dirs.push(parent.to_path_buf());
  }
  dirs.push(root.clone());
  dirs.push(root.join("Library").join("bin"));
  dirs.push(root.join("Library").join("usr").join("bin"));
  dirs.push(root.join("Scripts"));
  dirs.push(root.join("bin"));
  dirs.push(root.join("Lib").join("site-packages").join("torch").join("lib"));
  let mut parts = Vec::new();
  for dir in dirs {
    if !dir.is_dir() {
      continue;
    }
    let text = dir.to_string_lossy().to_string();
    if !parts.iter().any(|existing: &String| existing == &text) {
      parts.push(text);
    }
  }
  if let Ok(old) = std::env::var("PATH") {
    if !old.is_empty() {
      parts.push(old);
    }
  }
  let sep = if cfg!(windows) { ";" } else { ":" };
  parts.join(sep)
}

fn with_python_env(cmd: &mut std::process::Command, python: &std::path::Path) {
  cmd.env("PATH", augmented_path(python));
  cmd.env("PYTHONUTF8", "1");
  cmd.env("PYTHONIOENCODING", "utf-8");
}

const INSTALL_CANCELLED: &str = "Install cancelled.";

struct InstallCtrl {
  running: bool,
  cancel: bool,
  pid: Option<u32>,
  package: String,
  percent: Option<u8>,
  lines: Vec<String>,
}

static INSTALL: std::sync::Mutex<InstallCtrl> = std::sync::Mutex::new(InstallCtrl {
  running: false,
  cancel: false,
  pid: None,
  package: String::new(),
  percent: None,
  lines: Vec::new(),
});

fn install_lock() -> std::sync::MutexGuard<'static, InstallCtrl> {
  INSTALL.lock().unwrap_or_else(|err| err.into_inner())
}

fn begin_install_session() {
  let mut gate = install_lock();
  gate.running = true;
  gate.cancel = false;
  gate.pid = None;
  gate.package.clear();
  gate.percent = None;
  gate.lines.clear();
}

fn end_install_session() {
  let mut gate = install_lock();
  gate.running = false;
  gate.cancel = false;
  gate.pid = None;
}

fn install_running() -> bool {
  install_lock().running
}

fn install_cancelled() -> bool {
  install_lock().cancel
}

fn remember_install_pid(pid: u32) -> bool {
  let mut gate = install_lock();
  if gate.cancel || !gate.running {
    return false;
  }
  gate.pid = Some(pid);
  true
}

fn forget_install_pid(pid: u32) {
  let mut gate = install_lock();
  if gate.pid == Some(pid) {
    gate.pid = None;
  }
}

fn kill_install_pid(pid: u32) {
  #[cfg(windows)]
  {
    kill_pid(pid);
  }
  #[cfg(not(windows))]
  {
    let mut cmd = std::process::Command::new("kill");
    cmd.args(["-9", &pid.to_string()]);
    hidden(&mut cmd);
    let _ = cmd.output();
  }
}

fn force_stop_child(child: &mut std::process::Child) {
  let pid = child.id();
  forget_install_pid(pid);
  kill_install_pid(pid);
  let _ = child.kill();
  let _ = child.wait();
}

fn set_install_label(label: &str) {
  let label = label.trim();
  if label.is_empty() {
    return;
  }
  let mut gate = install_lock();
  if !gate.running {
    return;
  }
  gate.package = clip_chars(label, 80);
  gate.percent = None;
}

fn clip_chars(text: &str, max: usize) -> String {
  if text.chars().count() <= max {
    return text.to_string();
  }
  let mut out: String = text.chars().take(max.saturating_sub(1)).collect();
  out.push('…');
  out
}

fn strip_ansi(input: &str) -> String {
  let mut out = String::with_capacity(input.len());
  let mut chars = input.chars().peekable();
  while let Some(ch) = chars.next() {
    if ch == '\u{1b}' {
      if chars.peek() == Some(&'[') {
        chars.next();
        for next in chars.by_ref() {
          if next.is_ascii_alphabetic() {
            break;
          }
        }
      }
      continue;
    }
    out.push(ch);
  }
  out
}

fn visible_pip_line(raw: &str) -> String {
  let stripped = strip_ansi(raw);
  stripped
    .split(['\r', '\n'])
    .map(str::trim)
    .filter(|part| !part.is_empty())
    .next_back()
    .unwrap_or("")
    .to_string()
}

fn parse_progress(line: &str) -> Option<(u64, u64)> {
  let rest = line.strip_prefix("Progress ")?;
  let (current, total) = rest.split_once(" of ")?;
  let current = current.trim().parse::<u64>().ok()?;
  let total = total.trim().parse::<u64>().ok()?;
  Some((current, total))
}

fn collecting_name(line: &str) -> Option<String> {
  let rest = line.strip_prefix("Collecting ")?;
  let name = rest
    .split(|ch: char| ch.is_whitespace() || matches!(ch, '(' | ';' | '['))
    .next()
    .unwrap_or("")
    .trim();
  if name.is_empty() { None } else { Some(name.to_string()) }
}

fn installing_names(line: &str) -> Option<String> {
  let rest = line.strip_prefix("Installing collected packages:")?;
  let names: Vec<&str> = rest.split(',').map(str::trim).filter(|name| !name.is_empty()).collect();
  if names.is_empty() { None } else { Some(names.join(", ")) }
}

fn observe_pip_line(raw: &str) {
  let line = visible_pip_line(raw);
  if line.is_empty() {
    return;
  }
  let mut gate = install_lock();
  if !gate.running {
    return;
  }
  if let Some((current, total)) = parse_progress(&line) {
    if total > 0 {
      let percent = ((current.saturating_mul(100)) / total).min(100) as u8;
      gate.percent = Some(percent);
    }
    return;
  }
  if let Some(name) = collecting_name(&line) {
    gate.package = clip_chars(&name, 80);
    gate.percent = None;
  } else if let Some(name) = installing_names(&line) {
    gate.package = clip_chars(&name, 80);
    gate.percent = None;
  }
  if gate.lines.len() >= 80 {
    gate.lines.remove(0);
  }
  gate.lines.push(clip_chars(&line, 220));
}

fn distribution_name(spec: &str) -> &str {
  spec
    .split(['=', '>', '<', '!', '~', '[', ' ', ';'])
    .next()
    .unwrap_or(spec)
    .trim()
}

fn read_pipe_lines<R: std::io::Read>(reader: R, is_err: bool, tx: std::sync::mpsc::Sender<(bool, String)>) {
  let mut reader = std::io::BufReader::new(reader);
  let mut buf = String::new();
  loop {
    buf.clear();
    match std::io::BufRead::read_line(&mut reader, &mut buf) {
      Ok(0) => break,
      Ok(_) => {
        if tx.send((is_err, buf.clone())).is_err() {
          break;
        }
      }
      Err(_) => break,
    }
  }
}

fn append_captured_line(buf: &mut Vec<u8>, line: &str) {
  if buf.len() > 64_000 {
    return;
  }
  buf.extend_from_slice(line.as_bytes());
}

fn run_python_blocking(python: &std::path::Path, args: &[String]) -> Result<std::process::Output, String> {
  let mut cmd = std::process::Command::new(python);
  cmd
    .args(args)
    .stdin(std::process::Stdio::null())
    .stdout(std::process::Stdio::piped())
    .stderr(std::process::Stdio::piped());
  with_python_env(&mut cmd, python);
  hidden(&mut cmd);
  cmd.output().map_err(|err| format!("This Python did not run: {err}"))
}

fn run_python_tracked(python: &std::path::Path, args: &[String], pip_log: bool) -> Result<std::process::Output, String> {
  if install_cancelled() {
    return Err(INSTALL_CANCELLED.into());
  }
  let mut cmd = std::process::Command::new(python);
  cmd
    .args(args)
    .stdin(std::process::Stdio::null())
    .stdout(std::process::Stdio::piped())
    .stderr(std::process::Stdio::piped());
  with_python_env(&mut cmd, python);
  if pip_log {
    cmd.env("PYTHONUNBUFFERED", "1");
    cmd.env("PIP_PROGRESS_BAR", "raw");
  }
  hidden(&mut cmd);
  let mut child = cmd.spawn().map_err(|err| format!("This Python did not run: {err}"))?;
  if !remember_install_pid(child.id()) {
    force_stop_child(&mut child);
    return Err(INSTALL_CANCELLED.into());
  }
  let stdout = child.stdout.take().ok_or_else(|| "This Python did not run: no stdout".to_string())?;
  let stderr = child.stderr.take().ok_or_else(|| "This Python did not run: no stderr".to_string())?;
  let (tx, rx) = std::sync::mpsc::channel::<(bool, String)>();
  let tx_err = tx.clone();
  let out_thread = std::thread::spawn(move || read_pipe_lines(stdout, false, tx));
  let err_thread = std::thread::spawn(move || read_pipe_lines(stderr, true, tx_err));

  let mut out_buf = Vec::new();
  let mut err_buf = Vec::new();
  let status = loop {
    if install_cancelled() {
      force_stop_child(&mut child);
      let _ = out_thread.join();
      let _ = err_thread.join();
      return Err(INSTALL_CANCELLED.into());
    }
    match rx.recv_timeout(std::time::Duration::from_millis(200)) {
      Ok((is_err, line)) => {
        append_captured_line(if is_err { &mut err_buf } else { &mut out_buf }, &line);
        if pip_log {
          observe_pip_line(&line);
        }
      }
      Err(std::sync::mpsc::RecvTimeoutError::Timeout) => match child.try_wait() {
        Ok(Some(status)) => break status,
        Ok(None) => {}
        Err(err) => {
          forget_install_pid(child.id());
          let _ = out_thread.join();
          let _ = err_thread.join();
          return Err(format!("Could not check the installer: {err}"));
        }
      },
      Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
        break child.wait().map_err(|err| {
          forget_install_pid(child.id());
          format!("Could not check the installer: {err}")
        })?;
      }
    }
  };
  forget_install_pid(child.id());
  let _ = out_thread.join();
  let _ = err_thread.join();
  while let Ok((is_err, line)) = rx.try_recv() {
    append_captured_line(if is_err { &mut err_buf } else { &mut out_buf }, &line);
    if pip_log {
      observe_pip_line(&line);
    }
  }
  if install_cancelled() {
    return Err(INSTALL_CANCELLED.into());
  }
  Ok(std::process::Output {
    status,
    stdout: out_buf,
    stderr: err_buf,
  })
}

fn run_python(python: &std::path::Path, args: &[String]) -> Result<std::process::Output, String> {
  if install_running() {
    run_python_tracked(python, args, false)
  } else {
    run_python_blocking(python, args)
  }
}

fn output_text(bytes: &[u8]) -> String {
  String::from_utf8_lossy(bytes).trim().to_string()
}

fn text_tail(text: &str, max: usize) -> String {
  let text = text.trim();
  if text.len() <= max {
    return text.to_string();
  }
  let mut start = text.len() - max;
  while start < text.len() && !text.is_char_boundary(start) {
    start += 1;
  }
  text[start..].trim().to_string()
}

fn command_error(prefix: &str, output: &std::process::Output) -> String {
  let mut detail = output_text(&output.stderr);
  if detail.is_empty() {
    detail = output_text(&output.stdout);
  }
  if detail.is_empty() {
    detail = format!("exit {}", output.status);
  }
  format!("{prefix} {}", text_tail(&detail, 1200))
}

const PROBE: &str = r#"
import json, sys
out = {"torch": None, "cuda": False, "mps": False, "missing": [], "pins": {}}
try:
    import torch
except Exception as exc:
    sys.stderr.write(
        "PyTorch is not installed in this Python (%s). Install GPU PyTorch in the conda env first. This app will not install or upgrade torch.\n" % exc
    )
    sys.exit(2)
out["torch"] = getattr(torch, "__version__", "")
out["pins"]["torch"] = out["torch"]
try:
    out["cuda"] = bool(torch.cuda.is_available())
except Exception:
    out["cuda"] = False
try:
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    out["mps"] = bool(mps is not None and mps.is_available())
except Exception:
    out["mps"] = False
for name in ("torchvision", "torchaudio", "e3nn"):
    try:
        mod = __import__(name)
        version = getattr(mod, "__version__", None)
        if version:
            out["pins"][name] = version
    except Exception:
        pass
for name in ("mace", "fastapi", "uvicorn", "pydantic", "numpy", "ase"):
    try:
        __import__(name)
    except Exception:
        out["missing"].append(name)
sys.stdout.write(json.dumps(out) + "\n")
"#;

fn probe_python(python: &std::path::Path) -> Result<Probe, String> {
  let output = run_python(python, &["-c".into(), PROBE.into()])?;
  if !output.status.success() {
    let err = command_error("This Python failed the PyTorch check.", &output);
    if output.status.code() == Some(2) {
      return Err(err);
    }
    return Err(err);
  }
  let stdout = String::from_utf8_lossy(&output.stdout);
  let line = stdout.lines().rev().find(|line| line.trim_start().starts_with('{')).unwrap_or("");
  if line.is_empty() {
    return Err("This Python did not report its PyTorch status.".into());
  }
  serde_json::from_str(line).map_err(|err| format!("This Python returned an unreadable status: {err}"))
}

fn pip_spec(import_name: &str) -> Option<&'static str> {
  // Same packages and floors as sidecar/requirements.txt. Never torch.
  match import_name {
    "mace" => Some("mace-torch>=0.3.14"),
    "fastapi" => Some("fastapi>=0.110"),
    "uvicorn" => Some("uvicorn[standard]>=0.27"),
    "pydantic" => Some("pydantic>=2"),
    "numpy" => Some("numpy>=1.26"),
    "ase" => Some("ase>=3.22"),
    _ => None,
  }
}

/// Exact pins matching scripts/build-mace-runtime.mjs (packed mace-runtime).
/// mace-torch is installed with --no-deps, so these must be installed explicitly.
fn companion_pins() -> &'static [(&'static str, &'static str)] {
  &[("e3nn", "0.4.4")]
}

fn companion_pin_version(module: &str) -> Option<&'static str> {
  companion_pins()
    .iter()
    .find(|(name, _)| *name == module)
    .map(|(_, version)| *version)
}

fn normalize_pin_version(version: &str) -> &str {
  version.split('+').next().unwrap_or(version).trim()
}

fn pin_satisfied(probe: &Probe, name: &str, required: &str) -> bool {
  probe
    .pins
    .get(name)
    .map(|current| normalize_pin_version(current) == required)
    .unwrap_or(false)
}

fn pin_change_for(name: &str, required: &str, current: Option<&str>) -> PinChange {
  let message = match current {
    Some(cur) => format!(
      "MACE in this app needs {name} {required}; yours is {cur}. Install will change it to {required}."
    ),
    None => format!(
      "MACE in this app needs {name} {required}; it is not installed. Install will set it to {required}."
    ),
  };
  PinChange {
    name: name.into(),
    required: required.into(),
    current: current.map(|value| value.to_string()),
    message,
  }
}

fn pin_changes(probe: &Probe) -> Vec<PinChange> {
  companion_pins()
    .iter()
    .filter_map(|(name, required)| {
      if pin_satisfied(probe, name, required) {
        return None;
      }
      let current = probe.pins.get(*name).map(|value| normalize_pin_version(value));
      Some(pin_change_for(name, required, current))
    })
    .collect()
}

fn install_companion_pins(python: &std::path::Path) -> Result<(), String> {
  let probe = probe_python(python)?;
  let mut specs: Vec<String> = Vec::new();
  for (name, version) in companion_pins() {
    if pin_satisfied(&probe, name, version) {
      continue;
    }
    let spec = format!("{name}=={version}");
    assert_not_torch(&spec)?;
    specs.push(spec);
  }
  if specs.is_empty() {
    return Ok(());
  }
  // Install with deps: e3nn needs opt_einsum and friends. Never torch.
  pip_install(python, &specs, false)
}

fn assert_not_torch(spec: &str) -> Result<(), String> {
  let name = spec.split(['=', '>', '<', '[', ' ']).next().unwrap_or(spec);
  if name == "torch" || name == "torchvision" || name == "torchaudio" {
    return Err("Refusing to install or upgrade torch.".into());
  }
  Ok(())
}

fn pip_refused_progress_bar(output: &std::process::Output) -> bool {
  let mut detail = String::from_utf8_lossy(&output.stderr).to_string();
  detail.push_str(&String::from_utf8_lossy(&output.stdout));
  let detail = detail.to_lowercase();
  detail.contains("progress-bar")
    && (detail.contains("no such option") || detail.contains("unrecognized arguments") || detail.contains("unrecognized option"))
}

fn pip_install(python: &std::path::Path, specs: &[String], no_deps: bool) -> Result<(), String> {
  if install_cancelled() {
    return Err(INSTALL_CANCELLED.into());
  }
  if specs.is_empty() {
    return Ok(());
  }
  for spec in specs {
    assert_not_torch(spec)?;
  }
  let run = |specs: &[String], no_deps: bool, progress_bar: bool| -> Result<std::process::Output, String> {
    let mut args = vec![
      "-m".into(),
      "pip".into(),
      "install".into(),
      "--disable-pip-version-check".into(),
      "--no-input".into(),
      "--upgrade-strategy".into(),
      "only-if-needed".into(),
    ];
    if progress_bar {
      // "raw" prints "Progress <bytes> of <total>" even when pip is not attached to a terminal.
      args.push("--progress-bar".into());
      args.push("raw".into());
    }
    if no_deps {
      // mace-torch depends on torch. --no-deps installs MACE without fetching or upgrading torch.
      args.push("--no-deps".into());
    }
    args.extend(specs.iter().cloned());
    let label = specs
      .iter()
      .map(|spec| distribution_name(spec))
      .filter(|name| !name.is_empty())
      .collect::<Vec<_>>()
      .join(", ");
    if !label.is_empty() {
      set_install_label(&label);
    }
    if install_running() {
      run_python_tracked(python, &args, true)
    } else {
      run_python_blocking(python, &args)
    }
  };
  let output = run(specs, no_deps, true)?;
  if !output.status.success() && pip_refused_progress_bar(&output) {
    let output = run(specs, no_deps, false)?;
    if output.status.success() {
      return Ok(());
    }
    if install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    return Err(command_error("pip install failed. Torch was not changed.", &output));
  }
  if output.status.success() {
    return Ok(());
  }
  if install_cancelled() {
    return Err(INSTALL_CANCELLED.into());
  }
  if specs.iter().any(|spec| spec.contains("uvicorn[standard]")) {
    let plain: Vec<String> = specs
      .iter()
      .map(|spec| {
        if spec.contains("uvicorn[standard]") {
          "uvicorn>=0.27".into()
        } else {
          spec.clone()
        }
      })
      .collect();
    let retry = run(&plain, no_deps, true)?;
    if retry.status.success() {
      return Ok(());
    }
    if install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    return Err(command_error("pip install failed. Torch was not changed.", &retry));
  }
  Err(command_error("pip install failed. Torch was not changed.", &output))
}

fn map_distribution(module: &str) -> String {
  match module {
    "yaml" => "pyyaml".into(),
    "git" => "GitPython".into(),
    "cv2" => "opencv-python".into(),
    "sklearn" => "scikit-learn".into(),
    "torch_ema" => "torch-ema".into(),
    other => other.to_string(),
  }
}

fn fill_mace_deps(python: &std::path::Path) -> Result<(), String> {
  let script = r#"
import sys
try:
    import mace
    from mace.calculators import MACECalculator
except ModuleNotFoundError as exc:
    name = (getattr(exc, "name", None) or "").split(".")[0]
    sys.stdout.write(name)
    sys.exit(3)
except Exception as exc:
    sys.stderr.write(str(exc))
    sys.exit(4)
sys.exit(0)
"#;
  let mut seen: Vec<String> = Vec::new();
  for _ in 0..15 {
    let output = run_python(python, &["-c".into(), script.into()])?;
    if output.status.success() {
      return Ok(());
    }
    if output.status.code() != Some(3) {
      return Err(command_error("mace-torch did not import. Torch was not changed.", &output));
    }
    // Import-time warnings may be printed before the missing module name.
    // The probe writes the name last, so only use the last non-empty stdout line.
    let module = String::from_utf8_lossy(&output.stdout)
      .lines()
      .rev()
      .map(str::trim)
      .find(|line| !line.is_empty())
      .unwrap_or("")
      .to_string();
    if module == "mace" || module == "torch" || module == "torchvision" || module == "torchaudio" {
      return Err("mace-torch did not import, and this app will not install or upgrade torch. Torch was not changed.".into());
    }
    if module.is_empty() || !module.chars().all(|ch| ch.is_ascii_alphanumeric() || ch == '_') {
      return Err("mace-torch is missing a dependency whose name could not be installed. Torch was not changed.".into());
    }
    if seen.iter().any(|item| item == &module) {
      return Err(format!("pip could not provide {module} for mace-torch. Torch was not changed."));
    }
    seen.push(module.clone());
    let dist = map_distribution(&module);
    let package = match companion_pin_version(&module) {
      Some(version) => format!("{dist}=={version}"),
      None => dist,
    };
    assert_not_torch(&package)?;
    if install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    // Companions with exact pins install with deps; other fill-ins stay --no-deps.
    let no_deps = companion_pin_version(&module).is_none();
    pip_install(python, &[package], no_deps)?;
  }
  Err("mace-torch still has missing dependencies. Torch was not changed.".into())
}

fn required_missing(probe: &Probe) -> Vec<String> {
  probe
    .missing
    .iter()
    .filter(|name| pip_spec(name).is_some())
    .cloned()
    .collect()
}

fn validate_user_python(app: &tauri::AppHandle, python_path: &str) -> Result<(String, std::path::PathBuf), String> {
  let python_path = clean_python_path(python_path);
  if python_path.is_empty() {
    return Err("Choose python.exe inside the conda env, for example C:\\Users\\...\\anaconda3\\envs\\qdspace-user\\python.exe.".into());
  }
  let python = std::path::PathBuf::from(&python_path);
  if !python.is_file() {
    return Err(format!(
      "Python was not found at {}. Choose python.exe inside the conda env.",
      python.display()
    ));
  }
  if python.file_name().and_then(|name| name.to_str()).unwrap_or("").eq_ignore_ascii_case("pythonw.exe") {
    return Err("Choose python.exe, not pythonw.exe.".into());
  }
  if is_bundled_python(app, &python) || looks_like_bundled_runtime(&python) {
    return Err("That is the built-in CPU runtime. Choose python.exe from your conda env instead.".into());
  }
  let check = run_python(&python, &["-c".into(), "import sys; print(sys.executable)".into()])?;
  if !check.status.success() {
    return Err(command_error("This Python did not run.", &check));
  }
  Ok((python_path, python))
}

fn check_user_python_impl(app: &tauri::AppHandle, python_path: &str) -> Result<PythonCheck, String> {
  let (python_path, python) = validate_user_python(app, python_path)?;
  let probe = probe_python(&python)?;
  let torch = probe.torch.clone().unwrap_or_default();
  if torch.is_empty() {
    return Err("PyTorch is not installed in this Python. Install GPU PyTorch in the conda env first. This app will not install or upgrade torch.".into());
  }
  Ok(PythonCheck {
    python: python_path,
    device: device_label(&probe).into(),
    torch,
    missing: required_missing(&probe),
    pin_changes: pin_changes(&probe),
  })
}

/// Installs only names the user confirmed that are still missing, plus pinned MACE companions
/// (e.g. e3nn==0.4.4). Never installs torch. mace-torch still uses --no-deps.
/// Returns whether mace-torch was installed by this call, plus a fresh probe.
fn install_confirmed(python: &std::path::Path, requested: &[String]) -> Result<(Probe, bool), String> {
  if install_cancelled() {
    return Err(INSTALL_CANCELLED.into());
  }
  let first = probe_python(python)?;
  let before = first.torch.clone().unwrap_or_default();
  if before.is_empty() {
    return Err("PyTorch is not installed in this Python. Install GPU PyTorch in the conda env first. This app will not install or upgrade torch.".into());
  }

  let mut seen = std::collections::BTreeSet::new();
  let mut specs: Vec<String> = Vec::new();
  let mut install_mace = false;
  let mut install_pins = false;
  for name in requested {
    let name = name.trim();
    if name.is_empty() || !seen.insert(name.to_string()) {
      continue;
    }
    if name == "torch" || name == "torchvision" || name == "torchaudio" {
      return Err("Refusing to install or upgrade torch.".into());
    }
    if companion_pin_version(name).is_some() {
      // e3nn (and other packed-runtime pins): install/change even when import already works.
      install_pins = true;
      continue;
    }
    if pip_spec(name).is_none() {
      return Err(format!("This app will not install {name}."));
    }
    if !first.missing.iter().any(|missing| missing == name) {
      continue;
    }
    if name == "mace" {
      install_mace = true;
      // mace-torch is --no-deps; always enforce companion pins alongside it.
      install_pins = true;
      continue;
    }
    let spec = pip_spec(name).unwrap();
    assert_not_torch(spec)?;
    specs.push(spec.to_string());
  }

  if !specs.is_empty() {
    if install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    pip_install(python, &specs, false)?;
  }
  if install_mace {
    if install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    // Package name from sidecar/requirements.txt. --no-deps keeps the env's torch.
    pip_install(python, &["mace-torch>=0.3.14".into()], true)?;
    if install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    // Pin e3nn before fill_mace_deps so a newer env e3nn is downgraded, not left in place.
    install_companion_pins(python)?;
    if install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    fill_mace_deps(python)?;
  } else if install_pins {
    if install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    install_companion_pins(python)?;
  }
  if install_cancelled() {
    return Err(INSTALL_CANCELLED.into());
  }

  let did_work = !specs.is_empty() || install_mace || install_pins;
  let probe = if did_work { probe_python(python)? } else { first };
  let after = probe.torch.clone().unwrap_or_default();
  if after != before {
    return Err(format!(
      "Torch changed from {before} to {after}. Predict was not switched to this Python."
    ));
  }
  let still = required_missing(&probe);
  if !still.is_empty() {
    return Err(format!(
      "This Python is still missing packages ({}). Torch was not changed.",
      still.join(", ")
    ));
  }
  let still_pins = pin_changes(&probe);
  if !still_pins.is_empty() {
    let detail = still_pins
      .iter()
      .map(|change| change.message.as_str())
      .collect::<Vec<_>>()
      .join(" ");
    return Err(format!(
      "Pinned MACE companions are still wrong ({detail}). Torch was not changed."
    ));
  }
  Ok((probe, install_mace))
}

fn switch_user_sidecar(app: &tauri::AppHandle, python: &std::path::Path, python_path: String, probe: &Probe, installed_mace: bool) -> Result<UserPythonInfo, String> {
  let torch = probe.torch.clone().unwrap_or_default();
  let workdir = sidecar_workdir(app)?;
  // Disarm the previous watcher before the kill, so that exit is not treated as a crash.
  bump_sidecar_generation();
  if let Err(err) = stop_port(SIDECAR_PORT) {
    return Err(err);
  }
  if let Err(err) = start_user_sidecar(app, python, &workdir) {
    restart_default_sidecar(app);
    return Err(err);
  }
  Ok(UserPythonInfo {
    python: python_path,
    device: device_label(probe).into(),
    torch,
    installed_mace,
  })
}

async fn off_ui_thread<T, F>(work: F) -> Result<T, String>
where
  T: Send + 'static,
  F: FnOnce() -> Result<T, String> + Send + 'static,
{
  match tauri::async_runtime::spawn_blocking(work).await {
    Ok(result) => result,
    Err(err) => Err(format!("The Python task stopped before it finished: {err}")),
  }
}

fn push_pid(pids: &mut Vec<u32>, pid: u32) {
  if pid > 4 && pid != std::process::id() && !pids.contains(&pid) {
    pids.push(pid);
  }
}

fn parse_pids(bytes: &[u8]) -> Vec<u32> {
  let mut pids = Vec::new();
  for token in String::from_utf8_lossy(bytes).split_whitespace() {
    if let Ok(pid) = token.trim().parse::<u32>() {
      push_pid(&mut pids, pid);
    }
  }
  pids
}

#[cfg(windows)]
fn netstat_listen_pids(port: u16) -> Vec<u32> {
  let mut cmd = std::process::Command::new("netstat");
  cmd.args(["-ano", "-p", "tcp"]);
  hidden(&mut cmd);
  let Ok(output) = cmd.output() else {
    return Vec::new();
  };
  let suffix = format!(":{port}");
  let mut pids = Vec::new();
  for line in String::from_utf8_lossy(&output.stdout).lines() {
    if !line.to_ascii_uppercase().contains("LISTENING") {
      continue;
    }
    let cols: Vec<&str> = line.split_whitespace().collect();
    let Some(local) = cols.get(1) else { continue; };
    if !local.ends_with(&suffix) {
      continue;
    }
    if let Some(pid) = cols.last().and_then(|value| value.parse::<u32>().ok()) {
      push_pid(&mut pids, pid);
    }
  }
  pids
}

fn listener_pids(port: u16) -> Result<Vec<u32>, String> {
  #[cfg(windows)]
  {
    let script = format!(
      "Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | ForEach-Object {{ $_.OwningProcess }}"
    );
    let mut cmd = std::process::Command::new("powershell.exe");
    cmd.args(["-NoProfile", "-NonInteractive", "-Command", &script]);
    hidden(&mut cmd);
    if let Ok(output) = cmd.output() {
      if output.status.success() {
        let pids = parse_pids(&output.stdout);
        if !pids.is_empty() {
          return Ok(pids);
        }
      }
    }
    return Ok(netstat_listen_pids(port));
  }
  #[cfg(not(windows))]
  {
    let mut cmd = std::process::Command::new("lsof");
    cmd.args(["-nP", &format!("-iTCP:{port}"), "-sTCP:LISTEN", "-t"]);
    hidden(&mut cmd);
    match cmd.output() {
      Ok(output) => Ok(parse_pids(&output.stdout)),
      Err(err) => Err(format!("Could not inspect port {port} ({err}). Stop the process using that port and try again.")),
    }
  }
}

fn kill_pid(pid: u32) {
  #[cfg(windows)]
  {
    let mut cmd = std::process::Command::new("taskkill");
    cmd.args(["/F", "/T", "/PID", &pid.to_string()]);
    hidden(&mut cmd);
    let _ = cmd.output();
  }
  #[cfg(not(windows))]
  {
    let mut cmd = std::process::Command::new("kill");
    cmd.arg(pid.to_string());
    hidden(&mut cmd);
    let _ = cmd.output();
    if listening(SIDECAR_PORT) {
      let mut force = std::process::Command::new("kill");
      force.args(["-9", &pid.to_string()]);
      hidden(&mut force);
      let _ = force.output();
    }
  }
}

fn stop_port(port: u16) -> Result<(), String> {
  if !listening(port) {
    return Ok(());
  }
  let pids = listener_pids(port)?;
  if pids.is_empty() {
    return Err(format!(
      "Port {port} is in use, but this app could not find that process. Close the other Predict engine and try again."
    ));
  }
  for pid in pids {
    kill_pid(pid);
  }
  for _ in 0..25 {
    if !listening(port) {
      return Ok(());
    }
    std::thread::sleep(std::time::Duration::from_millis(200));
  }
  Err(format!("Port {port} is still in use after stopping the previous engine."))
}

fn log_tail(path: &std::path::Path) -> String {
  let text = std::fs::read_to_string(path).unwrap_or_default();
  let text = text_tail(&text, 1200);
  if text.is_empty() {
    "No log was written. Check that this Python can import uvicorn, fastapi, and the sidecar.".into()
  } else {
    text
  }
}

struct SidecarWatch {
  generation: u64,
  failure: Option<String>,
}

static SIDECAR_WATCH: std::sync::Mutex<SidecarWatch> = std::sync::Mutex::new(SidecarWatch {
  generation: 0,
  failure: None,
});

static ENSURE_SERVER: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn sidecar_watch_lock() -> std::sync::MutexGuard<'static, SidecarWatch> {
  SIDECAR_WATCH.lock().unwrap_or_else(|err| err.into_inner())
}

fn bump_sidecar_generation() -> u64 {
  let mut gate = sidecar_watch_lock();
  gate.generation = gate.generation.wrapping_add(1);
  gate.failure = None;
  gate.generation
}

fn ensure_predict_server(app: &tauri::AppHandle) {
  let _hold = ENSURE_SERVER.lock().unwrap_or_else(|err| err.into_inner());
  for _ in 0..20 {
    if !listening(SIDECAR_PORT) {
      break;
    }
    std::thread::sleep(std::time::Duration::from_millis(100));
  }
  if !listening(SIDECAR_PORT) {
    restart_default_sidecar(app);
  }
}

fn watch_user_sidecar(app: tauri::AppHandle, mut child: std::process::Child, generation: u64, log_path: std::path::PathBuf) {
  let status = child.wait();
  let status_text = match status {
    Ok(status) => status.to_string(),
    Err(err) => err.to_string(),
  };
  let message = format!("Your Python stopped ({status_text}). {}", log_tail(&log_path));
  {
    let mut gate = sidecar_watch_lock();
    if gate.generation != generation {
      return;
    }
    gate.failure = Some(message);
  }
  ensure_predict_server(&app);
}

/// Last lines from a user Python that exited after a successful switch.
/// The watcher starts the bundled runtime again when it records that exit.
#[tauri::command]
fn take_sidecar_failure() -> Option<String> {
  sidecar_watch_lock().failure.take()
}

fn start_user_sidecar(app: &tauri::AppHandle, python: &std::path::Path, cwd: &std::path::Path) -> Result<(), String> {
  let log_path = std::env::temp_dir().join("qdspace-user-python-sidecar.log");
  let log_file = std::fs::File::create(&log_path).map_err(|err| format!("Could not log the sidecar: {err}"))?;
  let stdout = log_file.try_clone().map_err(|err| format!("Could not log the sidecar: {err}"))?;
  let mut cmd = std::process::Command::new(python);
  cmd
    .args(["-m", "uvicorn", "sidecar_app:app", "--host", "127.0.0.1", "--port", "8765"])
    .current_dir(cwd)
    .stdin(std::process::Stdio::null())
    .stdout(std::process::Stdio::from(stdout))
    .stderr(std::process::Stdio::from(log_file));
  with_python_env(&mut cmd, python);
  let sidecar_dir = cwd.to_string_lossy().to_string();
  let pythonpath = match std::env::var("PYTHONPATH") {
    Ok(old) if !old.trim().is_empty() => {
      let sep = if cfg!(windows) { ";" } else { ":" };
      format!("{sidecar_dir}{sep}{old}")
    }
    _ => sidecar_dir,
  };
  cmd.env("PYTHONPATH", pythonpath);
  cmd.env("PYTHONUNBUFFERED", "1");
  hidden(&mut cmd);
  let generation = bump_sidecar_generation();
  let mut child = cmd.spawn().map_err(|err| format!("Could not start the sidecar with this Python: {err}"))?;
  let mut opened = false;
  for _ in 0..180 {
    if listening(SIDECAR_PORT) {
      opened = true;
      break;
    }
    match child.try_wait() {
      Ok(Some(status)) => {
        return Err(format!(
          "The sidecar stopped before it opened port 8765 ({status}). {}",
          log_tail(&log_path)
        ));
      }
      Ok(None) => {}
      Err(err) => return Err(format!("Could not check the sidecar: {err}")),
    }
    std::thread::sleep(std::time::Duration::from_millis(500));
  }
  if opened {
    let app = app.clone();
    let log_path = log_path.clone();
    std::thread::spawn(move || watch_user_sidecar(app, child, generation, log_path));
    return Ok(());
  }
  let _ = child.kill();
  let _ = child.wait();
  Err(format!("The sidecar did not open port 8765. {}", log_tail(&log_path)))
}

fn device_label(probe: &Probe) -> &'static str {
  if probe.cuda {
    "GPU"
  } else if probe.mps {
    "MPS"
  } else {
    "CPU"
  }
}

#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn command_output_text(output: &std::process::Output) -> String {
  let mut text = output_text(&output.stdout);
  let err = output_text(&output.stderr);
  if !err.is_empty() {
    if !text.is_empty() {
      text.push('\n');
    }
    text.push_str(&err);
  }
  text
}

#[tauri::command]
fn pick_python_path() -> Result<Option<String>, String> {
  #[cfg(windows)]
  {
    return pick_python_path_windows();
  }
  #[cfg(target_os = "macos")]
  {
    return pick_python_path_macos();
  }
  #[cfg(all(unix, not(target_os = "macos")))]
  {
    return pick_python_path_linux();
  }
  #[cfg(not(any(windows, unix)))]
  {
    Err("Paste the path to python.exe. A file dialog is not available on this system.".into())
  }
}

#[cfg(windows)]
fn pick_python_path_windows() -> Result<Option<String>, String> {
  let script = r#"
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Select the conda environment Python'
$dialog.Filter = 'Python executable|python.exe;python;python3.exe|All files|*.*'
$dialog.CheckFileExists = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::Out.Write($dialog.FileName)
}
"#;
  let mut cmd = std::process::Command::new("powershell.exe");
  // WindowStyle hides the console only. CREATE_NO_WINDOW can keep the file dialog from appearing.
  cmd.args(["-NoProfile", "-STA", "-WindowStyle", "Hidden", "-Command", script]);
  let output = cmd.output().map_err(|err| format!("Could not open a file dialog: {err}"))?;
  if !output.status.success() {
    return Err(command_error("Could not open a file dialog.", &output));
  }
  let path = output_text(&output.stdout);
  if path.is_empty() {
    Ok(None)
  } else {
    Ok(Some(path))
  }
}

#[cfg(target_os = "macos")]
fn pick_python_path_macos() -> Result<Option<String>, String> {
  let mut cmd = std::process::Command::new("osascript");
  cmd.args(["-e", "POSIX path of (choose file with prompt \"Select the conda environment Python\")"]);
  hidden(&mut cmd);
  let output = cmd.output().map_err(|err| format!("Could not open a file dialog: {err}"))?;
  if !output.status.success() {
    let detail = command_output_text(&output).to_lowercase();
    if detail.contains("cancel") || detail.contains("-128") {
      return Ok(None);
    }
    return Err(command_error("Could not open a file dialog.", &output));
  }
  let path = output_text(&output.stdout);
  if path.is_empty() { Ok(None) } else { Ok(Some(path)) }
}

#[cfg(all(unix, not(target_os = "macos")))]
fn pick_python_path_linux() -> Result<Option<String>, String> {
  let mut cmd = std::process::Command::new("zenity");
  cmd.args(["--file-selection", "--title=Select the conda environment Python"]);
  hidden(&mut cmd);
  match cmd.output() {
    Ok(output) if output.status.success() => {
      let path = output_text(&output.stdout);
      if path.is_empty() { Ok(None) } else { Ok(Some(path)) }
    }
    Ok(output) if output.status.code() == Some(1) => Ok(None),
    Ok(output) => Err(command_error("Could not open a file dialog. Paste the Python path instead.", &output)),
    Err(_) => Err("Paste the path to the conda environment Python. A file dialog is not available.".into()),
  }
}

/// Check torch, CUDA, and which sidecar libraries are missing. Does not install or restart the sidecar.
#[tauri::command]
async fn check_user_python(app: tauri::AppHandle, python_path: String) -> Result<PythonCheck, String> {
  off_ui_thread(move || check_user_python_impl(&app, &python_path)).await
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct PythonInstallStatus {
  running: bool,
  package: String,
  percent: Option<u8>,
  lines: Vec<String>,
}

/// Stop the pip process for the install that is running. Does not start the sidecar.
#[tauri::command]
fn cancel_python_install() -> Result<(), String> {
  let pid = {
    let mut gate = install_lock();
    gate.cancel = true;
    gate.pid.take()
  };
  if let Some(pid) = pid {
    kill_install_pid(pid);
  }
  Ok(())
}

/// Latest pip progress. Percent is set only when pip reports bytes downloaded out of a known total.
#[tauri::command]
fn python_install_status() -> PythonInstallStatus {
  let gate = install_lock();
  PythonInstallStatus {
    running: gate.running,
    package: gate.package.clone(),
    percent: gate.percent,
    lines: gate.lines.clone(),
  }
}

/// Install only the confirmed missing libraries into this interpreter, then start the sidecar on port 8765.
/// An empty list installs nothing and only switches the sidecar when the check already passed.
/// Cancelled installs return before the sidecar is switched.
#[tauri::command]
async fn apply_user_python(app: tauri::AppHandle, python_path: String, packages: Vec<String>) -> Result<UserPythonInfo, String> {
  let installing = !packages.is_empty();
  if installing {
    begin_install_session();
  }
  let outcome = off_ui_thread(move || {
    if installing && install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    let (python_path, python) = validate_user_python(&app, &python_path)?;
    let (probe, installed_mace) = install_confirmed(&python, &packages)?;
    if installing && install_cancelled() {
      return Err(INSTALL_CANCELLED.into());
    }
    switch_user_sidecar(&app, &python, python_path, &probe, installed_mace)
  })
  .await;
  if installing {
    end_install_session();
  }
  outcome
}

// ---------------------------------------------------------------------------
// Library file cache: structures / MD / plots downloaded on demand from the public
// QDSpace site are stored under <app data>/library-cache/<relative library path>.
// The webview does the HTTP fetch (CORS is open); Rust only reads and writes files.

const LIBRARY_CACHE_DIR: &str = "library-cache";

fn library_cache_root(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
  let base = app.path().app_data_dir().map_err(|e| format!("app data dir unavailable: {e}"))?;
  Ok(base.join(LIBRARY_CACHE_DIR))
}

fn windows_reserved_name(part: &str) -> bool {
  let stem = part.split('.').next().unwrap_or("").to_ascii_uppercase();
  matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
    || ((stem.starts_with("COM") || stem.starts_with("LPT"))
      && stem.len() == 4
      && stem.as_bytes()[3].is_ascii_digit())
}

/// Map a library-relative path (e.g. "II-VI/CdSe/.../relaxed.xyz") into the cache dir.
/// Rejects absolute paths, "..", drive letters and unexpected characters.
fn library_cache_file(app: &tauri::AppHandle, rel: &str) -> Result<std::path::PathBuf, String> {
  let rel = rel.trim().trim_start_matches('/');
  if rel.is_empty() || rel.len() > 400 {
    return Err(format!("invalid library path: {rel}"));
  }
  let mut path = library_cache_root(app)?;
  for part in rel.split('/') {
    let ok_chars = part
      .chars()
      .all(|c| c.is_ascii_alphanumeric() || "-_.@[]+=,()".contains(c));
    if part.is_empty()
      || part == "."
      || part == ".."
      || !ok_chars
      || part.ends_with('.')
      || part.ends_with(".part")
      || windows_reserved_name(part)
    {
      return Err(format!("invalid library path: {rel}"));
    }
    path.push(part);
  }
  Ok(path)
}

/// Cached file bytes (raw IPC response -> ArrayBuffer in JS). Err("not cached") if absent.
#[tauri::command]
async fn library_cache_read(app: tauri::AppHandle, path: String) -> Result<tauri::ipc::Response, String> {
  let file = library_cache_file(&app, &path)?;
  match std::fs::read(&file) {
    Ok(bytes) => Ok(tauri::ipc::Response::new(bytes)),
    Err(e) if e.kind() == std::io::ErrorKind::NotFound => Err("not cached".into()),
    Err(e) => Err(format!("could not read {}: {e}", file.display())),
  }
}

/// Save a downloaded library file (written to "<name>.part", then renamed).
#[tauri::command]
async fn library_cache_write(app: tauri::AppHandle, path: String, contents: String) -> Result<u64, String> {
  let file = library_cache_file(&app, &path)?;
  if let Some(parent) = file.parent() {
    std::fs::create_dir_all(parent).map_err(|e| format!("could not create {}: {e}", parent.display()))?;
  }
  let name = file.file_name().and_then(|n| n.to_str()).unwrap_or("file");
  let tmp = file.with_file_name(format!("{name}.part"));
  std::fs::write(&tmp, contents.as_bytes()).map_err(|e| format!("could not write {}: {e}", tmp.display()))?;
  if let Err(e) = std::fs::rename(&tmp, &file) {
    let _ = std::fs::remove_file(&tmp);
    return Err(format!("could not save {}: {e}", file.display()));
  }
  Ok(contents.len() as u64)
}

/// Size of each cached file, None where not cached (or the path is invalid).
#[tauri::command]
async fn library_cache_stat(app: tauri::AppHandle, paths: Vec<String>) -> Vec<Option<u64>> {
  paths
    .iter()
    .map(|p| {
      library_cache_file(&app, p)
        .ok()
        .and_then(|f| std::fs::metadata(f).ok())
        .filter(|m| m.is_file())
        .map(|m| m.len())
    })
    .collect()
}

#[tauri::command]
fn library_cache_dir(app: tauri::AppHandle) -> Result<String, String> {
  Ok(library_cache_root(&app)?.display().to_string())
}
