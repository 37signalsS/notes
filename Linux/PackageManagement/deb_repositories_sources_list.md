# Управление репозиториями в Debian и Ubuntu (`sources.list`)

## Определения

**APT-репозиторий** — сервер или локальный каталог, хранящий `.deb` пакеты и метаданные в стандартизированной структуре. Позволяет системе APT находить, устанавливать и обновлять ПО.

**`sources.list`** — основной конфигурационный файл (`/etc/apt/sources.list`) и файлы в директории `/etc/apt/sources.list.d/`, указывающие APT, где искать пакеты.

## Основные понятия

### Структура записи в `sources.list`

Каждая строка в файле `sources.list` (или в файле в `/etc/apt/sources.list.d/`) определяет источник пакетов и имеет структуру:

```
<type> [options] <url> <distribution> <component_1> <component_2> ...
```

*   **`type`**: Тип архива (`deb` для бинарных пакетов, `deb-src` для исходных кодов).
*   **`[options]`**: Необязательные параметры (например, `[arch=amd64]`, `[signed-by=/path/to/key.gpg]`).
*   **`url`**: Базовый URL репозитория.
*   **`distribution`**: Кодовое имя выпуска (например, `focal`, `bullseye`) или класс (`stable`, `testing`).
*   **`component`**: Компоненты репозитория, разделяющие ПО по лицензии и уровню поддержки.

### Компоненты репозиториев

#### Debian
*   `main`: Свободное ПО (DFSG).
*   `contrib`: Свободное ПО, зависящее от несвободного.
*   `non-free`: Несвободное ПО.
*   `non-free-firmware`: Несвободные прошивки (с Debian 12).

#### Ubuntu
*   `main`: Свободное ПО, поддерживаемое Canonical.
*   `restricted`: Проприетарные драйверы.
*   `universe`: Свободное ПО, поддерживаемое сообществом.
*   `multiverse`: Проприетарное ПО, не поддерживаемое Canonical.

### Роль GPG-ключей

При добавлении стороннего репозитория критически важен импорт его GPG-ключа. APT использует ключ для проверки цифровой подписи `Release.gpg` в репозитории, гарантируя подлинность пакетов. Без валидной подписи APT не установит пакеты.

## Практические сценарии

### Пример 1: Репозиторий Node.js на Debian

1.  **Установка зависимостей и GPG-ключа:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    ```

2.  **Добавление репозитория с привязкой к ключу:**
    ```bash
    NODE_MAJOR=24
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
    ```
    *Опция `[signed-by=...]` явно указывает APT, какой ключ использовать для этого репозитория.*

3.  **Установка Node.js:**
    ```bash
    sudo apt-get update
    sudo apt-get install nodejs -y
    ```

### Пример 2: Репозиторий Nginx на Ubuntu

1.  **Установка зависимостей и GPG-ключа:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg2 lsb-release ubuntu-keyring
    curl -fsSL https://nginx.org/keys/nginx_signing.key | sudo gpg --dearmor -o /usr/share/keyrings/nginx-archive-keyring.gpg
    ```

2.  **Добавление репозитория:**
    ```bash
    echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] https://nginx.org/packages/ubuntu `lsb_release -cs` nginx" | sudo tee /etc/apt/sources.list.d/nginx.list
    ```
    *Команда `lsb_release -cs` автоматически подставляет кодовое имя дистрибутива.*

3.  **Установка Nginx:**
    ```bash
    sudo apt-get update
    sudo apt-get install nginx -y
    ```

## Дополнительная информация

### Управление ключами: современный и устаревший подходы

*   **Современный подход (рекомендуемый):** GPG-ключи хранятся в `.gpg` формате в `/etc/apt/keyrings` или `/usr/share/keyrings`. Опция `signed-by=` в `sources.list` явно связывает репозиторий с его ключом, обеспечивая безопасность.
*   **Устаревший подход:** `apt-key add` добавлял ключ в глобальное хранилище `/etc/apt/trusted.gpg`. Этот метод не рекомендуется из-за общего доверия ко всем репозиториям.

### Проверка источников пакетов с `apt policy`

Команда `apt policy <package_name>` показывает доступность пакета, установленную версию и приоритеты источников.

```bash
apt policy nginx
```
Пример вывода:
```
nginx:
  Установлен: 1.20.2-1~focal
  Кандидат:   1.20.2-1~focal
  Таблица версий:
 *** 1.20.2-1~focal 500
        500 https://nginx.org/packages/ubuntu focal/nginx amd64 Packages
     1.18.0-0ubuntu1.4 500
        500 http://archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages
```
Это демонстрирует установку новой версии из стороннего репозитория `nginx.org`. Для тонкой настройки приоритетов используется **[Apt Pinning](./deb_apt_pinning.md)**.
