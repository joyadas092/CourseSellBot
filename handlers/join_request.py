import asyncio
import html
import logging
from aiogram import Router, Bot
from aiogram.types import ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import settings
from database.repositories.folder_repo import FolderRepository
from database.repositories.settings_repo import SettingsRepository
from services.invite_service import InviteService

logger = logging.getLogger(__name__)

router = Router(name="join_request_router")


async def _deliver_promo_dm(
    bot: Bot,
    user_id: int,
    user_first_name: str,
    channel_title: str,
    promo_settings: dict,
    delay_seconds: int = 0
) -> None:
    """Delivers promotional welcome message to user's DM after optional delay."""
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)

    try:
        bot_user = await bot.get_me()
        bot_username = bot_user.username or settings.BOT_USERNAME

        user_name = html.escape(user_first_name or "Friend")
        raw_text = promo_settings.get("text", "")
        text = raw_text.replace("{name}", user_name).replace("{channel}", html.escape(channel_title))

        promo_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛍️ Explore All Courses & VIP Access",
                    url=f"https://t.me/{bot_username}?start=catalog"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Contact Support",
                    url=f"https://t.me/{settings.SUPPORT_USERNAME}"
                )
            ]
        ])

        banner_file_id = promo_settings.get("banner_file_id")
        if banner_file_id:
            await bot.send_photo(
                chat_id=user_id,
                photo=banner_file_id,
                caption=text,
                reply_markup=promo_kb
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=promo_kb,
                disable_web_page_preview=True
            )
        logger.info(f"Delivered external join promo DM to user {user_id} (delay: {delay_seconds}s)")
    except TelegramForbiddenError:
        logger.debug(f"Cannot deliver promo DM to {user_id}: User has not started bot or blocked bot.")
    except Exception as e:
        logger.warning(f"Failed to deliver promo DM to {user_id}: {e}")


@router.chat_join_request()
async def on_chat_join_request(request: ChatJoinRequest):
    """
    Handles ChatJoinRequest:
    1. If request is for one of our official VIP Course groups/channels:
       - Strictly verifies buyer / demo validity via InviteService.
       - Does NOT scan or send marketing promo messages here.
    2. If request is from an External Channel/Group where bot is Admin:
       - Does NOT approve or alter the join request (stays pending).
       - Does NOT save dummy users to DB.
       - Sends the customized Promotional Welcome DM with courses & offers
         after the configured interval/delay.
    """
    chat_id = request.chat.id
    from_user = request.from_user
    user_id = from_user.id
    bot: Bot = request.bot

    try:
        # Check all VIP Course target chats
        all_folders = await FolderRepository.get_all_folders()
        course_chat_ids = {
            f.get("target_chat_id")
            for f in all_folders
            if f.get("target_chat_id") and f.get("target_chat_id") != -1000000000000
        }

        # Case 1: This is our official VIP Course Group/Channel
        if chat_id in course_chat_ids:
            logger.info(f"Join request from {user_id} is for Course VIP chat {chat_id}. Processing buyer verification...")
            await InviteService.process_chat_join_request(bot, request)
            return

        # Case 2: This is an EXTERNAL Group/Channel where bot is added as Admin
        promo_settings = await SettingsRepository.get_join_promo_settings()
        is_promo_enabled = promo_settings.get("enabled", True)
        if not is_promo_enabled:
            return

        delay_seconds = int(promo_settings.get("delay_seconds", 0))
        channel_title = request.chat.title or "our channel"

        # Dispatch async background task for delayed/instant DM delivery
        asyncio.create_task(
            _deliver_promo_dm(
                bot=bot,
                user_id=user_id,
                user_first_name=from_user.first_name,
                channel_title=channel_title,
                promo_settings=promo_settings,
                delay_seconds=delay_seconds
            )
        )

    except Exception as e:
        logger.error(f"Error handling chat join request for chat {chat_id}: {e}", exc_info=True)
