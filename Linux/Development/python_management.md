# Управление версиями Python в Linux

## Определения

* **Python** — высокоуровневый, универсальный, интерпретируемый язык программирования.
* **`pyenv`** — инструмент для установки нескольких версий Python и управления ими в одной операционной системе.
* **`pyenv-virtualenv`** — плагин для `pyenv`, позволяющий создавать и управлять изолированных виртуальными окружениями для проектов.
* **`uv`** — современный и сверхбыстрый инструмент (написан на Rust), объединяющий функции pip, venv, pyenv и pipx.
* **Изоляция зависимостей** — практика разделения пакетов для разных проектов в изолированные виртуальные окружения для предотвращения конфликтов версий библиотек.

## Основные концепции

### Принцип работы `pyenv`

`pyenv` вставляет «прокладки» (shims) в начало переменной `PATH`. При вызове команды `python` система сначала находит shim `pyenv`. Затем `pyenv` определяет целевую версию Python (глобальную, локальную для каталога или заданную через `shell`) и передаёт управление соответствующему исполняемому файлу.

### Безопасность системной версии Python

Python является критическим компонентом большинства дистрибутивов Linux. Системные пакетные менеджеры (`yum`, `apt`, `dnf`) зависят от системного Python (`/usr/bin/python`). **Запрещено изменять или удалять системный Python**, так как это приведет к поломке ОС. `pyenv` решает эту проблему, устанавливая версии в домашний каталог пользователя (`~/.pyenv`), не затрагивая системные файлы.

### PEP 668 (Externally Managed Environment)

Начиная с Python 3.11 (Ubuntu 23.04+) дистрибутивы Linux блокируют `pip install` вне виртуального окружения для системного Python. Это политика PEP 668 (PEP — Python Enhancement Proposal).

**Ошибка при попытке установки вне venv:**

```
error: externally-managed-environment
× This environment is externally managed
╰─> To install Python packages system-wide, try apt install
    python3-xyz, where xyz is the package you are trying to
    install.
...
```

**Причина:** предотвращение конфликтов между pip-пакетами и пакетами системного менеджера (apt) — см. раздел о безопасности системного Python выше.

**Решение:**

1. Использовать виртуальное окружение (`python3 -m venv /path/to/venv`) — **рекомендуемый способ**.
2. Установить с флагом `--break-system-packages` — только при понимании рисков конфликта с apt:

   ```bash
   pip install --break-system-packages <package>
   ```

   В Ansible это делается через параметр `extra_args`:
   ```yaml
   - name: Установка Python-библиотек
     ansible.builtin.pip:
       name: docker>=5.0.0
       extra_args: --break-system-packages
   ```

## Практические сценарии

### Установка `pyenv`

`pyenv` собирает Python из исходных кодов, поэтому предварительно требуются компилятор и библиотеки.

**1. Установка зависимостей для сборки:**

```bash
# Для RHEL 8/9 / AlmaLinux / Rocky Linux
sudo dnf groupinstall "Development Tools" -y
sudo dnf install -y git gcc make zlib-devel bzip2-devel readline-devel \
  sqlite-devel openssl-devel tk-devel libffi-devel xz-devel libuuid-devel \
  libnsl2 # для RHEL 9 используйте python3-libnsl2

# Для Debian/Ubuntu
sudo apt update && sudo apt install -y make build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev \
  xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
```

**2. Установка самого `pyenv`:**

```bash
git clone https://github.com/pyenv/pyenv.git ~/.pyenv
```

**3. Настройка окружения:**
Добавьте инициализацию в `~/.bashrc` (или `~/.zshrc`):

```bash
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo -e 'if command -v pyenv 1>/dev/null 2>&1; then\n  eval "$(pyenv init -)"\nfi' >> ~/.bashrc
source ~/.bashrc
```

### Управление версиями Python

**Просмотр и установка:**

```bash
# Список доступных для установки версий
pyenv install --list

# Установка конкретной версии (загрузка и компиляция)
pyenv install 3.12.4
```

**Выбор активной версии:**

```bash
pyenv global 3.12.4   # Установка версии по умолчанию для пользователя
pyenv local 3.12.4    # Версия только для текущего каталога (создаёт файл .python-version)
pyenv shell 3.12.4    # Версия только для текущей сессии shell
```

**Проверка статуса:**

```bash
pyenv versions   # Показать все установленные версии
# → выведет список, активная версия будет отмечена звездочкой (*)

pyenv version    # Показать только текущую активную версию и источник ее выбора
```

### Работа с `pyenv-virtualenv`

**Установка плагина и инициализация:**

```bash
git clone https://github.com/pyenv/pyenv-virtualenv.git $(pyenv root)/plugins/pyenv-virtualenv
echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
source ~/.bashrc
```

**Управление окружениями:**

```bash
# Создать окружение на базе Python 3.12.4
pyenv virtualenv 3.12.4 my-project-env

# Активировать локально (будет автоматически активироваться при входе в этот каталог)
pyenv local my-project-env

# Установка пакетов в изолированное окружение
pip install numpy pandas

# Удаление окружения
pyenv virtualenv-delete my-project-env
```

### Установка CLI-инструментов через `pipx`

`pipx` автоматически создаёт изолированное venv для каждого приложения и добавляет символьную ссылку на его исполняемый файл в `~/.local/bin`.

```bash
# Установка
pip install pipx

# Установка CLI-утилиты
pipx install ansible

# Запуск без установки (ephemeral)
pipx run black --check .

# Установка из каталога или репозитория
pipx install ./my-tool
pipx install git+https://github.com/psf/black.git

# Просмотр и управление
pipx list                # список установленных приложений
pipx upgrade-all         # обновить все приложения
pipx uninstall ansible   # удалить приложение
```

`pipx` использует системный Python (или `pyenv`-версию, если она активна) для создания venv, что гарантирует изоляцию как от системных пакетов, так и от окружений проектов.

## Современный стек: `uv`

`uv` — это универсальный менеджер Python-окружений, который заменяет целый ряд инструментов (pip, venv, pyenv, pipx). Написан на Rust, что обеспечивает кратный прирост производительности по сравнению с классическими утилитами.

### Ключевые возможности

1. **Управление версиями Python (замена pyenv):**
   ```bash
   uv python install 3.13  # установка конкретной версии
   uv python pin 3.13      # фиксация версии для проекта
   ```

2. **Виртуальные окружения и пакеты (замена venv + pip):**
   ```bash
   uv venv                             # создать окружение
   uv pip install -r requirements.txt  # быстрая установка
   uv sync                             # синхронизация окружения с lockfile
   ```

3. **Запуск и воспроизводимость:**
   ```bash
   uv run python script.py  # запуск без ручной активации venv
   uv run pytest            # выполнение тестов в окружении проекта
   ```

4. **CLI-инструменты (замена pipx):**
   ```bash
   uv tool run ruff check . # запуск без установки в систему
   ```

### Использование в CI/CD

`uv` идеально подходит для CI/CD благодаря скорости и поддержке детерминированных сборок.

- **`uv.lock`**: файл фиксации зависимостей (аналог `package-lock.json`). Его необходимо хранить в репозитории.
- **Флаг `--frozen`**: гарантирует установку строго из `uv.lock` без пересчёта графа зависимостей.

**Пример для GitHub Actions:**

```yaml
- name: Setup uv
  uses: astral-sh/setup-uv@v5 # рекомендуется закреплять версию (не @latest)

- name: Sync dependencies
  run: uv sync --frozen

- name: Run tests
  run: uv run pytest
```

## Дополнительная информация

### Сравнительная таблица инструментов

| Инструмент | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`venv`** | Встроенный модуль Python3 | Простые проекты, когда нужна только одна версия Python. См. [Dockerfile: Лучшие практики для Python](../../Docker/Dockerfile/Docker_best_practices/python.md). |
| **`pyenv`** | Менеджер версий Python | Когда нужно часто переключаться между разными версиями интерпретатора. |
| **`poetry`** | Менеджер зависимостей и сборок | Проекты, требующие строгого управления публикацией пакетов. |
| **`uv`** | **All-in-one менеджер (Rust)** | **Рекомендуемый современный стандарт**. Для максимальной скорости (особенно в CI/CD) и простоты управления. |
| **`pipx`** | Установка CLI-приложений | Установка системных утилит (ansible, black), если не используется `uv tool`. |
| **`asdf`** | Универсальный менеджер версий | При разработке на нескольких языках (Ruby, Node.js, Python) одновременно. |

### Диагностика проблем `pyenv`

* **`pyenv: command not found`**: Проверьте, добавлен ли `$PYENV_ROOT/bin` в `PATH` в вашем `~/.bashrc`.
* **Ошибка компиляции (сборки) Python**: Обычно вызвана нехваткой системных библиотек. Убедитесь, что установлены `zlib`, `openssl`, `libffi` (см. шаг "Установка зависимостей").
* **Установленный пакет или команда не найдены (Shim не обновлён)**: Выполните `pyenv rehash` для перестроения "прокладок".

### Полезные ссылки

* [Официальный репозиторий pyenv](https://github.com/pyenv/pyenv)
* [Официальный репозиторий pyenv-virtualenv](https://github.com/pyenv/pyenv-virtualenv)
