# Конфигурация и развертывание etcd

**Актуально для:** etcd 3.7.x (различия 3.5.x / 3.6.x указаны отдельно)

**etcd** в production почти никогда не запускается через флаги напрямую: используется YAML-конфигурация (`--config-file`) или environment variables, а жизненный цикл управляется systemd (bare metal / VM) или kubelet (Static Pod в Kubernetes). Правильная конфигурация критична для стабильности кластера.

## Определения

| Термин | Описание |
| :--- | :--- |
| **etcd.conf.yml** | YAML-файл конфигурации. Ключи — имена флагов без `--`. При указании `--config-file` флаги и env-переменные полностью игнорируются. |
| **ETCD_*-переменные** | Каждый флаг имеет соответствующую переменную: `--some-flag` → `ETCD_SOME_FLAG` (snake_case, верхний регистр, префикс `ETCD_`). |
| **Static Pod** | Под, управляемый kubelet напрямую через манифест в `/etc/kubernetes/manifests`. Стандартный способ запуска etcd в kubeadm-кластере. |
| **systemd unit** | Юнит для запуска etcd как системного сервиса (bare metal, VM). |
| **data-dir** | Директория данных: `member/snap/` (снапшоты и BoltDB-файл `db`), `member/wal/` (сегменты WAL). |
| **wal-dir** | Директория для WAL на отдельном диске (`--wal-dir`). Пусто по умолчанию — WAL хранится внутри `data-dir`. |
| **initial-cluster** | Список всех членов первичного кластера в формате `name=peerURL`. |
| **initial-cluster-state** | `new` для нового кластера, `existing` при добавлении к существующему. После успешной инициализации флаг игнорируется при рестартах. |
| **initial-cluster-token** | Идентификатор кластера, предотвращающий случайное слияние при восстановлении из снапшота. |

---

## Основные концепции

### Источники конфигурации и приоритеты

etcd принимает конфигурацию из трёх источников:

1. **Флаги командной строки** — `--flag-name value`
2. **Переменные окружения** — `ETCD_FLAG_NAME` (имя флага в snake_case в верхнем регистре с префиксом `ETCD_`; например, `--data-dir` → `ETCD_DATA_DIR`)
3. **Файл конфигурации** — YAML; путь указывается через `--config-file` или `ETCD_CONFIG_FILE`

**Правила приоритета** (проверено в `server/etcdmain/config.go`):

- Флаги командной строки имеют приоритет над переменными окружения.
- **Если указан файл конфигурации, все флаги и переменные окружения полностью игнорируются** — не «перекрываются», а именно игнорируются.

При загрузке конфига etcd логирует (поле `path` — путь к файлу):

```
loaded server configuration, other configuration command line flags and environment variables will be ignored if provided
```

Переменная `ETCD_VERSION` — специальная: etcd сбрасывает её и логирует предупреждение `cannot set special environment variable`.

### Структура конфигурационного файла

Ключи YAML — имена флагов без `--`. TLS-параметры вложены в секции `client-transport-security` и `peer-transport-security` (плоские ключи вида `peer-trusted-ca-file` в YAML не работают):

```yaml
# /etc/etcd/etcd.conf.yml
name: node1
data-dir: /var/lib/etcd

# Raft
listen-peer-urls: https://10.0.1.10:2380
initial-advertise-peer-urls: https://10.0.1.10:2380
initial-cluster: node1=https://10.0.1.10:2380,node2=https://10.0.1.11:2380,node3=https://10.0.1.12:2380
initial-cluster-state: existing
initial-cluster-token: etcd-cluster-1

# Client
listen-client-urls: https://10.0.1.10:2379
advertise-client-urls: https://10.0.1.10:2379

# TLS — вложенные секции, ключи без префиксов client-/peer-
client-transport-security:
  cert-file: /etc/etcd/pki/server.crt
  key-file: /etc/etcd/pki/server.key
  trusted-ca-file: /etc/etcd/pki/ca.crt
  client-cert-auth: true
peer-transport-security:
  cert-file: /etc/etcd/pki/peer.crt
  key-file: /etc/etcd/pki/peer.key
  trusted-ca-file: /etc/etcd/pki/ca.crt
  client-cert-auth: true

# Performance
auto-compaction-retention: "1"   # periodic-режим: целое число = часы (1 час)
quota-backend-bytes: 8589934592  # 8 GiB — рекомендуемый максимум (см. limits_and_constraints.md)
snapshot-count: 10000
heartbeat-interval: 100
election-timeout: 1000

# Logging
log-level: info
logger: zap
```

Полный пример конфига — [`etcd.conf.yml.sample`](https://github.com/etcd-io/etcd/blob/main/etcd.conf.yml.sample) в репозитории etcd.

**Duration-поля в конфиге — наносекунды.** Поля, тип которых в коде — `time.Duration` (`grpc-keepalive-min-time`, `grpc-keepalive-interval`, `grpc-keepalive-timeout`, `backend-batch-interval`, `corrupt-check-time`, `compact-hash-check-time`, `compaction-sleep-interval`, `watch-progress-notify-interval`, `warning-apply-duration`, `warning-unary-request-duration`, `downgrade-check-time`), принимают человекочитаемые строки (`10m`, `5s`) как флаги, но **в файле конфигурации — только целые числа в наносекундах** (известное ограничение стандартной библиотеки Go, golang/go#10275):

```yaml
# Корректно: 10 минут в наносекундах
watch-progress-notify-interval: 600000000000

# Ошибка: ошибка unmarshal
watch-progress-notify-interval: '10m'
```

`auto-compaction-retention` — исключение: это строковое поле, `5m` в файле работает (парсится через `time.ParseDuration`).

### Layout data-dir

```
<data-dir>/
└── member/
    ├── snap/
    │   ├── db                      # BoltDB-файл (основное хранилище)
    │   ├── {term}-{index}.snap     # снапшоты Raft
    │   └── {index}.snap.db         # снапшоты MVCC (v3)
    └── wal/
        ├── 0.tmp                   # временный файл при создании сегмента
        └── {seq}-{index}.wal       # сегменты WAL (по 64 MiB)
```

- Файл `db` находится в `member/snap/`, а не в корне `data-dir` и не в `member/`.
- Размер сегмента WAL — 64 MiB, зашит в код, не настраивается.
- `--wal-dir` позволяет разнести WAL на отдельный диск нативно, без симлинков (см. [Разделение WAL и данных](#разделение-wal-и-данных)).

---

## Установка и настройка

### Запуск через systemd (bare metal / VM)

```ini
# /etc/systemd/system/etcd.service
[Unit]
Description=etcd key-value store
Documentation=https://etcd.io/docs/v3.7/
After=network.target

[Service]
Type=notify
User=etcd
Group=etcd
ExecStart=/usr/bin/etcd --config-file=/etc/etcd/etcd.conf.yml
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

**Важно:**
- `LimitNOFILE` должен быть ≥ 65536 (по умолчанию часто 1024). При лимите ≤ 150 etcd аварийно завершается при старте: `file descriptor limit of etcd process is too low; please set higher` — 150 fd резервируется под внутренние нужды (WAL, снапшоты, transport, fd-монитор).
- `User=etcd` / `Group=etcd` — etcd не должен работать от root; директория `data-dir` должна принадлежать этому пользователю.
- `RestartSec=5s` предотвращает слишком частые перезапуски при сбоях.
- `Type=notify` — etcd отправляет `sd_notify`, systemd знает о реальном статусе готовности.
- Проверка фактического лимита: `cat /proc/$(pgrep etcd)/limits | grep "open files"`.

### Запуск как Static Pod (Kubernetes)

```yaml
# /etc/kubernetes/manifests/etcd.yaml
apiVersion: v1
kind: Pod
metadata:
  name: etcd
  namespace: kube-system
spec:
  containers:
  - name: etcd
    image: registry.k8s.io/etcd:3.7.2-0   # формат тега: <etcd-version>-<image-revision>
    command:
    - etcd
    - --config-file=/etc/etcd/etcd.conf.yml
    volumeMounts:
    - name: etcd-data
      mountPath: /var/lib/etcd
    - name: etcd-conf
      mountPath: /etc/etcd
    - name: pki
      mountPath: /etc/kubernetes/pki/etcd
      readOnly: true
  volumes:
  - name: etcd-data
    hostPath:
      path: /var/lib/etcd
  - name: etcd-conf
    hostPath:
      path: /etc/etcd
  - name: pki
    hostPath:
      path: /etc/kubernetes/pki/etcd
```

**Важно:**
- kubelet перезапускает Static Pod **только при изменении самого манифеста** в `/etc/kubernetes/manifests`. Изменение смонтированного `/etc/etcd/etcd.conf.yml` автоматического перезапуска не вызывает — после правки конфига Pod нужно перезапустить вручную (`kubectl delete pod etcd -n kube-system` или временно убрать/вернуть манифест).
- Теги образов etcd в `registry.k8s.io` имеют формат `<etcd-version>-<image-revision>` (например, `3.5.21-0`); тег вида `registry.k8s.io/etcd:3.7.2` — некорректный формат.
- `hostPath`-директории должны существовать на control-plane узле, иначе Pod не запустится.
- В Kubernetes компакцию keyspace выполняет kube-apiserver (`--etcd-compaction-interval`), поэтому `--auto-compaction-retention` на стороне etcd обычно оставляют выключенной (`0`) — конкурирующие компакторы ломают длинные watch-потоки (см. [kubernetes_integration.md](./kubernetes_integration.md)).

### Разделение WAL и данных

Для минимизации задержек `fdatasync` размещайте WAL и данные на отдельных дисках — нативный флаг `--wal-dir`:

```yaml
# /etc/etcd/etcd.conf.yml
data-dir: /var/lib/etcd        # диск 1 (снапшоты + BoltDB)
wal-dir: /var/lib/etcd-wal     # диск 2 (dedicated WAL)
```

**Валидация:**
```bash
# Проверить, что WAL на отдельном диске
df -h /var/lib/etcd-wal
# → /dev/nvme1n1p1
```

Симлинки (`ln -s`) — устаревший костыль: `--wal-dir` решает задачу нативно.

---

## Операции и команды

### Ключевые флаги

Полный список: `etcd --help` или [Configuration options](https://etcd.io/docs/v3.7/op-guide/configuration/). Ключевые флаги с дефолтами (3.7.x):

**Member:**

| Флаг | Default | Назначение |
| :--- | :--- | :--- |
| `--name` | `default` | Человекочитаемое имя члена |
| `--data-dir` | `${name}.etcd` | Директория данных |
| `--wal-dir` | `''` | Директория WAL на отдельном диске |
| `--snapshot-count` | `10000` | Число коммитов между автоматическими снапшотами |
| `--max-snapshots` / `--max-wals` | `5` / `5` | Число хранимых файлов снапшотов / сегментов WAL (`0` = без ограничения) |
| `--memory-mlock` | `false` | Закреплять страницы etcd (в частности bbolt) в RAM |
| `--quota-backend-bytes` | `0` | Квота backend; `0` = low space quota (2 GiB) |
| `--backend-bbolt-freelist-type` | `map` | Тип freelist bbolt (`array` / `map`) |
| `--max-txn-ops` | `128` | Макс. операций в транзакции |
| `--max-request-bytes` | `1572864` | Макс. размер клиентского запроса (1.5 MiB) |

**Raft / Clustering:**

| Флаг | Default | Назначение |
| :--- | :--- | :--- |
| `--heartbeat-interval` | `100` | Интервал heartbeat, мс |
| `--election-timeout` | `1000` | Таймаут выборов, мс; должен быть ≥ 5× `heartbeat-interval`, максимум 50000 мс |
| `--initial-election-tick-advance` | `true` | Быстрый форвард начальных тиков для ускорения выборов |
| `--listen-peer-urls` | `http://localhost:2380` | URL для peer-трафика |
| `--listen-client-urls` | `http://localhost:2379` | URL для gRPC-клиентов (и HTTP, если не задан `--listen-client-http-urls`) |
| `--listen-client-http-urls` | `''` | (3.7+) URL только для HTTP-трафика; убирает HTTP из `--listen-client-urls` |
| `--advertise-client-urls` | `http://localhost:2379` | URL, анонсируемые клиентам |
| `--initial-advertise-peer-urls` | `http://localhost:2380` | Peer URL, анонсируемый кластеру |
| `--initial-cluster` | `default=http://localhost:2380` | Состав кластера при bootstrap |
| `--initial-cluster-state` | `new` | `new` / `existing`; игнорируется при рестартах после инициализации |
| `--initial-cluster-token` | `etcd-cluster` | Токен кластера при bootstrap |
| `--pre-vote` | `true` | Алгоритм Pre-Vote (защита от разделённого узла при возврате в кластер) |
| `--strict-reconfig-check` | `true` | Отклонять реконфигурации, ведущие к потере кворума |
| `--auto-compaction-retention` | `0` | Автокомпакция (`0` = выключена) |
| `--auto-compaction-mode` | `periodic` | `periodic` / `revision` |
| `--snapshot-catchup-entries` | `5000` | Число entry для догона медленного follower после компакции raft-хранилища |

**Security / Auth:**

| Флаг | Default | Назначение |
| :--- | :--- | :--- |
| `--cert-file` / `--key-file` | `''` | TLS-сертификат и ключ для клиентских соединений |
| `--client-cert-auth` | `false` | mTLS для клиентов |
| `--trusted-ca-file` | `''` | CA для клиентов; **автоматически включает client cert auth** независимо от `--client-cert-auth` |
| `--peer-cert-file` / `--peer-key-file` | `''` | TLS-сертификат и ключ для peer-соединений |
| `--peer-client-cert-auth` | `false` | mTLS для peer |
| `--peer-trusted-ca-file` | `''` | CA для peer |
| `--auto-tls` / `--peer-auto-tls` | `false` | Автогенерируемые сертификаты |
| `--self-signed-cert-validity` | `1` | Срок автогенерируемых сертификатов, годы |
| `--tls-min-version` | `TLS1.2` | Мин. версия TLS |
| `--auth-token` | `simple` | Тип токена аутентификации (`simple` / `jwt`) |
| `--bcrypt-cost` | `10` | Стоимость bcrypt для хеширования паролей (4–31) |
| `--auth-token-ttl` | `300` | TTL токена аутентификации, секунды |

**Logging / Monitoring:**

| Флаг | Default | Назначение |
| :--- | :--- | :--- |
| `--logger` | `zap` | Только `zap` (структурированное логирование) |
| `--log-level` | `info` | `debug`, `info`, `warn`, `error`, `panic`, `fatal` |
| `--log-format` | `json` | `json` / `console` |
| `--log-outputs` | `default` | `stdout` / `stderr` отключают journald даже под systemd |
| `--metrics` | `basic` | `extensive` добавляет серверные gRPC-гистограммы |
| `--listen-metrics-urls` | `''` | URL для metrics и health-эндпоинтов |
| `--enable-pprof` | `false` | Профилирование через `/debug/pprof/` |

**Прочее:**

| Флаг | Default | Назначение |
| :--- | :--- | :--- |
| `--feature-gates` | — | Feature gates (заменили `--experimental-*` в 3.7; например, `--feature-gates=CompactHashCheck=true`) |
| `--grpc-keepalive-min-time` | `5s` | Мин. интервал между keepalive-пингами клиента |
| `--grpc-keepalive-interval` | `2h` | Частота серверных keepalive-пингов (`0` = отключить) |
| `--grpc-keepalive-timeout` | `20s` | Таймаут неотвечающего соединения (`0` = отключить) |
| `--enable-grpc-gateway` | `true` | gRPC gateway (HTTP/JSON → gRPC) |
| `--force-new-cluster` | `false` | Создать одночленный кластер из существующего data-dir (unsafe, см. [emergency_recovery.md](./emergency_recovery.md)) |
| `--unsafe-no-fsync` | `false` | Отключает fsync — потеря данных (unsafe) |

### Валидация конфигурации

```bash
# 1. Действующая конфигурация логируется при старте — ищите строку
#    "starting an etcd server" с полным effective config:
journalctl -u etcd | grep "starting an etcd server"
# → {"level":"info",...,"msg":"starting an etcd server","etcd-version":"3.7.2",
#    "name":"node1","data-dir":"/var/lib/etcd","wal-dir":"/var/lib/etcd-wal",
#    "heartbeat-interval":"100ms","election-timeout":"1s",
#    "initial-cluster":"node1=https://10.0.1.10:2380,...",
#    "initial-cluster-state":"existing","quota-backend-bytes":8589934592,...}

# 2. Фактические параметры процесса
ps aux | grep etcd
systemctl show etcd -p ExecStart

# 3. Работоспособность кластера
etcdctl endpoint health --cluster
etcdctl endpoint status --cluster -w table
```

**Правила валидации при старте** (проверяются в `server/embed/config.go`, `Validate()`):

- `election-timeout` должен быть ≥ 5× `heartbeat-interval`: `election-timeout[%vms] should be at least as 5 times as heartbeat-interval[%vms]`; максимум — 50000 мс.
- `--advertise-client-urls` обязателен, если `--listen-client-urls` задан явно.
- Нельзя биндить один URL одновременно в `--listen-client-urls` и `--listen-client-http-urls`: `cannot bind both --listen-client-urls and --listen-client-http-urls on the same url`.
- HTTPS-URL требует TLS: `TLS key/cert (--cert-file, --key-file) must be provided for client url %s with HTTPS scheme`.
- Одновременное указание нескольких механизмов bootstrap: `multiple discovery or bootstrap flags are set. Choose one of "initial-cluster", "discovery-endpoints" or "discovery-srv"`.
- `--discovery-fallback proxy` отклоняется: `v2 proxy is deprecated, and --discovery-fallback can't be configured as "proxy"`.
- HTTP и gRPC на одном порту: предупреждение `Running http and grpc server on single port. This is not recommended for production.`

### Изменение конфигурации

**Hot-reload не поддерживается**: все параметры требуют перезапуска процесса. Изменение через `etcdctl` невозможно — etcd не хранит конфигурацию в keyspace (ключа `/db/config` не существует), и `quota-backend-bytes` нельзя изменить через `etcdctl maintenance`.

Перезапуск с минимальным влиянием:

```bash
# 1. Передать лидерство другому узлу (чтобы клиенты не теряли запись на время рестарта)
etcdctl move-leader <OTHER_MEMBER_ID>

# 2. Перезапустить etcd
systemctl restart etcd

# 3. Проверить здоровье
etcdctl endpoint health --cluster
```

### Изменение URL члена

- **`--advertise-client-urls`**: обновить конфиг и перезапустить — достаточно.
- **Peer URLs**: сначала обновить membership, потом перезапуск:
  ```bash
  etcdctl member update <MEMBER_ID> --peer-urls=https://10.0.1.10:2380
  # затем перезапустить etcd с новыми --listen-peer-urls / --initial-advertise-peer-urls
  ```
- **`--name`**: сменить in-place нельзя (`etcdctl member update` меняет только peer-urls). Требуется `etcdctl member remove` + `member add` с пустым `data-dir` (см. [clustering_and_recovery.md](./clustering_and_recovery.md)).

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `file descriptor limit of etcd process is too low; please set higher` | Лимит fd ≤ 150 | Поднять `LimitNOFILE` в systemd (≥ 65536) |
| `election-timeout[%vms] should be at least as 5 times as heartbeat-interval[%vms]` | Слишком короткий election-timeout | Установить election-timeout ≥ 5× heartbeat-interval |
| `TLS key/cert (--cert-file, --key-file) must be provided for client url ... with HTTPS scheme` | HTTPS без сертификатов | Указать `cert-file`/`key-file` или использовать http |
| `cannot bind both --listen-client-urls and --listen-client-http-urls on the same url` | Дублирующийся URL | Убрать пересечение URL |
| `multiple discovery or bootstrap flags are set...` | Указано несколько механизмов bootstrap | Оставить один: `initial-cluster`, `discovery-endpoints` или `discovery-srv` |
| `v2 proxy is deprecated, and --discovery-fallback can't be configured as "proxy"` | `--discovery-fallback proxy` | Использовать `exit` |
| `data-dir %q not empty or could not be read` | `etcdutl snapshot restore` в непустую директорию | Указать новую/пустую `--data-dir` для restore |
| `wal-dir %q exists` | `etcdutl snapshot restore` в существующий WAL-dir | Указать новый `--wal-dir` |
| `etcdserver: assign ids error: the member count is unequal` | `--initial-cluster` не совпадает с составом при bootstrap/restore | Сверить `--initial-cluster` со списком членов |
| `etcdserver: assign ids error: unmatched member while checking PeerURLs` | Peer URL не совпадает с `--initial-cluster` | Проверить `--name` и peer URL в `--initial-cluster` |
| `etcd: this member has been permanently removed from the cluster. Exiting.` | Член удалён через `member remove` | Восстановить из снапшота или добавить заново |
| `context deadline exceeded` при старте | WAL поврежден или диск недоступен | Проверить WAL через `etcd-dump-logs`, `df -h`, `dmesg` |
| `no such file or directory: /etc/etcd/etcd.conf.yml` | Неверный путь к конфигу | Проверить `--config-file` / `ETCD_CONFIG_FILE` |

---

## Best Practices

- **Используйте `--config-file`:** все параметры в одном YAML; флаги в systemd-юните дублировать не нужно (при наличии конфига они всё равно игнорируются).
- **`LimitNOFILE=65536`:** обязательно для production.
- **Отдельный диск для data-dir:** никогда не размещайте `data-dir` на общем диске с ОС или другими сервисами; WAL — на отдельном диске (`--wal-dir`).
- **`initial-cluster-token`:** уникальный токен для каждого кластера; восстановление из снапшота с общим токеном может слить кластеры.
- **Секреты:** etcd.conf.yml не подставляет переменные окружения — не храните пароли в конфиге; ограничьте права на файл (только пользователь etcd) или монтируйте секреты (Kubernetes Secrets, Vault).
- **Планируйте перезапуски:** hot-reload не поддерживается — изменения требуют окна обслуживания и передачи лидерства.
- **Проверяйте effective config:** после старта ищите `starting an etcd server` в журнале — там фактические значения всех параметров.

---

## Edge Cases

- **Непустой data-dir при `--initial-cluster-state new`:** etcd не падает — он стартует как существующий член, читая состав кластера из data-dir. Ошибки «data-dir already exists» при обычном старте не существует; `data-dir %q not empty or could not be read` — только у `etcdutl snapshot restore`.
- **Смена `--name`:** невозможна in-place; требуется remove + re-add с пустым data-dir.
- **Смена `--listen-peer-urls`:** требует `etcdctl member update` и обновления `--initial-cluster`.
- **Восстановление на другую архитектуру:** amd64 ↔ arm64 совместимы (оба little-endian). При смене endianness (например, amd64 → s390x, big-endian) используйте логический backup (`etcdctl get --prefix`).
- **Static Pod и `hostPath`:** убедитесь, что `hostPath` существует на всех control-plane узлах, иначе Pod не запустится.
- **`--trusted-ca-file` включает mTLS:** установка CA автоматически включает client cert auth, даже если `--client-cert-auth: false`.

---

## См. также

* **[Лимиты и ограничения](./limits_and_constraints.md)** — quota-backend-bytes, max-request-bytes, размеры WAL.
* **[Тюнинг ядра](./kernel_tuning.md)** — fd-лимит, дисковый I/O.
* **[Безопасность etcd](./security.md)** — TLS-модель, RBAC, rotation сертификатов.
* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — пути записи и чтения.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — развёртывание и бэкап кластера.
* **[etcd в Kubernetes](./kubernetes_integration.md)** — etcd в K8s, компакция kube-apiserver.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики и логирование.
* **[Configuration options](https://etcd.io/docs/v3.7/op-guide/configuration/)** — полный список флагов (официальная документация).
