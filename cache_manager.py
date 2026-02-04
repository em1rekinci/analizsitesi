import json
from datetime import date, datetime
from pathlib import Path


class CacheManager:
    def __init__(self, cache_dir="cache_data"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.today = date.today().isoformat()

        self.matches_file = self.cache_dir / f"matches_{self.today}.json"
        self.teams_file = self.cache_dir / f"teams_{self.today}.json"

    # =====================
    # MATCH CACHE
    # =====================
    def get_matches_cache(self):
        if not self.matches_file.exists():
            return None
        try:
            with open(self.matches_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save_matches_cache(self, matches, picks):
        data = {
            "date": self.today,
            "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "matches": matches,
            "picks": picks,
        }
        with open(self.matches_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self._cleanup_old()

    # =====================
    # TEAM CACHE
    # =====================
    def get_teams_cache(self):
        if not self.teams_file.exists():
            return {}
        try:
            with open(self.teams_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_teams_cache(self, team_cache: dict):
        with open(self.teams_file, "w", encoding="utf-8") as f:
            json.dump(team_cache, f, ensure_ascii=False, indent=2)

    # =====================
    # CLEANUP
    # =====================
    def _cleanup_old(self):
        for file in self.cache_dir.glob("*.json"):
            if self.today not in file.name:
                file.unlink()
