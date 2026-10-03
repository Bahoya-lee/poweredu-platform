"""口令散列、会话与教学数据持久化测试。"""

from __future__ import annotations

import unittest

from server.auth import hash_password, is_expired, verify_password
from server.store import Store


class AuthTest(unittest.TestCase):
    def test_hash_and_verify(self) -> None:
        stored = hash_password("PowerEdu@2026")
        self.assertTrue(verify_password("PowerEdu@2026", stored))
        self.assertFalse(verify_password("wrong", stored))

    def test_hash_is_salted(self) -> None:
        self.assertNotEqual(hash_password("abc"), hash_password("abc"))

    def test_plaintext_never_stored(self) -> None:
        self.assertNotIn("PowerEdu@2026", hash_password("PowerEdu@2026"))

    def test_malformed_hash_is_rejected(self) -> None:
        self.assertFalse(verify_password("abc", "not-a-hash"))

    def test_expiry_helper(self) -> None:
        self.assertTrue(is_expired("2000-01-01T00:00:00+00:00"))
        self.assertFalse(is_expired("2999-01-01T00:00:00+00:00"))
        self.assertTrue(is_expired("垃圾字符串"))


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")

    def test_seed_creates_demo_accounts(self) -> None:
        stats = self.store.stats()
        self.assertGreaterEqual(stats["students"], 2)
        self.assertGreaterEqual(stats["teachers"], 2)
        self.assertGreaterEqual(stats["tasks"], 3)

    def test_login_and_session_lifecycle(self) -> None:
        user = self.store.verify_user("student01", "PowerEdu@2026")
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "student")
        self.assertIsNone(self.store.verify_user("student01", "bad-password"))

        token = self.store.create_session(user["id"])
        self.assertEqual(self.store.user_by_token(token)["username"], "student01")
        self.store.revoke_session(token)
        self.assertIsNone(self.store.user_by_token(token))
        self.assertIsNone(self.store.user_by_token("不存在"))

    def test_course_membership_filters_students(self) -> None:
        student = next(user for user in self.store.list_users("student") if user["username"] == "student01")
        outsider = next(user for user in self.store.list_users("student") if user["username"] == "student02")
        self.assertTrue(self.store.list_courses(student))
        self.assertEqual(self.store.list_courses(outsider), [])

    def test_task_and_submission_flow(self) -> None:
        student = self.store.verify_user("student01", "PowerEdu@2026")
        teacher = self.store.verify_user("teacher01", "PowerEdu@2026")
        course_id = self.store.list_courses(teacher)[0]["id"]
        task_id = self.store.create_task(course_id, "单元测试任务", "wscc9", "要求",
                                         {"min_vm": 0.9}, 0.02, "2026-12-31", teacher["id"])
        submission_id = self.store.submit(task_id, student["id"], "wscc9",
                                          {"id": "wscc9"}, {"converged": True}, 90.0, "自动评分")
        records = self.store.list_submissions(task_id=task_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["student_name"], student["name"])
        self.assertAlmostEqual(records[0]["score"], 90.0)

        self.store.grade_submission(submission_id, 95.0, "教师复核")
        self.assertAlmostEqual(self.store.list_submissions(task_id=task_id)[0]["score"], 95.0)

    def test_log_and_stats(self) -> None:
        user = self.store.verify_user("teacher01", "PowerEdu@2026")
        self.store.log(user["id"], "unit_test", "记录一条测试日志")
        logs = self.store.list_logs(10)
        self.assertEqual(logs[0]["action"], "unit_test")
        self.assertIn("submissions", self.store.stats())

    def test_set_password(self) -> None:
        user = self.store.verify_user("student01", "PowerEdu@2026")
        self.store.set_password(user["id"], "NewPass@2026")
        self.assertIsNotNone(self.store.verify_user("student01", "NewPass@2026"))
        self.assertIsNone(self.store.verify_user("student01", "PowerEdu@2026"))


if __name__ == "__main__":
    unittest.main()
