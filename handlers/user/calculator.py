from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from services.repository import Repository
from keyboards import user_kb
from states.user import CalculatorStates
from utils.safe_message import safe_answer_photo, safe_delete_message
from config import Config

router = Router()

@router.callback_query(F.data == "calculator")
async def calculator_menu_callback(call: types.CallbackQuery, state: FSMContext, config: Config):
    await state.clear()
    await safe_delete_message(call)
    await safe_answer_photo(
        call,
        photo=config.visuals.img_url_calculator,
        caption='<tg-emoji emoji-id="5877485980901971030">🧮</tg-emoji> <b>Калькулятор</b>\n\nВыберите, как вы хотите рассчитать стоимость:',
        reply_markup=user_kb.get_calculator_kb()
    )

@router.callback_query(F.data == "calc_by_stars")
async def calc_by_stars_start(call: types.CallbackQuery, state: FSMContext):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="Назад", callback_data="calculator")]])
    await call.message.edit_caption(caption="Введите количество звезд (минимум 50):", reply_markup=kb)
    await state.set_state(CalculatorStates.waiting_for_stars_amount)

@router.message(CalculatorStates.waiting_for_stars_amount)
async def calc_by_stars_process(message: types.Message, state: FSMContext, repo: Repository):
    try:
        stars_amount = int(message.text)
        if stars_amount < 50:
            await message.answer(
                '<tg-emoji emoji-id="5881702736843511327">❗️</tg-emoji> Минимальное количество для расчета — 50 звёзд.',
                parse_mode="HTML"
            )
            return
    except ValueError:
        await message.answer(
            '<tg-emoji emoji-id="5881702736843511327">❗️</tg-emoji> Пожалуйста, введите целое число.',
            parse_mode="HTML"
        )
        return

    star_price_str = await repo.get_setting('star_price')
    star_price = float(star_price_str) if star_price_str else 1.8
    total_cost = round(stars_amount * star_price, 2)
    
    await message.answer(
        f'<tg-emoji emoji-id="5976415793741566556">⭐</tg-emoji> <b>{stars_amount:,}</b> звёзд ≈ <b>{total_cost:.2f} ₽</b>',
        parse_mode="HTML"
    )
    await state.clear()

@router.callback_query(F.data == "calc_by_rub")
async def calc_by_rub_start(call: types.CallbackQuery, state: FSMContext):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="Назад", callback_data="calculator")]])
    await call.message.edit_caption(caption="Введите сумму в рублях (₽):", reply_markup=kb)
    await state.set_state(CalculatorStates.waiting_for_rub_amount)

@router.message(CalculatorStates.waiting_for_rub_amount)
async def calc_by_rub_process(message: types.Message, state: FSMContext, repo: Repository):
    try:
        rub_amount = float(message.text.replace(",", "."))
        if rub_amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            '<tg-emoji emoji-id="5881702736843511327">❗️</tg-emoji> Пожалуйста, введите корректное положительное число.',
            parse_mode="HTML"
        )
        return

    star_price_str = await repo.get_setting('star_price')
    star_price = float(star_price_str) if star_price_str else 1.8
    if star_price == 0:
        await message.answer(
            '<tg-emoji emoji-id="5881702736843511327">❗️</tg-emoji> Невозможно рассчитать, так как цена звезды равна нулю.',
            parse_mode="HTML"
        )
        return
        
    stars_count = int(rub_amount / star_price)

    await message.answer(
        f'₽ <b>{rub_amount:.2f}</b> ≈ <b>{stars_count:,}</b> <tg-emoji emoji-id="5976415793741566556">⭐</tg-emoji>',
        parse_mode="HTML"
    )
    await state.clear()