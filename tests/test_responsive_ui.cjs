const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const css = fs.readFileSync(path.join(__dirname, "../careerflow/static/app.css"), "utf8");

assert.match(css, /\.item-row > :first-child \{ min-width: 0; flex: 1 1 240px; \}/);
assert.match(css, /@media \(max-width: 1100px\) \{\s+\.item-row \{ flex-direction: column; align-items: flex-start; \}\s+\.item-row > :first-child \{ width: 100%; flex: 0 1 auto; \}/);
assert.match(css, /\.item-row \.actions \{ display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
assert.match(css, /\.item-row \.actions > button, \.item-row \.actions > a \{ width: 100%; \}/);
assert.match(css, /\.master-list-head \{ flex-direction: row; align-items: center; justify-content: space-between;/);
assert.match(css, /#cleaning-review:has\(\.cleaning-review\) \.cleaning-review > \.form-grid \{ grid-template-columns: 1fr; \}/);
assert.match(css, /\.score-row \{ flex-direction: column; align-items: flex-start; \}/);
assert.match(css, /\.table-scroll th:first-child, \.table-scroll td:first-child \{ width: 58%; white-space: normal; overflow-wrap: anywhere; \}/);
assert.match(css, /@media \(max-width: 420px\) \{\s+\.topbar \{ grid-template-columns: minmax\(0, 1fr\); grid-template-rows: auto auto auto; \}/);

console.log("Responsive UI contract passed");
