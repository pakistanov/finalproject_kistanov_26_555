"""HTTP-клиенты с единым результатом {FROM_TO: rate}."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import perf_counter
from urllib.parse import quote, urlparse

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import utc_timestamp, validate_number
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    """Общий контракт HTTP-клиентов и безопасная обработка ответов API."""

    source = "API"

    def __init__(self, config: ParserConfig, session=None) -> None:
        """Сохранить конфигурацию и HTTP-клиент для запросов."""
        self.config = config
        self._http = session if session is not None else requests
        self.last_metadata: dict[str, dict] = {}

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Получить и проверить курсы; ошибки представляются как ApiRequestError."""

    def _get_json(self, url: str, *, params=None, headers=None) -> tuple[dict, dict]:
        started = perf_counter()
        try:
            response = self._http.get(
                url,
                params=params,
                headers=headers,
                timeout=self.config.REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.exceptions.Timeout:
            raise ApiRequestError(f"{self.source}: превышено время ожидания") from None
        except requests.exceptions.RequestException:
            # Текст requests содержит URL с ключом ExchangeRate-API — не выводим его.
            raise ApiRequestError(f"{self.source}: ошибка сети") from None
        try:
            if response.status_code != 200:
                reasons = {
                    401: "неверный или отсутствующий API-ключ",
                    403: "доступ запрещён; проверьте API-ключ",
                    429: "превышен лимит запросов; повторите позже",
                }
                reason = reasons.get(
                    response.status_code, f"HTTP {response.status_code}"
                )
                raise ApiRequestError(f"{self.source}: {reason}")
            try:
                data = response.json()
            except ValueError:
                raise ApiRequestError(f"{self.source}: некорректный JSON") from None
            if not isinstance(data, dict):
                raise ApiRequestError(f"{self.source}: ожидался JSON-объект")
            meta = {
                "request_ms": round((perf_counter() - started) * 1000, 3),
                "status_code": response.status_code,
                "received_at": utc_timestamp(),
            }
            etag = response.headers.get("ETag")
            if etag:
                meta["etag"] = etag
            return data, meta
        finally:
            response.close()

    def _metadata(
        self,
        request_meta: dict,
        *,
        raw_id: str | None = None,
        provider_updated_at: str | None = None,
    ) -> dict:
        meta = {
            key: value for key, value in request_meta.items() if key != "received_at"
        }
        if raw_id is not None:
            meta["raw_id"] = raw_id
        if provider_updated_at is not None:
            meta["provider_updated_at"] = provider_updated_at
        return {"timestamp": request_meta["received_at"], "meta": meta}

    @staticmethod
    def _unix_time(value) -> str:
        timestamp = validate_number(value, name="timestamp", positive=True)
        return utc_timestamp(datetime.fromtimestamp(timestamp, UTC))


class CoinGeckoClient(BaseApiClient):
    """Получение криптовалют по CoinGecko ID в выбранной фиатной базе."""

    source = "CoinGecko"

    def fetch_rates(self) -> dict[str, float]:
        """Получить цены настроенных криптовалют и метаданные HTTP-ответа."""
        self.last_metadata = {}
        codes = self.config.CRYPTO_CURRENCIES
        if not codes:
            return {}
        headers = {}
        if self.config.COINGECKO_API_KEY:
            host = urlparse(self.config.COINGECKO_URL).hostname
            header = (
                "x-cg-pro-api-key"
                if host == "pro-api.coingecko.com"
                else "x-cg-demo-api-key"
            )
            headers[header] = self.config.COINGECKO_API_KEY
        data, request_meta = self._get_json(
            self.config.COINGECKO_URL,
            params={
                "ids": ",".join(self.config.CRYPTO_ID_MAP[code] for code in codes),
                "vs_currencies": self.config.BASE_CURRENCY.lower(),
                "include_last_updated_at": "true",
            },
            headers=headers,
        )
        rates, metadata = {}, {}
        try:
            for code in codes:
                raw_id = self.config.CRYPTO_ID_MAP[code]
                entry = data[raw_id]
                pair = f"{code}_{self.config.BASE_CURRENCY}"
                rates[pair] = validate_number(
                    entry[self.config.BASE_CURRENCY.lower()], name="rate", positive=True
                )
                provider_time = (
                    self._unix_time(entry["last_updated_at"])
                    if "last_updated_at" in entry
                    else None
                )
                metadata[pair] = self._metadata(
                    request_meta, raw_id=raw_id, provider_updated_at=provider_time
                )
        except KeyError, TypeError, ValueError, OSError, OverflowError:
            raise ApiRequestError("CoinGecko: некорректные данные котировок") from None
        self.last_metadata = metadata
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Получение фиатных курсов с преобразованием направления пары."""

    source = "ExchangeRate-API"

    def fetch_rates(self) -> dict[str, float]:
        """Получить фиатные пары к базе, инвертировав курсы ответа API."""
        self.last_metadata = {}
        base = self.config.BASE_CURRENCY
        codes = set(self.config.FIAT_CURRENCIES) - {base}
        if base != "USD":
            codes.add("USD")
        if not codes:
            return {}
        if not self.config.EXCHANGERATE_API_KEY:
            raise ApiRequestError("ExchangeRate-API: задайте EXCHANGERATE_API_KEY")
        key = quote(self.config.EXCHANGERATE_API_KEY, safe="")
        url = f"{self.config.EXCHANGERATE_API_URL.rstrip('/')}/{key}/latest/{base}"
        data, request_meta = self._get_json(url)
        if data.get("result") != "success":
            reasons = {
                "invalid-key": "неверный API-ключ",
                "inactive-account": "подтвердите регистрацию аккаунта",
                "quota-reached": "превышен лимит запросов",
                "unsupported-code": "базовая валюта не поддерживается",
                "malformed-request": "некорректный запрос",
            }
            reason = reasons.get(data.get("error-type"), "API вернул ошибку")
            raise ApiRequestError(f"ExchangeRate-API: {reason}")
        rates, metadata = {}, {}
        try:
            if data["base_code"] != base:
                raise ValueError("Неверная базовая валюта ответа")
            values = data.get("conversion_rates", data.get("rates"))
            if not isinstance(values, dict):
                raise ValueError("Нет курсов в ответе")
            provider_time = None
            if "time_last_update_unix" in data:
                provider_time = self._unix_time(data["time_last_update_unix"])
            elif "time_last_update_utc" in data:
                provider_time = utc_timestamp(
                    parsedate_to_datetime(data["time_last_update_utc"])
                )
            for code in sorted(codes):
                # API возвращает BASE→code, а храним цену code→BASE.
                forward = validate_number(values[code], name="rate", positive=True)
                pair = f"{code}_{base}"
                rates[pair] = validate_number(1 / forward, name="rate", positive=True)
                metadata[pair] = self._metadata(
                    request_meta, provider_updated_at=provider_time
                )
        except KeyError, TypeError, ValueError, OSError, OverflowError:
            raise ApiRequestError(
                "ExchangeRate-API: некорректные данные котировок"
            ) from None
        self.last_metadata = metadata
        return rates
