from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from pydantic import BaseModel
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, text
from sqlalchemy.orm import sessionmaker, declarative_base
import hashlib, os, json, logging

# ---------------- App ----------------
logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Law-to-Code MVP — DCL + CLEARANCE + Storage")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------- DB --------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lawtocode.db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Proof(Base):
    __tablename__ = "proofs"
    id = Column(Integer, primary_key=True, index=True)
    rule = Column(Text)
    data = Column(Text)
    result = Column(String(50))
    hash = Column(String(64))
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))

Base.metadata.create_all(bind=engine)

# ------------- Models ----------------
class RuleInput(BaseModel):
    rule: str
    data: dict

# ----------- API Key: header of ?api_key= ----------
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
api_key_query  = APIKeyQuery(name="api_key", auto_error=False)

def require_api_key(
    key_h: str | None = Depends(api_key_header),
    key_q: str | None = Depends(api_key_query),
):
    expected = os.getenv("API_KEY")
    if not expected:
        return None
    provided = key_h or key_q
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return None

# ------------- Helpers ---------------
def evaluate_rule(rule: str, data: dict) -> bool:
    try:
        # sandbox eval (zonder builtins)
        return bool(eval(rule, {"__builtins__": {}}, data))
    except Exception:
        return False

def hash_proof(rule: str, data: dict, result: bool) -> str:
    payload = f"{rule}|{json.dumps(data, sort_keys=True)}|{result}"
    return hashlib.sha256(payload.encode()).hexdigest()

# -------------- Routes ---------------
@app.get("/")
def root():
    return {"app": "Law-to-Code MVP", "docs": "/docs"}

@app.get("/health")
def health_check():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}

@app.post("/dcl/parse", dependencies=[Depends(require_api_key)])
def dcl_parse(input: RuleInput):
    rule = input.rule.strip()
    return {"parsed_rule": {"expression": rule, "fields": list(input.data.keys())}}

@app.post("/clearance/check", dependencies=[Depends(require_api_key)])
def clearance_check(input: RuleInput):
    session = SessionLocal()
    try:
        result = evaluate_rule(input.rule, input.data)
        h = hash_proof(input.rule, input.data, result)
        proof = Proof(rule=input.rule, data=json.dumps(input.data), result=str(result), hash=h)
        session.add(proof)
        session.commit()
        return {"result": result, "hash": h, "id": proof.id}
    finally:
        session.close()

@app.get("/proofs")
def list_proofs():
    session = SessionLocal()
    try:
        items = session.query(Proof).order_by(Proof.id.desc()).all()
        return [
            {
                "id": p.id,
                "rule": p.rule,
                "result": p.result,
                "hash": p.hash,
                "timestamp": p.timestamp.isoformat(),
            }
            for p in items
        ]
    finally:
        session.close()

@app.get("/proofs/{proof_id}")
def get_proof(proof_id: int):
    session = SessionLocal()
    try:
        p = session.query(Proof).filter(Proof.id == proof_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Proof not found")
        return {
            "id": p.id,
            "rule": p.rule,
            "data": json.loads(p.data),
            "result": p.result,
            "hash": p.hash,
            "timestamp": p.timestamp.isoformat(),
        }
    finally:
        session.close()
