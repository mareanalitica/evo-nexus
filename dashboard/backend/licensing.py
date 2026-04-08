"""OpenClaude Licensing — direct registration, activation, heartbeat, shutdown.

Follows the Evolution Licensing Server protocol:
  POST /v1/register/direct  — register with email/name, receive api_key
  POST /v1/activate         — validate existing api_key on startup
  POST /v1/heartbeat        — periodic ping with telemetry
  POST /v1/deactivate       — mark instance as offline on shutdown
  GET  /api/geo             — geo-lookup from client IP
"""

import hashlib
import hmac as hmac_mod
import socket
import uuid
import time
import threading
import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger("licensing")

LICENSING_SERVER = "https://license.evolutionfoundation.com.br"
PRODUCT = "open-claude"
VERSION = "0.1.0"
TIER = "open-claude-community"
HEARTBEAT_INTERVAL = 300  # 5 minutes (matching Ruby impl)
TIMEOUT = 10


# ── Instance ID (hardware-based) ─────────────

def generate_instance_id() -> str:
    """Generate unique ID based on hardware (hostname + MAC). Deterministic per machine."""
    hostname = socket.gethostname()
    mac = uuid.getnode()
    raw = f"{hostname}-{mac}-{PRODUCT}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── HMAC Signing ─────────────────────────────

def _hmac_sign(api_key: str, body: str) -> str:
    """HMAC-SHA256 signature for authenticated requests."""
    return hmac_mod.new(api_key.encode(), body.encode(), hashlib.sha256).hexdigest()


# ── RuntimeConfig persistence (DB) ───────────

def get_runtime_config(key: str) -> str | None:
    from models import RuntimeConfig
    try:
        row = RuntimeConfig.query.filter_by(key=key).first()
        return row.value if row else None
    except Exception:
        return None


def set_runtime_config(key: str, value: str):
    from models import db, RuntimeConfig
    try:
        row = RuntimeConfig.query.filter_by(key=key).first()
        if row:
            row.value = value
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = RuntimeConfig(key=key, value=value)
            db.session.add(row)
        db.session.commit()
    except Exception as e:
        logger.warning(f"Failed to save config {key}: {e}")


# ── Transport (HTTP client) ──────────────────

def _post(path: str, payload: dict, api_key: str | None = None) -> dict:
    """POST to licensing server. If api_key provided, signs with HMAC."""
    import json
    url = f"{LICENSING_SERVER}{path}"
    body = json.dumps(payload)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"OpenClaude/{VERSION}",
    }

    if api_key:
        signature = _hmac_sign(api_key, body)
        headers["Authorization"] = f"HMAC {signature}"

    resp = requests.post(url, data=body, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _get(path: str, headers: dict | None = None) -> dict:
    """GET from licensing server."""
    url = f"{LICENSING_SERVER}{path}"
    h = {"Accept": "application/json", "User-Agent": f"OpenClaude/{VERSION}"}
    if headers:
        h.update(headers)
    resp = requests.get(url, headers=h, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ── Geo Lookup ───────────────────────────────

def geo_lookup(client_ip: str | None = None) -> dict:
    """Get geo data from licensing server based on client IP."""
    if not client_ip:
        return {}
    try:
        return _get("/api/geo", headers={"X-Forwarded-For": client_ip})
    except Exception:
        return {}


# ── Direct Registration ──────────────────────

def direct_register(email: str, name: str, instance_id: str,
                    country: str | None = None, city: str | None = None) -> dict:
    """Register directly with the licensing server. Returns {api_key, tier, customer_id}."""
    payload = {
        "tier": TIER,
        "email": email,
        "name": name,
        "instance_id": instance_id,
        "version": VERSION,
    }
    if country:
        payload["country"] = country
    if city:
        payload["city"] = city

    return _post("/v1/register/direct", payload)


# ── Activation (startup with existing api_key) ──

def activate(instance_id: str, api_key: str) -> bool:
    """Validate existing api_key with licensing server. Returns True if active."""
    try:
        result = _post("/v1/activate", {
            "instance_id": instance_id,
            "version": VERSION,
        }, api_key=api_key)
        return result.get("status") == "active"
    except Exception:
        return False


# ── Heartbeat ────────────────────────────────

def heartbeat(instance_id: str, api_key: str, stats: dict | None = None) -> dict:
    """Periodic heartbeat. Returns server response."""
    payload = {
        "instance_id": instance_id,
        "version": VERSION,
        "messages_sent": 0,
    }
    if stats:
        payload.update(stats)

    try:
        return _post("/v1/heartbeat", payload, api_key=api_key)
    except Exception:
        return {}


# ── Deactivation (shutdown) ──────────────────

def deactivate(instance_id: str) -> bool:
    """Mark instance as offline on the licensing server."""
    try:
        _post("/v1/deactivate", {
            "instance_id": instance_id,
            "version": VERSION,
        })
        return True
    except Exception:
        return False


# ── Runtime Context (in-memory state) ────────

class RuntimeContext:
    """Thread-safe singleton holding license state."""

    def __init__(self):
        self.instance_id: str | None = None
        self.api_key: str | None = None
        self.tier: str = TIER
        self._active = threading.Event()

    @property
    def active(self) -> bool:
        return self._active.is_set()

    def activate(self, api_key: str, instance_id: str):
        self.api_key = api_key
        self.instance_id = instance_id
        self._active.set()

    def deactivate_ctx(self):
        self._active.clear()


# Global singleton
_context = RuntimeContext()


def get_context() -> RuntimeContext:
    return _context


# ── Setup (orchestrates direct registration) ─

def setup_perform(email: str, name: str, client_ip: str | None = None):
    """Full setup flow: geo lookup → direct register → save → activate → heartbeat."""
    ctx = get_context()

    # 1. Load or create instance_id
    instance_id = get_runtime_config("instance_id")
    if not instance_id:
        instance_id = generate_instance_id()
        set_runtime_config("instance_id", instance_id)

    # 2. Geo lookup
    geo = geo_lookup(client_ip)

    # 3. Direct register
    try:
        result = direct_register(
            email=email,
            name=name,
            instance_id=instance_id,
            country=geo.get("country"),
            city=geo.get("city"),
        )
    except Exception as e:
        logger.warning(f"License registration failed (non-blocking): {e}")
        # Save instance_id at minimum
        set_runtime_config("version", VERSION)
        set_runtime_config("tier", TIER)
        set_runtime_config("activated_at", datetime.now(timezone.utc).isoformat())
        return

    # 4. Save to DB
    api_key = result.get("api_key", "")
    if api_key:
        set_runtime_config("api_key", api_key)
    set_runtime_config("tier", result.get("tier", TIER))
    if result.get("customer_id"):
        set_runtime_config("customer_id", str(result["customer_id"]))
    set_runtime_config("version", VERSION)
    set_runtime_config("activated_at", datetime.now(timezone.utc).isoformat())

    # 5. Activate in memory
    if api_key:
        ctx.activate(api_key=api_key, instance_id=instance_id)
        logger.info(f"License activated: {instance_id[:8]}...")


# ── Initialize Runtime (startup) ─────────────

def initialize_runtime():
    """Called on app startup. Tries to load and validate existing license."""
    ctx = get_context()

    # 1. Load or create instance_id
    instance_id = get_runtime_config("instance_id")
    if not instance_id:
        instance_id = generate_instance_id()
        set_runtime_config("instance_id", instance_id)

    ctx.instance_id = instance_id

    # 2. Try to load existing api_key
    api_key = get_runtime_config("api_key")
    if not api_key:
        logger.info("No license found — waiting for setup/login to register")
        return

    # 3. Validate with licensing server (POST /v1/activate)
    if activate(instance_id, api_key):
        ctx.activate(api_key=api_key, instance_id=instance_id)
        logger.info(f"License validated on startup: {instance_id[:8]}...")
    else:
        logger.info("License validation failed — will retry on next login")
        ctx.api_key = api_key  # Keep for retry


# ── Attempt Setup (on login, if not active) ──

def attempt_setup_on_login(email: str, name: str, client_ip: str | None = None):
    """Called on user login. If license not active, tries to register/reactivate."""
    ctx = get_context()

    # Already active? Nothing to do.
    if ctx.active:
        return

    instance_id = ctx.instance_id or get_runtime_config("instance_id")
    api_key = ctx.api_key or get_runtime_config("api_key")

    # Try reactivation with existing api_key
    if api_key and instance_id:
        if activate(instance_id, api_key):
            ctx.activate(api_key=api_key, instance_id=instance_id)
            return

    # Last resort: direct register
    setup_perform(email=email, name=name, client_ip=client_ip)


# ── Auto-register for existing installs ──────

def auto_register_if_needed():
    """If users exist but no license, register retroactively."""
    try:
        instance_id = get_runtime_config("instance_id")
        api_key = get_runtime_config("api_key")

        # Already has api_key → just initialize
        if api_key:
            initialize_runtime()
            return

        from models import User
        if User.query.count() == 0:
            return  # No setup yet

        # Has users but no api_key → register with admin data
        admin = User.query.filter_by(role="admin").first()
        if not admin:
            return

        # Ensure instance_id
        if not instance_id:
            instance_id = generate_instance_id()
            set_runtime_config("instance_id", instance_id)

        setup_perform(
            email=admin.email or "",
            name=admin.display_name or admin.username,
        )
    except Exception as e:
        logger.debug(f"Auto-register skipped: {e}")


# ── Heartbeat Thread ─────────────────────────

_heartbeat_thread = None
_start_time = time.time()


def start_heartbeat(app):
    """Start background heartbeat thread."""
    global _heartbeat_thread

    def _run():
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            try:
                with app.app_context():
                    ctx = get_context()
                    if not ctx.active or not ctx.api_key or not ctx.instance_id:
                        continue

                    from models import User
                    result = heartbeat(ctx.instance_id, ctx.api_key, {
                        "uptime_seconds": int(time.time() - _start_time),
                        "user_count": User.query.count(),
                    })

                    if result.get("status") == "revoked":
                        ctx.deactivate_ctx()
                        set_runtime_config("tier", "revoked")
                        logger.warning("License revoked by server")
            except Exception:
                pass

    _heartbeat_thread = threading.Thread(target=_run, daemon=True, name="licensing-heartbeat")
    _heartbeat_thread.start()


# ── Shutdown Hook ────────────────────────────

def on_shutdown(app):
    """Deactivate instance on server shutdown."""
    try:
        with app.app_context():
            ctx = get_context()
            if ctx.instance_id:
                deactivate(ctx.instance_id)
    except Exception:
        pass


# ── License Status (for dashboard) ───────────

def get_license_status() -> dict:
    ctx = get_context()
    return {
        "active": ctx.active,
        "instance_id": ctx.instance_id or get_runtime_config("instance_id"),
        "tier": get_runtime_config("tier") or TIER,
        "version": VERSION,
        "activated_at": get_runtime_config("activated_at"),
        "product": PRODUCT,
    }
