const VACANCY_NAVIGATION_STORAGE_KEY = "careerflow-last-vacancy-navigation";

function readSavedVacancyNavigation() {
  try {
    if (typeof localStorage === "undefined") return null;
    const saved = JSON.parse(localStorage.getItem(VACANCY_NAVIGATION_STORAGE_KEY) || "null");
    const vacancyId = Number(saved?.vacancyId);
    return Number.isInteger(vacancyId) && vacancyId > 0
      ? { vacancyId, tab: typeof saved.tab === "string" ? saved.tab : "Overview" }
      : null;
  } catch (_) { return null; }
}

function saveVacancyNavigation(vacancyId, tab) {
  try { localStorage.setItem(VACANCY_NAVIGATION_STORAGE_KEY, JSON.stringify({ vacancyId, tab })); }
  catch (_) { /* Storage can be unavailable in private browsing or embedded contexts. */ }
}

function clearSavedVacancyNavigation() {
  try { localStorage.removeItem(VACANCY_NAVIGATION_STORAGE_KEY); }
  catch (_) { /* Storage can be unavailable in private browsing or embedded contexts. */ }
}

const savedVacancyNavigation = readSavedVacancyNavigation();
const state = {
  section: "vacancies",
  vacancies: [],
  selected: null,
  lastSelectedVacancy: null,
  lastSelectedVacancyTab: null,
  pendingVacancyId: savedVacancyNavigation?.vacancyId || null,
  pendingVacancyTab: savedVacancyNavigation?.tab || null,
  activeTab: null,
  viewEpoch: 0,
  selectionEpoch: 0,
  listEpoch: 0,
  importPreview: null,
  pendingResumeDraft: null,
  interviewCounts: new Map(),
  interviewCountEpochs: new Map(),
  interviewRequests: new Map(),
  sidebarOpen: false,
  locale: (() => {
    try { return localStorage.getItem("careerflow-locale") === "ru" ? "ru" : "en"; }
    catch (_) { return "en"; }
  })(),
  theme: (() => {
    try { return localStorage.getItem("careerflow-theme") === "dark" ? "dark" : "light"; }
    catch (_) { return "light"; }
  })(),
};
const listEl = document.querySelector("#vacancy-list");
const workspace = document.querySelector("#workspace");
const topbar = document.querySelector(".topbar");
const appLayout = document.querySelector("#app-layout");
const newVacancyButton = document.querySelector("#new-vacancy");
const themeToggle = document.querySelector("#theme-toggle");
const dialog = document.querySelector("#import-dialog");
const analyticsHelp = document.querySelector("#analytics-help");
const form = document.querySelector("#import-form");
const fileInput = document.querySelector("#vacancy-file");
const dropZone = document.querySelector("#drop-zone");
const selectedFile = document.querySelector("#selected-file");
const archivedToggle = document.querySelector("#show-archived");
const localeToggle = document.querySelector("#locale-toggle");
const sidebarToggle = document.querySelector("#sidebar-toggle");
const vacancySidebar = document.querySelector("#vacancy-sidebar");
const VACANCY_TABS = ["Overview", "Resume", "ATS", "AI / Codex", "Timeline", "Notes", "Files"];
let lastWorkspaceScrollTop = 0;

const RU = {
  "LOCAL CAREER WORKSPACE": "ЛОКАЛЬНОЕ ПРОСТРАНСТВО ПОИСКА РАБОТЫ",
  "Primary navigation": "Основная навигация",
  "Vacancies": "Вакансии", "Master Resume": "Главное резюме", "Analytics": "Аналитика", "+ Add vacancy": "+ Добавить вакансию", "LOCAL PROCESS ANALYTICS": "ЛОКАЛЬНАЯ АНАЛИТИКА ПРОЦЕССА", "Activity uses event dates; funnel uses vacancies added in the selected period.": "Активность считается по датам событий, а воронка — по вакансиям, добавленным в выбранном периоде.", "How analytics works": "Как работает аналитика", "Got it": "Понятно", "Period": "Период", "Grouping": "Группировка", "From": "От", "To": "До", "All time": "Всё время", "Current month": "Текущий месяц", "Last 3 months": "Последние 3 месяца", "Current year": "Текущий год", "Custom range": "Произвольный диапазон", "By month": "По месяцам", "By week": "По неделям", "Vacancies added": "Добавлено вакансий", "Applications sent": "Отправлено откликов", "Vacancies with interview": "Вакансий с интервью", "Interviews completed": "Проведено интервью", "Offers received": "Получено офферов", "Rejections received": "Получено отказов", "Active processes": "Активных процессов", "Successfully completed": "Успешно завершено", "Job-search funnel": "Воронка поиска работы", "Conversions": "Конверсии", "Transition": "Переход", "Base": "База", "Reached": "Достигли", "Conversion": "Конверсия", "Final outcomes": "Конечные результаты", "Activity trend": "Динамика активности", "Added / applications / interviews": "Добавлено / отклики / интервью", "Vacancies": "Вакансии", "Applications": "Отклики", "Interviews": "Интервью", "No activity in this period.": "В этом периоде активности нет.", "CareerFlow calculates analytics from recorded structured events. Mark submitted resumes, interview results, offers and final outcomes for accurate statistics.": "CareerFlow считает аналитику по зафиксированным структурированным событиям. Отмечайте отправленные резюме, результаты интервью, офферы и конечные исходы.", "Activity cards and the trend use events that happened within the selected period. The funnel and conversion table use vacancies added within that period and inspect their full history.": "Карточки активности и динамика используют события выбранного периода. Воронка и таблица конверсий учитывают вакансии, добавленные в этот период, и анализируют всю их историю.", "Several interview rounds count as several activity events, but as one vacancy in the funnel. Legacy vacancies archived during the analytics migration are intentionally excluded.": "Несколько раундов интервью считаются отдельными событиями активности, но одной вакансией в воронке. Архивные вакансии, созданные до миграции аналитики, намеренно исключены.", "Incomplete data": "Неполные данные",
  "Archived": "Архив", "Build your job-search workspace": "Создайте рабочее пространство для поиска работы",
  "Add a vacancy by pasting its text or dropping a TXT, HTML, PDF, or DOCX file.": "Добавьте вакансию: вставьте текст или перетащите файл TXT, HTML, PDF или DOCX.",
  "Add your first vacancy": "Добавить первую вакансию", "NEW RECORD": "НОВАЯ ЗАПИСЬ", "Add vacancy": "Добавить вакансию",
  "Close": "Закрыть", "Drop a file here": "Перетащите файл сюда", "or click to choose TXT, HTML, PDF, or DOCX": "или нажмите, чтобы выбрать TXT, HTML, PDF или DOCX",
  "or paste vacancy text": "или вставьте текст вакансии", "Description": "Описание", "Paste the full vacancy description…": "Вставьте полное описание вакансии…",
  "Use Codex to classify page clutter": "Использовать Codex для классификации лишних блоков", "Only when requested; vacancy text will be sent to the local Codex CLI.": "Только по запросу; текст вакансии будет передан локальному Codex CLI.",
  "Title (optional)": "Название (необязательно)", "Company (optional)": "Компания (необязательно)", "Salary (optional)": "Зарплата (необязательно)", "Source (optional)": "Источник (необязательно)",
  "Auto-detected": "Определится автоматически", "LinkedIn, referral…": "LinkedIn, рекомендация…", "Cancel": "Отмена", "Review description": "Проверить описание",
  "No archived vacancies.": "Архивных вакансий нет.", "No vacancies yet.": "Вакансий пока нет.", "Company not set": "Компания не указана", "Salary not specified": "Зарплата не указана", "No summary yet": "Описание пока отсутствует",
  "Saved": "Сохранена", "Applied": "Отклик отправлен", "Interview": "Собеседование", "Waiting": "Ожидание", "Offer": "Оффер", "Rejected": "Отказ",
  "Vacancy stage": "Этап вакансии", "Added": "Добавлена", "ATS": "ATS", "AI": "AI", "Heuristic ATS text-match score, not a probability of getting the job": "Эвристическая оценка совпадения ATS, не вероятность получения работы",
  "Overview": "Обзор", "Resume": "Резюме", "Timeline": "История", "Notes": "Заметки", "Files": "Файлы", "AI / Codex": "AI / Codex",
  "Export .md": "Экспорт .md", "Edit": "Изменить", "Restore": "Восстановить", "Archive": "Архивировать", "Delete": "Удалить",
  "SALARY": "ЗАРПЛАТА", "SOURCE": "ИСТОЧНИК", "Not specified": "Не указана", "Summary": "Краткое описание", "No summary": "Описание отсутствует",
  "Confirmed vacancy description": "Подтверждённое описание вакансии", "Used for ATS and Codex context. The original import remains preserved.": "Используется для ATS и контекста Codex. Исходный импорт сохраняется.",
  "Use Codex for this review": "Использовать Codex для этой проверки", "Only when selected; vacancy text will be sent to the local Codex CLI.": "Только при выборе; текст вакансии будет передан локальному Codex CLI.", "Clean description": "Очистить описание", "Review the proposed text before confirming. Original vacancy content remains unchanged.": "Проверьте текст перед подтверждением. Исходное содержимое вакансии не изменится.",
  "Codex classification completed successfully.": "Классификация Codex успешно завершена.", "Codex classification failed; local rules were used. Review uncertain blocks before confirmation.": "Классификация Codex не удалась; использованы локальные правила. Проверьте сомнительные блоки перед подтверждением.",
  "The primary Codex model could not classify this description.": "Основная модель Codex не смогла классифицировать это описание.", "Retry once with the stronger model": "Повторить один раз с более мощной моделью",
  "Cleaning method:": "Метод очистки:", "Original imported text": "Исходный импортированный текст", "Cleaned draft (editable)": "Очищенный вариант (можно редактировать)", "Removed blocks": "Удалённые блоки", "Needs review": "Требует проверки", "Nothing removed": "Ничего не удалено", "No uncertain blocks": "Сомнительных блоков нет", "Removed": "Удалено", "Uncertain": "Сомнительно", "Back": "Назад", "Confirm": "Подтвердить", "Confirm cleaned description": "Подтвердить очищенное описание",
  "Title": "Название", "Company": "Компания", "Salary": "Зарплата", "Source": "Источник", "Save changes": "Сохранить изменения",
  "Source version deleted": "Исходная версия удалена", "Created independently": "Создано независимо", "Based on Master Resume": "На основе главного резюме", "Based on Vacancy Resume": "На основе резюме вакансии",
  "Preview": "Предпросмотр", "Create next version": "Создать следующую версию", "Create new version from this": "Создать новую версию на основе этой", "Download Markdown": "Скачать Markdown", "Download original": "Скачать оригинал", "Submitted": "Отправлено", "Mark submitted": "Отметить отправленным", "Version": "Версия", "Resume name": "Название резюме",
  "Permanently delete this resume version? Its stored text and original files will be permanently removed. ATS history and existing copied child versions will remain, and any submitted marker will be cleared. Saved AI/Codex run history and copies already returned or exported outside CareerFlow are not scrubbed automatically.": "Удалить эту версию резюме навсегда? Сохранённый текст и исходные файлы будут удалены. История ATS и уже скопированные дочерние версии останутся, а отметка об отправке будет снята. История запусков AI/Codex и уже экспортированные копии автоматически не очищаются.",
  "Resume version deleted": "Версия резюме удалена", "GLOBAL IMMUTABLE LIBRARY": "ГЛОБАЛЬНАЯ НЕИЗМЕНЯЕМАЯ БИБЛИОТЕКА", "MASTER RESUME": "ГЛАВНОЕ РЕЗЮМЕ", "Create a new version whenever your canonical resume changes.": "Создавайте новую версию при каждом изменении основного резюме.", "Resume list": "Список резюме", "Add resume": "Добавить резюме", "Create a Master Resume version": "Создать версию главного резюме", "Create a new version": "Создать новую версию", "Create a version": "Создать версию", "Version name": "Название версии", "Resume file (PDF, DOCX, TXT, MD)": "Файл резюме (PDF, DOCX, TXT, MD)", "Or edit Markdown": "Или отредактируйте Markdown", "Save Master Resume version": "Сохранить версию главного резюме", "Master Resume copied into an editable new-version draft.": "Главное резюме скопировано в редактируемый черновик новой версии.", "Master Resume version created": "Версия главного резюме создана",
  "VACANCY-SPECIFIC HISTORY": "ИСТОРИЯ ПО ВАКАНСИИ", "Resume versions for this vacancy": "Версии резюме для этой вакансии", "No vacancy-specific versions yet.": "Версий для этой вакансии пока нет.", "Create from Master Resume": "Создать из главного резюме", "Copy into draft": "Скопировать в черновик", "No Master Resume exists yet.": "Главного резюме пока нет.", "Create one in the Master Resume section.": "Создайте его в разделе «Главное резюме».", "Add a vacancy-specific version": "Добавить версию для вакансии", "Save vacancy resume version": "Сохранить версию резюме вакансии", "Vacancy resume version created": "Версия резюме вакансии создана", "Submitted version recorded": "Отправленная версия сохранена",
  "EVIDENCE-BASED LOCAL COMPARISON": "ЛОКАЛЬНОЕ СРАВНЕНИЕ НА ОСНОВЕ ФАКТОВ", "ATS analysis": "Анализ ATS", "Run analysis": "Запустить анализ", "Run again": "Запустить снова", "Loading ATS workspace…": "Загрузка рабочего пространства ATS…", "Review the cleaned vacancy description before running ATS.": "Проверьте очищенное описание вакансии перед запуском ATS.", "ATS analysis requires a resume.": "Для анализа ATS нужно резюме.", "Create a resume for this vacancy or use a Master Resume version.": "Создайте резюме для этой вакансии или используйте версию главного резюме.", "Select a resume version and run ATS analysis.": "Выберите версию резюме и запустите анализ ATS.", "Create from Master Resume": "Создать из главного резюме", "Add resume": "Добавить резюме", "Requirements and evidence": "Требования и подтверждения", "Keywords": "Ключевые слова", "Covered": "Подтверждено", "Partial": "Частично", "Missing": "Не найдено",
  "EVENT LOG": "ЖУРНАЛ СОБЫТИЙ", "Add interview": "Добавить собеседование", "Date and time": "Дата и время", "Type": "Тип", "Notes": "Заметки", "Result": "Результат", "Scheduled, passed, follow-up…": "Назначено, пройдено, дальнейшие шаги…", "Add interview": "Добавить собеседование", "Interview added": "Собеседование добавлено",
  "DATED NOTES": "ЗАМЕТКИ ПО ДАТАМ", "New note": "Новая заметка", "Interview preparation, company research, impressions…": "Подготовка к собеседованию, исследование компании, впечатления…", "Add note": "Добавить заметку", "No notes yet.": "Заметок пока нет.", "Save": "Сохранить", "Note added": "Заметка добавлена", "Note saved": "Заметка сохранена", "Delete this note?": "Удалить эту заметку?", "Note deleted": "Заметка удалена",
  "LOCAL STORAGE": "ЛОКАЛЬНОЕ ХРАНИЛИЩЕ", "Attach file": "Прикрепить файл", "Up to 100 MB. Audio is stored as-is; automatic transcription is outside the MVP.": "До 100 МБ. Аудио хранится как есть; автоматическая расшифровка не входит в MVP.", "No attachments yet.": "Вложений пока нет.", "Download": "Скачать", "Remove this attachment?": "Удалить это вложение?", "File attached": "Файл прикреплён", "File removed": "Файл удалён", "Building…": "Формирование…", "Markdown report generated": "Markdown-отчёт создан",
  "READ-ONLY CLI ASSISTANT": "CLI-АССИСТЕНТ ТОЛЬКО ДЛЯ ЧТЕНИЯ", "CareerFlow sends the generated vacancy Markdown context to": "CareerFlow отправляет сгенерированный Markdown-контекст вакансии в", "Action": "Действие", "Analyze vacancy": "Анализ вакансии", "Improve resume": "Улучшить резюме", "Review ATS analysis": "Проверить анализ ATS", "Match resume to vacancy": "Сопоставить резюме с вакансией", "Create tailored resume": "Создать резюме под вакансию", "Prepare for interview": "Подготовиться к собеседованию", "Analyze interview notes": "Проанализировать заметки собеседования", "Custom request": "Свой запрос", "Model": "Модель", "Reasoning effort": "Уровень рассуждений", "Response language": "Язык ответа", "Auto": "Авто", "Russian": "Русский", "English": "Английский", "Request": "Запрос", "Run Codex": "Запустить Codex", "Saved responses": "Сохранённые ответы", "No saved responses yet.": "Сохранённых ответов пока нет.", "Filter saved responses…": "Фильтр сохранённых ответов…", "Codex response saved below. Open it when you are ready to review.": "Ответ Codex сохранён ниже. Откройте его, когда будете готовы к просмотру.", "View response": "Открыть ответ", "Hide response": "Скрыть ответ", "Create editable resume draft": "Создать редактируемый черновик резюме", "Tailored resume copied into an editable draft. Review it before saving a new version.": "Резюме под вакансию скопировано в редактируемый черновик. Проверьте его перед сохранением новой версии.", "Codex is working…": "Codex работает…", "Codex response received": "Ответ Codex получен", "AI match score updated": "AI-оценка совпадения обновлена", "AI match score": "AI-оценка совпадения", "AI score is not available because the model did not return valid JSON.": "AI-оценка недоступна: модель не вернула корректный JSON.", "Review the response, then manually decide what to save as a new resume version or note.": "Проверьте ответ и вручную решите, что сохранить как новую версию резюме или заметку.", "Legacy model unknown": "Старая модель неизвестна", "effort unknown": "уровень неизвестен", "Open vacancy list": "Открыть список вакансий", "Close vacancy list": "Закрыть список вакансий", "Switch to dark theme": "Переключить на тёмную тему", "Switch to light theme": "Переключить на светлую тему",
  "Review description": "Проверить описание", "Preparing preview…": "Подготовка предпросмотра…", "Vacancy imported": "Вакансия импортирована", "Deletion cancelled": "Удаление отменено", "Vacancy deleted": "Вакансия удалена", "Vacancy archived": "Вакансия отправлена в архив", "Vacancy restored": "Вакансия восстановлена", "Vacancy updated": "Вакансия обновлена", "Status changed to": "Статус изменён на", "Invalid value": "Недопустимое значение", "Request failed": "Запрос не выполнен", "Error": "Ошибка"
};

function translateText(value) {
  if (state.locale !== "ru") return value;
  const trimmed = value.trim();
  if (RU[trimmed]) return value.replace(trimmed, RU[trimmed]);
  return value
    .replace(/\bAdded\b/g, RU.Added)
    .replace(/\bATS (\d+%)/g, `${RU.ATS} $1`)
    .replace(/Company not set/g, RU["Company not set"])
    .replace(/Salary not specified/g, RU["Salary not specified"])
    .replace(/No summary yet/g, RU["No summary yet"])
    .replace(/Only when selected; vacancy text will be sent to the local Codex CLI\./g, RU["Only when selected; vacancy text will be sent to the local Codex CLI."])
    .replace(/Status changed to (.+)/g, (_, status) => `${RU["Status changed to"]} ${RU[status] || status}`)
    .replace(/Interview ·/g, `${RU.Interview} ·`)
    .replace(/Based on (Master Resume|Vacancy Resume) v(\d+)/g, (_, kind, version) => `${RU[`Based on ${kind}`]} v${version}`)
    .replace(/(Add interview) #(\d+)/g, (_, label, number) => `${RU[label]} #${number}`);
}

function applyLocale(root = document.body) {
  if (!root || state.locale !== "ru") return;
  const walker = document.createTreeWalker?.(root, typeof NodeFilter === "undefined" ? 4 : NodeFilter.SHOW_TEXT);
  if (walker) {
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent || parent.closest("textarea, pre, blockquote, .overview-text, .markdown-preview, .ai-response, .tag")) continue;
      node.nodeValue = translateText(node.nodeValue);
    }
  }
  root.querySelectorAll?.("[placeholder], [title], [aria-label]").forEach(element => {
    for (const attribute of ["placeholder", "title", "aria-label"]) {
      if (element.hasAttribute(attribute)) element.setAttribute(attribute, translateText(element.getAttribute(attribute)));
    }
  });
}

function setTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  if (document.documentElement) {
    document.documentElement.dataset.theme = state.theme;
    if (document.documentElement.style) document.documentElement.style.colorScheme = state.theme;
  }
  if (themeToggle) {
    const darkTheme = state.theme === "dark";
    themeToggle.textContent = darkTheme ? "☀" : "☾";
    const label = darkTheme ? "Switch to light theme" : "Switch to dark theme";
    themeToggle.setAttribute?.("aria-label", translateText(label));
    themeToggle.setAttribute?.("title", translateText(label));
  }
  try { localStorage.setItem("careerflow-theme", state.theme); } catch (_) { /* Ignore unavailable storage. */ }
}

function setLocale(locale) {
  state.locale = locale === "ru" ? "ru" : "en";
  try { localStorage.setItem("careerflow-locale", state.locale); } catch (_) { /* Ignore unavailable storage. */ }
  if (document.documentElement) document.documentElement.lang = state.locale;
  if (localeToggle) {
    localeToggle.textContent = state.locale === "ru" ? "eng" : "ru";
    localeToggle.setAttribute("aria-label", state.locale === "ru" ? "Switch language to English" : "Переключить язык на русский");
  }
  if (state.locale === "ru") applyLocale();
  else window.location.reload();
  if (state.locale === "ru" && state.section === "analytics") {
    renderAnalytics().catch(error => showError(error));
  }
}

localeToggle?.addEventListener("click", () => setLocale(state.locale === "ru" ? "en" : "ru"));
themeToggle?.addEventListener("click", () => setTheme(state.theme === "dark" ? "light" : "dark"));
if (typeof MutationObserver !== "undefined") new MutationObserver(() => applyLocale()).observe(document.body, { childList: true, subtree: true });

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

function renderSafeMarkdown(value = "") {
  const inline = text => escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/_([^_]+)_/g, "<em>$1</em>");
  const lines = String(value).replaceAll("\r", "").split("\n");
  const html = [];
  let listOpen = false;
  const closeList = () => { if (listOpen) { html.push("</ul>"); listOpen = false; } };
  for (const line of lines) {
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
    } else if (bullet) {
      if (!listOpen) { html.push("<ul>"); listOpen = true; }
      html.push(`<li>${inline(bullet[1])}</li>`);
    } else if (line.trim()) {
      closeList();
      html.push(`<p>${inline(line)}</p>`);
    } else {
      closeList();
    }
  }
  closeList();
  return html.join("");
}

function setSection(section) {
  state.section = section;
  lastWorkspaceScrollTop = 0;
  topbar?.classList?.remove?.("header-nav-hidden");
  document.querySelectorAll("[data-section]").forEach(button => button.classList.toggle("active", button.dataset.section === section));
  topbar?.setAttribute?.("data-section", section);
  appLayout.classList.toggle("master-mode", section !== "vacancies");
  setSidebarOpen(false);
  if (sidebarToggle) {
    sidebarToggle.hidden = false;
    sidebarToggle.disabled = false;
    sidebarToggle.setAttribute?.("aria-label", translateText("Open vacancy list"));
  }
  newVacancyButton.hidden = false;
}

function updateHeaderOnScroll() {
  if (typeof window !== "undefined" && window.matchMedia?.("(max-width: 600px)").matches) {
    topbar?.classList?.remove?.("header-nav-hidden");
    lastWorkspaceScrollTop = 0;
    return;
  }
  const documentScrollTop = document.documentElement?.scrollTop || document.body?.scrollTop || 0;
  const windowScrollTop = typeof window !== "undefined" ? window.scrollY || 0 : 0;
  const scrollTop = Math.max(0, workspace?.scrollTop || 0, documentScrollTop, windowScrollTop);
  const delta = scrollTop - lastWorkspaceScrollTop;
  if (scrollTop <= 8 || delta < -3) topbar?.classList?.remove?.("header-nav-hidden");
  else if (scrollTop > 28 && delta > 3) topbar?.classList?.add?.("header-nav-hidden");
  lastWorkspaceScrollTop = scrollTop;
}

const ANALYTICS_LABELS = {
  en: {
    added: "Added",
    application_submitted: "Application submitted",
    interview_invited: "Interview invitation",
    interview_completed: "Interview completed",
    offer_received: "Offer received",
    offer_accepted: "Offer accepted",
    added_to_application: "Added → application",
    application_to_interview: "Application → interview",
    interview_to_completed: "Interview invitation → completed interview",
    completed_to_offer: "Completed interview → offer",
    offer_to_accepted: "Offer → accepted",
    added_to_accepted: "Added → accepted offer",
    offer_declined: "Offer declined",
    employer_rejected: "Employer rejection",
    candidate_withdrew: "Candidate withdrew",
    vacancy_closed: "Vacancy closed or frozen",
    no_response: "No response",
    successful: "Successful outcomes",
    unsuccessful: "Unsuccessful outcomes",
    active: "Active processes",
  },
  ru: {
    added: "Добавлено",
    application_submitted: "Отклик отправлен",
    interview_invited: "Приглашение на интервью",
    interview_completed: "Интервью проведено",
    offer_received: "Оффер получен",
    offer_accepted: "Оффер принят",
    added_to_application: "Добавлено → отклик",
    application_to_interview: "Отклик → приглашение на интервью",
    interview_to_completed: "Приглашение → проведённое интервью",
    completed_to_offer: "Проведённое интервью → оффер",
    offer_to_accepted: "Оффер → принят",
    added_to_accepted: "Добавлено → принятый оффер",
    offer_declined: "Оффер отклонён кандидатом",
    employer_rejected: "Отказ работодателя",
    candidate_withdrew: "Кандидат прекратил процесс",
    vacancy_closed: "Вакансия закрыта или заморожена",
    no_response: "Нет ответа",
    successful: "Успешные исходы",
    unsuccessful: "Неуспешные исходы",
    active: "Активные процессы",
  },
};

function analyticsLabel(code) {
  return ANALYTICS_LABELS[state.locale]?.[code] || ANALYTICS_LABELS.en[code] || code;
}

workspace?.addEventListener?.("scroll", updateHeaderOnScroll, { passive: true });
if (typeof window !== "undefined") window.addEventListener?.("scroll", updateHeaderOnScroll, { passive: true });
document.addEventListener?.("scroll", updateHeaderOnScroll, { passive: true, capture: true });

function setSidebarOpen(open) {
  const isOpen = Boolean(open);
  state.sidebarOpen = isOpen;
  appLayout.classList.toggle("sidebar-open", isOpen);
  sidebarToggle?.setAttribute?.("aria-expanded", String(isOpen));
  sidebarToggle?.setAttribute?.("aria-label", translateText(isOpen ? "Close vacancy list" : "Open vacancy list"));
  const isCompactViewport = typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(max-width: 900px)").matches;
  vacancySidebar?.setAttribute?.("aria-hidden", String(isCompactViewport && !isOpen));
  if (vacancySidebar && "inert" in vacancySidebar) vacancySidebar.inert = isCompactViewport && !isOpen;
}

async function showVacancies() {
  const returningFromAnotherSection = state.section !== "vacancies";
  const rememberedVacancy = state.lastSelectedVacancy;
  const rememberedTab = state.lastSelectedVacancyTab;
  setSection("vacancies");
  state.viewEpoch++;
  if (returningFromAnotherSection && rememberedVacancy) {
    state.selected = rememberedVacancy;
    renderVacancy(rememberedVacancy);
    if (VACANCY_TABS.includes(rememberedTab) && rememberedTab !== "Overview") {
      await openTab(rememberedTab, rememberedVacancy);
    }
  } else if (state.selected) {
    renderEmpty();
  }
  else renderEmpty();
}

async function renderAnalytics() {
  setSection("analytics");
  state.viewEpoch++;
  const epoch = state.viewEpoch;
  workspace.innerHTML = `<div class="workspace-head analytics-head"><div><p class="eyebrow">LOCAL PROCESS ANALYTICS</p><h2>Analytics</h2><p class="muted">Activity uses event dates; funnel uses vacancies added in the selected period.</p></div><button class="icon-button help-button" type="button" aria-label="How analytics works" title="How analytics works">?</button></div><section class="analytics-filters panel"><label>Period<select id="analytics-period"><option value="">All time</option><option value="month">Current month</option><option value="3months">Last 3 months</option><option value="year">Current year</option><option value="custom">Custom range</option></select></label><label>Grouping<select id="analytics-bucket"><option value="month">By month</option><option value="week">By week</option></select></label><label class="analytics-date">From<input id="analytics-from" type="date"></label><label class="analytics-date">To<input id="analytics-to" type="date"></label></section><div id="analytics-content"><p class="muted">Loading analytics…</p></div>`;
  const period = workspace.querySelector("#analytics-period");
  const bucket = workspace.querySelector("#analytics-bucket");
  const fromInput = workspace.querySelector("#analytics-from");
  const toInput = workspace.querySelector("#analytics-to");
  const updateCustomVisibility = () => { const visible = period.value === "custom"; fromInput.closest(".analytics-date").hidden = !visible; toInput.closest(".analytics-date").hidden = !visible; };
  const load = async () => {
    const params = new URLSearchParams({ bucket: bucket.value });
    const now = new Date();
    if (period.value === "month") { params.set("from", new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10)); params.set("to", now.toISOString().slice(0, 10)); }
    if (period.value === "3months") { params.set("from", new Date(now.getFullYear(), now.getMonth() - 2, 1).toISOString().slice(0, 10)); params.set("to", now.toISOString().slice(0, 10)); }
    if (period.value === "year") { params.set("from", `${now.getFullYear()}-01-01`); params.set("to", now.toISOString().slice(0, 10)); }
    if (period.value === "custom" && fromInput.value && toInput.value) { params.set("from", fromInput.value); params.set("to", toInput.value); }
    try { const data = await api(`/api/analytics?${params}`); if (epoch === state.viewEpoch) renderAnalyticsData(data); }
    catch (error) { if (epoch === state.viewEpoch) workspace.querySelector("#analytics-content").innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
  };
  period.onchange = () => { updateCustomVisibility(); load(); }; bucket.onchange = load; fromInput.onchange = load; toInput.onchange = load; updateCustomVisibility(); await load();
}

function renderAnalyticsData(data) {
  const labels = { vacancies_added: "Vacancies added", applications_submitted: "Applications sent", vacancies_with_interview: "Vacancies with interview", interviews_completed: "Interviews completed", offers_received: "Offers received", rejections_received: "Rejections received", active_processes: "Active processes", completed_successfully: "Successfully completed" };
  const cards = Object.entries(labels).map(([key, label]) => `<article class="analytics-card"><span>${label}</span><strong>${data.activity_metrics[key] ?? 0}</strong></article>`).join("");
  const funnel = data.funnel.map(item => `<div class="funnel-row"><span>${escapeHtml(analyticsLabel(item.stage))}</span><strong>${item.count}</strong></div>`).join("");
  const conversions = data.conversions.map(item => `<tr><td>${escapeHtml(analyticsLabel(item.transition))}</td><td>${item.base}</td><td>${item.reached}</td><td>${item.percent == null ? "—" : `${item.percent}%`}</td></tr>`).join("");
  const outcomes = Object.entries(data.outcomes).map(([key, value]) => `<div class="result-row"><span>${escapeHtml(analyticsLabel(key))}</span><strong>${value}</strong></div>`).join("");
  const incomplete = data.incomplete_records?.length ? `<section class="panel incomplete-panel"><h3>Incomplete data</h3>${data.incomplete_records.map(item => `<div class="result-row"><span>${escapeHtml(item.title)}${item.company ? ` · ${escapeHtml(item.company)}` : ""}</span><strong>${escapeHtml(item.status || "Review")}</strong></div>`).join("")}</section>` : "";
  const series = data.series.map(item => `<div class="result-row"><span>${item.period}</span><strong>${item.vacancies_added} / ${item.applications_submitted} / ${item.interviews_completed}</strong></div>`).join("") || `<p class="muted">No activity in this period.</p>`;
  const chart = renderAnalyticsChart(data.series);
  document.querySelector("#analytics-content").innerHTML = `<section class="analytics-cards">${cards}</section><div class="analytics-grid"><section class="panel"><h3>Job-search funnel</h3>${funnel}</section><section class="panel"><h3>Conversions</h3><div class="table-scroll"><table><thead><tr><th>Transition</th><th>Base</th><th>Reached</th><th>Conversion</th></tr></thead><tbody>${conversions}</tbody></table></div></section><section class="panel"><h3>Final outcomes</h3>${outcomes}</section><section class="panel"><h3>Activity trend</h3><p class="muted">Added / applications / interviews</p>${chart}${series}</section></div>${incomplete}`;
  const help = document.querySelector(".help-button");
  help?.addEventListener("click", () => { analyticsHelp?.showModal(); analyticsHelp?.querySelector("[data-close-analytics-help]")?.focus(); });
}

function renderAnalyticsChart(series) {
  if (!series.length) return "";
  const width = 640, height = 180, pad = 24;
  const max = Math.max(1, ...series.flatMap(item => [item.vacancies_added, item.applications_submitted, item.interviews_completed]));
  const point = (key, index) => { const x = pad + (index * (width - pad * 2)) / Math.max(1, series.length - 1); const y = height - pad - (series[index][key] * (height - pad * 2)) / max; return `${x},${y}`; };
  const line = key => series.map((_, index) => point(key, index)).join(" ");
  return `<svg class="analytics-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Activity trend: vacancies, applications and interviews"><polyline class="chart-line vacancies" points="${line("vacancies_added")}"/><polyline class="chart-line applications" points="${line("applications_submitted")}"/><polyline class="chart-line interviews" points="${line("interviews_completed")}"/></svg><div class="chart-legend"><span class="vacancies">Vacancies</span><span class="applications">Applications</span><span class="interviews">Interviews</span></div>`;
}

function isCurrentMasterView(epoch, panel = workspace) {
  return state.section === "master-resume" && state.viewEpoch === epoch && workspace === panel;
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
    state.section === "vacancies"
    &&
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
  if (!state.selected && state.pendingVacancyId && state.section === "vacancies") {
    const restoreId = state.pendingVacancyId;
    const restoreTab = state.pendingVacancyTab;
    state.pendingVacancyId = null;
    state.pendingVacancyTab = null;
    const restoreEpoch = ++state.selectionEpoch;
    if (state.vacancies.some(item => item.id === restoreId)) {
      try {
        const vacancy = await api(`/api/vacancies/${restoreId}`);
        if (restoreEpoch === state.selectionEpoch && state.section === "vacancies" && !state.selected) {
          renderVacancy(vacancy);
          if (VACANCY_TABS.includes(restoreTab) && restoreTab !== "Overview") await openTab(restoreTab, vacancy);
        }
      } catch (_) { clearSavedVacancyNavigation(); }
    } else {
      clearSavedVacancyNavigation();
    }
  }
  if (state.selected && selectionEpoch === state.selectionEpoch) {
    const current = state.vacancies.find(item => item.id === state.selected.id);
    if (!current) { state.selected = null; state.lastSelectedVacancy = null; state.lastSelectedVacancyTab = null; renderEmpty(); }
  }
}

function renderList() {
  if (!state.vacancies.length) {
    listEl.innerHTML = `<p class="muted">${archivedToggle.checked ? "No archived vacancies." : "No vacancies yet."}</p>`;
    return;
  }
    listEl.innerHTML = state.vacancies.map(item => `
    <button class="vacancy-card ${state.selected?.id === item.id ? "active" : ""}" data-id="${item.id}">
      <strong class="vacancy-title" title="${escapeAttr(item.title)}">${escapeHtml(compactVacancyTitle(item.title))}</strong>
      <span>${escapeHtml(item.company || "Company not set")}</span>
      <span class="vacancy-meta">${escapeHtml(item.salary || "Salary not specified")} · Added ${new Date(`${item.created_at}Z`).toLocaleDateString()}</span>
      <span class="vacancy-summary">${escapeHtml(item.summary || "No summary yet")}</span>
      <span class="card-meta"><span class="badge">${escapeHtml(item.status)}</span><span class="score-group"><span title="Heuristic ATS text-match score, not a probability of getting the job">${item.match_percent == null ? "—" : `ATS ${item.match_percent}%`}</span>${item.ai_match_percent == null ? "" : `<span title="AI resume-to-vacancy score">AI ${item.ai_match_percent}%</span>`}</span></span>
    </button>`).join("");
}

function compactVacancyTitle(title) {
  const value = String(title || "").trim();
  const withoutPrefix = value.replace(/^(?:вакансия|ищем|нужен|требуется)\s+/i, "");
  const beforeCompany = withoutPrefix.split(/\s+(?:в компании|в компанию|—|–|—)\s+/i)[0].trim();
  return (beforeCompany || withoutPrefix || value).slice(0, 88);
}

function renderEmpty({ preserveSidebar = false } = {}) {
  const keepSidebarOpen = preserveSidebar && state.sidebarOpen;
  setSection("vacancies");
  state.selected = null;
  state.lastSelectedVacancy = null;
  state.lastSelectedVacancyTab = null;
  state.pendingVacancyId = null;
  state.pendingVacancyTab = null;
  clearSavedVacancyNavigation();
  state.activeTab = null;
  state.viewEpoch++;
  state.selectionEpoch++;
  workspace.innerHTML = `<div class="empty-state"><span class="empty-icon">↗</span><h2>Build your job-search workspace</h2><p>Add a vacancy by pasting its text or dropping a TXT, HTML, PDF, or DOCX file.</p><button class="primary" data-open-import>Add your first vacancy</button></div>`;
  if (keepSidebarOpen) setSidebarOpen(true);
}

const STAGES = ["Saved", "Applied", "Interview", "Waiting", "Offer", "Rejected"];

function stageBar(vacancy, interviewCount = state.interviewCounts.get(vacancy.id) ?? 0) {
  return `<div class="stage-scroll" aria-label="Vacancy stage"><div class="stage-bar">${STAGES.map(status => `<button type="button" class="stage-step ${status === vacancy.status ? "active" : ""}" data-stage="${status}" aria-pressed="${status === vacancy.status}">${status === "Interview" ? `Interview · <span data-interview-count>${interviewCount}</span>` : status}</button>`).join("")}</div></div>`;
}

function bindStageBar(vacancy) {
  document.querySelectorAll("[data-stage]").forEach(button => {
    button.onclick = async () => {
      if (button.dataset.stage === vacancy.status || button.disabled) return;
      const buttons = [...document.querySelectorAll("[data-stage]")];
      const previous = vacancy.status;
      buttons.forEach(item => {
        item.disabled = true;
        item.classList.toggle("active", item.dataset.stage === button.dataset.stage);
        item.setAttribute?.("aria-pressed", String(item.dataset.stage === button.dataset.stage));
      });
      try {
        const updated = await api(`/api/vacancies/${vacancy.id}/status`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: button.dataset.stage }),
        });
        await loadVacancies();
        if (state.section === "vacancies" && state.selected?.id === vacancy.id) renderVacancy(updated);
        toast(`Status changed to ${updated.status}`);
      } catch (error) {
        buttons.forEach(item => {
          item.classList.toggle("active", item.dataset.stage === previous);
          item.setAttribute?.("aria-pressed", String(item.dataset.stage === previous));
        });
        showError(error);
      } finally {
        buttons.forEach(item => { item.disabled = false; });
      }
    };
  });
}

function interviewCountEpoch(vacancyId) {
  return state.interviewCountEpochs.get(vacancyId) || 0;
}

function updateInterviewCount(vacancyId, count, epoch = interviewCountEpoch(vacancyId)) {
  if (interviewCountEpoch(vacancyId) !== epoch) return;
  state.interviewCounts.set(vacancyId, count);
  if (state.section !== "vacancies" || state.selected?.id !== vacancyId) return;
  const counter = document.querySelector("[data-interview-count]");
  if (counter) counter.textContent = String(count);
}

function invalidateInterviewCount(vacancyId) {
  const epoch = interviewCountEpoch(vacancyId) + 1;
  state.interviewCountEpochs.set(vacancyId, epoch);
  state.interviewRequests.delete(vacancyId);
  return epoch;
}

function loadInterviews(vacancyId) {
  const epoch = interviewCountEpoch(vacancyId);
  const current = state.interviewRequests.get(vacancyId);
  if (current?.epoch === epoch) return current.promise;

  const request = { epoch, promise: null };
  request.promise = api(`/api/vacancies/${vacancyId}/interviews`)
    .then(interviews => {
      updateInterviewCount(vacancyId, interviews.length, epoch);
      return interviews;
    })
    .finally(() => {
      if (state.interviewRequests.get(vacancyId) === request) state.interviewRequests.delete(vacancyId);
    });
  state.interviewRequests.set(vacancyId, request);
  return request.promise;
}

async function refreshInterviewCount(vacancy) {
  try {
    await loadInterviews(vacancy.id);
  } catch (error) { /* The stage remains usable if the count cannot be refreshed. */ }
}

function renderVacancy(vacancy) {
  setSection("vacancies");
  state.selectionEpoch++;
  state.viewEpoch++;
  state.activeTab = "Overview";
  state.selected = vacancy;
  state.lastSelectedVacancy = vacancy;
  state.lastSelectedVacancyTab = "Overview";
  saveVacancyNavigation(vacancy.id, "Overview");
  renderList();
  workspace.innerHTML = `
    <div class="workspace-head">
      <div><p class="eyebrow">${escapeHtml(vacancy.status)}</p><h2 class="vacancy-title" title="${escapeAttr(vacancy.title)}">${escapeHtml(compactVacancyTitle(vacancy.title))}</h2><p class="muted">${escapeHtml(vacancy.company || "Company not set")} · Added ${new Date(vacancy.created_at + "Z").toLocaleDateString()}</p></div>
      <div class="actions"><button id="export-report" class="secondary">Export .md</button><button id="edit-overview" class="secondary">Edit</button><button id="archive-vacancy" class="secondary">${vacancy.archived_at ? "Restore" : "Archive"}</button><button id="delete-vacancy" class="danger">Delete</button></div>
    </div>
    ${stageBar(vacancy)}
    <nav class="tabs">${VACANCY_TABS.map((tab, i) => `<button class="tab ${i === 0 ? "active" : ""}" data-tab="${tab}">${tab}</button>`).join("")}</nav>
    <section class="panel" id="content-panel"></section>`;
  document.querySelector("#edit-overview").onclick = () => renderEdit(vacancy);
  document.querySelector("#archive-vacancy").onclick = event => runAction(event.currentTarget, () => toggleArchive(vacancy));
  document.querySelector("#delete-vacancy").onclick = event => runAction(event.currentTarget, () => removeVacancy(vacancy));
  document.querySelector("#export-report").onclick = () => exportReport(vacancy);
  bindStageBar(vacancy);
  document.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => openTab(button.dataset.tab, vacancy));
  renderOverview(vacancy);
  refreshInterviewCount(vacancy);
}

function activateTab(name) {
  document.querySelectorAll("[data-tab]").forEach(button => button.classList.toggle("active", button.dataset.tab === name));
}

async function openTab(name, vacancy) {
  if (state.selected?.id !== vacancy.id) return;
  state.activeTab = name;
  state.lastSelectedVacancyTab = name;
  saveVacancyNavigation(vacancy.id, name);
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
  const source = String(vacancy.source || "").trim();
  const sourceIsUrl = /^https?:\/\//i.test(source);
  const sourceValue = sourceIsUrl
    ? `<a class="source-link" href="${escapeAttr(source)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source)}</a>`
    : escapeHtml(source || vacancy.source_type || translateText("Not specified"));
  panel.innerHTML = `
    <div class="form-grid overview-meta"><div><p class="eyebrow">SALARY</p><p>${escapeHtml(vacancy.salary || "Not specified")}</p></div><div><p class="eyebrow">SOURCE</p><p>${sourceValue}</p></div></div>
    <h3>Summary</h3><p>${escapeHtml(vacancy.summary || "No summary")}</p>
    <div class="section-head description-head"><div><h3>Confirmed vacancy description</h3><p class="muted">Used for ATS and Codex context. The original import remains preserved.</p></div><div class="stack"><label class="check-row"><input id="review-cleaning-codex" type="checkbox">Use Codex for this review <span class="muted">Only when selected; vacancy text will be sent to the local Codex CLI.</span></label><button class="secondary" id="review-cleaning">Clean description</button></div></div>
    <div class="overview-text">${escapeHtml(vacancy.description)}</div><div id="cleaning-review" aria-live="polite"></div>`;
  panel.querySelector("#review-cleaning").onclick = () => renderExistingDescriptionReview(vacancy);
}

function renderCleaningReview(preview, errorId) {
  const removed = preview.removed_blocks || [];
  const uncertain = preview.uncertain_blocks || [];
  const diagnostics = preview.diagnostics || {};
  const codexProfile = diagnostics.codex_model
    ? ` <code>${escapeHtml(diagnostics.codex_model)} / ${escapeHtml(diagnostics.codex_effort || "unknown")}</code>`
    : "";
  const classificationNotice = diagnostics.classification_source === "codex"
    ? `<div class="callout"><span>Codex classification completed successfully.</span>${codexProfile}</div>`
    : diagnostics.codex_requested && diagnostics.fallback_used
      ? `<div class="callout"><span>${escapeHtml((preview.warnings || [])[0] || "Codex classification failed; local rules were used. Review uncertain blocks before confirmation.")}</span>${codexProfile}</div>`
      : "";
  return `<section class="cleaning-review"><div class="callout">Review the proposed text before confirming. Original vacancy content remains unchanged.</div>
    ${classificationNotice}
    <p class="muted">Cleaning method: ${escapeHtml(preview.method || "local")}</p>
    <div class="form-grid"><label>Original imported text<textarea rows="10" readonly>${escapeHtml(preview.raw_description || "")}</textarea></label><label>Cleaned draft (editable)<textarea rows="10" data-cleaned-description>${escapeHtml(preview.description || "")}</textarea></label></div>
    <div class="split-grid"><section><h4>Removed blocks (${removed.length})</h4><ul class="review-list">${removed.length ? removed.map(item => `<li><strong>${escapeHtml(item.text)}</strong><span class="muted">${escapeHtml(item.reason || "Removed")}</span></li>`).join("") : `<li class="muted">Nothing removed</li>`}</ul></section><section><h4>Needs review (${uncertain.length})</h4><ul class="review-list">${uncertain.length ? uncertain.map(item => `<li><strong>${escapeHtml(item.text)}</strong><span class="muted">${escapeHtml(item.reason || "Uncertain")}</span></li>`).join("") : `<li class="muted">No uncertain blocks</li>`}</ul></section></div>
    <p class="error" id="${errorId}"></p><div class="dialog-actions"><button type="button" class="secondary" data-cancel-cleaning>Back</button><button type="button" class="primary" data-confirm-cleaning>Confirm</button></div></section>`;
}

function codexEscalationPrompt(preview) {
  const diagnostics = preview?.diagnostics || {};
  if (!diagnostics.fallback_used || diagnostics.escalation_available !== true || !diagnostics.escalation_model || !diagnostics.escalation_effort) return false;
  const model = `${diagnostics.escalation_model} / ${diagnostics.escalation_effort}`;
  return window.confirm(`${translateText("The primary Codex model could not classify this description.")} ${translateText("Retry once with the stronger model")} ${model}?`);
}

async function retryWithCodexEscalation(preview, request) {
  if (!codexEscalationPrompt(preview)) return preview;
  return request("escalation");
}

async function renderExistingDescriptionReview(vacancy) {
  const panel = document.querySelector("#content-panel");
  const target = panel.querySelector("#cleaning-review");
  const button = panel.querySelector("#review-cleaning");
  if (button.disabled) return;
  button.disabled = true;
  const view = currentView(vacancy, "Overview", panel);
  try {
    const useCodex = panel.querySelector("#review-cleaning-codex").checked;
    const requestPreview = codexProfile => api(`/api/vacancies/${vacancy.id}/description/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ use_codex: useCodex, ...(useCodex ? { codex_profile: codexProfile } : {}) }) });
    const initialPreview = await requestPreview(useCodex ? "primary" : undefined);
    const preview = useCodex ? await retryWithCodexEscalation(initialPreview, profile => requestPreview(profile)) : initialPreview;
    if (!isCurrentView(view)) return;
    target.innerHTML = renderCleaningReview(preview, "cleaning-error");
    target.querySelector("[data-cancel-cleaning]").onclick = () => { target.innerHTML = ""; };
    target.querySelector("[data-confirm-cleaning]").onclick = async event => {
      const confirm = event.currentTarget;
      await runAction(confirm, async () => {
        const description = target.querySelector("[data-cleaned-description]").value;
        const updated = await api(`/api/vacancies/${vacancy.id}/description/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ description, method: preview.method }) });
        await loadVacancies();
        target.innerHTML = "";
        if (isCurrentView(view)) { renderVacancy(updated); toast("Cleaned description confirmed"); }
      }, target.querySelector("#cleaning-error"), view);
    };
  } catch (error) {
    if (isCurrentView(view)) target.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  } finally { if (isCurrentView(view)) button.disabled = false; }
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
      <div class="actions"><button class="primary" type="submit">Save changes</button><button class="secondary" type="button" id="cancel-edit">Cancel</button></div>
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

function resumeOrigin(item) {
  if (item.source_deleted_at) return "Source version deleted";
  if (!item.source_resume_id || !item.source_kind || !item.source_version) return "Created independently";
  return `Based on ${item.source_kind === "master" ? "Master Resume" : "Vacancy Resume"} v${item.source_version}`;
}

function resumeDisplayTitle(item) {
  if (item.kind === "master") return item.label?.trim() || translateText("Master Resume");
  return "Vacancy Resume";
}

function resumeVersionLabel(version) {
  return `${translateText("Version")} ${version}`;
}

function resumePreviewTitle(item) {
  if (item.kind === "master") return `${resumeDisplayTitle(item)} · ${resumeVersionLabel(item.version)}`;
  return `${resumeDisplayTitle(item)} v${item.version}`;
}

function resumeItem(item, { masterWorkspace = false } = {}) {
  const title = masterWorkspace && item.kind === "master"
    ? resumeDisplayTitle(item)
    : `${resumeDisplayTitle(item)} v${item.version}`;
  const metadata = masterWorkspace && item.kind === "master"
    ? `${resumeVersionLabel(item.version)} · ${new Date(item.created_at + "Z").toLocaleString()}`
    : `${item.label || "No label"} · ${new Date(item.created_at + "Z").toLocaleString()}`;
  return `<article class="item-row"><div><strong>${escapeHtml(title)}</strong><p class="muted">${escapeHtml(metadata)}</p><p class="muted resume-origin">${escapeHtml(resumeOrigin(item))}</p></div><div class="actions"><button class="secondary" type="button" data-preview-resume="${item.id}">Preview</button><button class="secondary" type="button" data-use-resume="${item.id}">${masterWorkspace ? "Create next version" : "Create new version from this"}</button><a class="secondary link-button" href="/api/resumes/${item.id}/markdown" download>Download Markdown</a>${item.original_filename ? `<a class="secondary link-button" href="/api/resumes/${item.id}/download" download>Download original</a>` : ""}${item.is_submitted ? `<span class="badge success">Submitted</span>` : item.kind === "vacancy" ? `<button class="secondary" type="button" data-submit-resume="${item.id}">Mark submitted</button>` : ""}<button class="danger" type="button" data-delete-resume="${item.id}">Delete</button></div></article>`;
}

function bindResumeDelete(panel, refresh, viewCheck, view = null) {
  document.querySelectorAll("[data-delete-resume]").forEach(button => button.onclick = () => runAction(button, async () => {
    if (!window.confirm("Permanently delete this resume version? Its stored text and original files will be permanently removed. ATS history and existing copied child versions will remain, and any submitted marker will be cleared. Saved AI/Codex run history and copies already returned or exported outside CareerFlow are not scrubbed automatically.")) return;
    await api(`/api/resumes/${button.dataset.deleteResume}`, { method: "DELETE" });
    if (viewCheck()) { toast("Resume version deleted"); await refresh(); }
  }, null, view));
}

function bindResumePreview(panel, viewCheck) {
  document.querySelectorAll("[data-preview-resume]").forEach(button => button.onclick = () => runAction(button, async () => {
    const resume = await api(`/api/resumes/${button.dataset.previewResume}`);
    if (!viewCheck()) return;
    panel.querySelector("#resume-preview").innerHTML = `<hr><h4>${escapeHtml(resumePreviewTitle(resume))}</h4><div class="markdown-preview">${renderSafeMarkdown(resume.content_text)}</div>`;
  }));
}

function fillResumeDraft(panel, resume, label) {
  const resumeForm = panel.querySelector("#resume-form");
  const textArea = resumeForm.querySelector("textarea[name=text]");
  textArea.value = resume.content_text;
  resumeForm.querySelector("input[name=file]").value = "";
  resumeForm.querySelector("input[name=label]").value = label;
  resumeForm.querySelector("input[name=source_resume_id]").value = resume.id;
  textArea.focus();
}

async function renderMasterResume() {
  setSection("master-resume");
  state.selected = null;
  state.activeTab = "Master Resume";
  state.selectionEpoch++;
  const epoch = ++state.viewEpoch;
  workspace.innerHTML = `<p class="muted">Loading Master Resume versions…</p>`;
  try {
    const masters = await api("/api/resumes?kind=master");
    if (!isCurrentMasterView(epoch)) return;
    workspace.innerHTML = `<div class="standalone-head"><div><p class="eyebrow">GLOBAL IMMUTABLE LIBRARY</p><h2>Master Resume</h2><p class="muted">Create a new version whenever your canonical resume changes.</p></div></div>
      <section class="panel master-panel"><div class="section-head master-list-head"><h3>Resume list</h3><button class="primary" type="button" id="open-master-resume-dialog">Add resume</button></div><div class="item-list">${masters.length ? masters.map(item => resumeItem(item, { masterWorkspace: true })).join("") : `<div class="empty-inline"><h3>Create a Master Resume version</h3><p>Upload PDF, DOCX, TXT, or MD, or paste Markdown. Existing history is retained when prior versions are deleted.</p></div>`}</div>
      <div id="resume-preview" aria-live="polite"></div></section>
      <dialog id="master-resume-dialog" aria-labelledby="master-resume-dialog-title"><form id="resume-form" class="stack"><div class="dialog-head"><div><p class="eyebrow">MASTER RESUME</p><h2 id="master-resume-dialog-title">${masters.length ? "Create a new version" : "Create a version"}</h2></div><button type="button" class="icon-button" data-close-master-resume aria-label="Close">×</button></div><input type="hidden" name="source_resume_id"><label>Resume name<input name="label" placeholder="e.g. Product Manager CV"></label><label>Resume file (PDF, DOCX, TXT, MD)<input name="file" type="file" accept=".pdf,.docx,.txt,.md"></label><label>Or edit Markdown<textarea name="text" rows="14"></textarea></label><p class="error" id="resume-error"></p><div class="dialog-actions"><button class="secondary" type="button" data-close-master-resume>Cancel</button><button class="primary" type="submit">Save Master Resume version</button></div></form></dialog>`;
    const panel = workspace.querySelector?.(".master-panel") || workspace;
    const resumeDialog = workspace.querySelector("#master-resume-dialog");
    const resumeForm = workspace.querySelector("#resume-form");
    const isCurrent = () => isCurrentMasterView(epoch);
    bindResumePreview(panel, isCurrent);
    bindResumeDelete(panel, renderMasterResume, isCurrent);
    const openResumeDialog = () => {
      resumeDialog.showModal();
    };
    workspace.querySelector("#open-master-resume-dialog").onclick = () => {
      resumeForm.reset();
      resumeForm.querySelector("input[name=source_resume_id]").value = "";
      openResumeDialog();
    };
    workspace.querySelectorAll?.("[data-close-master-resume]").forEach(button => button.onclick = () => resumeDialog.close());
    document.querySelectorAll("[data-use-resume]").forEach(button => button.onclick = () => runAction(button, async () => {
      const resume = await api(`/api/resumes/${button.dataset.useResume}`);
      if (!isCurrent()) return;
      fillResumeDraft(workspace, resume, `Based on Master Resume v${resume.version}`);
      resumeForm.querySelector("input[name=source_resume_id]").value = String(resume.id ?? button.dataset.useResume);
      openResumeDialog();
      toast("Master Resume copied into an editable new-version draft.");
    }));
    resumeForm.onsubmit = async event => {
      event.preventDefault();
      const submittedForm = event.currentTarget;
      await runAction(submittedForm.querySelector("button[type=submit]"), async () => {
        const formData = new FormData(submittedForm);
        formData.append("kind", "master");
        if (!formData.get("source_resume_id")) formData.delete?.("source_resume_id");
        await api("/api/resumes", { method: "POST", body: formData });
        if (isCurrent()) { toast("Master Resume version created"); await renderMasterResume(); }
      }, workspace.querySelector("#resume-error"));
    };
  } catch (error) {
    if (isCurrentMasterView(epoch)) workspace.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
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
    panel.innerHTML = `<div class="section-head"><div><p class="eyebrow">VACANCY-SPECIFIC HISTORY</p><h3>Resume versions for this vacancy</h3></div></div>
      <div class="item-list">${versions.length ? versions.map(item => resumeItem(item)).join("") : `<p class="muted">No vacancy-specific versions yet.</p>`}</div><div id="resume-preview" aria-live="polite"></div><hr>
      <div class="source-picker"><h4>Create from Master Resume</h4>${masters.length ? `<div class="inline-form"><select id="master-source">${masters.map(item => `<option value="${item.id}">Master Resume v${item.version} — ${escapeHtml(item.label || "Untitled")}</option>`).join("")}</select><button class="secondary" type="button" id="create-from-master">Copy into draft</button></div>` : `<p class="muted">No Master Resume exists yet. <button class="text-button" type="button" data-go-master>Create one in the Master Resume section.</button></p>`}</div>
      <hr><h4>Add a vacancy-specific version</h4><form id="resume-form" class="stack"><input type="hidden" name="source_resume_id"><label>Version name<input name="label" placeholder="e.g. Backend-focused"></label><label>Resume file (PDF, DOCX, TXT, MD)<input name="file" type="file" accept=".pdf,.docx,.txt,.md"></label><label>Or edit Markdown<textarea name="text" rows="12"></textarea></label><p class="error" id="resume-error"></p><button class="primary" type="submit">Save vacancy resume version</button></form>`;
    const isCurrent = () => isCurrentView(view);
    bindResumePreview(panel, isCurrent);
    bindResumeDelete(panel, () => renderResumes(vacancy, view), isCurrent, view);
    document.querySelectorAll("[data-use-resume]").forEach(button => button.onclick = () => runAction(button, async () => {
      const resume = await api(`/api/resumes/${button.dataset.useResume}`);
      if (!isCurrent()) return;
      fillResumeDraft(panel, resume, `Based on Vacancy Resume v${resume.version}`);
      toast("Stored Markdown copied into the new-version draft.");
    }, null, view));
    const createFromMaster = panel.querySelector("#create-from-master");
    if (createFromMaster) createFromMaster.onclick = () => runAction(createFromMaster, async () => {
      const resume = await api(`/api/resumes/${panel.querySelector("#master-source").value}`);
      if (!isCurrent()) return;
      fillResumeDraft(panel, resume, `Based on Master Resume v${resume.version}`);
      toast("Master Resume copied into an editable draft. No AI generation was run.");
    }, null, view);
    const goMaster = panel.querySelector("[data-go-master]");
    if (goMaster) goMaster.onclick = () => renderMasterResume();
    panel.querySelector("#resume-form").onsubmit = async event => {
      event.preventDefault();
      const resumeForm = event.currentTarget;
      await runAction(resumeForm.querySelector("button[type=submit]"), async () => {
        const formData = new FormData(resumeForm);
        formData.append("kind", "vacancy");
        formData.append("vacancy_id", vacancy.id);
        if (!formData.get("source_resume_id")) formData.delete?.("source_resume_id");
        await api("/api/resumes", { method: "POST", body: formData });
        if (isCurrent()) { toast("Vacancy resume version created"); await renderResumes(vacancy, view); }
      }, panel.querySelector("#resume-error"), view);
    };
    const pendingDraft = state.pendingResumeDraft;
    if (pendingDraft?.vacancyId === vacancy.id) {
      fillResumeDraft(panel, {
        id: pendingDraft.sourceResumeId,
        content_text: pendingDraft.contentText,
      }, "AI tailored resume draft");
      state.pendingResumeDraft = null;
      toast("Tailored resume copied into an editable draft. Review it before saving a new version.");
    }
    document.querySelectorAll("[data-submit-resume]").forEach(button => button.onclick = () => runAction(button, async () => {
      await api(`/api/resumes/${button.dataset.submitResume}/submit`, { method: "POST" });
      if (isCurrent()) { toast("Submitted version recorded"); await renderResumes(vacancy, view); }
    }, null, view));
  } catch (error) { if (isCurrentView(view)) panel.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; }
}

function atsResult(analysis, vacancy = null) {
  if (!analysis) return "";
  const result = analysis.result;
  const resumeLabel = analysis.resume_kind_at_analysis && analysis.resume_version_at_analysis
    ? `${analysis.resume_kind_at_analysis === "master" ? "Master" : "Vacancy"} Resume v${analysis.resume_version_at_analysis}`
    : "legacy resume version";
  return `<div class="score-row"><div class="score" aria-label="ATS text-match score ${analysis.match_percent}%">${analysis.match_percent}%</div><div><h3>${analysis.is_stale ? "Historical ATS text match — rerun analysis" : "ATS text-match score"}</h3><p class="muted">Analysis #${analysis.id} · ${escapeHtml(resumeLabel)} (ID ${analysis.resume_version_id})</p>${vacancy?.ai_match_percent != null ? `<p class="score-inline"><strong>AI ${vacancy.ai_match_percent}%</strong> <span class="muted">AI resume-to-vacancy score</span></p>` : ""}<p class="muted">Heuristic comparison of vacancy wording with resume text. It is not a probability of getting the job or a definitive assessment of suitability.</p><p class="muted">${escapeHtml(result.disclaimer)}</p>${analysis.is_stale ? `<p class="error">${analysis.resume_deleted ? "The resume version used for this analysis was deleted. This result remains historical; create or select a current resume and run ATS again." : "The confirmed vacancy description changed after this run. This result is historical; run ATS again for a current score."}</p>` : ""}</div></div>
    <div class="metric-grid"><div><strong>${result.counts.covered}</strong><span>Covered</span></div><div><strong>${result.counts.partial}</strong><span>Partial</span></div><div><strong>${result.counts.missing}</strong><span>Missing</span></div></div>
    <h4>Requirements and evidence</h4><div class="item-list">${result.requirements.map(item => `<article class="requirement ${item.classification}"><span class="badge">${item.classification}</span><strong>${escapeHtml(item.requirement)}</strong><p>${escapeHtml(item.interpretation)}</p>${item.evidence ? `<blockquote>${escapeHtml(item.evidence)}</blockquote>` : ""}</article>`).join("")}</div>
    <h4>Keywords</h4><div class="tag-list">${result.keywords.map(word => `<span class="tag ${result.covered_keywords.includes(word) ? "hit" : ""}">${escapeHtml(word)}</span>`).join("")}</div>`;
}

async function renderAts(vacancy, view = null) {
  const panel = document.querySelector("#content-panel");
  panel.innerHTML = `<p class="muted">Loading ATS workspace…</p>`;
  try {
    const [versions, latest] = await Promise.all([
      api(`/api/resumes?kind=vacancy&vacancy_id=${vacancy.id}`),
      api(`/api/vacancies/${vacancy.id}/ats`),
    ]);
    if (!isCurrentView(view)) return;
    let emptyState = "";
    if (!vacancy.description_confirmed_at) {
      emptyState = `<div class="empty-inline"><h3>Review the cleaned vacancy description before running ATS.</h3><button type="button" class="secondary" data-review-description>Review description</button></div>`;
    } else if (!versions.length) {
      emptyState = `<div class="empty-inline"><h3>ATS analysis requires a resume.</h3><p>Create a resume for this vacancy or use a Master Resume version.</p><div class="actions centered"><button type="button" class="secondary" data-open-resume>Create from Master Resume</button><button type="button" class="primary" data-open-resume>Add resume</button></div></div>`;
    } else if (!latest) {
      emptyState = `<div class="empty-inline"><h3>Select a resume version and run ATS analysis.</h3><p>ATS is a local text comparison, not an employer decision and not a Codex analysis.</p></div>`;
    }
    panel.innerHTML = `<div class="section-head ats-head"><div><p class="eyebrow">EVIDENCE-BASED LOCAL COMPARISON</p><h3>ATS analysis</h3></div>${versions.length ? `<div class="actions"><select id="ats-resume">${versions.map(item => `<option value="${item.id}" ${latest && item.id === latest.resume_version_id ? "selected" : ""}>Vacancy Resume v${item.version} — ${escapeHtml(item.label || "Untitled")}</option>`).join("")}</select><button id="run-ats" class="primary" ${vacancy.description_confirmed_at ? "" : "disabled"}>${latest?.is_stale ? "Run again" : "Run analysis"}</button></div>` : ""}</div><p class="error" id="ats-error"></p>${emptyState}<div id="ats-result">${atsResult(latest, vacancy)}</div>`;
    document.querySelectorAll("[data-open-resume]").forEach(button => button.onclick = () => openTab("Resume", vacancy));
    const reviewButton = document.querySelector("[data-review-description]");
    if (reviewButton) reviewButton.onclick = () => openTab("Overview", vacancy);
    const runButton = document.querySelector("#run-ats");
    if (runButton) runButton.onclick = async () => {
      const button = document.querySelector("#run-ats");
      const errorTarget = document.querySelector("#ats-error");
      errorTarget.textContent = "";
      await runAction(button, async () => {
        const resumeId = Number(document.querySelector("#ats-resume").value);
        const analysis = await api(`/api/vacancies/${vacancy.id}/ats`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resume_version_id: resumeId }) });
        await loadVacancies();
        if (isCurrentView(view)) { document.querySelector("#ats-result").innerHTML = atsResult(analysis); toast("ATS analysis completed"); }
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
    loadInterviews(vacancy.id),
  ]);
  if (!isCurrentView(view)) return;
  panel.innerHTML = `<div class="section-head"><div><p class="eyebrow">EVENT LOG</p><h3>Timeline</h3></div></div>
    <div class="split-grid"><section><div class="timeline">${events.map(event => `<article><span></span><div><strong>${escapeHtml(event.title)}</strong><time>${new Date(event.event_at + (event.event_at.includes("T") ? "" : "Z")).toLocaleString()}</time>${event.details ? `<p>${escapeHtml(event.details)}</p>` : ""}</div></article>`).join("")}</div></section>
    <section><h4>Add interview #${interviews.length + 1}</h4><form id="interview-form" class="stack"><label>Date and time<input name="interview_at" type="datetime-local" required></label><label>Type<input name="interview_type" value="Interview" placeholder="HR, Technical, Hiring manager…"></label><label>Notes<textarea name="note" rows="4"></textarea></label><label>Result<input name="result" placeholder="Scheduled, passed, follow-up…"></label><p class="error" id="interview-error"></p><button class="primary" type="submit">Add interview</button></form></section></div>`;
  document.querySelector("#interview-form").onsubmit = async event => {
    event.preventDefault();
    const interviewForm = event.currentTarget;
    const errorTarget = panel.querySelector("#interview-error");
    errorTarget.textContent = "";
    await runAction(interviewForm.querySelector("button[type=submit]"), async () => {
      const payload = Object.fromEntries(new FormData(interviewForm));
      await api(`/api/vacancies/${vacancy.id}/interviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const countEpoch = invalidateInterviewCount(vacancy.id);
      updateInterviewCount(vacancy.id, interviews.length + 1, countEpoch);
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
    <form id="note-form" class="stack"><label>New note<textarea name="body" rows="4" placeholder="Interview preparation, company research, impressions…" required></textarea></label><p class="error" id="note-error"></p><button class="primary" type="submit">Add note</button></form><hr>
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
    <form id="attachment-form" class="inline-form"><input name="file" type="file" required><button class="primary" type="submit">Attach file</button></form><p class="error" id="attachment-error"></p><p class="muted file-hint">Up to 100 MB. Audio is stored as-is; automatic transcription is outside the MVP.</p><hr>
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
  return `<article class="item-row ai-history-row"><div><strong class="ai-history-title">${escapeHtml(run.action || shortAiPrompt(run.prompt))}</strong><p class="muted">${new Date(run.created_at + "Z").toLocaleString()} · ${escapeHtml(run.model || "Legacy model unknown")} · ${escapeHtml(run.reasoning_effort || "effort unknown")} · ${escapeHtml(responseLanguageLabel(run.response_language))}</p></div><div class="actions"><span class="badge ${run.status === "completed" ? "success" : ""}">${escapeHtml(run.status)}</span><button class="secondary" type="button" data-open-ai-run="${run.id}" data-vacancy-id="${run.vacancy_id || ""}" aria-expanded="false" aria-controls="ai-inline-${run.id}" aria-label="View saved response ${run.id}">View response</button></div><div id="ai-inline-${run.id}" class="ai-inline-result" hidden></div></article>`;
}

function responseLanguageLabel(value) {
  const label = value === "russian" ? "Russian" : value === "english" ? "English" : "Auto";
  return state.locale === "ru" ? RU[label] : label;
}

async function openSavedAiRun(button, vacancy, view, panel) {
  const row = button.closest?.(".ai-history-row");
  const inline = row?.querySelector(".ai-inline-result");
  if (inline?.dataset.loaded === "true") {
    inline.hidden = !inline.hidden;
    button.setAttribute("aria-expanded", String(!inline.hidden));
    button.textContent = inline.hidden ? "View response" : "Hide response";
    return;
  }
  await runAction(button, async () => {
    const run = await api(`/api/vacancies/${vacancy.id}/ai-runs/${button.dataset.openAiRun}`);
    if (!isCurrentView(view)) return;
    const result = aiResponseBlock(run, `Saved ${run.status === "completed" ? "response" : "error"}`);
    if (inline) { inline.innerHTML = result; inline.dataset.loaded = "true"; inline.hidden = false; button.setAttribute("aria-expanded", "true"); }
  }, null, view);
  if (inline?.dataset.loaded === "true") { button.setAttribute("aria-expanded", String(!inline.hidden)); button.textContent = inline.hidden ? "View response" : "Hide response"; }
}

function shortAiPrompt(prompt) {
  const value = String(prompt || "").trim();
  if (/^compare the selected resume/i.test(value)) return "Match resume to vacancy";
  if (/^review the heuristic ats/i.test(value)) return "Review ATS analysis";
  if (/^suggest truthful improvements/i.test(value)) return "Improve resume";
  if (/^analyze the role/i.test(value)) return "Analyze vacancy";
  if (/^prepare a focused interview/i.test(value)) return "Prepare for interview";
  if (/^analyze the interview notes/i.test(value)) return "Analyze interview notes";
  return value.length > 92 ? `${value.slice(0, 89)}…` : value;
}

function formatAiMatchResponse(response) {
  let payload;
  try { payload = JSON.parse(response); } catch { return `<pre class="ai-response">${escapeHtml(response)}</pre>`; }
  if (!payload || typeof payload !== "object") return `<pre class="ai-response">${escapeHtml(response)}</pre>`;
  const list = (value) => Array.isArray(value) && value.length ? `<ul>${value.map(item => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>` : `<p class="muted">—</p>`;
  return `<div class="ai-readable"><div class="ai-readable-score"><strong>${escapeHtml(String(payload.match_percent ?? "—"))}%</strong><span>AI resume-to-vacancy score</span></div><h4>Summary</h4><p>${escapeHtml(String(payload.summary || "—"))}</p><div class="ai-readable-columns"><div><h4>Strengths</h4>${list(payload.strengths)}</div><div><h4>Gaps</h4>${list(payload.gaps)}</div></div></div>`;
}

function renderAiMarkdown(response) {
  const lines = String(response || "").split(/\r?\n/);
  const html = [];
  let list = [];
  const flushList = () => { if (list.length) { html.push(`<ul>${list.join("")}</ul>`); list = []; } };
  const inline = value => escapeHtml(value).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) { flushList(); continue; }
    const heading = trimmed.match(/^#{1,4}\s+(.+)$/);
    if (heading) { flushList(); html.push(`<h4>${inline(heading[1])}</h4>`); continue; }
    const bullet = trimmed.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
    if (bullet) { list.push(`<li>${inline(bullet[1])}</li>`); continue; }
    flushList(); html.push(`<p>${inline(trimmed)}</p>`);
  }
  flushList();
  return `<div class="ai-readable markdown-readable">${html.join("")}</div>`;
}

function isMatchPrompt(prompt) { return /^compare the selected resume/i.test(String(prompt || "")); }

function formatAiResponse(response, prompt = "") {
  if (isMatchPrompt(prompt)) {
    try { const parsed = JSON.parse(response); if (parsed && typeof parsed === "object") return formatAiMatchResponse(response); } catch (_) { /* Fall through to readable text. */ }
  }
  return renderAiMarkdown(response);
}

function aiResponseBlock(run, title = "Saved response") {
  const response = run.status === "completed" ? run.response : run.error;
  const draftAction = run.status === "completed" && run.action === "Create tailored resume"
    ? `<div class="actions"><button class="primary" type="button" data-create-ai-draft="${run.id}">Create editable resume draft</button></div>`
    : "";
  return `<h4>${title} · ${escapeHtml(run.model || "Legacy model unknown")} · ${escapeHtml(run.reasoning_effort || "effort unknown")} · ${escapeHtml(responseLanguageLabel(run.response_language))}</h4><p class="muted">${escapeHtml(run.prompt || "")}</p>${run.status === "completed" ? formatAiResponse(response, run.prompt) : `<p class="error">${escapeHtml(response || "Codex request failed")}</p>`}${draftAction}`;
}

async function renderAi(vacancy, view = null) {
  const panel = document.querySelector("#content-panel");
  const [history, catalog] = await Promise.all([
    api(`/api/vacancies/${vacancy.id}/ai-runs`),
    api("/api/codex/models"),
  ]);
  if (!isCurrentView(view)) return;
  const actions = {
    "Analyze vacancy": "Analyze the role, prioritize its requirements, and identify questions I should clarify.",
    "Improve resume": "Suggest truthful improvements to the selected resume using only evidence already present in the context.",
    "Review ATS analysis": "Review the heuristic ATS analysis, point out false positives or weak evidence, and suggest truthful wording improvements.",
    "Match resume to vacancy": "Compare the selected resume with the vacancy requirements and return JSON with an integer match_percent from 0 to 100, a short summary, strengths, and gaps. Ignore navigation, company marketing, salary, and generic wording.",
    "Create tailored resume": "Create a complete vacancy-tailored Markdown resume using the source resume, vacancy fields and full description, and the latest available vacancy analysis, AI match, and resume improvements. Use only candidate facts present in the source resume. Analyze the role and match the source resume directly if saved analyses are missing. Use ATS only as an optional lexical hint; verify it against the source texts. Prioritize relevant experience and supported keywords. Do not invent claims, metrics, skills, dates, or experience.",
    "Prepare for interview": "Create a focused interview preparation plan with likely questions and evidence-backed talking points.",
    "Analyze interview notes": "Analyze the interview notes, extract follow-ups, risks, and suggested next actions.",
    "Custom request": "",
  };
  const prompts = actions;
  panel.innerHTML = `<div class="section-head"><div><p class="eyebrow">READ-ONLY CLI ASSISTANT</p><h3>AI / Codex</h3></div></div>
    <p class="callout">CareerFlow sends the generated vacancy Markdown context to <code>codex exec</code> in a read-only, ephemeral session. The response is shown here and never changes your CV or vacancy automatically.</p>
    <form id="ai-form" class="stack"><div class="form-grid ai-controls"><label>Action<select name="action" id="ai-action">${Object.keys(actions).map(action => `<option value="${escapeAttr(action)}">${action}</option>`).join("")}</select></label><label>Model<select name="model" id="ai-model">${catalog.models.map(model => `<option value="${escapeAttr(model.id)}" ${model.id === catalog.default_model ? "selected" : ""}>${escapeHtml(model.name)} (${escapeHtml(model.id)})</option>`).join("")}</select></label><label>Reasoning effort<select name="reasoning_effort" id="ai-effort"></select></label><label>Response language<select name="response_language" id="ai-response-language"><option value="auto" selected>Auto</option><option value="russian">Russian</option><option value="english">English</option></select></label></div>${catalog.source !== "codex-cli" ? `<p class="callout">${escapeHtml(catalog.warning || "Codex CLI catalog unavailable; using configured fallback.")}</p>` : ""}<label>Request<textarea name="prompt" id="ai-prompt" rows="6" required>${escapeHtml(prompts["Analyze vacancy"])}</textarea></label><p class="muted">Model and effort are validated against the local Codex CLI catalog.</p><p class="error" id="ai-error"></p><button class="primary" type="submit">Run Codex</button></form>
    <div id="ai-result" aria-live="polite"></div><hr><div class="section-head ai-history-head"><h4>Saved responses</h4><input id="ai-history-filter" type="search" placeholder="Filter saved responses…" aria-label="Filter saved responses"></div><div id="ai-history-list" class="item-list">${history.length ? history.map(aiHistoryItem).join("") : `<p class="muted">No saved responses yet.</p>`}</div>`;
  document.querySelector("#ai-action").onchange = event => {
    document.querySelector("#ai-prompt").value = prompts[event.target.value] || "";
    if (event.target.value === "Create tailored resume") {
      const preferredModel = catalog.models.find(model => model.id === "gpt-5.6-sol" && model.efforts.includes("medium"));
      if (preferredModel) {
        modelSelect.value = preferredModel.id;
        updateEfforts("medium");
      }
    }
  };
  const modelSelect = panel.querySelector("#ai-model");
  const effortSelect = panel.querySelector("#ai-effort");
  const updateEfforts = preferred => {
    const selected = catalog.models.find(model => model.id === modelSelect.value) || catalog.models[0];
    effortSelect.innerHTML = selected.efforts.map(effort => `<option value="${escapeAttr(effort)}">${escapeHtml(effort)}</option>`).join("");
    effortSelect.value = selected.efforts.includes(preferred) ? preferred : selected.id === catalog.default_model && selected.efforts.includes(catalog.default_effort) ? catalog.default_effort : selected.efforts[0];
  };
  updateEfforts(catalog.default_effort);
  modelSelect.onchange = () => updateEfforts("");
  panel.querySelector("#ai-history-filter").oninput = event => {
    const query = event.target.value.trim().toLowerCase();
    panel.querySelectorAll(".ai-history-row").forEach(row => { row.hidden = query !== "" && !row.textContent.toLowerCase().includes(query); });
  };
  document.querySelectorAll("[data-open-ai-run]").forEach(button => button.onclick = () => openSavedAiRun(button, vacancy, view, panel));
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
          panel.querySelector("#ai-result").innerHTML = `<p class="success-message">Codex response saved below. Open it when you are ready to review.</p>`;
          const historyList = panel.querySelector("#ai-history-list");
          if (historyList) {
            historyList.querySelector(".muted")?.remove();
            historyList.insertAdjacentHTML("afterbegin", aiHistoryItem({ ...run, action: run.action || payload.action, prompt: payload.prompt, model: run.model || payload.model, reasoning_effort: run.reasoning_effort || payload.reasoning_effort, response_language: run.response_language || payload.response_language }));
            const savedButton = historyList.querySelector(`[data-open-ai-run="${run.id}"]`);
            if (savedButton) savedButton.onclick = () => openSavedAiRun(savedButton, vacancy, view, panel);
          }
          if (run.ai_match_percent != null) { await loadVacancies(); state.selected = state.vacancies.find(item => item.id === vacancy.id) || state.selected; toast("AI match score updated"); }
          toast("Codex response received");
        }
      }
    }, errorEl, view);
  };
}

function importSignature(data, useCodex) {
  const file = data.get("file");
  return JSON.stringify({
    text: data.get("text") || "",
    file: file?.name ? { name: file.name, size: file.size ?? null, type: file.type || "", lastModified: file.lastModified ?? null } : null,
    title: data.get("title") || "",
    company: data.get("company") || "",
    salary: data.get("salary") || "",
    source: data.get("source") || "",
    url: data.get("url") || "",
    useCodex,
  });
}

function resetImportReview() {
  state.importPreview = null;
  delete form.dataset.urlImportToken;
  const review = document.querySelector("#import-review");
  if (review) review.innerHTML = "";
  const submit = form.querySelector("button[type=submit]");
  submit.hidden = false;
  submit.disabled = false;
  submit.textContent = "Review description";
}

function openDialog() { resetImportReview(); dialog.showModal(); }
function closeDialog() { dialog.close(); form.reset(); resetImportReview(); selectedFile.textContent = ""; document.querySelector("#import-error").textContent = ""; }

document.addEventListener("click", async event => {
  if (event.target.closest("[data-close-analytics-help]")) { analyticsHelp?.close(); return; }
  if (state.sidebarOpen && !event.target.closest("#vacancy-sidebar") && !event.target.closest("#sidebar-toggle")) {
    setSidebarOpen(false);
  }
  if (event.target.closest("#sidebar-toggle")) {
    setSidebarOpen(!state.sidebarOpen);
    return;
  }
  const sectionButton = event.target.closest("[data-section]");
  if (sectionButton) {
    if (sectionButton.dataset.section === "master-resume") await renderMasterResume();
    else if (sectionButton.dataset.section === "analytics") await renderAnalytics();
    else await showVacancies();
    return;
  }
  if (event.target.closest("[data-open-import]")) openDialog();
  if (event.target.closest("[data-close-dialog]")) closeDialog();
  const draftButton = event.target.closest("[data-create-ai-draft]");
  if (draftButton) {
    const vacancy = state.selected;
    if (!vacancy || state.activeTab !== "AI / Codex") return;
    await runAction(draftButton, async () => {
      const run = await api(`/api/vacancies/${vacancy.id}/ai-runs/${draftButton.dataset.createAiDraft}`);
      if (run.status !== "completed" || run.action !== "Create tailored resume" || !run.source_resume_id) {
        throw new Error("This saved response cannot be used as a tailored resume draft.");
      }
      state.pendingResumeDraft = {
        vacancyId: vacancy.id,
        sourceResumeId: run.source_resume_id,
        contentText: run.response,
      };
      await openTab("Resume", vacancy);
    });
    return;
  }
  const savedAiButton = event.target.closest("[data-open-ai-run]");
  if (savedAiButton && typeof savedAiButton.onclick !== "function") {
    const vacancy = state.selected;
    const panel = document.querySelector("#content-panel");
    if (vacancy && panel && state.activeTab === "AI / Codex") {
      openSavedAiRun(savedAiButton, vacancy, currentView(vacancy, "AI / Codex", panel), panel);
      return;
    }
  }
  const card = event.target.closest(".vacancy-card");
  if (card) {
    setSidebarOpen(false);
    const selectionEpoch = ++state.selectionEpoch;
    try {
      const vacancy = await api(`/api/vacancies/${card.dataset.id}`);
      if (selectionEpoch === state.selectionEpoch) {
        renderVacancy(vacancy);
      }
    } catch (error) { if (selectionEpoch === state.selectionEpoch) showError(error); }
  }
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && state.sidebarOpen) {
    setSidebarOpen(false);
    sidebarToggle?.focus?.();
  }
});
newVacancyButton.onclick = openDialog;
archivedToggle.onchange = async () => {
  renderEmpty({ preserveSidebar: true });
  try { await loadVacancies(); } catch (error) { showError(error); }
};
fileInput.onchange = () => { selectedFile.textContent = fileInput.files[0]?.name || ""; };
form?.querySelector?.('input[name="url"]')?.addEventListener("input", event => {
  const submit = form.querySelector("button[type=submit]");
  if (!state.importPreview) submit.textContent = event.target.value.trim() ? "Parse vacancy" : "Review description";
});
for (const eventName of ["dragenter", "dragover"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.add("dragging"); });
for (const eventName of ["dragleave", "drop"]) dropZone.addEventListener(eventName, event => { event.preventDefault(); dropZone.classList.remove("dragging"); });
dropZone.addEventListener("drop", event => { fileInput.files = event.dataTransfer.files; selectedFile.textContent = fileInput.files[0]?.name || ""; });
form.onsubmit = async event => {
  event.preventDefault();
  const error = document.querySelector("#import-error");
  const review = document.querySelector("#import-review");
  error.textContent = "";
  const submit = form.querySelector("button[type=submit]");
  if (submit.disabled) return;
  if (state.importPreview) return;
  submit.disabled = true;
  try {
    if (!state.importPreview) {
      submit.textContent = "Preparing preview…";
      const useCodex = form.querySelector('input[name="use_codex"]')?.checked || false;
      const previewData = new FormData(form);
      if (useCodex) previewData.set("use_codex", "true");
      else previewData.delete?.("use_codex");
      if (useCodex) previewData.set("codex_profile", "primary");
      else previewData.delete?.("codex_profile");
      const initialPreview = await api("/api/vacancies/import-preview", { method: "POST", body: previewData });
      const preview = useCodex
        ? await retryWithCodexEscalation(initialPreview, profile => {
          previewData.set("codex_profile", profile);
          return api("/api/vacancies/import-preview", { method: "POST", body: previewData });
        })
        : initialPreview;
      const snapshot = { preview, input: importSignature(previewData, useCodex) };
      state.importPreview = snapshot;
      if (preview.url_import_token) form.dataset.urlImportToken = preview.url_import_token;
      review.innerHTML = renderCleaningReview(preview, "import-review-error");
      submit.hidden = true;
      const confirm = review.querySelector("[data-confirm-cleaning]");
      confirm.onclick = async () => {
        if (confirm.disabled) return;
        confirm.disabled = true;
        const confirmError = review.querySelector("#import-review-error");
        confirmError.textContent = "";
        try {
          const currentInput = new FormData(form);
          const currentUseCodex = form.querySelector('input[name="use_codex"]')?.checked || false;
          const currentSignature = importSignature(currentInput, currentUseCodex);
          if (currentSignature !== snapshot.input) throw new Error("Import details changed after preview. Go back and review the updated description.");
          const data = currentInput;
          data.delete?.("use_codex");
          data.delete?.("codex_profile");
          data.set("cleaned_description", review.querySelector("[data-cleaned-description]").value);
          data.set("cleaning_method", preview.method);
          if (preview.url_import_token) data.set("url_import_token", preview.url_import_token);
          const vacancy = await api("/api/vacancies", { method: "POST", body: data });
          closeDialog(); await loadVacancies(); renderVacancy(vacancy); toast("Vacancy imported");
        } catch (exception) { confirmError.textContent = exception.message; }
        finally { confirm.disabled = false; }
      };
      review.querySelector("[data-cancel-cleaning]").onclick = resetImportReview;
    }
  } catch (exception) { error.textContent = exception.message; }
  finally { submit.disabled = false; if (!state.importPreview) submit.textContent = "Review description"; }
};

if (document.documentElement) document.documentElement.lang = state.locale;
setTheme(state.theme);
if (state.locale === "ru") {
  setLocale("ru");
  applyLocale();
}
setSection("vacancies");
document.querySelector('[data-section="analytics"]')?.addEventListener("click", () => { renderAnalytics().catch(error => showError(error)); });
loadVacancies().catch(error => { workspace.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`; });
