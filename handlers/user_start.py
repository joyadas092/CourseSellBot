import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.filters import CommandStart, Command
from database.repositories.user_repo import UserRepository
from database.repositories.folder_repo import FolderRepository
from database.repositories.settings_repo import SettingsRepository
from database.repositories.subscription_repo import SubscriptionRepository
from keyboards.user_kb import build_catalog_keyboard, build_folder_details_keyboard

logger = logging.getLogger(__name__)

router = Router(name="user_start_router")


async def render_catalog_view(target: Message | CallbackQuery, user_id: int):
    """Render the main store / catalog view matching Screenshot 1."""
    header_text = await SettingsRepository.get_catalog_header()
    folders = await FolderRepository.get_all_folders(only_active=True)

    if not folders:
        empty_text = (
            "🛍️ <b>Course & Premium Content Store</b>\n\n"
            "Currently there are no active courses available.\n"
            "Please check back shortly or contact our administrator!"
        )
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(empty_text)
            await target.answer()
        else:
            await target.answer(empty_text)
        return

    markup = build_catalog_keyboard(folders)

    if isinstance(target, CallbackQuery):
        msg = target.message
        if msg.photo:
            try:
                await msg.delete()
            except Exception:
                pass
            await target.bot.send_message(chat_id=msg.chat.id, text=header_text, reply_markup=markup)
        else:
            try:
                await msg.edit_text(text=header_text, reply_markup=markup)
            except Exception:
                await target.bot.send_message(chat_id=msg.chat.id, text=header_text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text=header_text, reply_markup=markup)


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Handle /start command from any user."""
    from_user = message.from_user
    if from_user:
        await UserRepository.get_or_create(
            user_id=from_user.id,
            username=from_user.username,
            full_name=from_user.full_name
        )
    await render_catalog_view(target=message, user_id=from_user.id)


@router.callback_query(F.data == "back_catalog")
async def cb_back_catalog(callback: CallbackQuery):
    """Navigate back to products catalog."""
    await render_catalog_view(target=callback, user_id=callback.from_user.id)


@router.callback_query(F.data.startswith("fld_view:"))
async def cb_folder_view(callback: CallbackQuery):
    """
    Render course / folder details page matching Screenshot 2:
    Content details, demo link, quotes, support info, and pricing tiers.
    """
    folder_id = callback.data.split(":", 1)[1]
    folder = await FolderRepository.get_folder(folder_id)

    if not folder:
        await callback.answer("Course not found or has been removed.", show_alert=True)
        return

    support_user = await SettingsRepository.get_support_username()
    demo_url = folder.get("demo_url")
    demo_section = f"\n<b>Demo :</b> <a href=\"{demo_url}\">Click me</a>\n" if demo_url else ""

    text = (
        f"<b>Content Details :-</b>\n"
        f"<blockquote>{folder.get('description', 'No details provided.')}</blockquote>"
        f"{demo_section}\n"
        f"<blockquote>Tum ginte ginte ginti bhul jaoge\n\n"
        f"You will lose count while counting.</blockquote>\n\n"
        f"<blockquote>Payment issue or want to pay via crypto? Contact:\n"
        f"@{support_user}</blockquote>"
    )

    has_used_demo = await UserRepository.has_used_demo(callback.from_user.id)
    markup = build_folder_details_keyboard(folder, has_used_demo=has_used_demo)
    banner_file_id = folder.get("banner_file_id")

    msg = callback.message
    bot = callback.bot

    if banner_file_id:
        if msg.photo:
            try:
                await msg.edit_media(
                    media=InputMediaPhoto(media=banner_file_id, caption=text),
                    reply_markup=markup
                )
                await callback.answer()
                return
            except Exception:
                pass
        try:
            await msg.delete()
        except Exception:
            pass
        try:
            await bot.send_photo(
                chat_id=msg.chat.id,
                photo=banner_file_id,
                caption=text,
                reply_markup=markup
            )
            await callback.answer()
            return
        except Exception as e:
            logger.warning(f"Could not send photo banner: {e}")

    # Fallback to text message
    if msg.photo:
        try:
            await msg.delete()
        except Exception:
            pass
        await bot.send_message(chat_id=msg.chat.id, text=text, reply_markup=markup)
    else:
        try:
            await msg.edit_text(text=text, reply_markup=markup)
        except Exception:
            await bot.send_message(chat_id=msg.chat.id, text=text, reply_markup=markup)

    await callback.answer()


@router.callback_query(F.data == "my_subscriptions")
async def cb_my_subscriptions(callback: CallbackQuery):
    """Display user's active subscriptions and validity dates."""
    user_id = callback.from_user.id
    subs = await SubscriptionRepository.list_by_user(user_id)

    if not subs:
        await callback.answer("You don't have any active subscriptions yet.", show_alert=True)
        return

    lines = ["<b>📋 Your Active Subscriptions:</b>\n"]
    for s in subs:
        valid_dt = s.get("valid_until")
        valid_str = valid_dt.strftime("%d %b %Y, %H:%M UTC") if valid_dt else "Never"
        status_emoji = "🟢 Active" if s.get("status") == "active" else "🔴 Expired"
        lines.append(
            f"• <b>{s.get('folder_title')}</b> ({s.get('plan_label')})\n"
            f"  Status: {status_emoji}\n"
            f"  Valid until: <code>{valid_str}</code>\n"
        )

    await callback.message.reply("\n".join(lines))
    await callback.answer()


@router.message(Command("privacy"))
async def cmd_privacy(message: Message):
    """Display privacy statement."""
    await message.answer(
        "🛡️ <b>Privacy Policy & Terms</b>\n\n"
        "1. All purchases provide non-transferable access for the specified duration.\n"
        "2. Private invite links are strictly linked to the purchasing account.\n"
        "3. Any attempt to share, forward, or leak invite links will result in automatic rejection.\n"
        "4. Automated systems will revoke access and remove accounts upon plan expiry.\n\n"
        "For inquiries, please contact our support team."
    )
