/* ═══════════════════════════════════════════════
   app.js — 단건 분석 + CSV 배치 처리 UI 로직
   ═══════════════════════════════════════════════ */

const API = '';  // 같은 오리진에서 서빙

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
function setProgress(label, pct, activeStep) {
  document.getElementById('progress-section').classList.remove('hidden');
  document.getElementById('progress-label').textContent = label;
  document.getElementById('progress-pct').textContent = `${Math.round(pct)}%`;
  document.getElementById('progress-bar').style.width = `${pct}%`;

  for (let i = 1; i <= 7; i++) {
    const dot = document.getElementById(`step-${i}`);
    dot.classList.remove('active', 'done');
    if (i < activeStep) dot.classList.add('done');
    else if (i === activeStep) dot.classList.add('active');
  }
}

function hideProgress() {
  document.getElementById('progress-section').classList.add('hidden');
}

/* ─── Score Gauge ─────────────────────────────── */
function drawGauge(score) {
  const svg = document.getElementById('score-gauge-svg');
  // SVG gradient 정의
  if (!svg.querySelector('defs')) {
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#6366f1"/>
        <stop offset="100%" stop-color="#22d3ee"/>
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
function drawRadar(breakdown) {
  const svg = document.getElementById('radar-chart');
  svg.innerHTML = '';
  const cx = 150, cy = 150, r = 100;
  const keys = Object.keys(breakdown);
  const n = keys.length;
  if (n < 3) return;

  const angle = (i) => ((2 * Math.PI * i) / n) - Math.PI / 2;
  const point = (i, val, scale) => {
    const a = angle(i);
    return [cx + Math.cos(a) * val * scale, cy + Math.sin(a) * val * scale];
  };

  // 배경 격자 (3 레이어)
  [0.33, 0.66, 1.0].forEach(t => {
    const pts = Array.from({ length: n }, (_, i) => point(i, r * t, 1)).map(p => p.join(',')).join(' ');
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', pts);
    poly.setAttribute('fill', 'none');
    poly.setAttribute('stroke', 'rgba(255,255,255,0.07)');
    poly.setAttribute('stroke-width', '1');
    svg.appendChild(poly);
  });

  // 축 선
  for (let i = 0; i < n; i++) {
    const [x, y] = point(i, r, 1);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', cx); line.setAttribute('y1', cy);
    line.setAttribute('x2', x);  line.setAttribute('y2', y);
    line.setAttribute('stroke', 'rgba(255,255,255,0.08)'); line.setAttribute('stroke-width', '1');
    svg.appendChild(line);
  }

  // 데이터 폴리곤
  const values = keys.map(k => (breakdown[k] || 0) / 10);
  const dataPts = values.map((v, i) => point(i, r * v, 1)).map(p => p.join(',')).join(' ');
  const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
  poly.setAttribute('points', dataPts);
  poly.setAttribute('fill', 'rgba(99,102,241,0.25)');
  poly.setAttribute('stroke', '#6366f1');
  poly.setAttribute('stroke-width', '2');
  svg.appendChild(poly);

  // 데이터 점 + 레이블
  keys.forEach((k, i) => {
    const [x, y] = point(i, r * values[i], 1);
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', x); circle.setAttribute('cy', y);
    circle.setAttribute('r', '4'); circle.setAttribute('fill', '#818cf8');
    svg.appendChild(circle);

    const [lx, ly] = point(i, r * 1.22, 1);
    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', lx); label.setAttribute('y', ly);
    label.setAttribute('text-anchor', 'middle');
    label.setAttribute('dominant-baseline', 'middle');
    label.setAttribute('fill', '#94a3b8');
    label.setAttribute('font-size', '9');
    label.setAttribute('font-family', 'Pretendard, Inter, sans-serif');
    label.textContent = k.replace(/_/g, ' ');
    svg.appendChild(label);
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

/* ─── Competitors Table ───────────────────────── */
function renderCompetitors(comps) {
  const tbody = document.getElementById('comp-tbody');
  tbody.innerHTML = '';
  document.getElementById('comp-count').textContent = `(${comps.length}개)`;
  document.getElementById('competitors-section').classList.remove('hidden');

  comps.forEach((c, idx) => {
    const rank = idx + 1;
    const sim = c.similarity ? (c.similarity * 100).toFixed(0) : '-';
    const score = c.score?.total_score?.toFixed(1) ?? '-';
    const status = c.verification || 'UNVERIFIED';
    const price = c.price ? `${c.price.toLocaleString()}원` : '-';

    tbody.innerHTML += `
      <tr>
        <td><span class="rank-badge rank-${rank}">${rank}</span></td>
        <td>${c.model_name}</td>
        <td>${c.brand || '-'}</td>
        <td>${price}</td>
        <td>${c.spec?.release_year || '-'}</td>
        <td class="score-val">${score}</td>
        <td>${(c.review_count || 0).toLocaleString()}</td>
        <td>
          <div class="sim-bar">
            <span class="sim-pct">${sim}%</span>
          </div>
        </td>
        <td>
          <span class="verify-dot ${status}"></span>
          ${status}
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

/* ─── 단건 분석 메인 ────────────────────────────── */
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

  try {
    // Step 1: 다나와 검색
    setProgress('Step 1/7: 다나와에서 모델 검색 중…', 5, 1);
    const searchRes = await fetch(`${API}/api/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_name: modelName }),
    }).then(r => r.ok ? r.json() : Promise.reject(await r.json()));

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
    }).then(r => r.ok ? r.json() : Promise.reject(await r.json()));

    const finalSpec = verifyRes.corrected_spec;
    const category = searchRes.category || 'tv';

    // Step 3: 채점
    setProgress('Step 3/7: 100점 채점 중…', 38, 3);
    const scoreRes = await fetch(`${API}/api/score`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category, spec: finalSpec }),
    }).then(r => r.ok ? r.json() : Promise.reject(await r.json()));

    // ─ 삼성 결과 카드 표시 ─
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
    // NOTE: category_url은 실제 카테고리 URL이 필요. 여기서는 skeleton 처리
    let competitorRes = { competitors: [] };
    try {
      competitorRes = await fetch(`${API}/api/competitors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category,
          samsung_spec: finalSpec,
          primary_spec_filter: {},
          category_url: `https://www.danawa.com/product/productListInit.php?cate_code=${getRulesCategoryId(category)}`,
        }),
      }).then(r => r.ok ? r.json() : Promise.reject(await r.json()));
    } catch { /* 경쟁사 탐색 실패 시 계속 */ }

    setProgress('Step 5/7: 유사도 필터 + 복합 랭킹 산출…', 70, 5);
    await sleep(300);

    // Step 6: 경쟁사 검증
    setProgress('Step 6/7: 경쟁사 공식몰 검증 중…', 82, 6);
    let verifiedComps = competitorRes.competitors || [];
    if (verifiedComps.length > 0) {
      try {
        const compVerifyRes = await fetch(`${API}/api/competitors/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ category, competitors: verifiedComps }),
        }).then(r => r.ok ? r.json() : Promise.reject(await r.json()));
        verifiedComps = compVerifyRes.competitors;
      } catch { /* 경쟁사 검증 실패 무시 */ }
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

// Enter 키 지원
document.getElementById('model-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') startAnalysis();
});

/* ─── 배치 업로드 ─────────────────────────────── */
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
  if (st.status === 'DONE') chip.style.cssText = 'background:rgba(16,185,129,.15);color:#10b981;padding:4px 10px;border-radius:20px;font-size:.75rem;font-weight:700';
  else if (st.status === 'RUNNING') chip.style.cssText = 'background:rgba(99,102,241,.15);color:#818cf8;padding:4px 10px;border-radius:20px;font-size:.75rem;font-weight:700';
  else chip.style.cssText = 'background:rgba(255,255,255,.07);color:#94a3b8;padding:4px 10px;border-radius:20px;font-size:.75rem;font-weight:700';

  document.getElementById('batch-progress-text').textContent = `${st.processed} / ${st.total}`;
  document.getElementById('batch-progress-bar').style.width = `${st.progress_pct}%`;

  if (st.status === 'DONE') document.getElementById('btn-download').disabled = false;
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

function getRulesCategoryId(category) {
  const map = {
    tv: '112', refrigerator: '107', washer: '108', dryer: '119',
    air_conditioner: '109', dishwasher: '254', air_purifier: '110',
    vacuum: '115', robot_vacuum: '572', microwave: '113', monitor: '102',
  };
  return map[category] || '112';
}
