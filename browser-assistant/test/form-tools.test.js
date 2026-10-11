"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {safeApplicationUrl,fieldValue,documentKind,submissionLabel,nextLabel,isAtsUrl,applicationLinks,uploadFieldComplete,requiredFieldsMissing}=require("../form-tools");
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

test("Arbeitnow Apply Now link leads to the real Ashby employer form",()=>{
  const links=[
    {text:"Manage cookie options",href:"https://arbeitnow.com/privacy"},
    {text:"Apply Now",href:"https://jobs.ashbyhq.com/statista/fa9658a6-2ff8-4d50-a228-6ac2ffead4a3/application?utm_source=arbeitnow.com"},
    {text:"Other jobs",href:"https://arbeitnow.com/jobs"},
  ];
  const found=applicationLinks(links,"https://arbeitnow.com/jobs/companies/statista/data-engineer-hamburg-or-berlin-249944");
  assert.equal(found.length,1);
  assert.equal(found[0].ats,true);
  assert.equal(isAtsUrl(found[0].url),true);
  assert.equal(new URL(found[0].url).hostname,"jobs.ashbyhq.com");
});
test("Ashby form Name Email and Phone map to user-reviewed personal profile",()=>{
  const profile={fullName:"Example Candidate",email:"candidate@example.com",phone:"+49 000 000"};
  assert.deepEqual(fieldValue({name:"name",label:"Name*",tag:"input",type:"text"},profile),{key:"fullName",value:"Example Candidate"});
  assert.deepEqual(fieldValue({name:"emailAddress",label:"Email*",tag:"input",type:"email"},profile),{key:"email",value:"candidate@example.com"});
  assert.deepEqual(fieldValue({name:"phoneNumber",label:"Phone number",tag:"input",type:"tel"},profile),{key:"phone",value:"+49 000 000"});
  assert.equal(documentKind({name:"resume",label:"Resume*",type:"file"}),"cv");
  assert.equal(documentKind({name:"experienceLetter",label:"Experience Letter",type:"file"}),"experience");
});
test("Employer link cannot redirect the assistant directly to a local server",()=>{
  const links=[
    {text:"Apply Now",href:"http://localhost:8000/private"},
    {text:"Apply Now",href:"https://127.0.0.1/admin"},
    {text:"Apply Now",href:"https://jobs.ashbyhq.com/statista/application"},
  ];
  const found=applicationLinks(links,"https://arbeitnow.com/job/1");
  assert.equal(found.length,1);
  assert.match(found[0].url,/ashbyhq/);
});

test("Ashby uploaded CV is complete when native file input resets but attached chip is visible",()=>{
  const doc={cv:{name:"Hamza_Zahid_Butt-CV.pdf"}};
  const fields=[
    {name:"emailAddress",type:"email",label:"Email",required:true,filled:true},
    {name:"resume",type:"file",label:"Resume ResumeHamza_Zahid_Butt-CV.pdfReplace or drag and drop here",
     attachmentText:"Resume ResumeHamza_Zahid_Butt-CV.pdfReplace or drag and drop here",
     required:true,filled:false},
    {name:"location",type:"text",label:"Your Location",required:true,filled:true},
  ];
  assert.equal(uploadFieldComplete(fields[1],doc),true);
  assert.equal(requiredFieldsMissing(fields,doc).length,0);
  // The approved final action should be recognized from the Ashby button label.
  assert.equal(submissionLabel("Submit Application"),true);
});
test("Upload validation does not bypass missing CV, wrong attachment, or pending upload",()=>{
  const doc={cv:{name:"Hamza_Zahid_Butt-CV.pdf"}};
  const upload={name:"resume",label:"Resume*",type:"file",required:true,filled:false};
  assert.equal(uploadFieldComplete(upload,doc),false);
  assert.equal(uploadFieldComplete({...upload,attachmentText:"Upload resume or drag here"},doc),false);
  assert.equal(uploadFieldComplete({...upload,attachmentText:"Different-CV.pdf Replace"},doc),false);
  assert.equal(uploadFieldComplete({...upload,attachmentText:"Hamza_Zahid_Butt-CV.pdf Uploading... Replace"},doc),false);
  assert.equal(requiredFieldsMissing([upload],doc).length,1);
});
test("Visual resume evidence is scoped to the exact user-selected document",()=>{
  const field={name:"resume",label:"Resume*",type:"file",required:true,filled:false,
    attachmentText:"Resume Hamza_Zahid_Butt-CV.pdf Replace"};
  assert.equal(uploadFieldComplete(field,{cv:{name:"Hamza_Zahid_Butt-CV.pdf"}}),true);
  assert.equal(uploadFieldComplete(field,{cv:{name:"Another-Resume.pdf"}}),false);
  assert.equal(uploadFieldComplete({...field,attachmentText:""}, {cv:{name:"Hamza_Zahid_Butt-CV.pdf"}}),false);
});

test("Ashby screenshot-style file input label proves existing attachment",()=>{
  const field={name:"resume",type:"file",required:true,filled:false,
    label:"Resume ResumeHamza_Zahid_Butt-CV.pdfReplace or drag and drop here"};
  assert.equal(uploadFieldComplete(field,{cv:{name:"Hamza_Zahid_Butt-CV.pdf"}}),true);
  assert.equal(uploadFieldComplete({...field,label:"Resume* Upload file"}, {cv:{name:"Hamza_Zahid_Butt-CV.pdf"}}),false);
});
