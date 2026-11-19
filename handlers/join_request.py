import logging
from aiogram import Router
from aiogram.types import ChatJoinRequest
from services.invite_service import InviteService

logger = logging.getLogger(__name__)

router = Router(name="join_request_router")


import html
import logging
from aiogram import Router, Bot
from aiogram.types import ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import settings
from database.repositories.folder_repo import FolderRepository
from database.repositories.settings_repo import SettingsRepository
from database.repositories.user_repo import UserRepository
from services.invite_service import InviteService

logger = logging.getLogger(__name__)

router = Router(name="join_request_router")


@router.chat_join_request()
async def on_chat_join_request(request: ChatJoinRequest):
    """
    Handles ChatJoinRequest intelligently:
    1. If the request is for one of our own VIP Course/Group chats:
       - Strictly verifies buyer / demo validity via InviteService.
       - Does NOT scan or send marketing promo messages here.
    2. If the request is from an External Channel/Group where the bot is Admin:
       - Automatically registers the user into the database.
       - Optionally auto-approves their join request.
       - Sends our customized Promotional Welcome DM with courses & offers (if enabled in Admin Panel).
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
        should_auto_approve = promo_settings.get("auto_approve", True)

        # 1. Register user in database
        try:
            await UserRepository.get_or_create(
                user_id=user_id,
                username=from_user.username,
                full_name=from_user.full_name
            )
        except Exception as e:
            logger.debug(f"Could not register user {user_id} in UserRepository: {e}")

        # 2. Auto-approve join request if enabled
        if should_auto_approve:
            try:
                await request.approve()
                logger.info(f"Auto-approved external join request for user {user_id} in chat {chat_id}")
            except Exception as e:
                logger.debug(f"Could not auto-approve join request in {chat_id}: {e}")

        # 3. If promotional message is disabled, stop here
        if not is_promo_enabled:
            return

        # 4. Prepare and deliver promotional welcome post in user's DM
        bot_user = await bot.get_me()
        bot_username = bot_user.username or settings.BOT_USERNAME

        channel_title = request.chat.title or "our channel"
        user_name = html.escape(from_user.first_name or "Friend")

        raw_text = promo_settings.get("text", "")
        # Replace variables
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
        try:
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
            logger.info(f"Delivered external join promo DM to user {user_id} from chat {chat_id}")
        except TelegramForbiddenError:
            # User has not initiated conversation with bot or has blocked bot
            logger.debug(f"Cannot deliver promo DM to {user_id}: User has not started bot or blocked bot.")
        except Exception as e:
            logger.warning(f"Failed to deliver promo DM to {user_id}: {e}")

    except Exception as e:
        logger.error(f"Error handling chat join request for chat {chat_id}: {e}", exc_info=True)
