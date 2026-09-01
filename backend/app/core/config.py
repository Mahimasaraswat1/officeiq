"""Application configuration.

All environment-specific values come from environment variables / .env
(PRD B.5: "never hard-coded secrets").
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- General -----------------------------------------------------------
    APP_NAME: str = "OfficeIQ API"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = True

    # --- Database ----------------------------------------------------------
    # Defaults to the Postgres service defined in docker-compose.yml.
    DATABASE_URL: str = (
        "postgresql+psycopg://officeiq:officeiq@localhost:5433/officeiq"
    )
    # Connection pool. The defaults suit a handful of uvicorn workers; raise
    # POOL_SIZE with worker count, never past what Postgres max_connections
    # allows across every worker and every replica.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT_SECONDS: int = 30
    # Recycle below any proxy/database idle timeout so a stale socket is
    # replaced before a query finds it dead.
    DB_POOL_RECYCLE_SECONDS: int = 1800
    # Log any statement slower than this. 0 disables.
    SLOW_QUERY_MS: int = 0

    # --- Auth / JWT --------------------------------------------------------
    SECRET_KEY: str = Field(default="change-me-in-production", min_length=8)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Account lockout (PRD A.7.1)
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15

    # Token lifetimes for one-time links
    INVITE_TOKEN_EXPIRE_HOURS: int = 72
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60

    # --- Email (Phase 1: console/file mock adapter) ------------------------
    EMAIL_BACKEND: Literal["console", "file", "smtp", "brevo"] = "file"
    EMAIL_OUTBOX_DIR: str = "./outbox"
    EMAIL_FROM: str = "no-reply@officeiq.dev"
    EMAIL_FROM_NAME: str = "OfficeIQ"

    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True

    # Brevo (HTTP API). Its SMTP relay needs a different credential entirely
    # (xsmtpsib-), so the API key below only works with EMAIL_BACKEND=brevo.
    BREVO_API_KEY: str | None = None
    BREVO_TIMEOUT_SECONDS: float = 15.0

    # --- Document storage (Phase 2) ---------------------------------------
    # local = filesystem (no services needed) | s3 = S3-compatible (MinIO/AWS)
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_ROOT: str = "./storage"

    S3_ENDPOINT_URL: str | None = "http://localhost:9000"
    S3_BUCKET: str = "officeiq-documents"
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None
    S3_REGION: str = "us-east-1"

    # Lifetime of a signed document-download link.
    DOWNLOAD_URL_EXPIRE_SECONDS: int = 300
    MAX_UPLOAD_SIZE_MB: int = 10

    # --- OCR / extraction (Phase 2) ---------------------------------------
    # tesseract = self-hosted | stub = deterministic no-op used by CI
    OCR_ENGINE: Literal["tesseract", "stub"] = "tesseract"
    TESSERACT_CMD: str | None = None  # None = find `tesseract` on PATH
    OCR_LANGUAGES: str = "eng"
    # Rasterisation DPI when a PDF has no embedded text layer.
    OCR_PDF_DPI: int = 200
    # Fields below this confidence are flagged for manual HR attention.
    OCR_LOW_CONFIDENCE_THRESHOLD: float = 0.70
    # Run extraction inline instead of in the background (used by tests).
    OCR_PROCESS_SYNCHRONOUSLY: bool = False

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    # --- Face matching (Phase 3) ------------------------------------------
    # opencv_dnn = YuNet detector + SFace recogniser | stub = no-op for CI
    FACE_MATCHER: Literal["opencv_dnn", "stub"] = "opencv_dnn"
    FACE_MODEL_DIR: str = "./models"
    FACE_DETECTOR_MODEL: str = "face_detection_yunet_2023mar.onnx"
    FACE_RECOGNIZER_MODEL: str = "face_recognition_sface_2021dec.onnx"
    # SFace's reference cosine threshold for "same person" (OpenCV Zoo default).
    FACE_MATCH_THRESHOLD: float = 0.363
    # Minimum YuNet score for a detection to be treated as a face.
    # Deliberately below the usual 0.85-0.9 demo default: the photo on an ID
    # card is small and low-contrast within the full scan, and scores ~0.80-0.85
    # even when perfectly clear. A stricter value rejects valid ID photos
    # outright. This gates *detection* ("is there a face?"), not identity — a
    # false positive still has to clear FACE_MATCH_THRESHOLD to count as a match.
    FACE_DETECTION_CONFIDENCE: float = 0.60

    # --- Mock ID verification (Phase 3) ------------------------------------
    # v1 simulates UIDAI/NSDL; no live government API is contacted (PRD A.4.2).
    MOCK_VERIFICATION_PROVIDER: str = "mock-uidai-nsdl"
    # Minimum similarity between the ID name and the profile name to count as a
    # match; below this HR sees a name-mismatch warning.
    NAME_MATCH_THRESHOLD: float = 0.80
    # Run verification inline instead of in the background (used by tests).
    VERIFICATION_PROCESS_SYNCHRONOUSLY: bool = False

    # --- RAG chatbot (Phase 5) ---------------------------------------------
    # Generation. The Claude API has no embeddings endpoint, so embeddings come
    # from a separate provider (see EMBEDDING_PROVIDER below).
    # claude = Anthropic API | groq = Groq (OpenAI-compatible, free tier)
    # stub = deterministic canned answer for CI
    CHAT_PROVIDER: Literal["claude", "groq", "stub"] = "claude"
    ANTHROPIC_API_KEY: str | None = None
    CHAT_MODEL: str = "claude-opus-5"

    # Groq. A separate model setting because the two providers share no model
    # names — swapping CHAT_PROVIDER alone would otherwise send a Claude model
    # id to Groq and 404.
    GROQ_API_KEY: str | None = None
    # Groq retires models without notice, and a retired name fails as a 404 at
    # request time rather than at startup. gpt-oss-120b follows the grounding
    # instructions closely and does not leak reasoning into the answer, which
    # qwen3.6-27b does (it emits a <think> block the citation parser then sees).
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    CHAT_MAX_TOKENS: int = 2000
    # Adaptive thinking depth: low | medium | high | xhigh | max
    CHAT_EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    @property
    def active_chat_model(self) -> str:
        """The model the configured provider will actually call.

        CHAT_MODEL and GROQ_MODEL are separate settings, so reporting
        CHAT_MODEL regardless of provider would tell an operator the wrong
        thing — a Groq deployment would claim to be running a Claude model.
        """
        if self.CHAT_PROVIDER == "groq":
            return self.GROQ_MODEL
        if self.CHAT_PROVIDER == "stub":
            return "stub"
        return self.CHAT_MODEL

    # Embeddings. voyage = Voyage AI (Anthropic's recommended partner);
    # local = deterministic hashing embedder used by the test suite.
    EMBEDDING_PROVIDER: Literal["voyage", "local"] = "voyage"
    VOYAGE_API_KEY: str | None = None
    VOYAGE_MODEL: str = "voyage-3"
    # Must match the model's output dimension AND the pgvector column width.
    # Changing it requires a migration + re-embedding every chunk.
    EMBEDDING_DIMENSIONS: int = 1024

    # --- Chunking & retrieval ----------------------------------------------
    CHUNK_TARGET_CHARS: int = 1200
    CHUNK_OVERLAP_CHARS: int = 200
    RETRIEVAL_TOP_K: int = 5
    # Chunks scoring below this cosine similarity are discarded as irrelevant.
    RETRIEVAL_MIN_SIMILARITY: float = 0.35
    # Below this answer confidence the bot escalates to HR (PRD A.7.6).
    CHAT_ESCALATION_THRESHOLD: float = 0.45
    # Run ingestion inline instead of in the background (used by tests).
    INGEST_PROCESS_SYNCHRONOUSLY: bool = False

    # --- Notifications & dashboard (Phase 6) -------------------------------
    # In-app notifications are always written. This additionally emails the
    # recipient for employee-facing events, through the same pluggable backend
    # invitations use — off by default so a dev outbox does not fill up.
    NOTIFICATION_EMAIL_ENABLED: bool = False
    # A task this many days from its due date counts as "due soon".
    TASK_DUE_SOON_DAYS: int = 3
    # Default window for /dashboard/trends.
    DASHBOARD_TREND_DAYS: int = 30
    # An in-flight onboarding untouched for this long is flagged as stalled.
    ONBOARDING_STALLED_DAYS: int = 7

    # --- Hardening (Phase 8) -----------------------------------------------
    # Host header allow-list. "*" is fine behind a trusted proxy that already
    # pins the host; set real names to block Host-header poisoning otherwise.
    ALLOWED_HOSTS: Annotated[list[str], NoDecode] = ["*"]
    # Strict-Transport-Security max-age, sent only over HTTPS in production.
    HSTS_MAX_AGE_SECONDS: int = 31_536_000
    # Compress responses above this size. Below it, compression costs more CPU
    # than it saves bytes.
    GZIP_MIN_SIZE_BYTES: int = 1024
    # Requests slower than this are logged at WARNING with their route.
    SLOW_REQUEST_MS: int = 1000
    # Echoed back and attached to every log line for one request.
    REQUEST_ID_HEADER: str = "X-Request-ID"

    # Rate limiting. The default backend is per-process and in-memory, which is
    # correct for one worker and approximate for several — see B.8 in the README.
    RATE_LIMIT_ENABLED: bool = True
    # Sign-in attempts per IP, on top of the per-account lockout.
    RATE_LIMIT_LOGIN: str = "10/minute"
    # Password-reset requests per IP — the expensive, emailing endpoints.
    RATE_LIMIT_PASSWORD_RESET: str = "5/hour"
    # Assistant questions per user; each one costs a model call.
    RATE_LIMIT_CHAT: str = "20/minute"
    # Report generation per user; each one scans and renders the whole table.
    RATE_LIMIT_REPORTS: str = "30/hour"

    # --- Frontend ----------------------------------------------------------
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    # NoDecode stops pydantic-settings from JSON-parsing this value, so the
    # validator below can accept a plain comma-separated string from .env.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # --- Bootstrap admin (seed script) -------------------------------------
    FIRST_ADMIN_EMAIL: str = "admin@officeiq.dev"
    FIRST_ADMIN_PASSWORD: str = "Admin@12345"
    FIRST_ADMIN_NAME: str = "System Administrator"

    @field_validator("CORS_ORIGINS", "ALLOWED_HOSTS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # --- Production guardrails ---------------------------------------------

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def provider_problems(self) -> list[str]:
        """Providers configured without the credentials they need.

        Checked in *every* environment, unlike production_problems(). A local
        run with a keyless provider still boots — the rest of the app works
        fine without the assistant — but it says so loudly at startup instead
        of failing silently once per question, which is how a missing key
        previously cost two debugging sessions.
        """
        problems: list[str] = []
        if self.CHAT_PROVIDER == "claude" and not self.ANTHROPIC_API_KEY:
            problems.append(
                "CHAT_PROVIDER=claude but ANTHROPIC_API_KEY is not set — every "
                "question will fail generation and escalate to HR."
            )
        if self.CHAT_PROVIDER == "groq" and not self.GROQ_API_KEY:
            problems.append(
                "CHAT_PROVIDER=groq but GROQ_API_KEY is not set — every question "
                "will fail generation and escalate to HR."
            )
        if self.EMBEDDING_PROVIDER == "voyage" and not self.VOYAGE_API_KEY:
            problems.append(
                "EMBEDDING_PROVIDER=voyage but VOYAGE_API_KEY is not set — "
                "retrieval falls back to the local hashing embedder, which "
                "matches wording rather than meaning."
            )
        return problems

    def production_problems(self) -> list[str]:
        """Settings that must not reach production, as human-readable reasons.

        Every entry is a development convenience that is *silent* when wrong:
        a stub OCR engine still returns 200s, a file email backend still
        "sends", a default signing key still issues valid-looking tokens. The
        failure mode is a system that looks healthy while doing nothing real,
        which is exactly the kind of thing a deploy should refuse rather than
        log a warning about.
        """
        problems: list[str] = []

        def bad(condition: bool, message: str) -> None:
            if condition:
                problems.append(message)

        # --- Secrets and debug ---
        bad(
            self.SECRET_KEY == "change-me-in-production",
            "SECRET_KEY is still the built-in default — anyone can forge a token.",
        )
        bad(
            len(self.SECRET_KEY) < 32,
            "SECRET_KEY is shorter than 32 characters; generate one with "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'`.",
        )
        bad(self.DEBUG, "DEBUG is on, which turns up log verbosity in production.")
        bad(
            self.FIRST_ADMIN_PASSWORD == "Admin@12345",
            "FIRST_ADMIN_PASSWORD is the documented default; the bootstrap admin "
            "would ship with a published password.",
        )

        # --- Infrastructure that only pretends to work ---
        bad(
            self.DATABASE_URL.startswith("sqlite"),
            "DATABASE_URL points at SQLite, which the schema (pgvector) does not "
            "fully support.",
        )
        bad(
            self.EMAIL_BACKEND in ("console", "file"),
            f"EMAIL_BACKEND={self.EMAIL_BACKEND} does not deliver mail; invitations "
            "would silently never arrive.",
        )
        bad(
            self.STORAGE_BACKEND == "local",
            "STORAGE_BACKEND=local keeps documents on one container's disk, so they "
            "vanish on redeploy and are invisible to other replicas.",
        )

        # --- AI/OCR shims that return plausible nonsense ---
        bad(
            self.OCR_ENGINE == "stub",
            "OCR_ENGINE=stub extracts nothing; every document would come back empty.",
        )
        bad(
            self.FACE_MATCHER == "stub",
            "FACE_MATCHER=stub does not compare faces.",
        )
        bad(
            self.CHAT_PROVIDER == "stub",
            "CHAT_PROVIDER=stub answers every question with canned text.",
        )
        bad(
            self.EMBEDDING_PROVIDER == "local",
            "EMBEDDING_PROVIDER=local is a hashing embedder that matches wording, "
            "not meaning; retrieval would quietly return the wrong policies.",
        )
        bad(
            self.CHAT_PROVIDER == "claude" and not self.ANTHROPIC_API_KEY,
            "CHAT_PROVIDER=claude requires ANTHROPIC_API_KEY.",
        )
        bad(
            self.CHAT_PROVIDER == "groq" and not self.GROQ_API_KEY,
            "CHAT_PROVIDER=groq requires GROQ_API_KEY.",
        )
        bad(
            self.EMBEDDING_PROVIDER == "voyage" and not self.VOYAGE_API_KEY,
            "EMBEDDING_PROVIDER=voyage requires VOYAGE_API_KEY.",
        )
        bad(
            self.STORAGE_BACKEND == "s3" and not (self.S3_ACCESS_KEY and self.S3_SECRET_KEY),
            "STORAGE_BACKEND=s3 requires S3_ACCESS_KEY and S3_SECRET_KEY.",
        )

        # --- Network exposure ---
        bad(
            "*" in self.CORS_ORIGINS,
            "CORS_ORIGINS contains '*', which lets any site call the API with a "
            "user's credentials.",
        )
        bad(
            not self.CORS_ORIGINS,
            "CORS_ORIGINS is empty, so the frontend cannot reach the API.",
        )
        bad(
            any(origin.startswith("http://") for origin in self.CORS_ORIGINS),
            "CORS_ORIGINS contains a plain-http origin; tokens would travel in clear.",
        )
        bad(
            self.FRONTEND_BASE_URL.startswith("http://"),
            "FRONTEND_BASE_URL is plain http, so emailed invite links would be "
            "insecure.",
        )
        return problems


class ConfigurationError(RuntimeError):
    """Raised at import time when production configuration is unsafe."""


@lru_cache
def get_settings() -> Settings:
    """Load settings, refusing to start a misconfigured production process.

    Failing at import is deliberate. Every check in `production_problems` is a
    fault that would otherwise be invisible at runtime — a health check would
    pass, requests would return 200, and nobody would find out until an
    employee's invitation never arrived. A container that will not start is a
    far cheaper failure than one that quietly does the wrong thing.
    """
    loaded = Settings()
    if loaded.is_production:
        problems = loaded.production_problems()
        if problems:
            listed = "\n".join(f"  - {problem}" for problem in problems)
            raise ConfigurationError(
                f"Refusing to start: {len(problems)} unsafe production setting(s).\n"
                f"{listed}\n"
                "Fix these, or set ENVIRONMENT=staging if this is not production."
            )
    return loaded


settings = get_settings()
