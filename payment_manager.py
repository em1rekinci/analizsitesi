import secrets
import os
from datetime import datetime
from pathlib import Path
import resend
from sqlalchemy import text
from db_manager import get_connection


class PaymentManager:
    """Havale/EFT ödeme yönetimi"""

    def __init__(self, upload_dir="uploads/receipts"):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    # =====================
    # EMAIL (RESEND)
    # =====================
    def send_email(self, to_email, subject, body):
        try:
            resend.api_key = os.getenv("RESEND_API_KEY")

            resend.Emails.send({
                "from": "Ekinci Analiz <noreply@resend.dev>",
                "to": [to_email],
                "subject": subject,
                "html": body
            })

            print(f"✅ Email gönderildi (Resend): {to_email}")
            return True

        except Exception as e:
            print(f"⚠️ Email gönderme hatası (Resend): {e}")
            return False

    # =====================
    # HELPERS
    # =====================
    def generate_payment_ref(self, user_id):
        random_part = secrets.token_hex(3).upper()
        return f"PM-{user_id}-{random_part}"

    # =====================
    # CREATE PAYMENT
    # =====================
    def create_payment(self, user_id, email, amount, sender_name, receipt_file, notes=""):
        try:
            payment_ref = self.generate_payment_ref(user_id)

            file_extension = Path(receipt_file.filename).suffix
            receipt_filename = f"{payment_ref}{file_extension}"
            receipt_path = self.upload_dir / receipt_filename

            import shutil
            with open(receipt_path, "wb") as buffer:
                shutil.copyfileobj(receipt_file.file, buffer)

            with get_connection() as conn:
                result = conn.execute(
                    text("""
                        INSERT INTO payments 
                        (user_id, email, payment_ref, amount, sender_name, receipt_path, notes)
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

            return {"success": True, "payment_id": payment_id, "payment_ref": payment_ref}

        except Exception as e:
            print(f"⚠️ Ödeme oluşturma hatası: {e}")
            return {"success": False, "error": str(e)}

    # =====================
    # APPROVE PAYMENT + MAIL
    # =====================
    def approve_payment(self, payment_id, approved_by="admin"):
        try:
            with get_connection() as conn:
                result = conn.execute(
                    text("""
                        SELECT user_id, email, payment_ref, amount, status
                        FROM payments
                        WHERE id = :pid
                    """),
                    {"pid": payment_id}
                ).fetchone()

                if not result:
                    return {"success": False, "error": "Ödeme bulunamadı"}

                user_id, email, payment_ref, amount, status = result

                if status == "approved":
                    return {"success": False, "error": "Bu ödeme zaten onaylanmış"}

                conn.execute(
                    text("""
                        UPDATE payments
                        SET status = 'approved',
                            approved_at = :approved,
                            approved_by = :by
                        WHERE id = :pid
                    """),
                    {
                        "approved": datetime.now().isoformat(),
                        "by": approved_by,
                        "pid": payment_id
                    }
                )
                conn.commit()

            # 📧 Onay maili
            subject = "Ödemeniz Onaylandı - Ekinci Analiz"
            body = f"""
            <html><body style="font-family:Arial;background:#f3f4f6;padding:20px;">
            <div style="max-width:600px;margin:auto;background:white;padding:30px;border-radius:10px;">
                <h2 style="color:#16a34a;">Ödeme Onaylandı</h2>
                <p>Ödemeniz başarıyla onaylandı.</p>
                <div style="background:#dcfce7;padding:15px;border-radius:8px;">
                    <strong>Referans:</strong> {payment_ref}<br>
                    <strong>Tutar:</strong> {amount}₺
                </div>
                <p>Hesabınıza giriş yaparak içeriklere erişebilirsiniz.</p>
            </div>
            </body></html>
            """

            self.send_email(email, subject, body)

            return {"success": True, "user_id": user_id}

        except Exception as e:
            print(f"⚠️ Onaylama hatası: {e}")
            return {"success": False, "error": str(e)}

    # =====================
    # REJECT PAYMENT + MAIL
    # =====================
    def reject_payment(self, payment_id, reason=""):
        try:
            with get_connection() as conn:
                result = conn.execute(
                    text("""
                        SELECT email, payment_ref, amount, status
                        FROM payments
                        WHERE id = :pid
                    """),
                    {"pid": payment_id}
                ).fetchone()

                if not result:
                    return {"success": False, "error": "Ödeme bulunamadı"}

                email, payment_ref, amount, status = result

                if status == "rejected":
                    return {"success": False, "error": "Bu ödeme zaten reddedilmiş"}

                conn.execute(
                    text("""
                        UPDATE payments
                        SET status = 'rejected',
                            rejection_reason = :reason
                        WHERE id = :pid
                    """),
                    {"reason": reason or "Belirtilmedi", "pid": payment_id}
                )
                conn.commit()

            # 📧 Reddetme maili
            subject = "Ödemeniz Reddedildi - Ekinci Analiz"
            body = f"""
            <html><body style="font-family:Arial;background:#f3f4f6;padding:20px;">
            <div style="max-width:600px;margin:auto;background:white;padding:30px;border-radius:10px;">
                <h2 style="color:#dc2626;">Ödeme Reddedildi</h2>
                <p>Ödemeniz aşağıdaki nedenle reddedildi:</p>
                <div style="background:#fee2e2;padding:15px;border-radius:8px;">
                    <strong>Referans:</strong> {payment_ref}<br>
                    <strong>Tutar:</strong> {amount}₺<br>
                    <strong>Neden:</strong> {reason or "Belirtilmedi"}
                </div>
            </div>
            </body></html>
            """

            self.send_email(email, subject, body)

            return {"success": True}

        except Exception as e:
            print(f"⚠️ Reddetme hatası: {e}")
            return {"success": False, "error": str(e)}

    # =====================
    # PAYMENT STATS
    # =====================
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

                rejected_count = conn.execute(
                    text("SELECT COUNT(*) FROM payments WHERE status = 'rejected'")
                ).fetchone()[0]

                total_revenue = conn.execute(
                    text("SELECT SUM(amount) FROM payments WHERE status = 'approved'")
                ).fetchone()[0] or 0

            return {
                "pending_payments": pending_count,
                "approved_payments": approved_count,
                "rejected_payments": rejected_count,
                "total_revenue": int(total_revenue)
            }

        except Exception as e:
            print(f"⚠️ Ödeme istatistik hatası: {e}")
            return {
                "pending_payments": 0,
                "approved_payments": 0,
                "rejected_payments": 0,
                "total_revenue": 0
            }

