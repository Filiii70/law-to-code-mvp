# app.py — Law-to-Code MVP (DCL + CLEARANCE + Storage)
from __future__ import annotations

import os
import json
import hashlib
from uuid import uuid4
from datetime import datetime, timezone
from typing import Generator

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from sqlalchemy import create_engine, text, String
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Text as SA_Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB

# ---------- Config ----------
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is niet ingesteld (Render → Environment).")
API_KEY = os.getenv("API_KEY")  # optioneel

# ---------- DB ----------
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

class Proof(Base):
    __tablename__ = "proofs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    rule_text: Mapped[str] = mapped_column(SA_Text)
    input_data: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB)
    hash_hex: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(SA_Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

Base.metadata.create_all(bind=engine)

def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- App ----------
app = FastAPI(
    title="Law-to-Code MVP",
    version="0.3.1",
    description=(
        "MVP voor DCL + CLEARANCE + Storage.\n\n"
        "Flow: POST /clearance/check ➜ automatisch opslaan (incl. description/meta) ➜ "
        "GET /proofs en GET /proofs/{id}."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# ---------- API-key middleware (alleen voor POST als API_KEY gezet is) ----------
@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    if API_KEY and request.method.upper() == "POST":
        provided = request.headers.get("x-api-key")
        if not provided or provided != API_KEY:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

# ---------- Schemas ----------
class ClearanceIn(BaseModel):
    rule: str = Field(..., description="Eenvoudige regel, bv. 'age >= 18'")
    data: dict = Field(..., description="Inputdata die wordt geëvalueerd")
    description: str | None = Field(default=None, description="Optioneel: tekstuele omschrijving")
    meta: dict | None = Field(default=None, description="Optioneel: extra metadata (JSON)")

class ProofOut(BaseModel):
    id: str
    created_at: datetime
    rule_text: str
    input_data: dict
    result: dict
    hash_hex: str
    description: str | None = None
    meta: dict | None = None

class ProofListOut(BaseModel):
    items: list[ProofOut]
    total: int

# ---------- Mini UI ----------
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

# ---------- Health ----------
@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "db": "down", "detail": str(e)})

# ---------- Evaluator (demo) ----------
_ALLOWED = [">=", "<=", ">", "<", "==", "!="]

def evaluate_rule(rule: str, data: dict) -> dict:
    op = next((o for o in _ALLOWED if o in rule), None)
    if not op:
        return {"passed": False, "log": [f"Unsupported rule: {rule}"]}
    left, right = [s.strip() for s in rule.split(op, 1)]
    if left not in data:
        return {"passed": False, "log": [f"Missing field in data: {left}"]}
    left_val = data[left]
    rv = right
    try:
        if isinstance(left_val, (int, float)) and right.replace(".", "", 1).lstrip("-").isdigit():
            rv = float(right) if "." in right else int(right)
    except Exception:
        pass
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

def persist_proof(db, rule_text: str, input_data: dict, result: dict, hash_hex: str,
                  description: str | None = None, meta: dict | None = None) -> str:
    obj = Proof(
        rule_text=rule_text,
        input_data=input_data,
        result=result,
        hash_hex=hash_hex,
        description=description,
        meta=meta,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj.id

# ---------- Endpoints ----------
@app.post("/clearance/check", description="Evalueer data tegen een regel en bewaar als proof (met optionele description/meta).")
def clearance_check(payload: ClearanceIn, db=Depends(get_db)):
    result = evaluate_rule(payload.rule, payload.data)
    to_hash = {"rule": payload.rule, "data": payload.data, "result": result}
    hash_hex = hashlib.sha256(json.dumps(to_hash, sort_keys=True).encode("utf-8")).hexdigest()
    proof_id = persist_proof(
        db,
        rule_text=payload.rule,
        input_data=payload.data,
        result=result,
        hash_hex=hash_hex,
        description=payload.description,
        meta=payload.meta,
    )
    return {"status": "ok", "result": result, "hash": hash_hex, "proof_id": proof_id}

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
            description=r.description,
            meta=r.meta,
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
        description=r.description,
        meta=r.meta,
    )

# Let op: GEEN uvicorn.run(...) hier. Render start de app zelf via het Start Command.
app", host="0.0.0.0", port=8000, reload=True)
