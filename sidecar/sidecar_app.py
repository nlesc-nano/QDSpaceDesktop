#!/usr/bin/env python3
"""FastAPI runner for the Predict sidecar. MACE and NequIP live in their own files.

Run (from repo root):
  npm run sidecar

Or:
  cd sidecar && source .venv/bin/activate
  uvicorn sidecar_app:app --host 127.0.0.1 --port 8765

Model is lazy-loaded on the first /predict (or /health with ?warmup=true).
"""
from __future__ import annotations

import threading
import time
from io import StringIO
from pathlib import Path
from typing import Optional, Union

import numpy as np
from ase import Atoms
from ase.data import chemical_symbols
from ase.io import read as ase_read
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import mace_engine
import nequip_engine

ROOT = Path(__file__).resolve().parent
MODEL_PATH = mace_engine.DEFAULT_MODEL
MODEL_NAME = mace_engine.MODEL_NAME

app = FastAPI(title="QDSpace MACE sidecar", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_calcs = {}
_load_s: Optional[float] = None
_predict_cancel = threading.Event()


class PredictionCancelled(Exception):
    """Raised when the user cancels an in-flight prediction."""


def clear_predict_cancel() -> None:
    _predict_cancel.clear()


def request_predict_cancel() -> None:
    _predict_cancel.set()


def check_predict_cancel() -> None:
    if _predict_cancel.is_set():
        raise PredictionCancelled("Prediction cancelled")


class PredictRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1)
    positions: list[list[float]] = Field(..., min_length=1)
    cell: Optional[list[list[float]]] = None
    pbc: Optional[Union[list[bool], bool]] = None
    device: str = "cpu"
    engine: str = "mace"
    model_path: Optional[str] = None
    head: Optional[str] = None


class PredictResponse(BaseModel):
    energy: float
    forces: list[list[float]]
    n_atoms: int
    device: str
    model: str
    latency_ms: float
    cold_load_s: Optional[float] = None


def gpu_status() -> tuple[bool, str]:
    try:
        import torch
    except Exception as e:
        return False, f"PyTorch is not available ({e})"
    if not torch.cuda.is_available():
        if not getattr(torch.version, "cuda", None):
            return False, "This PyTorch install is CPU-only. GPU needs a CUDA build of PyTorch."
        return False, "No CUDA GPU is visible."
    return True, torch.cuda.get_device_name(0)


def resolve_model(engine: str, model_path: Optional[str]) -> Path:
    engine = (engine or "mace").lower()
    if engine not in ("mace", "nequip"):
        raise RuntimeError("engine must be mace or nequip")
    if model_path and model_path.strip():
        path = Path(model_path.strip())
        if not path.is_file():
            raise RuntimeError(f"Model file not found: {path}")
        return path
    if engine == "nequip":
        raise RuntimeError("Load a compiled NequIP model first. There is no built-in NequIP file.")
    if not MODEL_PATH.is_file():
        raise RuntimeError(f"Model missing: {MODEL_PATH}")
    return MODEL_PATH


def get_calculator(device: str = "cpu", engine: str = "mace", model_path: Optional[str] = None, head: Optional[str] = None):
    global _load_s
    device = (device or "cpu").lower()
    engine = (engine or "mace").lower()
    if device not in ("cpu", "cuda"):
        raise RuntimeError("device must be cpu or cuda")
    if device == "cuda":
        ok, message = gpu_status()
        if not ok:
            raise RuntimeError(message)
    path = resolve_model(engine, model_path)
    engine_mod = nequip_engine if engine == "nequip" else mace_engine
    if engine == "mace":
        head = mace_engine.selected_head(mace_engine.read_heads(path), head)
    else:
        head = None
    key = engine_mod.cache_key(path, device, head)
    if key not in _calcs:
        calc, label, load_s = engine_mod.load(path, device, head)
        _calcs[key] = (calc, label)
        _load_s = load_s
    return _calcs[key]



class StructureFile(BaseModel):
    filename: str
    text: str = Field(..., min_length=1)


def atoms_to_payload(atoms: Atoms) -> dict:
    if len(atoms) < 1:
        raise ValueError("structure has no atoms")
    positions = np.asarray(atoms.get_positions(), dtype=float)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("positions must be an N x 3 array in angstroms")
    if not np.isfinite(positions).all():
        raise ValueError("positions contain NaN or infinity")
    symbols = list(atoms.get_chemical_symbols())
    unknown = sorted({s for s in symbols if s not in chemical_symbols})
    if unknown:
        raise ValueError(f"unknown element symbols: {', '.join(unknown)}")
    cell = None
    if atoms.cell.rank == 3 and float(atoms.cell.volume) > 0:
        cell = np.asarray(atoms.cell).tolist()
    pbc = bool(np.any(atoms.pbc))
    return {
        "symbols": symbols,
        "positions": positions.tolist(),
        "cell": cell,
        "pbc": atoms.pbc.tolist() if pbc else False,
        "n_atoms": len(atoms),
        "formula": atoms.get_chemical_formula(),
    }



def read_xyz_frames(text: str) -> list[Atoms]:
    try:
        frames = ase_read(StringIO(text), index=":", format="extxyz")
    except Exception as e:
        raise ValueError(f"ASE could not read this XYZ: {e}") from e
    if frames is None:
        raise ValueError("XYZ file has no frames")
    if not isinstance(frames, list):
        frames = [frames]
    if not frames:
        raise ValueError("XYZ file has no frames")
    return frames


def load_structure_text(filename: str, text: str) -> dict:
    name = filename.lower()
    if name.endswith(".json"):
        try:
            import json
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON: {e}") from e
        if isinstance(data, dict) and "symbols" in data and "positions" in data:
            atoms = Atoms(
                symbols=data["symbols"],
                positions=data["positions"],
                cell=data.get("cell"),
                pbc=data.get("pbc", False),
            )
            payload = atoms_to_payload(atoms)
            payload["format"] = "predict-json"
            return payload
        try:
            atoms = ase_read(StringIO(text), format="json")
        except Exception as e:
            raise ValueError(f"ASE could not read this JSON: {e}") from e
        payload = atoms_to_payload(atoms)
        payload["format"] = "ase-json"
        return payload
    if name.endswith(".xyz"):
        frames = read_xyz_frames(text)
        payload = atoms_to_payload(frames[0])
        payload["format"] = "xyz"
        payload["n_frames"] = len(frames)
        return payload
    raise ValueError("upload a .xyz or .json file")



@app.post("/model")
async def upload_model(request: Request, filename: str = "model.model"):
    name = Path(filename).name
    if not name or name in {".", ".."}:
        raise HTTPException(400, "missing model filename")
    data = await request.body()
    if len(data) < 1024:
        raise HTTPException(400, "model file looks empty")
    dest_dir = ROOT / "models" / "uploaded"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    dest.write_bytes(data)
    heads = []
    selected = None
    if name.lower().endswith(".model"):
        try:
            heads = mace_engine.read_heads(dest)
            selected = mace_engine.selected_head(heads)
        except Exception:
            heads = []
            selected = None
    return {"model_path": str(dest), "filename": name, "bytes": len(data), "heads": heads, "selected": selected}



@app.get("/heads")
def model_heads(model_path: Optional[str] = None):
    try:
        path = resolve_model("mace", model_path)
        heads = mace_engine.read_heads(path)
        return {"heads": heads, "selected": mace_engine.selected_head(heads)}
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/health")
def health(warmup: bool = False):
    info = {
        "status": "ok",
        "model": MODEL_NAME,
        "model_loaded": bool(_calcs),
        "device": "cpu" if "cuda" not in _calcs else "cuda",
        "gpu_available": gpu_status()[0],
        "gpu_message": gpu_status()[1],
        "model_path": str(MODEL_PATH),
    }
    if warmup:
        get_calculator(device="cpu", engine="mace")
        info["model_loaded"] = True
        info["cold_load_s"] = _load_s
    return info



@app.post("/structure")
def structure(req: StructureFile):
    try:
        return load_structure_text(req.filename, req.text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if len(req.symbols) != len(req.positions):
        raise HTTPException(400, "symbols and positions length mismatch")
    for p in req.positions:
        if len(p) != 3:
            raise HTTPException(400, "each position must be length 3")

    clear_predict_cancel()
    t0 = time.perf_counter()
    chosen = (req.device or "cpu").lower()
    engine = (req.engine or "mace").lower()
    path = resolve_model(engine, req.model_path)
    engine_mod = nequip_engine if engine == "nequip" else mace_engine
    head = None
    if engine == "mace":
        head = mace_engine.selected_head(mace_engine.read_heads(path), req.head)
    key = engine_mod.cache_key(path, chosen, head)
    first_load = key not in _calcs
    try:
        check_predict_cancel()
        calc, model_name = get_calculator(chosen, engine, req.model_path, req.head)
        check_predict_cancel()
    except PredictionCancelled:
        raise HTTPException(409, "Prediction cancelled")
    except Exception as e:
        raise HTTPException(500, str(e)) from e

    kwargs = {}
    if req.cell is not None:
        kwargs["cell"] = req.cell
    if req.pbc is not None:
        kwargs["pbc"] = req.pbc
    else:
        kwargs["pbc"] = False

    atoms = Atoms(symbols=req.symbols, positions=req.positions, **kwargs)
    atoms.calc = calc
    try:
        check_predict_cancel()
        energy = float(atoms.get_potential_energy())
        forces = atoms.get_forces().tolist()
    except PredictionCancelled:
        raise HTTPException(409, "Prediction cancelled")
    except Exception as e:
        raise HTTPException(500, f"calculator failure: {e}") from e
    latency_ms = (time.perf_counter() - t0) * 1000

    return PredictResponse(
        energy=energy,
        forces=forces,
        n_atoms=len(atoms),
        device=chosen,
        model=model_name,
        latency_ms=latency_ms,
        cold_load_s=_load_s if first_load else None,
    )



class TrajectoryRequest(BaseModel):
    filename: str = "trajectory.xyz"
    text: str = Field(..., min_length=1)
    device: str = "cpu"
    engine: str = "mace"
    model_path: Optional[str] = None
    head: Optional[str] = None


@app.post("/cancel-predict")
async def cancel_predict():
    """Ask the in-flight /predict or /predict-frames loop to stop soon."""
    request_predict_cancel()
    return {"status": "cancelling"}


@app.post("/predict-frames")
def predict_frames(req: TrajectoryRequest):
    clear_predict_cancel()
    try:
        frames = read_xyz_frames(req.text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    t0 = time.perf_counter()
    chosen = (req.device or "cpu").lower()
    engine = (req.engine or "mace").lower()
    try:
        check_predict_cancel()
        calc, model_name = get_calculator(chosen, engine, req.model_path, req.head)
        check_predict_cancel()
    except PredictionCancelled:
        raise HTTPException(409, "Prediction cancelled")
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    out = []
    try:
        for atoms in frames:
            check_predict_cancel()
            atoms.calc = calc
            energy = float(atoms.get_potential_energy())
            forces = atoms.get_forces().tolist()
            item = atoms_to_payload(atoms)
            item["energy"] = energy
            item["forces"] = forces
            out.append(item)
    except PredictionCancelled:
        raise HTTPException(409, "Prediction cancelled")
    except Exception as e:
        raise HTTPException(500, f"calculator failure: {e}") from e
    return {
        "n_frames": len(out),
        "frames": out,
        "device": chosen,
        "model": model_name,
        "latency_ms": (time.perf_counter() - t0) * 1000,
    }


@app.get("/")
def root():
    return {
        "service": "qdspace-mace-sidecar",
        "endpoints": ["POST /health", "GET /heads", "POST /model", "POST /structure", "POST /predict", "POST /predict-frames", "POST /cancel-predict"],
        "docs": "/docs",
    }
