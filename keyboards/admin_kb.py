from typing import List, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def build_admin_main_keyboard() -> InlineKeyboardMarkup:
    """Main administrative dashboard keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📁 Manage Courses / Folders", callback_data="adm_folders_list"),
            InlineKeyboardButton(text="➕ Add New Folder", callback_data="adm_add_folder")
        ],
        [
            InlineKeyboardButton(text="👥 Active Subscribers", callback_data="adm_subscribers"),
            InlineKeyboardButton(text="💰 Recent Payments", callback_data="adm_payments")
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast Message", callback_data="adm_broadcast"),
            InlineKeyboardButton(text="📣 Join Request Promo", callback_data="adm_join_promo")
        ],
        [
            InlineKeyboardButton(text="⚙️ Bot Header & Settings", callback_data="adm_settings"),
            InlineKeyboardButton(text="🧪 Test Payment", callback_data="adm_test_payment")
        ]
    ])


def build_admin_join_promo_keyboard(promo_settings: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Keyboard for configuring external channel join request promotions."""
    is_enabled = promo_settings.get("enabled", True)
    delay_sec = int(promo_settings.get("delay_seconds", 0))
    has_banner = bool(promo_settings.get("banner_file_id"))

    toggle_btn = "🔴 Turn OFF Promo" if is_enabled else "🟢 Turn ON Promo"
    if delay_sec <= 0:
        delay_btn = "⚡ Delay: Instant"
    elif delay_sec < 60:
        delay_btn = f"⏱️ Delay: {delay_sec}s"
    else:
        delay_btn = f"⏱️ Delay: {delay_sec // 60}m"

    banner_btn = "🖼️ Change Banner" if has_banner else "🖼️ Add Banner Photo"

    keyboard = [
        [
            InlineKeyboardButton(text=toggle_btn, callback_data="adm_jp_toggle_enabled"),
            InlineKeyboardButton(text=delay_btn, callback_data="adm_jp_select_delay")
        ],
        [
            InlineKeyboardButton(text="📝 Edit Promo Text", callback_data="adm_jp_edit_text"),
            InlineKeyboardButton(text=banner_btn, callback_data="adm_jp_set_banner")
        ]
    ]
    if has_banner:
        keyboard.append([
            InlineKeyboardButton(text="🗑️ Remove Banner Photo", callback_data="adm_jp_del_banner")
        ])
    keyboard.append([
        InlineKeyboardButton(text="👁️ Live Preview Post", callback_data="adm_jp_preview")
    ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="adm_main_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_admin_promo_delay_keyboard() -> InlineKeyboardMarkup:
    """Select interval after which bot sends message to external join request users."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚡ Instant (0 sec)", callback_data="adm_jp_setdelay:0"),
            InlineKeyboardButton(text="⏱️ 30 Seconds", callback_data="adm_jp_setdelay:30")
        ],
        [
            InlineKeyboardButton(text="⏱️ 1 Minute", callback_data="adm_jp_setdelay:60"),
            InlineKeyboardButton(text="⏱️ 2 Minutes", callback_data="adm_jp_setdelay:120")
        ],
        [
            InlineKeyboardButton(text="⏱️ 5 Minutes", callback_data="adm_jp_setdelay:300"),
            InlineKeyboardButton(text="⏱️ 10 Minutes", callback_data="adm_jp_setdelay:600")
        ],
        [
            InlineKeyboardButton(text="🔙 Back to Promo Setup", callback_data="adm_join_promo")
        ]
    ])


def build_admin_folders_list(folders: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """List of all folders for admin editing."""
    keyboard: List[List[InlineKeyboardButton]] = []

    for fld in folders:
        status_dot = "🟢" if fld.get("is_active", True) else "🔴"
        btn_text = f"{status_dot} {fld.get('button_text') or fld.get('title')}"
        keyboard.append([
            InlineKeyboardButton(text=btn_text, callback_data=f"adm_edit_fld:{fld['folder_id']}")
        ])

    keyboard.append([
        InlineKeyboardButton(text="➕ Add New Folder", callback_data="adm_add_folder")
    ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="adm_main_menu")
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_admin_folder_edit_keyboard(folder: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Editing actions for a specific folder."""
    folder_id = folder["folder_id"]
    is_active = folder.get("is_active", True)
    toggle_text = "🔴 Deactivate" if is_active else "🟢 Activate"
    has_demo = folder.get("has_demo", True)
    demo_text = "🎁 2-Min Demo: ON" if has_demo else "🎁 2-Min Demo: OFF"
    width = folder.get("row_width", 2)
    width_text = "📐 Width: Half (2/row)" if width == 2 else "📐 Width: Full (1/row)"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Edit Title", callback_data=f"adm_fld_title:{folder_id}"),
            InlineKeyboardButton(text="🏷️ Edit Button Text", callback_data=f"adm_fld_btn:{folder_id}")
        ],
        [
            InlineKeyboardButton(text="📝 Edit Description", callback_data=f"adm_fld_desc:{folder_id}"),
            InlineKeyboardButton(text="🖼️ Set / Change Banner", callback_data=f"adm_fld_banner:{folder_id}")
        ],
        [
            InlineKeyboardButton(text="🆔 Set Channel/Group ID", callback_data=f"adm_fld_chat:{folder_id}"),
            InlineKeyboardButton(text="🎬 Set Preview Link (Optional)", callback_data=f"adm_fld_demo:{folder_id}")
        ],
        [
            InlineKeyboardButton(text="💵 Manage Pricing Plans", callback_data=f"adm_fld_plans:{folder_id}"),
            InlineKeyboardButton(text=width_text, callback_data=f"adm_fld_toggle_width:{folder_id}")
        ],
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"adm_fld_toggle_active:{folder_id}"),
            InlineKeyboardButton(text=demo_text, callback_data=f"adm_fld_toggle_demo:{folder_id}")
        ],
        [
            InlineKeyboardButton(text="🗑️ Delete Folder", callback_data=f"adm_fld_delete:{folder_id}"),
            InlineKeyboardButton(text="🔙 Back to Folders", callback_data="adm_folders_list")
        ]
    ])


def build_admin_plans_keyboard(folder: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Keyboard for managing pricing plans of a folder."""
    folder_id = folder["folder_id"]
    plans = folder.get("plans", [])
    keyboard: List[List[InlineKeyboardButton]] = []

    for p in plans:
        plan_id = p.get("plan_id")
        label = p.get("label", "Plan")
        days = p.get("days", 30)
        price_inr = p.get("price_inr", 0)
        keyboard.append([
            InlineKeyboardButton(
                text=f"🗑️ Delete: {label} ({days}d - ₹{price_inr})",
                callback_data=f"adm_del_plan:{folder_id}:{plan_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(text="➕ Add New Pricing Tier", callback_data=f"adm_add_plan:{folder_id}")
    ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Back to Folder", callback_data=f"adm_edit_fld:{folder_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_admin_manual_payment_keyboard(pay_ref: str, user_id: int) -> InlineKeyboardMarkup:
    """Approval and rejection buttons sent to admin when user submits payment proof."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve & Send Access Link", callback_data=f"adm_appr_pay:{pay_ref}")
        ],
        [
            InlineKeyboardButton(text="❌ Quick Reject", callback_data=f"adm_rej_quick:{pay_ref}"),
            InlineKeyboardButton(text="💬 Reject with Reason", callback_data=f"adm_rej_msg:{pay_ref}")
        ]
    ])
