"""Общие проверки данных и демонстрационные курсы."""

import math
import re
from datetime import UTC, datetime

# Фиктивная цена одной единицы валюты в USD, а не рыночные котировки.
DEFAULT_EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 1.0786,
    "BTC": 59337.21,
    "RUB": 0.01016,
    "ETH": 3720.0,
}


def normalize_currency(currency_code: str) -> str:
    """Привести код валюты к верхнему регистру и проверить формат."""
    if not isinstance(currency_code, str):
        raise ValueError("Код валюты должен быть непустой строкой")
    code = currency_code.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]*", code):
        raise ValueError("Код валюты должен содержать латинские буквы и цифры")
    return code


def validate_number(value: float, *, name: str, positive: bool = False) -> float:
    """Проверить конечное число; bool и числовые строки не принимаются."""
    message = (
        f"'{name}' должен быть положительным числом"
        if positive
        else f"'{name}' должен быть неотрицательным числом"
    )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(message)
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(message) from exc
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(message)
    return number


def validate_user_id(user_id: int) -> int:
    """Идентификатор пользователя — положительное целое число."""
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id должен быть положительным целым числом")
    return user_id


def validate_username(username: str) -> str:
    """Удалить внешние пробелы и проверить имя пользователя."""
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")
    return username.strip()


def validate_password(password: str) -> str:
    """Пароль должен содержать не менее четырёх символов."""
    if not isinstance(password, str) or len(password) < 4:
        raise ValueError("Пароль должен быть не короче 4 символов")
    return password


def parse_timestamp(value: str) -> datetime:
    """Прочитать ISO-дату; даты без часового пояса трактуются как UTC."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)
