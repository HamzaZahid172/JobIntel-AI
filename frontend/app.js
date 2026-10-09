const API = localStorage.getItem('jobintel_api') || 'http://localhost:8100';

const navItems = [
  {route:'dashboard', label:'⌂ Dashboard'},
  {route:'job-market', label:'▣ Job Market'},
  {route:'applications', label:'▤ My Applications'},
  {route:'ats', label:'▤ ATS CV Check'},
  {route:'matches', label:'♡ Matches'},
  {route:'application-prep', label:'▣ Application Prep'},
  {route:'skill-gap', label:'▥ Skill Gap'},
  {route:'analytics', label:'▧ Analytics'},
  {route:'settings', label:'⚙ Settings'}
];
let currentUser = null;
let currentRoute = 'dashboard';
let jobMarketCache = [];
let showRejectedApplications = false;
let assistantStatusTimer = null;

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

async function load() {
  const d = await apiFetch('/api/dashboard');
  const s = d.summary;

  const sourceText = Object.entries(d.market.sources || {}).map(([k,v]) => `${k}: ${v}`).join(' · ');
  const atsConfigured = (d.market.source_analytics || []).filter(function(x){
    return x.mode === 'Employer ATS' && x.status === 'configured';
  }).length;
  document.querySelector('#marketStatus').textContent =
    d.market.live
      ? (d.cv.uploaded
          ? `CV-filtered market · ${d.market.relevant_jobs} relevant of ${d.market.total_jobs} tracked · ${sourceText || 'Current feeds'} · ATS sources configured: ${atsConfigured}/3 · Last sync ${fmtDate(d.market.last_sync)}`
          : `Live PostgreSQL snapshot · ${sourceText || 'Current feeds'} · ATS sources configured: ${atsConfigured}/3 · Last sync ${fmtDate(d.market.last_sync)}`)
      : 'No live jobs stored yet. Click “Refresh Current Jobs”.';

  const atsValue = s.ats_score == null ? '—' : `${Math.round(s.ats_score)} / 100`;
  const metrics = [
    ['💼', d.cv.uploaded ? 'CV-Relevant Jobs' : 'Tracked Live Jobs', s.active_jobs, d.cv.uploaded ? `Filtered from ${s.total_market_jobs} live jobs` : 'Current feed snapshot'],
    ['🆕','Posted Today',s.new_today,d.cv.uploaded ? 'Relevant to your profile' : 'Based on source timestamps'],
    ['➤','Applications',s.applications,'Your manual tracker'],
    ['👥','Interviews',s.interviews,'From your tracker'],
    ['🏆','Offers',s.offers,'From your tracker'],
    ['▤','ATS Readiness',atsValue,d.cv.uploaded ? `✓ ${d.cv.ats.status}` : 'Upload CV to calculate'],
  ];
  document.querySelector('#metrics').innerHTML = metrics.map((m,i)=>`
    <div class="metric card ${i===5?'atsMini':''}">
      <div class="metricIcon">${m[0]}</div>
      <div><small>${m[1]}</small><b>${m[2]}</b><span>${esc(m[3])}</span></div>
    </div>`).join('');

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
    `<div class="panelHead"><h3>Application Pipeline</h3><span class="pill info">✎ Manual tracking</span></div>
     <div class="pipeline">${['Saved','Applied','Screening','Interview','Final','Offer'].map(x=>`
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

function showAuth(message){
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
  currentRoute = route;
  if (updateHash) location.hash = route;
  renderNav();
  const dash = document.querySelector('#dashboardContent');
  const page = document.querySelector('#pageContent');
  const titles = {
    dashboard:['JobIntel AI','🇩🇪 Live Career Intelligence for Germany'],
    'job-market':['Job Market','All current jobs relevant to your CV'],
    applications:['My Applications','Track every application and outcome'],
    ats:['ATS CV Check','CV readiness, skills and role profile'],
    matches:['Best Matches','Current jobs ranked against your CV'],
    'application-prep':['Application Preparation','Prepared application packages, screening answers and CV-grounded cover letters'],
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
  if(route==='applications') return renderApplicationsPage();
  if(route==='ats') return renderAtsPage();
  if(route==='matches') return renderMatchesPage();
  if(route==='application-prep') return renderApplicationPrepPage();
  if(route==='skill-gap') return renderSkillGapPage();
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
    breakdownHtml +
    (!compact && missing.length ? '<p class="missingLine"><b>Missing:</b> ' + missing.map(esc).join(', ') + '</p>' : '') +
    (!compact && job.hard_blockers && job.hard_blockers.length ? '<p class="blockerLine"><b>Review:</b> ' + job.hard_blockers.map(esc).join(' ') + '</p>' : '') +
    '<div class="jobActions">' +
      (job.url ? '<a class="primaryLink" target="_blank" rel="noopener" href="' + esc(job.url) + '">Apply on source ↗</a>' : '') +
      '<button class="secondary coverLetterBtn" data-job-id="' + job.id + '">Create cover letter</button>' +
      '<button class="secondary prepareApplicationBtn" data-job-id="' + job.id + '">Prepare application</button>' +
      '<button class="secondary trackJob" data-job-id="' + job.id + '">Track application</button>' +
    '</div></article>';
}

function bindTrackButtons(){
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

async function prepareApplication(jobId, button){
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = 'Preparing…';
  try{
    const prepared = await apiFetch('/api/jobs/' + jobId + '/prepare-application', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({minimum_match:70})
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

async function renderApplicationsPage(){
  const results = await Promise.all([
    apiFetch('/api/applications'+(showRejectedApplications?'':'?active_only=true')),
    apiFetch('/api/gmail/events?limit=100').catch(function(){return [];})
  ]);
  const apps = results[0];
  const gmailEvents = results[1];
  const latestEventByApp = {};
  gmailEvents.forEach(function(event){
    if(event.application_id && !latestEventByApp[event.application_id]) latestEventByApp[event.application_id]=event;
  });
  const page = document.querySelector('#pageContent');
  page.innerHTML = '<div class="pageToolbar card"><div><b>' + apps.length + (showRejectedApplications?' tracked applications':' active applications') + '</b><small>Rejected applications are hidden from the active list but kept for analytics.</small></div><div><button id="toggleRejectedApps" class="secondary">'+(showRejectedApplications?'Hide rejected':'Show rejected')+'</button> <button id="syncGmailFromApps" class="secondary">Sync Gmail</button> <button id="pageAddApp" class="primary">＋ Add application</button></div></div>' +
    '<div class="card tableCard"><table class="dataTable"><thead><tr><th>Role</th><th>Company</th><th>Applied</th><th>Match</th><th>Status</th><th>Gmail signal</th><th>Link</th></tr></thead><tbody>' +
    apps.map(function(a){const e=latestEventByApp[a.id]; return '<tr><td><b>'+esc(a.role)+'</b></td><td>'+esc(a.company)+'</td><td>'+esc(a.applied_date)+'</td><td>'+Math.round(a.match_score||0)+'%</td><td><select class="statusSelect" data-id="'+a.id+'">'+['Saved','Applied','Screening','Interview','Final','Offer','Rejected'].map(function(s){return '<option '+(s===a.status?'selected':'')+'>'+s+'</option>';}).join('')+'</select></td><td>'+(e?'<span class="pill '+(e.outcome==='Rejected'?'warn':'good')+'">'+esc(e.outcome)+'</span><small>'+esc(e.subject||'')+'</small>':'—')+'</td><td>'+(a.url?'<a target="_blank" rel="noopener" href="'+esc(a.url)+'">Open ↗</a>':'—')+'</td></tr>';}).join('') +
    '</tbody></table></div>';
  document.querySelector('#pageAddApp').onclick=function(){openApplicationModal(null);};
  document.querySelector('#toggleRejectedApps').onclick=async function(){
    showRejectedApplications=!showRejectedApplications;
    await renderApplicationsPage();
  };
  document.querySelector('#syncGmailFromApps').onclick=async function(){
    try{
      const result=await apiFetch('/api/gmail/sync',{method:'POST'});
      alert('Gmail sync complete: '+result.matched+' matched message(s), '+result.updated+' application status update(s).');
      await renderApplicationsPage();
    }catch(err){alert('Gmail sync failed: '+err.message);}
  };
  document.querySelectorAll('.statusSelect').forEach(function(select){
    select.onchange=async function(){
      await apiFetch('/api/applications/'+select.dataset.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:select.value})});
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

async function renderAnalyticsPage(){
  const d=await apiFetch('/api/dashboard');
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
      '<div class="card analyticsMini"><small>ATS sources configured</small><b>'+configuredAts+'/3</b></div>'+
      '<div class="card analyticsMini"><small>ATS jobs collected</small><b>'+atsJobs+'</b></div>'+
    '</div>'+
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
  const sources=await apiFetch('/api/sources');
  const status=await apiFetch('/api/assistant/status');
  const targets=await apiFetch('/api/collector-targets');
  const gmail=await apiFetch('/api/gmail/status').catch(function(){return {configured:false,connected:false};});

  document.querySelector('#pageContent').innerHTML=
    '<div class="detailGrid">' +
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
          ? '<p><span class="pill good">Connected</span> '+esc(gmail.google_email||'Gmail')+'</p><p class="muted">Last sync: '+esc(gmail.last_synced_at||'Not synced yet')+'</p><div class="prepActions"><button id="gmailSyncButton" class="primary" type="button">Sync Gmail now</button><button id="gmailDisconnectButton" class="secondary" type="button">Disconnect</button></div>'
          : (gmail.configured
              ? '<p><span class="pill warn">Not connected</span></p><button id="gmailConnectButton" class="primary" type="button">Connect Gmail</button>'
              : '<p><span class="pill warn">OAuth setup required</span></p><p class="muted">Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_GMAIL_REDIRECT_URI in your .env, then rebuild the backend.</p>')) +
        '<p class="policyNote">Permission used: Gmail read-only. JobIntel does not send, delete or modify email.</p>' +
      '</div>' +
      '<div class="card detailPage atsTargets">' +
        '<h2>Direct employer ATS collectors</h2>' +
        '<p>Configure employers using Greenhouse, Lever, SmartRecruiters or Ashby. Refresh Current Jobs will pull public postings, keep Germany/remote-EU technical roles, and put them into the same CV-matching pipeline.</p>' +
        '<form id="collectorTargetForm" class="collectorForm">' +
          '<label>Provider<select name="provider"><option value="greenhouse">Greenhouse</option><option value="ashby">Ashby</option><option value="lever">Lever (global)</option><option value="lever-eu">Lever (EU)</option><option value="smartrecruiters">SmartRecruiters</option></select></label>' +
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
async function logout(){
  try{await apiFetch('/api/auth/logout',{method:'POST'});}catch{}
  localStorage.removeItem('jobintel_token'); currentUser=null; showAuth('Logged out.');
}

async function autoSyncGmail(){
  try{
    const status=await apiFetch('/api/gmail/status');
    if(!status.connected) return;
    const last=Number(localStorage.getItem('jobintel_gmail_autosync')||0);
    if(Date.now()-last < 15*60*1000) return;
    await apiFetch('/api/gmail/sync',{method:'POST'});
    localStorage.setItem('jobintel_gmail_autosync',String(Date.now()));
  }catch{}
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

document.querySelector('#avatar').onclick=function(){routeTo('settings');};
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
