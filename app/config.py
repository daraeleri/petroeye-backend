"""
Central settings for the PetroTwin backend, loaded from environment
variables / .env. Never hardcode connection strings or credentials
elsewhere in the codebase — import `settings` from here instead.
"""
from functools import cached_property
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

# Query parameters some hosted Postgres providers (e.g. Neon) put in their
# connection strings that asyncpg does not understand. TLS is enabled
# through `connect_args` instead (see `requires_ssl` and app/db/base.py).
_LIBPQ_ONLY_PARAMS = {"sslmode", "channel_binding"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/petroeye"
    # Neon: the direct (non-pooled) URL, used only for Alembic migrations.
    # `neon env pull` writes it; leave unset for a plain local Postgres.
    database_url_unpooled: str | None = None

    # --- MQTT ---------------------------------------------------------------
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_tls: bool = False
    # Stable client ID so the broker can keep a persistent session (QoS 1
    # messages are queued while the backend is briefly disconnected/asleep).
    mqtt_client_id: str = "petrotwin-backend"
    mqtt_enabled: bool = True

    # --- HTTP / CORS --------------------------------------------------------
    cors_origins: str = "http://localhost:3000"
    # Also allow any origin matching this regex: the production Vercel app and
    # its preview deployments (petroeye-frontend-<hash>-<team>.vercel.app).
    # Set to an empty string to rely on CORS_ORIGINS only.
    cors_origin_regex: str = r"https://petroeye-frontend(-[a-z0-9-]+)?\.vercel\.app"

    # --- Auth ---------------------------------------------------------------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 720
    # First admin, created on startup only if the users table is empty.
    admin_email: str | None = None
    admin_password: str | None = None

    # --- Fleet behaviour ----------------------------------------------------
    # Register unknown trucks automatically on their first MQTT message.
    # Convenient for the simulator; set to false once trucks are registered
    # through the API so unknown devices are rejected.
    auto_register_trucks: bool = True
    # A truck with no message for this long is shown as offline.
    offline_after_seconds: int = 120
    # Above this GPS speed the truck is considered moving.
    moving_speed_kmh: float = 3.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @cached_property
    def async_database_url(self) -> str:
        """`DATABASE_URL` normalised for SQLAlchemy + asyncpg (app traffic)."""
        return to_asyncpg_url(self.database_url)

    @cached_property
    def async_migration_url(self) -> str:
        """URL for Alembic. Neon's pooled endpoint (PgBouncer, transaction
        mode) must not be used for migrations, so prefer the direct
        `DATABASE_URL_UNPOOLED` when it is set."""
        return to_asyncpg_url(self.database_url_unpooled or self.database_url)


def to_asyncpg_url(url: str) -> str:
    """Accept the plain `postgres://` / `postgresql://` URLs hosted providers
    hand out and strip libpq-only query parameters asyncpg rejects."""
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    parts = urlsplit(url)
    query = parse_qsl(parts.query)
    if not any(k in _LIBPQ_ONLY_PARAMS for k, _ in query):
        return url
    kept = [(k, v) for k, v in query if k not in _LIBPQ_ONLY_PARAMS]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def requires_ssl(url: str) -> bool:
    query = dict(parse_qsl(urlsplit(url).query))
    return query.get("sslmode") in {"require", "verify-ca", "verify-full"}


def is_pgbouncer(url: str) -> bool:
    """Neon pooled endpoints have `-pooler` in the hostname."""
    return "-pooler." in (urlsplit(url).hostname or "")


settings = Settings()
