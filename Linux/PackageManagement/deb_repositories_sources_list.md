# Управление репозиториями в Debian и Ubuntu (`sources.list`)

## Определения

*   **APT-репозиторий**: Сервер или локальный каталог, который хранит `.deb` пакеты и метаданные, организованные в стандартизированную структуру. Он позволяет системе управления пакетами APT находить, устанавливать и обновлять ПО.
*   **`sources.list`**: Основной конфигурационный файл (`/etc/apt/sources.list`) и файлы в директории `/etc/apt/sources.list.d/`, которые указывают APT, где искать пакеты.

## Базовые концепции

### Структура записи в `sources.list`

Каждая строка в `sources.list` (или в файле в `/etc/apt/sources.list.d/`) определяет один источник пакетов и имеет следующую структуру:
```
<type> [options] <url> <distribution> <component_1> <component_2> ...
```
-   **`type`**: Тип архива (`deb` для бинарных пакетов, `deb-src` для исходных кодов).
-   **`[options]`**: Необязательные параметры в квадратных скобках, например, `[arch=amd64]` для указания архитектуры или `[signed-by=/path/to/key.gpg]` для связи репозитория с GPG-ключом.
-   **`url`**: Базовый URL репозитория.
-   **`distribution`**: Кодовое имя выпуска (например, `focal`, `bullseye`) или класс (`stable`, `testing`).
-   **`component`**: Компоненты репозитория, разделяющие ПО по лицензии и уровню поддержки.

### Компоненты репозиториев

#### Debian
-   `main`: Полностью свободное ПО, соответствующее Debian Free Software Guidelines (DFSG).
-   `contrib`: Свободное ПО, которое зависит от несвободного.
-   `non-free`: Несвободное ПО.
-   `non-free-firmware`: Несвободные прошивки, необходимые для работы оборудования (с Debian 12).

#### Ubuntu
-   `main`: Свободное ПО, официально поддерживаемое Canonical.
-   `restricted`: Проприетарные драйверы для устройств.
-   `universe`: Свободное ПО, поддерживаемое сообществом.
-   `multiverse`: Проприетарное ПО, не поддерживаемое Canonical.

### Роль GPG-ключей

При добавлении стороннего репозитория крайне важно импортировать его GPG-ключ. APT использует этот ключ для проверки цифровой подписи файла `Release.gpg` в репозитории. Это гарантирует, что пакеты не были подменены и действительно пришли из доверенного источника. **Без валидной подписи APT откажется устанавливать пакеты из репозитория.**

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
    *Команда `lsb_release -cs` автоматически подставляет кодовое имя вашего дистрибутива (например, `focal`).*

3.  **Установка Nginx:**
    ```bash
    sudo apt-get update
    sudo apt-get install nginx -y
    ```

## Расширенные детали

### Управление ключами: новая и старая практика

-   **Современный подход (рекомендуемый):** GPG-ключи хранятся в формате `.gpg` в директориях `/etc/apt/keyrings` или `/usr/share/keyrings`. В файле `sources.list` используется опция `signed-by=`, чтобы явно связать репозиторий с его ключом. Это безопасно, так как один ключ доверяет только одному конкретному репозиторию.
-   **Устаревший подход:** Ранее использовалась команда `apt-key add`, которая добавляла ключ в глобальное хранилище `/etc/apt/trusted.gpg`. Этот метод не рекомендуется, так как любой ключ в этом хранилище считается доверенным для *любого* репозитория в системе, что создает вектор для атаки.

### Проверка источников пакетов с `apt policy`

Команда `apt policy <package_name>` позволяет узнать, из каких репозиториев доступен пакет, его текущую установленную версию и приоритеты различных источников.
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
Это показывает, что установлена более новая версия из стороннего репозитория `nginx.org`. Для тонкой настройки приоритетов используется **[Apt Pinning](./deb_apt_pinning.md)**.