"""Сценарии работы с пользователями, портфелями и локальным кэшем."""

from dataclasses import dataclass

from valutatrade_hub.core.currencies import Currency, get_currency, get_supported_codes
from valutatrade_hub.core.exceptions import AuthenticationError, InsufficientFundsError
from valutatrade_hub.core.models import User
from valutatrade_hub.core.utils import (
    CachedRatesView,
    RateQuote,
    RateService,
    database_transaction,
    validate_number,
    validate_password,
    validate_user_id,
    validate_username,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging


@dataclass(frozen=True)
class WalletValuation:
    """Баланс валюты и его стоимость в выбранной базе."""

    currency_code: str
    balance: float
    value: float


@dataclass(frozen=True)
class PortfolioView:
    """Данные для таблицы портфеля и его итоговой стоимости."""

    username: str
    base_currency: str
    wallets: tuple[WalletValuation, ...]
    total_value: float


@dataclass(frozen=True)
class TradeResult:
    """Изменение одного кошелька и оценка операции в USD."""

    side: str
    currency_code: str
    amount: float
    quote: RateQuote
    usd_value: float
    previous_balance: float
    balance: float


class TradingService:
    """Бизнес-сценарии без сессии: вызывающий код явно передаёт user_id."""

    def __init__(
        self, storage: DatabaseManager | None = None, rates: RateService | None = None
    ) -> None:
        self._settings = SettingsLoader()
        self._storage = storage if storage is not None else DatabaseManager()
        self._logger = configure_logging(self._settings)
        self._rates = rates if rates is not None else RateService(self._storage)

    def get_user(self, user_id: int) -> User:
        """Загрузить пользователя по идентификатору или сообщить об отсутствии."""
        user_id = validate_user_id(user_id)
        for user in self._storage.load_users():
            if user.user_id == user_id:
                return user
        raise AuthenticationError(f"Пользователь с id={user_id} не найден")

    @database_transaction
    def register(self, username: str, password: str) -> User:
        """Создать пользователя с солью и пустой портфель; вход не выполнять."""
        username = validate_username(username)
        validate_password(password)
        users = self._storage.load_users()
        if any(user.username == username for user in users):
            raise ValueError(f"Имя пользователя '{username}' уже занято")
        user = User.create(
            max((user.user_id for user in users), default=0) + 1, username, password
        )
        self._storage.register_user(user)
        return user

    def login(self, username: str, password: str) -> User:
        """Проверить учётные данные и вернуть User, не сохраняя сессию."""
        username = validate_username(username)
        user = next(
            (user for user in self._storage.load_users() if user.username == username),
            None,
        )
        if user is None:
            raise AuthenticationError(f"Пользователь '{username}' не найден")
        if not user.verify_password(password):
            raise AuthenticationError("Неверный пароль")
        return user

    def list_currencies(self) -> tuple[Currency, ...]:
        """Вернуть описания всех валют из общего реестра."""
        return tuple(get_currency(code) for code in get_supported_codes())

    @log_action("GET_RATE")
    def get_rate(
        self, from_currency: str, to_currency: str, user_id: int | None = None
    ) -> RateQuote:
        """Прочитать свежий курс из кэша; обновление запускается отдельно."""
        if user_id is not None:
            self.get_user(user_id)
        return self._rates.get_rate(from_currency, to_currency)

    def show_rates(
        self,
        currency_code: str | None = None,
        *,
        top: int | None = None,
        base_currency: str | None = None,
    ) -> CachedRatesView:
        """Получить курсы для просмотра, включая пометку об истечении TTL."""
        return self._rates.get_cached_rates(
            currency_code, top=top, base_currency=base_currency
        )

    def update_rates(self, source: str | None = None):
        """Делегировать явное обновление выбранному источнику Parser Service."""
        from valutatrade_hub.parser_service.updater import create_updater

        return create_updater(source, self._storage).run_update()

    @database_transaction
    def show_portfolio(
        self, user_id: int, base_currency: str | None = None
    ) -> PortfolioView:
        """Загрузить пользователя и курсы и передать их в модель портфеля."""
        user = self.get_user(user_id)
        base = get_currency(
            self._settings.get("default_base_currency")
            if base_currency is None
            else base_currency
        ).code
        portfolio = self._storage.load_portfolio(user)
        if not portfolio.wallets:
            return PortfolioView(user.username, base, (), 0.0)
        usd_rates = {"USD": 1.0}
        for code in set(portfolio.wallets) | {base}:
            if code not in usd_rates:
                usd_rates[code] = self.get_rate(code, "USD", user_id=user_id).rate
        total = portfolio.get_total_value(base, rates=usd_rates)
        rows = tuple(
            WalletValuation(
                code, wallet.balance, wallet.balance * usd_rates[code] / usd_rates[base]
            )
            for code, wallet in sorted(portfolio.wallets.items())
        )
        return PortfolioView(user.username, base, rows, total)

    @log_action("BUY")
    @database_transaction
    def buy(self, user_id: int, currency_code: str, amount: float) -> TradeResult:
        """Увеличить баланс валюты; USD используется только для оценки."""
        user = self.get_user(user_id)
        code = get_currency(currency_code).code
        amount = validate_number(amount, name="amount", positive=True)
        quote = self.get_rate(code, "USD", user_id=user_id)
        value = validate_number(amount * quote.rate, name="usd_value", positive=True)
        portfolio = self._storage.load_portfolio(user)
        wallet = (
            portfolio.get_wallet(code)
            if code in portfolio.wallets
            else portfolio.add_currency(code)
        )
        before = wallet.balance
        wallet.deposit(amount)
        self._storage.save_portfolio(portfolio)
        return TradeResult("buy", code, amount, quote, value, before, wallet.balance)

    @log_action("SELL")
    @database_transaction
    def sell(self, user_id: int, currency_code: str, amount: float) -> TradeResult:
        """Уменьшить баланс валюты и вывести оценочную выручку без зачисления USD."""
        user = self.get_user(user_id)
        code = get_currency(currency_code).code
        amount = validate_number(amount, name="amount", positive=True)
        portfolio = self._storage.load_portfolio(user)
        if code not in portfolio.wallets:
            raise InsufficientFundsError(0, amount, code)
        wallet = portfolio.get_wallet(code)
        before = wallet.balance
        wallet.withdraw(amount)
        quote = self.get_rate(code, "USD", user_id=user_id)
        value = validate_number(amount * quote.rate, name="usd_value", positive=True)
        self._storage.save_portfolio(portfolio)
        return TradeResult("sell", code, amount, quote, value, before, wallet.balance)
