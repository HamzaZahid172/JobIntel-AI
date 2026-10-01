const API = localStorage.getItem('jobintel_api') || 'http://localhost:8100';

const nav = ['⌂ Dashboard','▣ Job Market','▤ My Applications','▤ ATS CV Check','♡ Matches','▥ Skill Gap','▧ Analytics','⚙ Settings'];
document.querySelector('#nav').innerHTML = nav.map((n,i)=>`<div class="nav ${i===0?'active':''}">${n}</div>`).join('');

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
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
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

load().catch(err => {
  document.querySelector('main').innerHTML = `<div class="error"><h2>JobIntel API is unavailable</h2><p>${esc(err.message)}</p><p>Start the stack with <code>docker compose up --build</code>.</p></div>`;
});
