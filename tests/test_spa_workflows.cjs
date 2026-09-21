const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../careerflow/static/app.js"), "utf8");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function fakeElement(tagName = "DIV") {
  const children = new Map();
  let html = "";
  return {
    tagName,
    dataset: {},
    fields: {},
    disabled: false,
    checked: false,
    value: "",
    textContent: "",
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {},
    focus() { this.focused = true; },
    querySelector(selector) {
      if (!children.has(selector)) {
        const child = fakeElement(selector.includes("button") ? "BUTTON" : selector.includes("form") ? "FORM" : "DIV");
        children.set(selector, child);
      }
      return children.get(selector);
    },
    get innerHTML() { return html; },
    set innerHTML(value) { html = value; children.clear(); this.lists = new Map(); },
    lists: new Map(),
  };
}

class MockFormData {
  constructor(form) { this.entries = Object.entries(form?.fields || {}); }
  append(key, value) { this.entries.push([key, value]); }
  get(key) { return this.entries.find(([name]) => name === key)?.[1] ?? null; }
  [Symbol.iterator]() { return this.entries[Symbol.iterator](); }
}

function harness() {
  const routes = new Map();
  const calls = [];
  const root = new Map();
  const listeners = new Map();
  const workspace = fakeElement();
  let panel = fakeElement();
  Object.defineProperty(workspace, "innerHTML", {
    get() { return this.html || ""; },
    set(value) { this.html = value; panel = fakeElement(); this.lists = new Map(); root.clear(); },
  });
  function rootElement(selector) {
    if (selector === "#workspace") return workspace;
    if (selector === "#content-panel") return panel;
    if (!root.has(selector)) root.set(selector, fakeElement(selector === "#import-form" ? "FORM" : "DIV"));
    return root.get(selector);
  }
  function list(selector) {
    const owner = selector === "[data-tab]" ? workspace : panel;
    if (owner.lists.has(selector)) return owner.lists.get(selector);
    const attributes = {
      "[data-tab]": ["data-tab", "tab"],
      "[data-preview-resume]": ["data-preview-resume", "previewResume"],
      "[data-use-resume]": ["data-use-resume", "useResume"],
      "[data-clone-resume]": ["data-clone-resume", "cloneResume"],
      "[data-submit-resume]": ["data-submit-resume", "submitResume"],
      "[data-open-ai-run]": ["data-open-ai-run", "openAiRun"],
      "[data-delete-file]": ["data-delete-file", "deleteFile"],
      ".note-card": ["data-note-id", "noteId"],
    };
    const [attribute, dataKey] = attributes[selector] || [];
    if (!attribute) return [];
    const html = selector === "[data-tab]" ? workspace.innerHTML : panel.innerHTML;
    const matches = [...html.matchAll(new RegExp(`${attribute}="([^"]+)"`, "g"))];
    const items = matches.map(([, value]) => {
      const item = fakeElement(selector === ".note-card" ? "FORM" : "BUTTON");
      item.dataset[dataKey] = value;
      return item;
    });
    owner.lists.set(selector, items);
    return items;
  }
  const document = {
    querySelector(selector) {
      if (selector === "#content-panel") return panel;
      if (selector === "#workspace") return workspace;
      if (selector.startsWith("#") && ["#vacancy-list", "#import-dialog", "#import-form", "#vacancy-file", "#drop-zone", "#selected-file", "#show-archived", "#new-vacancy", "#toast", "#status-selector", "#archive-vacancy", "#delete-vacancy", "#edit-overview", "#export-report"].includes(selector)) return rootElement(selector);
      return panel.querySelector(selector);
    },
    querySelectorAll: list,
    addEventListener(name, callback) { listeners.set(name, callback); },
    createElement() {
      return {
        textContent: "",
        get innerHTML() {
          return String(this.textContent).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
        },
      };
    },
    body: { appendChild() {} },
  };
  const fetch = async (url, options = {}) => {
    const key = `${options.method || "GET"} ${url}`;
    calls.push(key);
    if (!routes.has(key)) throw new Error(`Unmocked request: ${key}`);
    const responder = routes.get(key);
    const result = await (typeof responder === "function" ? responder(options) : responder);
    const { status = 200, payload } = result && "payload" in result ? result : { payload: result };
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: () => "application/json" },
      json: async () => payload,
    };
  };
  routes.set("GET /api/vacancies?archived=false", []);
  const context = vm.createContext({ document, fetch, FormData: MockFormData, window: { confirm: () => true, prompt: () => "DELETE" }, setTimeout: () => 0 });
  vm.runInContext(source, context);
  return {
    context, document, routes, calls, listeners,
    get panel() { return panel; },
    run(code) { return vm.runInContext(code, context); },
  };
}

const first = { id: 1, title: "First role", company: "A", salary: "", source: "", source_type: "text", status: "Saved", summary: "", description: "FIRST_DESCRIPTION", created_at: "2026-09-21 10:00:00", match_percent: null };
const second = { ...first, id: 2, title: "Second role", description: "SECOND_DESCRIPTION" };

async function testStaleNotesAndCardSelection() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  assert.match(app.panel.innerHTML, /FIRST_DESCRIPTION/);
  const notes = deferred();
  app.routes.set("GET /api/vacancies/1/notes", notes.promise);
  const pending = app.run('openTab("Notes", state.selected)');
  await app.run('openTab("Overview", state.selected)');
  assert.match(app.panel.innerHTML, /FIRST_DESCRIPTION/);
  notes.resolve([{ id: 1, body: "old note", created_at: "2026-09-21 10:00:00" }]);
  await pending;
  assert.match(app.panel.innerHTML, /FIRST_DESCRIPTION/);
  assert.doesNotMatch(app.panel.innerHTML, /New note/);

  const slowCard = deferred();
  app.routes.set("GET /api/vacancies/1", slowCard.promise);
  app.routes.set("GET /api/vacancies/2", second);
  const click = id => app.listeners.get("click")({ target: { closest: selector => selector === ".vacancy-card" ? { dataset: { id } } : null } });
  const oldSelection = click("1");
  await click("2");
  slowCard.resolve(first);
  await oldSelection;
  assert.equal(app.run("state.selected.id"), 2);
  assert.match(app.panel.innerHTML, /SECOND_DESCRIPTION/);
}

async function testResumePreviewAndEditableCopy() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  app.routes.set("GET /api/resumes?kind=master", [{ id: 42, kind: "master", version: 2, label: "Stored", original_filename: "cv.txt", created_at: "2026-09-21 10:00:00" }]);
  app.routes.set("GET /api/resumes?kind=vacancy&vacancy_id=1", []);
  app.routes.set("GET /api/resumes/42", { id: 42, kind: "master", version: 2, content_text: "Python <script>not markup</script>" });
  await app.run('openTab("Resume", state.selected)');
  assert.match(app.panel.innerHTML, /api\/resumes\/42\/download/);
  await app.document.querySelectorAll("[data-preview-resume]")[0].onclick();
  assert.match(app.panel.querySelector("#resume-preview").innerHTML, /Python &lt;script&gt;not markup&lt;\/script&gt;/);
  const form = app.panel.querySelector("#resume-form");
  form.querySelector("input[name=file]").value = "old-selection.pdf";
  await app.document.querySelectorAll("[data-use-resume]")[0].onclick();
  assert.equal(form.querySelector("textarea[name=text]").value, "Python <script>not markup</script>");
  assert.equal(form.querySelector("input[name=label]").value, "Based on master v2");
  assert.equal(form.querySelector("input[name=file]").value, "");
  assert.equal(app.calls.filter(call => call === "POST /api/resumes").length, 0);
}

async function testSavedAiDetailAndLateRun() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  const run = { id: 9, prompt: "Saved prompt", model: "gpt-5.6-luna", status: "completed", response: "FULL_SAVED_ANSWER", created_at: "2026-09-21 10:00:00" };
  const failed = { ...run, id: 8, status: "failed", response: "", error: "SAVED_FAILURE_DETAIL" };
  app.routes.set("GET /api/vacancies/1/ai-runs", [run, failed]);
  app.routes.set("GET /api/vacancies/1/ai-runs/9", run);
  app.routes.set("GET /api/vacancies/1/ai-runs/8", failed);
  await app.run('openTab("AI / Codex", state.selected)');
  await app.document.querySelectorAll("[data-open-ai-run]")[0].onclick();
  assert.match(app.panel.querySelector("#ai-history-result").innerHTML, /FULL_SAVED_ANSWER/);
  await app.document.querySelectorAll("[data-open-ai-run]")[1].onclick();
  assert.match(app.panel.querySelector("#ai-history-result").innerHTML, /SAVED_FAILURE_DETAIL/);
  await app.run('openTab("Overview", state.selected)');
  await app.run('openTab("AI / Codex", state.selected)');
  await app.document.querySelectorAll("[data-open-ai-run]")[0].onclick();
  assert.match(app.panel.querySelector("#ai-history-result").innerHTML, /FULL_SAVED_ANSWER/);

  app.routes.set("POST /api/vacancies/1/ai-runs", { ...failed, id: 11, error: "CODEX_EXECUTION_FAILED" });
  const failedForm = app.panel.querySelector("#ai-form");
  failedForm.fields = { prompt: "Retry prompt", model: "", action: "Custom request" };
  await failedForm.onsubmit({ preventDefault() {}, currentTarget: failedForm });
  assert.match(app.panel.querySelector("#ai-error").textContent, /CODEX_EXECUTION_FAILED/);
  assert.equal(failedForm.querySelector("button[type=submit]").disabled, false);

  const pending = deferred();
  app.routes.set("POST /api/vacancies/1/ai-runs", pending.promise);
  const aiForm = app.panel.querySelector("#ai-form");
  aiForm.fields = { prompt: "New prompt", model: "", action: "Custom request" };
  const button = aiForm.querySelector("button[type=submit]");
  const submission = aiForm.onsubmit({ preventDefault() {}, currentTarget: aiForm });
  assert.equal(button.disabled, true);
  app.run(`renderVacancy(${JSON.stringify(second)})`);
  pending.resolve({ ...run, id: 10, response: "LATE_FIRST_VACANCY_ANSWER" });
  await submission;
  assert.equal(button.disabled, false);
  assert.match(app.panel.innerHTML, /SECOND_DESCRIPTION/);
  assert.doesNotMatch(app.panel.innerHTML, /LATE_FIRST_VACANCY_ANSWER/);
}

async function testMutationFailuresAndDuplicateRecovery() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  app.routes.set("GET /api/vacancies/1/attachments", []);
  await app.run('openTab("Files", state.selected)');
  const attachmentForm = app.panel.querySelector("#attachment-form");
  const attachButton = attachmentForm.querySelector("button[type=submit]");
  const pending = deferred();
  app.routes.set("POST /api/vacancies/1/attachments", pending.promise);
  const submit = () => attachmentForm.onsubmit({ preventDefault() {}, currentTarget: attachmentForm });
  const firstSubmission = submit();
  await submit();
  assert.equal(attachButton.disabled, true);
  assert.equal(app.calls.filter(call => call === "POST /api/vacancies/1/attachments").length, 1);
  pending.resolve({ status: 422, payload: { detail: [{ loc: ["body", "file"], msg: "File is empty" }] } });
  await firstSubmission;
  assert.equal(attachButton.disabled, false);
  assert.match(app.panel.querySelector("#attachment-error").textContent, /file: File is empty/);
  app.routes.set("POST /api/vacancies/1/attachments", { id: 5, filename: "retry.txt" });
  await submit();
  assert.equal(app.calls.filter(call => call === "POST /api/vacancies/1/attachments").length, 2);
  assert.equal(attachButton.disabled, false);

  app.routes.set("GET /api/vacancies/1/notes", [{ id: 3, body: "Original", created_at: "2026-09-21 10:00:00" }]);
  await app.run('openTab("Notes", state.selected)');
  const noteForm = app.document.querySelectorAll(".note-card")[0];
  noteForm.fields = { body: "Changed" };
  app.routes.set("PATCH /api/vacancies/1/notes/3", () => { throw new Error("network offline"); });
  await noteForm.onsubmit({ preventDefault() {}, currentTarget: noteForm });
  assert.match(noteForm.querySelector("[data-note-error]").textContent, /network offline/);
  assert.equal(noteForm.querySelector("button[type=submit]").disabled, false);

  const statusSelector = app.document.querySelector("#status-selector");
  statusSelector.value = "Applied";
  app.routes.set("POST /api/vacancies/1/status", () => { throw new Error("status network failed"); });
  await statusSelector.onchange({ currentTarget: statusSelector });
  assert.equal(statusSelector.value, "Saved");
  assert.equal(statusSelector.disabled, false);
  assert.match(app.document.querySelector("#toast").textContent, /status network failed/);
}

(async () => {
  await testStaleNotesAndCardSelection();
  await testResumePreviewAndEditableCopy();
  await testSavedAiDetailAndLateRun();
  await testMutationFailuresAndDuplicateRecovery();
  process.stdout.write("SPA workflow regressions passed\n");
})().catch(error => {
  process.stderr.write(`${error.stack}\n`);
  process.exitCode = 1;
});
