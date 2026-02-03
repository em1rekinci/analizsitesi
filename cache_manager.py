import json
import os
from datetime import date, datetime
from pathlib import Path

class CacheManager:
    """Günlük maç ve takım istatistiklerini yöneten cache sistemi"""
    
    def __init__(self, cache_dir="cache_data"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.today = str(date.today())
        
        # Cache dosya yolları
        self.matches_file = self.cache_dir / f"matches_{self.today}.json"
        self.teams_file = self.cache_dir / f"teams_{self.today}.json"
        
    def _is_cache_valid(self, filepath):
        """Cache dosyasının bugüne ait olup olmadığını kontrol et"""
        if not filepath.exists():
            return False
            
        # Dosya adından tarihi çıkar
        filename = filepath.stem  # matches_2025-02-03
        file_date = filename.split('_')[-1]
        
        return file_date == self.today
    
    def get_matches_cache(self):
        """Maçları cache'den oku"""
        if self._is_cache_valid(self.matches_file):
            try:
                with open(self.matches_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"✅ Cache'den {len(data.get('matches', {}))} lig verisi yüklendi")
                    return data
            except Exception as e:
                print(f"⚠️ Cache okuma hatası: {e}")
                return None
        return None
    
    def save_matches_cache(self, matches_data, picks_data):
        """Maçları ve picks'i cache'e kaydet"""
        try:
            cache_data = {
                "date": self.today,
                "timestamp": datetime.now().isoformat(),
                "matches": matches_data,
                "picks": picks_data
            }
            
            with open(self.matches_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            print(f"💾 Cache kaydedildi: {len(matches_data)} lig")
            
            # Eski cache dosyalarını temizle
            self._cleanup_old_caches()
            
        except Exception as e:
            print(f"⚠️ Cache kaydetme hatası: {e}")
    
    def get_teams_cache(self):
        """Takım istatistiklerini cache'den oku"""
        if self._is_cache_valid(self.teams_file):
            try:
                with open(self.teams_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"✅ {len(data)} takım istatistiği cache'den yüklendi")
                    return data
            except Exception as e:
                print(f"⚠️ Takım cache okuma hatası: {e}")
                return {}
        return {}
    
    def save_teams_cache(self, teams_dict):
        """Takım istatistiklerini cache'e kaydet"""
        try:
            with open(self.teams_file, 'w', encoding='utf-8') as f:
                json.dump(teams_dict, f, ensure_ascii=False, indent=2)
            
            print(f"💾 {len(teams_dict)} takım istatistiği kaydedildi")
            
        except Exception as e:
            print(f"⚠️ Takım cache kaydetme hatası: {e}")
    
    def _cleanup_old_caches(self):
        """Eski günlere ait cache dosyalarını sil"""
        try:
            for file in self.cache_dir.glob("*.json"):
                if not self._is_cache_valid(file):
                    file.unlink()
                    print(f"🗑️ Eski cache silindi: {file.name}")
        except Exception as e:
            print(f"⚠️ Cache temizleme hatası: {e}")
    
    def clear_all_cache(self):
        """Tüm cache'i temizle (debug amaçlı)"""
        for file in self.cache_dir.glob("*.json"):
            file.unlink()
        print("🗑️ Tüm cache temizlendi")
