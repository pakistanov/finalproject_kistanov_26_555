# finalproject_kistanov_26_555

Консольное приложение для управления виртуальным валютным портфелем:
регистрация, вход, покупка и продажа валют, просмотр балансов и курсов.

**Технологии:** Python 3.14, uv, PrettyTable, Ruff. Данные хранятся в JSON.

## Установка и запуск

```powershell
uv sync --locked
uv run finalproject_kistanov_26_555
```

## Команды

После запуска введите команды в консоли приложения:

```text
register --username alice --password 1234
login --username alice --password 1234
deposit --amount 10000
buy --currency BTC --amount 0.05
sell --currency BTC --amount 0.01
show-portfolio
show-portfolio --base EUR
get-rate --from USD --to BTC
logout
help
exit
```

Новый портфель пуст; `deposit` пополняет виртуальный USD-баланс.
Покупка списывает USD, продажа начисляет USD. `amount` — количество валюты.
Для торговли выполните `login` и последующие команды в одном сеансе.
Пароль должен содержать не менее 4 символов. Справка по команде: `buy --help`.

## Хранение данных

Файлы создаются автоматически в `data/` и исключены из Git:

- `users.json` — пользователи, хеши паролей и соли.
- `portfolios.json` — портфели и балансы кошельков.
- `rates.json` — кэш курсов со временем обновления.

Используются фиксированные курсы; срок свежести кэша — 5 минут.

## Структура проекта

```text
src/valutatrade_hub/
├── core/
│   ├── models.py       # User, Wallet, Portfolio
│   ├── utils.py        # валидация данных
│   ├── usecases.py     # бизнес-логика
│   ├── storage.py      # работа с JSON
│   └── rates.py        # получение курсов
└── cli/
    └── interface.py    # командный интерфейс
main.py                 # запуск приложения
pyproject.toml          # настройки и зависимости
uv.lock                 # версии зависимостей
```

## Проверка кода и сборка

```powershell
uv run ruff check .
uv run ruff format --check .
uv --no-cache build
```

Собранный пакет находится в `dist/`.

## Gitflow

- `main` — стабильные выпуски; `develop` — разработка.
- `feature/*` создаются от `develop` и сливаются в неё через `--no-ff`.
- `release/*` — подготовка выпусков; `hotfix/*` — срочные исправления.
