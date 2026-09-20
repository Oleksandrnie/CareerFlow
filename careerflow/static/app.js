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
    <nav class="tabs">${["Overview", "ATS", "Resume", "Timeline", "Notes", "Files", "AI / Codex"].map((tab, i) => `<button class="tab ${i === 0 ? "active" : ""}" ${i ? "disabled" : ""}>${tab}</button>`).join("")}</nav>
    <section class="panel" id="overview-panel">
      <div class="form-grid"><div><p class="eyebrow">SALARY</p><p>${escapeHtml(vacancy.salary || "Not specified")}</p></div><div><p class="eyebrow">SOURCE</p><p>${escapeHtml(vacancy.source || vacancy.source_type)}</p></div></div>
      <h3>Summary</h3><p>${escapeHtml(vacancy.summary || "No summary")}</p>
      <h3>Original description</h3><div class="overview-text">${escapeHtml(vacancy.description)}</div>
    </section>`;
  document.querySelector("#edit-overview").onclick = () => renderEdit(vacancy);
  document.querySelector("#archive-vacancy").onclick = () => toggleArchive(vacancy);
}

function renderEdit(vacancy) {
  document.querySelector("#overview-panel").innerHTML = `
    <form id="edit-form" class="form-grid">
      <label>Title<input name="title" value="${escapeHtml(vacancy.title)}" required></label>
      <label>Company<input name="company" value="${escapeHtml(vacancy.company)}"></label>
      <label>Salary<input name="salary" value="${escapeHtml(vacancy.salary)}"></label>
      <label>Source<input name="source" value="${escapeHtml(vacancy.source)}"></label>
      <label style="grid-column:1/-1">Summary<textarea name="summary" rows="3">${escapeHtml(vacancy.summary)}</textarea></label>
      <label style="grid-column:1/-1">Description<textarea name="description" rows="14" required>${escapeHtml(vacancy.description)}</textarea></label>
      <div class="actions"><button class="primary">Save changes</button><button class="secondary" type="button" id="cancel-edit">Cancel</button></div>
    </form>`;
  document.querySelector("#cancel-edit").onclick = () => renderVacancy(vacancy);
  document.querySelector("#edit-form").onsubmit = async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    const updated = await api(`/api/vacancies/${vacancy.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    await loadVacancies(); renderVacancy(updated); toast("Vacancy updated");
  };
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
