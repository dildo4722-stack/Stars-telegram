import aiohttp
import json
import logging
from config import PLATEGA_MERCHANT_ID, PLATEGA_SECRET

logger = logging.getLogger(__name__)

class PlategaPayment: # Имя класса, которое ждет твой purchase_stars.py
    def __init__(self):
        self.base_url = "https://app.platega.io"
        self.merchant_id = PLATEGA_MERCHANT_ID
        self.secret = PLATEGA_SECRET

    async def create_invoice(self, amount: float, order_id: str = "deposit", description: str = "", user_id: int = None, payment_method: int = 2):
        """Создание счета. Аргументы подогнаны под вызов в purchase_stars.py"""
        
        # Обработка описания, как в твоем исходном коде
        if user_id:
            description = f"TgId:{user_id} | {description}"
        
        payload = {
            "paymentMethod": payment_method,
            "paymentDetails": {
                "amount": float(amount),
                "currency": "RUB"
            },
            "description": description[:255],
            "return": "https://t.me/kskdkdkdkfkfbot",
            "failedUrl": "https://t.me/kskdkdkdkfkfbot",
            "payload": str(order_id)
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-MerchantId": str(self.merchant_id),
            "X-Secret": str(self.secret)
        }
        print(f"DEBUG Headers: Merchant={self.merchant_id}, Secret={self.secret}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/v2/transaction/process",
                    json=payload,
                    headers=headers,
                    timeout=20
                ) as response:
                    res_text = await response.text()
                    if response.status == 200:
                        data = json.loads(res_text)
                        # Возвращаем кортеж (ссылка, ID), который ждет обработчик
                        return data.get("url"), data.get("transactionId")
                    
                    logger.error(f"Platega Error: {response.status} - {res_text}")
                    return None, None
        except Exception as e:
            logger.error(f"Platega Connection Error: {e}")
            return None, None

    async def check_status(self, transaction_id: str):
        """Метод для проверки статуса"""
        headers = {
            "X-MerchantId": self.merchant_id,
            "X-Secret": self.secret
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/transaction/{transaction_id}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("status") == "CONFIRMED"
                    return False
        except Exception:
            return False