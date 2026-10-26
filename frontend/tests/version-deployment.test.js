"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const base=path.join(__dirname,"..");
const read=name=>fs.readFileSync(path.join(base,name),"utf8");
const build=JSON.parse(read("version.json")).build;

test("frontend HTML, JS and Nginx identify the same release",()=>{
  const html=read("index.html");
  const js=read("app.js");
  const nginx=read("nginx.conf");
  const docker=read("Dockerfile");
  assert.match(html,/id="jobintelBuild"/);
  assert.ok(html.includes("Build "+build));
  assert.ok(html.includes("/app.js?v="+build));
  assert.ok(js.includes("JOBINTEL_UI_BUILD = '"+build+"'"));
  assert.ok(nginx.includes('X-JobIntel-Build "'+build+'"'));
  assert.ok(nginx.includes('Cache-Control "no-store'));
  assert.ok(docker.includes("version.json"));
  assert.ok(docker.includes("nginx.conf"));
});

test("single sync-all UI is used and per-row Gmail buttons are absent",()=>{
  const app=read("app.js");
  assert.ok(app.includes('id="syncAllApplications"'));
  assert.ok(!app.includes("checkSingleGmail"));
  assert.ok(app.includes("Test Gmail connection"));
  assert.ok(app.includes("/api/gmail/diagnostics"));
});
