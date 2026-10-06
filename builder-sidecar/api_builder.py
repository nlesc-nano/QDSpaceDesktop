# Vendored for QDSpace Desktop from
#   https://github.com/nlesc-nano/QDSpaceWebApp/blob/f9524b406e85295bf61dec2675429c5dec90daa2/backend/api_builder.py
# Desktop change: the POSIX-only pty/tty/fcntl import is optional (see below).
# Keep everything else identical so /builder/api/* matches the web Builder.
# To refresh: copy the upstream file again and re-apply that one change.
# backend/api_builder.py
# Active trigger for uvicorn reload of nanocrystal-builder package optimizations
from __future__ import annotations

import io
import json, logging, os, re, shutil, subprocess, sys, tempfile

import yaml
import traceback

# QDSpace Desktop: pty/tty/fcntl are POSIX-only. They are used only by
# popen_stream_tty(), which no route calls, so Windows can start without them.
try:
    import pty, tty, fcntl
except ImportError:  # Windows
    pty = tty = fcntl = None  # type: ignore[assignment]
import select
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import threading
import queue
import asyncio
import contextlib
import inspect
from builder.main import main as nc_builder_main

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import argparse
from ase.io import read as ase_read, write as ase_write
# miniCAT legacy imports removed

import numpy as np

# Core inorganic elements for each material (ignores organic ligands like MA/FA)
MATERIAL_ELEMENTS = {
    "CSPBCL3": ["Cs", "Pb", "Cl"], "CSPBBR3": ["Cs", "Pb", "Br"], "CSPBI3":  ["Cs", "Pb", "I"],
    "MAPBI3":  ["Pb", "I"], "FAPBI3":  ["Pb", "I"], 
    "ZNS":     ["Zn", "S"], "ZNSE":    ["Zn", "Se"], "ZNTE":    ["Zn", "Te"],
    "CDS":     ["Cd", "S"], "CDSE":    ["Cd", "Se"], "CDTE":    ["Cd", "Te"],
    "HGS":     ["Hg", "S"], "HGSE":    ["Hg", "Se"], "HGTE":    ["Hg", "Te"],
    "ALP":     ["Al", "P"], "ALAS":    ["Al", "As"], "ALSB":    ["Al", "Sb"],
    "GAP":     ["Ga", "P"], "GAAS":    ["Ga", "As"], "GASB":    ["Ga", "Sb"],
    "INP":     ["In", "P"], "INAS":    ["In", "As"], "INSB":    ["In", "Sb"],
    "PBS":     ["Pb", "S"], "PBSE":    ["Pb", "Se"]
}

def get_cluster_size_metrics(coords_ang, atom_symbols=None, material_name=None):
    """Calculates size using Axis-Aligned Bounding Box (ideal for lattice-cut QDs)."""
    coords = np.asarray(coords_ang, dtype=float)

    if atom_symbols is not None and material_name is not None:
        m_name = material_name.upper()
        if 'MATERIAL_ELEMENTS' in globals() and m_name in MATERIAL_ELEMENTS:
            core_elements = [el.lower() for el in MATERIAL_ELEMENTS[m_name]]
            core_coords = [coords[i] for i, sym in enumerate(atom_symbols) if sym.lower() in core_elements]
            if len(core_coords) > 0:
                coords = np.array(core_coords)

    if len(coords) < 2:
        return {'R_eff_hull': 1.0, 'diameter_hull': 2.0}

    # Blazing fast: Calculate peak-to-peak distance directly along X, Y, and Z axes
    spans = np.ptp(coords, axis=0)

    # Add 2.5 Å for the physical outer electron cloud (van der Waals radii)
    spans += 2.5

    # The effective diameter is the average of length, width, and height
    avg_diameter = np.mean(spans)
    R_eff = avg_diameter / 2.0

    return {'R_eff_hull': float(R_eff), 'diameter_hull': float(avg_diameter)}

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------

class Facet(BaseModel):
    hkl: str
    gamma: float
    scope: Optional[str] = "family"        # "family" | "facet"
    termination: Optional[str] = None     # None | "cation_rich" | "anion_rich"


class ShellLayer(BaseModel):
    material_cif: str
    aspect: List[float] = [1.0, 1.0, 1.0]
    facets: List[Facet] = []
    size_unit_cells: Optional[List[float]] = None
    interface_type: Optional[str] = "abrupt"
    interface_mixing_ratio: Optional[float] = 0.5
    interface_mixing_width: Optional[float] = 3.0


class LigJob(BaseModel):
    smiles: str
    ratio: float = 1.0
    target_count: int = 0
    dummy: str = ""
    replace: Optional[str] = None
    replace_charge: Optional[int] = None
    ligand_charge: Optional[int] = None
    distribution: Optional[str] = "uniform"


class NeutralJob(BaseModel):
    target: str = "anion"                 # "anion" | "cation" | "both"
    smiles: str
    ratio: float = 1.0
    target_count: int = 0
    distribution: str = "random"           # "random" | "uniform" | "segmented"
    target_symbol: Optional[str] = None


class ZTypeJob(BaseModel):
    cation: str
    anion: str
    anion_count: int = 0
    target_count: int = 0
    ratio: float = 1.0
    distribution: str = "random"           # "random" | "uniform" | "segmented"


class NeutralExchangeJob(BaseModel):
    cation: str
    anion: str
    anion_count: int = 0
    exchange_type: str = "mxn"             # "mxn" | "zwitterion" | "l_type"; "salt" accepted as legacy alias
    smiles: str
    target_count: int = 0
    ratio: float = 1.0
    distribution: str = "random"           # "random" | "uniform" | "segmented"


class AlloyingJob(BaseModel):
    replace: str
    replacement: str
    replacement_charge: int
    region: str = "both"                   # "surface" | "core" | "both"
    ratio: float = 1.0
    target_count: int = 0
    distribution: str = "random"           # "random" | "uniform" | "segmented"


class BuildOptions(BaseModel):
    radius_A: Optional[float] = None
    size_unit_cells: Optional[List[float]] = None
    core_cif_filename: str
    aspect: List[float] = [1.0, 1.0, 1.0]
    facets: List[Facet] = []
    shells: List[ShellLayer] = []

    # legacy (kept for compatibility elsewhere)
    ligand: Optional[str] = None
    surf_tol: Optional[float] = None

    # SMILES passivation
    cap_distribution: Optional[str] = "uniform"  # 'uniform' | 'segmented' | 'random'
    cap_anionic_jobs: Optional[List[LigJob]] = None  # replace Cl
    cap_cationic_jobs: Optional[List[LigJob]] = None  # replace Rb
    skip_core_build: bool = False
    xyz_unpassivated: Optional[str] = None

    # New Surface Reconstruction and Neutral passivation fields
    reconstruction_enabled: Optional[bool] = False
    # Ignored since the {111} reconstruction rewrite; kept so older clients validate.
    reconstruction_target_reduction: Optional[float] = 0.5
    reconstruction_min_separation: Optional[str] = "auto"
    neutral_enabled: Optional[bool] = False
    neutral_jobs: Optional[List[NeutralJob]] = None
    z_type_enabled: Optional[bool] = False
    z_type_jobs: Optional[List[ZTypeJob]] = None
    neutral_exchange_enabled: Optional[bool] = False
    neutral_exchange_jobs: Optional[List[NeutralExchangeJob]] = None
    alloying_enabled: Optional[bool] = False
    alloying_jobs: Optional[List[AlloyingJob]] = None
    x_type_enabled: Optional[bool] = None

    # Construction center ion (maps to YAML construction_origin)
    center_ion: Optional[str] = None

# ---------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------

app = FastAPI(
    title="QD_Builder API (Auto-Passivation)",
    version="5.3.6",
    description="Builds nanocrystals with automatic ligand selection for charge neutrality.",
)

allowed_origins = [
    os.getenv("FRONTEND_CDN", "https://dmq59n0f96mxz.cloudfront.net"),
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def read_index():
    index_path = Path(__file__).resolve().parent.parent / "docs" / "builder" / "index.html" 
    if not index_path.exists():
        return HTMLResponse(
            content="<h1>index.html not found</h1><p>Make sure the index.html file is in the same directory as api.py.</p>",
            status_code=404,
        )
    return HTMLResponse(content=index_path.read_text())


# Cache for analyzed CIF files to speed up repeated custom CIF uploads
_CIF_ANALYSIS_CACHE = {}


@app.post("/api/analyze_cif")
async def analyze_cif(file: UploadFile = File(...)):
    """
    Analyzes an uploaded CIF file and returns symmetry-distinct facet families,
    multiplicities, classifications (polar, stoichiometric), specific Miller index lists,
    and a guess for the crystal phase based on the spacegroup.
    """
    import tempfile
    import hashlib
    from pathlib import Path
    
    tmpdir = None
    try:
        content = await file.read()
        file_hash = hashlib.sha256(content).hexdigest()
        if file_hash in _CIF_ANALYSIS_CACHE:
            logging.info(f"Returning cached CIF analysis for {file.filename}")
            return JSONResponse(_CIF_ANALYSIS_CACHE[file_hash])

        tmpdir = tempfile.mkdtemp(prefix="qdb_analyze_")
        tmp = Path(tmpdir)
        cif_path = tmp / safe_filename(file.filename)
        cif_path.write_bytes(content)
        
        # Parse charges (oxidation numbers)
        try:
            charges = parse_cif_oxidation_numbers(cif_path.read_text("utf-8", "ignore"))
        except Exception:
            charges = {}
            
        from builder.scripts.analyze_cif_facets import _analyze, _hkl_compact, _richness
        
        # Execute pymatgen/symmetry analysis
        rows = _analyze(
            cif_path,
            charges,
            max_index=2,
            proper_only=True,
            supercell=3,
            layer_tol=0.08
        )
        
        # Detect crystal phase matching bulkTemplates
        from pymatgen.core import Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
        struct = Structure.from_file(str(cif_path))
        sga = SpacegroupAnalyzer(struct, symprec=1e-3)
        sg_symbol = sga.get_space_group_symbol()
        
        if "F-43m" in sg_symbol:
            phase = "zinc-blende"
        elif "Fm-3m" in sg_symbol:
            phase = "rock-salt"
        elif "Pm-3m" in sg_symbol:
            phase = "cubic"
        elif "P6_3mc" in sg_symbol:
            phase = "wurtzite"
        else:
            phase = sga.get_crystal_system()
            
        # Format symmetrically distinct facet families compact-style
        compact_rows = []
        for r in rows:
            hkl_compacts = [_hkl_tuple_to_compact(signed_row["hkl"]) for signed_row in r["signed"]]
            hkl_list = sorted(list(set(hkl_compacts)))
            
            # Identify valid terminations
            status = r["family_status"]
            if status in ("polar", "termination-sensitive"):
                terminations = ["cation_rich", "anion_rich"]
            else:
                terminations = ["stoichiometric"]
                
            recommended_hkl: Dict[str, str] = {}
            if status in ("polar", "termination-sensitive"):
                cation_terms: List[str] = []
                anion_terms: List[str] = []
                for signed_row in r["signed"]:
                    hkl_c = _hkl_tuple_to_compact(signed_row["hkl"])
                    for pattern in signed_row.get("patterns", []):
                        rich = _richness(pattern, charges)
                        if rich == "cation-rich":
                            cation_terms.append(hkl_c)
                        elif rich == "anion-rich":
                            anion_terms.append(hkl_c)
                if cation_terms:
                    positive = sorted({t for t in cation_terms if _is_nonnegative_compact(t)})
                    recommended_hkl["cation_rich"] = (
                        positive[0] if positive else _normalize_hkl_string(sorted(set(cation_terms))[0])
                    )
                if anion_terms:
                    negative = sorted({t for t in anion_terms if str(t).startswith("-")})
                    recommended_hkl["anion_rich"] = (
                        negative[0] if negative else sorted(set(anion_terms))[-1]
                    )

                cat_h = recommended_hkl.get("cation_rich")
                an_h = recommended_hkl.get("anion_rich")
                if cat_h and (not an_h or an_h == cat_h):
                    recommended_hkl["anion_rich"] = _opposite_compact_hkl(cat_h)
                elif an_h and not cat_h:
                    recommended_hkl["cation_rich"] = _opposite_compact_hkl(an_h)

            row_out: Dict[str, Any] = {
                "family": r["family"],
                "status": status,
                "multiplicity": r["multiplicity"],
                "hkl_list": hkl_list,
                "terminations": terminations,
            }
            if recommended_hkl:
                row_out["recommended_hkl"] = recommended_hkl
            compact_rows.append(row_out)
            
        lattice_lengths = [float(l) for l in struct.lattice.lengths]

        species = sorted({str(site.specie.symbol) for site in struct})
        
        # Parse constituent elements using electronegativity & metallic properties
        from pymatgen.core import Element
        cations = []
        anions = []
        for el_sym in species:
            try:
                el = Element(el_sym)
                if el.is_metal or el.X < 2.1:
                    cations.append(el_sym)
                else:
                    anions.append(el_sym)
            except Exception:
                cations.append(el_sym)
        
        response_data = {
            "status": "success",
            "phase": phase,
            "spacegroup": sg_symbol,
            "facets": compact_rows,
            "lattice_lengths": lattice_lengths,
            "species": species,
            "anions": anions,
            "cations": cations
        }
        _CIF_ANALYSIS_CACHE[file_hash] = response_data
        return JSONResponse(response_data)
        
    except Exception as e:
        import traceback
        logging.error(f"CIF analysis failed: {e}\n{traceback.format_exc()}")
        return JSONResponse({
            "status": "failed",
            "error": str(e)
        }, status_code=500)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

LIG_PLACEHOLDERS = {"Cl", "Rb"}
LOG_KEEP = 300
_LOG_RE = re.compile(r"(Build(ing)?|Wulff|facet|shell|core|Atoms?|Total charge|Export|Passivation|Done|Warn|Error)$", re.I)
_SKIP_RE = re.compile(r"(downgrade|CN=|unique,\s*depth=|q=\d|neighbor)", re.I)


def _filter_log(text: str) -> str:
    out: List[str] = []
    last = None
    for raw in text.splitlines():
        line = raw.strip()
        if _SKIP_RE.search(line):
            continue
        if not _LOG_RE.search(line):
            continue
        if len(line) > 140:
            line = line[:140] + " …"
        if line == last:
            continue
        out.append(line)
        last = line
    return "\n".join(out[-LOG_KEEP:])

def _xyz_count_symbols(xyz_text: str, targets=("Cl","Rb")) -> dict[str,int]:
    counts = {t: 0 for t in targets}
    lines = xyz_text.splitlines()
    if len(lines) < 3:
        return counts
    try:
        n = int(lines[0].strip())
    except Exception:
        n = len(lines) - 2
    start = 2
    end = min(len(lines), start + max(0, n))
    for i in range(start, end):
        parts = (lines[i] or "").split()
        if parts:
            sym = parts[0]
            if sym in counts:
                counts[sym] += 1
    return counts

def _allocate_counts_by_ratio(total: int, jobs) -> dict[str, int]:
    """Split `total` across jobs by their ratios (largest-remainder)."""
    items = []
    for j in jobs or []:
        if isinstance(j, dict):
            smiles = (j.get("smiles") or "").strip()
            ratio  = float(j.get("ratio") or 0)
        else:
            smiles = (getattr(j, "smiles", "") or "").strip()
            ratio  = float(getattr(j, "ratio", 0) or 0)
        if smiles:
            items.append([smiles, max(0.0, ratio)])
    if not items or total <= 0:
        return {}
    sw = sum(w for _, w in items)
    if sw <= 0:
        base, rem = divmod(total, len(items))
        out = {s: base for s,_ in items}
        for i in range(rem): out[items[i%len(items)][0]] += 1
        return out
    # proportional + largest remainder
    prov, acc = [], 0
    for s,w in items:
        exact = total * (w / sw)
        f = int(exact // 1)
        acc += f
        prov.append([s, f, exact - f])
    rem = total - acc
    prov.sort(key=lambda x: x[2], reverse=True)
    for i in range(rem): prov[i][1] += 1
    return {s:c for s,c,_ in prov}


def _get_heavy_atom_count(smiles: str) -> int:
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol:
            return mol.GetNumHeavyAtoms()
    except Exception:
        pass
    clean = re.sub(r'\[[^\]]+\]', '', smiles)
    letters = re.findall(r'[a-zA-Z]', clean)
    return sum(1 for l in letters if l.upper() != 'H')


def _count_molecules_by_smiles(xyz_text: str, core_elems: set[str], shell_elems: set[str], smiles_list: List[str]) -> Dict[str, int]:
    """
    Performs distance-based connected-component clustering on the organic (non-host) atoms in XYZ,
    counts the number of heavy atoms in each organic molecule cluster,
    and matches them back to the expected heavy atom counts of the requested SMILES strings.
    """
    if not xyz_text or not smiles_list:
        return {}
        
    try:
        from ase.io import read as ase_read
        atoms = ase_read(io.StringIO(xyz_text), format="xyz")
    except Exception as e:
        logging.error(f"ASE read failed in organic clustering: {e}")
        return {}
        
    positions = atoms.get_positions()
    symbols = atoms.get_chemical_symbols()
    n = len(atoms)
    
    # Identify host/inorganic core + shell elements
    host_elements = core_elems.union(shell_elems)
    organic_indices = [
        i for i in range(n)
        if symbols[i] not in host_elements and symbols[i] not in ("Cl", "Rb", "X")
    ]
    
    if not organic_indices:
        return {}
        
    # Build bonding graph adjacency list among organic indices (distance threshold < 2.2 Angstroms)
    adj = {i: [] for i in organic_indices}
    for i in range(len(organic_indices)):
        idx_i = organic_indices[i]
        pos_i = positions[idx_i]
        for j in range(i + 1, len(organic_indices)):
            idx_j = organic_indices[j]
            pos_j = positions[idx_j]
            dist = np.linalg.norm(pos_i - pos_j)
            if dist < 2.2:
                adj[idx_i].append(idx_j)
                adj[idx_j].append(idx_i)
                
    # Find connected components via DFS/BFS
    visited = set()
    components = []
    for idx in organic_indices:
        if idx not in visited:
            comp = []
            q = [idx]
            visited.add(idx)
            while q:
                curr = q.pop()
                comp.append(curr)
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        q.append(neighbor)
            components.append(comp)
            
    # For each component, count non-H heavy atoms
    heavy_counts = []
    for comp in components:
        heavy_atoms = [idx for idx in comp if symbols[idx] != "H"]
        heavy_counts.append(len(heavy_atoms))
        
    heavy_frequencies = Counter(heavy_counts)
    
    # Map smiles to heavy atom sizes
    smiles_to_heavy = {}
    for sm in smiles_list:
        if sm.strip():
            smiles_to_heavy[sm.strip()] = _get_heavy_atom_count(sm)
            
    counts_by_smiles = {}
    for h_count, num_mols in heavy_frequencies.items():
        if h_count <= 0:
            continue
        # Find any smiles that match this heavy count
        matched = [sm for sm, hc in smiles_to_heavy.items() if hc == h_count]
        if len(matched) == 1:
            counts_by_smiles[matched[0]] = num_mols
        elif len(matched) > 1:
            counts_by_smiles[matched[0]] = num_mols
            
    return counts_by_smiles


def _count_grouped_xyz(xyz_text: str, core_elems: set[str], shell_elems: set[str]) -> dict:
    counts = {"core": Counter(), "shell": Counter(), "ligand": Counter()}
    lines = xyz_text.splitlines()
    try:
        n = int(lines[0].strip())
    except Exception:
        n = 0

    for i in range(2, 2 + n):
        if i >= len(lines):
            break
        el = (lines[i].split() or ["?"])[0]
        if el in LIG_PLACEHOLDERS:
            grp = "ligand"
        elif el in core_elems:
            grp = "core"
        elif el in shell_elems:
            grp = "shell"
        else:
            grp = "ligand"
        counts[grp][el] += 1

    total = sum(sum(c.values()) for c in counts.values())
    fmt = lambda c: {"total": sum(c.values()), "by_element": dict(c)}  # noqa: E731
    return {
        "total_atoms": total,
        "core": fmt(counts["core"]),
        "shell": fmt(counts["shell"]),
        "ligand": fmt(counts["ligand"]),
    }


def _charge_of_xyz(xyz_text: str, charges: Dict[str, float]) -> float:
    lines = xyz_text.splitlines()
    try:
        n = int(lines[0].strip())
    except Exception:
        return 0.0

    total = 0.0
    for i in range(2, 2 + n):
        if i >= len(lines):
            break
        el = (lines[i].split() or ["?"])[0]
        total += charges.get(el, 0.0)
    return total


_COMMON_FORMAL_CHARGES = {
    "Li": 1.0, "Na": 1.0, "K": 1.0, "Rb": 1.0, "Cs": 1.0, "Ag": 1.0,
    "Mg": 2.0, "Ca": 2.0, "Sr": 2.0, "Ba": 2.0, "Zn": 2.0, "Cd": 2.0, "Hg": 2.0, "Pb": 2.0,
    "Al": 3.0, "Ga": 3.0, "In": 3.0, "Bi": 3.0,
    "F": -1.0, "Cl": -1.0, "Br": -1.0, "I": -1.0,
    "O": -2.0, "S": -2.0, "Se": -2.0, "Te": -2.0,
    "N": -3.0, "P": -3.0, "As": -3.0, "Sb": -3.0,
}


def _augment_charges_for_neutral_exchange(charges: Dict[str, float], opts: BuildOptions) -> None:
    import re

    for job in getattr(opts, "neutral_exchange_jobs", None) or []:
        exchange_type = (getattr(job, "exchange_type", None) or "mxn").lower()
        if exchange_type == "salt":
            exchange_type = "mxn"
        if exchange_type != "mxn":
            continue
        spec = (getattr(job, "smiles", "") or "").strip()
        if not spec:
            continue
        if "." in spec or any(ch in spec for ch in "[]+-"):
            for sym in re.findall(r"\[([A-Z][a-z]?)(?:\+\d*|\d+\+|-\d*|\d+-)?\]", spec):
                if sym in _COMMON_FORMAL_CHARGES:
                    charges.setdefault(sym, _COMMON_FORMAL_CHARGES[sym])
            continue
        for sym, _count in re.findall(r"([A-Z][a-z]?)(\d*)", spec):
            if sym in _COMMON_FORMAL_CHARGES:
                charges.setdefault(sym, _COMMON_FORMAL_CHARGES[sym])


def _validate_neutral_exchange_jobs(opts: BuildOptions) -> None:
    if not getattr(opts, "neutral_exchange_enabled", False):
        return
    from builder.neutral_exchange_posttreat import _validate_zwitterion_smiles

    for index, job in enumerate(getattr(opts, "neutral_exchange_jobs", None) or [], start=1):
        exchange_type = (getattr(job, "exchange_type", None) or "mxn").lower()
        if exchange_type != "zwitterion":
            continue
        smiles = (getattr(job, "smiles", "") or "").strip()
        if not smiles:
            continue
        try:
            _validate_zwitterion_smiles(smiles)
        except ValueError as exc:
            raise ValueError(f"Neutral exchange job {index}: {exc}") from exc


def run_cmd(cmd: List[str], cwd: Path) -> Tuple[str, str]:
    if cmd[0] == "nc-builder":
        exe = shutil.which("nc-builder")
        if not exe:
            raise RuntimeError("nc-builder not found on PATH for this server process.")
        cmd[0] = exe
    p = subprocess.run(cmd, cwd=str(cwd), check=True, text=True, capture_output=True)
    return p.stdout, p.stderr


def parse_cif_oxidation_numbers(text: str) -> Dict[str, float]:
    lines = text.splitlines()
    i = 0
    charges: Dict[str, float] = {}

    def read_loop(start: int):
        hdrs, rows, j = [], [], start + 1
        while j < len(lines) and lines[j].lstrip().startswith("_"):
            hdrs.append(lines[j].strip())
            j += 1
        while j < len(lines):
            t = lines[j].strip()
            if not t or t.startswith(("loop_", "data_", "_")):
                break
            rows.append(t)
            j += 1
        return hdrs, rows, j

    _KEY_ALIASES = {
        "_atom_type.symbol": "_atom_type_symbol",
        "_atom_type.oxidation_number": "_atom_type_oxidation_number",
        "_atom_type.charge": "_atom_type_charge",
        "_atom_site.type_symbol": "_atom_site_type_symbol",
        "_atom_site.oxidation_number": "_atom_site_oxidation_number",
        "_atom_site.charge": "_atom_site_charge",
        "_atom_site.label": "_atom_site_label",
    }

    def _norm_key(k: str) -> str:
        return _KEY_ALIASES.get(k.strip().lower(), k.strip().lower())

    def _elem_from_label(s: str) -> str:
        m = re.match(r"([A-Z][a-z]?)", s)
        return m.group(1) if m else s

    def _parse_charge_str(v: str) -> float:
        v = str(v).strip().replace(",", ".").replace(" ", "")
        if v.endswith("+"):
            v = v[:-1]
        elif v.endswith("-"):
            v = "-" + v[:-1]
        if v.startswith("+"):
            v = v[1:]
        return float(v) if v else 0.0

    while i < len(lines):
        if lines[i].strip().lower().startswith("loop_"):
            hdrs, rows, j = read_loop(i)
            headers = [_norm_key(h) for h in hdrs]
            sym_candidates = ["_atom_type_symbol", "_atom_site_type_symbol", "_atom_site_label"]
            ox_candidates = [
                "_atom_type_oxidation_number",
                "_atom_site_oxidation_number",
                "_atom_type_charge",
                "_atom_site_charge",
            ]
            si = next((headers.index(k) for k in sym_candidates if k in headers), None)
            oi = next((headers.index(k) for k in ox_candidates if k in headers), None)
            if si is not None and oi is not None:
                for row in rows:
                    toks = re.findall(r"(?:'[^']*'|\"[^\"]*\"|\S+)", row)
                    if len(toks) <= max(si, oi):
                        continue
                    raw_sym, raw_ox = toks[si].strip("'\""), toks[oi].strip("'\"")
                    if raw_sym in ".?" or raw_ox in ".?":
                        continue
                    sym = _elem_from_label(raw_sym)
                    try:
                        charges[sym] = _parse_charge_str(raw_ox)
                    except (ValueError, IndexError):
                        continue
            i = j
        else:
            i += 1

    return charges


def execute_builder_command(
    cmd: List[str], out_dir: str, primary_output_filename: str
) -> Tuple[bool, str, Dict[str, Path | None]]:
    out_dir_path = Path(out_dir)
    final_path = out_dir_path / primary_output_filename
    output_stem = final_path.stem
    cut_path = out_dir_path / f"{output_stem}_cut.xyz"

    logging.info(f"Running command in {out_dir_path}: {' '.join(cmd)}")

    try:
        p = subprocess.run(
            cmd,
            cwd=str(out_dir_path),
            capture_output=True,
            env=os.environ.copy(),
            check=False,
            text=True,
        )
        stdout = p.stdout or ""
        stderr = p.stderr or ""
        log_output = stdout + ("\n" + stderr if stderr else "")

        ok = p.returncode == 0 and final_path.exists() and final_path.stat().st_size > 0
        if not ok:
            logging.error(
                f"nc-builder execution check failed (return code: {p.returncode}).\nLogs:\n{log_output}"
            )

        found_files = {
            "final": final_path if final_path.exists() else None,
            "cut": cut_path if cut_path.exists() else None,
        }
        return ok, log_output, found_files

    except FileNotFoundError:
        msg = "Error: 'nc-builder' command not found. Is your conda environment activated?"
        logging.error(msg)
        return False, msg, {}

    except Exception as e:
        msg = f"An unexpected error occurred: {e}"
        logging.error(msg, exc_info=True)
        return False, msg, {}

def run_quiet(cmd, cwd=None, env=None):
    # Fastest: no stdout/err shipping over HTTP; write a log file for post-mortem.
    log_path = os.path.join(cwd or ".", "build.log")
    with open(log_path, "wb") as lf:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return p.returncode, log_path

def popen_stream_tty(cmd, cwd=None, env=None):
    """
    Spawn under a pseudo-terminal to force line-buffering in the child.
    Yields decoded lines ASAP. Slightly more CPU than pipes, but best interactivity.
    """
    master_fd, slave_fd = pty.openpty()
    # Optional: put the tty in raw-ish mode
    try:
        tty.setraw(master_fd)
    except Exception:
        pass

    # Make non-blocking
    fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    # Important: direct child's stdout/err to the slave tty
    p = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        bufsize=0,
        close_fds=True,
    )
    os.close(slave_fd)

    decoder = None
    try:
        while True:
            r, _, _ = select.select([master_fd], [], [], 0.25)
            if master_fd in r:
                try:
                    chunk = os.read(master_fd, 65536)
                except BlockingIOError:
                    chunk = b""
                if not chunk:
                    # could be just EAGAIN; fall through to poll
                    pass
                else:
                    if decoder is None:
                        decoder = (lambda b: b.decode("utf-8", "replace"))
                    text = decoder(chunk)
                    for line in text.splitlines():
                        yield line
            if p.poll() is not None:
                # Drain any residual
                try:
                    while True:
                        chunk = os.read(master_fd, 65536)
                        if not chunk:
                            break
                        text = (decoder or (lambda b: b.decode("utf-8","replace")))(chunk)
                        for line in text.splitlines():
                            yield line
                except Exception:
                    pass
                break
    finally:
        try: os.close(master_fd)
        except Exception: pass

def popen_stream(cmd: List[str], cwd: Path, env: Optional[Dict[str, str]] = None):
    """
    Yield text lines (stdout+stderr merged) from a long-running command.
    """
    if cmd[0] == "nc-builder":
        nc_builder_path = shutil.which("nc-builder")
        if not nc_builder_path:
            raise RuntimeError("nc-builder not found on PATH for this server process.")
        python_exe = sys.executable
        cmd = [python_exe, "-u", nc_builder_path] + cmd[1:]

    base_env = os.environ.copy()
    if env:
        base_env.update(env)

    # Ensure unbuffered UTF-8 streams for child
    base_env["PYTHONUNBUFFERED"] = "1"
    base_env["PYTHONIOENCODING"] = "utf-8"
    base_env["NCBUILDER_FLUSH"] = "1"
    base_env["QD_BUILDER_UNBUFFERED"] = "1"
    # ---------------------
    p = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=base_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,                # <- text mode (aka universal_newlines=True)
        encoding="utf-8",
        errors="replace",         # avoid crashes on odd bytes
    )
    try:
        for line in p.stdout:
            # line already decoded text with trailing newline if any
            yield line
    finally:
        if p.stdout:
            p.stdout.close()
        p.wait()

def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


def format_facets_to_dict(facets: List[Facet]) -> Dict[str, float]:
    return {f.hkl: f.gamma for f in facets}


class _QuotedStr(str):
    """Force double-quoted YAML strings (needed for hkl like -1-1-1)."""


def _quoted_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


yaml.add_representer(_QuotedStr, _quoted_str_representer)
yaml.SafeDumper.add_representer(_QuotedStr, _quoted_str_representer)


def _yaml_dump_canonical(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False)


def _aspect_is_unity(aspect: Optional[List[float]]) -> bool:
    vals = aspect or [1.0, 1.0, 1.0]
    return all(abs(float(a) - 1.0) < 1e-9 for a in vals)


def _needs_rb_in_recipe(opts: BuildOptions, positive_q_mode: str, *, repassivate_only: bool = False) -> bool:
    if repassivate_only:
        for job in opts.cap_cationic_jobs or []:
            if job.smiles.strip():
                return True
        return False
    posq = (positive_q_mode or "remove").strip().lower()
    if posq == "add":
        return True
    for job in opts.cap_cationic_jobs or []:
        if job.smiles.strip():
            return True
    return False


def _has_cation_rich_facets(facets) -> bool:
    for f in facets or []:
        term = getattr(f, "termination", None) if hasattr(f, "termination") else f.get("termination")
        if str(term or "").strip().lower() == "cation_rich":
            return True
    return False


def _positive_q_mode_for_opts(opts: BuildOptions, requested: str = "remove") -> str:
    posq = (requested or "remove").strip().lower()
    if posq not in ("remove", "add"):
        posq = "remove"
    if _has_cation_rich_facets(opts.facets):
        return "add"
    for shell in opts.shells or []:
        if _has_cation_rich_facets(shell.facets):
            return "add"
    return posq


def _hkl_tuple_to_compact(hkl: tuple) -> str:
    """Miller compact string compatible with nc-builder _parse_hkl."""
    return "".join(
        (f"-{abs(int(x))}" if int(x) < 0 else str(int(x)))
        for x in (hkl[0], hkl[1], hkl[2])
    )


def _opposite_compact_hkl(hkl_str: str) -> str:
    """Return the opposite signed Miller index in compact form (e.g. 111 -> -1-1-1)."""
    from builder.config import _parse_hkl

    h, k, l = _parse_hkl(str(hkl_str).strip())
    return _hkl_tuple_to_compact((-h, -k, -l))


def _is_nonnegative_compact(hkl_str: str) -> bool:
    s = str(hkl_str).strip()
    return bool(s) and not s.startswith("-") and "-" not in s


def _normalize_hkl_string(h: str) -> str:
    """Normalize stored/UI hkl to compact form; map 1-1-1 style to preferred positive family seed when possible."""
    s = str(h).strip().strip("()")
    if _is_nonnegative_compact(s):
        return s
    if s.startswith("-") and "-" not in s[1:]:
        return s
    # Ambiguous mixed-sign compact (e.g. 1-1-1): use absolute digits for non-anion family seeds
    digits = re.findall(r"\d", s)
    if len(digits) == 3:
        return "".join(digits)
    return s


def _build_post_treatment_from_opts(opts: BuildOptions) -> dict:
    post_treatment: dict = {}
    if opts.reconstruction_enabled:
        # Polar {111} reconstruction (zinc-blende II-VI / III-V with both
        # cation_rich {111} and anion_rich {-1-1-1} active); QD_Builder decides
        # applicability and skips with a log message otherwise.
        post_treatment["surface_reconstruction"] = {
            "enabled": True,
            "ligand": "Cl",
            "seed": 1337,
        }
    if opts.z_type_enabled and opts.z_type_jobs:
        z_passes = []
        for job in opts.z_type_jobs:
            target_count = int(job.target_count or 0)
            if job.cation.strip() and job.anion.strip() and (target_count > 0 or float(job.ratio) > 0):
                z_passes.append({
                    "cation": job.cation.strip(),
                    "anion": job.anion.strip(),
                    "anion_count": int(job.anion_count or 0),
                    "target_count": target_count,
                    "ratio": job.ratio,
                    "distribution": job.distribution or "random",
                })
        if z_passes:
            post_treatment["z_type_displacement"] = {
                "enabled": True,
                "passes": z_passes,
                "seed": 1337,
            }
    if opts.neutral_exchange_enabled and opts.neutral_exchange_jobs:
        ne_passes = []
        for job in opts.neutral_exchange_jobs:
            target_count = int(job.target_count or 0)
            if job.cation.strip() and job.anion.strip() and job.smiles.strip() and (target_count > 0 or float(job.ratio) > 0):
                ne_passes.append({
                    "cation": job.cation.strip(),
                    "anion": job.anion.strip(),
                    "anion_count": int(job.anion_count or 0),
                    "exchange_type": "mxn" if (job.exchange_type or "mxn") == "salt" else (job.exchange_type or "mxn"),
                    "smiles": job.smiles.strip(),
                    "target_count": target_count,
                    "ratio": job.ratio,
                    "distribution": job.distribution or "random",
                })
        if ne_passes:
            post_treatment["neutral_exchange"] = {
                "enabled": True,
                "passes": ne_passes,
                "seed": 1337,
            }
    if opts.alloying_enabled and opts.alloying_jobs:
        alloy_passes = []
        for job in opts.alloying_jobs:
            target_count = int(job.target_count or 0)
            if job.replace.strip() and job.replacement.strip() and (target_count > 0 or float(job.ratio) > 0):
                alloy_passes.append({
                    "replace": job.replace.strip(),
                    "with": job.replacement.strip(),
                    "with_charge": int(job.replacement_charge),
                    "region": job.region or "both",
                    "ratio": job.ratio,
                    "target_count": target_count,
                    "distribution": job.distribution or "random",
                })
        if alloy_passes:
            post_treatment["alloying"] = {
                "enabled": True,
                "passes": alloy_passes,
                "seed": 1337,
            }
    x_type_enabled = bool(opts.x_type_enabled) if opts.x_type_enabled is not None else bool(opts.cap_anionic_jobs or opts.cap_cationic_jobs)
    passes = []
    if x_type_enabled and opts.cap_anionic_jobs:
        for job in opts.cap_anionic_jobs:
            if job.smiles.strip():
                replace = (job.replace or job.dummy or "Cl").strip()
                passes.append({
                    "replace": replace,
                    "charge": job.ligand_charge,
                    "replace_charge": job.replace_charge,
                    "smiles": [job.smiles.strip()],
                    "ratio": job.ratio,
                    "target_count": int(getattr(job, "target_count", 0) or 0),
                    "distribution": job.distribution or opts.cap_distribution or "uniform",
                })
    if x_type_enabled and opts.cap_cationic_jobs:
        for job in opts.cap_cationic_jobs:
            if job.smiles.strip():
                replace = (job.replace or job.dummy or "Rb").strip()
                passes.append({
                    "replace": replace,
                    "charge": job.ligand_charge,
                    "replace_charge": job.replace_charge,
                    "smiles": [job.smiles.strip()],
                    "ratio": job.ratio,
                    "target_count": int(getattr(job, "target_count", 0) or 0),
                    "distribution": job.distribution or opts.cap_distribution or "uniform",
                })
    if passes:
        post_treatment["ligand_exchange"] = {
            "enabled": True,
            "passes": passes,
            "ff": "uff",
            "refinement_passes": 3,
            "sterics_mode": "vdw",
            "seed": 1337,
        }
    if opts.neutral_enabled and opts.neutral_jobs:
        neutral_passes = []
        for job in opts.neutral_jobs:
            if job.smiles.strip():
                neutral_passes.append({
                    "target": job.target or "anion",
                    "target_symbol": (job.target_symbol or "").strip() or None,
                    "smiles": job.smiles.strip(),
                    "ratio": job.ratio,
                    "target_count": int(getattr(job, "target_count", 0) or 0),
                    "distribution": job.distribution or "random",
                })
        if neutral_passes:
            post_treatment["neutral_ligands"] = {
                "enabled": True,
                "passes": neutral_passes,
                "ff": "uff",
                "refinement_passes": 3,
                "sterics_mode": "vdw",
                "offset_out": 0.5,
                "seed": 1337,
            }
    return post_treatment


def _run_repassivation_posttreatment(
    xyz_text: str,
    core_cif_path: Path,
    charges: Dict[str, float],
    post_treatment: dict,
    tmp_path: Path,
    *,
    facets_input: Optional[List] = None,
    log_sink: Optional[List[str]] = None,
) -> Tuple[str, List[dict]]:
    """
    Apply post_treatment on an existing XYZ without Wulff rebuild.

    Order matches nc-builder main.py:
      1. surface_reconstruction (Cl placeholders on polar facets)
      2. ligand_exchange (charged X-type)
      3. neutral_ligands (L-type)
    """
    from functools import partial

    from ase import Atoms
    from ase.io import read as ase_read, write as ase_write
    from pymatgen.core import Structure

    facets_yaml = format_facets_for_yaml(facets_input) if facets_input else [
        {"hkl": _QuotedStr("100"), "gamma": 1.0, "scope": "family"},
        {"hkl": _QuotedStr("110"), "gamma": 1.0, "scope": "family"},
        {"hkl": _QuotedStr("111"), "gamma": 1.0, "scope": "family"},
    ]
    lig_passes_for_defaults = ((post_treatment or {}).get("ligand_exchange") or {}).get("passes") or []
    include_cation_ligand = any(
        (int(p.get("charge") or 0) > 0) or 
        (int(p.get("replace_charge") or charges.get(p.get("replace"), 0) or 0) > 0)
        for p in lig_passes_for_defaults
    )
    minimal_yaml = {
        "charges": charges,
        "passivation": _default_passivation_block(
            include_cation_ligand=include_cation_ligand, ligand=_anion_placeholder_for_cif(core_cif_path)
        ),
        "facets": facets_yaml,
        "symmetry": {"proper_rotations_only": True},
    }
    if post_treatment:
        minimal_yaml["post_treatment"] = post_treatment

    yaml_path = tmp_path / "repassivate.yml"
    yaml_path.write_text(_yaml_dump_canonical(minimal_yaml), encoding="utf-8")

    from builder.config import parse_yaml_config
    from builder.facets import detect_facets_from_nc, expand_facets
    from builder.alloying_posttreat import run_alloying_posttreatment
    from builder.facet_reconstruction import _native_facets_and_planes, reconstruct_polar_facets
    from builder.ligand_exchange_posttreat import (
        rebalance_ligand_exchange_charge,
        run_ligand_exchange_posttreatment,
    )
    from builder.neutral_ligand_posttreat import run_neutral_ligand_posttreatment
    from builder.passivation_iterative import charge_balance_iterative
    from builder.z_type_displacement_posttreat import run_z_type_displacement_posttreatment

    cfg = parse_yaml_config(str(yaml_path))
    struct = Structure.from_file(str(core_cif_path))
    atoms = ase_read(io.StringIO(xyz_text), format="xyz")
    syms = list(atoms.get_chemical_symbols())
    pts = atoms.get_positions()
    cif_path = str(core_cif_path.resolve())
    anion_lig = cfg.passivation.ligand or "Cl"
    facet_seeds = expand_facets(struct, cfg.seeds, proper_only=cfg.proper_only)
    ledger: List[dict] = []

    pt = getattr(cfg, "post_treatment", None)
    surface_reconstruction_spec = getattr(pt, "surface_reconstruction", None)
    alloying_spec = getattr(pt, "alloying", None)
    z_type_spec = getattr(pt, "z_type_displacement", None)
    lig_ex = getattr(pt, "ligand_exchange", None)
    neutral_spec = getattr(pt, "neutral_ligands", None)

    def _detect_planes():
        facets, planes = _native_facets_and_planes(
            syms, pts, struct, cfg.charges, facet_seeds, anion_lig, cfg.passivation.surf_tol
        )
        if not planes:
            facets, planes = detect_facets_from_nc(
                syms, pts, struct.lattice, cfg.charges, facet_seeds, cfg.passivation.surf_tol
            )
        return facets, planes

    class _Capture(io.TextIOBase):
        def write(self, s):
            if log_sink is not None and s:
                if hasattr(log_sink, "put"):
                    log_sink.put(s)
                elif hasattr(log_sink, "append"):
                    log_sink.append(s)
            return len(s)

    with contextlib.redirect_stdout(_Capture()), contextlib.redirect_stderr(_Capture()):
        # 1. Surface reconstruction with Cl placeholders (polar facets)
        if surface_reconstruction_spec is not None and surface_reconstruction_spec.enabled:
            balance_fn = partial(
                charge_balance_iterative,
                cfg.charges,
                anion_lig,
                verbose=False,
                planes=[],
                surf_tol=cfg.passivation.surf_tol,
                cif_path=cif_path,
                positive_q_strategy="remove",
                write_all=False,
                prefix=str(tmp_path / "repass"),
                prepass_mode=cfg.passivation.prepass_mode,
                prepass_min_cn_terrace=cfg.passivation.prepass_min_cn_terrace,
                prepass_min_cn_edge=cfg.passivation.prepass_min_cn_edge,
                prepass_min_cn_vertex=cfg.passivation.prepass_min_cn_vertex,
            )
            recon_ledger: dict = {}
            recon_kwargs = {}
            if "ledger" in inspect.signature(reconstruct_polar_facets).parameters:
                recon_kwargs["ledger"] = recon_ledger
            syms, pts = reconstruct_polar_facets(
                syms,
                pts,
                struct=struct,
                facet_seeds=facet_seeds,
                charges=cfg.charges,
                ligand=anion_lig,
                surf_tol=cfg.passivation.surf_tol,
                cif_path=cif_path,
                spec=surface_reconstruction_spec,
                charge_balance_fn=balance_fn,
                verbose=False,
                write_all=False,
                prefix=str(tmp_path / "repass"),
                **recon_kwargs,
            )
            if recon_ledger:
                ledger.append({"surface_reconstruction": True, **recon_ledger})

        _facets, planes = _detect_planes()
        if log_sink is not None:
            msg = f"[system] Detected {len(planes)} Wulff plane(s) for post-treatment site discovery\n"
            if hasattr(log_sink, "put"):
                log_sink.put(msg)
            elif hasattr(log_sink, "append"):
                log_sink.append(msg)

        # 2. Inorganic alloying, then charge rebalance
        if alloying_spec is not None and alloying_spec.enabled:
            syms, pts, alloy_ledger = run_alloying_posttreatment(syms, pts, cfg, struct, planes)
            if alloy_ledger:
                for entry in alloy_ledger:
                    cfg.charges.setdefault(entry["replacement"], int(entry["replacement_charge"]))
                ledger.extend({"alloying": True, **entry} for entry in alloy_ledger)
                # A higher-valent dopant (In3+ on a Cd2+ site) is compensated
                # by extra X-type ligand; if the free ligand sites cannot absorb
                # it all, restart from the alloyed dot and remove surface atoms.
                alloyed_syms, alloyed_pts = list(syms), np.asarray(pts, float).copy()
                for strategy in ("add", "remove"):
                    if strategy == "remove":
                        if sum(int(cfg.charges.get(s, 0)) for s in syms) <= 0:
                            break
                        syms, pts = list(alloyed_syms), alloyed_pts.copy()
                    syms, pts = charge_balance_iterative(
                        syms,
                        pts,
                        cfg.charges,
                        anion_lig,
                        verbose=False,
                        planes=planes,
                        surf_tol=cfg.passivation.surf_tol,
                        cif_path=cif_path,
                        positive_q_strategy=strategy,
                        write_all=False,
                        prefix=str(tmp_path / "repass"),
                        prepass_mode=cfg.passivation.prepass_mode,
                        prepass_min_cn_terrace=cfg.passivation.prepass_min_cn_terrace,
                        prepass_min_cn_edge=cfg.passivation.prepass_min_cn_edge,
                        prepass_min_cn_vertex=cfg.passivation.prepass_min_cn_vertex,
                    )

        # 3. Z-type displacement (neutral inorganic groups; before X-type exchange)
        z_ledger: List[dict] = []
        if z_type_spec is not None and z_type_spec.enabled:
            syms, pts, z_ledger = run_z_type_displacement_posttreatment(
                syms, pts, cfg, struct, planes, cif_path
            )
            ledger.extend({"z_type": True, **entry} for entry in z_ledger)

        # 3b. Neutral exchange (optional; after displacement, before X-type exchange)
        neutral_exchange_spec = getattr(cfg.post_treatment, "neutral_exchange", None)
        if neutral_exchange_spec is not None and neutral_exchange_spec.enabled:
            from builder.neutral_exchange_posttreat import run_neutral_exchange_posttreatment
            syms, pts, ne_ledger = run_neutral_exchange_posttreatment(
                syms, pts, cfg, struct, planes, cif_path
            )
            ledger.extend({"neutral_exchange": True, **entry} for entry in ne_ledger)

        # 4. Charged ligand exchange (X-type)
        if lig_ex is not None and lig_ex.enabled:
            syms, pts, x_ledger = run_ligand_exchange_posttreatment(
                syms, pts, cfg, struct, planes, cif_path
            )
            ledger.extend(x_ledger)
            if x_ledger:
                q_element = int(sum(int(cfg.charges.get(sym, 0)) for sym in syms))
                q_ignored = int(sum(int(entry.get("ignored_element_charge", 0)) for entry in x_ledger))
                q_exchange = int(sum(int(entry.get("charge", 0)) for entry in x_ledger))
                q_total = q_element - q_ignored + q_exchange
                if q_total != 0:
                    if log_sink is not None:
                        msg = (
                            "[ligand-exchange:charge-balance] "
                            f"residual Q={q_total:+d}; running ligand-only exchange compensation\n"
                        )
                        if hasattr(log_sink, "put"):
                            log_sink.put(msg)
                        elif hasattr(log_sink, "append"):
                            log_sink.append(msg)
                    syms, pts = rebalance_ligand_exchange_charge(
                        syms, pts, cfg, struct, planes, cif_path, x_ledger, verbose=False
                    )

        # 5. Neutral ligand passivation (L-type; after exchange, same as nc-builder)
        if neutral_spec is not None and neutral_spec.enabled:
            syms, pts = run_neutral_ligand_posttreatment(syms, pts, cfg, struct, planes)

    out = io.StringIO()
    ase_write(out, Atoms(symbols=syms, positions=pts), format="xyz")
    return out.getvalue(), ledger


def _detect_z_type_options_for_xyz(
    xyz_text: str,
    core_cif_path: Path,
    charges: Dict[str, float],
    tmp_path: Path,
    *,
    facets_input: Optional[List] = None,
) -> List[dict]:
    if not xyz_text:
        return []
    try:
        from ase.io import read as ase_read
        from pymatgen.core import Structure
        from builder.config import parse_yaml_config
        from builder.facets import detect_facets_from_nc, expand_facets
        from builder.facet_reconstruction import _native_facets_and_planes
        from builder.z_type_displacement_posttreat import detect_z_type_displacement_options
    except Exception as exc:
        logging.error(f"Z-type imports failed: {exc}")
        return []

    try:
        facets_yaml = format_facets_for_yaml(facets_input) if facets_input else [
            {"hkl": _QuotedStr("100"), "gamma": 1.0, "scope": "family"},
            {"hkl": _QuotedStr("110"), "gamma": 1.0, "scope": "family"},
            {"hkl": _QuotedStr("111"), "gamma": 1.0, "scope": "family"},
        ]
        minimal_yaml = {
            "charges": charges,
            "passivation": _default_passivation_block(ligand=_anion_placeholder_for_cif(core_cif_path)),
            "facets": facets_yaml,
            "symmetry": {"proper_rotations_only": True},
        }
        yaml_path = tmp_path / "z_type_detect.yml"
        yaml_path.write_text(_yaml_dump_canonical(minimal_yaml), encoding="utf-8")
        cfg = parse_yaml_config(str(yaml_path))
        struct = Structure.from_file(str(core_cif_path))
        atoms = ase_read(io.StringIO(xyz_text), format="xyz")
        syms = list(atoms.get_chemical_symbols())
        pts = atoms.get_positions()
        facet_seeds = expand_facets(struct, cfg.seeds, proper_only=cfg.proper_only)
        anion_lig = cfg.passivation.ligand or "Cl"
        facets, planes = _native_facets_and_planes(
            syms, pts, struct, cfg.charges, facet_seeds, anion_lig, cfg.passivation.surf_tol
        )
        if not planes:
            facets, planes = detect_facets_from_nc(
                syms, pts, struct.lattice, cfg.charges, facet_seeds, cfg.passivation.surf_tol
            )
        return detect_z_type_displacement_options(syms, pts, cfg, struct, planes, str(core_cif_path))
    except Exception as exc:
        logging.error(f"Z-type option detection failed: {exc}", exc_info=True)
        return []


def _detect_surface_post_options_for_xyz(
    xyz_text: str,
    core_cif_path: Path,
    charges: Dict[str, float],
    tmp_path: Path,
    *,
    facets_input: Optional[List] = None,
) -> dict:
    out = {"alloying_options": [], "x_type_options": [], "l_type_options": []}
    if not xyz_text:
        return out
    try:
        from ase.io import read as ase_read
        from pymatgen.core import Structure
        from builder.config import parse_yaml_config
        from builder.facets import detect_facets_from_nc, expand_facets
        from builder.facet_reconstruction import _native_facets_and_planes
        from builder.alloying_posttreat import detect_alloying_options
        from builder.analysis import (
            coord_numbers_bipartite,
            bulk_cn_opposite_by_interior,
            derive_pair_cuts_from_cif,
        )
        from builder.ligand_exchange_posttreat import _bound_hosts
        from builder.neutral_ligand_posttreat import neutral_ligand_host_sites
    except Exception as exc:
        logging.error(f"Post-treatment option imports failed: {exc}")
        return out
    try:
        facets_yaml = format_facets_for_yaml(facets_input) if facets_input else [
            {"hkl": _QuotedStr("100"), "gamma": 1.0, "scope": "family"},
            {"hkl": _QuotedStr("110"), "gamma": 1.0, "scope": "family"},
            {"hkl": _QuotedStr("111"), "gamma": 1.0, "scope": "family"},
        ]
        minimal_yaml = {
            "charges": charges,
            "passivation": _default_passivation_block(ligand=_anion_placeholder_for_cif(core_cif_path)),
            "facets": facets_yaml,
            "symmetry": {"proper_rotations_only": True},
        }
        yaml_path = tmp_path / "post_options_detect.yml"
        yaml_path.write_text(_yaml_dump_canonical(minimal_yaml), encoding="utf-8")
        cfg = parse_yaml_config(str(yaml_path))
        struct = Structure.from_file(str(core_cif_path))
        atoms = ase_read(io.StringIO(xyz_text), format="xyz")
        syms = list(atoms.get_chemical_symbols())
        pts = atoms.get_positions()
        facet_seeds = expand_facets(struct, cfg.seeds, proper_only=cfg.proper_only)
        anion_lig = cfg.passivation.ligand or "Cl"
        _facets, planes = _native_facets_and_planes(
            syms, pts, struct, cfg.charges, facet_seeds, anion_lig, cfg.passivation.surf_tol
        )
        if not planes:
            _facets, planes = detect_facets_from_nc(
                syms, pts, struct.lattice, cfg.charges, facet_seeds, cfg.passivation.surf_tol
            )

        surface = np.zeros(len(pts), bool)
        for normal, d in planes:
            normal = np.asarray(normal, float)
            surface |= ((float(d) - pts @ normal) < float(cfg.passivation.surf_tol))
        pair_cuts = derive_pair_cuts_from_cif(str(core_cif_path), cfg.charges, safety=1.00)
        cn = coord_numbers_bipartite(syms, pts, cfg.charges, pair_cuts=pair_cuts)
        bulk_cn = bulk_cn_opposite_by_interior(
            syms, pts, planes, cfg.passivation.surf_tol, cfg.charges, pair_cuts=pair_cuts
        )
        native = {s.specie.symbol for s in struct.sites}
        non_native_coords = [pts[j] for j, s in enumerate(syms) if s not in native]

        def is_passivated(idx: int, cutoff: float = 3.5) -> bool:
            if not non_native_coords:
                return False
            pos = pts[idx]
            dists = np.linalg.norm(np.asarray(non_native_coords) - pos, axis=1)
            return bool(np.min(dists) < cutoff)

        out["alloying_options"] = detect_alloying_options(syms, pts, cfg, struct, planes)
        for sym in sorted(set(syms)):
            q = int(cfg.charges.get(sym, 0))
            if q == 0:
                continue
            if sym in native:
                available = 0
                for i, s in enumerate(syms):
                    if s != sym or not bool(surface[i]) or is_passivated(i):
                        continue
                    target_cn = int(bulk_cn.get(sym, 0))
                    if target_cn > 0 and int(cn[i]) >= target_cn:
                        continue
                    if not _bound_hosts(syms, pts, i, cfg.charges, pair_cuts):
                        continue
                    available += 1
                source = "native_surface"
            else:
                available = int(sum(1 for s in syms if s == sym))
                source = "placeholder"
            if available <= 0:
                continue
            out["x_type_options"].append({
                "replace": sym,
                "dummy": sym,
                "charge": q,
                "replace_charge": q,
                "ligand_charge": -1 if q < 0 else 1,
                "site_type": "anion" if q < 0 else "cation",
                "available_count": available,
                "source": source,
            })

        # Count L-type sites with the same routine the neutral-ligand pass
        # uses: a surface atom that already carries X-type Cl but still has a
        # free bond is available, which the old "no ligand within 3.5 A" rule
        # missed (CdSe: 24 reported, 72 placeable).
        l_type_options = []
        for sym in sorted(native):
            q = int(cfg.charges.get(sym, 0))
            if q == 0:
                continue
            site_type = "cation" if q > 0 else "anion"
            with contextlib.redirect_stdout(io.StringIO()):
                sites = neutral_ligand_host_sites(
                    syms, pts, cfg, struct, planes, native,
                    target=site_type, target_symbol=sym,
                )
            if sites:
                l_type_options.append({
                    "element": sym,
                    "target_symbol": sym,
                    "target": site_type,
                    "site_type": site_type,
                    "available_count": len(sites),
                })
        out["l_type_options"] = sorted(
            l_type_options,
            key=lambda item: (item["site_type"], item["element"]),
        )
    except Exception as exc:
        logging.error(f"Post-treatment option detection failed: {exc}", exc_info=True)
    return out


def format_facets_for_yaml(facets) -> List[dict]:
    """Normalize facets for nc-builder YAML with quoted hkl and deduplication."""
    seen: set[tuple] = set()
    out: List[dict] = []
    for f in facets or []:
        if hasattr(f, "hkl"):
            h = getattr(f, "hkl")
            g = float(getattr(f, "gamma"))
            sc = getattr(f, "scope", "family")
            term = getattr(f, "termination", None)
        else:
            h = f.get("hkl")
            g = float(f.get("gamma", 0.0))
            sc = f.get("scope", "family")
            term = f.get("termination", None)

        # "stoichiometric" (non-polar) is a CIF-analysis label, not a builder termination
        term = str(term).strip().lower() if term is not None else None
        if term not in ("cation_rich", "anion_rich"):
            term = None

        h_str = _normalize_hkl_string(str(h).strip())
        if sc == "family" and h_str.startswith("-") and term != "anion_rich":
            h_str = h_str.lstrip("-") or h_str

        key = (h_str, term, sc)
        if key in seen:
            continue
        seen.add(key)

        entry: dict = {
            "hkl": _QuotedStr(h_str),
            "gamma": g,
            "scope": sc,
        }
        if term is not None:
            entry["termination"] = term
        out.append(entry)

    # When cation/anion share the same hkl string, force anion to the opposite index
    cation_hkls = [str(e["hkl"]) for e in out if e.get("termination") == "cation_rich"]
    for entry in out:
        if entry.get("termination") != "anion_rich":
            continue
        h_str = str(entry["hkl"])
        for cat_h in cation_hkls:
            if h_str == cat_h:
                entry["hkl"] = _QuotedStr(_opposite_compact_hkl(cat_h))
                break

    return out


def _anion_placeholder(native_elements) -> str:
    """Anion ligand placeholder: Cl, unless Cl is a native species (CsPbCl3)."""
    native = set(native_elements or ())
    for sym in ("Cl", "Br", "I", "F"):
        if sym not in native:
            return sym
    return "Cl"


def _anion_placeholder_for_cif(cif_path) -> str:
    try:
        from pymatgen.core import Structure
        return _anion_placeholder({site.specie.symbol for site in Structure.from_file(str(cif_path)).sites})
    except Exception:
        return "Cl"


def _default_passivation_block(*, include_cation_ligand: bool = False, ligand: str = "Cl") -> dict:
    block = {
        "ligand": ligand,
        "surf_tol": 2.0,
        "prepass_mode": "role-aware",
        "prepass_min_cn_terrace": 3,
        "prepass_min_cn_edge": 2,
        "prepass_min_cn_vertex": 1,
    }
    if include_cation_ligand:
        block["cation_ligand"] = "Rb"
    return block


def _dist_string(jobs: List[LigJob], mode: str) -> str:
    xs = [f"{float(max(0.0, j.ratio)):.6g}" for j in jobs if j.smiles.strip()]
    if not xs:
        xs = ["1"]
    mode = (mode or "uniform").lower()
    if mode not in {"uniform", "segmented", "random"}:
        mode = "uniform"
    return ":".join(xs + [mode])

def run_capper_cli(script_path: Path, xyz_text: str, jobs: List[LigJob],
                   dummy: str, dist_mode: str, workdir: Path) -> Tuple[str, str, str]:
    """Return (capped_xyz, cap_log, out_name)."""
    qd_path = workdir / "qd_for_capping.xyz"
    qd_path.write_text(xyz_text, encoding="utf-8")

    out_prefix = workdir / f"capped_{dummy.lower()}"
    smiles = [j.smiles.strip() for j in jobs if j.smiles.strip()]
    if not smiles:
        return xyz_text, "[cap] No ligands provided; skipping.", ""

    # Use system-wide miniCAT CLI (on PATH) instead of the bundled script
    exe = shutil.which("miniCAT")
    if not exe:
        raise RuntimeError("miniCAT executable not found on PATH. Activate the env where miniCAT is installed.")

    # We assume miniCAT exposes a 'passivate' subcommand compatible with attach_from_smiles
    cmd = [
        exe, 
        "--qd", str(qd_path),
        "--out_prefix", str(out_prefix),
        "--job-ligands", *smiles,
        "--job-dummy", dummy,
        "--job-dist", _dist_string(jobs, dist_mode),
    ]
    p = subprocess.run(cmd, cwd=str(workdir), text=True, capture_output=True)
    log = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")

    candidates = [f"{out_prefix}_final.xyz", f"{out_prefix}.xyz", f"{out_prefix}_capped.xyz"]
    xyz_out, out_name = None, ""
    for cand in candidates:
        cp = Path(cand)
        if cp.exists() and cp.stat().st_size > 0:
            xyz_out = cp.read_text(encoding="utf-8")
            out_name = cp.name
            break

    if p.returncode != 0 or not xyz_out:
        raise RuntimeError(f"Capper failed (rc={p.returncode}).\n{log}")
    return xyz_out, log, out_name

def run_in_memory_capper(xyz_text: str, jobs: List[LigJob], default_dummy: str, dist_mode: str, out_stream=sys.stdout) -> str:
    """Runs miniCAT natively in memory and streams its logs to out_stream."""
    if not jobs:
        print("[cap] No ligands provided.", file=out_stream)
        return xyz_text
    
    valid_jobs = [j for j in jobs if j.smiles.strip()]
    if not valid_jobs:
        print("[cap] No valid SMILES.", file=out_stream)
        return xyz_text

    args = argparse.Namespace(
        seed=1337, ff="uff", refinement_passes=3, neigh=8,
        coarse_step_deg=20.0, sterics_mode="vdw", sterics_margin=0.25,
        warn_tol=1.4, adaptive_offset_steps=4, adaptive_offset_step=0.15,
        anchor_mode="dummy", offset_out=0.0, bond_len_override=None,
        neighbor_repulsion=0.5
    )
    reg = get_fg_registry()

    smiles_list = [j.smiles.strip() for j in valid_jobs]
    ratios = [j.ratio for j in valid_jobs]
    dummy = valid_jobs[0].dummy.strip() if valid_jobs[0].dummy else default_dummy
    
    # Redirect prints directly to our stream queue
    with contextlib.redirect_stdout(out_stream), contextlib.redirect_stderr(out_stream):
        print(f"[cap] Passivating {dummy} sites natively with {smiles_list} (mode={dist_mode})")
        precomputed_ligands = []
        role = None
        for sm in smiles_list:
            mol_neutral = smiles_to_3d_mol(_sanitize_simple_acid_smiles(sm), args.seed, args.ff)
            fg_matches = detect_fg_matches_neutral(mol_neutral, 'anion', reg) or detect_fg_matches_neutral(mol_neutral, 'cation', reg)
            if not fg_matches:
                print(f"No recognizable functional group for {sm}")
                continue
            ionic_mol, (fg_active, match_active) = build_per_site_variant(fg_matches, mol_neutral, 0, args.ff)
            precomputed_ligands.append({"mol": ionic_mol, "fg": fg_active, "match": match_active})
            if role is None:
                role = fg_matches[0][0].role

        job_dict = {
            "smiles": smiles_list, "dummy": dummy, "role": role,
            "ratios": ratios, "strategy": dist_mode, "precomputed_ligands": precomputed_ligands
        }
        
        current_qd = ase_read(io.StringIO(xyz_text), format="xyz")
        current_qd = execute_passivation_job(current_qd, job_dict, args)
        
        out_xyz = io.StringIO()
        ase_write(out_xyz, current_qd, format="xyz")
        
    return out_xyz.getvalue()


# ---------------------------------------------------------------------
# Route: build
# ---------------------------------------------------------------------
@app.post("/api/build", response_class=JSONResponse)
async def build_nanocrystal(files: List[UploadFile] = File(...), options: str = Form(...)):
    try:
        opts = BuildOptions.parse_raw(options)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid options JSON: {e}")
    try:
        _validate_neutral_exchange_jobs(opts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    tmpdir = tempfile.mkdtemp(prefix="qdb_")
    logging.info(f"Temporary directory created at: {tmpdir}")

    try:
        tmp_path = Path(tmpdir)

        # Save uploads
        file_map: Dict[str, Path] = {}
        for uploaded_file in files:
            s_filename = safe_filename(uploaded_file.filename)
            file_path = tmp_path / s_filename
            file_path.write_bytes(await uploaded_file.read())
            file_map[s_filename] = file_path

        # Core
        core_path = file_map.get(safe_filename(opts.core_cif_filename))
        if not core_path:
            raise HTTPException(404, f"Core file '{opts.core_cif_filename}' not found.")

        charges = parse_cif_oxidation_numbers(core_path.read_text("utf-8", "ignore"))
        core_elements = set(charges.keys())
        shell_elements: set[str] = set()
        positive_q_mode_eff = _positive_q_mode_for_opts(opts)

        import yaml

        # ---------------- First pass (info) ----------------
        logging.info("Running first pass to gather info...")
        first_pass_charges = charges.copy()
        if "Cl" not in first_pass_charges:
            first_pass_charges["Cl"] = -1.0

        temp_yaml_dict = {
            "shape": {"aspect": opts.aspect},
            "facets": format_facets_for_yaml(opts.facets),
            "charges": first_pass_charges,
            "passivation": {"ligand": "Cl", "surf_tol": 2.0},
        }
        if opts.size_unit_cells is not None:
            temp_yaml_dict["size_unit_cells"] = opts.size_unit_cells

        temp_yaml_path = tmp_path / "temp_config.yml"
        temp_yaml_path.write_text(yaml.safe_dump(temp_yaml_dict, sort_keys=False), encoding="utf-8")

        first_pass_output_file = "final.xyz"
        first_pass_cmd = [
            "nc-builder",
            str(core_path.resolve()),
            str(temp_yaml_path.resolve()),
        ]
        if opts.size_unit_cells is None and opts.radius_A is not None:
            first_pass_cmd += ["-r", f"{opts.radius_A:.4f}"]
        first_pass_cmd += [
            "-o",
            str((tmp_path / first_pass_output_file).resolve()),
            "--positive-q-mode",
            positive_q_mode_eff,
            "--center",
            "--write-all",
            "--verbose",
        ]
        p1_ok, p1_log, _ = execute_builder_command(first_pass_cmd, tmpdir, first_pass_output_file)
        if not p1_ok:
            return JSONResponse(status_code=500, content={"status": "failed", "log": p1_log})

        # ---------------- Second pass (final build) ----------------
        final_charges = charges.copy()
        if "Cl" not in final_charges:
            final_charges["Cl"] = -1.0
        if "Rb" not in final_charges:
            final_charges["Rb"] = 1.0
        _augment_charges_for_neutral_exchange(final_charges, opts)

        passivation_block = {"ligand": "Cl", "surf_tol": 2.0}

        if not opts.shells:
            yaml_dict = {
                "shape": {"aspect": opts.aspect},
                "facets": format_facets_for_yaml(opts.facets),
                "charges": final_charges,
                "passivation": passivation_block,
            }
            if opts.size_unit_cells is not None:
                yaml_dict["size_unit_cells"] = opts.size_unit_cells
            if opts.center_ion:
                yaml_dict["construction_origin"] = {"center_on_species": opts.center_ion}
            cmd = ["nc-builder", str(core_path.resolve())]
        else:
            core_mat = {
                "name": "core",
                "cif": str(core_path.resolve()),
                "facets": format_facets_for_yaml(opts.facets),
                "shape": {"aspect": opts.aspect},
            }
            if opts.size_unit_cells is not None:
                core_mat["size_unit_cells"] = opts.size_unit_cells
            materials = [core_mat]
            outermost_shell_path = core_path

            for i, shell in enumerate(opts.shells):
                shell_cif_path = file_map.get(safe_filename(shell.material_cif))
                if not shell_cif_path:
                    raise HTTPException(404, f"Shell material '{shell.material_cif}' not found.")

                shell_mat = {
                    "name": f"shell{i+1}",
                    "cif": str(shell_cif_path.resolve()),
                    "facets": format_facets_for_yaml(shell.facets) or "inherit",
                    "shape": {"aspect": shell.aspect},
                }
                if getattr(shell, "size_unit_cells", None) is not None:
                    shell_mat["size_unit_cells"] = shell.size_unit_cells
                materials.append(shell_mat)

                shell_charges = parse_cif_oxidation_numbers(shell_cif_path.read_text("utf-8", "ignore"))
                final_charges.update(shell_charges)
                shell_elements.update(shell_charges.keys())
                outermost_shell_path = shell_cif_path

            yaml_dict = {
                "materials": materials,
                "charges": final_charges,
                "symmetry": {"proper_rotations_only": True},
                "facet_options": {"pair_opposites": True},
                "passivation": passivation_block,
            }
            cmd = ["nc-builder", str(outermost_shell_path.resolve())]

        final_yaml_path = tmp_path / "config.yml"
        final_yaml_path.write_text(yaml.safe_dump(yaml_dict, sort_keys=False), encoding="utf-8")
        logging.info(f"Generated FINAL YAML config:\n{final_yaml_path.read_text()}")

        final_output_file = "final.xyz"
        cmd_extend = [
            str(final_yaml_path.resolve()),
        ]
        if opts.size_unit_cells is None and opts.radius_A is not None:
            cmd_extend += ["-r", f"{opts.radius_A:.4f}"]
        cmd_extend += [
            "-o",
            str((tmp_path / final_output_file).resolve()),
            "--positive-q-mode",
            positive_q_mode_eff,
            "--write-all",
            "--center",
            "--verbose",
        ]
        cmd.extend(cmd_extend)
        if opts.shells:
            cmd.extend(["--core-lattice-fit", "--core-strain-width", "2.5", "--core-center", "com"])

        ok, log, out_files = execute_builder_command(cmd, tmpdir, final_output_file)

        xyz_passivated_content = out_files.get("final").read_text() if out_files.get("final") else None
        xyz_unpassivated_content = out_files.get("cut").read_text() if out_files.get("cut") else None

        full_log = p1_log + "\n--- Second Pass ---\n" + log
        raw_log = full_log

        if not ok:
            return JSONResponse(status_code=500, content={"status": "failed", "log": raw_log})

        elements, total_charge = "unknown", 0
        grouped_counts: Dict[str, Any] = {}



        if xyz_passivated_content:
            try:
                from ase.io import read as ase_read

                atoms = ase_read(io.StringIO(xyz_passivated_content), format="xyz")
                symbols = atoms.get_chemical_symbols()
                elements = ",".join(sorted(set(symbols)))
                total_charge = sum(final_charges.get(s, 0.0) for s in symbols)
                grouped_counts = _count_grouped_xyz(xyz_passivated_content, core_elements, shell_elements)
            except Exception as e:
                logging.error(f"Could not parse passivated XYZ or calculate charge: {e}")

        # ---------- Organic passivation from SMILES (optional) ----------
        CAP_SCRIPT = None 
 
        cap_logs: List[str] = []
        current_xyz = xyz_passivated_content or xyz_unpassivated_content or ""
        download_name = None 
        try:
            if opts.cap_anionic_jobs:
                current_xyz, log1, name1 = run_capper_cli(
                    CAP_SCRIPT, current_xyz, opts.cap_anionic_jobs or [],
                    dummy="Cl", dist_mode=(opts.cap_distribution or "uniform"),
                    workdir=tmp_path
                )
                cap_logs.append(log1)
                download_name = name1 or download_name
        
            if opts.cap_cationic_jobs:
                current_xyz, log2, name2 = run_capper_cli(
                    CAP_SCRIPT, current_xyz, opts.cap_cationic_jobs or [],
                    dummy="Rb", dist_mode=(opts.cap_distribution or "uniform"),
                    workdir=tmp_path
                )
                cap_logs.append(log2)
                download_name = name2 or download_name
        
            if cap_logs:
                xyz_passivated_content = current_xyz
                # recompute metadata on capped structure
                from ase.io import read as ase_read

                atoms = ase_read(io.StringIO(current_xyz), format="xyz")
                symbols = atoms.get_chemical_symbols()
                elements = ",".join(sorted(set(symbols)))
                total_charge = sum(final_charges.get(s, 0.0) for s in symbols)
                grouped_counts = _count_grouped_xyz(current_xyz, core_elements, shell_elements)
                raw_log += "\n--- Organic capping ---\n" + "\n".join(cap_logs)

        except Exception as e:
            logging.exception("Capping step failed")
            raw_log += f"\n[cap][error] {e}"
        # -----------------------------------------------------------------

        # ---- compact summary ----
        init_charge = 0.0
        if xyz_unpassivated_content:
            init_charge = _charge_of_xyz(xyz_unpassivated_content, final_charges)

        cl_n = grouped_counts.get("ligand", {}).get("by_element", {}).get("Cl", 0)
        rb_n = grouped_counts.get("ligand", {}).get("by_element", {}).get("Rb", 0)
        core_comp = grouped_counts.get("core", {}).get("by_element", {})
        shell_comp = grouped_counts.get("shell", {}).get("by_element", {})

        summary_lines = [
            "Summary:",
            f"- Atoms total: {grouped_counts.get('total_atoms', 'NA')}",
            f"- Core:  {grouped_counts.get('core', {}).get('total', 0)}  | "
            + " ".join(f"{k}:{v}" for k, v in sorted(core_comp.items())),
            f"- Shell: {grouped_counts.get('shell', {}).get('total', 0)} | "
            + " ".join(f"{k}:{v}" for k, v in sorted(shell_comp.items())),
            f"- Ligand placeholders: Cl={cl_n}, Rb={rb_n}",
            f"- Charge: initial≈{round(init_charge)}, final≈{round(total_charge)}",
        ]
        raw_log = (raw_log + "\n" + "\n".join(summary_lines)).strip()

        return JSONResponse(
            content={
                "status": "success",
                "log": raw_log,
                "elements": elements,
                "xyz_passivated": xyz_passivated_content,
                "xyz_unpassivated": xyz_unpassivated_content,
                "total_charge": round(total_charge),
                "grouped_counts": grouped_counts,
                "download_name": download_name or "final.xyz"
            }
        )

    finally:
        logging.info(f"Cleaning up temporary directory: {tmpdir}")
        # shutil.rmtree(tmpdir)

class CapOnlyOptions(BaseModel):
    cap_distribution: Optional[str] = "uniform"
    cap_anionic_jobs: Optional[List[LigJob]] = None
    cap_cationic_jobs: Optional[List[LigJob]] = None

@app.post("/api/passivate")
async def passivate_endpoint(
    xyz_file: UploadFile = File(...),
    options: str = Form(...),
):
    """
    JSON in, JSON out. Response shape:
      {
        "status": "success" | "failed",
        "cmd": "python -u miniCAT --input ... --distribution ... --anion ... --ratio ...",
        "xyz_passivated": "<XYZ text>",                # on success
        "download_name": "capped_final.xyz",           # on success
        "log": "...",                                  # optional text log
        "error": "message", "traceback": "..."         # on failure
      }
    """

    # --- helper: normalize incoming jobs (dicts/objects) to attribute-style objects ---
    def _normalize_jobs(jobs):
        """
        Accepts a list of dicts or objects with (smiles, ratio) and
        returns a list of SimpleNamespace(smiles=..., ratio=float).
        Drops entries with empty smiles.
        """
        norm = []
        for j in jobs or []:
            if isinstance(j, dict):
                s = (j.get("smiles") or "").strip()
                r = float(j.get("ratio") or 0)
            else:
                s = (getattr(j, "smiles", "") or "").strip()
                r = float(getattr(j, "ratio", 0) or 0)
            if s:
                norm.append(SimpleNamespace(smiles=s, ratio=r))
        return norm

    try:
        cfg = json.loads(options or "{}")
    except Exception as e:
        return JSONResponse({"status": "failed", "error": f"Invalid options JSON: {e}"}, status_code=400)

    tmpdir = tempfile.mkdtemp(prefix="qdb_pass_")
    tmp = Path(tmpdir)
    pseudo_cmd = None  # filled before running so we can echo it even on failure

    try:
        # --- write incoming XYZ to disk ---
        xyz_path = tmp / (xyz_file.filename or "input.xyz")
        xyz_bytes = await xyz_file.read()
        xyz_path.write_bytes(xyz_bytes)

        # --- read + normalize options ---
        raw_anionic  = cfg.get("cap_anionic_jobs")  or []
        raw_cationic = cfg.get("cap_cationic_jobs") or []
        dist         = (cfg.get("cap_distribution") or "uniform").lower()
        if dist not in {"uniform", "segmented", "random"}:
            dist = "uniform"

        anionic  = _normalize_jobs(raw_anionic)
        cationic = _normalize_jobs(raw_cationic)

        # --- build a human-readable command we will echo back ---
        CAP_SCRIPT = None  

        exe_shown = shutil.which("miniCAT") or "miniCAT"
        
        # show two sequential miniCAT calls (anionic then cationic), matching how run_capper_cli is invoked
        def _dist_str(jobs):  # reuse same allocation logic for the display string
            return _dist_string(jobs, dist)
        
        an_cmd = f'{exe_shown} passivate --qd "{xyz_path}" --out_prefix "{(tmp / "capped_cl")}" --job-ligands ' + \
                 " ".join(j.smiles for j in anionic) + f' --job-dummy Cl --job-dist "{_dist_str(anionic)}"' if anionic else ""
        ca_cmd = f'{exe_shown} passivate --qd "{xyz_path}" --out_prefix "{(tmp / "capped_rb")}" --job-ligands ' + \
                 " ".join(j.smiles for j in cationic) + f' --job-dummy Rb --job-dist "{_dist_str(cationic)}"' if cationic else ""
        
        pseudo_cmd = " && ".join([c for c in (an_cmd, ca_cmd) if c])
        if not pseudo_cmd:
            pseudo_cmd = f"{exe_shown} passivate (no ligands provided)"

        # --- run passivation using your helper (no external shell needed) ---
        current_xyz = xyz_path.read_text()
        log_chunks = []

        def run_cap(jobs, ion_label):
            nonlocal current_xyz
            if not jobs:
                return None
            # run_capper_cli must accept (script_path, xyz_text, jobs, ion_symbol, dist, workdir)
            xyz_out, cap_log, out_name = run_capper_cli(
                CAP_SCRIPT, current_xyz, jobs, ion_label, dist, tmp
            )
            current_xyz = xyz_out
            if cap_log:
                log_chunks.append(cap_log)
            return out_name

        name1 = run_cap(anionic,  "Cl")
        name2 = run_cap(cationic, "Rb")
        dl_name = name2 or name1 or "capped_final.xyz"

        # --- corrected total charge (ligands: anion = -1, cation = +1) ---
        before_counts = _xyz_count_symbols(xyz_path.read_text(), targets=("Cl","Rb"))
        after_counts  = _xyz_count_symbols(current_xyz,       targets=("Cl","Rb"))

        n_anionic  = max(0, before_counts.get("Cl", 0) - after_counts.get("Cl", 0))
        n_cationic = max(0, before_counts.get("Rb", 0) - after_counts.get("Rb", 0))

        elem_charge = {"Cl": -1.0, "Rb": +1.0}
        raw_total = 0.0
        for line in current_xyz.splitlines()[2:]:
            parts = line.split()
            if parts:
                raw_total += elem_charge.get(parts[0], 0.0)

        total_charge = int(round(raw_total + (-1)*n_anionic + (+1)*n_cationic))

        ligand_detail = {
            "anionic":  _allocate_counts_by_ratio(n_anionic,  anionic),
            "cationic": _allocate_counts_by_ratio(n_cationic, cationic),
            "total": int(n_anionic + n_cationic),
        }
        
        return JSONResponse({
            "status": "success",
            "cmd": pseudo_cmd,
            "xyz_passivated": current_xyz,
            "download_name": dl_name,
            "log": "\n".join(log_chunks)[:200000],
            "total_charge": total_charge,   # ← include it
            "ligand_detail": ligand_detail, 
        })

    except Exception as e:
        tb = traceback.format_exc(limit=8)
        return JSONResponse({
            "status": "failed",
            "error": str(e),
            "traceback": tb,
            "cmd": pseudo_cmd or "N/A",
        }, status_code=500)
    finally:
        # Keep tmpdir for debugging? Comment next line to keep artifacts.
        # shutil.rmtree(tmpdir, ignore_errors=True)
        pass


# #####################################################################
# ###                  CORRECTED STREAMING ROUTE                    ###
# #####################################################################
#
# The placeholder function has been removed and the @app.post decorator
# is now on the real implementation below.
@app.post("/api/build_stream")

async def build_nanocrystal_stream(
    files: List[UploadFile] = File(...),
    options: str = Form(...),
    mode: str = Form("quiet"), # "quiet" (fast, default), "live-tty", or "live-pipe"
    positive_q_mode: str = Form("remove")
):
    """
    NDJSON stream:
      {"event":"status","line":"accepted"}           # flushed immediately
      {"event":"diag","files":[...],"shells":[...]}  # what server sees
      {"event":"cmd","line":"nc-builder ..."}        # the single run
      {"event":"log","line":"..."}                   # only in live modes
      {"event":"result", ...payload...}
    """

    try:
        opts = BuildOptions.parse_raw(options)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid options JSON: {e}")
    try:
        _validate_neutral_exchange_jobs(opts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    tmpdir = tempfile.mkdtemp(prefix="qdb_stream_")
    tmp_path = Path(tmpdir)

    # ---- READ & BUFFER UPLOADS BEFORE streaming (prevents closed-body errors) ----
    buffered_uploads: List[Tuple[str, bytes]] = []
    for uf in files:
        fname = safe_filename(uf.filename)
        data = await uf.read()
        buffered_uploads.append((fname, data))

    async def _run():
        # Always flush headers immediately so frontend won't see "Failed to fetch"
        yield json.dumps({"event": "status", "line": "accepted"}) + "\n"

        try:
            # ---- WRITE buffered uploads to disk inside the generator ----
            file_map: Dict[str, Path] = {}
            for fname, data in buffered_uploads:
                fp = tmp_path / fname
                fp.write_bytes(data)
                file_map[fname] = fp

            # Small diagnostic to help catch filename mismatches for shells
            try:
                diag = {
                    "files": sorted(list(file_map.keys())),
                    "core_expected": getattr(opts, "core_cif_filename", None),
                    "shells_expected": [getattr(sh, "material_cif", None) for sh in (opts.shells or [])],
                }
                yield json.dumps({"event": "diag", **diag}) + "\n"
            except Exception:
                pass

            core_basename = safe_filename(opts.core_cif_filename)
            core_path = file_map.get(core_basename)
            if not core_path:
                yield json.dumps({"event":"log","line": f"[error] Core file '{opts.core_cif_filename}' not found among uploaded: {', '.join(file_map)}"}) + "\n"
                yield json.dumps({"event":"result","status":"failed"}) + "\n"
                return

            # ---- Charges and bookkeeping ----
            charges = parse_cif_oxidation_numbers(core_path.read_text("utf-8", "ignore"))
            core_elements = set(charges.keys())
            shell_elements: set[str] = set()

            post_treatment = _build_post_treatment_from_opts(opts)
            is_repassivate = bool(
                getattr(opts, "skip_core_build", False) and getattr(opts, "xyz_unpassivated", None)
            )

            # ---- Build ONE YAML (core-only OR core@shell) ----
            posq_early = _positive_q_mode_for_opts(opts, positive_q_mode)
            needs_rb = _needs_rb_in_recipe(opts, posq_early, repassivate_only=is_repassivate)

            final_charges = charges.copy()
            if opts.shells:
                for sh in opts.shells:
                    shell_name = getattr(sh, "material_cif", "")
                    sp = file_map.get(safe_filename(shell_name))
                    if sp:
                        sc = parse_cif_oxidation_numbers(sp.read_text("utf-8", "ignore"))
                        final_charges.update(sc)
                        shell_elements.update(sc.keys())

            anion_ph = _anion_placeholder(core_elements | shell_elements)
            final_charges.setdefault(anion_ph, -1.0)
            if needs_rb:
                final_charges.setdefault("Rb", 1.0)
            for job in opts.alloying_jobs or []:
                if job.replacement.strip():
                    final_charges.setdefault(job.replacement.strip(), int(job.replacement_charge))
            _augment_charges_for_neutral_exchange(final_charges, opts)

            pass_defaults = _default_passivation_block(include_cation_ligand=needs_rb, ligand=anion_ph)
            if anion_ph != "Cl":
                yield json.dumps({"event": "log", "line": f"[info] Cl is native here; using {anion_ph} as the anion ligand placeholder"}) + "\n"

            # ---- Repassivation-only: post-treatment on stored XYZ (no Wulff rebuild) ----
            if is_repassivate:
                minimal_yaml = {"charges": final_charges}
                if post_treatment:
                    minimal_yaml["post_treatment"] = post_treatment
                yaml_text = _yaml_dump_canonical(minimal_yaml)
                yield json.dumps({"event": "yaml_preview", "text": yaml_text}) + "\n"
                yield json.dumps({"event": "log", "line": "[yaml] Repassivation recipe (post_treatment only)"}) + "\n"
                yield json.dumps({"event": "cmd", "line": "post-treatment: ligand exchange on existing XYZ"}) + "\n"
                yield json.dumps({
                    "event": "log",
                    "line": "[system] Reusing built core; applying post-treatment only...",
                }) + "\n"

                log_queue = queue.Queue()
                facets_for_repass = [
                    f.dict() if hasattr(f, "dict") else f
                    for f in (opts.facets or [])
                ]
                outermost_shell_path = core_path
                if opts.shells:
                    for sh in opts.shells:
                        shell_name = getattr(sh, "material_cif", "")
                        sp = file_map.get(safe_filename(shell_name))
                        if sp:
                            outermost_shell_path = sp

                import time as _time
                _t0 = _time.monotonic()

                def worker():
                    try:
                        xyz_res, ledg_res = _run_repassivation_posttreatment(
                            opts.xyz_unpassivated,
                            outermost_shell_path,
                            final_charges,
                            post_treatment,
                            tmp_path,
                            facets_input=facets_for_repass,
                            log_sink=log_queue,
                        )
                        log_queue.put(("DONE", xyz_res, ledg_res))
                    except Exception as ex:
                        tb = traceback.format_exc(limit=6)
                        log_queue.put(("ERROR", str(ex), tb))

                t = threading.Thread(target=worker)
                t.start()

                xyz_pass = None
                ledger = []
                try:
                    while True:
                        items = []
                        while not log_queue.empty():
                            try:
                                items.append(log_queue.get_nowait())
                            except queue.Empty:
                                break

                        stop = False
                        for item in items:
                            if isinstance(item, tuple) and item[0] in ("DONE", "ERROR"):
                                if item[0] == "DONE":
                                    xyz_pass = item[1]
                                    ledger = item[2]
                                else:
                                    raise Exception(f"{item[1]}\n{item[2]}")
                                stop = True
                            else:
                                for line in item.splitlines():
                                    if line.strip():
                                        yield json.dumps({"event": "log", "line": line}) + "\n"

                        if stop:
                            break
                        if not t.is_alive() and log_queue.empty():
                            break

                        await asyncio.sleep(0.05)
                except Exception as e:
                    yield json.dumps({"event": "log", "line": f"[error] Repassivation failed: {e}"}) + "\n"
                    yield json.dumps({"event": "result", "status": "failed", "error": str(e)}) + "\n"
                    return

                yield json.dumps({
                    "event": "log",
                    "line": f"[system] Post-treatment finished in {_time.monotonic() - _t0:.1f}s",
                }) + "\n"

                xyz_un = opts.xyz_unpassivated
                cmd = ["post-treatment: ligand exchange"]
                final_out = tmp_path / "repassivated.xyz"
                final_out.write_text(xyz_pass, encoding="utf-8")

                elements, total_charge, grouped_counts = "unknown", 0, {}
                try:
                    from ase.io import read as ase_read
                    atoms = ase_read(io.StringIO(xyz_pass), format="xyz")
                    symbols = atoms.get_chemical_symbols()
                    elements = ",".join(sorted(set(symbols)))
                    total_charge = sum(final_charges.get(s, 0.0) for s in symbols)
                    grouped_counts = _count_grouped_xyz(xyz_pass, core_elements, shell_elements)
                except Exception as e:
                    logging.error(f"XYZ parse fail after repassivation: {e}")

                anionic_detail, cationic_detail = {}, {}
                z_type_detail = {}
                for entry in ledger:
                    if entry.get("z_type"):
                        formula = entry.get("formula")
                        if formula:
                            z_type_detail[formula] = z_type_detail.get(formula, 0) + int(entry.get("removed", 0))
                        continue
                    sm = entry.get("smiles")
                    chg = entry.get("charge", 0)
                    if sm:
                        if chg < 0:
                            anionic_detail[sm] = anionic_detail.get(sm, 0) + 1
                        else:
                            cationic_detail[sm] = cationic_detail.get(sm, 0) + 1
                ligand_detail = {
                    "anionic": anionic_detail,
                    "cationic": cationic_detail,
                    "neutral": {},
                    "z_type": z_type_detail,
                    "total": sum(anionic_detail.values()) + sum(cationic_detail.values()),
                }
                z_type_options = _detect_z_type_options_for_xyz(
                    opts.xyz_unpassivated,
                    outermost_shell_path,
                    final_charges,
                    tmp_path,
                    facets_input=facets_for_repass,
                )
                post_options = _detect_surface_post_options_for_xyz(
                    opts.xyz_unpassivated,
                    outermost_shell_path,
                    final_charges,
                    tmp_path,
                    facets_input=facets_for_repass,
                )

                payload = {
                    "status": "success",
                    "elements": elements,
                    "xyz_passivated": xyz_pass,
                    "xyz_unpassivated": xyz_un,
                    "xyz_dummy": xyz_pass,
                    "total_charge": round(total_charge),
                    "grouped_counts": grouped_counts,
                    "download_name": "repassivated.xyz",
                    "last_command": " ".join(cmd),
                    "ligand_detail": ligand_detail,
                    "z_type_options": z_type_options,
                    **post_options,
                    "reconstruction": next(
                        (e for e in ledger if e.get("surface_reconstruction")), None
                    ),
                    "size_metrics": None,
                }
                yield json.dumps({"event": "result", **payload}) + "\n"
                return

            if not opts.shells:
                # Core-only schema
                facets_input = [f.dict() if hasattr(f, "dict") else f for f in (opts.facets or [])]
                if not facets_input:
                    facets_input = [
                        {"hkl": "100", "gamma": 1.0, "scope": "family"},
                        {"hkl": "110", "gamma": 1.0, "scope": "family"},
                        {"hkl": "111", "gamma": 1.0, "scope": "family"},
                    ]

                yaml_dict = {
                    "facets": format_facets_for_yaml(facets_input),
                    "charges": final_charges,
                    "passivation": pass_defaults,
                    "symmetry": {"proper_rotations_only": True},
                }
                if not _aspect_is_unity(opts.aspect):
                    yaml_dict["shape"] = {"aspect": opts.aspect}
                if opts.size_unit_cells is not None:
                    yaml_dict["size_unit_cells"] = opts.size_unit_cells
                if opts.center_ion:
                    yaml_dict["construction_origin"] = {"center_on_species": opts.center_ion}
                root_path = core_path

            else:
                # Core@shell schema
                core_mat = {
                    "name": "core",
                    "cif": str(core_path.resolve()),
                    "facets": format_facets_for_yaml(
                        [f.dict() if hasattr(f, "dict") else f for f in opts.facets]
                    ),
                }
                if not _aspect_is_unity(opts.aspect):
                    core_mat["shape"] = {"aspect": opts.aspect}
                if opts.size_unit_cells is not None:
                    core_mat["size_unit_cells"] = opts.size_unit_cells
                materials = [core_mat]
                outer = core_path
                for i, sh in enumerate(opts.shells):
                    shell_name = getattr(sh, "material_cif", "")
                    sp = file_map.get(safe_filename(shell_name))
                    if not sp:
                        yield json.dumps({"event":"log","line": f"[error] Shell '{shell_name}' not found among uploaded: {', '.join(file_map)}"}) + "\n"
                        yield json.dumps({"event":"result","status":"failed"}) + "\n"
                        return
                    shell_aspect = getattr(sh, "aspect", None) or [1.0, 1.0, 1.0]
                    shell_mat = {
                        "name":  f"shell{i+1}",
                        "cif":   str(sp.resolve()),
                        "facets": format_facets_for_yaml(
                            [f.dict() if hasattr(f, "dict") else f for f in (sh.facets or [])]
                        ) or "inherit",
                    }
                    if not _aspect_is_unity(shell_aspect):
                        shell_mat["shape"] = {"aspect": shell_aspect}
                    if getattr(sh, "size_unit_cells", None) is not None:
                        shell_mat["size_unit_cells"] = sh.size_unit_cells
                    if getattr(sh, "interface_type", "abrupt") == "mixed":
                        shell_mat["interface"] = {
                            "type": "mixed",
                            "mixing_width": getattr(sh, "interface_mixing_width", 3.0) or 3.0,
                            "mixing_ratio": getattr(sh, "interface_mixing_ratio", 0.5) or 0.5
                        }
                    else:
                        shell_mat["interface"] = {
                            "type": "abrupt"
                        }
                    materials.append(shell_mat)
                    sc = parse_cif_oxidation_numbers(sp.read_text("utf-8", "ignore"))
                    final_charges.update(sc)
                    shell_elements.update(sc.keys())
                    outer = sp

                yaml_dict = {
                    "materials": materials,
                    "charges": final_charges,
                    "symmetry": {"proper_rotations_only": True},
                    "facet_options": {"pair_opposites": True},
                    "passivation": pass_defaults,
                }
                if opts.center_ion:
                    yaml_dict["construction_origin"] = {"center_on_species": opts.center_ion}
                root_path = outer

            # Post-treatment (ligand exchange, etc.) runs on Repassivate only — not during Wulff build
            if post_treatment and (
                (opts.cap_anionic_jobs and any(j.smiles.strip() for j in opts.cap_anionic_jobs))
                or (opts.cap_cationic_jobs and any(j.smiles.strip() for j in opts.cap_cationic_jobs))
                or opts.z_type_enabled
                or opts.neutral_enabled
                or opts.reconstruction_enabled
            ):
                yield json.dumps({
                    "event": "log",
                    "line": "[system] Ligand exchange and other post-treatments run on Repassivate (not during Wulff build).",
                }) + "\n"

            final_yaml = tmp_path / "config.yml"
            yaml_text = _yaml_dump_canonical(yaml_dict)
            final_yaml.write_text(yaml_text, encoding="utf-8")
            yield json.dumps({"event": "yaml_preview", "text": yaml_text}) + "\n"
            yield json.dumps({"event": "log", "line": "[yaml] Generated config.yml (see preview above)"}) + "\n"

            final_out = tmp_path / "final.xyz"
            posq = _positive_q_mode_for_opts(opts, positive_q_mode)

            class LineQueueWriter(io.TextIOBase):
                def __init__(self, q): self.q, self.buf = q, ""
                def write(self, s):
                    self.buf += s
                    while "\n" in self.buf:
                        line, self.buf = self.buf.split("\n", 1)
                        self.q.put(line)
                    return len(s)
                def flush(self):
                    if self.buf: self.q.put(self.buf); self.buf = ""

            # ---- Run nc-builder (full Wulff build) ----
            cmd = [
                "nc-builder", str(root_path.resolve()), str(final_yaml.resolve()),
            ]
            if opts.size_unit_cells is None and opts.radius_A is not None:
                cmd += ["-r", f"{opts.radius_A:.4f}"]
            cmd += [
                "-o", str(final_out.resolve()),
                "--write-all", "--center", "--positive-q-mode", posq,
            ]
            if (mode or "quiet").strip() == "live-tty":
                cmd += ["--verbose"]
            if opts.shells:
                cmd += ["--core-lattice-fit", "--core-strain-width", "2.5", "--core-center", "com"]

            yield json.dumps({"event": "cmd", "line": " ".join(cmd)}) + "\n"

            log_queue = queue.Queue()

            def _run_builder_sync():
                qw = LineQueueWriter(log_queue)
                argv = cmd[1:]
                old_cwd = os.getcwd()
                with contextlib.redirect_stdout(qw), contextlib.redirect_stderr(qw):
                    try:
                        os.chdir(tmpdir)
                        nc_builder_main(argv)
                    except SystemExit as e:
                        if e.code != 0 and e.code is not None:
                            print(f"[error] nc-builder exited with code {e.code}")
                    except Exception:
                        print(f"[fatal] {traceback.format_exc()}")
                    finally:
                        os.chdir(old_cwd)
                        qw.flush()
                        log_queue.put(None)

            builder_thread = threading.Thread(target=_run_builder_sync)
            builder_thread.start()

            while True:
                try:
                    line = log_queue.get_nowait()
                    if line is None:
                        break
                    if line.strip():
                        yield json.dumps({"event": "log", "line": line}) + "\n"
                except queue.Empty:
                    await asyncio.sleep(0.01)

            builder_thread.join()

            if not final_out.exists() or final_out.stat().st_size == 0:
                xyz_candidates = sorted(
                    [p for p in tmp_path.glob("*.xyz")
                     if not p.name.endswith("_cut.xyz") and p.stat().st_size > 0],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if not xyz_candidates:
                    yield json.dumps({"event": "result", "status": "failed", "log": "nc-builder did not produce any output xyz"}) + "\n"
                    return
                final_out = xyz_candidates[0]
                yield json.dumps({"event": "log", "line": f"[system] Output located: {final_out.name}"}) + "\n"

            xyz_pass = final_out.read_text()
            xyz_cut = tmp_path / f"{final_out.stem}_cut.xyz"
            xyz_un = xyz_cut.read_text() if xyz_cut.exists() else xyz_pass

            elements, total_charge, grouped_counts = "unknown", 0, {}
            try:
                from ase.io import read as ase_read
                atoms = ase_read(io.StringIO(xyz_pass), format="xyz")
                symbols = atoms.get_chemical_symbols()
                elements = ",".join(sorted(set(symbols)))
                total_charge = sum(final_charges.get(s, 0.0) for s in symbols)
                grouped_counts = _count_grouped_xyz(xyz_pass, core_elements, shell_elements)
            except Exception as e:
                logging.error(f"XYZ parse fail: {e}")

            # ---- Pure Native Passing from nc-builder Output ----
            current_xyz = xyz_pass or xyz_un or ""
            download_name = "final.xyz"

            # Recompute quick metadata natively using final.json manifest
            try:
                final_json = tmp_path / f"{final_out.stem}.json"
                if final_json.exists():
                    manifest = json.loads(final_json.read_text(encoding="utf-8"))
                    total_charge = manifest.get("total_charge", 0)
                    grouped_counts = manifest.get("grouped_counts", {})
                    if not grouped_counts and "counts" in manifest:
                        grouped_counts = {
                            "core": {"by_element": dict(manifest["counts"]), "total": sum(manifest["counts"].values())}
                        }
                    
                    # 1. Parse charged X-type ligand exchange ledger
                    ledger = manifest.get("ligand_exchange_charge_ledger", [])
                    z_ledger = manifest.get("z_type_displacement_ledger", [])
                    anionic_detail = {}
                    cationic_detail = {}
                    z_type_detail = {}
                    for entry in z_ledger:
                        formula = entry.get("formula")
                        if formula:
                            z_type_detail[formula] = z_type_detail.get(formula, 0) + int(entry.get("removed", 0))
                    x_ligands_smiles = []
                    for entry in ledger:
                        sm = entry.get("smiles")
                        chg = entry.get("charge", 0)
                        if sm:
                            x_ligands_smiles.append(sm)
                            if chg < 0:
                                anionic_detail[sm] = anionic_detail.get(sm, 0) + 1
                            else:
                                cationic_detail[sm] = cationic_detail.get(sm, 0) + 1
                    
                    # 2. Parse L-type neutral passivation using bonding graph clustering
                    neutral_detail = {}
                    neutral_smiles = []
                    if opts.neutral_jobs:
                        neutral_smiles = [j.smiles.strip() for j in opts.neutral_jobs if j.smiles.strip()]
                    
                    all_organic_smiles = x_ligands_smiles + neutral_smiles
                    if all_organic_smiles:
                        cluster_counts = _count_molecules_by_smiles(
                            current_xyz, core_elements, shell_elements, all_organic_smiles
                        )
                        for sm in neutral_smiles:
                            neutral_detail[sm] = cluster_counts.get(sm, 0)
                            
                    ligand_detail = {
                        "anionic": anionic_detail,
                        "cationic": cationic_detail,
                        "neutral": neutral_detail,
                        "z_type": z_type_detail,
                        "total": sum(anionic_detail.values()) + sum(cationic_detail.values()) + sum(neutral_detail.values())
                    }
                else:
                    # Fallback if no final.json
                    from ase.io import read as ase_read
                    atoms = ase_read(io.StringIO(current_xyz), format="xyz")
                    symbols = atoms.get_chemical_symbols()
                    elements = ",".join(sorted(set(symbols)))
                    total_charge = sum(final_charges.get(s, 0.0) for s in symbols)
                    grouped_counts = _count_grouped_xyz(current_xyz, core_elements, shell_elements)
                    ligand_detail = {"anionic": {}, "cationic": {}, "neutral": {}, "z_type": {}, "total": 0}
            except Exception as e:
                logging.error(f"Post-cap metadata recompute failed: {e}")
                ligand_detail = {"anionic": {}, "cationic": {}, "neutral": {}, "z_type": {}, "total": 0}

            z_type_options = _detect_z_type_options_for_xyz(
                xyz_pass,
                root_path,
                final_charges,
                tmp_path,
                facets_input=[f.dict() if hasattr(f, "dict") else f for f in (opts.facets or [])],
            )
            post_options = _detect_surface_post_options_for_xyz(
                xyz_pass,
                root_path,
                final_charges,
                tmp_path,
                facets_input=[f.dict() if hasattr(f, "dict") else f for f in (opts.facets or [])],
            )
            
            size_metrics = None
            if current_xyz:
                try:
                    from ase.io import read as ase_read
                    tmp_atoms = ase_read(io.StringIO(current_xyz), format="xyz")
                    c_coords = tmp_atoms.get_positions()
                    c_symbols = tmp_atoms.get_chemical_symbols()
                    size_metrics = get_cluster_size_metrics(c_coords, c_symbols)
                except Exception as e:
                    logging.error(f"Failed to calculate size metrics: {e}")           

            payload = {
                "status": "success",
                "elements": elements,
                "xyz_passivated": current_xyz,
                "xyz_unpassivated": xyz_un,
                "xyz_dummy": xyz_pass,
                "total_charge": round(total_charge),
                "grouped_counts": grouped_counts,
                "download_name": download_name or "final.xyz",
                "last_command": " ".join(cmd),
                "ligand_detail": ligand_detail,
                "z_type_options": z_type_options,
                **post_options,
                "size_metrics": size_metrics, 
            }
            yield json.dumps({"event": "result", **payload}) + "\n"

        except Exception as e:
            # Stream a readable error instead of letting the connection drop
            tb = traceback.format_exc(limit=5)
            yield json.dumps({"event": "log", "line": f"[fatal] {e}\n{tb}"}) + "\n"
            yield json.dumps({"event": "result", "status": "failed", "error": str(e)}) + "\n"
        finally:
            logging.info(f"Cleaning up temporary directory: {tmpdir}")
            # shutil.rmtree(tmpdir, ignore_errors=True)
    
    return StreamingResponse(
        _run(),
        # OLD: media_type="application/x-ndjson",
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

# ---------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
