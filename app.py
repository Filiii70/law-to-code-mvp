# app.py
"""
Law-to-Code MVP — DCL + CLEARANCE + Storage (PostgreSQL)
Routes:
  GET  /                : mini UI/hello
  GET  /docs            : Swagger
  GET  /health          : DB healthcheck
  POST /dcl/parse       : parse rule-text → JSON schema
  POST /clearance/check : evaluate + persist proof
  GET  /proofs          : list proofs (paginated)
  GET  /proofs/{id}     : get single proof

Env:
  DATABASE_URL = postgresql://USER:PASS@HOST:PORT/DB (Render Internal URL)
  API_KEY      = optional; when set, POST routes require header: x-api-key: <API_KEY>
"""

from __future__ import annotations

import os, json, re, hashlib
from datetime import datetime, timezone
from typing import Any, Optional, List, Dict
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# --- SQLAlchemy / Postgres ---
from sqlalchemy import create_engine, Column, String, DateTime, Text, JSON, Integer
from sqlalchemy import text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

DATABASE_URL = os.getenv("DATABASE_URL")
API_KEY = (os.getenv("API_KEY") or "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is required")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

class Proof(Base):
    __tablename__ = "proofs"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    rule_text = Column(Text, nullable=False)
    data = Column(JSON, nullable=False)
    result = Column(String(8), nullable=False)      # "pass" | "fail"
    hash = Column(String(64), nullable=False)       # sha256
    proof_log = Column(JSON, nullable=False)        # full structured log

Base.metadata.create_all(bind=engine)

def db() -> Session:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

def require_api_key(x_api_key: Optional[str]) -> None:
    if API_KEY and (x_api_key or "").strip() != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# --- FastAPI ---
app = FastAPI(title="Law-to-Code MVP — DCL + CLEARANCE + Storage")

# ---- DCL toy parser ----
class DCLSchema(BaseModel):
    field: str
    op: str
    value: Any

class ParseRequest(BaseModel):
    text: str = Field(..., description='e.g. "age >= 18"')

class ClearanceRequest(BaseModel):
    rule: str
    data: Dict[str, Any]

def parse_rule(text: str) -> DCLSchema:
    # minimal parser: <field> <op> <value>
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$", text)
    if not m:
        raise HTTPException(400, "Unsupported rule format. Try: age >= 18")
    field, op, raw = m.groups()
    # try to coerce numeric/bool; else string without quotes needed
    try:
        if raw.lower() in ("true", "false"):
            val: Any = raw.lower() == "true"
        else:
            val = int(raw) if raw.isdigit() else float(raw)
    except:
        val = raw.strip().strip('"').strip("'")
    return DCLSchema(field=field, op=op, value=val)

def evaluate(schema: DCLSchema, data: Dict[str, Any]) -> bool:
    if schema.field not in data:
        return False
    left = data[schema.field]
    right = schema.value
    ops = {
        "==": lambda a,b: a == b,
        "!=": lambda a,b: a != b,
        ">=": lambda a,b: a >= b,
        "<=": lambda a,b: a <= b,
        ">":  lambda a,b: a >  b,
        "<":  lambda a,b: a <  b,
    }
    return bool(ops[schema.op](left, right))

# --- UI / Health ---
@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <html><body style="font-family:system-ui;margin:2rem">
      <h2>Law-to-Code MVP</h2>
      <p>Try <code>/docs</code> for the API.</p>
    </body></html>
    """

@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True, "db": "up"}

# --- DCL / CLEARANCE ---
@app.post("/dcl/parse")
def dcl_parse(req: ParseRequest):
    schema = parse_rule(req.text)
    return schema.model_dump()

@app.post("/clearance/check")
def clearance_check(req: ClearanceRequest, x_api_key: Optional[str] = Header(default=None)):
    require_api_key(x_api_key)

    schema = parse_rule(req.rule)
    passed = evaluate(schema, req.data)

    proof_log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rule": schema.model_dump(),
        "data": req.data,
        "result": "pass" if passed else "fail",
    }
    digest = hashlib.sha256(json.dumps(proof_log, sort_keys=True).encode("utf-8")).hexdigest()

    # persist
    with SessionLocal() as s:
        p = Proof(
            rule_text=req.rule,
            data=req.data,
            result="pass" if passed else "fail",
            hash=digest,
            proof_log=proof_log,
        )
        s.add(p)
        s.commit()
        s.refresh(p)

    return {"id": p.id, "hash": digest, "result": p.result, "proof": proof_log}

# --- Retrieval ---
@app.get("/proofs")
def list_proofs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    with SessionLocal() as s:
        total = s.query(Proof).count()
        rows: List[Proof] = (
            s.query(Proof)
            .order_by(Proof.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": r.id,
                    "created_at": r.created_at,
                    "result": r.result,
                    "hash": r.hash,
                    "rule_text": r.rule_text,
                } for r in rows
            ],
        }

@app.get("/proofs/{proof_id}")
def get_proof(proof_id: str):
    with SessionLocal() as s:
        r = s.get(Proof, proof_id)
        if not r:
            raise HTTPException(404, "Not found")
        return {
            "id": r.id,
            "created_at": r.created_at,
            "result": r.result,
            "hash": r.hash,
            "rule_text": r.rule_text,
            "data": r.data,
            "proof": r.proof_log,
        }
