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
# through `connect_args` instead (see `database_requires_ssl`).
_LIBPQ_ONLY_PARAMS = {"sslmode", "channel_binding"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/petroeye"

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
        """`database_url` normalised for SQLAlchemy + asyncpg.

        Accepts the plain `postgres://` / `postgresql://` URLs hosted
        providers hand out and strips libpq-only query parameters.
        """
        url = self.database_url
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

    @cached_property
    def database_requires_ssl(self) -> bool:
        query = dict(parse_qsl(urlsplit(self.database_url).query))
        return query.get("sslmode") in {"require", "verify-ca", "verify-full"}


settings = Settings()
