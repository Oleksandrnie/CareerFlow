const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(require("node:path").join(__dirname, "../careerflow/static/app.js"), "utf8");
const elements = new Map();
function element(selector) {
  if (!elements.has(selector)) elements.set(selector, {
    innerHTML: "",
    textContent: "",
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {},
  });
  return elements.get(selector);
}
const document = {
  querySelector: element,
  querySelectorAll: () => [],
  addEventListener() {},
  createElement: () => ({
    textContent: "",
    get innerHTML() { return this.textContent; },
  }),
};
const analysis = {
  id: 7,
  resume_version_id: 43,
  resume_kind_at_analysis: "vacancy",
  resume_version_at_analysis: 1,
  match_percent: 87,
  is_stale: true,
  result: {
    disclaimer: "Heuristic result",
    counts: { covered: 1, partial: 0, missing: 0 },
    requirements: [],
    keywords: [],
    covered_keywords: [],
  },
};
const responses = {
  "/api/vacancies?archived=undefined": [],
  "/api/resumes?kind=vacancy&vacancy_id=1": [{ id: 43, kind: "vacancy", version: 1, label: "Latest" }],
  "/api/vacancies/1/ats": analysis,
};
const context = vm.createContext({
  document,
  fetch: async url => ({
    ok: true,
    headers: { get: () => "application/json" },
    json: async () => responses[url],
  }),
  setTimeout,
});
vm.runInContext(source, context);

(async () => {
  await vm.runInContext("renderAts({id: 1, description_confirmed_at: '2026-09-26'})", context);
  const html = element("#content-panel").innerHTML;
  assert.match(html, /value="43" selected/);
  assert.match(html, /Historical ATS text match — rerun analysis/);
  assert.match(html, /Vacancy Resume v1 \(ID 43\)/);
  assert.match(html, /This result is historical/);
  assert.match(html, /not a probability of getting the job or a definitive assessment of suitability/);
  process.stdout.write("ATS UI provenance contract passed\n");
})().catch(error => {
  process.stderr.write(`${error.stack}\n`);
  process.exitCode = 1;
});
