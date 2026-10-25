"""Декоратор аудита: фиксирует результат операции и пробрасывает ошибки."""

import inspect
import math
from functools import wraps

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.infra.settings import SettingsLoader


def _log_value(value):
    """Некорректный ввод также должен оставаться допустимым JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return type(value).__name__


def log_action(action: str, *, verbose: bool | None = None):
    """Логировать только разрешённые поля, без паролей, хешей и соли."""

    def decorate(method):
        signature = inspect.signature(method)

        @wraps(method)
        def wrapped(self, *args, **kwargs):
            arguments = signature.bind(self, *args, **kwargs).arguments
            user_id = arguments.get("user_id")
            username = None
            if user_id is not None:
                try:
                    username = self.get_user(user_id).username
                except ValueError, StorageError:
                    pass
            currency = arguments.get("currency_code", arguments.get("from_currency"))
            event = {
                "action": action.upper(),
                "username": username,
                "user_id": _log_value(user_id),
                "currency_code": (
                    currency.strip().upper() if isinstance(currency, str) else None
                ),
                "amount": _log_value(arguments.get("amount")),
                "rate": None,
                "base": _log_value(arguments.get("to_currency", "USD")),
            }
            try:
                result = method(self, *args, **kwargs)
            except Exception as exc:
                event.update(
                    result="ERROR",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                self._logger.info("action", extra={"action_data": event})
                raise
            quote = getattr(result, "quote", result)
            event.update(result="OK", rate=getattr(quote, "rate", None))
            detailed = (
                SettingsLoader().get("log_verbose") if verbose is None else verbose
            )
            if detailed and hasattr(result, "previous_balance"):
                event["wallet"] = {
                    "before": result.previous_balance,
                    "after": result.balance,
                }
            self._logger.info("action", extra={"action_data": event})
            return result

        return wrapped

    return decorate
