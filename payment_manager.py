import secrets
from datetime import datetime
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import text
from db_manager import get_connection

class PaymentManager:
    """Havale/EFT ödeme yönetimi - PostgreSQL uyumlu"""
    
    def __init__(self, upload_dir="uploads/receipts"):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Email ayarları
        self.sender_email = "ekincianaliz@gmail.com"
        self.sender_password = "yosynqshvkcknnzx"  # Gmail App Password buraya
    
    def send_email(self, to_email, subject, body):
        """Email gönder"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'html'))
            
            # Gmail SMTP
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.send_message(msg)
            server.quit()
            
            print(f"✅ Email gönderildi: {to_email}")
            return True
        except Exception as e:
            print(f"⚠️ Email gönderme hatası: {e}")
            return False
    
    def generate_payment_ref(self, user_id):
        """Benzersiz ödeme referans kodu oluştur"""
        random_part = secrets.token_hex(3).upper()
        return f"PM-{user_id}-{random_part}"
    
    def create_payment(self, user_id, email, amount, sender_name, receipt_file, notes=""):
        """Yeni ödeme kaydı oluştur"""
        try:
            payment_ref = self.generate_payment_ref(user_id)
            
            file_extension = Path(receipt_file.filename).suffix
            receipt_filename = f"{payment_ref}{file_extension}"
            receipt_path = self.upload_dir / receipt_filename
            
            import shutil
            with open(receipt_path, "wb") as buffer:
                shutil.copyfileobj(receipt_file.file, buffer)
            
            print(f"💾 Dosya kaydedildi: {receipt_path}")
            
            with get_connection() as conn:
                result = conn.execute(
                    text("""
                        INSERT INTO payments (user_id, email, payment_ref, amount, sender_name, receipt_path, notes)
                        VALUES (:uid, :email, :ref, :amount, :sender, :path, :notes)
                        RETURNING id
                    """),
                    {
                        "uid": user_id,
                        "email": email,
                        "ref": payment_ref,
                        "amount": amount,
                        "sender": sender_name,
                        "path": str(receipt_path),
                        "notes": notes
                    }
                )
                payment_id = result.fetchone()[0]
                conn.commit()
            
            print(f"✅ Yeni ödeme kaydı: {payment_ref}")
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_ref": payment_ref
            }
            
        except Exception as e:
            print(f"⚠️ Ödeme kaydetme hatası: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def get_pending_payments(self):
        """Bekleyen ödemeleri getir"""
        try:
            with get_connection() as conn:
                results = conn.execute(
                    text("""
                        SELECT id, user_id, email, payment_ref, amount, sender_name, 
                               receipt_path, notes, status, created_at
                        FROM payments
                        WHERE status = 'pending'
                        ORDER BY created_at DESC
                    """)
                ).fetchall()
            
            payments = []
            for row in results:
                payments.append({
                    "id": row[0],
                    "user_id": row[1],
                    "email": row[2],
                    "payment_ref": row[3],
                    "amount": row[4],
                    "sender_name": row[5],
                    "receipt_path": row[6],
                    "receipt_url": f"/uploads/receipts/{Path(row[6]).name}",
                    "notes": row[7],
                    "status": row[8],
                    "status_text": "Beklemede",
                    "created_at": str(row[9])
                })
            
            return payments
            
        except Exception as e:
            print(f"⚠️ Bekleyen ödemeler getirme hatası: {e}")
            return []
    
    def get_approved_payments(self, limit=20):
        """Onaylanan ödemeleri getir"""
        try:
            with get_connection() as conn:
                results = conn.execute(
                    text("""
                        SELECT id, user_id, email, payment_ref, amount, sender_name, 
                               receipt_path, notes, status, created_at, approved_at
                        FROM payments
                        WHERE status = 'approved'
                        ORDER BY approved_at DESC
                        LIMIT :limit
                    """),
                    {"limit": limit}
                ).fetchall()
            
            payments = []
            for row in results:
                payments.append({
                    "id": row[0],
                    "user_id": row[1],
                    "email": row[2],
                    "payment_ref": row[3],
                    "amount": row[4],
                    "sender_name": row[5],
                    "receipt_path": row[6],
                    "receipt_url": f"/uploads/receipts/{Path(row[6]).name}",
                    "notes": row[7],
                    "status": row[8],
                    "status_text": "Onaylandı",
                    "created_at": str(row[9]),
                    "approved_at": str(row[10])
                })
            
            return payments
            
        except Exception as e:
            print(f"⚠️ Onaylı ödemeler getirme hatası: {e}")
            return []
    
    def approve_payment(self, payment_id, approved_by="admin"):
        """Ödemeyi onayla"""
        try:
            with get_connection() as conn:
                result = conn.execute(
                    text("SELECT user_id, status FROM payments WHERE id = :pid"),
                    {"pid": payment_id}
                ).fetchone()
                
                if not result:
                    return {"success": False, "error": "Ödeme bulunamadı"}
                
                user_id, current_status = result
                
                if current_status == "approved":
                    return {"success": False, "error": "Bu ödeme zaten onaylanmış"}
                
                conn.execute(
                    text("""
                        UPDATE payments 
                        SET status = 'approved', approved_at = :approved, approved_by = :by
                        WHERE id = :pid
                    """),
                    {
                        "approved": datetime.now().isoformat(),
                        "by": approved_by,
                        "pid": payment_id
                    }
                )
                conn.commit()
            
            print(f"✅ Ödeme onaylandı: {payment_id}")
            return {"success": True, "user_id": user_id}
            
        except Exception as e:
            print(f"⚠️ Ödeme onaylama hatası: {e}")
            return {"success": False, "error": str(e)}
    
    def reject_payment(self, payment_id, reason=""):
        """Ödemeyi reddet ve kullanıcıya mail gönder"""
        try:
            with get_connection() as conn:
                # Ödeme bilgilerini al
                result = conn.execute(
                    text("SELECT email, payment_ref, amount FROM payments WHERE id = :pid"),
                    {"pid": payment_id}
                ).fetchone()
                
                if not result:
                    return {"success": False, "error": "Ödeme bulunamadı"}
                
                user_email, payment_ref, amount = result
                
                # Ödemeyi reddet
                conn.execute(
                    text("""
                        UPDATE payments 
                        SET status = 'rejected', rejection_reason = :reason
                        WHERE id = :pid
                    """),
                    {"reason": reason if reason else "Belirtilmedi", "pid": payment_id}
                )
                conn.commit()
            
            print(f"✅ Ödeme reddedildi: {payment_id}")
            
            # Email göndermeyi dene (başarısız olsa bile rejection geçerli)
            try:
                subject = "Ödemeniz Reddedildi - Ekinci Analiz"
                body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; background: #f3f4f6; padding: 20px;">
                    <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px;">
                        <h2 style="color: #dc2626;">Ödeme Reddedildi</h2>
                        <p>Sayın Kullanıcı,</p>
                        <p>Ödemeniz aşağıdaki nedenle reddedilmiştir:</p>
                        
                        <div style="background: #fee2e2; padding: 15px; border-radius: 8px; margin: 20px 0;">
                            <strong>Referans:</strong> {payment_ref}<br>
                            <strong>Tutar:</strong> {amount}₺<br>
                            <strong>Ret Nedeni:</strong> {reason if reason else "Belirtilmedi"}
                        </div>
                        
                        <p>Lütfen ödeme dekontunuzu kontrol ederek tekrar deneyiniz.</p>
                        <p>Sorularınız için: <a href="mailto:ekincianaliz@gmail.com">ekincianaliz@gmail.com</a></p>
                        
                        <hr style="margin: 30px 0; border: none; border-top: 1px solid #e5e7eb;">
                        <p style="font-size: 12px; color: #6b7280;">
                            Ekinci Analiz - Premium Futbol Analiz Platformu
                        </p>
                    </div>
                </body>
                </html>
                """
                
                email_result = self.send_email(user_email, subject, body)
                if email_result:
                    print(f"✅ Reddetme maili gönderildi: {user_email}")
                else:
                    print(f"⚠️ Mail gönderilemedi ama ödeme reddedildi: {user_email}")
            except Exception as email_error:
                print(f"⚠️ Email hatası (ödeme yine de reddedildi): {email_error}")
            
            return {"success": True}
            
        except Exception as e:
            print(f"⚠️ Ödeme reddetme hatası: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def get_user_payments(self, user_id):
        """Kullanıcının tüm ödemelerini getir"""
        try:
            with get_connection() as conn:
                results = conn.execute(
                    text("""
                        SELECT payment_ref, amount, status, created_at, approved_at
                        FROM payments
                        WHERE user_id = :uid
                        ORDER BY created_at DESC
                    """),
                    {"uid": user_id}
                ).fetchall()
            
            payments = []
            for row in results:
                status_text = {
                    "pending": "Beklemede",
                    "approved": "Onaylandı",
                    "rejected": "Reddedildi"
                }.get(row[2], "Bilinmiyor")
                
                payments.append({
                    "payment_ref": row[0],
                    "amount": row[1],
                    "status": row[2],
                    "status_text": status_text,
                    "created_at": str(row[3]),
                    "approved_at": str(row[4]) if row[4] else None
                })
            
            return payments
            
        except Exception as e:
            print(f"⚠️ Kullanıcı ödemeleri getirme hatası: {e}")
            return []
    
    def get_payment_stats(self):
        """Ödeme istatistikleri"""
        try:
            with get_connection() as conn:
                pending_count = conn.execute(
                    text("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
                ).fetchone()[0]
                
                approved_count = conn.execute(
                    text("SELECT COUNT(*) FROM payments WHERE status = 'approved'")
                ).fetchone()[0]
                
                total_revenue = conn.execute(
                    text("SELECT SUM(amount) FROM payments WHERE status = 'approved'")
                ).fetchone()[0] or 0
            
            return {
                "pending_payments": pending_count,
                "approved_payments": approved_count,
                "total_revenue": int(total_revenue)
            }
            
        except Exception as e:
            print(f"⚠️ İstatistik hatası: {e}")
            return {
                "pending_payments": 0,
                "approved_payments": 0,
                "total_revenue": 0
            }
