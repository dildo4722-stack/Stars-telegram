import asyncio
from aiogram import Bot, Dispatcher, types, F

bot = Bot(token="8770201310:AAETMbc4g313i4U6kLWyUH_O2ziRNXYbdGA")
dp = Dispatcher()

@dp.message(F.entities)
async def show_emoji_ids(message: types.Message):
    """Показывает ID всех кастомных эмодзи в сообщении"""
    for entity in message.entities:
        if entity.type == "custom_emoji":
            await message.answer(f"Custom Emoji ID: <code>{entity.custom_emoji_id}</code>", parse_mode="HTML")

async def main():
    await dp.start_polling(bot)

asyncio.run(main())