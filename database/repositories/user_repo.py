from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from database.connection import DatabaseManager


class UserRepository:
    """Repository for managing Telegram users and overall stats."""

    @classmethod
    def _collection(cls):
        if DatabaseManager.db is None:
            raise RuntimeError("Database is not connected")
        return DatabaseManager.db.users

    @classmethod
    async def get_or_create(cls, user_id: int, username: Optional[str] = None, full_name: Optional[str] = None) -> Dict[str, Any]:
        """Get or create user record."""
        col = cls._collection()
        user = await col.find_one({"user_id": int(user_id)})
        now = datetime.now(timezone.utc)
        if not user:
            user = {
                "user_id": int(user_id),
                "username": username,
                "full_name": full_name,
                "created_at": now,
                "last_active": now,
                "total_orders": 0,
                "total_spent_inr": 0.0
            }
            await col.insert_one(user)
        else:
            await col.update_one(
                {"user_id": int(user_id)},
                {"$set": {
                    "last_active": now,
                    "username": username,
                    "full_name": full_name
                }}
            )
        return user

    @classmethod
    async def get_user_count(cls) -> int:
        """Total user count."""
        col = cls._collection()
        return await col.count_documents({})

    @classmethod
    async def get_all_user_ids(cls) -> List[int]:
        """Get list of all user IDs for broadcast."""
        col = cls._collection()
        cursor = col.find({}, {"user_id": 1})
        docs = await cursor.to_list(length=100000)
        return [d["user_id"] for d in docs if "user_id" in d]

    @classmethod
    async def get_demo_user_ids(cls) -> List[int]:
        """Get list of users who claimed the free demo trial."""
        col = cls._collection()
        cursor = col.find({"has_used_demo": True}, {"user_id": 1})
        docs = await cursor.to_list(length=100000)
        return [d["user_id"] for d in docs if "user_id" in d]

    @classmethod
    async def record_purchase(cls, user_id: int, amount_inr: float):
        """Update purchase stats for a user."""
        col = cls._collection()
        await col.update_one(
            {"user_id": int(user_id)},
            {
                "$inc": {
                    "total_orders": 1,
                    "total_spent_inr": float(amount_inr)
                }
            }
        )

    @classmethod
    async def has_used_demo(cls, user_id: int) -> bool:
        """Check if user has already consumed their lifetime free demo trial."""
        col = cls._collection()
        user = await col.find_one({"user_id": int(user_id)})
        if not user:
            return False
        return bool(user.get("has_used_demo", False))

    @classmethod
    async def mark_demo_used(cls, user_id: int, folder_id: str) -> bool:
        """Mark the lifetime demo as consumed for this user."""
        col = cls._collection()
        now = datetime.now(timezone.utc)
        result = await col.update_one(
            {"user_id": int(user_id)},
            {
                "$set": {
                    "has_used_demo": True,
                    "demo_used_at": now,
                    "demo_folder_id": folder_id
                }
            },
            upsert=True
        )
        return result.modified_count > 0 or result.upserted_id is not None

    @classmethod
    async def reset_demo(cls, user_id: int) -> bool:
        """Reset demo usage for a user (admin capability)."""
        col = cls._collection()
        result = await col.update_one(
            {"user_id": int(user_id)},
            {
                "$set": {
                    "has_used_demo": False,
                    "demo_reset_at": datetime.now(timezone.utc)
                }
            }
        )
        return result.modified_count > 0
