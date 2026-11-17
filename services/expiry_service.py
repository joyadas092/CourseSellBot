import asyncio
import logging
from datetime import datetime, timezone
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import settings
from database.repositories.subscription_repo import SubscriptionRepository

logger = logging.getLogger(__name__)


class ExpiryService:
    """
    Background worker periodically monitoring active subscriptions,
    dispatching reminders at 72 hours, 24 hours, 2 hours, and auto-removing expired members.
    """
    _running = False

    @classmethod
    async def start(cls, bot: Bot, check_interval_seconds: int = 60):
        """Start the background check loop."""
        cls._running = True
        logger.info("Starting subscription expiry & reminder monitor service...")
        while cls._running:
            try:
                await cls.check_all_subscriptions(bot)
            except Exception as exc:
                logger.error(f"Error in expiry monitor worker: {exc}")
            await asyncio.sleep(check_interval_seconds)

    @classmethod
    def stop(cls):
        """Stop background worker."""
        cls._running = False

    @classmethod
    async def check_all_subscriptions(cls, bot: Bot):
        """Check all users with an active course subscription."""
        now = datetime.now(timezone.utc)
        active_subs = await SubscriptionRepository.get_all_active_subscriptions()

        for sub in active_subs:
            sub_id = sub["subscription_id"]
            user_id = sub["user_id"]
            chat_id = sub.get("target_chat_id")
            folder_id = sub.get("folder_id")
            folder_title = sub.get("folder_title", "Course")
            valid_until = sub.get("valid_until")
            is_demo = sub.get("is_demo", False)

            if not valid_until:
                continue

            if valid_until.tzinfo is None:
                valid_until = valid_until.replace(tzinfo=timezone.utc)

            time_diff = (valid_until - now).total_seconds()
            reminders = sub.get("reminders_sent", {})

            # 1. Plan Expired: Remove user from channel/group and notify
            if time_diff <= 0:
                logger.info(f"Subscription {sub_id} for user {user_id} expired. Removing from chat {chat_id}")
                # Remove user from group/channel (ban then unban)
                if chat_id:
                    try:
                        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
                        logger.info(f"Successfully removed user {user_id} from chat {chat_id}")
                    except Exception as e:
                        logger.warning(f"Could not remove user {user_id} from chat {chat_id}: {e}")

                # Mark subscription as expired
                await SubscriptionRepository.mark_expired(sub_id)

                # Send expiry notification to user
                if is_demo:
                    renew_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💎 View Paid Plans", callback_data=f"fld_view:{folder_id}")],
                        [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
                    ])
                    msg_text = (
                        f"⌛ <b>Free Demo Trial Ended!</b>\n\n"
                        f"Your 2-minute free preview for <b>{folder_title}</b> has ended, and you have been removed from the private channel.\n\n"
                        "<i>(आपका 2 मिनट का डेमो ट्रायल समाप्त हो गया है)</i>\n\n"
                        "If you enjoyed the preview and want uninterrupted access, choose a regular plan below:"
                    )
                else:
                    renew_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Renew Subscription", callback_data=f"fld_view:{folder_id}")],
                        [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
                    ])
                    msg_text = (
                        f"❌ <b>Subscription Expired!</b>\n\n"
                        f"Your access to <b>{folder_title}</b> has expired, and your membership in the private group has ended.\n\n"
                        f"👇 Tap below to renew your plan and regain immediate access:"
                    )

                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=msg_text,
                        reply_markup=renew_kb
                    )
                except Exception as e:
                    logger.warning(f"Failed to send expiry notification to user {user_id}: {e}")

                # Notify Log Channel / Admins
                if settings.LOG_CHANNEL_ID:
                    try:
                        await bot.send_message(
                            chat_id=settings.LOG_CHANNEL_ID,
                            text=(
                                f"📤 <b>{'Demo ' if is_demo else ''}Member Expired & Removed</b>\n\n"
                                f"• Course: <b>{folder_title}</b>\n"
                                f"• User ID: <code>{user_id}</code>\n"
                                f"• Chat: <code>{chat_id}</code>\n"
                                f"• Action: Removed from private chat."
                            )
                        )
                    except Exception:
                        pass

            # Skip advance reminders for 2-minute demo plans
            elif is_demo:
                continue

            # 2. Urgent Reminder: 2 Hours left
            elif time_diff <= 7200:
                if not reminders.get("2h"):
                    renew_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⚡ Renew Access Now", callback_data=f"fld_view:{folder_id}")],
                        [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
                    ])
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=(
                                f"⌛ <b>Urgent: Access Expiring in 2 Hours!</b>\n\n"
                                f"Your subscription to <b>{folder_title}</b> will expire in less than 2 hours.\n"
                                f"To prevent automated removal from the private channel, please renew your access now."
                            ),
                            reply_markup=renew_kb
                        )
                    except Exception:
                        pass
                    await SubscriptionRepository.mark_reminder_sent(sub_id, "2h")

            # 3. 24 Hours Reminder (1 Day)
            elif time_diff <= 86400:
                if not reminders.get("24h"):
                    renew_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Renew Access", callback_data=f"fld_view:{folder_id}")],
                        [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
                    ])
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=(
                                f"⚠️ <b>Reminder: 24 Hours Left!</b>\n\n"
                                f"Your subscription to <b>{folder_title}</b> will expire tomorrow.\n"
                                f"Renew now to keep your access uninterrupted!"
                            ),
                            reply_markup=renew_kb
                        )
                    except Exception:
                        pass
                    await SubscriptionRepository.mark_reminder_sent(sub_id, "24h")

            # 4. 72 Hours Reminder (3 Days)
            elif time_diff <= 3 * 86400:
                if not reminders.get("72h"):
                    renew_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Renew Early", callback_data=f"fld_view:{folder_id}")],
                        [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
                    ])
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=(
                                f"🔔 <b>Notice: 3 Days Remaining</b>\n\n"
                                f"Your subscription to <b>{folder_title}</b> will expire in 3 days.\n"
                                f"Plan ahead and renew early to maintain continuous access."
                            ),
                            reply_markup=renew_kb
                        )
                    except Exception:
                        pass
                    await SubscriptionRepository.mark_reminder_sent(sub_id, "72h")

    @classmethod
    def schedule_immediate_demo_kick(
        cls,
        bot: Bot,
        sub_id: str,
        user_id: int,
        chat_id: int,
        folder_id: str,
        folder_title: str,
        delay_seconds: int = 120
    ):
        """Schedule precise async countdown (2 minutes) to kick demo user and notify them."""
        async def _demo_kick_task():
            await asyncio.sleep(max(1, delay_seconds))
            sub = await SubscriptionRepository.get_by_id(sub_id)
            if not sub or sub.get("status") != "active":
                return  # Already expired or processed

            logger.info(f"Executing scheduled 2-minute demo expiry for user {user_id} in chat {chat_id}")
            if chat_id:
                try:
                    await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                    await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
                    logger.info(f"Demo user {user_id} removed from chat {chat_id}")
                except Exception as e:
                    logger.warning(f"Could not remove demo user {user_id}: {e}")

            await SubscriptionRepository.mark_expired(sub_id)

            renew_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 View Paid Plans", callback_data=f"fld_view:{folder_id}")],
                [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
            ])

            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"⌛ <b>Free Demo Trial Ended!</b>\n\n"
                        f"Your 2-minute free preview for <b>{folder_title}</b> has ended, and you have been removed from the private channel.\n\n"
                        "<i>(आपका 2 मिनट का डेमो ट्रायल समाप्त हो गया है)</i>\n\n"
                        "If you enjoyed the preview and want uninterrupted access, choose a regular plan below:"
                    ),
                    reply_markup=renew_kb
                )
            except Exception:
                pass

            if settings.LOG_CHANNEL_ID:
                try:
                    await bot.send_message(
                        chat_id=settings.LOG_CHANNEL_ID,
                        text=(
                            f"⏱️ <b>Demo Trial Expired & Removed</b>\n\n"
                            f"• Course: <b>{folder_title}</b>\n"
                            f"• User: <code>{user_id}</code>\n"
                            f"• Chat: <code>{chat_id}</code>\n"
                            f"• Duration: 2 minutes complete."
                        )
                    )
                except Exception:
                    pass

        asyncio.create_task(_demo_kick_task())
