# Установка MongoDB на Ubuntu

## Определения

**MongoDB Community Edition** — бесплатная версия MongoDB с открытым исходным кодом, распространяемая по лицензии SSPL.

- **mongod:** Основной серверный процесс (демон) базы данных.
- **mongosh:** Современная интерактивная JavaScript-оболочка (shell) для администрирования и работы с данными.
- **mongodb-org:** Мета-пакет, устанавливающий сервер, оболочку, инструменты экспорта/импорта и настройки конфигурации.

## Базовые концепции

### Версионность и репозитории
Для установки рекомендуется использовать официальный репозиторий MongoDB, так как пакеты в стандартных репозиториях Ubuntu часто устарели. На июль 2026 года актуальной стабильной веткой является **8.0** (с минорными обновлениями до 8.x).

### Системные требования
- **Архитектура:** x86_64 или ARM64.
- **ОС:** Ubuntu 22.04 LTS (Jammy), 24.04 LTS (Noble), 26.04 LTS (Resolute).
- **Файловая система:** Рекомендуется XFS для WiredTiger (ext4 допустима, но менее производительна).

## Практические сценарии

### 1. Подготовка и импорт ключей

Установите необходимые зависимости и импортируйте GPG-ключ для проверки подписи пакетов:

```bash
sudo apt-get install -y gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
```

### 2. Настройка репозитория

Выберите команду в зависимости от версии вашей ОС:

**Ubuntu 26.04 (Resolute):**
```bash
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu resolute/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
```

**Ubuntu 24.04 (Noble):**
```bash
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
```

**Ubuntu 22.04 (Jammy):**
```bash
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
```

### 3. Установка и фиксация версии

Обновите список пакетов и установите MongoDB. Для предотвращения нежелательных обновлений рекомендуется «заморозить» текущую версию:

```bash
sudo apt-get update
sudo apt-get install -y mongodb-org

# Фиксация версии (опционально, но рекомендуется)
echo "mongodb-org hold" | sudo dpkg --set-selections
echo "mongodb-org-database hold" | sudo dpkg --set-selections
echo "mongodb-org-server hold" | sudo dpkg --set-selections
echo "mongodb-org-mongosh hold" | sudo dpkg --set-selections
echo "mongodb-org-tools hold" | sudo dpkg --set-selections
```

### 4. Настройка системы (Тюнинг)

Для стабильной работы MongoDB требуются специфические настройки ядра.

**Отключение Transparent Huge Pages (THP):**
MongoDB рекомендует отключать THP, так как они могут вызвать деградацию производительности. См. также: **[Тюнинг памяти в Linux](../../Linux/Core/memory/performance_tuning.md)**.

**Настройка лимитов (ulimit):**
Убедитесь, что лимиты на количество открытых файлов (`nofile`) и процессов (`nproc`) установлены корректно (обычно ≥ 64000).

### 5. Управление службой

```bash
sudo systemctl daemon-reload
sudo systemctl enable mongod
sudo systemctl start mongod

# Проверка статуса
sudo systemctl status mongod
```

### 6. Первичная настройка безопасности

По умолчанию MongoDB слушает только `127.0.0.1` и не требует пароля. После установки необходимо:
1. Создать администратора через `mongosh`.
2. Включить авторизацию в `/etc/mongod.conf`.

```yaml
security:
  authorization: enabled
```

## Дополнительная информация

- **Обзор и концепции:** **[Обзор MongoDB](./mongodb.md)**.
- **Автоматизация:** **[Развертывание через Ansible](../../Ansible/examples/mongodb_setup.md)**.
- **Логи:** По умолчанию находятся в `/var/log/mongodb/mongod.log`.
- **Данные:** По умолчанию находятся в `/var/lib/mongodb`.
