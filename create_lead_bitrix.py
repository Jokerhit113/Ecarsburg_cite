"""Создание лида в Bitrix24 через входящий вебхук."""
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL", "").strip().rstrip("/")


class BitrixLeadError(Exception):
    """Ошибка создания лида в Bitrix24."""


def create_lead(name: str, telephone_number: str, promocode: str) -> dict:
    """Создать лид и вернуть ответ Bitrix24. Исключения содержат безопасное описание."""
    webhook_url = os.getenv("BITRIX_WEBHOOK_URL", "").strip().rstrip("/")
    if not webhook_url:
        raise BitrixLeadError("Интеграция Bitrix24 не настроена: укажите BITRIX_WEBHOOK_URL в .env")
    if not re.match(r"^https://[^/]+/rest/[^/]+/[^/]+$", webhook_url):
        raise BitrixLeadError("Некорректный формат BITRIX_WEBHOOK_URL")

    clean_name = " ".join((name or "").split())
    clean_phone = " ".join((telephone_number or "").split())
    clean_promo = " ".join((promocode or "").split()) or "ECARSBURG"
    payload = {
        "fields": {
            "TITLE": f"{clean_name} С Сайта Визитки",
            "NAME": clean_name,
            "COMPANY_TITLE": clean_promo,
            "COMMENTS": f"Покупатель пришел от компании {clean_promo}",
            "EMAIL": [{"VALUE": "test@mail.ru", "VALUE_TYPE": "WORK"}],
            "PHONE": [{"VALUE": clean_phone, "VALUE_TYPE": "WORK"}],
        },
        "params": {"REGISTER_SONET_EVENT": "Y"},
    }
    try:
        response = requests.post(f"{webhook_url}/crm.lead.add.json", json=payload, timeout=(3.05, 10))
        response.raise_for_status()
        data = response.json()
    except requests.Timeout as exc:
        raise BitrixLeadError("Bitrix24 не ответил вовремя. Попробуйте позже.") from exc
    except requests.RequestException as exc:
        raise BitrixLeadError("Не удалось связаться с Bitrix24. Попробуйте позже.") from exc
    except ValueError as exc:
        raise BitrixLeadError("Bitrix24 вернул некорректный ответ.") from exc

    if data.get("error"):
        description = data.get("error_description") or data.get("error")
        raise BitrixLeadError(f"Bitrix24 отклонил запрос: {description}")
    if not data.get("result"):
        raise BitrixLeadError("Bitrix24 не подтвердил создание лида.")
    return {"id": data["result"]}
