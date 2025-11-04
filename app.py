# ============================================================
# Law-to-Code MVP — DCL + CLEARANCE + Storage (PostgreSQL)
# ============================================================

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, text
from sqlalchemy.orm import sessionmaker, declarative_base
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
# API-key dependency (toont x-api-key in Swagger)
# ------------------------------------------------------------
def require_api_key(x_api_key: str | None = Header(default=None, convert_underscores=False)):
    expected = os.getenv("API_KEY")
    if expected:
        if not x_api_key or x_api_key != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    # Als er geen API_KEY is gezet, is alles openbaar.
    return None

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def evaluate_rule(rule: str, data: dict) -> bool:
    try:
        # sandboxed eval: geen builtins
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
    html = '''
    <!doctype html>
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
def parse_rule(input: RuleInput, _: None = Depends(require_api_key)):
    # ultra-simple parser
    rule = input.rule.strip()
    return {"parsed_rule": {"expression": rule, "fields": list(input.data.keys())}}

@app.post("/clearance/check")
def clearance_check(input: RuleInput, _: None = Depends(require_api_key)):
    session = SessionLocal()
    try:
        result = evaluate_rule(input.rule, input.data)
        h = hash_proof(input.rule, input.data, result)
app:app", host="0.0.0.0", port=8000)
