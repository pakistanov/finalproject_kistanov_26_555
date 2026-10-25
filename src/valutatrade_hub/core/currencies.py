"""Иерархия валют и единый реестр поддерживаемых кодов."""

from abc import ABC, abstractmethod
from copy import copy

from valutatrade_hub.core.exceptions import CurrencyNotFoundError
from valutatrade_hub.core.utils import normalize_currency, validate_number


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' должен быть непустой строкой")
    return value.strip()


class Currency(ABC):
    """Общий интерфейс валюты с проверяемыми публичными именем и кодом."""

    def __init__(self, name: str, code: str) -> None:
        self.name = name
        self.code = code

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = _nonempty(value, "name")

    @property
    def code(self) -> str:
        return self._code

    @code.setter
    def code(self, value: str) -> None:
        self._code = normalize_currency(value)

    @abstractmethod
    def get_display_info(self) -> str:
        """Вернуть описание валюты для интерфейса и логов."""


class FiatCurrency(Currency):
    """Фиатная валюта с указанием страны или зоны эмиссии."""

    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        super().__init__(name, code)
        self.issuing_country = _nonempty(issuing_country, "issuing_country")

    def get_display_info(self) -> str:
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом и последней известной капитализацией."""

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float) -> None:
        super().__init__(name, code)
        self.algorithm = _nonempty(algorithm, "algorithm")
        self.market_cap = validate_number(market_cap, name="market_cap")

    def get_display_info(self) -> str:
        market_cap = f"{self.market_cap:.3g}".replace("e+", "e")
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {market_cap})"
        )


# Учебные метаданные, не обновляемые рыночные показатели.
_CURRENCIES: dict[str, Currency] = {
    "USD": FiatCurrency("US Dollar", "USD", "United States"),
    "EUR": FiatCurrency("Euro", "EUR", "Eurozone"),
    "RUB": FiatCurrency("Russian Ruble", "RUB", "Russia"),
    "BTC": CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
    "ETH": CryptoCurrency("Ethereum", "ETH", "Ethash", 4.5e11),
}


def get_currency(code: str) -> Currency:
    """Вернуть валюту; изменение объекта не меняет запись реестра."""
    try:
        normalized = normalize_currency(code)
    except ValueError as exc:
        raise CurrencyNotFoundError(str(code)) from exc
    if normalized not in _CURRENCIES:
        raise CurrencyNotFoundError(normalized)
    return copy(_CURRENCIES[normalized])


def get_supported_codes() -> tuple[str, ...]:
    return tuple(sorted(_CURRENCIES))
