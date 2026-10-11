# Consul Backup Verification Methodology

**Актуально для:** Consul 2.0.x / 1.22.x / 1.20.x / 1.19.x

## Определения

**Consul Backup Verification** — методика проверки целостности и восстанавливаемости резервных копий (snapshots) Consul. Бэкап без регулярного тестирования восстановления не считается рабочим: только restore-тест подтверждает, что снапшот можно использовать при катастрофе.

**Snapshot** — атомарный, моментный снимок состояния кластера, включающий KV-хранилище, каталог сервисов, подготовленные запросы (prepared queries), сессии и ACL. Снапшот создается на основе текущего зафиксированного индекса Raft-лога.

**Consistent mode** — режим создания снапшота, при котором запрос всегда направляется текущему лидеру кластера, который подтверждает свое лидерство перед записью. Гарантирует полную согласованность.

**Stale mode** — режим создания снапшота с любого сервера без перенаправления на лидера. Не гарантирует включение записей, записанных в последние ~100 мс, но снижает нагрузку на лидера.

## Основные концепции

### Что содержится в снапшоте

Снапшот включает (но не ограничивается):
- **KV entries** — все ключи и значения в каталоге
- **Service catalog** — зарегистрированные сервисы, проверки здоровья, метки
- **Prepared queries** — кэшированные запросы к каталогу
- **Sessions** — активные сессии
- **ACLs** — политики, роли, токены аутентификации

> **Важно:** Снапшот содержит extremely sensitive данные, включая учетные данные в восстанавливаемой форме. Храните файлы на зашифрованных носителях с контролем доступа.

### Типы проверок

| Проверка | Что проверяет | Частота |
| :--- | :--- | :--- |
| **Snapshot inspect** | Целостность файла, версия Raft, индекс, термик, разбивка по типам данных | После каждого бэкапа |
| **Restore drill** | Полное восстановление на тестовом кластере с проверкой данных и кворума | Еженедельно/ежемесячно |
| **Data validation** | Наличие критичных KV-ключей, ACL, сервисов после restore | После каждого restore drill |
| **Quorum test** | Кластер после restore образует кворум, лидер elected | После каждого restore drill |
| **Monotonic index** | Индекс снапшота monotonically увеличивается со временем | После каждого бэкапа |

### Архитектура проверки

```
Production Cluster
       │
       ▼
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Snapshot    │────►│  Snapshot Inspect │────►│  Validation  │
│  (daily)     │     │  (automated)      │     │  Report      │
└──────────────┘     └──────────────────┘     └──────────────┘
       │
       ▼
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Snapshot    │────►│  Restore Drill   │────►│  Test Cluster │
│  (weekly)    │     │  (isolated env)  │     │  Validation  │
└──────────────┘     └──────────────────┘     └──────────────┘
```

### Выходные данные `snapshot inspect`

```
$ consul snapshot inspect backup.snap
ID           2-1182-1542056499724
Size         4115
Index        1182
Term         2
Version      1

Type                       Count      Size
----                       ----       ----
KVS                        27         12.3KB
Register                   5          3.4KB
Index                      11         285B
Autopilot                  1          199B
Session                    1          199B
CoordinateBatchUpdate      1          166B
Tombstone                  2          146B
FederationState            1          139B
ChunkingState              1          12B
----                       ----       ----
Total                                 16.8KB
```

| Поле | Описание |
| :--- | :--- |
| `ID` | Уникальный идентификатор снапшота. |
| `Size` | Размер файла в байтах. |
| `Index` | Raft-индекс последней записи в снапшоте. |
| `Term` | Raft-терм последней записи. |
| `Version` | Версия формата снапшота (структура файла). |
| `Type` | Тип данных в снапшоте (KVS, Register, Session и т.д.). |
| `Count` | Количество объектов данного типа. |
| `Size` | Объем, занимаемый типом. |

## Практические сценарии

### 1. Автоматическая проверка снапшота (Snapshot Inspect)

```bash
#!/bin/bash
# verify-snapshot.sh
set -euo pipefail

SNAPSHOT="/var/backups/consul/consul-$(date +%Y%m%d).snap"
SNAPSHOT_DIR="/var/backups/consul"
MIN_INDEX_FILE="${SNAPSHOT_DIR}/.last_index"

# Проверка существования
if [ ! -f "$SNAPSHOT" ]; then
  echo "ERROR: Snapshot not found: $SNAPSHOT"
  exit 1
fi

# Проверка валидности
consul snapshot inspect "$SNAPSHOT"
# → Size: 1.2 MB
# → Index: 12345
# → Term: 2
# → Version: 1

# Проверка индекса в JSON
INDEX=$(consul snapshot inspect -format=json "$SNAPSHOT" | jq -r '.Index')
if [ "$INDEX" -eq 0 ] 2>/dev/null || [ -z "$INDEX" ]; then
  echo "ERROR: Invalid snapshot index"
  exit 1
fi

# Проверка монотонного роста индекса
if [ -f "$MIN_INDEX_FILE" ]; then
  LAST_INDEX=$(cat "$MIN_INDEX_FILE")
  if [ "$INDEX" -le "$LAST_INDEX" ]; then
    echo "ERROR: Snapshot index $INDEX is not greater than last index $LAST_INDEX"
    exit 1
  fi
fi
echo "$INDEX" > "$MIN_INDEX_FILE"

echo "OK: Snapshot $SNAPSHOT is valid (Index=$INDEX)"
```

### 2. Глубокая инспекция KV-данных

```bash
#!/bin/bash
# verify-snapshot-kv.sh
set -euo pipefail

SNAPSHOT="/var/backups/consul/consul-latest.snap"

# Детальная проверка KV с фильтром по префиксу
consul snapshot inspect -kvdetails -kvdepth 3 -kvfilter "config/" "$SNAPSHOT"
# → Key Name                     Count      Size
# → ----                         ----       ----
# → config/app                   15         2.1KB
# → config/billing               8          1.2KB
```

### 3. Полный restore drill (еженедельно)

```bash
#!/bin/bash
# restore-drill.sh
set -euo pipefail
trap 'rm -rf "$TEST_DIR"' EXIT

SNAPSHOT="/var/backups/consul/consul-latest.snap"
TEST_DIR="/tmp/consul-restore-test-$(date +%Y%m%d)"
TEST_DC="drill-test"
CONSUL_BIN="/usr/bin/consul"
LOG_FILE="/var/log/consul/restore-drill.log"

# 1. Создание тестового кластера
mkdir -p "$TEST_DIR"
export CONSUL_HTTP_ADDR="127.0.0.1:8500"

# 2. Восстановление снапшота (без флага DC)
"$CONSUL_BIN" snapshot restore "$SNAPSHOT" 2>&1 | tee "$LOG_FILE"
# → Restored snapshot

# 3. Запуск тестового кластера
"$CONSUL_BIN" agent -server -bootstrap-expect=1 \
  -data-dir="$TEST_DIR" \
  -node=test-server \
  -bind=127.0.0.1 \
  -client=127.0.0.1 \
  -datacenter="$TEST_DC" \
  -log-level=err &
CONSUL_PID=$!

# 4. Ожидание готовности (polling вместо sleep)
for i in {1..30}; do
  if "$CONSUL_BIN" operator raft list-peers -datacenter="$TEST_DC" >/dev/null 2>&1; then
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: Test cluster did not become ready in time"
    kill $CONSUL_PID 2>/dev/null || true
    exit 1
  fi
  sleep 2
done

# 5. Валидация данных
echo "=== Validating KV ==="
"$CONSUL_BIN" kv get config/app/db_url -datacenter="$TEST_DC"
# → postgres://app:pass@db:5432/app

echo "=== Validating Services ==="
"$CONSUL_BIN" catalog services -datacenter="$TEST_DC"
# → web-api, billing-api, order-db

echo "=== Validating ACL ==="
if [ -f "/etc/consul.d/management-token" ]; then
  MGMT_TOKEN=$(cat /etc/consul.d/management-token)
  "$CONSUL_BIN" acl token list -datacenter="$TEST_DC" -token "$MGMT_TOKEN" | head -5
fi

echo "=== Validating Raft ==="
"$CONSUL_BIN" operator raft list-peers -datacenter="$TEST_DC"
# → 1 voter, leader

# 6. Очистка
kill $CONSUL_PID 2>/dev/null || true
wait $CONSUL_PID 2>/dev/null || true

echo "OK: Restore drill completed successfully"
```

### 4. Валидация критичных данных

```bash
#!/bin/bash
# validate-critical-data.sh
set -euo pipefail

# Критичные KV-ключи, которые должны существовать после restore
EXPECTED_KEYS=(
  "config/app/db_url"
  "config/app/redis_url"
  "config/billing/payment_gateway"
)

for key in "${EXPECTED_KEYS[@]}"; do
  VALUE=$(consul kv get "$key")
  if [ -z "$VALUE" ]; then
    echo "ERROR: Critical key missing: $key"
    exit 1
  fi
  echo "OK: $key = $VALUE"
done

# Проверка, что сервисы зарегистрированы
SERVICES=$(consul catalog services)
for svc in web-api billing-api; do
  if ! echo "$SERVICES" | grep -q "^${svc}$"; then
    echo "ERROR: Service missing: $svc"
    exit 1
  fi
  echo "OK: Service $svc exists"
done
```

### 5. Интеграция с CI/CD

```yaml
# .gitlab-ci.yml
stages:
  - backup-verify

verify-consul-snapshot:
  stage: backup-verify
  image: consul:1.22
  script:
    - |
      SNAPSHOT="/backups/consul/consul-latest.snap"
      consul snapshot inspect "$SNAPSHOT"
    - |
      INDEX=$(consul snapshot inspect -format=json "$SNAPSHOT" | jq -r '.Index')
      if [ "$INDEX" -eq 0 ] || [ -z "$INDEX" ]; then
        echo "ERROR: Invalid snapshot index"
        exit 1
      fi
      echo "Snapshot Index: $INDEX"
    - |
      SIZE=$(consul snapshot inspect -format=json "$SNAPSHOT" | jq -r '.Size')
      if [ "$SIZE" -lt 1024 ]; then
        echo "ERROR: Snapshot too small ($SIZE bytes), possible corruption"
        exit 1
      fi
  only:
    - schedules
```

### 6. Восстановление после потери кворума

```bash
#!/bin/bash
# restore-quorum-loss.sh
# Используется, когда часть серверов жива, но недостаточно для кворума

SNAPSHOT="/var/backups/consul/consul-latest.snap"
DATA_DIR="/opt/consul/data"
PEERS_FILE="${DATA_DIR}/raft/peers.json"

# 1. Остановите выживший сервер
systemctl stop consul

# 2. Создайте peers.json с только выжившим узлом
cat > "$PEERS_FILE" <<'EOF'
[
  {
    "id": "SURVIVOR-UUID",
    "address": "10.0.1.10:8300",
    "non_voter": false
  }
]
EOF

# 3. Запустите сервер - он станет лидером в кластере из одного узла
systemctl start consul

# 4. Дождитесь готовности
sleep 5

# 5. Восстановите снапшот
consul snapshot restore "$SNAPSHOT"
# → Restored snapshot

# 6. Добавьте новые пустые серверы через Learner role
# consul operator server add -learner -address=new-server:8300

# 7. Автопилот автоматически повысит Learner до voter после синхронизации
```

## Структура снапшота и валидация

### Проверка монотонности индекса

Индекс Raft должен monotonically увеличиваться. Если новый снапшот имеет индекс меньше или равный предыдущему — это признак проблем с кластером или сброса состояния:

```bash
#!/bin/bash
# verify-index-monotonic.sh
SNAPSHOT="/var/backups/consul/consul-latest.snap"
INDEX_FILE="/var/backups/consul/.last_index"

CURRENT_INDEX=$(consul snapshot inspect -format=json "$SNAPSHOT" | jq -r '.Index')

if [ -f "$INDEX_FILE" ]; then
  LAST_INDEX=$(cat "$INDEX_FILE")
  if [ "$CURRENT_INDEX" -le "$LAST_INDEX" ]; then
    echo "ERROR: Index regression detected: $CURRENT_INDEX <= $LAST_INDEX"
    exit 1
  fi
fi

echo "$CURRENT_INDEX" > "$INDEX_FILE"
echo "OK: Index $CURRENT_INDEX is valid"
```

### Проверка версии Consul

Снапшот содержит поле `Version` (версия формата). При восстановлении требуется совпадение версий Consul между кластерами:

```bash
# Проверка версии на production
consul version
# → Consul v1.22.3

# Проверка версии в снапшоте
consul snapshot inspect backup.snap | grep Version
# → Version: 1

# Версия формата (поле Version) отличается от версии Consul.
# При восстановлении новый кластер должен работать под той же версией Consul,
# что и исходный.
```

### Проверка размера и разбивки

```bash
# Общий размер
consul snapshot inspect -format=json backup.snap | jq '.Size'
# → 4115

# Детальная разбивка по типам данных
consul snapshot inspect -kvdetails backup.snap | grep -E "KVS|Register|Session"
# → KVS          27    12.3KB
# → Register     5     3.4KB
# → Session      1     199B
```

## Устранение неполадок

### Snapshot inspect показывает ошибку

- **Причина:** Файл поврежден или создан на несовместимой версии.
- **Диагностика:** Проверьте целостность файла и версию Consul:
  ```bash
  file /var/backups/consul/consul-latest.snap
  # → data (расширение .snap)

  consul version
  # → Consul v1.22.3
  ```
- **Решение:** Пересоздайте снапшот на кластере той же версии.

### Restore drill падает с ошибкой кворума

- **Причина:** В снапшоте сохранены старые ID серверов, а новый кластер имеет другие ID.
- **Решение:** Используйте `peers.json` для принудительного формирования кворума (см. `consul-disaster-recovery.md`).

### Тестовый кластер не стартует

- **Диагностика:** Проверьте права на директорию и порты:
  ```bash
  ls -la /tmp/consul-restore-test-*/
  # → владелец consul:consul

  ss -tlnp | grep 8500
  # → должен быть свободен
  ```
- **Решение:** Создайте пользователя consul или укажите другой порт через `-client=127.0.0.1:8501`.

### Индекс снапшота не растет

- **Причина:** Кластер не принимает новые записи (потеря лидера, сетевой partition).
- **Диагностика:** Проверьте статус кластера:
  ```bash
  consul operator raft list-peers
  # → должен показывать лидера

  consul info | grep leader
  # → leader = true
  ```
- **Решение:** Восстановите кворум перед созданием нового снапшота.

### Снапшот создается, но restore возвращает ошибку версии

- **Причина:** Новый кластер работает под другой версией Consul.
- **Решение:** Восстановление требует совпадения версий. Поднимите новый кластер под той же версией, что и исходный.

## Лучшие практики

- **Snapshot inspect после каждого бэкапа:** Автоматизируйте проверку в cron/systemd timer. Проверяйте `Index`, `Size`, `Version`.
- **Restore drill еженедельно:** Тестируйте восстановление на изолированном окружении. Документируйте RTO (время восстановления).
- **Монотонный индекс:** Следите, чтобы индекс снапшота monotonically увеличивается. Сброс индекса указывает на потерю данных.
- **Храните снапшоты версионированно:** `consul-<version>-<dc>-<date>.snap`.
- **Внешнее хранилище:** Выгружайте снапшоты за пределы кластера сразу после создания.
- **Шифрование:** Снапшоты содержат учетные данные. Храните их на зашифрованных носителях (LUKS, storage-level encryption).
- **Документируйте процедуру:** В runbook опишите шаги restore drill с контактами ответственных и RTO.
- **Согласованность:** Для production используйте `consistent` mode. Для не критичных бэкапов — `-stale`.
- **Ротация:** Удаляйте старые снапшоты по retention policy (например, старше 30 дней).

## Граничные случаи

- **Восстановление на новую major-версию:** Не поддерживается. Требуется совпадение версий Consul между кластерами.
- **Восстановление на новую minor-версию:** Официально не документировано как поддерживаемое. Тестируйте в staging перед использованием в production.
- **Enterprise vs OSS:** Снапшоты Enterprise несовместимы с OSS и наоборот.
- **Кластер >5000 узлов:** Snapshot inspect может занимать значительное время. Используйте `-stale` для снижения нагрузки на лидера при создании, но для inspect это не применимо.
- **Частые снапшоты на больших кластерах:** Могут вызывать IO-задержки. Увеличьте `snapshot_threshold` в конфигурации серверов.
- **Сеть с высоким RTT:** При создании снапшота в `consistent` mode лидер должен подтвердить свое лидерство, что добавляет задержку на round-trip.
- **Снапшот при деградации кластера:** Если лидер недоступен, используйте `-stale` на фолловере для создания аварийного снапшота.
- **Enterprise snapshot agent:** В Enterprise версии используйте встроенный `snapshot agent` вместо внешних скриптов. Он управляет расписанием, ретеншеном и может сохранять в S3, Azure Blob, GCS.
- **Multi-DC:** Снапшот является локальным для дата-центра. Для WAN-федерации создавайте снапшоты в каждом ДЦ отдельно.
- **Federated clusters:** При восстановлении федерации восстанавливайте primary DC первым, затем secondary.

## Дополнительная информация

- **[Consul Disaster Recovery](./consul-disaster-recovery.md)** — сценарии восстановления, `peers.json`, quorum loss.
- **[Consul Snapshot Command](https://developer.hashicorp.com/consul/commands/snapshot)** — CLI справочник.
- **[Consul Snapshot Inspect](https://developer.hashicorp.com/consul/commands/snapshot/inspect)** — детали команды inspect.
- **[Consul Backup and Restore](https://developer.hashicorp.com/consul/docs/manage/disaster-recovery/backup-restore)** — официальная документация.
- **[Consul CLI Reference](./consul_cli_reference.md)** — продвинутое использование CLI, включая snapshot команды.
- **[Consul Consensus](./consul_consensus.md)** — Raft-консенсус, кворум, peers.json.
