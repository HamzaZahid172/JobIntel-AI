"use strict";
/* Local companion: launch on the user's computer so Chromium is visible.
   No remote service, bulk application, automatic consent, or CAPTCHA bypass. */
const http = require("node:http");
const { randomUUID } = require("node:crypto");
const {safeApplicationUrl,fieldValue,documentKind,submissionLabel,nextLabel,isAtsUrl,applicationLinks,uploadFieldComplete,requiredFieldsMissing} = require("./form-tools");

const HOST = "127.0.0.1", PORT = Number(process.env.JOBINTEL_ASSISTANT_PORT || 3401);
const ALLOWED = new Set(["http://localhost:3100", "http://127.0.0.1:3100"]);
const MAX_BODY_BYTES = 29 * 1024 * 1024;
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
function activePage() {
  if (!session) throw Error("No active browser session.");
  const pages = session.context.pages().filter(p=>!p.isClosed() && safeApplicationUrl(p.url()));
  if (!pages.length) throw Error("No public employer page is open.");
  // An ATS tab should always take precedence over the originating job aggregator.
  const ats = pages.filter(p=>isAtsUrl(p.url()));
  if (ats.length) session.page=ats[ats.length-1];
  else if (!session.page || session.page.isClosed()) session.page=pages[pages.length-1];
  return session.page;
}
async function visibleFields(page) {
  const expectedFiles=Object.values(session?.docs || {}).map(doc=>doc.name);
  return page.evaluate((expectedFiles)=>{
    const nodes=Array.from(document.querySelectorAll("input,textarea,select"));
    const labelOf = e=>{
      const labels=e.labels ? Array.from(e.labels).map(x=>x.innerText||x.textContent).join(" ") : "";
      const idref=e.getAttribute("aria-labelledby")||"";
      const viaId=idref.split(/\s+/).map(id=>document.getElementById(id)?.textContent||"").join(" ");
      const direct=e.getAttribute("aria-label")||e.closest("label")?.textContent||"";
      const nearest=e.type==="file" ?
        (e.closest("[data-testid],fieldset,[class*='upload'],[class*='field']")?.textContent ||
         e.parentElement?.parentElement?.textContent || "").trim().slice(0,160) : "";
      return [labels,viaId,direct,nearest].filter(Boolean).join(" ").replace(/\s+/g," ").slice(0,240);
    };
    const attachedFileText=e=>{
      // Scoped to the file-upload widget. Never trust filename mentions elsewhere.
      let node=e.parentElement;
      for(let depth=0;node && depth<9;depth++,node=node.parentElement){
        if(node===document.body || node.tagName==="FORM") break;
        const text=String(node.innerText||"").replace(/\\s+/g," ").trim();
        if(text.length>1000 || !text) continue;
        if(expectedFiles.some(filename=>text.toLowerCase().includes(filename.toLowerCase())) &&
            /\\b(replace|remove|delete|attached|uploaded|ersetzen|entfernen)\\b/i.test(text)){
          return text;
        }
      }
      return "";
    };
    return nodes.map((e,index)=>{
      const type=(e.type||"").toLowerCase();
      const visible=!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
      const files=type==="file";
      return {index,tag:e.tagName.toLowerCase(),type,name:e.name||"",id:e.id||"",
        placeholder:e.placeholder||"",autocomplete:e.autocomplete||"",
        label:labelOf(e),required:!!e.required,
        attachmentText:files?attachedFileText(e):"",
        filled:files?Boolean(e.files&&e.files.length):
          type==="radio"&&e.name?Array.from(document.getElementsByName(e.name)).some(x=>x.checked):
          type==="checkbox"?e.checked:!!e.value,
        visible};
    }).filter(x=>(x.visible||x.type==="file")&&x.type!=="hidden"&&x.type!=="password")
      .slice(0,120);
  },expectedFiles);
}
async function discoverLinks(page) {
  const links=await page.evaluate(()=>Array.from(document.querySelectorAll("a[href]")).map(a=>({
    href:a.href,text:(a.innerText||a.getAttribute("aria-label")||a.title||"").trim(),
  })));
  return applicationLinks(links,page.url());
}
async function consentVisible(page) {
  return page.evaluate(()=>{
    const text=Array.from(document.querySelectorAll("[role='dialog'],[aria-modal='true'],.fc-consent-root"))
      .filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length))
      .map(e=>e.innerText||"").join(" ").toLowerCase();
    return /consent|cookie|personal data|privacy|datenschutz/.test(text);
  });
}
async function review() {
  const page=activePage();
  await page.waitForLoadState("domcontentloaded",{timeout:8000}).catch(()=>{});
  const [fields,links,consent]=await Promise.all([
    visibleFields(page),discoverLinks(page),consentVisible(page)
  ]);
  const prepared=fields.map(x=>({
    ...x,kind:x.type==="file"?documentKind(x):null,
    filled:uploadFieldComplete(x,session.docs),
  }));
  return {active:true,id:session.id,url:page.url(),title:await page.title(),
    stage:isAtsUrl(page.url())?"employer ATS":links.length?"job listing":"employer page",
    applicationLinks:links,consentRequired:consent,
    fields:prepared.map(({attachmentText,...x})=>x), // omit personal filenames from raw widget text
    status:session.status,notes:session.notes,submissionAttempted:session.submissionAttempted};
}
async function openApplication(input) {
  const page=activePage();
  const found=(await discoverLinks(page)).find(link=>link.url===input.url);
  if(!found) throw Error("This application link is no longer on the current page. Inspect again.");
  if(!safeApplicationUrl(found.url))throw Error("The application URL is not permitted.");
  const newPage=await session.context.newPage();
  try {
    await newPage.goto(found.url,{waitUntil:"domcontentloaded",timeout:45000});
    if(!safeApplicationUrl(newPage.url()))throw Error("Application redirected to an unsafe URL.");
    session.page=newPage;
    session.status="employer application opened";
    session.notes.push("Opened the selected employer application page: "+new URL(newPage.url()).hostname);
    session.notes.push("Review the company and job title before uploading any documents.");
    return await review();
  } catch(err){
    await newPage.close().catch(()=>{});
    throw err;
  }
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
      if (popup===page) return;
      popup.waitForLoadState("domcontentloaded",{timeout:15000}).catch(()=>{}).then(()=>{
        if(!popup.isClosed() && safeApplicationUrl(popup.url())){
          session.page=popup;
          session.status="new employer tab";
          session.notes.push("New tab detected: "+new URL(popup.url()).hostname+". Click Inspect Form.");
        }
      });
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
  const page=activePage(), fields=await visibleFields(page),changes=[],warnings=[];
  const profile={...session.profile,fullName:session.profile.fullName||
    [session.profile.firstName,session.profile.lastName].filter(Boolean).join(" ")};
  for(const field of fields){
    if(uploadFieldComplete(field,session.docs))continue;
    const locator=page.locator("input,textarea,select").nth(field.index);
    try {
      if(field.type==="file"){
        const kind=documentKind(field);
        if(kind && session.docs[kind]){
          await locator.setInputFiles(session.docs[kind]);
          changes.push("Attached "+kind+": "+session.docs[kind].name);
        }else if(!kind){
          warnings.push("An unrecognized upload field needs manual attachment.");
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
  const page=activePage();
  const buttons=await page.locator("button,input[type=submit],a").all();
  let found=null;
  for(const button of buttons){
    try {
      if(!await button.isVisible())continue;
      const text=(await button.innerText().catch(()=>'')) ||
        (await button.getAttribute("value")) || (await button.getAttribute("aria-label")) || "";
      if(submissionLabel(text))continue;
      if(nextLabel(text)){found=button;break;}
    }catch{}
  }
  if(!found)throw Error("No safe Next/Continue button found. Click the next step manually in Chromium.");
  await found.click({timeout:5000});
  await page.waitForTimeout(900);
  session.notes.push("Clicked an intermediate step only; final submission is never automatic.");
  return await review();
}
async function submit(approval) {
  if(!session)throw Error("Start an application first.");
  if(approval!=="SUBMIT")throw Error("Type SUBMIT to authorize exactly this submission.");
  if(session.submissionAttempted)throw Error("Submission already attempted; verify the employer website.");
  const page=activePage();
  if(!isAtsUrl(page.url()))throw Error("Open the actual employer application form before approving submission.");
  const fields=await visibleFields(page);
  const missing=requiredFieldsMissing(fields,session.docs);
  if(missing.length)throw Error("Required fields still empty: "+missing.slice(0,6).map(x=>x.label||x.name||"unnamed field").join(", "));
  const buttons=await page.locator("button,input[type=submit]").all();
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
  await page.waitForTimeout(800);
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
  "POST /open-application": openApplication,
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
