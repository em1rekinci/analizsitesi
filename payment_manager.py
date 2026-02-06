import secrets
from datetime import datetime
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import text
from db_manager import get_connection

class PaymentManager:
    
    
    def __init__(self, upload_dir="uploads/receipts"):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Email ayarları - Environment variables'dan al
        import os
        self.resend_api_key = os.getenv("RESEND_API_KEY")
        self.email_from = "Payments <onboarding@resend.dev>"

        if not self.resend_api_key:
            print("⚠️ RESEND_API_KEY tanımlı değil")
        else:
            print("📧 Resend email sistemi aktif")


    
    def send_email(self, to_email, subject, body):
        if not self.resend_api_key:
            print("❌ Mail gönderilemedi: RESEND_API_KEY yok")
            return False

        try:
            response = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self.email_from,
                    "to": [to_email],
                    "subject": subject,
                    "html": body,
                },
                timeout=15,
            )

            if response.status_code == 200:
                print(f"✅ Mail gönderildi: {to_email}")
                return True
            else:
                print(f"❌ Mail hatası ({response.status_code}): {response.text}")
                return False

        except Exception as e:
            print(f"❌ Mail gönderme exception: {e}")
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
        """Ödemeyi onayla ve kullanıcıya bilgilendirme maili gönder"""
        try:
            with get_connection() as conn:
                result = conn.execute(
                    text("SELECT user_id, email, payment_ref, amount, status FROM payments WHERE id = :pid"),
                    {"pid": payment_id}
                ).fetchone()
                
                if not result:
                    return {"success": False, "error": "Ödeme bulunamadı"}
                
                user_id, user_email, payment_ref, amount, current_status = result
                
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
            
            # ✅ ONAYLAMA EMAİLİ GÖNDER
            try:
                subject = "🎉 Premium Üyeliğiniz Onaylandı - Ekinci Analiz"
                body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; background: #f3f4f6; padding: 20px;">
                    <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px;">
                        <h2 style="color: #10b981;">🎉 Premium Üyeliğiniz Onaylandı!</h2>
                        <p>Sayın Kullanıcı,</p>
                        <p>Ödemeniz başarıyla onaylanmıştır. Artık premium özelliklerimizden yararlanabilirsiniz!</p>
                        
                        <div style="background: #d1fae5; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #10b981;">
                            <strong>✅ Ödeme Referansı:</strong> {payment_ref}<br>
                            <strong>💰 Tutar:</strong> {amount}₺<br>
                            <strong>📅 Onaylanma Tarihi:</strong> {datetime.now().strftime('%d.%m.%Y %H:%M')}
                        </div>
                        
                        <div style="background: #fef3c7; padding: 15px; border-radius: 8px; margin: 20px 0;">
                            <h3 style="color: #92400e; margin-bottom: 10px;">🌟 Premium Özellikleriniz:</h3>
                            <ul style="color: #92400e; margin: 0; padding-left: 20px;">
                                <li>Sınırsız analiz erişimi</li>
                                <li>Özel istatistikler ve raporlar</li>
                                <li>Öncelikli destek</li>
                                <li>Tüm premium içeriklere erişim</li>
                            </ul>
                        </div>
                        
                        <p style="margin-top: 20px;">
                            <strong>Şimdi hesabınıza giriş yaparak premium özelliklerimizi keşfedebilirsiniz!</strong>
                        </p>
                        
                        <p>İyi analizler dileriz! ⚽</p>
                        
                        <hr style="margin: 30px 0; border: none; border-top: 1px solid #e5e7eb;">
                        <p style="font-size: 12px; color: #6b7280;">
                            Sorularınız için: <a href="mailto:ekincianaliz@gmail.com">ekincianaliz@gmail.com</a><br>
                            Ekinci Analiz - Premium Futbol Analiz Platformu
                        </p>
                    </div>
                </body>
                </html>
                """
                
                email_result = self.send_email(user_email, subject, body)
                if email_result:
                    print(f"✅ Onaylama maili gönderildi: {user_email}")
                else:
                    print(f"⚠️ Mail gönderilemedi ama ödeme onaylandı: {user_email}")
            except Exception as email_error:
                print(f"⚠️ Email hatası (ödeme yine de onaylandı): {email_error}")
                import traceback
                traceback.print_exc()
            
            return {"success": True, "user_id": user_id}
            
        except Exception as e:
            print(f"⚠️ Ödeme onaylama hatası: {e}")
            return {"success": False, "error": str(e)}
    
    def reject_payment(self, payment_id, reason=""):
        """Ödemeyi reddet ve kullanıcıya mail gönder"""
        print(f"🔍 DEBUG: reject_payment çağrıldı - ID: {payment_id}, Reason: {reason}")
        
        try:
            with get_connection() as conn:
                # Ödeme bilgilerini al
                print(f"📊 Veritabanından ödeme bilgileri alınıyor...")
                result = conn.execute(
                    text("SELECT email, payment_ref, amount, status FROM payments WHERE id = :pid"),
                    {"pid": payment_id}
                ).fetchone()
                
                if not result:
                    print(f"❌ HATA: Ödeme bulunamadı - ID: {payment_id}")
                    return {"success": False, "error": "Ödeme bulunamadı"}
                
                user_email, payment_ref, amount, current_status = result
                print(f"✅ Ödeme bulundu: {user_email} - {payment_ref} - {amount}₺ - Status: {current_status}")
                
                # Zaten reddedilmiş mi kontrol et
                if current_status == "rejected":
                    print(f"⚠️ Bu ödeme zaten reddedilmiş!")
                    return {"success": False, "error": "Bu ödeme zaten reddedilmiş"}
                
                # Ödemeyi reddet
                print(f"🔄 Ödeme durumu 'rejected' olarak güncelleniyor...")
                conn.execute(
                    text("""
                        UPDATE payments 
                        SET status = 'rejected', rejection_reason = :reason
                        WHERE id = :pid
                    """),
                    {"reason": reason if reason else "Belirtilmedi", "pid": payment_id}
                )
                conn.commit()
                print(f"✅ Veritabanı güncellendi")
            
            print(f"✅ Ödeme reddedildi: {payment_id}")
            
            # Email göndermeyi dene (başarısız olsa bile rejection geçerli)
            print(f"📧 Email gönderiliyor...")
            try:
                subject = "❌ Ödemeniz Reddedildi - Ekinci Analiz"
                body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; background: #f3f4f6; padding: 20px;">
                    <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px;">
                        <h2 style="color: #dc2626;">❌ Ödeme Reddedildi</h2>
                        <p>Sayın Kullanıcı,</p>
                        <p>Ne yazık ki ödemeniz aşağıdaki nedenle reddedilmiştir:</p>
                        
                        <div style="background: #fee2e2; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #dc2626;">
                            <strong>📄 Referans:</strong> {payment_ref}<br>
                            <strong>💰 Tutar:</strong> {amount}₺<br>
                            <strong>❌ Ret Nedeni:</strong> {reason if reason else "Dekont kontrolünde uyumsuzluk tespit edildi"}
                        </div>
                        
                        <div style="background: #fef3c7; padding: 15px; border-radius: 8px; margin: 20px 0;">
                            <h3 style="color: #92400e; margin-bottom: 10px;">ℹ️ Ne Yapmalısınız?</h3>
                            <ul style="color: #92400e; margin: 0; padding-left: 20px;">
                                <li>Ödeme dekontunuzu kontrol edin</li>
                                <li>Doğru tutarı gönderdiğinizden emin olun</li>
                                <li>Dekont fotoğrafının net olduğundan emin olun</li>
                                <li>Tekrar ödeme yaparak yeniden deneyin</li>
                            </ul>
                        </div>
                        
                        <p>Sorularınız için bizimle iletişime geçebilirsiniz:</p>
                        <p style="text-align: center; margin: 20px 0;">
                            <a href="mailto:ekincianaliz@gmail.com" 
                               style="background: #3b82f6; color: white; padding: 12px 24px; 
                                      text-decoration: none; border-radius: 6px; display: inline-block;">
                                📧 İletişime Geç
                            </a>
                        </p>
                        
                        <hr style="margin: 30px 0; border: none; border-top: 1px solid #e5e7eb;">
                        <p style="font-size: 12px; color: #6b7280;">
                            Ekinci Analiz - Premium Futbol Analiz Platformu<br>
                            E-posta: <a href="mailto:ekincianaliz@gmail.com">ekincianaliz@gmail.com</a>
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
                import traceback
                traceback.print_exc()
            
            print(f"✅ reject_payment işlemi tamamlandı")
            return {"success": True}
            
        except Exception as e:
            print(f"❌ KRITIK HATA: Ödeme reddetme hatası: {e}")
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
