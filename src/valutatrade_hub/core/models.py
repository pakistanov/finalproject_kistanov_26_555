"""Пользователь, отдельный кошелёк и валютный портфель."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import (
    DEFAULT_EXCHANGE_RATES,
    normalize_currency,
    parse_timestamp,
    validate_number,
    validate_password,
    validate_user_id,
    validate_username,
)


class User:
    """Пользователь с односторонним хешем пароля и индивидуальной солью."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        self._user_id = validate_user_id(user_id)
        self.username = username
        if not isinstance(hashed_password, str) or not hashed_password:
            raise ValueError("Хеш пароля не может быть пустым")
        if not isinstance(salt, str) or not salt:
            raise ValueError("Соль не может быть пустой")
        if not isinstance(registration_date, datetime):
            raise ValueError("Дата регистрации должна иметь тип datetime")
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> User:
        """Создать пользователя с новой случайной солью."""
        validate_password(password)
        salt = secrets.token_hex(16)
        return cls(
            user_id,
            username,
            cls._hash_password(password, salt),
            salt,
            datetime.now(UTC),
        )

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        self._username = validate_username(value)

    @property
    def hashed_password(self) -> str:
        return self._hashed_password

    @property
    def salt(self) -> str:
        return self._salt

    @property
    def registration_date(self) -> datetime:
        return self._registration_date

    def get_user_info(self) -> dict:
        """Вернуть публичные данные без хеша пароля и соли."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "registration_date": self.registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Сменить пароль, обновив соль и хеш после успешной проверки."""
        validate_password(new_password)
        self._salt = secrets.token_hex(16)
        self._hashed_password = self._hash_password(new_password, self._salt)

    def verify_password(self, password: str) -> bool:
        """Сравнить хеши, не сохраняя открытый пароль в объекте."""
        if not isinstance(password, str):
            return False
        candidate = self._hash_password(password, self.salt)
        return hmac.compare_digest(candidate.encode(), self.hashed_password.encode())

    def to_dict(self) -> dict:
        """Сериализация для хранилища; не предназначена для показа в CLI."""
        return {
            **self.get_user_info(),
            "hashed_password": self.hashed_password,
            "salt": self.salt,
        }

    @classmethod
    def from_dict(cls, data: dict) -> User:
        return cls(
            data["user_id"],
            data["username"],
            data["hashed_password"],
            data["salt"],
            parse_timestamp(data["registration_date"]),
        )


class Wallet:
    """Кошелёк одной валюты с неотрицательным конечным балансом."""

    def __init__(self, currency_code: str, balance: float = 0.0) -> None:
        self._currency_code = normalize_currency(currency_code)
        self.balance = balance

    @property
    def currency_code(self) -> str:
        return self._currency_code

    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        self._balance = validate_number(value, name="balance")

    def deposit(self, amount: float) -> None:
        """Пополнить баланс на положительную сумму."""
        amount = validate_number(amount, name="amount", positive=True)
        new_balance = validate_number(self.balance + amount, name="balance")
        if new_balance == self.balance:
            raise ValueError("Сумма слишком мала для изменения баланса")
        self.balance = new_balance

    def withdraw(self, amount: float) -> None:
        """Списать сумму, если средств достаточно."""
        amount = validate_number(amount, name="amount", positive=True)
        if amount > self.balance:
            raise InsufficientFundsError(
                f"Недостаточно средств: доступно {self.balance:.8f} "
                f"{self.currency_code}, требуется {amount:.8f} {self.currency_code}"
            )
        if self.balance - amount == self.balance:
            raise ValueError("Сумма слишком мала для изменения баланса")
        self.balance -= amount

    def get_balance_info(self) -> dict:
        return {"currency_code": self.currency_code, "balance": self.balance}


class Portfolio:
    """Все кошельки пользователя; обменные курсы выражаются в USD."""

    def __init__(
        self,
        user_id: int,
        wallets: dict[str, Wallet] | None = None,
        *,
        user: User,
    ) -> None:
        self._user_id = validate_user_id(user_id)
        if not isinstance(user, User) or user.user_id != user_id:
            raise ValueError("Пользователь не соответствует владельцу портфеля")
        self._user = user
        if wallets is not None and not isinstance(wallets, dict):
            raise ValueError("Кошельки должны быть словарём")
        self._wallets: dict[str, Wallet] = {}
        for code, wallet in (wallets or {}).items():
            code = normalize_currency(code)
            if not isinstance(wallet, Wallet) or wallet.currency_code != code:
                raise ValueError("Код валюты не соответствует кошельку")
            if code in self._wallets:
                raise ValueError(f"Кошелёк '{code}' уже существует")
            self._wallets[code] = wallet

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def user(self) -> User:
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Копия словаря; сами кошельки сохраняют свои методы изменения."""
        return self._wallets.copy()

    def add_currency(self, currency_code: str) -> Wallet:
        code = normalize_currency(currency_code)
        if code in self._wallets:
            raise ValueError(f"Кошелёк '{code}' уже существует")
        wallet = Wallet(code)
        self._wallets[code] = wallet
        return wallet

    def get_wallet(self, currency_code: str) -> Wallet:
        code = normalize_currency(currency_code)
        if code not in self._wallets:
            raise ValueError(
                f"У вас нет кошелька '{code}'. "
                "Он создаётся автоматически при первой покупке."
            )
        return self._wallets[code]

    def get_total_value(
        self,
        base_currency: str = "USD",
        exchange_rates: dict[str, float] | None = None,
    ) -> float:
        """Оценить портфель, используя цены одной единицы валюты в USD."""
        base = normalize_currency(base_currency)
        rates = DEFAULT_EXCHANGE_RATES if exchange_rates is None else exchange_rates
        if base not in rates:
            raise ValueError(f"Неизвестная базовая валюта '{base}'")
        base_rate = validate_number(rates[base], name="rate", positive=True)
        values = []
        for code, wallet in self._wallets.items():
            if wallet.balance == 0:
                continue
            if code not in rates:
                raise ValueError(f"Не удалось получить курс для {code}→{base}")
            rate = validate_number(rates[code], name="rate", positive=True)
            values.append(wallet.balance * (rate / base_rate))
        return validate_number(sum(values), name="total_value")

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "wallets": {
                code: wallet.get_balance_info()
                for code, wallet in self._wallets.items()
            },
        }
