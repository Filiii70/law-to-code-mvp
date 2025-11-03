# Law-to-Code MVP — DCL + CLEARANCE (Online Deploy)

Two easy ways to put this online:

## Option A — Render.com (recommended, no local setup)
1. Create a free account at Render.com.
2. Click “New +” → “Web Service” → “Build and deploy from a Git repo”.
3. Create a new GitHub repo and upload these files (or drag-drop the zip’s contents).
4. Choose **Environment: Docker**, set name `law-to-code-mvp`.
5. Deploy. Once live, open the given URL.

> Render uses the included `Dockerfile` and `render.yaml`. The app listens on port `8080` and will respond on `/`.

## Option B — Railway.app (quick alternative)
1. Create a free account at Railway.
2. New Project → Deploy from GitHub.
3. Push these files to a repo and connect it.
4. Railway detects the `Dockerfile` *or* use the `Procfile` to run:
   ```
   uvicorn app:app --host 0.0.0.0 --port $PORT
   ```
5. Open your service URL when deployed.

## Local test (optional)
```
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
# Open http://localhost:8000
```

---

**What you get online**  
A minimal UI where you type simple “law” rules (left), paste JSON data (right), click “Run CLEARANCE”, and see COMPLIANT/NON-COMPLIANT plus a proof hash.
