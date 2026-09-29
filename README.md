# QDSpace Desktop

Tauri desktop app for QDSpace: the Svelte interface, a local MACE sidecar for energy and forces, and a Builder that talks to a local Docker API.

## Layout

- `src/` is the Svelte interface, including Library, Builder, and Predict.
- `src-tauri/` is the native window.
- `sidecar/` is the FastAPI MACE service on port 8765.
- `public/` is the library catalog and the small builder CIF templates. The full structure library is not in this repo. The app can download a structure from the public site when it is needed.
- `scripts/` stages the installer catalog and starts the sidecar.

The MACE checkpoint is not in git. Place `2024-01-07-mace-128-L2_epoch-199.model` in `sidecar/models/` before running Predict.

## Prerequisites

- Node.js 20 or newer
- Rust stable, from https://rustup.rs
- WebView2 on Windows
- Python 3.10 or newer for the sidecar
- Visual Studio Build Tools with the C++ workload, on Windows
- Docker, only if you use Builder

## Develop

```powershell
npm install
npm run sidecar
npm run tauri:dev
```

Run the sidecar in one terminal and the desktop window in another. Builder also needs the Docker image `qdspace-builder` listening on port 8000.

## Installer

```powershell
npm run tauri:build
```

On Windows the setup file is written to `src-tauri\target\release\bundle\nsis\`. That installer is published on the GitHub release. It is not committed to the repo.

## Predict

`POST http://127.0.0.1:8765/predict` with `symbols` and `positions`. The response has `energy` in eV and `forces` in eV/Å. See `sidecar/predict_contract.md`.
