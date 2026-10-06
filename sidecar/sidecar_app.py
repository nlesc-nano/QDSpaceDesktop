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

import json
import threading
import time
import uuid
from io import StringIO
from pathlib import Path
from typing import Optional, Union

import numpy as np
from ase import Atoms
from ase.data import chemical_symbols
from ase.io import read as ase_read
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import mace_engine
import nequip_engine
import model_download

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

_download_mgr = model_download.DownloadManager()


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
    model_type: Optional[str] = None


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


def get_calculator(device: str = "cpu", engine: str = "mace", model_path: Optional[str] = None, head: Optional[str] = None, model_type: Optional[str] = None):
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
        model_type = mace_engine.normalize_model_type(model_type)
    else:
        head = None
        model_type = None
    if engine == "mace":
        key = engine_mod.cache_key(path, device, head, model_type)
    else:
        key = engine_mod.cache_key(path, device, head)
    if key not in _calcs:
        if engine == "mace":
            calc, label, load_s = engine_mod.load(path, device, head, model_type)
        else:
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


class ModelPathRequest(BaseModel):
    path: str = Field(..., min_length=1)
    model_type: Optional[str] = None


@app.post("/model-path")
def register_model_path(req: ModelPathRequest):
    """Load a model by absolute path without uploading bytes through POST /model."""
    path = Path(req.path.strip()).expanduser()
    if not path.is_file():
        raise HTTPException(400, f"Model file not found: {path}")
    if path.stat().st_size < 1024:
        raise HTTPException(400, "model file looks empty")
    heads = []
    selected = None
    if path.suffix.lower() == ".model" or path.name.lower().endswith(".model"):
        try:
            heads = mace_engine.read_heads(path)
            selected = mace_engine.selected_head(heads)
        except Exception:
            heads = []
            selected = None
    return {
        "model_path": str(path.resolve()),
        "filename": path.name,
        "bytes": path.stat().st_size,
        "heads": heads,
        "selected": selected,
        "model_type": mace_engine.normalize_model_type(req.model_type),
    }


class DownloadModelRequest(BaseModel):
    url: str = Field(..., min_length=8)
    dest_dir: str = Field(..., min_length=1)
    filename: Optional[str] = None
    expected_size: Optional[int] = None
    sha256: Optional[str] = None


@app.post("/download-model")
def download_model(req: DownloadModelRequest):
    try:
        job = _download_mgr.start(
            url=req.url,
            dest_dir=req.dest_dir,
            filename=req.filename,
            expected_size=req.expected_size,
            sha256=req.sha256,
        )
    except model_download.DownloadError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    snap = job.snapshot()
    return {"job_id": snap["id"], "status": snap["status"], "url": snap.get("url")}


@app.get("/download-model/{job_id}")
def download_model_status(job_id: str):
    job = _download_mgr.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown download job")
    return job.snapshot()


@app.post("/cancel-download/{job_id}")
def cancel_download(job_id: str):
    if not _download_mgr.cancel(job_id):
        raise HTTPException(404, "Unknown download job")
    return {"status": "cancelling", "id": job_id}



@app.get("/heads")
def model_heads(model_path: Optional[str] = None):
    try:
        path = resolve_model("mace", model_path)
        heads = mace_engine.read_heads(path)
        return {"heads": heads, "selected": mace_engine.selected_head(heads)}
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.get("/health")
def health_get(warmup: bool = False):
    """GET alias for probes (curl / Invoke-WebRequest without -Method POST)."""
    return health(warmup=warmup)


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
        "mace_torch": mace_engine.mace_torch_version(),
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
    model_type = None
    if engine == "mace":
        head = mace_engine.selected_head(mace_engine.read_heads(path), req.head)
        model_type = mace_engine.normalize_model_type(req.model_type)
    if engine == "mace":
        key = engine_mod.cache_key(path, chosen, head, model_type)
    else:
        key = engine_mod.cache_key(path, chosen, head)
    first_load = key not in _calcs
    try:
        check_predict_cancel()
        calc, model_name = get_calculator(chosen, engine, req.model_path, req.head, req.model_type)
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
    model_type: Optional[str] = None


def predict_one_frame(atoms: Atoms, calc) -> dict:
    """Energy and forces for one trajectory frame, plus its structure."""
    atoms.calc = calc
    energy = float(atoms.get_potential_energy())
    forces = atoms.get_forces().tolist()
    item = atoms_to_payload(atoms)
    item["energy"] = energy
    item["forces"] = forces
    return item


def ndjson_line(event: dict) -> bytes:
    # allow_nan=False: NaN is not valid JSON and would break the reader in the app.
    return (json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


@app.post("/cancel-predict")
async def cancel_predict():
    """Ask the in-flight /predict, /predict-frames, /predict-frames-stream or /predict-frames-job run to stop soon."""
    request_predict_cancel()
    cancel_all_jobs()
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
        calc, model_name = get_calculator(chosen, engine, req.model_path, req.head, getattr(req, 'model_type', None))
        check_predict_cancel()
    except PredictionCancelled:
        raise HTTPException(409, "Prediction cancelled")
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    out = []
    try:
        for atoms in frames:
            check_predict_cancel()
            out.append(predict_one_frame(atoms, calc))
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


@app.post("/predict-frames-stream")
def predict_frames_stream(req: TrajectoryRequest):
    """Like /predict-frames, but sends one NDJSON line per frame as soon as it is done.

    Lines (each a JSON object with a "type"):
      start     {"n_frames"}                       sent right away, before the model loads
      ready     {"device", "model", "cold_load_s"} model is loaded
      frame     {"index", "n_frames", "energy", "forces", "symbols", "positions", "cell",
                 "pbc", "n_atoms", "formula", "latency_ms", "elapsed_ms"}
      done      {"n_frames", "latency_ms"}         every frame finished
      cancelled {"completed", "n_frames"}          POST /cancel-predict stopped the run
      error     {"message", "index"?, "completed"} the run stopped on an error
    Bad XYZ text still fails up front with HTTP 400.
    """
    clear_predict_cancel()
    try:
        frames = read_xyz_frames(req.text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    t0 = time.perf_counter()
    chosen = (req.device or "cpu").lower()
    engine = (req.engine or "mace").lower()
    total = len(frames)

    def events():
        completed = 0
        yield ndjson_line({"type": "start", "n_frames": total})
        try:
            check_predict_cancel()
            had = set(_calcs)
            calc, model_name = get_calculator(chosen, engine, req.model_path, req.head, getattr(req, 'model_type', None))
            cold = _load_s if set(_calcs) != had else None
            check_predict_cancel()
        except PredictionCancelled:
            yield ndjson_line({"type": "cancelled", "completed": 0, "n_frames": total})
            return
        except Exception as e:
            yield ndjson_line({"type": "error", "message": str(e), "completed": 0, "n_frames": total})
            return
        yield ndjson_line({"type": "ready", "device": chosen, "model": model_name, "cold_load_s": cold})
        for index, atoms in enumerate(frames):
            if _predict_cancel.is_set():
                yield ndjson_line({"type": "cancelled", "completed": completed, "n_frames": total})
                return
            t_frame = time.perf_counter()
            try:
                item = predict_one_frame(atoms, calc)
                item.update({
                    "type": "frame",
                    "index": index,
                    "n_frames": total,
                    "latency_ms": (time.perf_counter() - t_frame) * 1000,
                    "elapsed_ms": (time.perf_counter() - t0) * 1000,
                })
                line = ndjson_line(item)
            except Exception as e:
                yield ndjson_line({
                    "type": "error",
                    "message": f"calculator failure on frame {index + 1}: {e}",
                    "index": index,
                    "completed": completed,
                    "n_frames": total,
                })
                return
            # If the app disconnects (Cancel aborts the fetch), Starlette stops pulling
            # from this generator, so no further frames are computed.
            yield line
            completed += 1
        yield ndjson_line({
            "type": "done",
            "n_frames": completed,
            "latency_ms": (time.perf_counter() - t0) * 1000,
        })

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Predict all frames as a background job the app polls.
#
# The Tauri WebView (WebView2 on Windows) often buffers a streamed fetch body
# until the response ends, so /predict-frames-stream progress can arrive all at
# once. Short polling requests always complete, so progress stays live.
# ---------------------------------------------------------------------------

_JOB_KEEP = 4  # finished jobs kept so a late poll still gets its frames
_jobs: dict[str, "FramesJob"] = {}
_jobs_lock = threading.Lock()


class FramesJob:
    def __init__(self, job_id: str, frames: list[Atoms], req: TrajectoryRequest):
        self.id = job_id
        self.atoms = frames
        self.total = len(frames)
        self.device = (req.device or "cpu").lower()
        self.engine = (req.engine or "mace").lower()
        self.model_path = req.model_path
        self.head = req.head
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.status = "starting"  # starting, loading, running, done, cancelled, error
        self.results: list[dict] = []
        self.model: Optional[str] = None
        self.cold_load_s: Optional[float] = None
        self.error: Optional[str] = None
        self.error_index: Optional[int] = None
        self.created = time.time()
        self.t0 = time.perf_counter()
        self.latency_ms: Optional[float] = None
        self.thread: Optional[threading.Thread] = None

    @property
    def finished(self) -> bool:
        return self.status in ("done", "cancelled", "error")

    def cancelled(self) -> bool:
        return self.cancel.is_set()

    def _finish(self, status: str, error: Optional[str] = None, index: Optional[int] = None) -> None:
        with self.lock:
            self.status = status
            self.error = error
            self.error_index = index
            self.latency_ms = (time.perf_counter() - self.t0) * 1000
            # The parsed structures are not needed once the run ends.
            self.atoms = []

    def run(self) -> None:
        try:
            if self.cancelled():
                self._finish("cancelled")
                return
            with self.lock:
                self.status = "loading"
            had = set(_calcs)
            calc, model_name = get_calculator(self.device, self.engine, self.model_path, self.head)
            cold = _load_s if set(_calcs) != had else None
            with self.lock:
                self.model = model_name
                self.cold_load_s = cold
                self.status = "running"
        except Exception as e:
            self._finish("error", str(e))
            return
        for index, atoms in enumerate(list(self.atoms)):
            if self.cancelled():
                self._finish("cancelled")
                return
            t_frame = time.perf_counter()
            try:
                item = predict_one_frame(atoms, calc)
                item.update({
                    "index": index,
                    "n_frames": self.total,
                    "latency_ms": (time.perf_counter() - t_frame) * 1000,
                    "elapsed_ms": (time.perf_counter() - self.t0) * 1000,
                })
                # Fail here, not in the poll, if the model returned NaN or infinity.
                json.dumps(item, allow_nan=False)
            except Exception as e:
                self._finish("error", f"calculator failure on frame {index + 1}: {e}", index)
                return
            with self.lock:
                self.results.append(item)
        self._finish("done")

    def snapshot(self, after: int) -> dict:
        with self.lock:
            done = len(self.results)
            after = max(0, min(after, done))
            return {
                "job_id": self.id,
                "status": self.status,
                "done": done,
                "total": self.total,
                "after": after,
                "frames": self.results[after:],
                "device": self.device,
                "model": self.model,
                "cold_load_s": self.cold_load_s,
                "latency_ms": self.latency_ms if self.finished else (time.perf_counter() - self.t0) * 1000,
                "cancelled": self.status == "cancelled",
                "error": self.error,
                "error_index": self.error_index,
            }


def _prune_jobs() -> None:
    """Keep every running job plus the newest few finished ones. Call with _jobs_lock held."""
    finished = sorted((j for j in _jobs.values() if j.finished), key=lambda j: j.created)
    for job in finished[:-_JOB_KEEP] if len(finished) > _JOB_KEEP else []:
        _jobs.pop(job.id, None)


def cancel_all_jobs() -> None:
    with _jobs_lock:
        for job in _jobs.values():
            job.cancel.set()


@app.post("/predict-frames-job")
def predict_frames_job(req: TrajectoryRequest):
    """Start predicting every frame in a background thread and return at once.

    Response: {"job_id", "n_frames", "status"}. Poll GET /predict-frames-job/{job_id}?after=N
    for progress and the frames finished since N. POST /cancel-predict stops it.
    Starting a new job cancels any job still running (one model run at a time).
    Bad XYZ text still fails up front with HTTP 400.
    """
    clear_predict_cancel()
    try:
        frames = read_xyz_frames(req.text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    job = FramesJob(uuid.uuid4().hex, frames, req)
    with _jobs_lock:
        previous = [j for j in _jobs.values() if not j.finished]
        for old in previous:
            old.cancel.set()
        _jobs[job.id] = job
        _prune_jobs()

    def runner():
        # Let a cancelled previous job reach its next frame boundary before this one uses the model.
        for old in previous:
            if old.thread is not None:
                old.thread.join()
        job.run()

    job.thread = threading.Thread(target=runner, name=f"predict-frames-{job.id[:8]}", daemon=True)
    job.thread.start()
    return {"job_id": job.id, "n_frames": job.total, "status": job.status}


@app.get("/predict-frames-job/{job_id}")
async def predict_frames_job_status(job_id: str, after: int = 0):
    """Progress of a /predict-frames-job run.

    status: starting | loading | running | done | cancelled | error
    frames: finished frames with index >= after (same fields as /predict-frames-stream "frame").
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown prediction job. The sidecar may have restarted.")
    return job.snapshot(after)


@app.get("/")
def root():
    return {
        "service": "qdspace-mace-sidecar",
        "endpoints": ["POST /health", "GET /heads", "POST /model", "POST /model-path", "POST /download-model", "GET /download-model/{id}", "POST /cancel-download/{id}", "POST /structure", "POST /predict", "POST /predict-frames", "POST /predict-frames-stream", "POST /predict-frames-job", "GET /predict-frames-job/{job_id}", "POST /cancel-predict"],
        "docs": "/docs",
    }
