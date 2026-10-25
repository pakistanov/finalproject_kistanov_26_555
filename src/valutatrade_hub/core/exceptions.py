"""Ожидаемые ошибки приложения, пригодные для вывода в CLI."""


class AuthenticationError(ValueError):
    """Операция требует входа в систему или корректных учётных данных."""


class InsufficientFundsError(ValueError):
    """В кошельке недостаточно средств."""


class RateUnavailableError(ValueError):
    """Не удалось получить курс валюты."""


class StorageError(RuntimeError):
    """Данные не удалось прочитать или сохранить."""
