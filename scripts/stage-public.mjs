import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const dest = resolve("public-release");
rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
for (const name of ["library_index.json", "metadata.json", "file_list.json", "vite.svg", "favicon.png", "favicon.ico"]) {
  const src = resolve("public", name);
  if (existsSync(src)) cpSync(src, resolve(dest, name));
}
const assets = resolve("public", "assets");
if (existsSync(assets)) cpSync(assets, resolve(dest, "assets"), { recursive: true });
const predict = resolve("public", "predict");
if (existsSync(predict)) cpSync(predict, resolve(dest, "predict"), { recursive: true });
for (const family of ["ABX3", "II-VI", "III-V", "IV-VI"]) {
  const src = resolve("public", family, "bulk_cifs");
  if (!existsSync(src)) continue;
  const out = resolve(dest, family, "bulk_cifs");
  mkdirSync(out, { recursive: true });
  cpSync(src, out, { recursive: true });
}
console.log("staged catalog, builder CIF templates, and predict samples into public-release");
