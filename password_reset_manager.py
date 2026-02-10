import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from db_manager import get_connection
from sqlalchemy import text
from sender import send_password_reset_email

# Türkiye saati için timezone
TR_TZ = timezone(timedelta(hours=3))


class PasswordResetManager:
    """Şifre sıfırlama token yönetimi"""
    
    def __init__(self):
        self.expire_minutes = 30
        print("🔑 Password Reset Manager başlatıldı")

    def create_token(self, user_id: int, ip_address: str) -> str:
        """Şifre sıfırlama token'ı oluştur"""
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        
        # UTC zaman kullan (Supabase UTC'de tutuyor)
        expires_at = datetime.utcnow() + timedelta(minutes=self.expire_minutes)
        
        with get_connection() as conn:
            conn.execute(
                text("""
                    INSERT INTO password_reset_tokens 
                    (user_id, token_hash, expires_at, ip_address)
                    VALUES (:user_id, :token_hash, :expires_at, :ip_address)
                """),
                {
                    "user_id": user_id,
                    "token_hash": token_hash,
                    "expires_at": expires_at,
                    "ip_address": ip_address
                }
            )
            conn.commit()
        
        print(f"🔑 Token oluşturuldu - User ID: {user_id}, Expires: {expires_at}")
        return raw_token  # Hash değil, gerçek token'ı döndür

    def verify_token(self, token: str) -> dict:
    """Token'ı doğrula"""
    try:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        print(f"🔍 Token doğrulanıyor - Hash: {token_hash[:20]}...")

        with get_connection() as conn:
            result = conn.execute(
                text("""
                    SELECT user_id, expires_at, used
                    FROM password_reset_tokens
                    WHERE token_hash = :token_hash
                """),
                {"token_hash": token_hash}
            ).fetchone()

        if not result:
            print("❌ Token bulunamadı")
            return {"valid": False, "error": "Geçersiz veya süresi dolmuş token"}

        user_id, expires_at, used = result
        print(f"✅ Token bulundu - User ID: {user_id}, Used: {used}, Expires: {expires_at}")

        # Token daha önce kullanılmış mı
        if used:
            print("❌ Token zaten kullanılmış")
            return {"valid": False, "error": "Bu token zaten kullanılmış"}

        # 🔥 EN KRİTİK FIX: timezone normalize
        now_utc = datetime.now(timezone.utc)

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now_utc > expires_at:
            print(f"❌ Token süresi dolmuş - Now: {now_utc}, Expires: {expires_at}")
            return {"valid": False, "error": "Token süresi dolmuş (30 dakika)"}

        print("✅ Token geçerli")
        return {
            "valid": True,
            "user_id": user_id
        }

    except Exception as e:
        print(f"❌ Token doğrulama hatası: {e}")
        import traceback
        traceback.print_exc()
        return {"valid": False, "error": "Token doğrulama hatası"}


    def reset_password(self, token: str, new_password: str) -> dict:
        """Şifreyi sıfırla"""
        try:
            verify_result = self.verify_token(token)
            
            if not verify_result["valid"]:
                return {"success": False, "error": verify_result["error"]}
            
            user_id = verify_result["user_id"]
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            
            # Şifreyi hashle
            password_hash = hashlib.sha256(new_password.encode()).hexdigest()
            
            with get_connection() as conn:
                # Şifreyi güncelle
                conn.execute(
                    text("UPDATE users SET password_hash = :pwd WHERE id = :user_id"),
                    {"pwd": password_hash, "user_id": user_id}
                )
                
                # Token'ı kullanılmış olarak işaretle
                conn.execute(
                    text("UPDATE password_reset_tokens SET used = TRUE WHERE token_hash = :token_hash"),
                    {"token_hash": token_hash}
                )
                
                conn.commit()
            
            print(f"✅ Şifre sıfırlandı - User ID: {user_id}")
            return {"success": True, "message": "Şifreniz başarıyla değiştirildi"}
            
        except Exception as e:
            print(f"❌ Şifre sıfırlama hatası: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": "Şifre sıfırlama işlemi başarısız oldu"}
    
    def send_reset_email(self, user_email: str, reset_link: str) -> bool:
        """
        Şifre sıfırlama emaili gönder
        
        Args:
            user_email: Kullanıcı email adresi
            reset_link: Şifre sıfırlama linki
            
        Returns:
            bool: Email gönderildiyse True
        """
        try:
            result = send_password_reset_email(user_email, reset_link)
            
            if result:
                print(f"✅ Şifre sıfırlama emaili gönderildi: {user_email}")
            else:
                print(f"⚠️ Email gönderilemedi: {user_email}")
            
            return result
            
        except Exception as e:
            print(f"❌ Email gönderme hatası: {e}")
            import traceback
            traceback.print_exc()
            return False
