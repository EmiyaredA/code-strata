import { build as viteBuild } from "vite";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
const root = fileURLToPath(new URL("../", import.meta.url));
await viteBuild({ root, configFile: resolve(root, "vite.config.js") });
await build({ entryPoints: [resolve(root, "scripts/parse-js.mjs")], bundle: true, platform: "node", format: "cjs", outfile: resolve(root, "../../scripts/parse-js.cjs"), minify: true, legalComments: "linked" });

await build({ entryPoints: [resolve(root, "scripts/analyze-code.mjs")], bundle: true, platform: "node", format: "cjs", outfile: resolve(root, "../../scripts/analyze-code.cjs"), minify: true, legalComments: "linked" });
