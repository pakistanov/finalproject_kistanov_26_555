"""Валидация данных, работа с JSON и временем."""

import json
import math
import os
import re
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from valutatrade_hub.core.exceptions import StorageError


def normalize_currency(currency_code: str) -> str:
    """Привести код валюты к верхнему регистру и проверить формат."""
    if not isinstance(currency_code, str):
        raise ValueError("Код валюты должен быть непустой строкой")
    code = currency_code.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,4}", code):
        raise ValueError("Код валюты должен содержать 2–5 латинских букв или цифр")
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


def utc_timestamp(moment: datetime | None = None) -> str:
    moment = datetime.now(UTC) if moment is None else moment
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def extract_rate_pairs(cache: dict) -> dict:
    """Читать новый снимок и прежний плоский формат, исключая заглушки."""
    pairs = cache.get("pairs", cache)
    if not isinstance(pairs, dict):
        raise StorageError(
            "Некорректная структура rates.json: pairs должен быть словарём"
        )
    return {
        pair: entry.copy()
        for pair, entry in pairs.items()
        if isinstance(entry, dict)
        and "rate" in entry
        and "DemoStub" not in str(entry.get("source", cache.get("source", "")))
    }


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Недопустимая JSON-константа: {value}")


def read_json(path: Path, expected_type: type, *, default=None) -> list | dict:
    try:
        with path.open(encoding="utf-8") as source:
            data = json.load(source, parse_constant=_reject_json_constant)
    except FileNotFoundError as exc:
        if default is not None:
            return deepcopy(default)
        raise StorageError(f"Не удалось прочитать {path.name}") from exc
    except (OSError, UnicodeError, ValueError) as exc:
        raise StorageError(f"Не удалось прочитать {path.name}") from exc
    if not isinstance(data, expected_type):
        raise StorageError(f"Некорректная структура {path.name}")
    return data


def atomic_write_json(path: Path, data: list | dict) -> None:
    temporary_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as target:
            temporary_path = Path(target.name)
            json.dump(data, target, ensure_ascii=False, indent=2, allow_nan=False)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError) as exc:
        raise StorageError(f"Не удалось сохранить {path.name}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
