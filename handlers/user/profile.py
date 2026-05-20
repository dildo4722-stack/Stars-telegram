import logging
from aiogram import F, Router, Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from datetime import datetime, timedelta

from config import Config
from services.repository import Repository
from keyboards import user_kb
from states.user import PaymentStates, PromoUserStates
from utils.safe_message import safe_answer_photo, safe_answer, safe_delete_message
from .start import show_main_menu

from payments.lolz_payment import LolzPayment
from payments.cryptobot_payment import CryptoBotPayment
from payments.xrocet_payment import XRocetPayment
from payments.crystalpay_payment import CrystalPayPayment
from payments.platega_payment import PlategaPayment

router = Router()

@router.callback_query(F.data == "profile")
async def profile_callback(call: types.CallbackQuery, repo: Repository, config: Config):
    user = await repo.get_or_create_user(call.from_user.id, call.from_user.username, call.from_user.first_name)
    total_stars_bought = await repo.get_total_stars_bought(user['telegram_id'])
    reg_date_obj = datetime.fromisoformat(user['created_at'])
    reg_date_formatted = reg_date_obj.strftime('%d.%m.%Y')

    text = (
        f'<tg-emoji emoji-id="5879770735999717115">👤</tg-emoji> Ваш профиль\n\n'
        f'<tg-emoji emoji-id="5936017305585586269">🆔</tg-emoji> ID: <code>{user["telegram_id"]}</code>\n'
        f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> Баланс: <b>{user["balance"]:.2f} ₽</b>\n'
        f'<tg-emoji emoji-id="5976415793741566556">⭐</tg-emoji> Куплено звезд: <b>{total_stars_bought:,}</b>\n'
        f'<tg-emoji emoji-id="5967412305338568701">📆</tg-emoji> Первый запуск бота: <b>{reg_date_formatted}</b>'
    )
    
    await safe_delete_message(call)
    await safe_answer_photo(
        call,
        photo=config.visuals.img_url_profile,
        caption=text,
        reply_markup=user_kb.get_profile_kb()
    )

@router.callback_query(F.data == "profile_topup_menu")
async def show_payment_methods(callback: types.CallbackQuery, repo: Repository, enabled_payment_systems: dict):
    print(f"Доступные системы: {enabled_payment_systems}") 
    
    active_payment = await repo.get_user_active_payment(callback.from_user.id)
    if active_payment:
        await callback.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> У вас уже есть активный платеж!',
            show_alert=True
        )
        return
    
    await callback.message.edit_caption(
        caption='<tg-emoji emoji-id="5927169041595634481">💳</tg-emoji> <b>Выберите способ пополнения:</b>',
        reply_markup=user_kb.get_payment_methods_keyboard(enabled_payment_systems)
    )


@router.callback_query(F.data.startswith("payment_"))
async def handle_payment_method(callback: types.CallbackQuery, state: FSMContext, repo: Repository, enabled_payment_systems: dict):
    payment_method = callback.data.split("_")[1]
    if not enabled_payment_systems.get(payment_method):
        await callback.answer("Эта платежная система временно отключена.", show_alert=True)
        return

    fee_percentage = float(await repo.get_setting(f"{payment_method}_fee") or "0")
    
    method_names = {
        "lolz": "Lolz Market", "cryptobot": "CryptoBot", 
        "xrocet": "xRocet", "crystalpay": "CrystalPay",
        "platega": "Банковская карта"
    }
    
    if payment_method == "cryptobot":
        await state.set_state(PaymentStates.choosing_crypto)
        await state.update_data(payment_method=payment_method, fee_percentage=fee_percentage)
        
        cryptobot_handler = CryptoBotPayment()
        assets_result = await cryptobot_handler.get_supported_assets_for_rub()
        if assets_result["success"]:
            status_text = f'<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> Доступно {len(assets_result["assets"])} криптовалют'
        else:
            status_text = '<tg-emoji emoji-id="5881702736843511327">⚠️</tg-emoji> Ошибка API'
        
        await callback.message.edit_caption(
            caption=(f'<tg-emoji emoji-id="5927169041595634481">💳</tg-emoji> <b>Пополнение через {method_names[payment_method]}</b>\n\n'
                     f'<tg-emoji emoji-id="5778311685638984859">💸</tg-emoji> Комиссия: <b>{fee_percentage}%</b>\n'
                     f'<tg-emoji emoji-id="5931472654660800739">📊</tg-emoji> Статус: {status_text}\n\n'
                     "🪙 Выберите криптовалюту для оплаты:"),
            reply_markup=user_kb.get_crypto_selection_keyboard(assets_result.get("assets"))
        )
    else:
        await state.set_state(PaymentStates.waiting_amount)
        await state.update_data(payment_method=payment_method, fee_percentage=fee_percentage)
        
        await callback.message.edit_caption(
            caption=(f'<tg-emoji emoji-id="5927169041595634481">💳</tg-emoji> <b>Пополнение через {method_names[payment_method]}</b>\n\n'
                     f'<tg-emoji emoji-id="5778311685638984859">💸</tg-emoji> Комиссия: <b>{fee_percentage}%</b>\n\n'
                     '<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> Введите сумму пополнения (минимум 10 ₽):'),
            reply_markup=user_kb.get_cancel_keyboard()
        )

@router.callback_query(StateFilter(PaymentStates.choosing_crypto), F.data.startswith("crypto_"))
async def handle_crypto_selection(callback: types.CallbackQuery, state: FSMContext):
    crypto_asset = callback.data.split("_")[1]
    data = await state.get_data()
    fee_percentage = data["fee_percentage"]
    
    await state.set_state(PaymentStates.waiting_amount)
    await state.update_data(crypto_asset=crypto_asset)
    
    await callback.message.edit_caption(
        caption=(f'<tg-emoji emoji-id="5927169041595634481">💳</tg-emoji> <b>Пополнение через CryptoBot</b>\n\n'
                 f'🪙 Криптовалюта: <b>{crypto_asset}</b>\n'
                 f'<tg-emoji emoji-id="5778311685638984859">💸</tg-emoji> Комиссия: <b>{fee_percentage}%</b>\n\n'
                 '<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> Введите сумму пополнения в рублях (минимум 10 ₽):'),
        reply_markup=user_kb.get_cancel_keyboard()
    )

@router.message(StateFilter(PaymentStates.waiting_amount))
async def process_payment_amount(message: types.Message, state: FSMContext, repo: Repository, config: Config, enabled_payment_systems: dict):
    try:
        amount = float(message.text.replace(",", "."))
        if amount < config.payments.min_payment_amount:
            await message.answer(
                f'<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Минимальная сумма пополнения - {config.payments.min_payment_amount} ₽',
                parse_mode="HTML"
            )
            return
    except ValueError:
        await message.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Введите корректную сумму (число)',
            parse_mode="HTML"
        )
        return

    data = await state.get_data()
    payment_method = data["payment_method"]
    if not enabled_payment_systems.get(payment_method):
        await message.answer("Эта платежная система была отключена. Попробуйте снова.")
        await state.clear()
        return

    fee_percentage = data["fee_percentage"]
    fee_amount = round(amount * fee_percentage / 100, 2)
    total_amount = amount + fee_amount
    
    payment_handlers = {
        "lolz": LolzPayment(), 
        "cryptobot": CryptoBotPayment(),
        "xrocet": XRocetPayment(config.xrocet.api_key),
        "crystalpay": CrystalPayPayment(config.crystalpay.login, config.crystalpay.secret),
        "platega": PlategaPayment()
    }
    payment_handler = payment_handlers[payment_method]
    
    invoice_result = None
    if payment_method == "cryptobot":
        invoice_result = await payment_handler.create_invoice(total_amount, data.get("crypto_asset", "USDT"))
    elif payment_method in ["xrocet", "crystalpay"]:
        invoice_result = await payment_handler.create_invoice(total_amount, "Пополнение баланса")
    elif payment_method == "platega":
        invoice_url, transaction_id = await payment_handler.create_invoice(
            amount=total_amount,
            order_id=f"topup_{message.from_user.id}_{int(datetime.now().timestamp())}",
            description="Пополнение баланса",
            user_id=message.from_user.id
        )
        if invoice_url:
            invoice_result = {
                "success": True,
                "invoice_id": transaction_id,
                "payment_url": invoice_url
            }
        else:
            invoice_result = {"success": False, "error": "Ошибка API Platega"}
    else:
        invoice_result = await payment_handler.create_invoice(total_amount)

    if not invoice_result or not invoice_result.get("success"):
        await message.answer(
            f'<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Ошибка создания платежа: {invoice_result.get("error", "Неизвестная ошибка")}',
            parse_mode="HTML"
        )
        await state.clear()
        return

    invoice_id, payment_url = invoice_result["invoice_id"], invoice_result["payment_url"]
    expires_at = datetime.now() + timedelta(seconds=config.payments.payment_timeout_seconds)
    method_names = {
        "lolz": "Lolz", 
        "cryptobot": "CryptoBot", 
        "xrocet": "xRocet", 
        "crystalpay": "CrystalPay",
        "platega": "Банковская карта"
    }
    
    payment_text = (f'<tg-emoji emoji-id="5927169041595634481">💳</tg-emoji> <b>Счет на оплату создан!</b>\n\n'
                f'<tg-emoji emoji-id="5967822972931542886">🏪</tg-emoji> Способ: {method_names[payment_method]}\n'
                f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> К зачислению: <b>{amount:.2f} ₽</b>\n'
                f'<tg-emoji emoji-id="5778311685638984859">💸</tg-emoji> Комиссия: <b>{fee_amount:.2f} ₽</b>\n'
                f'<tg-emoji emoji-id="5927169041595634481">💳</tg-emoji> К оплате: <b>{total_amount:.2f} ₽</b>\n\n'
                f'<tg-emoji emoji-id="5875206779196935950">📄</tg-emoji> ID счета: <code>{invoice_id}</code>')
    
    sent_message = await message.answer(payment_text, reply_markup=user_kb.get_payment_keyboard(payment_url, invoice_id))
    
    await repo.create_payment(
        user_id=message.from_user.id, payment_method=payment_method,
        amount=amount, fee_amount=fee_amount, total_amount=total_amount,
        invoice_id=invoice_id, expires_at=expires_at,
        crypto_asset=data.get("crypto_asset"), message_id=sent_message.message_id,
        chat_id=sent_message.chat.id, payload_id=invoice_result.get("payload")
    )
    await state.clear()

@router.callback_query(F.data.startswith("cancel_payment_"))
async def cancel_payment(callback: types.CallbackQuery, repo: Repository):
    invoice_id = callback.data.split("_")[2]
    await repo.update_payment_status(invoice_id, "cancelled")
    await callback.message.edit_text(
        '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> <b>Платеж отменен</b>',
        reply_markup=user_kb.get_main_menu_only_keyboard(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_caption(caption="Действие отменено.", reply_markup=user_kb.get_profile_kb())

@router.callback_query(F.data == "profile_activate_promo")
async def profile_activate_promo_callback(call: types.CallbackQuery, state: FSMContext):
    await safe_delete_message(call)
    await safe_answer(call, "<b>Активация промокода</b>\n\nВведите промокод:", reply_markup=user_kb.get_cancel_keyboard())
    await state.set_state(PromoUserStates.waiting_for_code)

@router.callback_query(F.data.startswith("check_pay_"))
async def check_platega_payment_handler(call: types.CallbackQuery, repo: Repository, config: Config):
    invoice_id = call.data.split("_")[2]
    payment = await repo.get_payment_by_invoice_id(invoice_id)
    
    if not payment or payment['status'] != 'pending':
        await call.answer(
            '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji> Платеж не найден или уже обработан.',
            show_alert=True
        )
        return

    if payment['payment_method'] == 'platega':
        from payments.platega_payment import PlategaPayment
        platega = PlategaPayment()
        
        is_paid = await platega.check_status(invoice_id)
        
        if is_paid:
            result = await repo.process_successful_payment(invoice_id)
            if result:
                await call.message.edit_text(
                    f'<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji> <b>Оплата прошла успешно!</b>\n'
                    f'<tg-emoji emoji-id="5877485980901971030">💰</tg-emoji> Ваш баланс пополнен на <b>{payment["amount"]:.2f} ₽</b>',
                    parse_mode="HTML"
                )
                await call.answer("Баланс пополнен!", show_alert=True)
        else:
            await call.answer(
                'Оплата еще не поступила. Попробуйте через минуту.',
                show_alert=True
            )
    else:
        await call.answer("Проверка для этого метода еще не настроена.", show_alert=True)

@router.message(PromoUserStates.waiting_for_code)
async def promo_user_enter_code(message: types.Message, state: FSMContext, repo: Repository, config: Config):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    promo = await repo.get_promo_by_code(code)
    
    if not promo or (promo['expires_at'] and datetime.fromisoformat(promo['expires_at']) < datetime.now()) or (promo['max_uses'] and promo['current_uses'] >= promo['max_uses']):
        await message.answer(
            '<tg-emoji emoji-id="5881702736843511327">❗️</tg-emoji> Промокод не найден или неактивен.',
            parse_mode="HTML"
        )
        return

    if await repo.check_promo_usage_by_user(user_id, promo['id']):
        await message.answer(
            '<tg-emoji emoji-id="5881702736843511327">❗️</tg-emoji> Вы уже использовали этот промокод.',
            parse_mode="HTML"
        )
        return

    await repo.activate_promo_for_user(user_id, promo)
    if promo['promo_type'] == 'discount':
        await message.answer(
            f'<tg-emoji emoji-id="5902002809573740949">🎉</tg-emoji> Промокод <code>{code}</code> активирован! Ваша скидка: <b>{promo["value"]}%</b> на следующую покупку.',
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f'<tg-emoji emoji-id="5902002809573740949">🎉</tg-emoji> Промокод <code>{code}</code> активирован! Баланс пополнен на <b>{promo["value"]} ₽</b>.',
            parse_mode="HTML"
        )
    
    await state.clear()
    await show_main_menu(message, repo, config, message.from_user)