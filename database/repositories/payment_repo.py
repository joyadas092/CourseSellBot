from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from database.connection import DatabaseManager


class PaymentRepository:
    """Repository for recording and querying payment transactions."""

    @classmethod
    def _collection(cls):
        if DatabaseManager.db is None:
            raise RuntimeError("Database is not connected")
        return DatabaseManager.db.payments

    @classmethod
    async def create_payment(
        cls,
        pay_ref: str,
        user_id: int,
        folder_id: str,
        plan_id: str,
        amount: float,
        currency: str = "INR",
        gateway: str = "razorpay_upiqr",
        order_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        username: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new pending payment entry."""
        col = cls._collection()
        now = datetime.now(timezone.utc)
        doc = {
            "pay_ref": pay_ref,
            "user_id": int(user_id),
            "username": username,
            "folder_id": folder_id,
            "plan_id": plan_id,
            "amount": float(amount),
            "currency": currency.upper(),
            "gateway": gateway,
            "order_id": order_id,
            "payment_id": None,
            "status": "pending",
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now
        }
        await col.insert_one(doc)
        return doc

    @classmethod
    async def get_by_ref(cls, pay_ref: str) -> Optional[Dict[str, Any]]:
        """Retrieve payment record by reference string."""
        col = cls._collection()
        return await col.find_one({"pay_ref": pay_ref})

    @classmethod
    async def claim_payment_session(
        cls,
        pay_ref: str,
        payment_id: str,
        gateway: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Atomically transition payment status from pending to paid.
        Guarantees that a payment can only be claimed and fulfilled ONCE.
        If already paid, expired, rejected, or cancelled, returns False.
        """
        col = cls._collection()
        now = datetime.now(timezone.utc)
        updates = {
            "status": "paid",
            "payment_id": payment_id,
            "paid_at": now,
            "updated_at": now
        }
        if gateway:
            updates["gateway"] = gateway
        if metadata_update:
            for k, v in metadata_update.items():
                updates[f"metadata.{k}"] = v
        result = await col.update_one(
            {
                "pay_ref": pay_ref,
                "status": {"$nin": ["paid", "expired", "rejected", "cancelled"]}
            },
            {"$set": updates}
        )
        return result.modified_count > 0

    @classmethod
    async def is_payment_id_already_fulfilled(cls, payment_id: str, exclude_pay_ref: str = "") -> bool:
        """Check if this gateway payment_id was already fulfilled in another payment record."""
        if not payment_id:
            return False
        col = cls._collection()
        query: Dict[str, Any] = {"payment_id": payment_id, "status": "paid"}
        if exclude_pay_ref:
            query["pay_ref"] = {"$ne": exclude_pay_ref}
        doc = await col.find_one(query, {"_id": 1})
        return bool(doc)

    @classmethod
    async def mark_paid(
        cls,
        pay_ref: str,
        payment_id: str,
        gateway: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Mark a payment transaction as paid atomically if not already paid."""
        col = cls._collection()
        now = datetime.now(timezone.utc)
        updates = {
            "status": "paid",
            "payment_id": payment_id,
            "updated_at": now
        }
        if gateway:
            updates["gateway"] = gateway
        if metadata_update:
            for k, v in metadata_update.items():
                updates[f"metadata.{k}"] = v
        result = await col.update_one({"pay_ref": pay_ref, "status": {"$ne": "paid"}}, {"$set": updates})
        return result.modified_count > 0

    @classmethod
    async def mark_rejected(cls, pay_ref: str, reason: str = "") -> bool:
        """Mark a payment transaction as rejected with an optional reason."""
        col = cls._collection()
        updates = {
            "status": "rejected",
            "rejection_reason": reason,
            "updated_at": datetime.now(timezone.utc)
        }
        result = await col.update_one({"pay_ref": pay_ref}, {"$set": updates})
        return result.modified_count > 0

    @classmethod
    async def update_metadata(cls, pay_ref: str, metadata_updates: Dict[str, Any]) -> bool:
        """Update payment metadata (e.g. telegram post chat & message id for auto deletion)."""
        col = cls._collection()
        updates = {
            f"metadata.{k}": v for k, v in metadata_updates.items()
        }
        updates["updated_at"] = datetime.now(timezone.utc)
        result = await col.update_one({"pay_ref": pay_ref}, {"$set": updates})
        return result.modified_count > 0

    @classmethod
    async def get_recent_payments(cls, limit: int = 50) -> List[Dict[str, Any]]:
        """Get latest payments for admin review."""
        col = cls._collection()
        cursor = col.find().sort("created_at", -1)
        return await cursor.to_list(length=limit)
