"""Ожидаемые ошибки приложения, пригодные для вывода в CLI."""


class AuthenticationError(ValueError):
    """Операция требует входа в систему или корректных учётных данных."""


class InsufficientFundsError(ValueError):
    """В кошельке недостаточно средств."""

    def __init__(self, available: float, required: float, code: str) -> None:
        """Сохранить доступную и требуемую суммы и сформировать сообщение."""
        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {available:.12g} {code}, "
            f"требуется {required:.12g} {code}"
        )


class CurrencyNotFoundError(ValueError):
    """Код валюты отсутствует в реестре."""

    def __init__(self, code: str) -> None:
        """Сохранить неизвестный код валюты и сообщение об ошибке."""
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(RuntimeError):
    """Провайдер не смог предоставить корректный курс."""

    def __init__(self, reason: str) -> None:
        """Добавить безопасную причину сбоя внешнего API."""
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class StorageError(RuntimeError):
    """Данные не удалось прочитать или сохранить."""


class RateUnavailableError(ValueError):
    """В локальном кэше нет подходящего курса."""

    def __init__(self, from_code: str, to_code: str) -> None:
        """Сформировать предложение загрузить отсутствующий курс."""
        super().__init__(
            f"Курс {from_code}→{to_code} недоступен. Выполните 'update-rates'."
        )


class StaleRateError(RateUnavailableError):
    """Кэш содержит курс, но его TTL истёк."""

    def __init__(self, from_code: str, to_code: str, updated_at: str) -> None:
        """Сформировать сообщение об истёкшем TTL и времени курса."""
        ValueError.__init__(
            self,
            f"Курс {from_code}→{to_code} устарел (обновлён: {updated_at}). "
            "Выполните 'update-rates'.",
        )
