import sqlite3
import secrets
from datetime import datetime
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class PaymentManager:
    """Havale/EFT ödeme yönetimi"""
    
    def __init__(self, db_path="users.db", upload_dir="uploads/receipts"):
        self.db_path = db_path
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._init_database()
        
        # Email ayarları
        self.sender_email = "ekincianaliz@gmail.com"
        self.sender_password = "yosynqshvkcknnzx"  # Gmail App Password
    
    def _init_database(self):
        """Payments tablosunu oluştur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                payment_ref TEXT UNIQUE NOT NULL,
                amount REAL NOT NULL,
                sender_name TEXT NOT NULL,
                receipt_path TEXT NOT NULL,
                notes TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                approved_at TEXT,
                approved_by TEXT,
                rejection_reason TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        conn.commit()
        conn.close()
        print("✅ Payments tablosu hazır")
    
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
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO payments (user_id, email, payment_ref, amount, sender_name, receipt_path, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, email, payment_ref, amount, sender_name, str(receipt_path), notes))
            
            conn.commit()
            payment_id = cursor.lastrowid
            conn.close()
            
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
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, user_id, email, payment_ref, amount, sender_name, 
                       receipt_path, notes, status, created_at
                FROM payments
                WHERE status = 'pending'
                ORDER BY created_at DESC
            """)
            
            payments = []
            for row in cursor.fetchall():
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
                    "created_at": row[9]
                })
            
            conn.close()
            return payments
            
        except Exception as e:
            print(f"⚠️ Bekleyen ödemeler getirme hatası: {e}")
            return []
    
    def get_approved_payments(self, limit=20):
        """Onaylanan ödemeleri getir"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, user_id, email, payment_ref, amount, sender_name, 
                       receipt_path, notes, status, created_at, approved_at
                FROM payments
                WHERE status = 'approved'
                ORDER BY approved_at DESC
                LIMIT ?
            """, (limit,))
            
            payments = []
            for row in cursor.fetchall():
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
                    "created_at": row[9],
                    "approved_at": row[10]
                })
            
            conn.close()
            return payments
            
        except Exception as e:
            print(f"⚠️ Onaylı ödemeler getirme hatası: {e}")
            return []
    
    def approve_payment(self, payment_id, approved_by="admin"):
        """Ödemeyi onayla"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT user_id, status FROM payments WHERE id = ?", (payment_id,))
            result = cursor.fetchone()
            
            if not result:
                conn.close()
                return {"success": False, "error": "Ödeme bulunamadı"}
            
            user_id, current_status = result
            
            if current_status == "approved":
                conn.close()
                return {"success": False, "error": "Bu ödeme zaten onaylanmış"}
            
            cursor.execute("""
                UPDATE payments 
                SET status = 'approved', approved_at = ?, approved_by = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), approved_by, payment_id))
            
            conn.commit()
            conn.close()
            
            print(f"✅ Ödeme onaylandı: {payment_id}")
            return {"success": True, "user_id": user_id}
            
        except Exception as e:
            print(f"⚠️ Ödeme onaylama hatası: {e}")
            return {"success": False, "error": str(e)}
    
    def reject_payment(self, payment_id, reason=""):
        """Ödemeyi reddet ve kullanıcıya mail gönder"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Ödeme bilgilerini al
            cursor.execute("SELECT email, payment_ref, amount FROM payments WHERE id = ?", (payment_id,))
            result = cursor.fetchone()
            
            if not result:
                conn.close()
                return {"success": False, "error": "Ödeme bulunamadı"}
            
            user_email, payment_ref, amount = result
            
            # Ödemeyi reddet
            cursor.execute("""
                UPDATE payments 
                SET status = 'rejected', rejection_reason = ?
                WHERE id = ?
            """, (reason if reason else "Belirtilmedi", payment_id))
            
            conn.commit()
            conn.close()
            
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
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT payment_ref, amount, status, created_at, approved_at
                FROM payments
                WHERE user_id = ?
                ORDER BY created_at DESC
            """, (user_id,))
            
            payments = []
            for row in cursor.fetchall():
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
                    "created_at": row[3],
                    "approved_at": row[4]
                })
            
            conn.close()
            return payments
            
        except Exception as e:
            print(f"⚠️ Kullanıcı ödemeleri getirme hatası: {e}")
            return []
    
    def get_payment_stats(self):
        """Ödeme istatistikleri"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
            pending_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'approved'")
            approved_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT SUM(amount) FROM payments WHERE status = 'approved'")
            total_revenue = cursor.fetchone()[0] or 0
            
            conn.close()
            
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
