"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const vm=require("node:vm");
const {readFileSync}=require("node:fs");
const {join}=require("node:path");

const source=readFileSync(join(__dirname,"..","app.js"),"utf8");
const start=source.indexOf("function publicJobUrl(value){");
const end=source.indexOf("function bindTrackButtons()",start);
assert.ok(start>=0 && end>start);
const context={URL,Math,esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);

test("job card keeps key actions visible and other tools available in a disclosure",()=>{
  const html=context.jobCard({id:4,title:"Backend",company:"Example",location:"Berlin",
    source:"Manual",url:"https://example.org/jobs/4",match:80,skills:["python"],
    matched_skills:["python"],missing_skills:[],score_breakdown:{}},false);
  const actions=html.slice(html.indexOf('<div class="jobActions">'),html.indexOf('<details class="jobMore">'));
  assert.match(actions,/View &amp; apply/);
  assert.match(actions,/tailorCvBtn/);
  assert.match(actions,/guidedApplyBtn/);
  assert.doesNotMatch(actions,/coverLetterBtn|atsReviewBtn|trackJob/);
  for(const id of ['coverLetterBtn','applicationQualityBtn','atsReviewBtn','startPracticeBtn','prepareApplicationBtn','trackJob'])
    assert.ok(html.includes(id),id);
  assert.match(html,/Matched in CV/);
  assert.match(html,/not an? prediction|not a prediction/);
});

test("job card does not expose unsafe links or confuse job skills with CV evidence",()=>{
  const html=context.jobCard({id:1,title:'<script>',company:'Example',location:'Germany',
    source:'Feed',url:'javascript:alert(1)',skills:['Kafka'],matched_skills:[],
    missing_skills:['Kafka'],score_breakdown:{}},false);
  assert.match(html,/Source link unavailable/);
  assert.doesNotMatch(html,/href="javascript:/);
  assert.match(html,/&lt;script&gt;/);
  assert.match(html,/Skills in job/);
  assert.match(html,/Not found in CV/);
});

test("unknown requirements do not appear as confirmed percentage matches",()=>{
  const html=context.jobCard({id:5,title:'Engineer',company:'Example',location:'Germany',source:'Feed',
    url:'https://example.org/jobs/5',skills:[],score_breakdown:{role_alignment:90,required_skills:70,experience:80,language:100},
    requirements:{required_skills:[],years_required:null,languages:[]}},false);
  assert.match(html,/Required skills Not specified/);
  assert.match(html,/Experience Not specified/);
  assert.match(html,/Language Not specified/);
  assert.doesNotMatch(html,/Language 100%/);
});

test("Action Center search and decision filter combine without changing the queue",()=>{
  const begin=source.indexOf('function filterActionJobs(');
  const finish=source.indexOf('async function renderActionCenter()',begin);
  assert.ok(begin>=0 && finish>begin);
  vm.runInContext(source.slice(begin,finish),context);
  const jobs=[
    {title:'Python Engineer',company:'Alpha',location:'Berlin',skills:['FastAPI'],opportunity:{decision:'Apply Now'}},
    {title:'Frontend Engineer',company:'Beta',location:'Remote',skills:['React'],opportunity:{decision:'Review'}},
    {title:'Python Analyst',company:'Gamma',location:'Berlin',skills:['Python'],opportunity:{decision:'Review'}}
  ];
  assert.deepEqual(Array.from(context.filterActionJobs(jobs,'  PYTHON ','Review'),job=>job.company),['Gamma']);
  assert.deepEqual(Array.from(context.filterActionJobs(jobs,'remote',''),job=>job.company),['Beta']);
  assert.equal(context.filterActionJobs(jobs,'fastapi','Apply Now').length,1);
  assert.equal(jobs.length,3);
});
