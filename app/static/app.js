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

/* 单元的字数权重：开启国标折算时，整页图只算满版的 20% */
function unitWeight(u) {
  const useFig = $('#figureDiscount') ? $('#figureDiscount').checked : false;
  const figs = u.figure_pages || 0;
  return useFig && figs ? Math.max(0, (u.pages || 0) - figs * 0.8) : (u.pages || 0);
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
      tip.textContent = `${fmt(pages)} 页 × ${fmt(ppw)} 字/页 ≈ ${fmt(total)} 字`;
    }
  }
}

/* ---------------- 统计条 ---------------- */
function updateStats() {
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

/* ---------------- 上传解析 ---------------- */
async function uploadPdf(file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name)) return toast('请选择 PDF 文件');
  if (state.parsing) return;

  state.parsing = true;
  const note = $('#parseNote');
  note.className = 'parse-note';
  note.innerHTML = '<span class="spinner" style="border-color:#ccc;border-top-color:#1f3a5f"></span> 正在解析目录…';

  const fd = new FormData();
  fd.append('file', file);
  fd.append('per_page_words', String(perPageWords()));
  fd.append('include_ref', String($('#includeRef').checked));

  const t0 = performance.now();
  try {
    const res = await fetch('/api/parse', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.detail || data.error || '解析失败');
    }
    state.bookTitle = (data.filename || '').replace(/\.pdf$/i, '');
    state.units = data.units.map((u) => ({ ...u }));
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
    })),
    people: state.people.map((p) => ({
      name: p.name, role: p.role,
      target_words: p.target_words || 0,
      allow_pair: p.allow_pair !== false,
    })),
    per_page_words: perPageWords(),
    tolerance: parseFloat($('#tol').value) / 100,
    calibrate: state.mode === 'target',
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

  const bound = (r.best_bound * 100).toFixed(1);
  if (r.within_declared_tolerance) {
    add('good', '✓', `全部 ${r.segments.length} 段都控制在 ±${(r.tolerance * 100).toFixed(0)}% 容差内（本书客观最小偏差 ±${bound}%）。`);
  } else {
    add('warn', '!', `本书在「任务不拆分」前提下，客观可达到的最小偏差是 ±${bound}%，你设定的 ±${(r.tolerance * 100).toFixed(0)}% 无法满足；方案已按最小偏差生成。`);
  }

  const gap = r.total_words - r.total_target;
  if (Math.abs(gap) > 0) {
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
