# ============================================================
# Law-to-Code MVP — DCL + CLEARANCE + Storage (PostgreSQL)
# ============================================================
# Routes:
#   GET /                : mini UI/hello
#   GET /docs            : Swagger UI
#   GET /health          : DB healthcheck
#   POST /dcl/parse      : parse rule-text → JSON schema
#   POST /clearance/check: evaluate + persist proof
#   GET /proofs          : list proofs (paginated)
#   GET /proofs/{id}     : get single proof
#
# Env vars:
#   DATABASE_URL = postgresql://USER:PASS@HOST:PORT/DB
#   API_KEY      = optional; when set, POST routes require header: x-api-key
# ============================================================

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import hashlib, os, json, logging

# ------------------------------------------------------------
# Setup
# ------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Law-to-Code MVP — DCL + CLEARANCE + Storage")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------
# Database
# ------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lawtocode.db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
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

# ------------------------------------------------------------
# Models
# ------------------------------------------------------------
class RuleInput(BaseModel):
    rule: str
    data: dict

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def check_api_key(request: Request):
    api_key_env = os.getenv("API_KEY")
    if api_key_env:
        header_key = request.headers.get("x-api-key")
        if header_key != api_key_env:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

def evaluate_rule(rule: str, data: dict):
    try:
        result = eval(rule, {}, data)
        return bool(result)
    except Exception:
        return False

def hash_proof(rule: str, data: dict, result: bool):
    content = f"{rule}|{json.dumps(data, sort_keys=True)}|{result}"
    return hashlib.sha256(content.encode()).hexdigest()

# ------------------------------------------------------------
# Routes
# ------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    html = '''
    <html>
        <body style="font-family:Arial; margin:40px;">
            <h1>Law-to-Code MVP</h1>
            <p>DCL + CLEARANCE + Storage</p>
            <p><a href="/docs">Open Swagger UI</a></p>
        </body>
    </html>
    '''
    return HTMLResponse(content=html)

@app.get("/health")
def health_check():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}

@app.post("/dcl/parse")
def parse_rule(input: RuleInput):
    # ultra-simplified parser
    rule = input.rule.strip()
    return {"parsed_rule": {"expression": rule, "fields": list(input.data.keys())}}

@app.post("/clearance/check")
def clearance_check(input: RuleInput, request: Request):
    check_api_key(request)
    session = SessionLocal()
    try:
        result = evaluate_rule(input.rule, input.data)
        hash_value = hash_proof(input.rule, input.data, result)
        proof = Proof(
            rule=input.rule,
            data=json.dumps(input.data),
            result=str(result),
            hash=hash_value,
        )
        session.add(proof)
        session.commit()
        return {"result": result, "hash": hash_value, "id": proof.id}
    finally:
        session.close()

@app.get("/proofs")
def list_proofs():
    session = SessionLocal()
    try:
        proofs = session.query(Proof).all()
        return [
            {
                "id": p.id,
                "rule": p.rule,
                "result": p.result,
                "hash": p.hash,
                "timestamp": p.timestamp.isoformat(),
            }
            for p in proofs
        ]
    finally:
        session.close()

@app.get("/proofs/{proof_id}")
def get_proof(proof_id: int):
    session = SessionLocal()
    try:
        proof = session.query(Proof).filter(Proof.id == proof_id).first()
        if not proof:
            raise HTTPException(status_code=404, detail="Proof not found")
        return {
            "id": proof.id,
            "rule": proof.rule,
            "data": json.loads(proof.data),
            "result": proof.result,
            "hash": proof.hash,
            "timestamp": proof.timestamp.isoformat(),
        }
    finally:
        session.close()

# ------------------------------------------------------------
# Run (for local dev)
# ------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
