"""HTTP 接口端到端测试：登录 → 仿真 → AI → 提交评分。"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from server.app import create_server, is_loopback, main


def api_call(base: str, path: str, payload=None, token=None, method=None):
    """调用接口，返回 (状态码, 解析后的响应体)。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method or ("POST" if data is not None else "GET"),
        headers={"Content-Type": "application/json"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        exc.close()
        return exc.code, json.loads(body) if body else {}


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server(port=0, db_path=":memory:")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        _, login = api_call(cls.base, "/api/auth/login",
                            {"username": "teacher01", "password": "PowerEdu@2026"})
        cls.teacher_token = login["token"]
        _, login = api_call(cls.base, "/api/auth/login",
                            {"username": "student01", "password": "PowerEdu@2026"})
        cls.student_token = login["token"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    # ---------- 基础 ----------

    def test_health_and_static_page(self) -> None:
        status, body = api_call(self.base, "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        with urllib.request.urlopen(self.base + "/", timeout=10) as response:
            html = response.read().decode("utf-8")
        self.assertIn("电真万确", html)

    def test_login_rejects_wrong_password(self) -> None:
        status, body = api_call(self.base, "/api/auth/login",
                                {"username": "student01", "password": "bad"})
        self.assertEqual(status, 401)
        self.assertFalse(body["ok"])

    def test_me_requires_token(self) -> None:
        status, _body = api_call(self.base, "/api/auth/me")
        self.assertEqual(status, 401)
        status, body = api_call(self.base, "/api/auth/me", token=self.student_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["user"]["username"], "student01")

    def test_dynamic_case_route(self) -> None:
        status, body = api_call(self.base, "/api/cases/wscc9")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["case"]["buses"]), 9)
        status, _body = api_call(self.base, "/api/cases/not_exist")
        self.assertEqual(status, 404)

    def test_unknown_api_returns_404(self) -> None:
        status, _body = api_call(self.base, "/api/nothing/here")
        self.assertEqual(status, 404)

    # ---------- 仿真 ----------

    def test_powerflow_requires_login(self) -> None:
        status, _body = api_call(self.base, "/api/simulate/powerflow", {"case_id": "wscc9"})
        self.assertEqual(status, 401)

    def test_powerflow_and_diagnosis(self) -> None:
        status, body = api_call(self.base, "/api/simulate/powerflow",
                                {"case_id": "ieee14"}, token=self.student_token)
        self.assertEqual(status, 200)
        self.assertTrue(body["result"]["converged"])
        self.assertEqual(len(body["result"]["buses"]), 14)
        self.assertIn("diagnosis", body)
        self.assertIn(body["diagnosis"]["level"], ("ok", "warn", "risk"))

    def test_powerflow_accepts_custom_case(self) -> None:
        _, body = api_call(self.base, "/api/cases/wscc9")
        case = body["case"]
        case["buses"][4]["pd"] = 150.0
        status, result = api_call(self.base, "/api/simulate/powerflow",
                                  {"case": case}, token=self.student_token)
        self.assertEqual(status, 200)
        self.assertTrue(result["result"]["converged"])
        self.assertLess(result["result"]["summary"]["min_vm"],
                        max(bus["vm"] for bus in result["result"]["buses"]))

    def test_shortcircuit_endpoint(self) -> None:
        status, body = api_call(self.base, "/api/simulate/shortcircuit",
                                {"case_id": "ieee14", "fault_bus": 4}, token=self.student_token)
        self.assertEqual(status, 200)
        self.assertGreater(body["result"]["fault_current_ka"], 1.0)

    def test_stability_and_cct_endpoints(self) -> None:
        status, body = api_call(self.base, "/api/simulate/stability",
                                {"case_id": "wscc9", "fault_bus": 7, "trip_branch": [6, 7],
                                 "clearing_time": 0.1, "t_end": 2.0}, token=self.student_token)
        self.assertEqual(status, 200)
        self.assertIn("stable", body["result"])
        status, body = api_call(self.base, "/api/simulate/cct",
                                {"case_id": "wscc9", "fault_bus": 7, "trip_branch": [6, 7]},
                                token=self.student_token)
        self.assertEqual(status, 200)
        self.assertGreater(body["result"]["cct"], 0.0)

    # ---------- AI 助教 ----------

    def test_ai_instruction_endpoint(self) -> None:
        status, body = api_call(self.base, "/api/ai/instruction",
                                {"case_id": "wscc9", "text": "把5号母线负荷增加到120兆瓦"},
                                token=self.student_token)
        self.assertEqual(status, 200)
        self.assertTrue(body["applied"])
        self.assertEqual(body["case"]["buses"][4]["pd"], 120.0)

    def test_ai_chat_endpoint(self) -> None:
        status, body = api_call(self.base, "/api/ai/chat",
                                {"message": "断开6-7线路", "case_id": "wscc9"},
                                token=self.student_token)
        self.assertEqual(status, 200)
        self.assertTrue(body["ops"])

    def test_ai_report_endpoint(self) -> None:
        status, body = api_call(self.base, "/api/ai/report",
                                {"case_id": "wscc9", "meta": {"author": "接口测试"}},
                                token=self.student_token)
        self.assertEqual(status, 200)
        self.assertIn("实验目的", body["report"])
        self.assertIn("接口测试", body["report"])

    # ---------- 教学管理 ----------

    def test_student_cannot_create_course(self) -> None:
        status, _body = api_call(self.base, "/api/courses",
                                 {"code": "X1", "name": "越权课程"}, token=self.student_token)
        self.assertEqual(status, 403)

    def test_teacher_creates_course_and_task_then_student_submits(self) -> None:
        status, body = api_call(self.base, "/api/courses",
                                {"code": "EE999", "name": "接口测试课程", "term": "2026 秋"},
                                token=self.teacher_token)
        self.assertEqual(status, 200)
        course_id = body["course_id"]

        status, body = api_call(self.base, "/api/tasks",
                                {"course_id": course_id, "title": "接口测试实验", "case_id": "wscc9",
                                 "requirements": "跑通潮流", "standard": {"min_vm": 0.95, "max_vm": 1.05},
                                 "tolerance": 0.02}, token=self.teacher_token)
        self.assertEqual(status, 200)
        task_id = body["task_id"]

        status, body = api_call(self.base, f"/api/tasks/{task_id}/submit",
                                {"case_id": "wscc9"}, token=self.student_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(body["score"], 0.0)
        self.assertTrue(body["comment"])

        status, body = api_call(self.base, "/api/submissions", token=self.teacher_token)
        self.assertEqual(status, 200)
        self.assertTrue(any(item["task_id"] == task_id for item in body["submissions"]))

    def test_student_sees_graded_submission(self) -> None:
        status, body = api_call(self.base, "/api/submissions", token=self.student_token)
        self.assertEqual(status, 200)
        for item in body["submissions"]:
            self.assertEqual(item["user_id"], 4)  # student01 的编号

    def test_teacher_cannot_submit(self) -> None:
        status, _body = api_call(self.base, "/api/tasks/1/submit",
                                 {"case_id": "wscc9"}, token=self.teacher_token)
        self.assertEqual(status, 403)

    def test_stats_endpoint(self) -> None:
        status, body = api_call(self.base, "/api/stats", token=self.teacher_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(body["stats"]["users"], 5)
        self.assertIn("cases", body)

    def test_logout_invalidates_token(self) -> None:
        status, body = api_call(self.base, "/api/auth/login",
                                {"username": "student02", "password": "PowerEdu@2026"})
        token = body["token"]
        status, _body = api_call(self.base, "/api/auth/logout", {}, token=token)
        self.assertEqual(status, 200)
        status, _body = api_call(self.base, "/api/auth/me", token=token)
        self.assertEqual(status, 401)


class NetworkGuardTest(unittest.TestCase):
    """默认只允许本机访问：非本机监听地址必须显式确认。"""

    def test_loopback_detection(self) -> None:
        for host in ("127.0.0.1", "localhost", "::1", "127.0.0.1"):
            self.assertTrue(is_loopback(host), host)
        for host in ("0.0.0.0", "192.168.1.10", "10.116.73.77"):
            self.assertFalse(is_loopback(host), host)

    def test_network_binding_is_refused_without_flag(self) -> None:
        self.assertEqual(main(["--host", "0.0.0.0", "--port", "0"]), 2)

    def test_lan_ip_binding_is_refused_without_flag(self) -> None:
        self.assertEqual(main(["--host", "192.168.1.20", "--port", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
