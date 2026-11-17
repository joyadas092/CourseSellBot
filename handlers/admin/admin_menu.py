import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import settings
from database.repositories.folder_repo import FolderRepository
from database.repositories.subscription_repo import SubscriptionRepository
from database.repositories.payment_repo import PaymentRepository
from database.repositories.user_repo import UserRepository
from database.repositories.settings_repo import SettingsRepository
from keyboards.admin_kb import build_admin_main_keyboard
from handlers.payments import activate_access_for_user

logger = logging.getLogger(__name__)

router = Router(name="admin_menu_router")


class AdminSettingsStates(StatesGroup):
    waiting_for_header = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Admin dashboard command."""
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Unauthorized access.")
        return

    total_folders = len(await FolderRepository.get_all_folders())
    total_users = await UserRepository.get_user_count()
    active_subs = len(await SubscriptionRepository.get_all_active_subscriptions())
    recent_payments = await PaymentRepository.get_recent_payments(limit=50)
    total_revenue = sum(p.get("amount", 0) for p in recent_payments if p.get("status") == "paid" and p.get("currency") == "INR")

    text = (
        "👑 <b>Admin Control Dashboard</b>\n\n"
        f"📁 <b>Total Courses / Folders:</b> <code>{total_folders}</code>\n"
        f"👥 <b>Active Subscribers:</b> <code>{active_subs}</code>\n"
        f"👤 <b>Total Registered Users:</b> <code>{total_users}</code>\n"
        f"💰 <b>Total Recorded Revenue:</b> ₹<code>{total_revenue:,.2f}</code>\n\n"
        "<i>Select an option below to manage courses, pricing, and members:</i>"
    )

    await message.reply(text, reply_markup=build_admin_main_keyboard())


@router.callback_query(F.data == "adm_main_menu")
async def cb_adm_main_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    await state.clear()
    total_folders = len(await FolderRepository.get_all_folders())
    total_users = await UserRepository.get_user_count()
    active_subs = len(await SubscriptionRepository.get_all_active_subscriptions())
    recent_payments = await PaymentRepository.get_recent_payments(limit=50)
    total_revenue = sum(p.get("amount", 0) for p in recent_payments if p.get("status") == "paid" and p.get("currency") == "INR")

    text = (
        "👑 <b>Admin Control Dashboard</b>\n\n"
        f"📁 <b>Total Courses / Folders:</b> <code>{total_folders}</code>\n"
        f"👥 <b>Active Subscribers:</b> <code>{active_subs}</code>\n"
        f"👤 <b>Total Registered Users:</b> <code>{total_users}</code>\n"
        f"💰 <b>Total Recorded Revenue:</b> ₹<code>{total_revenue:,.2f}</code>\n\n"
        "<i>Select an option below to manage courses, pricing, and members:</i>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=build_admin_main_keyboard())
    except Exception:
        await callback.message.reply(text, reply_markup=build_admin_main_keyboard())
    await callback.answer()


@router.callback_query(F.data == "adm_subscribers")
async def cb_adm_subscribers(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    active_subs = await SubscriptionRepository.get_all_active_subscriptions()
    if not active_subs:
        await callback.answer("No active subscribers currently.", show_alert=True)
        return

    lines = ["👥 <b>Active Subscribers:</b>\n"]
    for s in active_subs[:25]:
        v = s.get("valid_until")
        v_str = v.strftime("%d %b %Y") if v else "N/A"
        joined_icon = "✅ Joined" if s.get("invite_used") else "⏳ Not Joined"
        lines.append(
            f"• User <code>{s.get('user_id')}</code> (@{s.get('username') or 'N/A'})\n"
            f"  Course: <b>{s.get('folder_title')}</b> ({s.get('plan_label')})\n"
            f"  Status: {joined_icon} | Expiry: <code>{v_str}</code>\n"
        )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm_main_menu")]
    ])
    await callback.message.reply("\n".join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "adm_payments")
async def cb_adm_payments(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    payments = await PaymentRepository.get_recent_payments(limit=15)
    if not payments:
        await callback.answer("No payments recorded yet.", show_alert=True)
        return

    lines = ["💰 <b>Latest 15 Transactions:</b>\n"]
    for p in payments:
        st = "🟢 Paid" if p.get("status") == "paid" else "🟡 Pending"
        amt = p.get("amount", 0)
        curr = p.get("currency", "INR")
        gw = p.get("gateway", "N/A")
        lines.append(
            f"• <code>{p.get('pay_ref')}</code> | User: <code>{p.get('user_id')}</code>\n"
            f"  {st} | {amt} {curr} ({gw})\n"
        )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm_main_menu")]
    ])
    await callback.message.reply("\n".join(lines), reply_markup=kb)
    await callback.answer()


# ==========================================
# Settings & Catalog Header Editor
# ==========================================

@router.callback_query(F.data == "adm_settings")
async def cb_adm_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    current_header = await SettingsRepository.get_catalog_header()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Change Catalog Header", callback_data="adm_edit_header")],
        [InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="adm_main_menu")]
    ])

    text = (
        "⚙️ <b>Bot Settings & Store Header</b>\n\n"
        f"<b>Current Catalog Header Text:</b>\n"
        f"<blockquote>{current_header}</blockquote>\n\n"
        "Tap below to modify the header text shown on /start."
    )
    await callback.message.reply(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "adm_edit_header")
async def cb_adm_edit_header(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    await state.set_state(AdminSettingsStates.waiting_for_header)
    await callback.message.reply("📝 <b>Send the new catalog header text for /start (supports HTML):</b>")
    await callback.answer()


@router.message(AdminSettingsStates.waiting_for_header)
async def process_new_header(message: Message, state: FSMContext):
    new_header = message.html_text or message.text
    await SettingsRepository.set_catalog_header(new_header)
    await state.clear()
    await message.reply("✅ <b>Catalog header updated successfully!</b>\nTest it by sending /start.")


@router.message(Command("resetdemo"))
async def cmd_reset_demo(message: Message):
    """Admin command to reset lifetime demo for a user: /resetdemo <user_id>"""
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Unauthorized access.")
        return

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.reply("ℹ️ Usage: <code>/resetdemo &lt;user_id&gt;</code>")
        return

    target_user_id = int(parts[1])
    await UserRepository.reset_demo(target_user_id)
    await message.reply(f"✅ Demo usage reset for user <code>{target_user_id}</code>! They can now claim the free demo once again.")
