"""
Law-to-Code MVP Prototype — DCL + CLEARANCE + Use-Case Storage

Routes:
- GET  /                : eenvoudige demo-UI (DCL + CLEARANCE)
- POST /dcl/parse       : law-text -> DCL schema
- POST /clearance/check : schema + data -> compliance + proof hash
- POST /usecases/submit : Use-Case Inventory formulier -> DB + hash
- GET  /admin/usecases  : JSON lijst met alle use-cases

Opmerking:
Deze versie verwacht dat er in dezelfde map een `database.py`
en een `models_usecase.py` staan met de SQLAlchemy instellingen.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Body, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session
from database import Base, engine, SessionLocal
from models_usecase import UseCase

# -------------------------------------------------
# FastAPI app
# -------------------------------------------------
app = FastAPI(title="Law-to-Code MVP: DCL + CLEARANCE + Storage")

# -------------------------------------------------
# DATABASE-SETUP
# -------------------------------------------------


# Maak tabellen aan als ze nog niet bestaan
Base.metadata.create_all(bind=engine)


def get_db():
    """Eenvoudige dependency om een DB-sessie te krijgen."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -------------------------------------------------
# DCL-MODELLEN
# -------------------------------------------------
class DCLRule(BaseModel):
    id: str
    type: str  # required | equals | max | min | in
    field: str
    value: Optional[Any] = None


class DCLSchema(BaseModel):
    law_title: str = "Untitled Law Snippet"
    rules: List[DCLRule]
    source_text: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# -------------------------------------------------
# CLEARANCE-MODELLEN
# -------------------------------------------------
class ClearanceResult(BaseModel):
    rule_id: str
    field: str
    passed: bool
    details: str


class ProofLog(BaseModel):
    law_title: str
    schema: DCLSchema
    data_checked: Dict[str, Any]
    results: List[ClearanceResult]
    overall_passed: bool
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    proof_hash: str


# -------------------------------------------------
# DCL PARSER (ULTRA-SIMPEL)
# -------------------------------------------------
"""
Ondersteunde regels (één per lijn):

  require <veld>
  equals <veld> <waarde>
  max    <veld> <getal>
  min    <veld> <getal>
  in     <veld> [a,b,c]

Voorbeeld:

  require manufacturer
  require category
  in category [electronics, furniture]
  max weight 50
"""


def auto_cast(txt: str) -> Any:
    t = txt.strip()

    if t.lower() in {"true", "false"}:
        return t.lower() == "true"

    try:
        return int(t)
    except ValueError:
        pass

    try:
        return float(t)
    except ValueError:
        pass

    if (t.startswith("'") and t.endswith("'")) or (
        t.startswith('"') and t.endswith('"')
    ):
        return t[1:-1]

    return t


def parse_rule_line(line: str, idx: int) -> Optional[DCLRule]:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None

    parts = raw.split()
    if len(parts) < 2:
        return None

    keyword = parts[0].lower()

    # require <field>
    if keyword == "require" and len(parts) >= 2:
        field = parts[1]
        return DCLRule(id=f"r{idx}", type="required", field=field)

    # equals <field> <value>
    if keyword == "equals" and len(parts) >= 3:
        field = parts[1]
        value = " ".join(parts[2:])
        casted = auto_cast(value)
        return DCLRule(id=f"r{idx}", type="equals", field=field, value=casted)

    # max <field> <number>
    if keyword == "max" and len(parts) >= 3:
        field = parts[1]
        value = auto_cast(parts[2])
        return DCLRule(id=f"r{idx}", type="max", field=field, value=value)

    # min <field> <number>
    if keyword == "min" and len(parts) >= 3:
        field = parts[1]
        value = auto_cast(parts[2])
        return DCLRule(id=f"r{idx}", type="min", field=field, value=value)

    # in <field> [a,b,c]
    if keyword == "in" and len(parts) >= 3:
        field = parts[1]
        # alles tussen [ ] pakken
        if "[" in raw and "]" in raw:
            bracket = raw[raw.find("[") : raw.rfind("]") + 1]
            try:
                items = [
                    auto_cast(x.strip())
                    for x in bracket.strip("[]").split(",")
                    if x.strip()
                ]
            except Exception:
                items = [bracket]
        else:
            items = parts[2:]
        return DCLRule(id=f"r{idx}", type="in", field=field, value=items)

    return None


# -------------------------------------------------
# CLEARANCE LOGICA
# -------------------------------------------------
def evaluate(schema: DCLSchema, data: Dict[str, Any]) -> Tuple[List[ClearanceResult], bool]:
    results: List[ClearanceResult] = []
    overall = True

    for rule in schema.rules:
        field_value = data.get(rule.field, None)

        if rule.type == "required":
            passed = rule.field in data and data[rule.field] not in (None, "")
            details = f"Field '{rule.field}' is required; present={passed}"

        elif rule.type == "equals":
            passed = field_value == rule.value
            details = f"Field '{rule.field}' must equal {rule.value!r}; actual={field_value!r}"

        elif rule.type == "max":
            try:
                passed = float(field_value) <= float(rule.value)
            except Exception:
                passed = False
            details = (
                f"Field '{rule.field}' must be <= {rule.value}; actual={field_value}"
            )

        elif rule.type == "min":
            try:
                passed = float(field_value) >= float(rule.value)
            except Exception:
                passed = False
            details = (
                f"Field '{rule.field}' must be >= {rule.value}; actual={field_value}"
            )

        elif rule.type == "in":
            options = rule.value if isinstance(rule.value, list) else []
            passed = field_value in options
            details = f"Field '{rule.field}' must be in {options}; actual={field_value}"

        else:
            passed = False
            details = f"Unknown rule type: {rule.type}"

        results.append(
            ClearanceResult(
                rule_id=rule.id, field=rule.field, passed=passed, details=details
            )
        )
        if not passed:
            overall = False

    return results, overall


def proof_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(canonical).hexdigest()


# -------------------------------------------------
# API: DCL + CLEARANCE
# -------------------------------------------------
class ParseRequest(BaseModel):
    law_text: str
    law_title: Optional[str] = None


@app.post("/dcl/parse", response_model=DCLSchema)
async def dcl_parse(req: ParseRequest):
    lines = req.law_text.splitlines()
    rules: List[DCLRule] = []

    for i, line in enumerate(lines, start=1):
        r = parse_rule_line(line, i)
        if r:
            rules.append(r)

    return DCLSchema(
        law_title=req.law_title or "Law Snippet",
        rules=rules,
        source_text=req.law_text,
    )


class ClearanceRequest(BaseModel):
    schema: DCLSchema
    data: Dict[str, Any]


@app.post("/clearance/check", response_model=ProofLog)
async def clearance_check(req: ClearanceRequest):
    results, overall = evaluate(req.schema, req.data)

    payload = {
        "law_title": req.schema.law_title,
        "schema": json.loads(req.schema.model_dump_json()),
        "data_checked": req.data,
        "results": [r.model_dump() for r in results],
        "overall_passed": overall,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    h = proof_hash(payload)

    return ProofLog(
        law_title=req.schema.law_title,
        schema=req.schema,
        data_checked=req.data,
        results=results,
        overall_passed=overall,
        proof_hash=h,
    )


# -------------------------------------------------
# API: USE-CASE INVENTORY → DATABASE
# -------------------------------------------------
@app.post("/usecases/submit")
async def submit_usecase(
    system_name: str = Form(...),
    purpose: str = Form(...),
    context: str = Form(...),
    data_used: str = Form(...),
    safeguards: str = Form(...),
    extra_details: str = Form(""),
):
    """
    Ontvangt de velden van het Use-Case Inventory formulier en bewaart ze in de DB.
    Geeft een JSON terug met id + hash.
    """
    from datetime import datetime as _dt

    payload = {
        "system_name": system_name,
        "purpose": purpose,
        "context": context,
        "data_used": data_used,
        "safeguards": safeguards,
        "extra_details": extra_details,
        "timestamp": _dt.utcnow().isoformat() + "Z",
    }

    payload_str = json.dumps(payload, sort_keys=True)
    record_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    db: Session = next(get_db())
    entry = UseCase(
        system_name=system_name,
        purpose=purpose,
        context=context,
        data_used=data_used,
        safeguards=safeguards,
        extra_details=extra_details,
        record_hash=record_hash,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    return {
        "status": "ok",
        "id": entry.id,
        "hash": record_hash,
        "stored": True,
    }


@app.get("/admin/usecases")
async def admin_usecases():
    """
    JSON-lijst met alle geregistreerde use-cases.
    (Dit is de backend-tegenhanger van jouw admin/overview.)
    """
    db: Session = next(get_db())
    records = db.query(UseCase).order_by(UseCase.id.desc()).all()

    out: List[Dict[str, Any]] = []
    for r in records:
        out.append(
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "system_name": r.system_name,
                "purpose": r.purpose,
                "context": r.context,
                "data_used": r.data_used,
                "safeguards": r.safeguards,
                "extra_details": r.extra_details,
                "record_hash": r.record_hash,
            }
        )

    return out


# -------------------------------------------------
# MINIMALE DEMO-UI
# -------------------------------------------------
INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Law-to-Code MVP — DCL + CLEARANCE</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; line-height: 1.4; }
    h1 { margin-bottom: 0; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    textarea { width: 100%; height: 180px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    pre { background: #f6f7f9; padding: 12px; border-radius: 8px; overflow: auto; }
    button { padding: 10px 16px; border: 0; border-radius: 8px; background: #111; color: #fff; cursor: pointer; }
    .ok { color: #16794d; font-weight: 600; }
    .nok { color: #b00020; font-weight: 600; }
    .card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; }
    label { font-size: 12px; color: #555; }
  </style>
</head>
<body>
  <h1>Law-to-Code MVP</h1>
  <p><strong>DCL + CLEARANCE</strong> — parse simple legal rules → check data → produce a <em>proof hash</em>.</p>

  <div class="grid">
    <div class="card">
      <h3>1) Law Text → DCL</h3>
      <label>Law Title</label>
      <input id="law_title" style="width:100%;margin-bottom:8px" value="ESPR demo snippet" />
      <label>Law Text (one rule per line)</label>
      <textarea id="law_text">require manufacturer
require category
in category [electronics, furniture]
max weight 50
</textarea>
      <button onclick="parseDCL()">Parse to DCL</button>
      <h4>Schema (DCL)</h4>
      <pre id="schema_out"></pre>
    </div>

    <div class="card">
      <h3>2) Data → CLEARANCE</h3>
      <label>Product JSON</label>
      <textarea id="data_json">{
  "manufacturer": "ACME",
  "category": "electronics",
  "weight": 42
}</textarea>
      <button onclick="runClearance()">Run CLEARANCE</button>
      <h4>Result</h4>
      <div id="result"></div>
      <h4>Proof Log</h4>
      <pre id="proof"></pre>
    </div>
  </div>

  <script>
    let lastSchema = null;

    async function parseDCL() {
      const law_text = document.getElementById('law_text').value;
      const law_title = document.getElementById('law_title').value;
      const res = await fetch('/dcl/parse', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ law_text, law_title })
      });
      const data = await res.json();
      lastSchema = data;
      document.getElementById('schema_out').textContent = JSON.stringify(data, null, 2);
    }

    async function runClearance() {
      if (!lastSchema) await parseDCL();
      const dataStr = document.getElementById('data_json').value;
      let data;
      try { data = JSON.parse(dataStr); } catch(e) { alert('Invalid JSON for data'); return; }
      const res = await fetch('/clearance/check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema: lastSchema, data })
      });
      const proof = await res.json();
      document.getElementById('proof').textContent = JSON.stringify(proof, null, 2);
      const badge = proof.overall_passed ? '<span class="ok">COMPLIANT</span>' : '<span class="nok">NON-COMPLIANT</span>';
      document.getElementById('result').innerHTML = `Overall: ${badge}<br/>Proof Hash: <code>${proof.proof_hash}</code>`;
    }

    // Auto-parse on load
    parseDCL();
  </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)
