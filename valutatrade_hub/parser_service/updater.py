"""Опрос источников, журналирование и сохранение результатов обновления."""

import logging
from dataclasses import dataclass

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import ApiRequestError, StorageError
from valutatrade_hub.core.utils import parse_timestamp, utc_timestamp, validate_number
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import ParserStorage


@dataclass(frozen=True)
class UpdateResult:
    """Итог обновления: счётчики, время снимка и ошибки источников."""

    updated_count: int
    history_added: int
    last_refresh: str | None
    errors: dict[str, str]


class RatesUpdater:
    """Координация клиентов API, объединения курсов и их сохранения."""

    def __init__(
        self,
        clients: list[BaseApiClient],
        storage: ParserStorage,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        """Сохранить клиентов, хранилище и независимый логгер парсера."""
        self.clients = clients
        self.storage = storage
        self.logger = (
            logger
            if logger is not None
            else configure_logging(
                name="valutatrade.parser", file_path=storage.config.PARSER_LOG_FILE_PATH
            )
        )

    def _log(
        self,
        action: str,
        *,
        level: int = logging.INFO,
        exc_info: bool = False,
        **fields,
    ) -> None:
        self.logger.log(
            level,
            "parser",
            extra={"action_data": {"action": action, **fields}},
            exc_info=exc_info,
        )

    def run_update(self) -> UpdateResult:
        """Опросить источники и сохранить успешные результаты и список ошибок."""
        self._log("UPDATE_START", sources=[client.source for client in self.clients])
        records, errors = [], {}
        for client in self.clients:
            self._log("FETCH_START", source=client.source)
            try:
                rates = client.fetch_rates()
                if not isinstance(rates, dict):
                    raise ApiRequestError(
                        f"{client.source}: некорректный формат результата"
                    )
                source_records = []
                received_at = utc_timestamp()
                for pair, rate in rates.items():
                    left, right = pair.split("_")
                    left, right = get_currency(left).code, get_currency(right).code
                    if left == right:
                        raise ValueError("Пара одинаковых валют")
                    metadata = client.last_metadata.get(pair, {})
                    timestamp = utc_timestamp(
                        parse_timestamp(metadata.get("timestamp", received_at))
                    )
                    source_records.append(
                        {
                            "id": f"{left}_{right}_{timestamp}",
                            "from_currency": left,
                            "to_currency": right,
                            "rate": validate_number(rate, name="rate", positive=True),
                            "timestamp": timestamp,
                            "source": client.source,
                            "meta": metadata.get("meta", {}).copy(),
                        }
                    )
            except (ApiRequestError, ValueError, TypeError, AttributeError) as exc:
                message = (
                    exc.reason
                    if isinstance(exc, ApiRequestError)
                    else f"{client.source}: некорректные котировки"
                )
                errors[client.source] = message
                self._log(
                    "FETCH_ERROR",
                    level=logging.ERROR,
                    source=client.source,
                    result="ERROR",
                    error_type=type(exc).__name__,
                    error_message=message,
                    exc_info=True,
                )
                continue
            records.extend(source_records)
            self._log(
                "FETCH_DETAILS",
                level=logging.DEBUG,
                source=client.source,
                requests=[
                    {
                        "pair": pair,
                        "request_ms": metadata.get("meta", {}).get("request_ms"),
                        "status_code": metadata.get("meta", {}).get("status_code"),
                    }
                    for pair, metadata in client.last_metadata.items()
                ],
            )
            self._log(
                "FETCH_FINISH",
                source=client.source,
                result="OK",
                count=len(source_records),
            )
        if not records:
            reason = "; ".join(errors.values()) or "источники не вернули курсы"
            self._log("UPDATE_FINISH", level=logging.ERROR, result="ERROR", count=0)
            raise ApiRequestError(reason)
        try:
            self._log("WRITE_START", count=len(records))
            saved = self.storage.save(records)
        except StorageError as exc:
            self._log(
                "UPDATE_FINISH",
                level=logging.ERROR,
                result="ERROR",
                error_message=str(exc),
            )
            raise
        self._log(
            "UPDATE_FINISH",
            result="PARTIAL" if errors else "OK",
            count=saved.updated_count,
            history_added=saved.history_added,
            last_refresh=saved.last_refresh,
        )
        return UpdateResult(
            saved.updated_count, saved.history_added, saved.last_refresh, errors
        )


def create_updater(
    source: str | None = None, database: DatabaseManager | None = None
) -> RatesUpdater:
    """Собрать парсер для всех API либо одного выбранного источника."""
    config = ParserConfig.from_settings(database)
    factories = {"coingecko": CoinGeckoClient, "exchangerate": ExchangeRateApiClient}
    selected = factories if source is None else {source: factories.get(source)}
    if any(factory is None for factory in selected.values()):
        raise ValueError("Источник должен быть coingecko или exchangerate")
    clients = [factory(config) for factory in selected.values()]
    return RatesUpdater(clients, ParserStorage(config, database))
