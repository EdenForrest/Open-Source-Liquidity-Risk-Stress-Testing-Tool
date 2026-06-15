// Renders MODEL.md -> standalone HTML with KaTeX-rendered math.
// Usage: node md2html.mjs <input.md> <output.html>
import { readFileSync, writeFileSync } from 'node:fs';
import { marked } from 'marked';
import katex from 'katex';

const [, , inPath, outPath] = process.argv;
let src = readFileSync(inPath, 'utf8');

// Extract math first so marked never touches the TeX.
const blocks = [];
const inlines = [];
// $$ ... $$  (display)
src = src.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => {
  blocks.push(tex.trim());
  return `@@MATHBLOCK${blocks.length - 1}@@`;
});
// $ ... $  (inline) — avoid matching across newlines or empty
src = src.replace(/\$(?!\s)([^\n$]+?)(?<!\s)\$/g, (_, tex) => {
  inlines.push(tex.trim());
  return `@@MATHINLINE${inlines.length - 1}@@`;
});

marked.setOptions({ gfm: true, breaks: false });
let html = marked.parse(src);

html = html.replace(/@@MATHBLOCK(\d+)@@/g, (_, i) =>
  katex.renderToString(blocks[+i], { displayMode: true, throwOnError: false })
);
html = html.replace(/@@MATHINLINE(\d+)@@/g, (_, i) =>
  katex.renderToString(inlines[+i], { displayMode: false, throwOnError: false })
);

const katexCss = readFileSync(
  new URL('../node_modules/katex/dist/katex.min.css', import.meta.url), 'utf8'
);

const doc = `<!doctype html><html><head><meta charset="utf-8">
<style>${katexCss}</style>
<style>
  @page { size: A4; margin: 18mm 16mm; }
  body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         font-size: 10.5pt; line-height: 1.5; color: #1a1a1a; max-width: 100%; }
  h1 { font-size: 20pt; border-bottom: 2px solid #333; padding-bottom: 6px; }
  h2 { font-size: 15pt; margin-top: 1.6em; border-bottom: 1px solid #ddd; padding-bottom: 3px;
       page-break-after: avoid; }
  h3 { font-size: 12pt; margin-top: 1.2em; page-break-after: avoid; }
  code { background: #f4f4f4; padding: 1px 4px; border-radius: 3px;
         font-family: "Cascadia Code", Consolas, monospace; font-size: 9pt; }
  pre { background: #f6f8fa; padding: 10px 12px; border-radius: 5px; overflow-x: auto; }
  pre code { background: none; padding: 0; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 9.5pt; }
  th, td { border: 1px solid #ccc; padding: 5px 8px; text-align: left; }
  th { background: #f0f0f0; }
  blockquote { border-left: 3px solid #ccc; margin-left: 0; padding-left: 14px; color: #555; }
  hr { border: none; border-top: 1px solid #ddd; margin: 1.6em 0; }
  .katex-display { overflow-x: auto; overflow-y: hidden; padding: 2px 0; }
  a { color: #0b66c3; text-decoration: none; }
  h2, h3, table, pre, .katex-display { break-inside: avoid; }
</style></head><body>${html}</body></html>`;

writeFileSync(outPath, doc, 'utf8');
console.log('Wrote', outPath, `(${doc.length} bytes)`);
