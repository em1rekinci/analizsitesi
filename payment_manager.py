import secrets
import os
from datetime import datetime
from pathlib import Path
import resend
from sqlalchemy import text
from db_manager import get_connection


class PaymentManager:
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

            print(f"✅ Email gönderildi: {to_email}")
            return True
        except Exception as e:
            print(f"⚠️ Email hatası: {e}")
            return False

    # =====================
    # HELPERS
    # =====================
    def generate_payment_ref(self, user_id):
        return f"PM-{user_id}-{secrets.token_hex(3).upper()}"

    # =====================
    # CREATE PAYMENT
    # =====================
    def create_payment(self, user_id, email, amount, sender_name, receipt_file, notes=""):
        try:
            payment_ref = self.generate_payment_ref(user_id)

            receipt_path = self.upload_dir / f"{payment_ref}{Path(receipt_file.filename).suffix}"
            import shutil
            with open(receipt_path, "wb") as f:
                shutil.copyfileobj(receipt_file.file, f)

            with get_connection() as conn:
                pid = conn.execute(
                    text("""
                        INSERT INTO payments
                        (user_id, email, payment_ref, amount, sender_name, receipt_path, notes)
                        VALUES (:uid,:email,:ref,:amount,:sender,:path,:notes)
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
                ).fetchone()[0]
                conn.commit()

            return {"success": True, "payment_id": pid}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # =====================
    # GET PENDING PAYMENTS
    # =====================
    def get_pending_payments(self):
        with get_connection() as conn:
            rows = conn.execute(
                text("""
                    SELECT id,user_id,email,payment_ref,amount,sender_name,
                           receipt_path,notes,status,created_at
                    FROM payments
                    WHERE status='pending'
                    ORDER BY created_at DESC
                """)
            ).fetchall()

        return [{
            "id": r[0],
            "user_id": r[1],
            "email": r[2],
            "payment_ref": r[3],
            "amount": r[4],
            "sender_name": r[5],
            "receipt_path": r[6],
            "receipt_url": f"/uploads/receipts/{Path(r[6]).name}",
            "notes": r[7],
            "status": r[8],
            "created_at": str(r[9])
        } for r in rows]

    # =====================
    # GET APPROVED PAYMENTS
    # =====================
    def get_approved_payments(self, limit=50):
        with get_connection() as conn:
            rows = conn.execute(
                text("""
                    SELECT id,user_id,email,payment_ref,amount,sender_name,
                           receipt_path,notes,status,created_at,approved_at
                    FROM payments
                    WHERE status='approved'
                    ORDER BY approved_at DESC
                    LIMIT :limit
                """),
                {"limit": limit}
            ).fetchall()

        return [{
            "id": r[0],
            "user_id": r[1],
            "email": r[2],
            "payment_ref": r[3],
            "amount": r[4],
            "sender_name": r[5],
            "receipt_path": r[6],
            "receipt_url": f"/uploads/receipts/{Path(r[6]).name}",
            "notes": r[7],
            "status": r[8],
            "created_at": str(r[9]),
            "approved_at": str(r[10])
        } for r in rows]

    # =====================
    # APPROVE PAYMENT + MAIL
    # =====================
    def approve_payment(self, payment_id, approved_by="admin"):
        with get_connection() as conn:
            email, ref, amount = conn.execute(
                text("SELECT email,payment_ref,amount FROM payments WHERE id=:id"),
                {"id": payment_id}
            ).fetchone()

            conn.execute(
                text("""
                    UPDATE payments
                    SET status='approved',
                        approved_at=:t,
                        approved_by=:by
                    WHERE id=:id
                """),
                {"t": datetime.now().isoformat(), "by": approved_by, "id": payment_id}
            )
            conn.commit()

        self.send_email(
            email,
            "Ödemeniz Onaylandı - Ekinci Analiz",
            f"<h3>Ödeme Onaylandı</h3><p>{ref} - {amount}₺</p>"
        )

        return {"success": True}

    # =====================
    # REJECT PAYMENT + MAIL
    # =====================
    def reject_payment(self, payment_id, reason=""):
        with get_connection() as conn:
            email, ref, amount = conn.execute(
                text("SELECT email,payment_ref,amount FROM payments WHERE id=:id"),
                {"id": payment_id}
            ).fetchone()

            conn.execute(
                text("""
                    UPDATE payments
                    SET status='rejected',
                        rejection_reason=:r
                    WHERE id=:id
                """),
                {"r": reason or "Belirtilmedi", "id": payment_id}
            )
            conn.commit()

        self.send_email(
            email,
            "Ödemeniz Reddedildi - Ekinci Analiz",
            f"<h3>Ödeme Reddedildi</h3><p>{ref} - {amount}₺</p><p>{reason}</p>"
        )

        return {"success": True}

    # =====================
    # USER PAYMENTS
    # =====================
    def get_user_payments(self, user_id):
        with get_connection() as conn:
            rows = conn.execute(
                text("""
                    SELECT payment_ref,amount,status,created_at,approved_at
                    FROM payments
                    WHERE user_id=:uid
                    ORDER BY created_at DESC
                """),
                {"uid": user_id}
            ).fetchall()

        return [{
            "payment_ref": r[0],
            "amount": r[1],
            "status": r[2],
            "created_at": str(r[3]),
            "approved_at": str(r[4]) if r[4] else None
        } for r in rows]

    # =====================
    # PAYMENT STATS
    # =====================
    def get_payment_stats(self):
        with get_connection() as conn:
            pending = conn.execute(text("SELECT COUNT(*) FROM payments WHERE status='pending'")).fetchone()[0]
            approved = conn.execute(text("SELECT COUNT(*) FROM payments WHERE status='approved'")).fetchone()[0]
            rejected = conn.execute(text("SELECT COUNT(*) FROM payments WHERE status='rejected'")).fetchone()[0]
            revenue = conn.execute(
                text("SELECT SUM(amount) FROM payments WHERE status='approved'")
            ).fetchone()[0] or 0

        return {
            "pending_payments": pending,
            "approved_payments": approved,
            "rejected_payments": rejected,
            "total_revenue": int(revenue)
        }
