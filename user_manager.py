import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta

class UserManager:
    """Kullanıcı kayıt, giriş ve premium yönetimi"""
    
    # SONSUZ KULLANIM İÇİN SABİT REDEEM KODU
    MASTER_REDEEM_CODE = "SOCRATES1907"
    
    def __init__(self, db_path="users.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Veritabanı tablolarını oluştur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Kullanıcılar tablosu - lifetime_premium eklendi
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT,
                lifetime_premium INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT
            )
        """)
        
        # Session tablosu
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        conn.commit()
        conn.close()
        print("✅ Veritabanı hazır")
    
    def _hash_password(self, password):
        """Şifreyi güvenli şekilde hashle"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def use_redeem_code(self, code, user_id):
        """Redeem kodunu kontrol et ve kullanıcıyı ömürlük premium yap"""
        # Sadece master kodu kabul et
        if code.upper().strip() != self.MASTER_REDEEM_CODE:
            return {"success": False, "error": "Geçersiz kod"}
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Kullanıcıyı lifetime premium yap
            cursor.execute("""
                UPDATE users 
                SET is_premium = 1, lifetime_premium = 1, premium_until = '2099-12-31'
                WHERE id = ?
            """, (user_id,))
            
            conn.commit()
            conn.close()
            
            print(f"✅ Redeem kodu kullanıldı: {code} (User: {user_id})")
            return {"success": True, "message": "Ömürlük premium aktif edildi!"}
            
        except Exception as e:
            print(f"⚠️ Redeem kodu kullanma hatası: {e}")
            return {"success": False, "error": str(e)}
    
    def register_user(self, email, password, redeem_code=None):
        """Yeni kullanıcı kaydı"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Email kontrolü
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cursor.fetchone():
                conn.close()
                return {"success": False, "error": "Bu e-posta zaten kayıtlı"}
            
            # Kullanıcı oluştur
            password_hash = self._hash_password(password)
            cursor.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, password_hash)
            )
            
            conn.commit()
            user_id = cursor.lastrowid
            conn.close()
            
            # Redeem kodu varsa kullan
            has_redeem = False
            if redeem_code and redeem_code.strip():
                redeem_result = self.use_redeem_code(redeem_code.strip(), user_id)
                if redeem_result["success"]:
                    has_redeem = True
                    print(f"✅ Redeem kod kullanıldı - lifetime premium")
            
            print(f"✅ Yeni kullanıcı: {email}")
            return {
                "success": True, 
                "user_id": user_id,
                "has_redeem": has_redeem  # Bu bilgi login için önemli
            }
            
        except Exception as e:
            print(f"⚠️ Kayıt hatası: {e}")
            return {"success": False, "error": str(e)}
    
    def login_user(self, email, password):
        """Kullanıcı girişi"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            password_hash = self._hash_password(password)
            cursor.execute(
                "SELECT id, is_premium, premium_until, lifetime_premium FROM users WHERE email = ? AND password_hash = ?",
                (email, password_hash)
            )
            
            result = cursor.fetchone()
            
            if not result:
                conn.close()
                return {"success": False, "error": "E-posta veya şifre hatalı"}
            
            user_id, is_premium, premium_until, lifetime_premium = result
            
            # Son giriş zamanını güncelle
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_id)
            )
            conn.commit()
            conn.close()
            
            # Session oluştur
            session_id = self.create_session(user_id)
            
            return {
                "success": True,
                "user_id": user_id,
                "is_premium": bool(is_premium),
                "premium_until": premium_until,
                "lifetime_premium": bool(lifetime_premium),
                "session_id": session_id
            }
            
        except Exception as e:
            print(f"⚠️ Giriş hatası: {e}")
            return {"success": False, "error": str(e)}
    
    def create_session(self, user_id):
        """Kullanıcı için session oluştur"""
        session_id = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(days=7)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_id, user_id, expires_at.isoformat())
        )
        
        conn.commit()
        conn.close()
        
        return session_id
    
    def verify_session(self, session_id):
        """Session'ı doğrula ve kullanıcı bilgilerini getir"""
        if not session_id:
            return None
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT s.user_id, u.email, u.is_premium, u.premium_until, s.expires_at,
                       u.created_at, u.last_login, u.lifetime_premium
                FROM sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.session_id = ?
            """, (session_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return None
            
            user_id, email, is_premium, premium_until, expires_at, created_at, last_login, lifetime_premium = result
            
            # Session süresi dolmuş mu?
            if datetime.fromisoformat(expires_at) < datetime.now():
                self.delete_session(session_id)
                return None
            
            return {
                "user_id": user_id,
                "email": email,
                "is_premium": bool(is_premium),
                "premium_until": premium_until,
                "lifetime_premium": bool(lifetime_premium),
                "created_at": created_at,
                "last_login": last_login
            }
            
        except Exception as e:
            print(f"⚠️ Session doğrulama hatası: {e}")
            return None
    
    def delete_session(self, session_id):
        """Session'ı sil (logout)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
    
    def activate_premium(self, user_id, months=1):
        """Kullanıcıyı premium yap"""
        premium_until = datetime.now() + timedelta(days=30 * months)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE users SET is_premium = 1, premium_until = ? WHERE id = ?",
            (premium_until.isoformat(), user_id)
        )
        
        conn.commit()
        conn.close()
        
        print(f"⭐ User {user_id} premium yapıldı ({months} ay)")
        return True
    
    def get_user_stats(self):
        """İstatistikler (admin için)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
        premium_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE lifetime_premium = 1")
        lifetime_users = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total_users": total_users,
            "premium_users": premium_users,
            "free_users": total_users - premium_users,
            "lifetime_premium_users": lifetime_users
        }
