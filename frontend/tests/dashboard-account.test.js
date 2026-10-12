"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {readFileSync}=require("node:fs");
const {join}=require("node:path");

const root=join(__dirname,"..");
const html=readFileSync(join(root,"index.html"),"utf8");
const app=readFileSync(join(root,"app.js"),"utf8");
const css=readFileSync(join(root,"styles.css"),"utf8");

test("no promotional Local-first text remains in sidebar",()=>{
  assert.ok(!html.includes("Free job feeds + local CV analysis"));
  assert.ok(!html.includes('class="sideNote"'));
  assert.ok(html.includes('id="sidebarAccount"'));
});

test("authenticated account menu exposes real account actions",()=>{
  for(const id of ["accountMenu","accountSettings","accountSwitch","accountLogout","avatar"])
    assert.ok(html.includes('id="'+id+'"'),id);
  assert.match(app,/function toggleAccountMenu\(/);
  assert.match(app,/document\.querySelector\('#accountSwitch'\)\.onclick/);
  assert.match(app,/logout\(true\)/);
  assert.match(app,/logout\(false\)/);
  assert.match(app,/function stopClientPolling\(/);
  assert.match(app,/roleTo\('settings'\)|routeTo\('settings'\)/);
});

test("dashboard updates statistics without silently scraping employer sites",()=>{
  assert.ok(html.includes('id="refreshDashboard"'));
  assert.ok(html.includes('id="dashboardRefreshStatus"'));
  assert.match(app,/dashboardPoller=setInterval/);
  assert.match(app,/\},45000\)/);
  assert.match(app,/document\.hidden/);
  assert.match(app,/const statuses=d\.pipeline \|\| \{\}/);
  assert.match(app,/statuses\.Rejected\|\|0/);
  assert.match(app,/Awaiting Replies/);
  assert.match(app,/Interview Stages/);
  assert.match(app,/Gmail \+ manual statuses/);
  assert.match(app,/Cached jobs may be stale/);
  assert.match(app,/dashboardLoadPromise=renderDashboardData\(\)/);
  assert.match(app,/apiFetch\('\/api\/dashboard'\)/);
});

test("dashboard CSS supports account menu and summary on mobile",()=>{
  assert.match(css,/\.accountMenu/);
  assert.match(css,/\.dashboardRefreshStatus/);
  assert.match(css,/\.dashboardMetricBad/);
  assert.match(css,/@media\(max-width:760px\)\{\.metrics\{grid-template-columns:1fr\}/);
});
