import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Database URL'i al (Railway environment variable'dan)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # Fallback: SQLite (local development için)
    DATABASE_URL = "sqlite:///./users.db"
    print("⚠️  PostgreSQL bulunamadı, SQLite kullanılıyor")
else:
    print(f"✅ PostgreSQL bağlanıyor...")

# Engine oluştur
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_connection():
    """Database connection al"""
    return engine.connect()

def init_db():
    """Tabloları oluştur"""
    try:
        with engine.connect() as conn:
            # Users tablosu
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_premium INTEGER DEFAULT 0,
                    premium_until TEXT,
                    lifetime_premium INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TEXT
                )
            """))
            
            # Sessions tablosu
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            
            # Payments tablosu
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    email TEXT NOT NULL,
                    payment_ref TEXT UNIQUE NOT NULL,
                    amount REAL NOT NULL,
                    sender_name TEXT NOT NULL,
                    receipt_path TEXT NOT NULL,
                    notes TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TEXT,
                    approved_by TEXT,
                    rejection_reason TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            
            conn.commit()
        
        print("✅ Database tabloları hazır!")
        return True
    except Exception as e:
        print(f"⚠️  Database init hatası: {e}")
        return False
