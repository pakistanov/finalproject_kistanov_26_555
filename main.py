"""Запуск из корня проекта: uv run main.py."""

from valutatrade_hub.cli.interface import run


def main() -> int:
    """Запустить командный интерфейс установленного пакета."""
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
