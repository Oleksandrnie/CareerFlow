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
    querySelector: selector => element(selector),
    querySelectorAll: () => [],
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
    disclaimer: "Heuristic text comparison only. Missing means not evidenced in this resume version, not that the candidate lacks the experience.",
    counts: { covered: 1, partial: 0, missing: 0 },
    requirements: [{ classification: "partial", requirement: "REST APIs", interpretation: "Evidence found in this resume version", evidence: "REST APIs" }],
    keywords: [],
    covered_keywords: [],
  },
};
const responses = {
  "/api/vacancies?archived=undefined": [],
  "/api/resumes?kind=vacancy&vacancy_id=1": [{ id: 43, kind: "vacancy", version: 1, label: "Latest" }],
  "/api/resumes?kind=master": [],
  "/api/vacancies/1/ats": analysis,
  "/api/ats/assessments?resume_version_id=43": [],
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
context.analysis = analysis;
vm.runInContext(source, context);

(async () => {
  await vm.runInContext("renderAts({id: 1, description_confirmed_at: '2026-09-26'})", context);
  const html = element("#content-panel").innerHTML;
  assert.match(html, /value="43"[^>]*selected/);
  assert.match(html, /Historical ATS text match — rerun analysis/);
  assert.match(html, /Vacancy Resume v1 \(ID 43\)/);
  assert.match(html, /This result is historical/);
  assert.match(html, /not a probability of getting the job or a definitive assessment of suitability/);
  assert.match(html, /data-run-assessment="manager_audit"/);
  assert.match(html, /data-run-assessment="vacancy_match"/);
  const invalidManagerAudit = {
    assessment_kind: "manager_audit",
    result: { response_format_error: "Manager audit must use the six named manager risk checks." },
  };
  context.invalidManagerAudit = invalidManagerAudit;
  assert.match(vm.runInContext('state.locale = "en"; renderAssessmentResult(invalidManagerAudit)', context),
    /invalid format for the resume audit.*running the audit again/);
  assert.match(vm.runInContext('state.locale = "ru"; renderAssessmentResult(invalidManagerAudit)', context),
    /результат аудита в неверном формате.*запустить аудит ещё раз/);
  const historicalEnglishAssessment = {
    assessment_kind: "vacancy_match",
    locale: "ru",
    result: {
      overall_summary: "Strong overall fit based on the available evidence.",
      requirements: [{
        requirement: "English source requirement",
        status: "covered",
        vacancy_quote: "Exact English quote from the vacancy.",
        explanation: "The resume directly demonstrates this requirement.",
        resume_line_refs: ["L2"],
      }],
      strengths: [], gaps: [],
    },
  };
  context.historicalEnglishAssessment = historicalEnglishAssessment;
  const historicalHtml = vm.runInContext('state.locale = "ru"; renderAssessmentResult(historicalEnglishAssessment)', context);
  assert.match(historicalHtml, /Strong overall fit[\s\S]*?Это пояснение на английском языке/);
  assert.match(historicalHtml, /<strong>English source requirement<\/strong>/);
  assert.match(historicalHtml, /<blockquote>Exact English quote from the vacancy\.<\/blockquote>/);
  assert.match(historicalHtml, /Показать оригинальный текст/);
  assert.match(historicalHtml, /Пробелы/);
  const currentLocaleEnglishProse = {
    ...historicalEnglishAssessment,
    locale: "en",
  };
  context.currentLocaleEnglishProse = currentLocaleEnglishProse;
  const currentLocaleHtml = vm.runInContext('state.locale = "ru"; renderAssessmentResult(currentLocaleEnglishProse)', context);
  assert.match(currentLocaleHtml, /Это пояснение на английском языке\./, "the active UI locale controls the English explanation disclosure");
  assert.doesNotMatch(currentLocaleHtml, /<p>\s*<div class="assessment-prose"/, "assessment prose must not put a block disclosure inside a paragraph");
  const proseNode = { dataset: { assessmentOriginal: "English saved explanation." }, innerHTML: "" };
  context.proseRoot = { querySelectorAll: () => [proseNode] };
  vm.runInContext('state.locale = "ru"; refreshAssessmentProse(proseRoot)', context);
  assert.match(proseNode.innerHTML, /<details class="original-assessment-text">/);
  vm.runInContext('state.locale = "en"; refreshAssessmentProse(proseRoot)', context);
  assert.equal(proseNode.innerHTML, "English saved explanation.", "changing language updates an already rendered explanation without rerendering the page");
  const malformedAudit = {
    assessment_kind: "manager_audit",
    locale: "en",
    result: {
      evidence_review: [{ line_ref: "L4", xyz_verdict: 12, category: { unexpected: true }, quote: "A quoted resume line", xyz_assessment: "English assessment prose." }],
    },
  };
  context.malformedAudit = malformedAudit;
  const malformedAuditHtml = vm.runInContext('state.locale = "ru"; renderAssessmentResult(malformedAudit)', context);
  assert.match(malformedAuditHtml, /L4 · evidence/, "unexpected optional verdict/category types must safely fall back");
  assert.match(malformedAuditHtml, /A quoted resume line/);
  const localizedAtsHtml = vm.runInContext('state.locale = "ru"; atsResult(analysis, {id: 1})', context);
  assert.match(localizedAtsHtml, /Оценка текстового совпадения ATS/);
  assert.match(localizedAtsHtml, /В этой версии резюме найдено подтверждение\./);
  assert.match(localizedAtsHtml, /Это только текстовое сравнение/);
  process.stdout.write("ATS UI provenance contract passed\n");
})().catch(error => {
  process.stderr.write(`${error.stack}\n`);
  process.exitCode = 1;
});
