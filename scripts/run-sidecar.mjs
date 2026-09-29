#!/usr/bin/env node
/**
 * Cross-platform MACE sidecar launcher.
 * Prefers conda env "webappdesktop" on Windows; falls back to sidecar/.venv.
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sidecar = path.join(root, 'sidecar');
const isWin = process.platform === 'win32';

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', cwd: sidecar, shell: isWin, ...opts });
  if (r.status !== 0) process.exit(r.status ?? 1);
}

function resolvePython() {
  const condaCandidates = [
    process.env.CONDA_EXE,
    'C:\\ProgramData\\miniconda3\\Scripts\\conda.exe',
    'C:\\ProgramData\\anaconda3\\Scripts\\conda.exe',
    path.join(process.env.USERPROFILE || '', 'miniconda3', 'Scripts', 'conda.exe'),
    path.join(process.env.USERPROFILE || '', 'anaconda3', 'Scripts', 'conda.exe'),
  ].filter(Boolean);

  if (isWin) {
    const envPy = [
      'C:\\ProgramData\\miniconda3\\envs\\webappdesktop\\python.exe',
      'C:\\ProgramData\\anaconda3\\envs\\webappdesktop\\python.exe',
      path.join(process.env.USERPROFILE || '', 'miniconda3', 'envs', 'webappdesktop', 'python.exe'),
      path.join(process.env.USERPROFILE || '', 'anaconda3', 'envs', 'webappdesktop', 'python.exe'),
      path.join(process.env.USERPROFILE || '', '.conda', 'envs', 'webappdesktop', 'python.exe'),
    ];
    for (const p of envPy) {
      if (p && fs.existsSync(p)) {
        return { kind: 'conda-python', python: p };
      }
    }
    for (const conda of condaCandidates) {
      if (conda && fs.existsSync(conda)) {
        return { kind: 'conda-run', conda };
      }
    }
  }

  const venvDir = path.join(sidecar, '.venv');
  const py = isWin
    ? path.join(venvDir, 'Scripts', 'python.exe')
    : path.join(venvDir, 'bin', 'python');
  return { kind: 'venv', python: py, venvDir };
}

const resolved = resolvePython();

if (resolved.kind === 'venv' && !fs.existsSync(resolved.python)) {
  console.log('Creating Python venv in sidecar/.venv …');
  const basePy = isWin ? 'python' : 'python3';
  run(basePy, ['-m', 'venv', '.venv']);
}

if (resolved.kind === 'venv') {
  const pip = isWin
    ? path.join(resolved.venvDir, 'Scripts', 'pip.exe')
    : path.join(resolved.venvDir, 'bin', 'pip');
  console.log('Ensuring sidecar Python deps (venv) …');
  run(pip, ['install', '-q', 'torch', '--index-url', 'https://download.pytorch.org/whl/cpu']);
  run(pip, ['install', '-q', '-r', 'requirements.txt']);
  console.log('Starting uvicorn on http://127.0.0.1:8765 …');
  const child = spawn(
    resolved.python,
    ['-m', 'uvicorn', 'sidecar_app:app', '--host', '127.0.0.1', '--port', '8765'],
    { cwd: sidecar, stdio: 'inherit', shell: isWin },
  );
  child.on('exit', (code) => process.exit(code ?? 0));
} else if (resolved.kind === 'conda-python') {
  console.log(`Using conda env webappdesktop: ${resolved.python}`);
  console.log('Starting uvicorn on http://127.0.0.1:8765 …');
  const child = spawn(
    resolved.python,
    ['-m', 'uvicorn', 'sidecar_app:app', '--host', '127.0.0.1', '--port', '8765'],
    { cwd: sidecar, stdio: 'inherit', shell: isWin },
  );
  child.on('exit', (code) => process.exit(code ?? 0));
} else {
  console.log('Using: conda run -n webappdesktop …');
  const child = spawn(
    resolved.conda,
    ['run', '--no-capture-output', '-n', 'webappdesktop', 'python', '-m', 'uvicorn', 'sidecar_app:app', '--host', '127.0.0.1', '--port', '8765'],
    { cwd: sidecar, stdio: 'inherit', shell: isWin },
  );
  child.on('exit', (code) => process.exit(code ?? 0));
}
