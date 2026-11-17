import os
from typing import List, Union, Optional
from pydantic import Field, field_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram Bot Controller
    BOT_TOKEN: str = Field(default="", description="Telegram Bot API Token")
    BOT_USERNAME: str = Field(default="", description="Telegram Bot Username")

    # Superadmin Telegram user IDs (comma-separated or list)
    ADMIN_IDS: Union[List[int], str] = Field(
        default=[5886397642, 6417700277, 8725349820],
        description="Superadmin Telegram user IDs"
    )

    # Support Handle
    SUPPORT_USERNAME: str = Field(default="woxic_01", description="Support handle without @")

    # Audit & Log Channel
    LOG_CHANNEL_ID: Optional[Union[int, str]] = Field(default=None, description="Optional Log Channel ID")

    # MongoDB Connection
    MONGODB_URI: str = Field(
        default="mongodb://localhost:27017",
        validation_alias=AliasChoices("MONGODB_URI", "MONGO_URL"),
        description="Async MongoDB connection string"
    )
    MONGODB_DB_NAME: str = Field(default="CourseSellingBot", description="MongoDB Database Name")

    # Razorpay Payment Gateway
    RAZORPAY_KEY_ID: str = Field(default="", description="Razorpay Key ID")
    RAZORPAY_KEY_SECRET: str = Field(default="", description="Razorpay Key Secret")
    RAZORPAY_WEBHOOK_SECRET: str = Field(default="", description="Razorpay Webhook Secret")

    # PayPal Gateway
    PAYPAL_CLIENT_ID: str = Field(default="", description="PayPal Client ID")
    PAYPAL_CLIENT_SECRET: str = Field(default="", description="PayPal Client Secret")
    PAYPAL_MODE: str = Field(default="live", description="PayPal mode: live or sandbox")

    # Crypto Wallets
    CRYPTO_USDT_BEP20: str = Field(default="", description="USDT BEP-20 receiving address")
    CRYPTO_TON_ADDRESS: str = Field(default="", description="TON receiving address")

    # Manual UPI Gateway
    MANUAL_UPI_ID: str = Field(default="", description="Direct UPI VPA")
    MANUAL_UPI_NAME: str = Field(default="", description="Direct UPI Payee Name")

    # Default Catalog Headers
    CATALOG_HEADER: str = Field(
        default=(
            "🛍️ <b>Select a product to get started:</b>\n\n"
            "☘️ <i>Trust issues? Claim Free demo Now</i>\n\n"
            "<i>Type /privacy to read our privacy policy</i>"
        ),
        description="Default text shown on /start"
    )

    # Expiry Check Interval (seconds - default 20s for fast demo & subscription checks)
    EXPIRY_CHECK_INTERVAL: int = Field(default=20, description="Seconds between subscription expiry checks")

    # Web Server configuration (for Render Web Service & Health Checks)
    PORT: int = Field(default=8000, validation_alias=AliasChoices("PORT", "WEB_PORT"), description="HTTP port for web server")
    WEB_HOST: str = Field(default="0.0.0.0", description="Bind host for web server")

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip().isdigit()]
        if isinstance(v, int):
            return [v]
        return v or []

    @field_validator("LOG_CHANNEL_ID", mode="before")
    @classmethod
    def parse_log_channel(cls, v):
        if not v or str(v).strip() == "":
            return None
        try:
            return int(str(v).strip())
        except ValueError:
            return str(v).strip()


settings = Settings()
