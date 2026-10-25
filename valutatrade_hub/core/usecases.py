"""Сценарии приложения: сессия, регистрация, портфель и сделки."""

from dataclasses import dataclass

from valutatrade_hub.core.currencies import Currency, get_currency, get_supported_codes
from valutatrade_hub.core.exceptions import (
    AuthenticationError,
    InsufficientFundsError,
)
from valutatrade_hub.core.models import User
from valutatrade_hub.core.rates import RateQuote, RateService
from valutatrade_hub.core.utils import (
    validate_number,
    validate_password,
    validate_username,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager, database_transaction
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging


@dataclass(frozen=True)
class WalletValuation:
    currency_code: str
    balance: float
    value: float


@dataclass(frozen=True)
class PortfolioView:
    username: str
    base_currency: str
    wallets: tuple[WalletValuation, ...]
    total_value: float


@dataclass(frozen=True)
class TradeResult:
    side: str
    currency_code: str
    amount: float
    quote: RateQuote
    usd_value: float
    previous_balance: float
    balance: float
    previous_usd_balance: float
    usd_balance: float


class TradingService:
    """Бизнес-логика не зависит от ввода, печати и аргументов CLI."""

    def __init__(
        self, storage: DatabaseManager | None = None, rates: RateService | None = None
    ) -> None:
        self._settings = SettingsLoader()
        self._storage = storage if storage is not None else DatabaseManager()
        self._logger = configure_logging(self._settings)
        self._rates = rates if rates is not None else RateService(self._storage)
        self._current_user: User | None = None

    @property
    def current_user(self) -> User | None:
        return self._current_user

    def _require_user(self) -> User:
        if self._current_user is None:
            raise AuthenticationError("Сначала выполните login")
        return self._current_user

    @database_transaction
    def register(self, username: str, password: str) -> User:
        username = validate_username(username)
        validate_password(password)
        users = self._storage.load_users()
        if any(user.username == username for user in users):
            raise ValueError(f"Имя пользователя '{username}' уже занято")
        user_id = max((user.user_id for user in users), default=0) + 1
        user = User.create(user_id, username, password)
        self._storage.register_user(user)
        return user

    def login(self, username: str, password: str) -> User:
        self._current_user = None
        username = validate_username(username)
        user = next(
            (user for user in self._storage.load_users() if user.username == username),
            None,
        )
        if user is None:
            raise AuthenticationError(f"Пользователь '{username}' не найден")
        if not user.verify_password(password):
            raise AuthenticationError("Неверный пароль")
        self._current_user = user
        return user

    def logout(self) -> None:
        self._current_user = None

    def list_currencies(self) -> tuple[Currency, ...]:
        return tuple(get_currency(code) for code in get_supported_codes())

    @log_action("GET_RATE")
    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        return self._rates.get_rate(from_currency, to_currency)

    @database_transaction
    def show_portfolio(self, base_currency: str | None = None) -> PortfolioView:
        user = self._require_user()
        base = get_currency(
            self._settings.get("default_base_currency")
            if base_currency is None
            else base_currency
        ).code
        base_quote = self.get_rate(base, "USD")
        portfolio = self._storage.load_portfolio(user)
        usd_rates = {"USD": 1.0, base: base_quote.rate}
        wallets = portfolio.wallets
        for code, wallet in wallets.items():
            if wallet.balance > 0 and code not in usd_rates:
                usd_rates[code] = self.get_rate(code, "USD").rate
        total = portfolio.get_total_value(base, exchange_rates=usd_rates)
        rows = tuple(
            WalletValuation(
                code,
                wallet.balance,
                wallet.balance * (usd_rates.get(code, 0.0) / base_quote.rate),
            )
            for code, wallet in sorted(wallets.items())
        )
        return PortfolioView(user.username, base, rows, total)

    @database_transaction
    def deposit(self, currency_code: str, amount: float) -> float:
        """Выдать виртуальные USD для симуляции; реальные платежи не выполняются."""
        user = self._require_user()
        code = get_currency(currency_code).code
        amount = validate_number(amount, name="amount", positive=True)
        if code != "USD":
            raise ValueError("Виртуальное пополнение доступно только для USD")
        portfolio = self._storage.load_portfolio(user)
        wallet = (
            portfolio.get_wallet(code)
            if code in portfolio.wallets
            else portfolio.add_currency(code)
        )
        wallet.deposit(amount)
        self._storage.save_portfolio(portfolio)
        return wallet.balance

    @log_action("BUY")
    @database_transaction
    def buy(self, currency_code: str, amount: float) -> TradeResult:
        user = self._require_user()
        code, amount = self._validate_trade(currency_code, amount)
        portfolio = self._storage.load_portfolio(user)
        quote = self.get_rate(code, "USD")
        cost = validate_number(amount * quote.rate, name="usd_value", positive=True)
        if "USD" not in portfolio.wallets:
            raise InsufficientFundsError(0, cost, "USD")
        cash = portfolio.get_wallet("USD")
        previous_usd = cash.balance
        cash.withdraw(cost)
        target = (
            portfolio.get_wallet(code)
            if code in portfolio.wallets
            else portfolio.add_currency(code)
        )
        previous_balance = target.balance
        target.deposit(amount)
        self._storage.save_portfolio(portfolio)
        return TradeResult(
            "buy",
            code,
            amount,
            quote,
            cost,
            previous_balance,
            target.balance,
            previous_usd,
            cash.balance,
        )

    @log_action("SELL")
    @database_transaction
    def sell(self, currency_code: str, amount: float) -> TradeResult:
        user = self._require_user()
        code, amount = self._validate_trade(currency_code, amount)
        portfolio = self._storage.load_portfolio(user)
        if code not in portfolio.wallets:
            raise InsufficientFundsError(0, amount, code)
        target = portfolio.get_wallet(code)
        previous_balance = target.balance
        target.withdraw(amount)
        quote = self.get_rate(code, "USD")
        proceeds = validate_number(amount * quote.rate, name="usd_value", positive=True)
        cash = (
            portfolio.get_wallet("USD")
            if "USD" in portfolio.wallets
            else portfolio.add_currency("USD")
        )
        previous_usd = cash.balance
        cash.deposit(proceeds)
        self._storage.save_portfolio(portfolio)
        return TradeResult(
            "sell",
            code,
            amount,
            quote,
            proceeds,
            previous_balance,
            target.balance,
            previous_usd,
            cash.balance,
        )

    @staticmethod
    def _validate_trade(currency_code: str, amount: float) -> tuple[str, float]:
        code = get_currency(currency_code).code
        amount = validate_number(amount, name="amount", positive=True)
        if code == "USD":
            raise ValueError(
                "USD — расчётная валюта. Для пополнения используйте deposit; "
                "для обмена укажите другую валюту."
            )
        return code, amount
