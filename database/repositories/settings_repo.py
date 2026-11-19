from typing import Optional, Dict, Any
from database.connection import DatabaseManager
from config import settings


class SettingsRepository:
    """Repository for dynamic bot settings (header text, review links, etc.)."""

    @classmethod
    def _collection(cls):
        if DatabaseManager.db is None:
            raise RuntimeError("Database is not connected")
        return DatabaseManager.db.bot_settings

    @classmethod
    async def get_setting(cls, key: str, default: Any = None) -> Any:
        col = cls._collection()
        doc = await col.find_one({"key": key})
        if doc and "value" in doc:
            return doc["value"]
        return default

    @classmethod
    async def set_setting(cls, key: str, value: Any) -> bool:
        col = cls._collection()
        await col.update_one(
            {"key": key},
            {"$set": {"key": key, "value": value}},
            upsert=True
        )
        return True

    @classmethod
    async def get_catalog_header(cls) -> str:
        return await cls.get_setting("catalog_header", settings.CATALOG_HEADER)

    @classmethod
    async def set_catalog_header(cls, text: str) -> bool:
        return await cls.set_setting("catalog_header", text)

    @classmethod
    async def get_support_username(cls) -> str:
        return await cls.get_setting("support_username", settings.SUPPORT_USERNAME)

    @classmethod
    async def get_join_promo_settings(cls) -> Dict[str, Any]:
        """Fetch settings for Join Request Welcome Promotion on external groups/channels."""
        default_text = (
            "👋 <b>Welcome {name}!</b>\n\n"
            "Thank you for requesting to join <b>{channel}</b>.\n\n"
            "🔥 <b>Looking for Exclusive VIP Content & Premium Courses?</b>\n"
            "We offer top-rated premium access, courses, and VIP channels with instant automated activation!\n\n"
            "✨ <b>Why Join Us?</b>\n"
            "• ⚡ Instant automated single-use link delivery\n"
            "• 🎁 Free 2-Minute Demo preview available\n"
            "• 💳 Multiple easy payment options (UPI, PayPal, Crypto, Stars)\n"
            "• 🛡️ 100% Private, Safe & Verified\n\n"
            "👇 <b>Explore our catalog below to see everything we offer:</b>"
        )
        return {
            "enabled": await cls.get_setting("join_promo_enabled", True),
            "auto_approve": await cls.get_setting("join_promo_auto_approve", True),
            "text": await cls.get_setting("join_promo_text", default_text),
            "banner_file_id": await cls.get_setting("join_promo_banner", None)
        }

    @classmethod
    async def set_join_promo_setting(cls, field: str, value: Any) -> bool:
        """Update a specific join promo setting."""
        key_map = {
            "enabled": "join_promo_enabled",
            "auto_approve": "join_promo_auto_approve",
            "text": "join_promo_text",
            "banner": "join_promo_banner"
        }
        db_key = key_map.get(field, f"join_promo_{field}")
        return await cls.set_setting(db_key, value)
