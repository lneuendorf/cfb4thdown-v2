// Fails if a hex color literal or an arbitrary Tailwind color value appears outside tokens.css.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("../src", import.meta.url).pathname;
const SKIP = [join(ROOT, "styles", "tokens.css"), join(ROOT, "dev", "fixtures")];
const HEX = /#[0-9a-fA-F]{3,8}\b/;
const ARBITRARY_COLOR = /\b(?:bg|text|border|fill|stroke|ring|outline)-\[(?:#|rgb|hsl)/;
const findings = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (SKIP.some((s) => path.startsWith(s))) continue;
    if (statSync(path).isDirectory()) walk(path);
    else if (/\.(tsx?|css)$/.test(name)) {
      readFileSync(path, "utf8").split("\n").forEach((line, i) => {
        // Anchor fragments like href="#how" are not colors.
        const code = line.replace(/(["'`])#[a-z][\w-]*\1/g, "");
        if (HEX.test(code) || ARBITRARY_COLOR.test(code)) findings.push(`${path}:${i + 1}: ${line.trim()}`);
      });
    }
  }
}

walk(ROOT);
if (findings.length) {
  console.error(findings.join("\n"));
  process.exit(1);
}
console.log("tokens: clean");
