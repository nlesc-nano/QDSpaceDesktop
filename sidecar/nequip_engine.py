"""NequIP calculator loading. The sidecar runner calls this. It does not serve HTTP.

A file downloaded from nequip.net is a package, not an ASE calculator.
Compile it for this machine first, then pick the compiled file:

  nequip-compile nequip.net:group/model:version compiled.nequip.pt2 --device cpu --mode aotinductor --target ase
"""
from __future__ import annotations

import time
from pathlib import Path


def cache_key(path: Path, device: str, head: str | None = None) -> tuple:
    return ("nequip", device, str(path.resolve()))


def load(path: Path, device: str, head: str | None = None) -> tuple:
    """Return (calculator, label, load_seconds)."""
    name = path.name.lower()
    if name.endswith(".model"):
        raise RuntimeError("This looks like a MACE file. NequIP needs a compiled model (.nequip.pt2 or .nequip.pth).")
    if not (name.endswith(".nequip.pt2") or name.endswith(".nequip.pth") or name.endswith(".pt2") or name.endswith(".pth")):
        raise RuntimeError(
            "NequIP needs a compiled ASE model (.nequip.pt2 or .nequip.pth). "
            "A download from nequip.net has to be compiled first, for example: "
            "nequip-compile nequip.net:mir-group/NequIP-OAM-L:0.1 compiled.nequip.pt2 "
            "--device cpu --mode aotinductor --target ase"
        )
    try:
        from nequip.integrations.ase import NequIPCalculator
    except ImportError:
        try:
            from nequip.ase import NequIPCalculator
        except ImportError as e:
            raise RuntimeError(
                "The nequip package is not installed in this environment. Install it, then restart the sidecar."
            ) from e

    t0 = time.perf_counter()
    calc = NequIPCalculator.from_compiled_model(compile_path=str(path), device=device)
    return calc, path.name, time.perf_counter() - t0
