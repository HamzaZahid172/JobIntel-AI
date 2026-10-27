"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const vm=require("node:vm");
const {readFileSync}=require("node:fs");
const {join}=require("node:path");

test("CV draft is editable, downloads those edits, and protects unsaved changes",async()=>{
  const source=readFileSync(join(__dirname,"..","app.js"),"utf8");
  const start=source.indexOf("async function showTailorCv(jobId){");
  const end=source.indexOf("async function refreshApplicationsGmailInBackground",start);
  assert.ok(start>=0 && end>start);
  const nodes={};
  function node(id){
    if(!nodes[id])nodes[id]={value:'',innerHTML:'',disabled:false,
      classList:{add(){},remove(){}},querySelector(){return {textContent:''};}};
    return nodes[id];
  }
  let request=null,clicked=false,confirmation=0;
  const context={
    document:{querySelector(s){return node(s);},body:{appendChild(){}},
      createElement(){return {click(){clicked=true;},remove(){}};}},
    chooseRoleCvOption(versions,jobId,select){select.value='1';},
    esc:s=>s, confirm(){confirmation++;return false;}, alert(){throw Error('unexpected alert');},
    apiFetch:async(path,options)=>{
      if(path==='/api/cv/versions')return [{id:1,filename:'cv.pdf',ats_score:80},{id:2,filename:'other.pdf',ats_score:80}];
      if(path.endsWith('/tailor-cv?cv_id=1'))return {draft:{tailored_cv_text:'Original CV draft',suggested_summary:'Summary',cv_evidence:[],matched_skills:[],missing_skills_do_not_claim:[],instructions:'Review'}};
      if(path.endsWith('/tailor-cv/docx')){request=JSON.parse(options.body);return {content_base64:'YQ==',filename:'edited.docx'};}
      throw Error('Unexpected request '+path);
    },
    prepareApplication:async()=>{},URL:{createObjectURL(){return 'blob:test';},revokeObjectURL(){}},
    Blob,Uint8Array,atob,Number,Math,JSON
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start,end),context);
  await context.showTailorCv(42);
  assert.equal(node('#tailorEditable').value,'Original CV draft');
  node('#tailorEditable').value='The user edited this CV';
  await node('#downloadTailoredCv').onclick();
  assert.deepEqual(request,{cv_id:1,text:'The user edited this CV'});
  assert.equal(clicked,true);
  node('#tailorVersion').value='2';
  await node('#tailorVersion').onchange();
  assert.equal(confirmation,1);
  assert.equal(node('#tailorVersion').value,'1');
  assert.equal(node('#tailorEditable').value,'The user edited this CV');
});
