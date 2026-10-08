'use strict';

/* Resume Forge — four steps, no framework.
   The server owns parsing, matching, drafting and linting; this file is only
   fetch, render, and the two local conveniences (print sheet, clipboard). */

const $ = (id) => document.getElementById(id);

const state = {
  step: 1,
  jd: '',
  requirements: [],
  profile: '',
  markdown: '',
  archiveId: null,
  role: '',
};

/* ── plumbing ─────────────────────────────────────────── */

async function api(path, body, asBlob) {
  const opts = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  };
  const res = await fetch(path, opts);
  if (asBlob) {
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error(err.error || 'Export failed');
    }
    return res.blob();
  }
  const data = await res.json().catch(() => ({ error: 'Server returned invalid JSON' }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function status(el, msg, kind) {
  el.textContent = msg;
  el.className = 'status' + (kind ? ' ' + kind : '');
  el.hidden = !msg;
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ── steps ────────────────────────────────────────────── */

function show(n) {
  state.step = n;
  for (let i = 1; i <= 4; i++) {
    $('panel-' + i).hidden = i !== n;
    document.querySelector(`.step[data-step="${i}"]`)
      .setAttribute('aria-selected', String(i === n));
  }
  window.scrollTo(0, 0);
}

document.querySelectorAll('.step').forEach((btn) => {
  btn.addEventListener('click', () => show(Number(btn.dataset.step)));
});

/* ── 1. job ───────────────────────────────────────────── */

$('fetchBtn').addEventListener('click', async () => {
  const url = $('jdUrl').value.trim();
  if (!url) return;
  const btn = $('fetchBtn');
  btn.disabled = true;
  status($('exportStatus'), '');
  try {
    const data = await api('/api/fetch', { url });
    $('jdText').value = data.jd;
    state.jd = data.jd;
    renderRequirements(data.requirements);
    $('parseOut').hidden = false;
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
});

$('jdFile').addEventListener('change', async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  try {
    if (file.name.toLowerCase().endsWith('.docx')) {
      const buf = await file.arrayBuffer();
      let bin = '';
      const bytes = new Uint8Array(buf);
      for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
      const data = await api('/api/upload', { docx_base64: btoa(bin) });
      $('jdText').value = data.jd;
      state.jd = data.jd;
      renderRequirements(data.requirements);
      $('parseOut').hidden = false;
    } else {
      const text = await file.text();
      $('jdText').value = text;
      state.jd = text;
      status($('jdText').closest('.panel').querySelector('.hint') || $('parseOut'), '', null);
      $('parseOut').hidden = true;
    }
  } catch (e) {
    alert(e.message);
  }
  ev.target.value = '';
});

$('parseBtn').addEventListener('click', async () => {
  const jd = $('jdText').value;
  if (!jd.trim()) return alert('Paste a job description first.');
  const btn = $('parseBtn');
  btn.disabled = true;
  btn.textContent = 'Extracting…';
  try {
    const data = await api('/api/parse', { jd });
    state.jd = jd;
    state.requirements = data.requirements;
    state.archiveId = data.archive_id;
    renderRequirements(data.requirements);
    $('parseOut').hidden = false;
    renderArchiveNote(data);
    refreshLearned();
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Extract requirements';
  }
});

/* Every paste is archived, so the term counts and outcome history grow. Say so
   plainly rather than letting it happen silently. */
function renderArchiveNote(data) {
  const s = data.stats || {};
  if (data.already_seen) {
    $('archiveNote').textContent =
      'Seen before — not counted twice. Your archive holds ' +
      (s.postings || 0) + ' posting(s).';
  } else if (data.archived) {
    $('archiveNote').textContent =
      'Saved to your archive as posting #' + data.archive_id + '. Your ' +
      'archive now holds ' + (s.postings || 0) +
      ' posting(s) and ' + (s.unique_terms || 0) + ' distinct terms.';
  } else {
    $('archiveNote').textContent =
      'Could not write to the archive (read-only?). Everything else still works.';
  }
}

/* The learned signals, straight from the archive. */
async function refreshLearned() {
  let brief = '';
  try {
    brief = (await api('/api/learn/brief', { role: state.role })).brief || '';
  } catch { return; }
  if (!brief) return;
  $('learnBody').innerHTML =
    '<p class="evidence" style="margin:0">' + esc(brief) + '</p>';
  $('learnBox').hidden = false;
}

/* Outcome buttons. Reporting one is what turns a pile of postings into a
   record of which requirements this market actually confirms. */
const OUTCOMES = [
  ['applied', 'Applied'],
  ['interview', 'Interview'],
  ['offer', 'Offer'],
  ['rejected', 'Rejected'],
  ['ghosted', 'No response'],
];

function renderOutcomeButtons() {
  const box = $('outcomeBtns');
  box.innerHTML = '';
  for (const [value, label] of OUTCOMES) {
    const btn = document.createElement('button');
    btn.className = 'ghost';
    btn.textContent = label;
    btn.addEventListener('click', async () => {
      if (!state.archiveId) {
        return status($('outcomeNote'), 'This posting was not archived.', 'err');
      }
      btn.disabled = true;
      try {
        const data = await api('/api/learn/outcome', {
          id: state.archiveId,
          outcome: value,
        });
        status(
          $('outcomeNote'),
          'Recorded: ' + label + '. Archive now holds ' +
            data.stats.postings + ' posting(s), ' +
            data.stats.confirmed_terms + ' confirmed term(s).',
          'ok'
        );
        $('outcomeNote').hidden = false;
        refreshLearned();
      } catch (e) {
        status($('outcomeNote'), e.message, 'err');
      }
    });
    box.appendChild(btn);
  }
}

/* Each requirement is editable: the text can be corrected and the
   required/preferred polarity flipped before matching runs. */
function renderRequirements(reqs) {
  state.requirements = reqs.map((r) => ({ ...r }));
  $('reqCount').textContent = state.requirements.length;
  const box = $('reqList');
  box.innerHTML = '';

  state.requirements.forEach((req, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'req';
    wrap.innerHTML =
      '<textarea aria-label="Requirement text"></textarea>' +
      '<select aria-label="Requirement kind">' +
      '<option value="required">required</option>' +
      '<option value="preferred">preferred</option>' +
      '</select>';
    const ta = wrap.querySelector('textarea');
    const sel = wrap.querySelector('select');
    ta.value = req.text;
    sel.value = req.kind;
    ta.addEventListener('input', () => { state.requirements[i].text = ta.value; });
    sel.addEventListener('change', () => {
      state.requirements[i].kind = sel.value;
      ta.className = sel.value === 'required' ? 'kind-required' : 'kind-preferred';
    });
    ta.className = req.kind === 'required' ? 'kind-required' : 'kind-preferred';
    box.appendChild(wrap);
  });

  if (!state.requirements.length) {
    box.innerHTML = '<p class="hint">Nothing extracted. Add the requirements by hand below.</p>';
  }
}

$('toProfile').addEventListener('click', () => show(2));

/* ── 2. profile ───────────────────────────────────────── */

const TEMPLATE = `# Your Name
email@you.com | +1 555 0100 | City, Country | linkedin.com/in/you

## Preferences
- pages: 2
- market: US
- language: English

## Skills
Python, PostgreSQL, AWS, Kubernetes, Docker, Terraform, GraphQL, CI/CD

## Experience

### Senior Backend Engineer | Acme Corp | 2021 - Present
- Led migration of a monolith to 12 Python microservices serving 4M requests/day
- Cut p99 latency from 840ms to 210ms by adding Redis caching and query tuning
- Owned the on-call rotation for 9 services across 3 AWS regions
- Mentored 4 engineers; 2 were promoted within 18 months

### Software Engineer | Beta Labs | 2019 - 2021
- Built React dashboard used daily by 300 internal staff
- Wrote the CI/CD pipeline in GitHub Actions, cutting deploys from 40min to 4min
- Shipped PostgreSQL schema redesign that removed 2TB of redundant data

## Projects
- Side project X — description, link, what you built

## Education
### B.S. Computer Science | University | 2015 - 2019
`;

$('loadTpl').addEventListener('click', () => {
  $('profileText').value = TEMPLATE;
});

$('matchBtn').addEventListener('click', async () => {
  const profile = $('profileText').value;
  const btn = $('matchBtn');
  btn.disabled = true;
  btn.textContent = 'Matching…';
  try {
    const data = await api('/api/match', {
      profile,
      requirements: state.requirements,
    });
    state.profile = profile;
    state.role = data.role || '';
    renderMatch(data);
    $('matchOut').hidden = false;
    refreshLearned();
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save & match';
  }
});

function renderMatch(data) {
  const s = data.summary;
  $('matchCounts').textContent =
    `${s.covered} covered · ${s.partial} partial · ${s.gap} gap · ` +
    `${s.required_covered}/${s.required_total} required met`;

  const items = data.open_items;
  const box = $('openItems');
  box.innerHTML = '';

  if (!items.length) {
    box.innerHTML = '<p class="clean">Every extracted requirement has profile support.</p>';
  } else {
    const lead = document.createElement('p');
    lead.className = 'hint';
    lead.textContent =
      'Answer these into your profile above. Anything you add here becomes ' +
      'usable in the draft — anything you skip simply will not appear.';
    box.appendChild(lead);

    for (const item of items) {
      const div = document.createElement('div');
      div.className = 'item ' + item.status;

      const pill = document.createElement('span');
      pill.className = 'pill ' + item.status;
      pill.textContent = item.status === 'gap' ? 'no support' : 'adjacent';

      const kind = document.createElement('span');
      kind.className = 'count';
      kind.textContent = item.kind;

      const p = document.createElement('p');
      p.append(pill, kind, document.createTextNode(' ' + item.text));

      const terms = document.createElement('div');
      terms.className = 'terms';
      terms.textContent = 'unsupported: ' + item.missing.join(', ');

      div.append(p, terms);

      if (item.adjacent_evidence && item.adjacent_evidence.length) {
        const ev = document.createElement('div');
        ev.className = 'evidence';
        ev.textContent = 'closest in your profile: ' + item.adjacent_evidence[0];
        div.appendChild(ev);
      }

      const ta = document.createElement('textarea');
      ta.rows = 2;
      ta.placeholder = 'If you have this experience, describe it here and re-run the match.';
      ta.addEventListener('input', () => {
        if (ta.value.trim()) {
          div.className = 'item partial';
          pill.textContent = 'added';
        }
      });
      div.appendChild(ta);

      box.appendChild(div);
    }
  }

  const rows = document.createElement('div');
  for (const r of data.matrix.rows) {
    const div = document.createElement('div');
    div.className = 'mrow ' + r.status;

    const pill = document.createElement('span');
    pill.className = 'pill ' + r.status;
    pill.textContent = r.status;

    const p = document.createElement('p');
    p.append(pill, document.createTextNode(' ' + r.text));
    div.appendChild(p);

    const terms = document.createElement('div');
    terms.className = 'terms';
    terms.innerHTML = r.terms
      .map((t) => `<span class="t ${r.term_status[t]}">${esc(t)}</span>`)
      .join(' · ');
    div.appendChild(terms);

    if (r.evidence.length) {
      const ev = document.createElement('div');
      ev.className = 'evidence';
      ev.textContent = r.evidence.slice(0, 2).join('  |  ');
      div.appendChild(ev);
    }
    rows.appendChild(div);
  }
  $('matrixRows').innerHTML = '';
  $('matrixRows').appendChild(rows);
}

$('toDraft').addEventListener('click', () => show(3));

/* ── 3. draft ─────────────────────────────────────────── */

$('tailorBtn').addEventListener('click', async () => {
  const btn = $('tailorBtn');
  btn.disabled = true;
  status($('tailorStatus'), 'Drafting… the model only sees your profile and the posting.');
  try {
    const data = await api('/api/tailor', {
      profile: state.profile || $('profileText').value,
      requirements: state.requirements,
      jd: state.jd,
    });
    $('draftMd').value = data.markdown;
    state.markdown = data.markdown;
    renderWarnings(data);
    $('draftOut').hidden = false;
    status($('tailorStatus'), 'Draft written. Edit freely, then re-check.', 'ok');
  } catch (e) {
    status($('tailorStatus'), e.message, 'err');
  } finally {
    btn.disabled = false;
  }
});

function renderWarnings(data) {
  const all = [];
  for (const w of data.fabrication_warnings) {
    all.push(
      `<strong>Unsourced number “${esc(w.number)}”</strong> in ` +
      `${esc(w.role)}: ${esc(w.bullet)} — not in your profile. Delete or correct it.`
    );
  }
  for (const w of data.model_warnings || []) {
    all.push(esc(w));
  }
  const box = $('warnBox');
  $('warnList').innerHTML = all.length
    ? '<ul>' + all.map((h) => `<li>${h}</li>`).join('') + '</ul>'
    : '';
  box.hidden = !all.length;
}

$('relintBtn').addEventListener('click', async () => {
  state.markdown = $('draftMd').value;
  try {
    const data = await api('/api/lint', {
      markdown: state.markdown,
      requirements: state.requirements,
    });
    renderViolations(data.violations);
    show(4);
  } catch (e) {
    alert(e.message);
  }
});

$('useManual').addEventListener('click', () => {
  const text = $('manualDraft').value;
  if (!text.trim()) return alert('Paste a draft first.');
  $('draftMd').value = text;
  state.markdown = text;
  $('draftOut').hidden = false;
});

$('draftMd').addEventListener('input', (e) => { state.markdown = e.target.value; });

$('toExport').addEventListener('click', async () => {
  state.markdown = $('draftMd').value;
  try {
    const data = await api('/api/lint', {
      markdown: state.markdown,
      requirements: state.requirements,
    });
    renderViolations(data.violations);
    buildPrintSheet(state.markdown);
  } catch (e) {
    alert(e.message);
  }
  show(4);
});

/* ── 4. export ────────────────────────────────────────── */

function renderViolations(violations) {
  const box = $('violations');
  box.innerHTML = '';
  $('lintCount').textContent = violations.length
    ? `${violations.length} to fix`
    : 'clean';

  if (!violations.length) {
    box.innerHTML =
      '<p class="clean">No named violations. Read it once yourself — this ' +
      'checks structure and language, not whether the claims are true.</p>';
    return;
  }

  for (const v of violations) {
    const div = document.createElement('div');
    div.className = 'viol' + (v.severity === 'medium' ? ' medium' : '');
    div.innerHTML =
      `<div class="rule">${esc(v.rule)}</div>` +
      `<div class="offending">${esc(v.line)}</div>` +
      `<p class="fix">${esc(v.fix)}</p>`;
    box.appendChild(div);
  }
}

function slug() {
  const first = state.markdown.split('\n')[0] || 'Resume';
  return first.replace(/^#\s*/, '').trim().replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-|-$/g, '') || 'Resume';
}

$('downloadDocx').addEventListener('click', async () => {
  status($('exportStatus'), 'Building .docx…');
  try {
    const blob = await api(
      '/api/docx',
      { markdown: state.markdown, title: slug() },
      true
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = slug() + '.docx';
    a.click();
    URL.revokeObjectURL(url);
    status($('exportStatus'), 'Downloaded. Open it and check it looks right.', 'ok');
  } catch (e) {
    status($('exportStatus'), e.message, 'err');
  }
});

$('downloadPdf').addEventListener('click', async () => {
  status($('exportStatus'), 'Rendering PDF…');
  try {
    const blob = await api('/api/pdf', {
      markdown: state.markdown,
      title: slug(),
    }, true);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = slug() + '.pdf';
    a.click();
    URL.revokeObjectURL(url);
    status(
      $('exportStatus'),
      'Downloaded. Text-based, so a parser can read it. Open it once to check.',
      'ok'
    );
  } catch (e) {
    status($('exportStatus'), e.message, 'err');
  }
});

/* Print to PDF via the browser. Same stylesheet the Download .pdf button uses,
   so the two produce the same document. */
$('printPdf').addEventListener('click', () => {
  buildPrintSheet(state.markdown);
  window.print();
});

$('copyMd').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(state.markdown);
    status($('exportStatus'), 'Markdown copied.', 'ok');
  } catch {
    status($('exportStatus'), 'Clipboard blocked — select and copy manually.', 'err');
  }
});

$('downloadTxt').addEventListener('click', async () => {
  try {
    const data = await api('/api/lint', {
      markdown: state.markdown,
      requirements: state.requirements,
    });
    const blob = new Blob([data.plain_text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = slug() + '.txt';
    a.click();
    URL.revokeObjectURL(url);
    status(
      $('exportStatus'),
      'Saved. Read it top to bottom — that is what the parser sees.',
      'ok'
    );
  } catch (e) {
    status($('exportStatus'), e.message, 'err');
  }
});

/* ── print sheet ──────────────────────────────────────── */

/* Markdown -> the DOM the print stylesheet targets. Deliberately plain: one
   column, no tables, no images, because that is the ATS constraint. */
function buildPrintSheet(md) {
  const sheet = $('printSheet');
  sheet.innerHTML = '';
  const lines = md.split('\n');
  let ul = null;

  const closeList = () => { ul = null; };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { closeList(); continue; }

    const bullet = line.match(/^[-*]\s+(.*)$/);
    if (bullet) {
      if (!ul) {
        ul = document.createElement('ul');
        sheet.appendChild(ul);
      }
      const li = document.createElement('li');
      li.textContent = inline(bullet[1]);
      ul.appendChild(li);
      continue;
    }
    closeList();

    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      const text = h[2];
      if (level === 1) {
        const h1 = document.createElement('h1');
        h1.textContent = text;
        sheet.appendChild(h1);
      } else if (level === 2) {
        const h2 = document.createElement('h2');
        h2.textContent = text;
        sheet.appendChild(h2);
      } else {
        // Role heading: split a trailing date range onto the right.
        const m = text.match(
          /^(.*?)[\s|]+((?:19|20)\d{2}\s*[–—-]\s*(?:(?:19|20)\d{2}|Present|Current|Now))$/i
        );
        if (m) {
          const div = document.createElement('div');
          div.className = 'role-meta';
          const left = document.createElement('span');
          left.textContent = m[1].trim();
          const right = document.createElement('span');
          right.textContent = m[2].trim();
          div.append(left, right);
          sheet.appendChild(div);
        } else {
          const h3 = document.createElement('h3');
          h3.textContent = text;
          sheet.appendChild(h3);
        }
      }
      continue;
    }

    if (/^(-{3,}|={3,})$/.test(line)) continue;

    // The line directly after the h1 is the contact line.
    if (sheet.querySelector('h1') && !sheet.querySelector('h2') && !sheet.querySelector('.contact')) {
      const div = document.createElement('div');
      div.className = 'contact';
      div.textContent = line;
      sheet.appendChild(div);
      continue;
    }

    const p = document.createElement('p');
    p.innerHTML = inline(line);
    sheet.appendChild(p);
  }
}

/* Minimal inline handling: bold and code only. Nothing that a parser would
   have to untangle. */
function inline(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
}

/* ── boot ─────────────────────────────────────────────── */

(async function boot() {
  renderOutcomeButtons();
  try {
    const health = await fetch('/api-health').then((r) => r.json());
    $('statusBadge').hidden = false;
    $('statusBadge').textContent = health.has_api_key
      ? `key set · ${health.model}`
      : 'no API key · paste a draft instead';
    if (health.profile_exists) {
      const data = await api('/api/profile', {});
      $('profileText').value = data.profile;
      state.profile = data.profile;
    } else {
      $('profileText').value = TEMPLATE;
    }
    await refreshLearned();
  } catch {
    /* Offline-ish start is fine; the app still works for manual drafts. */
  }
})();