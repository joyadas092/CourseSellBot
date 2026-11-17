from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import uuid
from database.connection import DatabaseManager


class FolderRepository:
    """Repository for managing Courses / Folders / Catalog products."""

    @classmethod
    def _collection(cls):
        if DatabaseManager.db is None:
            raise RuntimeError("Database is not connected")
        return DatabaseManager.db.folders

    @classmethod
    async def create_folder(
        cls,
        title: str,
        button_text: str,
        description: str,
        target_chat_id: int,
        demo_url: Optional[str] = None,
        banner_file_id: Optional[str] = None,
        row_width: int = 2,
        plans: Optional[List[Dict[str, Any]]] = None,
        order_index: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create a new course/folder."""
        col = cls._collection()
        folder_id = f"fld_{uuid.uuid4().hex[:8]}"

        if order_index is None:
            count = await col.count_documents({})
            order_index = count + 1

        if plans is None:
            # Default standard pricing tier if none provided
            plans = [
                {"plan_id": "7d", "label": "7 Days", "days": 7, "price_inr": 49, "stars": 35, "price_usd": 0.99},
                {"plan_id": "1m", "label": "1 Month", "days": 30, "price_inr": 99, "stars": 75, "price_usd": 1.99},
                {"plan_id": "3m", "label": "3 Months", "days": 90, "price_inr": 199, "stars": 150, "price_usd": 3.99}
            ]

        doc = {
            "folder_id": folder_id,
            "title": title.strip(),
            "button_text": button_text.strip(),
            "description": description.strip(),
            "demo_url": demo_url.strip() if demo_url else None,
            "banner_file_id": banner_file_id,
            "target_chat_id": int(target_chat_id),
            "is_active": True,
            "has_demo": True,
            "row_width": int(row_width) if row_width in [1, 2] else 2,
            "plans": plans,
            "order_index": order_index,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }

        await col.insert_one(doc)
        return doc

    @classmethod
    async def get_folder(cls, folder_id: str) -> Optional[Dict[str, Any]]:
        """Get a folder by its unique folder_id."""
        col = cls._collection()
        return await col.find_one({"folder_id": folder_id})

    @classmethod
    async def get_all_folders(cls, only_active: bool = False) -> List[Dict[str, Any]]:
        """Retrieve all folders sorted by order_index."""
        col = cls._collection()
        query = {"is_active": True} if only_active else {}
        cursor = col.find(query).sort("order_index", 1)
        return await cursor.to_list(length=500)

    @classmethod
    async def update_folder(cls, folder_id: str, updates: Dict[str, Any]) -> bool:
        """Update folder properties."""
        col = cls._collection()
        updates["updated_at"] = datetime.now(timezone.utc)
        result = await col.update_one({"folder_id": folder_id}, {"$set": updates})
        return result.modified_count > 0

    @classmethod
    async def delete_folder(cls, folder_id: str) -> bool:
        """Permanently delete a folder."""
        col = cls._collection()
        result = await col.delete_one({"folder_id": folder_id})
        return result.deleted_count > 0

    @classmethod
    async def add_or_update_plan(cls, folder_id: str, plan_data: Dict[str, Any]) -> bool:
        """Add a new pricing tier or update an existing one by plan_id."""
        folder = await cls.get_folder(folder_id)
        if not folder:
            return False

        plans = folder.get("plans", [])
        plan_id = plan_data.get("plan_id") or f"plan_{uuid.uuid4().hex[:6]}"
        plan_data["plan_id"] = plan_id

        # Update if exists, else append
        updated = False
        for idx, p in enumerate(plans):
            if p.get("plan_id") == plan_id:
                plans[idx] = plan_data
                updated = True
                break

        if not updated:
            plans.append(plan_data)

        return await cls.update_folder(folder_id, {"plans": plans})

    @classmethod
    async def remove_plan(cls, folder_id: str, plan_id: str) -> bool:
        """Remove a pricing tier from a folder."""
        folder = await cls.get_folder(folder_id)
        if not folder:
            return False

        plans = [p for p in folder.get("plans", []) if p.get("plan_id") != plan_id]
        return await cls.update_folder(folder_id, {"plans": plans})

    @classmethod
    async def toggle_active(cls, folder_id: str) -> Optional[bool]:
        """Toggle active/inactive status."""
        folder = await cls.get_folder(folder_id)
        if not folder:
            return None
        new_status = not folder.get("is_active", True)
        await cls.update_folder(folder_id, {"is_active": new_status})
        return new_status

    @classmethod
    async def toggle_demo(cls, folder_id: str) -> Optional[bool]:
        """Toggle 2-minute free demo option on/off for this folder."""
        folder = await cls.get_folder(folder_id)
        if not folder:
            return None
        new_status = not folder.get("has_demo", True)
        await cls.update_folder(folder_id, {"has_demo": new_status})
        return new_status
