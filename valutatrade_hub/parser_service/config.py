"""Настройки API, отслеживаемых валют и файлов сервиса парсинга."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

from valutatrade_hub.core.currencies import CryptoCurrency, FiatCurrency, get_currency
from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.utils import validate_number
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EXCHANGERATE_API_URL = "https://v6.exchangerate-api.com/v6"
FIAT_CURRENCIES = ("EUR", "GBP", "RUB")
CRYPTO_CURRENCIES = ("BTC", "ETH", "SOL")
CRYPTO_ID_MAP = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}


def _get_api_key(name: str) -> str | None:
    """Окружение имеет приоритет над локальным .env в рабочем каталоге."""
    value = os.getenv(name)
    if value is None:
        try:
            value = dotenv_values(
                Path.cwd() / ".env", interpolate=False, encoding="utf-8-sig"
            ).get(name)
        except OSError, UnicodeError:
            raise StorageError("Не удалось прочитать файл .env") from None
    if value is None:
        return None
    return value.strip() or None


@dataclass
class ParserConfig:
    """Параметры API и файлов; секретные ключи исключены из repr."""

    EXCHANGERATE_API_KEY: str | None = field(
        default_factory=lambda: _get_api_key("EXCHANGERATE_API_KEY"), repr=False
    )
    COINGECKO_API_KEY: str | None = field(
        default_factory=lambda: _get_api_key("COINGECKO_API_KEY"), repr=False
    )
    COINGECKO_URL: str = COINGECKO_URL
    EXCHANGERATE_API_URL: str = EXCHANGERATE_API_URL
    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple[str, ...] = FIAT_CURRENCIES
    CRYPTO_CURRENCIES: tuple[str, ...] = CRYPTO_CURRENCIES
    CRYPTO_ID_MAP: dict[str, str] = field(default_factory=lambda: CRYPTO_ID_MAP.copy())
    RATES_FILE_PATH: Path = Path("data/rates.json")
    HISTORY_FILE_PATH: Path = Path("data/exchange_rates.json")
    PARSER_LOG_FILE_PATH: Path = Path("logs/parser.log")
    REQUEST_TIMEOUT: float = 10
    UPDATE_INTERVAL_SECONDS: float = 300

    def __post_init__(self) -> None:
        """Проверить валюты, URL, числовые параметры и уникальность путей."""
        base = get_currency(self.BASE_CURRENCY)
        if not isinstance(base, FiatCurrency):
            raise ValueError("Базовая валюта парсера должна быть фиатной")
        self.BASE_CURRENCY = base.code
        for attribute, currency_type in (
            ("FIAT_CURRENCIES", FiatCurrency),
            ("CRYPTO_CURRENCIES", CryptoCurrency),
        ):
            values = getattr(self, attribute)
            if not isinstance(values, (tuple, list)):
                raise ValueError(f"'{attribute}' должен быть списком валют")
            codes = []
            for code in values:
                currency = get_currency(code)
                if not isinstance(currency, currency_type):
                    raise ValueError(f"Некорректный тип валюты в {attribute}")
                if currency.code not in codes:
                    codes.append(currency.code)
            setattr(self, attribute, tuple(codes))
        if not isinstance(self.CRYPTO_ID_MAP, dict):
            raise ValueError("'CRYPTO_ID_MAP' должен быть словарём")
        self.CRYPTO_ID_MAP = self.CRYPTO_ID_MAP.copy()
        for code in self.CRYPTO_CURRENCIES:
            raw_id = self.CRYPTO_ID_MAP.get(code)
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise ValueError(f"Не задан CoinGecko ID для {code}")
        for attribute in ("COINGECKO_URL", "EXCHANGERATE_API_URL"):
            value = getattr(self, attribute)
            if not isinstance(value, str):
                raise ValueError(f"'{attribute}' должен быть HTTPS URL")
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username:
                raise ValueError(f"'{attribute}' должен быть HTTPS URL")
        for attribute in ("REQUEST_TIMEOUT", "UPDATE_INTERVAL_SECONDS"):
            setattr(
                self,
                attribute,
                validate_number(
                    getattr(self, attribute), name=attribute, positive=True
                ),
            )
        for attribute in (
            "RATES_FILE_PATH",
            "HISTORY_FILE_PATH",
            "PARSER_LOG_FILE_PATH",
        ):
            setattr(self, attribute, Path(getattr(self, attribute)).resolve())
        if (
            len(
                {
                    self.RATES_FILE_PATH,
                    self.HISTORY_FILE_PATH,
                    self.PARSER_LOG_FILE_PATH,
                }
            )
            != 3
        ):
            raise ValueError("Файлы парсера должны различаться")

    @classmethod
    def from_settings(cls, database: DatabaseManager | None = None) -> ParserConfig:
        """Собрать настройки из Singleton и ключи из окружения или .env."""
        settings = SettingsLoader()
        database = database if database is not None else DatabaseManager()
        return cls(
            COINGECKO_URL=settings.get("coingecko_url", COINGECKO_URL),
            EXCHANGERATE_API_URL=settings.get(
                "exchangerate_api_url", EXCHANGERATE_API_URL
            ),
            BASE_CURRENCY=settings.get("parser_base_currency", "USD"),
            FIAT_CURRENCIES=settings.get("parser_fiat_currencies", FIAT_CURRENCIES),
            CRYPTO_CURRENCIES=settings.get(
                "parser_crypto_currencies", CRYPTO_CURRENCIES
            ),
            CRYPTO_ID_MAP=settings.get("crypto_id_map", CRYPTO_ID_MAP.copy()),
            RATES_FILE_PATH=database.data_dir / settings.get("rates_file"),
            HISTORY_FILE_PATH=database.data_dir / settings.get("history_file"),
            PARSER_LOG_FILE_PATH=settings.get("log_dir")
            / settings.get("parser_log_file"),
            REQUEST_TIMEOUT=settings.get("request_timeout", 10),
            UPDATE_INTERVAL_SECONDS=settings.get("update_interval_seconds", 300),
        )
