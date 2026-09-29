# QDSpace Desktop

Local-only **Tauri v2** desktop shell around the QDSpace Vite/Svelte web app, plus a **MACE-MP-0 large** FastAPI sidecar for on-device energy/forces prediction.

> **No-push policy:** Do not `git push`, open PRs, or write to any remote. Local commits on this machine are optional. Deliver by copying this folder to Windows (`C:\Users\zainul.abideen\Downloads\Desktop App`).

## Architecture

```
QDSpaceDesktop/
├── src/                 # Vite + Svelte 5 UI (from QDSpaceWebApp qd-frontend)
│   ├── Builder.svelte   # Full existing builder (unchanged behaviour)
│   ├── Predict.svelte   # Desktop-only Predict Properties page
│   └── lib/desktop.js   # Feature gate + sidecar URL
├── src-tauri/           # Tauri v2 Rust shell
├── sidecar/             # FastAPI + MACE CPU (port 8765)
│   ├── sidecar_app.py
│   ├── models/*.model   # ~61 MB checkpoint
│   └── predict_contract.md
├── Dockerfile           # Web UI + sidecar smoke test (not full Tauri)
├── docker-compose.yml
└── upstream/            # Original repo backend/docs (reference only)
```

| Layer | Role |
|-------|------|
| **Frontend** | Existing QDSpace builder/library UI. `Predict` nav appears only when `VITE_APP_TARGET=desktop` or Tauri env/`__TAURI__` is set. |
| **Tauri** | Native window (WebView2 on Windows). `npm run tauri:dev` / `tauri:build`. |
| **Sidecar** | `POST http://127.0.0.1:8765/predict` — CPU float32 MACE, lazy load. |

Upstream web stack (brief): **Svelte 5 + Vite 7**, hand-rolled `currentRoute` navigation (no SvelteKit), Tailwind via CDN, `matterviz` viewer, optional `/api` proxy to FastAPI on `:8000`.

## Prerequisites (Windows)

1. **Node.js** 20+ (22 recommended) and npm  
2. **Rust** stable (`rustup`) — [https://rustup.rs](https://rustup.rs)  
3. **WebView2** Runtime (usually preinstalled on Win10/11)  
4. **Python** 3.10+ for the MACE sidecar  
5. Visual Studio Build Tools (C++ workload) for compiling Tauri on Windows  

Linux also needs WebKitGTK / related packages (see Tauri docs). This box may lack full GUI libs for `tauri build`.

## Run on Windows (native Tauri)

```powershell
cd "C:\Users\zainul.abideen\Downloads\Desktop App"

# 1) Frontend deps
npm install

# 2) Sidecar (separate terminal) — first run installs torch+mace (large)
npm run sidecar
# Or manually:
#   cd sidecar
#   python -m venv .venv
#   .\.venv\Scripts\activate
#   pip install torch --index-url https://download.pytorch.org/whl/cpu
#   pip install -r requirements.txt
#   uvicorn sidecar_app:app --host 127.0.0.1 --port 8765

# 3) Desktop app
npm run tauri:dev
```

Production installer:

```powershell
npm run tauri:build
# Artifacts under src-tauri\target\release\bundle\
```

### Sidecar without npm script

See [sidecar/README.md](./sidecar/README.md). Ensure `sidecar/models/2024-01-07-mace-128-L2_epoch-199.model` exists (~61 MB).

## Docker smoke test (UI + API, no Tauri window)

Full Tauri-in-Docker is awkward; Compose covers **Vite (desktop flag) + sidecar**:

```bash
docker compose up --build
# Browser: http://localhost:5173  — Predict tab visible
# API:     http://localhost:8765/docs
```

## Scripts

| Script | Purpose |
|--------|---------|
| `npm run dev` | Plain web Vite (no Predict nav) |
| `npm run dev:desktop` | Vite with `VITE_APP_TARGET=desktop` |
| `npm run tauri:dev` | Tauri + desktop Vite |
| `npm run tauri:build` | Native installer build |
| `npm run sidecar` | Start MACE FastAPI on `:8765` |

## Predict API (summary)

```json
POST /predict
{
  "symbols": ["O","H","H"],
  "positions": [[0,0,0],[0.757,0.586,0],[-0.757,0.586,0]],
  "pbc": false
}
```

Returns `energy` (eV), `forces` (eV/Å), `latency_ms`, optional `cold_load_s`. Full contract: `sidecar/predict_contract.md`.

## Status

See [DESKTOP_STATUS.md](./DESKTOP_STATUS.md) for what was verified on the build box and known gaps.
