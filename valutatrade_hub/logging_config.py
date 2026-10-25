"""JSON-журнал операций с ограничением размера и ротацией файлов."""

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.infra.settings import SettingsLoader

LOGGER_NAME = "valutatrade.actions"
_configuration_lock = RLock()


class ActionJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            **getattr(record, "action_data", {"message": record.getMessage()}),
        }
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def configure_logging(
    settings: SettingsLoader | None = None,
    *,
    name: str = LOGGER_NAME,
    file_path: Path | None = None,
) -> logging.Logger:
    """Повторная настройка не добавляет дублирующиеся обработчики."""
    settings = settings if settings is not None else SettingsLoader()
    path = file_path or settings.get("log_dir") / settings.get("log_file")
    path = path.resolve()
    with _configuration_lock:
        logger = logging.getLogger(name)
        logger.setLevel(settings.get("log_level"))
        logger.propagate = False
        matching_handler = None
        for handler in logger.handlers[:]:
            if isinstance(handler, RotatingFileHandler):
                if handler.baseFilename == str(path):
                    matching_handler = handler
                else:
                    logger.removeHandler(handler)
                    handler.close()
        if matching_handler is None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                matching_handler = RotatingFileHandler(
                    path,
                    maxBytes=settings.get("log_max_bytes"),
                    backupCount=settings.get("log_backup_count"),
                    encoding="utf-8",
                )
            except OSError as exc:
                raise StorageError("Не удалось открыть журнал операций") from exc
            logger.addHandler(matching_handler)
        matching_handler.maxBytes = settings.get("log_max_bytes")
        matching_handler.backupCount = settings.get("log_backup_count")
        matching_handler.setFormatter(ActionJsonFormatter())
        return logger
