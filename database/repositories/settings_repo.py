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
