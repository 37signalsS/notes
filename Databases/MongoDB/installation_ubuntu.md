# Установка MongoDB Community Edition на Ubuntu

## Практические сценарии

### 1. Импорт GPG ключа

Для установки из официального репозитория MongoDB необходимо сначала добавить его GPG-ключ в систему.

```bash
# Устанавливаем зависимости, если их нет
sudo apt-get install gnupg curl

# Импортируем ключ MongoDB
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
```

### 2. Добавление репозитория

Создайте файл `/etc/apt/sources.list.d/mongodb-org-7.0.list`, чтобы `apt` знал, откуда скачивать пакеты.

```bash
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
```

### 3. Установка пакетов

Обновите список пакетов и установите мета-пакет `mongodb-org`, который включает в себя все необходимые компоненты (сервер, клиент, утилиты).

```bash
sudo apt-get update
sudo apt-get install -y mongodb-org
```

### 4. Управление службой

После установки служба `mongod` не запускается автоматически.

- **Запустить службу:**

    ```bash
    sudo systemctl start mongod
    ```

- **Проверить статус службы:**

    ```bash
    sudo systemctl status mongod
    ```

- **Добавить в автозагрузку:**

    ```bash
    sudo systemctl enable mongod
    ```

### 5. Подключение к базе данных

Для подключения к базе данных используется `mongosh` (новый shell, который устанавливается вместе с сервером).

```bash
mongosh
```

## Дополнительная информация

- **Версия Ubuntu**: В примере добавления репозитория используется кодовое имя `jammy` для Ubuntu 22.04. Для других версий Ubuntu (например, `focal` для 20.04) необходимо изменить его в файле `/etc/apt/sources.list.d/mongodb-org-7.0.list`.
