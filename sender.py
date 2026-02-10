import os
import requests

# Resend API ayarları
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_FROM = "Ekinci Analiz <no-reply@ekincianaliz.online>"


def send_email(to: str, subject: str, body: str, html: bool = True) -> bool:
    """
    Genel email gönderme fonksiyonu (Resend API)
    
    Args:
        to: Alıcı email adresi
        subject: Email konusu
        body: Email içeriği (HTML veya plain text)
        html: True ise HTML, False ise plain text
    
    Returns:
        bool: Başarılı ise True
    """
    if not RESEND_API_KEY:
        print("❌ Mail gönderilemedi: RESEND_API_KEY environment variable tanımlı değil")
        return False

    try:
        payload = {
            "from": EMAIL_FROM,
            "to": [to],
            "subject": subject,
        }
        
        # HTML veya text olarak gönder
        if html:
            payload["html"] = body
        else:
            payload["text"] = body
        
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )

        if response.status_code == 200:
            print(f"✅ Email gönderildi: {to} - Subject: {subject}")
            return True
        else:
            print(f"❌ Email hatası ({response.status_code}): {response.text}")
            return False

    except Exception as e:
        print(f"❌ Email gönderme exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_password_reset_email(to_email: str, reset_link: str) -> bool:
    """Şifre sıfırlama emaili gönder"""
    subject = "🔑 Şifre Sıfırlama - Ekinci Analiz"
    
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background: #f3f4f6; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px;">
            <h2 style="color: #3b82f6;">🔑 Şifre Sıfırlama Talebi</h2>
            <p>Merhaba,</p>
            <p>Hesabınız için şifre sıfırlama talebi aldık. Şifrenizi sıfırlamak için aşağıdaki butona tıklayın:</p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{reset_link}" 
                   style="background: #3b82f6; color: white; padding: 14px 28px; 
                          text-decoration: none; border-radius: 8px; display: inline-block; 
                          font-weight: bold;">
                    🔓 Şifremi Sıfırla
                </a>
            </div>
            
            <div style="background: #fef3c7; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="color: #92400e; margin: 0;">
                    ⚠️ <strong>Önemli:</strong> Bu bağlantı 30 dakika boyunca geçerlidir.
                </p>
            </div>
            
            <p style="color: #6b7280; font-size: 14px;">
                Eğer bu talebi siz oluşturmadıysanız, bu e-postayı yok sayabilirsiniz. 
                Şifreniz değiştirilmeyecektir.
            </p>
            
            <p style="color: #9ca3af; font-size: 12px; margin-top: 20px;">
                Buton çalışmıyorsa bu linki tarayıcınıza kopyalayın:<br>
                <a href="{reset_link}" style="color: #3b82f6; word-break: break-all;">{reset_link}</a>
            </p>
            
            <hr style="margin: 30px 0; border: none; border-top: 1px solid #e5e7eb;">
            <p style="font-size: 12px; color: #6b7280; text-align: center;">
                Ekinci Analiz - Premium Futbol Analiz Platformu<br>
                E-posta: <a href="mailto:ekincianaliz@gmail.com">ekincianaliz@gmail.com</a>
            </p>
        </div>
    </body>
    </html>
    """
    
    return send_email(to=to_email, subject=subject, body=body, html=True)


def send_payment_approved_email(to_email: str, premium_until: str) -> bool:
    """Ödeme onaylandı emaili gönder"""
    subject = "✅ Premium Üyeliğiniz Aktif - Ekinci Analiz"
    
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background: #f3f4f6; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px;">
            <h2 style="color: #22c55e;">✅ Ödemeniz Onaylandı!</h2>
            <p>Harika haber! Premium üyelik ödemeniz onaylandı. 🎉</p>
            
            <div style="background: #d1fae5; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #22c55e;">
                <h3 style="color: #065f46; margin-top: 0;">⭐ Premium Üyelik Aktif</h3>
                <p style="color: #065f46; margin: 0;">
                    <strong>📅 Geçerlilik:</strong> {premium_until} tarihine kadar<br>
                    <strong>✨ Durum:</strong> Tüm özellikler aktif
                </p>
            </div>
            
            <div style="background: #eff6ff; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #1e40af; margin-top: 0;">🎯 Premium Avantajlarınız</h3>
                <ul style="color: #1e3a8a; margin: 0; padding-left: 20px;">
                    <li>CL-5 Büyük Lig-Portekiz-Hollanda-Brezilya ve Championship Tüm Maçları</li>
                    <li>Günlük en iyi bahis önerileri</li>
                    <li>Gelişmiş istatistik analizleri</li>
                    <li>7/24 güncel maç verileri</li>
                </ul>
            </div>
            
            <p style="text-align: center; margin: 30px 0;">
                <a href="https://ekincianaliz.com/dashboard" 
                   style="background: #3b82f6; color: white; padding: 14px 28px; 
                          text-decoration: none; border-radius: 8px; display: inline-block; 
                          font-weight: bold;">
                    🏠 Dashboard'a Git
                </a>
            </p>
            
            <p style="color: #16a34a; font-weight: bold; text-align: center;">
                İyi tahminler! ⚽
            </p>
            
            <hr style="margin: 30px 0; border: none; border-top: 1px solid #e5e7eb;">
            <p style="font-size: 12px; color: #6b7280; text-align: center;">
                Ekinci Analiz - Premium Futbol Analiz Platformu<br>
                E-posta: <a href="mailto:ekincianaliz@gmail.com">ekincianaliz@gmail.com</a>
            </p>
        </div>
    </body>
    </html>
    """
    
    return send_email(to=to_email, subject=subject, body=body, html=True)


def send_payment_rejected_email(to_email: str, payment_ref: str, amount: float, reason: str = "") -> bool:
    """Ödeme reddedildi emaili gönder"""
    subject = "❌ Ödeme Bildirimi - Ekinci Analiz"
    
    rejection_reason = reason if reason else "Dekont kontrolünde uyumsuzluk tespit edildi"
    
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
                <strong>❌ Ret Nedeni:</strong> {rejection_reason}
            </div>
            
            <div style="background: #fef3c7; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <h3 style="color: #92400e; margin-bottom: 10px;">ℹ️ Ne Yapmalısınız?</h3>
                <ul style="color: #92400e; margin: 0; padding-left: 20px;">
                    <li>Ödeme dekontunuzu kontrol edin</li>
                    <li>Doğru tutarı gönderdiğinizden emin olun</li>
                    <li>Dekont fotoğrafının net olduğundan emin olun</li>
                    <li>Açıklama kısmına referans kodunuzu yazdığınızdan emin olun</li>
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
            <p style="font-size: 12px; color: #6b7280; text-align: center;">
                Ekinci Analiz - Premium Futbol Analiz Platformu<br>
                E-posta: <a href="mailto:ekincianaliz@gmail.com">ekincianaliz@gmail.com</a>
            </p>
        </div>
    </body>
    </html>
    """
    
    return send_email(to=to_email, subject=subject, body=body, html=True)


# Test fonksiyonu
if __name__ == "__main__":
    print("📧 Sender.py - Email Test")
    if RESEND_API_KEY:
        print("✅ RESEND_API_KEY tanımlı")
    else:
        print("❌ RESEND_API_KEY tanımlı değil!")
