"""
Law-to-Code MVP — DCL + CLEARANCE + Storage (PostgreSQL)

Routes:
GET  /                 : mini UI/hello
GET  /docs             : Swagger UI
GET  /health           : DB healthcheck
POST /dcl/parse        : parse rule-text → JSON schema
POST /clearance/check  : evaluate + persist proof
GET  /proofs           : list proofs (paginated)
GET  /proofs/{id}      : get single proof

Env (Render):
DATABASE_URL = postgresql://USER:PASS@HOST:PORT/DB
API_KEY      = optional; when set, POST /clearance/check requires header: x-api-key
"""

from __future__ import annotations

import os
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel

from sqlalchemy import create_engine, text, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(title="Law-to-Code MVP", version="1.0")

# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # helpt bij slapende/verbroken connecties
    future=True
) if DATABASE_URL else None

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True) if engine else None
Base = declarative_base()

class Proof(Base):
    __tablename__ = "proofs"
    id = Column(Integer, primary_key=True, index=True)
    rule = Column(Text, nullable=False)
    data = Column(Text, nullable=False)
    result = Column(String(10), nullable=False)
    proof_hash = Column(String(64), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

if engine:
    Base.metadata.create_all(bind=engine)

# ============================================================
# SECURITY: API-KEY (OPTIONEEL)
# ============================================================

API_KEY: Optional[str] = os.getenv("API_KEY")
logging.warning(f"API_KEY present: {bool(API_KEY)}")

@app.middleware("http")
async def optional_api_key_for_clearance(request: Request, call_next):
    """
    Vereist x-api-key op /clearance/check ALLEEN als API_KEY is gezet in de omgeving.
    Zo vermijden we 500/401 verwarring tijdens testen.
    """
    if API_KEY and request.url.path.startswith("/clearance"):
        key = request.headers.get("x-api-key", "")
        if key.strip() != API_KEY.strip():
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

# ============================================================
# MODELS
# ============================================================

class RuleRequest(BaseModel):
    rule: str
    data: dict

# ============================================================
# BASIC ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home():
    """Mini UI om snel te testen."""
    return """
    <html>
      <head><title>Law-to-Code MVP</title></head>
      <body style='font-family: sans-serif; max-width: 720px; margin: 2rem auto;'>
        <h2>✅ Law-to-Code MVP – DCL + CLEARANCE</h2>
        <p>Probeer via <a href="/docs" target="_blank">/docs</a> de endpoints.</p>
        <p><b>Tip:</b> Voor POST /clearance/check: header <code>x-api-key: &lt;jouw key&gt;</code> is alleen nodig als je in Render <code>API_KEY</code> hebt gezet.</p>
      </body>
    </html>
    """

@app.get("/health")
async def health_check():
    """Eenvoudige health + DB-test, compatibel met SQLAlchemy 2.x."""
    if not engine:
        return {"status": "ok", "db": "not configured"}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}

# ============================================================
# DCL PARSER
# ============================================================

@app.post("/dcl/parse")
async def parse_rule(request: RuleRequest):
    """Zeer eenvoudige parser die een regel omzet naar een JSON-schema."""
    try:
        rule_text = request.rule
        schema = {"type": "comparison", "expression": rule_text}
        return {"parsed": schema}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

# ============================================================
# CLEARANCE CHECK (MVP)
# ============================================================

@app.post("/clearance/check")
async def clearance_check(request: RuleRequest):
    """
    Evalueert data tegen regel en bewaart het resultaat als bewijs.
    LET OP: 'eval' is enkel voor MVP/demo (geen onveilige invoer gebruiken in productie).
    """
    rule_text = request.rule
    data = request.data

    try:
        # Minimalistische evaluatie: bv. rule = "age >= 18", data={"age": 20}
        result = bool(eval(rule_text, {}, data))  # MVP, niet voor productie

        proof_data = {
            "rule": rule_text,
            "data": json.dumps(data, sort_keys=True),
            "result": str(result),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        proof_hash = hashlib.sha256(json.dumps(proof_data, sort_keys=True).encode()).hexdigest()

        if SessionLocal:
            db = SessionLocal()
            try:
                new_proof = Proof(
                    rule=rule_text,
                    data=json.dumps(data, sort_keys=True),
                    result=str(result),
                    proof_hash=proof_hash,
                )
                db.add(new_proof)
                db.commit()
            finally:
                db.close()

        return {"result": result, "proof_hash": proof_hash}

    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

# ============================================================
# PROOF STORAGE
# ============================================================

@app.get("/proofs")
async def list_proofs():
    """Lijst met opgeslagen bewijzen."""
    if not SessionLocal:
        return {"error": "Database not configured"}
    db = SessionLocal()
    try:
        proofs = db.query(Proof).order_by(Proof.id.desc()).all()
        return [
            {
                "id": p.id,
                "rule": p.rule,
                "data": json.loads(p.data),
                "result": p.result,
                "proof_hash": p.proof_hash,
                "timestamp": p.timestamp.isoformat()
            }
            for p in proofs
        ]
    finally:
        db.close()

@app.get("/proofs/{proof_id}")
async def get_proof(proof_id: int):
    """Haalt één bewijs op via ID."""
    if not SessionLocal:
        return {"error": "Database not configured"}
    db = SessionLocal()
    try:
        p = db.query(Proof).filter(Proof.id == proof_id).first()
        if not p:
            return JSONResponse(status_code=404, content={"detail": "Proof not found"})
        return {
            "id": p.id,
            "rule": p.rule,
            "data": json.loads(p.data),
            "result": p.result,
            "proof_hash": p.proof_hash,
            "timestamp": p.timestamp.isoformat()
        }
    finally:
        db.close()

# ============================================================
# RUN LOCALLY (development)
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
