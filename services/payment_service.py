import asyncio
import base64
import json
import logging
import random
import string
import time
from typing import Dict, Any, Optional
import aiohttp
from aiogram import Bot
from config import settings
from database.repositories.payment_repo import PaymentRepository

logger = logging.getLogger(__name__)

PAYMENT_SESSION_TTL_SECONDS = 15 * 60  # 15 minutes


class PaymentService:
    """Service handling payment gateways (Razorpay UPI QR, Payment Links, etc.)"""

    @classmethod
    def _get_client_session(cls, timeout: Optional[aiohttp.ClientTimeout] = None, headers: Optional[dict] = None) -> aiohttp.ClientSession:
        """Create a resilient aiohttp ClientSession with ThreadedResolver to avoid Windows aiodns issues."""
        try:
            connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
            return aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers)
        except Exception:
            return aiohttp.ClientSession(timeout=timeout, headers=headers)

    @classmethod
    async def _razorpay_auth_header(cls) -> dict:
        key_id = settings.RAZORPAY_KEY_ID
        key_secret = settings.RAZORPAY_KEY_SECRET
        if not key_id or not key_secret:
            raise RuntimeError("Razorpay credentials are not configured in settings")
        token = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    @classmethod
    async def create_razorpay_upi_qr(cls, user_id: int, amount_inr: float, pay_ref: str, title: str) -> dict:
        """Create a dynamic single-use UPI QR Code via Razorpay API."""
        close_at = int(time.time() + PAYMENT_SESSION_TTL_SECONDS)
        payload = {
            "type": "upi_qr",
            "usage": "single_use",
            "fixed_amount": True,
            "payment_amount": int(round(amount_inr * 100)),
            "close_by": close_at,
            "description": f"Course Access - {title[:30]}",
            "notes": {
                "user_id": str(user_id),
                "pay_ref": pay_ref,
            },
        }
        headers = await cls._razorpay_auth_header()
        async with cls._get_client_session() as session:
            async with session.post("https://api.razorpay.com/v1/payments/qr_codes", headers=headers, json=payload) as resp:
                body = await resp.text()
                if resp.status < 400:
                    return json.loads(body)
                # Retry once without close_by if merchant account disallows it
                if "close_by" in body.lower():
                    payload.pop("close_by", None)
                    async with session.post("https://api.razorpay.com/v1/payments/qr_codes", headers=headers, json=payload) as retry_resp:
                        retry_body = await retry_resp.text()
                        if retry_resp.status < 400:
                            return json.loads(retry_body)
                        raise RuntimeError(f"Razorpay UPI-QR error: {retry_resp.status} {retry_body[:300]}")
                raise RuntimeError(f"Razorpay UPI-QR error: {resp.status} {body[:300]}")

    @classmethod
    async def create_razorpay_payment_link(cls, user_id: int, amount_inr: float, pay_ref: str, title: str) -> dict:
        """Create a hosted checkout payment link on Razorpay."""
        expires_at = int(time.time() + PAYMENT_SESSION_TTL_SECONDS)
        payload = {
            "amount": int(round(amount_inr * 100)),
            "currency": "INR",
            "accept_partial": False,
            "description": f"Course Access - {title[:30]}",
            "reference_id": f"tg_{user_id}_{pay_ref[:10]}",
            "expire_by": expires_at,
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": {
                "user_id": str(user_id),
                "pay_ref": pay_ref,
            },
        }
        headers = await cls._razorpay_auth_header()
        async with cls._get_client_session() as session:
            async with session.post("https://api.razorpay.com/v1/payment_links", headers=headers, json=payload) as resp:
                body = await resp.text()
                if resp.status < 400:
                    return json.loads(body)
                if "expire_by" in body.lower():
                    payload.pop("expire_by", None)
                    async with session.post("https://api.razorpay.com/v1/payment_links", headers=headers, json=payload) as retry_resp:
                        retry_body = await retry_resp.text()
                        if retry_resp.status < 400:
                            return json.loads(retry_body)
                        raise RuntimeError(f"Razorpay payment-link error: {retry_resp.status} {retry_body[:300]}")
                raise RuntimeError(f"Razorpay payment-link error: {resp.status} {body[:300]}")

    @classmethod
    async def download_qr_image_bytes(cls, image_url: str) -> bytes:
        """Download QR code image from URL into in-memory bytes."""
        if not image_url:
            raise RuntimeError("Missing QR image URL")
        timeout = aiohttp.ClientTimeout(total=20)
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; CourseSellingBot/1.0)",
            "Accept": "image/*,*/*;q=0.8",
        }
        async with cls._get_client_session(timeout=timeout, headers=headers) as session:
            async with session.get(image_url) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise RuntimeError(f"QR download failed: {resp.status} {body[:200]}")
                return await resp.read()

    @classmethod
    async def get_razorpay_qr(cls, qr_code_id: str) -> dict:
        """Check status of Razorpay QR Code."""
        headers = await cls._razorpay_auth_header()
        async with cls._get_client_session() as session:
            async with session.get(f"https://api.razorpay.com/v1/payments/qr_codes/{qr_code_id}", headers=headers) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"Razorpay QR status error: {resp.status} {body[:200]}")
                return json.loads(body)

    @classmethod
    async def get_razorpay_payment_link(cls, payment_link_id: str) -> dict:
        """Check status of Razorpay Payment Link."""
        headers = await cls._razorpay_auth_header()
        async with cls._get_client_session() as session:
            async with session.get(f"https://api.razorpay.com/v1/payment_links/{payment_link_id}", headers=headers) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"Razorpay payment-link status error: {resp.status} {body[:200]}")
                return json.loads(body)

    @classmethod
    def schedule_delete_payment_post_in(cls, bot: Bot, chat_id: int, message_id: int, pay_ref: str, delay_seconds: int = PAYMENT_SESSION_TTL_SECONDS) -> None:
        """Auto-delete QR / Payment post after delay if unpaid."""
        async def _runner():
            await asyncio.sleep(max(1, int(delay_seconds)))
            payment = await PaymentRepository.get_by_ref(pay_ref)
            if payment and payment.get("status") == "paid":
                return  # Already paid and dealt with

            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass

            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="⌛ <b>Payment session expired (15 minutes).</b>\n\nQR code / payment link has been auto-deleted.\nPlease tap /start to generate a fresh payment if you still wish to join."
                )
            except Exception:
                pass

        asyncio.create_task(_runner())

    @classmethod
    async def delete_payment_post_now(cls, bot: Bot, pay_ref: str) -> None:
        """Immediately delete QR code / payment message upon payment confirmation."""
        if not pay_ref:
            return
        payment = await PaymentRepository.get_by_ref(pay_ref)
        if not payment:
            return
        metadata = payment.get("metadata", {})
        chat_id = metadata.get("post_chat_id")
        message_id = metadata.get("post_message_id")
        if chat_id and message_id:
            try:
                await bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
            except Exception:
                pass

    # ==========================================
    # PayPal REST API Integration
    # ==========================================

    _paypal_token_cache = {"token": "", "expires_at": 0}

    @classmethod
    def _paypal_base_url(cls) -> str:
        if (settings.PAYPAL_MODE or "").lower() == "sandbox":
            return "https://api-m.sandbox.paypal.com"
        return "https://api-m.paypal.com"

    @classmethod
    async def _paypal_get_access_token(cls) -> str:
        now = time.time()
        if cls._paypal_token_cache["token"] and cls._paypal_token_cache["expires_at"] > now + 60:
            return cls._paypal_token_cache["token"]

        client_id = settings.PAYPAL_CLIENT_ID
        client_secret = settings.PAYPAL_CLIENT_SECRET
        if not client_id or not client_secret:
            raise RuntimeError("PayPal credentials are not configured in settings")

        base_url = cls._paypal_base_url()
        auth_bytes = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_bytes}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {"grant_type": "client_credentials"}

        async with cls._get_client_session() as session:
            async with session.post(f"{base_url}/v1/oauth2/token", headers=headers, data=data) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"PayPal OAuth error: {resp.status} {body[:200]}")
                res = json.loads(body)
                token = res.get("access_token", "")
                expires_in = int(res.get("expires_in", 3600))
                cls._paypal_token_cache["token"] = token
                cls._paypal_token_cache["expires_at"] = now + expires_in
                return token

    @classmethod
    async def create_paypal_order(cls, user_id: int, amount_usd: float, pay_ref: str, title: str) -> dict:
        """Create a PayPal checkout order."""
        token = await cls._paypal_get_access_token()
        base_url = cls._paypal_base_url()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": pay_ref,
                    "custom_id": f"{user_id}:{pay_ref}",
                    "description": f"Access: {title[:50]}",
                    "amount": {
                        "currency_code": "USD",
                        "value": f"{amount_usd:.2f}"
                    }
                }
            ],
            "application_context": {
                "brand_name": "Premium Course Access",
                "landing_page": "NO_PREFERENCE",
                "user_action": "PAY_NOW"
            }
        }
        async with cls._get_client_session() as session:
            async with session.post(f"{base_url}/v2/checkout/orders", headers=headers, json=payload) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"PayPal Order creation error: {resp.status} {body[:200]}")
                return json.loads(body)

    @classmethod
    async def capture_paypal_order(cls, order_id: str) -> dict:
        """Capture an approved PayPal order."""
        token = await cls._paypal_get_access_token()
        base_url = cls._paypal_base_url()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        async with cls._get_client_session() as session:
            async with session.post(f"{base_url}/v2/checkout/orders/{order_id}/capture", headers=headers, json={}) as resp:
                body = await resp.text()
                if resp.status == 422:
                    # Order might already be captured, fetch details
                    return await cls.get_paypal_order(order_id)
                if resp.status >= 400:
                    raise RuntimeError(f"PayPal capture error: {resp.status} {body[:200]}")
                return json.loads(body)

    @classmethod
    async def get_paypal_order(cls, order_id: str) -> dict:
        """Fetch details of a PayPal order."""
        token = await cls._paypal_get_access_token()
        base_url = cls._paypal_base_url()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        async with cls._get_client_session() as session:
            async with session.get(f"{base_url}/v2/checkout/orders/{order_id}", headers=headers) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"PayPal order fetch error: {resp.status} {body[:200]}")
                return json.loads(body)
