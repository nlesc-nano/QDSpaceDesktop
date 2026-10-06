"""QDSpace Desktop Builder service (no Docker).

Desktop-minimal copy of QDSpaceWebApp backend/app.py. It mounts only the
QD_Builder API at /builder, so the Svelte Builder keeps calling
  http://127.0.0.1:8000/builder/api/analyze_cif
  http://127.0.0.1:8000/builder/api/build_stream
The library API (/api, boto3/S3/plotly) and the SPA static files are left out.

Launch (cwd = this folder, or builder-runtime/app in a packed build):
  python -m uvicorn builder_app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import os

# Headless: pymatgen/ase may pull in matplotlib; never open a GUI backend.
os.environ.setdefault("MPLBACKEND", "Agg")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import api_builder as builder_api  # vendored QDSpaceWebApp backend/api_builder.py

app = FastAPI(title="QDSpace Desktop Builder")

# The desktop window loads from http://localhost:5173 (tauri dev),
# tauri://localhost (macOS/Linux) or http://tauri.localhost (Windows).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "qdspace-builder"}


app.mount("/builder", builder_api.app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("QDSPACE_BUILDER_PORT", "8000")))
