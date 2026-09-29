"""MACE calculator loading. The sidecar runner calls this. It does not serve HTTP."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / "models" / "2024-01-07-mace-128-L2_epoch-199.model"
MODEL_NAME = "mace-mp-0-large"
_HEADS = {}
PREFERRED = ("default", "omat_pbe", "mp_pbe_refit_add", "matpes_r2scan")


def read_heads(path: Path) -> list[str]:
    key = str(path.resolve())
    if key in _HEADS:
        return _HEADS[key]
    import torch

    try:
        obj = torch.load(str(path), map_location="cpu", weights_only=False)
    except TypeError:
        obj = torch.load(str(path), map_location="cpu")
    raw = None
    if isinstance(obj, dict):
        raw = obj.get("heads")
        model = obj.get("model")
        if raw is None and model is not None:
            raw = getattr(model, "heads", None)
            if raw is None and isinstance(model, dict):
                raw = model.get("heads")
    else:
        raw = getattr(obj, "heads", None)
    if not raw:
        heads = []
    elif isinstance(raw, dict):
        heads = [str(name) for name in raw]
    else:
        heads = [str(name) for name in raw]
    _HEADS[key] = heads
    return heads


def selected_head(heads: list[str], requested: Optional[str] = None) -> Optional[str]:
    """Name to show. One head is returned but the UI hides the dropdown."""
    if not heads:
        return None
    if requested:
        if requested not in heads:
            raise RuntimeError(f"Head {requested!r} is not in this model. Available: {', '.join(heads)}")
        return requested
    for name in PREFERRED:
        if name in heads:
            return name
    return heads[0]


def calculator_head(name: Optional[str]) -> Optional[str]:
    if not name or name == "default":
        return None
    return name


def cache_key(path: Path, device: str, head: Optional[str] = None) -> tuple:
    return ("mace", device, str(path.resolve()), head)


def load(path: Path, device: str, head: Optional[str] = None) -> tuple:
    """Return (calculator, label, load_seconds)."""
    from mace.calculators import MACECalculator

    use = calculator_head(head)
    t0 = time.perf_counter()
    kwargs = {
        "model_paths": str(path),
        "device": device,
        "default_dtype": "float32",
    }
    if use:
        kwargs["head"] = use
    calc = MACECalculator(**kwargs)
    label = path.name if not head or head == "default" else f"{path.name} ({head})"
    return calc, label, time.perf_counter() - t0
