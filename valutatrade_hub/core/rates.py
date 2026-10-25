"""Чтение локального кэша, проверка TTL и расчёт обратных и кросс-курсов."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from valutatrade_hub.core.currencies import CryptoCurrency, get_currency
from valutatrade_hub.core.exceptions import RateUnavailableError, StaleRateError
from valutatrade_hub.core.utils import (
    extract_rate_pairs,
    normalize_currency,
    parse_timestamp,
    utc_timestamp,
    validate_number,
)
from valutatrade_hub.infra.database import DatabaseManager, database_transaction
from valutatrade_hub.infra.settings import SettingsLoader


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
        return (
            self._settings.get("rates_ttl_seconds") if self._ttl is None else self._ttl
        )

    def _graph(self, cache: dict, now: datetime, *, allow_stale: bool) -> dict:
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
        left, right = get_currency(from_currency).code, get_currency(to_currency).code
        now = self._clock()
        cache = self._storage.load_rates()
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
        now = self._clock()
        cache = self._storage.load_rates()
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
            codes = sorted(set(graph) - {base})
        if top is not None:
            if isinstance(top, bool) or not isinstance(top, int) or top <= 0:
                raise ValueError("'top' должен быть положительным целым числом")
            codes = [
                code for code in codes if isinstance(get_currency(code), CryptoCurrency)
            ]
            if not codes:
                raise ValueError("В кеше нет курсов криптовалют для выбранного фильтра")
        quotes = []
        for code in codes:
            quote = self._find(graph, code, base, now)
            if quote is not None:
                stale = (now - quote.updated_at).total_seconds() >= self.ttl_seconds
                quotes.append(replace(quote, is_stale=stale))
        if not quotes:
            raise RateUnavailableError(codes[0] if codes else base, base)
        if top is not None:
            quotes.sort(key=lambda quote: (-quote.rate, quote.from_currency))
            quotes = quotes[:top]
        refresh = cache.get("last_refresh")
        return CachedRatesView(
            tuple(quotes), refresh if isinstance(refresh, str) else None
        )
