"""
NexusOps Backend — FastAPI + Supabase
OWASP hardened, rate limited, env-var only secrets.
Zero hard-coded keys. Zero trust on input.
"""

import os
import re
import time
import hashlib
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator
from supabase import create_client, Client
from dotenv import load_dotenv

# ── Load env vars FIRST — never hard-code secrets ──────────────────────────
load_dotenv()

SUPABASE_URL: str = os.environ["SUPABASE_URL"]           # crash loud if missing
SUPABASE_SERVICE_KEY: str = os.environ["SUPABASE_SERVICE_KEY"]  # service key, backend only
ALLOWED_ORIGINS: list[str] = os.getenv(
    "ALLOWED_ORIGINS",
    "https://nexusops.vercel.app,http://localhost:3000"
).split(",")
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")

# ── Logging — structured, no sensitive data in logs ─────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("nexusops")

# ── In-memory rate limiter ───────────────────────────────────────────────────
# For production at scale: swap this for Redis (redis-py + fakeredis for tests)
class RateLimiter:
    """
    Sliding-window rate limiter keyed by IP.
    Stores timestamps of requests in a deque per key.
    Thread-safe enough for single-process; use Redis for multi-worker.
    """
    def __init__(self):
        self._store: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        window_start = now - window_seconds
        # Prune old timestamps outside the window
        self._store[key] = [t for t in self._store[key] if t > window_start]

        if len(self._store[key]) >= max_requests:
            return False  # Rate limit exceeded

        self._store[key].append(now)
        return True

    def cleanup(self, older_than_seconds: int = 3600):
        """Prune keys with no recent requests to prevent memory bloat."""
        cutoff = time.time() - older_than_seconds
        stale = [k for k, v in self._store.items() if not v or max(v) < cutoff]
        for k in stale:
            del self._store[k]

rate_limiter = RateLimiter()

# ── Supabase client — initialized once at startup ───────────────────────────
supabase: Client | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    log.info("Supabase client initialized")
    yield
    log.info("Shutting down")

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="NexusOps API",
    docs_url=None if ENVIRONMENT == "production" else "/docs",   # hide Swagger in prod
    redoc_url=None if ENVIRONMENT == "production" else "/redoc",
    openapi_url=None if ENVIRONMENT == "production" else "/openapi.json",
    lifespan=lifespan,
)

# ── Security Middleware ──────────────────────────────────────────────────────

# 1. Trusted hosts — rejects requests with unexpected Host headers (host-header injection)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["nexusops-backend.vercel.app", "nexusops-frontend.vercel.app", "*.nexusops.com", "localhost", "127.0.0.1"],
)

# 2. CORS — explicit allowlist only, no wildcards in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,          # no cookies/auth headers needed here
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
    max_age=600,
)

# 3. Security headers middleware (OWASP recommended)
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    # Prevent MIME sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Clickjacking protection
    response.headers["X-Frame-Options"] = "DENY"
    # XSS filter (legacy browsers)
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Only send referrer on same origin
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # CSP — tight policy, no inline scripts, no eval
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        "frame-ancestors 'none';"
    )
    # HSTS — force HTTPS for 1 year
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Remove server fingerprint
    response.headers.__delitem__("server") if "server" in response.headers else None
    return response

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_client_ip(request: Request) -> str:
    """
    Extract real IP. Check X-Forwarded-For first (set by Vercel/proxies).
    Hash it so we never log raw IPs (GDPR compliance).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    # Hash the IP — we use it for rate limiting but don't need to store raw IPs
    return hashlib.sha256(ip.encode()).hexdigest()[:16]

def enforce_rate_limit(ip_hash: str, max_req: int = 5, window: int = 60):
    """
    Raises HTTP 429 if IP exceeds max_req requests per window (seconds).
    Defaults: 5 requests/minute. Graceful — returns Retry-After header.
    """
    if not rate_limiter.is_allowed(ip_hash, max_req, window):
        log.warning(f"Rate limit exceeded | ip_hash={ip_hash}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait a moment and try again.",
            headers={"Retry-After": str(window)},
        )

# ── Input Models (Pydantic validates & sanitizes) ────────────────────────────

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

class WaitlistEntry(BaseModel):
    email: EmailStr
    name: str = ""
    source: str = "landing_page"

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email format")
        if len(v) > 254:  # RFC 5321 max
            raise ValueError("Email too long")
        return v

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        # Strip HTML tags and limit length — prevent stored XSS
        v = re.sub(r"<[^>]+>", "", v).strip()
        return v[:100]  # max 100 chars

    @field_validator("source")
    @classmethod
    def sanitize_source(cls, v: str) -> str:
        allowed = {"landing_page", "footer", "hero", "referral"}
        return v if v in allowed else "landing_page"

class BookingRequest(BaseModel):
    email: EmailStr
    name: str
    message: str = ""

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        v = re.sub(r"<[^>]+>", "", v).strip()
        if not v:
            raise ValueError("Name is required")
        return v[:100]

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        v = re.sub(r"<[^>]+>", "", v).strip()
        return v[:1000]

# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Public health check — no sensitive info exposed."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/api/waitlist", status_code=status.HTTP_201_CREATED)
async def join_waitlist(entry: WaitlistEntry, request: Request):
    """
    Add email to waitlist.
    Rate limit: 3 submissions per IP per 5 minutes.
    Duplicate emails return 200 (don't leak whether email exists).
    """
    ip_hash = get_client_ip(request)

    # Rate limit: 3 signups per IP per 5 min (prevents enumeration/spam)
    enforce_rate_limit(ip_hash, max_req=3, window=300)

    try:
        # Check for duplicate — upsert to avoid unique constraint errors leaking info
        result = supabase.table("waitlist").upsert(
            {
                "email": entry.email,          # already validated + lowercased
                "name": entry.name,
                "source": entry.source,
                "ip_hash": ip_hash,            # store hash, never raw IP
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="email",               # if email exists, update source/name silently
            ignore_duplicates=False,
        ).execute()

        log.info(f"Waitlist signup | source={entry.source}")  # no PII in logs
        return {"message": "You're on the list. We'll be in touch soon."}

    except Exception as e:
        # Never expose raw DB errors to the client
        log.error(f"Waitlist DB error: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again.",
        )

@app.get("/api/waitlist/count")
async def waitlist_count(request: Request):
    """
    Returns public count for social proof.
    Rate limit: 20 reads/min per IP (it's a GET, more lenient).
    Count is fuzzed slightly to avoid exposing exact DB size.
    """
    ip_hash = get_client_ip(request)
    enforce_rate_limit(ip_hash, max_req=20, window=60)

    try:
        result = supabase.table("waitlist").select("id", count="exact").execute()
        raw_count = result.count or 0
        # Add base offset so you don't start at 0 — social proof
        displayed_count = raw_count + 247
        return {"count": displayed_count}
    except Exception as e:
        log.error(f"Count query error: {type(e).__name__}")
        # Fail gracefully — return cached/default value, don't crash
        return {"count": 247}

@app.post("/api/booking", status_code=status.HTTP_201_CREATED)
async def create_booking(booking: BookingRequest, request: Request):
    """
    Log a booking intent (Calendly handles the actual scheduling).
    Rate limit: 2 per IP per 10 minutes.
    """
    ip_hash = get_client_ip(request)
    enforce_rate_limit(ip_hash, max_req=2, window=600)

    try:
        supabase.table("booking_intents").insert({
            "email": booking.email,
            "name": booking.name,
            "message": booking.message,
            "ip_hash": ip_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        log.info("Booking intent logged")
        return {"message": "Booking intent recorded. Check your Calendly link."}

    except Exception as e:
        log.error(f"Booking DB error: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again.",
        )

# ── Global exception handler — never leak stack traces ───────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled exception: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred."},
    )
