# QDSpace MACE sidecar — predict API contract

**Service:** local FastAPI process (CPU, MACE-MP-0 large, float32)  
**Base URL (dev):** `http://127.0.0.1:8765`  
**Model id string:** `mace-mp-0-large`  
**Auth:** none (bind to localhost only)

## Run

```bash
cd /workspace/qdspace-ml-spike
source .venv/bin/activate
uvicorn sidecar_app:app --host 127.0.0.1 --port 8765
```

Interactive OpenAPI: `http://127.0.0.1:8765/docs`

Model loads **lazily on first `/predict`** (or `POST /health?warmup=true`). First call may take a few seconds; subsequent calls are much faster.

---

## `POST /health`

Health / readiness probe. Body optional / empty.

### Query

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `warmup` | bool | `false` | If true, load the model before responding |

### Response `200`

```json
{
  "status": "ok",
  "model": "mace-mp-0-large",
  "model_loaded": false,
  "device": "cpu",
  "model_path": "/workspace/qdspace-ml-spike/models/2024-01-07-mace-128-L2_epoch-199.model"
}
```

When `warmup=true`, also includes `"cold_load_s": <float>` and `model_loaded: true`.

---

## `POST /predict`

Compute potential **energy** (eV) and per-atom **forces** (eV/Å) for a structure.

### Request body

```json
{
  "symbols": ["O", "H", "H"],
  "positions": [
    [0.0, 0.0, 0.0],
    [0.757, 0.586, 0.0],
    [-0.757, 0.586, 0.0]
  ],
  "cell": null,
  "pbc": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `symbols` | `string[]` | yes | Element symbols; length = N |
| `positions` | `number[N][3]` | yes | Cartesian coordinates in **Å** |
| `cell` | `number[3][3]` \| omit/null | no | Cell matrix in **Å**. Omit for non-periodic molecules |
| `pbc` | `boolean` \| `boolean[3]` \| omit | no | Periodic boundary conditions. Default **`false`** if omitted |

**Constraints**

- `symbols.length === positions.length` and ≥ 1
- Each position / force vector is length 3
- Units: Å (positions/cell), eV (energy), eV/Å (forces)
- CPU float32 inference only in this spike

### Response `200`

```json
{
  "energy": -14.18301773071289,
  "forces": [
    [0.0, -0.8409964442253113, 0.0],
    [0.5308021306991577, 0.42049819231033325, 0.0],
    [-0.5308021306991577, 0.42049819231033325, 0.0]
  ],
  "n_atoms": 3,
  "device": "cpu",
  "model": "mace-mp-0-large",
  "latency_ms": 3231.66,
  "cold_load_s": 0.134
}
```

| Field | Type | Description |
|-------|------|-------------|
| `energy` | float | Total potential energy (eV) |
| `forces` | `number[N][3]` | Forces (eV/Å), same order as atoms |
| `n_atoms` | int | Atom count |
| `device` | `"cpu"` | Compute device |
| `model` | string | Model identifier |
| `latency_ms` | float | Server-side wall time for this request (includes cold load if first call) |
| `cold_load_s` | float \| null | Present on the request that first loaded the model; otherwise omitted/null |

### Errors

| Status | When |
|--------|------|
| `400` | Length mismatch, malformed positions |
| `500` | Model file missing / calculator failure |

---

## Frontend integration notes

1. Prefer starting the sidecar when the user opens an ML panel; call `POST /health?warmup=true` in the background to hide cold-start cost.
2. Keep payloads small (N up to ~50–100 for snappy UX on CPU); show a spinner for first predict.
3. Do not expose the port beyond localhost.
4. Treat `latency_ms` as telemetry only; UI should use its own timer if needed.
5. Periodic solids: send `cell` + `pbc: true` (or `[true,true,true]`). Molecules: omit `cell`, `pbc: false`.

## Example curl

```bash
curl -s -X POST http://127.0.0.1:8765/predict \
  -H 'Content-Type: application/json' \
  -d '{"symbols":["O","H","H"],"positions":[[0,0,0],[0.757,0.586,0],[-0.757,0.586,0]],"pbc":false}'
```
