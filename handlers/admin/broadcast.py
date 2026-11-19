import asyncio
import logging
import time
import uuid
from typing import Dict, Any, List
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import (
    TelegramRetryAfter,
    TelegramForbiddenError,
    TelegramBadRequest,
    TelegramAPIError
)

from config import settings
from database.repositories.user_repo import UserRepository
from database.repositories.subscription_repo import SubscriptionRepository

logger = logging.getLogger(__name__)

router = Router(name="admin_broadcast_router")

# In-memory dictionary for tracking active broadcasts & cancellation signals
active_broadcasts: Dict[str, Dict[str, Any]] = {}


def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


class BroadcastStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_confirmation = State()


def format_seconds(seconds: float) -> str:
    """Format seconds into human-readable MM:SS or HH:MM:SS."""
    seconds = int(max(0, seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def render_progress_bar(current: int, total: int, length: int = 12) -> str:
    """Generates visual Unicode progress bar."""
    if total <= 0:
        return "░" * length
    ratio = min(1.0, max(0.0, current / total))
    filled = int(round(length * ratio))
    return "█" * filled + "░" * (length - filled)


# ==========================================
# Audience Selection & Command Triggers
# ==========================================

@router.message(Command("broadcast", "bcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """Admin command to start a broadcast directly or via reply."""
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Unauthorized access.")
        return

    await state.clear()
    reply = message.reply_to_message
    if reply:
        await state.update_data(
            replied_chat_id=reply.chat.id,
            replied_message_id=reply.message_id
        )

    all_users = len(await UserRepository.get_all_user_ids())
    active_subs = len(await SubscriptionRepository.get_active_subscriber_user_ids())
    expired_subs = len(await SubscriptionRepository.get_expired_subscriber_user_ids())
    demo_users = len(await UserRepository.get_demo_user_ids())

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🌐 All Users ({all_users})", callback_data="bcast_aud:all")
        ],
        [
            InlineKeyboardButton(text=f"👑 Active Subscribers ({active_subs})", callback_data="bcast_aud:active"),
            InlineKeyboardButton(text=f"⌛ Expired Subscribers ({expired_subs})", callback_data="bcast_aud:expired")
        ],
        [
            InlineKeyboardButton(text=f"🎁 Demo Trial Users ({demo_users})", callback_data="bcast_aud:demo")
        ],
        [
            InlineKeyboardButton(text="❌ Cancel", callback_data="bcast_cancel")
        ]
    ])

    reply_note = "\n\n📌 <i>Target message captured from your reply!</i>" if reply else ""
    text = (
        "📢 <b>Broadcast Control Center</b>\n\n"
        "Select the target audience for your broadcast message:\n\n"
        f"• 🌐 <b>All Users:</b> <code>{all_users:,}</code> (Full Bot Audience)\n"
        f"• 👑 <b>Active Subscribers:</b> <code>{active_subs:,}</code> (Current Paid Members)\n"
        f"• ⌛ <b>Expired Subscribers:</b> <code>{expired_subs:,}</code> (Win-Back / Renewal Offers)\n"
        f"• 🎁 <b>Demo Trial Users:</b> <code>{demo_users:,}</code> (High-Intent Leads)"
        f"{reply_note}\n\n"
        "👇 <i>Choose an audience below to proceed:</i>"
    )
    await message.reply(text, reply_markup=kb)


@router.callback_query(F.data == "adm_broadcast")
async def cb_adm_broadcast(callback: CallbackQuery, state: FSMContext):
    """Present audience segmentation options for broadcast."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    await state.clear()

    # Fetch counts
    all_users = len(await UserRepository.get_all_user_ids())
    active_subs = len(await SubscriptionRepository.get_active_subscriber_user_ids())
    expired_subs = len(await SubscriptionRepository.get_expired_subscriber_user_ids())
    demo_users = len(await UserRepository.get_demo_user_ids())

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🌐 All Users ({all_users})", callback_data="bcast_aud:all")
        ],
        [
            InlineKeyboardButton(text=f"👑 Active Subscribers ({active_subs})", callback_data="bcast_aud:active"),
            InlineKeyboardButton(text=f"⌛ Expired Subscribers ({expired_subs})", callback_data="bcast_aud:expired")
        ],
        [
            InlineKeyboardButton(text=f"🎁 Demo Trial Users ({demo_users})", callback_data="bcast_aud:demo")
        ],
        [
            InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="adm_main_menu")
        ]
    ])

    text = (
        "📢 <b>Broadcast Control Center</b>\n\n"
        "Select the target audience for your broadcast message:\n\n"
        f"• 🌐 <b>All Users:</b> <code>{all_users}</code> (Full Bot Audience)\n"
        f"• 👑 <b>Active Subscribers:</b> <code>{active_subs}</code> (Current Paid Members)\n"
        f"• ⌛ <b>Expired Subscribers:</b> <code>{expired_subs}</code> (Win-Back / Renewal Offers)\n"
        f"• 🎁 <b>Demo Trial Users:</b> <code>{demo_users}</code> (High-Intent Leads)\n\n"
        "👇 <i>Choose an audience below to proceed:</i>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.reply(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("bcast_aud:"))
async def cb_bcast_aud(callback: CallbackQuery, state: FSMContext):
    """Audience chosen, prompt for message or show preview if replied."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    audience_key = callback.data.split(":", 1)[1]
    audience_names = {
        "all": "🌐 All Registered Users",
        "active": "👑 Active Paid Subscribers",
        "expired": "⌛ Expired Subscribers",
        "demo": "🎁 Demo Trial Users"
    }
    aud_label = audience_names.get(audience_key, "All Users")

    data = await state.get_data()
    replied_msg_id = data.get("replied_message_id")
    replied_chat_id = data.get("replied_chat_id")

    if replied_msg_id and replied_chat_id:
        # User invoked /broadcast by replying to a message! Skip text prompt and show preview directly!
        if audience_key == "active":
            target_ids = await SubscriptionRepository.get_active_subscriber_user_ids()
        elif audience_key == "expired":
            target_ids = await SubscriptionRepository.get_expired_subscriber_user_ids()
        elif audience_key == "demo":
            target_ids = await UserRepository.get_demo_user_ids()
        else:
            target_ids = await UserRepository.get_all_user_ids()

        total = len(target_ids)
        if total == 0:
            await state.clear()
            await callback.message.reply(f"❌ There are 0 users in <b>{aud_label}</b>.")
            await callback.answer()
            return

        await state.update_data(
            bcast_chat_id=replied_chat_id,
            bcast_message_id=replied_msg_id,
            target_ids=target_ids,
            aud_label=aud_label,
            total=total,
            should_pin=False
        )
        await state.set_state(BroadcastStates.waiting_for_confirmation)

        pin_icon = "🔕 NO"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Start Broadcast Now", callback_data="bcast_start")
            ],
            [
                InlineKeyboardButton(text=f"📌 Pin for Users: {pin_icon}", callback_data="bcast_toggle_pin")
            ],
            [
                InlineKeyboardButton(text="❌ Cancel", callback_data="bcast_cancel")
            ]
        ])

        await callback.message.reply(
            "📋 <b>Broadcast Confirmation & Preview</b>\n\n"
            f"• <b>Target Audience:</b> {aud_label}\n"
            f"• <b>Total Recipients:</b> <code>{total:,}</code> users\n"
            f"• <b>Pin Message:</b> <code>{pin_icon}</code>\n"
            "• <b>Real-Time Progress:</b> ✅ Enabled\n\n"
            "⚠️ <i>Target message captured from reply. Tap 'Start Broadcast Now' when ready:</i>",
            reply_markup=kb
        )
        await callback.answer()
        return

    # Normal flow: Ask admin to send the message
    await state.update_data(audience=audience_key, should_pin=False)
    await state.set_state(BroadcastStates.waiting_for_message)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Audience Selection", callback_data="adm_broadcast")]
    ])

    await callback.message.reply(
        f"📢 <b>Target Audience:</b> {aud_label}\n\n"
        "<b>Please send the message you wish to broadcast:</b>\n"
        "• Supports Text, Photo, Video, Voice, Audio, Documents & Stickers.\n"
        "• Formatted text, captions & inline links are preserved.\n"
        "• You will see a confirmation preview before sending.",
        reply_markup=kb
    )
    await callback.answer()


# ==========================================
# Message Input & Confirmation Preview
# ==========================================

@router.message(BroadcastStates.waiting_for_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    """Capture broadcast message and show confirmation preview with live toggles."""
    data = await state.get_data()
    audience_key = data.get("audience", "all")
    should_pin = data.get("should_pin", False)

    # Resolve target IDs
    if audience_key == "active":
        target_ids = await SubscriptionRepository.get_active_subscriber_user_ids()
        aud_label = "👑 Active Subscribers"
    elif audience_key == "expired":
        target_ids = await SubscriptionRepository.get_expired_subscriber_user_ids()
        aud_label = "⌛ Expired Subscribers"
    elif audience_key == "demo":
        target_ids = await UserRepository.get_demo_user_ids()
        aud_label = "🎁 Demo Trial Users"
    else:
        target_ids = await UserRepository.get_all_user_ids()
        aud_label = "🌐 All Users"

    total = len(target_ids)
    if total == 0:
        await state.clear()
        await message.reply(
            f"❌ There are 0 users in <b>{aud_label}</b>. Broadcast cancelled.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data="adm_broadcast")]
            ])
        )
        return

    await state.update_data(
        bcast_chat_id=message.chat.id,
        bcast_message_id=message.message_id,
        target_ids=target_ids,
        aud_label=aud_label,
        total=total,
        should_pin=should_pin
    )
    await state.set_state(BroadcastStates.waiting_for_confirmation)

    pin_icon = "🔔 YES" if should_pin else "🔕 NO"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Start Broadcast Now", callback_data="bcast_start")
        ],
        [
            InlineKeyboardButton(text=f"📌 Pin for Users: {pin_icon}", callback_data="bcast_toggle_pin")
        ],
        [
            InlineKeyboardButton(text="❌ Cancel", callback_data="bcast_cancel")
        ]
    ])

    await message.reply(
        "📋 <b>Broadcast Confirmation & Preview</b>\n\n"
        f"• <b>Target Audience:</b> {aud_label}\n"
        f"• <b>Total Recipients:</b> <code>{total:,}</code> users\n"
        f"• <b>Pin Message:</b> <code>{pin_icon}</code>\n"
        "• <b>Real-Time Progress:</b> ✅ Enabled\n\n"
        "⚠️ <i>Verify your message above. Tap 'Start Broadcast Now' when ready:</i>",
        reply_markup=kb
    )


@router.callback_query(BroadcastStates.waiting_for_confirmation, F.data == "bcast_toggle_pin")
async def cb_bcast_toggle_pin(callback: CallbackQuery, state: FSMContext):
    """Toggle whether to pin the broadcast message for recipients."""
    data = await state.get_data()
    new_pin = not data.get("should_pin", False)
    await state.update_data(should_pin=new_pin)

    pin_icon = "🔔 YES" if new_pin else "🔕 NO"
    aud_label = data.get("aud_label", "Audience")
    total = data.get("total", 0)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Start Broadcast Now", callback_data="bcast_start")
        ],
        [
            InlineKeyboardButton(text=f"📌 Pin for Users: {pin_icon}", callback_data="bcast_toggle_pin")
        ],
        [
            InlineKeyboardButton(text="❌ Cancel", callback_data="bcast_cancel")
        ]
    ])

    await callback.message.edit_text(
        "📋 <b>Broadcast Confirmation & Preview</b>\n\n"
        f"• <b>Target Audience:</b> {aud_label}\n"
        f"• <b>Total Recipients:</b> <code>{total:,}</code> users\n"
        f"• <b>Pin Message:</b> <code>{pin_icon}</code>\n"
        "• <b>Real-Time Progress:</b> ✅ Enabled\n\n"
        "⚠️ <i>Verify your message above. Tap 'Start Broadcast Now' when ready:</i>",
        reply_markup=kb
    )
    await callback.answer(f"Pin set to: {pin_icon}")


@router.callback_query(F.data == "bcast_cancel")
async def cb_bcast_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel broadcast setup."""
    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Broadcast cancelled.</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="adm_main_menu")]
        ])
    )
    await callback.answer()


# ==========================================
# Real-Time Live Broadcast Execution Engine
# ==========================================

@router.callback_query(BroadcastStates.waiting_for_confirmation, F.data == "bcast_start")
async def cb_bcast_start(callback: CallbackQuery, state: FSMContext):
    """Starts the asynchronous real-time progress broadcast engine."""
    data = await state.get_data()
    await state.clear()

    bcast_chat_id = data["bcast_chat_id"]
    bcast_message_id = data["bcast_message_id"]
    target_ids: List[int] = data["target_ids"]
    aud_label: str = data["aud_label"]
    should_pin: bool = data.get("should_pin", False)
    total = len(target_ids)

    broadcast_id = uuid.uuid4().hex[:8]
    active_broadcasts[broadcast_id] = {
        "running": True,
        "cancel_requested": False
    }

    bot: Bot = callback.bot
    admin_chat_id = callback.message.chat.id

    # Create initial progress message with abort button
    abort_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏹️ Abort / Stop Broadcast", callback_data=f"bcast_abort:{broadcast_id}")]
    ])

    progress_msg = await callback.message.reply(
        "📡 <b>Broadcasting in Progress...</b>\n\n"
        f"[░░░░░░░░░░░░] <b>0.0%</b>\n\n"
        f"• <b>Audience:</b> {aud_label}\n"
        f"• <b>Total Targets:</b> <code>{total:,}</code>\n"
        f"• <b>Delivered:</b> <code>0</code> ✅\n"
        f"• <b>Failed / Blocked:</b> <code>0</code> ❌\n"
        f"• <b>Remaining:</b> <code>{total:,}</code> ⏳\n"
        f"• <b>Speed:</b> <code>0.0 msg/s</code>\n"
        f"• <b>Elapsed Time:</b> <code>00m 00s</code>\n"
        f"• <b>Est. Time Left (ETA):</b> <code>calculating...</code>",
        reply_markup=abort_kb
    )
    await callback.answer()

    # Asynchronous runner for real-time progress
    async def _execute_broadcast():
        sent = 0
        failed = 0
        start_time = time.time()
        last_ui_update = time.time()
        was_aborted = False

        for idx, uid in enumerate(target_ids):
            # Check for cancellation signal
            if active_broadcasts.get(broadcast_id, {}).get("cancel_requested"):
                was_aborted = True
                break

            try:
                copied = await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=bcast_chat_id,
                    message_id=bcast_message_id
                )
                if should_pin and copied:
                    try:
                        await bot.pin_chat_message(chat_id=uid, message_id=copied.message_id, both_sides=True)
                    except Exception:
                        pass
                sent += 1
            except TelegramRetryAfter as e:
                # Obey Telegram FloodWait exactly
                logger.warning(f"Broadcast FloodWait: sleeping {e.retry_after}s")
                await asyncio.sleep(e.retry_after)
                try:
                    await bot.copy_message(chat_id=uid, from_chat_id=bcast_chat_id, message_id=bcast_message_id)
                    sent += 1
                except Exception:
                    failed += 1
            except (TelegramForbiddenError, TelegramBadRequest):
                # User blocked bot or deleted account
                failed += 1
            except TelegramAPIError as e:
                logger.debug(f"Broadcast API error for {uid}: {e}")
                failed += 1
            except Exception:
                failed += 1

            # Pacing delay (~28 msg/sec) to avoid hitting Telegram's 30 msg/s ceiling
            await asyncio.sleep(0.035)

            # Update progress UI every 2.0 seconds
            now = time.time()
            if (now - last_ui_update >= 2.0) or (idx + 1 == total):
                last_ui_update = now
                elapsed = now - start_time
                completed = sent + failed
                percent = (completed / total) * 100 if total > 0 else 100.0
                speed = completed / elapsed if elapsed > 0 else 0.0
                remaining = total - completed
                eta_seconds = remaining / speed if speed > 0 else 0
                bar = render_progress_bar(completed, total, length=12)

                text = (
                    f"📡 <b>Broadcasting in Progress...</b>\n\n"
                    f"[{bar}] <b>{percent:.1f}%</b>\n\n"
                    f"• <b>Audience:</b> {aud_label}\n"
                    f"• <b>Total Targets:</b> <code>{total:,}</code>\n"
                    f"• <b>Delivered:</b> <code>{sent:,}</code> ✅\n"
                    f"• <b>Failed / Blocked:</b> <code>{failed:,}</code> ❌\n"
                    f"• <b>Remaining:</b> <code>{remaining:,}</code> ⏳\n"
                    f"• <b>Speed:</b> <code>{speed:.1f} msg/s</code>\n"
                    f"• <b>Elapsed Time:</b> <code>{format_seconds(elapsed)}</code>\n"
                    f"• <b>Est. Time Left (ETA):</b> <code>{format_seconds(eta_seconds)}</code>\n\n"
                    "<i>Tap below if you wish to stop midway:</i>"
                )

                try:
                    await progress_msg.edit_text(text, reply_markup=abort_kb)
                except Exception:
                    pass

        # Broadcast finished or aborted
        total_time = time.time() - start_time
        completed = sent + failed
        final_speed = completed / total_time if total_time > 0 else 0.0
        success_rate = (sent / completed) * 100 if completed > 0 else 0.0
        final_bar = render_progress_bar(completed, total, length=12)

        status_header = "⏹️ <b>Broadcast Aborted by Admin!</b>" if was_aborted else "✅ <b>Broadcast Completed Successfully!</b>"

        final_text = (
            f"{status_header}\n\n"
            f"[{final_bar}] <b>{(completed / total) * 100:.1f}%</b>\n\n"
            f"• <b>Target Audience:</b> {aud_label}\n"
            f"• <b>Total Target Size:</b> <code>{total:,}</code>\n"
            f"• <b>Successfully Delivered:</b> <code>{sent:,}</code> ✅\n"
            f"• <b>Failed / Blocked:</b> <code>{failed:,}</code> ❌\n"
            f"• <b>Delivery Rate:</b> <code>{success_rate:.1f}%</code>\n"
            f"• <b>Total Time Taken:</b> <code>{format_seconds(total_time)}</code>\n"
            f"• <b>Average Speed:</b> <code>{final_speed:.1f} msg/s</code>\n\n"
            "✨ <i>All tasks completed.</i>"
        )

        done_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to Admin Dashboard", callback_data="adm_main_menu")]
        ])

        try:
            await progress_msg.edit_text(final_text, reply_markup=done_kb)
        except Exception:
            await bot.send_message(chat_id=admin_chat_id, text=final_text, reply_markup=done_kb)

        active_broadcasts.pop(broadcast_id, None)

    asyncio.create_task(_execute_broadcast())


@router.callback_query(F.data.startswith("bcast_abort:"))
async def cb_bcast_abort(callback: CallbackQuery):
    """Handle abort / cancellation request from admin."""
    broadcast_id = callback.data.split(":", 1)[1]
    if broadcast_id in active_broadcasts:
        active_broadcasts[broadcast_id]["cancel_requested"] = True
        await callback.answer("🛑 Aborting broadcast... Stopping immediately.", show_alert=True)
    else:
        await callback.answer("Broadcast is already finished or not active.", show_alert=True)
