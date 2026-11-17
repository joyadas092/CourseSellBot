from typing import List, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import settings


def build_catalog_keyboard(folders: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Builds the main catalog inline keyboard matching Screenshot 1:
    Supports 1-column (full width) or 2-column buttons per row based on folder configuration.
    """
    keyboard: List[List[InlineKeyboardButton]] = []
    current_row: List[InlineKeyboardButton] = []

    for fld in folders:
        btn_text = fld.get("button_text") or fld.get("title")
        btn = InlineKeyboardButton(text=btn_text, callback_data=f"fld_view:{fld['folder_id']}")
        width = fld.get("row_width", 2)

        if width == 1:
            # Flush current row if partially filled
            if current_row:
                keyboard.append(current_row)
                current_row = []
            keyboard.append([btn])
        else:
            current_row.append(btn)
            if len(current_row) >= 2:
                keyboard.append(current_row)
                current_row = []

    if current_row:
        keyboard.append(current_row)

    # Footer navigation buttons
    keyboard.append([
        InlineKeyboardButton(text="👤 My Subscriptions", callback_data="my_subscriptions"),
        InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_folder_details_keyboard(folder: Dict[str, Any], has_used_demo: bool = False) -> InlineKeyboardMarkup:
    """
    Builds the folder detail view inline keyboard matching Screenshot 2:
    Renders free demo plan (2 mins) and dynamic pricing tiers (e.g. 7 Days - ₹49, 1 Month - ₹99, etc.)
    """
    keyboard: List[List[InlineKeyboardButton]] = []
    folder_id = folder["folder_id"]

    # Free Demo Plan (2 Minutes) Button
    if folder.get("has_demo", True):
        demo_btn_text = "🎁 Claim Free Demo (2 Mins)" if not has_used_demo else "🔒 Free Demo (Already Consumed)"
        keyboard.append([
            InlineKeyboardButton(text=demo_btn_text, callback_data=f"claim_demo:{folder_id}")
        ])

    plans = folder.get("plans", [])
    current_row: List[InlineKeyboardButton] = []
    for plan in plans:
        plan_id = plan.get("plan_id")
        label = plan.get("label", "Plan")
        price_inr = plan.get("price_inr", 0)
        btn_text = f"{label} - ₹{price_inr}"

        btn = InlineKeyboardButton(
            text=btn_text,
            callback_data=f"buy_plan:{folder_id}:{plan_id}"
        )

        current_row.append(btn)
        if len(current_row) >= 2:
            keyboard.append(current_row)
            current_row = []

    if current_row:
        keyboard.append(current_row)

    # Optional Demo Link button
    demo_url = folder.get("demo_url")
    extra_row: List[InlineKeyboardButton] = []
    if demo_url:
        extra_row.append(InlineKeyboardButton(text="🎬 Watch Demo", url=demo_url))

    extra_row.append(InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}"))
    keyboard.append(extra_row)

    # Back to catalog button
    keyboard.append([
        InlineKeyboardButton(text="🔙 Back to Products", callback_data="back_catalog")
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_payment_methods_keyboard(folder_id: str, plan_id: str, plan: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Builds payment methods selection menu."""
    price_inr = plan.get("price_inr", 0)
    stars = plan.get("stars", max(1, int(price_inr * 0.75)))
    price_usd = plan.get("price_usd", round(price_inr / 85.0, 2))

    buttons = [
        [
            InlineKeyboardButton(
                text=f"📱 Pay with UPI QR (₹{price_inr})",
                callback_data=f"pay_upiqr:{folder_id}:{plan_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"💳 Pay with Cards / NetBanking (₹{price_inr})",
                callback_data=f"pay_cards:{folder_id}:{plan_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"⭐ Pay with Telegram Stars ({stars} ⭐️)",
                callback_data=f"pay_stars:{folder_id}:{plan_id}"
            )
        ]
    ]

    # PayPal Gateway if configured
    if settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET:
        buttons.append([
            InlineKeyboardButton(
                text=f"🅿️ Pay with PayPal (${price_usd} USD)",
                callback_data=f"pay_paypal:{folder_id}:{plan_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text=f"🪙 Pay with Crypto (${price_usd} USDT / TON)",
            callback_data=f"pay_crypto:{folder_id}:{plan_id}"
        )
    ])

    # Direct / Manual UPI
    buttons.append([
        InlineKeyboardButton(
            text=f"⚡ Direct UPI Transfer (₹{price_inr})",
            callback_data=f"pay_manual:{folder_id}:{plan_id}"
        )
    ])

    buttons.append([
        InlineKeyboardButton(text="🔙 Back to Plans", callback_data=f"fld_view:{folder_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_payment_action_keyboard(pay_ref: str) -> InlineKeyboardMarkup:
    """Action keyboard shown beneath active UPI QR or payment link."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ I Have Paid", callback_data=f"checkpay:{pay_ref}")],
        [
            InlineKeyboardButton(text="💬 24/7 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancelpay:{pay_ref}")
        ]
    ])
