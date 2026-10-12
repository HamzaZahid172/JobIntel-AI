"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.join(__dirname,"..");
const html=fs.readFileSync(path.join(root,"index.html"),"utf8");
const js=fs.readFileSync(path.join(root,"app.js"),"utf8");

test("Google login is separate from password and existing Gmail scopes",()=>{
  assert.match(html,/id="googleSignIn"/);
  assert.match(html,/id="loginForm"/);
  assert.match(html,/id="registerForm"/);
  assert.ok(js.includes('/api/auth/google/start'));
  assert.ok(js.includes('/api/auth/google/link'));
  assert.ok(js.includes('/api/auth/google/exchange'));
  assert.match(js,/\/api\/auth\/google\/status/);
});

test("popup verifies backend origin and registered popup source",()=>{
  assert.match(js,/event\.origin!==new URL\(API\)\.origin/);
  assert.match(js,/event\.source!==googleAuthPopup/);
  assert.match(js,/msg\.type!=='jobintel-google-auth'/);
  assert.match(js,/localStorage\.setItem\('jobintel_token',result\.token\)/);
});

test("no extra Gmail permission is required to use Google login",()=>{
  const callback=js.slice(js.indexOf("async function startGoogleOAuth"),js.indexOf("window.addEventListener('message'"));
  assert.ok(!callback.includes("gmail.readonly"));
  assert.ok(!callback.includes("gmail.send"));
});
