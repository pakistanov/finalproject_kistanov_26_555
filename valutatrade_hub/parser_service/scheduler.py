"""Последовательное периодическое обновление без фоновой установки служб."""

import argparse
import logging
from threading import Event

from valutatrade_hub.core.exceptions import ApiRequestError, StorageError
from valutatrade_hub.core.utils import validate_number
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.updater import RatesUpdater, create_updater


class RatesScheduler:
    """Периодический последовательный запуск обновлений с возможностью остановки."""

    def __init__(
        self,
        updater: RatesUpdater,
        interval_seconds: float | None = None,
        *,
        stop_event: Event | None = None,
    ) -> None:
        """Настроить интервал обновления и событие остановки."""
        self.updater = updater
        self.interval = validate_number(
            updater.storage.config.UPDATE_INTERVAL_SECONDS
            if interval_seconds is None
            else interval_seconds,
            name="interval_seconds",
            positive=True,
        )
        self._stop = stop_event if stop_event is not None else Event()

    def stop(self) -> None:
        """Запросить остановку перед следующим циклом обновления."""
        self._stop.set()

    def run(self, *, max_cycles: int | None = None) -> int:
        """Обновлять курсы с интервалом, продолжая работу после сбоев API."""
        if max_cycles is not None and (
            isinstance(max_cycles, bool)
            or not isinstance(max_cycles, int)
            or max_cycles <= 0
        ):
            raise ValueError("Количество обновлений должно быть положительным целым")
        cycles = 0
        while not self._stop.is_set():
            try:
                self.updater.run_update()
            except (ApiRequestError, StorageError) as exc:
                self.updater.logger.error(
                    "scheduler",
                    extra={
                        "action_data": {
                            "action": "SCHEDULER_ERROR",
                            "error_message": str(exc),
                        }
                    },
                )
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            if self._stop.wait(self.interval):
                break
        return cycles


def main(argv: list[str] | None = None) -> int:
    """Обработать аргументы командной строки и запустить приложение."""
    parser = argparse.ArgumentParser(description="Периодическое обновление курсов")
    parser.add_argument("--interval", type=float, help="Интервал в секундах")
    parser.add_argument("--source", choices=("coingecko", "exchangerate"))
    parser.add_argument("--data-dir")
    parser.add_argument("--cycles", type=int, help="Завершиться после N обновлений")
    arguments = parser.parse_args(argv)
    try:
        updater = create_updater(arguments.source, DatabaseManager(arguments.data_dir))
        scheduler = RatesScheduler(updater, arguments.interval)
        scheduler.run(max_cycles=arguments.cycles)
    except KeyboardInterrupt:
        return 0
    except (ValueError, ApiRequestError, StorageError) as exc:
        print(str(exc))
        return 1
    finally:
        logging.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
