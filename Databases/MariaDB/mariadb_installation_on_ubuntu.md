# Установка MariaDB в Ubuntu

Хотя MariaDB может находиться в стандартных репозиториях Ubuntu, для получения конкретной или последней версии рекомендуется использовать официальный репозиторий MariaDB.

## Пошаговая инструкция

Процесс включает в себя добавление GPG-ключа репозитория и создание файла с его описанием.

1.  **Установка вспомогательных пакетов:**
    ```bash
    sudo apt update
    sudo apt install -y apt-transport-https curl
    ```

2.  **Добавление GPG ключа:**
    Ключ необходим для проверки подлинности пакетов.
    ```bash
    sudo mkdir -p /etc/apt/keyrings
    sudo curl -o /etc/apt/keyrings/mariadb-keyring.pgp 'https://mariadb.org/mariadb_release_signing_key.pgp'
    ```

3.  **Добавление репозитория:**
    Создайте файл `/etc/apt/sources.list.d/mariadb.sources`. Его содержимое определяет версию и дистрибутив.

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
    > **Примечание:** `jammy` соответствует Ubuntu 22.04. Для других версий Ubuntu (например, 20.04 `focal`) измените значение `Suites`. Версию MariaDB можно изменить, поменяв ее в `URIs` (например, на `10.11`).

4.  **Установка сервера:**
    После добавления репозитория обновите список пакетов и установите `mariadb-server`.
    ```bash
    sudo apt update
    sudo apt install -y mariadb-server
    ```

## Проверка установки

После установки сервис должен запуститься автоматически.

- **Проверить статус сервиса:**
  ```bash
  systemctl status mariadb
  ```

- **Подключиться к серверу:**
  Изначально для пользователя `root` пароль не требуется (используется аутентификация через unix-сокет).
  ```bash
  sudo mariadb
  ```
  Или, как псевдоним, можно использовать `mysql`.
  ```bash
  sudo mysql
  ```
  Внутри консоли вы увидите приветствие `Welcome to the MariaDB monitor`.
