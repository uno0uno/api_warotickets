from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    # Database - mapeando desde las variables de warolabs
    database_url: str
    db_user: str = Field(alias='NUXT_PRIVATE_DB_USER')
    db_host: str = Field(alias='NUXT_PRIVATE_DB_HOST')
    db_password: str = Field(alias='NUXT_PRIVATE_DB_PASSWORD')
    db_port: int = Field(default=5432, alias='NUXT_PRIVATE_DB_PORT')
    db_name: str = Field(alias='NUXT_PRIVATE_DB_NAME')

    # JWT Security
    jwt_secret: str = Field(alias='NUXT_PRIVATE_JWT_SECRET')
    auth_secret: str = Field(alias='BETTER_AUTH_SECRET_KEY')
    token_backend: str = Field(alias='NUXT_PRIVATE_TOKEN_BACKEND')

    # AWS SES (para emails)
    aws_access_key_id: Optional[str] = Field(default=None, alias='NUXT_PRIVATE_AWS_ACCES_KEY_ID')
    aws_secret_access_key: Optional[str] = Field(default=None, alias='NUXT_PRIVATE_AWS_SECRET_ACCESS_KEY')
    aws_region: Optional[str] = Field(default=None, alias='NUXT_PRIVATE_AWS_REGION')
    email_from: Optional[str] = Field(default=None, alias='NUXT_PRIVATE_EMAIL_FROM')
    aws_ses_from_email: Optional[str] = Field(default=None, alias='AWS_SES_FROM_EMAIL')

    # Cloudflare R2 - S3-compatible storage
    r2_access_key_id: Optional[str] = Field(default=None, alias='NUXT_PRIVATE_R2_ACCESS_KEY_ID')
    r2_secret_access_key: Optional[str] = Field(default=None, alias='NUXT_PRIVATE_R2_SECRET_ACCESS_KEY')
    r2_endpoint: Optional[str] = Field(default=None, alias='NUXT_PRIVATE_R2_ENDPOINT')
    r2_bucket: str = Field(default='warotickets-assets', alias='NUXT_PRIVATE_R2_BUCKET')

    # Encryption
    private_key_encrypter: Optional[str] = Field(default=None, alias='NUXT_PRIVATE_PRIVATE_KEY_ENCRYPTER')
    public_key_encrypter: Optional[str] = Field(default=None, alias='NUXT_PUBLIC_PUBLIC_KEY_ENCRYPTER')

    # Wompi - Pasarela de pagos
    wompi_public_key: Optional[str] = Field(default=None, alias='WOMPI_PUBLIC_KEY')
    wompi_private_key: Optional[str] = Field(default=None, alias='WOMPI_PRIVATE_KEY')
    wompi_events_secret: Optional[str] = Field(default=None, alias='WOMPI_EVENTS_SECRET')
    wompi_environment: str = Field(default='sandbox', alias='WOMPI_ENVIRONMENT')

    # App settings
    environment: str = Field(default="development", alias='NODE_ENV')
    base_url: str = Field(default="http://localhost:8001", alias='NUXT_PUBLIC_BASE_URL')
    frontend_url: str = Field(default="http://localhost:3000", alias='FRONTEND_URL')

    # FastAPI specific
    port: int = Field(default=8001, alias='FASTAPI_PORT')
    host: str = Field(default="0.0.0.0", alias='FASTAPI_HOST')
    debug: bool = Field(default=True, alias='DEBUG')

    # CORS configuration
    cors_origins: str = Field(alias='CORS_ORIGINS')

    # Localhost to tenant mapping for development
    localhost_mapping: str = Field(default="", alias='LOCALHOST_MAPPING')

    # Discord webhooks
    discord_webhook_url: Optional[str] = Field(default=None, alias='DISCORD_WEBHOOK_URL')
    discord_error_webhook_url: Optional[str] = Field(default=None, alias='DISCORD_ERROR_WEBHOOK_URL')
    discord_sales_webhook_url: Optional[str] = Field(default=None, alias='DISCORD_SALES_WEBHOOK_URL')

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def db_connection_params(self) -> dict:
        return {
            "host": self.db_host,
            "port": self.db_port,
            "user": self.db_user,
            "password": self.db_password,
            "database": self.db_name,
        }

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

settings = Settings()
