const API = localStorage.getItem('jobintel_api') || 'http://localhost:8100';

const navItems = [
  {route:'dashboard', label:'⌂ Dashboard'},
  {route:'job-market', label:'▣ Job Market'},
  {route:'applications', label:'▤ My Applications'},
  {route:'ats', label:'▤ ATS CV Check'},
  {route:'matches', label:'♡ Matches'},
  {route:'skill-gap', label:'▥ Skill Gap'},
  {route:'analytics', label:'▧ Analytics'},
  {route:'settings', label:'⚙ Settings'}
];
let currentUser = null;
let currentRoute = 'dashboard';
let jobMarketCache = [];

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
  document.querySelector('#marketStatus').textContent =
    d.market.live
      ? (d.cv.uploaded
          ? `CV-filtered market · ${d.market.relevant_jobs} relevant of ${d.market.total_jobs} tracked · ${sourceText || 'Current feeds'} · Last sync ${fmtDate(d.market.last_sync)}`
          : `Live PostgreSQL snapshot · ${sourceText || 'Current feeds'} · Last sync ${fmtDate(d.market.last_sync)}`)
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

  document.querySelector('#performance').innerHTML =
    head('My Performance','<span class="tag">Real application outcomes</span>') +
    (d.performance.length ? d.performance.map(p=>`
      <div class="perf"><span>${esc(p.label)}</span><div class="progress"><i style="width:${p.value}%"></i></div><b>${p.value}%</b></div>
      <small class="muted">${p.applications} applications</small>`).join('')
      : empty('No performance history yet. Add applications and update their status as you progress.'));

  document.querySelector('#gaps').innerHTML = head('Skill Gap for CV-Relevant Jobs') +
    (d.skill_gap.length ? d.skill_gap.map(x=>`
      <div class="gap"><b>${esc(x.skill)}</b><span class="pill warn">${x.market_count||0} jobs</span><small>${esc(x.action)}</small></div>`).join('')
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
    const errorText = result.errors?.length ? ` Some sources reported: ${result.errors.join(', ')}` : '';
    alert(`Stored ${result.stored} current jobs. Your CV filter and match scores have been refreshed.${errorText}`);
    await load();
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
  if(route==='skill-gap') return renderSkillGapPage();
  if(route==='analytics') return renderAnalyticsPage();
  if(route==='settings') return renderSettingsPage();
}

function jobCard(job, compact){
  const score = job.match == null ? '—' : Math.round(job.match) + '%';
  const skills = (job.matched_skills && job.matched_skills.length ? job.matched_skills : job.skills || []).slice(0,6);
  const missing = (job.missing_skills || []).slice(0,4);
  return '<article class="marketJob card">' +
    '<div class="marketJobTop"><div><span class="sourceTag">' + esc(job.source) + '</span>' +
    '<h3>' + esc(job.title) + '</h3><p>' + esc(job.company) + ' · ' + esc(job.location) + '</p></div>' +
    '<div class="scoreBadge">' + score + '<small>match</small></div></div>' +
    '<div class="tagRow">' + skills.map(function(s){return '<span class="tag">' + esc(s) + '</span>';}).join('') + '</div>' +
    (!compact && missing.length ? '<p class="missingLine"><b>Missing:</b> ' + missing.map(esc).join(', ') + '</p>' : '') +
    '<div class="jobActions">' +
      (job.url ? '<a class="primaryLink" target="_blank" rel="noopener" href="' + esc(job.url) + '">Apply on source ↗</a>' : '') +
      '<button class="secondary coverLetterBtn" data-job-id="' + job.id + '">Create cover letter</button>' +
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
}

async function downloadCoverLetter(jobId, button){
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = 'Generating cover letter…';

  try{
    const token = localStorage.getItem('jobintel_token');
    const response = await fetch(API + '/api/jobs/' + jobId + '/cover-letter.docx', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + token
      }
    });

    if(!response.ok){
      let message = 'Cover letter generation failed.';
      try{
        const body = await response.json();
        message = body.detail || body.message || message;
      }catch{}
      throw new Error(message);
    }

    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = filenameMatch ? filenameMatch[1] : 'JobIntel_Cover_Letter.docx';

    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();

    setTimeout(function(){ URL.revokeObjectURL(downloadUrl); }, 1000);
    button.textContent = 'Downloaded ✓';
    setTimeout(function(){ button.textContent = originalText; }, 1600);
  }catch(err){
    alert('Cover letter could not be created: ' + err.message);
    button.textContent = originalText;
  }finally{
    button.disabled = false;
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
  const apps = await apiFetch('/api/applications');
  const page = document.querySelector('#pageContent');
  page.innerHTML = '<div class="pageToolbar card"><div><b>' + apps.length + ' tracked applications</b><small>Update status as employers respond</small></div><button id="pageAddApp" class="primary">＋ Add application</button></div>' +
    '<div class="card tableCard"><table class="dataTable"><thead><tr><th>Role</th><th>Company</th><th>Applied</th><th>Match</th><th>Status</th><th>Link</th></tr></thead><tbody>' +
    apps.map(function(a){return '<tr><td><b>'+esc(a.role)+'</b></td><td>'+esc(a.company)+'</td><td>'+esc(a.applied_date)+'</td><td>'+Math.round(a.match_score||0)+'%</td><td><select class="statusSelect" data-id="'+a.id+'">'+['Saved','Applied','Screening','Interview','Final','Offer','Rejected'].map(function(s){return '<option '+(s===a.status?'selected':'')+'>'+s+'</option>';}).join('')+'</select></td><td>'+(a.url?'<a target="_blank" rel="noopener" href="'+esc(a.url)+'">Open ↗</a>':'—')+'</td></tr>';}).join('') +
    '</tbody></table></div>';
  document.querySelector('#pageAddApp').onclick=function(){openApplicationModal(null);};
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

async function renderSkillGapPage(){
  const d=await apiFetch('/api/dashboard');
  document.querySelector('#pageContent').innerHTML='<div class="detailGrid"><div class="card detailPage"><h2>Your top skills</h2>'+(d.profile.top_skills||[]).map(function(x){return '<div class="skillDetail"><b>'+esc(x.skill)+'</b><span>'+x.market_count+' relevant jobs</span></div>';}).join('')+'</div><div class="card detailPage"><h2>Repeated gaps</h2>'+d.skill_gap.map(function(g){return '<div class="gapPage"><b>'+esc(g.skill)+'</b><span class="pill warn">'+g.market_count+' jobs</span><p>'+esc(g.action)+'</p></div>';}).join('')+'</div></div>';
}

async function renderAnalyticsPage(){
  const d=await apiFetch('/api/dashboard');
  const sourceRows=Object.entries(d.market.all_sources||{}).map(function(row){return '<div class="analyticsRow"><b>'+esc(row[0])+'</b><span>'+row[1]+' jobs</span></div>';}).join('');
  document.querySelector('#pageContent').innerHTML='<div class="analyticsGrid"><div class="card detailPage"><h2>Application funnel</h2>'+Object.entries(d.pipeline).map(function(row){return '<div class="analyticsRow"><b>'+esc(row[0])+'</b><span>'+row[1]+'</span></div>';}).join('')+'</div><div class="card detailPage"><h2>Job sources</h2>'+sourceRows+'</div><div class="card detailPage"><h2>CV performance</h2>'+(d.performance.length?d.performance.map(function(p){return '<div class="analyticsRow"><b>'+esc(p.label)+'</b><span>'+p.value+'% interview conversion · '+p.applications+' apps</span></div>';}).join(''):'<p>No outcome history yet.</p>')+'</div></div>';
}

async function renderSettingsPage(){
  const sources=await apiFetch('/api/sources');
  const status=await apiFetch('/api/assistant/status');
  document.querySelector('#pageContent').innerHTML='<div class="detailGrid"><form id="profileForm" class="card detailPage"><h2>Profile</h2><label>Name<input name="display_name" value="'+esc(currentUser.display_name)+'"></label><label>Email<input disabled value="'+esc(currentUser.email)+'"></label><label>Target roles<textarea name="target_roles" rows="3">'+esc(currentUser.target_roles||'')+'</textarea></label><label>Target locations<textarea name="target_locations" rows="2">'+esc(currentUser.target_locations||'')+'</textarea></label><button class="primary" type="submit">Save profile</button><button id="logoutButton" class="dangerButton" type="button">Logout</button></form><div class="card detailPage"><h2>Career Assistant</h2><p>Mode: <b>'+esc(status.mode)+'</b></p><p>Ollama: '+(status.ollama_online?'Online':'Offline / fallback rules')+'</p><p>Model: '+esc(status.model)+'</p><h2>Job sources</h2>'+sources.active.map(function(s){return '<div class="sourceRow"><b>'+esc(s.name)+'</b><span class="pill good">'+esc(s.status)+'</span><small>'+esc(s.mode)+'</small></div>';}).join('')+'<h3>Planned / restricted</h3>'+sources.planned.map(function(s){return '<div class="sourceRow"><b>'+esc(s.name)+'</b><span class="pill warn">'+esc(s.status)+'</span><small>'+esc(s.mode)+'</small></div>';}).join('')+'<p class="policyNote">XING and StepStone are intentionally not scraped automatically. Import individual jobs manually unless you obtain authorized integration access.</p></div></div>';
  document.querySelector('#profileForm').onsubmit=async function(e){
    e.preventDefault(); const data=Object.fromEntries(new FormData(e.target).entries());
    currentUser=await apiFetch('/api/profile',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    showApp(); alert('Profile saved.');
  };
  document.querySelector('#logoutButton').onclick=logout;
}

async function logout(){
  try{await apiFetch('/api/auth/logout',{method:'POST'});}catch{}
  localStorage.removeItem('jobintel_token'); currentUser=null; showAuth('Logged out.');
}

async function updateAssistantStatus(){
  try{
    const status=await apiFetch('/api/assistant/status');
    const el=document.querySelector('#assistantMode');
    if(el) el.textContent=status.ollama_online?'● Ollama · '+status.model:'● Rules fallback';
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
