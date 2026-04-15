import ipaddress
import os
from typing import Dict, Tuple


def build_local_networks():
    networks = [
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
    ]

    # Optional public egress CIDRs/IPs that should be treated as trusted viewer networks
    # in hosted environments where private LAN ranges are not visible server-side.
    extra_cidrs = os.getenv("TRUSTED_VIEWER_CIDRS", "").strip()
    if extra_cidrs:
        for cidr in extra_cidrs.split(","):
            value = cidr.strip()
            if not value:
                continue
            try:
                networks.append(ipaddress.ip_network(value, strict=False))
            except ValueError:
                # Ignore invalid entries so one typo does not break app startup.
                continue

    return networks


def get_manager_password() -> str:
    return os.getenv("DASHBOARD_MANAGER_PASSWORD", "")


def get_admin_password() -> str:
    return os.getenv("DASHBOARD_ADMIN_PASSWORD", "")


def get_dashboard_public_flag() -> bool:
    return os.getenv("DASHBOARD_PUBLIC", "false").lower() in ("1", "true", "yes")


def get_device_token_settings() -> Tuple[str, str, int]:
    return (
        "device_tokens.json",
        os.getenv("DEVICE_TOKENS_DB", "").strip(),
        7,
    )


def create_qa_cache(ttl_cache_cls):
    ttl_seconds = float(os.getenv("QA_CACHE_TTL_SECONDS", "60"))
    cache = ttl_cache_cls(maxsize=int(os.getenv("QA_CACHE_MAXSIZE", "256")), ttl=ttl_seconds)
    return cache


def cache_get(cache, cache_key: str):
    return cache.get(cache_key)


def cache_set(cache, cache_key: str, data: Dict[str, object]):
    cache.set(cache_key, data)
    return data


def initial_backfill_progress() -> Dict[str, object]:
    return {
        "running": False,
        "total": 0,
        "processed": 0,
        "percent": 0,
        "last_updated": None,
        "errors": [],
    }


def get_webhook_api_key() -> str:
    return os.getenv("WEBHOOK_API_KEY", "")


def get_webhook_api_keys() -> list[str]:
    keys: list[str] = []

    multi = os.getenv("WEBHOOK_API_KEYS", "").strip()
    if multi:
        for raw in multi.split(","):
            key = raw.strip()
            if key and key not in keys:
                keys.append(key)

    single = os.getenv("WEBHOOK_API_KEY", "").strip()
    if single and single not in keys:
        keys.append(single)

    return keys


def get_hwid_log_path() -> str:
    return os.getenv("HWID_LOG_PATH", "logs/hwid_log.jsonl")


def get_frontend_paths() -> Tuple[str, str, str]:
    return (
        os.path.join("frontend", "pages"),
        os.path.join("frontend", "js"),
        os.path.join("frontend", "css"),
    )


def get_cors_allow_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    origins: list[str] = []
    for part in raw.split(","):
        value = part.strip()
        if value and value not in origins:
            origins.append(value)
    return origins or ["*"]


def is_legacy_query_auth_enabled() -> bool:
    return os.getenv("LEGACY_QUERY_AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def is_legacy_basic_auth_enabled() -> bool:
    return os.getenv("LEGACY_BASIC_AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes")
