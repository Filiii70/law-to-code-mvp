"""
Law-to-Code MVP — DCL + CLEARANCE + Storage (PostgreSQL)

Routes:
GET /                : mini UI/hello
GET /docs            : Swagger UI
GET /health          : DB healthcheck
POST /dcl/parse      : parse rule-text → JSON schema
POST /clearance/check: evaluate + persist proof
GET /proofs          : list proofs (paginated)
GET /proofs/{id}     : get single proof

Env:
DATABASE_URL = postgresql://USER:PASS@HOST:PORT/DB
API_KEY      = optional; when set, POST routes require header: x-api-key
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
import os
import logging
import hashlib
import json
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ============================================================
# INITIAL SETUP
# ============================================================

app = FastAPI(title="Law-to-Code MVP", version="1.0")

# Database setup --------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL) if DATABASE_URL else None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None
Base = declarative_base()


class Proof(Base):
    __tablename__ = "proofs"
    id = Column(Integer, primary_key=True, index=True)
    rule = Column(Text)
    data = Column(Text)
    result = Column(String(10))
    proof_hash = Column(String(64))
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))


if engine:
    Base.metadata.create_all(bind=engine)

# ============================================================
# SECURITY: API-KEY CHECK
# ============================================================

API_KEY = os.getenv("API_KEY")
logging.warning(f"Loaded API_KEY from env: {repr(API_KEY)}")


@app.middleware("http")
async def check_api_key(request: Request, call_next):
    """
    Middleware die elke /clearance-route controleert op een geldige API-key.
    """
    if request.url.path.startswith("/clearance"):
        key = request.headers.get("x-api-key")
        logging.warning(f"Incoming x-api-key header: {repr(key)}")

        if not API_KEY:
            return JSONResponse(
                status_code=500,
                content={"detail": "Server misconfigured: no API_KEY in env"}
            )

        if not key or key.strip() != API_KEY.strip():
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"}
            )

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
      <body style='font-family: sans-serif;'>
        <h2>✅ Law-to-Code MVP – DCL + CLEARANCE</h2>
        <form method='post' action='/clearance/check'>
          Rule: <input name='rule' value='age >= 18'><br><br>
          Data (JSON): <input name='data' value='{"age":20}'><br><br>
          <button type='submit'>Test rule</button>
        </form>
      </body>
    </html>
    """


@app.get("/health")
async def health_check():
    """Eenvoudige healthcheck + DB-test."""
    if not engine:
        return {"status": "ok", "db": "not configured"}
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
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
# CLEARANCE CHECK
# ============================================================

@app.post("/clearance/check")
async def clearance_check(request: RuleRequest):
    """Evalueert data tegen regel en bewaart het resultaat als bewijs."""
    rule_text = request.rule
    data = request.data

    try:
        result = eval(rule_text, {}, data)
        proof_data = {
            "rule": rule_text,
            "data": json.dumps(data),
            "result": str(result),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        proof_json = json.dumps(proof_data, sort_keys=True)
        proof_hash = hashlib.sha256(proof_json.encode()).hexdigest()

        if SessionLocal:
            db = SessionLocal()
            new_proof = Proof(
                rule=rule_text,
                data=json.dumps(data),
                result=str(result),
                proof_hash=proof_hash
            )
            db.add(new_proof)
            db.commit()
            db.close()

        return {"result": result, "proof_hash": proof_hash}

    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


# ============================================================
# PROOF STORAGE
# ============================================================

@app.get("/proofs")
async def list_proofs():
    """Lijst met opgeslagen bewijzen (optioneel paginated)."""
    if not SessionLocal:
        return {"error": "Database not configured"}
    db = SessionLocal()
    proofs = db.query(Proof).all()
    db.close()
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


@app.get("/proofs/{proof_id}")
async def get_proof(proof_id: int):
    """Haalt één bewijs op via ID."""
    if not SessionLocal:
        return {"error": "Database not configured"}
    db = SessionLocal()
    proof = db.query(Proof).filter(Proof.id == proof_id).first()
    db.close()
    if proof:
        return {
            "id": proof.id,
            "rule": proof.rule,
            "data": json.loads(proof.data),
            "result": proof.result,
            "proof_hash": proof.proof_hash,
            "timestamp": proof.timestamp.isoformat()
        }
    return JSONResponse(status_code=404, content={"detail": "Proof not found"})


# ============================================================
# RUN LOCALLY (for development)
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
