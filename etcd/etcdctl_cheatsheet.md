# etcdctl и etcdutl: шпаргалка по командам

## Определения

**etcdctl** — основной клиент командной строки для сетевого взаимодействия с кластером etcd (через gRPC). Используется для работы с данными, управления участниками и мониторинга состояния.

**etcdutl** — (начиная с версии 3.6) утилита для выполнения административных задач, требующих прямого доступа к файлам данных (офлайн-операции), таких как восстановление из снапшота или миграция данных.

**ETCDCTL_API** — переменная окружения, определяющая версию протокола.
*   **API v3**: Стандарт по умолчанию в 3.6+. Для старых версий включается через `export ETCDCTL_API=3`.

---

## Основные концепции

### Настройка окружения и аутентификация

Для постоянной работы рекомендуется настроить переменные окружения, чтобы не передавать флаги TLS и адреса в каждой команде.

```bash
# Базовая настройка (API v3)
export ETCDCTL_API=3
export ETCDCTL_ENDPOINTS="https://127.0.0.1:2379"

# Настройка TLS (для Kubernetes и защищенных кластеров)
export ETCDCTL_CACERT="/etc/etcd/ca.crt"
export ETCDCTL_CERT="/etc/etcd/server.crt"
export ETCDCTL_KEY="/etc/etcd/server.key"

# Настройка аутентификации (если включен RBAC)
export ETCDCTL_USER="admin:password"
```

### Форматы вывода

Флаг `-w` (или `--write-out`) изменяет формат ответа:
*   `simple` — текстовый (по умолчанию).
*   `table` — табличный (удобно для чтения).
*   `json` — для автоматизации и скриптов.

---

## Практические сценарии

### Управление данными (CRUD)

*   **Запись и чтение ключа:**
    ```bash
    etcdctl put /config/app "value1"
    # → OK
    etcdctl get /config/app
    # → /config/app
    # → value1
    ```

*   **Работа с префиксами (чтение всех ключей в директории):**
    ```bash
    etcdctl get /config/ --prefix
    etcdctl get /config/ --prefix --keys-only # Только названия ключей
    ```

*   **Удаление:**
    ```bash
    etcdctl del /config/old_key
    # → 1
    etcdctl del /config/ --prefix # Удалить всё по префиксу
    ```

### Продвинутые операции с данными

*   **Наблюдение (Watch):** Ожидание изменений ключа в реальном времени.
    ```bash
    etcdctl watch /config/app
    # → PUT
    # → /config/app
    # → new_value
    ```

*   **Аренда (Lease):** Ключи с ограниченным временем жизни (TTL).
    ```bash
    # Создать аренду на 60 секунд
    etcdctl lease grant 60
    # → lease 694d5765fc71500b granted with TTL(60s)

    # Привязать ключ к аренде
    etcdctl put /tmp/key "val" --lease=694d5765fc71500b

    # Продлить аренду
    etcdctl lease keep-alive 694d5765fc71500b
    ```

*   **Распределенные блокировки (Lock):**
    ```bash
    etcdctl lock mutex_name
    # → mutex_name/694d5765fc71500b (блокировка удерживается, пока команда запущена)
    ```

### Состояние и здоровье кластера

*   **Проверка здоровья всех узлов:**
    ```bash
    etcdctl endpoint health --cluster -w table
    # → +----------------+--------+-------+-------+
    # → |    ENDPOINT    | HEALTH |  TOOK | ERROR |
    # → +----------------+--------+-------+-------+
    # → | 127.0.0.1:2379 |   true | 1.5ms |       |
    # → +----------------+--------+-------+-------+
    ```

*   **Детальный статус (лидерство, размер БД, ревизия):**
    ```bash
    etcdctl endpoint status --cluster -w table
    ```

*   **Управление участниками:**
    ```bash
    etcdctl member list -w table
    etcdctl member add node3 --peer-urls=https://10.0.1.12:2380
    etcdctl member remove 8e9e05f521f74f0d
    ```

### Обслуживание и производительность

*   **Компакция (Сжатие истории):** Удаление старых ревизий для освобождения места.
    ```bash
    # Удалить все ревизии до 5000
    etcdctl compaction 5000
    # → compacted revision 5000
    ```

*   **Дефрагментация (Освобождение места в файловой системе):**
    ```bash
    etcdctl defrag --cluster
    # → Finished defragmenting etcd member[https://127.0.0.1:2379]
    ```

*   **Проверка производительности (Perf Check):** Симуляция нагрузки.
    ```bash
    etcdctl check perf --load="s" # s (small), m (medium), l (large), xl (x-large)
    # → PASS: Throughput is 150 writes/s
    ```

### Резервное копирование и восстановление

*   **Создание снапшота (Online):**
    ```bash
    etcdctl snapshot save backup.db
    # → Snapshot saved at backup.db
    ```

*   **Проверка статуса снапшота (Offline):**
    ```bash
    # В 3.6+ рекомендуется использовать etcdutl
    etcdutl snapshot status backup.db -w table
    ```

*   **Восстановление (Offline):** Требует прямого доступа к новой директории данных.
    ```bash
    # Для etcd 3.6+
    etcdutl snapshot restore backup.db --data-dir /var/lib/etcd-new
    ```

---

## Дополнительная информация

*   **[Архитектура и основные концепции](./architecture-and-concepts.md)** — глубокое понимание WAL, Raft и Revision.
*   **[Кластеризация и восстановление](./clustering_and_recovery.md)** — процедуры замены узлов и災害 восстановление.
*   **[MVCC и версионирование](./mvcc_versioning_and_compaction.md)** — подробнее о ревизиях и транзакциях.
