/* 电真万确平台前端主程序：状态管理、接口调用、视图渲染。 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = 'poweredu_token';

  const state = {
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: null,
    cases: [],
    caseData: null,
    originalCase: null,
    powerflow: null,
    shortcircuit: null,
    stability: null,
    cct: null,
    diagnosis: null,
    tasks: [],
    submissions: [],
    courses: [],
    llm: false,
    dirty: false,
  };

  /* ---------------- 基础工具 ---------------- */

  async function api(path, payload, method) {
    const options = { method: method || (payload === undefined ? 'GET' : 'POST'), headers: {} };
    if (state.token) options.headers.Authorization = 'Bearer ' + state.token;
    if (payload !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    let body = {};
    try { body = await response.json(); } catch (err) { body = {}; }
    if (response.status === 401) {
      setUser(null);
      throw new Error(body.error || '请先登录');
    }
    if (!response.ok) throw new Error(body.error || ('请求失败：' + response.status));
    return body;
  }

  let toastTimer = null;
  function toast(text) {
    const box = $('toast');
    box.textContent = text;
    box.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { box.hidden = true; }, 2600);
  }

  function esc(text) {
    return String(text === undefined || text === null ? '' : text)
      .replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  }

  function num(value, digits) {
    return Number(value).toFixed(digits === undefined ? 3 : digits);
  }

  function view(name) {
    ['workbench', 'labs', 'console', 'about', 'login'].forEach((key) => {
      const section = $('view-' + key);
      if (section) section.hidden = key !== name;
    });
    document.querySelectorAll('#mainTabs .tab').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.view === name);
    });
  }

  /* ---------------- 登录 ---------------- */

  function setUser(user) {
    state.user = user;
    $('userName').textContent = user ? `${user.name}（${user.username}）` : '—';
    $('roleBadge').textContent = user ? ({ student: '学生', teacher: '教师', admin: '管理员' }[user.role] || user.role) : '未登录';
    $('logoutBtn').hidden = !user;
    if (!user) {
      state.token = '';
      localStorage.removeItem(TOKEN_KEY);
      view('login');
    }
  }

  async function login() {
    const username = $('loginUser').value.trim();
    const password = $('loginPass').value;
    $('loginError').textContent = '';
    try {
      const body = await api('/api/auth/login', { username, password });
      state.token = body.token;
      localStorage.setItem(TOKEN_KEY, body.token);
      setUser(body.user);
      toast('登录成功，欢迎 ' + body.user.name);
      await enterPlatform();
    } catch (err) {
      $('loginError').textContent = err.message;
    }
  }

  async function logout() {
    try { await api('/api/auth/logout', {}); } catch (err) { /* 忽略 */ }
    setUser(null);
    state.caseData = null;
    toast('已退出登录');
  }

  /* ---------------- 算例与工作台 ---------------- */

  async function loadCases() {
    const body = await api('/api/cases');
    state.cases = body.cases || [];
    renderCaseList();
    const select = $('taskCase');
    if (select) {
      select.innerHTML = state.cases.map((item) =>
        `<option value="${item.id}">${esc(item.name)}</option>`).join('');
    }
  }

  function renderCaseList() {
    const box = $('caseList');
    box.innerHTML = state.cases.map((item) => `
      <div class="case-card ${state.caseData && state.caseData.id === item.id ? 'active' : ''}" data-case="${item.id}">
        <strong>${esc(item.name)}</strong>
        <small>${item.bus_count} 节点 · ${item.branch_count} 支路 · ${item.gen_count} 机 · 负荷 ${item.load_p_mw} MW</small>
      </div>`).join('');
  }

  async function selectCase(caseId) {
    const body = await api('/api/cases/' + encodeURIComponent(caseId));
    state.caseData = body.case;
    state.originalCase = JSON.parse(JSON.stringify(body.case));
    state.powerflow = null;
    state.shortcircuit = null;
    state.stability = null;
    state.cct = null;
    state.diagnosis = null;
    state.dirty = false;
    $('caseTitle').textContent = body.case.name;
    $('caseMeta').textContent = `${body.case.buses.length} 节点 · 基准 ${body.case.base_mva} MVA`;
    $('runStatus').textContent = '待计算';
    $('runStatus').className = 'pill';
    $('faultBus').value = (body.case.buses.find((b) => b.type === 'PQ') || body.case.buses[0]).id;
    const branch = (body.case.branches || [])[0];
    $('tripBranch').value = branch ? `${branch.fbus}-${branch.tbus}` : '';
    renderCaseList();
    renderTables();
    renderDiagram();
    $('chartConvergence').innerHTML = '';
    $('chartLoading').innerHTML = '';
    $('busResultTable').innerHTML = '';
    $('branchResultTable').innerHTML = '';
    $('shortCircuitTable').innerHTML = '';
    $('chartShortCircuit').innerHTML = '';
    $('chartStability').innerHTML = '';
    $('chartOmega').innerHTML = '';
    $('stableVerdict').textContent = '';
    $('diagnosis').className = 'diagnosis';
    $('diagnosis').textContent = '选择算例后点击“潮流计算”，AI 助教会在这里给出结果诊断。';
  }

  function renderDiagram() {
    if (!state.caseData) return;
    NetDiagram.render($('diagram'), state.caseData, state.powerflow, {});
  }

  function renderTables() {
    if (!state.caseData) return;
    const typeOptions = ['SLACK', 'PV', 'PQ'];
    const busRows = state.caseData.buses.map((bus) => {
      const info = state.powerflow ? state.powerflow.buses.find((item) => item.id === bus.id) : null;
      const vmCell = info ? `<td>${num(info.vm, 4)}</td><td>${num(info.va, 3)}</td>` : '<td colspan="2" class="muted">未计算</td>';
      return `<tr>
        <td>${bus.id}</td>
        <td><input data-kind="bus" data-id="${bus.id}" data-field="name" value="${esc(bus.name)}"></td>
        <td><select data-kind="bus" data-id="${bus.id}" data-field="type">
          ${typeOptions.map((opt) => `<option value="${opt}"${bus.type === opt ? ' selected' : ''}>${opt}</option>`).join('')}
        </select></td>
        <td><input type="number" step="0.001" data-kind="bus" data-id="${bus.id}" data-field="vm" value="${bus.vm}"></td>
        <td><input type="number" step="1" data-kind="bus" data-id="${bus.id}" data-field="pd" value="${bus.pd}"></td>
        <td><input type="number" step="1" data-kind="bus" data-id="${bus.id}" data-field="qd" value="${bus.qd}"></td>
        <td><input type="number" step="0.01" data-kind="bus" data-id="${bus.id}" data-field="vmin" value="${bus.vmin}"></td>
        <td><input type="number" step="0.01" data-kind="bus" data-id="${bus.id}" data-field="vmax" value="${bus.vmax}"></td>
        ${vmCell}
      </tr>`;
    }).join('');
    $('busEditTable').innerHTML = `<thead><tr>
        <th>编号</th><th>名称</th><th>类型</th><th>电压设定(p.u.)</th><th>P负荷(MW)</th>
        <th>Q负荷(MVar)</th><th>下限</th><th>上限</th><th>电压(p.u.)</th><th>相角(°)</th>
      </tr></thead><tbody>${busRows}</tbody>`;

    const branchRows = state.caseData.branches.map((branch) => `
      <tr>
        <td>${branch.id}</td>
        <td>${branch.fbus}</td>
        <td>${branch.tbus}</td>
        <td><input type="number" step="0.0001" data-kind="branch" data-id="${branch.id}" data-field="r" value="${branch.r}"></td>
        <td><input type="number" step="0.0001" data-kind="branch" data-id="${branch.id}" data-field="x" value="${branch.x}"></td>
        <td><input type="number" step="0.0001" data-kind="branch" data-id="${branch.id}" data-field="b" value="${branch.b}"></td>
        <td><input type="number" step="0.001" data-kind="branch" data-id="${branch.id}" data-field="tap" value="${branch.tap}"></td>
        <td><input type="number" step="1" data-kind="branch" data-id="${branch.id}" data-field="rate" value="${branch.rate}"></td>
        <td><select data-kind="branch" data-id="${branch.id}" data-field="status">
          <option value="1"${branch.status ? ' selected' : ''}>投运</option>
          <option value="0"${branch.status ? '' : ' selected'}>停运</option>
        </select></td>
      </tr>`).join('');
    $('branchEditTable').innerHTML = `<thead><tr>
        <th>编号</th><th>首端</th><th>末端</th><th>R(p.u.)</th><th>X(p.u.)</th><th>B(p.u.)</th>
        <th>变比</th><th>额定(MVA)</th><th>状态</th>
      </tr></thead><tbody>${branchRows}</tbody>`;
  }

  function handleTableEdit(event) {
    const target = event.target;
    const kind = target.dataset.kind;
    if (!kind) return;
    const id = Number(target.dataset.id);
    const field = target.dataset.field;
    const collection = kind === 'bus' ? state.caseData.buses : state.caseData.branches;
    const item = collection.find((entry) => entry.id === id);
    if (!item) return;
    const numeric = target.type === 'number' || field === 'status';
    item[field] = numeric ? Number(target.value) : target.value;
    state.dirty = true;
    state.powerflow = null;
    state.shortcircuit = null;
    state.stability = null;
    state.diagnosis = null;
    $('runStatus').textContent = '参数已修改，待重新计算';
    $('runStatus').className = 'pill warn';
    renderDiagram();
  }

  /* ---------------- 仿真 ---------------- */

  function casePayload(extra) {
    if (!state.caseData) throw new Error('请先选择算例');
    const payload = Object.assign({ case: state.caseData, case_id: state.caseData.id }, extra || {});
    return payload;
  }

  async function withBusy(button, working, task) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = working;
    try { return await task(); } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  async function runPowerFlow() {
    if (!state.caseData) { toast('请先选择算例'); return; }
    await withBusy($('runPowerFlow'), '计算中…', async () => {
      try {
        const body = await api('/api/simulate/powerflow', casePayload());
        state.powerflow = body.result;
        state.diagnosis = body.diagnosis;
        state.dirty = false;
        const ok = body.result.converged;
        $('runStatus').textContent = ok
          ? `潮流收敛 · ${body.result.iterations} 次迭代 · 网损 ${num(body.result.summary.loss_p, 2)} MW`
          : '潮流不收敛';
        $('runStatus').className = 'pill ' + (ok ? 'ok' : 'risk');
        renderDiagram();
        renderTables();
        renderPowerFlowResult();
        renderDiagnosis();
        showPanel('panel-powerflow');
        toast(ok ? '潮流计算完成' : '潮流未收敛，请看 AI 诊断');
      } catch (err) { toast(err.message); }
    });
  }

  function renderPowerFlowResult() {
    const result = state.powerflow;
    if (!result || !result.buses) return;
    Charts.convergence($('chartConvergence'), result.history);
    const branches = result.branches || [];
    Charts.bar($('chartLoading'), branches.map((b) => `${b.from}-${b.to}`),
      branches.map((b) => b.loading), {
        colorFor: (value) => (value > 100 ? '#d64545' : value > 80 ? '#d9822b' : '#2f7fd1'),
        yMax: Math.max(100, ...branches.map((b) => b.loading)),
        showValue: false,
      });

    const busRows = result.buses.map((bus) => {
      const bad = bus.vm < (bus.vmin || 0.9) - 1e-9 ? 'num-bad'
        : bus.vm > (bus.vmax || 1.1) + 1e-9 ? 'num-warn' : '';
      return `<tr>
        <td>${bus.id}</td><td>${esc(bus.name)}</td><td>${bus.type}</td>
        <td class="${bad}">${num(bus.vm, 4)}</td><td>${num(bus.va, 3)}</td>
        <td>${num(bus.p, 2)}</td><td>${num(bus.q, 2)}</td>
        <td>${num(bus.pd, 1)}</td><td>${num(bus.qd, 1)}</td>
      </tr>`;
    }).join('');
    $('busResultTable').innerHTML = `<thead><tr><th>编号</th><th>名称</th><th>类型</th><th>电压(p.u.)</th>
      <th>相角(°)</th><th>注入P(MW)</th><th>注入Q(MVar)</th><th>负荷P</th><th>负荷Q</th></tr></thead>
      <tbody>${busRows}</tbody>`;

    const branchRows = branches.map((branch) => {
      const cls = branch.loading > 100 ? 'num-bad' : branch.loading > 80 ? 'num-warn' : '';
      return `<tr>
        <td>${branch.from}-${branch.to}</td>
        <td>${num(branch.p_from, 2)}</td><td>${num(branch.q_from, 2)}</td>
        <td>${num(branch.p_to, 2)}</td><td>${num(branch.q_to, 2)}</td>
        <td>${num(branch.loss_p, 3)}</td><td>${num(branch.loss_q, 3)}</td>
        <td class="${cls}">${num(branch.loading, 1)}</td>
      </tr>`;
    }).join('');
    $('branchResultTable').innerHTML = `<thead><tr><th>支路</th><th>首端P(MW)</th><th>首端Q(MVar)</th>
      <th>末端P(MW)</th><th>末端Q(MVar)</th><th>P损耗(MW)</th><th>Q损耗(MVar)</th><th>负载率(%)</th>
      </tr></thead><tbody>${branchRows}</tbody>`;
  }

  async function runShortCircuit() {
    if (!state.caseData) { toast('请先选择算例'); return; }
    await withBusy($('runShortCircuit'), '计算中…', async () => {
      try {
        const bus = Number($('faultBus').value) || state.caseData.buses[0].id;
        const body = await api('/api/simulate/shortcircuit', casePayload({ fault_bus: bus }));
        if (body.result.error) { toast(body.result.error); return; }
        state.shortcircuit = body.result;
        renderShortCircuitResult();
        showPanel('panel-shortcircuit');
        toast(`母线 ${bus} 短路电流 ${num(body.result.fault_current_ka, 3)} kA`);
      } catch (err) { toast(err.message); }
    });
  }

  function renderShortCircuitResult() {
    const result = state.shortcircuit;
    if (!result) return;
    const rows = result.per_bus || [];
    Charts.bar($('chartShortCircuit'), rows.map((item) => String(item.bus)),
      rows.map((item) => item.current_ka), {
        colorFor: (value, index) => (rows[index].bus === result.fault_bus ? '#d64545' : '#2f7fd1'),
        yLabel: 'kA', showValue: true,
      });
    const tableRows = rows.map((item) => `
      <tr><td>${item.bus}</td><td>${esc(item.name)}</td>
      <td>${num(item.vm_pre, 4)}</td><td>${num(item.zbus_mag, 4)}</td>
      <td>${num(item.current_pu, 3)}</td>
      <td class="${item.bus === result.fault_bus ? 'num-bad' : ''}">${num(item.current_ka, 3)}</td></tr>`).join('');
    $('shortCircuitTable').innerHTML = `<thead><tr><th>母线</th><th>名称</th><th>故障前电压(p.u.)</th>
      <th>自阻抗(p.u.)</th><th>短路电流(p.u.)</th><th>短路电流(kA)</th></tr></thead><tbody>${tableRows}</tbody>`;
  }

  function parseTrip() {
    const raw = $('tripBranch').value.trim();
    if (!raw) return null;
    const match = raw.match(/(\d+)\s*[-—~到至]\s*(\d+)/);
    if (match) return [Number(match[1]), Number(match[2])];
    return Number(raw);
  }

  async function runStability() {
    if (!state.caseData) { toast('请先选择算例'); return; }
    await withBusy($('runStability'), '仿真中…', async () => {
      try {
        const payload = casePayload({
          fault_bus: Number($('faultBus').value) || state.caseData.buses[0].id,
          trip_branch: parseTrip(),
          clearing_time: Number($('clearingTime').value) || 0.15,
        });
        const body = await api('/api/simulate/stability', payload);
        if (body.result.error) { toast(body.result.error); return; }
        state.stability = body.result;
        renderStabilityResult();
        showPanel('panel-stability');
        toast(body.result.stable ? '系统保持暂态稳定' : '系统失去暂态稳定');
      } catch (err) { toast(err.message); }
    });
  }

  async function runCCT() {
    if (!state.caseData) { toast('请先选择算例'); return; }
    await withBusy($('runCCT'), '搜索中…', async () => {
      try {
        const payload = casePayload({
          fault_bus: Number($('faultBus').value) || state.caseData.buses[0].id,
          trip_branch: parseTrip(),
        });
        const body = await api('/api/simulate/cct', payload);
        state.cct = body.result;
        $('stableVerdict').textContent = body.result.message || `极限切除时间 ${num(body.result.cct, 3)} s`;
        showPanel('panel-stability');
        toast('极限切除时间 ≈ ' + num(body.result.cct, 3) + ' s');
      } catch (err) { toast(err.message); }
    });
  }

  function renderStabilityResult() {
    const result = state.stability;
    if (!result || !result.curves) return;
    const times = result.curves.t;
    const deltaSeries = result.curves.machines.map((machine, index) => ({
      name: `${machine.name}(母线${machine.bus})`,
      points: times.map((t, i) => [t, machine.delta_deg[i]]),
      color: Charts.PALETTE[index % Charts.PALETTE.length],
    }));
    Charts.line($('chartStability'), deltaSeries, { xLabel: '时间 (s)', yLabel: '功角 (°)' });
    const omegaSeries = result.curves.machines.map((machine, index) => ({
      name: machine.name,
      points: times.map((t, i) => [t, machine.omega_pu[i]]),
      color: Charts.PALETTE[index % Charts.PALETTE.length],
    }));
    Charts.line($('chartOmega'), omegaSeries, { xLabel: '时间 (s)', yLabel: '转速 (p.u.)', yMin: 0.95, yMax: 1.05 });
    $('stableVerdict').textContent = (result.stable ? '✔ 结论：系统保持暂态稳定' : '✘ 结论：系统失去暂态稳定')
      + `（切除时间 ${num(result.clearing_time, 3)} s，最大相对功角差 ${num(result.max_angle_diff_deg, 2)}°）`;
  }

  function showPanel(panelId) {
    document.querySelectorAll('#resultTabs .subtab').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.panel === panelId);
    });
    document.querySelectorAll('.sub-panel').forEach((panel) => {
      panel.classList.toggle('active', panel.id === panelId);
    });
  }

  /* ---------------- AI 助教 ---------------- */

  function appendMessage(role, text, level) {
    const box = $('chatLog');
    const div = document.createElement('div');
    div.className = 'msg ' + role + (level ? ' ' + level : '');
    div.textContent = text;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function renderDiagnosis() {
    const box = $('diagnosis');
    if (!state.diagnosis) {
      box.className = 'diagnosis';
      box.textContent = '暂无诊断结果。';
      return;
    }
    box.className = 'diagnosis ' + (state.diagnosis.level || '');
    box.textContent = state.diagnosis.text;
  }

  async function sendChat(text) {
    if (!text) return;
    appendMessage('user', text);
    $('chatInput').value = '';
    try {
      const body = await api('/api/ai/chat', {
        message: text,
        case: state.caseData,
        case_id: state.caseData ? state.caseData.id : null,
        result: state.powerflow,
      });
      appendMessage('ai', body.reply, body.level);
      if (body.case && body.ops && body.ops.length) {
        state.caseData = body.case;
        state.dirty = true;
        state.powerflow = null;
        renderTables();
        renderDiagram();
        $('runStatus').textContent = `AI 已修改算例（${body.ops.length} 项），待重新计算`;
        $('runStatus').className = 'pill warn';
        toast('AI 已更新算例参数，正在重新计算潮流');
        await runPowerFlow();
      }
    } catch (err) {
      appendMessage('ai', '出错了：' + err.message, 'risk');
    }
  }

  /* ---------------- 实验报告 ---------------- */

  async function generateReport() {
    if (!state.caseData) { toast('请先选择算例'); return; }
    try {
      if (!state.powerflow) await runPowerFlow();
      const body = await api('/api/ai/report', casePayload({
        power_flow: state.powerflow,
        short_circuit: state.shortcircuit,
        stability: state.stability,
        meta: { title: `${state.caseData.name} 仿真实验报告` },
      }));
      showReport(body.report);
      toast('报告草稿已生成');
    } catch (err) { toast(err.message); }
  }

  function markdownToHtml(markdown) {
    const lines = String(markdown).split(/\r?\n/);
    let html = '';
    let inTable = false;
    lines.forEach((line) => {
      const row = line.trim();
      if (/^\|/.test(row)) {
        const cells = row.replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
        if (cells.every((cell) => /^-{2,}$/.test(cell))) return;
        if (!inTable) { html += '<table>'; inTable = true; }
        const tag = html.endsWith('<table>') ? 'th' : 'td';
        html += '<tr>' + cells.map((cell) => `<${tag}>${esc(cell)}</${tag}>`).join('') + '</tr>';
        return;
      }
      if (inTable) { html += '</table>'; inTable = false; }
      if (/^###\s/.test(row)) html += `<h4>${esc(row.slice(4))}</h4>`;
      else if (/^##\s/.test(row)) html += `<h3>${esc(row.slice(3))}</h3>`;
      else if (/^#\s/.test(row)) html += `<h2>${esc(row.slice(2))}</h2>`;
      else if (/^[-*]\s/.test(row)) html += `<p class="bullet">• ${esc(row.slice(2))}</p>`;
      else if (/^\d+\.\s/.test(row)) html += `<p class="bullet">${esc(row)}</p>`;
      else if (row === '') html += '<div class="gap"></div>';
      else html += `<p>${esc(row)}</p>`;
    });
    if (inTable) html += '</table>';
    return html;
  }

  function showReport(markdown) {
    const overlay = document.createElement('div');
    overlay.className = 'report-overlay';
    overlay.innerHTML = `<div class="report-window">
      <div class="report-head"><strong>实验报告草稿</strong>
        <span><button id="downloadReport">下载 .md</button><button id="closeReport">关闭</button></span></div>
      <div class="report-body">${markdownToHtml(markdown)}</div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#closeReport').onclick = () => overlay.remove();
    overlay.querySelector('#downloadReport').onclick = () => {
      const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = (state.caseData ? state.caseData.name : '实验') + '报告.md';
      link.click();
      URL.revokeObjectURL(link.href);
    };
  }

  /* ---------------- 我的实验 ---------------- */

  async function loadLabs() {
    const body = await api('/api/tasks');
    state.tasks = body.tasks || [];
    state.submissions = body.submissions || [];
    renderTasks();
    renderMySubmissions();
    $('labMeta').textContent = `${state.tasks.length} 个实验任务 · 已提交 ${state.submissions.length} 次`;
  }

  function renderTasks() {
    const submitted = {};
    state.submissions.forEach((item) => { submitted[item.task_id] = item; });
    $('taskGrid').innerHTML = state.tasks.map((task) => {
      const done = submitted[task.id];
      return `<div class="task-card">
        <h3>${esc(task.title)}</h3>
        <p class="muted">${esc(task.course_name || '')} · 算例 ${esc(task.case_id)} · 截止 ${esc(task.deadline || '未设置')}</p>
        <p>${esc(task.requirements || '')}</p>
        <p class="muted">评分标准：最低电压 ${task.standard && task.standard.min_vm !== undefined ? task.standard.min_vm : '—'} p.u.
          · 最大负载率 ${task.standard && task.standard.max_loading !== undefined ? task.standard.max_loading : '—'} %</p>
        ${done ? `<p class="num-ok">已提交，得分 ${done.score === null ? '待批阅' : done.score} 分 · ${esc(done.comment || '')}</p>` : ''}
        <div class="actions">
          <button data-load="${task.case_id}">载入算例</button>
          <button class="primary" data-submit="${task.id}">提交结果</button>
        </div>
      </div>`;
    }).join('') || '<p class="muted">暂无实验任务。</p>';
  }

  function renderMySubmissions() {
    if (!state.submissions.length) {
      $('mySubmissions').innerHTML = '<tbody><tr><td class="muted">暂无提交记录</td></tr></tbody>';
      return;
    }
    const rows = state.submissions.map((item) => `<tr>
      <td>${item.id}</td><td>${esc(item.task_title || '')}</td><td>${esc(item.case_id)}</td>
      <td>${item.score === null ? '待批阅' : item.score}</td>
      <td>${esc(item.comment || '')}</td>
      <td>${(item.created_at || '').replace('T', ' ').slice(0, 19)}</td></tr>`).join('');
    $('mySubmissions').innerHTML = `<thead><tr><th>编号</th><th>任务</th><th>算例</th><th>得分</th>
      <th>批语</th><th>提交时间</th></tr></thead><tbody>${rows}</tbody>`;
  }

  async function submitTask(taskId) {
    if (!state.caseData) { toast('请先载入该任务对应的算例'); return; }
    try {
      const body = await api(`/api/tasks/${taskId}/submit`, { case: state.caseData, case_id: state.caseData.id });
      toast(`提交成功，得分 ${body.score} 分`);
      await loadLabs();
    } catch (err) { toast(err.message); }
  }

  /* ---------------- 教学控制台 ---------------- */

  async function loadConsole() {
    const stats = await api('/api/stats');
    state.courses = (await api('/api/courses')).courses || [];
    const submissions = (await api('/api/submissions')).submissions || [];
    state.allSubmissions = submissions;
    const tiles = [
      ['平台用户', stats.stats.users], ['学生', stats.stats.students], ['教师', stats.stats.teachers],
      ['课程', stats.stats.courses], ['实验任务', stats.stats.tasks],
      ['提交次数', stats.stats.submissions], ['平均分', stats.stats.avg_score],
      ['内置算例', (stats.cases || []).length],
    ];
    $('statGrid').innerHTML = tiles.map(([label, value]) =>
      `<div class="stat"><b>${value}</b><span>${label}</span></div>`).join('');
    $('courseSelect').innerHTML = state.courses.map((course) =>
      `<option value="${course.id}">${esc(course.name)}（${esc(course.code)}）</option>`).join('');
    const rows = submissions.map((item) => `<tr>
      <td>${item.id}</td><td>${esc(item.student_name)}</td><td>${esc(item.task_title)}</td>
      <td>${esc(item.case_id)}</td><td class="${item.score >= 80 ? 'num-ok' : item.score >= 60 ? 'num-warn' : 'num-bad'}">${item.score}</td>
      <td>${esc(item.comment || '')}</td>
      <td>${(item.created_at || '').replace('T', ' ').slice(0, 19)}</td></tr>`).join('');
    $('allSubmissions').innerHTML = `<thead><tr><th>编号</th><th>学生</th><th>任务</th><th>算例</th>
      <th>得分</th><th>批语</th><th>时间</th></tr></thead><tbody>${rows || '<tr><td colspan="7" class="muted">暂无提交</td></tr>'}</tbody>`;
  }

  async function createTask() {
    try {
      const courseId = Number($('courseSelect').value);
      if (!courseId) { toast('请先创建课程'); return; }
      const body = await api('/api/tasks', {
        course_id: courseId,
        title: $('taskTitle').value || '未命名实验',
        case_id: $('taskCase').value,
        requirements: $('taskReq').value,
        deadline: $('taskDeadline').value,
        standard: {
          min_vm: Number($('taskMinVm').value),
          max_vm: Number($('taskMaxVm').value),
          max_loading: Number($('taskMaxLoad').value),
        },
      });
      $('consoleMsg').textContent = '任务已发布，编号 ' + body.task_id;
      toast('任务发布成功');
      await loadConsole();
    } catch (err) {
      $('consoleMsg').textContent = err.message;
    }
  }

  function exportCsv() {
    const rows = [['提交编号', '学生', '任务', '算例', '得分', '批语', '时间']];
    (state.allSubmissions || []).forEach((item) => {
      rows.push([item.id, item.student_name, item.task_title, item.case_id, item.score, item.comment, item.created_at]);
    });
    const csv = '\ufeff' + rows.map((row) => row.map((cell) => `"${String(cell === null ? '' : cell).replace(/"/g, '""')}"`).join(',')).join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = '成绩导出.csv';
    link.click();
    URL.revokeObjectURL(link.href);
  }

  /* ---------------- 事件绑定与初始化 ---------------- */

  function bind() {
    $('loginBtn').onclick = login;
    $('loginPass').onkeydown = (event) => { if (event.key === 'Enter') login(); };
    $('logoutBtn').onclick = logout;
    $('runPowerFlow').onclick = runPowerFlow;
    $('runShortCircuit').onclick = runShortCircuit;
    $('runStability').onclick = runStability;
    $('runCCT').onclick = runCCT;
    $('chatSend').onclick = () => sendChat($('chatInput').value.trim());
    $('chatInput').onkeydown = (event) => { if (event.key === 'Enter') sendChat($('chatInput').value.trim()); };
    $('exportReport').onclick = generateReport;
    $('createTaskBtn').onclick = createTask;
    $('exportCsv').onclick = exportCsv;
    $('resetCase').onclick = () => {
      if (!state.originalCase) return;
      state.caseData = JSON.parse(JSON.stringify(state.originalCase));
      state.powerflow = null;
      renderTables();
      renderDiagram();
      toast('已恢复算例原始参数');
    };
    $('saveCase').onclick = () => {
      if (!state.caseData) return;
      state.caseData.id = 'custom';
      state.caseData.name = (state.caseData.name || '自定义') + '（自定义）';
      $('caseTitle').textContent = state.caseData.name;
      toast('已切换为自定义算例，可直接仿真或提交');
    };
    $('mainTabs').addEventListener('click', async (event) => {
      const target = event.target.closest('.tab');
      if (!target) return;
      const name = target.dataset.view;
      view(name);
      try {
        if (name === 'labs') { await loadLabs(); view('labs'); }
        else if (name === 'console') { await loadConsole(); view('console'); }
      } catch (err) { toast(err.message); }
    });
    $('resultTabs').addEventListener('click', (event) => {
      const target = event.target.closest('.subtab');
      if (target) showPanel(target.dataset.panel);
    });
    $('caseList').addEventListener('click', (event) => {
      const card = event.target.closest('.case-card');
      if (!card) return;
      selectCase(card.dataset.case).catch((err) => toast(err.message));
    });
    document.querySelectorAll('.quick-actions button').forEach((button) => {
      button.onclick = () => sendChat(button.dataset.text);
    });
    ['busEditTable', 'branchEditTable'].forEach((id) => {
      $(id).addEventListener('change', handleTableEdit);
    });
    $('taskGrid').addEventListener('click', (event) => {
      const load = event.target.dataset.load;
      const submit = event.target.dataset.submit;
      if (load) { selectCase(load).then(() => { view('workbench'); toast('已载入算例：' + load); }).catch((err) => toast(err.message)); }
      else if (submit) submitTask(Number(submit));
    });
  }

  async function enterPlatform() {
    await loadCases();
    if (!state.caseData && state.cases.length) {
      const first = state.cases.find((item) => item.id === 'wscc9') || state.cases[0];
      await selectCase(first.id);
    }
    view('workbench');
    appendMessage('ai', '你好！我是电力系统教学助教。可以先点“潮流计算”，也可以直接对我说“把5号母线负荷增加到120兆瓦”。');
  }

  async function init() {
    bind();
    if (!state.token) { view('login'); return; }
    try {
      const body = await api('/api/auth/me');
      setUser(body.user);
      state.llm = body.llm;
      $('llmBadge').textContent = body.llm ? '大模型已接入' : '本地规则引擎';
      await enterPlatform();
    } catch (err) {
      setUser(null);
    }
  }

  document.addEventListener('DOMContentLoaded', init);
  window.PowerEdu = { state, api };
})();
