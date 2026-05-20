import asyncio
from aiogram import F, Router, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.repository import Repository
from states.admin import BroadcastConstructorStates
from keyboards.admin_kb import get_broadcast_constructor_kb

router = Router()

async def show_broadcast_constructor_menu(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await message.answer(
        '<tg-emoji emoji-id="5884123981706956210">📢</tg-emoji> <b>Конструктор рассылки</b>\n\nВы можете изменить любой элемент поста перед отправкой.',
        reply_markup=get_broadcast_constructor_kb(data),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastConstructorStates.menu)

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        text='<tg-emoji emoji-id="5884123981706956210">📢</tg-emoji> <b>Новая рассылка</b>\n\nОтправьте мне сообщение, которое станет основой для рассылки. Это может быть текст, фото или видео с подписью.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=" Назад", callback_data="admin_panel")]]),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastConstructorStates.waiting_for_initial_post)

@router.message(BroadcastConstructorStates.waiting_for_initial_post, F.text | F.photo | F.video)
async def broadcast_initial_post_handler(message: types.Message, state: FSMContext):
    post_data = {
        "text": message.html_text or message.caption,
        "photo_id": message.photo[-1].file_id if message.photo else None,
        "video_id": message.video.file_id if message.video else None,
        "button_text": None,
        "button_url": None
    }
    await state.set_data(post_data)
    await show_broadcast_constructor_menu(message, state)

@router.callback_query(BroadcastConstructorStates.menu, F.data == 'broadcast_edit_text')
async def broadcast_edit_text_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        '<tg-emoji emoji-id="5879841310902324730">✏️</tg-emoji> Отправьте новый текст для рассылки.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="back_to_broadcast_menu")]]),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastConstructorStates.editing_text)

@router.message(BroadcastConstructorStates.editing_text)
async def broadcast_process_edited_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.html_text)
    await message.answer(
        '<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Текст обновлен.',
        parse_mode="HTML"
    )
    await show_broadcast_constructor_menu(message, state)

@router.callback_query(BroadcastConstructorStates.menu, F.data == 'broadcast_edit_media')
async def broadcast_edit_media_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        'Отправьте новое фото или видео.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="back_to_broadcast_menu")]]),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastConstructorStates.editing_media)

@router.message(BroadcastConstructorStates.editing_media, F.photo | F.video)
async def broadcast_process_edited_media(message: types.Message, state: FSMContext):
    await state.update_data(
        photo_id=message.photo[-1].file_id if message.photo else None,
        video_id=message.video.file_id if message.video else None
    )
    await message.answer(
        '<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Медиа обновлено.',
        parse_mode="HTML"
    )
    await show_broadcast_constructor_menu(message, state)

@router.callback_query(BroadcastConstructorStates.menu, F.data == 'broadcast_add_button')
async def broadcast_add_button_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Введите текст для кнопки:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="back_to_broadcast_menu")]]),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastConstructorStates.adding_button_text)
    
@router.callback_query(BroadcastConstructorStates.menu, F.data == 'broadcast_delete_button')
async def broadcast_delete_button(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(button_text=None, button_url=None)
    data = await state.get_data()
    await call.message.edit_reply_markup(reply_markup=get_broadcast_constructor_kb(data))
    await call.answer(
        '<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Кнопка удалена.',
        parse_mode="HTML"
    )

@router.message(BroadcastConstructorStates.adding_button_text)
async def broadcast_process_button_text(message: types.Message, state: FSMContext):
    await state.update_data(button_text=message.text)
    await message.answer(
        '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Теперь введите URL-ссылку для кнопки (например, <code>https://google.com</code>):',
        parse_mode="HTML"
    )
    await state.set_state(BroadcastConstructorStates.adding_button_url)

@router.message(BroadcastConstructorStates.adding_button_url, F.text.startswith('http'))
async def broadcast_process_button_url(message: types.Message, state: FSMContext):
    await state.update_data(button_url=message.text)
    await message.answer(
        '<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Кнопка добавлена/изменена.',
        parse_mode="HTML"
    )
    await show_broadcast_constructor_menu(message, state)

@router.callback_query(BroadcastConstructorStates.menu, F.data == 'broadcast_preview')
async def broadcast_preview(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    text, photo_id, video_id = data.get("text", " "), data.get("photo_id"), data.get("video_id")
    button_text, button_url = data.get("button_text"), data.get("button_url")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=button_url)]]) if button_text and button_url else None
    
    await call.message.answer(
        '<tg-emoji emoji-id="5942877472163892475">👀</tg-emoji> <b>Предпросмотр:</b>',
        parse_mode="HTML"
    )
    try:
        if photo_id: await bot.send_photo(call.from_user.id, photo_id, caption=text, reply_markup=kb)
        elif video_id: await bot.send_video(call.from_user.id, video_id, caption=text, reply_markup=kb)
        else: await bot.send_message(call.from_user.id, text, reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        await bot.send_message(call.from_user.id, f'<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Ошибка предпросмотра: {e}', parse_mode="HTML")

@router.callback_query(BroadcastConstructorStates.menu, F.data == 'broadcast_send')
async def broadcast_send(call: types.CallbackQuery, state: FSMContext, repo: Repository, bot: Bot):
    await call.answer(
        '<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Рассылка запущена в фоновом режиме.',
        show_alert=True,
        parse_mode="HTML"
    )
    await call.message.edit_text(
        '<tg-emoji emoji-id="5936170807716745162">⏳</tg-emoji> Рассылка запущена... Отчет придет по завершению.',
        parse_mode="HTML"
    )
    
    data = await state.get_data()
    text, photo_id, video_id = data.get("text"), data.get("photo_id"), data.get("video_id")
    button_text, button_url = data.get("button_text"), data.get("button_url")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=button_url)]]) if button_text and button_url else None
    
    users = await repo.get_all_users_for_broadcast()
    count, errors = 0, 0
    
    for user in users:
        try:
            if photo_id: await bot.send_photo(user["telegram_id"], photo_id, caption=text, reply_markup=kb)
            elif video_id: await bot.send_video(user["telegram_id"], video_id, caption=text, reply_markup=kb)
            else: await bot.send_message(user["telegram_id"], text, reply_markup=kb, disable_web_page_preview=True)
            count += 1
        except Exception:
            errors += 1
        await asyncio.sleep(0.05)
        
    await state.clear()
    await bot.send_message(
        call.from_user.id,
        f'<tg-emoji emoji-id="5884123981706956210">📢</tg-emoji> Рассылка завершена!\n\n'
        f'<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Успешно: {count}\n'
        f'<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Ошибок: {errors}',
        parse_mode="HTML"
    )

@router.callback_query(BroadcastConstructorStates.menu, F.data == 'broadcast_cancel')
async def broadcast_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "Рассылка отменена.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="В админ-панель", callback_data="admin_panel")]])
    )

@router.callback_query(F.data == "back_to_broadcast_menu")
async def back_to_broadcast_menu(call: types.CallbackQuery, state: FSMContext):
    try:
        await call.message.delete()
    except Exception:
        pass
    await show_broadcast_constructor_menu(call.message, state)