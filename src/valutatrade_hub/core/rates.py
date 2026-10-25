"""Единый контракт курсов, кэш JSON и заменяемая демонстрационная заглушка."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from valutatrade_hub.core.exceptions import RateUnavailableError
from valutatrade_hub.core.storage import JsonStorage
from valutatrade_hub.core.utils import (
    DEFAULT_EXCHANGE_RATES,
    normalize_currency,
    parse_timestamp,
    validate_number,
)


@dataclass(frozen=True)
class RateQuote:
    """Курс: сколько единиц to_currency стоит одна единица from_currency."""

    from_currency: str
    to_currency: str
    rate: float
    updated_at: datetime
    source: str


class StubRateProvider:
    """Фиктивные USD-цены; этот класс позже заменит клиент Parser Service."""

    source = "DemoStub"

    def __init__(self, exchange_rates: dict[str, float] | None = None) -> None:
        rates = DEFAULT_EXCHANGE_RATES if exchange_rates is None else exchange_rates
        self._rates = {
            normalize_currency(code): validate_number(rate, name="rate", positive=True)
            for code, rate in rates.items()
        }
        self._rates["USD"] = 1.0

    @property
    def currencies(self) -> frozenset[str]:
        return frozenset(self._rates)

    def get_usd_rate(self, currency_code: str) -> float:
        return self._rates[currency_code]


class RateService:
    """Свежий прямой/обратный курс или кросс-курс через USD, иначе провайдер."""

    def __init__(
        self,
        storage: JsonStorage,
        provider: StubRateProvider | None = None,
        *,
        ttl_seconds: float = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._storage = storage
        self._provider = provider if provider is not None else StubRateProvider()
        self._ttl = validate_number(ttl_seconds, name="ttl_seconds", positive=True)
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)

    def _cached(
        self, cache: dict, from_code: str, to_code: str, now: datetime
    ) -> RateQuote | None:
        for left, right, inverse in (
            (from_code, to_code, False),
            (to_code, from_code, True),
        ):
            entry = cache.get(f"{left}_{right}")
            if not isinstance(entry, dict):
                continue
            try:
                rate = validate_number(entry["rate"], name="rate", positive=True)
                timestamp = parse_timestamp(entry["updated_at"])
                age = (now - timestamp).total_seconds()
                if not 0 <= age < self._ttl:
                    continue
                rate = validate_number(
                    1 / rate if inverse else rate, name="rate", positive=True
                )
            except KeyError, TypeError, ValueError, OverflowError:
                continue
            return RateQuote(
                from_code,
                to_code,
                rate,
                timestamp,
                str(entry.get("source", cache.get("source", "Cache"))),
            )
        return None

    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Получить курс, его время и источник; устаревшие данные не выдаются."""
        from_code = normalize_currency(from_currency)
        to_code = normalize_currency(to_currency)
        now = self._clock()
        cache = self._storage.load_rates()
        error = f"Курс {from_code}→{to_code} недоступен. Повторите попытку позже."
        if from_code == to_code:
            known = from_code in self._provider.currencies or any(
                from_code in key.split("_")
                for key, entry in cache.items()
                if isinstance(entry, dict) and "rate" in entry
            )
            if not known:
                raise RateUnavailableError(error)
            return RateQuote(from_code, to_code, 1.0, now, "Identity")
        direct = self._cached(cache, from_code, to_code, now)
        if direct is not None:
            return direct

        legs = []
        changed = False
        for code in (from_code, to_code):
            if code == "USD":
                legs.append(RateQuote("USD", "USD", 1.0, now, "Identity"))
                continue
            quote = self._cached(cache, code, "USD", now)
            if quote is None:
                try:
                    rate = self._provider.get_usd_rate(code)
                except (KeyError, OSError, TimeoutError) as exc:
                    raise RateUnavailableError(error) from exc
                quote = RateQuote(code, "USD", rate, now, self._provider.source)
                cache[f"{code}_USD"] = {
                    "rate": rate,
                    "updated_at": now.isoformat(),
                    "source": quote.source,
                }
                changed = True
            legs.append(quote)
        try:
            rate = validate_number(
                legs[0].rate / legs[1].rate, name="rate", positive=True
            )
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            raise RateUnavailableError(error) from exc
        sources = sorted({quote.source for quote in legs if quote.source != "Identity"})
        result = RateQuote(
            from_code,
            to_code,
            rate,
            min(quote.updated_at for quote in legs),
            " + ".join(sources),
        )
        if changed:
            cache[f"{from_code}_{to_code}"] = {
                "rate": result.rate,
                "updated_at": result.updated_at.isoformat(),
                "source": result.source,
            }
            cache["source"] = self._provider.source
            cache["last_refresh"] = now.isoformat()
            self._storage.save_rates(cache)
        return result
