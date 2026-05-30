# Управление репозиториями в Debian и Ubuntu (`sources.list`)

## Определения

**APT-репозиторий** — сервер или локальный каталог, хранящий `.deb` пакеты и метаданные в стандартизированной структуре (dists/, pool/, indices/). Позволяет системе APT находить, устанавливать и обновлять ПО.

**`sources.list`** — основной конфигурационный файл (`/etc/apt/sources.list`) и файлы в директории `/etc/apt/sources.list.d/`, указывающие APT, где искать пакеты.

**GPG-ключ репозитория** — криптографический ключ для проверки цифровой подписи `Release.gpg` или `InRelease`. Гарантирует подлинность пакетов и защиту от MitM-атак.

**Компонент репозитория** — категория пакетов внутри дистрибутива, разделяющая ПО по лицензии и уровню поддержки.

## Основные понятия

### Форматы файлов источников

#### One-line формат (традиционный)

Однострочная запись в `/etc/apt/sources.list` или `/etc/apt/sources.list.d/<name>.list`:

```
<type> [options] <url> <distribution> <component_1> <component_2> ...
```

#### DEB822 формат (современный, Debian 12+, Ubuntu 24.04+)

Многострочный формат в `/etc/apt/sources.list.d/<name>.sources`:

```
Types: deb
URIs: https://packages.example.com/repo
Suites: stable
Components: main
Architectures: amd64
Signed-By: /etc/apt/keyrings/example.gpg
Enabled: yes
```

**Поля фильтрации компонентов (APT 3.2+):**

В APT 3.2 в `.sources` файлах появились поля `Include` и `Exclude` для фильтрации пакетов репозитория:

```
Types: deb
URIs: https://packages.example.com/repo
Suites: stable
Components: main
Include: nginx*,certbot*
Exclude: *-dbg,*-dev
```

| Поле | Назначение | Пример |
| :--- | :--- | :--- |
| `Include` | whitelist пакетов (glob-паттерны) | `Include: nginx*,certbot*` |
| `Exclude` | blacklist пакетов (glob-паттерны) | `Exclude: *-dbg,*-dev` |

Это позволяет загружать только нужные пакеты, экономя трафик и место.

| Аспект | One-line | DEB822 |
| :--- | :--- | :--- |
| **Файл** | `.list` | `.sources` |
| **Несколько suit** | Отдельная строка на каждый | Один блок `Suites:` с запятыми |
| **Читаемость** | Ниже | Выше |
| **Миграция** | `apt modernize-sources` | — |

> **Рекомендация:** Для новых репозиториев на Debian 12+ и Ubuntu 24.04+ предпочтительнее DEB822 формат.

### Структура записи в `sources.list`

Каждая строка в файле `sources.list` (или в файле в `/etc/apt/sources.list.d/`) определяет источник пакетов:

```
<type> [options] <url> <distribution> <component_1> <component_2> ...
```

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`type`** | Тип архива | `deb` (бинарные), `deb-src` (исходники) |
| **`[options]`** | Необязательные параметры | `[arch=amd64]`, `[signed-by=/path/to/key.gpg]` |
| **`url`** | Базовый URL репозитория | `http://archive.ubuntu.com/ubuntu` |
| **`distribution`** | Кодовое имя или класс | `focal`, `bullseye`, `stable`, `testing` |
| **`component`** | Компонент репозитория | `main`, `restricted`, `universe` |

### Компоненты репозиториев

#### Debian

| Компонент | Описание | Лицензия | Поддержка |
| :--- | :--- | :--- | :--- |
| **`main`** | Свободное ПО, соответствует DFSG | Свободная | Официальная |
| **`contrib`** | Свободное ПО, зависящее от несвободного | Свободная | Официальная |
| **`non-free`** | Несвободное ПО | Проприетарная | Нет |
| **`non-free-firmware`** | Несвободные прошивки (с Debian 12) | Проприетарная | Нет |

#### Ubuntu

| Компонент | Описание | Лицензия | Поддержка |
| :--- | :--- | :--- | :--- |
| **`main`** | Свободное ПО, поддерживаемое Canonical | Свободная | Официальная (LTS: 5 лет) |
| **`restricted`** | Проприетарные драйверы | Проприетарная | Официальная (ограниченная) |
| **`universe`** | Свободное ПО, поддерживаемое сообществом | Свободная | Сообщество |
| **`multiverse`** | Проприетарное ПО, не поддерживаемое Canonical | Проприетарная | Нет |

### Роль GPG-ключей

При добавлении стороннего репозитория критически важен импорт его GPG-ключа. APT использует ключ для проверки цифровой подписи:

- **`Release.gpg`** — отдельный файл подписи (устаревший формат)
- **`InRelease`** — подпись внутри файла метаданных (современный формат)

Без валидной подписи APT не установит пакеты из репозитория.

### Управление ключами: современный и устаревший подходы

| Подход | Расположение | Команда | Статус |
| :--- | :--- | :--- | :--- |
| **Современный** | `/etc/apt/keyrings/` или `/usr/share/keyrings/` | `gpg --dearmor -o` | **Рекомендуемый** |
| **Устаревший** | `/etc/apt/trusted.gpg` | `apt-key add` | **Не рекомендуется** |

**Проблема устаревшего подхода:** `apt-key add` добавляет ключ в глобальное хранилище доверия, что означает доверие всем репозиториям, использующим этот ключ. Современный подход с `signed-by=` явно связывает репозиторий с его ключом.

## Практические сценарии

### Пример 1: Репозиторий Node.js на Debian/Ubuntu

1. **Установка зависимостей и GPG-ключа:**

    ```bash
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | \
        sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    ```

2. **Добавление репозитория с привязкой к ключу:**

    ```bash
    NODE_MAJOR=20
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | \
        sudo tee /etc/apt/sources.list.d/nodesource.list
    ```

    *Опция `[signed-by=...]` явно указывает APT, какой ключ использовать для этого репозитория.*

3. **Установка Node.js:**

    ```bash
    sudo apt-get update
    sudo apt-get install nodejs -y
    ```

### Пример 2: Репозиторий Nginx на Ubuntu

1. **Установка зависимостей и GPG-ключа:**

    ```bash
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg2 lsb-release ubuntu-keyring
    curl -fsSL https://nginx.org/keys/nginx_signing.key | \
        sudo gpg --dearmor -o /usr/share/keyrings/nginx-archive-keyring.gpg
    ```

2. **Добавление репозитория:**

    ```bash
    echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] \
        https://nginx.org/packages/ubuntu $(lsb_release -cs) nginx" | \
        sudo tee /etc/apt/sources.list.d/nginx.list
    ```

    *Команда `lsb_release -cs` автоматически подставляет кодовое имя дистрибутива.*

3. **Установка Nginx:**

    ```bash
    sudo apt-get update
    sudo apt-get install nginx -y
    ```

### Пример 3: Репозиторий Docker на Ubuntu

1. **Добавление GPG-ключа:**

    ```bash
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    ```

2. **Добавление репозитория:**

    ```bash
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    ```

3. **Установка Docker:**

    ```bash
    sudo apt-get update
    sudo apt-get install docker-ce docker-ce-cli containerd.io
    ```

    > **Полная инструкция:** см. SSoT-файл **[Установка Docker на Ubuntu](../../Docker/docker_install_ubuntu.md)**.

### Пример 4: Google Chrome

```bash
# Установка .deb пакета (репозиторий и ключ добавляются автоматически)
wget https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
sudo apt-get install -f

# Созданный файл репозитория:
# /etc/apt/sources.list.d/google-chrome.list
```

### Пример 5: PPA (Personal Package Archive) на Ubuntu

PPA — упрощённый механизм добавления репозиториев Launchpad.

```bash
# Добавление PPA через add-apt-repository
sudo add-apt-repository ppa:ondrej/nginx

# Автоматически:
# 1. Импортирует GPG-ключ с Launchpad
# 2. Создаёт файл в /etc/apt/sources.list.d/

# Обновление и установка
sudo apt-get update
sudo apt-get install nginx
```

Альтернативно вручную (современный метод):

```bash
# Импортировать ключ в изолированное хранилище
sudo gpg --keyserver keyserver.ubuntu.com --recv-keys <KEY_ID>
sudo gpg --export --armor <KEY_ID> | \
    sudo gpg --dearmor -o /etc/apt/keyrings/ondrej-nginx.gpg

# Добавить репозиторий с привязкой к ключу
echo "deb [signed-by=/etc/apt/keyrings/ondrej-nginx.gpg] \
    http://ppa.launchpad.net/ondrej/nginx/ubuntu $(lsb_release -cs) main" | \
    sudo tee /etc/apt/sources.list.d/ondrej-nginx.list
```

### Пример 6: Локальное зеркало репозитория

Создание зеркала для автономной или ускоренной работы (подробнее: [Зеркалирование репозиториев](./apt_mirror/practical_scenarios.md)):

```bash
# Настройка клиента на использование локального зеркала
echo "deb http://mirror.local/ubuntu focal main restricted universe multiverse" | \
    sudo tee /etc/apt/sources.list.d/local-mirror.list
```

> **Примечание:** Полная инструкция по созданию зеркала — в [apt_mirror/practical_scenarios.md](./apt_mirror/practical_scenarios.md).

## Дополнительная информация

### Проверка источников пакетов с `apt policy`

Команда `apt policy` показывает доступность пакета, установленную версию и приоритеты источников.

```bash
# Информация о пакете
apt policy nginx

# Пример вывода:
# nginx:
#   Установлен: 1.20.2-1~focal
#   Кандидат:   1.20.2-1~focal
#   Таблица версий:
#  *** 1.20.2-1~focal 500
#         500 https://nginx.org/packages/ubuntu focal/nginx amd64 Packages
#      1.18.0-0ubuntu1.4 500
#         500 http://archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages
```

Это демонстрирует установку новой версии из стороннего репозитория `nginx.org`. Для тонкой настройки приоритетов используется **[Apt Pinning](./deb_apt_pinning.md)**.

### Официальные зеркала Debian/Ubuntu

| Дистрибутив | Основное зеркало | Зеркало безопасности |
| :--- | :--- | :--- |
| **Debian** | `deb.debian.org` | `security.debian.org` |
| **Ubuntu** | `archive.ubuntu.com` | `security.ubuntu.com` |
| **Ubuntu (зеркала)** | `cc.archive.ubuntu.com` (cc = код страны) | — |

### Типовые проблемы и решения

| Проблема | Решение |
| :--- | :--- |
| **NO_PUBKEY** | Импортировать ключ: `curl -fsSL <URL>/key.gpg \| sudo gpg --dearmor -o /etc/apt/keyrings/repo.gpg`, добавить `[signed-by=...]` в `sources.list` |
| **GPG error** | Перейти на современный метод с `signed-by=` и `/etc/apt/keyrings/` |
| **404 Not Found** | Актуализировать кодовое имя дистрибутива в `sources.list` |
| **Certificate verification failed** | Проверить `ca-certificates`, дату системы, proxy |
| **Repository not found** | Проверить URL, наличие компонента в дистрибутиве |

### Безопасность репозиториев

1. **Используйте `[signed-by=]`** для явной привязки ключа к репозиторию
2. **Храните ключи в `/etc/apt/keyrings/`** в формате `.gpg`
3. **Предпочитайте HTTPS** для `url` репозиториев
4. **Регулярно обновляйте кэш** (`apt update`)
5. **Проверяйте подписи** при установке из сторонних источников
6. **Избегайте `apt-key add`** — этот метод устарел
