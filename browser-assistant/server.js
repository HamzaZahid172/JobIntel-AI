"use strict";
/* Local companion: launch on the user's computer so Chromium is visible.
   No remote service, bulk application, automatic consent, or CAPTCHA bypass. */
const http = require("node:http");
const { randomUUID } = require("node:crypto");
const {safeApplicationUrl,fieldValue,documentKind,submissionLabel,nextLabel} = require("./form-tools");

const HOST = "127.0.0.1", PORT = Number(process.env.JOBINTEL_ASSISTANT_PORT || 3401);
const ALLOWED = new Set(["http://localhost:3100", "http://127.0.0.1:3100"]);
const MAX_BODY_BYTES = 24 * 1024 * 1024;
let session = null;

function json(res, code, payload, origin) {
  res.writeHead(code, {"Content-Type":"application/json; charset=utf-8",
    "Cache-Control":"no-store", "Access-Control-Allow-Origin": origin || "http://localhost:3100",
    "Vary":"Origin", "Access-Control-Allow-Headers":"Content-Type,X-JobIntel-Assistant",
    "Access-Control-Allow-Methods":"GET,POST,OPTIONS"});
  res.end(JSON.stringify(payload));
}
function readBody(req) {
  return new Promise((resolve,reject)=>{
    const chunks=[]; let length=0;
    req.on("data",chunk=>{
      length+=chunk.length;
      if(length>MAX_BODY_BYTES){reject(new Error("Payload exceeds 24 MB"));req.destroy();return;}
      chunks.push(chunk);
    });
    req.on("end",()=>{
      try {resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")||"{}"));}
      catch {reject(new Error("Invalid JSON payload"));}
    });
    req.on("error",reject);
  });
}
function documentsFromInput(docs) {
  const result={}; let total=0;
  for(const kind of ["cv","cover","experience"]){
    const d=docs && docs[kind];
    if(!d)continue;
    if(typeof d.name!=="string" || !/\.(pdf|doc|docx|txt)$/i.test(d.name) ||
       !/^[\w .()\-]{1,180}$/.test(d.name) ||
       typeof d.base64!=="string") throw Error("Unsupported document format.");
    const buffer=Buffer.from(d.base64,"base64");
    if(!buffer.length || buffer.length>8*1024*1024)throw Error("Each attachment must be under 8 MB.");
    total+=buffer.length;
    if(total>20*1024*1024)throw Error("Total attachments exceed 20 MB.");
    const mimeType=/\.pdf$/i.test(d.name)?"application/pdf":/\.docx$/i.test(d.name)?
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
      /\.doc$/i.test(d.name)?"application/msword":"text/plain";
    result[kind]={name:d.name,mimeType,buffer};
  }
  return result;
}
async function visibleFields(page) {
  return page.evaluate(()=>{
    const nodes=Array.from(document.querySelectorAll("input,textarea,select"));
    return nodes.map((e,index)=>{
      const label=e.labels && e.labels.length?Array.from(e.labels).map(x=>x.innerText).join(" "):
        (e.id?document.querySelector('label[for="'+CSS.escape(e.id)+'"]')?.innerText:"") ||
        e.closest("label")?.innerText || e.getAttribute("aria-label") || "";
      return {index,tag:e.tagName.toLowerCase(),type:(e.type||"").toLowerCase(),
        name:e.name||"",id:e.id||"",placeholder:e.placeholder||"",
        autocomplete:e.autocomplete||"",label:label.slice(0,180),required:!!e.required,
        filled:e.type==="radio"&&e.name?Array.from(document.getElementsByName(e.name)).some(x=>x.checked):
          e.type==="checkbox"?e.checked:!!e.value,
        visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)};
    }).filter(x=>x.visible&&x.type!=="hidden"&&x.type!=="password").slice(0,120);
  });
}
async function review() {
  if(!session || session.page.isClosed())throw Error("No active browser session.");
  const page=session.page, fields=await visibleFields(page);
  return {active:true,id:session.id,url:page.url(),title:await page.title(),
    fields:fields.map(x=>({...x,kind:x.type==="file"?documentKind(x):null})),
    status:session.status,notes:session.notes,submissionAttempted:session.submissionAttempted};
}
async function start(input) {
  if(session && !session.page.isClosed()) throw Error("Close the existing application session first.");
  if(!safeApplicationUrl(input.url)) throw Error("Use a public HTTPS employer application URL.");
  const profile=input.profile||{};
  for(const k of ["firstName","lastName","fullName","email","phone","city","country","linkedin","github","portfolio"]){
    if(profile[k] && (typeof profile[k]!=="string" || profile[k].length>250))throw Error("Invalid profile field.");
  }
  const docs=documentsFromInput(input.documents);
  const { chromium } = require("playwright");
  const browser=await chromium.launch({headless:false});
  try {
    const context=await browser.newContext({acceptDownloads:false});
    const page=await context.newPage();
    const id=randomUUID();
    session={browser,context,page,profile,docs,id,notes:[],status:"opened",submissionAttempted:false};
    context.on("page",popup=>{
      if(!popup.isClosed()){session.page=popup;session.notes.push("An application popup opened. Inspect the new form.");}
    });
    await page.goto(input.url,{waitUntil:"domcontentloaded",timeout:45000});
    session.notes.push("Employer page opened. Review the browser before filling.");
    return await review();
  }catch(err){
    session=null;await browser.close();throw err;
  }
}
async function fill() {
  if(!session)throw Error("Start an application first.");
  const page=session.page, fields=await visibleFields(page),changes=[],warnings=[];
  const profile={...session.profile,fullName:session.profile.fullName||
    [session.profile.firstName,session.profile.lastName].filter(Boolean).join(" ")};
  for(const field of fields){
    if(field.filled)continue;
    const locator=page.locator("input,textarea,select").nth(field.index);
    try {
      if(field.type==="file"){
        const kind=documentKind(field);
        if(kind && session.docs[kind]){
          await locator.setInputFiles(session.docs[kind]);
          changes.push("Attached "+kind+": "+session.docs[kind].name);
        }
        continue;
      }
      const entry=fieldValue(field,profile);
      if(entry && entry.value){
        await locator.fill(entry.value,{timeout:2500});
        changes.push("Filled "+(field.label||field.name||entry.key));
      }
    }catch(err){
      warnings.push("Could not fill "+(field.label||field.name||"field")+"; complete it manually.");
    }
  }
  session.notes.push(...changes.slice(-15));
  if(warnings.length)session.notes.push(...warnings.slice(-8));
  session.status="filled";
  return {...(await review()),changes,warnings};
}
async function clickNext() {
  if(!session)throw Error("Start an application first.");
  const currentFields=await visibleFields(session.page);
  const hasApplicationForm=currentFields.some(x=>x.type==="file"||x.type==="email")||
    currentFields.filter(x=>x.required).length>=2;
  const buttons=await session.page.locator("button,input[type=submit],a").all();
  let found=null;
  for(const button of buttons){
    try {
      if(!await button.isVisible())continue;
      const text=(await button.innerText().catch(()=>'')) ||
        (await button.getAttribute("value")) || (await button.getAttribute("aria-label")) || "";
      const initialApply=!hasApplicationForm && /^apply now$/i.test(text.trim());
      if(submissionLabel(text)&&!initialApply)continue;
      if(initialApply||nextLabel(text)){found=button;break;}
    }catch{}
  }
  if(!found)throw Error("No safe Next/Continue button found. Click the next step manually in Chromium.");
  await found.click({timeout:5000});
  await session.page.waitForTimeout(900);
  session.notes.push("Clicked an intermediate step only; final submission is never automatic.");
  return await review();
}
async function submit(approval) {
  if(!session)throw Error("Start an application first.");
  if(approval!=="SUBMIT")throw Error("Type SUBMIT to authorize exactly this submission.");
  if(session.submissionAttempted)throw Error("Submission already attempted; verify the employer website.");
  const fields=await visibleFields(session.page);
  const missing=fields.filter(x=>x.required&&!x.filled);
  if(missing.length)throw Error("Required fields still empty: "+missing.slice(0,6).map(x=>x.label||x.name||"unnamed field").join(", "));
  const buttons=await session.page.locator("button,input[type=submit]").all();
  const matched=[];
  for(const button of buttons){
    try {
      if(!await button.isVisible() || !await button.isEnabled())continue;
      const label=(await button.innerText().catch(()=>''))||
        (await button.getAttribute("value"))|| (await button.getAttribute("aria-label"))||"";
      if(submissionLabel(label))matched.push(button);
    }catch{}
  }
  if(matched.length!==1)throw Error("Could not identify exactly one final Submit button. Complete and submit manually in Chromium.");
  // Never report a successful employer application solely because a click occurred.
  session.submissionAttempted=true;
  await matched[0].click({timeout:5000});
  session.status="submission_attempted";
  session.notes.push("Final submit was clicked after explicit approval. Check the employer page for confirmation.");
  await session.page.waitForTimeout(800);
  return await review();
}
async function close() {
  if(session){const b=session.browser;session=null;await b.close();}
  return {active:false};
}
const handlers={
  "GET /health": async()=>({ready:true,localOnly:true}),
  "GET /status": async()=>session?await review():{active:false},
  "POST /start": start,
  "POST /fill": fill,
  "POST /next": clickNext,
  "POST /submit": async(input)=>submit(input.approval),
  "POST /close": close,
};
const server=http.createServer(async(req,res)=>{
  const origin=req.headers.origin;
  if(origin && !ALLOWED.has(origin))return json(res,403,{error:"Origin not allowed."},"http://localhost:3100");
  if(req.method==="OPTIONS")return json(res,200,{ok:true},origin);
  const route=req.method+" "+new URL(req.url,"http://localhost").pathname;
  if(!handlers[route])return json(res,404,{error:"Not found"},origin);
  if(req.method==="POST" && (req.headers["x-jobintel-assistant"]!=="1" ||
     !(req.headers["content-type"]||"").startsWith("application/json")))
    return json(res,403,{error:"Only local JobIntel JSON requests are accepted."},origin);
  try{const input=req.method==="POST"?await readBody(req):{};return json(res,200,await handlers[route](input),origin);}
  catch(err){return json(res,400,{error:String(err.message||err)},origin);}
});
server.listen(PORT,HOST,()=>console.log("JobIntel browser assistant: http://"+HOST+":"+PORT));
process.on("SIGINT",async()=>{await close();server.close();process.exit(0);});
