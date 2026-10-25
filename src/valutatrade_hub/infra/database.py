"""Singleton для JSON-хранилища и блокировки операций чтение→запись."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.storage import JsonStorage
from valutatrade_hub.infra.settings import SettingsLoader


def database_transaction(method):
    """Удерживать блокировку менеджера до завершения сценария."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._storage.transaction():
            return method(self, *args, **kwargs)

    return wrapped


class DatabaseManager:
    """__new__ делает создание единственного экземпляра явным и читаемым."""

    _instance = None
    _instance_lock = RLock()

    def __new__(cls, data_dir: str | Path | None = None):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, data_dir: str | Path | None = None) -> None:
        with self._instance_lock:
            if self._initialized:
                if data_dir is not None and Path(data_dir).resolve() != self.data_dir:
                    raise StorageError("DatabaseManager уже использует другой каталог")
                return
            settings = SettingsLoader()
            directory = settings.get("data_dir") if data_dir is None else Path(data_dir)
            filenames = {
                "users.json": settings.get("users_file"),
                "portfolios.json": settings.get("portfolios_file"),
                "rates.json": settings.get("rates_file"),
            }
            self._lock = RLock()
            self._storage = JsonStorage(Path(directory).resolve(), filenames=filenames)
            self._initialized = True

    @property
    def data_dir(self) -> Path:
        return self._storage.data_dir

    @contextmanager
    def transaction(self) -> Iterator[DatabaseManager]:
        """Сериализовать связанные операции в пределах одного процесса."""
        with self._lock:
            yield self

    def load_users(self) -> list[User]:
        with self._lock:
            return self._storage.load_users()

    def register_user(self, user: User) -> None:
        with self._lock:
            self._storage.register_user(user)

    def load_portfolio_data(self) -> list[dict]:
        with self._lock:
            return self._storage.load_portfolio_data()

    def load_portfolio(self, user: User) -> Portfolio:
        with self._lock:
            return self._storage.load_portfolio(user)

    def save_portfolio(self, portfolio: Portfolio) -> None:
        with self._lock:
            self._storage.save_portfolio(portfolio)

    def load_rates(self) -> dict:
        with self._lock:
            return self._storage.load_rates()

    def save_rates(self, rates: dict) -> None:
        with self._lock:
            self._storage.save_rates(rates)
