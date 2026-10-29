/* 公考备考台 · 纯静态网页客户端
 * 数据流：方法库/题库/错题 → 浏览器 IndexedDB（不上传任何服务器）
 * 模型：用户自配 OpenAI 兼容端点（/chat/completions，SSE 流式）
 */
'use strict';

/* ---------------- 提示词（从 xingce-review-pro / kaogong 协议提炼的网页版） ---------------- */

const MODE_PROMPTS = {
  'free': '你是公考备考助手，服务国考、浙江省考、江西省考、浙江事业编和江西事业编。先给结论和关键步骤，按需展开；不确定的考试信息（年份、类别）保持未知，不猜测。',

  'xingce-solve': `你是行测讲解员（网页版 xingce 协议）。按以下顺序输出：
1. 题型识别
2. 答案来源与结论（无官方答案的易争议题只给方法倾向，写明"本题未经官方核验"）
3. 关键推理/计算过程（只基于用户给的题面，独立复核计算与单位）
4. 用户答案处理（用户给了答案才写；没给思路时不推断确定错因，只标"待确认"）
5. 方法讲解与速度评估（为什么用、怎么做、预计用时、关键步骤数、模型推理风险、是否值得做）
6. 易错点与复盘动作
规则：题目模糊、数据缺失或答案冲突时停止确定性判断并列明待核对项；不虚构真题来源。`,

  'xingce-review': `你是行测复盘教练（网页版 xingce 复盘协议）。流程：
第一轮：只记录用户的答案，不判对错，先问"你为什么这么选，又是怎么排除其他选项的？你也可以直接说'讲吧'。"
用户回应后进入讲解：题型识别 → 答案来源与结论 → 用户答案判定（有官方答案按其判定；无官方答案只写与方法倾向一致/不一致，不判对错）→ 完整推理 → 方法讲解与速度评估 → 错因定位（必须有用户思路或确认作依据，否则标"待确认"）→ 下一步训练动作。
只有用户答案已核验为错误且完整讲解完成时，界面才会提供"存错题"按钮。`,

  'shenlun': `你是申论/综应/职测/公基备考教练（网页版 kaogong 协议）。反馈分三层：材料证据（引用用户作答原文）、结构建议（怎么改）、训练量表（自评维度，不冒称官方分数）。当年考纲、公告、法律与时政信息不确定时明确提示需核对官方来源，不用记忆里的旧口径充当最新政策。`,
};

const MODULE_HINTS = [
  [/资料分析|增长率|增长量|比重|基期|现期|平均数|倍数/, ['资料分析', '速算', '增长', '比重', '基期', '现期']],
  [/类比推理|类比/, ['类比']],
  [/逻辑填空|成语|实词|搭配|填空/, ['逻辑填空', '成语', '实词', '搭配']],
  [/片段阅读|主旨|意图|细节|标题|排序|填句/, ['片段阅读', '主旨', '意图', '细节', '语句']],
  [/定义判断|定义/, ['定义判断']],
  [/削弱|加强|前提|论证|翻译|真假|分析推理/, ['削弱', '加强', '前提', '翻译', '分析推理']],
  [/图形|九宫格|六面体|折叠/, ['图形']],
  [/数量关系|方程|行程|工程|概率|排列|几何/, ['数量关系', '方程', '行程', '工程', '概率']],
];

/* ---------------- Markdown 渲染（marked 本地打包 + 轻量消毒） ---------------- */

function sanitizeHtml(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll('script,iframe,object,embed,link,meta').forEach(n => n.remove());
  doc.querySelectorAll('*').forEach(n => {
    [...n.attributes].forEach(a => {
      if (/^on/i.test(a.name) || a.value.trim().toLowerCase().startsWith('javascript:')) n.removeAttribute(a.name);
    });
  });
  return doc.body.innerHTML;
}

function renderMd(raw) {
  let html;
  try {
    html = marked.parse(String(raw || ''), { breaks: true, gfm: true });
  } catch (e) {
    html = esc(raw);
  }
  return sanitizeHtml(html);
}

/* 流式期间节流重绘，结束后强制刷一帧最终版式 */
function throttlePaint(fn, ms = 150) {
  let timer = null, hasPending = false;
  const run = () => { timer = null; fn(); };
  return {
    kick() { hasPending = true; if (!timer) timer = setTimeout(run, ms); },
    flush() { if (timer) { clearTimeout(timer); timer = null; } if (hasPending) { hasPending = false; fn(); } },
  };
}

/* ---------------- 小工具 ---------------- */

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* 题库 stem/options 含 HTML：转纯文本用于展示与提示词 */
function stripHtml(s) {
  return String(s ?? '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|li|tr|h[1-6])>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/\n{3,}/g, '\n\n').trim();
}
const hasImg = (q) => /<img|<svg/i.test(q.stem || '') || (q.options || []).some(o => /<img|<svg/i.test(o.text || ''));

async function sha256Hex(text) {
  if (crypto && crypto.subtle) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
  }
  let h1 = 0x12345678, h2 = 0x9e3779b9;
  for (let i = 0; i < text.length; i++) {
    h1 = (h1 ^ text.charCodeAt(i)) * 16777619 >>> 0;
    h2 = (h2 + text.charCodeAt(i) * (i + 7)) >>> 0;
  }
  return (h1.toString(16) + h2.toString(16)).padStart(16, '0');
}

/* ---------------- IndexedDB ---------------- */

const DB = { db: null };

function dbOpen() {
  if (DB.db) return Promise.resolve(DB.db);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('kaogong-web', 2);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('files')) db.createObjectStore('files', { keyPath: 'path' });
      if (!db.objectStoreNames.contains('bank')) db.createObjectStore('bank', { keyPath: 'qid' });
      if (!db.objectStoreNames.contains('records')) db.createObjectStore('records', { keyPath: 'event_id' });
      if (!db.objectStoreNames.contains('chats')) db.createObjectStore('chats', { keyPath: 'id' });
    };
    req.onsuccess = () => { DB.db = req.result; resolve(DB.db); };
    req.onerror = () => reject(req.error);
  });
}

function tx(store, mode, fn) {
  return dbOpen().then(db => new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const req = fn(t.objectStore(store));
    t.oncomplete = () => resolve(req && req.result);
    t.onerror = () => reject(t.error);
  }));
}
const dbPut   = (store, val) => tx(store, 'readwrite', s => s.put(val));
const dbGetAll= (store) => tx(store, 'readonly', s => s.getAll());
const dbClear = (store) => tx(store, 'readwrite', s => s.clear());
const dbCount = (store) => tx(store, 'readonly', s => s.count());

/* 分块批量写入：一个事务写 CHUNK 条，块间让出事件循环刷新进度 */
async function bulkPut(store, items, onProgress, chunk = 800) {
  for (let i = 0; i < items.length; i += chunk) {
    const slice = items.slice(i, i + chunk);
    await tx(store, 'readwrite', s => { for (const it of slice) s.put(it); });
    if (onProgress) onProgress(Math.min(i + chunk, items.length), items.length);
  }
  return items.length;
}

function progress(text) {
  const el = $('#import-progress');
  el.style.display = text ? 'block' : 'none';
  el.textContent = text || '';
}

function parseBankJsonl(text) {
  const out = [];
  for (const line of text.split('\n')) {
    const s = line.trim();
    if (!s) continue;
    try {
      const q = JSON.parse(s);
      if (q.qid && q.stem) out.push(q);
    } catch (e) { /* 跳过坏行 */ }
  }
  return out;
}

/* ---------------- 设置 ---------------- */

const Settings = {
  data: { base: '', key: '', model: '', proxy: false },
  load() {
    try { Object.assign(this.data, JSON.parse(localStorage.getItem('kg.settings') || '{}')); } catch (e) {}
    $('#set-base').value = this.data.base;
    $('#set-key').value = this.data.key;
    $('#set-model').value = this.data.model;
    $('#set-proxy').checked = !!this.data.proxy;
  },
  save() {
    this.data = { base: $('#set-base').value.trim(), key: $('#set-key').value.trim(), model: $('#set-model').value.trim(), proxy: $('#set-proxy').checked };
    localStorage.setItem('kg.settings', JSON.stringify(this.data));
    flash('设置已保存（仅本浏览器）');
  },
  ready() { return this.data.base && this.data.model; },
};

function flash(text, isError) {
  const el = document.createElement('div');
  el.className = 'msg';
  el.innerHTML = `<div class="who">ℹ️</div><div class="bubble ${isError ? 'err-box' : ''}">${esc(text)}</div>`;
  $('#chat-log').appendChild(el);
  scrollChat();
}

/* ---------------- OpenAI 兼容流式调用 ---------------- */

async function chatStream(messages, onDelta) {
  if (!Settings.ready()) throw new Error('请先在「设置」里填 Base URL 和模型名');
  const useProxy = Settings.data.proxy;
  const url = useProxy
    ? location.origin + '/llm/chat/completions'
    : Settings.data.base.replace(/\/+$/, '') + '/chat/completions';
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(Settings.data.key ? { 'Authorization': 'Bearer ' + Settings.data.key } : {}),
        ...(useProxy ? { 'X-Target-Base': Settings.data.base.replace(/\/+$/, '') } : {}),
      },
      body: JSON.stringify({ model: Settings.data.model, messages, stream: true, temperature: 0.3 }),
    });
  } catch (e) {
    throw new Error('连接失败：' + e.message + ' —— 若用自建端点，多为 CORS 拦截：勾选「本地代理」（serve.py 启动）即可绕过；Ollama 也可设 OLLAMA_ORIGINS=*。');
  }
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    let hint = '';
    try {
      const err = JSON.parse(body).error?.message;
      if (err) hint = ' —— ' + err + '（模型名是否正确？注意大小写）';
    } catch (e) {}
    throw new Error('HTTP ' + res.status + '：' + body.slice(0, 300) + hint);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '', full = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      const s = line.trim();
      if (!s.startsWith('data:')) continue;
      const payload = s.slice(5).trim();
      if (payload === '[DONE]') continue;
      try {
        const d = JSON.parse(payload).choices?.[0]?.delta;
        // 兼容思考型模型（如 Qwen3 系列）：reasoning_content 先流式到达
        const reason = d && (d.reasoning_content || d.reasoning);
        if (reason) { onDelta({ type: 'reason', text: reason }); }
        if (d && d.content) { full += d.content; onDelta({ type: 'content', text: d.content }); }
      } catch (e) { /* 忽略不完整行 */ }
    }
  }
  return full;
}

/* 把流式增量写入气泡：思考灰显纯文本，正文按 Markdown 节流渲染，首字前显示等待提示 */
function makeStreamer(bubble) {
  const wait = document.createElement('div');
  wait.className = 'hint';
  wait.textContent = '⏳ 等待模型输出（自建服务器首个字可能要一两分钟）…';
  bubble.appendChild(wait);

  let rSpan = null, rLen = 0;
  let cDiv = null, contentRaw = '';
  const paint = () => {
    if (!cDiv) { cDiv = document.createElement('div'); cDiv.className = 'md'; bubble.appendChild(cDiv); }
    cDiv.innerHTML = renderMd(contentRaw);
    scrollChat();
  };
  const kick = throttlePaint(paint).kick;

  return {
    onDelta(d) {
      if (wait.parentNode) wait.remove();
      if (d.type === 'reason') {
        rLen += d.text.length;
        if (!rSpan) { rSpan = document.createElement('span'); rSpan.className = 'reasoning'; bubble.appendChild(rSpan); }
        if (rLen <= 4000) rSpan.textContent = '〔思考〕' + (rSpan.dataset.tail || '') + d.text;
        else { rSpan.dataset.tail = (rSpan.dataset.tail || '') + d.text; rSpan.textContent = '〔思考超过 4000 字，已折叠，继续生成中…〕'; }
        scrollChat();
      } else {
        contentRaw += d.text;
        kick();
      }
    },
    flush() {
      if (wait.parentNode) wait.remove();
      if (contentRaw) { throttlePaint(paint).flush(); paint(); }
    },
    get raw() { return contentRaw; },
  };
}

/* ---------------- 方法库检索注入 ---------------- */

function pickKeywords(text) {
  const hits = [];
  for (const [re, kws] of MODULE_HINTS) if (re.test(text)) hits.push(...kws);
  return hits.length ? hits : ['行测', '方法'];
}

async function retrieveCards(userText, limit = 6, maxChars = 14000) {
  const files = await dbGetAll('files');
  if (!files.length) return '';
  const kws = pickKeywords(userText);
  const scored = [];
  for (const f of files) {
    if (!/\.md$/.test(f.path) || f.path.includes('exam-research')) continue;
    let score = 0;
    const name = f.path.split('/').pop();
    for (const kw of kws) {
      if (name.includes(kw)) score += 5;
      const occurrences = f.text.split(kw).length - 1;
      if (occurrences) score += Math.min(occurrences, 6);
    }
    if (/方法卡\/am-card/.test(f.path)) score *= 1.3;
    if (score > 0) scored.push({ f, score });
  }
  scored.sort((a, b) => b.score - a.score);
  let out = '', used = 0;
  for (const { f } of scored) {
    if (used >= limit || out.length >= maxChars) break;
    const chunk = f.text.slice(0, 2600);
    out += `\n【方法卡 ${name(f.path)}】\n${chunk}\n`;
    used++;
  }
  return out ? '以下是本机方法库检索到的参考资料（依据时引用卡名）：\n' + out : '';

  function name(p) { return p.split('/').pop().replace(/\.md$/, ''); }
}

async function buildMessages(history, userText) {
  const mode = $('#mode').value;
  const sys = MODE_PROMPTS[mode];
  let context = '';
  if (mode.startsWith('xingce')) context = await retrieveCards(userText);
  const msgs = [{ role: 'system', content: sys + (context ? '\n\n' + context : '') }];
  for (const m of history.slice(-8)) msgs.push({ role: m.role, content: m.content });
  msgs.push({ role: 'user', content: userText });
  return msgs;
}

/* ---------------- 对话历史（IndexedDB 持久化） ---------------- */

let currentChatId = null;

function chatTitle() {
  const first = history.find(m => m.role === 'user');
  return first ? first.content.replace(/\s+/g, ' ').slice(0, 24) : '新对话';
}

async function saveChat() {
  if (!history.length) return;
  if (!currentChatId) currentChatId = 'c-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  await dbPut('chats', { id: currentChatId, title: chatTitle(), updatedAt: Date.now(), messages: history.slice() });
  renderHistList();
}

async function renderHistList() {
  let chats = [];
  try { chats = (await dbGetAll('chats')).sort((a, b) => b.updatedAt - a.updatedAt); } catch (e) {}
  const list = $('#hist-list');
  list.innerHTML = '';
  if (!chats.length) { list.innerHTML = '<div class="hist-empty">还没有对话，发第一条消息开始。</div>'; return; }
  chats.slice(0, 50).forEach(c => {
    const el = document.createElement('div');
    el.className = 'hist-item' + (c.id === currentChatId ? ' active' : '');
    el.innerHTML = `<span class="t">${esc(c.title)}</span><button class="del" title="删除此对话">×</button>`;
    el.addEventListener('click', e => {
      if (e.target.classList.contains('del')) return;
      openChat(c.id);
    });
    el.querySelector('.del').addEventListener('click', async () => {
      await tx('chats', 'readwrite', s => s.delete(c.id));
      if (currentChatId === c.id) newChat();
      renderHistList();
    });
    list.appendChild(el);
  });
}

function newChat() {
  history = [];
  currentChatId = null;
  $('#chat-log').innerHTML = '';
  renderHistList();
  $('#chat-input').focus();
}

async function openChat(id) {
  const c = await tx('chats', 'readonly', s => s.get(id));
  if (!c) return;
  currentChatId = c.id;
  history = (c.messages || []).slice();
  renderChatLog();
  renderHistList();
  switchTab('chat');
}

function renderChatLog() {
  const log = $('#chat-log');
  log.innerHTML = '';
  history.forEach(m => {
    if (m.role === 'user') { addMsg('user', m.content); return; }
    const bubble = addMsg('assistant', '');
    bubble.innerHTML = '<div class="md">' + renderMd(m.content || '') + '</div>';
  });
}

/* ---------------- 对话 UI ---------------- */

let history = [];
let sending = false;

function addMsg(role, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
  const icon = role === 'user' ? '🙋' : '🎓';
  el.innerHTML = `<div class="who">${icon}</div><div class="bubble">${esc(text)}</div>`;
  $('#chat-log').appendChild(el);
  scrollChat();
  return el.querySelector('.bubble');
}

function scrollChat() { const log = $('#chat-log'); log.scrollTop = log.scrollHeight; }

async function sendChat() {
  const input = $('#chat-input');
  const text = input.value.trim();
  if (!text || sending) return;
  if (!Settings.ready()) { switchTab('settings'); flash('请先完成模型端点设置', true); return; }
  sending = true;
  $('#chat-send').disabled = true;
  input.value = '';
  addMsg('user', text);
  const bubble = addMsg('assistant', '');
  const stream = makeStreamer(bubble);
  try {
    const msgs = await buildMessages(history, text);
    await chatStream(msgs, d => stream.onDelta(d));
    stream.flush();
    history.push({ role: 'user', content: text }, { role: 'assistant', content: stream.raw });
    saveChat();
  } catch (e) {
    bubble.innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
  } finally {
    sending = false;
    $('#chat-send').disabled = false;
    input.focus();
  }
}

/* ---------------- 资料载入 ---------------- */

async function importLibrary(fileList) {
  const mdFiles = [...fileList].filter(f => /\.md$/i.test(f.name) && f.size < 400_000);
  progress(`方法库读取中… 0/${mdFiles.length}`);
  const items = [];
  for (let i = 0; i < mdFiles.length; i++) {
    items.push({ path: mdFiles[i].webkitRelativePath || mdFiles[i].name, text: await mdFiles[i].text() });
    if (i % 50 === 49) progress(`方法库读取中… ${i + 1}/${mdFiles.length}`);
  }
  await bulkPut('files', items, (x, y) => progress(`方法库写入中… ${x}/${y}`));
  progress('');
  refreshStatus();
  flash(`方法库已导入 ${items.length} 个 Markdown 文件（仅本浏览器）`);
}

async function importBank(file) {
  const text = await file.text();
  let items;
  if (/\.jsonl$/i.test(file.name) || text.trim().startsWith('{')) {
    items = parseBankJsonl(text);
  } else {
    // 总题库.md：按 "### " 题块粗切，qid 用内容散列
    items = [];
    for (const b of text.split(/\n(?=### )/)) {
      if (!(b.includes('答案') || b.includes('- '))) continue;
      items.push({ qid: 'MD-' + (await sha256Hex(b)).slice(0, 12), module: '', kp: '', year: '', paper: '', stem: b, options: [], answer: '', explanation: '' });
    }
  }
  await bulkPut('bank', items, (x, y) => progress(`题库写入中… ${x}/${y}`));
  progress('');
  refreshStatus();
  flash(`题库已导入 ${items.length} 题（仅本浏览器，不上传）`);
}

/* 本地运行器一键载入：/bank.jsonl 与 /methods.json 由 serve.py 只读挂载 */
async function loadLocal(url, label, store, map) {
  let res;
  try {
    res = await fetch(url);
  } catch (e) {
    flash(`${label}载入失败：${e.message}`, true);
    return;
  }
  if (res.status === 404) {
    flash(`${label}未挂载：请用「python3 webapp/serve.py」启动后重试，或改用手动文件导入`, true);
    return;
  }
  if (!res.ok) { flash(`${label}载入失败：HTTP ${res.status}`, true); return; }

  progress(`${label}下载解析中…（大文件约需十几秒）`);
  let items;
  if (store === 'bank') {
    items = parseBankJsonl(await res.text());
  } else {
    items = (await res.json()).map(map || (x => x));
  }
  await bulkPut(store, items, (x, y) => progress(`${label}写入中… ${x}/${y}`));
  progress('');
  refreshStatus();
  flash(`${label}已载入 ${items.length} 条`);
}

/* ---------------- 考我 ---------------- */

async function startQuiz() {
  const kp = $('#quiz-kp').value.trim();
  const n = Math.max(1, Math.min(20, parseInt($('#quiz-n').value, 10) || 5));
  const bank = await dbGetAll('bank');
  const pool = (kp ? bank.filter(q => (q.kp || '').includes(kp) || (q.module || '').includes(kp) || (q.stem || '').includes(kp)) : bank)
    .filter(q => !hasImg(q));
  if (!pool.length) { flash('题库里没有可文字作答的匹配题：换个考点关键词，或先载入题库', true); return; }
  const picked = pool.sort(() => Math.random() - 0.5).slice(0, n);
  renderQuiz(picked, pool);
}

function renderQuiz(questions, pool) {
  const area = $('#quiz-area');
  area.innerHTML = '';
  const used = new Set(questions.map(q => q.qid));
  questions.forEach((q, idx) => area.appendChild(buildQuizCard(q, idx, pool, used)));
}

function buildQuizCard(q, idx, pool, used) {
  const card = document.createElement('div');
  card.className = 'quiz-item';
  const meta = [q.year, q.paper, q.kp].filter(Boolean).join(' ｜ ');
  const opts = (q.options || []).map(o =>
    `<label data-label="${esc(o.label)}"><input type="radio" name="q${idx}-${Math.random().toString(36).slice(2,6)}" value="${esc(o.label)}"><b>${esc(o.label)}</b> ${esc(stripHtml(o.text))}</label>`
  ).join('');
  card.innerHTML = `
    <p class="meta">第 ${idx + 1} 题${meta ? ' ｜ ' + esc(meta) : ''}</p>
    <p class="stem">${esc(stripHtml(q.stem))}</p>
    <div class="opts">${opts || '<span class="hint">（无选项，主观作答后由模型判讲）</span>'}</div>
    <div class="row">
      <button class="grade">判分</button>
      <button class="explain" style="display:none">要讲解</button>
      <button class="save" style="display:none">存错题</button>
      <button class="swap">换一道</button>
    </div>
    <div class="verdict" style="display:none"></div>
    <div class="expl" style="display:none"></div>`;

  card.addEventListener('change', () => {
    card.querySelectorAll('.opts label').forEach(l =>
      l.classList.toggle('picked', l.querySelector('input').checked));
  });

  card.querySelector('.grade').addEventListener('click', () => gradeQuiz(card, q));
  card.querySelector('.explain').addEventListener('click', () => explainQuiz(card, q));
  card.querySelector('.save').addEventListener('click', () => saveWrong(card, q));
  card.querySelector('.swap').addEventListener('click', () => {
    const alt = (pool || []).find(x => !used.has(x.qid) && !hasImg(x));
    if (!alt) { card.querySelector('.swap').textContent = '没有更多了'; card.querySelector('.swap').disabled = true; return; }
    used.add(alt.qid);
    const fresh = buildQuizCard(alt, idx, pool, used);
    card.replaceWith(fresh);
  });
  return card;
}

function gradeQuiz(card, q) {
  const picked = card.querySelector('input[name^="q"]:checked');
  const verdict = card.querySelector('.verdict');
  const userAns = picked ? picked.value : '(未作答)';
  const official = q.answer || (q.options || []).find(o => o.is_correct)?.label || '';
  const right = official && userAns === official;
  verdict.style.display = 'block';
  verdict.className = 'verdict ' + (right ? 'right' : 'wrong');
  verdict.textContent = right
    ? `✔ 回答正确（你选 ${userAns}）`
    : `✘ 回答错误：你选 ${userAns}，官方答案 ${official || '库内缺失'}`;
  card.querySelector('.explain').style.display = '';
  if (!right && official) card.querySelector('.save').style.display = '';
  card.dataset.userAns = userAns;
  card.dataset.right = right ? '1' : '';
}

async function explainQuiz(card, q) {
  const expl = card.querySelector('.expl');
  expl.style.display = 'block';
  expl.classList.add('md');
  expl.textContent = '⏳ 生成讲解中…（自建服务器可能要一两分钟）';
  const userAns = card.dataset.userAns || '(未作答)';
  const official = q.answer || '';
  const opts = (q.options || []).map(o => `${o.label}. ${stripHtml(o.text)}`).join('\n');
  const bankExpl = q.explanation ? `\n库内官方解析：\n${q.explanation}` : '';
  const prompt = `请按行测讲题协议讲解这道题。
题面：${stripHtml(q.stem)}
选项：${opts || '（无）'}
我的答案：${userAns}
官方答案：${official || '未知'}${bankExpl}
要求：题型识别 → 答案结论 → 关键推理 → 我的错因（依据我的答案与官方答案差异）→ 易错点与复盘动作。`;
  try {
    const msgs = await buildMessages([], prompt);
    let out = '', think = 0;
    const kick = throttlePaint(() => { expl.innerHTML = renderMd(out); }, 200);
    await chatStream(msgs, d => {
      if (d.type === 'content') { out += d.text; kick.kick(); }
      else { think += d.text.length; if (!out) expl.textContent = `⏳ 模型思考中… 已思考 ${think} 字（正文随后到）`; }
    });
    expl.innerHTML = renderMd(out) || esc('（模型没有返回正文，可重试）');
  } catch (e) {
    expl.innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
  }
}

/* ---------------- 错题记录（event_id 幂等） ---------------- */

async function saveWrong(card, q) {
  const userAns = card.dataset.userAns || '';
  const date = new Date().toISOString().slice(0, 10);
  const stemNorm = stripHtml(q.stem).replace(/\s+/g, '').slice(0, 120);
  const event_id = (await sha256Hex(`${date}|${q.qid}|${stemNorm}|${userAns}|attempt-1`)).slice(0, 16);
  const existing = await tx('records', 'readonly', s => s.get(event_id));
  const rec = existing || {
    event_id, date,
    source_qid: q.qid, source: q.paper || 'webapp导入题库',
    question_type: q.kp || q.module || '未知',
    stem: stemNorm,
    user_answer: userAns, verified_answer: q.answer || '',
    explanation_completed: true,
    error_reason: '待确认（网页端未采集思路）',
    created_by: 'webapp',
  };
  await dbPut('records', rec);
  refreshStatus();
  card.querySelector('.save').textContent = existing ? '已存在(幂等)' : '已存 ✓';
  card.querySelector('.save').disabled = true;
}

async function renderRecords() {
  const list = $('#rec-list');
  const recs = (await dbGetAll('records')).sort((a, b) => (a.date < b.date ? 1 : -1));
  list.innerHTML = recs.length ? '' : '<div class="card"><p class="hint">暂无错题记录。</p></div>';
  for (const r of recs) {
    const el = document.createElement('div');
    el.className = 'rec-item';
    el.innerHTML = `
      <div class="head">${esc(r.date)} ｜ ${esc(r.question_type)} ｜ event_id ${esc(r.event_id)}</div>
      <p class="stem">${esc(r.stem)}…</p>
      <p>我的答案 <b>${esc(r.user_answer)}</b> ｜ 正确 <b>${esc(r.verified_answer)}</b>｜<span class="reason">${esc(r.error_reason)}</span></p>`;
    list.appendChild(el);
  }
}

function exportRecords() {
  dbGetAll('records').then(recs => {
    const blob = new Blob([JSON.stringify({ schema_version: 1, wrong_answers: recs }, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `webapp-records-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
}

async function importRecords(file) {
  const data = JSON.parse(await file.text());
  const recs = Array.isArray(data) ? data : (data.wrong_answers || []);
  let n = 0;
  for (const r of recs) if (r.event_id) { await dbPut('records', r); n++; }
  refreshStatus(); renderRecords();
  flash(`导入 ${n} 条错题记录（event_id 幂等去重）`);
}

/* ---------------- 状态与导航 ---------------- */

async function refreshStatus() {
  const [lib, bank, rec] = await Promise.all([dbCount('files'), dbCount('bank'), dbCount('records')]);
  $('#st-lib').innerHTML = lib ? `方法库：<span class="on">${lib} 文件</span>` : '方法库：未导入';
  $('#st-bank').innerHTML = bank ? `题库：<span class="on">${bank} 题</span>` : '题库：未导入';
  $('#st-rec').innerHTML = rec ? `错题：<span class="on">${rec} 条</span>` : '错题：0 条';
}

function switchTab(name) {
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + name));
  if (name === 'records') renderRecords();
}

/* ---------------- 绑定 ---------------- */

document.querySelectorAll('#tabs button').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));
$('#chat-send').addEventListener('click', sendChat);
$('#chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});
$('#set-save').addEventListener('click', () => Settings.save());
$('#set-test').addEventListener('click', async () => {
  Settings.save();
  try {
    const out = await chatStream([{ role: 'user', content: '回复"连通正常"四个字' }], () => {});
    flash('连通正常，模型回复：' + out.slice(0, 60));
  } catch (e) { flash(e.message, true); }
});
$('#imp-lib').addEventListener('change', e => e.target.files.length && importLibrary(e.target.files));
$('#imp-bank').addEventListener('change', e => e.target.files[0] && importBank(e.target.files[0]));
$('#load-bank-local').addEventListener('click', () => loadLocal('/bank.jsonl', '题库', 'bank'));
$('#load-methods-local').addEventListener('click', () => loadLocal('/methods.json', '方法库', 'files'));
$('#imp-lib-clear').addEventListener('click', async () => { await dbClear('files'); refreshStatus(); });
$('#imp-bank-clear').addEventListener('click', async () => { await dbClear('bank'); refreshStatus(); });
$('#quiz-start').addEventListener('click', startQuiz);
$('#rec-export').addEventListener('click', exportRecords);
$('#rec-import').addEventListener('change', e => e.target.files[0] && importRecords(e.target.files[0]));
$('#rec-clear').addEventListener('click', async () => {
  if (confirm('确定清空本浏览器的错题记录？')) { await dbClear('records'); refreshStatus(); renderRecords(); }
});
$('#chat-new').addEventListener('click', newChat);

Settings.load();
refreshStatus();
renderHistList();
// 启动时自动恢复最近一次对话，刷新不丢上下文
dbGetAll('chats').then(chats => {
  const latest = chats.sort((a, b) => b.updatedAt - a.updatedAt)[0];
  if (latest) openChat(latest.id);
});
