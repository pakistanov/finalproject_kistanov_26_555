"""Валидация данных, работа с JSON и временем."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING

from valutatrade_hub.core.exceptions import (
    RateUnavailableError,
    StaleRateError,
    StorageError,
)

if TYPE_CHECKING:
    from valutatrade_hub.infra.database import DatabaseManager

# Заглушка только для самостоятельного использования модели Portfolio.
# Рабочие usecases всегда передают курсы из кэша.
EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 1.0786,
    "GBP": 1.25,
    "RUB": 0.01016,
    "BTC": 59337.21,
    "ETH": 3720.0,
    "SOL": 145.12,
}


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
    """Преобразовать дату в ISO 8601 UTC с суффиксом Z."""
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
    """Прочитать JSON заданного типа; при отсутствии использовать default."""
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
    """Записать JSON через временный файл с атомарной заменой назначения."""
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


def database_transaction(method):
    """Удерживать блокировку менеджера до завершения сценария."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._storage.transaction():
            return method(self, *args, **kwargs)

    return wrapped


@dataclass(frozen=True)
class RateQuote:
    """Цена одной единицы from_currency в единицах to_currency."""

    from_currency: str
    to_currency: str
    rate: float
    updated_at: datetime
    source: str
    is_stale: bool = False


@dataclass(frozen=True)
class CachedRatesView:
    """Курсы локального снимка и время его последнего обновления."""

    quotes: tuple[RateQuote, ...]
    last_refresh: str | None


class RateService:
    """Core не обращается к API: обновлением занимается Parser Service."""

    def __init__(
        self,
        storage: DatabaseManager | None = None,
        *,
        ttl_seconds: float | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Подключить читатель кэша, часы и настройку TTL."""
        from valutatrade_hub.infra.database import DatabaseManager
        from valutatrade_hub.infra.settings import SettingsLoader

        self._settings = SettingsLoader()
        self._storage = storage if storage is not None else DatabaseManager()
        self._ttl = (
            None
            if ttl_seconds is None
            else validate_number(ttl_seconds, name="ttl_seconds", positive=True)
        )
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)

    @property
    def ttl_seconds(self) -> float:
        """Вернуть срок свежести курсов в секундах."""
        return (
            self._settings.get("rates_ttl_seconds") if self._ttl is None else self._ttl
        )

    def _graph(self, cache: dict, now: datetime, *, allow_stale: bool) -> dict:
        from valutatrade_hub.core.currencies import get_currency

        graph: dict[str, dict[str, RateQuote]] = {}
        for pair, entry in extract_rate_pairs(cache).items():
            try:
                left, right = pair.split("_")
                left, right = get_currency(left).code, get_currency(right).code
                if left == right:
                    continue
                rate = validate_number(entry["rate"], name="rate", positive=True)
                inverse = validate_number(1 / rate, name="rate", positive=True)
                updated = parse_timestamp(entry["updated_at"])
                age = (now - updated).total_seconds()
                if age < 0 or (not allow_stale and age >= self.ttl_seconds):
                    continue
                source = entry.get("source", cache.get("source", "Cache"))
                if not isinstance(source, str) or not source.strip():
                    continue
            except KeyError, TypeError, ValueError, OverflowError:
                continue
            for origin, target, value in ((left, right, rate), (right, left, inverse)):
                previous = graph.setdefault(origin, {}).get(target)
                if previous is None or previous.updated_at < updated:
                    graph[origin][target] = RateQuote(
                        origin, target, value, updated, source
                    )
        return graph

    @staticmethod
    def _find(graph: dict, left: str, right: str, now: datetime) -> RateQuote | None:
        if left == right:
            return RateQuote(left, right, 1.0, now, "Identity")
        queue = deque([(left, 1.0, now, frozenset())])
        visited = {left}
        while queue:
            origin, accumulated, updated, sources = queue.popleft()
            for target, edge in sorted(graph.get(origin, {}).items()):
                if target in visited:
                    continue
                try:
                    value = validate_number(
                        accumulated * edge.rate, name="rate", positive=True
                    )
                    validate_number(1 / value, name="rate", positive=True)
                except ValueError:
                    continue
                timestamp = min(updated, edge.updated_at)
                combined = sources | {edge.source}
                if target == right:
                    return RateQuote(
                        left, right, value, timestamp, " + ".join(sorted(combined))
                    )
                visited.add(target)
                queue.append((target, value, timestamp, combined))
        return None

    @database_transaction
    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Получить свежий прямой, обратный или кросс-курс из локального кэша."""
        from valutatrade_hub.core.currencies import get_currency

        left, right = get_currency(from_currency).code, get_currency(to_currency).code
        cache = self._storage.load_rates()
        now = self._clock()
        quote = self._find(self._graph(cache, now, allow_stale=False), left, right, now)
        if quote is not None:
            return quote
        stale = self._find(self._graph(cache, now, allow_stale=True), left, right, now)
        if stale is not None:
            raise StaleRateError(left, right, utc_timestamp(stale.updated_at))
        raise RateUnavailableError(left, right)

    @database_transaction
    def get_cached_rates(
        self,
        currency_code: str | None = None,
        *,
        top: int | None = None,
        base_currency: str | None = None,
    ) -> CachedRatesView:
        """Отобрать курсы; топ определяется в USD до пересчёта базы вывода."""
        from valutatrade_hub.core.currencies import CryptoCurrency, get_currency

        if top is not None and (
            isinstance(top, bool) or not isinstance(top, int) or top <= 0
        ):
            raise ValueError("'top' должен быть положительным целым числом")
        cache = self._storage.load_rates()
        now = self._clock()
        graph = self._graph(cache, now, allow_stale=True)
        if not graph:
            raise ValueError(
                "Локальный кеш курсов пуст. Выполните 'update-rates', "
                "чтобы загрузить данные."
            )
        base = get_currency(
            self._settings.get("default_base_currency")
            if base_currency is None
            else base_currency
        ).code
        if currency_code is not None:
            code = normalize_currency(currency_code)
            if code not in graph:
                raise ValueError(f"Курс для '{code}' не найден в кеше.")
            codes = [code]
        else:
            codes = sorted(set(graph) if top is not None else set(graph) - {base})
        if top is not None:
            ranked = []
            for code in codes:
                if not isinstance(get_currency(code), CryptoCurrency):
                    continue
                price = self._find(graph, code, "USD", now)
                if price is None:
                    raise RateUnavailableError(code, "USD")
                ranked.append((code, price.rate))
            if not ranked:
                raise ValueError("В кеше нет курсов криптовалют для выбранного фильтра")
            codes = [
                code
                for code, _ in sorted(ranked, key=lambda item: (-item[1], item[0]))[
                    :top
                ]
            ]
        quotes = []
        for code in codes:
            quote = self._find(graph, code, base, now)
            if quote is None:
                raise RateUnavailableError(code, base)
            stale = (now - quote.updated_at).total_seconds() >= self.ttl_seconds
            quotes.append(replace(quote, is_stale=stale))
        if not quotes:
            raise RateUnavailableError(base, base)
        refresh = cache.get("last_refresh")
        return CachedRatesView(
            tuple(quotes), refresh if isinstance(refresh, str) else None
        )
