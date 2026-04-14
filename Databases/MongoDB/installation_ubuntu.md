# Установка MongoDB на Ubuntu

## Определения

**MongoDB Community Edition** — бесплатная версия MongoDB с открытым исходным кодом. Текущая стабильная версия — 8.0.

## Основные концепции

### Компоненты

- **mongod** — серверный процесс MongoDB.
- **mongosh** — командная оболочка для взаимодействия с БД.

## Практические сценарии

### 1. Импорт GPG-ключа

```bash
sudo apt-get install gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
```

### 2. Настройка репозитория

Создайте файл `/etc/apt/sources.list.d/mongodb-org-8.0.list`:

**Ubuntu 24.04 (Noble):**

```bash
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
```

**Ubuntu 22.04 (Jammy):**

```bash
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
```

**Ubuntu 20.04 (Focal):**

```bash
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
```

### 3. Установка пакетов

```bash
sudo apt-get update
sudo apt-get install -y mongodb-org
```

### 4. Управление службой

```bash
sudo systemctl start mongod
sudo systemctl status mongod
sudo systemctl enable mongod
```

**Остановка и перезапуск:**

```bash
sudo systemctl stop mongod
sudo systemctl restart mongod
```

### 5. Подключение к БД

```bash
mongosh
```

## Дополнительная информация

- **Основная документация:** **[Основы MongoDB](./mongodb.md)**.
- **Версии Ubuntu:** Кодовые имена: `noble` (24.04), `jammy` (22.04), `focal` (20.04).
