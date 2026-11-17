import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import settings
from database.repositories.folder_repo import FolderRepository
from keyboards.admin_kb import (
    build_admin_folders_list,
    build_admin_folder_edit_keyboard,
    build_admin_plans_keyboard
)

logger = logging.getLogger(__name__)

router = Router(name="admin_folder_crud_router")


def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


class AddFolderStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_btn_text = State()
    waiting_for_width = State()
    waiting_for_desc = State()
    waiting_for_chat_id = State()
    waiting_for_banner = State()


class EditFolderStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_btn_text = State()
    waiting_for_desc = State()
    waiting_for_banner = State()
    waiting_for_chat_id = State()
    waiting_for_demo = State()


class AddPlanStates(StatesGroup):
    waiting_for_label = State()
    waiting_for_days = State()
    waiting_for_price = State()


# ==========================================
# List Folders
# ==========================================

@router.callback_query(F.data == "adm_folders_list")
async def cb_adm_folders_list(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    await state.clear()
    folders = await FolderRepository.get_all_folders()
    text = (
        "📁 <b>Course / Folder Catalog Manager</b>\n\n"
        "Here are all your existing courses. Tap any folder to edit its details, description, banner, pricing tiers, or button mapping on /start."
    )
    markup = build_admin_folders_list(folders)

    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.reply(text, reply_markup=markup)
    await callback.answer()


# ==========================================
# Add New Folder Wizard
# ==========================================

@router.callback_query(F.data == "adm_add_folder")
async def cb_adm_add_folder(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    await state.set_state(AddFolderStates.waiting_for_title)
    await callback.message.reply(
        "➕ <b>Add New Course / Folder (Step 1/6)</b>\n\n"
        "Please enter the internal <b>Course Title / Name</b> (e.g. <code>Prime Video VIP</code> or <code>Python Full Stack Masterclass</code>):"
    )
    await callback.answer()


@router.message(AddFolderStates.waiting_for_title)
async def process_add_title(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(title=title)
    await state.set_state(AddFolderStates.waiting_for_btn_text)
    await message.reply(
        f"🏷️ <b>Button Text Mapping (Step 2/6)</b>\n\n"
        f"Enter the exact text you want to appear on the <code>/start</code> menu button:\n"
        f"<i>Examples:</i>\n"
        f"• <code>📺 Prime Video</code>\n"
        f"• <code>Jio hotstar ad-free 4kplan ₹29</code>\n"
        f"• <code>⭐ Python Masterclass ₹499</code>"
    )


@router.message(AddFolderStates.waiting_for_btn_text)
async def process_add_btn_text(message: Message, state: FSMContext):
    btn_text = message.text.strip()
    await state.update_data(button_text=btn_text)
    await state.set_state(AddFolderStates.waiting_for_width)
    await message.reply(
        "📐 <b>Button Layout Width (Step 3/6)</b>\n\n"
        "How should this button be placed on the <code>/start</code> menu?\n"
        "• Reply <b>1</b> for Full Row (single button spanning full width)\n"
        "• Reply <b>2</b> for Half Row (2 buttons side-by-side per row)"
    )


@router.message(AddFolderStates.waiting_for_width)
async def process_add_width(message: Message, state: FSMContext):
    val = message.text.strip()
    row_width = 1 if val == "1" else 2
    await state.update_data(row_width=row_width)
    await state.set_state(AddFolderStates.waiting_for_desc)
    await message.reply(
        "📝 <b>Course Description & Content Details (Step 4/6)</b>\n\n"
        "Send the detailed content description (supports HTML/formatting). "
        "This will be displayed inside the quote box when a user clicks this course:"
    )


@router.message(AddFolderStates.waiting_for_desc)
async def process_add_desc(message: Message, state: FSMContext):
    desc = message.html_text or message.text
    await state.update_data(description=desc)
    await state.set_state(AddFolderStates.waiting_for_chat_id)
    await message.reply(
        "🔗 <b>Target Private Channel / Group ID (Step 5/6)</b>\n\n"
        "Enter the numeric Telegram Chat ID of the private channel or group (usually starts with <code>-100</code>, e.g. <code>-1001928374650</code>).\n\n"
        "💡 <i>Note: The 2-minute free demo and paid subscriptions automatically use this channel ID to generate secure, single-use invite links. No manual link needed!</i>\n\n"
        "⚠️ <i>Ensure the bot is added as an ADMIN in this group/channel with permissions to:</i>\n"
        "• <i>Invite users via link</i>\n"
        "• <i>Manage members / ban users</i>"
    )


@router.message(AddFolderStates.waiting_for_chat_id)
async def process_add_chat_id(message: Message, state: FSMContext):
    txt = message.text.strip()
    try:
        chat_id = int(txt)
    except ValueError:
        await message.reply("❌ Invalid format. Please enter a valid numeric ID (e.g. <code>-1001234567890</code>):")
        return

    await state.update_data(target_chat_id=chat_id)
    await state.set_state(AddFolderStates.waiting_for_banner)
    await message.reply(
        "🖼️ <b>Course Banner / Poster Image (Step 6/6)</b>\n\n"
        "Please send a photo to be used as the course banner, or reply <b>skip</b> to use text-only details:"
    )


@router.message(AddFolderStates.waiting_for_banner)
async def process_add_banner(message: Message, state: FSMContext):
    banner_file_id = None
    if message.photo:
        banner_file_id = message.photo[-1].file_id
    elif message.text and message.text.strip().lower() != "skip":
        banner_file_id = message.text.strip()

    data = await state.get_data()
    await state.clear()

    folder = await FolderRepository.create_folder(
        title=data["title"],
        button_text=data["button_text"],
        description=data["description"],
        target_chat_id=data["target_chat_id"],
        demo_url=data.get("demo_url"),
        banner_file_id=banner_file_id,
        row_width=data.get("row_width", 2)
    )

    text = (
        f"✅ <b>Course / Folder Created Successfully!</b>\n\n"
        f"• <b>Title:</b> {folder['title']}\n"
        f"• <b>Button Label:</b> {folder['button_text']}\n"
        f"• <b>Target Chat ID:</b> <code>{folder['target_chat_id']}</code>\n"
        f"• <b>Layout Width:</b> {'Full Row' if folder.get('row_width') == 1 else 'Half Row'}\n\n"
        "Default pricing plans (7 Days - ₹49, 1 Month - ₹99, 3 Months - ₹199) have been applied. "
        "You can customize pricing anytime in the folder edit menu."
    )

    markup = build_admin_folder_edit_keyboard(folder)
    await message.reply(text, reply_markup=markup)


# ==========================================
# Edit Folder Menu
# ==========================================

@router.callback_query(F.data.startswith("adm_edit_fld:"))
async def cb_adm_edit_fld(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Unauthorized", show_alert=True)
        return

    await state.clear()
    folder_id = callback.data.split(":", 1)[1]
    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        await callback.answer("Folder not found.", show_alert=True)
        return

    status_str = "🟢 Active" if folder.get("is_active", True) else "🔴 Inactive"
    plans_count = len(folder.get("plans", []))

    text = (
        f"📁 <b>Editing: {folder['title']}</b>\n\n"
        f"• <b>Status:</b> {status_str}\n"
        f"• <b>Button Label:</b> <code>{folder.get('button_text')}</code>\n"
        f"• <b>Layout:</b> {'Full Row (1/row)' if folder.get('row_width') == 1 else 'Half Row (2/row)'}\n"
        f"• <b>Target Chat ID:</b> <code>{folder.get('target_chat_id')}</code>\n"
        f"• <b>Pricing Plans:</b> {plans_count} active\n\n"
        "Select an item to edit below:"
    )

    markup = build_admin_folder_edit_keyboard(folder)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.reply(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_fld_toggle_active:"))
async def cb_adm_toggle_active(callback: CallbackQuery):
    folder_id = callback.data.split(":", 1)[1]
    new_status = await FolderRepository.toggle_active(folder_id)
    status_msg = "Activated" if new_status else "Deactivated"
    await callback.answer(f"Folder is now {status_msg}!")
    # Refresh edit menu
    folder = await FolderRepository.get_folder(folder_id)
    if folder:
        markup = build_admin_folder_edit_keyboard(folder)
        await callback.message.edit_reply_markup(reply_markup=markup)


@router.callback_query(F.data.startswith("adm_fld_toggle_demo:"))
async def cb_adm_toggle_demo(callback: CallbackQuery):
    folder_id = callback.data.split(":", 1)[1]
    new_status = await FolderRepository.toggle_demo(folder_id)
    status_msg = "Enabled (ON)" if new_status else "Disabled (OFF)"
    await callback.answer(f"2-Min Demo is now {status_msg}!")
    folder = await FolderRepository.get_folder(folder_id)
    if folder:
        markup = build_admin_folder_edit_keyboard(folder)
        await callback.message.edit_reply_markup(reply_markup=markup)


@router.callback_query(F.data.startswith("adm_fld_toggle_width:"))
async def cb_adm_toggle_width(callback: CallbackQuery):
    folder_id = callback.data.split(":", 1)[1]
    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        return
    new_width = 1 if folder.get("row_width", 2) == 2 else 2
    await FolderRepository.update_folder(folder_id, {"row_width": new_width})
    folder["row_width"] = new_width
    markup = build_admin_folder_edit_keyboard(folder)
    await callback.message.edit_reply_markup(reply_markup=markup)
    await callback.answer(f"Layout changed to {'Full Row' if new_width == 1 else 'Half Row (2/row)'}!")


@router.callback_query(F.data.startswith("adm_fld_delete:"))
async def cb_adm_fld_delete(callback: CallbackQuery):
    folder_id = callback.data.split(":", 1)[1]
    await FolderRepository.delete_folder(folder_id)
    await callback.answer("Folder deleted successfully!", show_alert=True)
    folders = await FolderRepository.get_all_folders()
    await callback.message.edit_text(
        "📁 <b>Course / Folder Catalog Manager</b>\n\nFolder was removed.",
        reply_markup=build_admin_folders_list(folders)
    )


# ==========================================
# Individual Property Editors
# ==========================================

@router.callback_query(F.data.startswith("adm_fld_title:"))
async def cb_edit_title(callback: CallbackQuery, state: FSMContext):
    folder_id = callback.data.split(":", 1)[1]
    await state.update_data(folder_id=folder_id)
    await state.set_state(EditFolderStates.waiting_for_title)
    await callback.message.reply("✏️ Send the new <b>Course Title</b>:")
    await callback.answer()


@router.message(EditFolderStates.waiting_for_title)
async def process_edit_title(message: Message, state: FSMContext):
    data = await state.get_data()
    folder_id = data["folder_id"]
    await FolderRepository.update_folder(folder_id, {"title": message.text.strip()})
    await state.clear()
    folder = await FolderRepository.get_folder(folder_id)
    await message.reply("✅ Course title updated!", reply_markup=build_admin_folder_edit_keyboard(folder))


@router.callback_query(F.data.startswith("adm_fld_btn:"))
async def cb_edit_btn(callback: CallbackQuery, state: FSMContext):
    folder_id = callback.data.split(":", 1)[1]
    await state.update_data(folder_id=folder_id)
    await state.set_state(EditFolderStates.waiting_for_btn_text)
    await callback.message.reply("🏷️ Send the new <b>Button Text</b> for /start:")
    await callback.answer()


@router.message(EditFolderStates.waiting_for_btn_text)
async def process_edit_btn(message: Message, state: FSMContext):
    data = await state.get_data()
    folder_id = data["folder_id"]
    await FolderRepository.update_folder(folder_id, {"button_text": message.text.strip()})
    await state.clear()
    folder = await FolderRepository.get_folder(folder_id)
    await message.reply("✅ Button text mapped successfully!", reply_markup=build_admin_folder_edit_keyboard(folder))


@router.callback_query(F.data.startswith("adm_fld_desc:"))
async def cb_edit_desc(callback: CallbackQuery, state: FSMContext):
    folder_id = callback.data.split(":", 1)[1]
    await state.update_data(folder_id=folder_id)
    await state.set_state(EditFolderStates.waiting_for_desc)
    await callback.message.reply("📝 Send the new <b>Description</b> (supports HTML):")
    await callback.answer()


@router.message(EditFolderStates.waiting_for_desc)
async def process_edit_desc(message: Message, state: FSMContext):
    data = await state.get_data()
    folder_id = data["folder_id"]
    desc = message.html_text or message.text
    await FolderRepository.update_folder(folder_id, {"description": desc})
    await state.clear()
    folder = await FolderRepository.get_folder(folder_id)
    await message.reply("✅ Description updated!", reply_markup=build_admin_folder_edit_keyboard(folder))


@router.callback_query(F.data.startswith("adm_fld_banner:"))
async def cb_edit_banner(callback: CallbackQuery, state: FSMContext):
    folder_id = callback.data.split(":", 1)[1]
    await state.update_data(folder_id=folder_id)
    await state.set_state(EditFolderStates.waiting_for_banner)
    await callback.message.reply("🖼️ Send a new photo for the course banner, or type <b>remove</b> to clear:")
    await callback.answer()


@router.message(EditFolderStates.waiting_for_banner)
async def process_edit_banner(message: Message, state: FSMContext):
    data = await state.get_data()
    folder_id = data["folder_id"]
    banner_id = None
    if message.photo:
        banner_id = message.photo[-1].file_id
    elif message.text and message.text.strip().lower() != "remove":
        banner_id = message.text.strip()

    await FolderRepository.update_folder(folder_id, {"banner_file_id": banner_id})
    await state.clear()
    folder = await FolderRepository.get_folder(folder_id)
    await message.reply("✅ Course banner updated!", reply_markup=build_admin_folder_edit_keyboard(folder))


@router.callback_query(F.data.startswith("adm_fld_chat:"))
async def cb_edit_chat(callback: CallbackQuery, state: FSMContext):
    folder_id = callback.data.split(":", 1)[1]
    await state.update_data(folder_id=folder_id)
    await state.set_state(EditFolderStates.waiting_for_chat_id)
    await callback.message.reply("🔗 Send the new <b>Target Channel/Group ID</b> (e.g. <code>-1001234567890</code>):")
    await callback.answer()


@router.message(EditFolderStates.waiting_for_chat_id)
async def process_edit_chat(message: Message, state: FSMContext):
    try:
        cid = int(message.text.strip())
    except ValueError:
        await message.reply("❌ Invalid format. Please enter numeric chat ID:")
        return
    data = await state.get_data()
    folder_id = data["folder_id"]
    await FolderRepository.update_folder(folder_id, {"target_chat_id": cid})
    await state.clear()
    folder = await FolderRepository.get_folder(folder_id)
    await message.reply("✅ Target chat ID updated!", reply_markup=build_admin_folder_edit_keyboard(folder))


@router.callback_query(F.data.startswith("adm_fld_demo:"))
async def cb_edit_demo(callback: CallbackQuery, state: FSMContext):
    folder_id = callback.data.split(":", 1)[1]
    await state.update_data(folder_id=folder_id)
    await state.set_state(EditFolderStates.waiting_for_demo)
    prompt = (
        "🎬 <b>Set Public Preview / Teaser Link (Optional)</b>\n\n"
        "If you have a public teaser channel or preview sample post that you want users to view before buying, send its link here.\n\n"
        "💡 <i>Note: The 2-Minute Free VIP Demo is 100% automated by the bot using the Target Channel ID. You do NOT need any link for the 2-minute demo.</i>\n\n"
        "Send the public link, or type <b>remove</b> to clear:"
    )
    await callback.message.reply(prompt)
    await callback.answer()


@router.message(EditFolderStates.waiting_for_demo)
async def process_edit_demo(message: Message, state: FSMContext):
    data = await state.get_data()
    folder_id = data["folder_id"]
    txt = message.text.strip()
    demo_val = None if txt.lower() == "remove" else txt
    await FolderRepository.update_folder(folder_id, {"demo_url": demo_val})
    await state.clear()
    folder = await FolderRepository.get_folder(folder_id)
    status_text = "cleared" if not demo_val else f"set to {demo_val}"
    await message.reply(f"✅ Preview link {status_text}!", reply_markup=build_admin_folder_edit_keyboard(folder))


# ==========================================
# Pricing Plans Manager
# ==========================================

@router.callback_query(F.data.startswith("adm_fld_plans:"))
async def cb_adm_fld_plans(callback: CallbackQuery):
    folder_id = callback.data.split(":", 1)[1]
    folder = await FolderRepository.get_folder(folder_id)
    if not folder:
        return

    text = (
        f"💵 <b>Pricing Plans: {folder['title']}</b>\n\n"
        "Here are the active subscription tiers for this course. "
        "Tap a plan to remove it, or add a new pricing option:"
    )

    markup = build_admin_plans_keyboard(folder)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.reply(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_del_plan:"))
async def cb_adm_del_plan(callback: CallbackQuery):
    parts = callback.data.split(":")
    folder_id = parts[1]
    plan_id = parts[2]

    await FolderRepository.remove_plan(folder_id, plan_id)
    await callback.answer("Plan removed!")
    folder = await FolderRepository.get_folder(folder_id)
    markup = build_admin_plans_keyboard(folder)
    await callback.message.edit_reply_markup(reply_markup=markup)


@router.callback_query(F.data.startswith("adm_add_plan:"))
async def cb_adm_add_plan(callback: CallbackQuery, state: FSMContext):
    folder_id = callback.data.split(":", 1)[1]
    await state.update_data(folder_id=folder_id)
    await state.set_state(AddPlanStates.waiting_for_label)
    await callback.message.reply(
        "➕ <b>Add New Pricing Plan (Step 1/3)</b>\n\n"
        "Enter the label name for this duration (e.g. <code>1 Month</code>, <code>7 Days</code>, <code>1 Year</code>, <code>Lifetime</code>):"
    )
    await callback.answer()


@router.message(AddPlanStates.waiting_for_label)
async def process_plan_label(message: Message, state: FSMContext):
    label = message.text.strip()
    await state.update_data(label=label)
    await state.set_state(AddPlanStates.waiting_for_days)
    await message.reply(
        "⏳ <b>Validity in Days (Step 2/3)</b>\n\n"
        "Enter the number of access days (e.g. <code>7</code> for 7 days, <code>30</code> for 1 month, <code>3650</code> for lifetime):"
    )


@router.message(AddPlanStates.waiting_for_days)
async def process_plan_days(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
    except ValueError:
        await message.reply("❌ Invalid number. Please enter an integer number of days:")
        return

    await state.update_data(days=days)
    await state.set_state(AddPlanStates.waiting_for_price)
    await message.reply(
        "💰 <b>Price in INR (Step 3/3)</b>\n\n"
        "Enter the price in Rupees (e.g. <code>49</code>, <code>99</code>, <code>199</code>, <code>499</code>):"
    )


@router.message(AddPlanStates.waiting_for_price)
async def process_plan_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
    except ValueError:
        await message.reply("❌ Invalid price. Please enter a valid number (e.g. 99):")
        return

    data = await state.get_data()
    folder_id = data["folder_id"]
    label = data["label"]
    days = data["days"]
    await state.clear()

    plan_data = {
        "label": label,
        "days": days,
        "price_inr": price,
        "stars": max(1, int(price * 0.75)),
        "price_usd": round(price / 85.0, 2)
    }

    await FolderRepository.add_or_update_plan(folder_id, plan_data)
    folder = await FolderRepository.get_folder(folder_id)

    await message.reply(
        f"✅ <b>Pricing Plan Added:</b> {label} ({days} Days - ₹{price})!",
        reply_markup=build_admin_plans_keyboard(folder)
    )
