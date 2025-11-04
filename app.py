from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, text
from sqlalchemy.orm import sessionmaker, declarative_base
import hashlib, os, json, logging

# ------------------------------------------------------------
# App & CORS
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

# ------------------------------------------------------------
# Models
# ------------------------------------------------------------
class RuleInput(BaseModel):
    rule: str
    data: dict

# ------------------------------------------------------------
# API-key dependency (Swagger toont x-api-key veld automatisch)
# ------------------------------------------------------------
def require_api_key(x_api_key: str | None = Header(default=None, convert_underscores=False)):
    expected = os.getenv("API_KEY")
    if expected:
        if not x_api_key or x_api_key != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return None

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def evaluate_rule(rule: str, data: dict) -> bool:
    try:
        return bool(eval(rule, {"__builtins__": {}}, data))
    except Exception:
        return False

def hash_proof(rule: str, data: dict, result: bool) -> str:
    content = f"{rule}|{json.dumps(data, sort_keys=True)}|{result}"
    return hashlib.sha256(content.encode()).hexdigest()

# ------------------------------------------------------------
# Routes
# ------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    html = (
        "<!doctype html>\n"
        "<html>\n"
        "  <body style='font-family:Arial; margin:40px;'>\n"
        "    <h1>Law-to-Code MVP</h1>\n"
        "    <p>DCL + CLEARANCE + Storage</p>\n"
        "    <p><a href='/docs'>Open Swagger UI</a></p>\n"
        "  </body>\n"
        "</html>\n"
    )
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
def parse_rule(input: RuleInput, _: None = Depends(require_api_key)):
    rule = input.rule.strip()
    return {"parsed_rule": {"expression": rule, "fields": list(input.data.keys())}}

@app.post("/clearance/check")
def clearance_check(input: RuleInput, _: None = Depends(require_api_key)):
    session = SessionLocal()
    try:
        result = evaluate_rule(input.rule, input.data)
        h = hash_proof(input.rule, input.data, result)
        session.add(Proof(rule=input.rule, data=json.dumps(input.data), result=str(result), hash=h))
        session.commit()
        return {"result": result, "hash": h, "id": session.query(Proof).order_by(Proof.id.desc()).first().id}
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

# ------------------------------------------------------------
# Local run (ignored on Render, safe to keep)
# ------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
