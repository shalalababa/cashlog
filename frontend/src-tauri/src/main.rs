// Cashlog desktop shell.
//
// The desktop app is intentionally thin: on startup it launches the same local
// FastAPI backend used in web/dev mode and points the webview at it. The
// backend is bundled as a self-contained PyInstaller sidecar (`cashlog-backend`,
// an externalBin installed next to this exe); in a source checkout we fall back
// to running `python -m scripts.serve`.
//
// The backend resolves its database, JSON mirror and xlsx paths from
// `cashlog.config`. The installed (frozen) backend defaults to a per-user data
// dir (`%LOCALAPPDATA%\Cashlog` on Windows), and all three are overridable via
// CASHLOG_DB / CASHLOG_DATA_DIR / CASHLOG_WORKBOOK — so the desktop build can be
// pointed at the very same SQLite / JSON / xlsx files as the browser version,
// satisfying the P6 acceptance "桌面版能读写同一 SQLite/JSON/xlsx 路径".
//
// Port: we bind a free ephemeral port and hand it to the backend (CASHLOG_PORT)
// rather than hard-coding 8000, so the app never collides with — or, worse,
// renders — some other local service. Setting CASHLOG_PORT pins a fixed port
// (and lets a dev attach the shell to an already-running server).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// Handle to the backend we spawned (if any), so we can stop it when the app
/// exits. `None` means we did not start it (already running, or not found).
struct BackendProcess(Mutex<Option<Child>>);

/// Resolve the port the backend should serve on.
///
/// Returns `(port, pinned)`. `CASHLOG_PORT` pins a fixed port (`pinned = true`,
/// which also enables attaching to an already-running server). Otherwise we ask
/// the OS for a free ephemeral port so the app never clashes with another local
/// service on a well-known port.
fn resolve_port() -> (u16, bool) {
    if let Ok(raw) = std::env::var("CASHLOG_PORT") {
        if let Ok(n) = raw.trim().parse::<u16>() {
            if n != 0 {
                return (n, true);
            }
        }
    }
    let port = TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8000);
    (port, false)
}

/// Locate the backend directory (the one containing `scripts/serve.py`).
///
/// Honours `CASHLOG_BACKEND_DIR`; otherwise probes paths relative to both the
/// executable and the current working directory, so it works whether launched
/// by `tauri dev` (cwd = src-tauri) or as the built exe (under target/…).
fn resolve_backend_dir() -> Option<PathBuf> {
    if let Ok(dir) = std::env::var("CASHLOG_BACKEND_DIR") {
        return Some(PathBuf::from(dir));
    }
    let mut bases: Vec<PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            bases.push(parent.to_path_buf());
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        bases.push(cwd);
    }
    // Relative hops from a base up to the repo's backend/ dir.
    const RELS: [&str; 6] = [
        "backend",
        "../backend",
        "../../backend",
        "../../../backend",
        "../../../../backend",
        "../../../../../backend",
    ];
    for base in &bases {
        for rel in RELS {
            let cand = base.join(rel);
            if cand.join("scripts").join("serve.py").exists() {
                return Some(cand);
            }
        }
    }
    None
}

/// Keep a spawned child from flashing a console window on Windows. No-op
/// elsewhere.
fn quiet(cmd: &mut Command) {
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(not(windows))]
    let _ = cmd;
}

/// Locate the bundled backend sidecar. Tauri places an externalBin next to the
/// app executable at install time (target-triple suffix stripped), so we look
/// for `cashlog-backend[.exe]` beside our own exe. This is the path that makes
/// an *installed* app self-contained — no system Python required.
fn resolve_sidecar() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let name = if cfg!(target_os = "windows") {
        "cashlog-backend.exe"
    } else {
        "cashlog-backend"
    };
    let cand = dir.join(name);
    if cand.exists() {
        Some(cand)
    } else {
        None
    }
}

fn spawn_sidecar(path: &Path, port: u16) -> Option<Child> {
    let mut cmd = Command::new(path);
    cmd.env("CASHLOG_PORT", port.to_string());
    quiet(&mut cmd);
    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("cashlog: failed to start bundled backend sidecar ({e})");
            None
        }
    }
}

/// Dev fallback: run `scripts.serve` from a source checkout via system Python.
fn spawn_backend(dir: &Path, port: u16) -> Option<Child> {
    let python = if cfg!(target_os = "windows") { "python" } else { "python3" };
    let mut cmd = Command::new(python);
    cmd.args(["-m", "scripts.serve"])
        .current_dir(dir)
        .env("CASHLOG_PORT", port.to_string());
    quiet(&mut cmd);
    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("cashlog: failed to start backend ({e}); is Python installed?");
            None
        }
    }
}

/// Start the backend: prefer the bundled sidecar (installed app), otherwise run
/// from a source checkout (dev). Returns the child we spawned, if any.
fn start_backend(port: u16) -> Option<Child> {
    if let Some(sidecar) = resolve_sidecar() {
        return spawn_sidecar(&sidecar, port);
    }
    match resolve_backend_dir() {
        Some(dir) => spawn_backend(&dir, port),
        None => {
            eprintln!(
                "cashlog: no bundled sidecar and could not locate a source backend; \
                 start it manually (cd backend && python -m scripts.serve) or set \
                 CASHLOG_BACKEND_DIR"
            );
            None
        }
    }
}

/// Probe the Cashlog backend's health endpoint on `port`.
///
/// Returns true only when it answers `GET /api/health` with a JSON body
/// containing `"ok": true`. A bare TCP connect is not enough: some *other* local
/// service could be listening on that port, and we must never render it as if it
/// were Cashlog. The body is tiny (`{"ok":true,"version":"…"}`), so a short
/// HTTP/1.0 request with `close` is all we need — no HTTP client dependency.
fn backend_health_ok(port: u16) -> bool {
    let mut stream = match TcpStream::connect(("127.0.0.1", port)) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let req = format!(
        "GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut resp = String::new();
    if stream.read_to_string(&mut resp).is_err() {
        return false;
    }
    // Tolerate any whitespace the server inserts between JSON tokens.
    let compact: String = resp.chars().filter(|c| !c.is_whitespace()).collect();
    compact.contains("\"ok\":true")
}

/// Block until the backend answers a healthy `/api/health` on `port`. Returns
/// `false` if it never does within ~10s, so the caller can fail closed instead
/// of pointing the window at a port we haven't confirmed is ours.
fn wait_for_backend(port: u16) -> bool {
    for _ in 0..50 {
        if backend_health_ok(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

fn main() {
    let (port, pinned) = resolve_port();

    // Attach to an already-running *Cashlog* server only when the port is pinned
    // (a dev convenience). On a fresh ephemeral port nothing is listening, so we
    // always spawn our own backend.
    let backend = if pinned && backend_health_ok(port) {
        None
    } else {
        start_backend(port)
    };

    // Fail closed: if the backend never reports healthy on our port (e.g. it
    // crashed, or a pinned port is held by a non-Cashlog service), do not open a
    // window onto it — that's exactly how a stranger's service would get
    // rendered. Stop any child we started and exit.
    if !wait_for_backend(port) {
        if let Some(mut child) = backend {
            let _ = child.kill();
        }
        eprintln!(
            "cashlog: backend did not become healthy on 127.0.0.1:{port}; refusing to \
             open the window. If you pinned CASHLOG_PORT, make sure it is free."
        );
        std::process::exit(1);
    }

    let url = format!("http://127.0.0.1:{port}");

    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(backend)))
        .setup(move |app| {
            // Build the window here so it points at the runtime-chosen port (the
            // static config can't carry a dynamic URL).
            let parsed: tauri::Url = url.parse().expect("backend url should be valid");
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(parsed))
                .title("Cashlog")
                .inner_size(1280.0, 860.0)
                .min_inner_size(980.0, 640.0)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Cashlog desktop app")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app.try_state::<BackendProcess>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
