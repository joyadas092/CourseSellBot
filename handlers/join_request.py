import logging
from aiogram import Router
from aiogram.types import ChatJoinRequest
from services.invite_service import InviteService

logger = logging.getLogger(__name__)

router = Router(name="join_request_router")


@router.chat_join_request()
async def on_chat_join_request(request: ChatJoinRequest):
    """
    Handles ChatJoinRequest when a user clicks a restricted invite link:
    - If legitimate buyer: Approves join request, revokes the link, marks joined, sends welcome.
    - If intruder / different user: Declines join request and immediately alerts legitimate buyer!
    """
    try:
        await InviteService.process_chat_join_request(request.bot, request)
    except Exception as e:
        logger.error(f"Error handling chat join request: {e}", exc_info=True)
