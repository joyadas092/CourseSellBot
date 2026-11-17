import logging
import time
from datetime import datetime, timezone
from typing import Optional
from aiogram import Bot
from aiogram.types import ChatJoinRequest
from config import settings
from database.repositories.subscription_repo import SubscriptionRepository
from database.repositories.folder_repo import FolderRepository

logger = logging.getLogger(__name__)


class InviteService:
    """Handles unique single-use invite link generation and strict join request verification."""

    @classmethod
    async def generate_user_invite_link(cls, bot: Bot, chat_id: int, user_id: int, subscription_id: str) -> str:
        """
        Creates a unique Telegram invite link configured with creates_join_request=True.
        This forces Telegram to route the join request through our bot's verification handler.
        """
        try:
            # Create restricted invite link with admin approval required (creates_join_request=True)
            # Link expires after 24 hours if unused
            expire_timestamp = int(time.time() + 86400)
            invite = await bot.create_chat_invite_link(
                chat_id=chat_id,
                name=f"Sub_{user_id}_{subscription_id[:6]}",
                creates_join_request=True,
                expire_date=expire_timestamp
            )
            # Save link to subscription record
            await SubscriptionRepository.set_invite_link(subscription_id, invite.invite_link)
            return invite.invite_link
        except Exception as e:
            logger.error(f"Failed to create chat invite link for chat {chat_id}: {e}")
            raise

    @classmethod
    async def process_chat_join_request(cls, bot: Bot, request: ChatJoinRequest) -> None:
        """
        Validates the incoming ChatJoinRequest:
        1. If legitimate paid user -> Approve request, revoke link, mark joined.
        2. If another user (intruder) -> Decline request, alert the original buyer!
        """
        chat_id = request.chat.id
        from_user = request.from_user
        intruder_id = from_user.id
        intruder_name = from_user.full_name
        intruder_username = f"@{from_user.username}" if from_user.username else "No Username"
        used_link = request.invite_link.invite_link if request.invite_link else None

        logger.info(f"Join request received for chat {chat_id} from user {intruder_id} with link {used_link}")

        # 1. Lookup subscription by the exact invite link clicked
        subscription = None
        if used_link:
            subscription = await SubscriptionRepository.get_by_invite_link(chat_id, used_link)

        # 2. If not found by link, check if the joining user has a pending subscription for this chat
        if not subscription:
            subscription = await SubscriptionRepository.get_pending_user_subscription(chat_id, intruder_id)

        # Case A: No subscription exists at all
        if not subscription:
            logger.warning(f"Unauthorized join attempt: User {intruder_id} has no subscription for chat {chat_id}")
            try:
                await bot.decline_chat_join_request(chat_id=chat_id, user_id=intruder_id)
            except Exception as e:
                logger.error(f"Failed to decline join request: {e}")
            try:
                await bot.send_message(
                    chat_id=intruder_id,
                    text=(
                        f"⛔ <b>Access Denied to {request.chat.title}</b>\n\n"
                        "You do not have an active subscription for this private group/channel.\n"
                        "Please use /start to view available courses and purchase your access."
                    )
                )
            except Exception:
                pass
            return

        expected_user_id = subscription["user_id"]
        sub_id = subscription["subscription_id"]
        folder_title = subscription.get("folder_title", "Private Group")

        # Case B: LEGITIMATE BUYER MATCH!
        if intruder_id == expected_user_id:
            logger.info(f"Approving legitimate subscriber {expected_user_id} for {folder_title}")
            try:
                # 1. Approve user into the group/channel
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=intruder_id)
            except Exception as e:
                logger.error(f"Failed to approve join request: {e}")

            # 2. Immediately revoke the invite link so it can never be used again
            if used_link or subscription.get("invite_link"):
                link_to_revoke = used_link or subscription.get("invite_link")
                try:
                    await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=link_to_revoke)
                    logger.info(f"Revoked single-use invite link for subscription {sub_id}")
                except Exception as e:
                    logger.warning(f"Could not revoke invite link: {e}")

            is_demo = subscription.get("is_demo", False)
            folder_id = subscription.get("folder_id", "")

            # 3. Mark subscription as joined (if demo, starts 120s timer from join time)
            if is_demo:
                await SubscriptionRepository.mark_joined(sub_id, start_now_seconds=120)
                # Schedule exact 2-minute countdown kick
                from services.expiry_service import ExpiryService
                ExpiryService.schedule_immediate_demo_kick(
                    bot=bot,
                    sub_id=sub_id,
                    user_id=intruder_id,
                    chat_id=chat_id,
                    folder_id=folder_id,
                    folder_title=folder_title,
                    delay_seconds=120
                )
            else:
                await SubscriptionRepository.mark_joined(sub_id)

            # 4. Send friendly welcome confirmation
            if is_demo:
                welcome_text = (
                    f"🎉 <b>Welcome to {folder_title} (Demo Access)!</b>\n\n"
                    "⏱️ <b>Your 2-minute free demo preview is now active!</b>\n"
                    "⏳ <b>Removal Time:</b> You will be automatically removed after exactly 2 minutes.\n\n"
                    "<i>(2 मिनट पूरे होते ही आप चैनल से रिमूव हो जाएंगे)</i>\n\n"
                    "Enjoy your quick preview!"
                )
            else:
                valid_dt = subscription["valid_until"]
                valid_str = valid_dt.strftime("%d %b %Y, %H:%M UTC") if isinstance(valid_dt, datetime) else str(valid_dt)
                welcome_text = (
                    f"🎉 <b>Welcome to {folder_title}!</b>\n\n"
                    "✅ Your join request has been approved.\n"
                    f"⏳ <b>Subscription Active Until:</b> <code>{valid_str}</code>\n\n"
                    "Enjoy your premium access!"
                )

            try:
                await bot.send_message(
                    chat_id=intruder_id,
                    text=welcome_text
                )
            except Exception:
                pass
            return

        # Case C: INTRUDER / UNAUTHORIZED USER USING SOMEONE ELSE'S LINK!
        logger.warning(
            f"SECURITY ALERT: User {intruder_id} ({intruder_name}) tried to use invite link belonging to {expected_user_id}!"
        )

        # 1. Decline intruder's request immediately
        try:
            await bot.decline_chat_join_request(chat_id=chat_id, user_id=intruder_id)
        except Exception as e:
            logger.error(f"Failed to decline intruder: {e}")

        # 2. Inform the intruder
        try:
            await bot.send_message(
                chat_id=intruder_id,
                text=(
                    f"⛔ <b>Access Blocked</b>\n\n"
                    "This invite link was issued exclusively to another subscriber.\n"
                    "Your join request was rejected."
                )
            )
        except Exception:
            pass

        # 3. ALERT THE LEGITIMATE BUYER THAT SOMEONE TRIED TO ENTER WITH THEIR LINK!
        try:
            await bot.send_message(
                chat_id=expected_user_id,
                text=(
                    "🚨 <b>SECURITY ALERT!</b>\n\n"
                    f"Someone attempted to enter <b>{folder_title}</b> using your private invite link!\n\n"
                    f"👤 <b>Intruder ID:</b> <code>{intruder_id}</code>\n"
                    f"👤 <b>Intruder Name:</b> {intruder_name} ({intruder_username})\n\n"
                    "⛔ <b>Action Taken:</b> Their request was automatically <b>REJECTED</b> by the bot.\n\n"
                    "🔒 <i>Please do not share your private links. Each link is restricted to your account only.</i>"
                )
            )
            logger.info(f"Security alert dispatched to buyer {expected_user_id}")
        except Exception as e:
            logger.error(f"Failed to send security alert to legitimate buyer: {e}")

        # 4. Log alert to Admin / Log Channel
        if settings.LOG_CHANNEL_ID:
            try:
                await bot.send_message(
                    chat_id=settings.LOG_CHANNEL_ID,
                    text=(
                        f"🛡️ <b>Security Alert: Intruder Blocked</b>\n\n"
                        f"• Course: <b>{folder_title}</b>\n"
                        f"• Legitimate Owner: <code>{expected_user_id}</code>\n"
                        f"• Blocked Intruder: <code>{intruder_id}</code> ({intruder_username})\n"
                        f"• Result: Declined entry automatically."
                    )
                )
            except Exception:
                pass
