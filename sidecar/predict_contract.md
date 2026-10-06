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
  "model_path": "/workspace/qdspace-ml-spike/models/2024-01-07-mace-128-L2_epoch-199.model",
  "mace_torch": "0.3.12"
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

## `POST /predict-frames-stream`

Predict every frame of a multi-frame XYZ and send each result **as soon as that frame is done**, so the app can show "Frame 1000 of 1600" and the latest energy/forces while the run continues. `POST /predict-frames` still exists and returns everything in one JSON response at the end.

### Request body

Same as `/predict-frames`:

```json
{ "filename": "traj.xyz", "text": "<whole .xyz file>", "device": "cpu", "engine": "mace", "model_path": null, "head": null }
```

### Response `200` — `application/x-ndjson`

One JSON object per line, each with a `type`:

| `type` | Fields | When |
|--------|--------|------|
| `start` | `n_frames` | Right away, before the model loads |
| `ready` | `device`, `model`, `cold_load_s` | Model is loaded (`cold_load_s` is set only if this request loaded it) |
| `frame` | `index` (0-based), `n_frames`, `energy`, `forces`, `symbols`, `positions`, `cell`, `pbc`, `n_atoms`, `formula`, `latency_ms` (this frame), `elapsed_ms` (since the request started) | After each frame |
| `done` | `n_frames`, `latency_ms` | Every frame finished; last line |
| `cancelled` | `completed`, `n_frames` | `POST /cancel-predict` stopped the run between frames; last line |
| `error` | `message`, `completed`, `n_frames`, `index` (if a frame failed) | Model load or a frame failed; last line |

```text
{"type":"start","n_frames":1600}
{"type":"ready","device":"cpu","model":"mace-mp-0-large","cold_load_s":null}
{"symbols":["O","H","H"],"positions":[...],"cell":null,"pbc":false,"n_atoms":3,"formula":"H2O","energy":-14.18,"forces":[...],"type":"frame","index":0,"n_frames":1600,"latency_ms":41.2,"elapsed_ms":45.0}
...
{"type":"done","n_frames":1600,"latency_ms":65321.7}
```

Unreadable XYZ text still fails up front with HTTP `400`. A stream that ends without `done`, `cancelled` or `error` means the process stopped.

### Cancel

`POST /cancel-predict` sets a flag the loop checks before each frame; the stream then ends with a `cancelled` line. Closing the connection (the app aborts its fetch) also stops the loop after the frame in progress. The app keeps the frames that already arrived.

```bash
curl -sN -X POST http://127.0.0.1:8765/predict-frames-stream \
  -H 'Content-Type: application/json' \
  -d '{"filename":"traj.xyz","text":"3\nframe 1\nO 0 0 0\nH 0.757 0.586 0\nH -0.757 0.586 0\n"}'
```

---

## `POST /predict-frames-job` + `GET /predict-frames-job/{job_id}` (used by the desktop app)

Same work as `/predict-frames-stream`, but as a background job the app polls. The Tauri window on Windows (WebView2) can buffer a streamed `fetch` body until the response ends, so stream progress may show up all at once. Short polls always complete, so the "Frame N of M" counter stays live. The app tries this first and falls back to `/predict-frames-stream`, then `/predict-frames`, on older sidecars.

### Start — `POST /predict-frames-job`

Body: same as `/predict-frames`. Returns right away (model loading happens in the job):

```json
{ "job_id": "3f2a…", "n_frames": 1600, "status": "starting" }
```

Unreadable XYZ text still fails with HTTP `400`. Starting a new job cancels any job still running.

### Poll — `GET /predict-frames-job/{job_id}?after=N`

```json
{
  "job_id": "3f2a…", "status": "running", "done": 412, "total": 1600, "after": 400,
  "frames": [ { "index": 400, "energy": -14.18, "forces": [...], "symbols": [...], "positions": [...], "cell": null, "pbc": false, "n_atoms": 3, "formula": "H2O", "n_frames": 1600, "latency_ms": 41.2, "elapsed_ms": 16500.3 }, … ],
  "device": "cpu", "model": "mace-mp-0-large", "cold_load_s": null, "latency_ms": 16510.0,
  "cancelled": false, "error": null, "error_index": null
}
```

| Field | Meaning |
|-------|---------|
| `status` | `starting`, `loading` (model), `running`, `done`, `cancelled`, `error` |
| `done` / `total` | Frames finished / frames in the file |
| `frames` | Finished frames with `index >= after` (pass the number of frames you already have) |
| `error`, `error_index` | Set when `status` is `error` |

`404` means the job is unknown (the sidecar restarted, or it was pruned; the newest 4 finished jobs are kept). The app polls about every 200 ms.

`POST /cancel-predict` also stops jobs between frames; the job ends with `status: "cancelled"` and keeps the frames that finished, so one more poll returns them.

```bash
JOB=$(curl -s -X POST http://127.0.0.1:8765/predict-frames-job -H 'Content-Type: application/json' \
  -d '{"filename":"traj.xyz","text":"3\nframe 1\nO 0 0 0\nH 0.757 0.586 0\nH -0.757 0.586 0\n"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
curl -s "http://127.0.0.1:8765/predict-frames-job/$JOB?after=0"
```

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


---

## Foundation model download (Predict item 6)

### `POST /model-path`

Register an absolute model path without uploading bytes (preferred for large `.model` files).

```json
{ "path": "C:\\Models\\mace-mpa-0-medium.model", "model_type": null }
```

Response mirrors `POST /model` (`model_path`, `filename`, `bytes`, `heads`, `selected`, `model_type`).

`model_type` of `"PolarMACE"` is stored for later `/predict` loads of POLAR models.

### `POST /download-model`

```json
{ "url": "https://github.com/ACEsuit/mace-foundations/releases/download/...", "dest_dir": "C:\\Models", "filename": "optional.model", "expected_size": 79462305, "sha256": null }
```

Returns `{ "job_id", "status" }`. Hosts are allowlisted (`github.com`, `raw.githubusercontent.com`, `huggingface.co`, …). Writes to `filename.part` then renames.

### `GET /download-model/{job_id}`

`{ "id", "status", "bytes_done", "bytes_total", "path", "error", "url" }` — `status` is `starting|running|done|cancelled|error`.

### `POST /cancel-download/{job_id}`

Stops an in-flight download; partial `.part` is removed.

### Predict `model_type`

`POST /predict`, `/predict-frames*`, and job variants accept optional `model_type` (e.g. `"PolarMACE"`). Passed through to `MACECalculator`.

### tauri:dev sidecar refresh

The running sidecar is often the copy under `src-tauri/target/debug/mace-runtime/`. After editing `sidecar/sidecar_app.py` (or `model_download.py` / `mace_engine.py`), either:

1. Copy the changed files into that runtime folder and restart `npm run tauri:dev`, or
2. Rebuild the runtime with `npm run mace-runtime` if you use the bundled sidecar.

Curated catalog: `src/lib/maceModels.json`. UI: Predict → Model → **Download foundation model…**.
