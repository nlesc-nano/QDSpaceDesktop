#!/usr/bin/env node
/**
 * Build a gitignored CPU MACE sidecar runtime at <repo>/mace-runtime.
 *
 * Layout (what the installer launches):
 *   Windows:  mace-runtime/python.exe
 *             mace-runtime/app/{sidecar_app.py,mace_engine.py,nequip_engine.py,models/}
 *   macOS:    mace-runtime/bin/python   (python-build-standalone CPython 3.11, not a venv)
 *             mace-runtime/app/...
 *   Linux:    mace-runtime/bin/python   (venv from Python 3.11; CI uses actions/setup-python)
 *             mace-runtime/app/...
 *
 * Launch (cwd = mace-runtime/app):
 *   python -m uvicorn sidecar_app:app --host 127.0.0.1 --port 8765
 *
 * The default checkpoint is sidecar/models/2024-01-07-mace-128-L2_epoch-199.model
 * (~61 MB, committed). If that file is missing, this script downloads the public
 * MACE-MP-0 large asset and fails if the download does not land a real checkpoint.
 *
 * Linux venvs are not relocatable: bin/python points at the interpreter that
 * created them (the GitHub runner's setup-python). macOS does not use a venv.
 * It unpacks Astral's install_only CPython and replaces relative symlinks with
 * real files so the DMG does not ship a dangling bin/python. Windows uses the
 * official embeddable CPython zip, which is self-contained.
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const MODEL_NAME = '2024-01-07-mace-128-L2_epoch-199.model';
const MODEL_URL =
  'https://github.com/ACEsuit/mace-foundations/releases/download/mace_mp_0/2024-01-07-mace-128-L2_epoch-199.model';
const MIN_MODEL_BYTES = 1_000_000;
const EMBED_URL = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip';
const GET_PIP_URL = 'https://bootstrap.pypa.io/get-pip.py';
// install_only assets on tag 20260929 (cpython 3.11.16, aarch64 and x86_64 apple-darwin).
const PBS_TAG = '20260929';
const PBS_PYTHON = '3.11.16';
const TORCH_INDEX = 'https://download.pytorch.org/whl/cpu';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runtime = path.join(root, 'mace-runtime');
const isWin = process.platform === 'win32';

function fail(message) {
  console.error(`ERROR: ${message}`);
  process.exit(1);
}

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...opts });
  if (r.error) fail(`${cmd} failed to start: ${r.error.message}`);
  if (r.status !== 0) fail(`${cmd} ${args.join(' ')} exited ${r.status}`);
}

async function download(url, dest) {
  console.log(`Downloading ${url}`);
  const res = await fetch(url, { redirect: 'follow' });
  if (!res.ok) fail(`download failed (${res.status}) ${url}`);
  const buf = Buffer.from(await res.arrayBuffer());
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, buf);
  return buf.length;
}

async function ensureModel() {
  const dest = path.join(root, 'sidecar', 'models', MODEL_NAME);
  if (fs.existsSync(dest) && fs.statSync(dest).size >= MIN_MODEL_BYTES) {
    console.log(`Using builtin model ${dest} (${fs.statSync(dest).size} bytes)`);
    return dest;
  }
  console.log(`Builtin model missing or too small at ${dest}`);
  console.log('Downloading MACE-MP-0 large from the public ACEsuit release.');
  let size = 0;
  try {
    size = await download(MODEL_URL, dest);
  } catch (err) {
    fail(
      `builtin model ${MODEL_NAME} is not in the repo and the download failed: ${err.message}\n` +
        `Commit sidecar/models/${MODEL_NAME} (~61 MB) or place the file there.\n` +
        `Public URL: ${MODEL_URL}`,
    );
  }
  if (size < MIN_MODEL_BYTES) {
    fs.rmSync(dest, { force: true });
    fail(
      `downloaded model is only ${size} bytes (expected ~63509066). ` +
        `Refusing to pack a bad file from ${MODEL_URL}`,
    );
  }
  console.log(`Downloaded model to ${dest} (${size} bytes)`);
  return dest;
}

function copyApp(modelPath) {
  const appDir = path.join(runtime, 'app');
  const modelsDir = path.join(appDir, 'models');
  fs.mkdirSync(modelsDir, { recursive: true });
  for (const name of ['sidecar_app.py', 'mace_engine.py', 'nequip_engine.py']) {
    const src = path.join(root, 'sidecar', name);
    if (!fs.existsSync(src)) fail(`missing sidecar source ${src}`);
    fs.copyFileSync(src, path.join(appDir, name));
  }
  fs.copyFileSync(modelPath, path.join(modelsDir, MODEL_NAME));
}

function installPackages(py) {
  // Proven local set: torch 2.14.0+cpu, mace-torch 0.3.16 --no-deps, e3nn 0.4.4,
  // plus the libraries MACECalculator imports on top of the sidecar requirements.
  run(py, ['-m', 'pip', 'install', '--upgrade', 'pip']);
  run(py, ['-m', 'pip', 'install', 'torch==2.14.0', '--index-url', TORCH_INDEX]);
  run(py, ['-m', 'pip', 'install', 'mace-torch==0.3.16', '--no-deps']);
  run(py, [
    '-m', 'pip', 'install',
    'e3nn==0.4.4',
    'numpy',
    'scipy',
    'ase',
    'matscipy',
    'opt_einsum',
    'pyyaml',
    'fastapi',
    'uvicorn[standard]',
    'pydantic',
    'torch-ema',
    'torchmetrics',
    'pandas',
    'h5py',
    'lmdb',
    'orjson',
  ]);
}

async function buildWindows() {
  fs.rmSync(runtime, { recursive: true, force: true });
  fs.mkdirSync(runtime, { recursive: true });
  const zipPath = path.join(runtime, 'python-embed.zip');
  await download(EMBED_URL, zipPath);
  run('powershell.exe', [
    '-NoProfile',
    '-Command',
    `Expand-Archive -LiteralPath '${zipPath.replace(/'/g, "''")}' -DestinationPath '${runtime.replace(/'/g, "''")}' -Force`,
  ]);
  fs.rmSync(zipPath, { force: true });

  const pthName = fs.readdirSync(runtime).find((name) => name.endsWith('._pth'));
  if (!pthName) fail('embeddable Python did not include a ._pth file');
  const pthPath = path.join(runtime, pthName);
  const sitePackages = path.join(runtime, 'Lib', 'site-packages');
  fs.mkdirSync(sitePackages, { recursive: true });
  // The embed zip ignores Lib\\site-packages unless that folder is listed in
  // python*._pth. Uncommenting "import site" alone still leaves pip invisible,
  // which is why "python -m pip" said "No module named pip" after get-pip.
  let text = fs.readFileSync(pthPath, 'utf8').replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
  const lines = text.split('\n').map((line) => line.trimEnd()).filter((line) => line.length > 0);
  const kept = lines.filter((line) => line !== 'import site' && line !== '#import site' && line !== '# import site' && line !== 'Lib\\site-packages' && line !== 'Lib/site-packages');
  const body = [...kept, 'Lib\\site-packages', 'import site'].join('\n') + '\n';
  fs.writeFileSync(pthPath, body, 'utf8');

  const py = path.join(runtime, 'python.exe');
  if (!fs.existsSync(py)) fail(`python.exe missing after extracting ${EMBED_URL}`);
  const getPip = path.join(runtime, 'get-pip.py');
  await download(GET_PIP_URL, getPip);
  run(py, [getPip, '--no-warn-script-location']);
  installPackages(py);
  fs.rmSync(getPip, { force: true });
}

function unixBasePython() {
  for (const cmd of ['python3', 'python']) {
    const r = spawnSync(cmd, ['-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])'], {
      encoding: 'utf8',
    });
    if (r.status === 0) {
      const ver = (r.stdout || '').trim();
      if (!ver.startsWith('3.11.')) {
        console.warn(`warning: expected Python 3.11 (actions/setup-python), found ${cmd} ${ver}`);
      }
      return cmd;
    }
  }
  fail('Python 3.11 was not found. On CI, run actions/setup-python with python-version 3.11 before this script.');
}

function buildUnix() {
  fs.rmSync(runtime, { recursive: true, force: true });
  const base = unixBasePython();
  let created = spawnSync(base, ['-m', 'venv', '--copies', runtime], { stdio: 'inherit' });
  if (created.status !== 0) {
    fs.rmSync(runtime, { recursive: true, force: true });
    console.warn('python -m venv --copies failed; retrying without --copies');
    created = spawnSync(base, ['-m', 'venv', runtime], { stdio: 'inherit' });
  }
  if (created.status !== 0) fail('could not create mace-runtime venv');
  const py = ['python', 'python3']
    .map((name) => path.join(runtime, 'bin', name))
    .find((candidate) => fs.existsSync(candidate));
  if (!py) fail('venv did not create bin/python');
  installPackages(py);
}

function darwinArch() {
  const requested = process.env.QDSPACE_MAC_ARCH;
  if (requested === 'aarch64' || requested === 'x86_64') return requested;
  if (requested) fail(`QDSPACE_MAC_ARCH must be aarch64 or x86_64, got ${requested}`);
  if (process.arch === 'arm64') return 'aarch64';
  if (process.arch === 'x64') return 'x86_64';
  fail(`unsupported Mac arch ${process.arch}; set QDSPACE_MAC_ARCH to aarch64 or x86_64`);
}

// Tauri resource packaging can turn a symlink into a plain file that no longer
// points at its target. python-build-standalone ships relative symlinks
// (bin/python -> python3.11). Copy each one to a real file or directory.
function materializeSymlinks(root) {
  const stack = [root];
  let copiedDirs = 0;
  while (stack.length) {
    const dir = stack.pop();
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, ent.name);
      if (ent.isSymbolicLink()) {
        const link = fs.readlinkSync(p);
        const target = path.isAbsolute(link) ? link : path.resolve(path.dirname(p), link);
        if (!fs.existsSync(target)) fail(`dangling symlink ${p} -> ${link}`);
        const st = fs.statSync(target);
        fs.unlinkSync(p);
        if (st.isDirectory()) {
          copiedDirs += 1;
          if (copiedDirs > 1000) fail(`too many directory symlinks under ${root}`);
          fs.cpSync(target, p, { recursive: true, dereference: false });
          stack.push(p);
        } else {
          fs.copyFileSync(target, p);
          fs.chmodSync(p, st.mode & 0o777);
        }
      } else if (ent.isDirectory()) {
        stack.push(p);
      }
    }
  }
}

async function buildDarwin() {
  const arch = darwinArch();
  const filename = `cpython-${PBS_PYTHON}+${PBS_TAG}-${arch}-apple-darwin-install_only.tar.gz`;
  const url = `https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${filename}`;
  console.log(`macOS standalone CPython ${PBS_PYTHON} for ${arch}`);
  fs.rmSync(runtime, { recursive: true, force: true });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'qdspace-cpython-'));
  const archive = path.join(tmp, filename);
  await download(url, archive);
  run('tar', ['-xzf', archive, '-C', tmp]);
  const extracted = path.join(tmp, 'python');
  if (!fs.existsSync(path.join(extracted, 'bin', 'python3.11'))) {
    fs.rmSync(tmp, { recursive: true, force: true });
    fail(`standalone archive has no python/bin/python3.11 (${url})`);
  }
  fs.cpSync(extracted, runtime, { recursive: true, dereference: false });
  // Copy symlink targets while the unpack folder still exists. The standalone
  // man pages point at that folder with an absolute path.
  materializeSymlinks(runtime);
  fs.rmSync(tmp, { recursive: true, force: true });
  installPackages(path.join(runtime, 'bin', 'python3.11'));
  for (const name of ['python', 'python3', 'python3.11']) {
    const bin = path.join(runtime, 'bin', name);
    if (!fs.existsSync(bin)) continue;
    if (fs.lstatSync(bin).isSymbolicLink()) fail(`bin/${name} is still a symlink`);
    fs.chmodSync(bin, fs.statSync(bin).mode | 0o755);
  }
  const py = path.join(runtime, 'bin', 'python');
  if (!fs.existsSync(py)) fail('standalone tree has no bin/python');
}

const modelPath = await ensureModel();
if (isWin) await buildWindows();
else if (process.platform === 'darwin') await buildDarwin();
else buildUnix();
copyApp(modelPath);

const python = isWin
  ? path.join(runtime, 'python.exe')
  : path.join(runtime, 'bin', 'python');
const appDir = path.join(runtime, 'app');
if (!fs.existsSync(python)) fail(`runtime python missing at ${python}`);
if (!fs.existsSync(path.join(appDir, 'sidecar_app.py'))) fail('app/sidecar_app.py was not copied');
if (!fs.existsSync(path.join(appDir, 'models', MODEL_NAME))) fail('app model was not copied');
console.log(`CPU MACE runtime ready at ${runtime}`);
console.log(`Launch: ${python} -m uvicorn sidecar_app:app --host 127.0.0.1 --port 8765`);
console.log(`cwd: ${appDir}`);
