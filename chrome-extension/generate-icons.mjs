/**
 * generate-icons.mjs
 *
 * Converts icon.svg → icon16.png, icon48.png, icon128.png using the
 * `sharp` library. Run once after cloning:
 *
 *   node chrome-extension/generate-icons.mjs
 *
 * Requires Node 18+ and sharp:
 *   npm install --save-dev sharp   (or: npx --yes sharp)
 */

import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { join, dirname } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const svgPath   = join(__dirname, 'icons', 'icon.svg');
const svg       = readFileSync(svgPath);

let sharp;
try {
  sharp = (await import('sharp')).default;
} catch {
  console.error('sharp is not installed. Run: npm install --save-dev sharp');
  process.exit(1);
}

for (const size of [16, 48, 128]) {
  const out = join(__dirname, 'icons', `icon${size}.png`);
  await sharp(svg).resize(size, size).png().toFile(out);
  console.log(`✓ icons/icon${size}.png`);
}
console.log('Icons generated.');
