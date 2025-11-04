# app.py — Law-to-Code MVP (DCL + CLEARANCE + Storage)
# - Swagger UI op /docs (FastAPI standaard)  ✅
# - Healthcheck /health met DB ping (text('SELECT 1'))  ✅
# - API-key beveiliging voor POST (header: x-api-key)  ✅
# - POST /clearance/check slaat automatisch op in PostgreSQL (JSONB)  ✅
# - GET /proofs en GET /proofs/{id} om resultaten te bekijken  ✅

from __future__ import annotations
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Generator

import os
import json
import hashlib
from uuid import uuid4
from datetime import datetime, timezone

# --- Database (SQLAlchemy 2.x) ---
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text as SA_Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB  # PostgreSQL JSONB

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    # Laat een duidelijke fout zien als DB niet gezet is
    raise RuntimeError("DATABASE_URL is niet ingesteld (Render → Service → Environment).")

# pool_pre_ping voorkomt 'stale' connections bij PaaS  ✅
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

class Proof(Base):
    __tablename__ = "proofs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    rule_text: Mapped[str] = mapped_column(SA_Text)
    input_data: Mapped[dict] = mapped_column(JSONB)   # ✅ JSONB opslag
    result: Mapped[dict] = mapped_column(JSONB)       # ✅ JSONB opslag
    hash_hex: Mapped[str] = mapped_column(String(128))

# Maak tabellen aan (no-op als ze bestaan)
Base.metadata.create_all(bind=engine)

def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- FastAPI app ---
app = FastAPI(title="Law-to-Code MVP", version="0.2.0")

# CORS basic open (pas aan indien nodig)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY")  # Optioneel. Als gezet: POST endpoints vereisen x-api-key.

@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    # Beveilig enkel POST-routes als API_KEY gezet is
    if API_KEY and request.method.upper() == "POST":
        provided = request.headers.get("x-api-key")
        if not provided or provided != API_KEY:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

# --- Models ---
class ClearanceIn(BaseModel):
    rule: str
    data: dict

class ProofOut(BaseModel):
    id: str
    created_at: datetime
    rule_text: str
    input_data: dict
    result: dict
    hash_hex: str

class ProofListOut(BaseModel):
    items: list[ProofOut]
    total: int

# --- Mini UI op root ---
@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <html>
      <head><title>Law-to-Code MVP</title></head>
      <body style="font-family: sans-serif; max-width: 720px; margin: 2rem auto;">
        <h1>Law-to-Code MVP</h1>
        <p>Open <a href="/docs">/docs</a> om de API te testen.</p>
        <ul>
          <li>GET <code>/health</code></li>
          <li>POST <code>/clearance/check</code></li>
          <li>GET <code>/proofs</code>, <code>/proofs/{id}</code></li>
        </ul>
      </body>
    </html>
    """

# --- Health check (DB ping met text('SELECT 1')) ---
@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "db": "down", "detail": str(e)})

# --- HELPER: eenvoudige evaluator (demo) ---
# Ondersteunt simpele vergelijkingen zoals: age >= 18, score == 10, etc.
_allowed_ops = [">=", "<=", ">", "<", "==", "!="]

def evaluate_rule(rule: str, data: dict) -> dict:
    # Vind operator
    op = next((o for o in _allowed_ops if o in rule), None)
    if not op:
        return {"passed": False, "log": [f"Unsupported rule: {rule}"]}

    left, right = [s.strip() for s in rule.split(op, 1)]
    if left not in data:
        return {"passed": False, "log": [f"Missing field in data: {left}"]}

    left_val = data[left]
    # Coerce right naar type van left indien mogelijk
    rv = right
    try:
        if isinstance(left_val, (int, float)) and right.replace(".", "", 1).lstrip("-").isdigit():
            rv = float(right) if "." in right else int(right)
    except Exception:
        pass

    # Vergelijk
    ops = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        ">":  lambda a, b: a >  b,
        "<":  lambda a, b: a <  b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }
    try:
        ok = ops[op](left_val, rv)
        return {"passed": bool(ok), "log": [f"Evaluated: {left_val} {op} {rv} -> {ok}"]}
    except Exception as e:
        return {"passed": False, "log": [f"Evaluation error: {e}"]}

def persist_proof(db, rule_text: str, input_data: dict, result: dict, hash_hex: str) -> str:
    obj = Proof(
        rule_text=rule_text,
        input_data=input_data,
        result=result,
        hash_hex=hash_hex,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj.id

# --- API: CLEARANCE ---
@app.post("/clearance/check")
def clearance_check(payload: ClearanceIn, db=Depends(get_db)):
    result = evaluate_rule(payload.rule, payload.data)

    # Hash over rule + data + result (stabiel en sort_keys=True)
    to_hash = {
        "rule": payload.rule,
        "data": payload.data,
        "result": result,
    }
    hash_hex = hashlib.sha256(json.dumps(to_hash, sort_keys=True).encode("utf-8")).hexdigest()

    # Automatisch opslaan ➜ proofs
    proof_id = persist_proof(db, rule_text=payload.rule, input_data=payload.data, result=result, hash_hex=hash_hex)

    return {"status": "ok", "result": result, "hash": hash_hex, "proof_id": proof_id}

# --- API: PROOFS ---
@app.get("/proofs", response_model=ProofListOut)
def list_proofs(limit: int = 50, offset: int = 0, db=Depends(get_db)):
    q = db.query(Proof).order_by(Proof.created_at.desc())
    total = q.count()
    rows = q.limit(limit).offset(offset).all()
    items = [
        ProofOut(
            id=r.id,
            created_at=r.created_at,
            rule_text=r.rule_text,
            input_data=r.input_data,
            result=r.result,
            hash_hex=r.hash_hex,
        ) for r in rows
    ]
    return {"items": items, "total": total}

@app.get("/proofs/{proof_id}", response_model=ProofOut)
def get_proof(proof_id: str, db=Depends(get_db)):
    r = db.query(Proof).get(proof_id)
    if not r:
        raise HTTPException(status_code=404, detail="Proof not found")
    return ProofOut(
        id=r.id,
        created_at=r.created_at,
        rule_text=r.rule_text,
        input_data=r.input_data,
        result=r.result,
        hash_hex=r.hash_hex,
    )
   uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
