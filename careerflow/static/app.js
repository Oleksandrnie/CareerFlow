const state = { vacancies: [], selected: null, activeTab: null, viewEpoch: 0, selectionEpoch: 0, listEpoch: 0 };
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
  if (!response.ok) throw new Error(apiErrorMessage(payload, response.status));
  return payload;
}

function apiErrorMessage(payload, status) {
  const detail = payload && typeof payload === "object" && "detail" in payload ? payload.detail : payload;
  if (Array.isArray(detail)) {
    return detail.map(item => {
      const field = Array.isArray(item.loc) ? item.loc.filter(part => part !== "body").join(".") : "";
      return `${field ? `${field}: ` : ""}${item.msg || "Invalid value"}`;
    }).join("; ") || `Request failed (${status})`;
  }
  if (typeof detail === "string" && detail.trim()) return detail;
  return `Request failed (${status})`;
}

function escapeHtml(value = "") {
  const node = document.createElement("div");
  node.textContent = value;
  return node.innerHTML;
}

function escapeAttr(value = "") {
  return escapeHtml(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function toast(message) {
  const el = document.querySelector("#toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

function showError(error, target = null) {
  const message = error?.message || String(error);
  if (target) target.textContent = message;
  else toast(`Error: ${message}`);
}

async function runAction(control, action, errorTarget = null, view = null) {
  if (control.disabled) return;
  control.disabled = true;
  const originalText = control.tagName === "BUTTON" ? control.textContent : null;
  try {
    await action();
  } catch (error) {
    if (!view || isCurrentView(view)) showError(error, errorTarget);
  } finally {
    control.disabled = false;
    if (originalText !== null) control.textContent = originalText;
  }
}

function currentView(vacancy, tab, panel = document.querySelector("#content-panel")) {
  return { vacancyId: vacancy.id, tab, panel, epoch: state.viewEpoch };
}

function isCurrentView(view) {
  return !view || (
    state.selected?.id === view.vacancyId
    && state.activeTab === view.tab
    && state.viewEpoch === view.epoch
    && document.querySelector("#content-panel") === view.panel
  );
}

async function loadVacancies() {
  const epoch = ++state.listEpoch;
  const archived = archivedToggle.checked;
  const selectionEpoch = state.selectionEpoch;
  const vacancies = await api(`/api/vacancies?archived=${archived}`);
  if (epoch !== state.listEpoch || archived !== archivedToggle.checked) return;
  state.vacancies = vacancies;
  renderList();
  if (state.selected && selectionEpoch === state.selectionEpoch) {
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
      <span class="vacancy-meta">${escapeHtml(item.salary || "Salary not specified")} · Added ${new Date(`${item.created_at}Z`).toLocaleDateString()}</span>
      <span class="vacancy-summary">${escapeHtml(item.summary || "No summary yet")}</span>
      <span class="card-meta"><span class="badge">${escapeHtml(item.status)}</span><span>${item.match_percent == null ? "—" : `${item.match_percent}%`}</span></span>
    </button>`).join("");
}

function renderEmpty() {
  state.selected = null;
  state.activeTab = null;
  state.viewEpoch++;
  state.selectionEpoch++;
  workspace.innerHTML = `<div class="empty-state"><span class="empty-icon">↗</span><h2>Build your job-search workspace</h2><p>Add a vacancy by pasting its text or dropping a TXT, HTML, PDF, or DOCX file.</p><button class="primary" data-open-import>Add your first vacancy</button></div>`;
}

function renderVacancy(vacancy) {
  state.selectionEpoch++;
  state.viewEpoch++;
  state.activeTab = "Overview";
  state.selected = vacancy;
  renderList();
  workspace.innerHTML = `
    <div class="workspace-head">
      <div><p class="eyebrow">${escapeHtml(vacancy.status)}</p><h2>${escapeHtml(vacancy.title)}</h2><p class="muted">${escapeHtml(vacancy.company || "Company not set")} · Added ${new Date(vacancy.created_at + "Z").toLocaleDateString()}</p></div>
      <div class="actions"><select id="status-selector" aria-label="Vacancy status">${["Saved", "Applied", "Interview", "Waiting", "Offer", "Rejected"].map(status => `<option ${status === vacancy.status ? "selected" : ""}>${status}</option>`).join("")}</select><button id="export-report" class="secondary">Export .md</button><button id="edit-overview" class="secondary">Edit</button><button id="archive-vacancy" class="secondary">${vacancy.archived_at ? "Restore" : "Archive"}</button><button id="delete-vacancy" class="danger">Delete</button></div>
    </div>
    <nav class="tabs">${["Overview", "ATS", "Resume", "Timeline", "Notes", "Files", "AI / Codex"].map((tab, i) => `<button class="tab ${i === 0 ? "active" : ""}" data-tab="${tab}">${tab}</button>`).join("")}</nav>
    <section class="panel" id="content-panel"></section>`;
  document.querySelector("#edit-overview").onclick = () => renderEdit(vacancy);
  document.querySelector("#archive-vacancy").onclick = event => runAction(event.currentTarget, () => toggleArchive(vacancy));
  document.querySelector("#delete-vacancy").onclick = event => runAction(event.currentTarget, () => removeVacancy(vacancy));
  document.querySelector("#export-report").onclick = () => exportReport(vacancy);
  document.querySelector("#status-selector").onchange = async event => {
    const selector = event.currentTarget;
    const epoch = state.viewEpoch;
    const selectedStatus = selector.value;
    await runAction(selector, async () => {
      const updated = await api(`/api/vacancies/${vacancy.id}/status`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: selectedStatus }) });
      await loadVacancies();
      if (state.viewEpoch === epoch && state.selected?.id === vacancy.id) renderVacancy(updated);
      toast(`Status changed to ${updated.status}`);
    });
    if (state.selected?.id === vacancy.id && document.querySelector("#status-selector") === selector) {
      selector.value = state.vacancies.find(item => item.id === vacancy.id)?.status || vacancy.status;
    }
  };
  document.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => openTab(button.dataset.tab, vacancy));
  renderOverview(vacancy);
}

function activateTab(name) {
  document.querySelectorAll("[data-tab]").forEach(button => button.classList.toggle("active", button.dataset.tab === name));
}

async function openTab(name, vacancy) {
  if (state.selected?.id !== vacancy.id) return;
  state.activeTab = name;
  state.viewEpoch++;
  const view = currentView(vacancy, name);
  activateTab(name);
  try {
    if (name === "Overview") renderOverview(vacancy);
    if (name === "Resume") await renderResumes(vacancy, view);
    if (name === "ATS") await renderAts(vacancy, view);
    if (name === "Timeline") await renderTimeline(vacancy, view);
    if (name === "Notes") await renderNotes(vacancy, view);
    if (name === "Files") await renderFiles(vacancy, view);
    if (name === "AI / Codex") await renderAi(vacancy, view);
  } catch (error) {
    if (isCurrentView(view)) view.panel.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
}

function renderOverview(vacancy) {
  const panel = document.querySelector("#content-panel");
  panel.innerHTML = `
    <div class="form-grid"><div><p class="eyebrow">SALARY</p><p>${escapeHtml(vacancy.salary || "Not specified")}</p></div><div><p class="eyebrow">SOURCE</p><p>${escapeHtml(vacancy.source || vacancy.source_type)}</p></div></div>
    <h3>Summary</h3><p>${escapeHtml(vacancy.summary || "No summary")}</p>
    <h3>Original description</h3><div class="overview-text">${escapeHtml(vacancy.description)}</div>`;
}

function renderEdit(vacancy) {
  state.activeTab = "Overview";
  state.viewEpoch++;
  const view = currentView(vacancy, "Overview");
  activateTab("Overview");
  document.querySelector("#content-panel").innerHTML = `
    <form id="edit-form" class="form-grid">
      <label>Title<input name="title" value="${escapeAttr(vacancy.title)}" required></label>
      <label>Company<input name="company" value="${escapeAttr(vacancy.company)}"></label>
      <label>Salary<input name="salary" value="${escapeAttr(vacancy.salary)}"></label>
      <label>Source<input name="source" value="${escapeAttr(vacancy.source)}"></label>
      <label style="grid-column:1/-1">Summary<textarea name="summary" rows="3">${escapeHtml(vacancy.summary)}</textarea></label>
      <label style="grid-column:1/-1">Description<textarea name="description" rows="14" required>${escapeHtml(vacancy.description)}</textarea></label>
      <div class="actions"><button class="primary">Save changes</button><button class="secondary" type="button" id="cancel-edit">Cancel</button></div>
    </form>`;
  document.querySelector("#cancel-edit").onclick = () => openTab("Overview", vacancy);
  document.querySelector("#edit-form").onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button[type=submit]");
    await runAction(button, async () => {
      const payload = Object.fromEntries(new FormData(form));
      const updated = await api(`/api/vacancies/${vacancy.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      await loadVacancies();
      if (isCurrentView(view)) renderVacancy(updated);
      toast("Vacancy updated");
    }, null, view);
  };
}

function resumeItem(item) {
  return `<article class="item-row"><div><strong>${item.kind === "master" ? "Master" : "Vacancy"} Resume v${item.version}</strong><p class="muted">${escapeHtml(item.label || "No label")} · ${new Date(item.created_at + "Z").toLocaleString()}</p></div><div class="actions"><button class="secondary" type="button" data-preview-resume="${item.id}">Preview text</button><button class="secondary" type="button" data-use-resume="${item.id}">Create new version from this text</button>${item.original_filename ? `<a class="secondary link-button" href="/api/resumes/${item.id}/download" download>Download original</a>` : ""}${item.is_submitted ? `<span class="badge success">Submitted</span>` : item.kind === "vacancy" ? `<button class="secondary" type="button" data-submit-resume="${item.id}">Mark submitted</button>` : `<button class="secondary" type="button" data-clone-resume="${item.id}">Create vacancy version</button>`}</div></article>`;
}

async function renderResumes(vacancy, view = null) {
  const panel = document.querySelector("#content-panel");
  panel.innerHTML = `<p class="muted">Loading resume versions…</p>`;
  try {
    const [masters, versions] = await Promise.all([
      api("/api/resumes?kind=master"),
      api(`/api/resumes?kind=vacancy&vacancy_id=${vacancy.id}`),
    ]);
    if (!isCurrentView(view)) return;
    panel.innerHTML = `
      <div class="section-head"><div><p class="eyebrow">IMMUTABLE HISTORY</p><h3>Resume versions</h3></div></div>
      <div class="split-grid"><section><h4>For this vacancy</h4><div class="item-list">${versions.length ? versions.map(resumeItem).join("") : `<p class="muted">No tailored versions yet.</p>`}</div></section><section><h4>Master Resume</h4><div class="item-list">${masters.length ? masters.map(resumeItem).join("") : `<p class="muted">No master resume yet.</p>`}</div></section></div>
      <div id="resume-preview" aria-live="polite"></div>
      <hr><h4>Add a new version</h4>
      <form id="resume-form" class="stack">
        <div class="form-grid"><label>Version type<select name="kind"><option value="vacancy">For this vacancy</option><option value="master">Master Resume</option></select></label><label>Label<input name="label" placeholder="e.g. Backend-focused"></label></div>
        <label>Resume file (PDF, DOCX, TXT)<input name="file" type="file" accept=".pdf,.docx,.txt,.md"></label>
        <label>Or paste resume text<textarea name="text" rows="7"></textarea></label>
        <p class="error" id="resume-error"></p><button class="primary" type="submit">Save new version</button>
      </form>`;
    document.querySelector("#resume-form").onsubmit = async event => {
      event.preventDefault();
      const resumeForm = event.currentTarget;
      const errorTarget = panel.querySelector("#resume-error");
      errorTarget.textContent = "";
      await runAction(resumeForm.querySelector("button[type=submit]"), async () => {
        const formData = new FormData(resumeForm);
        if (formData.get("kind") === "vacancy") formData.append("vacancy_id", vacancy.id);
        await api("/api/resumes", { method: "POST", body: formData });
        if (isCurrentView(view)) { toast("Resume version created"); await renderResumes(vacancy, view); }
      }, errorTarget, view);
    };
    document.querySelectorAll("[data-preview-resume]").forEach(button => button.onclick = () => runAction(button, async () => {
      const resume = await api(`/api/resumes/${button.dataset.previewResume}`);
      if (!isCurrentView(view)) return;
      panel.querySelector("#resume-preview").innerHTML = `<hr><h4>${resume.kind === "master" ? "Master" : "Vacancy"} Resume v${resume.version} — text preview</h4><pre class="ai-response">${escapeHtml(resume.content_text)}</pre>`;
    }, null, view));
    document.querySelectorAll("[data-use-resume]").forEach(button => button.onclick = () => runAction(button, async () => {
      const resume = await api(`/api/resumes/${button.dataset.useResume}`);
      if (!isCurrentView(view)) return;
      const resumeForm = panel.querySelector("#resume-form");
      const textArea = resumeForm.querySelector("textarea[name=text]");
      textArea.value = resume.content_text;
      resumeForm.querySelector("input[name=file]").value = "";
      resumeForm.querySelector("input[name=label]").value = `Based on ${resume.kind} v${resume.version}`;
      textArea.focus();
      toast("Stored text copied into the new-version form. Edit it before saving.");
    }, null, view));
    document.querySelectorAll("[data-clone-resume]").forEach(button => button.onclick = async () => {
      await runAction(button, async () => {
        const formData = new FormData(); formData.append("kind", "vacancy"); formData.append("vacancy_id", vacancy.id); formData.append("source_resume_id", button.dataset.cloneResume);
        await api("/api/resumes", { method: "POST", body: formData });
        if (isCurrentView(view)) { toast("Vacancy version created"); await renderResumes(vacancy, view); }
      }, null, view);
    });
    document.querySelectorAll("[data-submit-resume]").forEach(button => button.onclick = async () => {
      await runAction(button, async () => {
        await api(`/api/resumes/${button.dataset.submitResume}/submit`, { method: "POST" });
        if (isCurrentView(view)) { toast("Submitted version recorded"); await renderResumes(vacancy, view); }
      }, null, view);
    });
  } catch (error) { if (isCurrentView(view)) panel.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
}

function atsResult(analysis) {
  if (!analysis) return `<div class="empty-inline"><h3>No ATS analysis yet</h3><p>Choose a resume version and run a transparent text comparison.</p></div>`;
  const result = analysis.result;
  const resumeLabel = analysis.resume_kind_at_analysis && analysis.resume_version_at_analysis
    ? `${analysis.resume_kind_at_analysis === "master" ? "Master" : "Vacancy"} Resume v${analysis.resume_version_at_analysis}`
    : "legacy resume version";
  return `<div class="score-row"><div class="score">${analysis.match_percent}%</div><div><h3>${analysis.is_stale ? "Historical match — rerun ATS" : "Current resume match"}</h3><p class="muted">Analysis #${analysis.id} · ${escapeHtml(resumeLabel)} (ID ${analysis.resume_version_id})</p><p class="muted">${escapeHtml(result.disclaimer)}</p>${analysis.is_stale ? `<p class="error">Vacancy description changed or this older result has unknown provenance. This score is not current.</p>` : ""}</div></div>
    <div class="metric-grid"><div><strong>${result.counts.covered}</strong><span>Covered</span></div><div><strong>${result.counts.partial}</strong><span>Partial</span></div><div><strong>${result.counts.missing}</strong><span>Missing</span></div></div>
    <h4>Requirements and evidence</h4><div class="item-list">${result.requirements.map(item => `<article class="requirement ${item.classification}"><span class="badge">${item.classification}</span><strong>${escapeHtml(item.requirement)}</strong><p>${escapeHtml(item.interpretation)}</p>${item.evidence ? `<blockquote>${escapeHtml(item.evidence)}</blockquote>` : ""}</article>`).join("")}</div>
    <h4>Keywords</h4><div class="tag-list">${result.keywords.map(word => `<span class="tag ${result.covered_keywords.includes(word) ? "hit" : ""}">${escapeHtml(word)}</span>`).join("")}</div>`;
}

async function renderAts(vacancy, view = null) {
  const panel = document.querySelector("#content-panel");
  panel.innerHTML = `<p class="muted">Loading ATS workspace…</p>`;
  try {
    const [masters, versions, latest] = await Promise.all([
      api("/api/resumes?kind=master"),
      api(`/api/resumes?kind=vacancy&vacancy_id=${vacancy.id}`),
      api(`/api/vacancies/${vacancy.id}/ats`),
    ]);
    if (!isCurrentView(view)) return;
    const options = [...versions, ...masters];
    panel.innerHTML = `<div class="section-head"><div><p class="eyebrow">EVIDENCE-BASED</p><h3>ATS analysis</h3></div><div class="actions"><select id="ats-resume">${options.map(item => `<option value="${item.id}" ${latest && item.id === latest.resume_version_id ? "selected" : ""}>${item.kind === "master" ? "Master" : "Vacancy"} v${item.version} — ${escapeHtml(item.label || "Untitled")}</option>`).join("")}</select><button id="run-ats" class="primary" ${options.length ? "" : "disabled"}>Run analysis</button></div></div><p class="error" id="ats-error"></p><div id="ats-result">${atsResult(latest)}</div>`;
    document.querySelector("#run-ats").onclick = async () => {
      const button = panel.querySelector("#run-ats");
      const errorTarget = panel.querySelector("#ats-error");
      errorTarget.textContent = "";
      await runAction(button, async () => {
        const resumeId = Number(panel.querySelector("#ats-resume").value);
        const analysis = await api(`/api/vacancies/${vacancy.id}/ats`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resume_version_id: resumeId }) });
        await loadVacancies();
        if (isCurrentView(view)) { panel.querySelector("#ats-result").innerHTML = atsResult(analysis); toast("ATS analysis completed"); }
      }, errorTarget, view);
    };
  } catch (error) { if (isCurrentView(view)) panel.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
}

async function toggleArchive(vacancy) {
  const selectionEpoch = state.selectionEpoch;
  const action = vacancy.archived_at ? "restore" : "archive";
  await api(`/api/vacancies/${vacancy.id}/${action}`, { method: "POST" });
  if (selectionEpoch === state.selectionEpoch && state.selected?.id === vacancy.id) renderEmpty();
  await loadVacancies();
  toast(action === "archive" ? "Vacancy archived" : "Vacancy restored");
}

async function removeVacancy(vacancy) {
  const selectionEpoch = state.selectionEpoch;
  const versions = await api(`/api/resumes?kind=vacancy&vacancy_id=${vacancy.id}`);
  if (selectionEpoch !== state.selectionEpoch || state.selected?.id !== vacancy.id) return;
  let policy = "delete_all";
  if (versions.length) {
    const answer = window.prompt(`This vacancy has ${versions.length} CV version(s). Type KEEP to preserve them in the Master Resume library, DELETE to remove everything, or Cancel to stop.`);
    if (answer === null) return;
    if (answer.trim().toUpperCase() === "KEEP") policy = "preserve_resumes";
    else if (answer.trim().toUpperCase() !== "DELETE") { toast("Deletion cancelled"); return; }
  } else if (!window.confirm("Permanently delete this vacancy and all of its history and files?")) return;
  await api(`/api/vacancies/${vacancy.id}?resume_policy=${policy}`, { method: "DELETE" });
  if (selectionEpoch === state.selectionEpoch && state.selected?.id === vacancy.id) renderEmpty();
  await loadVacancies();
  toast("Vacancy deleted");
}

async function renderTimeline(vacancy, view = null) {
  const panel = document.querySelector("#content-panel");
  const [events, interviews] = await Promise.all([
    api(`/api/vacancies/${vacancy.id}/timeline`),
    api(`/api/vacancies/${vacancy.id}/interviews`),
  ]);
  if (!isCurrentView(view)) return;
  panel.innerHTML = `<div class="section-head"><div><p class="eyebrow">EVENT LOG</p><h3>Timeline</h3></div></div>
    <div class="split-grid"><section><div class="timeline">${events.map(event => `<article><span></span><div><strong>${escapeHtml(event.title)}</strong><time>${new Date(event.event_at + (event.event_at.includes("T") ? "" : "Z")).toLocaleString()}</time>${event.details ? `<p>${escapeHtml(event.details)}</p>` : ""}</div></article>`).join("")}</div></section>
    <section><h4>Add interview #${interviews.length + 1}</h4><form id="interview-form" class="stack"><label>Date and time<input name="interview_at" type="datetime-local" required></label><label>Type<input name="interview_type" value="Interview" placeholder="HR, Technical, Hiring manager…"></label><label>Notes<textarea name="note" rows="4"></textarea></label><label>Result<input name="result" placeholder="Scheduled, passed, follow-up…"></label><p class="error" id="interview-error"></p><button class="primary">Add interview</button></form></section></div>`;
  document.querySelector("#interview-form").onsubmit = async event => {
    event.preventDefault();
    const interviewForm = event.currentTarget;
    const errorTarget = panel.querySelector("#interview-error");
    errorTarget.textContent = "";
    await runAction(interviewForm.querySelector("button[type=submit]"), async () => {
      const payload = Object.fromEntries(new FormData(interviewForm));
      await api(`/api/vacancies/${vacancy.id}/interviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const updated = await api(`/api/vacancies/${vacancy.id}`);
      await loadVacancies();
      if (isCurrentView(view)) { renderVacancy(updated); await openTab("Timeline", updated); toast("Interview added"); }
    }, errorTarget, view);
  };
}

async function renderNotes(vacancy, view = null) {
  const panel = document.querySelector("#content-panel");
  const notes = await api(`/api/vacancies/${vacancy.id}/notes`);
  if (!isCurrentView(view)) return;
  panel.innerHTML = `<div class="section-head"><div><p class="eyebrow">DATED NOTES</p><h3>Notes</h3></div></div>
    <form id="note-form" class="stack"><label>New note<textarea name="body" rows="4" placeholder="Interview preparation, company research, impressions…" required></textarea></label><p class="error" id="note-error"></p><button class="primary">Add note</button></form><hr>
    <div class="item-list">${notes.length ? notes.map(note => `<form class="note-card" data-note-id="${note.id}"><textarea name="body" rows="4">${escapeHtml(note.body)}</textarea><p class="error" data-note-error></p><div class="card-meta"><time>${new Date(note.created_at + "Z").toLocaleString()}</time><div class="actions"><button class="secondary" type="submit">Save</button><button class="danger" type="button" data-delete-note>Delete</button></div></div></form>`).join("") : `<p class="muted">No notes yet.</p>`}</div>`;
  document.querySelector("#note-form").onsubmit = async event => {
    event.preventDefault();
    const noteForm = event.currentTarget;
    const errorTarget = panel.querySelector("#note-error");
    errorTarget.textContent = "";
    await runAction(noteForm.querySelector("button[type=submit]"), async () => {
      const payload = Object.fromEntries(new FormData(noteForm));
      await api(`/api/vacancies/${vacancy.id}/notes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (isCurrentView(view)) { toast("Note added"); await renderNotes(vacancy, view); }
    }, errorTarget, view);
  };
  document.querySelectorAll(".note-card").forEach(noteForm => {
    const errorTarget = noteForm.querySelector("[data-note-error]");
    noteForm.onsubmit = async event => {
      event.preventDefault();
      errorTarget.textContent = "";
      await runAction(noteForm.querySelector("button[type=submit]"), async () => {
        await api(`/api/vacancies/${vacancy.id}/notes/${noteForm.dataset.noteId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.fromEntries(new FormData(noteForm))) });
        if (isCurrentView(view)) toast("Note saved");
      }, errorTarget, view);
    };
    noteForm.querySelector("[data-delete-note]").onclick = async event => {
      if (!window.confirm("Delete this note?")) return;
      errorTarget.textContent = "";
      await runAction(event.currentTarget, async () => {
        await api(`/api/vacancies/${vacancy.id}/notes/${noteForm.dataset.noteId}`, { method: "DELETE" });
        if (isCurrentView(view)) { toast("Note deleted"); await renderNotes(vacancy, view); }
      }, errorTarget, view);
    };
  });
}

async function renderFiles(vacancy, view = null) {
  const panel = document.querySelector("#content-panel");
  const attachments = await api(`/api/vacancies/${vacancy.id}/attachments`);
  if (!isCurrentView(view)) return;
  const formatSize = bytes => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
  panel.innerHTML = `<div class="section-head"><div><p class="eyebrow">LOCAL STORAGE</p><h3>Files</h3></div></div>
    <form id="attachment-form" class="inline-form"><input name="file" type="file" required><button class="primary">Attach file</button></form><p class="error" id="attachment-error"></p><p class="muted file-hint">Up to 100 MB. Audio is stored as-is; automatic transcription is outside the MVP.</p><hr>
    <div class="item-list">${attachments.length ? attachments.map(file => `<article class="item-row"><div><strong>${escapeHtml(file.filename)}</strong><p class="muted">${formatSize(file.size_bytes)} · ${escapeHtml(file.media_type)}</p></div><div class="actions"><a class="secondary link-button" href="/api/vacancies/${vacancy.id}/attachments/${file.id}/download">Download</a><button class="danger" data-delete-file="${file.id}">Delete</button></div></article>`).join("") : `<p class="muted">No attachments yet.</p>`}</div>`;
  document.querySelector("#attachment-form").onsubmit = async event => {
    event.preventDefault();
    const attachmentForm = event.currentTarget;
    const errorTarget = panel.querySelector("#attachment-error");
    errorTarget.textContent = "";
    await runAction(attachmentForm.querySelector("button[type=submit]"), async () => {
      await api(`/api/vacancies/${vacancy.id}/attachments`, { method: "POST", body: new FormData(attachmentForm) });
      if (isCurrentView(view)) { toast("File attached"); await renderFiles(vacancy, view); }
    }, errorTarget, view);
  };
  document.querySelectorAll("[data-delete-file]").forEach(button => button.onclick = async () => {
    if (!window.confirm("Remove this attachment?")) return;
    await runAction(button, async () => {
      await api(`/api/vacancies/${vacancy.id}/attachments/${button.dataset.deleteFile}`, { method: "DELETE" });
      if (isCurrentView(view)) { toast("File removed"); await renderFiles(vacancy, view); }
    }, null, view);
  });
}

async function exportReport(vacancy) {
  const button = document.querySelector("#export-report");
  if (button.disabled) return;
  button.disabled = true; button.textContent = "Building…";
  try {
    const report = await api(`/api/vacancies/${vacancy.id}/reports`, { method: "POST" });
    const link = document.createElement("a");
    link.href = `/api/vacancies/${vacancy.id}/reports/${report.id}/download`;
    link.download = report.filename;
    document.body.appendChild(link); link.click(); link.remove(); toast("Markdown report generated");
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = "Export .md"; }
}

function aiHistoryItem(run) {
  return `<article class="item-row"><div><strong>${escapeHtml(run.prompt)}</strong><p class="muted">${new Date(run.created_at + "Z").toLocaleString()} · ${escapeHtml(run.model || "Legacy model unknown")}</p></div><div class="actions"><span class="badge ${run.status === "completed" ? "success" : ""}">${escapeHtml(run.status)}</span><button class="secondary" type="button" data-open-ai-run="${run.id}" aria-label="View saved response ${run.id}">View response</button></div></article>`;
}

async function renderAi(vacancy, view = null) {
  const panel = document.querySelector("#content-panel");
  const history = await api(`/api/vacancies/${vacancy.id}/ai-runs`);
  if (!isCurrentView(view)) return;
  const actions = {
    "Analyze vacancy": "Analyze the role, prioritize its requirements, and identify questions I should clarify.",
    "Improve resume": "Suggest truthful improvements to the selected resume using only evidence already present in the context.",
    "Review ATS analysis": "Review the heuristic ATS analysis, point out false positives or weak evidence, and suggest truthful wording improvements.",
    "Prepare for interview": "Create a focused interview preparation plan with likely questions and evidence-backed talking points.",
    "Analyze interview notes": "Analyze the interview notes, extract follow-ups, risks, and suggested next actions.",
    "Custom request": "",
  };
  panel.innerHTML = `<div class="section-head"><div><p class="eyebrow">READ-ONLY CLI ASSISTANT</p><h3>AI / Codex</h3></div></div>
    <p class="callout">CareerFlow sends the generated vacancy Markdown context to <code>codex exec</code> in a read-only, ephemeral session. The response is shown here and never changes your CV or vacancy automatically.</p>
    <form id="ai-form" class="stack"><div class="form-grid"><label>Action<select name="action" id="ai-action">${Object.keys(actions).map(action => `<option>${action}</option>`).join("")}</select></label><label>Model<input name="model" value="gpt-5.6-luna" placeholder="Leave blank for Luna"></label></div><label>Request<textarea name="prompt" id="ai-prompt" rows="6" required>${escapeHtml(actions["Analyze vacancy"])}</textarea></label><p class="muted">Default: gpt-5.6-luna · reasoning effort low</p><p class="error" id="ai-error"></p><button class="primary" type="submit">Run Codex</button></form>
    <div id="ai-result" aria-live="polite"></div><hr><h4>Saved responses</h4><div class="item-list">${history.length ? history.map(aiHistoryItem).join("") : `<p class="muted">No saved responses yet.</p>`}</div><div id="ai-history-result" aria-live="polite"></div>`;
  document.querySelector("#ai-action").onchange = event => { const template = actions[event.target.value]; if (template) document.querySelector("#ai-prompt").value = template; };
  document.querySelectorAll("[data-open-ai-run]").forEach(button => button.onclick = () => runAction(button, async () => {
    const run = await api(`/api/vacancies/${vacancy.id}/ai-runs/${button.dataset.openAiRun}`);
    if (!isCurrentView(view)) return;
    panel.querySelector("#ai-history-result").innerHTML = `<hr><h4>Saved ${run.status === "completed" ? "response" : "error"} · ${escapeHtml(run.model || "Legacy model unknown")}</h4><p class="muted">${escapeHtml(run.prompt)}</p><pre class="ai-response">${escapeHtml(run.status === "completed" ? run.response : run.error)}</pre>`;
  }, null, view));
  document.querySelector("#ai-form").onsubmit = async event => {
    event.preventDefault();
    const aiForm = event.currentTarget;
    const button = aiForm.querySelector("button[type=submit]");
    const errorEl = panel.querySelector("#ai-error");
    errorEl.textContent = "";
    await runAction(button, async () => {
      button.textContent = "Codex is working…";
      const payload = Object.fromEntries(new FormData(aiForm));
      const run = await api(`/api/vacancies/${vacancy.id}/ai-runs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (isCurrentView(view)) {
        if (run.status === "failed") {
          errorEl.textContent = run.error || "Codex could not complete this request.";
        } else {
          panel.querySelector("#ai-result").innerHTML = `<hr><h4>Codex response</h4><pre class="ai-response">${escapeHtml(run.response)}</pre><p class="muted">Review the response, then manually decide what to save as a new resume version or note.</p>`;
          toast("Codex response received");
        }
      }
    }, errorEl, view);
  };
}

function openDialog() { dialog.showModal(); }
function closeDialog() { dialog.close(); form.reset(); selectedFile.textContent = ""; document.querySelector("#import-error").textContent = ""; }

document.addEventListener("click", async event => {
  if (event.target.closest("[data-open-import]")) openDialog();
  if (event.target.closest("[data-close-dialog]")) closeDialog();
  const card = event.target.closest(".vacancy-card");
  if (card) {
    const selectionEpoch = ++state.selectionEpoch;
    try {
      const vacancy = await api(`/api/vacancies/${card.dataset.id}`);
      if (selectionEpoch === state.selectionEpoch) renderVacancy(vacancy);
    } catch (error) { if (selectionEpoch === state.selectionEpoch) showError(error); }
  }
});
document.querySelector("#new-vacancy").onclick = openDialog;
archivedToggle.onchange = () => { renderEmpty(); loadVacancies().catch(error => showError(error)); };
fileInput.onchange = () => { selectedFile.textContent = fileInput.files[0]?.name || ""; };
for (const eventName of ["dragenter", "dragover"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.add("dragging"); });
for (const eventName of ["dragleave", "drop"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.remove("dragging"); });
dropZone.addEventListener("drop", event => { fileInput.files = event.dataTransfer.files; selectedFile.textContent = fileInput.files[0]?.name || ""; });
form.onsubmit = async event => {
  event.preventDefault();
  const error = document.querySelector("#import-error");
  error.textContent = "";
  const submit = form.querySelector("button[type=submit]");
  if (submit.disabled) return;
  submit.disabled = true; submit.textContent = "Importing…";
  try {
    const vacancy = await api("/api/vacancies", { method: "POST", body: new FormData(form) });
    closeDialog(); await loadVacancies(); renderVacancy(vacancy); toast("Vacancy imported");
  } catch (exception) { error.textContent = exception.message; }
  finally { submit.disabled = false; submit.textContent = "Import vacancy"; }
};

loadVacancies().catch(error => { workspace.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; });
