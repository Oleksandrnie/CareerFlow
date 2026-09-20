const state = { vacancies: [], selected: null };
const listEl = document.querySelector("#vacancy-list");
const workspace = document.querySelector("#workspace");
const dialog = document.querySelector("#import-dialog");
const form = document.querySelector("#import-form");
const fileInput = document.querySelector("#vacancy-file");
const dropZone = document.querySelector("#drop-zone");
const selectedFile = document.querySelector("#selected-file");
const archivedToggle = document.querySelector("#show-archived");

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const payload = response.headers.get("content-type")?.includes("json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(payload.detail || payload || `Request failed (${response.status})`);
  return payload;
}

function escapeHtml(value = "") {
  const node = document.createElement("div");
  node.textContent = value;
  return node.innerHTML;
}

function toast(message) {
  const el = document.querySelector("#toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

async function loadVacancies() {
  state.vacancies = await api(`/api/vacancies?archived=${archivedToggle.checked}`);
  renderList();
  if (state.selected) {
    const current = state.vacancies.find(item => item.id === state.selected.id);
    if (!current) { state.selected = null; renderEmpty(); }
  }
}

function renderList() {
  if (!state.vacancies.length) {
    listEl.innerHTML = `<p class="muted">${archivedToggle.checked ? "No archived vacancies." : "No vacancies yet."}</p>`;
    return;
  }
  listEl.innerHTML = state.vacancies.map(item => `
    <button class="vacancy-card ${state.selected?.id === item.id ? "active" : ""}" data-id="${item.id}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.company || "Company not set")}</span>
      <span class="card-meta"><span class="badge">${escapeHtml(item.status)}</span><span>${item.match_percent == null ? "—" : `${item.match_percent}%`}</span></span>
    </button>`).join("");
}

function renderEmpty() {
  workspace.innerHTML = `<div class="empty-state"><span class="empty-icon">↗</span><h2>Build your job-search workspace</h2><p>Add a vacancy by pasting its text or dropping a TXT, HTML, PDF, or DOCX file.</p><button class="primary" data-open-import>Add your first vacancy</button></div>`;
}

function renderVacancy(vacancy) {
  state.selected = vacancy;
  renderList();
  workspace.innerHTML = `
    <div class="workspace-head">
      <div><p class="eyebrow">${escapeHtml(vacancy.status)}</p><h2>${escapeHtml(vacancy.title)}</h2><p class="muted">${escapeHtml(vacancy.company || "Company not set")} · Added ${new Date(vacancy.created_at + "Z").toLocaleDateString()}</p></div>
      <div class="actions"><button id="edit-overview" class="secondary">Edit</button><button id="archive-vacancy" class="secondary">${vacancy.archived_at ? "Restore" : "Archive"}</button></div>
    </div>
    <nav class="tabs">${["Overview", "ATS", "Resume", "Timeline", "Notes", "Files", "AI / Codex"].map((tab, i) => `<button class="tab ${i === 0 ? "active" : ""}" data-tab="${tab}" ${i > 2 ? "disabled" : ""}>${tab}</button>`).join("")}</nav>
    <section class="panel" id="content-panel"></section>`;
  document.querySelector("#edit-overview").onclick = () => renderEdit(vacancy);
  document.querySelector("#archive-vacancy").onclick = () => toggleArchive(vacancy);
  document.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => openTab(button.dataset.tab, vacancy));
  renderOverview(vacancy);
}

function activateTab(name) {
  document.querySelectorAll("[data-tab]").forEach(button => button.classList.toggle("active", button.dataset.tab === name));
}

function openTab(name, vacancy) {
  activateTab(name);
  if (name === "Overview") renderOverview(vacancy);
  if (name === "Resume") renderResumes(vacancy);
  if (name === "ATS") renderAts(vacancy);
}

function renderOverview(vacancy) {
  const panel = document.querySelector("#content-panel");
  panel.innerHTML = `
    <div class="form-grid"><div><p class="eyebrow">SALARY</p><p>${escapeHtml(vacancy.salary || "Not specified")}</p></div><div><p class="eyebrow">SOURCE</p><p>${escapeHtml(vacancy.source || vacancy.source_type)}</p></div></div>
    <h3>Summary</h3><p>${escapeHtml(vacancy.summary || "No summary")}</p>
    <h3>Original description</h3><div class="overview-text">${escapeHtml(vacancy.description)}</div>`;
}

function renderEdit(vacancy) {
  activateTab("Overview");
  document.querySelector("#content-panel").innerHTML = `
    <form id="edit-form" class="form-grid">
      <label>Title<input name="title" value="${escapeHtml(vacancy.title)}" required></label>
      <label>Company<input name="company" value="${escapeHtml(vacancy.company)}"></label>
      <label>Salary<input name="salary" value="${escapeHtml(vacancy.salary)}"></label>
      <label>Source<input name="source" value="${escapeHtml(vacancy.source)}"></label>
      <label style="grid-column:1/-1">Summary<textarea name="summary" rows="3">${escapeHtml(vacancy.summary)}</textarea></label>
      <label style="grid-column:1/-1">Description<textarea name="description" rows="14" required>${escapeHtml(vacancy.description)}</textarea></label>
      <div class="actions"><button class="primary">Save changes</button><button class="secondary" type="button" id="cancel-edit">Cancel</button></div>
    </form>`;
  document.querySelector("#cancel-edit").onclick = () => renderOverview(vacancy);
  document.querySelector("#edit-form").onsubmit = async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    const updated = await api(`/api/vacancies/${vacancy.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    await loadVacancies(); renderVacancy(updated); toast("Vacancy updated");
  };
}

function resumeItem(item) {
  return `<article class="item-row"><div><strong>${item.kind === "master" ? "Master" : "Vacancy"} Resume v${item.version}</strong><p class="muted">${escapeHtml(item.label || "No label")} · ${new Date(item.created_at + "Z").toLocaleString()}</p></div><div class="actions">${item.is_submitted ? `<span class="badge success">Submitted</span>` : item.kind === "vacancy" ? `<button class="secondary" data-submit-resume="${item.id}">Mark submitted</button>` : `<button class="secondary" data-clone-resume="${item.id}">Create vacancy version</button>`}</div></article>`;
}

async function renderResumes(vacancy) {
  const panel = document.querySelector("#content-panel");
  panel.innerHTML = `<p class="muted">Loading resume versions…</p>`;
  try {
    const [masters, versions] = await Promise.all([
      api("/api/resumes?kind=master"),
      api(`/api/resumes?kind=vacancy&vacancy_id=${vacancy.id}`),
    ]);
    panel.innerHTML = `
      <div class="section-head"><div><p class="eyebrow">IMMUTABLE HISTORY</p><h3>Resume versions</h3></div></div>
      <div class="split-grid"><section><h4>For this vacancy</h4><div class="item-list">${versions.length ? versions.map(resumeItem).join("") : `<p class="muted">No tailored versions yet.</p>`}</div></section><section><h4>Master Resume</h4><div class="item-list">${masters.length ? masters.map(resumeItem).join("") : `<p class="muted">No master resume yet.</p>`}</div></section></div>
      <hr><h4>Add a new version</h4>
      <form id="resume-form" class="stack">
        <div class="form-grid"><label>Version type<select name="kind"><option value="vacancy">For this vacancy</option><option value="master">Master Resume</option></select></label><label>Label<input name="label" placeholder="e.g. Backend-focused"></label></div>
        <label>Resume file (PDF, DOCX, TXT)<input name="file" type="file" accept=".pdf,.docx,.txt,.md"></label>
        <label>Or paste resume text<textarea name="text" rows="7"></textarea></label>
        <p class="error" id="resume-error"></p><button class="primary" type="submit">Save new version</button>
      </form>`;
    document.querySelector("#resume-form").onsubmit = async event => {
      event.preventDefault();
      const formData = new FormData(event.currentTarget);
      if (formData.get("kind") === "vacancy") formData.append("vacancy_id", vacancy.id);
      try { await api("/api/resumes", { method: "POST", body: formData }); toast("Resume version created"); renderResumes(vacancy); }
      catch (error) { document.querySelector("#resume-error").textContent = error.message; }
    };
    document.querySelectorAll("[data-clone-resume]").forEach(button => button.onclick = async () => {
      const formData = new FormData(); formData.append("kind", "vacancy"); formData.append("vacancy_id", vacancy.id); formData.append("source_resume_id", button.dataset.cloneResume);
      await api("/api/resumes", { method: "POST", body: formData }); toast("Vacancy version created"); renderResumes(vacancy);
    });
    document.querySelectorAll("[data-submit-resume]").forEach(button => button.onclick = async () => {
      await api(`/api/resumes/${button.dataset.submitResume}/submit`, { method: "POST" }); toast("Submitted version recorded"); renderResumes(vacancy);
    });
  } catch (error) { panel.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
}

function atsResult(analysis) {
  if (!analysis) return `<div class="empty-inline"><h3>No ATS analysis yet</h3><p>Choose a resume version and run a transparent text comparison.</p></div>`;
  const result = analysis.result;
  return `<div class="score-row"><div class="score">${analysis.match_percent}%</div><div><h3>Resume match</h3><p class="muted">${escapeHtml(result.disclaimer)}</p></div></div>
    <div class="metric-grid"><div><strong>${result.counts.covered}</strong><span>Covered</span></div><div><strong>${result.counts.partial}</strong><span>Partial</span></div><div><strong>${result.counts.missing}</strong><span>Missing</span></div></div>
    <h4>Requirements and evidence</h4><div class="item-list">${result.requirements.map(item => `<article class="requirement ${item.classification}"><span class="badge">${item.classification}</span><strong>${escapeHtml(item.requirement)}</strong><p>${escapeHtml(item.interpretation)}</p>${item.evidence ? `<blockquote>${escapeHtml(item.evidence)}</blockquote>` : ""}</article>`).join("")}</div>
    <h4>Keywords</h4><div class="tag-list">${result.keywords.map(word => `<span class="tag ${result.covered_keywords.includes(word) ? "hit" : ""}">${escapeHtml(word)}</span>`).join("")}</div>`;
}

async function renderAts(vacancy) {
  const panel = document.querySelector("#content-panel");
  panel.innerHTML = `<p class="muted">Loading ATS workspace…</p>`;
  try {
    const [masters, versions, latest] = await Promise.all([
      api("/api/resumes?kind=master"),
      api(`/api/resumes?kind=vacancy&vacancy_id=${vacancy.id}`),
      api(`/api/vacancies/${vacancy.id}/ats`),
    ]);
    const options = [...versions, ...masters];
    panel.innerHTML = `<div class="section-head"><div><p class="eyebrow">EVIDENCE-BASED</p><h3>ATS analysis</h3></div><div class="actions"><select id="ats-resume">${options.map(item => `<option value="${item.id}">${item.kind === "master" ? "Master" : "Vacancy"} v${item.version} — ${escapeHtml(item.label || "Untitled")}</option>`).join("")}</select><button id="run-ats" class="primary" ${options.length ? "" : "disabled"}>Run analysis</button></div></div><div id="ats-result">${atsResult(latest)}</div>`;
    document.querySelector("#run-ats").onclick = async () => {
      const button = document.querySelector("#run-ats"); button.disabled = true; button.textContent = "Analyzing…";
      try {
        const analysis = await api(`/api/vacancies/${vacancy.id}/ats`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resume_version_id: Number(document.querySelector("#ats-resume").value) }) });
        document.querySelector("#ats-result").innerHTML = atsResult(analysis); await loadVacancies(); toast("ATS analysis completed");
      } catch (error) { document.querySelector("#ats-result").innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
      finally { button.disabled = false; button.textContent = "Run analysis"; }
    };
  } catch (error) { panel.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
}

async function toggleArchive(vacancy) {
  const action = vacancy.archived_at ? "restore" : "archive";
  await api(`/api/vacancies/${vacancy.id}/${action}`, { method: "POST" });
  state.selected = null; renderEmpty(); await loadVacancies(); toast(action === "archive" ? "Vacancy archived" : "Vacancy restored");
}

function openDialog() { dialog.showModal(); }
function closeDialog() { dialog.close(); form.reset(); selectedFile.textContent = ""; document.querySelector("#import-error").textContent = ""; }

document.addEventListener("click", async event => {
  if (event.target.closest("[data-open-import]")) openDialog();
  if (event.target.closest("[data-close-dialog]")) closeDialog();
  const card = event.target.closest(".vacancy-card");
  if (card) renderVacancy(await api(`/api/vacancies/${card.dataset.id}`));
});
document.querySelector("#new-vacancy").onclick = openDialog;
archivedToggle.onchange = () => { state.selected = null; renderEmpty(); loadVacancies(); };
fileInput.onchange = () => { selectedFile.textContent = fileInput.files[0]?.name || ""; };
for (const eventName of ["dragenter", "dragover"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.add("dragging"); });
for (const eventName of ["dragleave", "drop"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.remove("dragging"); });
dropZone.addEventListener("drop", event => { fileInput.files = event.dataTransfer.files; selectedFile.textContent = fileInput.files[0]?.name || ""; });
form.onsubmit = async event => {
  event.preventDefault();
  const error = document.querySelector("#import-error");
  error.textContent = "";
  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true; submit.textContent = "Importing…";
  try {
    const vacancy = await api("/api/vacancies", { method: "POST", body: new FormData(form) });
    closeDialog(); await loadVacancies(); renderVacancy(vacancy); toast("Vacancy imported");
  } catch (exception) { error.textContent = exception.message; }
  finally { submit.disabled = false; submit.textContent = "Import vacancy"; }
};

loadVacancies().catch(error => { workspace.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; });
