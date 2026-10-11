# Установка MongoDB на Ubuntu

**Актуально для:** MongoDB 8.0.x (8.0.28 — последний patch на июль 2026)

---

## Определения

*   **MongoDB Community Edition** — бесплатная версия документо-ориентированной NoSQL СУБД с открытым исходным кодом.
*   **`mongod`** — основной серверный процесс (демон) базы данных.
*   **`mongosh`** — современная интерактивная JavaScript-оболочка (shell), заменившая устаревший `mongo` shell в версии 5.0+.
*   **`mongodb-org`** — мета-пакет, устанавливающий сервер, оболочку, инструменты и настройки конфигурации.
*   **SSPL (Server Side Public License)** — лицензия, под которой распространяется MongoDB, ограничивающая предоставление СУБД в качестве платного облачного сервиса третьими лицами.
*   **GPG-ключ** — открытый ключ для проверки подлинности пакетов в репозитории. В современных Ubuntu рекомендуется хранить его в `/usr/share/keyrings/`.
*   **`apt-mark hold`** — механизм фиксации версии пакета в Debian/Ubuntu, предотвращающий автоматическое обновление при `apt upgrade`.

---

## Базовые концепции

### Требования и подготовка (Prerequisites)

Перед началом установки необходимо убедиться, что целевая система соответствует минимальным требованиям:

1.  **Аппаратная поддержка AVX:** Начиная с версии 5.0+, для работы MongoDB требуется процессор с поддержкой набора инструкций **AVX**.
    *   **Проверка:** `grep -q avx /proc/cpuinfo && echo "AVX supported" || echo "AVX NOT supported"`
2.  **Операционная система:** Официально поддерживаются 64-битные LTS-версии Ubuntu (AMD64 и ARM64):
    *   Ubuntu 24.04 LTS (Noble)
    *   Ubuntu 22.04 LTS (Jammy)
    *   Ubuntu 20.04 LTS (Focal)
3.  **Файловая система:** Рекомендуется использовать **XFS**. Использование `ext4` допустимо, но WiredTiger работает эффективнее с XFS благодаря лучшей обработке разреженных файлов и `fsync`.
4.  **Сетевые настройки:** Порт по умолчанию — `27017`. Убедитесь, что фаервол (`ufw`) не блокирует локальные соединения.
5.  **Память:** Минимум 4 ГБ RAM (рекомендуется 16+ ГБ для Production). WiredTiger Cache по умолчанию занимает 50% RAM.
6.  **Диск:** Минимум 20 ГБ SSD (рекомендуется 100+ ГБ NVMe SSD для Production).

---

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

# Фиксация пакетов (современный метод)
sudo apt-mark hold mongodb-org mongodb-org-database mongodb-org-server mongodb-org-mongosh mongodb-org-tools
```

**Валидация:** Проверьте статус hold: `apt-mark showhold | grep mongodb`.

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

**Валидация:** Подключитесь через `mongosh` и выполните `db.serverStatus().ok`.

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

---

## Справочник команд (Operations Reference)

| Команда / Действие | Описание |
| :--- | :--- |
| `sudo apt-mark hold mongodb-org` | Фиксация версий пакетов для предотвращения автоматических обновлений. |
| `sudo apt-mark unhold mongodb-org` | Снятие фиксации перед плановым обновлением. |
| `apt-mark showhold \| grep mongodb` | Проверка статуса hold для MongoDB-пакетов. |
| `grep -q avx /proc/cpuinfo` | Проверка поддержки AVX (требуется для MongoDB 5.0+). |
| `cat /etc/lsb-release` | Определение версии Ubuntu для выбора правильного репозитория. |
| `systemctl status mongod` | Проверка статуса службы. |
| `journalctl -u mongod -f` | Просмотр логов службы в реальном времени. |
| `mongosh --eval "db.serverStatus().ok"` | Быстрая проверка работоспособности сервера. |
| `db.serverStatus().wiredTiger.cache` | Проверка состояния кэша WiredTiger. |
| `db.getReplicationInfo()` | Проверка Oplog window (для replica set). |

---

## Ограничения

*   **AVX:** MongoDB 5.0+ требует поддержки AVX. Старое оборудование без AVX не поддерживается.
*   **Версии Ubuntu:** MongoDB 8.0 официально поддерживает только Ubuntu 20.04, 22.04, 24.04 LTS. Другие версии Ubuntu не tested.
*   **Файловая система:** XFS рекомендуется для Production. `ext4` работает, но может иметь worse performance при высоких нагрузках.
*   **Swap:** Рекомендуется минимальный swap (`vm.swappiness = 1`), чтобы избежать вытеснения WiredTiger Cache на диск.
*   **Одна инсталляция:** На одном хосте не может быть нескольких активных `mongod` инстансов с одинаковыми путями данных.

---

## Лучшие практики (Best Practices)

### Подготовка к установке

1.  **Проверка аппаратных требований:** Убедитесь, что CPU поддерживает AVX, а RAM ≥ 4 ГБ (16+ ГБ для Production).
2.  **Выбор файловой системы:** Используйте XFS на выделенных устройствах (LVM, ZFS или physical disk). Избегайте shared storage с высокой latency.
3.  **Фиксация версий:** Используйте `apt-mark hold` для всех `mongodb-org*` пакетов. Это предотвращает неконтролируемые обновления при `apt upgrade`.
4.  **Идемпотентность:** Записывайте все шаги установки в плейбуки (Ansible) или скрипты. Это позволяет быстро восстанавливать систему после сбоя.

### Во время и после установки

5.  **Отключение THP:** Настройте персистентное отключение через systemd-юнит (см. Шаг 4), а не временный скрипт.
6.  **Настройка `ulimit`:** Установите `nofile` и `nproc` ≥ 64000 через systemd override или `/etc/security/limits.conf`.
7.  **Безопасность:** Включите авторицию (`security.authorization: enabled`) сразу после первого подключения. Не оставляйте запущенный инстанс без RBAC в production.
8.  **Мониторинг:** Создайте пользователя для мониторинга с ролью `clusterMonitor` и настройте экспортёр для Prometheus.

### Резервное копирование

9.  **Стратегия бэкапа:** Комбинируйте логические (`mongodump`) и физические (snapshot storage) бэкапы. Для PITR используйте Percona Backup for MongoDB.
10. **Тестирование восстановления:** Регулярно проверяйте, что бэкапы восстанавливаются. Бэкап, который не проверен, не считается валидным.

---

## Граничные случаи и ограничения (Edge Cases)

*   **Старое оборудование без AVX:** MongoDB 5.0+ не установится. Решения: замена оборудования или использование форка (Percona Server for MongoDB) с поддержкой старого CPU.
*   **Ошибка GPG-ключа при обновлении:** Если ключ истёк, импорт нового ключа не обновит существующий. Удалите старый ключ: `sudo apt-key del <key-id>` и повторите импорт.
*   **Конфликт портов:** Если порт 27017 занят другим сервисом, измените `net.port` в `mongod.conf` перед первым запуском.
*   **Недостаток памяти на small инстансах:** При RAM < 4 ГБ WiredTiger Cache может вызывать OOM. Уменьшите `storage.wiredTiger.engineConfig.cacheSizeGB` в конфигурации.
*   **Сеть с firewall:** Если mongod привязывается к `127.0.0.1`, удалённое подключение невозможно. Измените `net.bindIp` на `0.0.0.0` или конкретный IP, но только с включённым TLS.
*   **Откат после неудачной установки:** Удалите пакеты: `sudo apt-get purge mongodb-org*`, удалите данные: `sudo rm -rf /var/lib/mongodb /var/log/mongodb`, удалите репозиторий: `sudo rm /etc/apt/sources.list.d/mongodb-org-8.0.list`.

---

## Диагностика и решение проблем (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **`Illegal instruction (core dumped)`** | CPU не поддерживает AVX. | Перейдите на старое оборудование или используйте MongoDB < 5.0 (не рекомендуется). |
| **GPG error: The following signatures were invalid** | Устаревший или неверный GPG-ключ. | Удалите старый ключ и повторите Шаг 1. |
| **`mongod` падает при старте с ошибкой `WiredTiger error (13)`** | Проблемы с правами на `/var/lib/mongodb`. | `sudo chown -R mongodb:mongodb /var/lib/mongodb`. |
| **Служба `active (running)`, но подключения не проходят** | Ошибка привязки IP в `bindIp`. | Проверьте `net.bindIp` в `mongod.conf`. Убедитесь, что IP существует. |
| **`apt-get install` не находит пакет `mongodb-org`** | Репозиторий не добавлен или `apt-get update` не выполнен. | Проверьте `/etc/apt/sources.list.d/mongodb-org-8.0.list` и выполните `sudo apt-get update`. |
| **`mongosh` не подключается: `ECONNREFUSED`** | Служба не запущена или порт изменён. | Проверьте `systemctl status mongod` и `net.bindIp`. |
| **Высокий CPU Usage после установки** | Отсутствие индексов (COLLSCAN) или включённый THP. | Проверьте `db.collection.explain("executionStats").find(...)` и отключите THP. |

---

## Дополнительная информация

*   **Обзор и глубокая теория**: **[Обзор MongoDB](./mongodb.md)**.
*   **Администрирование**: **[Администрирование и обслуживание](./mongodb-administration.md)** — бэкапы, обновление, мониторинг.
*   **Безопасность**: **[Безопасность MongoDB](./mongodb-security.md)** — RBAC, TLS, аутентификация.
*   **Инфраструктура как код**: **[Ansible-роль для MongoDB](../../Ansible/examples/mongodb_setup.md)**.
