# Установка MongoDB на Ubuntu

## Определения

**MongoDB Community Edition** — бесплатная версия документо-ориентированной NoSQL СУБД с открытым исходным кодом.

- **`mongod`**: Основной серверный процесс (демон) базы данных.
- **`mongosh`**: Современная интерактивная JavaScript-оболочка (shell), заменившая устаревший `mongo` shell в версии 5.0+.
- **`mongodb-org`**: Мета-пакет, устанавливающий сервер, оболочку, инструменты и настройки конфигурации.
- **SSPL (Server Side Public License)** — лицензия, под которой распространяется MongoDB, ограничивающая предоставление СУБД в качестве платного облачного сервиса третьими лицами.

## Базовые концепции

### Требования и подготовка (Prerequisites)

Перед началом установки необходимо убедиться, что целевая система соответствует минимальным требованиям:

1.  **Аппаратная поддержка AVX:** Начиная с версии 5.0+, для работы MongoDB требуется процессор с поддержкой набора инструкций **AVX**.
    *   **Проверка:** `grep -q avx /proc/cpuinfo && echo "AVX supported" || echo "AVX NOT supported"`
2.  **Операционная система:** Официально поддерживаются 64-битные версии Ubuntu (AMD64 и ARM64).
3.  **Файловая система:** Рекомендуется использовать **XFS**. Использование `ext4` допустимо, но WiredTiger работает эффективнее с XFS благодаря лучшей обработке разреженных файлов и `fsync`.
4.  **Сетевые настройки:** Порт по умолчанию — `27017`. Убедитесь, что фаервол (`ufw`) не блокирует локальные соединения.

## Практические сценарии

### 1. Подготовка и импорт GPG-ключей

Импорт ключей необходим для проверки подлинности пакетов. В современных версиях Ubuntu рекомендуется использовать директорию `/usr/share/keyrings/`.

```bash
sudo apt-get install -y gnupg curl

# Импорт ключа для MongoDB 8.0
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
```
**Валидация:** Проверьте наличие файла: `ls -l /usr/share/keyrings/mongodb-server-8.0.gpg`.

### 2. Настройка официального репозитория

Для получения актуальных обновлений безопасности используйте репозиторий `repo.mongodb.org`.

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

### 3. Установка и фиксация версии (Pinning)

Фиксация версии критична для Production-сред, чтобы избежать автоматического обновления мажорных версий при выполнении `apt upgrade`.

```bash
sudo apt-get update
sudo apt-get install -y mongodb-org

# Фиксация пакетов
echo "mongodb-org hold" | sudo dpkg --set-selections
echo "mongodb-org-database hold" | sudo dpkg --set-selections
echo "mongodb-org-server hold" | sudo dpkg --set-selections
echo "mongodb-org-mongosh hold" | sudo dpkg --set-selections
echo "mongodb-org-tools hold" | sudo dpkg --set-selections
```

### 4. Тюнинг ОС для MongoDB 8.0+

Для обеспечения производительности WiredTiger необходимо применить следующие настройки:

1.  **Transparent Huge Pages (THP):** Должны быть отключены, так как они вызывают непредсказуемые задержки (latency).
    *   Создайте systemd-юнит или добавьте в `/etc/rc.local`:
    ```bash
    echo "never" | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
    echo "never" | sudo tee /sys/kernel/mm/transparent_hugepage/defrag
    ```
2.  **Лимиты ресурсов (`ulimit`):**
    *   Отредактируйте `/etc/security/limits.conf`:
    ```text
    mongodb soft nofile 64000
    mongodb hard nofile 64000
    mongodb soft nproc 64000
    mongodb hard nproc 64000
    ```
3.  **Swap и память:**
    *   `vm.swappiness = 1` (в `/etc/sysctl.conf`).
    *   На NUMA-системах: `sudo apt install numactl` и запускайте через `numactl --interleave=all`.

### 5. Управление службой и проверка здоровья

```bash
sudo systemctl daemon-reload
sudo systemctl enable mongod
sudo systemctl start mongod

# Проверка статуса
sudo systemctl status mongod # Должен быть "active (running)"
# Проверка через лог
grep "Waiting for connections" /var/log/mongodb/mongod.log
```

### 6. Первоначальная настройка безопасности (RBAC)

**Внимание:** По умолчанию MongoDB устанавливается без авторизации. Это небезопасно.

1.  **Создание администратора:**
    ```javascript
    // Запустите mongosh
    use admin
    db.createUser({
      user: "root_admin",
      pwd: passwordPrompt(),
      roles: [ { role: "root", db: "admin" } ]
    })
    ```
2.  **Включение авторизации в `/etc/mongod.conf`:**
    ```yaml
    security:
      authorization: enabled
    ```
3.  **Перезапуск:** `sudo systemctl restart mongod`.

## Диагностика и решение проблем (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **`Illegal instruction (core dumped)`** | CPU не поддерживает AVX. | Перейдите на старое оборудование или используйте MongoDB < 5.0 (не рекомендуется). |
| **GPG error: The following signatures were invalid** | Устаревший или неверный GPG-ключ. | Удалите старый ключ и повторите Шаг 1. |
| **`mongod` падает при старте с ошибкой `WiredTiger error (13)`** | Проблемы с правами на `/var/lib/mongodb`. | `sudo chown -R mongodb:mongodb /var/lib/mongodb`. |
| **Служба `active (running)`, но подключения не проходят** | Ошибка привязки IP в `bindIp`. | Проверьте `net.bindIp` в `mongod.conf`. Убедитесь, что IP существует. |

## Дополнительная информация

- **Обзор и глубокая теория**: **[Обзор MongoDB](./mongodb.md)**.
- **Инфраструктура как код**: **[Ansible-роль для MongoDB](../../Ansible/examples/mongodb_setup.md)**.
- **Kubernetes**: **[Развертывание через Оператор](./mongodb_operator.md)**.
- **Мониторинг**: **[Экспортеры для Prometheus](../../Prometheus/Exporters/other_exporters.md)**.
