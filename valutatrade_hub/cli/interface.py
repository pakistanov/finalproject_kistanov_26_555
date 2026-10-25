"""Разбор команд и вывод результатов без бизнес-логики сделок."""

import argparse
import shlex
import sys
from importlib.metadata import version
from typing import TextIO

from prettytable import PrettyTable

from valutatrade_hub.core.currencies import get_supported_codes
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    RateUnavailableError,
    StorageError,
)
from valutatrade_hub.core.rates import CachedRatesView, RateQuote
from valutatrade_hub.core.usecases import PortfolioView, TradeResult, TradingService
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.updater import UpdateResult


class CommandExit(Exception):
    """Справка не должна завершать интерактивный сеанс."""

    def __init__(self, status: int = 0, message: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class CommandParser(argparse.ArgumentParser):
    """Ошибки синтаксиса команд обрабатывает интерфейс, а не sys.exit."""

    def exit(self, status: int = 0, message: str | None = None) -> None:
        raise CommandExit(status, message)

    def error(self, message: str) -> None:
        raise CommandExit(2, message)


def build_parser(*, global_options: bool = False) -> CommandParser:
    parser = CommandParser(
        prog="finalproject_kistanov_26_555",
        description="Виртуальный валютный кошелёк с курсами из локального кэша",
    )
    if global_options:
        parser.add_argument(
            "--data-dir",
            help=(
                "Каталог JSON-данных "
                "(по умолчанию из настроек или VALUTATRADE_DATA_DIR)"
            ),
        )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('finalproject_kistanov_26_555')}",
    )
    commands = parser.add_subparsers(dest="command", title="Команды")
    for command, help_text in (
        ("register", "Зарегистрироваться"),
        ("login", "Войти в систему"),
    ):
        child = commands.add_parser(command, help=help_text)
        child.add_argument("--username", required=True)
        child.add_argument("--password", required=True)
    portfolio = commands.add_parser("show-portfolio", help="Посмотреть портфель")
    portfolio.add_argument("--base", help="Базовая валюта (по умолчанию из настроек)")
    for command, help_text in (
        ("buy", "Купить валюту за USD"),
        ("sell", "Продать валюту за USD"),
        ("deposit", "Пополнить виртуальный USD-баланс"),
    ):
        child = commands.add_parser(command, help=help_text)
        child.add_argument("--currency", required=command != "deposit", default="USD")
        child.add_argument("--amount", required=True, type=float)
    rate = commands.add_parser("get-rate", help="Получить курс валюты")
    rate.add_argument("--from", dest="from_currency", required=True)
    rate.add_argument("--to", dest="to_currency", required=True)
    update = commands.add_parser("update-rates", help="Обновить курсы из внешних API")
    update.add_argument("--source", choices=("coingecko", "exchangerate"))
    cached = commands.add_parser("show-rates", help="Посмотреть локальный кэш курсов")
    cached.add_argument("--currency")
    cached.add_argument("--top", type=int)
    cached.add_argument("--base")
    commands.add_parser("currencies", help="Список поддерживаемых валют")
    commands.add_parser("logout", help="Завершить текущую сессию")
    commands.add_parser("help", help="Показать справку")
    commands.add_parser("exit", help="Выйти из приложения")
    commands.add_parser("quit", help="Выйти из приложения")
    return parser


def format_portfolio(view: PortfolioView) -> str:
    title = f"Портфель пользователя '{view.username}' (база: {view.base_currency})"
    if not view.wallets:
        return f"{title}\nПортфель пуст. Пополните его: deposit --amount 1000"
    table = PrettyTable(["Валюта", "Баланс", f"Стоимость, {view.base_currency}"])
    table.align["Валюта"] = "l"
    table.align["Баланс"] = "r"
    table.align[f"Стоимость, {view.base_currency}"] = "r"
    for wallet in view.wallets:
        table.add_row(
            [wallet.currency_code, f"{wallet.balance:.12g}", f"{wallet.value:,.2f}"]
        )
    return f"{title}\n{table}\nИТОГО: {view.total_value:,.2f} {view.base_currency}"


def format_cached_rates(view: CachedRatesView) -> str:
    table = PrettyTable(["Пара", "Курс", "Обновлено", "Источник", "Состояние"])
    for quote in view.quotes:
        table.add_row(
            [
                f"{quote.from_currency}_{quote.to_currency}",
                f"{quote.rate:.12g}",
                quote.updated_at.isoformat(),
                quote.source,
                "устарел" if quote.is_stale else "актуален",
            ]
        )
    result = f"Курсы из кэша (обновлено: {view.last_refresh or '—'}):\n{table}"
    if any(quote.is_stale for quote in view.quotes):
        result += "\nЕсть устаревшие курсы. Выполните 'update-rates'."
    return result


def format_update(result: UpdateResult) -> str:
    status = (
        "Обновление завершено с ошибками." if result.errors else "Обновление завершено."
    )
    message = (
        f"{status} Обновлено курсов: {result.updated_count}. "
        f"Последнее обновление: {result.last_refresh or '—'}"
    )
    if result.errors:
        message += "\n" + "\n".join(result.errors.values())
        message += "\nПодробности — в журнале парсера."
    return message


def format_error(error: Exception) -> str:
    if isinstance(error, (InsufficientFundsError, RateUnavailableError)):
        return str(error)
    if isinstance(error, CurrencyNotFoundError):
        return f"{error}. Поддерживаемые валюты: {', '.join(get_supported_codes())}"
    if isinstance(error, ApiRequestError):
        return f"{error}. Повторите попытку позже или проверьте сеть."
    return f"Ошибка: {error}"


def format_quote(quote: RateQuote) -> str:
    return (
        f"Курс {quote.from_currency}→{quote.to_currency}: {quote.rate:.12g} "
        f"(обновлено: {quote.updated_at.isoformat()})\n"
        f"Обратный курс {quote.to_currency}→{quote.from_currency}: "
        f"{1 / quote.rate:.12g}\nИсточник: {quote.source}"
    )


def format_trade(trade: TradeResult) -> str:
    action = "Покупка" if trade.side == "buy" else "Продажа"
    value_label = "Стоимость покупки" if trade.side == "buy" else "Выручка"
    return (
        f"{action} выполнена: {trade.amount:.12g} {trade.currency_code} "
        f"по курсу {trade.quote.rate:.12g} USD/{trade.currency_code}\n"
        f"Изменения в портфеле:\n"
        f"- {trade.currency_code}: было {trade.previous_balance:.12g} "
        f"→ стало {trade.balance:.12g}\n"
        f"- USD: было {trade.previous_usd_balance:.12g} "
        f"→ стало {trade.usd_balance:.12g}\n"
        f"{value_label}: {trade.usd_value:,.2f} USD\n"
        f"Источник: {trade.quote.source}"
    )


class WalletApplication:
    """Одна интерактивная сессия, живущая до exit или конца ввода."""

    def __init__(self, service: TradingService, output: TextIO | None = None) -> None:
        self.service = service
        self.parser = build_parser()
        self.output = output

    def dispatch(self, arguments: argparse.Namespace) -> bool:
        """Вызвать сценарий и отобразить результат; False означает выход."""
        match arguments.command:
            case "register":
                user = self.service.register(arguments.username, arguments.password)
                message = (
                    f"Пользователь '{user.username}' зарегистрирован "
                    f"(id={user.user_id}). "
                    f"Войдите: login --username {shlex.quote(user.username)} "
                    "--password ****"
                )
            case "login":
                user = self.service.login(arguments.username, arguments.password)
                message = f"Вы вошли как '{user.username}'"
            case "logout":
                self.service.logout()
                message = "Вы вышли из учётной записи"
            case "show-portfolio":
                message = format_portfolio(self.service.show_portfolio(arguments.base))
            case "buy":
                message = format_trade(
                    self.service.buy(arguments.currency, arguments.amount)
                )
            case "sell":
                message = format_trade(
                    self.service.sell(arguments.currency, arguments.amount)
                )
            case "deposit":
                balance = self.service.deposit(arguments.currency, arguments.amount)
                message = f"Виртуальный USD-баланс пополнен. Баланс: {balance:.12g} USD"
            case "get-rate":
                message = format_quote(
                    self.service.get_rate(
                        arguments.from_currency, arguments.to_currency
                    )
                )
            case "update-rates":
                message = format_update(self.service.update_rates(arguments.source))
            case "show-rates":
                message = format_cached_rates(
                    self.service.show_rates(
                        arguments.currency,
                        top=arguments.top,
                        base_currency=arguments.base,
                    )
                )
            case "currencies":
                message = "\n".join(
                    currency.get_display_info()
                    for currency in self.service.list_currencies()
                )
            case "help":
                self.parser.print_help(file=self.output)
                return True
            case "exit" | "quit":
                return False
            case _:
                return True
        print(message, file=self.output)
        return True

    def execute(self, line: str) -> bool:
        """Обработать строку; ошибки одной команды не прерывают сеанс."""
        try:
            tokens = shlex.split(line)
            if not tokens:
                return True
            return self.dispatch(self.parser.parse_args(tokens))
        except CommandExit as exc:
            if exc.message:
                print(f"Ошибка: {exc.message}", file=self.output)
        except (ValueError, ApiRequestError, StorageError) as exc:
            print(format_error(exc), file=self.output)
        return True

    def run(self) -> int:
        print(
            "Валютный кошелёк. Средства виртуальные.\n"
            "Команды: help; справка по команде: buy --help; выход: exit.",
            file=self.output,
        )
        while True:
            try:
                line = input("valuta> ")
            except EOFError, KeyboardInterrupt:
                print(file=self.output)
                break
            if not self.execute(line):
                break
        return 0


def main(argv: list[str] | None = None) -> int:
    """Запустить одну команду или интерактивную оболочку без аргументов."""
    parser = build_parser(global_options=True)
    try:
        arguments = parser.parse_args(argv)
    except CommandExit as exc:
        if exc.message:
            print(f"Ошибка: {exc.message}", file=sys.stderr)
        return exc.status
    try:
        storage = DatabaseManager(arguments.data_dir)
        application = WalletApplication(TradingService(storage))
        if arguments.command is None:
            return application.run()
        application.dispatch(arguments)
    except (ValueError, ApiRequestError, StorageError) as exc:
        print(format_error(exc), file=sys.stderr)
        return 1
    return 0
