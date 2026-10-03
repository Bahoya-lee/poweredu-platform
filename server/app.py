"""HTTP 服务与 REST 接口（纯标准库实现，无需任何第三方依赖）。

启动方式：
    python -m server.app --port 8000
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

if __package__ in (None, ""):  # 允许 python server/app.py 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import ai_assistant
from server.engine import cases as case_library
from server.engine.models import Case
from server.engine.powerflow import solve_power_flow
from server.engine.shortcircuit import solve_short_circuit
from server.engine.stability import find_critical_clearing_time, simulate_transient_stability
from server.store import Store

STATIC_DIR = Path(__file__).resolve().parent / "static"
COOKIE_NAME = "poweredu_token"
MAX_BODY = 8 * 1024 * 1024


class ApiError(Exception):
    """带状态码的业务异常。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _case_from_payload(payload: Dict[str, Any]) -> Case:
    """从请求体取出算例：优先使用自定义算例，其次按编号载入内置算例。"""
    if payload.get("case"):
        return Case.from_dict(payload["case"])
    case_id = payload.get("case_id")
    if not case_id:
        raise ApiError("缺少 case_id 或 case 字段")
    try:
        return case_library.get_case(case_id)
    except KeyError as exc:
        raise ApiError(str(exc), 404) from exc


def _resolve_case_name(case: Case) -> Case:
    """自定义算例缺少名称时补一个可读名字。"""
    if not case.name or case.name == "自定义算例":
        case.name = f"自定义算例（{len(case.buses)} 节点）"
    return case


def grade_submission(task: Dict[str, Any], case: Case, result: Dict[str, Any]) -> Tuple[float, str]:
    """按任务标准自动评分，返回分数与评语。"""
    standard = task.get("standard") or {}
    checks: List[Tuple[str, bool, str]] = []
    checks.append(("潮流收敛", bool(result.get("converged")), "潮流未收敛"))

    if result.get("converged"):
        summary = result.get("summary", {})
        if "min_vm" in standard:
            ok = summary.get("min_vm", 0.0) >= float(standard["min_vm"]) - 1e-6
            checks.append((f"最低电压不低于 {standard['min_vm']}", ok,
                           f"实际最低电压 {summary.get('min_vm', 0):.4f} p.u."))
        if "max_vm" in standard:
            ok = summary.get("max_vm", 9.9) <= float(standard["max_vm"]) + 1e-6
            checks.append((f"最高电压不超过 {standard['max_vm']}", ok,
                           f"实际最高电压 {summary.get('max_vm', 0):.4f} p.u."))
        if "max_loading" in standard:
            ok = summary.get("max_loading", 9e9) <= float(standard["max_loading"]) + 1e-6
            checks.append((f"最大负载率不超过 {standard['max_loading']}%", ok,
                           f"实际最大负载率 {summary.get('max_loading', 0):.1f}%"))
        if standard.get("stable") is not None:
            pass

    passed = sum(1 for _name, ok, _msg in checks if ok)
    score = round(100.0 * passed / len(checks), 1) if checks else 0.0
    failures = [f"{name}（{msg}）" for name, ok, msg in checks if not ok]
    comment = "全部检查通过。" if not failures else "未通过：" + "；".join(failures)
    return score, comment


class PowerEduHandler(BaseHTTPRequestHandler):
    """请求分发器。"""

    server_version = "PowerEdu/1.0"
    protocol_version = "HTTP/1.1"
    store: Store
    routes: Dict[Tuple[str, str], Callable[..., Any]] = {}

    # ---------- 基础工具 ----------

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - 覆盖父类
        if os.environ.get("POWEREDU_VERBOSE"):
            super().log_message(fmt, *args)

    def _send_json(self, payload: Any, status: int = 200, cookie: Optional[str] = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ApiError("请求体过大", 413)
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("请求体不是合法 JSON") from exc
        return data if isinstance(data, dict) else {"data": data}

    def _token(self, payload: Dict[str, Any]) -> Optional[str]:
        header = self.headers.get("Authorization") or ""
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        cookie = self.headers.get("Cookie") or ""
        for chunk in cookie.split(";"):
            if "=" in chunk:
                name, value = chunk.split("=", 1)
                if name.strip() == COOKIE_NAME:
                    return urllib.parse.unquote(value.strip())
        return payload.get("token")

    def _current_user(self, payload: Dict[str, Any], required: bool = True) -> Optional[Dict[str, Any]]:
        user = self.store.user_by_token(self._token(payload))
        if user is None and required:
            raise ApiError("请先登录", 401)
        return user

    # ---------- 路由 ----------

    def do_GET(self) -> None:  # noqa: N802 - 父类约定
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - 父类约定
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        try:
            if path.startswith("/api/"):
                payload: Dict[str, Any] = {}
                if method == "POST":
                    payload = self._read_body()
                query = urllib.parse.parse_qs(parsed.query)
                handler = self.routes.get((method, path))
                if handler is None:
                    handler, params = self._match_dynamic(method, path)
                else:
                    params = {}
                if handler is None:
                    raise ApiError(f"未知接口：{method} {path}", 404)
                result = handler(self, payload, query, params)
                if isinstance(result, tuple):
                    payload_out, status, cookie = (list(result) + [None])[:3]
                    self._send_json(payload_out, status, cookie)
                else:
                    self._send_json(result)
            else:
                self._serve_static(path)
        except ApiError as exc:
            self._send_json({"ok": False, "error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001 - 兜底，避免服务线程中断
            self._send_json({"ok": False, "error": f"服务器内部错误：{exc}"}, 500)

    def _match_dynamic(self, method: str, path: str) -> Tuple[Optional[Callable[..., Any]], Dict[str, str]]:
        """匹配 /api/tasks/3/submit 这类带参数路径。"""
        parts = [item for item in path.strip("/").split("/") if item]
        for (route_method, pattern), handler in self.routes.items():
            if route_method != method:
                continue
            pattern_parts = [item for item in pattern.strip("/").split("/") if item]
            if len(pattern_parts) != len(parts):
                continue
            params: Dict[str, str] = {}
            matched = True
            for want, got in zip(pattern_parts, parts):
                if want.startswith("<") and want.endswith(">"):
                    params[want[1:-1]] = got
                elif want != got:
                    matched = False
                    break
            if matched:
                return handler, params
        return None, {}

    def _serve_static(self, path: str) -> None:
        relative = path.lstrip("/") or "index.html"
        target = (STATIC_DIR / relative).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self._send_json({"ok": False, "error": "页面不存在"}, 404)
            return
        data = target.read_bytes()
        mime, _ = mimetypes.guess_type(str(target))
        self.send_response(200)
        self.send_header("Content-Type", (mime or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ---------------- 各接口实现 ----------------


def api_health(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    return {"ok": True, "service": "电真万确 · AI 赋能电力教学仿真平台",
            "version": "1.0.0", "llm": ai_assistant.llm_available()}


def api_login(handler: PowerEduHandler, payload, query, params) -> Tuple[Dict[str, Any], int, str]:
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    user = handler.store.verify_user(username, password)
    if not user:
        handler.store.log(None, "login_failed", f"账号 {username}")
        raise ApiError("账号或口令不正确", 401)
    token = handler.store.create_session(user["id"])
    handler.store.log(user["id"], "login", f"{user['name']} 登录")
    cookie = f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax"
    return {"ok": True, "token": token, "user": user}, 200, cookie


def api_logout(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    token = handler._token(payload)
    if token:
        handler.store.revoke_session(token)
    return {"ok": True}


def api_me(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    user = handler._current_user(payload)
    return {"ok": True, "user": user, "llm": ai_assistant.llm_available()}


def api_cases(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    handler._current_user(payload, required=False)
    return {"ok": True, "cases": case_library.list_cases()}


def api_case_detail(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    handler._current_user(payload, required=False)
    try:
        case = case_library.get_case(params["case_id"])
    except KeyError as exc:
        raise ApiError(str(exc), 404) from exc
    return {"ok": True, "case": case.to_dict()}


def api_powerflow(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    user = handler._current_user(payload)
    case = _resolve_case_name(_case_from_payload(payload))
    result = solve_power_flow(case, enforce_q_limits=bool(payload.get("enforce_q_limits")))
    if user:
        handler.store.log(user["id"], "powerflow",
                          f"{case.id} 收敛={result.get('converged')}")
    return {"ok": True, "case": case.to_dict(), "result": result,
            "diagnosis": ai_assistant.diagnose(case, result)}


def api_shortcircuit(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    user = handler._current_user(payload)
    case = _resolve_case_name(_case_from_payload(payload))
    fault_bus = payload.get("fault_bus")
    result = solve_short_circuit(case, fault_bus=int(fault_bus) if fault_bus else None,
                                 fault_impedance=float(payload.get("fault_impedance") or 0.0))
    if user:
        handler.store.log(user["id"], "shortcircuit", f"{case.id} 母线 {fault_bus}")
    return {"ok": True, "case": case.to_dict(), "result": result}


def api_stability(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    user = handler._current_user(payload)
    case = _resolve_case_name(_case_from_payload(payload))
    fault_bus = int(payload.get("fault_bus") or case.slack_bus().id)
    trip = payload.get("trip_branch")
    result = simulate_transient_stability(
        case,
        fault_bus,
        trip,
        clearing_time=float(payload.get("clearing_time") or 0.15),
        t_end=float(payload.get("t_end") or 3.0),
        dt=float(payload.get("dt") or 0.01),
    )
    if user:
        handler.store.log(user["id"], "stability",
                          f"{case.id} 故障母线 {fault_bus} 切除 {payload.get('clearing_time')}")
    return {"ok": True, "result": result}


def api_cct(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    handler._current_user(payload)
    case = _resolve_case_name(_case_from_payload(payload))
    fault_bus = int(payload.get("fault_bus") or case.slack_bus().id)
    result = find_critical_clearing_time(case, fault_bus, payload.get("trip_branch"))
    return {"ok": True, "result": result}


def api_ai_chat(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    user = handler._current_user(payload)
    message = payload.get("message") or ""
    context = {
        "case": payload.get("case"),
        "result": payload.get("result"),
        "case_id": payload.get("case_id"),
    }
    if not context["case"] and context["case_id"]:
        try:
            context["case"] = case_library.get_case(context["case_id"]).to_dict()
        except KeyError:
            pass
    if payload.get("case_id") == "custom" and payload.get("case"):
        context["case_id"] = "custom"
    reply = ai_assistant.chat(message, context)
    if user:
        handler.store.log(user["id"], "ai_chat", message[:200])
    return {"ok": True, **reply}


def api_ai_instruction(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    handler._current_user(payload)
    case = _resolve_case_name(_case_from_payload(payload))
    outcome = ai_assistant.apply_instruction(case, payload.get("text") or "")
    return {"ok": True, "reply": outcome["reply"], "ops": outcome["ops"],
            "applied": outcome["applied"], "case": outcome["case"].to_dict()}


def api_ai_explain(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    handler._current_user(payload)
    case = _resolve_case_name(_case_from_payload(payload))
    result = payload.get("result") or solve_power_flow(case)
    return {"ok": True, "diagnosis": ai_assistant.diagnose(case, result)}


def api_ai_report(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    handler._current_user(payload)
    case = _resolve_case_name(_case_from_payload(payload))
    power_flow = payload.get("power_flow")
    if not power_flow:
        candidate = payload.get("result")
        power_flow = candidate if candidate and candidate.get("buses") else solve_power_flow(case)
    report = ai_assistant.draft_report(
        case,
        power_flow=power_flow,
        short_circuit=payload.get("short_circuit"),
        stability=payload.get("stability"),
        meta=payload.get("meta"),
    )
    return {"ok": True, "report": report}


def api_courses(handler: PowerEduHandler, payload, query, params) -> Any:
    user = handler._current_user(payload)
    if handler.command == "POST":
        if user["role"] not in ("teacher", "admin"):
            raise ApiError("只有教师可以创建课程", 403)
        course_id = handler.store.create_course(
            payload.get("code") or f"C{os.urandom(2).hex()}",
            payload.get("name") or "未命名课程",
            payload.get("term") or "",
            user["id"],
            payload.get("intro") or "",
        )
        handler.store.log(user["id"], "create_course", payload.get("name", ""))
        return {"ok": True, "course_id": course_id}
    return {"ok": True, "courses": handler.store.list_courses(user)}


def api_tasks(handler: PowerEduHandler, payload, query, params) -> Any:
    user = handler._current_user(payload)
    if handler.command == "POST":
        if user["role"] not in ("teacher", "admin"):
            raise ApiError("只有教师可以发布任务", 403)
        course_id = int(payload.get("course_id") or 0)
        if not course_id:
            raise ApiError("缺少 course_id")
        task_id = handler.store.create_task(
            course_id,
            payload.get("title") or "未命名实验",
            payload.get("case_id") or "wscc9",
            payload.get("requirements") or "",
            payload.get("standard") or {},
            float(payload.get("tolerance") or 0.02),
            payload.get("deadline") or "",
            user["id"],
        )
        handler.store.log(user["id"], "create_task", payload.get("title", ""))
        return {"ok": True, "task_id": task_id}
    course_id = query.get("course_id", [None])[0]
    tasks = handler.store.list_tasks(int(course_id) if course_id else None)
    submissions = handler.store.list_submissions(user_id=user["id"] if user["role"] == "student" else None)
    return {"ok": True, "tasks": tasks, "submissions": submissions}


def api_submit(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    user = handler._current_user(payload)
    if user["role"] not in ("student", "admin"):
        raise ApiError("只有学生可以提交实验", 403)
    task = handler.store.get_task(int(params["task_id"]))
    if not task:
        raise ApiError("任务不存在", 404)
    case = _resolve_case_name(_case_from_payload(payload))
    # 服务端重新求解，避免直接采信前端上传的结果
    result = solve_power_flow(case)
    score, comment = grade_submission(task, case, result)
    submission_id = handler.store.submit(task["id"], user["id"], case.id, case.to_dict(),
                                         result, score, comment)
    handler.store.log(user["id"], "submit", f"任务 {task['id']} 得分 {score}")
    return {"ok": True, "submission_id": submission_id, "score": score,
            "comment": comment, "result": result}


def api_submissions(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    user = handler._current_user(payload)
    task_id = query.get("task_id", [None])[0]
    if user["role"] == "student":
        records = handler.store.list_submissions(task_id=int(task_id) if task_id else None,
                                                 user_id=user["id"])
    else:
        records = handler.store.list_submissions(task_id=int(task_id) if task_id else None)
    return {"ok": True, "submissions": records}


def api_stats(handler: PowerEduHandler, payload, query, params) -> Dict[str, Any]:
    handler._current_user(payload)
    return {"ok": True, "stats": handler.store.stats(), "logs": handler.store.list_logs(20),
            "cases": case_library.list_cases(), "llm": ai_assistant.llm_available()}


def build_routes() -> Dict[Tuple[str, str], Callable[..., Any]]:
    """注册全部接口路由。"""
    return {
        ("GET", "/api/health"): api_health,
        ("POST", "/api/auth/login"): api_login,
        ("POST", "/api/auth/logout"): api_logout,
        ("GET", "/api/auth/me"): api_me,
        ("GET", "/api/cases"): api_cases,
        ("GET", "/api/cases/<case_id>"): api_case_detail,
        ("POST", "/api/simulate/powerflow"): api_powerflow,
        ("POST", "/api/simulate/shortcircuit"): api_shortcircuit,
        ("POST", "/api/simulate/stability"): api_stability,
        ("POST", "/api/simulate/cct"): api_cct,
        ("POST", "/api/ai/chat"): api_ai_chat,
        ("POST", "/api/ai/instruction"): api_ai_instruction,
        ("POST", "/api/ai/explain"): api_ai_explain,
        ("POST", "/api/ai/report"): api_ai_report,
        ("GET", "/api/courses"): api_courses,
        ("POST", "/api/courses"): api_courses,
        ("GET", "/api/tasks"): api_tasks,
        ("POST", "/api/tasks"): api_tasks,
        ("POST", "/api/tasks/<task_id>/submit"): api_submit,
        ("GET", "/api/submissions"): api_submissions,
        ("GET", "/api/stats"): api_stats,
    }


def create_server(host: str = "127.0.0.1", port: int = 0, db_path: Optional[str] = None) -> ThreadingHTTPServer:
    """创建（未启动的）HTTP 服务实例。"""
    store = Store(db_path or os.environ.get("POWEREDU_DB") or "poweredu.db")

    class BoundHandler(PowerEduHandler):
        pass

    BoundHandler.store = store
    BoundHandler.routes = build_routes()

    httpd = ThreadingHTTPServer((host, port), BoundHandler)
    httpd.daemon_threads = True
    httpd.store = store  # type: ignore[attr-defined]

    original_close = httpd.server_close

    def close_with_store() -> None:
        """退出时同时关闭数据库连接，避免数据文件被占用。"""
        try:
            store.close()
        finally:
            original_close()

    httpd.server_close = close_with_store  # type: ignore[method-assign]
    return httpd


def free_port(preferred: int) -> int:
    """优先使用指定端口，被占用时自动挑选空闲端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "127.0.0.0/8")


def is_loopback(host: str) -> bool:
    """判断监听地址是否只对本机开放。"""
    return host.strip().lower() in LOOPBACK_HOSTS


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="电真万确 · AI 赋能电力教学仿真平台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认仅本机（127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--db", default=None, help="SQLite 数据库文件路径")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="显式允许对局域网/外网开放（默认禁止，需配合 --host 0.0.0.0 使用）",
    )
    args = parser.parse_args(argv)

    # 默认只允许本机访问：避免在未确认的情况下把机器暴露到网络上
    network_mode = not is_loopback(args.host)
    if network_mode and not (args.allow_network or os.environ.get("POWEREDU_ALLOW_NETWORK") == "1"):
        print(
            "已阻止对网络开放：当前平台默认只允许本机访问。\n"
            f"  你指定了 --host {args.host}，这会让同一网络内的其他机器也能连入本机。\n"
            "  如果确实需要，请显式确认后重试：\n"
            f"     python -m server.app --host {args.host} --port {args.port} --allow-network\n"
            "  或设置环境变量 POWEREDU_ALLOW_NETWORK=1。\n"
            "  仅本机使用请直接运行：python -m server.app --port 8000",
            file=sys.stderr,
        )
        return 2

    port = free_port(args.port)
    httpd = create_server(args.host, port, args.db)
    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{shown_host}:{port}/"
    banner = ["=" * 66, "  电真万确 · AI 赋能电力教学仿真平台"]
    if network_mode:
        banner += [
            f"  监听地址：{args.host}:{port}（已对网络开放）",
            "  ⚠ 其他机器可以访问本服务，请确认已获得网络与安全方面的许可",
        ]
    else:
        banner += [
            f"  本机访问：{url}",
            "  运行模式：仅本机（不开放端口，不受防火墙影响）",
        ]
    banner += [
        "  演示账号：teacher01 / student01 / admin    口令：PowerEdu@2026",
        "  停止服务：Ctrl + C",
        "=" * 66,
    ]
    print("\n".join(banner), flush=True)
    if args.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
