# Установка и настройка MariaDB

### Определения

**MariaDB** — это мощная, надежная и открытая реляционная система управления базами данных (СУБД), разработанная сообществом и являющаяся форком MySQL. Она широко используется для веб-приложений, аналитики и других задач, требующих высокой производительности и масштабируемости.

### Практические сценарии

#### Установка MariaDB в различных операционных системах

##### Установка из стандартных репозиториев

Это самый простой способ быстрой установки, который предоставляет стабильную, но не всегда последнюю версию MariaDB.

* **Для Ubuntu и Debian:**

    ```bash
    sudo apt update
    sudo apt install -y mariadb-server mariadb-client
    ```

* **Для CentOS:**

    ```bash
    sudo yum update
    sudo yum install -y mariadb mariadb-server
    ```

После установки рекомендуется проверить статус сервиса:

```bash
systemctl status mariadb
```

##### Установка из официального репозитория MariaDB (для Ubuntu/Debian)

Для получения конкретной или самой актуальной версии MariaDB рекомендуется использовать официальный репозиторий.

1. **Установка вспомогательных пакетов:**

    ```bash
    sudo apt update
    sudo apt install -y apt-transport-https curl
    ```

2. **Добавление GPG ключа:**

    ```bash
    sudo mkdir -p /etc/apt/keyrings
    sudo curl -o /etc/apt/keyrings/mariadb-keyring.pgp 'https://mariadb.org/mariadb_release_signing_key.pgp'
    ```

3. **Добавление репозитория:**
    Создайте файл `/etc/apt/sources.list.d/mariadb.sources`, указав необходимую версию MariaDB и дистрибутив Ubuntu.

    **Пример для MariaDB 11.3 и Ubuntu 22.04 (Jammy):**

    ```
    # MariaDB 11.3 repository list
    # https://mariadb.org/download/
    X-Repolib-Name: MariaDB
    Types: deb
    URIs: https://deb.mariadb.org/11.3/ubuntu
    Suites: jammy
    Components: main main/debug
    Signed-By: /etc/apt/keyrings/mariadb-keyring.pgp
    ```

    > **Примечание:** `jammy` соответствует Ubuntu 22.04. Для других версий Ubuntu (например, 20.04 `focal`) или версий MariaDB измените соответствующие значения в файле.

4. **Установка сервера:**

    ```bash
    sudo apt update
    sudo apt install -y mariadb-server
    ```

После установки сервис должен запуститься автоматически.

#### Базовая настройка безопасности

После установки рекомендуется выполнить базовую настройку безопасности. Подробное описание процесса с использованием утилиты `mysql_secure_installation` и рекомендации по защите SQL-сервера доступны в разделе **[Безопасная установка SQL-сервера](../SQL/installation_security.md)**.

#### Подключение к серверу MariaDB

После успешной установки и настройки безопасности можно подключиться к серверу. Изначально для пользователя `root` пароль может не требоваться (используется аутентификация через unix-сокет).

```bash
sudo mariadb
# или, используя псевдоним:
sudo mysql
```

### Дополнительная информация

* Актуальную информацию о версиях и инструкциях по установке всегда можно найти на [официальном сайте MariaDB](https://mariadb.org/download/).
* Для получения сведений о клиентских утилитах MariaDB, которые используются для взаимодействия с сервером, см. **[Клиентские утилиты MariaDB](client_utilities.md)**.
