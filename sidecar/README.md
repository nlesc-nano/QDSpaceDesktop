# QDSpace MACE sidecar

Local FastAPI service exposing `POST /predict` for MACE-MP-0 **large** (CPU, float32).

## Contract

See [predict_contract.md](./predict_contract.md).

- Base URL: `http://127.0.0.1:8765`
- Lazy model load on first `/predict` or `POST /health?warmup=true`

## Model checkpoint

Expected path:

```
sidecar/models/2024-01-07-mace-128-L2_epoch-199.model
```

(~61 MB). This desktop tree already includes the checkpoint when copied from the ML spike.
If missing, download MACE-MP-0 large from the [MACE foundation models](https://github.com/ACEsuit/mace)
release assets / Hugging Face and place it at that path (filename must match, or edit `MODEL_PATH` in `sidecar_app.py`).

## Setup (Windows / Linux / macOS)

```bash
cd sidecar
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
uvicorn sidecar_app:app --host 127.0.0.1 --port 8765
```

From the desktop app root you can also run:

```bash
npm run sidecar
```

## Smoke test

```bash
curl -s -X POST http://127.0.0.1:8765/predict \
  -H "Content-Type: application/json" \
  -d '{"symbols":["O","H","H"],"positions":[[0,0,0],[0.757,0.586,0],[-0.757,0.586,0]],"pbc":false}'
```

OpenAPI docs: http://127.0.0.1:8765/docs

## Notes

- Bind to localhost only — no auth.
- First predict is slow (model load + compile); later calls are much faster.
- Optional: start this before `npm run tauri:dev` so the Predict page can call it.
