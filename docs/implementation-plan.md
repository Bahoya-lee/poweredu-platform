# 电真万确 · AI 赋能电力教学仿真平台 实施计划

> **给执行者：** 按 Task 1 → Task 12 顺序执行，每个任务结束都有可独立验证的产物。
> 步骤用复选框（`- [ ]`）跟踪。全部代码仅用 Python 标准库，禁止引入 pip 依赖。

**Goal:** 交付面向全校师生的浏览器端电力教学仿真平台，含国产自主仿真内核（潮流/短路/暂态稳定）、AI 助教与教学管理，替代需安装授权的国外商业软件。

**Architecture:** 单进程 Python 标准库 HTTP 服务同时承载静态单页应用与 REST API；计算内核与 Web 层解耦，可被脚本与测试单独调用；教学数据（账号、课程、任务、提交、日志）落在 SQLite；前端无构建、无 CDN，向量图与曲线用 SVG 自绘。

**Tech Stack:** Python 3.11+（本机实测 3.14）、`http.server` / `sqlite3` / `json` / 内置复数运算、原生 JS + SVG、`unittest`。

**Spec:** 《电真万确-AI赋能电力教学仿真软件平台》榜题（AI+科研赛道，电气与自动化学院，交付「工作台、其他」）。需求原文整理见 `docs/方案说明书.md` 第 1 章。

## Global Constraints

- 运行时依赖：仅 Python 标准库；缺 numpy 也必须能跑。
- 前端不得引用外部 CDN；离线单机与校园内网均可完整使用。
- 界面文案为简体中文，术语与《电力系统分析》教材一致（母线/节点、标幺值、PV/PQ/平衡节点）。
- 数值口径：功率基准 `baseMVA = 100`，角度单位为度，电压为标幺值。
- 口令存储用 `hashlib.pbkdf2_hmac('sha256', pwd, salt, 120000)`，禁止明文落库。
- 每个任务完成后必须跑通对应测试命令，再进入下一任务。

## 需求 → 任务映射

| 赛题要求 | 覆盖任务 |
| --- | --- |
| 基于 AI 开发国内首款全自主电力仿真软件 | Task 1–6（自主内核） |
| 教学软件大量盗版、安装复杂且不合规 | Task 7–9、Task 12（免安装、浏览器即用、一键部署） |
| AI 开发全新的国产化自主仿真软件 | Task 8、Task 11（AI 助教：自然语言建模、诊断、报告） |
| 省去国外软件授权费，直接经济效益百万/年 | Task 12（合规与效益测算） |
| 交付「工作台、其他」 | Task 10（仿真工作台）+ Task 11（教学管理台）+ Task 12（文档） |
| 服务全校师生 | Task 7、Task 11（多角色账号、课程、任务、自动评分） |

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `server/engine/linalg.py` | 稠密线性代数：选主元 LU 求解、Gauss-Jordan 求逆 |
| `server/engine/models.py` | Bus / Gen / Branch / Case 数据模型、校验、JSON 序列化 |
| `server/engine/powerflow.py` | Ybus 组网、牛顿-拉夫逊潮流、PV→PQ 无功限值处理 |
| `server/engine/shortcircuit.py` | 节点阻抗矩阵法三相短路计算 |
| `server/engine/stability.py` | 经典模型摇摆方程、RK4 时域仿真、极限切除时间二分搜索 |
| `server/engine/cases.py` | 内置算例库（三机九节点、IEEE 14、双机教学、辐射状配电） |
| `server/store.py` | SQLite 建表、种子数据、用户/课程/任务/提交/日志 CRUD |
| `server/auth.py` | 口令散列、会话令牌、角色鉴权 |
| `server/ai_assistant.py` | 意图解析、结果诊断、报告生成、可选大模型接入 |
| `server/app.py` | HTTP 路由、静态资源、REST API、统一错误处理 |
| `server/static/*` | 单页应用：工作台、单线图、曲线、AI 对话、教学管理 |
| `tests/test_*.py` | 内核数值校验、AI 解析、端到端接口测试 |
| `start.bat` / `start.sh` | 一键启动（端口探测、打印地址、可选自动开浏览器） |

---

### Task 1: 线性代数底座

**Files:** Create `server/engine/linalg.py`；Test `tests/test_linalg.py`

**Interfaces:**
- Produces: `solve(matrix, rhs) -> list[complex]`、`invert(matrix) -> list[list[complex]]`、`matmul(a, b)`、`matvec(a, x)`

- [ ] **Step 1: 写失败测试**

```python
def test_solve_matches_hand_calculation(self):
    self.assertAlmostEqual(solve([[2, 1], [1, 3]], [5, 10])[1], 3.0)

def test_invert_complex_matrix_gives_identity(self):
    a = [[1 + 1j, 2 - 1j], [0.5j, 3 + 0j]]
    product = matmul(invert(a), a)
    self.assertAlmostEqual(product[0][0].real, 1.0, places=9)
```

- [ ] **Step 2: 运行失败** — `python -m unittest discover -s tests -p "test_linalg.py" -v`
- [ ] **Step 3: 实现** — 选主元 LU 前代/回代 + Gauss-Jordan 求逆，用 `abs()` 选主元以兼容复数；奇异矩阵抛 `ValueError`
- [ ] **Step 4: 通过** — 重跑 Step 2 命令，预期 OK
- [ ] **Step 5: 提交** — `git add server/engine/linalg.py tests/test_linalg.py` 并 `git commit -m "feat: add complex linear algebra core"`

### Task 2: 元件与算例数据模型

**Files:** Create `server/engine/models.py`；Test `tests/test_models.py`

**Interfaces:**
- Produces: `Bus`、`Gen`、`Branch`、`Case`（含 `to_dict()` / `from_dict()`）、`Case.validate() -> list[str]`、`Case.index_of(bus_id) -> int`、`Case.bus_ids() -> list[int]`

- [ ] **Step 1: 写失败测试**

```python
def test_roundtrip_keeps_bus_order(self):
    case = Case.from_dict(SAMPLE_CASE)
    self.assertEqual(case.to_dict()["buses"][0]["id"], 1)
    self.assertEqual(case.validate(), [])

def test_validate_reports_dangling_branch(self):
    case = Case.from_dict(SAMPLE_CASE)
    case.branches[0].tbus = 99
    self.assertTrue(any("99" in m for m in case.validate()))
```

- [ ] **Step 2: 运行失败** — `python -m unittest discover -s tests -p "test_models.py" -v`
- [ ] **Step 3: 实现** — `@dataclass` 定义元件字段；`from_dict` 做类型规范化（母线类型转大写、数值转 float）；`validate` 检查支路端点存在、母线编号唯一、平衡节点唯一、非零阻抗
- [ ] **Step 4: 通过** — 重跑 Step 2 命令
- [ ] **Step 5: 提交** — `git commit -m "feat: add power system element models"`

### Task 3: Ybus 组网与牛顿-拉夫逊潮流

**Files:** Create `server/engine/powerflow.py`；Test `tests/test_powerflow.py`

**Interfaces:**
- Produces: `build_ybus(case) -> list[list[complex]]`、`solve_power_flow(case, tol=1e-8, max_iter=30) -> dict`
- 返回：`{"converged": bool, "iterations": int, "history": [{"iter": i, "mismatch": m}], "buses": [...], "branches": [...], "generators": [...], "summary": {...}}`；母线字段 `{"id","name","vm","va","p","q","type"}`，支路字段 `{"from","to","p_from","q_from","p_to","q_to","loss_p","loss_q","loading"}`（p/q 单位 MW/MVar，va 单位度）

- [ ] **Step 1: 写失败测试（对标准解回归）**

```python
def test_wscc9_matches_reference_voltage_profile(self):
    res = solve_power_flow(get_case("wscc9"))
    self.assertTrue(res["converged"])
    expected = [1.04, 1.025, 1.025, 1.02579, 0.99563, 1.01265, 1.02577, 1.01588, 1.03235]
    for bus, want in zip(res["buses"], expected):
        self.assertLess(abs(bus["vm"] - want), 1e-4)

def test_ieee14_matches_reference_voltage_profile(self):
    res = solve_power_flow(get_case("ieee14"))
    self.assertTrue(res["converged"])
    self.assertLess(abs(res["buses"][13]["vm"] - 1.036), 5e-3)
```

- [ ] **Step 2: 运行失败** — `python -m unittest discover -s tests -p "test_powerflow.py" -v`（先跑，预期因算例库/求解器缺失而报错）
- [ ] **Step 3: 实现** — 变压器非标准变比 `t = a·e^{jθ}` 的 π 型等效（`Yff=(y+jb/2)/a²`、`Yft=-y/conj(t)`、`Ytf=-y/t`、`Ytt=y+jb/2`）；极坐标雅可比矩阵四象限公式；每轮输出最大功率不平衡量到 `history`；收敛后回代发电机无功、支路潮流与损耗、率载率；支持 PV 母线无功越限转 PQ
- [ ] **Step 4: 通过** — 重跑 Step 2 命令，且 `iterations` 落在 4–6 次
- [ ] **Step 5: 提交** — `git commit -m "feat: newton-raphson power flow on domestic core"`

### Task 4: 三相短路计算

**Files:** Create `server/engine/shortcircuit.py`；Test `tests/test_shortcircuit.py`

**Interfaces:**
- Consumes: `build_ybus`、`solve_power_flow`
- Produces: `solve_short_circuit(case, fault_bus=None, fault_impedance=0.0) -> dict`，返回 `{"fault_bus": id, "fault_current_ka": x, "bus_voltages": [{"bus","vm"}], "per_bus": [{"bus","current_ka","zbus_mag"}]}`

- [ ] **Step 1: 写失败测试**

```python
def test_fault_bus_voltage_collapses(self):
    res = solve_short_circuit(get_case("ieee14"), fault_bus=4)
    v4 = [b for b in res["bus_voltages"] if b["bus"] == 4][0]
    self.assertLess(v4["vm"], 0.05)

def test_two_machine_matches_analytic_current(self):
    res = solve_short_circuit(get_case("two_machine"), fault_bus=2)
    expect = 100.0 / (0.20 + 0.10) * 5.0 / 1.732  # baseMVA/(Xd+Xt) -> kA @10.5kV
    self.assertLess(abs(res["fault_current_ka"] - expect) / expect, 0.05)
```

- [ ] **Step 2: 运行失败** — `python -m unittest discover -s tests -p "test_shortcircuit.py" -v`
- [ ] **Step 3: 实现** — 以潮流结果电压为故障前电压；`Zbus = inv(Ybus + Y_gen'')`（`Y_gen''` 为发电机次暂态电抗并联支路）；`I_f = V_pre/(Z_kk + Z_f)`；`ΔV = -Z[:,k]·I_f`；按 `S_base/(√3·V_base)` 折算有名值 kA，母线基准电压取 `case.base_kv`
- [ ] **Step 4: 通过** — 重跑 Step 2 命令
- [ ] **Step 5: 提交** — `git commit -m "feat: three-phase short circuit solver"`

### Task 5: 暂态稳定时域仿真

**Files:** Create `server/engine/stability.py`；Test `tests/test_stability.py`

**Interfaces:**
- Produces: `simulate_transient_stability(case, fault_bus, trip_branch, clearing_time, t_end=3.0, dt=0.01) -> dict`，返回 `{"stable": bool, "curves": {"t": [...], "machines": [{"gen","bus","delta_deg":[...],"omega_pu":[...]}]}, "max_angle_diff_deg": x, "clearing_time": t}`
- Produces: `find_critical_clearing_time(case, fault_bus, trip_branch, lo=0.02, hi=1.0, tol=0.005) -> dict`，返回 `{"cct": x, "stable_at": lo, "unstable_at": hi}`

- [ ] **Step 1: 写失败测试**

```python
def test_early_clearing_stable_late_unstable(self):
    early = simulate_transient_stability(get_case("wscc9"), 7, (6, 7), 0.05)
    late = simulate_transient_stability(get_case("wscc9"), 7, (6, 7), 0.60)
    self.assertTrue(early["stable"])
    self.assertFalse(late["stable"])

def test_cct_inside_bounds(self):
    res = find_critical_clearing_time(get_case("wscc9"), 7, (6, 7))
    self.assertGreater(res["cct"], 0.05)
    self.assertLess(res["cct"], 0.60)
```

- [ ] **Step 2: 运行失败** — `python -m unittest discover -s tests -p "test_stability.py" -v`
- [ ] **Step 3: 实现** — 负荷转恒定阻抗并由潮流结果求内电势 `E_i = V_i + jX'_i·I_i`；加 `X'd` 后 Kron 降阶到 m 台机内节点；`dδ/dt = 2πf(ω-1)`、`dω/dt = (Pm - Pe - D(ω-1))/(2H)` 用 RK4 积分；故障期间故障母线并联 `1e-4` 阻抗，切除时刻移除事故线路；判稳条件为任意两机最大相对角差超 360° 且末段仍在增大
- [ ] **Step 4: 通过** — 重跑 Step 2 命令
- [ ] **Step 5: 提交** — `git commit -m "feat: transient stability time-domain simulation"`

### Task 6: 内置算例库

**Files:** Create `server/engine/cases.py`、`server/engine/__init__.py`；Test `tests/test_cases.py`

**Interfaces:**
- Produces: `list_cases() -> list[dict]`（`id/name/desc/buses/branches/gens/level/tags`）、`get_case(case_id) -> Case`（返回深拷贝）、`register_case(case_id, case, meta)`、`case_summary(case) -> dict`

- [ ] **Step 1: 写失败测试** —— 每个内置算例 `validate()` 为空、`get_case('wscc9').buses` 长度为 9、`get_case('ieee14')` 支路数为 20、`get_case('unknown')` 抛 `KeyError`
- [ ] **Step 2: 运行失败** — `python -m unittest discover -s tests -p "test_cases.py" -v`
- [ ] **Step 3: 实现** — 录入标幺参数（100 MVA 基准）、母线类型与电压设定值、发电机 `H/D/X'd`、单线图坐标 `x/y`（0–100 画布）；配电算例 `radial5` 用于课堂演示
- [ ] **Step 4: 通过** — 重跑 Step 2 命令
- [ ] **Step 5: 提交** — `git commit -m "feat: add built-in case library"`

### Task 7: 数据持久化与账号体系

**Files:** Create `server/store.py`、`server/auth.py`；Test `tests/test_auth_store.py`

**Interfaces:**
- Produces: `hash_password(pwd) -> str`、`verify_password(pwd, stored) -> bool`、`Store(db_path)`，方法：`create_user/verify_user/create_session/user_by_token/revoke_session/list_courses/create_course/create_task/list_tasks/get_task/submit/list_submissions/log/list_logs/stats`

- [ ] **Step 1: 写失败测试** —— 正确口令校验通过、错误口令失败、注销后令牌失效、角色字段落库、提交记录可按任务回读、`stats()` 返回师生与提交计数
- [ ] **Step 2: 运行失败** — `python -m unittest discover -s tests -p "test_auth_store.py" -v`
- [ ] **Step 3: 实现** — SQLite 建表 `users/sessions/courses/tasks/submissions/logs`；种子数据 `admin`、`teacher01`、`student01`（默认口令 `PowerEdu@2026`）；口令 PBKDF2-HMAC-SHA256 12 万次迭代 + 随机盐
- [ ] **Step 4: 通过** — 重跑 Step 2 命令
- [ ] **Step 5: 提交** — `git commit -m "feat: sqlite store and account system"`

### Task 8: AI 助教

**Files:** Create `server/ai_assistant.py`；Test `tests/test_ai_assistant.py`

**Interfaces:**
- Produces: `apply_instruction(case, text) -> {"ops": [...], "case": Case, "reply": str, "applied": bool}`
- Produces: `diagnose(case, result) -> {"level": "ok|warn|risk", "findings": [{"title","detail","level"}], "text": str}`
- Produces: `draft_report(case, results, meta) -> str`（Markdown）
- Produces: `chat(message, context) -> {"reply": str, "ops": [...], "source": "rule|llm"}`

- [ ] **Step 1: 写失败测试**

```python
def test_natural_language_load_edit(self):
    out = apply_instruction(get_case("wscc9"), "把5号母线的负荷增加到120兆瓦")
    bus5 = [b for b in out["case"].buses if b.id == 5][0]
    self.assertEqual(bus5.pd, 120)

def test_diagnose_flags_low_voltage(self):
    case = get_case("wscc9")
    case.buses[4].pd *= 3
    diag = diagnose(case, solve_power_flow(case))
    self.assertTrue(any("电压" in f["title"] for f in diag["findings"]) or diag["level"] == "risk")
```

- [ ] **Step 2: 运行失败** — `python -m unittest discover -s tests -p "test_ai_assistant.py" -v`
- [ ] **Step 3: 实现** — 中文正则槽位（母线号、数值、MW/MVar/kV 单位）；支持指令：改负荷、改发电机出力、改电压设定值、投切线路、改变压器变比、加/减负荷百分比、解释结果；诊断规则表（电压越限、线路过载、相角差过大、不收敛、无功越限）；无 API Key 时走规则引擎，配置 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY` 时调用兼容 Chat Completions 的接口，网络异常自动降级
- [ ] **Step 4: 通过** — 重跑 Step 2 命令
- [ ] **Step 5: 提交** — `git commit -m "feat: ai teaching assistant"`

### Task 9: HTTP 服务与 REST API

**Files:** Create `server/app.py`、`server/__init__.py`；Test `tests/test_api.py`

**Interfaces:**
- Produces: `create_server(host="127.0.0.1", port=0, db_path=None) -> ThreadingHTTPServer`、`api_call(base, path, payload, cookie=None) -> (status, dict)`（测试辅助）、`main()`（`python -m server.app --port 8000`）
- 端点：`POST /api/auth/login|logout`、`GET /api/auth/me`、`GET /api/cases`、`GET /api/cases/<id>`、`POST /api/simulate/powerflow|shortcircuit|stability|cct`、`POST /api/ai/chat|explain|report|instruction`、`GET|POST /api/courses`、`GET|POST /api/tasks`、`POST /api/tasks/<id>/submit`、`GET /api/submissions`、`GET /api/stats`

- [ ] **Step 1: 写失败测试**

```python
def test_full_flow_login_simulate_submit(self):
    srv = create_server(port=0, db_path=":memory:")
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    status, login = api_call(base, "/api/auth/login", {"username": "student01", "password": "PowerEdu@2026"})
    self.assertEqual(status, 200)
    status, res = api_call(base, "/api/simulate/powerflow", {"case_id": "wscc9"}, login["token"])
    self.assertTrue(res["result"]["converged"])

def test_unauthorized_is_401(self):
    ...  # 未带令牌访问 /api/cases 之外的受保护端点
```

- [ ] **Step 2: 运行失败** — `python -m unittest discover -s tests -p "test_api.py" -v`
- [ ] **Step 3: 实现** — 路由表分派 + `do_GET/do_POST`；JSON 编解码；`Authorization: Bearer`/Cookie 双通道会话；静态文件 MIME 表；路径穿越防护（`resolve()` 后校验前缀）；异常统一转 `{"ok": false, "error": msg}`
- [ ] **Step 4: 通过** — 重跑 Step 2 命令，覆盖 401 与 404 负路径
- [ ] **Step 5: 提交** — `git commit -m "feat: stdlib http api server"`

### Task 10: 仿真工作台前端

**Files:** Create `server/static/index.html`、`server/static/styles.css`、`server/static/netdiagram.js`、`server/static/charts.js`

**Interfaces:**
- Consumes: Task 9 全部端点
- Produces: `NetDiagram.render(svgEl, case, result, options)`、`Charts.line(container, series, options)`、`Charts.bar(container, labels, values, options)`、`Charts.convergence(container, history)`

- [ ] **Step 1: 骨架** —— 顶栏（品牌 / 角色 / 退出）+ 视图容器（登录、工作台、我的实验、教学控制台）
- [ ] **Step 2: 单线图** —— 母线按 `x/y` 落点，平衡/PV/PQ 三类节点不同符号，支路画潮流箭头，越限母线与过载线路按阈值着色
- [ ] **Step 3: 参数编辑** —— 母线表与支路表可就地编辑，改动回写本地算例对象并可"另存为自定义算例"
- [ ] **Step 4: 结果面板** —— 潮流结果表 + 迭代收敛曲线 + 率载率柱状图 + 暂态摇摆曲线 + 短路电流表
- [ ] **Step 5: 手动验证** —— 启动服务，切换算例、运行潮流，确认图形与数值随结果刷新

### Task 11: 教学管理前端与 AI 对话

**Files:** Modify `server/static/index.html`、`server/static/app.js`

- [ ] **Step 1: AI 对话面板** —— 输入自然语言 → `/api/ai/chat` → 展示回复与操作清单，可一键应用到当前算例并重算
- [ ] **Step 2: 我的实验（学生）** —— 任务列表、载入指定算例、提交结果、查看得分与批语
- [ ] **Step 3: 教学控制台（教师）** —— 建课、发布任务（含标准答案与容差）、班级进度、导出成绩 CSV
- [ ] **Step 4: 一键生成实验报告** —— `/api/ai/report` 返回 Markdown，页内渲染并可下载 `.md`
- [ ] **Step 5: 手动验证** —— 教师账号发任务，学生账号提交，教师端可见成绩

### Task 12: 交付文档与一键启动

**Files:** Create `README.md`、`docs/方案说明书.md`、`start.bat`、`start.sh`、`requirements.txt`（内容仅说明"无需第三方依赖"）

- [ ] **Step 1: 一键启动脚本** —— 检测 Python、探测空闲端口、打印访问地址、`--open` 时自动打开浏览器
- [ ] **Step 2: 方案说明书** —— 赛题需求逐条应答、功能架构图、核心算法公式、国产化替代对照表、部署方案、经济效益测算、答辩要点
- [ ] **Step 3: README** —— 五分钟上手、账号说明、目录结构、二次开发指引、常见问题
- [ ] **Step 4: 全量回归** —— `python -m unittest discover -s tests -v` 全绿
- [ ] **Step 5: 冒烟演示** —— 启动服务，走通"登录 → 选算例 → 潮流 → AI 诊断 → 生成报告 → 提交任务"

## Self-Review

1. **Spec coverage:** 自主内核（Task 1–6）、免安装合规（Task 9、12）、AI 赋能（Task 8、11）、教学工作台（Task 10）、服务全校师生（Task 7、11）、效益论证（Task 12）—— 需求映射表中每行都有对应任务。
2. **Placeholder scan:** 无 TBD/TODO 项；关键算法任务均给出接口签名与判定阈值。
3. **Type consistency:** `solve_power_flow` 返回的 `buses[i]["vm"/"va"/"p"/"q"]` 字段被 Task 4/5/8/9/10 统一引用；`Case` 对象在 Task 2 定义后贯穿后续全部任务；`apply_instruction` 统一返回 `{"ops","case","reply","applied"}`。
