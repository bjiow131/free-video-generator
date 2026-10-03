"""Persistent user, session and credit store.

Uses PostgreSQL when DATABASE_URL is configured and SQLite otherwise.
"""
import hashlib
import hmac
import os
import secrets
import threading
from datetime import datetime, timezone, timedelta
from core.storage import db, IS_POSTGRES

INITIAL_CREDITS=int(os.environ.get("AI_STUDIO_INITIAL_CREDITS","50"))
_lock=threading.RLock()

def _now():
    return datetime.now(timezone.utc).isoformat()

def _hash_password(password,salt=None):
    salt=salt or secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,210000)
    return "pbkdf2_sha256$210000$%s$%s"%(salt.hex(),digest.hex())

def _check_password(password,encoded):
    try:
        _,rounds,salt_hex,digest_hex=encoded.split("$",3)
        digest=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt_hex),int(rounds))
        return hmac.compare_digest(digest.hex(),digest_hex)
    except Exception:
        return False

def init_db():
    with _lock,db() as conn:
        if IS_POSTGRES:
            conn.execute("""CREATE TABLE IF NOT EXISTS users(
                id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,
                credits INTEGER NOT NULL DEFAULT 50,created_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS sessions(
                token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,expires_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS ledger(
                id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount INTEGER NOT NULL,kind TEXT NOT NULL,description TEXT NOT NULL,
                created_at TEXT NOT NULL,metadata TEXT DEFAULT '')""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id,created_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS generations(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,model TEXT NOT NULL,type TEXT NOT NULL,prompt TEXT NOT NULL,status TEXT NOT NULL,output_path TEXT,credits INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_generations_user ON generations(user_id,created_at)")
        else:
            conn.executescript("""CREATE TABLE IF NOT EXISTS users(
                id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL COLLATE NOCASE,password_hash TEXT NOT NULL,
                credits INTEGER NOT NULL DEFAULT 50,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(
                token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ledger(
                id TEXT PRIMARY KEY,user_id TEXT NOT NULL,amount INTEGER NOT NULL,kind TEXT NOT NULL,
                description TEXT NOT NULL,created_at TEXT NOT NULL,metadata TEXT DEFAULT '');
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id,created_at);
                CREATE TABLE IF NOT EXISTS generations(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,model TEXT NOT NULL,type TEXT NOT NULL,prompt TEXT NOT NULL,status TEXT NOT NULL,output_path TEXT,credits INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_generations_user ON generations(user_id,created_at);""")

def create_user(email,password):
    email=email.strip().lower()
    if "@" not in email or len(email)>254: raise ValueError("Введите корректный email")
    if len(password)<8: raise ValueError("Пароль должен содержать минимум 8 символов")
    uid,now=secrets.token_hex(16),_now()
    with _lock,db() as conn:
        try:
            conn.execute("INSERT INTO users(id,email,password_hash,credits,created_at) VALUES(%s,%s,%s,%s,%s)" if IS_POSTGRES else "INSERT INTO users(id,email,password_hash,credits,created_at) VALUES(?,?,?,?,?)",
                         (uid,email,_hash_password(password),INITIAL_CREDITS,now))
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise ValueError("Пользователь с таким email уже зарегистрирован")
            raise
        q="INSERT INTO ledger(id,user_id,amount,kind,description,created_at) VALUES(%s,%s,%s,%s,%s,%s)" if IS_POSTGRES else "INSERT INTO ledger(id,user_id,amount,kind,description,created_at) VALUES(?,?,?,?,?,?)"
        conn.execute(q,(secrets.token_hex(12),uid,INITIAL_CREDITS,"bonus","Стартовые кредиты",now))
    return uid,email

def authenticate(email,password):
    q="SELECT id,email,password_hash FROM users WHERE lower(email)=lower(%s)" if IS_POSTGRES else "SELECT id,email,password_hash FROM users WHERE email=? COLLATE NOCASE"
    with _lock,db() as conn:
        row=conn.execute(q,(email.strip().lower(),)).fetchone()
    return (row["id"],row["email"]) if row and _check_password(password,row["password_hash"]) else None

def create_session(user_id,days=30):
    raw=secrets.token_urlsafe(32)
    now=datetime.now(timezone.utc); exp=now+timedelta(days=days)
    q="INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(%s,%s,%s,%s)" if IS_POSTGRES else "INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)"
    with _lock,db() as conn:
        conn.execute(q,(hashlib.sha256(raw.encode()).hexdigest(),user_id,now.isoformat(),exp.isoformat()))
    return raw

def get_user_by_session(token):
    if not token:return None
    q="""SELECT u.id,u.email,u.credits FROM sessions s JOIN users u ON u.id=s.user_id
         WHERE s.token_hash=%s AND s.expires_at>%s""" if IS_POSTGRES else """SELECT u.id,u.email,u.credits FROM sessions s JOIN users u ON u.id=s.user_id
         WHERE s.token_hash=? AND s.expires_at>?"""
    with _lock,db() as conn:
        row=conn.execute(q,(hashlib.sha256(token.encode()).hexdigest(),_now())).fetchone()
    return dict(row) if row else None

def revoke_session(token):
    q="DELETE FROM sessions WHERE token_hash=%s" if IS_POSTGRES else "DELETE FROM sessions WHERE token_hash=?"
    with _lock,db() as conn: conn.execute(q,(hashlib.sha256(token.encode()).hexdigest(),))

def get_user(user_id):
    q="SELECT id,email,credits,created_at FROM users WHERE id=%s" if IS_POSTGRES else "SELECT id,email,credits,created_at FROM users WHERE id=?"
    with _lock,db() as conn:
        row=conn.execute(q,(user_id,)).fetchone()
    return dict(row) if row else None

def change_credits(user_id,amount,kind,description,metadata=""):
    with _lock,db() as conn:
        q="SELECT credits FROM users WHERE id=%s FOR UPDATE" if IS_POSTGRES else "SELECT credits FROM users WHERE id=?"
        row=conn.execute(q,(user_id,)).fetchone()
        if not row: raise ValueError("Пользователь не найден")
        new_balance=int(row["credits"])+amount
        if new_balance<0: raise ValueError("Недостаточно кредитов")
        q="UPDATE users SET credits=%s WHERE id=%s" if IS_POSTGRES else "UPDATE users SET credits=? WHERE id=?"
        conn.execute(q,(new_balance,user_id))
        q="INSERT INTO ledger(id,user_id,amount,kind,description,created_at,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s)" if IS_POSTGRES else "INSERT INTO ledger(id,user_id,amount,kind,description,created_at,metadata) VALUES(?,?,?,?,?,?,?)"
        conn.execute(q,(secrets.token_hex(12),user_id,amount,kind,description,_now(),metadata))
    return get_user(user_id)

def ledger(user_id,limit=50):
    q="SELECT amount,kind,description,created_at,metadata FROM ledger WHERE user_id=%s ORDER BY created_at DESC LIMIT %s" if IS_POSTGRES else "SELECT amount,kind,description,created_at,metadata FROM ledger WHERE user_id=? ORDER BY created_at DESC LIMIT ?"
    with _lock,db() as conn:
        rows=conn.execute(q,(user_id,int(limit))).fetchall()
    return [dict(r) for r in rows]

def add_generation(user_id,model,kind,prompt,status,output_path=None,credits=0):
    gid=secrets.token_hex(16)
    q="INSERT INTO generations(id,user_id,model,type,prompt,status,output_path,credits,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)" if IS_POSTGRES else "INSERT INTO generations(id,user_id,model,type,prompt,status,output_path,credits,created_at) VALUES(?,?,?,?,?,?,?,?,?)"
    with _lock,db() as conn:
        conn.execute(q,(gid,user_id,model,kind,prompt,status,output_path,int(credits),_now()))
    return gid

def generations(user_id,limit=50):
    q="SELECT id,model,type,prompt,status,output_path,credits,created_at FROM generations WHERE user_id=%s ORDER BY created_at DESC LIMIT %s" if IS_POSTGRES else "SELECT id,model,type,prompt,status,output_path,credits,created_at FROM generations WHERE user_id=? ORDER BY created_at DESC LIMIT ?"
    with _lock,db() as conn:
        rows=conn.execute(q,(user_id,int(limit))).fetchall()
    return [dict(r) for r in rows]

def update_generation(generation_id,status,output_path=None):
    q="UPDATE generations SET status=%s,output_path=%s WHERE id=%s" if IS_POSTGRES else "UPDATE generations SET status=?,output_path=? WHERE id=?"
    with _lock,db() as conn:
        conn.execute(q,(status,output_path,generation_id))
