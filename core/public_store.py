"""Minimal persistent user/credits store for AI Studio."""
import hashlib,hmac,os,secrets,sqlite3,threading
from datetime import datetime,timezone
DB_PATH=os.environ.get("AI_STUDIO_DB_PATH",os.path.join(os.environ.get("AI_STUDIO_DATA_DIR","/tmp/ai-studio"),"users.db"))
INITIAL_CREDITS=int(os.environ.get("AI_STUDIO_INITIAL_CREDITS","50"))
_lock=threading.RLock()
def _db():
 os.makedirs(os.path.dirname(DB_PATH) or ".",exist_ok=True); c=sqlite3.connect(DB_PATH,check_same_thread=False); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); return c
def init_db():
 with _lock,_db() as db: db.executescript("CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL COLLATE NOCASE,password_hash TEXT NOT NULL,credits INTEGER NOT NULL DEFAULT 50,created_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,amount INTEGER NOT NULL,kind TEXT NOT NULL,description TEXT NOT NULL,created_at TEXT NOT NULL,metadata TEXT DEFAULT ''); CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id); CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id,created_at);")
def _now(): return datetime.now(timezone.utc).isoformat()
def _hash_password(password,salt=None):
 salt=salt or secrets.token_bytes(16); digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,210000); return "pbkdf2_sha256$210000$%s$%s"%(salt.hex(),digest.hex())
def _check_password(password,encoded):
 try:
  _,rounds,salt_hex,digest_hex=encoded.split("$",3); digest=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt_hex),int(rounds)); return hmac.compare_digest(digest.hex(),digest_hex)
 except Exception: return False
def create_user(email,password):
 email=email.strip().lower()
 if "@" not in email or len(email)>254: raise ValueError("Введите корректный email")
 if len(password)<8: raise ValueError("Пароль должен содержать минимум 8 символов")
 uid,now=secrets.token_hex(16),_now()
 with _lock,_db() as db:
  try: db.execute("INSERT INTO users(id,email,password_hash,credits,created_at) VALUES(?,?,?,?,?)",(uid,email,_hash_password(password),INITIAL_CREDITS,now))
  except sqlite3.IntegrityError: raise ValueError("Пользователь с таким email уже зарегистрирован")
  db.execute("INSERT INTO ledger(id,user_id,amount,kind,description,created_at) VALUES(?,?,?,?,?,?)",(secrets.token_hex(12),uid,INITIAL_CREDITS,"bonus","Стартовые кредиты",now))
 return uid,email
def authenticate(email,password):
 with _lock,_db() as db: row=db.execute("SELECT id,email,password_hash FROM users WHERE email=? COLLATE NOCASE",(email.strip().lower(),)).fetchone()
 return (row["id"],row["email"]) if row and _check_password(password,row["password_hash"]) else None
def create_session(user_id,days=30):
 raw=secrets.token_urlsafe(32); from datetime import timedelta; now=datetime.now(timezone.utc); exp=now+timedelta(days=days)
 with _lock,_db() as db: db.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",(hashlib.sha256(raw.encode()).hexdigest(),user_id,now.isoformat(),exp.isoformat()))
 return raw
def get_user_by_session(token):
 if not token:return None
 with _lock,_db() as db: row=db.execute("SELECT u.id,u.email,u.credits FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",(hashlib.sha256(token.encode()).hexdigest(),_now())).fetchone()
 return dict(row) if row else None
def revoke_session(token):
 with _lock,_db() as db: db.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),))
def get_user(user_id):
 with _lock,_db() as db: row=db.execute("SELECT id,email,credits,created_at FROM users WHERE id=?",(user_id,)).fetchone()
 return dict(row) if row else None
def change_credits(user_id,amount,kind,description,metadata=""):
 with _lock,_db() as db:
  row=db.execute("SELECT credits FROM users WHERE id=?",(user_id,)).fetchone()
  if not row: raise ValueError("Пользователь не найден")
  new_balance=int(row["credits"])+amount
  if new_balance<0: raise ValueError("Недостаточно кредитов")
  db.execute("UPDATE users SET credits=? WHERE id=?",(new_balance,user_id)); db.execute("INSERT INTO ledger(id,user_id,amount,kind,description,created_at,metadata) VALUES(?,?,?,?,?,?,?)",(secrets.token_hex(12),user_id,amount,kind,description,_now(),metadata))
 return get_user(user_id)
def ledger(user_id,limit=50):
 with _lock,_db() as db: rows=db.execute("SELECT amount,kind,description,created_at,metadata FROM ledger WHERE user_id=? ORDER BY created_at DESC LIMIT ?",(user_id,limit)).fetchall()
 return [dict(r) for r in rows]
