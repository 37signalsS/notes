# etcdctl и etcdutl: шпаргалка по командам

Данный справочник содержит основные команды для управления кластером etcd v3.7.1 и выше.

## Определения

| Инструмент | Описание |
| :--- | :--- |
| **etcdctl** | Основной клиент командной строки для сетевого взаимодействия с кластером (через gRPC). Используется для работы с данными, управления участниками и мониторинга состояния. |
| **etcdutl** | (с v3.6+) Утилита для офлайн-операций, требующих прямого доступа к файлам данных (напр., восстановление из снапшота, дефрагментация файла БД, проверка статуса снапшота). |
| **ETCDCTL_API** | Переменная окружения для выбора версии протокола. В v3.7+ стандарт — **v3**. |

---

## Базовые концепции

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

*   **Транзакции (Txn):** Атомарное выполнение нескольких операций.
    ```bash
    etcdctl txn --interactive
    # Пример логики:
    # cmp: mod("/config/app") = "123"
    # success: put "/config/app" "new_val"
    # failure: get "/config/app"
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
    # Добавить узел как learner (без права голоса)
    etcdctl member add node3 --peer-urls=https://10.0.1.12:2380 --learner
    # Повысить learner до голосующего участника
    etcdctl member promote <MEMBER_ID>
    # Удалить узел
    etcdctl member remove 8e9e05f521f74f0d
    ```

*   **Управление алармами (Alarms):**
    ```bash
    # Список активных алармов (напр., NOSPACE)
    etcdctl alarm list
    # Сброс всех алармов
    etcdctl alarm disarm
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
### Управление доступом (RBAC)

Аутентификация требует создания пользователя `root` перед включением.

*   **Работа с пользователями:**
    ```bash
    etcdctl user add my_user           # Создать пользователя
    etcdctl user delete my_user        # Удалить пользователя
    etcdctl user list                  # Список всех пользователей
    etcdctl user get root              # Информация о пользователе и его ролях
    ```

*   **Работа с ролями:**
    ```bash
    etcdctl role add my_role                             # Создать роль
    etcdctl role grant-permission my_role readwrite /a   # Дать права на ключ
    etcdctl role grant-permission my_role read /b --prefix # Дать права на префикс
    etcdctl user grant-role my_user my_role              # Привязать роль к пользователю
    ```

*   **Включение аутентификации:**
    ```bash
    etcdctl auth enable   # Включить (требует наличия пользователя root)
    etcdctl auth disable  # Выключить
    ```

### Резервное копирование и восстановление

*   **Создание снапшота (Online):**
    ```bash
    # Базовая команда
    etcdctl snapshot save backup.db

    # Полная команда с TLS и эндпоинтами (рекомендуется для HA кластеров)
    ETCDCTL_API=3 etcdctl snapshot save /path/to/backup.db \
      --endpoints=https://etcd1.example.com:2379,https://etcd2.example.com:2379,https://etcd3.example.com:2379 \
      --cacert=/etc/etcd/pki/ca.pem \
      --cert=/etc/etcd/pki/etcd.pem \
      --key=/etc/etcd/pki/etcd-key.pem
    ```
    **Разбор флагов:**
    *   `ETCDCTL_API=3`: Принудительное использование API v3.
    *   `snapshot save`: Создает снимок и сохраняет его по указанному пути.
    *   `--endpoints`: Список URL-адресов всех серверов etcd в кластере.
    *   `--cacert`, `--cert`, `--key`: Пути к сертификатам и ключам для безопасной аутентификации.

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
*   **[Кластеризация и восстановление](./clustering_and_recovery.md)** — процедуры замены узлов и аварийное восстановление.
*   **[MVCC и версионирование](./mvcc_versioning_and_compaction.md)** — подробнее о ревизиях и транзакциях.
