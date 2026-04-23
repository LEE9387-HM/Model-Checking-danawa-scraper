/* ═══════════════════════════════════════════════
   app.js — SpecRank UI 로직
   DB 즉시 분석 모드 + 실시간 크롤링 모드 + CSV 배치
   ═══════════════════════════════════════════════ */

const API = '';  // 같은 오리진에서 서빙
const API_BASE = location.hostname === 'localhost' ? '' : 'https://danawa-api.fortume9388.workers.dev';

/* ─── 모드 상태 ──────────────────────────────────── */
let _currentMode = 'db';  // 'db' | 'live'

function switchMode(mode) {
  _currentMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`mode-${mode}`).classList.add('active');

  const dbArea  = document.getElementById('db-input-area');
  const liveArea = document.getElementById('live-input-area');

  if (mode === 'db') {
    dbArea.classList.remove('hidden');
    liveArea.classList.add('hidden');
  } else {
    dbArea.classList.add('hidden');
    liveArea.classList.remove('hidden');
  }

  // 결과 섹션 초기화
  document.getElementById('verdict-section').classList.add('hidden');
  document.getElementById('result-card').classList.add('hidden');
  document.getElementById('competitors-section').classList.add('hidden');
  document.getElementById('logic-accordion').classList.add('hidden');
  document.getElementById('spec-banner').classList.add('hidden');
}

/* ─── 탭 전환 ─────────────────────────────────── */
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
  document.getElementById(`tab-${name}`).classList.add('active');
  document.getElementById(`panel-${name}`).classList.remove('hidden');
}

/* ─── Toast ───────────────────────────────────── */
function showToast(msg, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast${isError ? ' error' : ''}`;
  setTimeout(() => el.classList.add('hidden'), 4000);
}

/* ─── Progress ────────────────────────────────── */
const STEP_LABELS = ['다나와 검색', '공식몰 검증', '100점 채점', '경쟁사 탐색', '유사도 필터', '경쟁사 검증', '완료'];

function setProgress(label, pct, activeStep) {
  document.getElementById('progress-section').classList.remove('hidden');
  document.getElementById('progress-label').textContent = label;
  document.getElementById('progress-pct').textContent = `${Math.round(pct)}%`;
  const bar = document.getElementById('progress-bar');
  bar.style.width = `${pct}%`;
  bar.style.background = pct === 100
    ? 'linear-gradient(90deg,#059669,#10b981)'
    : 'linear-gradient(90deg,#1B4FD8,#0891B2)';

  const indicators = document.getElementById('step-indicators');
  for (let i = 1; i <= 7; i++) {
    const dot = document.getElementById(`step-${i}`);
    dot.classList.remove('active', 'done');
    if (i < activeStep) {
      dot.classList.add('done');
      dot.textContent = '✓';
    } else {
      dot.textContent = i;
      if (i === activeStep) dot.classList.add('active');
    }
  }
  indicators.querySelectorAll('.step-connector').forEach((conn, idx) => {
    conn.classList.toggle('done', idx + 1 < activeStep - 1);
  });
}

function hideProgress() {
  document.getElementById('progress-section').classList.add('hidden');
}

/* ─── Score Gauge ─────────────────────────────── */
function drawGauge(score) {
  const svg = document.getElementById('score-gauge-svg');
  if (!svg.querySelector('defs')) {
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#1B4FD8"/>
        <stop offset="100%" stop-color="#0891B2"/>
      </linearGradient>`;
    svg.prepend(defs);
  }
  const fill = document.getElementById('gauge-fill');
  const circumference = 2 * Math.PI * 50;
  const offset = circumference * (1 - score / 100);
  fill.style.strokeDashoffset = offset;
  document.getElementById('gauge-score-text').textContent = score.toFixed(1);
}

/* ─── Radar Chart ─────────────────────────────── */
function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function drawRadar(breakdown) {
  const svg = document.getElementById('radar-chart');
  svg.innerHTML = '';
  const cx = 155, cy = 155, r = 100;
  const keys = Object.keys(breakdown);
  const n = keys.length;
  if (n < 3) return;

  const angle = i => (2 * Math.PI * i / n) - Math.PI / 2;
  const pt    = (i, radius) => [
    cx + Math.cos(angle(i)) * radius,
    cy + Math.sin(angle(i)) * radius,
  ];

  [0.33, 0.66, 1.0].forEach((t, li) => {
    const pts = Array.from({ length: n }, (_, i) => pt(i, r * t).join(',')).join(' ');
    svg.appendChild(svgEl('polygon', {
      points: pts, fill: 'none',
      stroke: 'rgba(0,0,0,0.07)', 'stroke-width': '1',
    }));
    const [lx, ly] = pt(0, r * t);
    const levelLabel = svgEl('text', {
      x: lx + 4, y: ly - 3,
      fill: 'rgba(0,0,0,0.2)', 'font-size': '7',
      'font-family': 'Pretendard,Inter,sans-serif',
    });
    levelLabel.textContent = [3, 6, 10][li];
    svg.appendChild(levelLabel);
  });

  for (let i = 0; i < n; i++) {
    const [x, y] = pt(i, r);
    svg.appendChild(svgEl('line', {
      x1: cx, y1: cy, x2: x, y2: y,
      stroke: 'rgba(0,0,0,0.08)', 'stroke-width': '1',
    }));
  }

  const values = keys.map(k => Math.min((breakdown[k] || 0) / 10, 1));
  const dataPts = values.map((v, i) => pt(i, r * v).join(',')).join(' ');
  const poly = svgEl('polygon', {
    points: dataPts,
    fill: 'rgba(27,79,216,0.12)',
    stroke: '#1B4FD8', 'stroke-width': '2',
    class: 'radar-poly',
  });
  svg.appendChild(poly);

  keys.forEach((k, i) => {
    const v = values[i];
    const [x, y] = pt(i, r * v);
    const group = svgEl('g', { class: 'radar-point-group', style: 'cursor:default' });
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = `${k.replace(/_/g, ' ')}: ${(breakdown[k] || 0).toFixed(1)} / 10`;
    group.appendChild(title);
    group.appendChild(svgEl('circle', {
      cx: x, cy: y, r: '5',
      fill: '#3B6FE8', stroke: '#1B4FD8', 'stroke-width': '1.5',
    }));
    const scoreLabel = svgEl('text', {
      x: x + (x > cx ? 7 : -7),
      y: y + (y > cy ? 5 : -3),
      fill: '#1B4FD8', 'font-size': '8',
      'font-family': 'Pretendard,Inter,sans-serif',
      'text-anchor': x > cx ? 'start' : 'end',
    });
    scoreLabel.textContent = (breakdown[k] || 0).toFixed(1);
    group.appendChild(scoreLabel);
    svg.appendChild(group);

    const [lx, ly] = pt(i, r * 1.27);
    const lbl = svgEl('text', {
      x: lx, y: ly,
      'text-anchor': 'middle', 'dominant-baseline': 'middle',
      fill: '#4A5568', 'font-size': '9.5',
      'font-family': 'Pretendard,Inter,sans-serif',
    });
    lbl.textContent = k.replace(/_/g, ' ');
    svg.appendChild(lbl);
  });
}

/* ─── Score Breakdown ─────────────────────────── */
function renderBreakdown(breakdown) {
  const container = document.getElementById('score-breakdown');
  container.innerHTML = '';
  Object.entries(breakdown).forEach(([key, val]) => {
    const pct = Math.round((val / 10) * 100);
    container.innerHTML += `
      <div class="breakdown-item">
        <div class="breakdown-name">${key.replace(/_/g, ' ')}</div>
        <div class="breakdown-bar-wrap">
          <div class="breakdown-bar" style="width:${pct}%"></div>
        </div>
        <div class="breakdown-score">${val.toFixed(1)} / 10</div>
      </div>`;
  });
}

/* ─── Verdict Card (DB 모드 전용) ────────────────── */
const VERDICT_META = {
  OVERPRICED:   { label: '⚠ OVERPRICED',   cls: 'verdict-overpriced',  desc: '동급 경쟁사 대비 가격이 높습니다' },
  SLIGHT_HIGH:  { label: '↑ SLIGHT HIGH',  cls: 'verdict-slight-high', desc: '소폭 고가 구간입니다' },
  FAIR:         { label: '✓ FAIR',          cls: 'verdict-fair',        desc: '가격 경쟁력이 적정합니다' },
  GOOD_VALUE:   { label: '★ GOOD VALUE',   cls: 'verdict-good-value',  desc: '가성비가 우수합니다' },
  COMPETITIVE:  { label: '⚡ COMPETITIVE', cls: 'verdict-competitive',  desc: '뛰어난 가격 경쟁력을 보입니다' },
  NO_MATCH:     { label: '— NO MATCH',     cls: 'verdict-no-match',    desc: 'DB 내 비교 가능한 경쟁사가 없습니다' },
};

function renderVerdictCard(result) {
  const agg = result.aggregate || {};
  const samsung = result.samsung || {};
  const verdict = agg.overall_verdict || 'NO_MATCH';
  const meta = VERDICT_META[verdict] || VERDICT_META.NO_MATCH;
  const cpi = agg.weighted_cpi || 0;

  const section = document.getElementById('verdict-section');
  const card = document.getElementById('verdict-card');

  card.className = `verdict-card ${meta.cls}`;
  section.classList.remove('hidden');

  document.getElementById('verdict-badge').textContent = meta.label;
  document.getElementById('verdict-summary').textContent = meta.desc;
  document.getElementById('verdict-cpi-value').textContent = cpi > 0 ? cpi.toFixed(1) : '—';

  const barEl = document.getElementById('verdict-cpi-bar');
  const clampedPct = Math.min(Math.max((cpi / 150) * 100, 0), 100);
  barEl.style.width = `${clampedPct}%`;

  document.getElementById('verdict-model-name').textContent = samsung.model_name || '';
  const specs = samsung.specs || {};
  const size = specs.screen_size_inch ? `${specs.screen_size_inch}"` : (samsung.size ? `${samsung.size}"` : '');
  const res  = specs.resolution || samsung.resolution || '';
  const year = samsung.year ? ` · ${samsung.year}년형` : '';
  document.getElementById('verdict-year-size').textContent = `${size}${res ? ' ' + res : ''}${year}`;
  document.getElementById('verdict-price').textContent =
    samsung.price ? `${samsung.price.toLocaleString()}원` : '';

  // 판정 기준 아코디언 표시
  document.getElementById('logic-accordion').classList.remove('hidden');

  requestAnimationFrame(() => { card.classList.add('verdict-animate'); });
}

/* ─── 스펙 기준 배너 렌더링 ─────────────────────────── */
function renderSpecBanner(samsungSpecs) {
  const banner = document.getElementById('spec-banner');
  if (!samsungSpecs) { banner.classList.add('hidden'); return; }

  const chips = [];
  if (samsungSpecs.screen_size_inch) chips.push(`📐 ${samsungSpecs.screen_size_inch}"`);
  if (samsungSpecs.panel_type)       chips.push(`🖥 ${samsungSpecs.panel_type}`);
  if (samsungSpecs.resolution)       chips.push(`🔲 ${samsungSpecs.resolution}`);
  if (samsungSpecs.refresh_rate_hz)  chips.push(`⚡ ${samsungSpecs.refresh_rate_hz}Hz`);
  if (samsungSpecs.hdr)              chips.push(`🌟 ${samsungSpecs.hdr}`);

  banner.innerHTML = `
    <span class="spec-banner-label">삼성 기준 스펙</span>
    ${chips.map(c => `<span class="spec-chip">${c}</span>`).join('')}
  `;
  banner.classList.remove('hidden');
}

/* ─── DB 모드 경쟁사 테이블 ──────────────────────── */
function cpiClass(cpi) {
  if (cpi > 115) return 'cpi-over';
  if (cpi > 105) return 'cpi-high';
  if (cpi > 95)  return 'cpi-fair';
  return 'cpi-good';
}

function verdictShortLabel(v) {
  const short = { OVERPRICED: 'OVER', SLIGHT_HIGH: 'HIGH', FAIR: 'FAIR', GOOD_VALUE: 'GV', COMPETITIVE: 'COMP' };
  return short[v] || v;
}

/* 삼성 기준 스펙 저장 (renderDbCompetitors에서 참조) */
let _samsungSpecs = null;

function renderDbCompetitors(matches, samsungSpecs) {
  _samsungSpecs = samsungSpecs || null;
  const tbody = document.getElementById('comp-tbody-db');
  tbody.innerHTML = '';

  document.getElementById('comp-count').textContent = `(${matches.length}개)`;
  document.getElementById('competitors-section').classList.remove('hidden');
  document.getElementById('sort-hint').textContent = '복합 매칭순 · 스펙유사도 40% + 연형근접 35% + 크기근접 15% + 패널 10%';

  document.getElementById('comp-table-db').classList.remove('hidden');
  document.getElementById('comp-table-live').classList.add('hidden');

  // 스펙 기준 배너
  renderSpecBanner(samsungSpecs);

  matches.forEach((m) => {
    const matchPct = m.match_score != null ? (m.match_score * 100).toFixed(0) : '-';
    const adjPrice = m.adjusted_price ? `${Math.round(m.adjusted_price).toLocaleString()}원` : '-';
    const realPrice = m.price ? `${m.price.toLocaleString()}원` : '-';
    const scoreFmt = m.score != null ? m.score.toFixed(1) : '-';
    const adjCpi = m.adjusted_cpi != null ? m.adjusted_cpi.toFixed(1) : '-';
    const adjCpiCls = m.adjusted_cpi != null ? cpiClass(m.adjusted_cpi) : '';
    const verdictLbl = verdictShortLabel(m.verdict || '');

    // 스펙 매칭 칩 (삼성 기준 대비)
    const specs = m.specs || {};
    const specChips = buildSpecMatchChips(samsungSpecs, specs);

    // 매칭 기여도 바
    const contribBar = buildContribBar(m);

    tbody.innerHTML += `
      <tr class="db-row rank-${m.rank}">
        <td><span class="rank-badge rank-${Math.min(m.rank, 10)}">${m.rank}</span></td>
        <td class="model-cell" title="${m.model_name}">
          ${m.model_name}
          ${specChips ? `<div class="spec-match-chips">${specChips}</div>` : ''}
        </td>
        <td>${m.brand || '-'}</td>
        <td class="price-real">${realPrice}</td>
        <td class="price-adj" title="감가상각 조정 후 환산가">${adjPrice}</td>
        <td>${m.year || '-'}</td>
        <td><span class="score-chip ${m.score >= 70 ? 'score-high' : m.score >= 50 ? 'score-mid' : 'score-low'}">${scoreFmt}</span></td>
        <td>
          <div class="sim-bar-wrap">
            <div class="sim-bar-fill" style="width:${matchPct}%"></div>
            <span class="sim-pct">${matchPct}%</span>
          </div>
          ${contribBar}
        </td>
        <td><span class="cpi-chip ${adjCpiCls}">${adjCpi}</span></td>
        <td><span class="verdict-mini verdict-mini-${(m.verdict||'').toLowerCase()}">${verdictLbl}</span></td>
      </tr>`;
  });
}

function buildSpecMatchChips(samsungSpecs, compSpecs) {
  if (!samsungSpecs) return '';
  const chips = [];

  // 패널 비교
  const sPanel = (samsungSpecs.panel_type || '').toLowerCase().trim();
  const cPanel = (compSpecs.panel_type || '').toLowerCase().trim();
  if (sPanel && cPanel) {
    chips.push(sPanel === cPanel
      ? `<span class="spec-match-chip spec-match-ok">✅ ${compSpecs.panel_type}</span>`
      : `<span class="spec-match-chip spec-match-diff">❌ ${compSpecs.panel_type || '패널미상'}</span>`);
  }

  // 인치 비교
  const sSize = samsungSpecs.screen_size_inch;
  const cSize = compSpecs.screen_size_inch;
  if (sSize != null && cSize != null) {
    const diff = Math.abs(cSize - sSize);
    const cls = diff === 0 ? 'spec-match-ok' : diff <= 2 ? 'spec-match-near' : 'spec-match-diff';
    const icon = diff === 0 ? '✅' : diff <= 2 ? '⚠️' : '❌';
    chips.push(`<span class="spec-match-chip ${cls}">${icon} ${cSize}"</span>`);
  }

  // Hz 비교
  const sHz = samsungSpecs.refresh_rate_hz;
  const cHz = compSpecs.refresh_rate_hz;
  if (sHz != null && cHz != null) {
    const cls = cHz >= sHz ? 'spec-match-ok' : cHz >= sHz * 0.8 ? 'spec-match-near' : 'spec-match-diff';
    const icon = cHz >= sHz ? '✅' : cHz >= sHz * 0.8 ? '⚠️' : '❌';
    chips.push(`<span class="spec-match-chip ${cls}">${icon} ${cHz}Hz</span>`);
  }

  return chips.join('');
}

function buildContribBar(m) {
  const spec  = Math.round((m.spec_cosine_similarity  || 0) * 40);
  const year  = Math.round((m.year_proximity          || 0) * 35);
  const size  = Math.round((m.size_closeness          || 0) * 15);
  const panel = Math.round((m.panel_type_bonus        || 0) * 10);
  return `
    <div class="match-contrib-bar" title="스펙${spec}% + 연형${year}% + 크기${size}% + 패널${panel}%">
      <div class="contrib-seg contrib-spec"  style="flex:${spec}"></div>
      <div class="contrib-seg contrib-year"  style="flex:${year}"></div>
      <div class="contrib-seg contrib-size"  style="flex:${size}"></div>
      <div class="contrib-seg contrib-panel" style="flex:${panel}"></div>
    </div>`;
}

/* ─── 실시간 모드 경쟁사 테이블 ─────────────────── */
function scoreClass(score) {
  if (score >= 80) return 'score-high';
  if (score >= 60) return 'score-mid';
  return 'score-low';
}

function renderCompetitors(comps) {
  const tbody = document.getElementById('comp-tbody');
  tbody.innerHTML = '';
  document.getElementById('comp-count').textContent = `(${comps.length}개)`;
  document.getElementById('competitors-section').classList.remove('hidden');
  document.getElementById('sort-hint').textContent = '복합 랭킹순 · 인기 50% + 리뷰 30% + 유사도 20%';

  document.getElementById('comp-table-live').classList.remove('hidden');
  document.getElementById('comp-table-db').classList.add('hidden');

  comps.forEach((c, idx) => {
    const rank = c.rank ?? idx + 1;
    const simVal = c.similarity ? c.similarity * 100 : 0;
    const simPct = simVal ? simVal.toFixed(0) : '-';
    const scoreVal = c.score?.total_score ?? null;
    const scoreDisp = scoreVal !== null ? scoreVal.toFixed(1) : '-';
    const scoreCls = scoreVal !== null ? scoreClass(scoreVal) : '';
    const status = c.verification || 'UNVERIFIED';
    const price = c.price ? `${c.price.toLocaleString()}원` : '-';
    const year = c.release_year || c.spec?.release_year || '-';

    tbody.innerHTML += `
      <tr class="row-${status}">
        <td><span class="rank-badge rank-${Math.min(rank, 10)}">${rank}</span></td>
        <td class="model-cell" title="${c.model_name}">${c.model_name}</td>
        <td>${c.brand || '-'}</td>
        <td>${price}</td>
        <td>${year}</td>
        <td><span class="score-chip ${scoreCls}">${scoreDisp}</span></td>
        <td>${(c.review_count || 0).toLocaleString()}</td>
        <td>
          <div class="sim-bar-wrap">
            <div class="sim-bar-fill" style="width:${simVal.toFixed(0)}%"></div>
            <span class="sim-pct">${simPct}%</span>
          </div>
        </td>
        <td>
          <span class="verify-dot ${status}"></span>
          <span class="verify-text">${status}</span>
        </td>
      </tr>`;
  });
}

/* ─── Verify Diffs ────────────────────────────── */
function renderDiffs(diffs) {
  const container = document.getElementById('verify-diffs');
  const entries = Object.entries(diffs);
  if (entries.length === 0) {
    container.classList.add('hidden');
    container.innerHTML = '';
    return;
  }
  container.classList.remove('hidden');
  container.innerHTML = `
    <div class="diffs-title">⚠️ 공식몰 기준으로 보정된 항목 (${entries.length}개)</div>
    <div class="diffs-list">
      ${entries.map(([key, diff]) => `
        <div class="diff-item">
          <span class="diff-key">${key.replace(/_/g, ' ')}</span>
          <span class="diff-from">${diff.danawa || '(없음)'}</span>
          <span class="diff-arrow">→</span>
          <span class="diff-to">${diff.official}</span>
          <span class="diff-label">(${diff.official_label || ''})</span>
        </div>`).join('')}
    </div>`;
}

/* ══════════════════════════════════════════════════
   DB 즉시 분석 모드
   ══════════════════════════════════════════════════ */

let _dbFilters = { sizes: [], resolutions: [], years: [] };

async function loadDbFilters() {
  try {
    const data = await fetch(API_BASE + '/api/tv/models').then(r => r.json());
    _dbFilters = data.filters || { sizes: [], resolutions: [], years: [] };

    const sizeEl = document.getElementById('filter-size');
    const resEl  = document.getElementById('filter-resolution');
    const yearEl = document.getElementById('filter-year');

    _dbFilters.sizes.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = `${s}"`;
      sizeEl.appendChild(opt);
    });
    _dbFilters.resolutions.forEach(r => {
      const opt = document.createElement('option');
      opt.value = r;
      opt.textContent = r;
      resEl.appendChild(opt);
    });
    _dbFilters.years.forEach(y => {
      const opt = document.createElement('option');
      opt.value = y;
      opt.textContent = `${y}년형`;
      yearEl.appendChild(opt);
    });

    await refreshModelList(data.models || []);
  } catch (e) {
    console.warn('[DB 필터 로드 실패]', e);
    document.getElementById('db-model-count').textContent = 'DB 연결 실패 — 실시간 모드를 이용해주세요';
  }
}

async function onFilterChange() {
  const size       = document.getElementById('filter-size').value;
  const resolution = document.getElementById('filter-resolution').value;
  const year       = document.getElementById('filter-year').value;

  const params = new URLSearchParams();
  if (size)       params.append('size', size);
  if (resolution) params.append('resolution', resolution);
  if (year)       params.append('year', year);

  try {
    const data = await fetch(API_BASE + '/api/tv/models?' + params).then(r => r.json());
    await refreshModelList(data.models || []);
  } catch (e) {
    console.warn('[필터 적용 실패]', e);
  }
}

async function refreshModelList(models) {
  const sel = document.getElementById('model-select');
  sel.innerHTML = '<option value="">— 삼성 TV 모델 선택 —</option>';
  models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.model_name;
    const sizeStr  = m.size ? `${m.size}"` : '';
    const yearStr  = m.year ? ` ${m.year}년` : '';
    const priceStr = m.price ? ` · ${m.price.toLocaleString()}원` : '';
    opt.textContent = `${m.model_name}  ${sizeStr}${yearStr}${priceStr}`;
    sel.appendChild(opt);
  });

  const countEl = document.getElementById('db-model-count');
  countEl.textContent = models.length > 0
    ? `${models.length}개 모델`
    : '선택한 조건에 맞는 모델이 없습니다';
}

let _dbAnalyzing = false;

async function startDbAnalysis() {
  if (_dbAnalyzing) return;

  const sel = document.getElementById('model-select');
  const modelName = sel.value;
  if (!modelName) { showToast('모델을 선택해주세요', true); return; }

  _dbAnalyzing = true;
  document.getElementById('btn-db-analyze').disabled = true;
  document.getElementById('verdict-section').classList.add('hidden');
  document.getElementById('result-card').classList.add('hidden');
  document.getElementById('competitors-section').classList.add('hidden');

  // 로딩 표시
  document.getElementById('btn-db-analyze').querySelector('.btn-text').textContent = '분석 중…';

  try {
    const result = await fetch(API_BASE + '/api/tv/match', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_name: modelName }),
    }).then(async r => {
      if (r.ok) return r.json();
      const text = await r.text();
      let errBody;
      try { errBody = JSON.parse(text); } catch { errBody = { detail: text }; }
      // 404 = DB에 없음 → Fallback
      if (r.status === 404) {
        errBody._fallback = true;
      }
      return Promise.reject(errBody);
    });

    renderVerdictCard(result);

    if (result.matches && result.matches.length > 0) {
      renderDbCompetitors(result.matches, result.samsung?.specs || null);
    } else {
      document.getElementById('competitors-section').classList.add('hidden');
      document.getElementById('spec-banner').classList.add('hidden');
    }

  } catch (err) {
    if (err._fallback) {
      // DB에 없음 → 실시간 모드로 자동 전환
      showToast('DB에 해당 모델이 없어 실시간 분석으로 전환합니다…');
      switchMode('live');
      document.getElementById('model-input').value = modelName;
      setTimeout(() => startAnalysis(), 800);
    } else {
      showToast(`오류: ${err.detail || err.message || '알 수 없는 오류'}`, true);
      console.error(err);
    }
  } finally {
    _dbAnalyzing = false;
    document.getElementById('btn-db-analyze').disabled = false;
    document.getElementById('btn-db-analyze').querySelector('.btn-text').textContent = '즉시 분석';
  }
}

/* ══════════════════════════════════════════════════
   실시간 크롤링 모드 (기존 7단계)
   ══════════════════════════════════════════════════ */
let _analyzing = false;

async function startAnalysis() {
  if (_analyzing) return;
  const modelInput = document.getElementById('model-input');
  const modelName = modelInput.value.trim();
  if (!modelName) { showToast('모델명을 입력해주세요', true); return; }

  _analyzing = true;
  document.getElementById('btn-analyze').disabled = true;
  document.getElementById('result-card').classList.add('hidden');
  document.getElementById('competitors-section').classList.add('hidden');
  document.getElementById('verdict-section').classList.add('hidden');

  try {
    // Step 1: 다나와 검색
    setProgress('Step 1/7: 다나와에서 모델 검색 중…', 5, 1);
    const searchRes = await fetch(`${API}/api/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_name: modelName }),
    }).then(async r => {
      if (r.ok) return r.json();
      const text = await r.text();
      let errBody;
      try { errBody = JSON.parse(text); } catch { errBody = { detail: text }; }
      return Promise.reject(errBody);
    });

    // Step 2: 공식몰 검증
    setProgress('Step 2/7: 삼성 공식몰 교차검증 중…', 22, 2);
    const verifyRes = await fetch(`${API}/api/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_name: modelName,
        category: searchRes.category || 'tv',
        raw_spec: searchRes.raw_spec,
      }),
    }).then(async r => {
      if (r.ok) return r.json();
      const text = await r.text();
      let errBody;
      try { errBody = JSON.parse(text); } catch { errBody = { detail: text }; }
      return Promise.reject(errBody);
    });

    const finalSpec = verifyRes.corrected_spec;
    const category = searchRes.category || 'tv';

    // Step 3: 채점
    setProgress('Step 3/7: 100점 채점 중…', 38, 3);
    const scoreRes = await fetch(`${API}/api/score`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category, spec: finalSpec }),
    }).then(async r => {
      if (r.ok) return r.json();
      const text = await r.text();
      let errBody;
      try { errBody = JSON.parse(text); } catch { errBody = { detail: text }; }
      return Promise.reject(errBody);
    });

    // 삼성 결과 카드 표시
    document.getElementById('result-card').classList.remove('hidden');
    document.getElementById('result-category-badge').textContent = category.toUpperCase();
    document.getElementById('result-model-name').textContent = modelName;
    document.getElementById('result-brand').textContent = `제조사: ${searchRes.brand || '-'}`;
    document.getElementById('result-year').textContent = `출시: ${finalSpec.release_year || '-'}`;
    document.getElementById('result-price').textContent = `최저가: ${(searchRes.price || 0).toLocaleString()}원`;

    drawGauge(scoreRes.total_score);
    drawRadar(scoreRes.breakdown);
    renderBreakdown(scoreRes.breakdown);

    const verifyRow = document.getElementById('verify-status-row');
    verifyRow.classList.remove('hidden');
    const badge = document.getElementById('verify-badge');
    badge.textContent = verifyRes.status;
    badge.className = `verify-badge ${verifyRes.status}`;
    document.getElementById('verify-desc').textContent = {
      VERIFIED: '다나와 스펙과 삼성 공식몰 스펙 일치',
      CORRECTED: '공식몰 기준으로 스펙 보정됨',
      UNVERIFIED: '공식몰에서 모델 확인 불가',
    }[verifyRes.status] || '';
    renderDiffs(verifyRes.diffs || {});

    // Step 4~5: 경쟁사 탐색
    setProgress('Step 4/7: 다나와에서 경쟁사 탐색 중…', 55, 4);
    let competitorRes = { competitors: [] };
    try {
      const releaseYear = finalSpec.release_year
        || parseInt(searchRes.raw_spec?.__release_year__ || '0') || null;

      competitorRes = await fetch(`${API}/api/competitors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category,
          samsung_spec: finalSpec,
          primary_spec_filter: {},
          category_url: '',
          release_year: releaseYear,
        }),
      }).then(async r => {
        if (r.ok) return r.json();
        const text = await r.text();
        let errBody;
        try { errBody = JSON.parse(text); } catch { errBody = { detail: text }; }
        return Promise.reject(errBody);
      });
    } catch (e) {
      console.warn('[경쟁사 탐색 실패, 계속 진행]', e);
    }

    setProgress('Step 5/7: 유사도 필터 + 복합 랭킹 산출…', 70, 5);
    await sleep(300);

    // Step 6: 경쟁사 공식몰 검증 + 재채점/재랭킹
    setProgress('Step 6/7: 경쟁사 공식몰 검증 중…', 82, 6);
    let verifiedComps = competitorRes.competitors || [];
    if (verifiedComps.length > 0) {
      try {
        const compVerifyRes = await fetch(`${API}/api/competitors/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            category,
            competitors: verifiedComps,
            samsung_spec: finalSpec,
          }),
        }).then(async r => {
          if (r.ok) return r.json();
          const text = await r.text();
          let errBody;
          try { errBody = JSON.parse(text); } catch { errBody = { detail: text }; }
          return Promise.reject(errBody);
        });
        verifiedComps = compVerifyRes.competitors;
        if (compVerifyRes.rescored) {
          showToast('공식몰 스펙 보정 후 재채점/재랭킹이 적용되었습니다.');
        }
      } catch (e) {
        console.warn('[경쟁사 검증 실패, 기존 결과 유지]', e);
      }
    }

    // Step 7: 결과 출력
    setProgress('Step 7/7: 완료!', 100, 7);
    await sleep(500);
    hideProgress();

    if (verifiedComps.length > 0) renderCompetitors(verifiedComps);

  } catch (err) {
    hideProgress();
    showToast(`오류: ${err.detail || err.message || '알 수 없는 오류'}`, true);
    console.error(err);
  } finally {
    _analyzing = false;
    document.getElementById('btn-analyze').disabled = false;
  }
}

document.getElementById('model-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') startAnalysis();
});

/* ══════════════════════════════════════════════════
   CSV 배치 처리
   ══════════════════════════════════════════════════ */
let _selectedFile = null;
let _currentJobId = null;
let _pollTimer = null;

function handleDrop(e) {
  e.preventDefault();
  document.getElementById('dropzone').classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) setSelectedFile(file);
}

function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) setSelectedFile(file);
}

function setSelectedFile(file) {
  _selectedFile = file;
  document.getElementById('selected-filename').textContent = `선택됨: ${file.name}`;
  document.getElementById('btn-batch-upload').disabled = false;
}

async function uploadBatch() {
  if (!_selectedFile) return;
  const formData = new FormData();
  formData.append('file', _selectedFile);
  try {
    document.getElementById('btn-batch-upload').disabled = true;
    const res = await fetch(`${API}/api/batch/upload`, { method: 'POST', body: formData }).then(r => r.json());
    _currentJobId = res.job_id;
    document.getElementById('batch-status-section').classList.remove('hidden');
    document.getElementById('batch-job-id-display').textContent = `Job ID: ${_currentJobId}`;
    startPolling();
  } catch (err) {
    showToast('업로드 실패: ' + (err.detail || err.message), true);
    document.getElementById('btn-batch-upload').disabled = false;
  }
}

function startPolling() {
  clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    if (!_currentJobId) return;
    try {
      const st = await fetch(`${API}/api/batch/${_currentJobId}/status`).then(r => r.json());
      updateBatchUI(st);
      if (['DONE', 'FAILED', 'CANCELLED'].includes(st.status)) clearInterval(_pollTimer);
    } catch { clearInterval(_pollTimer); }
  }, 3000);
}

function updateBatchUI(st) {
  const chip = document.getElementById('batch-status-label');
  chip.textContent = st.status;
  chip.className = 'batch-status-chip';
  const chipStyles = {
    DONE:      'background:rgba(16,185,129,.15);color:#10b981',
    RUNNING:   'background:rgba(99,102,241,.15);color:#818cf8',
    FAILED:    'background:rgba(239,68,68,.15);color:#f87171',
    CANCELLED: 'background:rgba(148,163,184,.12);color:#94a3b8',
    PAUSED:    'background:rgba(245,158,11,.12);color:#fbbf24',
    QUEUED:    'background:rgba(255,255,255,.07);color:#94a3b8',
  };
  chip.style.cssText = (chipStyles[st.status] || chipStyles.QUEUED)
    + ';padding:4px 10px;border-radius:20px;font-size:.75rem;font-weight:700';

  document.getElementById('batch-progress-text').textContent = `${st.processed} / ${st.total}`;
  document.getElementById('batch-progress-bar').style.width = `${st.progress_pct}%`;

  const errCount = document.getElementById('batch-error-count');
  if (st.error_count > 0) {
    errCount.classList.remove('hidden');
    errCount.textContent = `오류 ${st.error_count}건`;
    document.getElementById('batch-error-section').classList.remove('hidden');
    renderErrorList(st.errors || []);
  }

  const etaEl = document.getElementById('batch-eta');
  const etaSep = document.getElementById('eta-sep');
  if (st.eta_seconds != null && st.status === 'RUNNING') {
    etaEl.classList.remove('hidden');
    etaSep.classList.remove('hidden');
    etaEl.textContent = `남은 시간 약 ${formatEta(st.eta_seconds)}`;
  } else {
    etaEl.classList.add('hidden');
    etaSep.classList.add('hidden');
  }

  const curModel = document.getElementById('batch-current-model');
  if (st.current_model && st.status === 'RUNNING') {
    curModel.classList.remove('hidden');
    curModel.textContent = `⚙ 처리 중: ${st.current_model}`;
  } else {
    curModel.classList.add('hidden');
  }

  if (st.status === 'DONE') {
    document.getElementById('btn-download').disabled = false;
    curModel.classList.add('hidden');
  }
}

function formatEta(seconds) {
  if (seconds < 60) return `${seconds}초`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}분 ${s}초` : `${m}분`;
}

function renderErrorList(errors) {
  const list = document.getElementById('batch-error-list');
  if (!errors.length) return;
  list.innerHTML = errors.map(e => `
    <div class="batch-error-item">
      <span class="batch-error-model">${e.model_name}</span>
      <span class="batch-error-msg">${e.error}</span>
    </div>`).join('');
}

function toggleErrorList() {
  const list = document.getElementById('batch-error-list');
  const btn  = document.querySelector('.batch-error-toggle');
  const hidden = list.classList.toggle('hidden');
  btn.textContent = hidden ? '▶ 오류 목록 보기' : '▼ 오류 목록 닫기';
}

async function downloadBatchResult() {
  if (!_currentJobId) return;
  window.open(`${API}/api/batch/${_currentJobId}/result`, '_blank');
}

async function cancelBatch() {
  if (!_currentJobId) return;
  await fetch(`${API}/api/batch/${_currentJobId}`, { method: 'DELETE' });
  clearInterval(_pollTimer);
  showToast('취소 요청 완료');
}

/* ─── 유틸 ────────────────────────────────────── */
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

/* ─── 초기화 ──────────────────────────────────── */
loadDbFilters();
