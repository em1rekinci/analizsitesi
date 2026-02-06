import hashlib
import secrets
from datetime import datetime, timedelta
from sqlalchemy import text
from db_manager import get_connection, init_db

class UserManager:
    """Kullanıcı kayıt, giriş ve premium yönetimi - PostgreSQL uyumlu"""
    
    # SONSUZ KULLANIM İÇİN SABİT REDEEM KODU
    MASTER_REDEEM_CODE = "SOCRATES1907"
    
    def __init__(self):
        # Database tabloları oluştur
        init_db()
    
    def _hash_password(self, password):
        """Şifreyi güvenli şekilde hashle"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def use_redeem_code(self, code, user_id):
        """Redeem kodunu kontrol et ve kullanıcıyı ömürlük premium yap"""
        if code.upper().strip() != self.MASTER_REDEEM_CODE:
            return {"success": False, "error": "Geçersiz kod"}
        
        try:
            with get_connection() as conn:
                # Kullanıcıyı lifetime premium yap
                conn.execute(
                    text("UPDATE users SET is_premium = 1, lifetime_premium = 1, premium_until = :until WHERE id = :user_id"),
                    {"until": "2099-12-31", "user_id": user_id}
                )
                conn.commit()
            
            print(f"✅ Redeem kodu kullanıldı: {code} (User: {user_id})")
            return {"success": True, "message": "Ömürlük premium aktif edildi!"}
            
        except Exception as e:
            print(f"⚠️ Redeem kodu kullanma hatası: {e}")
            return {"success": False, "error": str(e)}
    
    def register_user(self, email, password, redeem_code=None):
        """Yeni kullanıcı kaydı"""
        try:
            with get_connection() as conn:
                # Email kontrolü
                result = conn.execute(
                    text("SELECT id FROM users WHERE email = :email"),
                    {"email": email}
                ).fetchone()
                
                if result:
                    return {"success": False, "error": "Bu e-posta zaten kayıtlı"}
                
                # Kullanıcı oluştur
                password_hash = self._hash_password(password)
                result = conn.execute(
                    text("INSERT INTO users (email, password_hash) VALUES (:email, :pwd) RETURNING id"),
                    {"email": email, "pwd": password_hash}
                )
                user_id = result.fetchone()[0]
                conn.commit()
            
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
                "has_redeem": has_redeem
            }
            
        except Exception as e:
            print(f"⚠️ Kayıt hatası: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def login_user(self, email, password):
        """Kullanıcı girişi"""
        try:
            with get_connection() as conn:
                password_hash = self._hash_password(password)
                
                result = conn.execute(
                    text("SELECT id, is_premium, premium_until, lifetime_premium FROM users WHERE email = :email AND password_hash = :pwd"),
                    {"email": email, "pwd": password_hash}
                ).fetchone()
                
                if not result:
                    return {"success": False, "error": "E-posta veya şifre hatalı"}
                
                user_id, is_premium, premium_until, lifetime_premium = result
                
                # Son giriş zamanını güncelle
                conn.execute(
                    text("UPDATE users SET last_login = :login WHERE id = :user_id"),
                    {"login": datetime.now().isoformat(), "user_id": user_id}
                )
                conn.commit()
            
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
        
        with get_connection() as conn:
            conn.execute(
                text("INSERT INTO sessions (session_id, user_id, expires_at) VALUES (:sid, :uid, :exp)"),
                {"sid": session_id, "uid": user_id, "exp": expires_at.isoformat()}
            )
            conn.commit()
        
        return session_id
    
    def verify_session(self, session_id):
        """Session'ı doğrula ve kullanıcı bilgilerini getir"""
        if not session_id:
            return None
        
        try:
            with get_connection() as conn:
                result = conn.execute(
                    text("""
                        SELECT s.user_id, u.email, u.is_premium, u.premium_until, s.expires_at,
                               u.created_at, u.last_login, u.lifetime_premium
                        FROM sessions s
                        JOIN users u ON s.user_id = u.id
                        WHERE s.session_id = :sid
                    """),
                    {"sid": session_id}
                ).fetchone()
            
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
                "created_at": str(created_at),
                "last_login": last_login
            }
            
        except Exception as e:
            print(f"⚠️ Session doğrulama hatası: {e}")
            return None
    
    def delete_session(self, session_id):
        """Session'ı sil (logout)"""
        with get_connection() as conn:
            conn.execute(
                text("DELETE FROM sessions WHERE session_id = :sid"),
                {"sid": session_id}
            )
            conn.commit()
    
    def activate_premium(self, user_id, months=1):
        """Kullanıcıyı premium yap"""
        premium_until = datetime.now() + timedelta(days=30 * months)
        
        with get_connection() as conn:
            conn.execute(
                text("UPDATE users SET is_premium = 1, premium_until = :until WHERE id = :user_id"),
                {"until": premium_until.isoformat(), "user_id": user_id}
            )
            conn.commit()
        
        print(f"⭐ User {user_id} premium yapıldı ({months} ay)")
        return True
    
    def get_user_stats(self):
        """İstatistikler (admin için)"""
        with get_connection() as conn:
            total_users = conn.execute(text("SELECT COUNT(*) FROM users")).fetchone()[0]
            premium_users = conn.execute(text("SELECT COUNT(*) FROM users WHERE is_premium = 1")).fetchone()[0]
            lifetime_users = conn.execute(text("SELECT COUNT(*) FROM users WHERE lifetime_premium = 1")).fetchone()[0]
        
        return {
            "total_users": total_users,
            "premium_users": premium_users,
            "free_users": total_users - premium_users,
            "lifetime_premium_users": lifetime_users
        }
