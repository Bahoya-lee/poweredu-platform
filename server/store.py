"""SQLite 数据持久层：账号、课程、实验任务、提交、操作日志。"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .auth import default_password, expiry, hash_password, is_expired, new_token, now_iso, verify_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student',
    org TEXT DEFAULT '',
    student_no TEXT DEFAULT '',
    must_change INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    term TEXT DEFAULT '',
    teacher_id INTEGER,
    intro TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS course_members (
    course_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (course_id, user_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    case_id TEXT NOT NULL,
    requirements TEXT DEFAULT '',
    standard TEXT DEFAULT '{}',
    tolerance REAL DEFAULT 0.02,
    deadline TEXT DEFAULT '',
    created_by INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    snapshot TEXT DEFAULT '{}',
    result TEXT DEFAULT '{}',
    score REAL,
    comment TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""


class Store:
    """线程安全的轻量数据访问对象。"""

    def __init__(self, db_path: str | Path = "poweredu.db", seed: bool = True) -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        if seed:
            self.seed()

    # ---------- 底层 ----------

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def _query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params))

    # ---------- 种子数据 ----------

    def seed(self) -> None:
        """首次运行写入演示账号、课程与实验任务。"""
        if self._query("SELECT id FROM users LIMIT 1"):
            return
        password = default_password()
        admin = self.create_user("admin", password, "系统管理员", "admin", org="电气与自动化学院")
        teacher = self.create_user("teacher01", password, "刘老师", "teacher", org="电气与自动化学院")
        teacher2 = self.create_user("teacher02", password, "邹老师", "teacher", org="电气与自动化学院")
        student = self.create_user("student01", password, "梁同学", "student",
                                   org="电气工程及其自动化", student_no="2025301053013")
        self.create_user("student02", password, "王同学", "student",
                         org="电气工程及其自动化", student_no="2025301053014")

        course = self.create_course("EE301", "电力系统分析", "2026 秋", teacher,
                                    "面向电气工程本科生的主干课程，含潮流、短路与稳定三个实验模块。")
        self.join_course(course, student)

        self.create_task(
            course,
            "实验一：三机九节点系统潮流计算",
            "wscc9",
            "1) 计算全网潮流分布；2) 记录各母线电压幅值与相角；3) 说明哪条线路损耗最大并解释原因。",
            {"min_vm": 0.95, "max_vm": 1.10, "max_loading": 130.0, "converged": True},
            0.02,
            "2026-11-01",
            teacher,
        )
        self.create_task(
            course,
            "实验二：IEEE 14 节点短路电流计算",
            "ieee14",
            "1) 计算 4 号母线三相短路电流；2) 给出各母线短路电流对照表；3) 分析故障点电压跌落规律。",
            {"min_vm": 0.95, "max_vm": 1.10, "max_loading": 130.0, "converged": True},
            0.05,
            "2026-11-15",
            teacher,
        )
        self.create_task(
            course,
            "实验三：功角稳定性与极限切除时间",
            "wscc9",
            "1) 仿真 7 号母线三相短路；2) 绘制发电机功角摇摆曲线；3) 用二分法求极限切除时间。",
            {"min_vm": 0.95, "max_vm": 1.10, "max_loading": 130.0, "converged": True},
            0.05,
            "2026-12-01",
            teacher2,
        )
        self.log(admin, "seed", "初始化演示数据")

    # ---------- 用户与会话 ----------

    def create_user(self, username: str, password: str, name: str, role: str = "student",
                    org: str = "", student_no: str = "") -> int:
        """创建账号，返回用户编号。"""
        cursor = self._execute(
            "INSERT INTO users (username, password, name, role, org, student_no, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (username, hash_password(password), name, role, org, student_no, now_iso()),
        )
        return int(cursor.lastrowid)

    def verify_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """校验账号口令，成功返回用户信息。"""
        rows = self._query("SELECT * FROM users WHERE username = ?", (username,))
        if not rows or not verify_password(password, rows[0]["password"]):
            return None
        return self._user_dict(rows[0])

    def user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """按编号取用户。"""
        rows = self._query("SELECT * FROM users WHERE id = ?", (user_id,))
        return self._user_dict(rows[0]) if rows else None

    def list_users(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出用户，可按角色过滤。"""
        if role:
            rows = self._query("SELECT * FROM users WHERE role = ? ORDER BY id", (role,))
        else:
            rows = self._query("SELECT * FROM users ORDER BY id")
        return [self._user_dict(row) for row in rows]

    def set_password(self, user_id: int, password: str) -> None:
        """重设口令，并清除强制改密标记。"""
        self._execute(
            "UPDATE users SET password = ?, must_change = 0 WHERE id = ?",
            (hash_password(password), user_id),
        )

    def create_session(self, user_id: int) -> str:
        """创建会话令牌。"""
        token = new_token()
        self._execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now_iso(), expiry()),
        )
        return token

    def user_by_token(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        """按令牌取用户，令牌无效或过期返回 None。"""
        if not token:
            return None
        rows = self._query("SELECT * FROM sessions WHERE token = ?", (token,))
        if not rows:
            return None
        if is_expired(rows[0]["expires_at"]):
            self._execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        return self.user_by_id(int(rows[0]["user_id"]))

    def revoke_session(self, token: str) -> None:
        """注销会话。"""
        self._execute("DELETE FROM sessions WHERE token = ?", (token,))

    # ---------- 课程与任务 ----------

    def create_course(self, code: str, name: str, term: str, teacher_id: int,
                      intro: str = "") -> int:
        """新建课程。"""
        cursor = self._execute(
            "INSERT OR IGNORE INTO courses (code, name, term, teacher_id, intro, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (code, name, term, teacher_id, intro, now_iso()),
        )
        if cursor.lastrowid:
            return int(cursor.lastrowid)
        rows = self._query("SELECT id FROM courses WHERE code = ?", (code,))
        return int(rows[0]["id"]) if rows else 0

    def list_courses(self, user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """列出课程；学生只看到自己加入的课程。"""
        if user and user["role"] == "student":
            rows = self._query(
                "SELECT c.*, u.name AS teacher_name FROM courses c"
                " LEFT JOIN users u ON u.id = c.teacher_id"
                " JOIN course_members m ON m.course_id = c.id AND m.user_id = ?"
                " ORDER BY c.id",
                (user["id"],),
            )
        else:
            rows = self._query(
                "SELECT c.*, u.name AS teacher_name FROM courses c"
                " LEFT JOIN users u ON u.id = c.teacher_id ORDER BY c.id"
            )
        return [dict(row) for row in rows]

    def join_course(self, course_id: int, user_id: int) -> None:
        """把学生加入课程。"""
        self._execute(
            "INSERT OR IGNORE INTO course_members (course_id, user_id) VALUES (?, ?)",
            (course_id, user_id),
        )

    def course_members(self, course_id: int) -> List[Dict[str, Any]]:
        """课程成员名单。"""
        rows = self._query(
            "SELECT u.* FROM users u JOIN course_members m ON m.user_id = u.id"
            " WHERE m.course_id = ? ORDER BY u.id",
            (course_id,),
        )
        return [self._user_dict(row) for row in rows]

    def create_task(self, course_id: int, title: str, case_id: str, requirements: str,
                    standard: Dict[str, Any], tolerance: float, deadline: str,
                    created_by: int) -> int:
        """发布实验任务。"""
        cursor = self._execute(
            "INSERT INTO tasks (course_id, title, case_id, requirements, standard, tolerance,"
            " deadline, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (course_id, title, case_id, requirements, json.dumps(standard, ensure_ascii=False),
             tolerance, deadline, created_by, now_iso()),
        )
        return int(cursor.lastrowid)

    def list_tasks(self, course_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """列出实验任务。"""
        if course_id:
            rows = self._query(
                "SELECT t.*, c.name AS course_name FROM tasks t"
                " JOIN courses c ON c.id = t.course_id WHERE t.course_id = ? ORDER BY t.id",
                (course_id,),
            )
        else:
            rows = self._query(
                "SELECT t.*, c.name AS course_name FROM tasks t"
                " JOIN courses c ON c.id = t.course_id ORDER BY t.id"
            )
        return [self._task_dict(row) for row in rows]

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """按编号取任务。"""
        rows = self._query(
            "SELECT t.*, c.name AS course_name FROM tasks t"
            " JOIN courses c ON c.id = t.course_id WHERE t.id = ?",
            (task_id,),
        )
        return self._task_dict(rows[0]) if rows else None

    # ---------- 提交与评分 ----------

    def submit(self, task_id: int, user_id: int, case_id: str, snapshot: Dict[str, Any],
               result: Dict[str, Any], score: Optional[float], comment: str = "") -> int:
        """保存一次实验提交。"""
        cursor = self._execute(
            "INSERT INTO submissions (task_id, user_id, case_id, snapshot, result, score,"
            " comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, user_id, case_id, json.dumps(snapshot, ensure_ascii=False),
             json.dumps(result, ensure_ascii=False), score, comment, now_iso()),
        )
        return int(cursor.lastrowid)

    def list_submissions(self, task_id: Optional[int] = None,
                         user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """查询提交记录。"""
        sql = ("SELECT s.*, u.name AS student_name, t.title AS task_title FROM submissions s"
               " JOIN users u ON u.id = s.user_id JOIN tasks t ON t.id = s.task_id WHERE 1=1")
        params: List[Any] = []
        if task_id:
            sql += " AND s.task_id = ?"
            params.append(task_id)
        if user_id:
            sql += " AND s.user_id = ?"
            params.append(user_id)
        sql += " ORDER BY s.id DESC"
        rows = self._query(sql, tuple(params))
        out = []
        for row in rows:
            item = dict(row)
            item["snapshot"] = json.loads(item["snapshot"] or "{}")
            item["result"] = json.loads(item["result"] or "{}")
            out.append(item)
        return out

    def grade_submission(self, submission_id: int, score: float, comment: str) -> None:
        """教师手工评分。"""
        self._execute("UPDATE submissions SET score = ?, comment = ? WHERE id = ?",
                      (score, comment, submission_id))

    # ---------- 日志与统计 ----------

    def log(self, user_id: Optional[int], action: str, detail: str = "") -> None:
        """写操作日志。"""
        self._execute(
            "INSERT INTO logs (user_id, action, detail, created_at) VALUES (?, ?, ?, ?)",
            (user_id, action, detail, now_iso()),
        )

    def list_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """最近操作日志。"""
        rows = self._query(
            "SELECT l.*, u.name AS user_name FROM logs l LEFT JOIN users u ON u.id = l.user_id"
            " ORDER BY l.id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    def stats(self) -> Dict[str, Any]:
        """平台概览统计。"""
        def scalar(sql: str, params: tuple = ()) -> int:
            rows = self._query(sql, params)
            return int(rows[0][0]) if rows and rows[0][0] is not None else 0

        return {
            "users": scalar("SELECT COUNT(*) FROM users"),
            "teachers": scalar("SELECT COUNT(*) FROM users WHERE role = 'teacher'"),
            "students": scalar("SELECT COUNT(*) FROM users WHERE role = 'student'"),
            "courses": scalar("SELECT COUNT(*) FROM courses"),
            "tasks": scalar("SELECT COUNT(*) FROM tasks"),
            "submissions": scalar("SELECT COUNT(*) FROM submissions"),
            "graded": scalar("SELECT COUNT(*) FROM submissions WHERE score IS NOT NULL"),
            "avg_score": round(float(
                (self._query("SELECT AVG(score) FROM submissions WHERE score IS NOT NULL") or
                 [(0,)])[0][0] or 0.0), 2),
        }

    # ---------- 行转换 ----------

    def close(self) -> None:
        """关闭数据库连接（服务退出时调用，便于备份或删除数据文件）。"""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    @staticmethod
    def _user_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "username": row["username"],
            "name": row["name"],
            "role": row["role"],
            "org": row["org"],
            "student_no": row["student_no"],
            "must_change": bool(row["must_change"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _task_dict(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        try:
            item["standard"] = json.loads(item.get("standard") or "{}")
        except (TypeError, ValueError):
            item["standard"] = {}
        return item
