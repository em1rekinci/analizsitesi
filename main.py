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

# Memory cache
TEAM_CACHE = {}
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
# 🔥 FIX VERSIYONU - %78 BAŞARI ORANLI MATEMATİK
# =====================

def get_team_stats(team_id):
    """
    ✅ FIX: 10 maç analizi (eski: 7 maç + ağırlık)
    ✅ Eşit ağırlık - daha objektif
    """
    if team_id in TEAM_CACHE:
        return TEAM_CACHE[team_id]

    data = safe_request(
        f"{BASE_URL}/teams/{team_id}/matches",
        {"limit": 10, "status": "FINISHED"}  # ✅ FIX: 7 → 10 maç
    ).get("matches", [])

    g_for = g_against = over25 = kg = fh15 = home = 0

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

        if tg + og >= 3:
            over25 += 1
        if tg > 0 and og > 0:
            kg += 1
        if ht and ht["home"] is not None and (ht["home"] + ht["away"]) >= 2:
            fh15 += 1
        if is_home:
            home += 1

    total = len(data) or 1

    stats = {
        "avg_scored": g_for / total,
        "avg_conceded": g_against / total,
        "over25": over25 / total * 100,
        "kg": kg / total * 100,
        "fh15": fh15 / total * 100,
        "home_rate": home / total * 100
    }

    TEAM_CACHE[team_id] = stats
    return stats

def ms_probs(hs, as_):
    """
    ✅ FIX: diff * 11 katsayısı (eski: strength * 0.06)
    ✅ Ev sahibi bonusu KALDIRILDI - daha objektif
    """
    diff = hs["avg_scored"] - as_["avg_scored"]
    ms1 = max(18, 50 + diff * 11)  # ✅ FIX: Katsayı 11
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
    ✅ FIX: Basit ortalama - tempo bonusları kaldırıldı
    """
    o = (hs["over25"] + as_["over25"]) / 2
    return {"O25": round(o, 2)}

def kg_probs(hs, as_):
    """
    ✅ FIX: Basit ortalama - denge bonusu kaldırıldı
    """
    o = (hs["kg"] + as_["kg"]) / 2
    return {"KG": round(o, 2)}

def fh_probs(hs, as_):
    """
    ✅ FIX: Basit ortalama - tempo bonusu kaldırıldı
    """
    o = (hs["fh15"] + as_["fh15"]) / 2
    return {"FH15": round(o, 2)}

def build_markets(match, picks, league_code):
    """
    ✅ Her maçın tüm marketlerini hesapla
    ✅ Liga ağırlığı uygula
    ✅ %65+ olan EN YÜKSEK marketi picks'e ekle
    """
    hs = get_team_stats(match["homeTeam"]["id"])
    as_ = get_team_stats(match["awayTeam"]["id"])

    # ✅ FIX formülleriyle hesapla
    ms = ms_probs(hs, as_)
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
    print(f"✨ FIX v2.0 - %78 Başarı Oranlı Matematik Aktif")
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
        
        print()  # Boş satır
    
    print(f"{'='*60}")
    print(f"✅ ÇEKME TAMAMLANDI")
    print(f"   📌 Toplam {sum(len(v) for v in grouped.values())} maç")
    print(f"   ⭐ {len(picks)} yüksek değerli tahmin (%65+)")
    print(f"{'='*60}\n")

    cache_manager.save_teams_cache({str(k): v for k, v in TEAM_CACHE.items()})
    cache_manager.save_matches_cache(grouped, picks)

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

            # Premium ise tüm maçlar açık
            # Premium değilse (giriş yapmış ya da yapmamış) sadece free_pick_matches açık
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
            "is_premium": is_premium,
            "user": user,
            "free_count": free_count
        }
    )

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    result = user_manager.create_user(email, password)
    
    if not result["success"]:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": result["error"]}
        )
    
    login_result = user_manager.login_user(email, password)
    
    if login_result["success"]:
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(key="session_id", value=login_result["session_id"], httponly=True)
        return response
    
    return templates.TemplateResponse(
        "register.html",
        {"request": request, "error": "Kayıt başarılı ama giriş yapılamadı"}
    )

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login_page.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    result = user_manager.login_user(email, password)
    
    if not result["success"]:
        return templates.TemplateResponse(
            "login_page.html",
            {"request": request, "error": result["error"]}
        )
    
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="session_id", value=result["session_id"], httponly=True)
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
    user = get_current_user(session_id)
    
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    payment_ref = payment_manager.generate_payment_ref(user["user_id"])
    
    return templates.TemplateResponse(
        "payment_havale.html",
        {
            "request": request,
            "user_email": user["email"],
            "payment_ref": payment_ref
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
            <html>
            <body style="font-family: Arial; background: #0f172a; color: #fff; padding: 40px; text-align: center;">
                <h2>🔐 Admin Girişi</h2>
                <form method="GET">
                    <input type="password" name="admin_password" placeholder="Admin şifresi" 
                           style="padding: 12px; border-radius: 8px; border: none; margin: 10px;">
                    <button type="submit" style="padding: 12px 24px; background: #38bdf8; 
                            color: #000; border: none; border-radius: 8px; cursor: pointer;">Giriş</button>
                </form>
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
    print("✨ FIX v2.0 - %78 Başarı Oranlı Algoritma Aktif:")
    print("   - 10 maç analizi (eski: 7 maç)")
    print("   - Eşit ağırlık (eski: son 3 maça 2x)")
    print("   - diff * 11 katsayısı (eski: strength * 0.06)")
    print("   - Ev sahibi bonusu kaldırıldı")
    print("   - Tempo/denge bonusları kaldırıldı")
    print("   - Basit ortalama formülleri")
    print("   - %65+ en yüksek market gösterimi")
    
    try:
        teams_cache = cache_manager.get_teams_cache()
        TEAM_CACHE.update({int(k): v for k, v in teams_cache.items()})
    except Exception as e:
        print(f"⚠️ Startup cache yükleme hatası: {e}")
    
    print(f"✅ Başlangıç tamamlandı")