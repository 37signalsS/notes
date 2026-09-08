# Идемпотентность

## Определения

**Идемпотентность (Idempotency)** — это свойство операции, при котором её многократное выполнение с одними и теми же входными параметрами приводит к тому же результату, что и однократное, не изменяя состояние системы после первого успешного вызова.

*   **Математическая формулировка:** $f(x) = f(f(x))$.
*   **Инженерный смысл:** Гарантия того, что повторный запрос (из-за сбоя сети, таймаута или ретрая клиента) не приведет к дублированию бизнес-логики (например, двойному списанию средств или созданию лишней записи в БД).

Идемпотентность является фундаментом надежности распределенных систем, позволяя реализовать семантику доставки **Exactly-once** на уровне бизнес-логики, даже если транспорт обеспечивает только **At-least-once**.

## Базовые концепции

### Типы операций по уровню идемпотентности

1.  **Естественно идемпотентные (Безопасные):**
    *   **Чтение (Safe methods):** `GET`, `HEAD`, `OPTIONS`. Не меняют состояние (side-effect free).
    *   **Удаление по ID:** `DELETE /orders/123`. Первый вызов удаляет, последующие подтверждают отсутствие ресурса (состояние системы — «ресурс удален» — остается неизменным).
    *   **Установка абсолютного значения:** `SET balance = 100`. Повторное присвоение того же значения не меняет итоговое состояние.
2.  **Неидемпотентные (Опасные):**
    *   **Инкремент:** `UPDATE accounts SET balance = balance + 10`. Каждый вызов изменяет состояние относительно предыдущего.
    *   **Добавление в коллекцию:** `POST /comments`. Без дедупликации создает новый ресурс при каждом запросе.
    *   **Вызов внешних неидемпотентных API:** Отправка Email или SMS без внешнего ключа дедупликации.

### Трехстадийная модель состояния запроса
Современная реализация идемпотентности рассматривает запрос как конечный автомат:

| Статус | Описание | Ответ сервера |
| :--- | :--- | :--- |
| **Pending (В процессе)** | Запрос уже обрабатывается другим потоком/узлом. | `409 Conflict` или `202 Accepted` |
| **Completed (Завершен)** | Запрос успешно выполнен, результат сохранен в кэше. | Исходный статус (напр. `201 Created`) + тело ответа |
| **Failed (Ошибка)** | Запрос завершился ошибкой (валидация или сбой). | `4xx` (кэшируется) или `5xx` (разрешается повтор) |

### Ложная идемпотентность
Ситуация, когда система сообщает об успехе, но фактически состояние не соответствует ожиданиям.
*   **Пример:** Terraform сообщает `Apply complete`, но из-за ошибки в провайдере ресурс не был создан, а его ID записан в `tfstate`.
*   **Configuration Drift:** Когда внешние факторы меняют систему в обход инструментов автоматизации, делая повторный запуск непредсказуемым.

## Практические сценарии реализации

### 1. Реализация в API (Idempotency Key)
Стандарт для критических систем (Stripe, Adyen, банковские API).

**Алгоритм работы:**
1.  **Client:** Генерирует уникальный `Idempotency-Key` (рекомендуется UUID v4).
2.  **Server (Atomic Claim):** Пытается атомарно создать запись о ключе в хранилище (Redis/PostgreSQL).
    *   Используется `SET key NX` в Redis или `INSERT ... ON CONFLICT` в SQL.
3.  **Fingerprinting:** Сервер сохраняет хэш тела запроса вместе с ключом. Если пришел тот же ключ, но с другим телом — возвращается `400 Bad Request`.
4.  **Execution:** Выполняется бизнес-логика.
5.  **Caching:** Результат выполнения (HTTP-код, заголовки, тело) сохраняется в БД/кэше с TTL (обычно 24–48 часов).

### 2. Транзакционный UPSERT в БД
Гарантия консистентности при конкурентных запросах.

*   **SQL (PostgreSQL):**
    ```sql
    -- Атомарная вставка с игнорированием дубликатов
    INSERT INTO users (email, full_name)
    VALUES ('user@example.com', 'Ivan Ivanov')
    ON CONFLICT (email) DO NOTHING;
    ```
*   **Важное ограничение:** Все действия (бизнес-логика + сохранение ключа идемпотентности) должны происходить в рамках **одной БД-транзакции**.

### 3. Паттерны Inbox и Outbox в очередях
Для систем с семантикой **At-least-once**.

*   **Transactional Outbox (Producer):** Событие сохраняется в таблицу `outbox` в той же транзакции, что и бизнес-данные. Это гарантирует, что если данные сохранились, сообщение точно будет отправлено (хотя может и продублироваться).
*   **Inbox Pattern (Consumer):** Обработчик ведет таблицу `processed_messages`. При получении нового сообщения он проверяет его ID в таблице в рамках транзакции обработки.

### 4. Инфраструктура как код (IaC)
Идемпотентность — основа декларативного подхода.

*   **Ansible:** Модули проверяют текущее состояние (`current`) и сравнивают с желаемым (`desired`).
    *   *Антипаттерн:* Использование `shell` без параметров `creates`/`removes`.
    ```yaml
    # Плохо: выполняется при каждом запуске
    - shell: /usr/bin/create_user.sh --name ivan
    # Хорошо: идемпотентно
    - shell: /usr/bin/create_user.sh --name ivan
      args:
        creates: /home/ivan/.ssh/id_rsa
    ```
*   **Terraform:** Использует `tfstate` как источник правды о текущем состоянии ресурсов, вычисляя разницу (diff) для применения изменений.

### 5. Идемпотентность в shell-скриптах (bash)
Shell-скрипты по умолчанию **не идемпотентны** — каждая команда выполняется безотносительно предыдущего состояния. Для обеспечения идемпотентности используется паттерн **Check before Do**.

**Паттерн Check before Do:**
```bash
#!/bin/bash
# Проверка существования пользователя перед созданием
if ! id -u "$USERNAME" &>/dev/null; then
    useradd -m -s /bin/bash "$USERNAME"
    echo "User $USERNAME created"
else
    echo "User $USERNAME already exists — skipping"
fi
```

**Паттерн File-based idempotency (для критических операций):**
```bash
#!/bin/bash
MARKER="/var/run/.first_boot_completed"

if [ ! -f "$MARKER" ]; then
    # Выполнить одноразовую настройку
    /opt/scripts/initial_setup.sh
    touch "$MARKER"
    echo "First boot setup completed"
else
    echo "First boot already completed — skipping"
fi
```

**Паттерн идемпотентного монтирования:**
```bash
# Проверка, примонтирована ли уже filesystem
if ! mountpoint -q /mnt/data; then
    mount /dev/sdb1 /mnt/data
fi
```

**Паттерн идемпотентного добавления в конфиг:**
```bash
# Добавление строки в файл, если её там ещё нет
grep -qF "MaxSessions 10" /etc/ssh/sshd_config || \
    echo "MaxSessions 10" >> /etc/ssh/sshd_config
```

**Антипаттерн:** Использование `echo >>` без проверки — при каждом запуске добавляет дубликат строки.

### 6. Идемпотентность в systemd
Systemd юниты по своей природе идемпотентны для состояний `started`/`stopped`/`restarted`, но **не идемпотентны** для `exec`-директив.

**Идемпотентные директивы:**
```ini
[Service]
# После выполнения ExecStart контейнер будет в состоянии "running"
# Повторный запуск systemd остановит старый и запустит новый
Type=simple
ExecStart=/usr/bin/my-daemon --config /etc/myapp/config.yaml

# Идемпотентное условие — выполнить только если файл существует
ExecStartPre=/bin/test -f /etc/myapp/config.yaml
```

**Антипаттерн — неидемпотентные ExecStartPre:**
```ini
# ПЛОХО: команда выполнится при каждом запуске юнита
ExecStartPre=/usr/bin/mkdir -p /var/lib/myapp

# ХОРОШО: идемпотентная проверка/создание
ExecStartPre=/bin/sh -c '[ -d /var/lib/myapp ] || mkdir -p /var/lib/myapp'
```

**Паттерн One-shot сервис для одноразовой настройки:**
```ini
[Unit]
Description=Initial database migration
After=postgresql.service

[Service]
Type=oneshot
ExecStart=/opt/migrate.sh
# Условие выполнения — отсутствие маркера
ExecStartPre=/bin/sh -c '[ ! -f /var/lib/myapp/.migrated ]'
ExecStartPost=/bin/touch /var/lib/myapp/.migrated
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

### 7. Идемпотентность в Docker Compose и контейнерах
Docker Compose обеспечивает **декларативную идемпотентность** на уровне описания сервисов, но побочные эффекты (тома, сети, данные) требуют осторожности.

**Идемпотентные операции:**
```yaml
# docker-compose.yml
services:
  app:
    image: myapp:1.2.3
    # Интересы: повторный docker compose up не пересоздаст контейнер,
    # если образ и конфигурация не изменились
    volumes:
      - app-data:/var/lib/myapp/data  # Том сохраняется между перезапусками
    environment:
      - DB_HOST=postgres
    restart: unless-stopped  # Идемпотентное управление перезапуском

volumes:
  app-data:  # Объявление тома — идемпотентно (не удаляет данные)
```

**Антипаттерн — данные в ephemeral-томах:**
```yaml
# ПЛОХО: данные теряются при каждом перезапуске
services:
  db:
    image: postgres:16
    # Нет volume — данные не сохраняются

# ХОРОШО: данные сохраняются идемпотентно
services:
  db:
    image: postgres:16
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

**Идемпотентность в Dockerfile (multi-stage build):**
```dockerfile
# Каждый слой — идемпотентная операция
# Если инструкция не изменилась, Docker использует кэш
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Паттерн: копирование только если изменился source
COPY --chown=app:app requirements.txt /app/
RUN pip install -r /app/requirements.txt

COPY --chown=app:app . /app/  # Слой пересоздаётся только при изменении файлов
```

### 8. Идемпотентность в миграциях баз данных
Миграции должны быть **обратимыми** и **многократно исполняемыми**.

**Идемпотентные SQL-паттерны:**
```sql
-- Создание таблицы (если не существует)
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Добавление колонки (если не существует) — PostgreSQL 9.6+
ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS actor_id UUID;

-- UPSERT — атомарное обновление или вставка
INSERT INTO feature_flags (flag_name, enabled, updated_at)
VALUES ('new_checkout', true, NOW())
ON CONFLICT (flag_name)
    DO UPDATE SET enabled = EXCLUDED.enabled,
                  updated_at = EXCLUDED.updated_at;

-- Удаление (если существует)
DROP TABLE IF EXISTS deprecated_cache;
```

**Паттерн версионирования миграций:**
```sql
-- Таблица отслеживания применённых миграций
CREATE TABLE IF NOT EXISTS schema_migrations (
    version BIGINT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

-- Выполнение миграции только если ещё не применена
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 20240115) THEN
        ALTER TABLE users ADD COLUMN phone VARCHAR(20);
        INSERT INTO schema_migrations (version) VALUES (20240115);
    END IF;
END
$$;
```

### 9. Идемпотентность в cron и scheduled tasks
Задачи по расписанию должны быть безопасными для повторного выполнения, особенно при перезапуске демона cron или при дублировании запусков (failover).

**Паттерн execution tracking (файловый маркер):**
```bash
#!/bin/bash
# /etc/cron.daily/backup.sh
LOCKFILE="/var/run/backup_$(date +%Y%m%d).lock"

# flock + проверка маркера — защита от параллельных и дублирующих запусков
if ! flock -n "$LOCKFILE" 2>/dev/null; then
    echo "Backup already running or completed today — exiting"
    exit 0
fi

perform_backup
# flock автоматически освобождается при завершении скрипта
```

**Паттерн идемпотентного ротационного резервного копирования:**
```bash
#!/bin/bash
BACKUP_DIR="/backup/$(date +%Y%m%d)"
SNAPSHOT_FILE="/backup/latest.sql.gz"

if [ -d "$BACKUP_DIR" ]; then
    echo "Backup for today already exists at $BACKUP_DIR — skipping"
    exit 0
fi

mkdir -p "$BACKUP_DIR"
pg_dump mydb | gzip > "$BACKUP_DIR/dump.sql.gz"
ln -sfn "$BACKUP_DIR/dump.sql.gz" "$SNAPSHOT_FILE"
```

## Проектирование и тонкости реализации

### Управление побочными эффектами (Side Effects)
Если операция включает вызов внешней системы (например, отправка денег через сторонний банк):
1.  **External Idempotency:** Передавайте внешней системе *свой* ключ идемпотентности.
2.  **Reconciliation:** Если внешний вызов завершился таймаутом, система должна уметь «довыяснить» статус операции через фоновый процесс (polling) перед тем, как разрешить повтор.

### Детерминизм и состояние гонки (Race Conditions)
*   **Детерминизм:** При одинаковых входных данных результат должен быть идентичным. Избегайте использования `NOW()` или случайных чисел внутри идемпотентной логики, если они не сохраняются при первом вызове.
*   **Распределенные блокировки:** Используйте Redis Redlock или семантику `SELECT FOR UPDATE` в SQL, чтобы предотвратить параллельное выполнение двух идентичных запросов на разных узлах API.

### Граничные случаи и решение проблем (Troubleshooting)
*   **Hash Collisions:** Риск крайне мал при использовании UUID v4, но сохранение хэша payload (fingerprint) защищает от случайных совпадений.
*   **TTL Management:** Ключ должен жить дольше, чем максимальное время, в течение которого клиент может повторять попытки. Для финансов — 24-72 часа.
*   **Изменение Payload:** Если клиент прислал тот же ключ, но изменил сумму платежа — это явная ошибка или попытка мошенничества.

**DevOps/SRE-специфичные проблемы:**
*   **Ansible: `changed` при идемпотентном запуске:** Если модуль `shell`/`command` возвращает `changed: true` при каждом запуске — используйте `changed_when: false` или параметры `creates`/`removes`. Проверяйте через `--check --diff` перед реальным прогоном.
*   **Terraform: state lock conflicts:** При параллельных запусках `terraform apply` на одном state-файле возникает deadlock. Решение: использовать удалённый backend (S3, Consul) с `lock=true`.
*   **Docker Compose: recreate при несущественных изменениях:** Изменение `environment` или `labels` в `docker-compose.yml` приводит к пересозданию контейнера. Используйте `docker compose up --no-recreate` для предотвращения ненужных перезапусков.
*   **Cron: дублирующиеся запуски:** При перезапуске демона cron или при failover-кластере задачи могут выполниться дважды. Используйте `flock` или файловые маркеры с проверкой даты.
*   **Миграции БД: гонка при деплое:** Если два процесса деплоя одновременно применяют миграцию, возникнет конфликт. Решение: использовать advisory locks в PostgreSQL (`SELECT pg_advisory_lock(migration_id)`) или таблицу `schema_migrations` с уникальным constraint.
*   **Systemd: неидемпотентные ExecStartPre:** Команды `mkdir`, `cp`, `chown` в `ExecStartPre` выполняются при каждом запуске юнита. Используйте проверку условий (`[ -d ... ] || ...`).

## Идемпотентность в Configuration Management (обобщение)

Идемпотентность является фундаментальным свойством инструментов управления конфигурацией. Все современные CM-инструменты (Ansible, Puppet, Chef, SaltStack) стремятся к **декларативному подходу**: оператор описывает **желаемое состояние** (desired state), а инструмент вычисляет и применяет только необходимые изменения.

**Общие принципы:**
1.  **State comparison:** Инструмент считывает текущее состояние системы (фактическое) и сравнивает с описанным в манифесте/плейбуке (желаемым).
2.  **Diff application:** Применяются только те изменения, которые необходимы для достижения желаемого состояния.
3.  **No side effects:** Если текущее состояние уже соответствует желаемому — никаких изменений не вносится.

**Сравнение инструментов:**

| Инструмент | Подход к идемпотентности | Механизм | Ограничения |
|:--- |:--- |:--- |:--- |
| **Ansible** | Модули проверяют состояние через SSH | `creates`/`removes`, `state`, `check_mode` | `shell`/`command` неидемпотентны по умолчанию |
| **Puppet** | Каталог сравнения (catalog compilation) | Сравнение catalog с текущим состоянием через агент | Ошибки в catalog могут привести к конфликтам |
| **Chef** | Сервер сравнения (convergence) | `chef-client` применяет runlist, проверяя resource через провайдеры | The node может содержать устаревшие данные |
| **SaltStack** | Декларативные state-файлы | Salt module проверяет состояние и применяет изменения | Lone state не всегда детерминирован |

**Паттерн "Проверка перед действием" (общий):**
Для каждого ресурса (файл, пакет, сервис, пользователь) операция должна:
1.  Проверить текущее состояние (существует ли файл, установлен ли пакет, запущен ли сервис).
2.  Сравнить с желаемым.
3.  Применить изменение только при расхождении.

**Антипаттерн:** Использование императивных команд (`service nginx restart`, `apt-get install`) без проверки текущего состояния. Это приводит к нарушению идемпотентности и непредсказуемым результатам при повторных запусках.

## Дополнительная информация

### См. также
*   **[Гарантии доставки в Kafka](../Kafka/delivery_guarantees.md)** — Exactly-once через Transactional API.
*   **[Инфраструктура как код (IaC)](./iac_overview.md)** — роль идемпотентности в автоматизации.
*   **[HTTP-методы: стандарты](../Networking/Protocols/HTTP/http_methods.md)** — детальная таблица свойств методов.
*   **[Распределенные транзакции](../Databases/Concepts/distributed_transactions.md)** — паттерны Saga и TCC.
*   **[Ansible: основные концепции](../Ansible/ansible_core_concepts.md)** — идемпотентность как фундамент Ansible.
*   **[Ansible: антипаттерны](../Ansible/ansible_bad_practices.md)** — нарушения идемпотентности в Ansible.
