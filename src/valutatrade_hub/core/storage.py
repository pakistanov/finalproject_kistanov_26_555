"""JSON-хранилище с атомарной заменой отдельных файлов."""

import json
import os
import tempfile
from pathlib import Path

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import validate_user_id


class JsonStorage:
    """Локальное хранилище для одного запущенного экземпляра приложения."""

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for filename, default in (
                ("users.json", []),
                ("portfolios.json", []),
                ("rates.json", {"source": "DemoStub", "last_refresh": None}),
            ):
                if not (self.data_dir / filename).exists():
                    self._write(filename, default)
        except OSError as exc:
            raise StorageError("Не удалось создать каталог данных") from exc

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise ValueError(f"Недопустимая JSON-константа: {value}")

    def _read(self, filename: str, expected_type: type) -> list | dict:
        path = self.data_dir / filename
        try:
            with path.open(encoding="utf-8") as source:
                data = json.load(source, parse_constant=self._reject_constant)
        except (OSError, UnicodeError, ValueError) as exc:
            raise StorageError(f"Не удалось прочитать {filename}") from exc
        if not isinstance(data, expected_type):
            raise StorageError(f"Некорректная структура {filename}")
        return data

    def _write(self, filename: str, data: list | dict) -> None:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.data_dir,
                prefix=f".{filename}.",
                suffix=".tmp",
                delete=False,
            ) as target:
                temporary_path = Path(target.name)
                json.dump(data, target, ensure_ascii=False, indent=2, allow_nan=False)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary_path, self.data_dir / filename)
        except (OSError, TypeError, ValueError) as exc:
            raise StorageError(f"Не удалось сохранить {filename}") from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

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
        return self._read("rates.json", dict)

    def save_rates(self, rates: dict) -> None:
        self._write("rates.json", rates)
