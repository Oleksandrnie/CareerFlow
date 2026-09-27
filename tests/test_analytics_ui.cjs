const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "careerflow/static/app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "careerflow/static/app.css"), "utf8");

for (const label of [
  'added: "Добавлено"',
  'application_submitted: "Отклик отправлен"',
  'interview_invited: "Приглашение на интервью"',
  'offer_accepted: "Оффер принят"',
  'added_to_application: "Добавлено → отклик"',
  'employer_rejected: "Отказ работодателя"',
]) {
  assert.match(app, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
}

assert.match(app, /analyticsLabel\(item\.stage\)/);
assert.match(app, /analyticsLabel\(item\.transition\)/);
assert.match(app, /analyticsLabel\(key\)/);
assert.match(app, /window\.matchMedia\?\.\("\(max-width: 600px\)"\)\.matches/);
assert.match(app, /sidebarToggle\.hidden = section !== "vacancies"/);
assert.match(app, /state\.locale === "ru" && state\.section === "analytics"/);
assert.match(css, /\.analytics-head \{ display: grid; grid-template-columns: minmax\(0, 1fr\) 44px;/);
assert.match(css, /\.analytics-head \.help-button \{[^}]*justify-self: end;/);
assert.match(css, /\.analytics-date\[hidden\] \{ display: none !important; \}/);
assert.match(css, /\.sidebar-toggle\[hidden\] \{ display: none !important; \}/);
assert.match(css, /\.topbar\.header-nav-hidden \.primary-nav \{ display: flex;/);

console.log("Analytics mobile UI contract passed");
