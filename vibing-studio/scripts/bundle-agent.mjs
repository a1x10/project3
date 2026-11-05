// Bundles STELLA CODER into ./agent (one ESM file + skills) so electron-builder ships it in resources/agent.
// electron-builder never copies node_modules into extraResources, hence the single-file bundle.
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = path.resolve(root, "../stella-coder");
const out = path.join(root, "agent");
const run = (cmd, cwd) => execSync(cmd, { cwd, stdio: "inherit", shell: true });

if (!fs.existsSync(path.join(src, "package.json"))) throw new Error("stella-coder not found next to vibing-studio");
if (!fs.existsSync(path.join(src, "node_modules"))) run("npm ci --no-audit --no-fund", src);
run("npm run build", src);

fs.rmSync(out, { recursive: true, force: true });
await build({
  entryPoints: [path.join(src, "dist/cli/main.js")],
  outfile: path.join(out, "dist/cli/main.js"),
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  // CommonJS dependencies inside an ESM bundle need require/__dirname
  banner: { js: "import{createRequire as __cr}from'module';import{fileURLToPath as __fu}from'url';import{dirname as __dn}from'path';const require=__cr(import.meta.url);const __filename=__fu(import.meta.url);const __dirname=__dn(__filename);" },
  // Ink imports the React devtools bridge statically but only uses it with DEV=true: stub it out
  plugins: [
    {
      name: "stub-devtools",
      setup(b) {
        b.onResolve({ filter: /^react-devtools-core$/ }, () => ({ path: "react-devtools-core", namespace: "stub" }));
        b.onLoad({ filter: /.*/, namespace: "stub" }, () => ({ contents: "export default { initialize() {}, connectToDevTools() {} };", loader: "js" }));
      },
    },
  ],
  logLevel: "warning",
  legalComments: "none",
});
fs.cpSync(path.join(src, "builtin"), path.join(out, "builtin"), { recursive: true });
if (fs.existsSync(path.join(src, "dist/router"))) fs.cpSync(path.join(src, "dist/router"), path.join(out, "dist/router"), { recursive: true });
const pkg = JSON.parse(fs.readFileSync(path.join(src, "package.json"), "utf8"));
fs.writeFileSync(path.join(out, "package.json"), JSON.stringify({ name: pkg.name, version: pkg.version, type: "module", private: true }, null, 2));
console.log(`agent bundled: ${(fs.statSync(path.join(out, "dist/cli/main.js")).size / 1048576).toFixed(1)} MB`);
