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
  const elementListeners = new Map();
  let html = "";
  return {
    tagName,
    dataset: {},
    fields: {},
    disabled: false,
    checked: false,
    hidden: false,
    value: "",
    textContent: "",
    classList: { add() {}, remove() {}, toggle(name, force) { this[name] = force ?? !this[name]; } },
    addEventListener(name, callback) { elementListeners.set(name, callback); },
    dispatch(name, event = {}) { return elementListeners.get(name)?.(event); },
    setAttribute(name, value) { this[name] = String(value); },
    getAttribute(name) { return this[name] ?? null; },
    removeAttribute(name) { delete this[name]; },
    remove() { this.removed = true; },
    showModal() { this.open = true; },
    close() { this.open = false; },
    reset() { this.fields = {}; },
    focus() { this.focused = true; },
    closest() { return fakeElement("DIV"); },
    querySelector(selector) {
      if (!children.has(selector)) {
        const child = fakeElement(selector.includes("button") ? "BUTTON" : selector.includes("form") ? "FORM" : "DIV");
        children.set(selector, child);
      }
      return children.get(selector);
    },
    querySelectorAll() { return []; },
    get innerHTML() { return this.html ?? html; },
    set innerHTML(value) {
      for (const [form] of String(value).matchAll(/<form\b[^>]*>[\s\S]*?<\/form>/g)) {
        assert.match(form, /<button\b[^>]*\btype="submit"[^>]*>/, "Every rendered form needs an explicit submit button");
      }
      html = value; children.clear(); this.lists = new Map();
    },
    lists: new Map(),
  };
}

class MockFormData {
  constructor(form) { this.entries = Object.entries(form?.fields || {}); }
  append(key, value) { this.entries.push([key, value]); }
  get(key) { return this.entries.find(([name]) => name === key)?.[1] ?? null; }
  set(key, value) {
    this.delete(key);
    this.entries.push([key, value]);
  }
  delete(key) { this.entries = this.entries.filter(([name]) => name !== key); }
  [Symbol.iterator]() { return this.entries[Symbol.iterator](); }
}

function harness(storage = new Map()) {
  const routes = new Map();
  const calls = [];
  const root = new Map();
  const listeners = new Map();
  const workspace = fakeElement();
  const themeToggle = fakeElement("BUTTON");
  const sidebarToggle = fakeElement("BUTTON");
  const sectionButtons = ["vacancies", "master-resume", "analytics"].map(section => {
    const button = fakeElement("BUTTON");
    button.dataset.section = section;
    return button;
  });
  const vacancySidebar = fakeElement("ASIDE");
  vacancySidebar.inert = false;
  const appLayout = fakeElement("MAIN");
  const documentElement = fakeElement("HTML");
  documentElement.style = {};
  let panel = fakeElement();
  Object.defineProperty(workspace, "innerHTML", {
    get() { return this.html || ""; },
    set(value) { this.html = value; panel = fakeElement(); this.lists = new Map(); root.clear(); },
  });
  function rootElement(selector) {
    if (selector === "#workspace") return workspace;
    if (selector === "#content-panel") return panel;
    if (selector === "#app-layout") return appLayout;
    if (selector === "#sidebar-toggle") return sidebarToggle;
    if (selector === "#vacancy-sidebar") return vacancySidebar;
    if (selector === "#import-form") {
      if (!root.has(selector)) root.set(selector, fakeElement("FORM"));
      return root.get(selector);
    }
    if (!root.has(selector)) root.set(selector, fakeElement(selector === "#import-form" ? "FORM" : "DIV"));
    return root.get(selector);
  }
  function list(selector) {
    if (selector === "button[data-section]") return sectionButtons;
    const owner = ["[data-tab]", "[data-stage]", "[data-section]"].includes(selector)
      || (selector === "[data-delete-resume]" && workspace.innerHTML.includes("master-panel")) ? workspace : panel;
    if (owner.lists.has(selector)) return owner.lists.get(selector);
    const attributes = {
      "[data-tab]": ["data-tab", "tab"],
      "[data-stage]": ["data-stage", "stage"],
      "[data-section]": ["data-section", "section"],
      "[data-open-resume]": ["data-open-resume", "openResume"],
      "[data-preview-resume]": ["data-preview-resume", "previewResume"],
      "[data-use-resume]": ["data-use-resume", "useResume"],
      "[data-clone-resume]": ["data-clone-resume", "cloneResume"],
      "[data-submit-resume]": ["data-submit-resume", "submitResume"],
      "[data-delete-resume]": ["data-delete-resume", "deleteResume"],
      "[data-open-ai-run]": ["data-open-ai-run", "openAiRun"],
      "[data-delete-file]": ["data-delete-file", "deleteFile"],
      ".note-card": ["data-note-id", "noteId"],
    };
    const [attribute, dataKey] = attributes[selector] || [];
    if (!attribute) return [];
    const html = ["[data-tab]", "[data-stage]", "[data-section]"].includes(selector) ? workspace.innerHTML : panel.innerHTML;
    const matches = [...html.matchAll(new RegExp(`${attribute}="([^"]+)"`, "g"))];
    const items = matches.map(([, value]) => {
      const item = fakeElement(selector === ".note-card" ? "FORM" : "BUTTON");
      item.dataset[dataKey] = value;
      if (selector === "[data-open-ai-run]") {
        const row = fakeElement("ARTICLE");
        item.closest = target => target === ".ai-history-row" ? row : null;
        item.aiRow = row;
      }
      return item;
    });
    owner.lists.set(selector, items);
    return items;
  }
  const document = {
    documentElement,
    querySelector(selector) {
      if (selector === "#content-panel") return panel;
      if (selector === "#workspace") return workspace;
      if (selector === "#theme-toggle") return themeToggle;
      if (["#app-layout", "#sidebar-toggle", "#vacancy-sidebar"].includes(selector)) return rootElement(selector);
      if (selector === "[data-interview-count]") return workspace.querySelector(selector);
      if (selector.startsWith("#") && ["#vacancy-list", "#import-dialog", "#import-form", "#import-review", "#import-error", "#vacancy-file", "#drop-zone", "#selected-file", "#show-archived", "#new-vacancy", "#toast", "#status-selector", "#archive-vacancy", "#delete-vacancy", "#edit-overview", "#export-report"].includes(selector)) return rootElement(selector);
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
  routes.set("GET /api/codex/models", { models: [{ id: "gpt-5.6-luna", name: "Luna", efforts: ["low", "medium"] }], default_model: "gpt-5.6-luna", default_effort: "low", source: "codex-cli", warning: "" });
  let reloadCount = 0;
  let viewportWidth = 1200;
  const sidebarViewportListeners = new Set();
  const window = {
    confirm: () => true,
    prompt: () => "DELETE",
    location: { reload() { reloadCount += 1; } },
    scrollY: 0,
    matchMedia(query) {
      const maxWidth = Number(query.match(/max-width:\s*(\d+)px/)?.[1] || 0);
      return {
        matches: maxWidth > 0 && viewportWidth <= maxWidth,
        addEventListener(name, callback) {
          if (name === "change" && maxWidth === 900) sidebarViewportListeners.add(callback);
        },
      };
    },
    setViewport(width) {
      const wasCompact = viewportWidth <= 900;
      viewportWidth = width;
      const isCompact = viewportWidth <= 900;
      if (wasCompact !== isCompact) {
        sidebarViewportListeners.forEach(callback => callback({ matches: isCompact, media: "(max-width: 900px)" }));
      }
    },
  };
  const localStorage = {
    getItem(key) { return storage.get(key) ?? null; },
    setItem(key, value) { storage.set(key, String(value)); },
    removeItem(key) { storage.delete(key); },
  };
  const context = vm.createContext({ document, fetch, FormData: MockFormData, URLSearchParams, window, localStorage, setTimeout: () => 0 });
  vm.runInContext(source, context);
  return {
    context, document, routes, calls, listeners, sectionButtons,
    get panel() { return panel; },
    workspace, themeToggle, sidebarToggle, vacancySidebar, appLayout, documentElement,
    run(code) { return vm.runInContext(code, context); },
    window,
    get reloadCount() { return reloadCount; },
  };
}

const first = { id: 1, title: "First role", company: "A", salary: "", source: "", source_type: "text", status: "Saved", summary: "", description: "FIRST_DESCRIPTION", created_at: "2026-09-21 10:00:00", match_percent: null };
const second = { ...first, id: 2, title: "Second role", description: "SECOND_DESCRIPTION" };

async function testStaleNotesAndCardSelection() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify({ ...first, description_confirmed_at: "2026-09-21" })})`);
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

async function testVacancyNavigationRestoresLastSelection() {
  const app = harness();
  app.routes.set("GET /api/vacancies/1/notes", []);
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  assert.equal(app.run("state.lastSelectedVacancy.id"), 1);
  await app.run('openTab("Notes", state.selected)');
  assert.equal(app.run("state.lastSelectedVacancyTab"), "Notes");

  app.run('state.section = "master-resume"; state.selected = null');
  await app.run("showVacancies()");
  assert.equal(app.run("state.selected.id"), 1, "returning to Vacancies should restore the last vacancy");
  assert.equal(app.run("state.activeTab"), "Notes", "returning to Vacancies should restore the last vacancy tab");
  assert.match(app.document.querySelector("#workspace").innerHTML, /First role/);

  await app.run("showVacancies()");
  assert.equal(app.run("state.selected"), null, "a second Vacancies click should return to the landing screen");
  assert.equal(app.run("state.lastSelectedVacancy"), null, "landing screen should clear the remembered vacancy");
  assert.equal(app.run("state.lastSelectedVacancyTab"), null, "landing screen should clear the remembered tab");
  assert.match(app.document.querySelector("#workspace").innerHTML, /Build your job-search workspace/);
}

async function testVacancyNavigationRestoresAfterReload() {
  const storage = new Map();
  const firstSession = harness(storage);
  firstSession.run(`renderVacancy(${JSON.stringify(first)})`);
  await firstSession.run('openTab("Notes", state.selected)');
  assert.match(storage.get("careerflow-last-vacancy-navigation"), /"vacancyId":1/);
  assert.match(storage.get("careerflow-last-vacancy-navigation"), /"tab":"Notes"/);

  const reloaded = harness(storage);
  reloaded.routes.set("GET /api/vacancies?archived=false", [first]);
  reloaded.routes.set("GET /api/vacancies/1", first);
  await reloaded.run("loadVacancies()");
  assert.equal(reloaded.run("state.selected.id"), 1, "reload should restore the saved vacancy");
  assert.equal(reloaded.run("state.activeTab"), "Notes", "reload should restore the saved vacancy tab");
}

async function testOverviewLinkAndTabOrder() {
  const app = harness();
  const vacancy = {
    ...first,
    source: "https://example.com/jobs/project-manager",
    source_type: "html",
  };
  app.run(`renderVacancy(${JSON.stringify(vacancy)})`);
  const workspaceHtml = app.run('document.querySelector("#workspace").innerHTML');
  const tabOrder = [...workspaceHtml.matchAll(/data-tab="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(tabOrder, ["Overview", "Resume", "ATS", "AI / Codex", "Timeline", "Notes", "Files"]);
  assert.match(app.panel.innerHTML, /href="https:\/\/example\.com\/jobs\/project-manager"/);
  assert.match(app.panel.innerHTML, /target="_blank"/);
  assert.doesNotMatch(app.panel.innerHTML, /VACANCY LINK/);

  const longTitle = "Senior Principal Platform Engineer — Distributed Systems and Infrastructure Leadership, Europe";
  app.run(`renderVacancy(${JSON.stringify({ ...vacancy, title: longTitle })})`);
  assert.match(app.workspace.innerHTML, new RegExp(longTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), "the full vacancy title should be visible without hover");
  assert.equal(app.run(`compactVacancyTitle(${JSON.stringify(longTitle)})`), longTitle);
  app.run(`state.vacancies = [${JSON.stringify({ ...vacancy, title: longTitle })}]; renderList()`);
  assert.match(app.run("listEl.innerHTML"), new RegExp(longTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
}

async function testThemeTogglePreservesCurrentView() {
  const views = [
    { section: "analytics", tab: null },
    { section: "master-resume", tab: null },
    ...["Overview", "Resume", "ATS", "AI / Codex", "Timeline", "Notes", "Files"].map(tab => ({ section: "vacancies", tab })),
  ];
  for (const view of views) {
    const storage = new Map([["careerflow-theme", "light"], ["careerflow-locale", "en"]]);
    const app = harness(storage);
    await new Promise(resolve => setTimeout(resolve, 0));
    app.run(`state.section = ${JSON.stringify(view.section)}; state.activeTab = ${JSON.stringify(view.tab)}; state.selected = ${JSON.stringify(first)}; state.lastSelectedVacancy = state.selected; state.lastSelectedVacancyTab = ${JSON.stringify(view.tab)};`);
    app.workspace.innerHTML = `<main data-view="${view.section}" data-tab="${view.tab || ""}"><form><textarea>Unsaved draft</textarea></form></main>`;
    app.workspace.scrollTop = 246;
    const importForm = app.document.querySelector("#import-form");
    importForm.fields = { text: "An unsaved vacancy description" };
    const importDialog = app.document.querySelector("#import-dialog");
    importDialog.open = true;
    const markupBefore = app.workspace.innerHTML;

    app.themeToggle.dispatch("click");
    assert.equal(app.run("state.theme"), "dark", `${view.section}/${view.tab || "home"}: toggle should activate dark theme`);
    assert.equal(app.documentElement.dataset.theme, "dark");
    assert.equal(app.documentElement.style.colorScheme, "dark");
    assert.equal(app.themeToggle.getAttribute("aria-pressed"), "true");
    assert.equal(storage.get("careerflow-theme"), "dark");
    assert.equal(app.run("state.section"), view.section, `${view.section}/${view.tab || "home"}: section should be preserved`);
    assert.equal(app.run("state.activeTab"), view.tab, `${view.section}/${view.tab || "home"}: active tab should be preserved`);
    assert.equal(app.run("state.selected.id"), first.id, `${view.section}/${view.tab || "home"}: selected vacancy should be preserved`);
    assert.equal(app.workspace.innerHTML, markupBefore, `${view.section}/${view.tab || "home"}: rendered view should not be replaced`);
    assert.equal(app.workspace.scrollTop, 246, `${view.section}/${view.tab || "home"}: scroll position should be preserved`);
    assert.equal(importForm.fields.text, "An unsaved vacancy description");
    assert.equal(importDialog.open, true, `${view.section}/${view.tab || "home"}: open dialog should remain open`);
    assert.equal(app.reloadCount, 0, `${view.section}/${view.tab || "home"}: theme changes must not reload the app`);

    app.themeToggle.dispatch("click");
    assert.equal(app.run("state.theme"), "light");
    assert.equal(storage.get("careerflow-theme"), "light");
    assert.equal(app.run("state.section"), view.section);
    assert.equal(app.run("state.activeTab"), view.tab);
    assert.equal(app.workspace.innerHTML, markupBefore);
    assert.equal(importForm.fields.text, "An unsaved vacancy description");
    assert.equal(importDialog.open, true);
    assert.equal(app.reloadCount, 0);
  }
}

async function testEditAndInterviewSubmitControls() {
  const app = harness();
  app.routes.set("GET /api/vacancies/1/interviews", []);
  app.run(`renderVacancy(${JSON.stringify({ ...first, description_confirmed_at: "2026-09-21" })})`);
  app.run('renderEdit(state.selected)');
  const editForm = app.panel.querySelector("#edit-form");
  editForm.fields = { title: "Updated role", company: "A", salary: "", source: "", summary: "", description: "FIRST_DESCRIPTION" };
  const updated = { ...first, title: "Updated role" };
  app.routes.set("PATCH /api/vacancies/1", updated);
  app.routes.set("GET /api/vacancies?archived=false", [updated]);
  await editForm.onsubmit({ preventDefault() {}, currentTarget: editForm });
  assert.match(app.panel.innerHTML, /FIRST_DESCRIPTION/);
  assert.equal(app.calls.filter(call => call === "PATCH /api/vacancies/1").length, 1);

  app.routes.set("GET /api/vacancies/1/timeline", []);
  app.routes.set("GET /api/vacancies/1/interviews", []);
  await app.run('openTab("Timeline", state.selected)');
  assert.match(app.panel.innerHTML, /type="submit">Add interview/);
}

async function testInterviewCounterLifecycleAndStaleReads() {
  const app = harness();
  const initialInterviews = deferred();
  const interviews = [];
  app.routes.set("GET /api/vacancies/1/interviews", initialInterviews.promise);
  app.routes.set("GET /api/vacancies/1/timeline", []);
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  const timeline = app.run('openTab("Timeline", state.selected)');
  assert.equal(
    app.calls.filter(call => call === "GET /api/vacancies/1/interviews").length,
    1,
    "the stage bar and Timeline must share an in-flight interview request",
  );
  initialInterviews.resolve([]);
  await timeline;
  assert.equal(app.document.querySelector("[data-interview-count]").textContent, "0");
  assert.match(app.panel.innerHTML, /Add interview #1/);

  const staleBeforeAdd = deferred();
  let serveStaleRead = true;
  app.routes.set("GET /api/vacancies/1/interviews", () => {
    if (serveStaleRead) {
      serveStaleRead = false;
      return staleBeforeAdd.promise;
    }
    return interviews.slice();
  });
  const staleRefresh = app.run("refreshInterviewCount(state.selected)");
  const pendingPost = deferred();
  app.routes.set("POST /api/vacancies/1/interviews", pendingPost.promise);
  app.routes.set("GET /api/vacancies/1", first);
  app.routes.set("GET /api/vacancies?archived=false", [first]);
  const firstForm = app.panel.querySelector("#interview-form");
  firstForm.fields = { interview_at: "2026-09-27T10:00", interview_type: "HR", note: "", result: "" };
  const firstButton = firstForm.querySelector("button[type=submit]");
  const firstSubmission = firstForm.onsubmit({ preventDefault() {}, currentTarget: firstForm });
  await firstForm.onsubmit({ preventDefault() {}, currentTarget: firstForm });
  assert.equal(firstButton.disabled, true);
  assert.equal(
    app.calls.filter(call => call === "POST /api/vacancies/1/interviews").length,
    1,
    "an interview form cannot be submitted twice while its request is pending",
  );
  interviews.push({ id: 1 });
  pendingPost.resolve(interviews[0]);
  await firstSubmission;
  assert.match(app.document.querySelector("#workspace").innerHTML, /data-interview-count>1<\/span>/);
  assert.match(app.panel.innerHTML, /Add interview #2/);

  staleBeforeAdd.resolve([]);
  await staleRefresh;
  assert.equal(
    app.document.querySelector("[data-interview-count]").textContent,
    "1",
    "a pre-mutation response must not overwrite the successful add",
  );

  app.routes.set("POST /api/vacancies/1/interviews", () => {
    const interview = { id: interviews.length + 1 };
    interviews.push(interview);
    return interview;
  });
  const secondForm = app.panel.querySelector("#interview-form");
  secondForm.fields = { interview_at: "2026-09-28T10:00", interview_type: "Technical", note: "", result: "" };
  await secondForm.onsubmit({ preventDefault() {}, currentTarget: secondForm });
  assert.match(app.document.querySelector("#workspace").innerHTML, /data-interview-count>2<\/span>/);
  assert.match(app.panel.innerHTML, /Add interview #3/);

  await app.run('openTab("Overview", state.selected)');
  assert.match(app.document.querySelector("#workspace").innerHTML, /data-interview-count>2<\/span>/);
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  assert.match(
    app.document.querySelector("#workspace").innerHTML,
    /data-interview-count>2<\/span>/,
    "reopening a vacancy should render its last authoritative count immediately",
  );
  await app.run("refreshInterviewCount(state.selected)");
  await app.run('openTab("Timeline", state.selected)');
  assert.equal(app.document.querySelector("[data-interview-count]").textContent, "2");

  const lateFirstVacancy = deferred();
  app.routes.set("GET /api/vacancies/1/interviews", lateFirstVacancy.promise);
  const oldSelectionRefresh = app.run("refreshInterviewCount(state.selected)");
  app.routes.set("GET /api/vacancies/2/interviews", []);
  app.run(`renderVacancy(${JSON.stringify(second)})`);
  await app.run("refreshInterviewCount(state.selected)");
  lateFirstVacancy.resolve([{ id: 1 }, { id: 2 }, { id: 3 }]);
  await oldSelectionRefresh;
  assert.equal(app.run("state.selected.id"), 2);
  assert.equal(
    app.document.querySelector("[data-interview-count]").textContent,
    "0",
    "a late count for the old vacancy must not overwrite the newer selection",
  );
}

async function testResumePreviewAndEditableCopy() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  app.routes.set("GET /api/resumes?kind=master", [{ id: 42, kind: "master", version: 2, label: "Stored", original_filename: "cv.txt", created_at: "2026-09-21 10:00:00" }]);
  app.routes.set("GET /api/resumes?kind=vacancy&vacancy_id=1", [{ id: 43, kind: "vacancy", version: 1, label: "Tailored", original_filename: "tailored.txt", source_resume_id: 42, source_kind: "master", source_version: 2, created_at: "2026-09-21 10:00:00" }]);
  app.routes.set("GET /api/resumes/42", { id: 42, kind: "master", version: 2, content_text: "Python <script>not markup</script>" });
  app.routes.set("GET /api/resumes/43", { id: 43, kind: "vacancy", version: 1, content_text: "# Python\n<script>not markup</script>" });
  await app.run('openTab("Resume", state.selected)');
  assert.match(app.panel.innerHTML, /api\/resumes\/43\/download/);
  assert.match(app.panel.innerHTML, /Based on Master Resume v2/);
  assert.doesNotMatch(app.panel.innerHTML, /api\/resumes\/42\/download/);
  await app.document.querySelectorAll("[data-preview-resume]")[0].onclick();
  assert.match(app.panel.querySelector("#resume-preview").innerHTML, /<h1>Python<\/h1>/);
  assert.match(app.panel.querySelector("#resume-preview").innerHTML, /&lt;script&gt;not markup&lt;\/script&gt;/);
  const form = app.panel.querySelector("#resume-form");
  form.querySelector("input[name=file]").value = "old-selection.pdf";
  await app.document.querySelectorAll("[data-use-resume]")[0].onclick();
  assert.equal(form.querySelector("textarea[name=text]").value, "# Python\n<script>not markup</script>");
  assert.equal(form.querySelector("input[name=label]").value, "Based on Vacancy Resume v1");
  assert.equal(form.querySelector("input[name=file]").value, "");
  app.panel.querySelector("#master-source").value = "42";
  await app.panel.querySelector("#create-from-master").onclick();
  assert.equal(form.querySelector("textarea[name=text]").value, "Python <script>not markup</script>");
  assert.equal(form.querySelector("input[name=label]").value, "Based on Master Resume v2");
  assert.equal(form.querySelector("input[name=source_resume_id]").value, 42);
  assert.equal(app.calls.filter(call => call === "POST /api/resumes").length, 0);
}

async function testResumeDeleteInBothLists() {
  const app = harness();
  const master = { id: 51, kind: "master", version: 3, label: "Master", created_at: "2026-09-21 10:00:00" };
  app.routes.set("GET /api/resumes?kind=master", [master]);
  await app.run("renderMasterResume()");
  assert.match(app.document.querySelector("#workspace").innerHTML, /data-delete-resume="51"/);
  app.window.confirm = () => false;
  await app.document.querySelectorAll("[data-delete-resume]")[0].onclick();
  assert.equal(app.calls.filter(call => call === "DELETE /api/resumes/51").length, 0);
  app.window.confirm = () => true;
  app.routes.set("DELETE /api/resumes/51", { deleted_resume_id: 51, kind: "master", version: 3, history_retained: true });
  app.routes.set("GET /api/resumes?kind=master", []);
  await app.document.querySelectorAll("[data-delete-resume]")[0].onclick();
  assert.equal(app.calls.filter(call => call === "DELETE /api/resumes/51").length, 1);
  assert.doesNotMatch(app.document.querySelector("#workspace").innerHTML, /data-delete-resume="51"/);

  app.run(`renderVacancy(${JSON.stringify(first)})`);
  app.routes.set("GET /api/resumes?kind=master", []);
  app.routes.set("GET /api/resumes?kind=vacancy&vacancy_id=1", [{ id: 61, kind: "vacancy", version: 1, label: "Tailored", created_at: "2026-09-21 10:00:00", source_resume_id: 51, source_kind: "master", source_version: 3, source_deleted_at: "2026-09-22" }]);
  await app.run('openTab("Resume", state.selected)');
  assert.match(app.panel.innerHTML, /Source version deleted/);
  app.routes.set("DELETE /api/resumes/61", { deleted_resume_id: 61, kind: "vacancy", version: 1, history_retained: true });
  app.routes.set("GET /api/resumes?kind=vacancy&vacancy_id=1", []);
  await app.document.querySelectorAll("[data-delete-resume]")[0].onclick();
  assert.equal(app.calls.filter(call => call === "DELETE /api/resumes/61").length, 1);
  assert.doesNotMatch(app.panel.innerHTML, /data-delete-resume="61"/);
}

async function testStageFourMasterCrmAndAtsAcceptance() {
  const app = harness();
  app.routes.set("GET /api/vacancies/1/interviews", []);
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  await app.run("refreshInterviewCount(state.selected)");
  const workspace = app.document.querySelector("#workspace");
  assert.match(fs.readFileSync(path.join(__dirname, "../careerflow/static/index.html"), "utf8"), /data-section="master-resume"/);
  assert.match(workspace.innerHTML, /data-stage="Interview"/);
  assert.match(workspace.innerHTML, /data-interview-count>0/);
  app.routes.set("GET /api/vacancies/1/interviews", [{ id: 1 }, { id: 2 }]);
  await app.run("refreshInterviewCount(state.selected, state.viewEpoch)");
  assert.equal(app.calls.filter(call => call === "GET /api/vacancies/1/interviews").length, 2);
  assert.equal(app.document.querySelector("[data-interview-count]").textContent, "2");
  assert.equal(app.run("state.selected.id"), 1);

  app.routes.set("POST /api/vacancies/1/status", () => { throw new Error("stage update failed"); });
  const stageButtons = app.document.querySelectorAll("[data-stage]");
  const applied = stageButtons.find(button => button.dataset.stage === "Applied");
  const saved = stageButtons.find(button => button.dataset.stage === "Saved");
  await applied.onclick();
  assert.equal(saved.classList.active, true);
  assert.equal(applied.classList.active, false);
  assert.match(app.document.querySelector("#toast").textContent, /stage update failed/);

  const updated = { ...first, status: "Applied" };
  app.routes.set("POST /api/vacancies/1/status", updated);
  app.routes.set("GET /api/vacancies?archived=false", [updated]);
  await app.document.querySelectorAll("[data-stage]").find(button => button.dataset.stage === "Applied").onclick();
  const appliedAfterUpdate = app.document.querySelectorAll("[data-stage]").find(button => button.dataset.stage === "Applied");
  assert.equal(appliedAfterUpdate.getAttribute("aria-pressed"), "true");
  assert.equal(appliedAfterUpdate.classList.active, true);

  app.routes.set("GET /api/resumes?kind=master", [{ id: 42, kind: "master", version: 3, label: "Canonical", created_at: "2026-09-21 10:00:00" }]);
  app.routes.set("GET /api/resumes?kind=vacancy&vacancy_id=1", []);
  await app.run('openTab("Resume", state.selected)');
  assert.match(app.panel.innerHTML, /Create from Master Resume/);
  assert.match(app.panel.innerHTML, /Master Resume v3/);
  assert.match(app.panel.innerHTML, /Save vacancy resume version/);
  assert.doesNotMatch(app.panel.innerHTML, /Save Master Resume version/);

  app.routes.set("GET /api/resumes?kind=vacancy&vacancy_id=1", []);
  app.run('state.selected.description_confirmed_at = "2026-09-21"');
  app.routes.set("GET /api/vacancies/1/ats", null);
  await app.run('openTab("ATS", state.selected)');
  assert.match(app.panel.innerHTML, /Master Resume v3 — Canonical/);
  assert.match(app.panel.innerHTML, /data-run-assessment="manager_audit"/);
  const atsWorkspace = app.panel.innerHTML;
  assert.match(atsWorkspace, /data-run-assessment="vacancy_match"/);
  assert.match(fs.readFileSync(path.join(__dirname, "../careerflow/static/app.js"), "utf8"), /not an employer decision and not a Codex analysis/);

  app.run("state.selected.description_confirmed_at = null");
  await app.run('openTab("ATS", state.selected)');
  assert.match(app.panel.innerHTML, /Review the cleaned vacancy description before running ATS/);
  assert.doesNotMatch(app.panel.innerHTML, /data-open-resume/);
}

async function testMasterResumeWorkspaceAndSave() {
  const app = harness();
  app.routes.set("GET /api/resumes?kind=master", [{ id: 42, kind: "master", version: 1, label: "Initial", original_filename: null, created_at: "2026-09-21 10:00:00" }]);
  await app.run("renderMasterResume()");
  assert.match(app.document.querySelector("#workspace").innerHTML, /GLOBAL IMMUTABLE LIBRARY/);
  assert.match(app.document.querySelector("#workspace").innerHTML, /Initial/);
  assert.match(app.document.querySelector("#workspace").innerHTML, /Version 1/);
  assert.match(app.document.querySelector("#workspace").innerHTML, /Download Markdown/);
  assert.match(app.document.querySelector("#workspace").innerHTML, /Resume list/);
  assert.match(app.document.querySelector("#workspace").innerHTML, /id="open-master-resume-dialog">Add resume/);
  assert.match(app.document.querySelector("#workspace").innerHTML, /<dialog id="master-resume-dialog"/);
  const addResume = app.document.querySelector("#workspace").querySelector("#open-master-resume-dialog");
  addResume.onclick();
  assert.equal(app.document.querySelector("#workspace").querySelector("#master-resume-dialog").open, true);
  const masterForm = app.document.querySelector("#workspace").querySelector("#resume-form");
  assert.match(fs.readFileSync(path.join(__dirname, "../careerflow/static/app.js"), "utf8"), /<label>Resume name<input name="label"/);
  assert.notEqual(masterForm.querySelector("input[name=label]").focused, true, "opening a new Master Resume dialog must not trigger the mobile keyboard");
  masterForm.fields = { label: "Second version", text: "# Updated profile", source_resume_id: "" };
  app.routes.set("POST /api/resumes", options => {
    assert.equal(options.body.get("kind"), "master");
    return { id: 43 };
  });
  app.routes.set("GET /api/resumes?kind=master", [{ id: 42, kind: "master", version: 1, label: "Initial", created_at: "2026-09-21 10:00:00" }, { id: 43, kind: "master", version: 2, label: "Second version", created_at: "2026-09-22 10:00:00" }]);
  await masterForm.onsubmit({ preventDefault() {}, currentTarget: masterForm });
  assert.equal(app.calls.filter(call => call === "POST /api/resumes").length, 1);
  assert.match(app.document.querySelector("#workspace").innerHTML, /Second version/);
  assert.match(app.document.querySelector("#workspace").innerHTML, /Version 2/);
}

async function testImportPreviewEditConfirmAndRecovery() {
  const app = harness();
  const importForm = app.document.querySelector("#import-form");
  const submit = importForm.querySelector("button[type=submit]");
  const codexChoice = importForm.querySelector('input[name="use_codex"]');
  const originalFile = { name: "role.html", size: 120, type: "text/html", lastModified: 1234 };
  importForm.fields = { text: "Raw vacancy", file: originalFile, title: "Engineer", company: "A", salary: "", source: "Board" };

  const pendingPreview = deferred();
  app.routes.set("POST /api/vacancies/import-preview", options => {
    assert.equal(options.body.get("text"), "Raw vacancy");
    assert.equal(options.body.get("use_codex"), null, "Codex must remain opt-in");
    return pendingPreview.promise;
  });
  const firstPreview = importForm.onsubmit({ preventDefault() {} });
  await importForm.onsubmit({ preventDefault() {} });
  assert.equal(app.calls.filter(call => call === "POST /api/vacancies/import-preview").length, 1, "preview cannot double-submit");
  pendingPreview.resolve({ raw_description: "Raw vacancy", description: "Clean draft", method: "local:rules", removed_blocks: [], uncertain_blocks: [] });
  await firstPreview;

  const review = app.document.querySelector("#import-review");
  assert.match(review.innerHTML, /Cleaned draft \(editable\)/);
  assert.equal(submit.hidden, true);
  review.querySelector("[data-cleaned-description]").value = "Edited clean draft";
  importForm.fields = { ...importForm.fields, text: "Changed raw vacancy" };
  await review.querySelector("[data-confirm-cleaning]").onclick();
  assert.equal(app.calls.filter(call => call === "POST /api/vacancies").length, 0);
  assert.match(review.querySelector("#import-review-error").textContent, /changed after preview/i);

  review.querySelector("[data-cancel-cleaning]").onclick();
  assert.equal(app.run("state.importPreview"), null);
  assert.equal(review.innerHTML, "");
  assert.equal(submit.hidden, false);
  assert.equal(submit.textContent, "Review description");

  codexChoice.checked = true;
  app.routes.set("POST /api/vacancies/import-preview", options => {
    assert.equal(options.body.get("text"), "Changed raw vacancy");
    assert.equal(options.body.get("use_codex"), "true", "Codex is sent only after the explicit checkbox opt-in");
    assert.equal(options.body.get("codex_profile"), "primary", "Codex cleanup starts with the primary profile");
    return { raw_description: "Changed raw vacancy", description: "Codex clean draft", method: "codex:rules", removed_blocks: [{ text: "Apply", reason: "CTA" }], uncertain_blocks: [] };
  });
  let importSuccessPromptCount = 0;
  app.window.confirm = () => { importSuccessPromptCount++; return true; };
  await importForm.onsubmit({ preventDefault() {} });
  assert.equal(importSuccessPromptCount, 0, "successful import cleanup must not prompt for escalation");
  const confirm = review.querySelector("[data-confirm-cleaning]");
  review.querySelector("[data-cleaned-description]").value = "User-confirmed draft";
  const pendingCreate = deferred();
  app.routes.set("POST /api/vacancies", options => {
    assert.equal(options.body.get("cleaned_description"), "User-confirmed draft");
    assert.equal(options.body.get("cleaning_method"), "codex:rules");
    assert.equal(options.body.get("use_codex"), null, "Codex preview flag is not forwarded to vacancy creation");
    return pendingCreate.promise;
  });
  app.routes.set("GET /api/vacancies?archived=false", []);
  const creation = confirm.onclick();
  await confirm.onclick();
  assert.equal(app.calls.filter(call => call === "POST /api/vacancies").length, 1, "confirmation cannot double-submit");
  pendingCreate.resolve({ ...first, description: "User-confirmed draft", raw_description: "Changed raw vacancy", description_confirmed_at: "2026-09-26" });
  await creation;
  assert.equal(app.run("state.importPreview"), null);
  assert.equal(submit.hidden, false, "closing a completed import must restore Review for the next vacancy");

  const fallbackApp = harness();
  const fallbackForm = fallbackApp.document.querySelector("#import-form");
  fallbackForm.fields = { text: "Fallback vacancy", file: originalFile, title: "Engineer", company: "A", salary: "", source: "Board", use_codex: "true" };
  fallbackForm.querySelector('input[name="use_codex"]').checked = true;
  let importPrompt = "";
  fallbackApp.window.confirm = message => { importPrompt = message; return true; };
  fallbackApp.routes.set("POST /api/vacancies/import-preview", options => {
    const profile = options.body.get("codex_profile");
    if (profile === "primary") return { raw_description: "Fallback vacancy", description: "Local draft", method: "local-fallback:rules", removed_blocks: [], uncertain_blocks: [], diagnostics: { classification_source: "local", codex_requested: true, fallback_used: true, escalation_available: true, escalation_model: "gpt-5.6-sol", escalation_effort: "medium" } };
    assert.equal(profile, "escalation");
    return { raw_description: "Fallback vacancy", description: "Escalated draft", method: "codex:rules", removed_blocks: [], uncertain_blocks: [], diagnostics: { classification_source: "codex", codex_requested: true, fallback_used: false } };
  });
  await fallbackForm.onsubmit({ preventDefault() {} });
  assert.match(importPrompt, /primary Codex model.*stronger model.*gpt-5\.6-sol \/ medium/i);
  assert.match(fallbackApp.document.querySelector("#import-review").innerHTML, /Cleaning method: codex:rules/);

  const cancelApp = harness();
  const cancelForm = cancelApp.document.querySelector("#import-form");
  cancelForm.fields = { text: "Fallback vacancy", file: originalFile, title: "Engineer", company: "A", salary: "", source: "Board", use_codex: "true" };
  cancelForm.querySelector('input[name="use_codex"]').checked = true;
  let cancelPreviewCalls = 0;
  cancelApp.window.confirm = () => false;
  cancelApp.routes.set("POST /api/vacancies/import-preview", options => {
    cancelPreviewCalls++;
    assert.equal(options.body.get("codex_profile"), "primary");
    return { raw_description: "Fallback vacancy", description: "Local draft", method: "local-fallback:rules", removed_blocks: [], uncertain_blocks: [], diagnostics: { classification_source: "local", codex_requested: true, fallback_used: true, escalation_available: true, escalation_model: "gpt-5.6-sol", escalation_effort: "medium" } };
  });
  await cancelForm.onsubmit({ preventDefault() {} });
  assert.equal(cancelPreviewCalls, 1, "Cancel keeps the import local fallback without retrying");
  assert.match(cancelApp.document.querySelector("#import-review").innerHTML, /Cleaning method: local-fallback:rules/);
}

async function testUrlImportStructuredDefaultsAndEditableMetadata() {
  const app = harness();
  const importForm = app.document.querySelector("#import-form");
  importForm.fields = { url: "https://jobs.example/role", text: "", title: "", company: "", salary: "", source: "" };
  app.routes.set("POST /api/vacancies/import-preview", () => ({
    raw_description: "Page and vacancy text",
    description: "Build reliable systems",
    method: "json-ld",
    source_type: "url",
    url_import_token: "preview-token",
    inferred_fields: {
      title: "Platform Engineer",
      company: "Example Corp",
      salary: "80000–100000 EUR YEAR",
      source: "https://jobs.example/role",
    },
    extracted_fields: {
      title: "Platform Engineer",
      company: "Example Corp",
      salary: "80000–100000 EUR YEAR",
      date_posted: "2026-09-25",
      locations: ["Amsterdam", "Utrecht"],
    },
    removed_blocks: [],
    uncertain_blocks: [],
  }));
  await importForm.onsubmit({ preventDefault() {} });

  assert.equal(importForm.querySelector('[name="title"]').value, "Platform Engineer");
  assert.equal(importForm.querySelector('[name="company"]').value, "Example Corp");
  assert.equal(importForm.querySelector('[name="salary"]').value, "80000–100000 EUR YEAR");
  assert.equal(importForm.querySelector('[name="source"]').value, "https://jobs.example/role");
  const review = app.document.querySelector("#import-review");
  assert.match(review.innerHTML, /Detected fields/);
  assert.match(review.innerHTML, /Amsterdam, Utrecht/);

  importForm.fields = {
    ...importForm.fields,
    title: "Lead Platform Engineer",
    company: "Edited Company",
    source: "https://canonical.example/role",
  };
  app.routes.set("POST /api/vacancies", options => {
    assert.equal(options.body.get("url_import_token"), "preview-token");
    assert.equal(options.body.get("title"), "Lead Platform Engineer");
    assert.equal(options.body.get("company"), "Edited Company");
    assert.equal(options.body.get("source"), "https://canonical.example/role");
    return { ...first, title: "Lead Platform Engineer", company: "Edited Company", source_type: "url" };
  });
  app.routes.set("GET /api/vacancies?archived=false", []);
  await review.querySelector("[data-confirm-cleaning]").onclick();
  assert.equal(app.calls.filter(call => call === "POST /api/vacancies").length, 1, "metadata edits after preview are allowed");
}

async function testExistingDescriptionReviewAndCodexOptIn() {
  const app = harness();
  app.run('state.locale = "ru"');
  assert.equal(app.run('translateText("Vacancy sections")'), "Разделы вакансии");
  const localizedHint = app.run('translateText("Only when selected; vacancy text will be sent to the local Codex CLI.")');
  assert.equal(localizedHint, "Только при выборе; текст вакансии будет передан локальному Codex CLI.");
  assert.doesNotMatch(localizedHint, /undefined/);
  app.run('state.locale = "en"');
  const confirmed = { ...first, description_confirmed_at: "2026-09-21", raw_description: "Raw FIRST_DESCRIPTION Apply" };
  app.run(`renderVacancy(${JSON.stringify(confirmed)})`);
  app.routes.set("POST /api/vacancies/1/description/preview", options => {
    assert.deepEqual(JSON.parse(options.body), { use_codex: false });
    return { raw_description: confirmed.raw_description, description: "Local cleaned", method: "local:rules", removed_blocks: [], uncertain_blocks: [] };
  });
  await app.panel.querySelector("#review-cleaning").onclick();
  assert.match(app.panel.innerHTML, /Clean description/);
  const review = app.panel.querySelector("#cleaning-review");
  assert.match(review.innerHTML, /Cleaning method: local:rules/);
  review.querySelector("[data-cleaned-description]").value = "Manually edited result";
  const pendingApply = deferred();
  app.routes.set("POST /api/vacancies/1/description/apply", options => {
    assert.deepEqual(JSON.parse(options.body), { description: "Manually edited result", method: "local:rules" });
    return pendingApply.promise;
  });
  app.routes.set("GET /api/vacancies?archived=false", []);
  const confirm = review.querySelector("[data-confirm-cleaning]");
  const applying = confirm.onclick({ currentTarget: confirm });
  await confirm.onclick({ currentTarget: confirm });
  assert.equal(app.calls.filter(call => call === "POST /api/vacancies/1/description/apply").length, 1, "existing-description confirmation cannot double-submit");
  pendingApply.resolve({ ...confirmed, description: "Manually edited result", description_revision: 2 });
  await applying;

  const codexApp = harness();
  codexApp.run(`renderVacancy(${JSON.stringify(confirmed)})`);
  codexApp.panel.querySelector("#review-cleaning-codex").checked = true;
  codexApp.routes.set("POST /api/vacancies/1/description/preview", options => {
    assert.deepEqual(JSON.parse(options.body), { use_codex: true, codex_profile: "primary" });
    return { raw_description: confirmed.raw_description, description: "Codex cleaned", method: "codex:rules", removed_blocks: [], uncertain_blocks: [], warnings: [], diagnostics: { classification_source: "codex", codex_requested: true, fallback_used: false, codex_profile: "primary", codex_model: "gpt-5.6-luna", codex_effort: "low" } };
  });
  let successPromptCount = 0;
  codexApp.window.confirm = () => { successPromptCount++; return true; };
  await codexApp.panel.querySelector("#review-cleaning").onclick();
  assert.equal(successPromptCount, 0, "successful primary cleanup must not prompt for escalation");
  assert.match(codexApp.panel.innerHTML, /Clean description/);
  assert.match(codexApp.panel.querySelector("#cleaning-review").innerHTML, /Cleaning method: codex:rules/);
  assert.match(codexApp.panel.querySelector("#cleaning-review").innerHTML, /Codex classification completed successfully/);
  assert.match(codexApp.panel.querySelector("#cleaning-review").innerHTML, /gpt-5\.6-luna.*low/);

  const fallbackApp = harness();
  fallbackApp.run(`renderVacancy(${JSON.stringify(confirmed)})`);
  fallbackApp.panel.querySelector("#review-cleaning-codex").checked = true;
  fallbackApp.routes.set("POST /api/vacancies/1/description/preview", options => {
    const body = JSON.parse(options.body);
    assert.equal(body.use_codex, true);
    if (body.codex_profile === "primary") return { raw_description: confirmed.raw_description, description: "Locally cleaned", method: "local-fallback:rules", removed_blocks: [], uncertain_blocks: [], warnings: ["Codex classification failed; local rules were used. Review uncertain blocks before confirmation."], diagnostics: { classification_source: "local", codex_requested: true, fallback_used: true, escalation_available: true, escalation_model: "gpt-5.6-sol", escalation_effort: "medium", codex_error: "SENSITIVE_RAW_CLI_ERROR" } };
    assert.equal(body.codex_profile, "escalation");
    return { raw_description: confirmed.raw_description, description: "Escalated cleaned", method: "codex:rules", removed_blocks: [], uncertain_blocks: [], warnings: [], diagnostics: { classification_source: "codex", codex_requested: true, fallback_used: false, codex_model: "gpt-5.6-sol", codex_effort: "medium" } };
  });
  let fallbackPrompt = "";
  fallbackApp.window.confirm = message => { fallbackPrompt = message; return true; };
  await fallbackApp.panel.querySelector("#review-cleaning").onclick();
  const fallbackReview = fallbackApp.panel.querySelector("#cleaning-review").innerHTML;
  assert.match(fallbackPrompt, /primary Codex model.*stronger model.*gpt-5\.6-sol \/ medium/i);
  assert.match(fallbackReview, /Cleaning method: codex:rules/);
  assert.doesNotMatch(fallbackReview, /SENSITIVE_RAW_CLI_ERROR/);

  const cancelApp = harness();
  cancelApp.run(`renderVacancy(${JSON.stringify(confirmed)})`);
  cancelApp.panel.querySelector("#review-cleaning-codex").checked = true;
  cancelApp.routes.set("POST /api/vacancies/1/description/preview", options => {
    const body = JSON.parse(options.body);
    assert.equal(body.codex_profile, "primary");
    return { raw_description: confirmed.raw_description, description: "Locally cleaned", method: "local-fallback:rules", removed_blocks: [], uncertain_blocks: [], warnings: ["Codex classification failed; local rules were used."], diagnostics: { classification_source: "local", codex_requested: true, fallback_used: true, escalation_available: true, escalation_model: "gpt-5.6-sol", escalation_effort: "medium" } };
  });
  cancelApp.window.confirm = () => false;
  await cancelApp.panel.querySelector("#review-cleaning").onclick();
  assert.match(cancelApp.panel.querySelector("#cleaning-review").innerHTML, /Cleaning method: local-fallback:rules/);
  assert.equal(cancelApp.calls.filter(call => call === "POST /api/vacancies/1/description/preview").length, 1, "Cancel keeps the local fallback without retrying");
}

async function testSavedAiDetailAndLateRun() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  const run = { id: 9, prompt: "Saved prompt", model: "gpt-5.6-luna", reasoning_effort: "low", response_language: "russian", status: "completed", response: "FULL_SAVED_ANSWER", created_at: "2026-09-21 10:00:00" };
  const failed = { ...run, id: 8, status: "failed", response: "", error: "SAVED_FAILURE_DETAIL" };
  app.routes.set("GET /api/vacancies/1/ai-runs", [run, failed]);
  const modelCatalog = { models: [{ id: "gpt-5.6-luna", name: "Luna", efforts: ["low", "medium"] }, { id: "gpt-6-sol", name: "Sol", efforts: ["high", "ultra"] }], default_model: "gpt-5.6-luna", default_effort: "low", source: "codex-cli", warning: "" };
  app.routes.set("GET /api/codex/models", modelCatalog);
  app.routes.set("GET /api/vacancies/1/ai-runs/9", run);
  app.routes.set("GET /api/vacancies/1/ai-runs/8", failed);
  await app.run('openTab("AI / Codex", state.selected)');
  assert.match(app.panel.innerHTML, /name="model" id="ai-model"/);
  assert.match(app.panel.innerHTML, /name="reasoning_effort" id="ai-effort"/);
  assert.match(app.panel.innerHTML, /name="response_language" id="ai-response-language"/);
  assert.match(app.panel.innerHTML, /value="auto" selected>Auto<\/option><option value="russian">Russian<\/option><option value="english">English/);
  assert.match(app.panel.innerHTML, /gpt-5\.6-luna · low · Russian/);
  assert.match(app.panel.innerHTML, /Review ATS analysis/);
  app.panel.querySelector("#ai-action").value = "Improve resume";
  app.panel.querySelector("#ai-action").onchange({ target: app.panel.querySelector("#ai-action") });
  assert.match(app.panel.querySelector("#ai-prompt").value, /truthful improvements/i);
  await app.run('setLocale("ru")');
  assert.match(app.panel.querySelector("#ai-prompt").value, /Предложи правдивые улучшения/);
  app.panel.querySelector("#ai-prompt").value = "My custom prompt";
  app.panel.querySelector("#ai-prompt").oninput({ target: app.panel.querySelector("#ai-prompt") });
  await app.run('setLocale("en")');
  assert.equal(app.panel.querySelector("#ai-prompt").value, "My custom prompt", "language switch preserves manually edited prompt");
  app.panel.querySelector("#ai-model").value = "gpt-6-sol";
  app.panel.querySelector("#ai-model").onchange();
  assert.equal(app.panel.querySelector("#ai-effort").value, "high");
  const savedButtons = app.document.querySelectorAll("[data-open-ai-run]");
  await savedButtons[0].onclick();
  const savedResponseHtml = savedButtons[0].aiRow.querySelector(".ai-inline-result").innerHTML;
  assert.match(savedResponseHtml, /FULL_SAVED_ANSWER/);
  assert.match(savedResponseHtml, /gpt-5\.6-luna · low/);
  assert.match(savedResponseHtml, /Russian/);
  assert.match(savedResponseHtml, /<details class="ai-prompt-disclosure"><summary>Show request<\/summary><div class="ai-prompt-text">Saved prompt<\/div><\/details>/);
  assert.doesNotMatch(savedResponseHtml, /<details[^>]*\bopen/);
  assert.ok(savedResponseHtml.indexOf("FULL_SAVED_ANSWER") < savedResponseHtml.indexOf("<details class=\"ai-prompt-disclosure\">"), "saved response must appear before the collapsed prompt disclosure");
  await savedButtons[1].onclick();
  assert.match(savedButtons[1].aiRow.querySelector(".ai-inline-result").innerHTML, /SAVED_FAILURE_DETAIL/);
  assert.doesNotMatch(app.panel.innerHTML, /id="ai-history-result"/);
  await app.run('openTab("Overview", state.selected)');
  await app.run('openTab("AI / Codex", state.selected)');
  const reopenedButton = app.document.querySelectorAll("[data-open-ai-run]")[0];
  await reopenedButton.onclick();
  assert.match(reopenedButton.aiRow.querySelector(".ai-inline-result").innerHTML, /FULL_SAVED_ANSWER/);

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

async function testTailoredResumeActionAndExplicitDraftHandoff() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  const run = {
    id: 15, vacancy_id: 1, action: "Create tailored resume",
    prompt: "Create a complete vacancy-tailored Markdown resume.",
    model: "gpt-5.6-sol", reasoning_effort: "medium", status: "completed",
    source_resume_id: 61, response: "# Tailored\n\nEvidence-based content",
    created_at: "2026-09-21 10:00:00",
  };
  const catalog = {
    models: [
      { id: "gpt-5.6-luna", name: "Luna", efforts: ["low"] },
      { id: "gpt-5.6-sol", name: "Sol", efforts: ["medium", "high"] },
    ],
    default_model: "gpt-5.6-luna", default_effort: "low", source: "codex-cli", warning: "",
  };
  app.routes.set("GET /api/vacancies/1/ai-runs", [run]);
  app.routes.set("GET /api/codex/models", catalog);
  app.routes.set("GET /api/vacancies/1/ai-runs/15", run);
  await app.run('openTab("AI / Codex", state.selected)');
  assert.match(app.panel.innerHTML, /Create tailored resume/);
  app.panel.querySelector("#ai-action").value = "Create tailored resume";
  app.panel.querySelector("#ai-action").onchange({ target: app.panel.querySelector("#ai-action") });
  assert.equal(app.panel.querySelector("#ai-model").value, "gpt-5.6-sol");
  assert.equal(app.panel.querySelector("#ai-effort").value, "medium");
  assert.match(app.panel.querySelector("#ai-prompt").value, /only candidate facts/i);

  const openedRow = app.document.querySelectorAll("[data-open-ai-run]")[0];
  await openedRow.onclick();
  assert.match(openedRow.aiRow.querySelector(".ai-inline-result").innerHTML, /data-create-ai-draft="15"/);
  assert.match(openedRow.aiRow.querySelector(".ai-inline-result").innerHTML, /Create editable resume draft/);
  assert.equal(openedRow.textContent, "Hide response");
  assert.equal(app.calls.filter(call => call.startsWith("POST /api/resumes")).length, 0);

  app.routes.set("GET /api/resumes?kind=master", []);
  app.routes.set("GET /api/resumes?kind=vacancy&vacancy_id=1", []);
  const draftButton = { dataset: { createAiDraft: "15" }, disabled: false, tagName: "BUTTON", textContent: "Create editable resume draft" };
  await app.listeners.get("click")({ target: { closest: selector => selector === "[data-create-ai-draft]" ? draftButton : null } });
  const resumeForm = app.panel.querySelector("#resume-form");
  assert.equal(resumeForm.querySelector("textarea[name=text]").value, run.response);
  assert.equal(resumeForm.querySelector("input[name=source_resume_id]").value, 61);
  assert.equal(app.calls.filter(call => call.startsWith("POST /api/resumes")).length, 0, "draft handoff must not save a resume version");
}

async function testAiResponseLanguageSubmission() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  app.routes.set("GET /api/vacancies/1/ai-runs", []);
  await app.run('openTab("AI / Codex", state.selected)');
  let submitted;
  app.routes.set("POST /api/vacancies/1/ai-runs", options => {
    submitted = JSON.parse(options.body);
    return {
      id: 21, vacancy_id: 1, action: submitted.action, prompt: submitted.prompt,
      model: submitted.model, reasoning_effort: submitted.reasoning_effort,
      response_language: submitted.response_language, status: "completed",
      response: "English answer", created_at: "2026-09-21 10:00:00",
    };
  });
  const aiForm = app.panel.querySelector("#ai-form");
  aiForm.fields = {
    action: "Analyze vacancy", prompt: "Analyze this role", model: "gpt-5.6-luna",
    reasoning_effort: "low", response_language: "english",
  };
  await aiForm.onsubmit({ preventDefault() {}, currentTarget: aiForm });
  assert.equal(submitted.response_language, "english");
}

async function testResponsiveSidebarToggleClosesAfterSelection() {
  const app = harness();
  assert.equal(app.run("state.sidebarOpen"), true, "desktop vacancy list starts open");
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  assert.equal(app.run("state.sidebarOpen"), false, "selecting a vacancy hides the desktop list");
  assert.match(app.workspace.innerHTML, /<h2 class="vacancy-title" tabindex="-1">First role<\/h2>/);
  const click = app.listeners.get("click");
  const toggleTarget = { closest: selector => selector === "#sidebar-toggle" ? {} : null };
  await click({ target: toggleTarget });
  assert.equal(app.run("state.sidebarOpen"), true);
  await click({ target: { closest: () => null } });
  assert.equal(app.run("state.sidebarOpen"), true, "clicking outside does not close the desktop panel");
  app.routes.set("GET /api/vacancies/1", first);
  const vacancyCard = {
    dataset: { id: "1" },
    closest: selector => selector === ".vacancy-card" ? vacancyCard : null,
  };
  await click({ target: vacancyCard });
  assert.equal(app.run("state.sidebarOpen"), false);
  assert.equal(app.workspace.querySelector(".workspace-head .vacancy-title").focused, true);
  await click({ target: toggleTarget });
  assert.equal(app.run("state.sidebarOpen"), true);
  const secondCard = {
    dataset: { id: "2" },
    closest: selector => selector === ".vacancy-card" ? secondCard : null,
  };
  app.routes.set("GET /api/vacancies/2", second);
  await click({ target: secondCard });
  assert.equal(app.run("state.selected.id"), 2);
  assert.equal(app.run("state.sidebarOpen"), false);
}

async function testSidebarAcrossMainSectionsAndBlankHeaderClick() {
  const app = harness();
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  app.routes.set("GET /api/analytics?bucket=month", {
    activity_metrics: {}, funnel: [], conversions: [], outcomes: {}, series: [], incomplete_records: [],
  });
  app.routes.set("GET /api/resumes?kind=master", []);
  await app.run("renderAnalytics()");
  app.run('state.activeTab = "ATS"; state.lastSelectedVacancyTab = "ATS"');
  const click = app.listeners.get("click");
  const toggleTarget = { closest: selector => selector === "#sidebar-toggle" ? {} : null };
  const workspaceBeforeToggle = app.workspace.innerHTML;

  assert.equal(app.sidebarToggle.hidden, false, "desktop drawer toggle stays available in Analytics");
  await click({ target: toggleTarget });
  assert.equal(app.run("state.sidebarOpen"), true);
  assert.equal(app.sectionButtons.find(button => button.dataset.section === "analytics").classList.active, true);
  assert.equal(app.run("state.section"), "analytics");
  assert.equal(app.run("state.selected.id"), first.id);
  assert.equal(app.run("state.activeTab"), "ATS");
  assert.equal(app.workspace.innerHTML, workspaceBeforeToggle, "opening the sidebar does not replace the current workspace");
  assert.equal(app.vacancySidebar.getAttribute("aria-hidden"), "false");
  assert.equal(app.vacancySidebar.inert, false);

  const blankHeaderArea = {
    closest: selector => selector === "[data-section]" ? { dataset: { section: "vacancies" } } : null,
  };
  await click({ target: blankHeaderArea });
  assert.equal(app.run("state.section"), "analytics", "blank header space does not act like a navigation control");
  assert.equal(app.run("state.selected.id"), first.id);
  assert.equal(app.workspace.innerHTML, workspaceBeforeToggle);
  assert.equal(app.run("state.sidebarOpen"), true);

  await click({ target: toggleTarget });
  assert.equal(app.run("state.sidebarOpen"), false);
  assert.equal(app.run("state.section"), "analytics");
  assert.equal(app.run("state.selected.id"), first.id);
  assert.equal(app.run("state.activeTab"), "ATS");
  assert.equal(app.workspace.innerHTML, workspaceBeforeToggle, "closing the sidebar leaves the current workspace intact");
  assert.equal(app.vacancySidebar.getAttribute("aria-hidden"), "true");
  assert.equal(app.vacancySidebar.inert, true);

  await app.run("renderMasterResume()");
  assert.equal(app.sidebarToggle.hidden, false, "desktop drawer toggle stays available in Master Resume");
  const masterWorkspace = app.workspace.innerHTML;
  await click({ target: toggleTarget });
  assert.equal(app.run("state.section"), "master-resume");
  assert.equal(app.run("state.activeTab"), "Master Resume");
  assert.equal(app.workspace.innerHTML, masterWorkspace);
  assert.equal(app.run("state.sidebarOpen"), true);
  assert.equal(app.sectionButtons.find(button => button.dataset.section === "master-resume").classList.active, true);
  await click({ target: toggleTarget });
  assert.equal(app.run("state.sidebarOpen"), false);
  assert.equal(app.run("state.section"), "master-resume");
  assert.equal(app.workspace.innerHTML, masterWorkspace);

  app.routes.set("GET /api/vacancies/1", first);
  const vacancyCard = {
    dataset: { id: "1" },
    closest: selector => selector === ".vacancy-card" ? vacancyCard : null,
  };
  await click({ target: toggleTarget });
  await click({ target: vacancyCard });
  assert.equal(app.run("state.section"), "vacancies", "selecting a vacancy from another section opens its workspace");
  assert.equal(app.run("state.selected.id"), first.id);
  assert.equal(app.run("state.activeTab"), "Overview");
  assert.equal(app.run("state.sidebarOpen"), false);
}

async function testSidebarResizeAndCompactDismissal() {
  const app = harness();
  assert.equal(app.sidebarToggle.hidden, false);
  assert.equal(app.run("state.sidebarOpen"), true);

  app.run('setSection("analytics")');
  assert.equal(app.sidebarToggle.hidden, false, "desktop sections keep the vacancy-list button available");
  assert.equal(app.run("state.sidebarOpen"), false);

  app.window.setViewport(700);
  assert.equal(app.sidebarToggle.hidden, false, "compact sections expose the drawer button after resize");
  assert.equal(app.run("state.sidebarOpen"), false);
  await app.listeners.get("click")({ target: { closest: selector => selector === "#sidebar-toggle" ? {} : null } });
  assert.equal(app.run("state.sidebarOpen"), true);
  await app.listeners.get("click")({ target: { closest: () => null } });
  assert.equal(app.run("state.sidebarOpen"), false, "outside clicks dismiss the compact drawer");

  app.window.setViewport(1200);
  assert.equal(app.sidebarToggle.hidden, false, "desktop sections keep the drawer button after resize");
  assert.equal(app.run("state.sidebarOpen"), false);

  app.run('setSection("vacancies")');
  assert.equal(app.sidebarToggle.hidden, false);
  assert.equal(app.run("state.sidebarOpen"), true);
  app.window.setViewport(700);
  assert.equal(app.run("state.sidebarOpen"), false, "compact viewport starts with the drawer closed");
  app.window.setViewport(1200);
  assert.equal(app.run("state.sidebarOpen"), true, "desktop vacancy list reopens when no vacancy is selected");
}

async function testResponsiveSidebarStaysOpenWhenArchiveFilterChanges() {
  const app = harness();
  app.routes.set("GET /api/vacancies?archived=true", []);
  app.run("state.sidebarOpen = true");
  const archived = app.document.querySelector("#show-archived");
  archived.checked = true;
  await archived.onchange();
  assert.equal(app.run("state.sidebarOpen"), true);
}

async function testVacancyDeletionUsesInAppPolicyDialog() {
  const app = harness();
  app.window.prompt = () => { throw new Error("prompt must not be used"); };
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  app.routes.set("GET /api/resumes?kind=vacancy&vacancy_id=1", [{ id: 51 }, { id: 52 }]);
  app.routes.set("DELETE /api/vacancies/1?resume_policy=preserve_resumes", { deleted: 1 });
  app.routes.set("GET /api/vacancies?archived=false", []);

  const deletion = app.run("removeVacancy(state.selected)");
  await new Promise(resolve => setTimeout(resolve, 0));
  const dialog = app.run("deleteVacancyDialog");
  assert.equal(dialog.open, true);
  assert.match(dialog.querySelector("#delete-vacancy-message").textContent, /2/);
  assert.equal(dialog.querySelector("[data-delete-vacancy-keep]").hidden, false);
  dialog.querySelector("[data-delete-vacancy-keep]").onclick();
  await deletion;

  assert.equal(dialog.open, false);
  assert.equal(app.calls.filter(call => call === "DELETE /api/vacancies/1?resume_policy=preserve_resumes").length, 1);
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

  app.routes.set("POST /api/vacancies/1/status", () => { throw new Error("status network failed"); });
  app.run(`renderVacancy(${JSON.stringify(first)})`);
  const appliedStage = app.document.querySelectorAll("[data-stage]").find(button => button.dataset.stage === "Applied");
  await appliedStage.onclick();
  assert.equal(appliedStage.disabled, false);
  assert.match(app.document.querySelector("#toast").textContent, /status network failed/);
}

(async () => {
  await testStaleNotesAndCardSelection();
  await testVacancyNavigationRestoresLastSelection();
  await testVacancyNavigationRestoresAfterReload();
  await testOverviewLinkAndTabOrder();
  await testThemeTogglePreservesCurrentView();
  await testEditAndInterviewSubmitControls();
  await testInterviewCounterLifecycleAndStaleReads();
  await testResumePreviewAndEditableCopy();
  await testResponsiveSidebarToggleClosesAfterSelection();
  await testSidebarAcrossMainSectionsAndBlankHeaderClick();
  await testResponsiveSidebarStaysOpenWhenArchiveFilterChanges();
  await testSidebarResizeAndCompactDismissal();
  await testStageFourMasterCrmAndAtsAcceptance();
  await testMasterResumeWorkspaceAndSave();
  await testImportPreviewEditConfirmAndRecovery();
  await testUrlImportStructuredDefaultsAndEditableMetadata();
  await testExistingDescriptionReviewAndCodexOptIn();
  await testSavedAiDetailAndLateRun();
  await testTailoredResumeActionAndExplicitDraftHandoff();
  await testAiResponseLanguageSubmission();
  await testVacancyDeletionUsesInAppPolicyDialog();
  await testMutationFailuresAndDuplicateRecovery();
  process.stdout.write("SPA workflow regressions passed\n");
})().catch(error => {
  process.stderr.write(`${error.stack}\n`);
  process.exitCode = 1;
});
