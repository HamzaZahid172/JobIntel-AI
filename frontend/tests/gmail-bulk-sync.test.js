"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {readFileSync}=require("node:fs");
const {join}=require("node:path");
const app=readFileSync(join(__dirname,"..","app.js"),"utf8");

test("one sync-all action replaces the per-application Gmail buttons",()=>{
  assert.match(app,/id="syncAllApplications"/);
  assert.match(app,/querySelector\('#syncAllApplications'\)\.onclick/);
  assert.ok(!app.includes("checkSingleGmail"));
  assert.ok(!app.includes("data-app-id=\"'+a.id+'\">Check Gmail"));
});

test("Gmail refresh is single-flight and automatically checks on navigation or tab focus",()=>{
  assert.match(app,/if\(applicationGmailRefreshPromise\)return applicationGmailRefreshPromise/);
  assert.match(app,/api\/gmail\/sync-applications/);
  assert.match(app,/document\.addEventListener\('visibilitychange'/);
  assert.match(app,/window\.addEventListener\('focus'/);
  assert.match(app,/currentRoute==='applications'/);
  assert.match(app,/Gmail check unavailable/);
});

test("sync shows a last-check summary without claiming an employer response",()=>{
  assert.match(app,/Gmail checked at /);
  assert.match(app,/status update\(s\)/);
  assert.match(app,/employers not checked/);
});
