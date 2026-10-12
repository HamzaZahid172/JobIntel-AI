const API = localStorage.getItem('jobintel_api') || 'http://localhost:8100';

const navItems = [
  {route:'dashboard', label:'⌂ Dashboard'},
  {route:'job-market', label:'▣ Job Market'},
  {route:'action-center', label:'★ Action Center'},
  {route:'applications', label:'▤ My Applications'},
  {route:'ats', label:'▤ ATS CV Check'},
  {route:'matches', label:'♡ Matches'},
  {route:'application-prep', label:'▣ Application Prep'},
  {route:'interview-prep', label:'🎤 Interview Practice'},
  {route:'skill-gap', label:'▥ Skill Gap'},
  {route:'analytics', label:'▧ Analytics'},
  {route:'settings', label:'⚙ Settings'}
];
let currentUser = null;
let currentRoute = 'dashboard';
let jobMarketCache = [];
let showRejectedApplications = false;
let assistantStatusTimer = null;
let dashboardPoller = null;
let dashboardLoadPromise = null;
let lastDashboardCheck = 0;
let gmailStatusWatcher = null;
let observedGmailSyncTime = null;
let gmailStatusCheckInFlight = false;
let applicationGmailRefreshPromise = null;
let lastApplicationGmailRefreshAt = 0;
let lastApplicationGmailRefreshResult = null;

function renderNav(){
  document.querySelector('#nav').innerHTML = navItems.map(function(item){
    return '<button class="nav navButton ' + (item.route===currentRoute?'active':'') + '" data-route="' + item.route + '">' + item.label + '</button>';
  }).join('');
  document.querySelectorAll('[data-route]').forEach(function(button){
    button.onclick = function(){ routeTo(button.dataset.route); };
  });
}

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const head = (title, action='') => `<div class="panelHead"><h3>${title}</h3>${action}</div>`;
const fmtDate = iso => iso ? new Date(iso).toLocaleString() : 'Not synced yet';

function ring(value, label) {
  const v = Math.max(0, Math.min(100, Number(value || 0)));
  return `<div class="ring" style="--v:${v*3.6}deg"><div><b>${v}%</b><small>${esc(label)}</small></div></div>`;
}

function empty(message) {
  return `<div class="empty">${esc(message)}</div>`;
}

async function apiFetch(path, options={}) {
  const token = localStorage.getItem('jobintel_token');
  options.headers = Object.assign({}, options.headers || {});
  if (token) options.headers.Authorization = 'Bearer ' + token;
  const response = await fetch(API + path, options);
  if (response.status === 401 && !path.startsWith('/api/auth/')) {
    localStorage.removeItem('jobintel_token');
    showAuth('Your session expired. Please log in again.');
    throw new Error('Login required');
  }
  if (!response.ok) {
    let detail = response.status + ' ' + response.statusText;
    try { const body = await response.json(); detail = body.detail || body.message || detail; } catch {}
    throw new Error(detail);
  }
  return response.json();
}

function humanRoleFamily(value) {
  return {
    software_backend: 'Software / Backend',
    automation_qa: 'QA Automation',
    data_engineering: 'Data Engineering',
    ai_ml: 'AI / ML',
    frontend_fullstack: 'Frontend / Full-stack',
    devops_platform: 'DevOps / Platform',
  }[value] || value;
}

async function load(){
  if(dashboardLoadPromise)return dashboardLoadPromise;
  dashboardLoadPromise=renderDashboardData();
  try{
    await dashboardLoadPromise;
  }catch(err){
    const line=document.querySelector('#dashboardRefreshStatus');
    if(line && currentRoute==='dashboard')line.textContent='Dashboard refresh failed: '+err.message+' · Showing previously loaded values.';
    throw err;
  }finally{
    dashboardLoadPromise=null;
  }
}

async function renderDashboardData() {
  const d = await apiFetch('/api/dashboard');
  lastDashboardCheck=Date.now();
  const statusLine=document.querySelector('#dashboardRefreshStatus');
  if(statusLine && currentRoute==='dashboard'){
    statusLine.textContent='Dashboard checked '+new Date(lastDashboardCheck).toLocaleTimeString()+' · Auto-refresh every 45 seconds while this tab is active. Job feeds require separate manual refresh.';
  }
  const s = d.summary;

  const sourceText = Object.entries(d.market.sources || {}).map(([k,v]) => `${k}: ${v}`).join(' · ');
  const atsConfigured = (d.market.source_analytics || []).filter(function(x){
    return x.mode === 'Employer ATS' && x.status === 'configured';
  }).length;
  const syncedAt=d.market.last_sync?new Date(d.market.last_sync).getTime():0;
  const marketStale=!syncedAt || Date.now()-syncedAt>12*60*60*1000;
  document.querySelector('#marketStatus').textContent =
    d.market.live
      ? (d.cv.uploaded
          ? `CV-filtered market · ${d.market.relevant_jobs} relevant of ${d.market.total_jobs} tracked · ${sourceText || 'Current feeds'} · ATS sources configured: ${atsConfigured} · Last sync ${fmtDate(d.market.last_sync)}`
          : `Live PostgreSQL snapshot · ${sourceText || 'Current feeds'} · ATS sources configured: ${atsConfigured}/3 · Last sync ${fmtDate(d.market.last_sync)}`)
      : 'No stored jobs yet. Click “Refresh Current Jobs”.';
  if(d.market.live && marketStale){
    document.querySelector('#marketStatus').textContent += ' · Cached jobs may be stale; refresh sources when ready.';
  }

  const atsValue = s.ats_score == null ? '—' : `${Math.round(s.ats_score)} / 100`;
  const statuses=d.pipeline || {};
  const awaiting=(statuses.Applied||0)+(statuses.Screening||0);
  const metrics = [
    ['💼', d.cv.uploaded ? 'Relevant Jobs' : 'Tracked Jobs', s.active_jobs, `From ${s.total_market_jobs} stored vacancies`],
    ['🆕', 'Posted Today', s.new_today, 'Based on available posting dates'],
    ['➤', 'Applications Tracked', s.applications, 'Including closed / rejected records'],
    ['✉', 'Awaiting Replies', awaiting, 'Applied or screening'],
    ['👥', 'Interview Stages', s.interviews, 'Interview, final and offers'],
    ['↘', 'Rejections', statuses.Rejected||0, 'Kept in application history'],
    ['🏆', 'Offers', s.offers, 'Confirmed tracker status'],
    ['▤', 'ATS Readiness', atsValue, d.cv.uploaded ? `✓ ${d.cv.ats.status}` : 'Upload CV to calculate'],
  ];
  document.querySelector('#metrics').innerHTML = metrics.map((m,i)=>`
    <div class="metric card ${i===7?'atsMini':i===5?'dashboardMetricBad':''}">
      <div class="metricIcon">${m[0]}</div>
      <div><small>${m[1]}</small><b>${m[2]}</b><span>${esc(m[3])}</span></div>
    </div>`).join('');

  try {
    const action=await apiFetch('/api/action-center');
    document.querySelector('#actionCenterQuick').innerHTML=
      '<div class="panelHead"><h3>★ Job Action Center</h3><button id="openActionCenter" class="primary">Open Action Queue</button></div>'+
      '<p><b>'+action.apply_now+'</b> jobs to apply · <b>'+action.review+'</b> to review · <b>'+action.followups.length+'</b> follow-ups due</p>'+
      '<small>Includes opportunity ranking, CV-tailoring suggestions and follow-up drafts. All applications require your approval.</small>';
    document.querySelector('#openActionCenter').onclick=function(){routeTo('action-center');};
  }catch(err){
    document.querySelector('#actionCenterQuick').textContent='Action Center is temporarily unavailable.';
  }

  const matchesHtml = d.matches.length ? d.matches.map(m => {
    const score = m.match == null ? '<span class="noScore">Upload CV<br>to score</span>' : ring(Math.round(m.match),'Match');
    const matched = (m.matched_skills || []).slice(0,4);
    const visibleSkills = matched.length ? matched : (m.skills || []).slice(0,4);
    const skills = visibleSkills.map(x=>`<span class="tag">${esc(x)}</span>`).join('');
    const roles = (m.job_role_families || []).slice(0,2).map(x=>`<span class="roleTag">${esc(humanRoleFamily(x))}</span>`).join('');
    return `<div class="job">
      <div class="company">${esc(m.company).slice(0,2).toUpperCase()}</div>
      <div class="grow">
        <a class="jobTitle" href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.title)}</a>
        <small>${esc(m.company)} · ${esc(m.location)}</small>
        <div>${skills}${roles}<span class="sourceTag">${esc(m.source)}</span></div>
        ${m.url ? `<a class="applyBtn" href="${esc(m.url)}" target="_blank" rel="noopener">Apply on source ↗</a>` : ''}
      </div>
      ${score}
    </div>`;
  }).join('') : empty(d.cv.uploaded ? 'No strong CV-relevant jobs in the current snapshot. Refresh the feeds.' : 'No live jobs yet. Refresh the feeds.');
  document.querySelector('#matches').innerHTML = head(d.cv.uploaded ? 'Best Current Matches for Your CV' : 'Latest Relevant Jobs') + matchesHtml;

  if (d.cv.uploaded) {
    const profileSkills = d.profile.top_skills || [];
    const maxCv = Math.max(...profileSkills.map(x=>x.cv_count), 1);
    document.querySelector('#skills').innerHTML =
      head('Your Top Skills + Current Demand','<span class="tag">CV-first</span>') +
      (profileSkills.length ? `<div class="bars">${profileSkills.map(x=>`
        <div class="skillRow">
          <div class="skillName"><b>${esc(x.skill)}</b><small>CV mentions: ${x.cv_count} · In relevant jobs: ${x.market_count}</small></div>
          <div class="skillBar"><i style="width:${Math.max(8,x.cv_count/maxCv*100)}%"></i></div>
        </div>
      `).join('')}</div>
      <div class="roleSummary"><b>Target role families</b><div>${(d.profile.role_families||[]).map(x=>`<span class="roleTag">${esc(humanRoleFamily(x))}</span>`).join('')}</div></div>`
      : empty('No skills detected from the uploaded CV.'));
  } else {
    const max = Math.max(...d.top_skills.map(x=>x.count), 1);
    document.querySelector('#skills').innerHTML = head('Top Skills in Current Jobs') +
      (d.top_skills.length ? `<div class="bars">${d.top_skills.map(x=>`
        <div class="barItem"><span>${esc(x.skill)}</span><div><i style="width:${Math.max(5,x.count/max*100)}%"></i></div><b>${x.count}</b></div>
      `).join('')}</div>` : empty('No market data yet.'));
  }

  document.querySelector('#pipeline').innerHTML =
    `<div class="panelHead"><h3>Application Pipeline</h3><span class="pill info">Gmail + manual statuses</span></div>
     <div class="pipeline">${['Saved','Applied','Screening','Interview','Final','Offer','Rejected'].map(x=>`
       <div><div class="dot">${d.pipeline[x]||0}</div><small>${x}</small></div>`).join('')}</div>
     <button id="addApp" class="primary">＋ Add application</button>`;

  if (d.cv.uploaded) {
    const a = d.cv.ats;
    const suggestions = (a.suggestions || []).slice(0,3).map(x=>`<li>△ ${esc(x)}</li>`).join('');
    document.querySelector('#ats').innerHTML = head('ATS CV Check') + `
      <div class="atsBody">
        ${ring(a.score,'ATS')}
        <div class="atsCopy">
          <span class="pill ${a.score>=80?'good':'warn'}">✓ ${esc(a.status)}</span>
          <p><b>${esc(d.cv.filename)}</b><br>${esc(a.score_type || 'ATS Readiness')} · Uploaded ${fmtDate(d.cv.uploaded_at)}</p>
          <p>${a.skills_detected.length} skills detected · Generic keyword coverage ${a.keyword_coverage}%</p>
        </div>
      </div>
      <ul class="atsList"><li>✓ CV is machine-readable</li><li>✓ Core sections ${esc(a.sections_complete)}</li><li>ℹ Job-specific match is scored separately</li>${suggestions}</ul>
      <div class="uploadRow">
        <input id="cvFile" type="file" accept=".pdf,.docx,.txt">
        <button id="uploadCv" class="secondary">Replace CV</button>
      </div>`;
  } else {
    document.querySelector('#ats').innerHTML = head('ATS CV Check') + `
      <div class="cvEmpty">
        <b>Upload your real CV</b>
        <p>PDF, DOCX or TXT. JobIntel will rank your skills, check ATS readiness and use the CV to filter current jobs.</p>
        <input id="cvFile" type="file" accept=".pdf,.docx,.txt">
        <button id="uploadCv" class="primary">Upload & Analyze CV</button>
      </div>`;
  }

  const conversion = d.conversion || {};
  const conversionHtml = conversion.submitted ? `
    <div class="conversionStats">
      <div><b>${conversion.positive_response_rate}%</b><small>Positive response</small></div>
      <div><b>${conversion.interview_rate}%</b><small>Interview rate</small></div>
      <div><b>${conversion.rejection_rate}%</b><small>Rejection rate</small></div>
    </div>
    <div class="conversionDiagnosis">
      ${(conversion.recommendations || []).map(x=>`<p>→ ${esc(x)}</p>`).join('')}
    </div>` : '';
  document.querySelector('#performance').innerHTML =
    head('Application Conversion','<span class="tag">Outcome-driven</span>') +
    conversionHtml +
    (d.performance.length ? d.performance.map(p=>`
      <div class="perf"><span>${esc(p.label)}</span><div class="progress"><i style="width:${p.value}%"></i></div><b>${p.value}%</b></div>
      <small class="muted">${p.applications} applications</small>`).join('')
      : empty('No performance history yet. Add applications and update their status as you progress.'));

  document.querySelector('#gaps').innerHTML = head('Skill Gap for CV-Relevant Jobs') +
    (d.skill_gap.length ? d.skill_gap.map(x=>`
      <div class="gap"><b>${esc(x.skill)}</b><span class="pill warn">${x.market_count||0} jobs</span><small>${x.required_count||0} required · ${x.preferred_count||0} preferred</small><small>${esc(x.action)}</small></div>`).join('')
      : empty(d.cv.uploaded ? 'No clear repeated gap in your filtered job set.' : 'Upload your CV to calculate real skill gaps.'));

  document.querySelector('#readiness').innerHTML = head('Interview Readiness') +
    (d.cv.uploaded ? `
      <div class="ready">${ring(d.interview_readiness.score,'Avg. top matches')}<div>
        <span class="pill good">${esc(d.interview_readiness.level)}</span>
        <p>Average of your strongest CV-relevant current job matches. This is not an interview probability.</p>
      </div></div>`
      : empty('Upload your CV first. JobIntel will then calculate readiness from CV-relevant live roles.'));

  document.querySelector('#followups').innerHTML = head('Follow-ups') +
    (d.followups.length ? `<div class="followBig">🔔 <b>${d.followups.length}</b><span>applications need attention</span></div>` +
      d.followups.map(f=>`<div class="follow"><div><b>${esc(f.role)}</b><small>${esc(f.company)} · ${esc(f.status)} · ${f.days} days</small></div><span class="pill warn">Review</span></div>`).join('')
      : empty('No follow-ups due right now.'));

  document.querySelector('#suggestions').innerHTML = head('✨ AI Improvement Suggestions') +
    `<div class="suggestGrid">${d.ai_suggestions.map((x,i)=>`
      <div class="suggest"><div class="suggestIcon">${['◉','◎','▤','☁'][i]||'✦'}</div><b>${esc(x.title)}</b><small>${esc(x.detail)}</small></div>`).join('')}</div>`;

  document.querySelector('#addApp').onclick = () => document.querySelector('#modal').classList.remove('hidden');
  document.querySelector('#uploadCv').onclick = uploadCv;
}

async function uploadCv() {
  const file = document.querySelector('#cvFile')?.files?.[0];
  if (!file) { alert('Please choose your CV file first.'); return; }
  const button = document.querySelector('#uploadCv');
  button.disabled = true;
  button.textContent = 'Analyzing…';
  try {
    const form = new FormData();
    form.append('file', file);
    const result = await apiFetch('/api/cv/upload', {method:'POST', body:form});
    alert(`CV analyzed: ATS Readiness ${result.ats.score}/100. ${result.jobs_rescored} current jobs rescored and filtered.`);
    await load();
  } catch (err) {
    alert(`CV upload failed: ${err.message}`);
  } finally {
    button.disabled = false;
  }
}

async function refreshJobs() {
  const button = document.querySelector('#refreshJobs');
  button.disabled = true;
  button.textContent = '↻ Refreshing…';
  try {
    const result = await apiFetch('/api/jobs/sync?force=true', {method:'POST'});
    const publicErrors = result.errors?.length ? result.errors : [];
    const atsErrors = result.ats_collectors?.errors?.length ? result.ats_collectors.errors : [];
    const allErrors = publicErrors.concat(atsErrors);
    const atsCount = result.ats_collectors?.fetched || 0;
    const errorText = allErrors.length ? ` Some sources reported: ${allErrors.join(', ')}` : '';
    alert(`Stored ${result.stored} current jobs. Employer ATS added/refreshed ${atsCount} jobs.${errorText}`);
    if(currentRoute === 'dashboard') await load();
    if(currentRoute === 'job-market') await renderJobMarket(false);
    if(currentRoute === 'action-center') await renderActionCenter();
  } catch (err) {
    alert(`Job refresh failed: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = '↻ Refresh Current Jobs';
  }
}

async function ask() {
  const input = document.querySelector('#chatInput');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';
  const msgs = document.querySelector('#messages');
  msgs.innerHTML += `<div class="bubble me">${esc(q)}</div>`;
  try {
    const j = await apiFetch('/api/assistant', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:q})
    });
    msgs.innerHTML += `<div class="bubble ai">${esc(j.answer)}</div>`;
  } catch (err) {
    msgs.innerHTML += `<div class="bubble ai">Assistant error: ${esc(err.message)}</div>`;
  }
  msgs.scrollTop = msgs.scrollHeight;
}

document.querySelector('#closeTailorModal').onclick=function(){document.querySelector('#tailorModal').classList.add('hidden');};
document.querySelector('#copyTailorDraft').onclick=async function(){
  try{await navigator.clipboard.writeText(document.querySelector('#tailorDraft').value);this.textContent='Copied ✓';}
  catch(err){alert('Copy unavailable; select the text manually.');}
};
document.querySelector('#refreshJobs').onclick = refreshJobs;
document.querySelector('#sendChat').onclick = ask;
document.querySelector('#chatInput').onkeydown = e => { if (e.key === 'Enter') ask(); };
document.querySelector('#closeModal').onclick = () => document.querySelector('#modal').classList.add('hidden');
document.querySelector('#appForm').onsubmit = async e => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target).entries());
  f.match_score = Number(f.match_score || 0);
  try {
    await apiFetch('/api/applications', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(f)
    });
    document.querySelector('#modal').classList.add('hidden');
    e.target.reset();
    await load();
  } catch (err) {
    alert(`Application could not be saved: ${err.message}`);
  }
};

boot();


function initials(name){
  return (name || 'U').split(/\s+/).filter(Boolean).slice(0,2).map(function(x){return x[0].toUpperCase();}).join('');
}

function closeAccountMenu(){
  const menu=document.querySelector('#accountMenu');
  if(menu)menu.classList.add('hidden');
  const avatar=document.querySelector('#avatar');
  if(avatar)avatar.setAttribute('aria-expanded','false');
}

function toggleAccountMenu(){
  const menu=document.querySelector('#accountMenu');
  if(!menu || !currentUser)return;
  const isOpen=menu.classList.contains('hidden');
  menu.classList.toggle('hidden',!isOpen);
  document.querySelector('#avatar').setAttribute('aria-expanded',String(isOpen));
  if(isOpen)document.querySelector('#accountSettings').focus();
}

function stopClientPolling(){
  if(assistantStatusTimer){clearInterval(assistantStatusTimer);assistantStatusTimer=null;}
  if(gmailStatusWatcher){clearInterval(gmailStatusWatcher);gmailStatusWatcher=null;}
  if(dashboardPoller){clearInterval(dashboardPoller);dashboardPoller=null;}
}

function startClientPolling(){
  if(!assistantStatusTimer)assistantStatusTimer=setInterval(updateAssistantStatus,10000);
  if(!gmailStatusWatcher)gmailStatusWatcher=setInterval(autoSyncGmail,30000);
  if(!dashboardPoller)dashboardPoller=setInterval(function(){
    if(currentRoute==='dashboard' && !document.hidden && localStorage.getItem('jobintel_token')){
      load().catch(function(){});
    }
  },45000);
}

function showAuth(message){
  closeAccountMenu();
  stopClientPolling();
  document.querySelector('#authScreen').classList.remove('hidden');
  document.querySelector('#appShell').classList.add('hidden');
  if (message) document.querySelector('#authMessage').textContent = message;
}

function showApp(){
  document.querySelector('#authScreen').classList.add('hidden');
  document.querySelector('#appShell').classList.remove('hidden');
  document.querySelector('#userNameMini').textContent = currentUser.display_name;
  document.querySelector('#userEmailMini').textContent = currentUser.email;
  document.querySelector('#avatar').textContent = initials(currentUser.display_name);
  document.querySelector('#accountMenuName').textContent=currentUser.display_name;
  document.querySelector('#accountMenuEmail').textContent=currentUser.email;
  startClientPolling();
}

async function boot(){
  bindAuth();
  const token = localStorage.getItem('jobintel_token');
  if (!token) return showAuth();
  try{
    currentUser = await apiFetch('/api/auth/me');
    showApp();
    currentRoute = (location.hash || '#dashboard').slice(1);
    if (!navItems.some(function(x){return x.route===currentRoute;})) currentRoute='dashboard';
    renderNav();
    await routeTo(currentRoute, false);
    updateAssistantStatus();
    autoSyncGmail();
    if(!assistantStatusTimer){
      assistantStatusTimer = setInterval(updateAssistantStatus, 10000);
    }
    if(!gmailStatusWatcher)gmailStatusWatcher=setInterval(autoSyncGmail,30000);
  }catch(err){
    showAuth(err.message);
  }
}

function bindAuth(){
  document.querySelector('#loginTab').onclick = function(){
    document.querySelector('#loginTab').classList.add('active');
    document.querySelector('#registerTab').classList.remove('active');
    document.querySelector('#loginForm').classList.remove('hidden');
    document.querySelector('#registerForm').classList.add('hidden');
  };
  document.querySelector('#registerTab').onclick = function(){
    document.querySelector('#registerTab').classList.add('active');
    document.querySelector('#loginTab').classList.remove('active');
    document.querySelector('#registerForm').classList.remove('hidden');
    document.querySelector('#loginForm').classList.add('hidden');
  };
  document.querySelector('#loginForm').onsubmit = async function(e){
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    try{
      const result = await apiFetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
      localStorage.setItem('jobintel_token', result.token);
      currentUser = result.user;
      showApp(); renderNav(); await routeTo('dashboard'); updateAssistantStatus();
    }catch(err){ document.querySelector('#authMessage').textContent = err.message; }
  };
  document.querySelector('#registerForm').onsubmit = async function(e){
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    try{
      const result = await apiFetch('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
      localStorage.setItem('jobintel_token', result.token);
      currentUser = result.user;
      showApp(); renderNav(); await routeTo('dashboard'); updateAssistantStatus();
    }catch(err){ document.querySelector('#authMessage').textContent = err.message; }
  };
}

async function routeTo(route, updateHash=true){
  closeAccountMenu();
  currentRoute = route;
  if (updateHash) location.hash = route;
  renderNav();
  const dash = document.querySelector('#dashboardContent');
  const page = document.querySelector('#pageContent');
  const titles = {
    dashboard:['JobIntel AI','🇩🇪 Live Career Intelligence for Germany'],
    'job-market':['Job Market','All current jobs relevant to your CV'],
    'action-center':['Action Center','Apply now, CV tailoring and recruiter follow-ups'],
    applications:['My Applications','Track every application and outcome'],
    ats:['ATS CV Check','CV readiness, skills and role profile'],
    matches:['Best Matches','Current jobs ranked against your CV'],
    'application-prep':['Application Preparation','Prepared application packages, screening answers and CV-grounded cover letters'],
    'interview-prep':['Interview Practice','Practice technical and behavioral questions tailored to your CV and vacancies'],
    'skill-gap':['Skill Gap','What current target jobs ask for that your CV is missing'],
    analytics:['Analytics','Your application and market performance'],
    settings:['Settings','Profile, AI assistant and data sources']
  };
  document.querySelector('#pageTitle').textContent = titles[route][0];
  document.querySelector('#pageSubtitle').textContent = titles[route][1];

  if(route==='dashboard'){
    dash.classList.remove('hidden'); page.classList.add('hidden');
    await load();
    return;
  }
  dash.classList.add('hidden'); page.classList.remove('hidden');
  page.innerHTML = '<div class="pageLoading">Loading…</div>';

  if(route==='job-market') return renderJobMarket(false);
  if(route==='action-center') return renderActionCenter();
  if(route==='applications'){
    const loaded=renderApplicationsPage();
    loaded.then(function(){
      if(currentRoute==='applications')refreshApplicationsGmailInBackground();
    }).catch(function(){});
    return loaded;
  }
  if(route==='ats') return renderAtsPage();
  if(route==='matches') return renderMatchesPage();
  if(route==='application-prep') return renderApplicationPrepPage();
  if(route==='skill-gap') return renderSkillGapPage();
  if(route==='interview-prep') return renderInterviewPracticePage();
  if(route==='analytics') return renderAnalyticsPage();
  if(route==='settings') return renderSettingsPage();
}

function jobCard(job, compact){
  const score = job.match == null ? '—' : Math.round(job.match) + '%';
  const skills = (job.matched_skills && job.matched_skills.length ? job.matched_skills : job.skills || []).slice(0,6);
  const missing = (job.missing_skills || []).slice(0,4);
  const breakdown = job.score_breakdown || {};
  const breakdownHtml = !compact && Object.keys(breakdown).length
    ? '<div class="matchBreakdownMini"><span>Role ' + Math.round(breakdown.role_alignment || 0) + '%</span><span>Required skills ' + Math.round(breakdown.required_skills || 0) + '%</span><span>Experience ' + Math.round(breakdown.experience || 0) + '%</span><span>Language ' + Math.round(breakdown.language || 0) + '%</span></div>'
    : '';
  return '<article class="marketJob card">' +
    '<div class="marketJobTop"><div><span class="sourceTag">' + esc(job.source) + '</span>' +
    '<h3>' + esc(job.title) + '</h3><p>' + esc(job.company) + ' · ' + esc(job.location) + '</p></div>' +
    '<div class="scoreBadge">' + score + '<small>match</small></div></div>' +
    '<div class="tagRow">' + skills.map(function(s){return '<span class="tag">' + esc(s) + '</span>';}).join('') + '</div>' +
    (job.opportunity ? '<p class="opportunityLine"><b>Opportunity '+Math.round(job.opportunity.score)+'/100</b> · '+esc(job.opportunity.decision)+' · '+esc(job.opportunity.track)+(job.opportunity.age_days!=null?' · '+job.opportunity.age_days+'d old':'')+'</p>' : '') +
    (job.opportunity&&job.opportunity.eligibility?'<p class="eligibilityLine"><b>Eligibility:</b> '+esc(job.opportunity.eligibility.status)+' · '+esc(job.opportunity.eligibility.seniority)+' · '+esc(job.opportunity.eligibility.employment_type)+'</p>'+((job.opportunity.eligibility.needs_confirmation||[]).length?'<p class="muted">Verify: '+job.opportunity.eligibility.needs_confirmation.map(esc).join('; ')+'</p>':''):'') +
    breakdownHtml +
    (!compact && missing.length ? '<p class="missingLine"><b>Missing:</b> ' + missing.map(esc).join(', ') + '</p>' : '') +
    (!compact && job.hard_blockers && job.hard_blockers.length ? '<p class="blockerLine"><b>Review:</b> ' + job.hard_blockers.map(esc).join(' ') + '</p>' : '') +
    '<div class="jobActions">' +
      (job.url ? '<a class="primaryLink" target="_blank" rel="noopener" href="' + esc(job.url) + '">Apply on source ↗</a>' : '') +
      '<button class="secondary coverLetterBtn" data-job-id="' + job.id + '">Create cover letter</button>' +
      '<button class="secondary tailorCvBtn" data-job-id="' + job.id + '">Tailor CV</button>' +
      '<button class="primary guidedApplyBtn" data-job-id="' + job.id + '">Assisted Apply</button>' +
      '<button class="secondary atsReviewBtn" data-job-id="' + job.id + '">ATS Review</button>' +
      '<button class="secondary startPracticeBtn" data-job-id="' + job.id + '">Interview Prep</button>' +
      '<button class="secondary prepareApplicationBtn" data-job-id="' + job.id + '">Prepare application</button>' +
      '<button class="secondary trackJob" data-job-id="' + job.id + '">Track application</button>' +
    '</div></article>';
}

function bindTrackButtons(){
  document.querySelectorAll('.startPracticeBtn').forEach(function(button){
    button.onclick=async function(){
      button.disabled=true;
      button.textContent='Preparing questions…';
      try{
        const item=await apiFetch('/api/jobs/'+button.dataset.jobId+'/interview-practice',{method:'POST'});
        await routeTo('interview-prep');
        await openInterviewPractice(item.id);
      }catch(err){alert('Could not start interview practice: '+err.message);}
      finally{button.disabled=false;button.textContent='Interview Prep';}
    };
  });
  document.querySelectorAll('.guidedApplyBtn').forEach(function(button){
    button.onclick=function(){
      const job=jobMarketCache.find(function(item){return String(item.id)===String(button.dataset.jobId);});
      if(job)openAssistModal(job);
    };
  });
  document.querySelectorAll('.trackJob').forEach(function(button){
    button.onclick = function(){
      const job = jobMarketCache.find(function(x){return String(x.id)===String(button.dataset.jobId);});
      if(job) openApplicationModal(job);
    };
  });

  document.querySelectorAll('.coverLetterBtn').forEach(function(button){
    button.onclick = function(){
      downloadCoverLetter(button.dataset.jobId, button);
    };
  });

  document.querySelectorAll('.atsReviewBtn').forEach(function(button){
    button.onclick=function(){showAtsReview(button.dataset.jobId);};
  });
  document.querySelectorAll('.tailorCvBtn').forEach(function(button){
    button.onclick=function(){showTailorCv(button.dataset.jobId);};
  });
  document.querySelectorAll('.prepareApplicationBtn').forEach(function(button){
    button.onclick = function(){
      prepareApplication(button.dataset.jobId, button);
    };
  });
}

async function downloadCoverLetter(jobId, button){
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = 'Generating cover letter…';

  try{
    const payload = await apiFetch('/api/jobs/' + jobId + '/cover-letter', {
      method: 'POST'
    });

    if(!payload.content_base64){
      throw new Error('The generated document was empty.');
    }

    const binary = atob(payload.content_base64);
    const bytes = new Uint8Array(binary.length);
    for(let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);

    const blob = new Blob(
      [bytes],
      {type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
    );
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = payload.filename || 'JobIntel_Cover_Letter.docx';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function(){ URL.revokeObjectURL(downloadUrl); }, 1500);

    button.textContent = payload.generator === 'ollama' ? 'AI letter downloaded ✓' : 'Letter downloaded ✓';
    setTimeout(function(){ button.textContent = originalText; }, 1800);
  }catch(err){
    alert('Cover letter could not be created: ' + err.message);
    button.textContent = originalText;
  }finally{
    button.disabled = false;
  }
}

async function prepareApplication(jobId, button, cvId=null){
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = 'Preparing…';
  try{
    const prepared = await apiFetch('/api/jobs/' + jobId + '/prepare-application', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({minimum_match:70,cv_id:cvId})
    });
    button.textContent = prepared.status === 'Package Ready' ? 'Package ready ✓' : 'Needs review ✓';
    setTimeout(function(){ button.textContent = originalText; }, 1600);
    await routeTo('application-prep');
  }catch(err){
    alert('Application package could not be prepared: ' + err.message);
    button.textContent = originalText;
  }finally{
    button.disabled = false;
  }
}

async function downloadPackageCoverLetter(packageId, button){
  const original = button.textContent;
  button.disabled = true;
  button.textContent = 'Preparing download…';
  try{
    const payload = await apiFetch('/api/application-packages/' + packageId + '/cover-letter', {method:'POST'});
    const binary = atob(payload.content_base64 || '');
    if(!binary) throw new Error('The prepared cover letter is empty.');
    const bytes = new Uint8Array(binary.length);
    for(let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
    const blob = new Blob([bytes], {type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = payload.filename || 'Prepared_Cover_Letter.docx';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function(){ URL.revokeObjectURL(url); }, 1500);
  }catch(err){
    alert('Prepared cover letter could not be downloaded: ' + err.message);
  }finally{
    button.disabled=false;
    button.textContent=original;
  }
}

function openApplicationModal(job){
  const form = document.querySelector('#appForm');
  form.elements.company.value = job ? job.company : '';
  form.elements.role.value = job ? job.title : '';
  form.elements.location.value = job ? job.location : 'Germany';
  form.elements.url.value = job ? job.url : '';
  form.elements.match_score.value = job && job.match != null ? Math.round(job.match) : 0;
  form.elements.cv_version.value = 'Current CV';
  document.querySelector('#modal').classList.remove('hidden');
}

async function renderJobMarket(includeAll){
  jobMarketCache = await apiFetch('/api/jobs?limit=500&include_all=' + (includeAll?'true':'false'));
  const page = document.querySelector('#pageContent');
  page.innerHTML =
    '<div class="pageToolbar card"><div><b>' + jobMarketCache.length + ' jobs</b><small>' + (includeAll?'All tracked technical jobs':'CV-relevant jobs') + '</small></div>' +
    '<input id="jobSearch" placeholder="Search title, company, location or skill">' +
    '<select id="sourceFilter"><option value="">All sources</option></select>' +
    '<select id="matchFilter"><option value="0">Any match</option><option value="60">60%+</option><option value="70">70%+</option><option value="80">80%+</option></select>' +
    '<button id="toggleMarket" class="secondary">' + (includeAll?'Show CV-relevant':'Show all tracked') + '</button>' +
    '<button id="openImport" class="primary">＋ Import job</button></div>' +
    '<div id="marketCount" class="resultCount"></div><div id="jobMarketGrid" class="jobMarketGrid"></div>';
  const sources = Array.from(new Set(jobMarketCache.map(function(x){return x.source;}))).sort();
  document.querySelector('#sourceFilter').innerHTML += sources.map(function(s){return '<option>' + esc(s) + '</option>';}).join('');
  function draw(){
    const q = document.querySelector('#jobSearch').value.toLowerCase();
    const source = document.querySelector('#sourceFilter').value;
    const min = Number(document.querySelector('#matchFilter').value);
    const rows = jobMarketCache.filter(function(j){
      const hay = [j.title,j.company,j.location,(j.skills||[]).join(' ')].join(' ').toLowerCase();
      return (!q || hay.includes(q)) && (!source || j.source===source) && ((j.match||0)>=min);
    });
    document.querySelector('#marketCount').textContent = 'Showing ' + rows.length + ' of ' + jobMarketCache.length;
    document.querySelector('#jobMarketGrid').innerHTML = rows.map(function(j){return jobCard(j,false);}).join('') || '<div class="empty">No jobs match these filters.</div>';
    bindTrackButtons();
  }
  ['jobSearch','sourceFilter','matchFilter'].forEach(function(id){document.querySelector('#'+id).oninput=draw;});
  document.querySelector('#toggleMarket').onclick=function(){renderJobMarket(!includeAll);};
  document.querySelector('#openImport').onclick=function(){document.querySelector('#importModal').classList.remove('hidden');};
  draw();
}

const ASSIST_BASE='http://127.0.0.1:3401';
let activeAssistJob=null;
let lastAssistStatus=null;
let activeAssistVaultDocs={};
let activeAssistDraftReady=false;


async function assistRequest(path,body){
  const config={method:body===undefined?'GET':'POST',headers:{"X-JobIntel-Assistant":"1"}};
  if(body!==undefined){
    config.headers["Content-Type"]="application/json";
    config.body=JSON.stringify(body);
  }
  let response;
  try{response=await fetch(ASSIST_BASE+path,config);}
  catch(err){throw new Error('Local browser assistant is offline. Open a Mac terminal in browser-assistant, then run npm install, npx playwright install chromium, and npm start.');}
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'Local browser assistant error');
  return result;
}

async function assistDocument(file){
  if(!file)return null;
  if(file.size>8*1024*1024)throw new Error('Each attachment must be 8 MB or less.');
  if(!/\.(pdf|doc|docx|txt)$/i.test(file.name))throw new Error('Only PDF, DOC, DOCX or TXT attachments are supported.');
  const bytes=new Uint8Array(await file.arrayBuffer());
  let binary='';
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return {name:file.name,mimeType:file.type||'application/octet-stream',base64:btoa(binary)};
}
function assistMessage(msg){
  document.querySelector('#assistMessage').textContent=msg;
}
function assistReview(status){
  lastAssistStatus=status;
  const target=document.querySelector('#assistReview');
  if(!status||!status.active){target.textContent='No active session.';return;}
  const fields=status.fields||[];
  const links=(status.applicationLinks||[]);
  target.innerHTML='<b>Employer browser: '+esc(status.title||'Application form')+'</b>'+
    '<p>Stage: '+esc(status.stage||status.status)+' · '+fields.length+' detected fields · '+fields.filter(function(x){return x.filled;}).length+' filled</p>'+
    '<a target="_blank" rel="noopener" href="'+esc(status.url)+'">Current browser page ↗</a>'+
    (status.consentRequired?'<p class="assistNotice">Cookie/privacy consent detected. Review your preferences directly in Chromium; JobIntel will not accept automatically.</p>':'')+
    (links.length?'<div class="assistHandoff"><label>Employer application link<select id="assistLinkSelect">'+
      links.map(function(x){return '<option value="'+esc(x.url)+'">'+esc(x.title)+' — '+esc(new URL(x.url).hostname)+'</option>';}).join('')+
      '</select></label><button id="assistOpenEmployer" type="button" class="primary">Open Actual Application Form →</button></div>':'')+
    '<h4>Fields to review</h4><ul>'+
    fields.filter(function(x){return x.required&&!x.filled||x.type==='file'&&!x.filled;}).slice(0,16).map(function(x){
      return '<li>'+esc(x.label||x.name||x.id||x.type)+' '+(x.required?'(required)':'')+(x.kind?' — '+esc(x.kind):'')+'</li>';
    }).join('')+'</ul>'+
    '<p>'+esc((status.notes||[]).slice(-3).join(' | '))+'</p>'+
    (status.submissionAttempted?'<p><b>Submission was attempted. Verify employer confirmation before recording as Applied.</b></p>':'');
  const open=document.querySelector('#assistOpenEmployer');
  if(open)open.onclick=async function(){
    const url=document.querySelector('#assistLinkSelect').value;
    const selected=links.find(function(item){return item.url===url;});
    if(!selected || !confirm('Open '+new URL(selected.url).hostname+' in the Playwright browser? Confirm the company and vacancy before uploading documents.'))return;
    open.disabled=true;
    try{
      assistMessage('Opening the employer application form...');
      const next=await assistRequest('/open-application',{url:selected.url});
      assistReview(next);
      assistMessage('Employer application opened. Inspect the actual form, then Fill Known Fields & Attach.');
    }catch(err){assistMessage(err.message);open.disabled=false;}
  };
}
async function primeAssistedApplication(job){
  const form=document.querySelector('#assistStartForm');
  const start=form.querySelector('button[type=submit]');
  const documentInfo=document.querySelector('#assistDocInfo');
  const draftBox=document.querySelector('#assistGeneratedLetter');
  const useDraft=document.querySelector('#assistIncludeLetter');
  start.disabled=true;
  activeAssistVaultDocs={};
  activeAssistDraftReady=false;
  draftBox.value='';
  useDraft.checked=false;
  documentInfo.textContent='Loading verified candidate profile and saved documents…';
  try{
    const [profile,selection]=await Promise.all([
      apiFetch('/api/candidate-profile'),
      apiFetch('/api/documents/selected?job_id='+encodeURIComponent(job.id))
    ]);
    if(activeAssistJob!==job)return;
    for(const key of ['firstName','lastName','email','phone','city','country','linkedin','github','portfolio']){
      if(form.elements[key] && profile[key])form.elements[key].value=profile[key];
    }
    activeAssistVaultDocs=selection.documents||{};
    const chosen=activeAssistVaultDocs.cv;
    documentInfo.textContent=chosen?
      'Saved CV: '+chosen.filename+' ('+selection.role_family+') ·'+
      (activeAssistVaultDocs.experience?' experience letter available':' no experience letter saved'):
      'No saved original CV file. Select a CV override below or upload it once in Settings → Private document vault.';
    start.disabled=false;
    // Draft generation can take longer with the local Ollama model; do not
    // block browser interaction or upload the draft without user review.
    try{
      const cv_id=chosen&&chosen.cv_profile_id;
      const result=await apiFetch('/api/jobs/'+job.id+'/prepare-application',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({minimum_match:0,...(cv_id?{cv_id}:{} )})
      });
      if(activeAssistJob!==job)return;
      draftBox.value=result.cover_letter_text||'';
      activeAssistDraftReady=Boolean(draftBox.value.trim());
      useDraft.checked=activeAssistDraftReady;
      assistMessage(activeAssistDraftReady?
        'Candidate documents loaded and tailored cover letter prepared. Review or edit the letter before attaching.':
        'Candidate documents loaded. Write or upload a cover letter if requested.');
    }catch(err){
      if(activeAssistJob===job)assistMessage(
        'Saved profile ready. Letter generation unavailable: '+err.message+
        '. You can continue and upload a letter manually.');
    }
  }catch(err){
    if(activeAssistJob===job){
      documentInfo.textContent='Vault/profile unavailable: '+err.message+'; select the CV file manually.';
      start.disabled=false;
    }
  }
}

function openAssistModal(job){
  if(!job.url){alert('This opportunity has no application link.');return;}
  activeAssistJob=job;lastAssistStatus=null;
  document.querySelector('#assistModal').classList.remove('hidden');
  document.querySelector('#assistStartForm').classList.remove('hidden');
  document.querySelector('#assistWorkspace').classList.add('hidden');
  const form=document.querySelector('#assistStartForm');
  form.reset();
  const parts=(currentUser.display_name||'').trim().split(/\s+/);
  form.elements.firstName.value=parts[0]||'';
  form.elements.lastName.value=parts.slice(1).join(' ')||'';
  form.elements.email.value=currentUser.email||'';
  form.elements.country.value='Germany';
  document.querySelector('#assistJobTitle').textContent=job.title+' · '+job.company;
  assistMessage('Loading saved CV, verified profile and tailored cover letter…');
  primeAssistedApplication(job);
}
function bindAssistedApply(){
  document.querySelector('#assistCloseModal').onclick=function(){
    document.querySelector('#assistModal').classList.add('hidden');
  };
  document.querySelector('#assistStartForm').onsubmit=async function(event){
    event.preventDefault();
    const form=event.currentTarget;
    const button=form.querySelector('button[type=submit]');
    button.disabled=true;assistMessage('Starting local Chromium. This may take a few seconds...');
    try{
      const fd=new FormData(form);
      const profile={};
      ['firstName','lastName','email','phone','city','country','linkedin','github','portfolio'].forEach(function(key){
        profile[key]=String(fd.get(key)||'').trim();
      });
      const documents={};
      for(const kind of ['cv','cover','experience']){
        const file=fd.get(kind);
        if(file&&file.size)documents[kind]=await assistDocument(file);
      }
      // User-selected override always takes precedence over a saved document.
      for(const kind of ['cv','experience','cover']){
        const saved=activeAssistVaultDocs[kind];
        if(!documents[kind]&&saved&&!(kind==='cover'&&
             document.querySelector('#assistIncludeLetter').checked&&activeAssistDraftReady)){
          documents[kind]=await apiFetch('/api/documents/'+saved.id+'/content');
        }
      }
      const draftText=document.querySelector('#assistGeneratedLetter').value.trim();
      if(!documents.cover&&draftText&&document.querySelector('#assistIncludeLetter').checked){
        documents.cover=await apiFetch('/api/jobs/'+activeAssistJob.id+'/cover-letter-render',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({text:draftText})
        });
      }
      if(!documents.cv)throw new Error('No original CV file is available. Upload it once in Settings → Private document vault, or select a CV override here.');
      const status=await assistRequest('/start',{url:activeAssistJob.url,profile,documents});
      form.classList.add('hidden');
      document.querySelector('#assistWorkspace').classList.remove('hidden');
      assistReview(status);assistMessage('Chromium opened. Review the form, then click Fill Known Fields.');
    }catch(err){assistMessage(err.message);}
    finally{button.disabled=false;}
  };
  for(const item of [
    ['#assistInspect','/status','Inspect'],
    ['#assistFill','/fill','Fill Known Fields'],
    ['#assistNext','/next','Next / Continue']
  ]){
    const btn=document.querySelector(item[0]);
    btn.onclick=async function(){
      btn.disabled=true;
      try{
        const status=await assistRequest(item[1],item[1]==='/status'?undefined:{});
        assistReview(status);
        assistMessage(item[2]+' completed. Review the visible employer page and unresolved fields.');
      }catch(err){assistMessage(err.message);}
      finally{btn.disabled=false;}
    };
  }
  document.querySelector('#assistSubmit').onclick=async function(){
    const approval=document.querySelector('#assistApproval').value;
    if(approval!=='SUBMIT'){assistMessage('Type exactly SUBMIT in the approval field.');return;}
    if(!confirm('Submit this application to the employer now? Check every form answer and uploaded document first.'))return;
    try{
      const status=await assistRequest('/submit',{approval});
      assistReview(status);
      assistMessage('Submit was clicked. Verify the confirmation on the employer site. Do not submit twice.');
    }catch(err){assistMessage(err.message);}
  };
  document.querySelector('#assistTrack').onclick=function(){
    if(!activeAssistJob)return;
    if(!confirm('Have you verified on the employer website that the application was submitted?'))return;
    document.querySelector('#assistModal').classList.add('hidden');
    openApplicationModal(activeAssistJob);
  };
  document.querySelector('#assistCloseBrowser').onclick=async function(){
    try{await assistRequest('/close',{});assistReview({active:false});
      document.querySelector('#assistStartForm').classList.remove('hidden');
      document.querySelector('#assistWorkspace').classList.add('hidden');
      assistMessage('Local browser closed. Uploaded documents have been cleared from worker memory.');
    }catch(err){assistMessage(err.message);}
  };
}
bindAssistedApply();

// Cache per-session lookup outcomes to avoid repeatedly querying Gmail on rerenders.
const followupContactCache = new Map();
const FOLLOWUP_CONTACT_TTL_MS = 15 * 60 * 1000;

// Gmail read-only can discover replies; sending requires separate Google consent.
async function startGmailSendAuthorization(){
  if(!confirm('Allow JobIntel to request Gmail Send access? Google will ask for permission. No email will be sent by this step.'))return false;
  try{
    const result=await apiFetch('/api/gmail/enable-send',{method:'POST'});
    if(!result.authorization_url || !result.authorization_url.startsWith('https://accounts.google.com/')){
      throw new Error('Unexpected Google authorization URL.');
    }
    const popup=window.open(result.authorization_url,'_blank','noopener,noreferrer');
    // Popup blockers may return null, even when the new tab was successfully opened.
    alert('Approve Gmail Send permission in the Google tab. Then return to JobIntel and click Check Gmail Permission. Sending still requires your confirmation.');
    return true;
  }catch(err){
    alert('Could not start Gmail Send authorization: '+err.message);
    return false;
  }
}

async function renderActionCenter(){
  const results=await Promise.all([
    apiFetch('/api/action-center'),
    apiFetch('/api/gmail/status').catch(function(){return {connected:false,can_send:false};})
  ]);
  const action=results[0],gmail=results[1];
  const page=document.querySelector('#pageContent');
  jobMarketCache=(action.opportunities||[]).map(function(row){return row.job;});
  page.innerHTML='<div class="pageIntro"><h2>Today’s Job Action Queue</h2>' +
    '<p>Apply to strong engineering matches. Every browser-assisted submission needs your approval.</p></div>' +
    '<div class="analyticsSummary">' +
    '<div class="card analyticsMini"><small>Apply Now</small><b>'+action.apply_now+'</b></div>' +
    '<div class="card analyticsMini"><small>Review</small><b>'+action.review+'</b></div>' +
    '<div class="card analyticsMini"><small>Follow-ups due</small><b>'+action.followups.length+'</b></div></div>' +
    (!action.cv_uploaded?'<div class="card detailPage"><h3>Upload your CV first</h3><p>Opportunity ranking needs evidence from your CV.</p></div>':'') +
    '<div class="pageIntro"><h3>Best current opportunities</h3></div>' +
    '<div class="jobMarketGrid">'+(jobMarketCache.map(function(job){return jobCard(job,false);}).join('')||empty('No strong matching openings in the current feed. Refresh jobs or add employer ATS collectors.'))+'</div>' +
    '<div class="pageIntro"><h3>Recruiter follow-up assistant</h3><p>JobIntel checks your connected Gmail automatically when follow-ups are due. It displays the source of every suggested address. Review the recipient and message before sending.</p></div>' +
    '<div class="followupGrid">'+(action.followups.map(function(row){
      return '<article class="card followupCard" data-app-id="'+row.application_id+'">'+
        '<h3>'+esc(row.role)+'</h3><p>'+esc(row.company)+' · '+row.days_waiting+' days waiting</p>'+
        '<label>Recruiter email address <small>(suggested automatically when supported by evidence)</small><input class="followupTo" type="email" placeholder="Find contact email below" value="'+esc((row.recipient_lookup||{}).recommended||'')+'"></label>'+
        '<div class="followupLookupActions"><button type="button" class="secondary followupFindContact">Find Contact Email</button><span class="followupLookupStatus" role="status"></span></div>'+
        '<div class="followupContactResults"></div>'+
        '<label>Email subject<input class="followupSubject" value="'+esc(row.subject)+'"></label>'+
        '<label>Editable email draft<textarea class="followupBody" rows="9">'+esc(row.body)+'</textarea></label>'+
        '<div class="prepActions">'+
        '<button type="button" class="secondary followupCopy">Copy draft</button>'+
        '<button type="button" class="primary followupSend"'+(gmail.can_send?'':' hidden')+'>Review & Send via Gmail</button>'+
        '<button type="button" class="secondary followupEnableGmail"'+(gmail.can_send?' hidden':'')+'>Enable Gmail sending</button>'+
        '<button type="button" class="secondary followupRecheckGmail"'+(gmail.can_send?' hidden':'')+'>Check Gmail Permission</button>'+
        '<button type="button" class="secondary followupSent">I sent this externally</button></div>'+
        '<small>'+(gmail.can_send?'Gmail send is authorized; no email is sent without clicking Review & Send.':'Gmail read-only remains available; enable Send separately in Settings.')+'</small>'+
        '</article>';
    }).join('')||empty('No follow-ups are due right now.'))+'</div>';
  bindTrackButtons();
  function renderContactOptions(card, lookup){
    const target=card.querySelector('.followupContactResults');
    const status=card.querySelector('.followupLookupStatus');
    const addr=card.querySelector('.followupTo');
    target.replaceChildren();
    const contacts=lookup.candidates||[];
    if(lookup.recommended && !addr.value.trim()) addr.value=lookup.recommended;
    status.textContent=lookup.warning||(
      contacts.length?contacts.length+' sourced contact(s) found. Review the address before sending.':
      'No reliable contact found yet. Do not guess an email address.'
    );
    contacts.forEach(function(contact){
      const item=document.createElement('div');
      item.className='followupContactOption';
      const detail=document.createElement('small');
      detail.textContent=contact.email+' · '+contact.source.replace(/_/g,' ')+' · '+contact.confidence+
        ' confidence · '+contact.source_detail;
      item.appendChild(detail);
      const use=document.createElement('button');
      use.type='button';
      use.className='secondary';
      use.textContent='Use this email';
      use.onclick=function(){addr.value=contact.email;status.textContent='Selected '+contact.email+'; verify the destination before sending.';};
      item.appendChild(use);
      if(contact.evidence_url && /^https:\/\//i.test(contact.evidence_url)){
        const link=document.createElement('a');
        link.href=contact.evidence_url;link.target='_blank';link.rel='noopener noreferrer';
        link.textContent='View source ↗';item.appendChild(link);
      }
      target.appendChild(item);
    });
    if(lookup.web_search_url && /^https:\/\/www\.google\.com\/search\?/i.test(lookup.web_search_url)){
      const link=document.createElement('a');
      link.href=lookup.web_search_url;link.target='_blank';link.rel='noopener noreferrer';
      link.className='followupGoogleLink';
      link.textContent='Search Google for official employer recruiting contacts ↗';
      target.appendChild(link);
    }
  }
  document.querySelectorAll('.followupCard').forEach(function(card){
    const id=Number(card.dataset.appId);
    const addr=card.querySelector('.followupTo');
    const subject=card.querySelector('.followupSubject');
    const body=card.querySelector('.followupBody');
    const current=action.followups.find(function(item){return item.application_id===id;});
    if(current && current.recipient_lookup)renderContactOptions(card,current.recipient_lookup);
    const cached=followupContactCache.get(id);
    if(cached && Date.now()-cached.at<FOLLOWUP_CONTACT_TTL_MS)renderContactOptions(card,cached.result);
    const find=card.querySelector('.followupFindContact');
    find.onclick=async function(){
      find.disabled=true;
      card.querySelector('.followupLookupStatus').textContent='Searching Gmail messages and available public sources...';
      try{
        const lookup=await apiFetch('/api/applications/'+id+'/find-contact',{method:'POST'});
        followupContactCache.set(id,{at:Date.now(),result:lookup});
        renderContactOptions(card,lookup);
      }catch(err){
        card.querySelector('.followupLookupStatus').textContent='Contact search could not complete: '+err.message;
      }finally{find.disabled=false;}
    };
    card.querySelector('.followupCopy').onclick=async function(){
      try{await navigator.clipboard.writeText('To: '+addr.value+'\nSubject: '+subject.value+'\n\n'+body.value);
        this.textContent='Copied ✓';
      }catch(err){alert('Copy unavailable; select the message text manually.');}
    };
    const enable=card.querySelector('.followupEnableGmail');
    if(enable)enable.onclick=async function(){
      enable.disabled=true;
      await startGmailSendAuthorization();
      enable.disabled=false;
    };
    const check=card.querySelector('.followupRecheckGmail');
    if(check)check.onclick=async function(){
      check.disabled=true;
      try{
        const status=await apiFetch('/api/gmail/status');
        if(!status.can_send)throw new Error('Gmail Send is not authorized yet. Complete consent in the Google tab first.');
        document.querySelectorAll('.followupSend').forEach(function(button){button.hidden=false;});
        document.querySelectorAll('.followupEnableGmail,.followupRecheckGmail').forEach(function(button){button.hidden=true;});
        document.querySelectorAll('.followupLookupStatus').forEach(function(label){
          label.textContent='Gmail Send enabled. Review the recipient before sending.';
        });
      }catch(err){
        const status=card.querySelector('.followupLookupStatus');
        status.textContent=err.message;
      }finally{check.disabled=false;}
    };
    const send=card.querySelector('.followupSend');
    if(send)send.onclick=async function(){
      const recipient=addr.value.trim();
      if(!recipient || !addr.checkValidity()){alert('Enter one verified recruiter email address first.');return;}
      if(!subject.value.trim()||!body.value.trim()){alert('Review subject and message first.');return;}
      if(!confirm('Send this exact message from your connected Gmail account to '+recipient+'?'))return;
      send.disabled=true;
      try{
        await apiFetch('/api/applications/'+id+'/send-follow-up',{method:'POST',
          headers:{'Content-Type':'application/json'},body:JSON.stringify({
            recipient,subject:subject.value.trim(),body:body.value.trim()
          })});
        alert('Gmail accepted the message. You can verify it in your Sent folder.');
        await renderActionCenter();
      }catch(err){alert('Gmail send did not complete: '+err.message);send.disabled=false;}
    };
    card.querySelector('.followupSent').onclick=async function(){
      if(!confirm('Confirm you already sent this follow-up outside JobIntel?'))return;
      try{await apiFetch('/api/applications/'+id+'/follow-up-sent',{method:'POST'});
        await renderActionCenter();
      }catch(err){alert('Could not record follow-up: '+err.message);}
    };
  });

  // Run real server-side Gmail searches automatically without blocking the job queue.
  // Limit concurrency to protect Gmail quotas and avoid repeated requests on rerender.
  if(gmail.connected){
    const due=action.followups.filter(function(row){
      const cached=followupContactCache.get(row.application_id);
      if(cached && Date.now()-cached.at<FOLLOWUP_CONTACT_TTL_MS)return false;
      // Strong saved employer-domain evidence already provides a recipient.
      return !(row.recipient_lookup && row.recipient_lookup.recommended);
    }).slice(0,10);
    let nextIndex=0;
    async function lookupWorker(){
      while(nextIndex<due.length){
        const row=due[nextIndex++];
        const card=page.querySelector('.followupCard[data-app-id="'+row.application_id+'"]');
        if(!card)continue;
        const status=card.querySelector('.followupLookupStatus');
        status.textContent='Searching Gmail automatically for an employer reply address...';
        try{
          const lookup=await apiFetch('/api/applications/'+row.application_id+'/find-contact',{method:'POST'});
          followupContactCache.set(row.application_id,{at:Date.now(),result:lookup});
          // Navigation may have replaced the Action Center; don't update stale cards.
          if(card.isConnected)renderContactOptions(card,lookup);
        }catch(err){
          if(card.isConnected)status.textContent='Automatic lookup failed. Use Find Contact Email to retry.';
        }
      }
    }
    await Promise.all([lookupWorker(),lookupWorker()]);
  }
}

async function showAtsReview(jobId){
  const modal=document.querySelector('#tailorModal');
  const versionSelect=document.querySelector('#tailorVersion');
  const output=document.querySelector('#tailorDraft');
  modal.classList.remove('hidden');
  modal.querySelector('h3').textContent='Job-specific ATS Simulation';
  output.value='Evaluating CV against job requirements...';
  document.querySelector('#prepareWithSelectedCv').classList.add('hidden');
  try{
    const cvs=await apiFetch('/api/cv/versions');
    if(!cvs.length)throw new Error('Upload a CV first.');
    versionSelect.innerHTML=cvs.map(function(cv){return '<option value="'+cv.id+'">'+esc(cv.filename)+'</option>';}).join('');
    async function read(){
      const payload=await apiFetch('/api/jobs/'+jobId+'/ats-review?cv_id='+versionSelect.value);
      const a=payload.assessment;
      output.value=a.label+'\n\nCurrent CV: '+payload.cv_filename+
        '\nJob-specific match: '+a.job_match_score+'%'+
        '\nGeneric CV ATS readiness: '+a.ats_readiness+'/100'+
        '\nRequired skill coverage: '+(a.required_skill_coverage===null?'Not measured':a.required_skill_coverage+'%')+
        '\n\nSkills supported by CV: '+(a.required_skills_found||[]).join(', ')+
        '\nMissing evidence (do not fabricate): '+(a.required_skills_missing||[]).join(', ')+
        '\nBlockers: '+(a.hard_blockers||[]).join('; ')+
        '\n\nReadability checks: '+JSON.stringify(a.cv_parse_checks,null,2)+
        '\n\nRecommendations:\n'+(a.suggestions||[]).map(function(x){return '• '+x;}).join('\n')+
        '\n\nThis is a LOCAL simulator, not approval by an employer ATS.';
    }
    versionSelect.onchange=read;await read();
  }catch(err){output.value=err.message;}
}

async function showTailorCv(jobId){
  const modal=document.querySelector('#tailorModal');
  modal.querySelector('h3').textContent='Evidence-based CV Tailoring';
  document.querySelector('#prepareWithSelectedCv').classList.remove('hidden');
  const versionSelect=document.querySelector('#tailorVersion');
  const prepButton=document.querySelector('#prepareWithSelectedCv');
  prepButton.onclick=async function(){
    await prepareApplication(jobId,prepButton,Number(versionSelect.value));
    modal.classList.add('hidden');
  };
  const draftArea=document.querySelector('#tailorDraft');
  modal.classList.remove('hidden');
  draftArea.value='Loading CV evidence…';
  try{
    const versions=await apiFetch('/api/cv/versions');
    if(!versions.length)throw new Error('Upload a CV first.');
    versionSelect.innerHTML=versions.map(function(v){
      return '<option value="'+v.id+'">'+esc(v.filename)+' · '+Math.round(v.ats_score)+' ATS readiness</option>';
    }).join('');
    async function refresh(){
      const data=await apiFetch('/api/jobs/'+jobId+'/tailor-cv?cv_id='+versionSelect.value);
      const d=data.draft;
      draftArea.value='SUGGESTED PROFILE SUMMARY\n'+d.suggested_summary+
        '\n\nORIGINAL CV EVIDENCE (review before using)\n'+(d.cv_evidence||[]).map(function(x){return '• '+x;}).join('\n')+
        '\n\nMATCHED REQUIREMENTS\n'+(d.matched_skills||[]).join(', ')+
        '\n\nMISSING - DO NOT CLAIM\n'+(d.missing_skills_do_not_claim||[]).join(', ')+
        '\n\n'+d.instructions;
    }
    versionSelect.onchange=refresh;
    await refresh();
  }catch(err){draftArea.value='CV tailoring could not load: '+err.message;}
}


async function refreshApplicationsGmailInBackground(){
  // Runs automatically after loading or refreshing My Applications.
  // A short in-tab debounce avoids duplicate requests from rapid navigation.
  if(applicationGmailRefreshPromise ||
     Date.now()-lastApplicationGmailRefreshAt<45000 ||
     !localStorage.getItem('jobintel_token'))return;
  lastApplicationGmailRefreshAt=Date.now();
  applicationGmailRefreshPromise=(async function(){
    const message=document.querySelector('#gmailAutoRefreshStatus');
    if(message)message.textContent='Checking Gmail in background…';
    try{
      const status=await apiFetch('/api/gmail/status');
      if(!status.connected){
        lastApplicationGmailRefreshResult='Gmail not connected — connect in Settings';
        return;
      }
      const result=await apiFetch('/api/gmail/sync-applications',{method:'POST'});
      lastApplicationGmailRefreshResult='Gmail checked · '+result.updated+' status update(s)';
      observedGmailSyncTime=result.last_synced_at||observedGmailSyncTime;
      if(currentRoute==='applications')await renderApplicationsPage();
    }catch(err){
      lastApplicationGmailRefreshResult='Gmail check unavailable: '+err.message;
    }finally{
      const label=document.querySelector('#gmailAutoRefreshStatus');
      if(label && currentRoute==='applications')label.textContent=lastApplicationGmailRefreshResult||'';
    }
  })();
  try{await applicationGmailRefreshPromise;}
  finally{applicationGmailRefreshPromise=null;}
}

async function renderApplicationsPage(){
  const results = await Promise.all([
    apiFetch('/api/applications'),
    apiFetch('/api/gmail/events?limit=200').catch(function(){return [];})
  ]);
  const allApplications = results[0];
  const apps = showRejectedApplications ? allApplications :
    allApplications.filter(function(a){return a.status!=='Rejected';});
  const gmailEvents = results[1];
  const latestEventByApp = {};
  gmailEvents.forEach(function(event){
    if(event.application_id && !latestEventByApp[event.application_id]) latestEventByApp[event.application_id]=event;
  });
  const page = document.querySelector('#pageContent');
  const rejected = allApplications.filter(function(a){return a.status==='Rejected';});
  const rejectedIds = new Set(rejected.map(function(a){return a.id;}));
  const recentSignals = gmailEvents.filter(function(e){
    return e.outcome==='Rejected' && rejectedIds.has(e.application_id) &&
      e.received_at && Date.now()-new Date(e.received_at).getTime()<14*86400000;
  });
  const recentCompanies = Array.from(new Set(recentSignals.map(function(e){
    const app=rejected.find(function(a){return a.id===e.application_id;});
    return app ? app.company : '';
  }).filter(Boolean)));
  const banner = recentCompanies.length
    ? '<div class="card gmailRejectionNotice"><b>Recent rejection detected: '+esc(recentCompanies.join(', '))+
      '</b><p>Gmail confirmed this outcome. The application is kept in your history. Select Show rejected to review it.</p>'+
      '<small>Click a Rejected status below to view the employer’s reason and next steps.</small></div>'
    : '';
  page.innerHTML = '<div class="pageToolbar card"><div><b>' + apps.length + (showRejectedApplications?' tracked applications':' active applications') + '</b><small>'+rejected.length+' rejected application(s) retained for history and analytics.</small><small id="gmailAutoRefreshStatus" role="status">'+esc(lastApplicationGmailRefreshResult||'Gmail checks automatically when this page opens')+'</small></div><div><button id="toggleRejectedApps" class="secondary">'+(showRejectedApplications?'Hide rejected':'Show rejected ('+rejected.length+')')+'</button> <button id="pageAddApp" class="primary">＋ Add application</button></div></div>' +
    banner +
    '<div class="card tableCard"><table class="dataTable"><thead><tr><th>Role</th><th>Company</th><th>Applied</th><th>Match</th><th>Status</th><th>Gmail signal</th><th>Link</th></tr></thead><tbody>' +
    apps.map(function(a){const e=latestEventByApp[a.id]; return '<tr><td><b>'+esc(a.role)+'</b></td><td>'+esc(a.company)+'</td><td>'+esc(a.applied_date)+'</td><td>'+Math.round(a.match_score||0)+'%</td><td>'+(a.status==='Rejected'?'<button type="button" class="gmailRejectedStatus reviewRejection" data-app-id="'+esc(a.id)+'" title="View employer rejection reason and next steps">Rejected ↗</button>':'<select class="statusSelect" data-id="'+a.id+'">'+['Saved','Applied','Screening','Interview','Final','Offer','Rejected'].map(function(s){return '<option '+(s===a.status?'selected':'')+'>'+s+'</option>';}).join('')+'</select>')+'</td><td>'+(e?'<span class="pill '+(e.outcome==='Rejected'?'warn':'good')+'">'+esc(e.outcome)+'</span><small>'+esc(e.subject||'')+'</small>':'—')+'</td><td>'+(a.url?'<a target="_blank" rel="noopener" href="'+esc(a.url)+'">Open ↗</a>':'—')+'</td></tr>';}).join('') +
    '</tbody></table></div><section id="rejectionReviewResult" class="card rejectionReviewPanel hidden" aria-live="polite"></section>';
  async function reviewRejection(id){
    const box=document.querySelector('#rejectionReviewResult');
    if(!box)return;
    box.classList.remove('hidden');
    box.innerHTML='<b>Loading original employer rejection...</b>';
    box.scrollIntoView({behavior:'smooth',block:'nearest'});
    try{
      const data=await apiFetch('/api/applications/'+id+'/rejection-review');
      if(!data.reason_available){
        box.innerHTML='<h3>Email status needs verification</h3>'+
          (data.source_subject?'<p><b>Original Gmail subject:</b> '+esc(data.source_subject)+'</p>':'')+
          (data.source_sender?'<p><b>From:</b> '+esc(data.source_sender)+'</p>':'')+
          '<p>'+esc(data.message)+'</p>';
        return;
      }
      box.innerHTML='<div class="rejectionReviewHead"><h3>Why was this application rejected? — '+esc(data.company)+'</h3>'+
        '<button class="secondary closeRejectionReview" type="button">Close</button></div>'+
        '<p><b>'+esc(data.role)+'</b> · '+esc(data.status)+'</p>'+
        '<div class="gmailEvidenceMeta">'+
        '<div><b>Original Gmail subject:</b> '+esc(data.source_subject||'(no subject)')+'</div>'+
        '<div><b>From:</b> '+esc(data.source_sender||'Unknown sender')+'</div>'+
        (data.gmail_received_at?'<div><b>Received:</b> '+esc(data.gmail_received_at)+'</div>':'')+
        '</div>'+
        '<p><b>What the employer stated:</b> '+esc(data.employer_reason)+'</p>'+
        (data.confirmed_rejection_excerpt?'<p><b>Rejection decision found in email:</b> '+esc(data.confirmed_rejection_excerpt)+'</p>':'')+
        (data.evidence?'<blockquote>'+esc(data.evidence)+'</blockquote>':'')+
        '<p class="rejectionReviewCaution">'+esc(data.limitations)+'</p>'+
        '<h4>Next steps for your job search</h4><ul>'+
        (data.actions||[]).map(function(item){return '<li>'+esc(item)+'</li>';}).join('')+'</ul>'+
        '<small>Evidence source: original Gmail message (verify the subject above in your inbox)</small>';
      const close=box.querySelector('.closeRejectionReview');
      if(close)close.onclick=function(){box.classList.add('hidden');};
    }catch(err){
      box.innerHTML='<h3>Rejection review unavailable</h3><p>'+esc(err.message)+'</p>';
    }
  }
  document.querySelectorAll('.reviewRejection').forEach(function(button){
    button.onclick=function(){reviewRejection(Number(button.dataset.appId));};
  });
  document.querySelector('#pageAddApp').onclick=function(){openApplicationModal(null);};
  document.querySelector('#toggleRejectedApps').onclick=async function(){
    showRejectedApplications=!showRejectedApplications;
    await renderApplicationsPage();
  };
  document.querySelectorAll('.statusSelect').forEach(function(select){
    select.onchange=async function(){
      await apiFetch('/api/applications/'+select.dataset.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:select.value})});
      await renderApplicationsPage();
    };
  });
}

async function renderAtsPage(){
  const cv = await apiFetch('/api/cv');
  const page = document.querySelector('#pageContent');
  if(!cv.uploaded){
    page.innerHTML='<div class="card detailPage"><h2>Upload your CV</h2><p>JobIntel will parse it locally, calculate generic ATS readiness, rank your skills and use it to filter current jobs.</p><input id="pageCvFile" type="file" accept=".pdf,.docx,.txt"><button id="pageUploadCv" class="primary">Upload & analyze</button></div>';
  }else{
    const a=cv.ats;
    page.innerHTML='<div class="detailGrid"><div class="card detailPage"><h2>ATS Readiness: '+a.score+'/100</h2><span class="pill good">'+esc(a.status)+'</span><p><b>'+esc(cv.filename)+'</b></p><p>Machine readable: yes · Core sections: '+esc(a.sections_complete)+' · Skills detected: '+a.skills_detected.length+'</p><h3>Suggestions</h3><ul>'+a.suggestions.map(function(x){return '<li>'+esc(x)+'</li>';}).join('')+'</ul><input id="pageCvFile" type="file" accept=".pdf,.docx,.txt"><button id="pageUploadCv" class="secondary">Replace CV</button></div><div class="card detailPage"><h2>Your strongest skills</h2>'+cv.top_skills.map(function(x){return '<div class="skillDetail"><b>'+esc(x.skill)+'</b><span>CV mentions '+x.cv_count+' · relevant jobs '+x.market_count+'</span></div>';}).join('')+'</div></div>';
  }
  document.querySelector('#pageUploadCv').onclick=uploadCvFromPage;
}

async function uploadCvFromPage(){
  const file=document.querySelector('#pageCvFile').files[0];
  if(!file) return alert('Choose a CV file first.');
  const form=new FormData(); form.append('file',file);
  const result=await apiFetch('/api/cv/upload',{method:'POST',body:form});
  alert('CV analyzed: ATS Readiness '+result.ats.score+'/100.');
  await renderAtsPage();
}

async function renderMatchesPage(){
  jobMarketCache=await apiFetch('/api/jobs?limit=100');
  document.querySelector('#pageContent').innerHTML='<div class="pageIntro"><h2>Best matches for your current CV</h2><p>These scores combine skill overlap, role relevance, experience and language signals.</p></div><div class="jobMarketGrid">'+jobMarketCache.map(function(j){return jobCard(j,false);}).join('')+'</div>';
  bindTrackButtons();
}

async function renderApplicationPrepPage(){
  const packages = await apiFetch('/api/application-packages');
  const page = document.querySelector('#pageContent');

  if(!packages.length){
    page.innerHTML =
      '<div class="card detailPage"><h2>No prepared applications yet</h2>' +
      '<p>Open Job Market or Matches and click <b>Prepare application</b>. JobIntel will snapshot the current CV/job match, generate a cover letter, draft safe screening answers and flag anything that needs your input.</p>' +
      '<button id="goJobMarket" class="primary">Open Job Market</button></div>';
    document.querySelector('#goJobMarket').onclick=function(){routeTo('job-market');};
    return;
  }

  page.innerHTML =
    '<div class="pageIntro"><h2>Prepared application packages</h2><p>Preparation is automatic; submission is still under your control.</p></div>' +
    '<div class="prepGrid">' +
      packages.map(function(item){
        const p=item.package||{};
        const job=p.job||{};
        const validation=p.validation||{};
        const answers=p.screening_answers||[];
        const unresolved=p.unresolved_fields||[];
        const breakdown=(p.match||{}).score_breakdown||{};
        return '<article class="card prepCard">' +
          '<div class="prepHead"><div><span class="sourceTag">'+esc(job.source||'Prepared')+'</span><h3>'+esc(job.title||'Job')+'</h3><p>'+esc(job.company||'')+' · '+esc(job.location||'')+'</p></div><div class="scoreBadge">'+Math.round(item.match_score||0)+'%<small>match</small></div></div>' +
          '<div class="prepStatus"><span class="pill '+(item.status==='Package Ready'?'good':'warn')+'">'+esc(item.status)+'</span><span>'+esc(item.cover_letter_generator)+' cover letter</span></div>' +
          '<div class="matchBreakdownMini"><span>Role '+Math.round(breakdown.role_alignment||0)+'%</span><span>Required '+Math.round(breakdown.required_skills||0)+'%</span><span>Experience '+Math.round(breakdown.experience||0)+'%</span><span>Language '+Math.round(breakdown.language||0)+'%</span></div>' +
          (!validation.passed ? '<div class="prepWarning"><b>Validation needs review</b><br>'+((validation.hard_blockers||[]).map(esc).join('<br>') || 'Match threshold or eligibility checks need review.')+'</div>' : '') +
          '<form class="prepAnswers" data-package-id="'+item.id+'">' +
            answers.map(function(a){
              return '<label><span>'+esc(a.question)+' <small>'+esc(a.status)+'</small></span><textarea name="'+esc(a.key)+'" rows="2" placeholder="'+(a.status==='needs_user_input'?'Add your answer before applying':'Draft answer')+'">'+esc(a.answer||'')+'</textarea></label>';
            }).join('') +
            '<div class="prepActions">' +
              '<button type="submit" class="secondary">Save answers</button>' +
              '<button type="button" class="secondary packageCoverBtn" data-package-id="'+item.id+'">Download cover letter</button>' +
              (job.url?'<a class="primaryLink" href="'+esc(job.url)+'" target="_blank" rel="noopener">Open application ↗</a>':'') +
            '</div>' +
            (unresolved.length?'<p class="unresolvedLine">'+unresolved.length+' field(s) still need your input before this package is ready.</p>':'') +
          '</form>' +
        '</article>';
      }).join('') +
    '</div>';

  document.querySelectorAll('.prepAnswers').forEach(function(form){
    form.onsubmit=async function(e){
      e.preventDefault();
      const values=Object.fromEntries(new FormData(form).entries());
      try{
        await apiFetch('/api/application-packages/'+form.dataset.packageId+'/answers',{
          method:'PATCH',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({answers:values})
        });
        await renderApplicationPrepPage();
      }catch(err){alert('Answers could not be saved: '+err.message);}
    };
  });

  document.querySelectorAll('.packageCoverBtn').forEach(function(button){
    button.onclick=function(){downloadPackageCoverLetter(button.dataset.packageId,button);};
  });
}

async function renderSkillGapPage(){
  const d=await apiFetch('/api/dashboard');
  const gaps=d.skill_gap||[];
  document.querySelector('#pageContent').innerHTML=
    '<div class="pageIntro"><h2>Skill Gap Analysis</h2><p>Calculated from missing required and preferred skills in your current CV-relevant jobs, not from the whole market.</p></div>'+
    '<div class="detailGrid">'+
      '<div class="card detailPage"><h2>Your top skills</h2>'+
        ((d.profile.top_skills||[]).length?(d.profile.top_skills||[]).map(function(x){return '<div class="skillDetail"><b>'+esc(x.skill)+'</b><span>'+x.market_count+' relevant jobs</span></div>';}).join(''):'<p>No CV skills available.</p>')+
      '</div>'+
      '<div class="card detailPage"><h2>Repeated gaps</h2>'+
        (gaps.length?gaps.map(function(g){
          return '<div class="gapPage"><div class="gapTitleRow"><b>'+esc(g.skill)+'</b><span class="pill warn">'+g.market_count+' jobs</span></div>'+
            '<div class="gapCounts"><span>'+g.required_count+' required</span><span>'+g.preferred_count+' preferred</span><span>'+esc(g.gap_type)+'-heavy</span></div>'+
            '<p>'+esc(g.action)+'</p></div>';
        }).join(''):'<p>No repeated missing skills in the current filtered market.</p>')+
      '</div>'+
    '</div>';
}

async function openInterviewPractice(practiceId){
  const practice=await apiFetch('/api/interview-practice/'+practiceId);
  if(currentRoute!=='interview-prep')return;
  const holder=document.querySelector('#interviewPracticeWorkspace');
  if(!holder)return;
  holder.innerHTML='<div class="card detailPage"><h3>'+esc(practice.job_title)+' · '+esc(practice.company)+'</h3>'+
    '<p class="muted">Practice prompts based on your job description and saved CV. This is coaching, not an employer test.</p>'+
    (practice.questions||[]).map(function(q,i){
      const completed=practice.answers[String(i)];
      return '<form class="interviewAnswerForm" data-session="'+practice.id+'" data-index="'+i+'">'+
        '<label><b>'+(i+1)+'. '+esc(q.question)+'</b>'+
        '<small>'+esc(q.topic)+' · Job skills: '+(q.relevant_job_skills||[]).map(esc).join(', ')+'</small>'+
        '<textarea name="answer" rows="5" maxlength="6000" minlength="20" required placeholder="Explain a real example with your contribution and result.">'+esc(completed&&completed.answer||'')+'</textarea></label>'+
        '<button type="submit" class="secondary">Save answer & get coaching</button>'+
        '<div class="interviewAnswerFeedback" aria-live="polite">'+
        (completed?'<p>'+completed.feedback.feedback.map(esc).join(' · ')+'</p>':'')+'</div></form>';
    }).join('')+'</div>';
  holder.querySelectorAll('.interviewAnswerForm').forEach(function(form){
    form.onsubmit=async function(event){
      event.preventDefault();
      const btn=form.querySelector('button[type=submit]');
      btn.disabled=true;
      try{
        const result=await apiFetch('/api/interview-practice/'+form.dataset.session+'/answer',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({question_index:Number(form.dataset.index),answer:form.elements.answer.value})
        });
        form.querySelector('.interviewAnswerFeedback').innerHTML='<b>Feedback:</b> '+
          (result.feedback.feedback||[]).map(esc).join(' · ')+
          '<p class="muted">'+esc(result.feedback.disclaimer)+'</p>';
      }catch(err){alert('Interview answer could not be saved: '+err.message);}
      finally{btn.disabled=false;}
    };
  });
}

async function renderInterviewPracticePage(){
  const sessions=await apiFetch('/api/interview-practice');
  const holder=document.querySelector('#pageContent');
  holder.innerHTML='<div class="pageIntro"><h2>Interview Practice</h2>'+
    '<p>Prepare from the actual employer job description and your saved CV. Practice in English, save answers, and get structured feedback. Questions are representative, not leaked employer questions.</p></div>'+
    '<div class="card detailPage"><h3>Start with a suitable vacancy</h3>'+
    '<p>Go to Job Market or Action Center, choose a role and click <b>Interview Prep</b>. Previous practice sessions appear below.</p>'+
    '<button id="interviewOpenJobs" class="secondary">Browse suitable jobs</button></div>'+
    '<div class="card detailPage"><h3>Saved practice sessions</h3>'+
    (sessions.length?sessions.map(function(s){
      return '<div class="analyticsRow"><span>Session #'+s.id+' · '+s.answers_count+
        '/'+s.questions_count+' answers · '+esc(s.created_at.slice(0,10))+'</span>'+
        '<button type="button" class="secondary loadPracticeBtn" data-id="'+s.id+'">Resume</button></div>';
    }).join(''):'<p>No practice sessions yet.</p>')+'</div>'+
    '<div id="interviewPracticeWorkspace"></div>';
  document.querySelector('#interviewOpenJobs').onclick=function(){routeTo('job-market');};
  document.querySelectorAll('.loadPracticeBtn').forEach(function(b){
    b.onclick=function(){openInterviewPractice(b.dataset.id).catch(e=>alert(e.message));};
  });
}

async function renderAnalyticsPage(){
  const [d,conversion]=await Promise.all([apiFetch('/api/dashboard'),apiFetch('/api/analytics/conversion')]);
  const sourceAnalytics=d.market.source_analytics||[];
  const sourceRows=sourceAnalytics.map(function(s){
    const statusClass=s.status==='active'||s.status==='configured'?'good':'warn';
    const targetText=s.mode==='Employer ATS'
      ? (s.targets ? s.enabled_targets+' enabled target'+(s.enabled_targets===1?'':'s') : 'Add employer target')
      : s.mode;
    return '<div class="sourceAnalyticsRow">'+
      '<div><b>'+esc(s.source)+'</b><small>'+esc(targetText)+'</small></div>'+
      '<div class="sourceMetrics"><strong>'+s.jobs+' jobs</strong><span>'+s.relevant_jobs+' CV-relevant</span></div>'+
      '<span class="pill '+statusClass+'">'+esc(s.status)+'</span>'+
    '</div>';
  }).join('');

  const configuredAts=sourceAnalytics.filter(function(s){return s.mode==='Employer ATS' && s.status==='configured';}).length;
  const atsJobs=sourceAnalytics.filter(function(s){return s.mode==='Employer ATS';}).reduce(function(sum,s){return sum+s.jobs;},0);

  document.querySelector('#pageContent').innerHTML=
    '<div class="analyticsSummary">'+
      '<div class="card analyticsMini"><small>Total tracked jobs</small><b>'+d.market.total_jobs+'</b></div>'+
      '<div class="card analyticsMini"><small>CV-relevant jobs</small><b>'+d.market.relevant_jobs+'</b></div>'+
      '<div class="card analyticsMini"><small>ATS sources configured</small><b>'+configuredAts+'</b></div>'+
      '<div class="card analyticsMini"><small>ATS jobs collected</small><b>'+atsJobs+'</b></div>'+
    '</div>'+
    '<div class="card detailPage"><h2>Application conversion by role</h2><p>'+esc(conversion.interpretation)+'</p>'+
      Object.entries(conversion.by_role||{}).map(function(row){
        return '<div class="analyticsRow"><b>'+esc(row[0])+'</b><span>'+
          row[1].applications+' applications · '+row[1].interviews_or_later+
          ' interview-stage · '+row[1].rejected+' rejected</span></div>';
      }).join('')+
    '</div>'+
    '<div class="card detailPage"><h2>CV version performance</h2>'+
      Object.entries(conversion.by_cv_version||{}).map(function(row){
        return '<div class="analyticsRow"><b>'+esc(row[0])+'</b><span>'+
          row[1].applications+' apps · '+row[1].interviews_or_later+' interview-stage</span></div>';
      }).join('')+'</div>'+
    '<div class="analyticsGrid">'+
      '<div class="card detailPage"><h2>Application funnel</h2>'+Object.entries(d.pipeline).map(function(row){return '<div class="analyticsRow"><b>'+esc(row[0])+'</b><span>'+row[1]+'</span></div>';}).join('')+'</div>'+
      '<div class="card detailPage sourceAnalyticsCard"><div class="panelHead"><h2>Job sources</h2><button id="configureSources" class="secondary">Configure ATS</button></div>'+
        '<p class="muted">A source can be supported by JobIntel but still show 0 jobs until at least one employer target is configured and refreshed.</p>'+
        sourceRows+
      '</div>'+
      '<div class="card detailPage"><h2>CV performance</h2>'+(d.performance.length?d.performance.map(function(p){return '<div class="analyticsRow"><b>'+esc(p.label)+'</b><span>'+p.value+'% interview conversion · '+p.applications+' apps</span></div>';}).join(''):'<p>No outcome history yet.</p>')+'</div>'+
    '</div>';

  document.querySelector('#configureSources').onclick=function(){routeTo('settings');};
}

async function renderSettingsPage(){
  const verifiedProfile=await apiFetch('/api/candidate-profile');
  const vaultDocuments=await apiFetch('/api/documents');
  const sources=await apiFetch('/api/sources');
  const status=await apiFetch('/api/assistant/status');
  const targets=await apiFetch('/api/collector-targets');
  const gmail=await apiFetch('/api/gmail/status').catch(function(){return {configured:false,connected:false};});

  document.querySelector('#pageContent').innerHTML=
    '<div class="detailGrid">' +
      '<div class="card detailPage">' +
        '<h2>Saved application profile</h2>' +
        '<p>Confirm these details once. JobIntel fills known fields automatically and asks for missing or sensitive answers.</p>' +
        '<form id="candidateProfileForm"><div class="p0ProfileGrid">' +
        ['firstName','lastName','phone','city','country','linkedin','github','portfolio','education','employment','languages'].map(function(key){
          const human=key.replace(/([A-Z])/g,' $1').replace(/^./,m=>m.toUpperCase());
          return '<label>'+esc(human)+'<input name="'+key+'" value="'+esc(verifiedProfile[key]||'')+'" placeholder="'+(key==='country'?'Germany':'')+'"></label>';
        }).join('')+'</div>' +
        '<p class="p0VaultInfo">Email: '+esc(verifiedProfile.email)+' (verified account)</p>' +
        '<button class="primary" type="submit">Save verified application profile</button></form></div>' +
      '<div class="card detailPage">' +
        '<h2>Private document vault</h2>' +
        '<p>Upload each CV version and supporting letter once. Files are encrypted and stored in a persistent local Docker volume.</p>' +
        '<form id="candidateVaultUpload"><label>Document type<select name="kind"><option value="cv">CV / Resume</option><option value="experience">Experience letter</option><option value="cover">Reusable cover letter</option></select></label>' +
        '<label>CV role family<select name="role_family"><option value="general">General</option><option value="qa">QA Automation</option><option value="data">Data Engineering</option><option value="backend">Backend / AI</option></select></label>' +
        '<label>Original document<input name="document" type="file" accept=".pdf,.doc,.docx,.txt" required></label>' +
        '<button class="primary" type="submit">Save document</button></form>' +
        (vaultDocuments.length?vaultDocuments.map(function(doc){
          return '<div class="p0VaultRow"><b>'+esc(doc.filename)+'</b><small>'+esc(doc.kind)+' · '+esc(doc.role_family)+
            ' · '+(doc.size_bytes/1024).toFixed(0)+' KB</small>' +
            (doc.default_document?'<span class="pill good">Default</span>':'<button type="button" class="secondary candidateVaultDefault" data-id="'+doc.id+'">Set default</button>')+'</div>';
        }).join(''):'<p>No original files saved yet. Upload a CV once to enable automatic document attachment.</p>') +
      '</div>' +
      '<form id="profileForm" class="card detailPage">' +
        '<h2>Profile</h2>' +
        '<label>Name<input name="display_name" value="'+esc(currentUser.display_name)+'"></label>' +
        '<label>Email<input disabled value="'+esc(currentUser.email)+'"></label>' +
        '<label>Target roles<textarea name="target_roles" rows="3">'+esc(currentUser.target_roles||'')+'</textarea></label>' +
        '<label>Target locations<textarea name="target_locations" rows="2">'+esc(currentUser.target_locations||'')+'</textarea></label>' +
        '<button class="primary" type="submit">Save profile</button>' +
        '<button id="logoutButton" class="dangerButton" type="button">Logout</button>' +
      '</form>' +
      '<div class="card detailPage">' +
        '<h2>Career Assistant</h2>' +
        '<p>Mode: <b>'+esc(status.mode)+'</b></p>' +
        '<p>Ollama: '+(status.ollama_online?'Online':'Offline / fallback rules')+'</p>' +
        '<p>Model: '+esc(status.model)+'</p>' +
        '<h2>Job sources</h2>' +
        sources.active.map(function(s){return '<div class="sourceRow"><b>'+esc(s.name)+'</b><span class="pill good">'+esc(s.status)+'</span><small>'+esc(s.mode)+'</small></div>';}).join('') +
        '<h3>Planned / restricted</h3>' +
        sources.planned.map(function(s){return '<div class="sourceRow"><b>'+esc(s.name)+'</b><span class="pill warn">'+esc(s.status)+'</span><small>'+esc(s.mode)+'</small></div>';}).join('') +
        '<p class="policyNote">XING and StepStone remain manual/authorized integrations. Direct employer ATS collectors are preferred for automated acquisition.</p>' +
      '</div>' +
      '<div class="card detailPage">' +
        '<h2>Gmail application tracking</h2>' +
        '<p>Connect Gmail with read-only access. JobIntel scans recent messages, matches them to tracked applications, and can update outcomes such as Screening, Interview, Offer or Rejected.</p>' +
        (gmail.connected
          ? '<p><span class="pill good">Connected</span> '+esc(gmail.google_email||'Gmail')+'</p><p class="muted">Last sync: '+esc(gmail.last_synced_at||'Not synced yet')+'</p><div class="prepActions"><button id="gmailSyncButton" class="primary" type="button">Sync Gmail now</button>'+(gmail.can_send?'<span class="pill good">Send authorized</span>':'<button id="gmailSendPermissionButton" class="secondary" type="button">Enable Gmail sending</button>')+'<button id="gmailDisconnectButton" class="secondary" type="button">Disconnect</button></div>'
          : (gmail.configured
              ? '<p><span class="pill warn">Not connected</span></p><button id="gmailConnectButton" class="primary" type="button">Connect Gmail</button>'
              : '<p><span class="pill warn">OAuth setup required</span></p><p class="muted">Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_GMAIL_REDIRECT_URI in your .env, then rebuild the backend.</p>')) +
        '<p class="policyNote">'+(gmail.can_send?'Gmail read and send enabled. Sending is never automatic: you review each recipient and message before clicking Send.':'Gmail read-only is active. For sending, add gmail.send to Google Cloud Data Access and click Enable Gmail sending to authorize it separately.')+'</p>' +
      '</div>' +
      '<div class="card detailPage atsTargets">' +
        '<h2>Direct employer ATS collectors</h2>' +
        '<p>Configure employers using Greenhouse, Lever, SmartRecruiters, Ashby, Personio or Workable. Refresh Current Jobs will pull public postings, keep Germany/remote-EU technical roles, and put them into the same CV-matching pipeline.</p>' +
        '<form id="collectorTargetForm" class="collectorForm">' +
          '<label>Provider<select name="provider"><option value="greenhouse">Greenhouse</option><option value="ashby">Ashby</option><option value="lever">Lever (global)</option><option value="lever-eu">Lever (EU)</option><option value="smartrecruiters">SmartRecruiters</option><option value="personio">Personio</option><option value="workable">Workable</option></select></label>' +
          '<label>Company label<input name="label" placeholder="Company name" required></label>' +
          '<label>Job board / company identifier<input name="identifier" placeholder="Greenhouse: board token · Ashby: final URL segment" required></label>' +
          '<button class="primary" type="submit">Add collector</button>' +
        '</form>' +
        '<div id="collectorTargetsList">' +
          (targets.length ? targets.map(function(t){return '<div class="sourceRow"><div><b>'+esc(t.label)+'</b><small>'+esc(t.provider)+' · '+esc(t.identifier)+'</small></div><span class="pill good">'+(t.enabled?'enabled':'disabled')+'</span><button class="iconBtn deleteCollector" data-id="'+t.id+'" type="button">✕</button></div>';}).join('') : '<div class="empty">No employer ATS companies configured yet.</div>') +
        '</div>' +
      '</div>' +
      '<div class="card detailPage">' +
        '<h2>External collector bridge</h2>' +
        '<p>Your existing Playwright collector can stay separate and send normalized, authorized results to <code>POST /api/jobs/bulk-import</code>. This keeps browser automation isolated from JobIntel core.</p>' +
        '<pre class="codeSample">{ "jobs": [{ "source": "External Collector", "title": "...", "company": "...", "location": "Germany", "url": "...", "description": "...", "remote": false }] }</pre>' +
      '</div>' +
    '</div>';

  document.querySelector('#candidateProfileForm').onsubmit=async function(e){
    e.preventDefault();
    const button=e.target.querySelector('button[type=submit]');
    button.disabled=true;
    try{
      const values=Object.fromEntries(new FormData(e.target).entries());
      await apiFetch('/api/candidate-profile',{method:'PATCH',
        headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});
      alert('Verified application profile saved. These details can be reused by Assisted Apply.');
      await renderSettingsPage();
    }catch(err){alert('Candidate profile could not be saved: '+err.message);}
    finally{button.disabled=false;}
  };
  document.querySelector('#candidateVaultUpload').onsubmit=async function(e){
    e.preventDefault();
    const button=e.target.querySelector('button[type=submit]');
    button.disabled=true;
    try{
      const form=new FormData(e.target);
      const kind=form.get('kind');
      const role=form.get('role_family');
      const file=form.get('document');
      if(!file||!file.size)throw new Error('Select your original PDF/DOCX file.');
      const payload=new FormData();
      payload.append('file',file);
      const path=kind==='cv'?'/api/cv/upload?role_family='+encodeURIComponent(role):
        '/api/documents?kind='+encodeURIComponent(kind)+'&role_family=general';
      await apiFetch(path,{method:'POST',body:payload});
      await renderSettingsPage();
    }catch(err){alert('Document could not be saved: '+err.message);}
    finally{button.disabled=false;}
  };
  document.querySelectorAll('.candidateVaultDefault').forEach(function(button){
    button.onclick=async function(){
      button.disabled=true;
      try{
        await apiFetch('/api/documents/'+button.dataset.id+'/default',{method:'POST'});
        await renderSettingsPage();
      }catch(err){alert('Could not select default document: '+err.message);}
      finally{button.disabled=false;}
    };
  });

  document.querySelector('#profileForm').onsubmit=async function(e){
    e.preventDefault();
    const data=Object.fromEntries(new FormData(e.target).entries());
    currentUser=await apiFetch('/api/profile',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    showApp();
    alert('Profile saved.');
  };

  document.querySelector('#logoutButton').onclick=logout;

  if(document.querySelector('#gmailConnectButton')){
    document.querySelector('#gmailConnectButton').onclick=async function(){
      try{
        const result=await apiFetch('/api/gmail/connect',{method:'POST'});
        window.open(result.authorization_url,'_blank','noopener');
      }catch(err){alert('Gmail connection could not start: '+err.message);}
    };
  }
  if(document.querySelector('#gmailSendPermissionButton')){
    document.querySelector('#gmailSendPermissionButton').onclick=async function(){
      await startGmailSendAuthorization();
    };
  }
  if(document.querySelector('#gmailSyncButton')){
    document.querySelector('#gmailSyncButton').onclick=async function(){
      try{
        const result=await apiFetch('/api/gmail/sync',{method:'POST'});
        alert('Gmail sync complete: '+result.matched+' matched, '+result.updated+' status update(s).');
        await renderSettingsPage();
      }catch(err){alert('Gmail sync failed: '+err.message);}
    };
  }
  if(document.querySelector('#gmailDisconnectButton')){
    document.querySelector('#gmailDisconnectButton').onclick=async function(){
      if(!confirm('Disconnect Gmail from JobIntel?')) return;
      await apiFetch('/api/gmail/disconnect',{method:'DELETE'});
      await renderSettingsPage();
    };
  }

  document.querySelector('#collectorTargetForm').onsubmit=async function(e){
    e.preventDefault();
    const data=Object.fromEntries(new FormData(e.target).entries());
    try{
      await apiFetch('/api/collector-targets',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(data)
      });
      await renderSettingsPage();
      alert('Collector added. Click Refresh Current Jobs to fetch its current postings.');
    }catch(err){
      alert('Collector could not be added: '+err.message);
    }
  };

  document.querySelectorAll('.deleteCollector').forEach(function(button){
    button.onclick=async function(){
      await apiFetch('/api/collector-targets/'+button.dataset.id,{method:'DELETE'});
      await renderSettingsPage();
    };
  });
}
async function logout(switchAccount=false){
  closeAccountMenu();
  try{await apiFetch('/api/auth/logout',{method:'POST'});}catch{}
  localStorage.removeItem('jobintel_token');
  currentUser=null;
  showAuth(switchAccount?'Sign in with another JobIntel account or create a local profile.':'You have logged out.');
  document.querySelector('#loginTab').click();
  const form=document.querySelector('#loginForm');
  if(form){form.reset();form.querySelector('input[name=email]').focus();}
}

async function autoSyncGmail(){
  // The backend worker syncs every ~2 minutes while Docker is running.
  // This check simply refreshes the applications page when a new sync lands.
  if(gmailStatusCheckInFlight || document.hidden || !localStorage.getItem('jobintel_token')) return;
  gmailStatusCheckInFlight=true;
  try{
    const status=await apiFetch('/api/gmail/status');
    if(!status.connected)return;
    const newStamp=status.last_synced_at||'';
    if(observedGmailSyncTime===null){
      observedGmailSyncTime=newStamp;
    }else if(newStamp && newStamp!==observedGmailSyncTime){
      observedGmailSyncTime=newStamp;
      if(currentRoute==='applications')await renderApplicationsPage();
    }
  }catch(err){
    // Keep manual Sync Gmail as fallback when offline or OAuth has expired.
  }finally{gmailStatusCheckInFlight=false;}
}

async function updateAssistantStatus(){
  try{
    const status=await apiFetch('/api/assistant/status');
    const el=document.querySelector('#assistantMode');
    if(!el) return;
    if(status.state==='ready'){
      el.textContent='● Ollama · ' + status.model;
      el.title='Local Ollama model is ready.';
    }else if(status.state==='model_downloading'){
      el.textContent='● Ollama model downloading…';
      el.title='Ollama server is running, but the model is still being downloaded.';
    }else if(status.state==='server_offline'){
      el.textContent='● Ollama starting…';
      el.title='Waiting for the local Ollama container.';
    }else{
      el.textContent='● Rules fallback';
      el.title='Ollama is disabled.';
    }
  }catch{}
}

document.querySelector('#avatar').onclick=toggleAccountMenu;
document.querySelector('#sidebarAccount').onclick=toggleAccountMenu;
document.querySelector('#accountSettings').onclick=function(){closeAccountMenu();routeTo('settings');};
document.querySelector('#accountSwitch').onclick=function(){logout(true);};
document.querySelector('#accountLogout').onclick=function(){logout(false);};
document.addEventListener('click',function(event){
  if(!event.target.closest('#accountMenu,#avatar,#sidebarAccount'))closeAccountMenu();
});
document.addEventListener('keydown',function(event){
  if(event.key==='Escape')closeAccountMenu();
});
document.addEventListener('visibilitychange',function(){
  if(!document.hidden && currentRoute==='dashboard' &&
     localStorage.getItem('jobintel_token') && Date.now()-lastDashboardCheck>45000){
    load().catch(function(){});
  }
});
document.querySelector('#refreshDashboard').onclick=async function(){
  const button=this;
  button.disabled=true;
  button.textContent='Updating…';
  try{await load();}
  catch(err){/* Dashboard displays an inline error without resetting widgets. */}
  finally{button.disabled=false;button.textContent='↻ Update dashboard';}
};
document.querySelector('#closeImportModal').onclick=function(){document.querySelector('#importModal').classList.add('hidden');};
document.querySelector('#importForm').onsubmit=async function(e){
  e.preventDefault();
  const data=Object.fromEntries(new FormData(e.target).entries());
  data.remote=Boolean(e.target.elements.remote.checked);
  try{
    await apiFetch('/api/jobs/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    document.querySelector('#importModal').classList.add('hidden'); e.target.reset();
    alert('Job imported and scored against your CV.');
    if(currentRoute==='job-market') await renderJobMarket(false);
  }catch(err){alert('Import failed: '+err.message);}
};
