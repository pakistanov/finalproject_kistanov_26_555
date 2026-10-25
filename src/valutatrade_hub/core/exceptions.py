"""Ожидаемые ошибки приложения, пригодные для вывода в CLI."""


class AuthenticationError(ValueError):
    """Операция требует входа в систему или корректных учётных данных."""


class InsufficientFundsError(ValueError):
    """В кошельке недостаточно средств."""

    def __init__(self, available: float, required: float, code: str) -> None:
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
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(RuntimeError):
    """Провайдер не смог предоставить корректный курс."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class StorageError(RuntimeError):
    """Данные не удалось прочитать или сохранить."""
