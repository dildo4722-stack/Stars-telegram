import re
import logging
from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from services.repository import Repository
from services.fragment_sender import FragmentSender
from services.profit_calculator import ProfitCalculator
from keyboards import user_kb
from states.user import BuyPremiumStates
from keyboards.user_kb import PREMIUM_PLANS
from .start import format_text_with_user_data
from config import Config
from utils.safe_message import safe_delete_and_send_photo, safe_edit_message

router = Router()

async def get_premium_prices(repo: Repository):
    keys = [f'premium_price_{i}' for i in range(len(PREMIUM_PLANS))]
    prices_db = await repo.get_multiple_settings(keys)
    return [float(prices_db.get(f'premium_price_{i}', plan['price'])) for i, plan in enumerate(PREMIUM_PLANS)]

@router.callback_query(F.data == "buy_premium")
async def buy_premium_callback(call: types.CallbackQuery, state: FSMContext, config: Config):
    await state.clear()
    await safe_delete_and_send_photo(
        call, config, config.visuals.img_url_premium,
        '<tg-emoji emoji-id="6032937473162614352">⭐</tg-emoji> <b>Купить премиум</b>\n\n'
        '<tg-emoji emoji-id="5881702736843511327">⚠️</tg-emoji> Получить могут только пользователи без активной подписки\n\n'
        '<tg-emoji emoji-id="5879770735999717115">👤</tg-emoji> Выберите получателя премиума:',
        user_kb.get_buy_premium_kb()
    )

@router.callback_query(F.data == "buy_premium_self")
async def buy_premium_self_callback(call: types.CallbackQuery, repo: Repository):
    user = await repo.get_user(call.from_user.id)
    premium_prices = await get_premium_prices(repo)
    kb = user_kb.get_premium_plans_kb(premium_prices, user["discount"], prefix="buy_premium_self_plan", back_target="buy_premium")
    await safe_edit_message(call, text="<b>Выберите тариф для себя:</b>", reply_markup=kb)

@router.callback_query(F.data.startswith("buy_premium_self_plan_"))
async def buy_premium_self_plan_selected(call: types.CallbackQuery, state: FSMContext, repo: Repository):
    plan_index = int(call.data.split("_")[-1])
    plan = PREMIUM_PLANS[plan_index]
    premium_prices = await get_premium_prices(repo)
    price = premium_prices[plan_index]
    user = await repo.get_user(call.from_user.id)
    discount = user["discount"]

    if discount:
        discounted_price = round(price * (1 - float(discount) / 100), 2)
        text = f"Тариф для себя: <b>{plan['name']}</b>\nСтоимость: {price}₽ → <b>{discounted_price}₽</b> (скидка {discount}%)"
        await state.update_data(plan_index=plan_index, total=discounted_price)
    else:
        text = f"Тариф для себя: <b>{plan['name']}</b>\nСтоимость: <b>{price}₽</b>"
        await state.update_data(plan_index=plan_index, total=price)
        
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Подтвердить", callback_data="buy_premium_self_confirm")],
        [types.InlineKeyboardButton(text="Назад", callback_data="buy_premium_self")]
    ])
    await safe_edit_message(call, text=f"{text}\n\nПодтвердить покупку?", reply_markup=kb)
    await state.set_state(BuyPremiumStates.waiting_for_self_confirm)

@router.callback_query(BuyPremiumStates.waiting_for_self_confirm, F.data == "buy_premium_self_confirm")
async def buy_premium_self_confirm_callback(call: types.CallbackQuery, state: FSMContext, repo: Repository, fragment_sender: FragmentSender):
    if not call.from_user.username:
        await call.answer("У вас нету логина в тг, установите его и попробуйте еще раз", show_alert=True)
        await state.clear()
        return
        
    data = await state.get_data()
    plan_index, total = data.get("plan_index"), data.get("total")
    plan = PREMIUM_PLANS[plan_index]
    user_obj = call.from_user
    user_db = await repo.get_user(user_obj.id)

    if float(user_db["balance"]) < total:
        await safe_edit_message(
            call,
            text=f'Недостаточно средств! Не хватает: <b>{total - float(user_db["balance"])}₽</b>',
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="Пополнить баланс", callback_data="profile_topup_menu")]
            ])
        )
        await state.clear()
        return

    success_text_template = await repo.get_setting('purchase_success_text')
    success_text = format_text_with_user_data(success_text_template, user_obj)
    
    months = plan["duration"] // 30
    profit_calc = ProfitCalculator()
    cost_ton, profit_rub = await profit_calc.calculate_premium_profit(months, total)
    
    await repo.update_user_balance(user_obj.id, total, operation='sub')
    
    success = await fragment_sender.send_premium(call.from_user.username, months)
    
    if success:
        await repo.update_user_discount(user_obj.id, None) 
        await repo.add_purchase_to_history(user_obj.id, 'premium', plan['name'], months, total, profit_rub)
        final_message = f"{success_text}\n\nПремиум <b>{plan['name']}</b> успешно активирован!"
        await safe_edit_message(call, text=final_message, reply_markup=None)
        
        profit_text = (
            f'<tg-emoji emoji-id="5807465992363710697">💎</tg-emoji> <b>Новая продажа премиума</b>\n\n'
            f'<tg-emoji emoji-id="5879770735999717115">👤</tg-emoji> Покупатель: @{call.from_user.username}\n'
            f'<tg-emoji emoji-id="5967412305338568701">📆</tg-emoji> Тариф: {plan["name"]}\n'
            f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> Выручка: {total:.2f}₽\n'
            f'<tg-emoji emoji-id="5913702317667913862">📈</tg-emoji> Прибыль: {profit_rub:.2f}₽\n'
            f'<tg-emoji emoji-id="5931472654660800739">📊</tg-emoji> Маржа: {profit_calc.get_profit_margin(total - profit_rub, total):.1f}%'
        )
        await fragment_sender._notify_admins(profit_text)
    else:
        await repo.update_user_balance(user_obj.id, total, operation='add')
        error_kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Главное меню", callback_data="main_menu")]
        ])
        await safe_edit_message(
            call,
            text='<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Произошла ошибка при отправке премиума. Средства возвращены на ваш баланс. Обратитесь в поддержку.',
            reply_markup=error_kb
        )
    await state.clear()

@router.callback_query(F.data == "buy_premium_gift")
async def buy_premium_gift_callback(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_message(
        call,
        text="<b>Пожалуйста, укажите юзернейм (@username) получателя.</b>",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Назад", callback_data="buy_premium")]
        ])
    )
    await state.set_state(BuyPremiumStates.waiting_for_gift_recipient)

@router.message(BuyPremiumStates.waiting_for_gift_recipient)
async def process_premium_gift_recipient(message: types.Message, state: FSMContext, repo: Repository, config: Config):
    match = re.match(r"^@?([a-zA-Z0-9_]{5,32})$", message.text.strip())
    if not match:
        await message.answer(
            '<tg-emoji emoji-id="5881702736843511327">❗️</tg-emoji> <b>Неверный формат!</b>\n\nВведите корректный юзернейм (например, <code>@username</code>).',
            parse_mode="HTML"
        )
        return
    
    recipient = match.group(1)
    await state.update_data(recipient=recipient)
    
    user = await repo.get_user(message.from_user.id)
    premium_prices = await get_premium_prices(repo)
    kb = user_kb.get_premium_plans_kb(premium_prices, user["discount"], prefix="buy_premium_gift_plan", back_target="buy_premium_gift")
    
    await message.delete()
    await message.answer_photo(
        photo=config.visuals.img_url_premium,
        caption=f"Получатель: <code>@{recipient}</code>\n\n<b>Выберите тариф для подарка:</b>", 
        reply_markup=kb
    )
    await state.set_state(BuyPremiumStates.waiting_for_gift_plan)

@router.callback_query(BuyPremiumStates.waiting_for_gift_plan, F.data.startswith("buy_premium_gift_plan_"))
async def buy_premium_gift_plan_selected(call: types.CallbackQuery, state: FSMContext, repo: Repository):
    plan_index = int(call.data.split("_")[-1])
    plan = PREMIUM_PLANS[plan_index]
    premium_prices = await get_premium_prices(repo)
    price = premium_prices[plan_index]
    user = await repo.get_user(call.from_user.id)
    data = await state.get_data()
    recipient = data.get("recipient")
    discount = user["discount"]

    if discount:
        discounted_price = round(price * (1 - float(discount) / 100), 2)
        text = f"Тариф для <code>@{recipient}</code>: <b>{plan['name']}</b>\nСтоимость: {price}₽ → <b>{discounted_price}₽</b> (скидка {discount}%)"
        await state.update_data(plan_index=plan_index, total=discounted_price)
    else:
        text = f"Тариф для <code>@{recipient}</code>: <b>{plan['name']}</b>\nСтоимость: <b>{price}₽</b>"
        await state.update_data(plan_index=plan_index, total=price)
        
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Подтвердить", callback_data="buy_premium_gift_confirm")],
        [types.InlineKeyboardButton(text="Назад", callback_data="buy_premium_gift")]
    ])
    await safe_edit_message(call, text=f"{text}\n\nПодтвердить покупку?", reply_markup=kb)
    await state.set_state(BuyPremiumStates.waiting_for_gift_confirm)

@router.callback_query(BuyPremiumStates.waiting_for_gift_confirm, F.data == "buy_premium_gift_confirm")
async def buy_premium_gift_confirm_callback(call: types.CallbackQuery, state: FSMContext, repo: Repository, fragment_sender: FragmentSender):
    data = await state.get_data()
    plan_index, total, recipient = data.get("plan_index"), data.get("total"), data.get("recipient")
    plan = PREMIUM_PLANS[plan_index]
    user_obj = call.from_user
    user_db = await repo.get_user(user_obj.id)

    if float(user_db["balance"]) < total:
        await safe_edit_message(
            call,
            text=f'Недостаточно средств! Не хватает: <b>{total - float(user_db["balance"])}₽</b>',
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="Пополнить баланс", callback_data="profile_topup_menu")]
            ])
        )
        await state.clear()
        return

    success_text_template = await repo.get_setting('purchase_success_text')
    success_text = format_text_with_user_data(success_text_template, user_obj)

    months = plan["duration"] // 30
    profit_calc = ProfitCalculator()
    cost_ton, profit_rub = await profit_calc.calculate_premium_profit(months, total)
    
    await repo.update_user_balance(user_obj.id, total, operation='sub')
    
    success = await fragment_sender.send_premium(recipient, months)
    
    if success:
        await repo.update_user_discount(user_obj.id, None) 
        await repo.add_purchase_to_history(user_obj.id, 'premium', f"{plan['name']} for @{recipient}", months, total, profit_rub)
        final_message = f"{success_text}\n\nПремиум <b>{plan['name']}</b> для <code>@{recipient}</code> успешно куплен!"
        await safe_edit_message(call, text=final_message, reply_markup=None)

        profit_text = (
            f'<tg-emoji emoji-id="5902002809573740949">🎉</tg-emoji> <b>Новый подарок премиума</b>\n\n'
            f'<tg-emoji emoji-id="5879770735999717115">👤</tg-emoji> Покупатель: @{call.from_user.username}\n'
            f'<tg-emoji emoji-id="5776219138917668486">🎯</tg-emoji> Получатель: @{recipient}\n'
            f'<tg-emoji emoji-id="5967412305338568701">📆</tg-emoji> Тариф: {plan["name"]}\n'
            f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> Выручка: {total:.2f}₽\n'
            f'<tg-emoji emoji-id="5913702317667913862">📈</tg-emoji> Прибыль: {profit_rub:.2f}₽\n'
            f'<tg-emoji emoji-id="5931472654660800739">📊</tg-emoji> Маржа: {profit_calc.get_profit_margin(total - profit_rub, total):.1f}%'
        )
        await fragment_sender._notify_admins(profit_text)
    else:
        await repo.update_user_balance(user_obj.id, total, operation='add')
        error_kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Главное меню", callback_data="main_menu")]
        ])
        await safe_edit_message(
            call,
            text='<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Произошла ошибка при отправке премиума. Средства возвращены на ваш баланс. Обратитесь в поддержку.',
            reply_markup=error_kb
        )
    await state.clear()