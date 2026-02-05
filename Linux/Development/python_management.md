# Управление версиями Python в Linux

### Определения

**Python** — это высокоуровневый, универсальный и интерпретируемый язык программирования.

**`pyenv`** — это инструмент для установки нескольких версий Python и управления ими в одной операционной системе.

**`pyenv-virtualenv`** — это плагин для `pyenv`, который позволяет создавать и управлять изолированными виртуальными окружениями для проектов.

### Основные концепции

*   **Принцип работы `pyenv`:**
    `pyenv` работает путем вставки "прокладок" (shims) в начало переменной окружения `PATH`. Когда вызывается команда, например, `python`, операционная система сначала находит "прокладку" `pyenv`. `pyenv` затем определяет, какую версию Python использовать (глобальную, локальную для каталога или активированную через `shell`), и передает команду соответствующему исполняемому файлу Python.

*   **Изоляция зависимостей:**
    Изоляция зависимостей — это практика разделения пакетов, необходимых для разных проектов. `pyenv-virtualenv` решает эту задачу, позволяя создавать отдельные окружения, каждое со своим набором библиотек, привязанных к определенной версии Python.

*   **Безопасность системной версии:**
    Python является критическим компонентом многих дистрибутивов Linux. Системные утилиты (например, `yum`, `apt`) зависят от системной версии Python (`/usr/bin/python`). **Никогда не пытайтесь изменять или удалять системный Python**. `pyenv` устанавливает версии Python в домашний каталог пользователя (`~/.pyenv`), не затрагивая системные файлы.

### Практические сценарии

*   **Установка `pyenv` и его зависимостей:**
    *   **Установка зависимостей для сборки Python:**
        `pyenv` собирает Python из исходного кода, поэтому требуются компилятор и сопутствующие библиотеки.
        -   **Для CentOS 7 (`yum`):**
            ```bash
            sudo yum update -y && sudo yum install -y epel-release && sudo yum install -y git gcc zlib-devel bzip2-devel readline-devel sqlite-devel openssl-devel libffi-devel xz-devel
            ```
        -   **Для CentOS 8 / RHEL 8 (`dnf`):**
            ```bash
            sudo dnf update -y && sudo dnf install -y make gcc zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel openssl-devel tk-devel libffi-devel xz-devel libuuid-devel gdbm-libs libnsl2 git
            ```
    *   **Установка `pyenv`:**
        ```bash
        git clone https://github.com/pyenv/pyenv.git ~/.pyenv
        ```
    *   **Настройка окружения:**
        Добавьте следующие команды в `~/.bashrc` (или `~/.zshrc`) для автоматической инициализации `pyenv`.
        ```bash
        echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
        echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
        echo -e 'if command -v pyenv 1>/dev/null 2>&1; then\n  eval "$(pyenv init -)"\nfi' >> ~/.bashrc
        source ~/.bashrc
        ```

*   **Установка и управление версиями Python:**
    *   **Просмотр доступных версий:**
        ```bash
        pyenv install --list
        ```
    *   **Установка нужной версии:**
        ```bash
        # Пример установки версии 3.10.4
        pyenv install 3.10.4
        ```
    *   **Выбор версии Python:**
        -   **Глобально:** `pyenv global 3.10.4` (версия по умолчанию для пользователя).
        -   **Локально:** `pyenv local 3.10.4` (версия для конкретного каталога, создает файл `.python-version`).
    *   **Просмотр версий:**
        -   `pyenv versions` — покажет все установленные версии.
        -   `pyenv version` — покажет активную версию.

*   **Установка и использование `pyenv-virtualenv`:**
    *   **Установка плагина:**
        ```bash
        git clone https://github.com/pyenv/pyenv-virtualenv.git $(pyenv root)/plugins/pyenv-virtualenv
        echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
        source ~/.bashrc
        ```
    *   **Создание и активация виртуального окружения:**
        ```bash
        # Создать окружение 'my-project-env' на базе Python 3.10.4
        pyenv virtualenv 3.10.4 my-project-env

        # Активировать его для текущего проекта (локально)
        pyenv local my-project-env

        # Теперь окружение активируется автоматически при входе в каталог.
        # Пакеты, установленные через pip, будут изолированы.
        pip install numpy pandas
        ```
