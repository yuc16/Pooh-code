"""Web 端用户鉴权：SQLite + scrypt 密码 + 服务端 token。

只服务 Web channel；CLI / 飞书等渠道不走这里。
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .paths import PROJECT_ROOT

# 放到项目根目录下的 private/ 里，故意避开 workplace/ ——
# 沙箱只允许 agent 操作 workplace/，所以这里 agent 读不到也写不到。
PRIVATE_DIR = PROJECT_ROOT / "private"
DB_PATH = PRIVATE_DIR / "auth.db"
TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 天

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LEN = 64

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    pass


@dataclass
class User:
    id: int
    email: str


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LEN,
        maxmem=128 * 1024 * 1024,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$", 2)
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=len(expected),
        maxmem=128 * 1024 * 1024,
    )
    return secrets.compare_digest(actual, expected)


class AuthStore:
    """SQLite 单文件；进程级锁保证写操作安全。"""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    pwd_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    ua TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tokens_user ON auth_tokens(user_id);
                """
            )

    # ---------- user ops ----------
    @staticmethod
    def _normalize_email(email: str) -> str:
        email = (email or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise AuthError("邮箱格式不正确")
        return email

    @staticmethod
    def _check_password(password: str) -> None:
        if not password or len(password) < 8:
            raise AuthError("密码至少 8 位")
        if len(password) > 128:
            raise AuthError("密码过长")

    def register(self, email: str, password: str) -> User:
        email = self._normalize_email(email)
        self._check_password(password)
        with self._lock, self._conn:
            try:
                cur = self._conn.execute(
                    "INSERT INTO users(email, pwd_hash, created_at) VALUES(?,?,?)",
                    (email, _hash_password(password), int(time.time())),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthError("该邮箱已注册") from exc
            return User(id=int(cur.lastrowid), email=email)

    def login(self, email: str, password: str) -> User:
        email = self._normalize_email(email)
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, pwd_hash FROM users WHERE email=?", (email,)
            ).fetchone()
        if not row:
            raise AuthError("邮箱或密码错误")
        uid, em, pwd_hash = row
        if not _verify_password(password, pwd_hash):
            raise AuthError("邮箱或密码错误")
        return User(id=int(uid), email=em)

    # ---------- token ops ----------
    def issue_token(self, user_id: int, ua: str | None = None, ttl: int = TOKEN_TTL_SECONDS) -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO auth_tokens(token, user_id, created_at, expires_at, ua) VALUES(?,?,?,?,?)",
                (token, user_id, now, now + ttl, ua),
            )
        return token

    def resolve_token(self, token: str | None) -> User | None:
        if not token:
            return None
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                """
                SELECT u.id, u.email, t.expires_at FROM auth_tokens t
                JOIN users u ON u.id = t.user_id
                WHERE t.token=?
                """,
                (token,),
            ).fetchone()
        if not row:
            return None
        uid, email, exp = row
        if int(exp) < now:
            self.revoke_token(token)
            return None
        return User(id=int(uid), email=email)

    def revoke_token(self, token: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM auth_tokens WHERE token=?", (token,))

    def gc_expired(self) -> None:
        now = int(time.time())
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (now,))


# 模块级单例（server 启动时 import 即创建，线程安全）
_store_singleton: AuthStore | None = None
_store_lock = threading.Lock()


def get_store() -> AuthStore:
    global _store_singleton
    if _store_singleton is None:
        with _store_lock:
            if _store_singleton is None:
                _store_singleton = AuthStore()
    return _store_singleton
