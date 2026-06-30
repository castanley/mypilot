"""Runtime configuration loaded from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    mypilot_env: str = "production"

    # Datastores
    database_url: str = "postgresql+asyncpg://mypilot:mypilot@mypilot-db:5432/mypilot"
    redis_url: str = "redis://mypilot-redis:6379/0"

    # DB connection pool. Sized explicitly rather than relying on SQLAlchemy's small default: a
    # pool_size baseline + max_overflow burst, a short pool_timeout so a checkout spike fails fast
    # instead of stalling on the 30s default, and a statement_timeout so a pathological query can't
    # pin a connection forever. Keep pool_size+max_overflow within your Postgres max_connections.
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout_seconds: int = 5
    db_statement_timeout_ms: int = 15000  # 0 disables

    # Object storage (MinIO / S3). Used from Milestone 4; bucket is provisioned at startup.
    s3_endpoint: str = "http://mypilot-object-storage:9000"
    s3_bucket: str = "mypilot"
    s3_access_key: str = "mypilot"
    s3_secret_key: str = "mypilot"
    # botocore connection-pool size — keep >= the upload-concurrency budget so concurrent object
    # I/O doesn't serialize on the default 10-conn pool.
    s3_max_pool_connections: int = 32
    # Optional server-side encryption-at-rest. The object store does the crypto; the app just tags
    # each write so the bucket encrypts it. Empty = no SSE header (rely on the bucket's own default
    # policy, or none). "AES256" = SSE-S3; "aws:kms" = SSE-KMS (then set s3_sse_kms_key_id). Reads /
    # Range are unaffected — the store decrypts transparently on GET.
    s3_sse: str = ""             # "" | "AES256" | "aws:kms"
    s3_sse_kms_key_id: str = ""  # required when s3_sse == "aws:kms"

    # Ingest upload limits. Each upload is fully buffered in RAM (the body is Ed25519-signed whole),
    # so a per-file cap + a concurrency gate bound peak memory: at the worst case ~ max_file × N
    # concurrent. A comma 60s segment (qlog/qcamera/fcamera) is a few-to-tens of MB; 64 MiB is a
    # generous real ceiling (was 1 GiB, which let a handful of uploads OOM the worker that also holds
    # every WebSocket). Raise per-deployment if a fork uploads larger artifacts.
    max_upload_bytes: int = 64 * 1024 * 1024
    max_concurrent_uploads: int = 16

    # Security
    api_secret_key: str = "dev-insecure-change-me"
    cookie_secure: bool = False
    site_address: str = "localhost"

    # Cookies
    session_cookie_name: str = "mypilot_session"
    csrf_cookie_name: str = "mypilot_csrf"
    session_ttl_seconds: int = 60 * 60 * 24 * 14  # 14 days

    # Pairing
    pairing_code_ttl_seconds: int = 600           # 10 minutes
    pairing_code_length: int = 8

    # Presence / realtime
    presence_ttl_seconds: int = 30
    heartbeat_interval_seconds: int = 10
    # Write-behind coalescing for the device_status row: persist the telemetry snapshot to Postgres at
    # most once per this many seconds per device, instead of on every heartbeat (the live map is
    # unaffected — the realtime event is built from each beat in-memory and the working trail lives in
    # Redis). 0 = persist every beat (the default). Onroad transitions + going offline always force an
    # immediate persist.
    heartbeat_persist_interval_seconds: int = 0

    # Device request signing
    device_signature_max_skew_seconds: int = 60

    # Rate limits (fixed window)
    login_rate_limit: int = 10           # attempts
    login_rate_window: int = 60          # per seconds
    pairing_rate_limit: int = 20
    pairing_rate_window: int = 60

    @property
    def is_testing(self) -> bool:
        return self.mypilot_env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
