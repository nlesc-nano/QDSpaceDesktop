# QDSpace Desktop

Tauri desktop app for QDSpace: the Svelte interface, a local MACE sidecar for energy and forces, and a local Builder service. Neither needs Docker.

## Layout

- `src/` is the Svelte interface, including Library, Builder, and Predict.
- `src-tauri/` is the native window.
- `sidecar/` is the FastAPI MACE service on port 8765.
- `builder-sidecar/` is the FastAPI Builder service on port 8000 (QD_Builder, pymatgen, RDKit). See `builder-sidecar/README.md`.
- `public/` is the library catalog and the small builder CIF templates. The full structure library is not in this repo. The app can download a structure from the public site when it is needed.
- `scripts/` stages the installer catalog and starts the sidecar.

The MACE checkpoint is not in git. Place `2024-01-07-mace-128-L2_epoch-199.model` in `sidecar/models/` before running Predict.

## Prerequisites

- Node.js 20 or newer
- Rust stable, from https://rustup.rs
- WebView2 on Windows
- Python 3.10 or newer for the sidecar
- Visual Studio Build Tools with the C++ workload, on Windows

## Develop

```powershell
npm install
npm run builder-runtime
npm run sidecar
npm run tauri:dev
```

Run the sidecar in one terminal and the desktop window in another. `npm run builder-runtime` builds the gitignored `builder-runtime/` folder once (portable Python with the Builder packages, about 0.6 GB). The app then starts Builder on `127.0.0.1:8000` by itself. Installers bundle the same folder, so users do not need Docker. If `builder-runtime/` is missing and `QDSPACE_ROOT` is set, the app falls back to the old `qdspace-builder` Docker image.

## Installer

```powershell
npm run tauri:build
```

Build `mace-runtime/` and `builder-runtime/` first (`npm run mace-runtime`, `npm run builder-runtime`) so the installer bundles both. On Windows the setup file is written to `src-tauri\target\release\bundle\nsis\`. That installer is published on the GitHub release. It is not committed to the repo.

## Predict

`POST http://127.0.0.1:8765/predict` with `symbols` and `positions`. The response has `energy` in eV and `forces` in eV/Å. See `sidecar/predict_contract.md`.
