from aiogram import F, Router, Bot, types
from aiogram.filters import Command
from aiogram.enums import ChatMemberStatus

from config import Config
from services.repository import Repository
from keyboards.user_kb import get_main_menu_kb, SubscribeCallback

router = Router()

def format_text_with_user_data(text: str, user: types.User) -> str:
    if not text:
        return ""
    username = f"@{user.username}" if user.username else "пользователь"
    return text.replace('{ID}', str(user.id)).replace('{@username}', username).replace('{full_name}', user.full_name)

async def show_main_menu(message: types.Message, repo: Repository, config: Config, user: types.User):
    # ВАЖНО: Текст должен содержать корректные ID. 
    # Если бот не премиум, он отобразит их как обычные эмодзи или проигнорирует тег.
    start_text_template = (
        '<tg-emoji emoji-id="5453969572354878595">👋</tg-emoji> <b>Добро пожаловать!</b>\n\n'
        '<tg-emoji emoji-id="5219943216781995020">💎</tg-emoji> У нас Вы можете приобрести '
        'Stars и Premium на свой аккаунт за рубли\n\n'
        '<tg-emoji emoji-id="5258024802010026053">🛍️</tg-emoji> <b>Хороших покупок!</b>'
    )
    
    # Получаем остальные настройки из БД
    settings = await repo.get_multiple_settings(['support_contact', 'news_channel_link'])
    support_contact = settings.get('support_contact')
    news_channel_link = settings.get('news_channel_link')
    
    # Форматируем текст (подстановка имени пользователя и т.д.)
    final_text = format_text_with_user_data(start_text_template, user)
    
    await message.answer_photo(
        config.visuals.img_url_main,
        caption=final_text,
        reply_markup=get_main_menu_kb(config, user.id, support_contact, news_channel_link),
        parse_mode="HTML" # Убедись, что parse_mode указан как HTML
    )

@router.message(Command("start"))
async def cmd_start(message: types.Message, repo: Repository, config: Config):
    await repo.get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    await show_main_menu(message, repo, config, message.from_user)

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(call: types.CallbackQuery, repo: Repository, config: Config):
    # Не удаляем сообщение
    await show_main_menu(call.message, repo, config, call.from_user)
    await call.answer()  # Закрываем callback query

@router.callback_query(SubscribeCallback.filter(F.action == "check"))
async def check_subscription_handler(call: types.CallbackQuery, bot: Bot, repo: Repository, config: Config):
    settings = await repo.get_multiple_settings(['news_channel_id', 'news_channel_link'])
    channel_id = settings.get('news_channel_id')
    
    if not channel_id:
        await call.answer("Канал для проверки не настроен.", show_alert=True)
        return

    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=call.from_user.id)
        if member.status not in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await call.answer("✅ Спасибо за подписку!", show_alert=True)
            try:
                await call.message.delete()
            except Exception:
                pass
            await show_main_menu(call.message, repo, config, call.from_user)
        else:
            await call.answer("Вы все еще не подписаны. Попробуйте еще раз.", show_alert=True)
    except Exception:
        await call.answer("Не удалось проверить подписку. Убедитесь, что вы подписаны.", show_alert=True)