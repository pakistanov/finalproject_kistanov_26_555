"""История измерений и атомарное обновление последнего среза курсов."""

from dataclasses import dataclass

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.utils import (
    atomic_write_json,
    extract_rate_pairs,
    normalize_currency,
    parse_timestamp,
    read_json,
    utc_timestamp,
    validate_number,
)
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.config import ParserConfig


@dataclass(frozen=True)
class SaveResult:
    """Количество изменённых пар и новых измерений после сохранения."""

    updated_count: int
    history_added: int
    last_refresh: str | None


class ParserStorage:
    """Атомарная запись истории измерений и последнего снимка курсов."""

    def __init__(
        self, config: ParserConfig, database: DatabaseManager | None = None
    ) -> None:
        """Подключить пути снимка и истории к блокировке хранилища."""
        self.config = config
        self._database = database if database is not None else DatabaseManager()

    @staticmethod
    def _record(record: dict) -> dict:
        try:
            left = normalize_currency(record["from_currency"])
            right = normalize_currency(record["to_currency"])
            if left == right:
                raise ValueError("Нельзя сохранять пару одинаковых валют")
            timestamp = utc_timestamp(parse_timestamp(record["timestamp"]))
            identifier = f"{left}_{right}_{timestamp}"
            if record.get("id", identifier) != identifier:
                raise ValueError("Идентификатор не соответствует паре и времени")
            source = record["source"]
            if not isinstance(source, str) or not source.strip():
                raise ValueError("Не задан источник")
            meta = record.get("meta", {})
            if not isinstance(meta, dict):
                raise ValueError("Некорректные метаданные")
            if "status_code" in meta and meta["status_code"] != 200:
                raise ValueError("Ответ API не был успешным")
            if "request_ms" in meta:
                validate_number(meta["request_ms"], name="request_ms")
            return {
                "id": identifier,
                "from_currency": left,
                "to_currency": right,
                "rate": validate_number(record["rate"], name="rate", positive=True),
                "timestamp": timestamp,
                "source": source,
                "meta": meta.copy(),
            }
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise StorageError("Некорректное измерение курса") from exc

    def save(self, records: list[dict]) -> SaveResult:
        """Добавить уникальные замеры; в кэше побеждает только более свежий."""
        incoming = [self._record(record) for record in records]
        with self._database.transaction():
            old_history = read_json(self.config.HISTORY_FILE_PATH, list, default=[])
            history = {}
            for record in old_history:
                normalized = self._record(record)
                history.setdefault(normalized["id"], normalized)
            before_count = len(history)
            canonical = [
                history.setdefault(record["id"], record) for record in incoming
            ]
            cache = read_json(
                self.config.RATES_FILE_PATH,
                dict,
                default={"pairs": {}, "last_refresh": None},
            )
            pairs = extract_rate_pairs(cache)
            updated_pairs = set()
            for record in canonical:
                pair = f"{record['from_currency']}_{record['to_currency']}"
                existing = pairs.get(pair)
                if existing is not None:
                    try:
                        old_time = parse_timestamp(existing["updated_at"])
                        validate_number(existing["rate"], name="rate", positive=True)
                    except (KeyError, TypeError, ValueError) as exc:
                        raise StorageError(f"Некорректный курс {pair} в кэше") from exc
                    if parse_timestamp(record["timestamp"]) <= old_time:
                        continue
                pairs[pair] = {
                    "rate": record["rate"],
                    "updated_at": record["timestamp"],
                    "source": record["source"],
                }
                updated_pairs.add(pair)
            last_refresh = (
                utc_timestamp() if updated_pairs else cache.get("last_refresh")
            )
            new_history = list(history.values())
            history_changed = new_history != old_history
            if history_changed:
                atomic_write_json(self.config.HISTORY_FILE_PATH, new_history)
            if updated_pairs:
                try:
                    atomic_write_json(
                        self.config.RATES_FILE_PATH,
                        {"pairs": pairs, "last_refresh": last_refresh},
                    )
                except StorageError:
                    if history_changed:
                        atomic_write_json(self.config.HISTORY_FILE_PATH, old_history)
                    raise
            return SaveResult(
                len(updated_pairs), len(history) - before_count, last_refresh
            )
