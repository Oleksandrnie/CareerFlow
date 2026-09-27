const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const css = fs.readFileSync(path.join(__dirname, "../careerflow/static/app.css"), "utf8");
const app = fs.readFileSync(path.join(__dirname, "../careerflow/static/app.js"), "utf8");

assert.match(css, /\.item-row > :first-child \{ min-width: 0; flex: 1 1 240px; \}/);
assert.match(css, /@media \(max-width: 1100px\) \{\s+\.item-row \{ flex-direction: column; align-items: flex-start; \}\s+\.item-row > :first-child \{ width: 100%; flex: 0 1 auto; \}/);
assert.match(css, /\.item-row \.actions \{ display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
assert.match(css, /\.item-row \.actions > button, \.item-row \.actions > a \{ width: 100%; \}/);
assert.match(css, /\.master-list-head \{ flex-direction: row; align-items: center; justify-content: space-between;/);
assert.match(css, /#cleaning-review:has\(\.cleaning-review\) \.cleaning-review > \.form-grid \{ grid-template-columns: 1fr; \}/);
assert.match(css, /\.score-row \{ flex-direction: column; align-items: flex-start; \}/);
assert.match(css, /\.score \{ display: grid; place-items: center; width: 82px; min-width: 82px; height: 82px; aspect-ratio: 1; flex: 0 0 82px;/);
assert.match(css, /\.table-scroll th:first-child, \.table-scroll td:first-child \{ width: 58%; white-space: normal; overflow-wrap: anywhere; \}/);
assert.match(css, /\.table-scroll th:not\(:first-child\), \.table-scroll td:not\(:first-child\) \{ text-align:center; \}/);
assert.match(app, /renderEmpty\(\{ preserveSidebar = false \} = \{\}\)/);
assert.match(app, /renderEmpty\(\{ preserveSidebar: true \}\)/);
assert.match(css, /@media \(max-width: 420px\) \{\s+\.topbar \{ grid-template-columns: minmax\(0, 1fr\) auto; grid-template-rows: auto auto; column-gap: 8px;/);
assert.match(css, /\.topbar-actions \{ grid-column: 2; grid-row: 1; min-width: 0; flex-wrap: nowrap;/);
assert.match(css, /\.primary-nav \{ grid-column: 1 \/ -1; grid-row: 2; \}/);
assert.match(css, /@media \(max-width: 340px\) \{\s+\.topbar h1 \{ font-size: 16px; \}/);
assert.match(css, /\.topbar-actions \.primary \{ width: 34px; min-width: 34px; padding-inline: 0; font-size: 0; \}/);

console.log("Responsive UI contract passed");
