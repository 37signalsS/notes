# Управление версиями Python в Linux

## Определения

**Python** — высокоуровневый, универсальный, интерпретируемый язык программирования.

**`pyenv`** — инструмент для установки и управления несколькими версиями Python в одной ОС.

**`pyenv-virtualenv`** — плагин для `pyenv`, создающий и управляющий изолированными виртуальными окружениями для проектов.

## Базовые концепции

### Принцип работы `pyenv`

`pyenv` вставляет «прокладки» (shims) в начало `PATH`. При вызове `python` система находит shim `pyenv`, который определяет целевую версию Python (глобальную, локальную или через `shell`) и передаёт управление соответствующему исполняемому файлу.

### Изоляция зависимостей

Практика разделения пакетов для разных проектов. `pyenv-virtualenv` создаёт отдельные окружения с собственным набором библиотек, привязанных к конкретной версии Python.

### Безопасность системной версии

Python — критический компонент дистрибутивов Linux. Системные утилиты (`yum`, `apt`, `dnf`) зависят от системного Python (`/usr/bin/python`). **Запрещено изменять или удалять системный Python.** `pyenv` устанавливает версии в `~/.pyenv`, не затрагивая системные файлы.

## Практические сценарии

### Установка `pyenv`

**Зависимости для сборки Python:**

`pyenv` собирает Python из исходников, требуются компилятор и библиотеки.

**Для RHEL-совместимых систем:**

```bash
# RHEL 8 / AlmaLinux 8 / Rocky Linux 8
sudo dnf groupinstall "Development Tools" -y
sudo dnf install -y git gcc make zlib-devel bzip2-devel readline-devel \
  sqlite-devel openssl-devel tk-devel libffi-devel xz-devel libuuid-devel \
  gdbm-libs libnsl2

# RHEL 9 / AlmaLinux 9 / Rocky Linux 9
sudo dnf groupinstall "Development Tools" -y
sudo dnf install -y git gcc make zlib-devel bzip2-devel readline-devel \
  sqlite-devel openssl-devel tk-devel libffi-devel xz-devel libuuid-devel \
  python3-libnsl2
```

**Для Debian/Ubuntu:**

```bash
sudo apt update && sudo apt install -y make build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev \
  xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
```

**Установка `pyenv`:**

```bash
git clone https://github.com/pyenv/pyenv.git ~/.pyenv
```

**Настройка окружения:**

Добавить в `~/.bashrc` (или `~/.zshrc`):

```bash
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo -e 'if command -v pyenv 1>/dev/null 2>&1; then\n  eval "$(pyenv init -)"\nfi' >> ~/.bashrc
source ~/.bashrc
```

### Управление версиями Python

**Просмотр доступных версий:**

```bash
pyenv install --list
```

**Установка версии:**

```bash
pyenv install 3.12.4
```

**Выбор версии:**

| Область | Команда | Описание |
| :--- | :--- | :--- |
| Глобально | `pyenv global 3.12.4` | Версия по умолчанию для пользователя |
| Локально | `pyenv local 3.12.4` | Версия для каталога (создаёт `.python-version`) |
| Сессия | `pyenv shell 3.12.4` | Версия для текущей сессии shell |

**Просмотр версий:**

```bash
pyenv versions   # все установленные версии
pyenv version    # активная версия
```

### Работа с `pyenv-virtualenv`

**Установка плагина:**

```bash
git clone https://github.com/pyenv/pyenv-virtualenv.git $(pyenv root)/plugins/pyenv-virtualenv
echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
source ~/.bashrc
```

**Создание и активация окружения:**

```bash
# Создать окружение на базе Python 3.12.4
pyenv virtualenv 3.12.4 my-project-env

# Активировать локально (автоматическая активация при входе в каталог)
pyenv local my-project-env

# Установка пакетов в изолированное окружение
pip install numpy pandas
```

**Удаление окружения:**

```bash
pyenv virtualenv-delete my-project-env
```

## Дополнительная информация

### Альтернативные инструменты

| Инструмент | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`venv`** | Встроенный модуль Python3 | Простые проекты, одна версия Python |
| **`pipenv`** | Комбинация `pip` + `virtualenv` + `Pipfile` | Проекты с зависимостями в стиле JavaScript |
| **`poetry`** | Менеджер зависимостей и сборок | Современные Python-проекты с packaging |
| **`uv`** | Быстрый менеджер пакетов на Rust | Высокая производительность установки |
| **`asdf`** | Универсальный менеджер версий | Несколько языков в одном инструменте |

### Файл `.python-version`

Автоматически создаётся командой `pyenv local`. Содержит номер версии или имя окружения. Рекомендуется коммитить в репозиторий для фиксации версии Python проекта.

### Диагностика проблем

| Проблема | Решение |
| :--- | :--- |
| `pyenv: command not found` | Проверить `PATH` и инициализацию в `~/.bashrc` |
| Ошибка сборки Python | Установить зависимости (zlib, openssl, libffi) |
| Shim не обновлён | Выполнить `pyenv rehash` |

### Полезные ссылки

- [Официальная документация pyenv](https://github.com/pyenv/pyenv)
- [Документация pyenv-virtualenv](https://github.com/pyenv/pyenv-virtualenv)
- [Рекомендованные зависимости для сборки](https://github.com/pyenv/pyenv/wiki#suggested-build-environment)
