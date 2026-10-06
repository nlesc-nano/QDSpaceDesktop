# Builder sidecar

FastAPI service for the desktop Builder tab. The app starts it on `127.0.0.1:8000` from the packed `builder-runtime/`, so users need no Docker.

- `builder_app.py` mounts the Builder API at `/builder`, same as the web app, so `src/Builder.svelte` calls `/builder/api/analyze_cif` and `/builder/api/build_stream` unchanged. It leaves out the library API, S3, and the static site.
- `api_builder.py` is vendored from [QDSpaceWebApp](https://github.com/nlesc-nano/QDSpaceWebApp) `backend/api_builder.py`. The only change is that the POSIX-only `pty`/`tty`/`fcntl` import is optional, so it starts on Windows. The commit is in the file header.
- `requirements.txt` lists the packages. `scripts/build-builder-runtime.mjs` also installs [QD_Builder](https://github.com/nlesc-nano/QD_Builder) and [miniCAT](https://github.com/nlesc-nano/miniCAT) from pinned commits.

To update from upstream, copy `backend/api_builder.py` again, re-apply the optional import, and bump the `QD_BUILDER_REF` and `MINICAT_REF` commits in the build script to match.

Run it without the desktop app:

```
npm run builder-runtime
cd builder-runtime/app
../python.exe -m uvicorn builder_app:app --host 127.0.0.1 --port 8000      # Windows
../bin/python -m uvicorn builder_app:app --host 127.0.0.1 --port 8000      # macOS / Linux
```
