import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Haalt de DATABASE_URL uit de environment (Render)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# Maak de engine naar PostgreSQL (Render-db law-to-code-db)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

# Session-fabriek
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Basisclass voor alle tabellen
Base = declarative_base()
