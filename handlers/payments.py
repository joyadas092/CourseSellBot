import asyncio
import logging
import random
import string
import time
import uuid
from datetime import datetime, timezone
from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
    BufferedInputFile
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from config import settings
from database.repositories.folder_repo import FolderRepository
from database.repositories.payment_repo import PaymentRepository
from database.repositories.subscription_repo import SubscriptionRepository
from database.repositories.user_repo import UserRepository
from database.repositories.settings_repo import SettingsRepository
from services.payment_service import PaymentService, PAYMENT_SESSION_TTL_SECONDS
from services.invite_service import InviteService
from keyboards.user_kb import (
    build_payment_methods_keyboard,
    build_payment_action_keyboard
)
from keyboards.admin_kb import build_admin_manual_payment_keyboard

logger = logging.getLogger(__name__)

router = Router(name="payments_router")

# Concurrency & Debounce locks to prevent duplicate rapid verification / duplicate subscription grants
_in_flight_verifications: set = set()
_user_locks: dict = {}


def _get_user_lock(user_id: int) -> asyncio.Lock:
    import asyncio
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


class ManualPaymentStates(StatesGroup):
    waiting_for_proof = State()


class AdminRejectState(StatesGroup):
    waiting_for_reason = State()


# ==========================================
# Free Demo Plan (2 Minutes) Flow
# ==========================================

@router.callback_query(F.data.startswith("claim_demo:"))
async def cb_claim_demo(callback: CallbackQuery):
    """Initiates free 2-minute demo claim with lifetime check and warning."""
    user_id = callback.from_user.id
    folder_id = callback.data.split(":", 1)[1]

    # 1. Lifetime demo consumption check
    already_used = await UserRepository.has_used_demo(user_id)
    if already_used:
        await callback.answer(
            "⚠️ You have already consumed your demo plan! Lifetime limit is 1 trial per user. Please upgrade to a paid plan.",
            show_alert=True
        )
        return

    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        await callback.answer("Course not found.", show_alert=True)
        return

    if not folder.get("has_demo", True):
        await callback.answer("Demo access is currently disabled for this course.", show_alert=True)
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Start 2-Minute Demo Now", callback_data=f"confirm_demo:{folder_id}")],
        [InlineKeyboardButton(text="🔙 Back to Course", callback_data=f"fld_view:{folder_id}")]
    ])

    text = (
        f"🎁 <b>Free 2-Minute Demo Trial</b>\n\n"
        f"📦 <b>Course:</b> {folder['title']}\n"
        f"⏱️ <b>Duration:</b> Exactly 2 Minutes\n"
        f"💰 <b>Price:</b> Free (₹0)\n\n"
        "⚠️ <b>IMPORTANT / ध्यान दें:</b>\n"
        "1. Your <b>2-minute preview timer</b> begins the moment you join the private channel.\n"
        "2. Exactly 2 minutes after joining, you will be <b>automatically removed</b> by the bot.\n"
        "3. <b>Lifetime Limit:</b> Each user is allowed only <b>1 free demo trial</b> for their lifetime.\n\n"
        "👉 <i>Would you like to start your 2-minute free trial now?</i>"
    )

    msg = callback.message
    if msg.photo:
        try:
            await msg.delete()
        except Exception:
            pass
        await callback.bot.send_message(chat_id=msg.chat.id, text=text, reply_markup=confirm_kb)
    else:
        try:
            await msg.edit_text(text=text, reply_markup=confirm_kb)
        except Exception:
            await callback.bot.send_message(chat_id=msg.chat.id, text=text, reply_markup=confirm_kb)
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_demo:"))
async def cb_confirm_demo(callback: CallbackQuery):
    """Confirms demo, marks lifetime consumed, creates invite link and delivers it."""
    user_id = callback.from_user.id
    folder_id = callback.data.split(":", 1)[1]

    # Re-check lifetime demo lock to prevent concurrency race
    already_used = await UserRepository.has_used_demo(user_id)
    if already_used:
        await callback.answer(
            "⚠️ You have already consumed your demo plan! You cannot claim it again.",
            show_alert=True
        )
        return

    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        await callback.answer("Course not found.", show_alert=True)
        return

    target_chat_id = folder.get("target_chat_id")
    if not target_chat_id or target_chat_id == -1000000000000:
        await callback.answer(
            "⚠️ The target channel is not configured yet by admin. Please contact support.",
            show_alert=True
        )
        return

    # 1. Mark lifetime demo as consumed immediately
    await UserRepository.mark_demo_used(user_id, folder_id)

    # 2. Create demo subscription record in DB (120 seconds duration)
    pay_ref = f"demo_{uuid.uuid4().hex[:10]}"
    sub = await SubscriptionRepository.create_subscription(
        user_id=user_id,
        folder_id=folder_id,
        folder_title=folder["title"],
        target_chat_id=target_chat_id,
        plan_id="demo",
        plan_label="Free Demo (2 Mins)",
        days=0,
        amount=0.0,
        currency="FREE",
        gateway="free_demo",
        pay_ref=pay_ref,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
        is_demo=True,
        duration_seconds=120
    )
    sub_id = sub["subscription_id"]

    # 3. Generate restricted single-use invite link (creates_join_request=True)
    invite_link = None
    try:
        invite_link = await InviteService.generate_user_invite_link(
            bot=callback.bot,
            chat_id=target_chat_id,
            user_id=user_id,
            subscription_id=sub_id
        )
    except Exception as e:
        logger.error(f"Failed to create demo invite link: {e}")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    if invite_link:
        join_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Join Private Channel (Demo)", url=invite_link)],
            [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
        ])
        msg_text = (
            f"🎁 <b>Free Demo Activated!</b>\n\n"
            f"📦 <b>Course:</b> {folder['title']}\n"
            f"⏱️ <b>Trial Validity:</b> Exactly 2 Minutes\n\n"
            f"👇 <b>Click below to join the private channel:</b>\n"
            f"<a href=\"{invite_link}\">🔗 Direct Demo Join Link</a>\n\n"
            "⚠️ <b>IMPORTANT INSTRUCTIONS:</b>\n"
            "• Your 2-minute timer starts the moment your join request is accepted.\n"
            "• After 2 minutes, the bot will automatically remove you from the channel.\n"
            "• <i>(2 मिनट पूर्ण होने पर आप ऑटोमेटिकली रिमूव हो जाएंगे)</i>\n"
            "• Lifetime limit is 1 free demo per user."
        )
    else:
        join_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Contact Admin", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
        ])
        msg_text = (
            f"🎁 <b>Free Demo Plan</b>\n\n"
            "⚠️ Bot encountered an issue generating the invite link. "
            f"Please contact @{settings.SUPPORT_USERNAME}."
        )

    msg = callback.message
    if msg.photo:
        try:
            await msg.delete()
        except Exception:
            pass
        await callback.bot.send_message(chat_id=msg.chat.id, text=msg_text, reply_markup=join_kb)
    else:
        try:
            await msg.edit_text(text=msg_text, reply_markup=join_kb)
        except Exception:
            await callback.bot.send_message(chat_id=msg.chat.id, text=msg_text, reply_markup=join_kb)

    await callback.answer("Demo activated! Tap the link to join.", show_alert=False)


# ==========================================
# Plan Selection & Payment Method Menu
# ==========================================

@router.callback_query(F.data.startswith("buy_plan:"))
async def cb_buy_plan(callback: CallbackQuery):
    """Present payment methods for selected plan."""
    parts = callback.data.split(":")
    folder_id = parts[1]
    plan_id = parts[2]

    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        await callback.answer("Course not found.", show_alert=True)
        return

    plans = folder.get("plans", [])
    selected_plan = next((p for p in plans if p.get("plan_id") == plan_id), None)
    if not selected_plan:
        await callback.answer("Selected pricing plan is no longer available.", show_alert=True)
        return

    label = selected_plan.get("label", "Plan")
    days = selected_plan.get("days", 30)
    price_inr = selected_plan.get("price_inr", 0)
    stars = selected_plan.get("stars", max(1, int(price_inr * 0.75)))
    price_usd = selected_plan.get("price_usd", round(price_inr / 85.0, 2))

    text = (
        f"💎 <b>Checkout: {folder['title']}</b>\n\n"
        f"📦 <b>Selected Tier:</b> {label} ({days} Days Access)\n"
        f"💵 <b>Price:</b> ₹{price_inr} INR • {stars} ⭐️ Telegram Stars (${price_usd} USD)\n\n"
        "👇 <b>Select your preferred payment method below:</b>"
    )

    markup = build_payment_methods_keyboard(folder_id, plan_id, selected_plan)

    msg = callback.message
    if msg.photo:
        try:
            await msg.delete()
        except Exception:
            pass
        await callback.bot.send_message(chat_id=msg.chat.id, text=text, reply_markup=markup)
    else:
        try:
            await msg.edit_text(text=text, reply_markup=markup)
        except Exception:
            await callback.bot.send_message(chat_id=msg.chat.id, text=text, reply_markup=markup)

    await callback.answer()


# ==========================================
# Razorpay UPI QR Code
# ==========================================

@router.callback_query(F.data.startswith("pay_upiqr:"))
async def cb_pay_upiqr(callback: CallbackQuery):
    parts = callback.data.split(":")
    folder_id = parts[1]
    plan_id = parts[2]

    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        await callback.answer("Course not found.", show_alert=True)
        return

    plans = folder.get("plans", [])
    plan = next((p for p in plans if p.get("plan_id") == plan_id), None)
    if not plan:
        await callback.answer("Plan not found.", show_alert=True)
        return

    user_id = callback.from_user.id
    pay_ref = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

    status_msg = await callback.message.reply("⏳ <i>Generating UPI QR code... Please wait 5 seconds.</i>")

    try:
        qr_data = await PaymentService.create_razorpay_upi_qr(
            user_id=user_id,
            amount_inr=plan["price_inr"],
            pay_ref=pay_ref,
            title=folder["title"]
        )
        qr_image_url = qr_data.get("image_url", "")
        qr_code_id = qr_data.get("id", "")
        if not qr_image_url:
            raise RuntimeError("Missing QR image URL from Razorpay")

        qr_bytes = await PaymentService.download_qr_image_bytes(qr_image_url)

        # Store payment record
        await PaymentRepository.create_payment(
            pay_ref=pay_ref,
            user_id=user_id,
            folder_id=folder_id,
            plan_id=plan_id,
            amount=plan["price_inr"],
            currency="INR",
            gateway="razorpay_upiqr",
            order_id=qr_code_id,
            metadata={
                "qr_code_id": qr_code_id,
                "expires_at": time.time() + PAYMENT_SESSION_TTL_SECONDS
            },
            username=callback.from_user.username
        )

        caption = (
            f"💳 <b>Course Access:</b> {folder['title']}\n"
            f"📦 <b>Tier:</b> {plan.get('label')} ({plan.get('days')} Days)\n"
            f"💰 <b>Amount:</b> ₹{plan['price_inr']}\n"
            f"🔑 <b>Reference:</b> <code>{pay_ref}</code>\n\n"
            "<b>➡️ Pay using UPI QR (Scan & Pay)</b>\n\n"
            "<u>How to pay:</u>\n"
            "1. Save / Screenshot this QR code.\n"
            "2. Open any UPI app (Google Pay, PhonePe, Paytm, BHIM).\n"
            f"3. Scan and complete payment of <b>₹{plan['price_inr']}</b>.\n"
            "4. Return here and tap <b>✅ I Have Paid</b> below.\n\n"
            "⏳ <i>This QR code will be auto-deleted in 15 minutes.</i>"
        )

        kb = build_payment_action_keyboard(pay_ref)
        qr_photo = BufferedInputFile(qr_bytes, filename=f"upi_qr_{pay_ref}.png")
        payment_post = await callback.message.reply_photo(photo=qr_photo, caption=caption, reply_markup=kb)

        # Save post ID for auto deletion
        await PaymentRepository.update_metadata(
            pay_ref,
            {"post_chat_id": payment_post.chat.id, "post_message_id": payment_post.message_id}
        )

        PaymentService.schedule_delete_payment_post_in(
            bot=callback.bot,
            chat_id=payment_post.chat.id,
            message_id=payment_post.message_id,
            pay_ref=pay_ref,
            delay_seconds=PAYMENT_SESSION_TTL_SECONDS
        )

        await status_msg.delete()
    except Exception as e:
        logger.error(f"Failed to generate UPI QR: {e}")
        try:
            await status_msg.edit_text(f"❌ Failed to generate UPI QR: {e}\n\nPlease try another payment method or contact support.")
        except Exception:
            pass


# ==========================================
# Razorpay Cards / NetBanking / Payment Link
# ==========================================

@router.callback_query(F.data.startswith("pay_cards:"))
async def cb_pay_cards(callback: CallbackQuery):
    parts = callback.data.split(":")
    folder_id = parts[1]
    plan_id = parts[2]

    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        await callback.answer("Course not found.", show_alert=True)
        return

    plans = folder.get("plans", [])
    plan = next((p for p in plans if p.get("plan_id") == plan_id), None)
    if not plan:
        await callback.answer("Plan not found.", show_alert=True)
        return

    user_id = callback.from_user.id
    pay_ref = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

    status_msg = await callback.message.reply("⏳ <i>Creating payment link... Please wait.</i>")

    try:
        link_data = await PaymentService.create_razorpay_payment_link(
            user_id=user_id,
            amount_inr=plan["price_inr"],
            pay_ref=pay_ref,
            title=folder["title"]
        )
        short_url = link_data.get("short_url", "")
        link_id = link_data.get("id", "")
        if not short_url:
            raise RuntimeError("Missing short_url from Razorpay")

        await PaymentRepository.create_payment(
            pay_ref=pay_ref,
            user_id=user_id,
            folder_id=folder_id,
            plan_id=plan_id,
            amount=plan["price_inr"],
            currency="INR",
            gateway="razorpay_link",
            order_id=link_id,
            metadata={
                "payment_link_id": link_id,
                "expires_at": time.time() + PAYMENT_SESSION_TTL_SECONDS
            },
            username=callback.from_user.username
        )

        kb = build_payment_action_keyboard(pay_ref)
        # Prepend Open Link button
        from aiogram.types import InlineKeyboardButton
        kb.inline_keyboard.insert(0, [InlineKeyboardButton(text="🔐 Open Payment Link", url=short_url)])

        payment_post = await callback.message.reply(
            f"💳 <b>Pay via Cards / UPI / NetBanking</b>\n\n"
            f"📦 <b>Course:</b> {folder['title']} ({plan.get('label')})\n"
            f"💰 <b>Amount:</b> ₹{plan['price_inr']}\n"
            f"🔑 <b>Reference:</b> <code>{pay_ref}</code>\n\n"
            "Click the <b>🔐 Open Payment Link</b> button to pay.\n"
            "After payment, return here and tap <b>✅ I Have Paid</b>.\n\n"
            "⏳ <i>Valid for 15 minutes.</i>",
            reply_markup=kb
        )

        await PaymentRepository.update_metadata(
            pay_ref,
            {"post_chat_id": payment_post.chat.id, "post_message_id": payment_post.message_id}
        )

        PaymentService.schedule_delete_payment_post_in(
            bot=callback.bot,
            chat_id=payment_post.chat.id,
            message_id=payment_post.message_id,
            pay_ref=pay_ref,
            delay_seconds=PAYMENT_SESSION_TTL_SECONDS
        )

        await status_msg.delete()
    except Exception as e:
        logger.error(f"Failed to generate Payment Link: {e}")
        try:
            await status_msg.edit_text(f"❌ Failed to create payment link: {e}\n\nPlease try again shortly or contact support.")
        except Exception:
            pass


# ==========================================
# Telegram Stars Payment
# ==========================================

@router.callback_query(F.data.startswith("pay_stars:"))
async def cb_pay_stars(callback: CallbackQuery):
    parts = callback.data.split(":")
    folder_id = parts[1]
    plan_id = parts[2]

    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        await callback.answer("Course not found.", show_alert=True)
        return

    plans = folder.get("plans", [])
    plan = next((p for p in plans if p.get("plan_id") == plan_id), None)
    if not plan:
        await callback.answer("Plan not found.", show_alert=True)
        return

    stars_amount = plan.get("stars", max(1, int(plan.get("price_inr", 100) * 0.75)))
    user_id = callback.from_user.id
    pay_ref = f"stars_{uuid.uuid4().hex[:10]}"

    await PaymentRepository.create_payment(
        pay_ref=pay_ref,
        user_id=user_id,
        folder_id=folder_id,
        plan_id=plan_id,
        amount=stars_amount,
        currency="XTR",
        gateway="stars",
        username=callback.from_user.username
    )

    prices = [LabeledPrice(label=f"{folder['title']} ({plan.get('label')})", amount=stars_amount)]

    await callback.bot.send_invoice(
        chat_id=user_id,
        title=f"Access: {folder['title']}",
        description=f"{plan.get('label')} ({plan.get('days')} Days Access)",
        payload=pay_ref,
        currency="XTR",
        prices=prices,
        provider_token=""
    )
    await callback.answer("Stars invoice sent! Tap above to complete payment.")


@router.pre_checkout_query()
async def process_pre_checkout_query(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    sp = message.successful_payment
    pay_ref = sp.invoice_payload
    telegram_charge_id = sp.telegram_payment_charge_id
    total_amount = sp.total_amount
    user_id = message.from_user.id

    payment = await PaymentRepository.get_by_ref(pay_ref)
    if not payment or payment.get("status") == "paid":
        return

    folder_id = payment["folder_id"]
    plan_id = payment["plan_id"]
    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        return

    plan = next((p for p in folder.get("plans", []) if p.get("plan_id") == plan_id), {})

    await PaymentRepository.mark_paid(
        pay_ref=pay_ref,
        payment_id=telegram_charge_id,
        gateway="stars"
    )

    await activate_access_for_user(
        bot=message.bot,
        user_id=user_id,
        folder=folder,
        plan=plan,
        amount=total_amount,
        currency="XTR",
        gateway="Telegram Stars",
        pay_ref=pay_ref,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )


# ==========================================
# Verification & Subscription Activation Logic
# ==========================================

@router.callback_query(F.data.startswith("checkpay:"))
async def cb_checkpay(callback: CallbackQuery):
    pay_ref = callback.data.split(":", 1)[1].strip()
    user_id = callback.from_user.id

    # 1. Debounce rapid double-clicks (prevent concurrent duplicate processing)
    if pay_ref in _in_flight_verifications:
        await callback.answer("⏳ Verification in progress, please wait...", show_alert=True)
        return

    _in_flight_verifications.add(pay_ref)
    try:
        async with _get_user_lock(user_id):
            payment = await PaymentRepository.get_by_ref(pay_ref)
            if not payment:
                await callback.answer("Payment session not found.", show_alert=True)
                return

            # If already paid (processed earlier or by webhook), delete post and exit
            if payment.get("status") == "paid":
                await PaymentService.delete_payment_post_now(callback.bot, pay_ref)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.answer("✅ Payment already confirmed and activated!", show_alert=True)
                return

            metadata = payment.get("metadata", {})
            expires_at = metadata.get("expires_at", 0)
            if expires_at and time.time() > expires_at:
                await PaymentService.delete_payment_post_now(callback.bot, pay_ref)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.answer("⌛ Payment session expired. Please start over from /start.", show_alert=True)
                return

            await callback.answer("🔄 Checking payment status with gateway...", show_alert=False)

            qr_code_id = metadata.get("qr_code_id", "")
            payment_link_id = metadata.get("payment_link_id", "")
            folder_id = payment["folder_id"]
            plan_id = payment["plan_id"]

            folder = await FolderRepository.get_folder(folder_id)
            plan = next((p for p in folder.get("plans", []) if p.get("plan_id") == plan_id), {}) if folder else {}

            is_paid = False
            payment_id = ""

            try:
                if qr_code_id:
                    qr_data = await PaymentService.get_razorpay_qr(qr_code_id)
                    received = int(qr_data.get("payments_amount_received") or 0)
                    payments_count = int(qr_data.get("payments_count") or 0)
                    expected = int(round(payment["amount"] * 100))
                    if received >= expected or payments_count > 0:
                        is_paid = True
                        payments = qr_data.get("payments") or []
                        if isinstance(payments, list) and payments:
                            first = payments[0] or {}
                            payment_id = first.get("id") or ""
                elif payment_link_id:
                    link_data = await PaymentService.get_razorpay_payment_link(payment_link_id)
                    if (link_data.get("status") or "").lower() == "paid":
                        is_paid = True
                        payment_id = link_data.get("payment_id") or ""
            except Exception as e:
                logger.error(f"Error checking Razorpay payment: {e}")

            if not is_paid:
                await callback.message.reply(
                    "❌ <b>Payment not detected yet.</b>\n\n"
                    "Please ensure you completed payment in your UPI app, wait 5-10 seconds, then tap <b>✅ I Have Paid</b> again.\n\n"
                    f"If money was deducted from your bank, please contact @{settings.SUPPORT_USERNAME}."
                )
                return

            # Dedup check against duplicate gateway payment fulfillment
            if payment_id and await PaymentRepository.is_payment_id_already_fulfilled(payment_id, exclude_pay_ref=pay_ref):
                await PaymentService.delete_payment_post_now(callback.bot, pay_ref)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.answer("⚠️ This transaction was already fulfilled on another session.", show_alert=True)
                return

            # Atomic claim session (prevents race condition & double validity grant)
            claimed = await PaymentRepository.claim_payment_session(
                pay_ref=pay_ref,
                payment_id=payment_id or f"rzp_{uuid.uuid4().hex[:8]}",
                gateway=payment.get("gateway", "razorpay_upiqr")
            )

            # Immediately delete QR code / payment link post from chat so no duplicate taps can happen
            await PaymentService.delete_payment_post_now(callback.bot, pay_ref)
            try:
                await callback.message.delete()
            except Exception:
                pass

            if not claimed:
                await callback.answer("✅ Payment already processed!", show_alert=True)
                return

            # Activate access and deliver secure single-use invite link
            await activate_access_for_user(
                bot=callback.bot,
                user_id=user_id,
                folder=folder,
                plan=plan,
                amount=payment["amount"],
                currency=payment.get("currency", "INR"),
                gateway="Razorpay UPI",
                pay_ref=pay_ref,
                username=callback.from_user.username,
                full_name=callback.from_user.full_name
            )
    finally:
        _in_flight_verifications.discard(pay_ref)


@router.callback_query(F.data.startswith("cancelpay:"))
async def cb_cancelpay(callback: CallbackQuery):
    pay_ref = callback.data.split(":", 1)[1].strip()
    await PaymentService.delete_payment_post_now(callback.bot, pay_ref)
    await callback.message.delete()
    await callback.answer("Payment cancelled.")


async def activate_access_for_user(
    bot: Bot,
    user_id: int,
    folder: dict,
    plan: dict,
    amount: float,
    currency: str,
    gateway: str,
    pay_ref: str,
    username: str = None,
    full_name: str = None
):
    """
    Activates the subscription and creates a unique single-use invite link (creates_join_request=True).
    This strictly restricts entry to this user only!
    """
    folder_id = folder["folder_id"]
    folder_title = folder["title"]
    target_chat_id = folder["target_chat_id"]
    plan_id = plan.get("plan_id", "default")
    plan_label = plan.get("label", "Access")
    days = int(plan.get("days", 30))

    # 1. Create or extend subscription in DB
    sub = await SubscriptionRepository.create_subscription(
        user_id=user_id,
        folder_id=folder_id,
        folder_title=folder_title,
        target_chat_id=target_chat_id,
        plan_id=plan_id,
        plan_label=plan_label,
        days=days,
        amount=amount,
        currency=currency,
        gateway=gateway,
        pay_ref=pay_ref,
        username=username,
        full_name=full_name
    )
    sub_id = sub["subscription_id"]

    # 2. Record spend in user repository
    await UserRepository.record_purchase(user_id, amount_inr=amount if currency == "INR" else 0)

    # 3. Generate unique restricted invite link (creates_join_request=True) if not already generated
    invite_link = sub.get("invite_link")
    if not invite_link:
        try:
            invite_link = await InviteService.generate_user_invite_link(
                bot=bot,
                chat_id=target_chat_id,
                user_id=user_id,
                subscription_id=sub_id
            )
        except Exception as e:
            logger.error(f"Failed to generate invite link for chat {target_chat_id}: {e}")

    valid_until = sub["valid_until"]
    valid_str = valid_until.strftime("%d %b %Y, %H:%M UTC") if isinstance(valid_until, datetime) else str(valid_until)

    # 4. Deliver invite link to user
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    if invite_link:
        join_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Join Private Channel Now", url=invite_link)],
            [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
        ])
        msg_text = (
            f"🎉 <b>Payment Successful! Access Granted</b>\n\n"
            f"📦 <b>Course:</b> {folder_title}\n"
            f"💎 <b>Plan:</b> {plan_label} ({days} Days)\n"
            f"⏳ <b>Valid Until:</b> <code>{valid_str}</code>\n\n"
            f"👇 <b>Click the button below to join the private channel:</b>\n"
            f"<a href=\"{invite_link}\">🔗 Direct Join Link</a>\n\n"
            f"⚠️ <b>IMPORTANT SECURITY NOTE:</b>\n"
            f"This invite link is strictly tied to your account (ID: <code>{user_id}</code>). "
            "After you join, it will expire automatically. If anyone else attempts to join with this link, "
            "their request will be rejected and reported to you."
        )
    else:
        join_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Contact Admin for Access", url=f"https://t.me/{settings.SUPPORT_USERNAME}")]
        ])
        msg_text = (
            f"🎉 <b>Payment Successful!</b>\n\n"
            f"You have purchased <b>{plan_label}</b> for <b>{folder_title}</b>.\n"
            "⚠️ The bot encountered an issue creating an automated invite link. "
            f"Please message @{settings.SUPPORT_USERNAME} with reference: <code>{pay_ref}</code> to be added manually."
        )

    try:
        await bot.send_message(chat_id=user_id, text=msg_text, reply_markup=join_kb)
    except Exception as e:
        logger.error(f"Failed to send confirmation to user {user_id}: {e}")

    # 5. Notify Log Channel / Admin
    if settings.LOG_CHANNEL_ID:
        try:
            await bot.send_message(
                chat_id=settings.LOG_CHANNEL_ID,
                text=(
                    f"💰 <b>New Purchase Confirmed!</b>\n\n"
                    f"• User: <code>{user_id}</code> (@{username or 'N/A'})\n"
                    f"• Course: <b>{folder_title}</b>\n"
                    f"• Plan: <b>{plan_label}</b> ({days}d)\n"
                    f"• Amount: <code>{amount} {currency}</code> ({gateway})\n"
                    f"• Ref: <code>{pay_ref}</code>"
                )
            )
        except Exception:
            pass


# ==========================================
# PayPal Checkout & Verification
# ==========================================

@router.callback_query(F.data.startswith("pay_paypal:"))
async def cb_pay_paypal(callback: CallbackQuery):
    parts = callback.data.split(":")
    folder_id = parts[1]
    plan_id = parts[2]

    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        await callback.answer("Course not found.", show_alert=True)
        return

    plans = folder.get("plans", [])
    plan = next((p for p in plans if p.get("plan_id") == plan_id), None)
    if not plan:
        await callback.answer("Plan not found.", show_alert=True)
        return

    user_id = callback.from_user.id
    pay_ref = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    price_usd = plan.get("price_usd", round(plan.get("price_inr", 100) / 85.0, 2))

    status_msg = await callback.message.reply("⏳ <i>Generating PayPal checkout link... Please wait.</i>")

    try:
        order_data = await PaymentService.create_paypal_order(
            user_id=user_id,
            amount_usd=price_usd,
            pay_ref=pay_ref,
            title=folder["title"]
        )
        order_id = order_data.get("id", "")
        links = order_data.get("links", [])
        approve_url = next((l["href"] for l in links if l.get("rel") == "approve"), "")

        if not approve_url:
            raise RuntimeError("Missing approval URL from PayPal order response")

        await PaymentRepository.create_payment(
            pay_ref=pay_ref,
            user_id=user_id,
            folder_id=folder_id,
            plan_id=plan_id,
            amount=price_usd,
            currency="USD",
            gateway="paypal",
            order_id=order_id,
            metadata={
                "paypal_order_id": order_id,
                "expires_at": time.time() + PAYMENT_SESSION_TTL_SECONDS
            },
            username=callback.from_user.username
        )

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🅿️ Open PayPal to Pay", url=approve_url)],
            [InlineKeyboardButton(text="✅ I Have Paid", callback_data=f"check_paypal:{pay_ref}")],
            [
                InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancelpay:{pay_ref}")
            ]
        ])

        payment_post = await callback.message.reply(
            f"🅿️ <b>Pay with PayPal</b>\n\n"
            f"📦 <b>Course:</b> {folder['title']} ({plan.get('label')})\n"
            f"💰 <b>Amount:</b> ${price_usd} USD\n"
            f"🔑 <b>Reference:</b> <code>{pay_ref}</code>\n\n"
            "<u>How to pay:</u>\n"
            "1. Tap <b>🅿️ Open PayPal to Pay</b> to complete payment in browser.\n"
            "2. After payment approval, return here and tap <b>✅ I Have Paid</b>.\n\n"
            "⏳ <i>Valid for 15 minutes.</i>",
            reply_markup=kb
        )

        await PaymentRepository.update_metadata(
            pay_ref,
            {"post_chat_id": payment_post.chat.id, "post_message_id": payment_post.message_id}
        )

        PaymentService.schedule_delete_payment_post_in(
            bot=callback.bot,
            chat_id=payment_post.chat.id,
            message_id=payment_post.message_id,
            pay_ref=pay_ref,
            delay_seconds=PAYMENT_SESSION_TTL_SECONDS
        )

        await status_msg.delete()
    except Exception as e:
        logger.error(f"Failed to generate PayPal order: {e}")
        try:
            await status_msg.edit_text(f"❌ Failed to initiate PayPal: {e}\n\nPlease try another payment method or contact support.")
        except Exception:
            pass


@router.callback_query(F.data.startswith("check_paypal:"))
async def cb_check_paypal(callback: CallbackQuery):
    pay_ref = callback.data.split(":", 1)[1].strip()
    user_id = callback.from_user.id

    # 1. Debounce rapid double-clicks (prevent concurrent duplicate processing)
    if pay_ref in _in_flight_verifications:
        await callback.answer("⏳ Verification in progress, please wait...", show_alert=True)
        return

    _in_flight_verifications.add(pay_ref)
    try:
        async with _get_user_lock(user_id):
            payment = await PaymentRepository.get_by_ref(pay_ref)
            if not payment:
                await callback.answer("Payment record not found.", show_alert=True)
                return

            if payment.get("status") == "paid":
                await PaymentService.delete_payment_post_now(callback.bot, pay_ref)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.answer("✅ Payment already confirmed and access activated!", show_alert=True)
                return

            metadata = payment.get("metadata", {})
            expires_at = metadata.get("expires_at", 0)
            if expires_at and time.time() > expires_at:
                await PaymentService.delete_payment_post_now(callback.bot, pay_ref)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.answer("⌛ Payment session expired. Please start over from /start.", show_alert=True)
                return

            await callback.answer("🔄 Verifying PayPal transaction...", show_alert=False)

            order_id = metadata.get("paypal_order_id", "")
            folder_id = payment["folder_id"]
            plan_id = payment["plan_id"]

            folder = await FolderRepository.get_folder(folder_id)
            plan = next((p for p in folder.get("plans", []) if p.get("plan_id") == plan_id), {}) if folder else {}

            is_paid = False
            capture_id = ""

            try:
                order_info = await PaymentService.get_paypal_order(order_id)
                order_status = (order_info.get("status") or "").upper()
                if order_status == "COMPLETED":
                    is_paid = True
                    pu = order_info.get("purchase_units", [{}])[0]
                    captures = pu.get("payments", {}).get("captures", [])
                    if captures:
                        capture_id = captures[0].get("id", "")
                elif order_status == "APPROVED":
                    cap_res = await PaymentService.capture_paypal_order(order_id)
                    cap_status = (cap_res.get("status") or "").upper()
                    if cap_status in ("COMPLETED", "APPROVED"):
                        is_paid = True
                        pu = cap_res.get("purchase_units", [{}])[0]
                        captures = pu.get("payments", {}).get("captures", [])
                        if captures:
                            capture_id = captures[0].get("id", "")
            except Exception as e:
                logger.error(f"Error checking PayPal order: {e}")

            if not is_paid:
                await callback.message.reply(
                    "❌ <b>Payment not completed yet.</b>\n\n"
                    "Please ensure you approved the payment in your PayPal account, then tap <b>✅ I Have Paid</b> again.\n\n"
                    f"If payment was charged, please contact @{settings.SUPPORT_USERNAME}."
                )
                return

            # Dedup check against duplicate gateway payment fulfillment
            if capture_id and await PaymentRepository.is_payment_id_already_fulfilled(capture_id, exclude_pay_ref=pay_ref):
                await PaymentService.delete_payment_post_now(callback.bot, pay_ref)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.answer("⚠️ This PayPal transaction was already fulfilled on another session.", show_alert=True)
                return

            # Atomic claim session (prevents race condition & double validity grant)
            claimed = await PaymentRepository.claim_payment_session(
                pay_ref=pay_ref,
                payment_id=capture_id or f"pp_{uuid.uuid4().hex[:8]}",
                gateway="paypal"
            )

            # Delete instruction post immediately
            await PaymentService.delete_payment_post_now(callback.bot, pay_ref)
            try:
                await callback.message.delete()
            except Exception:
                pass

            if not claimed:
                await callback.answer("✅ Payment already processed!", show_alert=True)
                return

            # Deliver access link (idempotent)
            await activate_access_for_user(
                bot=callback.bot,
                user_id=user_id,
                folder=folder,
                plan=plan,
                amount=payment["amount"],
                currency="USD",
                gateway="PayPal",
                pay_ref=pay_ref,
                username=callback.from_user.username,
                full_name=callback.from_user.full_name
            )
    finally:
        _in_flight_verifications.discard(pay_ref)


# ==========================================
# Crypto & Manual UPI Gateways
# ==========================================

@router.callback_query(F.data.startswith("pay_crypto:"))
async def cb_pay_crypto(callback: CallbackQuery):
    parts = callback.data.split(":")
    folder_id = parts[1]
    plan_id = parts[2]

    folder = await FolderRepository.get_folder(folder_id)
    plan = next((p for p in folder.get("plans", []) if p.get("plan_id") == plan_id), {}) if folder else {}

    price_usd = plan.get("price_usd", round(plan.get("price_inr", 100) / 85.0, 2))
    pay_ref = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

    # Create pending payment record
    await PaymentRepository.create_payment(
        pay_ref=pay_ref,
        user_id=callback.from_user.id,
        folder_id=folder_id,
        plan_id=plan_id,
        amount=price_usd,
        currency="USDT",
        gateway="crypto",
        username=callback.from_user.username
    )

    text = (
        f"🪙 <b>Pay with Crypto (USDT / TON)</b>\n\n"
        f"📦 <b>Course:</b> {folder.get('title')} ({plan.get('label')})\n"
        f"💵 <b>Amount to Send:</b> <code>${price_usd} USDT</code>\n"
        f"🔑 <b>Reference ID:</b> <code>{pay_ref}</code>\n\n"
        "<b>1. USDT (BEP-20 / Binance Smart Chain):</b>\n"
        f"<code>{settings.CRYPTO_USDT_BEP20}</code>\n\n"
        "<b>2. TON (The Open Network):</b>\n"
        f"<code>{settings.CRYPTO_TON_ADDRESS}</code>\n\n"
        "<u>Instructions:</u>\n"
        "1. Send the exact amount to either address above.\n"
        "2. Once sent, tap <b>📸 I Have Paid (Submit Proof)</b> below to upload your screenshot or transaction hash.\n"
        "3. Our team will verify and activate your access immediately."
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 I Have Paid (Submit Proof)", callback_data=f"submit_proof:{pay_ref}")],
        [
            InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}"),
            InlineKeyboardButton(text="🔙 Back", callback_data=f"buy_plan:{folder_id}:{plan_id}")
        ]
    ])

    sent_msg = await callback.message.reply(text, reply_markup=kb)
    await PaymentRepository.update_metadata(
        pay_ref,
        {"post_chat_id": sent_msg.chat.id, "post_message_id": sent_msg.message_id}
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay_manual:"))
async def cb_pay_manual(callback: CallbackQuery):
    parts = callback.data.split(":")
    folder_id = parts[1]
    plan_id = parts[2]

    folder = await FolderRepository.get_folder(folder_id)
    plan = next((p for p in folder.get("plans", []) if p.get("plan_id") == plan_id), {}) if folder else {}

    pay_ref = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    price_inr = plan.get("price_inr", 0)

    # Create pending payment record
    await PaymentRepository.create_payment(
        pay_ref=pay_ref,
        user_id=callback.from_user.id,
        folder_id=folder_id,
        plan_id=plan_id,
        amount=price_inr,
        currency="INR",
        gateway="manual_upi",
        username=callback.from_user.username
    )

    upi_id = settings.MANUAL_UPI_ID or "Please contact support for UPI"
    upi_name = settings.MANUAL_UPI_NAME or "Admin"

    text = (
        f"⚡ <b>Direct UPI Payment</b>\n\n"
        f"📦 <b>Course:</b> {folder.get('title')} ({plan.get('label')})\n"
        f"💰 <b>Amount to Pay:</b> <code>₹{price_inr}</code>\n"
        f"🔑 <b>Reference ID:</b> <code>{pay_ref}</code>\n\n"
        f"<b>UPI ID:</b> <code>{upi_id}</code>\n"
        f"<b>Payee Name:</b> {upi_name}\n\n"
        "<u>Instructions:</u>\n"
        f"1. Open any UPI app (GPay, PhonePe, Paytm) and transfer <b>₹{price_inr}</b> to the UPI ID above.\n"
        "2. Once paid, tap <b>📸 I Have Paid (Submit Proof)</b> below to upload the screenshot or 12-digit UTR.\n"
        "3. Our admin team will verify and grant access instantly."
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 I Have Paid (Submit Proof)", callback_data=f"submit_proof:{pay_ref}")],
        [
            InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{settings.SUPPORT_USERNAME}"),
            InlineKeyboardButton(text="🔙 Back", callback_data=f"buy_plan:{folder_id}:{plan_id}")
        ]
    ])

    sent_msg = await callback.message.reply(text, reply_markup=kb)
    await PaymentRepository.update_metadata(
        pay_ref,
        {"post_chat_id": sent_msg.chat.id, "post_message_id": sent_msg.message_id}
    )
    await callback.answer()


@router.callback_query(F.data.startswith("submit_proof:"))
async def cb_submit_proof(callback: CallbackQuery, state: FSMContext):
    pay_ref = callback.data.split(":", 1)[1].strip()
    payment = await PaymentRepository.get_by_ref(pay_ref)
    if not payment:
        await callback.answer("Payment session not found.", show_alert=True)
        return

    if payment.get("status") == "paid":
        await callback.answer("✅ This payment is already approved and active!", show_alert=True)
        return

    await state.set_state(ManualPaymentStates.waiting_for_proof)
    await state.update_data(pay_ref=pay_ref)

    prompt = (
        "📸 <b>Submit Payment Proof</b>\n\n"
        f"Please send your payment screenshot / receipt photo or enter your 12-digit UTR / transaction hash now for reference: <code>{pay_ref}</code>.\n\n"
        "<i>Make sure the amount and transaction reference are clearly visible.</i>\n\n"
        "Type /cancel to abort."
    )
    await callback.message.reply(prompt)
    await callback.answer()


@router.message(ManualPaymentStates.waiting_for_proof, Command("cancel"))
async def cancel_proof_submission(message: Message, state: FSMContext):
    await state.clear()
    await message.reply("🛑 Payment proof submission cancelled. You can try again anytime from /start.")


@router.message(ManualPaymentStates.waiting_for_proof, F.photo | F.document | F.text)
async def process_manual_payment_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    pay_ref = data.get("pay_ref")
    if not pay_ref:
        await state.clear()
        await message.reply("❌ Session expired. Please start over from /start.")
        return

    payment = await PaymentRepository.get_by_ref(pay_ref)
    if not payment or payment.get("status") == "paid":
        await state.clear()
        await message.reply("❌ Invalid or already processed payment.")
        return

    file_id = ""
    is_photo = False
    is_doc = False
    text_note = ""

    if message.photo:
        file_id = message.photo[-1].file_id
        is_photo = True
        text_note = message.caption or ""
    elif message.document:
        file_id = message.document.file_id
        is_doc = True
        text_note = message.caption or ""
    elif message.text:
        text_note = message.text.strip()

    await state.clear()

    # Delete original instruction message to keep chat tidy
    await PaymentService.delete_payment_post_now(message.bot, pay_ref)

    user_id = message.from_user.id
    folder_id = payment["folder_id"]
    plan_id = payment["plan_id"]
    amount = payment.get("amount", 0)
    currency = payment.get("currency", "INR")
    gateway = payment.get("gateway", "manual")

    folder = await FolderRepository.get_folder(folder_id)
    plan = next((p for p in folder.get("plans", []) if p.get("plan_id") == plan_id), {}) if folder else {}
    folder_title = folder.get("title", "Course") if folder else "Course"
    plan_label = plan.get("label", "Access")

    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%d %b %Y, %H:%M:%S UTC")

    # Update payment status & proof metadata
    await PaymentRepository.update_metadata(
        pay_ref,
        {
            "proof_file_id": file_id,
            "proof_type": "photo" if is_photo else ("document" if is_doc else "text"),
            "proof_text": text_note,
            "submitted_at": now_str
        }
    )

    await message.reply(
        "✅ <b>Payment Proof Submitted Successfully!</b>\n\n"
        "Your proof has been forwarded to our admin team for verification.\n"
        "Once approved, you will automatically receive your VIP access link right here.\n\n"
        f"🔑 <b>Reference ID:</b> <code>{pay_ref}</code>\n"
        f"💬 Support: @{settings.SUPPORT_USERNAME}"
    )

    # Format notification for Admins
    admin_caption = (
        "🚨 <b>MANUAL PAYMENT REVIEW REQUEST</b>\n\n"
        f"👤 <b>User:</b> {message.from_user.full_name} (@{message.from_user.username or 'N/A'})\n"
        f"🆔 <b>Telegram UID:</b> <code>{user_id}</code>\n"
        f"📦 <b>Course:</b> <b>{folder_title}</b>\n"
        f"💎 <b>Plan:</b> {plan_label} ({plan.get('days', 30)} Days)\n"
        f"💰 <b>Amount:</b> <code>{amount} {currency}</code> ({gateway})\n"
        f"🔑 <b>Reference ID:</b> <code>{pay_ref}</code>\n"
        f"⏰ <b>Submitted At:</b> <i>{now_str}</i>\n"
    )
    if text_note:
        admin_caption += f"\n📝 <b>User Note / UTR:</b> <code>{text_note}</code>\n"
    admin_caption += "\n👇 <b>Choose an Admin Action below:</b>"

    admin_kb = build_admin_manual_payment_keyboard(pay_ref, user_id)
    admin_dm_msg_ids = {}

    for admin_chat_id in settings.ADMIN_IDS:
        try:
            if is_photo:
                adm_msg = await message.bot.send_photo(
                    chat_id=admin_chat_id,
                    photo=file_id,
                    caption=admin_caption,
                    reply_markup=admin_kb
                )
            elif is_doc:
                adm_msg = await message.bot.send_document(
                    chat_id=admin_chat_id,
                    document=file_id,
                    caption=admin_caption,
                    reply_markup=admin_kb
                )
            else:
                adm_msg = await message.bot.send_message(
                    chat_id=admin_chat_id,
                    text=admin_caption,
                    reply_markup=admin_kb
                )
            admin_dm_msg_ids[str(admin_chat_id)] = adm_msg.message_id
        except Exception as e:
            logger.warning(f"Could not dispatch manual payment to admin {admin_chat_id}: {e}")

    # Log channel if configured
    log_channel_id = settings.LOG_CHANNEL_ID
    log_msg_id = None
    if log_channel_id:
        try:
            if is_photo:
                log_msg = await message.bot.send_photo(
                    chat_id=log_channel_id,
                    photo=file_id,
                    caption=admin_caption,
                    reply_markup=admin_kb
                )
            elif is_doc:
                log_msg = await message.bot.send_document(
                    chat_id=log_channel_id,
                    document=file_id,
                    caption=admin_caption,
                    reply_markup=admin_kb
                )
            else:
                log_msg = await message.bot.send_message(
                    chat_id=log_channel_id,
                    text=admin_caption,
                    reply_markup=admin_kb
                )
            log_msg_id = log_msg.message_id
        except Exception as e:
            logger.warning(f"Failed to forward proof to log channel: {e}")

    await PaymentRepository.update_metadata(
        pay_ref,
        {
            "admin_dm_msg_ids": admin_dm_msg_ids,
            "log_channel_id": log_channel_id,
            "log_channel_msg_id": log_msg_id
        }
    )


# ==========================================
# Admin Manual Payment Actions (Approve / Reject)
# ==========================================

def _is_caller_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


@router.callback_query(F.data.startswith("adm_appr_pay:"))
async def cb_adm_appr_pay(callback: CallbackQuery):
    admin_id = callback.from_user.id
    if not _is_caller_admin(admin_id):
        await callback.answer("⛔ Access denied. You are not an authorized admin.", show_alert=True)
        return

    pay_ref = callback.data.split(":", 1)[1].strip()
    payment = await PaymentRepository.get_by_ref(pay_ref)
    if not payment:
        await callback.answer("Payment record not found.", show_alert=True)
        return

    if payment.get("status") == "paid":
        await callback.answer("⚠️ This payment has already been approved!", show_alert=True)
        return

    if payment.get("status") in ("failed", "rejected"):
        await callback.answer("⚠️ This payment was previously rejected!", show_alert=True)
        return

    admin_tag = f"@{callback.from_user.username}" if callback.from_user.username else f"Admin {admin_id}"
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%d %b %Y, %H:%M UTC")

    # Atomic DB mark: prevents double approval
    marked = await PaymentRepository.mark_paid(
        pay_ref=pay_ref,
        payment_id=f"manual_{pay_ref}",
        gateway=f"Manual ({payment.get('gateway', 'upi')})",
        metadata_update={
            "approved_by_id": admin_id,
            "approved_by_name": admin_tag,
            "approved_at": now_str
        }
    )

    if not marked:
        await callback.answer("⚠️ Payment already processed by another admin!", show_alert=True)
        return

    folder_id = payment["folder_id"]
    plan_id = payment["plan_id"]
    user_id = payment["user_id"]
    folder = await FolderRepository.get_folder(folder_id)
    plan = next((p for p in folder.get("plans", []) if p.get("plan_id") == plan_id), {}) if folder else {}

    # Activate access and deliver single-use restricted invite link
    await activate_access_for_user(
        bot=callback.bot,
        user_id=user_id,
        folder=folder,
        plan=plan,
        amount=payment["amount"],
        currency=payment.get("currency", "INR"),
        gateway="Manual Approved",
        pay_ref=pay_ref,
        username=payment.get("username")
    )

    updated_caption = (
        "✅ <b>MANUAL PAYMENT APPROVED</b>\n\n"
        f"👤 <b>User ID:</b> <code>{user_id}</code> (@{payment.get('username') or 'N/A'})\n"
        f"📦 <b>Course:</b> <b>{folder.get('title')}</b>\n"
        f"💎 <b>Plan:</b> {plan.get('label')} ({plan.get('days')} Days)\n"
        f"💰 <b>Amount:</b> <code>{payment['amount']} {payment.get('currency')}</code>\n"
        f"🔑 <b>Reference ID:</b> <code>{pay_ref}</code>\n"
        f"👮 <b>Approved By:</b> {admin_tag}\n"
        f"⏰ <b>Approved At:</b> <i>{now_str}</i>\n\n"
        "<i>VIP invite link has been generated and delivered to the user.</i>"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    done_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approved & Link Sent", callback_data="noop")]
    ])

    try:
        if callback.message.photo or callback.message.document:
            await callback.message.edit_caption(caption=updated_caption, reply_markup=done_kb)
        else:
            await callback.message.edit_text(text=updated_caption, reply_markup=done_kb)
    except Exception:
        pass

    # Synchronize across other admin messages & log channel
    meta = payment.get("metadata", {})
    sync_targets = []
    if meta.get("log_channel_id") and meta.get("log_channel_msg_id"):
        sync_targets.append((meta["log_channel_id"], meta["log_channel_msg_id"]))
    dm_msgs = meta.get("admin_dm_msg_ids") or {}
    for a_id_str, m_id in dm_msgs.items():
        try:
            sync_targets.append((int(a_id_str), m_id))
        except (ValueError, TypeError):
            pass

    for sync_chat_id, sync_msg_id in sync_targets:
        if callback.message and sync_chat_id == callback.message.chat.id and sync_msg_id == callback.message.message_id:
            continue
        try:
            await callback.bot.edit_message_caption(
                chat_id=sync_chat_id,
                message_id=sync_msg_id,
                caption=updated_caption,
                reply_markup=done_kb
            )
        except Exception:
            try:
                await callback.bot.edit_message_text(
                    chat_id=sync_chat_id,
                    message_id=sync_msg_id,
                    text=updated_caption,
                    reply_markup=done_kb
                )
            except Exception:
                pass

    await callback.answer("✅ Payment approved and VIP access link sent!", show_alert=True)


@router.callback_query(F.data.startswith("adm_rej_quick:"))
async def cb_adm_rej_quick(callback: CallbackQuery):
    admin_id = callback.from_user.id
    if not _is_caller_admin(admin_id):
        await callback.answer("⛔ Access denied. Unauthorized admin.", show_alert=True)
        return

    pay_ref = callback.data.split(":", 1)[1].strip()
    payment = await PaymentRepository.get_by_ref(pay_ref)
    if not payment:
        await callback.answer("Payment record not found.", show_alert=True)
        return

    if payment.get("status") == "paid":
        await callback.answer("⚠️ Cannot reject: payment was already approved!", show_alert=True)
        return

    admin_tag = f"@{callback.from_user.username}" if callback.from_user.username else f"Admin {admin_id}"
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%d %b %Y, %H:%M UTC")

    await PaymentRepository.mark_rejected(pay_ref, reason=f"Quick reject by {admin_tag}")

    user_id = payment["user_id"]
    folder_id = payment["folder_id"]
    folder = await FolderRepository.get_folder(folder_id)
    folder_title = folder.get("title", "Course") if folder else "Course"

    # Notify user in clean English
    try:
        await callback.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ <b>Payment Proof Rejected</b>\n\n"
                f"Your payment proof for <b>{folder_title}</b> with reference <code>{pay_ref}</code> could not be verified and has been rejected.\n\n"
                f"If you believe this is an error, please contact our support team: @{settings.SUPPORT_USERNAME}."
            )
        )
    except Exception:
        pass

    updated_caption = (
        "❌ <b>PAYMENT REJECTED (QUICK REJECT)</b>\n\n"
        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📦 <b>Course:</b> {folder_title}\n"
        f"🔑 <b>Reference ID:</b> <code>{pay_ref}</code>\n"
        f"👮 <b>Rejected By:</b> {admin_tag}\n"
        f"⏰ <b>Rejected At:</b> <i>{now_str}</i>"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    done_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Payment Rejected", callback_data="noop")]
    ])

    try:
        if callback.message.photo or callback.message.document:
            await callback.message.edit_caption(caption=updated_caption, reply_markup=done_kb)
        else:
            await callback.message.edit_text(text=updated_caption, reply_markup=done_kb)
    except Exception:
        pass

    await callback.answer("❌ Payment rejected and user notified.", show_alert=True)


@router.callback_query(F.data.startswith("adm_rej_msg:"))
async def cb_adm_rej_msg(callback: CallbackQuery, state: FSMContext):
    admin_id = callback.from_user.id
    if not _is_caller_admin(admin_id):
        await callback.answer("⛔ Access denied. Unauthorized admin.", show_alert=True)
        return

    pay_ref = callback.data.split(":", 1)[1].strip()
    payment = await PaymentRepository.get_by_ref(pay_ref)
    if not payment:
        await callback.answer("Payment record not found.", show_alert=True)
        return

    if payment.get("status") == "paid":
        await callback.answer("⚠️ Cannot reject: payment was already approved!", show_alert=True)
        return

    await state.set_state(AdminRejectState.waiting_for_reason)
    await state.update_data(
        pay_ref=pay_ref,
        msg_chat_id=callback.message.chat.id,
        msg_id=callback.message.message_id
    )

    await callback.message.reply(
        f"💬 <b>Enter Rejection Reason for <code>{pay_ref}</code></b>\n\n"
        "Please type the reason for rejection (e.g. <i>'UTR not found in bank statement'</i>, <i>'Screenshot blurry'</i>, <i>'Incorrect amount'</i>):\n\n"
        "Send /cancel to abort."
    )
    await callback.answer()


@router.message(AdminRejectState.waiting_for_reason, Command("cancel"))
async def cancel_admin_rejection(message: Message, state: FSMContext):
    await state.clear()
    await message.reply("🛑 Rejection reason input cancelled.")


@router.message(AdminRejectState.waiting_for_reason, F.text)
async def process_admin_rejection_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    pay_ref = data.get("pay_ref")
    await state.clear()

    if not pay_ref:
        await message.reply("❌ Session lost.")
        return

    payment = await PaymentRepository.get_by_ref(pay_ref)
    if not payment or payment.get("status") == "paid":
        await message.reply("❌ Payment already processed or not found.")
        return

    reason = message.text.strip()
    admin_tag = f"@{message.from_user.username}" if message.from_user.username else f"Admin {message.from_user.id}"
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%d %b %Y, %H:%M UTC")

    await PaymentRepository.mark_rejected(pay_ref, reason=reason)

    user_id = payment["user_id"]
    folder_id = payment["folder_id"]
    folder = await FolderRepository.get_folder(folder_id)
    folder_title = folder.get("title", "Course") if folder else "Course"

    # Notify buyer with custom reason inside blockquote
    try:
        await message.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ <b>Payment Proof Rejected</b>\n\n"
                f"Your payment proof for <b>{folder_title}</b> with reference <code>{pay_ref}</code> was rejected.\n\n"
                "<b>Reason from Admin:</b>\n"
                f"<blockquote>{reason}</blockquote>\n\n"
                f"Please verify and submit again, or contact our support team: @{settings.SUPPORT_USERNAME}."
            )
        )
    except Exception:
        pass

    updated_caption = (
        "❌ <b>PAYMENT REJECTED WITH REASON</b>\n\n"
        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📦 <b>Course:</b> {folder_title}\n"
        f"🔑 <b>Reference ID:</b> <code>{pay_ref}</code>\n"
        f"👮 <b>Rejected By:</b> {admin_tag}\n"
        f"💬 <b>Reason:</b> <i>{reason}</i>\n"
        f"⏰ <b>Rejected At:</b> <i>{now_str}</i>"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    done_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Rejected with Reason", callback_data="noop")]
    ])

    await message.reply(updated_caption, reply_markup=done_kb)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()
