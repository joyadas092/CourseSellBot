from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
import uuid
from database.connection import DatabaseManager


class SubscriptionRepository:
    """Repository for managing user subscriptions, validity, invite links and expiry."""

    @classmethod
    def _collection(cls):
        if DatabaseManager.db is None:
            raise RuntimeError("Database is not connected")
        return DatabaseManager.db.subscriptions

    @classmethod
    async def create_subscription(
        cls,
        user_id: int,
        folder_id: str,
        folder_title: str,
        target_chat_id: int,
        plan_id: str,
        plan_label: str,
        days: int,
        amount: float,
        currency: str,
        gateway: str,
        pay_ref: str,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        is_demo: bool = False,
        duration_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create a new subscription record for a paid user or demo user (strictly idempotent on pay_ref)."""
        col = cls._collection()

        # Idempotency lock: If a subscription for this pay_ref already exists, return it!
        if pay_ref:
            existing = await col.find_one({"pay_ref": pay_ref})
            if existing:
                return existing

        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc)
        
        if is_demo or duration_seconds:
            secs = duration_seconds or 120
            valid_until = now + timedelta(seconds=secs)
        else:
            valid_until = now + timedelta(days=int(days))

        doc = {
            "subscription_id": sub_id,
            "user_id": int(user_id),
            "username": username,
            "full_name": full_name,
            "folder_id": folder_id,
            "folder_title": folder_title,
            "target_chat_id": int(target_chat_id),
            "plan_id": plan_id,
            "plan_label": plan_label,
            "days": int(days),
            "amount": float(amount),
            "currency": currency,
            "gateway": gateway,
            "pay_ref": pay_ref,
            "status": "active",  # Starts active upon payment or demo activation
            "is_demo": bool(is_demo),
            "duration_seconds": duration_seconds or (120 if is_demo else None),
            "invite_link": None,
            "invite_used": False,
            "created_at": now,
            "joined_at": None,
            "valid_until": valid_until,
            "reminders_sent": {
                "72h": False,
                "24h": False,
                "2h": False,
                "expired": False
            }
        }

        await col.insert_one(doc)
        return doc

    @classmethod
    async def get_by_id(cls, subscription_id: str) -> Optional[Dict[str, Any]]:
        """Find subscription by ID."""
        col = cls._collection()
        return await col.find_one({"subscription_id": subscription_id})

    @classmethod
    async def get_by_pay_ref(cls, pay_ref: str) -> Optional[Dict[str, Any]]:
        """Find subscription by payment reference."""
        if not pay_ref:
            return None
        col = cls._collection()
        return await col.find_one({"pay_ref": pay_ref})

    @classmethod
    async def get_active_subscription(cls, user_id: int, folder_id: str) -> Optional[Dict[str, Any]]:
        """Get currently active subscription for a specific user and course."""
        col = cls._collection()
        now = datetime.now(timezone.utc)
        return await col.find_one({
            "user_id": int(user_id),
            "folder_id": folder_id,
            "status": "active",
            "valid_until": {"$gt": now}
        })

    @classmethod
    async def get_by_invite_link(cls, chat_id: int, invite_link: str) -> Optional[Dict[str, Any]]:
        """Find subscription matching target chat ID and invite link."""
        col = cls._collection()
        return await col.find_one({
            "target_chat_id": int(chat_id),
            "invite_link": invite_link
        })

    @classmethod
    async def get_pending_user_subscription(cls, chat_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Find active subscription for user in target chat that hasn't joined yet."""
        col = cls._collection()
        return await col.find_one({
            "target_chat_id": int(chat_id),
            "user_id": int(user_id),
            "status": "active",
            "invite_used": False
        })

    @classmethod
    async def set_invite_link(cls, subscription_id: str, invite_link: str) -> bool:
        """Store the generated unique invite link."""
        col = cls._collection()
        result = await col.update_one(
            {"subscription_id": subscription_id},
            {"$set": {"invite_link": invite_link}}
        )
        return result.modified_count > 0

    @classmethod
    async def mark_joined(cls, subscription_id: str, start_now_seconds: Optional[int] = None) -> bool:
        """Mark subscription as joined and record timestamp. If start_now_seconds provided, sets valid_until from now."""
        col = cls._collection()
        now = datetime.now(timezone.utc)
        update_data: Dict[str, Any] = {
            "joined_at": now,
            "invite_used": True
        }
        if start_now_seconds:
            update_data["valid_until"] = now + timedelta(seconds=start_now_seconds)

        result = await col.update_one(
            {"subscription_id": subscription_id},
            {"$set": update_data}
        )
        return result.modified_count > 0

    @classmethod
    async def get_all_active_subscriptions(cls) -> List[Dict[str, Any]]:
        """Get all active subscriptions for the background expiry worker."""
        col = cls._collection()
        cursor = col.find({"status": "active"})
        return await cursor.to_list(length=5000)

    @classmethod
    async def mark_reminder_sent(cls, subscription_id: str, reminder_key: str) -> bool:
        """Mark a specific reminder (72h, 24h, 2h) as sent."""
        col = cls._collection()
        result = await col.update_one(
            {"subscription_id": subscription_id},
            {"$set": {f"reminders_sent.{reminder_key}": True}}
        )
        return result.modified_count > 0

    @classmethod
    async def mark_expired(cls, subscription_id: str) -> bool:
        """Set subscription status to expired."""
        col = cls._collection()
        result = await col.update_one(
            {"subscription_id": subscription_id},
            {"$set": {
                "status": "expired",
                "reminders_sent.expired": True
            }}
        )
        return result.modified_count > 0

    @classmethod
    async def extend_subscription(cls, subscription_id: str, additional_days: int) -> Optional[Dict[str, Any]]:
        """Extend subscription validity by N days."""
        sub = await cls.get_by_id(subscription_id)
        if not sub:
            return None

        col = cls._collection()
        now = datetime.now(timezone.utc)
        current_valid = sub["valid_until"]
        if current_valid.tzinfo is None:
            current_valid = current_valid.replace(tzinfo=timezone.utc)

        base_time = max(now, current_valid)
        new_valid = base_time + timedelta(days=int(additional_days))

        await col.update_one(
            {"subscription_id": subscription_id},
            {"$set": {
                "valid_until": new_valid,
                "status": "active",
                "reminders_sent.expired": False,
                "reminders_sent.2h": False,
                "reminders_sent.24h": False,
                "reminders_sent.72h": False
            }}
        )
        sub["valid_until"] = new_valid
        return sub

    @classmethod
    async def list_by_folder(cls, folder_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """List subscriptions for a specific course/folder."""
        col = cls._collection()
        cursor = col.find({"folder_id": folder_id}).sort("created_at", -1)
        return await cursor.to_list(length=limit)

    @classmethod
    async def list_by_user(cls, user_id: int) -> List[Dict[str, Any]]:
        """List all subscriptions belonging to a user."""
        col = cls._collection()
        cursor = col.find({"user_id": int(user_id)}).sort("created_at", -1)
        return await cursor.to_list(length=100)

    @classmethod
    async def get_active_premium_count(cls) -> int:
        """Count active paid premium subscribers (excluding demos)."""
        col = cls._collection()
        now = datetime.now(timezone.utc)
        return await col.count_documents({
            "status": "active",
            "valid_until": {"$gt": now},
            "is_demo": {"$ne": True}
        })

    @classmethod
    async def get_active_demo_count(cls) -> int:
        """Count currently active demo trials running right now."""
        col = cls._collection()
        now = datetime.now(timezone.utc)
        return await col.count_documents({
            "status": "active",
            "valid_until": {"$gt": now},
            "is_demo": True
        })

    @classmethod
    async def get_total_subscriptions_count(cls) -> int:
        """Total paid subscriptions created all-time."""
        col = cls._collection()
        return await col.count_documents({"is_demo": {"$ne": True}})

    @classmethod
    async def get_expired_subscriptions_count(cls) -> int:
        """Total expired paid subscriptions."""
        col = cls._collection()
        return await col.count_documents({"status": "expired", "is_demo": {"$ne": True}})

    @classmethod
    async def get_active_subscriber_user_ids(cls) -> List[int]:
        """Get distinct user IDs with an active paid subscription."""
        col = cls._collection()
        now = datetime.now(timezone.utc)
        ids = await col.distinct("user_id", {
            "status": "active",
            "valid_until": {"$gt": now},
            "is_demo": {"$ne": True}
        })
        return [int(x) for x in ids if str(x).isdigit()]

    @classmethod
    async def get_expired_subscriber_user_ids(cls) -> List[int]:
        """Get distinct user IDs with expired paid subscriptions."""
        col = cls._collection()
        ids = await col.distinct("user_id", {
            "status": "expired",
            "is_demo": {"$ne": True}
        })
        return [int(x) for x in ids if str(x).isdigit()]
