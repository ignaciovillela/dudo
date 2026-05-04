import { Resvg } from "@resvg/resvg-js";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const svgPath = join(__dirname, "..", "static", "og-cover.svg");
const outPath = join(__dirname, "..", "static", "og-cover.png");

const svg = readFileSync(svgPath, "utf8");
const resvg = new Resvg(svg, {
  fitTo: { mode: "width", value: 1200 },
});

const pngData = resvg.render();
const pngBuffer = pngData.asPng();

writeFileSync(outPath, pngBuffer);
console.log(`og-cover.png generado (${pngBuffer.byteLength} bytes)`);

