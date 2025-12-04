# Управление репозиториями в Debian и Ubuntu (`sources.list`)

Файл `/etc/apt/sources.list` и файлы в директории `/etc/apt/sources.list.d/` определяют, откуда система управления пакетами APT (Advanced Package Tool) будет загружать и устанавливать пакеты.

Каждая строка в `sources.list` имеет следующую структуру:

```
<type> <url> <distribution> <component_1> <component_2> ...
```

-   **`type`**: Тип архива.
    -   `deb`: бинарные пакеты (скомпилированные приложения).
    -   `deb-src`: исходные коды пакетов.
-   **`url`**: Базовый URL репозитория.
-   **`distribution`**: Имя выпуска (кодовое имя) или класс выпуска (например, `buster` для Debian, `focal` для Ubuntu).
-   **`component`**: Компоненты репозитория, которые различаются между Debian и Ubuntu.

## Компоненты репозиториев

### Debian
-   `main`: Основные, полностью свободные пакеты, соответствующие Debian Free Software Guidelines.
-   `contrib`: Пакеты, которые сами по себе свободны, но зависят от несвободных пакетов.
-   `non-free`: Пакеты, которые не соответствуют Debian Free Software Guidelines.
-   `non-free-firmware`: Несвободные прошивки, необходимые для работы некоторого оборудования (появился в Debian 12).

### Ubuntu
-   `main`: Основные, полностью свободные пакеты, поддерживаемые Canonical.
-   `restricted`: Проприетарные драйверы для устройств.
-   `universe`: Свободное ПО, поддерживаемое сообществом.
-   `multiverse`: Проприетарное ПО, не поддерживаемое Canonical.

---

## Добавление сторонних репозиториев

При добавлении сторонних репозиториев крайне важно импортировать GPG-ключ, которым подписаны пакеты. Это позволяет системе проверить подлинность пакетов, убедившись, что они получены именно от заявленного разработчика и не были изменены.

### Пример 1: Репозиторий Node.js на Debian

1.  **Установка зависимостей и GPG-ключа:**
    ```bash
    sudo apt update
    sudo apt install -y ca-certificates curl gnupg
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    ```

2.  **Добавление репозитория NodeSource:**
    ```bash
    NODE_MAJOR=24
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
    ```

3.  **Установка Node.js:**
    ```bash
    sudo apt update
    sudo apt install nodejs -y
    ```

### Пример 2: Репозиторий Nginx на Ubuntu

1.  **Установка зависимостей и импорт GPG-ключа:**
    ```bash
    sudo apt update
    sudo apt install -y curl gnupg2 ca-certificates lsb-release ubuntu-keyring
    curl -fsSL https://nginx.org/keys/nginx_signing.key | sudo gpg --dearmor -o /usr/share/keyrings/nginx-archive-keyring.gpg
    ```

2.  **Добавление репозитория Nginx:**
    ```bash
    echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] https://nginx.org/packages/ubuntu `lsb_release -cs` nginx" | sudo tee /etc/apt/sources.list.d/nginx.list
    ```
    *Примечание: `lsb_release -cs` автоматически подставит кодовое имя вашего дистрибутива.*

3.  **Установка Nginx:**
    ```bash
    sudo apt update
    sudo apt install nginx -y
    ```

### Пример 3: Репозиторий Oracle MySQL (через `.deb` пакет)

Некоторые производители предоставляют `.deb` пакет, который автоматически настраивает репозиторий.

1.  **Загрузка и установка `.deb` пакета:**
    ```bash
    wget https://dev.mysql.com/get/mysql-apt-config_0.8.22-1_all.deb
    sudo dpkg -i mysql-apt-config_0.8.22-1_all.deb
    ```
    *Во время установки будет предложено выбрать нужные компоненты.*

2.  **Установка MySQL:**
    ```bash
    sudo apt update
    sudo apt install mysql-server -y
    ```
---

## Проверка источников пакетов с помощью `apt policy`

Команда `apt policy <package_name>` позволяет узнать, из каких репозиториев доступен пакет, его текущую установленную версию и приоритеты различных источников. APT выбирает пакет из источника с наивысшим приоритетом.

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
Это показывает, что установлена более новая версия из стороннего репозитория `nginx.org`.

---
**Связанные темы:**
*   [Обзор управления пакетами в Linux](./linux_package_management_overview.md)
*   [Приоритизация пакетов с помощью APT Pinning](./deb_apt_pinning.md)
