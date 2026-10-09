"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {safeApplicationUrl,fieldValue,documentKind,submissionLabel,nextLabel}=require("../form-tools");
test("only public HTTPS job URLs",()=>{
 assert.equal(safeApplicationUrl("https://jobs.example.com/job/1"),true);
 for(const u of ["http://jobs.example.com","https://localhost:8000","https://127.0.0.1/","https://192.168.1.1/","https://[::1]/","file:///etc/passwd","https://user:pass@example.com/"]){
   assert.equal(safeApplicationUrl(u),false,u);
 }
});
test("only known profile evidence is auto-filled",()=>{
 assert.deepEqual(fieldValue({name:"first_name",type:"text",tag:"input"},{firstName:"Sam"}),{key:"firstName",value:"Sam"});
 assert.equal(fieldValue({name:"salary_expectation",type:"text",tag:"input"},{salary:"80000"}),null);
 assert.equal(fieldValue({name:"work_authorization",type:"select-one",tag:"select"},{country:"DE"}),null);
});
test("documents require recognizable labels",()=>{
 assert.equal(documentKind({label:"Upload resume"}),"cv");
 assert.equal(documentKind({label:"Cover letter"}),"cover");
 assert.equal(documentKind({label:"Arbeitszeugnis"}),"experience");
 assert.equal(documentKind({label:"Unspecified attachment"}),null);
});
test("submission step cannot be treated as next",()=>{
 assert.equal(submissionLabel("Submit application"),true);
 assert.equal(nextLabel("Submit application"),false);
 assert.equal(nextLabel("Continue"),true);
});
