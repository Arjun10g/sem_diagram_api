# SEM Diagram API

Convert **lavaan SEM syntax** to publication-quality path diagrams via a REST API backed by Graphviz.

## Features

- Parse lavaan syntax (CFA, full SEM, mediation, growth curves)
- Render to SVG, PNG, PDF via Graphviz `dot`
- Fully configurable layout, node shapes, colours, arrowheads, typography
- Rate limiting, request size limits, timeouts, auto-ban, concurrency control
- PostgreSQL activity log (requests, errors, rate events)
- Admin stats endpoint

---

## Quick start (local, Docker)

### 1. Clone and configure
```bash
git clone <your-repo>
cd sem_diagram_api
cp .env.example .env
# Edit .env — at minimum change ADMIN_API_KEY and POSTGRES_PASSWORD
```

### 2. Start with Docker Compose
```bash
docker compose up --build
```

API is now at **http://localhost:8000**
Docs at **http://localhost:8000/docs**

### 3. Test it
```bash
curl -s http://localhost:8000/health | python3 -m json.tool

curl -s -X POST http://localhost:8000/render/svg \
  -H "Content-Type: application/json" \
  -d '{"syntax": "visual =~ x1 + x2 + x3", "render": {}}' \
  | python3 -m json.tool
```

---

## Local dev (without Docker)

Requires Python 3.11+ and Graphviz installed (`brew install graphviz` / `apt install graphviz`).

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start Postgres separately, then:
uvicorn app.main:app --reload
```

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check incl. Graphviz status |
| GET | `/examples` | List built-in example models |
| GET | `/examples/{filename}` | Fetch example syntax |
| POST | `/parse` | Parse lavaan syntax, return statements |
| POST | `/render` | Full render — returns SVG, DOT, graph JSON |
| POST | `/render/svg` | SVG only |
| POST | `/render/png` | PNG binary |
| POST | `/render/pdf` | PDF binary |
| GET | `/admin/stats?hours=24` | Usage statistics (requires `X-Api-Key`) |
| GET | `/admin/health-db` | Database connectivity check |

### Render request body

```json
{
  "syntax": "visual =~ x1 + x2 + x3\ntextual =~ x4 + x5 + x6",
  "strict_validation": true,
  "render": {
    "rankdir": "TB",
    "splines": "spline",
    "latent_fillcolor": "#EAF2FF",
    "show_variances": false
  },
  "include_dot": false,
  "include_svg": true,
  "include_graph_json": true,
  "include_messages": true
}
```

Full list of render options: see `app/models/request_models.py` or `/docs`.

---

## Deployment on Railway

### 1. Create project
1. Push repo to GitHub
2. New Railway project → Deploy from GitHub repo
3. Railway detects `railway.toml` and uses the Dockerfile

### 2. Add Postgres plugin
In Railway: **New** → **Database** → **PostgreSQL**  
Railway automatically injects `DATABASE_URL` into your service.

### 3. Set environment variables
In Railway service settings → Variables:

```
ADMIN_API_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
ALLOWED_ORIGINS=https://your-shiny-app.shinyapps.io
RATE_LIMIT_RENDER_RPM=20
MAX_CONCURRENT_RENDERS=5
LOG_FORMAT=json
```

### 4. Point your Shiny app
In `app.R`:
```r
API_BASE_DEFAULT <- Sys.getenv("SEM_API_URL", "http://127.0.0.1:8000")
```
Set `SEM_API_URL` in your Shiny deployment to the Railway public URL.

---

## Project structure

```
sem_diagram_api/
├── app/
│   ├── api/
│   │   ├── routes.py          # Main API endpoints
│   │   └── admin.py           # Admin stats endpoint
│   ├── db/
│   │   └── database.py        # PostgreSQL async layer
│   ├── middleware/
│   │   ├── rate_limit.py      # Sliding-window rate limiter
│   │   ├── security.py        # Size limits, timeout, auto-ban, concurrency
│   │   └── logging_mw.py      # Request logging + exception handler
│   ├── models/
│   │   ├── request_models.py  # Pydantic request schemas
│   │   ├── response_models.py # Pydantic response schemas
│   │   └── sem_graph.py       # Internal graph data model
│   ├── services/
│   │   ├── parser.py          # lavaan syntax parser
│   │   ├── graph_builder.py   # Build SemGraph from parsed statements
│   │   ├── dot_renderer.py    # SemGraph → Graphviz DOT
│   │   ├── validator.py       # Semantic validation
│   │   └── pipeline.py        # parse → build → validate → render
│   ├── utils/
│   │   ├── graphviz_helpers.py # Graphviz subprocess wrapper
│   │   └── example_loader.py  # Load example .txt files
│   ├── logger.py              # Structured logging config
│   └── main.py                # FastAPI app + middleware registration
├── examples/
│   ├── cfa.txt
│   ├── sem.txt
│   ├── mediation.txt
│   └── growth.txt
├── Dockerfile
├── docker-compose.yml
├── railway.toml
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Admin stats

```bash
curl -H "X-Api-Key: your_admin_key" \
     "https://your-api.railway.app/admin/stats?hours=24"
```

Returns request counts, error rates, p50/p95 render latency, top IPs, recent bans.

---

## Rate limits

| Tier | Endpoints | Default |
|------|-----------|---------|
| render | `/render*` | 20 req/min + 5 burst/sec |
| parse | `/parse` | 60 req/min |
| global | everything else | 120 req/min |

Responses include `X-RateLimit-Remaining` and `X-RateLimit-Limit` headers.  
Blocked requests return `429` with `Retry-After`.

---

## Environment variables

See `.env.example` for the full list with descriptions.
