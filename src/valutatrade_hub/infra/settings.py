"""Кэшируемая конфигурация из секции [tool.valutatrade]."""

import os
import tomllib
from pathlib import Path
from threading import RLock
from typing import Any

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.utils import validate_number

DEFAULT_SETTINGS = {
    "data_dir": "data",
    "users_file": "users.json",
    "portfolios_file": "portfolios.json",
    "rates_file": "rates.json",
    "rates_ttl_seconds": 300,
    "default_base_currency": "USD",
    "log_dir": "logs",
    "log_file": "actions.log",
    "log_format": "json",
    "log_level": "INFO",
    "log_max_bytes": 1048576,
    "log_backup_count": 3,
    "log_verbose": False,
}


class SettingsLoader:
    """Один экземпляр; __new__ выбран для явной и читаемой реализации."""

    _instance = None
    _instance_lock = RLock()

    def __new__(cls, config_path: str | Path | None = None):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_path: str | Path | None = None) -> None:
        with self._instance_lock:
            path = Path(config_path or Path.cwd() / "pyproject.toml").resolve()
            if self._initialized:
                if config_path is not None and path != self._config_path:
                    raise ValueError("SettingsLoader уже использует другой файл")
                return
            self._config_path = path
            self._explicit_path = config_path is not None
            self._values: dict[str, Any] = {}
            self.reload()
            self._initialized = True

    def get(self, key: str, default: Any = None) -> Any:
        with self._instance_lock:
            return self._values.get(key, default)

    def reload(self) -> None:
        """Перечитать файл; при ошибке сохранить предыдущую конфигурацию."""
        with self._instance_lock:
            configured = {}
            try:
                if self._config_path.exists() or self._explicit_path:
                    with self._config_path.open("rb") as source:
                        configured = (
                            tomllib.load(source).get("tool", {}).get("valutatrade", {})
                        )
            except (OSError, ValueError, AttributeError) as exc:
                raise ValueError("Не удалось загрузить конфигурацию проекта") from exc
            if not isinstance(configured, dict):
                raise ValueError("Секция tool.valutatrade должна быть таблицей")
            values = DEFAULT_SETTINGS | configured
            for key, environment in (
                ("data_dir", "VALUTATRADE_DATA_DIR"),
                ("log_dir", "VALUTATRADE_LOG_DIR"),
            ):
                values[key] = os.environ.get(environment, values[key])
            self._validate(values)
            self._values = values

    def _validate(self, values: dict) -> None:
        values["rates_ttl_seconds"] = validate_number(
            values["rates_ttl_seconds"], name="rates_ttl_seconds", positive=True
        )
        values["default_base_currency"] = get_currency(
            values["default_base_currency"]
        ).code
        for key in ("data_dir", "log_dir"):
            if not isinstance(values[key], str) or not values[key].strip():
                raise ValueError(f"'{key}' должен содержать путь к каталогу")
            path = Path(values[key]).expanduser()
            if not path.is_absolute():
                path = self._config_path.parent / path
            values[key] = path.resolve()
        for key in ("users_file", "portfolios_file", "rates_file", "log_file"):
            filename = values[key]
            if (
                not isinstance(filename, str)
                or not filename.strip()
                or Path(filename).name != filename
                or filename in (".", "..")
            ):
                raise ValueError(f"'{key}' должен содержать только имя файла")
        filenames = {
            values[key].casefold()
            for key in ("users_file", "portfolios_file", "rates_file")
        }
        if len(filenames) != 3:
            raise ValueError("Имена JSON-файлов должны различаться")
        if (
            str(values["log_dir"]).casefold() == str(values["data_dir"]).casefold()
            and values["log_file"].casefold() in filenames
        ):
            raise ValueError("Журнал операций не должен совпадать с JSON-хранилищем")
        for key in ("log_max_bytes", "log_backup_count"):
            if isinstance(values[key], bool) or not isinstance(values[key], int):
                raise ValueError(f"'{key}' должен быть положительным целым числом")
            if values[key] <= 0:
                raise ValueError(f"'{key}' должен быть положительным целым числом")
        level = values["log_level"]
        if not isinstance(level, str) or level.upper() not in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }:
            raise ValueError("Некорректный уровень логирования")
        values["log_level"] = level.upper()
        if values["log_format"] != "json":
            raise ValueError("Поддерживается формат логов 'json'")
        if not isinstance(values["log_verbose"], bool):
            raise ValueError("'log_verbose' должен быть логическим значением")
