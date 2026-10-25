"""Разбор команд и вывод результатов без бизнес-логики сделок."""

import argparse
import os
import shlex
import sys
from importlib.metadata import version
from typing import TextIO

from prettytable import PrettyTable

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.rates import RateQuote
from valutatrade_hub.core.storage import JsonStorage
from valutatrade_hub.core.usecases import PortfolioView, TradeResult, TradingService


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
        description="Виртуальный валютный кошелёк с демонстрационными курсами",
    )
    if global_options:
        parser.add_argument(
            "--data-dir",
            default=os.environ.get("VALUTATRADE_DATA_DIR", "data"),
            help="Каталог JSON-данных (по умолчанию data или VALUTATRADE_DATA_DIR)",
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
    portfolio.add_argument("--base", default="USD")
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


def format_source(source: str) -> str:
    if "DemoStub" in source:
        return f"{source} (фиксированные демонстрационные курсы)"
    return source


def format_quote(quote: RateQuote) -> str:
    return (
        f"Курс {quote.from_currency}→{quote.to_currency}: {quote.rate:.12g} "
        f"(обновлено: {quote.updated_at.isoformat()})\n"
        f"Обратный курс {quote.to_currency}→{quote.from_currency}: "
        f"{1 / quote.rate:.12g}\nИсточник: {format_source(quote.source)}"
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
        f"Источник: {format_source(trade.quote.source)}"
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
        except (ValueError, StorageError) as exc:
            print(f"Ошибка: {exc}", file=self.output)
        return True

    def run(self) -> int:
        print(
            "Валютный кошелёк. Курсы демонстрационные, средства виртуальные.\n"
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
        storage = JsonStorage(arguments.data_dir)
        application = WalletApplication(TradingService(storage))
        if arguments.command is None:
            return application.run()
        application.dispatch(arguments)
    except (ValueError, StorageError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0
