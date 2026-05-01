"""SYBA North Fargo Practice Scheduler — backend.

Serves the static HTML app plus a small JSON API:
  GET  /                  -> the app HTML
  GET  /api/me            -> { authed, username?, role? }
  POST /api/login         -> { username, password } -> session cookie
  POST /api/logout        -> clears session
  GET  /api/schedule      -> the current schedule (public)
  PUT  /api/schedule      -> save schedule (auth required)
  GET  /api/users         -> list users (admin)
  POST /api/users         -> create user (admin)
  PUT  /api/users/<id>    -> update password/role (admin)
  DELETE /api/users/<id>  -> remove user (admin)

Storage:
  /data/users.db         SQLite — user accounts
  /data/schedule.json    JSON   — current shared schedule
  Both live in a Docker volume so they survive container rebuilds.
"""
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "users.db"
SCHEDULE_PATH = DATA_DIR / "schedule.json"
APP_DIR = Path(__file__).parent

MIN_PASSWORD_LEN = 8
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
SESSION_DAYS = 14

app = Flask(__name__, static_folder=None)

# A secret key signs the session cookie. Set SECRET_KEY in the environment for
# stable sessions across restarts; otherwise we generate a new one each boot.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SECURE_COOKIES", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
    JSON_SORT_KEYS=False,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db() -> None:
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                password_hash   TEXT    NOT NULL,
                role            TEXT    NOT NULL DEFAULT 'editor',
                full_name       TEXT,
                created_at      TEXT    NOT NULL,
                last_login_at   TEXT,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until    TEXT
            )
            """
        )
        db.commit()

    # Bootstrap the first admin from environment variables (compose sets
    # these). Only runs when the user table is empty so re-running the
    # container on an existing volume is safe.
    bootstrap_user = os.environ.get("BOOTSTRAP_ADMIN_USERNAME")
    bootstrap_pw = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
    if bootstrap_user and bootstrap_pw:
        with get_db() as db:
            count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count == 0:
                db.execute(
                    "INSERT INTO users (username, password_hash, role, created_at)"
                    " VALUES (?, ?, 'admin', ?)",
                    (
                        bootstrap_user,
                        generate_password_hash(bootstrap_pw),
                        utc_now_iso(),
                    ),
                )
                db.commit()
                app.logger.info("Bootstrapped admin user %r", bootstrap_user)


init_db()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def current_user() -> dict | None:
    if "user_id" not in session:
        return None
    return {
        "id": session["user_id"],
        "username": session.get("username"),
        "role": session.get("role"),
    }


def require_login(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "auth required"}), 401
        return fn(*args, **kwargs)

    return wrapped


def require_admin(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u or u["role"] != "admin":
            return jsonify({"error": "admin required"}), 403
        return fn(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# Static + auth routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_file(APP_DIR / "practice-scheduler.html")


@app.route("/healthz")
def healthz():
    return "ok\n", 200, {"Content-Type": "text/plain"}


@app.route("/api/me")
def me():
    u = current_user()
    if not u:
        return jsonify({"authed": False})
    return jsonify({"authed": True, "username": u["username"], "role": u["role"]})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        # Lockout check
        if user and user["locked_until"]:
            try:
                until = datetime.fromisoformat(user["locked_until"])
                if datetime.now(timezone.utc) < until:
                    remain = int((until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
                    return jsonify({
                        "error": f"Account temporarily locked. Try again in {remain} minutes."
                    }), 429
            except ValueError:
                pass

        if not user or not check_password_hash(user["password_hash"], password):
            # Tarpit + record failure
            time.sleep(0.5)
            if user:
                attempts = (user["failed_attempts"] or 0) + 1
                locked_until = None
                if attempts >= MAX_FAILED_ATTEMPTS:
                    locked_until = (
                        datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
                    ).isoformat(timespec="seconds")
                    attempts = 0
                db.execute(
                    "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                    (attempts, locked_until, user["id"]),
                )
                db.commit()
            return jsonify({"error": "Invalid username or password"}), 401

        db.execute(
            "UPDATE users SET last_login_at = ?, failed_attempts = 0,"
            " locked_until = NULL WHERE id = ?",
            (utc_now_iso(), user["id"]),
        )
        db.commit()

    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    return jsonify({"username": user["username"], "role": user["role"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/change-password", methods=["POST"])
@require_login
def change_password():
    data = request.get_json(silent=True) or {}
    current = data.get("current") or ""
    new = data.get("new") or ""
    if len(new) < MIN_PASSWORD_LEN:
        return jsonify({"error": f"New password must be at least {MIN_PASSWORD_LEN} characters."}), 400
    with get_db() as db:
        row = db.execute(
            "SELECT password_hash FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if not row or not check_password_hash(row["password_hash"], current):
            time.sleep(0.5)
            return jsonify({"error": "Current password is incorrect."}), 401
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new), session["user_id"]),
        )
        db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Schedule routes
# ---------------------------------------------------------------------------
EMPTY_SCHEDULE = {
    "version": 2,
    "teams": [],
    "gyms": [],
    "practices": [],
    "blackouts": [],
}


def read_schedule() -> dict:
    if SCHEDULE_PATH.exists():
        try:
            with SCHEDULE_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            app.logger.exception("Could not read schedule.json")
    return dict(EMPTY_SCHEDULE)


def write_schedule(payload: dict) -> None:
    tmp = SCHEDULE_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(SCHEDULE_PATH)


@app.route("/api/schedule")
def get_schedule():
    return jsonify(read_schedule())


@app.route("/api/schedule", methods=["PUT"])
@require_login
def put_schedule():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    # Whitelist top-level keys
    payload = {
        "version": data.get("version", 2),
        "teams": data.get("teams") or [],
        "gyms": data.get("gyms") or [],
        "practices": data.get("practices") or [],
        "blackouts": data.get("blackouts") or [],
    }
    payload["lastModified"] = {
        "user": session["username"],
        "at": utc_now_iso(),
    }
    write_schedule(payload)
    return jsonify({"ok": True, "lastModified": payload["lastModified"]})


# ---------------------------------------------------------------------------
# User management (admin)
# ---------------------------------------------------------------------------
def serialize_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "fullName": row["full_name"],
        "createdAt": row["created_at"],
        "lastLoginAt": row["last_login_at"],
        "locked": bool(row["locked_until"]),
    }


@app.route("/api/users")
@require_admin
def list_users():
    with get_db() as db:
        rows = db.execute(
            "SELECT id, username, role, full_name, created_at, last_login_at, locked_until"
            " FROM users ORDER BY username COLLATE NOCASE"
        ).fetchall()
    return jsonify([serialize_user(r) for r in rows])


@app.route("/api/users", methods=["POST"])
@require_admin
def create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = data.get("role") or "editor"
    full_name = (data.get("fullName") or "").strip() or None

    if role not in ("editor", "admin"):
        return jsonify({"error": "Role must be 'editor' or 'admin'."}), 400
    if not username:
        return jsonify({"error": "Username is required."}), 400
    if len(password) < MIN_PASSWORD_LEN:
        return jsonify({
            "error": f"Password must be at least {MIN_PASSWORD_LEN} characters."
        }), 400

    with get_db() as db:
        try:
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    username,
                    generate_password_hash(password),
                    role,
                    full_name,
                    utc_now_iso(),
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "A user with that username already exists."}), 409
    return jsonify({"ok": True})


@app.route("/api/users/<int:user_id>", methods=["PUT"])
@require_admin
def update_user(user_id: int):
    data = request.get_json(silent=True) or {}
    fields, params = [], []
    if data.get("password"):
        if len(data["password"]) < MIN_PASSWORD_LEN:
            return jsonify({
                "error": f"Password must be at least {MIN_PASSWORD_LEN} characters."
            }), 400
        fields.append("password_hash = ?")
        params.append(generate_password_hash(data["password"]))
    if data.get("role") in ("editor", "admin"):
        fields.append("role = ?")
        params.append(data["role"])
    if "fullName" in data:
        fields.append("full_name = ?")
        params.append((data["fullName"] or "").strip() or None)
    if data.get("unlock"):
        fields.append("failed_attempts = 0")
        fields.append("locked_until = NULL")
    if not fields:
        return jsonify({"error": "Nothing to update."}), 400
    params.append(user_id)
    with get_db() as db:
        db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)
        db.commit()
    return jsonify({"ok": True})


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@require_admin
def delete_user(user_id: int):
    if user_id == session.get("user_id"):
        return jsonify({"error": "You cannot delete your own account."}), 400
    with get_db() as db:
        # Prevent removing the last admin
        admins = db.execute(
            "SELECT id FROM users WHERE role = 'admin'"
        ).fetchall()
        if len(admins) <= 1 and any(a["id"] == user_id for a in admins):
            return jsonify({"error": "At least one admin must remain."}), 400
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Dev entry point. In production we use gunicorn (see Dockerfile).
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
