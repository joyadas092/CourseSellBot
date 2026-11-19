import html
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import settings
from database.repositories.folder_repo import FolderRepository
from database.repositories.subscription_repo import SubscriptionRepository
from database.repositories.payment_repo import PaymentRepository
from database.repositories.user_repo import UserRepository
from database.repositories.settings_repo import SettingsRepository
from keyboards.admin_kb import build_admin_main_keyboard, build_admin_join_promo_keyboard

logger = logging.getLogger(__name__)

router = Router(name="admin_menu_router")


class AdminSettingsStates(StatesGroup):
    waiting_for_header = State()
    waiting_for_join_promo_text = State()
    waiting_for_join_promo_banner = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


async def build_status_dashboard_text() -> str:
    """Builds comprehensive real-time statistics for /status and /admin."""
    total_users = await UserRepository.get_user_count()
    total_demos_claimed = await UserRepository.get_total_demo_claimed_count()
    active_demos = await SubscriptionRepository.get_active_demo_count()
    active_premium = await SubscriptionRepository.get_active_premium_count()
    total_subs_all = await SubscriptionRepository.get_total_subscriptions_count()
    expired_subs = await SubscriptionRepository.get_expired_subscriptions_count()

    folders = await FolderRepository.get_all_folders()
    active_folders = sum(1 for f in folders if f.get("is_active", True))

    revenue_stats = await PaymentRepository.get_total_revenue_stats()
    total_revenue_inr = revenue_stats.get("INR", 0.0)
    total_paid_orders = await PaymentRepository.get_paid_count()

    promo_settings = await SettingsRepository.get_join_promo_settings()
    promo_status = "🟢 Enabled (Active)" if promo_settings.get("enabled", True) else "🔴 Disabled (Off)"
    promo_auto = "⚡ Auto-Approve: ON" if promo_settings.get("auto_approve", True) else "⚡ Auto-Approve: OFF"

    rzp_status = "🟢 Active" if settings.RAZORPAY_KEY_ID else "⚪ Not Configured"
    pp_status = "🟢 Active" if settings.PAYPAL_CLIENT_ID else "⚪ Not Configured"

    return (
        "📊 <b>Bot Real-Time Status & Analytics</b>\n\n"
        "👥 <b>User & Subscription Metrics:</b>\n"
        f"• 👤 <b>Total Registered Users:</b> <code>{total_users:,}</code>\n"
        f"• 👑 <b>Active Premium Subscribers:</b> <code>{active_premium:,}</code>\n"
        f"• 🎁 <b>Total Free Demos Claimed:</b> <code>{total_demos_claimed:,}</code>\n"
        f"• ⚡ <b>Demos Active Right Now:</b> <code>{active_demos:,}</code>\n"
        f"• ⌛ <b>Expired Subscribers:</b> <code>{expired_subs:,}</code>\n"
        f"• 📦 <b>All-Time Subscriptions:</b> <code>{total_subs_all:,}</code>\n\n"
        "📁 <b>Courses & Catalogs:</b>\n"
        f"• <b>Total Courses / Folders:</b> <code>{len(folders)}</code>\n"
        f"• <b>Active Visible Courses:</b> <code>{active_folders}</code>\n\n"
        "💰 <b>Financial Performance:</b>\n"
        f"• <b>Total Revenue (INR):</b> ₹<code>{total_revenue_inr:,.2f}</code>\n"
        f"• <b>Total Paid Orders:</b> <code>{total_paid_orders:,}</code>\n\n"
        "🌐 <b>Promotion & Gateway Status:</b>\n"
        f"• <b>Join Request Promo:</b> <code>{promo_status}</code> ({promo_auto})\n"
        f"• <b>Razorpay UPI QR:</b> <code>{rzp_status}</code>\n"
        f"• <b>PayPal:</b> <code>{pp_status}</code>\n"
        "• <b>Telegram Stars:</b> <code>🟢 Active</code>\n"
        "• <b>Manual UPI & Crypto:</b> <code>🟢 Active</code>"
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Real-time system status command."""
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Unauthorized access.")
        return

    text = await build_status_dashboard_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Refresh Status", callback_data="adm_refresh_status"),
            InlineKeyboardButton(text="📢 Broadcast", callback_data="adm_broadcast")
        ],
        [
            InlineKeyboardButton(text="👑 Admin Dashboard", callback_data="adm_main_menu"),
            InlineKeyboardButton(text="👥 Subscribers", callback_data="adm_subscribers")
        ]
    ])
    await message.reply(text, reply_markup=kb)


@router.callback_query(F.data == "adm_refresh_status")
async def cb_refresh_status(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return
    text = await build_status_dashboard_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Refresh Status", callback_data="adm_refresh_status"),
            InlineKeyboardButton(text="📢 Broadcast", callback_data="adm_broadcast")
        ],
        [
            InlineKeyboardButton(text="👑 Admin Dashboard", callback_data="adm_main_menu"),
            InlineKeyboardButton(text="👥 Subscribers", callback_data="adm_subscribers")
        ]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer("Status refreshed!")


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Admin dashboard command."""
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Unauthorized access.")
        return

    total_folders = len(await FolderRepository.get_all_folders())
    total_users = await UserRepository.get_user_count()
    active_premium = await SubscriptionRepository.get_active_premium_count()
    total_demos = await UserRepository.get_total_demo_claimed_count()
    revenue_stats = await PaymentRepository.get_total_revenue_stats()
    total_revenue = revenue_stats.get("INR", 0.0)

    text = (
        "👑 <b>Admin Control Dashboard</b>\n\n"
        f"📁 <b>Total Courses / Folders:</b> <code>{total_folders}</code>\n"
        f"👑 <b>Active Premium Subscribers:</b> <code>{active_premium}</code>\n"
        f"🎁 <b>Total Demos Claimed:</b> <code>{total_demos}</code>\n"
        f"👤 <b>Total Registered Users:</b> <code>{total_users}</code>\n"
        f"💰 <b>Total Recorded Revenue:</b> ₹<code>{total_revenue:,.2f}</code>\n\n"
        "<i>Select an option below to manage courses, broadcast, promo & pricing:</i>"
    )

    await message.reply(text, reply_markup=build_admin_main_keyboard())


@router.callback_query(F.data == "adm_main_menu")
async def cb_adm_main_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    if state:
        await state.clear()
    total_folders = len(await FolderRepository.get_all_folders())
    total_users = await UserRepository.get_user_count()
    active_premium = await SubscriptionRepository.get_active_premium_count()
    total_demos = await UserRepository.get_total_demo_claimed_count()
    revenue_stats = await PaymentRepository.get_total_revenue_stats()
    total_revenue = revenue_stats.get("INR", 0.0)

    text = (
        "👑 <b>Admin Control Dashboard</b>\n\n"
        f"📁 <b>Total Courses / Folders:</b> <code>{total_folders}</code>\n"
        f"👑 <b>Active Premium Subscribers:</b> <code>{active_premium}</code>\n"
        f"🎁 <b>Total Demos Claimed:</b> <code>{total_demos}</code>\n"
        f"👤 <b>Total Registered Users:</b> <code>{total_users}</code>\n"
        f"💰 <b>Total Recorded Revenue:</b> ₹<code>{total_revenue:,.2f}</code>\n\n"
        "<i>Select an option below to manage courses, broadcast, promo & pricing:</i>"
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


# ==========================================
# Join Request Promo Configuration
# ==========================================

@router.callback_query(F.data == "adm_join_promo")
async def cb_adm_join_promo(callback: CallbackQuery, state: FSMContext = None):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return
    if state:
        await state.clear()
    promo = await SettingsRepository.get_join_promo_settings()
    st = "🟢 Enabled (Active)" if promo.get("enabled", True) else "🔴 Disabled (Off)"
    ap = "🟢 ON (Instant Entry)" if promo.get("auto_approve", True) else "🔴 OFF (Manual)"
    banner_st = "✅ Photo Attached" if promo.get("banner_file_id") else "❌ No Photo (Text Only)"

    text = (
        "📣 <b>Join Request Welcome Promotion Setup</b>\n\n"
        "When the bot is added as an Admin in external channels/groups, "
        "it can auto-approve join requests and send users a private promotional DM showcasing what you offer!\n\n"
        f"• <b>Promo Status:</b> <code>{st}</code>\n"
        f"• <b>Auto-Approve Joins:</b> <code>{ap}</code>\n"
        f"• <b>Banner Media:</b> <code>{banner_st}</code>\n\n"
        "📝 <b>Current Message Template:</b>\n"
        f"<blockquote>{promo.get('text', '')[:350]}...</blockquote>\n\n"
        "<i>Use buttons below to customize or toggle features:</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=build_admin_join_promo_keyboard(promo))
    except Exception:
        await callback.message.reply(text, reply_markup=build_admin_join_promo_keyboard(promo))
    await callback.answer()


@router.callback_query(F.data == "adm_jp_toggle_enabled")
async def cb_adm_jp_toggle_enabled(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    promo = await SettingsRepository.get_join_promo_settings()
    new_val = not promo.get("enabled", True)
    await SettingsRepository.set_join_promo_setting("enabled", new_val)
    await callback.answer(f"Join Promo is now {'Enabled' if new_val else 'Disabled'}!")
    await cb_adm_join_promo(callback, state=None)


@router.callback_query(F.data == "adm_jp_toggle_auto")
async def cb_adm_jp_toggle_auto(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    promo = await SettingsRepository.get_join_promo_settings()
    new_val = not promo.get("auto_approve", True)
    await SettingsRepository.set_join_promo_setting("auto_approve", new_val)
    await callback.answer(f"Auto-Approve is now {'ON' if new_val else 'OFF'}!")
    await cb_adm_join_promo(callback, state=None)


@router.callback_query(F.data == "adm_jp_edit_text")
async def cb_adm_jp_edit_text(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminSettingsStates.waiting_for_join_promo_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Cancel", callback_data="adm_join_promo")]
    ])
    await callback.message.reply(
        "📝 <b>Edit Join Request Promotional Message</b>\n\n"
        "Send the new text you want users to receive when they join your external channels.\n\n"
        "💡 <b>Available Placeholders:</b>\n"
        "• <code>{name}</code> - User's name\n"
        "• <code>{channel}</code> - Channel/Group title\n\n"
        "• Supports HTML formatting (bold, italic, code, quotes).",
        reply_markup=kb
    )
    await callback.answer()


@router.message(AdminSettingsStates.waiting_for_join_promo_text)
async def process_join_promo_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    new_text = message.html_text or message.text
    await SettingsRepository.set_join_promo_setting("text", new_text)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Promo Setup", callback_data="adm_join_promo")]
    ])
    await message.reply("✅ <b>Promotional message updated successfully!</b>", reply_markup=kb)


@router.callback_query(F.data == "adm_jp_set_banner")
async def cb_adm_jp_set_banner(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminSettingsStates.waiting_for_join_promo_banner)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Cancel", callback_data="adm_join_promo")]
    ])
    await callback.message.reply(
        "🖼️ <b>Upload Promotional Banner Photo</b>\n\n"
        "Please send a photo to be attached to the welcome promo message.",
        reply_markup=kb
    )
    await callback.answer()


@router.message(AdminSettingsStates.waiting_for_join_promo_banner)
async def process_join_promo_banner(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.photo:
        await message.reply("❌ Please send a valid photo or tap Cancel:")
        return
    photo_id = message.photo[-1].file_id
    await SettingsRepository.set_join_promo_setting("banner", photo_id)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Promo Setup", callback_data="adm_join_promo")]
    ])
    await message.reply("✅ <b>Promotional banner photo updated successfully!</b>", reply_markup=kb)


@router.callback_query(F.data == "adm_jp_del_banner")
async def cb_adm_jp_del_banner(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await SettingsRepository.set_join_promo_setting("banner", None)
    await callback.answer("Banner photo removed!")
    await cb_adm_join_promo(callback, state=None)


@router.callback_query(F.data == "adm_jp_preview")
async def cb_adm_jp_preview(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    promo = await SettingsRepository.get_join_promo_settings()
    bot_user = await callback.bot.get_me()
    bot_username = bot_user.username or settings.BOT_USERNAME
    name = html.escape(callback.from_user.first_name or "Friend")
    text = promo.get("text", "").replace("{name}", name).replace("{channel}", "Sample Channel")

    promo_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Explore All Courses & VIP Access", url=f"https://t.me/{bot_username}?start=catalog")],
        [InlineKeyboardButton(text="💬 Contact Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
    ])
    banner_id = promo.get("banner_file_id")
    if banner_id:
        await callback.message.reply_photo(photo=banner_id, caption=text, reply_markup=promo_kb)
    else:
        await callback.message.reply(text=text, reply_markup=promo_kb, disable_web_page_preview=True)
    await callback.answer("Sent preview above!")


@router.callback_query(F.data == "adm_test_payment")
async def cb_adm_test_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return
    from handlers.payments import cmd_simulate_payment
    await cmd_simulate_payment(callback.message)
    await callback.answer()
