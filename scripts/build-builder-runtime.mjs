#!/usr/bin/env node
/**
 * Build a gitignored Builder runtime at <repo>/builder-runtime, so installers
 * start the structure Builder on 127.0.0.1:8000 without Docker.
 *
 * Same layout as scripts/build-mace-runtime.mjs:
 *   Windows:  builder-runtime/python.exe   (official embeddable CPython 3.11)
 *   macOS:    builder-runtime/bin/python   (python-build-standalone CPython 3.11)
 *   Linux:    builder-runtime/bin/python   (venv; CI uses actions/setup-python 3.11)
 *   all:      builder-runtime/app/{builder_app.py,api_builder.py}
 *
 * Launch (cwd = builder-runtime/app):
 *   python -m uvicorn builder_app:app --host 127.0.0.1 --port 8000
 *
 * Packages: builder-sidecar/requirements.txt (FastAPI, ase, pymatgen, RDKit, ...)
 * plus QD_Builder (nc-builder, Python package `builder`) and miniCAT from GitHub
 * archives at pinned commits. No torch, boto3, mangum, plotly/kaleido extras.
 * pymatgen still pulls in its own plotly/matplotlib/pandas dependencies.
 *
 * Env overrides:
 *   QDSPACE_QD_BUILDER_REF   QD_Builder commit/branch (default: pinned commit)
 *   QDSPACE_MINICAT_REF      miniCAT commit/branch    (default: pinned commit)
 *   QDSPACE_MAC_ARCH         aarch64 | x86_64 (macOS only, as for mace-runtime)
 *   QDSPACE_BUILDER_COMPILE  set to 0 to skip precompiling .pyc files
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const EMBED_URL = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip';
const GET_PIP_URL = 'https://bootstrap.pypa.io/get-pip.py';
// Same standalone CPython as mace-runtime.
const PBS_TAG = '20260929';
const PBS_PYTHON = '3.11.16';

// Commits the vendored builder-sidecar/api_builder.py was taken against
// (QDSpaceWebApp f9524b4, 2026-10-05). Bump together with that file.
const QD_BUILDER_REF = process.env.QDSPACE_QD_BUILDER_REF || '5ac3803f8df30ecba8e4f85311a15afe2990b018';
const MINICAT_REF = process.env.QDSPACE_MINICAT_REF || '9022ad16a5ff59783071fe6f75f417b3afe8f6c9';
const QD_BUILDER_URL = `https://github.com/nlesc-nano/QD_Builder/archive/${QD_BUILDER_REF}.zip`;
const MINICAT_URL = `https://github.com/nlesc-nano/miniCAT/archive/${MINICAT_REF}.zip`;

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runtime = path.join(root, 'builder-runtime');
const sourceDir = path.join(root, 'builder-sidecar');
const requirements = path.join(sourceDir, 'requirements.txt');
const APP_FILES = ['builder_app.py', 'api_builder.py'];
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

function pipEnv() {
  // Keep a developer's PYTHONPATH/PYTHONHOME or pip config out of the packed tree.
  const env = { ...process.env, PIP_DISABLE_PIP_VERSION_CHECK: '1', PYTHONUTF8: '1' };
  delete env.PYTHONPATH;
  delete env.PYTHONHOME;
  return env;
}

function installPackages(py) {
  const env = pipEnv();
  const pip = (...args) => run(py, ['-m', 'pip', 'install', '--no-cache-dir', '--no-warn-script-location', ...args], { env });
  pip('--upgrade', 'pip', 'setuptools', 'wheel');
  // --prefer-binary: take an older wheel over a newer sdist. Matters on Intel
  // macOS, where recent RDKit/spglib only ship arm64 wheels.
  pip('--prefer-binary', '-r', requirements);
  // QD_Builder and miniCAT are plain setuptools projects from GitHub archives.
  // Their dependencies are already installed above. --no-build-isolation uses
  // the setuptools installed above, which also works with the Windows embeddable
  // Python (its ._pth file ignores the PYTHONPATH pip's isolation relies on).
  pip('--no-deps', '--no-build-isolation', QD_BUILDER_URL, MINICAT_URL);
  // Fail now, not on a user's machine, if an import is missing.
  run(py, ['-c', [
    'import fastapi, uvicorn, multipart, ase, numpy, scipy, yaml, pymatgen.core, rdkit, minicat',
    'from builder.main import main',
    'from builder.scripts.analyze_cif_facets import _analyze',
    'import rdkit; print("builder deps ok; rdkit", rdkit.__version__)',
  ].join('\n')], { env });
}

function copyApp() {
  const appDir = path.join(runtime, 'app');
  fs.mkdirSync(appDir, { recursive: true });
  for (const name of APP_FILES) {
    const src = path.join(sourceDir, name);
    if (!fs.existsSync(src)) fail(`missing Builder source ${src}`);
    fs.copyFileSync(src, path.join(appDir, name));
  }
}

function smokeTest(py) {
  // Import the FastAPI app exactly as uvicorn will (cwd = app/).
  // sys.path.insert mirrors uvicorn's --app-dir; the embeddable Python's ._pth
  // file keeps cwd off sys.path for `python -c`.
  const code = 'import sys; sys.path.insert(0, "."); import builder_app; print("builder_app ok:", [r.path for r in builder_app.app.routes])';
  run(py, ['-c', code], {
    cwd: path.join(runtime, 'app'),
    env: { ...pipEnv(), MPLBACKEND: 'Agg' },
  });
}

function precompile(py) {
  if (process.env.QDSPACE_BUILDER_COMPILE === '0') return;
  // Ship .pyc files (~+200 MB unpacked): an installed app folder may be
  // read-only (macOS /Applications, Program Files), and compiling
  // pymatgen/RDKit/scipy on every launch makes Builder slow to come up.
  const env = pipEnv();
  const site = spawnSync(py, ['-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], { encoding: 'utf8', env });
  const sitePackages = (site.stdout || '').trim();
  if (site.status !== 0 || !sitePackages) fail('could not locate site-packages for compileall');
  // unchecked-hash: the .pyc stays valid even when the installer copy changes
  // file mtimes. -f rewrites the timestamp-based .pyc files pip already wrote.
  // app/ is left out so a hand-edited builder_app.py is never shadowed.
  const r = spawnSync(
    py,
    ['-m', 'compileall', '-q', '-f', '-j', '0', '--invalidation-mode', 'unchecked-hash', sitePackages],
    { stdio: 'inherit', env },
  );
  if (r.status !== 0) console.warn('warning: compileall reported errors (some vendored test files do not compile); continuing');
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
  fs.mkdirSync(path.join(runtime, 'Lib', 'site-packages'), { recursive: true });
  // Same fix as mace-runtime: list Lib\site-packages and enable `import site`.
  // The ._pth file also keeps cwd off sys.path; uvicorn adds its --app-dir
  // (default ".") itself, so `-m uvicorn builder_app:app` still finds app/.
  const text = fs.readFileSync(pthPath, 'utf8').replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
  const lines = text.split('\n').map((line) => line.trimEnd()).filter((line) => line.length > 0);
  const kept = lines.filter((line) => !['import site', '#import site', '# import site', 'Lib\\site-packages', 'Lib/site-packages'].includes(line));
  fs.writeFileSync(pthPath, [...kept, 'Lib\\site-packages', 'import site'].join('\n') + '\n', 'utf8');

  const py = path.join(runtime, 'python.exe');
  if (!fs.existsSync(py)) fail(`python.exe missing after extracting ${EMBED_URL}`);
  const getPip = path.join(runtime, 'get-pip.py');
  await download(GET_PIP_URL, getPip);
  run(py, [getPip, '--no-warn-script-location'], { env: pipEnv() });
  fs.rmSync(getPip, { force: true });
  installPackages(py);
  return py;
}

function unixBasePython() {
  for (const cmd of ['python3.11', 'python3', 'python']) {
    const r = spawnSync(cmd, ['-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])'], { encoding: 'utf8' });
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
  if (created.status !== 0) fail('could not create builder-runtime venv');
  const py = ['python', 'python3']
    .map((name) => path.join(runtime, 'bin', name))
    .find((candidate) => fs.existsSync(candidate));
  if (!py) fail('venv did not create bin/python');
  installPackages(py);
  return py;
}

function darwinArch() {
  const requested = process.env.QDSPACE_MAC_ARCH;
  if (requested === 'aarch64' || requested === 'x86_64') return requested;
  if (requested) fail(`QDSPACE_MAC_ARCH must be aarch64 or x86_64, got ${requested}`);
  if (process.arch === 'arm64') return 'aarch64';
  if (process.arch === 'x64') return 'x86_64';
  fail(`unsupported Mac arch ${process.arch}; set QDSPACE_MAC_ARCH to aarch64 or x86_64`);
}

// See build-mace-runtime.mjs: Tauri resources must not contain symlinks.
function materializeSymlinks(dirRoot) {
  const stack = [dirRoot];
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
          if (copiedDirs > 1000) fail(`too many directory symlinks under ${dirRoot}`);
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
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'qdspace-builder-cpython-'));
  const archive = path.join(tmp, filename);
  await download(url, archive);
  run('tar', ['-xzf', archive, '-C', tmp]);
  const extracted = path.join(tmp, 'python');
  if (!fs.existsSync(path.join(extracted, 'bin', 'python3.11'))) {
    fs.rmSync(tmp, { recursive: true, force: true });
    fail(`standalone archive has no python/bin/python3.11 (${url})`);
  }
  fs.cpSync(extracted, runtime, { recursive: true, dereference: false });
  materializeSymlinks(runtime);
  fs.rmSync(tmp, { recursive: true, force: true });
  installPackages(path.join(runtime, 'bin', 'python3.11'));
  // pip may add new console-script symlinks; keep the tree link-free.
  materializeSymlinks(runtime);
  for (const name of ['python', 'python3', 'python3.11']) {
    const bin = path.join(runtime, 'bin', name);
    if (!fs.existsSync(bin)) continue;
    if (fs.lstatSync(bin).isSymbolicLink()) fail(`bin/${name} is still a symlink`);
    fs.chmodSync(bin, fs.statSync(bin).mode | 0o755);
  }
  const py = path.join(runtime, 'bin', 'python');
  if (!fs.existsSync(py)) fail('standalone tree has no bin/python');
  return py;
}

function folderBytes(dir) {
  let total = 0;
  const stack = [dir];
  while (stack.length) {
    const d = stack.pop();
    for (const ent of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, ent.name);
      if (ent.isDirectory()) stack.push(p);
      else if (ent.isFile()) total += fs.statSync(p).size;
    }
  }
  return total;
}

if (!fs.existsSync(requirements)) fail(`missing ${requirements}`);
let py;
if (isWin) py = await buildWindows();
else if (process.platform === 'darwin') py = await buildDarwin();
else py = buildUnix();
copyApp();
smokeTest(py);
precompile(py);

const python = isWin ? path.join(runtime, 'python.exe') : path.join(runtime, 'bin', 'python');
const appDir = path.join(runtime, 'app');
if (!fs.existsSync(python)) fail(`runtime python missing at ${python}`);
for (const name of APP_FILES) {
  if (!fs.existsSync(path.join(appDir, name))) fail(`app/${name} was not copied`);
}
// The rebuild wiped builder-runtime/, including the committed placeholder that
// lets tauri.conf.json bundle.resources resolve on a fresh checkout.
fs.writeFileSync(path.join(runtime, '.gitkeep'), '');
console.log(`Builder runtime ready at ${runtime} (${(folderBytes(runtime) / 1024 / 1024).toFixed(0)} MB)`);
console.log(`Launch: ${python} -m uvicorn builder_app:app --host 127.0.0.1 --port 8000`);
console.log(`cwd: ${appDir}`);
