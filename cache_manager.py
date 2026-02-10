import json
from datetime import date, datetime
from pathlib import Path


class CacheManager:
    def __init__(self, cache_dir="cache_data"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def _today(self):
        return date.today().isoformat()

    def _matches_file(self):
        return self.cache_dir / f"matches_{self._today()}.json"

    def _teams_file(self):
        return self.cache_dir / f"teams_{self._today()}.json"

    # =====================
    # MATCH CACHE
    # =====================
    def get_matches_cache(self):
        file = self._matches_file()
        if not file.exists():
            return None
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return None

    def save_matches_cache(self, matches, picks, coupons=None):
        """✅ Güncellenmiş - coupons parametresi eklendi"""
        data = {
            "date": self._today(),
            "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "matches": matches,
            "picks": picks,
            "coupons": coupons or {"daily": [], "high_odds": [], "super_odds": []}
        }
        with open(self._matches_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.cleanup_old()

    # =====================
    # TEAM CACHE
    # =====================
    def get_teams_cache(self):
        file = self._teams_file()
        if not file.exists():
            return {}
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def save_teams_cache(self, teams: dict):
        with open(self._teams_file(), "w", encoding="utf-8") as f:
            json.dump(teams, f, ensure_ascii=False, indent=2)

    # =====================
    # CLEANUP
    # =====================
    def cleanup_old(self):
        today = self._today()
        for f in self.cache_dir.glob("*.json"):
            if today not in f.name:
                f.unlink()
