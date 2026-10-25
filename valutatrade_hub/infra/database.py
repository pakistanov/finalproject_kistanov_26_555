"""Singleton для JSON-хранилища и блокировки операций чтение→запись."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import atomic_write_json, read_json, validate_user_id
from valutatrade_hub.infra.settings import SettingsLoader


class JsonStorage:
    """Локальное хранилище для одного запущенного экземпляра приложения."""

    def __init__(
        self, data_dir: str | Path = "data", *, filenames: dict[str, str] | None = None
    ) -> None:
        self.data_dir = Path(data_dir)
        self._filenames = filenames or {}
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for filename, default in (
                ("users.json", []),
                ("portfolios.json", []),
            ):
                if not self._path(filename).exists():
                    self._write(filename, default)
        except OSError as exc:
            raise StorageError("Не удалось создать каталог данных") from exc

    def _path(self, filename: str) -> Path:
        return self.data_dir / self._filenames.get(filename, filename)

    def _read(self, filename: str, expected_type: type) -> list | dict:
        return read_json(self._path(filename), expected_type)

    def _write(self, filename: str, data: list | dict) -> None:
        atomic_write_json(self._path(filename), data)

    def load_users(self) -> list[User]:
        data = self._read("users.json", list)
        try:
            users = [User.from_dict(item) for item in data]
            if len({user.user_id for user in users}) != len(users):
                raise ValueError("Повторяющиеся идентификаторы")
            if len({user.username for user in users}) != len(users):
                raise ValueError("Повторяющиеся имена")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise StorageError("Некорректные данные в users.json") from exc
        return users

    def load_portfolio_data(self) -> list[dict]:
        data = self._read("portfolios.json", list)
        try:
            identifiers = set()
            for item in data:
                user_id = validate_user_id(item["user_id"])
                if user_id in identifiers or not isinstance(item["wallets"], dict):
                    raise ValueError("Некорректный портфель")
                identifiers.add(user_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError("Некорректные данные в portfolios.json") from exc
        return data

    def register_user(self, user: User) -> None:
        """Сохранить пользователя и пустой портфель, откатив обычный сбой записи."""
        users = self.load_users()
        portfolios = self.load_portfolio_data()
        if any(
            existing.user_id == user.user_id or existing.username == user.username
            for existing in users
        ):
            raise ValueError(f"Имя пользователя '{user.username}' уже занято")
        if any(item["user_id"] == user.user_id for item in portfolios):
            raise StorageError("Новый user_id уже используется в portfolios.json")
        self._write(
            "portfolios.json", [*portfolios, {"user_id": user.user_id, "wallets": {}}]
        )
        try:
            self._write(
                "users.json", [*(item.to_dict() for item in users), user.to_dict()]
            )
        except StorageError:
            self._write("portfolios.json", portfolios)
            raise

    def load_portfolio(self, user: User) -> Portfolio:
        data = self.load_portfolio_data()
        item = next((item for item in data if item["user_id"] == user.user_id), None)
        if item is None:
            raise StorageError("Портфель пользователя не найден в portfolios.json")
        try:
            wallets = {}
            for code, values in item["wallets"].items():
                if "currency_code" in values and values["currency_code"] != code:
                    raise ValueError("Код валюты не соответствует кошельку")
                wallets[code] = Wallet(code, values["balance"])
            return Portfolio(user.user_id, wallets, user=user)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError("Некорректные кошельки в portfolios.json") from exc

    def save_portfolio(self, portfolio: Portfolio) -> None:
        data = self.load_portfolio_data()
        for index, item in enumerate(data):
            if item["user_id"] == portfolio.user_id:
                data[index] = portfolio.to_dict()
                self._write("portfolios.json", data)
                return
        raise StorageError("Портфель пользователя не найден в portfolios.json")

    def load_rates(self) -> dict:
        return read_json(
            self._path("rates.json"), dict, default={"pairs": {}, "last_refresh": None}
        )

    def save_rates(self, rates: dict) -> None:
        self._write("rates.json", rates)


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
