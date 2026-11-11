/* 书稿字数分配工具 —— 前端交互 */
'use strict';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const ROLES = ['总主编', '主编', '副主编', '参编'];
const KIND_CN = {
  'project-head': '项目标题',
  'task': '任务',
  'project-tail': '项目检测等',
  'ref': '参考文献',
};

const state = {
  units: [],
  people: [
    { name: '夏群', role: '主编', target_words: 60000, allow_pair: true },
    { name: '邓竹君', role: '主编', target_words: 50000, allow_pair: true },
    { name: '景丽', role: '主编', target_words: 40000, allow_pair: true },
    { name: '汪涛', role: '副主编', target_words: 40000, allow_pair: true },
    { name: '卢振芝', role: '副主编', target_words: 40000, allow_pair: true },
    { name: '欧唐燕', role: '副主编', target_words: 30000, allow_pair: true },
    { name: '黄嘉嘉', role: '副主编', target_words: 30000, allow_pair: true },
    { name: '刘洁俐', role: '副主编', target_words: 30000, allow_pair: true },
    { name: '梁锦', role: '参编', target_words: 20000, allow_pair: true },
    { name: '夏紫晴', role: '参编', target_words: 20000, allow_pair: true },
  ],
  result: null,
  parsing: false,
  mode: 'ppw',   // 字数口径：ppw | total | target
};

/* ---------------- 工具函数 ---------------- */
const fmt = (n) => (n === null || n === undefined || isNaN(n)) ? '—' : Number(n).toLocaleString('zh-CN');
const wan = (n) => (n / 10000).toFixed(1) + ' 万';

function toast(msg, ms = 2400) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), ms);
}

function perPageWords() {
  return Math.max(1, parseInt($('#ppw').value, 10) || 1200);
}

function totalPages() {
  return state.units.reduce((a, u) => a + (u.pages || 0), 0);
}

/* 正文页数：不含参考文献（目录、扉页本就不在单元里） */
function bodyPages() {
  const body = state.units.filter((u) => u.kind !== 'ref');
  const n = body.reduce((a, u) => a + (u.pages || 0), 0);
  return n || totalPages();
}

/* 单元的字数权重：开启国标折算时，整页图只算满版的 20% */
function unitWeight(u) {
  const useFig = $('#figureDiscount') ? $('#figureDiscount').checked : false;
  const figs = u.figure_pages || 0;
  return useFig && figs ? Math.max(0, (u.pages || 0) - figs * 0.8) : (u.pages || 0);
}

/* 平均法下的每页字数：总字数 ÷ 正文页数 */
function avgPerPage() {
  const bp = bodyPages();
  if (!bp) return 0;
  return computeTotalWords() / bp;
}

function totalWeight() {
  return state.units.reduce((a, u) => a + unitWeight(u), 0);
}

function totalTarget() {
  return state.people.reduce((a, p) => a + (p.target_words || 0), 0);
}

/* 全书总字数的来源：
   ppw    —— 页数 × 每页字数
   total  —— 用户手动输入的总字数
   target —— 名单需求合计 */
function computeTotalWords() {
  if (state.mode === 'target') return totalTarget();
  if (state.mode === 'total') return Math.max(0, parseInt($('#totalWords').value, 10) || 0);
  return Math.round(totalWeight() * perPageWords());
}

/* 按页数比例把总字数精确分摊到每个单元（合计严格等于总字数） */
function distributeWords(total) {
  const pages = state.units.map((u) => unitWeight(u));
  const sumP = pages.reduce((a, b) => a + b, 0);
  if (!sumP) { state.units.forEach((u) => { u.words = 0; }); return; }
  const exact = pages.map((p) => (total * p) / sumP);
  const base = exact.map((x) => Math.floor(x));
  const rem = total - base.reduce((a, b) => a + b, 0);
  const order = exact.map((x, i) => [x - base[i], i]).sort((a, b) => b[0] - a[0]);
  for (let k = 0; k < rem; k++) base[order[k % order.length][1]] += 1;
  state.units.forEach((u, i) => { u.words = base[i]; });
}

function recomputeWords() {
  distributeWords(computeTotalWords());
}

/* 让「每页字数」与「全书总字数」两个输入框互相映照，并锁定非当前口径的那个 */
function syncWordInputs() {
  const pages = totalPages();
  const total = computeTotalWords();
  const ppw = pages ? Math.round(total / pages) : perPageWords();
  // 两个框都保持可编辑：用户改哪个，就以哪个为口径，另一个自动换算成派生值。
  // 「每页字数」在 ppw 口径下是输入源，绝不回写（否则输入会被自己的派生值覆盖）。
  const active = document.activeElement;
  if (state.mode !== 'ppw' && active !== $('#ppw')) $('#ppw').value = ppw;
  if (active !== $('#totalWords')) $('#totalWords').value = total || 0;
  $('#calibrate').checked = state.mode === 'target';
  const tip = $('#totalTip');
  if (tip) {
    if (!pages) {
      tip.textContent = '填这里就按总字数分摊到各章节';
    } else if (state.mode === 'ppw') {
      const eff = totalWeight();
      const figNote = Math.abs(eff - pages) > 0.01 ? `（有效 ${eff.toFixed(1)} 页）` : '';
      tip.textContent = `${fmt(pages)} 页${figNote} × ${fmt(perPageWords())} 字/页 ≈ ${fmt(total)} 字`;
    } else {
      const avg = bodyPages() ? (total / bodyPages()) : 0;
      tip.textContent =
        `正文 ${fmt(bodyPages())} 页 → 平均 ${avg.toFixed(1)} 字/页（总字数 ÷ 正文页数，不含目录、扉页、参考文献）`;
    }
  }
}

/* ---------------- 统计条 ---------------- */
function updateStats() {
  refreshMemberHint();
  const pages = totalPages();
  const words = computeTotalWords();
  const target = totalTarget();
  const gap = words - target;

  $('#stPages').textContent = pages ? pages + ' 页' : '—';
  $('#stWords').textContent = pages ? fmt(words) : '—';
  $('#stTarget').textContent = target ? fmt(target) : '—';
  const gapEl = $('#stGap');
  if (!pages || !target) {
    gapEl.textContent = '—';
    gapEl.classList.remove('warn');
  } else {
    gapEl.textContent = (gap > 0 ? '+' : '') + fmt(gap);
    gapEl.classList.toggle('warn', Math.abs(gap) > target * 0.03);
  }

  const sumEl = $('#peopleSum');
  if (sumEl) {
    sumEl.innerHTML = `共 <b>${state.people.length}</b> 人，合计需要 <b>${fmt(target)}</b> 字（${wan(target)}）`;
  }

  if (state.units.length) {
    const projCount = new Set(state.units.filter(u => u.kind === 'project-head').map(u => u.project_no)).size;
    const taskCount = state.units.filter(u => u.kind === 'task').length;
    $('#unitSummary').textContent = `${projCount} 个项目 · ${taskCount} 个任务 · ${state.units.length} 个分配单元 · 共 ${pages} 页`;
  }
}

/* ---------------- 名单 ---------------- */
function renderPeople() {
  const tb = $('#peopleTable tbody');
  tb.innerHTML = '';
  state.people.forEach((p, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="muted">${i + 1}</td>
      <td><input data-i="${i}" data-k="name" value="${escapeAttr(p.name)}" placeholder="姓名" /></td>
      <td>
        <select data-i="${i}" data-k="role">
          ${ROLES.map(r => `<option value="${r}"${r === p.role ? ' selected' : ''}>${r}</option>`).join('')}
        </select>
      </td>
      <td>
        <div class="amount">
          <input type="number" data-i="${i}" data-k="target_words" value="${p.target_words}" min="0" step="1000" />
          <span class="wan">${wan(p.target_words || 0)}</span>
        </div>
      </td>
      <td style="text-align:center">
        <input type="checkbox" data-i="${i}" data-k="allow_pair" ${p.allow_pair ? 'checked' : ''} style="width:auto" />
      </td>
      <td class="ops">
        <button class="icon-btn" data-act="up" data-i="${i}" title="上移">↑</button>
        <button class="icon-btn" data-act="down" data-i="${i}" title="下移">↓</button>
        <button class="icon-btn" data-act="del" data-i="${i}" title="删除">×</button>
      </td>`;
    tb.appendChild(tr);
  });

  tb.oninput = (e) => {
    const i = +e.target.dataset.i;
    const k = e.target.dataset.k;
    if (k === 'target_words') state.people[i][k] = parseInt(e.target.value, 10) || 0;
    else if (k === 'allow_pair') state.people[i][k] = e.target.checked;
    else state.people[i][k] = e.target.value;
    if (k === 'target_words') {
      const sub = e.target.parentElement.querySelector('.wan');
      if (sub) sub.textContent = wan(state.people[i].target_words);
    }
    updateStats();
  };
  tb.onchange = (e) => {
    if (e.target.dataset.k === 'role') {
      state.people[+e.target.dataset.i].role = e.target.value;
    }
  };
  tb.onclick = (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const i = +btn.dataset.i;
    const act = btn.dataset.act;
    if (act === 'del') {
      if (state.people.length <= 1) return toast('至少保留一位编写人员');
      state.people.splice(i, 1);
    } else if (act === 'up' && i > 0) {
      [state.people[i - 1], state.people[i]] = [state.people[i], state.people[i - 1]];
    } else if (act === 'down' && i < state.people.length - 1) {
      [state.people[i + 1], state.people[i]] = [state.people[i], state.people[i + 1]];
    }
    renderPeople();
    updateStats();
  };
  updateStats();
}

function escapeAttr(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/* ---------------- 章节单元 ---------------- */
function normalizeUnits() {
  state.units.forEach((u, i) => {
    u.index = i;
    u.pages = Math.max(0, u.pages || 0);
    u.end = u.start + u.pages - 1;
  });
  recomputeWords();
}

function renderUnits() {
  const tb = $('#unitsTable tbody');
  tb.innerHTML = '';
  normalizeUnits();

  if (!state.units.length) {
    tb.innerHTML = `<tr><td colspan="8" class="muted" style="padding:20px;text-align:center">
      尚未解析书稿：上传 PDF 自动识别，或点下方「添加单元 / 批量录入」手工建表</td></tr>`;
    updateUnitSum();
    return;
  }

  state.units.forEach((u, i) => {
    const tr = document.createElement('tr');
    tr.dataset.i = i;
    tr.innerHTML = `
      <td class="muted">${i + 1}</td>
      <td><input data-i="${i}" data-k="label" value="${escapeAttr(u.label)}" /></td>
      <td class="muted">${KIND_CN[u.kind] || u.kind}</td>
      <td><input type="number" class="num" data-i="${i}" data-k="start" value="${u.start}" min="0" /></td>
      <td><input type="number" class="num" data-i="${i}" data-k="pages" value="${u.pages}" min="0" /></td>
      <td class="num muted">${u.end}</td>
      <td class="num">${fmt(u.words)}</td>
      <td><button class="icon-btn" data-act="delUnit" data-i="${i}" title="删除">×</button></td>`;
    tb.appendChild(tr);
  });
  updateUnitSum();
}

function updateUnitSum() {
  const el = $('#unitSum');
  if (!el) return;
  el.innerHTML = state.units.length
    ? `<b>${state.units.length}</b> 个分配单元，合计 <b>${totalPages()}</b> 页 / <b>${fmt(computeTotalWords())}</b> 字`
    : '';
}

function bindUnitsTable() {
  const tb = $('#unitsTable tbody');
  tb.addEventListener('input', (e) => {
    const i = +e.target.dataset.i;
    const k = e.target.dataset.k;
    const u = state.units[i];
    if (!u) return;
    if (k === 'label') u.label = e.target.value;
    else if (k === 'start') u.start = parseInt(e.target.value, 10) || 0;
    else if (k === 'pages') u.pages = Math.max(0, parseInt(e.target.value, 10) || 0);
    u.end = u.start + u.pages - 1;
    recomputeWords();
    const rows = tb.querySelectorAll('tr');
    state.units.forEach((uu, k) => {
      const row = rows[k];
      if (!row || row.children.length < 7) return;
      row.children[5].textContent = uu.end;
      row.children[6].textContent = fmt(uu.words);
    });
    updateStats();
    updateUnitSum();
  });
  tb.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act="delUnit"]');
    if (!btn) return;
    state.units.splice(+btn.dataset.i, 1);
    renderUnits();
    updateStats();
  });
}

function guessKind(label) {
  if (/项目检测|岗位实践|能力拓展|小结|思考题/.test(label)) return 'project-tail';
  if (/^项目/.test(label)) return 'project-head';
  if (/^任务/.test(label)) return 'task';
  if (/参考文献/.test(label)) return 'ref';
  return 'other';
}

function addUnit(label = '新单元', pages = 1, start = null) {
  const last = state.units[state.units.length - 1];
  const st = start !== null ? start : (last ? last.start + last.pages : 1);
  state.units.push({
    index: state.units.length, label, kind: guessKind(label),
    start: st, end: st + pages - 1, pages, words: pages * perPageWords(),
    project_no: null,
  });
  renderUnits();
  updateStats();
}

function parseBulkLine(line) {
  const raw = line.trim();
  if (!raw) return null;
  const normalized = raw.replace(/(\d+)\s*[-–—~至]\s*(\d+)/g, '$1 $2');
  const tokens = normalized.split(/[\s　]+/).filter(Boolean);
  const nums = [];
  while (tokens.length && /^\d+$/.test(tokens[tokens.length - 1])) {
    nums.unshift(parseInt(tokens.pop(), 10));
  }
  const label = tokens.join(' ').trim();
  if (!label) return null;
  let start = 0, pages = 1;
  if (nums.length === 1) { pages = Math.max(1, nums[0]); }
  else if (nums.length >= 2) { start = nums[0]; pages = Math.max(1, nums[1] - nums[0] + 1); }
  return { label, start, pages };
}

function applyBulk(clearFirst) {
  const text = $('#bulkText').value;
  const lines = text.split('\n').map(parseBulkLine).filter(Boolean);
  if (!lines.length) return toast('没有可导入的内容');
  if (clearFirst) state.units = [];
  let cursor = state.units.length ? state.units[state.units.length - 1].start + state.units[state.units.length - 1].pages : 1;
  lines.forEach((it) => {
    const start = it.start || cursor;
    state.units.push({
      index: state.units.length, label: it.label, kind: guessKind(it.label),
      start, end: start + it.pages - 1, pages: it.pages, words: it.pages * perPageWords(),
      project_no: null,
    });
    cursor = start + it.pages;
  });
  renderUnits();
  updateStats();
  $('#bulkPanel').hidden = true;
  toast(`已导入 ${lines.length} 个单元`);
}

/* ---------------- 大文件：只传前若干页 ---------------- */
/* 解析只需要目录和开头几页，正文末尾用总页数推算，所以可以只传一小段。
   大幅降低上传体积，避免公网隧道的 100 秒上限。 */
async function slicePdfHead(file, headPages) {
  if (!window.PDFLib) throw new Error('PDF 处理库未加载');
  const { PDFDocument } = window.PDFLib;
  const buf = await file.arrayBuffer();
  const src = await PDFDocument.load(buf, { ignoreEncryption: true, updateMetadata: false });
  const total = src.getPageCount();
  if (total <= headPages) return { blob: file, totalPages: total, sliced: false };
  const out = await PDFDocument.create();
  const idx = Array.from({ length: headPages }, (_, i) => i);
  const pages = await out.copyPages(src, idx);
  pages.forEach((p) => out.addPage(p));
  const bytes = await out.save();
  return {
    blob: new Blob([bytes], { type: 'application/pdf' }),
    totalPages: total,
    sliced: true,
  };
}

/* ---------------- 上传解析 ---------------- */
async function uploadPdf(file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name)) return toast('请选择 PDF 文件');
  if (state.parsing) return;

  // 大文件走公网隧道会被 Cloudflare 的 100 秒上限掐断，提前提醒
  const mb = file.size / 1024 / 1024;
  const overTunnel = !/^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  // 超过这个体积就走「只传前 30 页」的省流量模式（切页只要 1 秒，传得更快）
  const SLICE_LIMIT_MB = 15;
  const SLICE_PAGES = 30;

  state.parsing = true;
  const note = $('#parseNote');
  note.className = 'parse-note';
  note.innerHTML = '<span class="spinner" style="border-color:#ccc;border-top-color:#1f3a5f"></span> 正在解析目录…';

  const fd = new FormData();
  let sendFile = file;
  let totalPagesOverride = null;
  if (overTunnel && mb > SLICE_LIMIT_MB && window.PDFLib) {
    try {
      note.innerHTML = '<span class="spinner" style="border-color:#ccc;border-top-color:#1f3a5f"></span> '
        + `文件较大（${mb.toFixed(0)} MB），正在提取前 ${SLICE_PAGES} 页（目录所在部分）…`;
      const sliced = await slicePdfHead(file, SLICE_PAGES);
      if (sliced.sliced) {
        sendFile = sliced.blob;
        totalPagesOverride = sliced.totalPages;
        note.innerHTML = '<span class="spinner" style="border-color:#ccc;border-top-color:#1f3a5f"></span> '
          + `已提取 ${(sliced.blob.size / 1024 / 1024).toFixed(1)} MB（原 ${mb.toFixed(0)} MB），正在解析…`;
      }
    } catch (e) {
      console.warn('切片失败，改为整本上传', e);
    }
  }
  fd.append('file', sendFile, file.name);
  if (totalPagesOverride) fd.append('total_pages', String(totalPagesOverride));
  fd.append('per_page_words', String(perPageWords()));
  fd.append('include_ref', String($('#includeRef').checked));
  const splitChk = $('#splitSections');
  fd.append('split_sections', String(splitChk ? splitChk.checked : false));
  fd.append('min_section_pages', '1');

  const t0 = performance.now();
  try {
    const res = await fetch('/api/parse', { method: 'POST', body: fd });
    if (res.status === 524 || res.status === 504) {
      throw new Error(
        '公网隧道超时（HTTP ' + res.status + '）。大文件请改用内网地址访问，' +
        '或压缩 PDF 后重试'
      );
    }
    if (res.status === 413) {
      throw new Error('文件太大，被网关拒绝（HTTP 413）。请改用内网地址或压缩 PDF');
    }
    let data;
    try {
      data = await res.json();
    } catch (e) {
      throw new Error('服务器返回异常（HTTP ' + res.status + '），可能是文件过大导致网关超时');
    }
    if (!res.ok || !data.ok) {
      throw new Error(data.detail || data.error || '解析失败');
    }
    state.bookTitle = (data.filename || '').replace(/\.pdf$/i, '');
    state.units = data.units.map((u) => ({ ...u }));
    const authorNote = data.cover_people && data.cover_people.length
      ? applyCoverResult({
          people: data.cover_people,
          skipped: data.cover_skipped || [],
          policy: data.cover_policy || {},
          warnings: [],
          title: '',
        }, { silent: true })
      : applyDetectedAuthors(data.authors);
    recomputeWords(); syncWordInputs();
    renderUnits();
    updateStats();
    const secs = ((performance.now() - t0) / 1000).toFixed(1);
    note.className = 'parse-note ok';
    note.innerHTML = `已识别《${escapeAttr(file.name)}》：${state.units.length} 个分配单元，`
      + `共 ${totalPages()} 页；书页与 PDF 物理页偏移 ${data.offset}（书页 ${data.offset + 1} 对应 PDF 第 1 页之后的第 ${data.offset} 页）。`
      + `解析耗时 ${secs}s。`;
    $('#cardUnits').classList.remove('collapsed');
    $('#resultHint').textContent = '确认名单与参数后点击生成';
  } catch (err) {
    note.className = 'parse-note';
    note.innerHTML = `<span style="color:#b3402f">解析失败：${escapeAttr(err.message)}</span>`;
    toast('解析失败：' + err.message);
  } finally {
    state.parsing = false;
  }
}

/* ---------------- 扉页名单 ---------------- */
const DEFAULT_WORDS_BY_ROLE = { 主编: 60000, 副主编: 40000, 参编: 20000 };

/* 把扉页识别到的编写名单填进名单表；总主编默认不纳入分配（一般只署名不写章节） */
function applyDetectedAuthors(authors) {
  if (!Array.isArray(authors) || !authors.length) return '';
  const workable = authors.filter((a) => a.role !== '总主编');
  const skipped = authors.length - workable.length;
  if (!workable.length) return '';
  state.people = workable.map((a) => ({
    name: a.name,
    role: a.role,
    target_words: DEFAULT_WORDS_BY_ROLE[a.role] || 20000,
    allow_pair: true,
  }));
  renderPeople();
  updateStats();
  const tail = skipped ? `，另有 ${skipped} 位总主编已识别但未纳入（只署名不写章节）` : '';
  const msg = `已从扉页识别 ${workable.length} 位编写人${tail}。字数是按角色填的默认值，请核对调整。`;
  toast(msg);
  return msg;
}

/* ---------------- 示例书 ---------------- */
async function loadDemo() {
  try {
    const res = await fetch('/static/demo.json');
    const demo = await res.json();
    state.units = demo.units.map((u) => ({ ...u }));
    state.people = demo.people.map((p) => ({ ...p }));
    state.mode = 'ppw';
    $('#ppw').value = demo.per_page_words;
    $('#calibrate').checked = false;
    recomputeWords(); syncWordInputs();
    renderPeople();
    renderUnits();
    updateStats();
    $('#parseNote').className = 'parse-note ok';
    $('#parseNote').textContent =
      `已载入示例《${demo.filename}》：${demo.units.length} 个分配单元，共 ${totalPages()} 页。`;
    $('#cardUnits').classList.remove('collapsed');
    await runAllocate();
  } catch (err) {
    toast('示例加载失败：' + err.message);
  }
}

/* ---------------- 分配 ---------------- */
function payload(extra = {}) {
  return {
    units: state.units.map((u) => ({
      index: u.index, label: u.label, kind: u.kind,
      start: u.start, end: u.end, pages: u.pages, words: u.words,
      project_no: u.project_no ?? null,
      figure_pages: u.figure_pages || 0,
    })),
    people: state.people.map((p) => ({
      name: p.name, role: p.role,
      target_words: p.target_words || 0,
      allow_pair: p.allow_pair !== false,
    })),
    per_page_words: perPageWords(),
    tolerance: parseFloat($('#tol').value) / 100,
    calibrate: state.mode === 'target',
    allow_over: $('#allowOver') ? $('#allowOver').checked : false,
    total_words: state.mode === 'total' ? (parseInt($('#totalWords').value, 10) || 0) : null,
    use_figure_discount: $('#figureDiscount') ? $('#figureDiscount').checked : true,
    hours_per_1000: parseFloat($('#hoursPerK') ? $('#hoursPerK').value : '1') || 0,
    deadline: $('#deadline') ? $('#deadline').value : '',
    book_title: state.bookTitle || '书稿',
    ...extra,
  };
}

async function runAllocate() {
  if (!state.units.length) return toast('请先上传书籍 PDF');
  if (!state.people.length) return toast('请先填写编写名单');

  const btn = $('#runBtn');
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>计算中';

  try {
    const res = await fetch('/api/allocate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload()),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '分配失败');
    state.result = data;
    renderResult();
    toast('方案已生成');
  } catch (err) {
    toast('分配失败：' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}

/* ---------------- 结果渲染 ---------------- */
function renderResult() {
  const r = state.result;
  const tb = $('#resultTable tbody');
  tb.innerHTML = '';
  if (!r) return;

  r.segments.forEach((seg) => {
    const tr = document.createElement('tr');
    if (seg.cooperative) tr.classList.add('coop-row');
    if (!seg.within_tolerance) tr.classList.add('over-row');

    const tags = [];
    if (seg.cooperative) tags.push('<span class="tag coop">合作</span>');
    if (seg.cross_project) tags.push('<span class="tag cross">跨项目</span>');
    if (!seg.within_tolerance) tags.push('<span class="tag over">超差</span>');

    const roleText = seg.members.map((m) => m.role).join(' + ');
    const nameText = seg.members.map((m) => m.name).join(' + ');
    const pct = (seg.delta_ratio * 100);
    const ratioCls = seg.within_tolerance ? 'ok' : 'bad';

    tr.innerHTML = `
      <td class="muted">${seg.order}</td>
      <td>${roleText}</td>
      <td class="who">${escapeAttr(nameText)}${tags.join('')}</td>
      <td class="chap">${escapeAttr(seg.chapter_text || seg.labels.join('；'))}</td>
      <td class="num muted">${seg.start}–${seg.end}</td>
      <td class="num">${seg.pages}</td>
      <td class="num">${fmt(seg.words)}</td>
      <td class="num muted">${fmt(seg.target)}</td>
      <td class="ratio ${ratioCls}">${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%</td>
      <td class="num muted">${seg.hours !== undefined && seg.hours > 0 ? seg.hours : '—'}</td>
      <td class="muted" style="font-size:11.5px">${escapeAttr(noteText(seg))}</td>`;
    tb.appendChild(tr);

    // 联合编写：把两个人各自负责的章节单独列出来
    if (seg.assignments && seg.assignments.length) {
      seg.assignments.forEach((a) => {
        const sub = document.createElement('tr');
        sub.className = 'assign-row';
        const subPct = a.target ? ((a.words - a.target) / a.target) * 100 : 0;
        const subCls = Math.abs(subPct) <= (r.tolerance * 100) ? 'ok' : 'bad';
        sub.innerHTML = `
          <td class="muted">└</td>
          <td><span class="assign-tag">${escapeAttr(a.role)}</span></td>
          <td class="who">${escapeAttr(a.name)}</td>
          <td class="chap">${escapeAttr(a.chapter_text || a.labels.join('；'))}</td>
          <td class="num muted">${a.start}–${a.end}</td>
          <td class="num">${a.pages}</td>
          <td class="num">${fmt(a.words)}</td>
          <td class="num muted">${fmt(a.target)}</td>
          <td class="ratio ${subCls}">${subPct >= 0 ? '+' : ''}${subPct.toFixed(1)}%</td>
          <td colspan="2" class="muted" style="font-size:11.5px">段内分得 ${a.unit_count} 个任务</td>`;
        tb.appendChild(sub);
      });
    }
  });

  // 汇总行
  const tr = document.createElement('tr');
  tr.style.fontWeight = '600';
  tr.innerHTML = `
    <td colspan="4">合计 ${r.segments.length} 段 / ${r.people_count} 人</td>
    <td class="num">${r.segments[0] ? r.segments[0].start : ''}–${r.segments.length ? r.segments[r.segments.length - 1].end : ''}</td>
    <td class="num">${r.segments.reduce((a, s) => a + s.pages, 0)}</td>
    <td class="num">${fmt(r.total_words)}</td>
    <td class="num">${fmt(r.total_target)}</td>
    <td class="num">${r.segments.reduce((a, s) => a + (s.hours || 0), 0).toFixed(1)}</td>
    <td></td>`;
  tb.appendChild(tr);

  // 横幅
  const banners = $('#banners');
  banners.innerHTML = '';
  const add = (cls, ico, text) => {
    const d = document.createElement('div');
    d.className = 'banner ' + cls;
    d.innerHTML = `<span class="b-ico">${ico}</span><span>${text}</span>`;
    banners.appendChild(d);
  };

  // 偏差降不下去的诊断
  (r.diagnosis || []).forEach((line) => add('warn', '!', escapeAttr(line)));

  if (r.mode === 'under_bound') {
    const mu = ((r.max_under || 0) * 100).toFixed(1);
    const mo = ((r.max_over || 0) * 100).toFixed(1);
    add('good', '✓',
      `按「允许超额」口径生成：最大欠额 ${mu}%（没人少写超过这个幅度），最大超额 +${mo}%。` +
      `多写的部分按实际字数认定，不影响交付。`);
  } else {
    const bound = (r.best_bound * 100).toFixed(1);
    if (r.within_declared_tolerance) {
      add('good', '✓', `全部 ${r.segments.length} 段都控制在 ±${(r.tolerance * 100).toFixed(0)}% 容差内（本书客观最小偏差 ±${bound}%）。`);
    } else {
      add('warn', '!', `本书在「任务不拆分」前提下，客观可达到的最小偏差是 ±${bound}%，你设定的 ±${(r.tolerance * 100).toFixed(0)}% 无法满足；方案已按最小偏差生成。`);
    }
  }

  const gap = r.total_words - r.total_target;
  // 字数不够：必然有人欠额，给出到字数的修正按钮
  if (gap < -Math.max(1000, r.total_target * 0.005)) {
    add('warn', '⚠',
      `全书可分配 ${fmt(r.total_words)} 字，比名单需求 ${fmt(r.total_target)} 字少 ${fmt(-gap)} 字——` +
      `这种情况下必然有人写不够，和算法无关。`);
    if (!$('#fixWordsBtn')) {
      const btn = document.createElement('button');
      btn.id = 'fixWordsBtn';
      btn.className = 'btn sm';
      btn.style.cssText = 'margin:2px 0 10px 44px';
      btn.textContent = `改为按名单需求（${fmt(r.total_target)} 字）重算`;
      btn.addEventListener('click', () => {
        const cal = $('#calibrate');
        if (cal) { cal.checked = true; cal.dispatchEvent(new Event('change', { bubbles: true })); }
        state.mode = 'target';
        recomputeWords(); syncWordInputs(); updateStats();
        $('#runBtn').click();
      });
      banners.appendChild(btn);
    }
  } else if (Math.abs(gap) > 0) {
    add('info', 'i', `可分配字数 ${fmt(r.total_words)}，名单需求 ${fmt(r.total_target)}，${gap > 0 ? '多' : '少'} ${fmt(Math.abs(gap))} 字（每页 ${fmt(r.per_page_words)} 字口径）。`);
  }

  const coops = r.segments.filter((s) => s.cooperative);
  if (coops.length) {
    add('info', 'i', `共 ${coops.length} 段采用合作编写：` +
      coops.map((s) => `${s.members.map((m) => m.name).join('+')}（第 ${s.start}–${s.end} 页）`).join('；'));
  }

  const over = r.segments.filter((s) => !s.within_tolerance);
  if (over.length) {
    add('warn', '!', `有 ${over.length} 段超出容差：` +
      over.map((s) => `${s.members.map((m) => m.name).join('+')} ${(s.delta_ratio * 100).toFixed(1)}%`).join('、') +
      `。可在「章节与页数」里核对页数，或把相近的人员调成相邻顺序后重算。`);
  }

  $('#resultHint').textContent = `${r.segments.length} 段 · 每页 ${fmt(r.per_page_words)} 字口径`;
  $('#exportBtn').disabled = false;
  $('#copyBtn').disabled = false;
}

/* ---------------- 复制为文本 ---------------- */
function resultToText() {
  const r = state.result;
  if (!r) return '';
  const rows = [['段', '角色', '编写人', '负责章节', '页码', '页数', '分配字数', '目标字数', '偏差', '折合课时', '备注']];
  r.segments.forEach((s) => {
    rows.push([
      s.order,
      s.members.map((m) => m.role).join(' + '),
      s.members.map((m) => m.name).join(' + '),
      s.chapter_text || s.labels.join('；'),
      `${s.start}-${s.end}`,
      s.pages,
      s.words,
      s.target,
      (s.delta_ratio * 100).toFixed(1) + '%',
      s.hours !== undefined && s.hours > 0 ? s.hours : '—',
      noteText(s),
    ]);
  });
  return rows.map((cols) => cols.join('\t')).join('\n');
}

/* ---------------- 从 Excel / CSV 导入名单 ---------------- */
function clearResultPanel() {
  state.result = null;
  const tb = $('#resultTable tbody');
  if (tb) tb.innerHTML = '';
  const banners = $('#banners');
  if (banners) banners.innerHTML = '';
  ['#exportBtn', '#copyBtn'].forEach((sel) => {
    const el = $(sel);
    if (el) el.disabled = true;
  });
}

/* ---------------- 自动优化名单顺序 ---------------- */
function bindOptimizeOrder() {
  const btn = $('#optimizeBtn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    if (!state.units.length) return toast('请先导入书稿，才知道有哪些章节可分');
    if (state.people.length < 2) return toast('至少需要两位编写人');
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = '搜索中…';
    try {
      const res = await fetch('/api/optimize-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '优化失败');
      const order = (data.optimized && data.optimized.order) || [];
      if (!order.length) throw new Error('没有返回顺序');
      const byName = new Map(state.people.map((p) => [p.name, p]));
      state.people = order.map((o) => byName.get(o.name) || o);
      renderPeople();
      updateStats();
      const b = data.mode === 'under_bound'
        ? `欠额 ${(data.max_under * 100).toFixed(1)}% / 超额 ${(data.max_over * 100).toFixed(1)}%`
        : `±${(data.best_bound * 100).toFixed(2)}%`;
      clearResultPanel();
      state.result = data;
      renderResult();
      $('#exportBtn').disabled = false;
      $('#copyBtn').disabled = false;
      showPolicyNote(
        `已搜索 ${data.optimized.searched} 种名单顺序，最优结果 ${b}。` +
        `顺序已自动调整为：${order.map((o) => o.name).join(' → ')}`
      );
      toast(`已优化：${b}（搜索 ${data.optimized.searched} 种顺序）`);
    } catch (err) {
      toast('优化失败：' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  });
}

/* ---------------- 上传扉页，自动识别名单 ---------------- */
function bindCoverUpload() {
  const btn = $('#coverBtn');
  const input = $('#coverFile');
  if (!btn || !input) return;
  btn.addEventListener('click', () => input.click());
  input.addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = '识别中…';
    try {
      const fd = new FormData();
      fd.append('file', file);
      const resp = await fetch('/api/parse-cover', { method: 'POST', body: fd });
      const data = await resp.json();
      if (!data.ok) {
        toast(data.error || '扉页识别失败');
        return;
      }
      applyCoverResult(data);
    } catch (err) {
      toast('扉页识别失败：' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = label;
      input.value = '';
    }
  });
}

/* 把扉页识别结果落到名单表，并说明制度口径 */
function applyCoverResult(data, opts) {
  const silent = !!(opts && opts.silent);
  state.people = data.people.map((p) => ({ ...p, allow_pair: p.allow_pair !== false }));
  if (data.title) state.bookTitle = data.title;
  clearResultPanel();
  renderPeople();
  updateStats();

  const pol = data.policy || {};
  const skipped = (data.skipped || []).map((s) => `${s.role}${s.name}`);
  const parts = [
    `已识别 ${data.people.length} 位编写人，按制度填入 ${(pol.total || 0).toLocaleString()} 字`,
  ];
  const chiefs = data.people.filter((p) => p.role === '主编').length;
  const vices = data.people.filter((p) => p.role === '副主编').length;
  const members = data.people.filter((p) => p.role === '参编').length;
  if (chiefs) parts.push(`主编 ${chiefs} 位 6/5/3 万`);
  if (vices) parts.push(`副主编 ${vices} 位各 2 万`);
  if (members) parts.push(`参编 ${members} 位暂记 0（等全书字数出来后再看余量）`);
  if (skipped.length) parts.push(`${skipped.join('、')} 只署名不分配`);

  const warn = (data.warnings || []).join('；');
  const msg = parts.join('，') + '。' + (warn ? '注意：' + warn + '。' : '');
  showPolicyNote(msg);
  if (!silent) {
    toast(msg.length > 90 ? msg.slice(0, 90) + '…' : msg);
  }
  return msg;
}

/* 名单区的制度说明条 */
function showPolicyNote(text) {
  let box = $('#policyNote');
  if (!box) {
    box = document.createElement('p');
    box.id = 'policyNote';
    box.className = 'parse-note ok';
    box.style.margin = '10px 0 0';
    const card = $('#cardPeople');
    if (card) card.appendChild(box);
  }
  box.textContent = text;
  box.style.display = text ? '' : 'none';
}

/* 全书字数已知时，测算还能给几位参编各分 1 万 */
function refreshMemberHint() {
  const box = $('#policyNote');
  if (!box) return;
  const pending = state.people.filter((p) => p.role === '参编' && !p.target_words);
  if (!pending.length) return;
  if (!state.units.length) {
    showPolicyNote('参编暂记 0 字：等书稿页数确定后，会自动算出能给几位参编各分 1 万。');
    return;
  }
  const total = computeTotalWords();
  const need = totalTarget();
  const gap = total - need;
  const each = 10000;
  const canFill = Math.max(0, Math.min(pending.length, Math.floor(gap / each)));
  if (canFill <= 0) {
    showPolicyNote(
      `全书可分配 ${fmt(total)} 字，名单需求 ${fmt(need)} 字，余 ${fmt(gap)} 字，` +
      `不够给参编各分 1 万，${pending.length} 位参编不分配。`
    );
    return;
  }
  const rest = pending.length - canFill;
  const text =
    `全书可分配 ${fmt(total)} 字，名单需求 ${fmt(need)} 字，余 ${fmt(gap)} 字：` +
    `可给前 ${canFill} 位参编各 1 万元` +
    (rest ? `，其余 ${rest} 位不分配` : '') +
    '。';
  showPolicyNote(text);
  let act = $('#memberFillBtn');
  if (!act) {
    act = document.createElement('button');
    act.id = 'memberFillBtn';
    act.className = 'btn sm';
    act.style.marginLeft = '10px';
    act.addEventListener('click', () => {
      const n = parseInt(act.dataset.n || '0', 10);
      let used = 0;
      state.people = state.people.map((p) => {
        if (p.role === '参编' && !p.target_words && used < n) {
          used += 1;
          return { ...p, target_words: 10000 };
        }
        return p;
      });
      renderPeople();
      updateStats();
      toast(`已给前 ${used} 位参编各分配 1 万字`);
    });
    box.appendChild(act);
  }
  act.dataset.n = String(canFill);
  act.textContent = `给前 ${canFill} 位参编各分 1 万`;
  act.style.display = '';
}

function bindPeopleImport() {
  const btn = $('#importPeople');
  const input = $('#peopleFile');
  if (btn && input) {
    btn.addEventListener('click', () => input.click());
    input.addEventListener('change', async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      const label = btn.textContent;
      btn.disabled = true;
      btn.textContent = '导入中…';
      try {
        const fd = new FormData();
        fd.append('file', file);
        const resp = await fetch('/api/import-people', { method: 'POST', body: fd });
        const data = await resp.json();
        if (!data.ok) {
          toast(data.error || '导入失败');
          return;
        }
        state.people = data.people;
        clearResultPanel();
        renderPeople();
        updateStats();
        const warn = (data.warnings || []).join(' ');
        toast(
          `已导入 ${data.people.length} 人（工作表「${data.sheet}」，表头在第 ${data.header_row} 行）` +
          (warn ? '。' + warn : '。请核对后重新生成方案')
        );
      } catch (err) {
        toast('导入失败：' + err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = label;
        input.value = '';
      }
    });
  }
  bindCoverUpload();
  bindOptimizeOrder();
  const tpl = $('#templateBtn');
  if (tpl) {
    tpl.addEventListener('click', () => { window.location.href = '/api/people-template'; });
  }
}

async function doCopy() {
  if (!state.result) return toast('请先生成方案');
  const text = resultToText();
  try {
    await navigator.clipboard.writeText(text);
    toast('已复制，可直接粘贴到 Word / 微信');
  } catch (err) {
    // 退化方案：创建临时 textarea
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast('已复制');
  }
}

function noteText(seg) {
  const parts = [];
  if (seg.cooperative) parts.push('合作编写');
  if (seg.cross_project) parts.push(`跨 ${seg.project_nos.length} 个项目`);
  if (!seg.within_tolerance) parts.push('建议微调');
  return parts.join('，') || '—';
}

/* ---------------- 导出 ---------------- */
async function doExport() {
  if (!state.result) return toast('请先生成方案');
  const btn = $('#exportBtn');
  btn.disabled = true;
  try {
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload()),
    });
    if (!res.ok) throw new Error('导出失败');
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '字数分配表.xlsx';
    a.click();
    URL.revokeObjectURL(a.href);
    toast('已导出 Excel');
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
}

/* ---------------- 事件绑定 ---------------- */
function bind() {
  const dz = $('#dropzone');
  const fi = $('#fileInput');
  dz.addEventListener('click', () => fi.click());
  $('#pickBtn').addEventListener('click', (e) => { e.stopPropagation(); fi.click(); });
  fi.addEventListener('change', () => { uploadPdf(fi.files[0]); fi.value = ''; });

  ['dragenter', 'dragover'].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('over'); }));
  dz.addEventListener('drop', (e) => {
    const f = e.dataTransfer.files[0];
    if (f) uploadPdf(f);
  });

  $('#ppw').addEventListener('input', () => {
    state.mode = 'ppw';
    recomputeWords(); syncWordInputs(); renderUnits(); updateStats();
  });
  $('#totalWords').addEventListener('input', () => {
    state.mode = 'total';
    recomputeWords(); syncWordInputs(); renderUnits(); updateStats();
  });
  $('#tol').addEventListener('input', (e) => { $('#tolVal').textContent = '±' + e.target.value + '%'; });
  if ($('#figureDiscount')) {
    $('#figureDiscount').addEventListener('change', () => {
      recomputeWords(); syncWordInputs(); renderUnits(); updateStats();
      const n = state.units.reduce((a, u) => a + (u.figure_pages || 0), 0);
      if (n) toast(`已${$('#figureDiscount').checked ? '启用' : '关闭'}整页图折算，全书 ${n} 页整页图`);
    });
  }
  $('#calibrate').addEventListener('change', (e) => {
    state.mode = e.target.checked ? 'target' : 'ppw';
    recomputeWords(); syncWordInputs(); renderUnits(); updateStats();
    if (e.target.checked && state.units.length) {
      toast(`总字数已对齐名单需求合计：${fmt(totalTarget())} 字`);
    }
  });
  $('#includeRef').addEventListener('change', () => {
    if (!$('#parseNote').classList.contains('ok')) return;
    toast('已切换「参考文献」口径，请重新上传 PDF 生效');
  });

  $('#addPerson').addEventListener('click', () => {
    state.people.push({ name: '', role: '参编', target_words: 20000, allow_pair: true });
    renderPeople();
  });
  bindPeopleImport();
  $('#loadDefault').addEventListener('click', async () => {
    const res = await fetch('/api/default-people');
    const data = await res.json();
    state.people = data.people.map((p) => ({ ...p, allow_pair: true }));
    renderPeople();
    toast('已载入示例名单');
  });

  $('#toggleUnits').addEventListener('click', () => $('#cardUnits').classList.toggle('collapsed'));
  $('#addUnit').addEventListener('click', () => addUnit());
  $('#toggleBulk').addEventListener('click', () => {
    const p = $('#bulkPanel');
    p.hidden = !p.hidden;
    if (!p.hidden) $('#bulkText').focus();
  });
  $('#bulkApply').addEventListener('click', () => applyBulk(false));
  $('#bulkClear').addEventListener('click', () => applyBulk(true));
  bindUnitsTable();
  $('#demoBtn').addEventListener('click', (e) => { e.stopPropagation(); loadDemo(); });
  $('#runBtn').addEventListener('click', runAllocate);
  $('#exportBtn').addEventListener('click', doExport);
  $('#copyBtn').addEventListener('click', doCopy);
}

/* ---------------- 启动 ---------------- */
bind();
renderPeople();
syncWordInputs();
renderUnits();
updateStats();

if (new URLSearchParams(location.search).get('demo') === '1') {
  loadDemo();
}
