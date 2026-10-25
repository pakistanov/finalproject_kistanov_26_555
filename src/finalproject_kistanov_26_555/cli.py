"""Точка входа консольного приложения."""

from argparse import ArgumentParser
from importlib.metadata import version


class WalletApplication:
    """Каркас приложения для последующей реализации валютного кошелька."""

    def run(self) -> None:
        """Запустить приложение."""
        print("Валютный кошелёк. Базовое окружение готово к разработке.")


def main() -> None:
    """Обработать аргументы командной строки и запустить приложение."""
    parser = ArgumentParser(
        prog="finalproject_kistanov_26_555",
        description="Консольный валютный кошелёк",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('finalproject_kistanov_26_555')}",
    )
    parser.parse_args()
    WalletApplication().run()
