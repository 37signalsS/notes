# Установка MongoDB на Ubuntu

## Определения

**MongoDB Community Edition** — бесплатная версия документо-ориентированной NoSQL СУБД с открытым исходным кодом.

- **`mongod`**: Основной серверный процесс (демон) базы данных.
- **`mongosh`**: Современная интерактивная JavaScript-оболочка (shell), заменившая устаревший `mongo` shell.
- **`mongodb-org`**: Мета-пакет, устанавливающий сервер, оболочку, инструменты и настройки конфигурации.
- **SSPL (Server Side Public License)** — лицензия, ограничивающая предоставление MongoDB в качестве платного сервиса третьими лицами.

## Базовые концепции

### Требования и подготовка
- **Репозитории**: Рекомендуется использовать официальный источник `repo.mongodb.org`, так как пакеты в стандартных репозиториях Ubuntu часто устарели.
- **Архитектура**: x86_64 или ARM64.
- **Файловая система**: **XFS** является предпочтительной для движка WiredTiger. `ext4` допустима, но менее производительна при высоких нагрузках.
- **Фиксация версии (Pinning)**: Для предотвращения случайных обновлений в production-средах пакеты необходимо "замораживать".

## Практические сценарии

### 1. Подготовка и импорт ключей

Установите необходимые зависимости и импортируйте GPG-ключ для проверки подписи пакетов MongoDB 8.0+:

```bash
sudo apt-get install -y gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
```

### 2. Настройка репозитория под версию ОС

Выберите и выполните команду, соответствующую вашей версии Ubuntu:

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

Обновите список пакетов и установите мета-пакет `mongodb-org`:

```bash
sudo apt-get update
sudo apt-get install -y mongodb-org

# Фиксация текущей версии для предотвращения нежелательных обновлений
echo "mongodb-org hold" | sudo dpkg --set-selections
echo "mongodb-org-database hold" | sudo dpkg --set-selections
echo "mongodb-org-server hold" | sudo dpkg --set-selections
echo "mongodb-org-mongosh hold" | sudo dpkg --set-selections
echo "mongodb-org-tools hold" | sudo dpkg --set-selections
```

### 4. Настройка системы (Тюнинг)

Для стабильной работы MongoDB 8.0+ требуются специфические настройки ядра Linux. Подробнее: **[Оптимизация памяти в Linux](../../Linux/Core/memory/performance_tuning.md)**.

1. **Отключение Transparent Huge Pages (THP)**:
   MongoDB рекомендует отключать THP, так как они могут вызвать деградацию производительности и задержки.
   ```bash
   echo "never" | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
   echo "never" | sudo tee /sys/kernel/mm/transparent_hugepage/defrag
   ```
2. **Настройка лимитов (ulimit)**:
   Убедитесь, что лимиты на количество открытых файлов (`nofile`) и процессов (`nproc`) установлены корректно (рекомендуется ≥ 64000).
3. **Swap и NUMA**:
   - Рекомендуется установить `vm.swappiness = 1`.
   - На многопроцессорных системах запускайте `mongod` через `numactl --interleave=all`.

### 5. Управление службой и проверка

```bash
sudo systemctl daemon-reload
sudo systemctl enable mongod
sudo systemctl start mongod

# Проверка статуса службы
sudo systemctl status mongod
```

### 6. Первичная настройка безопасности (RBAC)

По умолчанию MongoDB слушает только `127.0.0.1` и не требует пароля. **Обязательно** настройте администратора до открытия доступа извне:

1. Подключитесь локально: `mongosh`.
2. Создайте администратора:
   ```javascript
   use admin
   db.createUser({
     user: "admin",
     pwd: passwordPrompt(),
     roles: [ { role: "root", db: "admin" } ]
   })
   ```
3. Включите авторизацию в `/etc/mongod.conf`:
   ```yaml
   security:
     authorization: enabled
   ```
4. Перезапустите службу: `sudo systemctl restart mongod`.

## Дополнительная информация

- **Обзор и концепции (SSoT)**: **[Обзор MongoDB](./mongodb.md)**.
- **Автоматизация**: **[Развертывание через Ansible](../../Ansible/examples/mongodb_setup.md)**.
- **Логи**: По умолчанию находятся в `/var/log/mongodb/mongod.log`.
- **Данные**: По умолчанию находятся в `/var/lib/mongodb`.
- **Мониторинг**: Используйте `mongodb_exporter` для интеграции с **[Prometheus](../../Prometheus/Exporters/other_exporters.md)**.
