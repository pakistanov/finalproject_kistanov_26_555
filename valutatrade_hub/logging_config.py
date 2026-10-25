"""JSON-журнал операций с ограничением размера и ротацией файлов."""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock
from typing import TextIO

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.infra.settings import SettingsLoader

LOGGER_NAME = "valutatrade.actions"
PARSER_LOGGER_NAME = "valutatrade.parser"
_configuration_lock = RLock()


class ActionJsonFormatter(logging.Formatter):
    """Форматировать одну запись JSON с UTC-временем и контекстом операции."""

    def format(self, record: logging.LogRecord) -> str:
        """Сериализовать поля события и безопасный traceback при его наличии."""
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            **getattr(record, "action_data", {"message": record.getMessage()}),
        }
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)


class ParserConsoleFormatter(logging.Formatter):
    """Краткие сообщения о шагах обновления для пользовательской консоли."""

    def format(self, record: logging.LogRecord) -> str:
        """Преобразовать структурированное событие парсера в одну строку."""
        event = getattr(record, "action_data", {})
        action = event.get("action")
        source = event.get("source", "API")
        match action:
            case "UPDATE_START":
                message = "Начато обновление курсов"
            case "FETCH_START":
                message = f"Запрос к {source}"
            case "FETCH_FINISH":
                message = f"{source}: получено курсов — {event.get('count', 0)}"
            case "FETCH_ERROR":
                message = event.get("error_message", f"{source}: ошибка")
            case "WRITE_START":
                message = f"Сохранение курсов: {event.get('count', 0)}"
            case "UPDATE_FINISH":
                message = (
                    f"Обновление: {event.get('result')}, "
                    f"записано {event.get('count', 0)}"
                )
            case _:
                message = event.get("error_message", record.getMessage())
        return f"{record.levelname}: {message}"


@contextmanager
def parser_console_logging(output: TextIO | None = None) -> Iterator[logging.Logger]:
    """Подключить INFO-консоль только на время явной команды update-rates."""
    logger = logging.getLogger(PARSER_LOGGER_NAME)
    handler = logging.StreamHandler(output if output is not None else sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(ParserConsoleFormatter())
    logger.addHandler(handler)
    try:
        yield logger
    finally:
        logger.removeHandler(handler)
        handler.close()


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
        level = (
            logging.DEBUG if name == PARSER_LOGGER_NAME else settings.get("log_level")
        )
        logger.setLevel(level)
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
        matching_handler.setLevel(level)
        return logger
