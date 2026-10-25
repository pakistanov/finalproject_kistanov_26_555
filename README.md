# finalproject_kistanov_26_555

Учебное консольное приложение, имитирующее работу валютного кошелька.
Проект оформлен как устанавливаемый Python-пакет со структурой `src/`.

Текущий этап — подготовка окружения. Добавлены класс `WalletApplication`,
консольная точка входа, справка и вывод версии. Валютные операции будут
реализованы на следующих этапах.

Фамилия: `kistanov`, группа: `26-555`. В имени Python-пакета разделители
номера группы заменены подчёркиваниями: `finalproject_kistanov_26_555`.

## Окружение и зависимости

- Python 3.14; версия закреплена в `.python-version`.
- `uv` — окружение, зависимости и сборка пакета.
- `prettytable` — форматированный табличный вывод на следующих этапах.
- `ruff` — зависимость для разработки: анализ и форматирование кода.
- `json`, `shlex`, `time` входят в стандартную библиотеку Python;
  устанавливать их отдельно не нужно. `shlex` предполагается использовать
  для разбора команд самого приложения, без передачи их системной оболочке.

## Установка и запуск

Из корня проекта выполните:

```powershell
uv sync --locked
uv run finalproject_kistanov_26_555
uv run finalproject_kistanov_26_555 --help
uv run finalproject_kistanov_26_555 --version
```

Альтернативный запуск:

```powershell
uv run python -m finalproject_kistanov_26_555
```

`uv` создаёт `.venv` и устанавливает в неё пакет и зависимости.
Активировать окружение вручную не требуется. Кэш `uv` хранится внутри
проекта в `.uv-cache/` согласно `uv.toml` и исключён из Git.

## Качество кода

```powershell
uv run ruff check .
uv run ruff format --check .
```

Для применения исправлений и форматирования:

```powershell
uv run ruff check --fix .
uv run ruff format .
```

Включены проверки ошибок, импортов, распространённых проблем и современного
синтаксиса Python. Длина строки — 88 символов.

## Сборка и установка пакета

```powershell
uv --no-cache build
```

В `dist/` появятся wheel (`.whl`) и исходный архив (`.tar.gz`).
Wheel можно установить в отдельное окружение:

```powershell
uv venv .venv-install
uv pip install --python .venv-install/Scripts/python.exe dist/finalproject_kistanov_26_555-0.1.0-py3-none-any.whl
.venv-install/Scripts/finalproject_kistanov_26_555.exe --version
```

Окружение `.venv-install/` исключено из Git правилом `.venv*/`.

## Структура проекта

```text
FinalProject/
├── .gitattributes
├── .gitignore
├── .python-version
├── pyproject.toml
├── README.md
├── uv.lock
├── uv.toml
└── src/
    └── finalproject_kistanov_26_555/
        ├── __init__.py
        ├── __main__.py
        └── cli.py
```

## Работа с Git

Репозиторий инициализирован с основной веткой `main`.
Для разработки используйте GitHub Flow: отдельная ветка на задачу,
проверки качества перед коммитом, затем слияние в `main`.

```powershell
git switch -c feature/wallet-models
uv run ruff check .
uv run ruff format --check .
git add .
git commit -m "feat: add wallet models"
```

Фиксируйте завершённые задачи небольшими осмысленными коммитами.
`uv.lock` хранится в репозитории для воспроизводимой установки зависимостей.
