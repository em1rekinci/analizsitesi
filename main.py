from fastapi import FastAPI, Request, Cookie
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import requests, time, os
from datetime import datetime, timedelta, timezone, date
from collections import defaultdict

from cache_manager import CacheManager
from user_manager import UserManager
from payment_manager import PaymentManager

# =====================
# APP
# =====================
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# =====================
# CONFIG
# =====================
API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_KEY}
TR_TZ = timezone(timedelta(hours=3))

cache_manager = CacheManager()
user_manager = UserManager()
payment_manager = PaymentManager()

TEAM_CACHE = {}  # RAM

# =====================
# SAFE REQUEST
# =====================
def safe_request(url, params=None):
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(20)
    except:
        pass
    return {}

# =====================
# TEAM STATS
# =====================
def get_team_stats(team_id):
    if team_id in TEAM_CACHE:
        return TEAM_CACHE[team_id]

    data = safe_request(
        f"{BASE_URL}/teams/{team_id}/matches",
        {"limit": 10, "status": "FINISHED"}
    ).get("matches", [])

    g_for = g_against = over25 = kg = fh15 = 0

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
        if tg + og >= 3: over25 += 1
        if tg > 0 and og > 0: kg += 1
        if ht and ht["home"] + ht["away"] >= 2: fh15 += 1

    total = len(data) or 1
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
# FETCH ALL MATCHES (1 KERE)
# =====================
def fetch_all_matches():
    grouped = defaultdict(list)
    picks = []
    today = date.today().isoformat()

    competitions = {
        "Premier League": "PL",
        "La Liga": "PD",
        "Serie A": "SA",
        "Bundesliga": "BL1",
        "Ligue 1": "FL1"
    }

    for league, code in competitions.items():
        data = safe_request(
            f"{BASE_URL}/competitions/{code}/matches",
            {"dateFrom": today, "dateTo": today}
        )

        for m in data.get("matches", []):
            dt = datetime.fromisoformat(
                m["utcDate"].replace("Z", "+00:00")
            ).astimezone(TR_TZ)

            m["time"] = dt.strftime("%H:%M")
            m["league"] = league
            grouped[league].append(m)

    cache_manager.save_teams_cache({str(k): v for k, v in TEAM_CACHE.items()})
    cache_manager.save_matches_cache(grouped, picks)

# =====================
# DASHBOARD
# =====================
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, session_id: str = Cookie(None)):
    user = user_manager.verify_session(session_id) if session_id else None
    is_premium = user["is_premium"] if user else False

    cached = cache_manager.get_matches_cache()

    # 🔥 CACHE YOKSA → İLK GİRİŞ → API ÇEK
    if not cached:
        fetch_all_matches()
        cached = cache_manager.get_matches_cache()

        if not cached:
            return HTMLResponse("<h1>Veriler hazırlanıyor, 10-20 sn sonra yenileyin</h1>")

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "matches": cached["matches"],
            "picks": cached.get("picks", []),
            "user": user,
            "is_premium": is_premium
        }
    )

# =====================
# STARTUP
# =====================
@app.on_event("startup")
async def startup():
    teams = cache_manager.get_teams_cache()
    TEAM_CACHE.update({int(k): v for k, v in teams.items()})
