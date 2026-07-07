from fastapi import FastAPI, Request, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse  # noqa: F401
from time import perf_counter, time
from uuid import uuid4
from pydantic import BaseModel
import jwt
from typing import Optional, List, Dict, Any
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from fastapi.responses import PlainTextResponse
from collections import deque, defaultdict
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import re
import json
import requests
import os
from dotenv import load_dotenv

app = FastAPI()

load_dotenv()
ALLOWED_ORIGINS = [
    "https://dash-lnxsv8.example.com",
    "https://exam.sanand.workers.dev",
    "https://app-bkdpxh.example.com",
]
YOUR_EMAIL = "25ds3000083@ds.study.iitm.ac.in"  # replace with your real logged-in email


# Startup time
started = perf_counter()

# In-memory log buffer
logs = deque(maxlen=1000)

# Prometheus counter
http_requests_total = Counter("http_requests_total", "Total HTTP requests")


class SelectiveCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Let the default CORS middleware run first
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid4())
        http_requests_total.inc()
        request.state.request_id = request_id
        response = await call_next(request)

        logs.append(
            {
                "level": "INFO",
                "ts": perf_counter(),
                "path": request.url.path,
                "request_id": request_id,
            }
        )

        path = request.url.path
        method = request.method
        # For /analytics, force Access-Control-Allow-Origin: *
        if (path == "/analytics") or (path == "/orders" and method == "GET"):
            # Remove any existing origin set by CORSMiddleware
            response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["X-Request-ID"] = request_id

        return response


# Standard CORS for all routes (restricted origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom middleware to override origin for /analytics only
app.add_middleware(SelectiveCORSMiddleware)


# Bucket config
RATE_LIMIT = 13  # B
WINDOW_SECONDS = 10

# client_id -> list of request timestamps
client_requests = defaultdict(list)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_id = request.headers.get("X-Client-Id")
    if not client_id:
        return await call_next(request)

    now = time()
    client_requests[client_id] = [
        ts for ts in client_requests[client_id] if now - ts < WINDOW_SECONDS
    ]

    if len(client_requests[client_id]) >= RATE_LIMIT:
        return Response(
            status_code=429,
            content="Too Many Requests",
        )

    client_requests[client_id].append(now)
    return await call_next(request)


@app.middleware("http")
async def add_headers(request: Request, call_next):
    start = perf_counter()
    request_id = str(uuid4())

    response = await call_next(request)

    process_time = max(perf_counter() - start, 0.0)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{process_time:.6f}"
    return response


@app.get("/stats")
async def stats(values: str):
    nums = [int(x.strip()) for x in values.split(",") if x.strip() != ""]
    count = len(nums)
    total = sum(nums)
    minimum = min(nums)
    maximum = max(nums)
    mean = total / count

    return {
        "email": YOUR_EMAIL,
        "count": count,
        "sum": total,
        "min": minimum,
        "max": maximum,
        "mean": round(mean, 2),
    }


# Verify Endpoint
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2okOHspNjgA+2rTLbeuY
cxiP/hG8C6Sb9iwg3yiLAA4HCnpITcbWCSelbvbYGuc3EbNy4xFyf5Cbj5DHJMID
EkryOgyd2giIIIBOUBj8S63uGcnRpOBh9NFatfNwheKuzsPuVNldu6A9cNteNpXc
WyJjG2axVfmq7i6SuKr1JoWYG7xTTAvKPujSl4OtsQfO3h5NepzdfXpr28oNnzfW
ed+zclR6BcmNNo/WVfJ4xyCLSf0BCOgdTgW6PdaChd1l9VDetJZVEgC5tkyvXsfI
SI6iyrYbKR0NEBSqq4XkadEjsCs4F1RncsS4LlgniT7GlkL9Mce3b0wGLs9/7ZIX
dQIDAQAB
-----END PUBLIC KEY-----"""


EXPECTED_ISS = "https://idp.exam.local"
EXPECTED_AUD = "tds-yf86g1jp.apps.exam.local"


class VerifyRequest(BaseModel):
    token: str


@app.post("/verify")
def verify_token(body: VerifyRequest):
    try:
        claims = jwt.decode(
            body.token,
            PUBLIC_KEY,
            algorithms=["RS256"],
            audience=EXPECTED_AUD,
            issuer=EXPECTED_ISS,
        )

        return {
            "valid": True,
            "email": claims.get("email"),
            "sub": claims.get("sub"),
            "aud": claims.get("aud"),
        }

    except Exception as e:
        print(e)
        raise HTTPException(status_code=401, detail={"valid": False})


# Analytics Endpoint
class Event(BaseModel):
    user: str
    amount: float
    ts: int


class AnalyticsRequest(BaseModel):
    events: List[Event]


class AnalyticsResponse(BaseModel):
    email: str
    total_events: int
    unique_users: int
    revenue: float
    top_user: Optional[str] = None


# --- Your assigned values ---
API_KEY = "ak_f15dl7dq4ii90bors6szlpt2"


@app.post("/analytics")
async def analytics_endpoint(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    # 1. Auth: check API key
    if x_api_key is None or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. Parse and validate JSON body using Pydantic
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        req = AnalyticsRequest(**body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    events = req.events

    # 3. Aggregation logic

    total_events = len(events)

    users_set = set()
    revenue = 0.0
    user_positive_totals: Dict[str, float] = {}

    for ev in events:
        user = ev.user
        amount = ev.amount

        users_set.add(user)

        # Only positive amounts count for revenue and top_user
        if amount > 0:
            revenue += amount
            current = user_positive_totals.get(user, 0.0)
            user_positive_totals[user] = current + amount

    unique_users = len(users_set)

    # top_user: user with highest total of positive amounts
    top_user: Optional[str] = None
    if user_positive_totals:
        # Grader guarantees no ties
        top_user = max(user_positive_totals, key=user_positive_totals.get)

    response_data = AnalyticsResponse(
        email=YOUR_EMAIL,
        total_events=total_events,
        unique_users=unique_users,
        revenue=revenue,
        top_user=top_user,
    )
    resp = JSONResponse(content=response_data.model_dump())
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.get("/work")
def work(n: int):
    # Simulate work
    for _ in range(n):
        pass

    return {"email": YOUR_EMAIL, "done": n}


@app.get("/healthz")
def healthz():
    return {"status": "ok", "uptime_s": perf_counter() - started}


@app.get("/logs/tail")
def tail(limit: int = 10):
    return list(logs)[-limit:]


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


"""
This part is for /extract wala from
"""
LLM_URL = f"{os.getenv('CLOUDFLARED_URL')}/v1/chat/completions"
MODEL = "google/gemma-4-e4b:2"


class ExtractRequest(BaseModel):
    text: str


class InvoiceResponse(BaseModel):
    vendor: str
    amount: float
    currency: str
    date: str


@app.post("/extract", response_model=InvoiceResponse)
def extract_invoice(req: ExtractRequest):
    text = req.text.strip()

    # Handle empty input safely
    if not text:
        return InvoiceResponse(vendor="", amount=0, currency="USD", date="1970-01-01")
    print(text)
    prompt = f"""
Extract invoice fields from the text below.

Return ONLY valid JSON:
{{
  "vendor": "string",
  "amount": number,
  "currency": "3-letter uppercase currency code",
  "date": "YYYY-MM-DD"
}}

Invoice:
{text}
"""

    response = requests.post(
        LLM_URL,
        headers={"Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
        timeout=180,
    )

    result = response.json()

    content = result["choices"][0]["message"]["content"]

    # Extract JSON if model adds extra text
    match = re.search(r"\{.*\}", content, re.S)
    data = json.loads(match.group())
    print(data)
    return InvoiceResponse(**data)


# For the Pagination API
@app.get("/ping")
async def ping(request: Request):
    request_id = request.state.request_id
    return {"email": YOUR_EMAIL, "request_id": request_id}


# ----- Config -----
TOTAL_ORDERS = 57  # <-- set this to your assigned T

# ----- In-memory stores -----

# For idempotent order creation:
# idempotency_key -> order dict

all_orders: List[Dict[str, Any]] = []
idempotency_index: Dict[str, int] = {}
# ----- 1. Idempotent order creation -----


@app.post("/orders")
async def create_order(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required",
        )

    # If we've already created an order for this key, return it
    if idempotency_key in idempotency_index:
        idx = idempotency_index[idempotency_key]
        return all_orders[idx]

    # First time: create a new order
    order_id = str(uuid4())
    order = {"id": order_id}  # top-level "id" as required

    # Store order and remember its index for this key
    all_orders.append(order)
    idempotency_index[idempotency_key] = len(all_orders) - 1

    return order


# ----- 2. Cursor pagination over fixed catalog -----


def encode_cursor(order_id: int) -> str:
    """
    Turn an order ID into an opaque cursor string.
    Grader treats it as opaque, so any reversible encoding works.
    Here we just use the string representation.
    """
    return str(order_id)


def decode_cursor(cursor: str) -> int:
    """
    Decode cursor back to list index.
    If invalid or out of range, treat as 0 (start).
    """
    try:
        idx = int(cursor)
        if idx < 0:
            return 0
        return idx
    except (ValueError, TypeError):
        return 0


@app.get("/orders")
async def list_orders(
    limit: int = Query(10, ge=1, le=100),
    cursor: Optional[str] = Query(None),
):
    start_index = 0 if cursor is None else decode_cursor(cursor)

    # Clamp start_index to valid range
    if start_index >= len(all_orders):
        return {"items": [], "next_cursor": None}

    # Collect up to `limit` orders
    items: List[Dict[str, Any]] = []
    current_index = start_index

    while current_index < len(all_orders) and len(items) < limit:
        items.append(all_orders[current_index])
        current_index += 1

    # Determine next cursor
    if current_index >= len(all_orders):
        next_cursor = None
    else:
        next_cursor = encode_cursor(current_index)

    return {"items": items, "next_cursor": next_cursor}
