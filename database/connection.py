import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import pymongo
from config import settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None

    @classmethod
    async def connect(cls):
        """Establish async connection to MongoDB and ensure indexes."""
        try:
            logger.info("Connecting to MongoDB...")
            cls.client = AsyncIOMotorClient(
                settings.MONGODB_URI,
                serverSelectionTimeoutMS=5000,
                maxPoolSize=50,
                minPoolSize=5
            )
            cls.db = cls.client[settings.MONGODB_DB_NAME]
            # Ping database
            await cls.client.admin.command("ping")
            logger.info(f"Successfully connected to MongoDB: {settings.MONGODB_DB_NAME}")
            await cls.create_indexes()
        except Exception as exc:
            logger.error(f"Failed to connect to MongoDB: {exc}")
            # Keep client instance so it can retry later without crashing
            pass

    @classmethod
    async def create_indexes(cls):
        """Create database indexes for query performance and data integrity."""
        if cls.db is None:
            return
        try:
            # Folders / Courses collection
            await cls.db.folders.create_index("folder_id", unique=True)
            await cls.db.folders.create_index([("is_active", pymongo.ASCENDING), ("order_index", pymongo.ASCENDING)])

            # Subscriptions collection
            await cls.db.subscriptions.create_index("subscription_id", unique=True)
            await cls.db.subscriptions.create_index("user_id")
            await cls.db.subscriptions.create_index("folder_id")
            await cls.db.subscriptions.create_index("status")
            await cls.db.subscriptions.create_index("valid_until")
            await cls.db.subscriptions.create_index("invite_link")

            # Payments collection
            await cls.db.payments.create_index("pay_ref", unique=True)
            await cls.db.payments.create_index("user_id")
            await cls.db.payments.create_index("status")

            # Users collection
            await cls.db.users.create_index("user_id", unique=True)

            # Bot Settings collection
            await cls.db.bot_settings.create_index("key", unique=True)
            logger.info("MongoDB indexes verified successfully.")
        except Exception as exc:
            logger.warning(f"Error creating indexes: {exc}")
