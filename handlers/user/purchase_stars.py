import re
from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from services.repository import Repository
from services.fragment_sender import FragmentSender
from services.profit_calculator import ProfitCalculator
from keyboards import user_kb
from states.user import BuyStarsGiftStates, BuyStarsSelfStates, BuyStarsConfirmStates
from .start import format_text_with_user_data
from config import Config
from utils.safe_message import safe_delete_and_send_photo, safe_edit_message

from payments.platega_payment import PlategaPayment

router = Router()


@router.callback_query(F.data == "buy_stars")
async def buy_stars_callback(call: types.CallbackQuery, state: FSMContext, config: Config):
    """Начальный экран выбора кому купить звезды"""
    await state.clear()
    await safe_delete_and_send_photo(
        call, config, config.visuals.img_url_stars,
        '<tg-emoji emoji-id="5976415793741566556">⭐</tg-emoji> <b>Купить звёзды</b>\n\n'
        '<tg-emoji emoji-id="5879770735999717115">👤</tg-emoji> Кому вы хотите купить звёзды?',
        user_kb.get_buy_stars_kb()
    )


@router.callback_query(F.data == "check_platega_payment")
async def check_platega_payment_handler(
    call: types.CallbackQuery, 
    state: FSMContext, 
    repo: Repository,
    fragment_sender: FragmentSender
):
    """Проверяет статус платежа в Platega и обновляет баланс."""
    data = await state.get_data()
    payment_id = data.get("platega_payment_id")
    required_amount = data.get("required_amount")
    total = data.get("total")
    amount = data.get("amount")
    purchase_type = data.get("purchase_type")
    recipient = data.get("recipient")
    
    if not payment_id:
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Данные платежа не найдены. Начните покупку заново.',
            show_alert=True
        )
        return
    
    if data.get("payment_processed"):
        await call.answer(
            '<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Этот платеж уже обработан!',
            show_alert=True
        )
        return
    
    platega = PlategaPayment()
    status = await platega.check_status(payment_id)
    
    if status == "paid":
        await state.update_data(payment_processed=True)
        
        await repo.update_user_balance(
            call.from_user.id, 
            required_amount, 
            operation='add'
        )
        
        user = await repo.get_user(call.from_user.id)
        new_balance = float(user["balance"])
        
        await call.answer(
            '<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Оплата получена! Баланс пополнен.',
            show_alert=True
        )
        
        if new_balance >= total:
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(
                    text="Завершить покупку", 
                    callback_data=f"complete_purchase_{purchase_type}"
                )],
                [types.InlineKeyboardButton(text="В меню", callback_data="main_menu")]
            ])
            
            await call.message.answer(
                f'<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Баланс пополнен на <b>{required_amount}₽</b>\n'
                f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> Текущий баланс: <b>{new_balance}₽</b>\n\n'
                f'Средств достаточно для покупки {amount}<tg-emoji emoji-id="5976415793741566556">⭐</tg-emoji> за {total}₽\n'
                f'Нажмите кнопку ниже для завершения покупки.',
                reply_markup=kb,
                parse_mode="HTML"
            )
        else:
            shortage = round(total - new_balance, 2)
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(
                    text="Пополнить еще", 
                    callback_data="buy_stars_self_confirm" if purchase_type == "self" else "buy_stars_gift_confirm"
                )],
                [types.InlineKeyboardButton(text="В меню", callback_data="main_menu")]
            ])
            
            await call.message.answer(
                f'<tg-emoji emoji-id="5881702736843511327">⚠️</tg-emoji> Баланс пополнен, но все еще недостаточно средств.\n'
                f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> Текущий баланс: <b>{new_balance}₽</b>\n'
                f'<tg-emoji emoji-id="5877485980901971030">💵</tg-emoji> Не хватает: <b>{shortage}₽</b>\n\n'
                f'Нажмите кнопку ниже чтобы пополнить недостающую сумму.',
                reply_markup=kb,
                parse_mode="HTML"
            )
    elif status == "CANCELED":
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Платеж был отменен. Создайте новый платеж.',
            show_alert=True
        )
    elif status == "NOT_FOUND":
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Платеж не найден. Возможно, он был удален.',
            show_alert=True
        )
    else:
        await call.answer(
            '<tg-emoji emoji-id="5881702736843511327">⚠️</tg-emoji> Оплата еще не получена. Попробуйте через 1-2 минуты.',
            show_alert=True
        )


@router.callback_query(F.data.startswith("complete_purchase_"))
async def complete_purchase_handler(
    call: types.CallbackQuery, 
    state: FSMContext,
    repo: Repository, 
    fragment_sender: FragmentSender
):
    """Завершает покупку после успешного пополнения баланса."""
    purchase_type = call.data.split("_")[-1]
    data = await state.get_data()
    
    amount = data.get("amount")
    total = data.get("total")
    recipient = data.get("recipient")
    
    if not amount or not total:
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Данные покупки утеряны. Начните заново.',
            show_alert=True
        )
        return
    
    if purchase_type == "self" and not call.from_user.username:
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> У вас должен быть установлен @username в Telegram! '
            'Установите его в настройках профиля и попробуйте снова.',
            show_alert=True
        )
        return
    
    user_db = await repo.get_user(call.from_user.id)
    
    if float(user_db["balance"]) < total:
        await call.answer(
            f'<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Недостаточно средств! Баланс: {user_db["balance"]}₽, требуется: {total}₽',
            show_alert=True
        )
        return
    
    target_username = recipient if purchase_type == "gift" else call.from_user.username
    
    if not target_username:
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Ошибка: не указан получатель звезд.',
            show_alert=True
        )
        return
    
    await process_star_purchase(
        call, state, repo, fragment_sender, 
        amount, total, target_username, purchase_type
    )


async def process_star_purchase(
    call: types.CallbackQuery,
    state: FSMContext,
    repo: Repository,
    fragment_sender: FragmentSender,
    amount: int,
    total: float,
    recipient_username: str,
    purchase_type: str
):
    """Общая функция для отправки звезд и обработки результата."""
    
    await repo.update_user_balance(call.from_user.id, total, operation='sub')
    
    success = await fragment_sender.send_stars(recipient_username, amount)
    
    if success:
        await repo.update_user_discount(call.from_user.id, None)
        
        profit_calc = ProfitCalculator()
        cost_ton, profit_rub = await profit_calc.calculate_stars_profit(amount, total)
        
        if purchase_type == "gift":
            description = f'{amount} Stars for @{recipient_username}'
        else:
            description = f'{amount} Stars'
            
        await repo.add_purchase_to_history(
            call.from_user.id, 'stars', description, amount, total, profit_rub
        )
        
        success_text_template = await repo.get_setting('purchase_success_text')
        if success_text_template:
            success_text = format_text_with_user_data(success_text_template, call.from_user)
        else:
            if purchase_type == "gift":
                success_text = f'<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Подарок для @{recipient_username} успешно отправлен!\n{amount}<tg-emoji emoji-id="5976415793741566556">⭐</tg-emoji> уже у получателя!'
            else:
                success_text = f'<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Покупка успешна!\n{amount}<tg-emoji emoji-id="5976415793741566556">⭐</tg-emoji> зачислены на ваш баланс!'
        
        await call.message.answer(success_text, parse_mode="HTML")
        
        profit_text = (
            f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> <b>Новая продажа звёзд</b>\n\n'
            f'<tg-emoji emoji-id="5879770735999717115">👤</tg-emoji> Покупатель: @{call.from_user.username}\n'
            f'<tg-emoji emoji-id="5776219138917668486">🎯</tg-emoji> Получатель: @{recipient_username}\n'
            f'<tg-emoji emoji-id="5976415793741566556">⭐</tg-emoji> Количество: {amount} звёзд\n'
            f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> Выручка: {total:.2f}₽\n'
            f'<tg-emoji emoji-id="5913702317667913862">📈</tg-emoji> Прибыль: {profit_rub:.2f}₽'
        )
        await fragment_sender._notify_admins(profit_text)
        
        await state.clear()
        
    else:
        await repo.update_user_balance(call.from_user.id, total, operation='add')
        
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="Попробовать снова", 
                callback_data=f"complete_purchase_{purchase_type}"
            )],
            [types.InlineKeyboardButton(text="В меню", callback_data="main_menu")]
        ])
        
        await call.message.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Ошибка при отправке звёзд. Средства возвращены на баланс.\n'
            'Пожалуйста, попробуйте еще раз или обратитесь в поддержку.',
            reply_markup=kb,
            parse_mode="HTML"
        )


async def handle_insufficient_balance(
    call: types.CallbackQuery,
    state: FSMContext,
    repo: Repository,
    amount: int,
    total: float,
    purchase_type: str,
    recipient: str = None
):
    """Обработка недостаточного баланса - создание платежа в Platega."""
    
    user_db = await repo.get_user(call.from_user.id)
    current_balance = float(user_db["balance"]) if user_db["balance"] else 0.0
    
    required_amount = round(total - current_balance, 2)
    
    platega = PlategaPayment()
    
    if purchase_type == "gift":
        description = f"Пополнение баланса для подарка {amount}⭐ пользователю @{recipient}"
    else:
        description = f"Пополнение баланса для покупки {amount}⭐"
    
    payment_url, payment_id = await platega.create_invoice(
        amount=required_amount,
        user_id=call.from_user.id,
        description=description
    )
    
    if not payment_url or not payment_id:
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Ошибка создания платежа. Попробуйте позже.',
            show_alert=True
        )
        return
    
    await state.update_data(
        platega_payment_id=payment_id,
        required_amount=required_amount,
        amount=amount,
        total=total,
        purchase_type=purchase_type,
        recipient=recipient,
        payment_processed=False
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="Оплатить через Platega", 
            url=payment_url
        )],
        [types.InlineKeyboardButton(
            text="Я оплатил", 
            callback_data="check_platega_payment"
        )],
        [types.InlineKeyboardButton(
            text="Отмена", 
            callback_data="buy_stars"
        )]
    ])
    
    message_text = (
        f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> <b>Недостаточно средств</b>\n\n'
        f'<tg-emoji emoji-id="5877485980901971030">💵</tg-emoji> Стоимость покупки: <b>{total}₽</b>\n'
        f'<tg-emoji emoji-id="5927169041595634481">💳</tg-emoji> Ваш баланс: <b>{current_balance}₽</b>\n'
        f'<tg-emoji emoji-id="5881702736843511327">❗</tg-emoji> Не хватает: <b>{required_amount}₽</b>\n\n'
        f'Нажмите кнопку ниже для пополнения баланса через Platega.\n'
        f'После оплаты нажмите <b>«Я оплатил»</b> для проверки платежа.'
    )
    
    await safe_edit_message(call, text=message_text, reply_markup=kb)


@router.callback_query(F.data == "buy_stars_self")
async def buy_stars_self_callback(call: types.CallbackQuery, config: Config):
    """Выбор способа покупки звезд для себя"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Ввести количество", callback_data="buy_stars_self_amount"),
            types.InlineKeyboardButton(text="Готовые паки", callback_data="buy_stars_self_packs")
        ],
        [types.InlineKeyboardButton(text="Назад", callback_data="buy_stars")]
    ])
    await safe_edit_message(
        call, 
        text="<b>Покупка звёзд для себя</b>\n\nВыберите способ:", 
        reply_markup=kb
    )


@router.callback_query(F.data == "buy_stars_self_amount")
async def buy_stars_self_amount_callback(call: types.CallbackQuery, state: FSMContext):
    """Ввод количества звезд вручную"""
    await safe_edit_message(
        call, 
        text="<b>Введите количество звёзд для покупки (минимум 50):</b>", 
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Назад", callback_data="buy_stars_self")]
        ])
    )
    await state.set_state(BuyStarsSelfStates.waiting_for_self_amount)


@router.message(BuyStarsSelfStates.waiting_for_self_amount)
async def process_self_amount(message: types.Message, state: FSMContext, repo: Repository):
    """Обработка введенного количества звезд"""
    try:
        amount = int(message.text)
        if amount < 50:
            await message.answer(
                '<tg-emoji emoji-id="5881702736843511327">❗</tg-emoji> Минимальное количество для покупки — 50 звёзд.',
                parse_mode="HTML"
            )
            return
    except ValueError:
        await message.answer(
            '<tg-emoji emoji-id="5881702736843511327">❗</tg-emoji> Введите целое число.',
            parse_mode="HTML"
        )
        return

    star_price = float(await repo.get_setting('star_price'))
    total = round(amount * star_price, 2)
    user = await repo.get_user(message.from_user.id)
    discount = user["discount"] if user["discount"] else None

    if discount:
        discounted_total = round(total * (1 - float(discount) / 100), 2)
        price_text = (
            f"Вы выбрали: <b>{amount}</b> звёзд\n"
            f"Итоговая стоимость: <s>{total}₽</s> <b>{discounted_total}₽</b> (скидка {discount}%)"
        )
        await state.update_data(amount=amount, total=discounted_total, purchase_type="self")
    else:
        price_text = f"Вы выбрали: <b>{amount}</b> звёзд\nИтоговая стоимость: <b>{total}₽</b>"
        await state.update_data(amount=amount, total=total, purchase_type="self")
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Подтвердить", callback_data="buy_stars_self_confirm")],
        [types.InlineKeyboardButton(text="Назад", callback_data="buy_stars_self")]
    ])
    
    await message.answer(f"{price_text}\n\nПодтвердить покупку?", reply_markup=kb)
    await state.set_state(BuyStarsConfirmStates.waiting_for_confirm)


@router.callback_query(F.data == "buy_stars_self_packs")
@router.callback_query(F.data.startswith("buy_stars_self_packs_page_"))
async def buy_stars_self_packs_callback(call: types.CallbackQuery, repo: Repository):
    """Отображение готовых пакетов звезд"""
    page = int(call.data.split("_")[-1]) if "page" in call.data else 0
    user = await repo.get_user(call.from_user.id)
    star_price = float(await repo.get_setting('star_price'))
    
    await safe_edit_message(
        call, 
        text="<b>Выберите готовый пакет звёзд:</b>", 
        reply_markup=user_kb.get_star_packs_kb(
            page, "buy_stars_self", star_price, user["discount"] if user["discount"] else None , back_target="buy_stars_self"
        )
    )


@router.callback_query(F.data.startswith("buy_stars_self_pack_"))
async def buy_stars_self_pack_selected(call: types.CallbackQuery, state: FSMContext, repo: Repository):
    """Обработка выбора готового пакета"""
    amount = int(call.data.split("_")[-1])
    star_price = float(await repo.get_setting('star_price'))
    total = round(amount * star_price, 2)
    user = await repo.get_user(call.from_user.id)
    discount = user["discount"] if user["discount"] else None

    if discount:
        discounted_total = round(total * (1 - float(discount) / 100), 2)
        price_text = (
            f"Вы выбрали пакет: <b>{amount}</b> звёзд\n"
            f"Итоговая стоимость: {total}₽ → <b>{discounted_total}₽</b> (скидка {discount}%)"
        )
        await state.update_data(amount=amount, total=discounted_total, purchase_type="self")
    else:
        price_text = f"Вы выбрали пакет: <b>{amount}</b> звёзд\nИтоговая стоимость: <b>{total}₽</b>"
        await state.update_data(amount=amount, total=total, purchase_type="self")
        
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Подтвердить", callback_data="buy_stars_self_confirm")],
        [types.InlineKeyboardButton(text="Назад", callback_data="buy_stars_self_packs")]
    ])
    
    await safe_edit_message(call, text=f"{price_text}\n\nПодтвердить покупку?", reply_markup=kb)
    await state.set_state(BuyStarsConfirmStates.waiting_for_confirm)


@router.callback_query(BuyStarsConfirmStates.waiting_for_confirm, F.data == "buy_stars_self_confirm")
async def buy_stars_self_confirm_callback(
    call: types.CallbackQuery, 
    state: FSMContext, 
    repo: Repository,
    fragment_sender: FragmentSender
):
    """Подтверждение покупки для себя"""
    data = await state.get_data()
    amount = data.get("amount")
    total = data.get("total")
    user_db = await repo.get_user(call.from_user.id)
    
    if not amount or not total:
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Данные покупки утеряны. Начните заново.',
            show_alert=True
        )
        return
    
    current_balance = float(user_db["balance"]) if user_db["balance"] else 0.0
    
    if current_balance >= total:
        await process_star_purchase(
            call, state, repo, fragment_sender, 
            amount, total, call.from_user.username, "self"
        )
        return
    
    await handle_insufficient_balance(
        call, state, repo, amount, total, "self"
    )


@router.callback_query(F.data == "buy_stars_gift")
async def buy_stars_gift_callback(call: types.CallbackQuery, state: FSMContext):
    """Начало покупки в подарок - запрос получателя"""
    await state.clear()
    await safe_edit_message(
        call, 
        text="<b>Укажите юзернейм (@username) получателя:</b>", 
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Назад", callback_data="buy_stars")]
        ])
    )
    await state.set_state(BuyStarsGiftStates.waiting_for_recipient)


@router.message(BuyStarsGiftStates.waiting_for_recipient)
async def process_gift_recipient(message: types.Message, state: FSMContext, config: Config):
    """Обработка юзернейма получателя подарка"""
    match = re.match(r"^@?([a-zA-Z0-9_]{5,32})$", message.text.strip())
    if not match:
        await message.answer(
            '<tg-emoji emoji-id="5881702736843511327">❗️</tg-emoji> Введите корректный юзернейм.\n'
            'Например: @username (без пробелов, от 5 до 32 символов)',
            parse_mode="HTML"
        )
        return

    recipient = match.group(1)
    await state.update_data(recipient=recipient, purchase_type="gift")
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Количество", callback_data="buy_stars_gift_amount"),
            types.InlineKeyboardButton(text="Паки", callback_data="buy_stars_gift_packs")
        ],
        [types.InlineKeyboardButton(text="Назад", callback_data="buy_stars_gift")]
    ])
    
    await message.delete()
    await message.answer_photo(
        photo=config.visuals.img_url_stars, 
        caption=f"Получатель: <code>@{recipient}</code>\n\nВыберите количество звёзд для подарка:",
        reply_markup=kb
    )


@router.callback_query(F.data == "back_to_gift_choice")
async def back_to_gift_choice(call: types.CallbackQuery, state: FSMContext, config: Config):
    """Возврат к выбору способа для подарка"""
    data = await state.get_data()
    recipient = data.get('recipient', 'неизвестный')
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Количество", callback_data="buy_stars_gift_amount"),
            types.InlineKeyboardButton(text="Паки", callback_data="buy_stars_gift_packs")
        ],
        [types.InlineKeyboardButton(text="Назад", callback_data="buy_stars_gift")]
    ])
    
    await call.message.delete()
    await call.message.answer_photo(
        photo=config.visuals.img_url_stars, 
        caption=f"Получатель: @{recipient}\n\nВыберите способ:",
        reply_markup=kb
    )


@router.callback_query(F.data == "buy_stars_gift_amount")
async def buy_stars_gift_amount_callback(call: types.CallbackQuery, state: FSMContext):
    """Ввод количества звезд для подарка"""
    data = await state.get_data()
    recipient = data.get('recipient', 'получатель')
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Назад", callback_data="back_to_gift_choice")]
    ])
    
    await safe_edit_message(
        call, 
        text=f"Получатель: @{recipient}\n\n<b>Введите количество звёзд (минимум 50):</b>", 
        reply_markup=kb
    )
    await state.set_state(BuyStarsGiftStates.waiting_for_gift_amount)


@router.message(BuyStarsGiftStates.waiting_for_gift_amount)
async def process_gift_amount(message: types.Message, state: FSMContext, repo: Repository):
    """Обработка количества звезд для подарка"""
    try:
        amount = int(message.text)
        if amount < 50:
            await message.answer(
                '<tg-emoji emoji-id="5881702736843511327">❗</tg-emoji> Минимальное количество для подарка — 50 звёзд.',
                parse_mode="HTML"
            )
            return
    except ValueError:
        await message.answer(
            '<tg-emoji emoji-id="5881702736843511327">❗</tg-emoji> Введите целое число.',
            parse_mode="HTML"
        )
        return

    star_price = float(await repo.get_setting('star_price'))
    total = round(amount * star_price, 2)
    user = await repo.get_user(message.from_user.id)
    discount = user["discount"] if user["discount"] else None
    data = await state.get_data()
    recipient = data.get('recipient', 'получатель')
    
    if discount:
        discounted_total = round(total * (1 - float(discount) / 100), 2)
        price_text = (
            f"Подарок для @{recipient}: <b>{amount}</b> звёзд\n"
            f"Стоимость: <s>{total}₽</s> <b>{discounted_total}₽</b> (скидка {discount}%)"
        )
        await state.update_data(amount=amount, total=discounted_total)
    else:
        price_text = f"Подарок для @{recipient}: <b>{amount}</b> звёзд\nСтоимость: <b>{total}₽</b>"
        await state.update_data(amount=amount, total=total)
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Подтвердить", callback_data="buy_stars_gift_confirm")],
        [types.InlineKeyboardButton(text="Назад", callback_data="buy_stars_gift_amount")]
    ])
    
    await message.answer(f"{price_text}\n\nПодтвердить покупку?", reply_markup=kb)
    await state.set_state(BuyStarsConfirmStates.waiting_for_gift_confirm)


@router.callback_query(F.data == "buy_stars_gift_packs")
@router.callback_query(F.data.startswith("buy_stars_gift_packs_page_"))
async def buy_stars_gift_packs_callback(call: types.CallbackQuery, state: FSMContext, repo: Repository):
    """Отображение готовых пакетов для подарка"""
    page = int(call.data.split("_")[-1]) if "page" in call.data else 0
    user = await repo.get_user(call.from_user.id)
    star_price = float(await repo.get_setting('star_price'))
    data = await state.get_data()
    recipient = data.get('recipient', 'получатель')
    
    await safe_edit_message(
        call, 
        text=f"Получатель: @{recipient}\n\n<b>Выберите готовый пакет звёзд:</b>", 
        reply_markup=user_kb.get_star_packs_kb(
            page, "buy_stars_gift", star_price, user["discount"] if user["discount"] else None, back_target="back_to_gift_choice"
        )
    )


@router.callback_query(F.data.startswith("buy_stars_gift_pack_"))
async def buy_stars_gift_pack_selected(call: types.CallbackQuery, state: FSMContext, repo: Repository):
    """Обработка выбора готового пакета для подарка"""
    amount = int(call.data.split("_")[-1])
    star_price = float(await repo.get_setting('star_price'))
    total = round(amount * star_price, 2)
    user = await repo.get_user(call.from_user.id)
    discount = user["discount"] if user["discount"] else None
    data = await state.get_data()
    recipient = data.get('recipient', 'получатель')

    if discount:
        discounted_total = round(total * (1 - float(discount) / 100), 2)
        price_text = (
            f"Подарок для @{recipient}: <b>{amount}</b> звёзд\n"
            f"Стоимость: {total}₽ → <b>{discounted_total}₽</b> (скидка {discount}%)"
        )
        await state.update_data(amount=amount, total=discounted_total)
    else:
        price_text = f"Подарок для @{recipient}: <b>{amount}</b> звёзд\nСтоимость: <b>{total}₽</b>"
        await state.update_data(amount=amount, total=total)
        
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Подтвердить", callback_data="buy_stars_gift_confirm")],
        [types.InlineKeyboardButton(text="Назад", callback_data="buy_stars_gift_packs")]
    ])
    
    await safe_edit_message(call, text=f"{price_text}\n\nПодтвердить покупку?", reply_markup=kb)
    await state.set_state(BuyStarsConfirmStates.waiting_for_gift_confirm)


@router.callback_query(BuyStarsConfirmStates.waiting_for_gift_confirm, F.data == "buy_stars_gift_confirm")
async def buy_stars_gift_confirm_callback(
    call: types.CallbackQuery, 
    state: FSMContext, 
    repo: Repository,
    fragment_sender: FragmentSender
):
    """Подтверждение покупки в подарок"""
    data = await state.get_data()
    amount = data.get("amount")
    total = data.get("total")
    recipient = data.get("recipient")
    user_db = await repo.get_user(call.from_user.id)
    
    if not amount or not total or not recipient:
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Данные покупки утеряны. Начните заново.',
            show_alert=True
        )
        return
    
    current_balance = float(user_db["balance"]) if user_db["balance"] else 0.0
    
    if current_balance >= total:
        await process_star_purchase(
            call, state, repo, fragment_sender, 
            amount, total, recipient, "gift"
        )
        return
    
    await handle_insufficient_balance(
        call, state, repo, amount, total, "gift", recipient
    )