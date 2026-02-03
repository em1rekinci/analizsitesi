from fastapi import FastAPI, Request, Form, Cookie, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import requests, time, os
from datetime import datetime, timedelta, timezone, date
from collections import defaultdict
from cache_manager import CacheManager
from user_manager import UserManager
from payment_manager import PaymentManager

import os
from fastapi.staticfiles import StaticFiles

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

# Admin şifresi (değiştirin!)
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
    "Championship": "ELC"
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
    "DED": 0.98
}

# =====================
# HELPER: GET USER FROM COOKIE
# =====================
def get_current_user(session_id: str = None):
    """Cookie'den kullanıcıyı al"""
    if not session_id:
        return None
    return user_manager.verify_session(session_id)

# =====================
# SAFE REQUEST
# =====================
def safe_request(url, params=None, max_retries=3):
    """API isteği gönder, timeout ve rate limit durumunda yeniden dene"""
    
    for attempt in range(max_retries):
        try:
            print(f"📡 API isteği (deneme {attempt + 1}/{max_retries}): {url}")
            
            r = requests.get(
                url, 
                headers=HEADERS, 
                params=params, 
                timeout=30
            )
            
            if r.status_code == 429:
                print("⚠️ Rate limit! 20 saniye bekleniyor...")
                time.sleep(20)
                continue
                
            if r.status_code != 200:
                print(f"⚠️ API Hatası: {r.status_code}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                return {}
                
            print(f"✅ API isteği başarılı")
            return r.json()
            
        except requests.exceptions.Timeout:
            print(f"⏱️ Timeout! Deneme {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(10)
                continue
            return {}
                
        except requests.exceptions.ConnectionError as e:
            print(f"🔌 Bağlantı hatası: {e}")
            if attempt < max_retries - 1:
                time.sleep(10)
                continue
            return {}
                
        except Exception as e:
            print(f"❌ Beklenmeyen hata: {e}")
            return {}
    
    return {}

# =====================
# TEAM STATS
# =====================
def get_team_stats(team_id):
    """Takım istatistiklerini getir"""
    
    if team_id in TEAM_CACHE:
        return TEAM_CACHE[team_id]
    
    teams_cache = cache_manager.get_teams_cache()
    team_id_str = str(team_id)
    
    if team_id_str in teams_cache:
        TEAM_CACHE[team_id] = teams_cache[team_id_str]
        return TEAM_CACHE[team_id]
    
    print(f"🌐 API'den takım çekiliyor: {team_id}")
    matches = safe_request(
        f"{BASE_URL}/teams/{team_id}/matches",
        {"limit": 10, "status": "FINISHED"}
    ).get("matches", [])

    g_for = g_against = over25 = kg = fh15 = 0

    for m in matches:
        ft = m["score"]["fullTime"]
        ht = m["score"].get("halfTime")
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
        if ht and ht["home"] is not None:
            if ht["home"] + ht["away"] >= 2:
                fh15 += 1

    total = len(matches) or 1

    stats = {
        "avg_scored": round(g_for / total, 2),
        "avg_conceded": round(g_against / total, 2),
        "over25": round(over25 / total * 100, 2),
        "kg": round(kg / total * 100, 2),
        "fh15": round(fh15 / total * 100, 2)
    }

    TEAM_CACHE[team_id] = stats
    return stats

# =====================
# PERCENT ENGINE
# =====================
def clamp(x, low=5, high=95):
    return max(low, min(high, x))

def ms_probs(hs, as_):
    diff = hs["avg_scored"] - as_["avg_scored"]
    raw = 50 + diff * 9
    ms1 = clamp(raw)
    ms2 = clamp(100 - raw)
    ms0 = clamp(100 - (ms1 + ms2), 8, 30)

    t = ms1 + ms0 + ms2
    return {
        "MS1": round(ms1 / t * 100, 2),
        "MS0": round(ms0 / t * 100, 2),
        "MS2": round(ms2 / t * 100, 2)
    }

def over_probs(hs, as_):
    base = (hs["over25"] + as_["over25"]) / 2
    adj = abs(hs["avg_scored"] - as_["avg_scored"]) * 4
    o = clamp(base + adj, 10, 85)
    return {"O25": round(o, 2)}

def kg_probs(hs, as_):
    gap = abs(hs["avg_scored"] - as_["avg_scored"])
    base = (hs["kg"] + as_["kg"]) / 2
    o = clamp(base - gap * 6, 10, 75)
    return {"KG": round(o, 2)}

def fh_probs(hs, as_):
    o = clamp((hs["fh15"] + as_["fh15"]) / 2, 5, 80)
    return {"FH15": round(o, 2)}

# =====================
# MARKETS
# =====================
def build_markets(match, picks, league_code):
    hs = get_team_stats(match["homeTeam"]["id"])
    as_ = get_team_stats(match["awayTeam"]["id"])

    ms = ms_probs(hs, as_)
    over = over_probs(hs, as_)
    kg = kg_probs(hs, as_)
    fh = fh_probs(hs, as_)

    all_markets = {**ms, **over, **kg}
    best_key, best_val = max(all_markets.items(), key=lambda x: x[1])

    weighted = min(best_val * LEAGUE_WEIGHT.get(league_code, 1.0), 95)

    if weighted >= 65:
        picks.append({
            "match": f"{match['homeTeam']['name']} - {match['awayTeam']['name']}",
            "market": best_key,
            "value": round(weighted, 2)
        })

    all_markets["FH15"] = fh["FH15"]
    all_markets["best"] = best_key
    all_markets["best_value"] = round(weighted, 2)

    return all_markets

# =====================
# FETCH ALL MATCHES
# =====================
def fetch_all_matches():
    """Tüm liglerin bugünkü maçlarını API'den çek"""
    print("🔄 Günlük veri güncelleniyor...")
    
    grouped = defaultdict(list)
    picks = []
    today = date.today().isoformat()
    all_matches = []

    for league, code in COMPETITIONS.items():
        print(f"📡 {league} çekiliyor...")
        data = safe_request(
            f"{BASE_URL}/competitions/{code}/matches",
            {"dateFrom": today, "dateTo": today}
        )

        if not data:
            print(f"⚠️ {league} için veri alınamadı, atlanıyor...")
            continue

        for m in data.get("matches", []):
            try:
                dt = datetime.fromisoformat(
                    m["utcDate"].replace("Z", "+00:00")
                ).astimezone(TR_TZ)

                m["time"] = dt.strftime("%H:%M")
                m["markets"] = build_markets(m, picks, code)
                m["league"] = league
                all_matches.append(m)
            except Exception as e:
                print(f"⚠️ Maç işleme hatası: {e}")
                continue

    # FREE / PREMIUM LOGIC
    total = len(all_matches)
    
    if total == 0:
        print("⚠️ Hiç maç bulunamadı!")
        return grouped, picks
    
    free_limit = 3 if total >= 10 else 2

    all_matches.sort(key=lambda x: x["markets"]["best_value"], reverse=True)
    free_set = {
        f'{m["homeTeam"]["name"]}-{m["awayTeam"]["name"]}'
        for m in all_matches[:free_limit]
    }

    for m in all_matches:
        key = f'{m["homeTeam"]["name"]}-{m["awayTeam"]["name"]}'
        m["is_free"] = key in free_set
        grouped[m["league"]].append(m)
    
    # Cache'e kaydet
    try:
        cache_manager.save_teams_cache({str(k): v for k, v in TEAM_CACHE.items()})
        picks_sorted = sorted(picks, key=lambda x: x["value"], reverse=True)
        cache_manager.save_matches_cache(dict(grouped), picks_sorted)
        print("✅ Veri başarıyla güncellendi ve cache'lendi!")
    except Exception as e:
        print(f"⚠️ Cache kaydetme hatası: {e}")
    
    return grouped, sorted(picks, key=lambda x: x["value"], reverse=True)

# =====================
# DASHBOARD (PUBLIC)
# =====================
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, session_id: str = Cookie(None)):
    # Kullanıcı kontrolü
    user = get_current_user(session_id)
    is_premium = user["is_premium"] if user else False
    
    # 1. Önce cache'den dene
    try:
        cached_data = cache_manager.get_matches_cache()
        
        if cached_data:
            print("✅ Cache'den yüklendi")
            return templates.TemplateResponse(
                "dashboard.html",
                {
                    "request": request,
                    "matches": cached_data["matches"],
                    "picks": cached_data["picks"],
                    "is_premium": is_premium,
                    "user": user
                }
            )
    except Exception as e:
        print(f"⚠️ Cache okuma hatası: {e}")
    
    # 2. Cache yoksa API'den çek
    try:
        print("🔄 API'den veri çekiliyor...")
        matches, picks = fetch_all_matches()
        
        if not matches:
            raise Exception("API'den veri alınamadı")
        
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "matches": matches,
                "picks": picks,
                "is_premium": is_premium,
                "user": user
            }
        )
        
    except Exception as e:
        print(f"❌ Dashboard hatası: {e}")
        return HTMLResponse(content="<h1>Geçici hata</h1>", status_code=503)

# =====================
# ACCOUNT PAGE
# =====================
@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, session_id: str = Cookie(None)):
    user = get_current_user(session_id)
    
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Premium kalan gün hesapla
    days_left = 0
    if user["is_premium"] and user["premium_until"]:
        try:
            premium_date = datetime.fromisoformat(user["premium_until"])
            days_left = (premium_date - datetime.now()).days
        except:
            days_left = 0
    
    return templates.TemplateResponse(
        "account.html",
        {
            "request": request,
            "user": user,
            "days_left": max(0, days_left)
        }
    )

# =====================
# REGISTER (GET)
# =====================
@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, session_id: str = Cookie(None)):
    # Zaten giriş yapmışsa ödeme sayfasına yönlendir
    user = get_current_user(session_id)
    if user:
        return RedirectResponse(url="/payment", status_code=303)
    
    return templates.TemplateResponse("register.html", {"request": request})

# =====================
# REGISTER (POST)
# =====================
@app.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...)
):
    if password != password2:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Şifreler eşleşmiyor"}
        )
    
    if len(password) < 6:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Şifre en az 6 karakter olmalı"}
        )
    
    # Kullanıcı oluştur
    result = user_manager.register_user(email, password)
    
    if not result["success"]:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": result["error"]}
        )
    
    # Başarılı - giriş yap
    login_result = user_manager.login_user(email, password)
    
    if login_result["success"]:
        response = templates.TemplateResponse(
            "register.html",
            {"request": request, "success": True}
        )
        response.set_cookie(key="session_id", value=login_result["session_id"], httponly=True)
        return response
    
    return templates.TemplateResponse(
        "register.html",
        {"request": request, "error": "Kayıt başarılı ama giriş yapılamadı"}
    )

# =====================
# LOGIN (GET)
# =====================
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login_page.html", {"request": request})

# =====================
# LOGIN (POST)
# =====================
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

# =====================
# LOGOUT
# =====================
@app.get("/logout")
def logout(session_id: str = Cookie(None)):
    if session_id:
        user_manager.delete_session(session_id)
    
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.delete_cookie("session_id")
    return response

# =====================
# PAYMENT PAGE (Havale/EFT)
# =====================
@app.get("/payment", response_class=HTMLResponse)
def payment_page(request: Request, session_id: str = Cookie(None)):
    user = get_current_user(session_id)
    
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Referans kodu oluştur
    payment_ref = payment_manager.generate_payment_ref(user["user_id"])
    
    return templates.TemplateResponse(
        "payment_havale.html",
        {
            "request": request,
            "user_email": user["email"],
            "payment_ref": payment_ref
        }
    )

# =====================
# SUBMIT PAYMENT (Dekont Yükle)
# =====================
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
    
    # Dosya boyutu kontrolü (5MB)
    if receipt.size > 5 * 1024 * 1024:
        return JSONResponse({"success": False, "error": "Dosya çok büyük (max 5MB)"})
    
    # Ödeme kaydı oluştur
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

# =====================
# PAYMENT PENDING PAGE
# =====================
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

# =====================
# ADMIN PANEL
# =====================
@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, admin_password: str = None):
    # Basit şifre kontrolü (gerçek projede daha güvenli olmalı)
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
    
    # İstatistikler
    user_stats = user_manager.get_user_stats()
    payment_stats = payment_manager.get_payment_stats()
    
    stats = {**user_stats, **payment_stats}
    
    # Bekleyen ve onaylanan ödemeler
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

# =====================
# ADMIN: APPROVE PAYMENT
# =====================
@app.post("/admin/approve-payment/{payment_id}")
async def admin_approve_payment(payment_id: int):
    # Ödemeyi onayla
    result = payment_manager.approve_payment(payment_id)
    
    if not result["success"]:
        return JSONResponse({"success": False, "error": result["error"]})
    
    # Kullanıcıyı premium yap
    user_id = result["user_id"]
    user_manager.activate_premium(user_id, months=1)
    
    return JSONResponse({"success": True})

# =====================
# ADMIN: REJECT PAYMENT
# =====================
@app.post("/admin/reject-payment/{payment_id}")
async def admin_reject_payment(payment_id: int, request: Request):
    body = await request.json()
    reason = body.get("reason", "")
    
    result = payment_manager.reject_payment(payment_id, reason)
    return JSONResponse(result)

# =====================
# REFRESH
# =====================
@app.get("/refresh", response_class=HTMLResponse)
def refresh_data(request: Request, session_id: str = Cookie(None)):
    user = get_current_user(session_id)
    is_premium = user["is_premium"] if user else False
    
    try:
        matches, picks = fetch_all_matches()
        
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "matches": matches,
                "picks": picks,
                "is_premium": is_premium,
                "user": user
            }
        )
    except Exception as e:
        return HTMLResponse(f"<h1>Hata:</h1><pre>{str(e)}</pre>")

# =====================
# HEALTH
# =====================
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

# =====================
# STARTUP
# =====================
@app.on_event("startup")
async def startup_event():
    print("🚀 Uygulama başlatılıyor...")
    
    try:
        teams_cache = cache_manager.get_teams_cache()
        TEAM_CACHE.update({int(k): v for k, v in teams_cache.items()})
    except Exception as e:
        print(f"⚠️ Startup cache yükleme hatası: {e}")
    
    print(f"✅ Başlangıç tamamlandı")
