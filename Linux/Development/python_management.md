# Управление версиями Python в Linux

**Python** — это высокоуровневый, универсальный и интерпретируемый язык программирования, который широко используется во многих областях, от веб-разработки до науки о данных.

Python является неотъемлемой частью большинства Linux-дистрибутивов, но системная версия Python часто бывает устаревшей. Этот документ описывает безопасные методы установки и управления несколькими версиями Python, не затрагивая системные пакеты.

**Критически важно:** Никогда не пытайтесь удалить, изменить или заменить системную версию Python (обычно `/usr/bin/python` или `/usr/bin/python2`). Системные утилиты, такие как `yum` в CentOS или `apt` в Ubuntu, зависят от нее, и ее изменение может привести к поломке операционной системы.

---

## Управление версиями с помощью `pyenv`

`pyenv` — это мощный инструмент, который позволяет легко устанавливать несколько версий Python и переключаться между ними. Он работает, изменяя переменную окружения `PATH` и создавая "прокладки" (shims) для исполняемых файлов Python.

### 1. Установка зависимостей для сборки

`pyenv` компилирует Python из исходного кода, поэтому необходимо установить зависимости для сборки.

**Для CentOS 7 (`yum`):**

```bash
sudo yum update -y
sudo yum install -y epel-release
sudo yum install -y git gcc zlib-devel bzip2-devel readline-devel sqlite-devel openssl-devel libffi-devel xz-devel
```

**Для CentOS 8 / RHEL 8 (`dnf`):**

```bash
sudo dnf update -y
sudo dnf install -y make gcc zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel openssl-devel tk-devel libffi-devel xz-devel libuuid-devel gdbm-libs libnsl2 git
```

### 2. Установка `pyenv`

Склонируйте репозиторий `pyenv` и настройте переменные окружения.

```bash
git clone https://github.com/pyenv/pyenv.git ~/.pyenv
```

Добавьте следующие строки в ваш `~/.bashrc` (или `~/.zshrc`):

```bash
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo -e 'if command -v pyenv 1>/dev/null 2>&1; then\n  eval "$(pyenv init -)"\nfi' >> ~/.bashrc
```

Примените изменения:

```bash
source ~/.bashrc
```

### 3. Установка нужной версии Python

Теперь вы можете установить любую необходимую версию Python.

```bash
# Посмотреть все доступные для установки версии
pyenv install --list

# Установить последнюю стабильную версию (например, 3.14.0)
pyenv install 3.14.0
```
Этот процесс может занять некоторое время.

### 4. Управление версиями

-   **Посмотреть все установленные версии:**

    ```bash
    pyenv versions
    ```

-   **Установить глобальную версию Python:**

    Эта версия будет использоваться по умолчанию во всей системе для вашего пользователя.

    ```bash
    pyenv global 3.14.0
    ```

-   **Установить локальную версию для проекта:**

    Эта версия будет активна только внутри конкретного каталога. `pyenv` создает файл `.python-version` для этого.

    ```bash
    # Находясь в каталоге проекта
    pyenv local 3.14.0
    ```

-   **Проверить активную версию:**

    ```bash
    python --version
    # или
    pyenv version
    ```

---

## Виртуальные окружения с `pyenv-virtualenv`

Изоляция зависимостей проекта — это стандартная практика. Плагин `pyenv-virtualenv` позволяет создавать виртуальные окружения, привязанные к конкретной версии Python, установленной через `pyenv`.

### Установка `pyenv-virtualenv`

Если вы устанавливали `pyenv` вручную, плагин нужно установить отдельно.

```bash
git clone https://github.com/pyenv/pyenv-virtualenv.git $(pyenv root)/plugins/pyenv-virtualenv
```
Добавьте в `~/.bashrc`:

```bash
echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
```

И перезапустите оболочку `source ~/.bashrc`.

### Создание и активация окружения

```bash
# Создать виртуальное окружение 'my-project-env' на базе Python 3.14.0
pyenv virtualenv 3.14.0 my-project-env

# Активировать окружение для текущего проекта
# (создаст файл .python-version в текущей директории)
pyenv local my-project-env

# Теперь, при входе в эту директорию, окружение будет активироваться автоматически.
# Установленные пакеты будут изолированы.
pip install requests
```
