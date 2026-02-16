
from fastapi import FastAPI, Request, Form, Cookie, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import requests, time, os
from datetime import datetime, timedelta, timezone, date
from collections import defaultdict
from cache_manager import CacheManager
from user_manager import UserManager
from payment_manager import PaymentManager
from password_reset_manager import PasswordResetManager  # ✅ YENİ
from sqlalchemy import text
from db_manager import get_connection
import statistics

app = FastAPI()

os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# =====================
# APP
# =====================
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# =====================
# CONFIG
# =====================
API_KEY = os.getenv("FOOTBALL_API_KEY", "350b0fe840aa431d8e199a328ac5cd34")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_KEY}

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "34emr256.")

# Managers
cache_manager = CacheManager()
user_manager = UserManager()
payment_manager = PaymentManager()
reset_manager = PasswordResetManager()

# Memory cache
TEAM_CACHE = {}
TEAM_STRENGTH_CACHE = {}
TR_TZ = timezone(timedelta(hours=3))

# =====================
# LIGLER
# =====================
COMPETITIONS = {
    "Champions League": "CL",
    "Premier League": "PL",
    "La Liga": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
    "Eredivisie": "DED",
    "Primeira Liga": "PPL",
    "Championship": "ELC",
    "Brezilya Serie A": "BSA"
}

LEAGUE_WEIGHT = {
    "CL": 1.08,
    "PL": 1.05,
    "BL1": 1.04,
    "SA": 1.04,
    "PD": 1.03,
    "FL1": 1.02,
    "ELC": 1.01,
    "PPL": 1.00,
    "DED": 0.98,
    "BSA": 1.00 
}

def get_current_user(session_id: str = None):
    if not session_id:
        return None
    return user_manager.verify_session(session_id)

def safe_request(url, params=None, retries=2):
    """
    API request - hata loglama ve retry ile
    """
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            
            if r.status_code == 200:
                return r.json()
            
            elif r.status_code == 429:
                wait_time = 20 * (attempt + 1)
                print(f"⚠️ Rate limit (429): {url}")
                print(f"   💤 {wait_time} saniye bekleniyor...")
                time.sleep(wait_time)
                continue
            
            elif r.status_code == 403:
                print(f"🚫 Erişim engellendi (403): {url}")
                print(f"   ⚠️ API key kontrolü gerekiyor!")
                return {}
            
            elif r.status_code == 404:
                print(f"❌ Bulunamadı (404): {url}")
                return {}
            
            elif r.status_code >= 500:
                print(f"⚠️ Sunucu hatası ({r.status_code}): {url}")
                if attempt < retries - 1:
                    time.sleep(5)
                    continue
                return {}
            
            else:
                print(f"⚠️ Bilinmeyen hata ({r.status_code}): {url}")
                return {}
                
        except requests.exceptions.Timeout:
            print(f"⏱️ Timeout: {url} - Deneme {attempt + 1}/{retries}")
            if attempt < retries - 1:
                time.sleep(3)
                continue
            return {}
            
        except requests.exceptions.ConnectionError:
            print(f"🔌 Bağlantı hatası: {url} - Deneme {attempt + 1}/{retries}")
            if attempt < retries - 1:
                time.sleep(5)
                continue
            return {}
            
        except Exception as e:
            print(f"❌ Beklenmeyen hata: {url}")
            print(f"   Hata detayı: {str(e)}")
            return {}
    
    print(f"💥 Tüm denemeler başarısız: {url}")
    return {}

# =====================
# 🔥 YENİ v3.0 - %83.5 BAŞARI HEDEFLİ MATEMATİK
# =====================

def get_team_stats(team_id):
    """
    ✅ 3. ÖZELLİK: EV/DEPLASMAN FORMU AYRIMI
    Son 10 maçı ev ve deplasman olarak ayırır
    """
    if team_id in TEAM_CACHE:
        return TEAM_CACHE[team_id]

    data = safe_request(
        f"{BASE_URL}/teams/{team_id}/matches",
        {"limit": 10, "status": "FINISHED"}
    ).get("matches", [])

    # Genel istatistikler
    g_for = g_against = over25 = kg = fh15 = home_count = 0
    
    # Ev/Deplasman ayrımı
    home_goals = []
    away_goals = []
    home_conceded = []
    away_conceded = []

    for m in data:
        ft = m["score"]["fullTime"]
        ht = m["score"]["halfTime"]
        if ft["home"] is None:
            continue

        is_home = m["homeTeam"]["id"] == team_id
        tg = ft["home"] if is_home else ft["away"]
        og = ft["away"] if is_home else ft["home"]

        g_for += tg
        g_against += og

        # ✅ Ev/Deplasman ayrımı
        if is_home:
            home_goals.append(tg)
            home_conceded.append(og)
            home_count += 1
        else:
            away_goals.append(tg)
            away_conceded.append(og)

        if tg + og >= 3:
            over25 += 1
        if tg > 0 and og > 0:
            kg += 1
        if ht and ht["home"] is not None and (ht["home"] + ht["away"]) >= 2:
            fh15 += 1

    total = len(data) or 1

    stats = {
        "avg_scored": g_for / total,
        "avg_conceded": g_against / total,
        "over25": over25 / total * 100,
        "kg": kg / total * 100,
        "fh15": fh15 / total * 100,
        "home_rate": home_count / total * 100,
        
        # ✅ Ev/Deplasman ayrımı
        "home_avg_scored": sum(home_goals) / max(len(home_goals), 1),
        "home_avg_conceded": sum(home_conceded) / max(len(home_conceded), 1),
        "away_avg_scored": sum(away_goals) / max(len(away_goals), 1),
        "away_avg_conceded": sum(away_conceded) / max(len(away_conceded), 1),
        
        # ✅ 2. ÖZELLİK: Form tutarlılığı için gol listesi
        "goals_list": home_goals + away_goals
    }

    TEAM_CACHE[team_id] = stats
    return stats

def get_team_strength(team_id):
    """
    ✅ 1. ÖZELLİK: TAKIM GÜCÜ HESAPLAMA (0-100)
    Liverpool-City gibi maçlarda saçmalığı önler
    """
    if team_id in TEAM_STRENGTH_CACHE:
        return TEAM_STRENGTH_CACHE[team_id]
    
    stats = get_team_stats(team_id)
    
    # Güç = Atak + Savunma dengesi
    attack_power = stats["avg_scored"] * 25
    defense_power = (3 - stats["avg_conceded"]) * 25
    
    strength = attack_power + defense_power
    strength = max(0, min(100, strength))
    
    TEAM_STRENGTH_CACHE[team_id] = strength
    return strength

def check_consistency(goals_list):
    """
    ✅ 2. ÖZELLİK: FORM TUTARLILIĞI
    Standart sapma ile tutarlılığı ölçer
    
    Örnek:
    [3, 2, 3, 2, 3] → std_dev = 0.5 → Tutarlı = 1.0
    [5, 0, 6, 0, 4] → std_dev = 2.8 → Tutarsız = 0.6
    """
    if len(goals_list) < 3:
        return 1.0  # Yeterli veri yok, nötr
    
    try:
        std_dev = statistics.stdev(goals_list)
        mean = statistics.mean(goals_list)
        
        # Varyasyon katsayısı (CV)
        if mean > 0:
            cv = std_dev / mean
        else:
            cv = 0
        
        # CV düşükse tutarlı, yüksekse tutarsız
        if cv < 0.3:
            return 1.15  # Çok tutarlı → +15% güven
        elif cv < 0.5:
            return 1.05  # Tutarlı → +5% güven
        elif cv < 0.8:
            return 1.0   # Normal
        elif cv < 1.2:
            return 0.92  # Tutarsız → -8% güven
        else:
            return 0.80  # Çok tutarsız → -20% güven
    except:
        return 1.0

def ms_probs(home_id, away_id, hs, as_, is_home_match=True):
    """
    ✅ 1. ÖZELLİK: Rakip kalite faktörü
    ✅ 3. ÖZELLİK: Ev/Deplasman formu kullanımı
    ✅ 2. ÖZELLİK: Form tutarlılığı entegrasyonu
    """
    
    # ✅ Ev/Deplasman formu kullan
    if is_home_match:
        home_scored = hs["home_avg_scored"]
        away_scored = as_["away_avg_scored"]
    else:
        home_scored = hs["avg_scored"]
        away_scored = as_["avg_scored"]
    
    # Temel fark
    diff = home_scored - away_scored
    
    # ✅ 1. ÖZELLİK: Rakip kalite kontrolü
    away_strength = get_team_strength(away_id)
    home_strength = get_team_strength(home_id)
    
    # Deplasman takımı çok güçlüyse diff'i azalt
    if away_strength > 75:  # Top 6 seviye (City, Liverpool, Arsenal vb)
        diff *= 0.3  # %70 azalt
    elif away_strength > 65:  # Top 10 seviye
        diff *= 0.5  # %50 azalt
    elif away_strength > 55:  # Orta üst
        diff *= 0.7  # %30 azalt
    
    # Ev sahibi çok zayıfsa
    if home_strength < 40:
        diff *= 0.8
    
    # ✅ 2. ÖZELLİK: Form tutarlılığı uygula
    home_consistency = check_consistency(hs["goals_list"])
    away_consistency = check_consistency(as_["goals_list"])
    
    diff *= home_consistency
    diff *= (2 - away_consistency)  # Rakip tutarsızsa avantaj
    
    ms1 = max(18, 50 + diff * 11)
    ms2 = max(18, 50 - diff * 11)
    msx = max(12, 100 - (ms1 + ms2))
    
    t = ms1 + msx + ms2
    
    return {
        "MS1": round(ms1 / t * 100, 2),
        "MS0": round(msx / t * 100, 2),
        "MS2": round(ms2 / t * 100, 2)
    }

def over_probs(hs, as_):
    """
    ✅ 4. ÖZELLİK: OYUN TARZI UYUMU
    İki hücum takımı → Over yükselir
    İki savunma takımı → Under yükselir
    """
    base = (hs["over25"] + as_["over25"]) / 2
    
    # ✅ Oyun tarzı uyumu
    home_attack = hs["avg_scored"]
    away_attack = as_["avg_scored"]
    
    # İki takım da hücum odaklıysa
    if home_attack > 2.5 and away_attack > 2.5:
        base *= 1.15  # +15% Over bonusu
    
    # İki takım da savunma odaklıysa
    elif home_attack < 1.2 and away_attack < 1.2:
        base *= 0.80  # -20% Over (Under'a kaydir)
    
    # Bir takım çok gol atıyor, diğeri çok yiyor
    home_defense = hs["avg_conceded"]
    away_defense = as_["avg_conceded"]
    
    if (home_attack > 2.5 and away_defense > 1.8) or (away_attack > 2.5 and home_defense > 1.8):
        base *= 1.10  # +10% Over bonusu
    
    return {"O25": min(round(base, 2), 95)}

def kg_probs(hs, as_):
    """
    ✅ 4. ÖZELLİK: OYUN TARZI UYUMU
    İki hücum takımı → KG yükselir
    Bir takım çok savunmacıysa → KG düşer
    """
    base = (hs["kg"] + as_["kg"]) / 2
    
    # ✅ Oyun tarzı uyumu
    home_attack = hs["avg_scored"]
    away_attack = as_["avg_scored"]
    
    # İki takım da hücum odaklıysa
    if home_attack > 2.0 and away_attack > 2.0:
        base *= 1.12  # +12% KG bonusu
    
    # Bir takım çok savunmacıysa
    if home_attack < 1.0 or away_attack < 1.0:
        base *= 0.85  # -15% KG
    
    return {"KG": min(round(base, 2), 90)}

def fh_probs(hs, as_):
    """
    ✅ Basit ortalama - oyun tarzı etkisi az
    """
    o = (hs["fh15"] + as_["fh15"]) / 2
    return {"FH15": round(o, 2)}

def generate_coupons(picks):
    """
    ✅ YENİ MANTIK: %65 üstü tahminleri en yüksekten düşüğe sırala
    
    1️⃣ GÜNÜN KOMBİNESİ: En yüksek 3 tahmin (%65+)
    2️⃣ YÜKSEK ORAN: Sonraki 4 tahmin (%65+)
    3️⃣ SÜPER ORAN: Sonraki 5 tahmin (%65+)
    
    Tüm kuponlar %65+ tahminlerden oluşur ve yüksekten düşüğe sıralanır.
    """
    if not picks:
        return {
            "daily": [],
            "high_odds": [],
            "super_odds": []
        }
    
    # %65 ve üstü tahminleri filtrele ve en yüksekten düşüğe sırala
    filtered_picks = [p for p in picks if p['value'] >= 65]
    sorted_picks = sorted(filtered_picks, key=lambda x: x['value'], reverse=True)
    
    # 1️⃣ GÜNÜN KOMBİNESİ: İlk 3 tahmin (en yüksek değerliler)
    daily_coupon = sorted_picks[:3]
    
    # 2️⃣ YÜKSEK ORAN: Sonraki 4 tahmin
    high_odds_coupon = sorted_picks[3:7]
    
    # 3️⃣ SÜPER ORAN: Sonraki 5 tahmin
    super_odds_coupon = sorted_picks[7:12]
    
    return {
        "daily": daily_coupon,
        "high_odds": high_odds_coupon,
        "super_odds": super_odds_coupon
    }

def build_markets(match, picks, league_code):
    """
    ✅ Her maçın tüm marketlerini hesapla
    ✅ Liga ağırlığı uygula
    ✅ %65+ olan EN YÜKSEK marketi picks'e ekle
    """
    home_id = match["homeTeam"]["id"]
    away_id = match["awayTeam"]["id"]
    
    hs = get_team_stats(home_id)
    as_ = get_team_stats(away_id)

    # ✅ Yeni formüllerle hesapla
    ms = ms_probs(home_id, away_id, hs, as_, is_home_match=True)
    over = over_probs(hs, as_)
    kg = kg_probs(hs, as_)
    fh = fh_probs(hs, as_)

    # Liga ağırlığı uygula
    weight = LEAGUE_WEIGHT.get(league_code, 1.0)
    
    # Tüm piyasaları ağırlıklandır
    all_markets = {}
    for market, value in {**ms, **over, **kg, **fh}.items():
        weighted_value = min(value * weight, 95)
        all_markets[market] = round(weighted_value, 2)

    # ✅ En yüksek piyasayı bul
    best_key, best_value = max(all_markets.items(), key=lambda x: x[1])
    
    # ✅ Sadece en yüksek piyasa %65+ ise picks'e ekle
    if best_value >= 65:
        picks.append({
            "match": f"{match['homeTeam']['name']} - {match['awayTeam']['name']}",
            "market": best_key,
            "value": best_value
        })

    all_markets["best"] = best_key
    all_markets["best_value"] = best_value

    return all_markets

def fetch_all_matches():
    grouped = defaultdict(list)
    picks = []
    today = date.today().isoformat()
    
    print(f"\n{'='*60}")
    print(f"🔄 MAÇ ÇEKME BAŞLADI - {today}")
    print(f"✨ v3.0 ULTRA - %83.5 Başarı Hedefli Matematik")
    print(f"{'='*60}")
    print(f"📌 Aktif Özellikler:")
    print(f"   1️⃣ Rakip Kalite Faktörü (Liverpool-City fix)")
    print(f"   2️⃣ Form Tutarlılığı (Standart sapma)")
    print(f"   3️⃣ Ev/Deplasman Formu Ayrımı")
    print(f"   4️⃣ Oyun Tarzı Uyumu (Over/KG optimize)")
    print(f"{'='*60}\n")

    for league, code in COMPETITIONS.items():
        print(f"📊 {league} ({code}) kontrol ediliyor...")
        
        data = safe_request(
            f"{BASE_URL}/competitions/{code}/matches",
            {"dateFrom": today, "dateTo": today}
        )
        
        matches = data.get("matches", [])
        
        if not matches:
            print(f"   ℹ️ Bugün maç yok\n")
            continue
        
        print(f"   ✅ {len(matches)} maç bulundu")

        for m in matches:
            try:
                dt = datetime.fromisoformat(
                    m["utcDate"].replace("Z", "+00:00")
                ).astimezone(TR_TZ)

                m["time"] = dt.strftime("%H:%M")
                m["league"] = league
                m["markets"] = build_markets(m, picks, code)
                
                grouped[league].append(m)
                print(f"      • {m['homeTeam']['name']} - {m['awayTeam']['name']} ({m['time']})")
            except Exception as e:
                print(f"      ❌ Maç işlenirken hata: {str(e)}")
                continue
        
        print()
    
    print(f"{'='*60}")
    print(f"✅ ÇEKME TAMAMLANDI")
    print(f"   📌 Toplam {sum(len(v) for v in grouped.values())} maç")
    print(f"   ⭐ {len(picks)} yüksek değerli tahmin (%65+)")
    print(f"   🎯 Hedef Başarı: %83.5")
    print(f"{'='*60}\n")

    # ✅ YENİ: Kuponları oluştur
    coupons = generate_coupons(picks)
    print(f"🎫 KUPONLAR OLUŞTURULDU:")
    print(f"   🏆 Günün Kombinesi: {len(coupons['daily'])} maç")
    print(f"   🎯 Yüksek Oran: {len(coupons['high_odds'])} maç")
    print(f"   🔥 Süper Oran: {len(coupons['super_odds'])} maç")
    print(f"{'='*60}\n")

    cache_manager.save_teams_cache({str(k): v for k, v in TEAM_CACHE.items()})
    cache_manager.save_matches_cache(grouped, picks, coupons)  # ✅ Kuponları da kaydet

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, session_id: str = Cookie(None)):
    user = user_manager.verify_session(session_id) if session_id else None
    is_premium = user["is_premium"] if user else False

    cached = cache_manager.get_matches_cache()

    if not cached:
        fetch_all_matches()
        cached = cache_manager.get_matches_cache()
        if not cached:
            return HTMLResponse("<h1>Veriler hazırlanıyor, birkaç saniye sonra yenileyin</h1>")

    all_matches = cached.get("matches", {})
    all_picks = cached.get("picks", [])
    coupons = cached.get("coupons", {"daily": [], "high_odds": [], "super_odds": []})  # ✅ Kuponları al

    # =====================
    # FREE MAÇ MANTIĞI
    # =====================

    # toplam maç sayısı
    flat_matches = []
    for league_matches in all_matches.values():
        for m in league_matches:
            flat_matches.append(
                f"{m['homeTeam']['name']} - {m['awayTeam']['name']}"
            )

    total_matches = len(flat_matches)

    # free kullanıcıya garanti gösterilecek maç sayısı
    free_count = 3 if total_matches >= 10 else 2

    # picks varsa en iyiler
    sorted_picks = sorted(all_picks, key=lambda x: x["value"], reverse=True)
    free_pick_matches = set(p["match"] for p in sorted_picks[:free_count])

    # =====================
    # MAÇLARA FLAG EKLE
    # =====================
    for league_matches in all_matches.values():
        for match in league_matches:
            match_name = f"{match['homeTeam']['name']} - {match['awayTeam']['name']}"

            match["is_free"] = (
                is_premium
                or match_name in free_pick_matches
             )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "matches": all_matches,
            "picks": all_picks,
            "coupons": coupons,  # ✅ Kuponları template'e gönder
            "is_premium": is_premium,
            "user": user,
            "free_count": free_count
        }
    )

@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, session_id: str = Cookie(None)):
    user = get_current_user(session_id)
    
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Premium kalan gün hesapla
    days_left = 0
    if user["is_premium"] and user["premium_until"]:
        try:
            if user.get("lifetime_premium"):
                days_left = 99999  # Lifetime için çok büyük sayı
            else:
                premium_date = datetime.fromisoformat(user["premium_until"])
                days_left = max(0, (premium_date - datetime.now()).days)
        except:
            days_left = 0
    
    return templates.TemplateResponse(
        "account.html",
        {
            "request": request,
            "user": user,
            "days_left": days_left
        }
    )


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/coupons", response_class=HTMLResponse)
def coupons_page(request: Request, session_id: str = Cookie(None)):
    """
    ✅ YENİ: Hazır Kuponlar Sayfası
    """
    user = user_manager.verify_session(session_id) if session_id else None
    is_premium = user["is_premium"] if user else False
    
    cached = cache_manager.get_matches_cache()
    
    if not cached:
        return HTMLResponse("<h1>Veriler yükleniyor, lütfen birkaç saniye sonra tekrar deneyin</h1>")
    
    coupons = cached.get("coupons", {"daily": [], "high_odds": [], "super_odds": []})
    
    return templates.TemplateResponse(
        "coupons.html",
        {
            "request": request,
            "coupons": coupons,
            "is_premium": is_premium,
            "user": user
        }
    )

@app.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    redeem_code: str = Form(None)
):
    """
    ✅ DÜZELTİLDİ: 
    - confirm_password kontrolü eklendi
    - redeem_code desteği eklendi
    - register_user() fonksiyonu kullanılıyor (create_user değil)
    - Redeem kod varsa direkt dashboard, yoksa payment
    """
    
    # Validasyon
    if not email or not password:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "E-posta ve şifre gerekli"}
        )
    
    if password != confirm_password:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Şifreler eşleşmiyor"}
        )
    
    if len(password) < 6:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Şifre en az 6 karakter olmalı"}
        )
    
    # ✅ DÜZELTİLDİ: register_user() kullan (create_user değil!)
    result = user_manager.register_user(email, password, redeem_code)
    
    if not result["success"]:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": result["error"]}
        )
    
    # ✅ Kayıt başarılı - otomatik login yap
    login_result = user_manager.login_user(email, password)
    
    if not login_result["success"]:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Kayıt başarılı ama giriş yapılamadı"}
        )
    
    # ✅ Redeem kod kullanıldıysa dashboard, yoksa payment'a yönlendir
    redirect_url = "/dashboard" if result.get("has_redeem") else "/payment"
    
    response = RedirectResponse(url=redirect_url, status_code=303)
    
    # ✅ Session cookie'sini set et (30 gün)
    response.set_cookie(
        key="session_id", 
        value=login_result["session_id"], 
        httponly=True,
        max_age=30 * 24 * 60 * 60,  # 30 gün
        samesite="lax"
    )
    
    return response

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login_page.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    remember_me: str = Form(None)  # ✅ Beni hatırla checkbox (HTML'den "true" gelir)
):
    result = user_manager.login_user(email, password)
    
    if not result["success"]:
        return templates.TemplateResponse(
            "login_page.html",
            {"request": request, "error": result["error"]}
        )
    
    response = RedirectResponse(url="/dashboard", status_code=303)
    
    # ✅ Beni hatırla işaretliyse 30 gün, değilse oturum süresi (tarayıcı kapanınca siler)
    max_age = 30 * 24 * 60 * 60 if remember_me == "true" else None  # 30 gün
    
    response.set_cookie(
        key="session_id", 
        value=result["session_id"], 
        httponly=True,
        max_age=max_age,
        samesite="lax"  # Güvenlik için
    )
    return response

@app.get("/logout")
def logout(session_id: str = Cookie(None)):
    if session_id:
        user_manager.delete_session(session_id)
    
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.delete_cookie("session_id")
    return response

@app.get("/payment", response_class=HTMLResponse)
def payment_page(request: Request, session_id: str = Cookie(None)):
    """
    ✅ DÜZELTİLDİ: Session kontrolü ve user bilgisi düzgün çekiliyor
    """
    user = get_current_user(session_id)
    
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Zaten premium ise dashboard'a yönlendir
    if user.get("is_premium"):
        return RedirectResponse(url="/dashboard", status_code=303)
    
    payment_ref = payment_manager.generate_payment_ref(user["user_id"])
    
    return templates.TemplateResponse(
        "payment_havale.html",
        {
            "request": request,
            "user_email": user["email"],
            "payment_ref": payment_ref
        }
    )

@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    """Şifremi unuttum sayfası"""
    return templates.TemplateResponse("forgot_password.html", {"request": request})

@app.post("/forgot-password")
async def forgot_password(
    request: Request,
    email: str = Form(...)
):
    """Şifre sıfırlama linki gönder"""
    try:
        # Kullanıcıyı bul
        with get_connection() as conn:
            result = conn.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": email}
            ).fetchone()

        if not result:
            return templates.TemplateResponse(
                "forgot_password.html",
                {"request": request, "error": "Bu e-posta adresi kayıtlı değil"}
            )

        user_id = result[0]

        # Token oluştur
        ip_address = request.client.host
        token = reset_manager.create_token(user_id, ip_address)

        # Reset linki oluştur
        reset_link = f"{request.base_url}reset-password?token={token}"

        # Email gönder
        try:
            reset_manager.send_reset_email(email, reset_link)
            print(f"✅ Reset email gönderildi: {email}")
        except Exception as e:
            print(f"⚠️ Email gönderilemedi: {e}")
            print(f"🔑 Manuel Reset link: {reset_link}")

        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "success": f"Şifre sıfırlama linki {email} adresinize gönderildi! Email kutunuzu kontrol edin."
            }
        )

    except Exception as e:
        print(f"❌ Forgot password hatası: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "forgot_password.html",
            {"request": request, "error": "Bir hata oluştu, lütfen tekrar deneyin"}
        )

@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str = None):
    """Şifre sıfırlama sayfası"""
    try:
        print(f"🔍 Reset password GET request - Token: {token[:20] if token else 'None'}...")
        
        if not token:
            print(f"❌ Token parametresi yok")
            return RedirectResponse(url="/login", status_code=303)
        
        # Token'ı doğrula
        print(f"🔍 Token doğrulanıyor...")
        verify_result = reset_manager.verify_token(token)
        
        print(f"✅ Verify result: {verify_result}")
        
        if not verify_result["valid"]:
            print(f"❌ Token geçersiz: {verify_result.get('error')}")
            return templates.TemplateResponse(
                "reset_password.html",
                {
                    "request": request,
                    "error": verify_result["error"],
                    "token": token
                }
            )
        
        print(f"✅ Token geçerli, sayfa gösteriliyor")
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token}
        )
        
    except Exception as e:
        print(f"❌ Reset password GET hatası: {e}")
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"<h1>Hata</h1><pre>{str(e)}\n\n{traceback.format_exc()}</pre>", status_code=500)



@app.post("/reset-password")
async def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Şifreyi sıfırla"""
    try:
        print(f"🔍 Reset password POST request")
        
        if password != confirm_password:
            return templates.TemplateResponse(
                "reset_password.html",
                {
                    "request": request,
                    "error": "Şifreler eşleşmiyor",
                    "token": token
                }
            )
        
        if len(password) < 6:
            return templates.TemplateResponse(
                "reset_password.html",
                {
                    "request": request,
                    "error": "Şifre en az 6 karakter olmalı",
                    "token": token
                }
            )
        
        # Şifreyi sıfırla
        result = reset_manager.reset_password(token, password)
        
        if result["success"]:
            return templates.TemplateResponse(
                "reset_password.html",
                {
                    "request": request,
                    "success": "Şifreniz başarıyla değiştirildi! Giriş sayfasına yönlendiriliyorsunuz..."
                }
            )
        else:
            return templates.TemplateResponse(
                "reset_password.html",
                {
                    "request": request,
                    "error": result["error"],
                    "token": token
                }
            )
            
    except Exception as e:
        print(f"❌ Reset password POST hatası: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "Bir hata oluştu, lütfen tekrar deneyin",
                "token": token
            }
        )


@app.post("/submit-payment")
async def submit_payment(
    request: Request,
    session_id: str = Cookie(None),
    payment_ref: str = Form(...),
    sender_name: str = Form(...),
    amount: float = Form(...),
    notes: str = Form(""),
    receipt: UploadFile = File(...)
):
    user = get_current_user(session_id)
    
    if not user:
        return JSONResponse({"success": False, "error": "Giriş yapmanız gerekiyor"})
    
    if receipt.size > 5 * 1024 * 1024:
        return JSONResponse({"success": False, "error": "Dosya çok büyük (max 5MB)"})
    
    result = payment_manager.create_payment(
        user_id=user["user_id"],
        email=user["email"],
        amount=amount,
        sender_name=sender_name,
        receipt_file=receipt,
        notes=notes
    )
    
    if result["success"]:
        return JSONResponse({"success": True, "payment_ref": result["payment_ref"]})
    else:
        return JSONResponse({"success": False, "error": result["error"]})

@app.get("/payment-pending", response_class=HTMLResponse)
def payment_pending_page(request: Request, session_id: str = Cookie(None)):
    user = get_current_user(session_id)
    
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse(
        "payment_pending.html",
        {
            "request": request,
            "user_email": user["email"],
            "upload_time": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "payment_ref": "Kontrol ediliyor..."
        }
    )

@app.get("/admin5600", response_class=HTMLResponse)
def admin_panel(request: Request, admin_password: str = None):
    if admin_password != ADMIN_PASSWORD:
        return HTMLResponse("""
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <title>Admin Girişi - Ekinci Analiz</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            width: 100%;
            max-width: 400px;
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid #334155;
            border-radius: 16px;
            padding: 40px 30px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }
        .login-header {
            text-align: center;
            margin-bottom: 40px;
        }
        .login-header h1 {
            color: #38bdf8;
            font-size: 28px;
            margin-bottom: 8px;
        }
        .login-header p {
            color: #94a3b8;
            font-size: 14px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            color: #cbd5e1;
            font-size: 14px;
            font-weight: 500;
            margin-bottom: 8px;
        }
        .form-group input {
            width: 100%;
            padding: 14px 16px;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid #334155;
            border-radius: 8px;
            color: #e2e8f0;
            font-size: 16px;
            transition: all 0.3s;
        }
        .form-group input:focus {
            outline: none;
            border-color: #38bdf8;
            background: rgba(15, 23, 42, 0.8);
            box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.1);
        }
        .form-group input::placeholder {
            color: #64748b;
        }
        .login-btn {
            width: 100%;
            padding: 14px;
            background: #38bdf8;
            color: #0f172a;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            margin-top: 10px;
        }
        .login-btn:hover {
            background: #0ea5e9;
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(56, 189, 248, 0.2);
        }
        @media (max-width: 480px) {
            .login-container {
                padding: 30px 20px;
            }
            .login-header h1 {
                font-size: 24px;
            }
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <h1>🔒 Admin Girişi</h1>
            <p>Ekinci Analiz Yönetim Paneli</p>
        </div>
        <form method="GET">
            <div class="form-group">
                <label for="admin_password">Admin Şifresi</label>
                <input 
                    type="password" 
                    id="admin_password" 
                    name="admin_password" 
                    placeholder="Şifrenizi girin"
                    required
                    autocomplete="current-password"
                    autofocus
                >
            </div>
            <button type="submit" class="login-btn">Giriş Yap</button>
        </form>
    </div>
</body>
</html>
        """)
   
     
    user_stats = user_manager.get_user_stats()
    payment_stats = payment_manager.get_payment_stats()
    
    stats = {**user_stats, **payment_stats}
    
    pending_payments = payment_manager.get_pending_payments()
    approved_payments = payment_manager.get_approved_payments(limit=10)
    
    return templates.TemplateResponse(
        "admin_panel.html",
        {
            "request": request,
            "stats": stats,
            "pending_payments": pending_payments,
            "approved_payments": approved_payments
        }
    )

@app.post("/admin/approve-payment/{payment_id}")
async def admin_approve_payment(payment_id: int):
    result = payment_manager.approve_payment(payment_id)
    
    if not result["success"]:
        return JSONResponse({"success": False, "error": result["error"]})
    
    user_id = result["user_id"]
    user_manager.activate_premium(user_id, months=1)
    
    return JSONResponse({"success": True})

@app.post("/admin/reject-payment/{payment_id}")
async def admin_reject_payment(payment_id: int, request: Request):
    body = await request.json()
    reason = body.get("reason", "")
    
    result = payment_manager.reject_payment(payment_id, reason)
    return JSONResponse(result)

@app.get("/refresh", response_class=HTMLResponse)
def refresh_data(request: Request, session_id: str = Cookie(None)):
    user = get_current_user(session_id)
    is_premium = user["is_premium"] if user else False
    
    try:
        fetch_all_matches()
        cached = cache_manager.get_matches_cache()
        
        if not cached:
            return HTMLResponse("<h1>Veriler yüklenemedi, lütfen birkaç saniye bekleyip tekrar deneyin</h1>")
        
        # Free picks mantığı
        all_matches = cached.get("matches", {})
        all_picks = cached.get("picks", [])
        coupons = cached.get("coupons", {"daily": [], "high_odds": [], "super_odds": []})  # ✅ Kuponları al
        
        # Toplam maç sayısı
        total_matches = sum(len(matches) for matches in all_matches.values())
        
        # Free pick sayısını belirle
        free_count = 3 if total_matches >= 10 else 2
        
        # En yüksek değerli picksleri sırala
        sorted_picks = sorted(all_picks, key=lambda x: x['value'], reverse=True)
        free_pick_matches = set(p["match"] for p in sorted_picks[:free_count])
        
        # Her maça is_free flag ekle
        for league_matches in all_matches.values():
            for match in league_matches:
                match_name = f"{match['homeTeam']['name']} - {match['awayTeam']['name']}"
                match['is_free'] = (
                   is_premium
                   or match_name in free_pick_matches
                )
        
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "matches": all_matches,
                "picks": all_picks,
                "coupons": coupons,  # ✅ Kuponları template'e gönder
                "is_premium": is_premium,
                "user": user,
                "free_count": free_count,
                "free_pick_matches": free_pick_matches
            }
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"<h1>Hata:</h1><pre>{str(e)}</pre>")

@app.get("/health")
def health_check():
    try:
        cached_data = cache_manager.get_matches_cache()
        stats = user_manager.get_user_stats()
        payment_stats = payment_manager.get_payment_stats()
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "cache": {
                "status": "loaded" if cached_data else "empty",
                "date": cached_data.get("date") if cached_data else None
            },
            "users": stats,
            "payments": payment_stats
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.on_event("startup")
async def startup_event():
    print("🚀 Uygulama başlatılıyor...")
    print("=" * 60)
    print("✨ v3.0 ULTRA - %83.5 Başarı Hedefli Algoritma")
    print("=" * 60)
    print("📌 Aktif Özellikler:")
    print("   1️⃣ Rakip Kalite Faktörü")
    print("      → Liverpool-City gibi maçlarda diff azaltma")
    print("      → Güçlü rakibe karşı gerçekçi yüzdeler")
    print()
    print("   2️⃣ Form Tutarlılığı (Standart Sapma)")
    print("      → [3,2,3,2,3] = Tutarlı → +15% güven")
    print("      → [5,0,6,0,4] = Tutarsız → -20% güven")
    print()
    print("   3️⃣ Ev/Deplasman Formu Ayrımı")
    print("      → Evde: avg 3.5 gol")
    print("      → Deplasmanada: avg 2.0 gol")
    print("      → Doğru istatistik kullanımı")
    print()
    print("   4️⃣ Oyun Tarzı Uyumu")
    print("      → Hücum vs Hücum → Over +15%")
    print("      → Savunma vs Savunma → Over -20%")
    print("      → KG ve Over optimize edildi")
    print("=" * 60)
    
    try:
        teams_cache = cache_manager.get_teams_cache()
        TEAM_CACHE.update({int(k): v for k, v in teams_cache.items()})
        print(f"✅ {len(TEAM_CACHE)} takım cache'den yüklendi")
    except Exception as e:
        print(f"⚠️ Startup cache yükleme hatası: {e}")
    
    print(f"✅ Başlangıç tamamlandı - Hedef: %83.5 başarı!")
    print("=" * 60)
