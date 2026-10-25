from datetime import datetime, timezone
import os
import sqlite3
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sentinel.db")
DB_PATH = Path(DATABASE_URL.removeprefix("sqlite:///")) if DATABASE_URL.startswith("sqlite:///") else Path("sentinel.db")
if not DB_PATH.is_absolute():
    DB_PATH = Path(__file__).resolve().parent / DB_PATH


def now():
    return datetime.now(timezone.utc).isoformat()


def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS user_profiles (
        uid TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, photo_url TEXT,
        date_of_birth TEXT, phone_number TEXT, provider TEXT NOT NULL DEFAULT 'google',
        role TEXT NOT NULL DEFAULT 'USER', account_status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_at TEXT NOT NULL, last_login_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
    )""")
    db.commit()
    return db


def get_profile(uid):
    with connection() as db:
        row = db.execute("SELECT * FROM user_profiles WHERE uid = ?", (uid,)).fetchone()
        return dict(row) if row else None


def upsert_profile(uid, profile):
    timestamp = now()
    existing = get_profile(uid)
    created = existing["created_at"] if existing else timestamp
    values = {
        "uid": uid, "name": profile.get("name") or profile.get("email", "Google user").split("@")[0],
        "email": profile.get("email", ""), "photo_url": profile.get("photoURL", ""),
        "date_of_birth": profile.get("dateOfBirth", existing.get("date_of_birth") if existing else ""),
        "phone_number": profile.get("phoneNumber", existing.get("phone_number") if existing else ""),
        "provider": "google", "role": existing.get("role", "USER") if existing else "USER",
        "account_status": existing.get("account_status", "ACTIVE") if existing else "ACTIVE",
        "created_at": created, "last_login_at": timestamp, "last_seen_at": timestamp,
    }
    with connection() as db:
        db.execute("""INSERT INTO user_profiles
            (uid,name,email,photo_url,date_of_birth,phone_number,provider,role,account_status,created_at,last_login_at,last_seen_at)
            VALUES (:uid,:name,:email,:photo_url,:date_of_birth,:phone_number,:provider,:role,:account_status,:created_at,:last_login_at,:last_seen_at)
            ON CONFLICT(uid) DO UPDATE SET name=:name,email=:email,photo_url=:photo_url,date_of_birth=:date_of_birth,
            phone_number=:phone_number,provider=:provider,last_login_at=:last_login_at,last_seen_at=:last_seen_at""", values)
        db.commit()
    return values


def ensure_profile(uid, profile):
    existing = get_profile(uid)
    if existing:
        timestamp = now()
        with connection() as db:
            db.execute("UPDATE user_profiles SET last_seen_at = ? WHERE uid = ?", (timestamp, uid))
            db.commit()
        existing["last_seen_at"] = timestamp
        return existing
    return upsert_profile(uid, profile)


def public_profile(profile):
    if not profile:
        return None
    return {"uid": profile["uid"], "name": profile["name"], "email": profile["email"], "photoURL": profile["photo_url"],
            "dateOfBirth": profile["date_of_birth"], "phoneNumber": profile["phone_number"], "provider": profile["provider"],
            "role": profile["role"], "accountStatus": profile["account_status"], "createdAt": profile["created_at"],
            "lastLoginAt": profile["last_login_at"], "lastSeenAt": profile["last_seen_at"]}
