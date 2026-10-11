# Consul CLI — продвинутое использование

**Актуально для:** Consul 2.0.x / 1.22.x / 1.20.x / 1.19.x

## Определения

**Consul CLI** — единое бинарное приложение `consul`, принимающее подкоманды для всех операций с кластером: от базовых (`kv put`, `members`) до операторских (`operator raft`, `operator autopilot`) и диагностических (`debug`, `troubleshoot`). Все команды оборачивают HTTP API и возвращают non-zero exit status при ошибках.

**Subcommand** — группа логически связанных операций (например, `consul operator raft`, `consul snapshot save`).

**Consistent mode** — режим, при котором запрос направляется лидеру, который подтверждает лидерство перед записью. Гарантирует полную согласованность. Используется по умолчанию для большинства команд.

**Stale mode** — режим, при котором запрос может быть обработан любым сервером без перенаправления на лидера. Снижает задержку, но может вернуть устаревшие данные (на ~100 мс). Указывается флагом `-stale`.

**Gossip-пул** — группа узлов, обменивающихся сообщениями через протокол gossip. Consul имеет LAN-пул (внутри дата-центра) и WAN-пул (между дата-центрами).

## Основные концепции

### Полный каталог команд

| Категория | Команды | Назначение |
| :--- | :--- | :--- |
| **Agent** | `members`, `info`, `monitor`, `reload`, `leave`, `force-leave` | Статус агентов, перезагрузка, graceful/force shutdown |
| **Operator** | `operator raft`, `operator autopilot`, `operator audit`, `operator usage`, `operator utilization` | Raft-кворум, Autopilot, аудит (Enterprise) |
| **ACL** | `acl bootstrap`, `acl token`, `acl policy`, `acl role` | Управление доступом |
| **Config** | `config write`, `config read`, `config list`, `config validate`, `config delete` | Config entries (service defaults, splitter, resolver) |
| **Connect** | `connect`, `intention`, `troubleshoot proxy` | Service Mesh: intentions, TLS, диагностика |
| **KV** | `kv put`, `kv get`, `kv delete`, `kv list`, `kv export`, `kv import` | Ключ-значение хранилище |
| **Services** | `services`, `catalog services`, `service register` | Каталог сервисов |
| **Health** | `health checks`, `health service` | Проверки здоровья |
| **Snapshot** | `snapshot save`, `snapshot restore`, `snapshot inspect`, `snapshot agent` (Enterprise), `snapshot decode` | Резервное копирование |
| **Debug** | `debug` | Сбор диагностического архива |
| **Keyring** | `keyring -list`, `keyring -install`, `keyring -use`, `keyring -remove` | Управление gossip-шифрованием |
| **Event** | `event` | Публикация событий через gossip |
| **Exec** | `exec` | Удаленное выполнение команд через gossip |
| **Troubleshoot** | `troubleshoot ports`, `troubleshoot proxy`, `troubleshoot upstreams` | Диагностика сети и Service Mesh |
| **Other** | `validate`, `version`, `watch`, `lock`, `maint`, `join`, `rtt` | Валидация, версия, блокировки, maintenance |

### Переменные окружения CLI

CLI флаги имеют наивысший приоритет, но переменные окружения удобны для скриптов и систем инициализации:

| Переменная | Назначение | Пример |
| :--- | :--- | :--- |
| `CONSUL_HTTP_ADDR` | Адрес HTTP API Consul | `127.0.0.1:8500`, `https://consul.service.consul:8501`, `unix:///var/run/consul.sock` |
| `CONSUL_HTTP_TOKEN` | ACL-токен для API запросов | `aba7cbe5-879b-999a-07cc-2efd9ac0ffe` |
| `CONSUL_HTTP_TOKEN_FILE` | Путь к файлу с токеном | `/etc/consul.d/.token` |
| `CONSUL_HTTP_AUTH` | HTTP Basic auth (user:pass) | `operations:JPIMCmhDHzTukgO6` |
| `CONSUL_HTTP_SSL` | Включить HTTPS | `true` |
| `CONSUL_HTTP_SSL_VERIFY` | Проверять TLS-сертификат | `false` (только для dev) |
| `CONSUL_CACERT` | Путь к CA-сертификату | `/etc/consul.d/ca.crt` |
| `CONSUL_CAPATH` | Директория с CA-сертификатами | `/etc/consul.d/ca_certs/` |
| `CONSUL_CLIENT_CERT` | Клиентский сертификат | `/etc/consul.d/client.crt` |
| `CONSUL_CLIENT_KEY` | Приватный ключ клиента | `/etc/consul.d/client.key` |
| `CONSUL_TLS_SERVER_NAME` | SNI имя сервера | `consulserver.domain` |
| `CONSUL_GRPC_ADDR` | Адрес gRPC API (для Envoy) | `127.0.0.1:8502` |
| `CONSUL_NAMESPACE` | Enterprise: namespace по умолчанию | `default` |
| `CONSUL_DATACENTER` | Дата-центр по умолчанию | `dc1` |
| `CONSUL_STALE` | Использовать stale mode по умолчанию | `true` |

### Автодополнение

Включите автодополнение для вашей оболочки:

```bash
consul -autocomplete-install
# Перезапустите shell, затем:
# $ consul o<TAB>
# operator
```

## Практические сценарии

### 1. Мониторинг кластера в реальном времени

```bash
# Поток логов агента с указанного узла
consul monitor -log-level=info
# → [INFO]  agent: Synced node info
# → [INFO]  agent: Synced service "web"
# → [WARN]  agent: State sync failed: connection refused

# В JSON-формате для парсинга
consul monitor -log-level=debug -log-json
```

`-log-level` поддерживает `trace`, `debug`, `info`, `warn`, `error`. Можно запросить более детальный уровень, чем настроен в агенте: если агент работает на `warn`, `monitor -log-level=debug` покажет debug-события.

### 2. Диагностика Raft-кворума

```bash
# Список серверов с их статусами
consul operator raft list-peers
# → Node     ID              Address         State     Voter  RaftProtocol  Commit Index  Trails Leader By
# → alice    127.0.0.1:8300  127.0.0.1:8300  follower  true   3             1167         0 commits
# → bob      127.0.0.2:8300  127.0.0.2:8300  leader    true   3             1167         -
# → carol    127.0.0.3:8300  127.0.0.3:8300  follower  true   2             1159         8 commits

# При аварии кластера (нет лидера) используйте -stale
consul operator raft list-peers -stale

# Статус Autopilot
consul operator autopilot health
# → Server          Healthy    Last Contact    Raft Version
# → server1         true       12ms            3

# Текущая конфигурация Autopilot
consul operator autopilot get-config
# → CleanupDeadServers = true
# → LastContactThreshold = 200ms
# → MaxTrailingLogs = 250

# Изменение конфигурации Autopilot
consul operator autopilot set-config -min-quorum=3 -last-contact-threshold=500ms
# → Configuration updated!

# Состояние Autopilot
consul operator autopilot state
# → Healthy: true
# → Failure Tolerance: 1
# → Leader: 79324811-9588-4311-b208-f272e38aaabf

# Ручная передача лидерства (по ID, не по address)
consul operator raft transfer-leader -id="79324811-9588-4311-b208-f272e38aaabf"
# Без -id передается случайному серверу

# Удаление невалидного пира
consul operator raft remove-peer -id="dead-server-uuid"
```

### 3. Сбор диагностического архива

```bash
# Сбор полного архива (по умолчанию 5 минут, интервал 30с)
consul debug -duration=5m -interval=30s -output=/tmp/consul-debug.tar.gz
# → Archive created: /tmp/consul-debug.tar.gz

# Содержимое архива:
# - agent/     — конфигурация и версия агента
# - host/      — CPU, memory, disk
# - members/   — LAN и WAN участники
# - metrics/   — метрики Prometheus за интервал
# - logs/      — TRACE логи за duration
# - pprof/     — heap, CPU, goroutine профили (требует enable_debug=true)

# Выборочный сбор (например, без pprof)
consul debug -capture agent -capture host -capture logs -capture metrics
```

> **Важно:** Архив может содержать чувствительные данные. Проверяйте содержимое перед отправкой в поддержку.

### 4. Управление config entries

```bash
# Валидация перед применением
consul config validate service-defaults.hcl
# → Valid configuration

# Запись
consul config write service-defaults.hcl
# → Config entry written

# Чтение конкретного entry
consul config read -kind service-defaults -name billing-api

# Список всех entries определенного типа
consul config list -kind service-defaults

# Удаление
consul config delete -kind service-splitter -name web-api
```

### 5. Диагностика Service Mesh

```bash
# Проверка связности прокси
consul troubleshoot proxy -upstream-ip 10.0.1.50
# → ✓ Certificates are valid
# → ✓ Envoy has 0 rejected configurations
# → ✓ Envoy has detected 0 connection failure(s)

# Проверка intentions
consul intention match -source web-api -destination billing-api
# → Allowed

# Проверка портов
consul troubleshoot ports
# → TCP: Port 8500 on localhost is open.
# → TCP: Port 8301 on localhost is open.

# С exported services (peering)
consul catalog services -peer=cluster-b
```

### 6. Управление gossip keyring

```bash
# Список ключей (LAN и WAN)
consul keyring -list
# → WAN:
# →   a1i101sMY8rxB+0eAKD/gw== [2/2]
# → dc1 (LAN):
# →   a1i101sMY8rxB+0eAKD/gw== [2/2]

# Установка нового ключа (распространяется на все узлы)
consul keyring -install <NEW_KEY>
# → Key installed successfully

# Смена первичного ключа (должен быть уже установлен)
consul keyring -use <NEW_KEY>
# → Key activated successfully

# Удаление старого ключа (не первичного)
consul keyring -remove <OLD_KEY>
# → Key removed successfully

# Только локальный сервер (без WAN-запроса)
consul keyring -list -local-only
```

> **Важно:** Keyring операции влияют на LAN и WAN пулы одновременно. Только `-list` может быть ограничен локально через `-local-only`.

### 7. События и удаленное выполнение

```bash
# Публикация события (gossip, best-effort доставка)
consul event -name="deploy" -service="web" web-api v2.3.1
# → Event fired: deploy

# Удаленное выполнение команды на узлах
consul exec -service="web" -wait=30s "uptime"
# → node1: 14:23:01 up 10 days
# → node2: 14:23:01 up 5 days

# Ограничение по узлам
consul exec -node="web-.*" "systemctl status nginx"
```

> **Важно:** События и exec используют gossip. Доставка не гарантирована, данные не персистятся. Для критичных задач используйте API/KV.

### 8. Операции с снапшотами

```bash
# Создание снапшота (consistent mode по умолчанию)
consul snapshot save /tmp/backup.snap
# → Saved and verified snapshot to index 8419

# Создание с appended metadata (filename)
consul snapshot save -append-filename version,dc /tmp/backup.snap
# → Saved: backup-1.22.3-dc1.snap

# Проверка снапшота
consul snapshot inspect /tmp/backup.snap
# → ID:           2-5-1477944140022
# → Size:         667
# → Index:        5
# → Term:         2
# → Version:      1

# Детальная инспекция в JSON
consul snapshot inspect -format=json /tmp/backup.snap | jq '.Index'
# → 8419

# Восстановление
consul snapshot restore /tmp/backup.snap
# → Restored snapshot

# Enterprise: периодические снапшоты через встроенный агент
consul snapshot agent -config-file=/etc/consul.d/snapshot.hcl
```

### 9. Управление участниками кластера

```bash
# Список участников
consul members
# → Node      Address         Status  Type    Build  Protocol
# → server1   10.0.1.10:8301  alive   server  1.22.3  3
# → client1   10.0.1.20:8301  alive   client  1.22.3  3

# Подробная информация об агенте
consul info | grep -E "leader|version|dc"
# → leader = true
# → version = 1.22.3
# → datacenter = dc1

# Принудительный leave (узел не отвечает)
consul force-leave server3 -prune
# → Node forcefully removed from cluster

# Force leave для WAN
consul force-leave server1.dc2 -wan

# Graceful leave
consul leave
# → Gracefully leaving...
```

### 10. Валидация и обслуживание

```bash
# Валидация конфигурационных файлов
consul validate /etc/consul.d/
# → Config file(s) valid

# Перевод узла в maintenance mode
consul maint -enable -reason="kernel update"
# → Node entered maintenance mode

# Вывод из maintenance
consul maint -disable

# Версия CLI
consul version
# → Consul v1.22.3
# → Consul Protocol: 2 (Fails to support protocol versions: 1)
```

## Устранение неполадок

### `consul members` показывает узлы как `failed`

- **Причина:** Gossip-порты (8301/8302 UDP) заблокированы firewall, или узел не ответил за `serf_lan` timeout (по умолчанию 72 часа до reap).
- **Диагностика:**
  ```bash
  ss -u -lpn | grep 8301
  # → должен слушать

  iptables -L -n | grep 8301
  # → должен быть ACCEPT
  ```
- **Решение:** Откройте UDP порты. Если узел уже dead — `consul force-leave <node>`.

### `consul operator raft list-peers` показывает `non-voter` или learner

- **Причина:** Узел добавлен как Learner и еще не синхронизировался, либо Autopilot еще не promoted его.
- **Диагностика:**
  ```bash
  consul operator autopilot state
  # → проверьте Healthy и Last Contact

  consul operator autopilot get-config
  # → ServerStabilizationTime — время перед promotion
  ```
- **Решение:** Дождитесь stabilization time. Если узел здоров и не promoted — проверьте `MinQuorum` и `CleanupDeadServers`.

### `consul debug` создает слишком большой архив

- **Решение:** Уменьшите `-duration` или ограничьте capture targets:
  ```bash
  consul debug -duration=1m -interval=10s -capture agent -capture host
  ```

### Config entry не применяется

- **Диагностика:**
  ```bash
  consul config validate service-defaults.hcl
  ```
- **Решение:** Исправьте синтаксические ошибки. Проверьте, что ACL-токен имеет права на `service:write` или `operator:write` в зависимости от типа config entry.

### Snapshot inspect показывает ошибку

- **Причина:** Файл поврежден или создан на несовместимой версии Consul.
- **Диагностика:**
  ```bash
  consul version
  # → должен совпадать с версией кластера, создавшего снапшот
  ```
- **Решение:** Пересоздайте снапшот.

### `consul event` или `consul exec` не доставляются

- **Причина:** Gossip не работает (разделенный кластер, отключенные порты).
- **Диагностика:**
  ```bash
  consul members
  # → все узлы должны быть alive

  ss -u -lpn | grep 8301
  ```
- **Решение:** Восстановите LAN-связность. Помните: доставка best-effort, без гарантий.

## Лучшие практики

- **Согласованность версий:** Используйте одинаковые версии CLI и серверов. Версия протокола отображается в `consul version`.
- **Stale mode для read-only:** Для `members`, `catalog services`, `health service` используйте `-stale` для снижения нагрузки на лидера.
- **Автодополнение:** Включайте `consul -autocomplete-install` на всех рабочихstations операторов.
- **Токены через файлы:** Используйте `CONSUL_HTTP_TOKEN_FILE` вместо `CONSUL_HTTP_TOKEN`, чтобы не暴露 токены в процессах (`ps aux`).
- **Валидация:** Всегда `consul config validate` перед `consul config write`.
- **Debug archives:** Собирайте debug только при проблемах. Архивики могут содержать чувствительные данные.
- **Keyring rotation:** Ротируйте gossip ключи регулярно. Используйте `-install` → `-use` → `-remove` последовательность.
- **Force-leave:** Используйте только для неработающих узлов. Живой узел пересоединится.
- **Scripts over manual:** Автоматизируйте через bash/Python/Terraform, а не через ручные CLI вызовы.
- **Documentation:** В runbook фиксируйте точные версии CLI и флаги для операций в production.

## Граничные случаи

- **CLI версии:** Несовместимость версий CLI и серверов может привести к ошибкам сериализации или нераспознанным флагам. Используйте версию CLI >= версии серверов.
- **Large clusters (>5000 узлов):** `consul members` и `consul catalog services` могут быть медленными. Используйте фильтры:
  ```bash
  consul members -service="web"
  consul catalog services -tag="production"
  ```
- **Multi-DC:** Большинству команд требуется `-datacenter=<dc>`, если вы обращаетесь к агенту в другом ДЦ. Исключения: `operator raft`, `snapshot` (локальный для агента).
- **ACL:** Операторские команды (`operator raft remove-peer`, `operator autopilot set-config`) требуют `operator:write`. Read-only операторские команды требуют `operator:read`.
- **Enterprise-only:** `operator audit`, `snapshot agent`, `namespace`, `partition` доступны только в Enterprise.
- **Gossip best-effort:** `event` и `exec` не гарантируют доставку. Не используйте для критичных операций.
- **Unix socket:** `CONSUL_HTTP_ADDR=unix:///var/run/consul.sock` поддерживается, но требует соответствующей конфигурации агента (`addresses.api = "unix:///var/run/consul.sock"`).
- **Stale на лидере:** Флаг `-stale` на лидере не имеет эффекта — лидер всегда отвечает согласованными данными.
- **Troubleshoot ports:** Требует доступа к целевому хосту на TCP. Проверяются только TCP порты, UDP (8301/8302) проверяются отдельно.

## Дополнительная информация

- **[Consul Commands](https://developer.hashicorp.com/consul/commands)** — полный справочник команд.
- **[Consul Operator](https://developer.hashicorp.com/consul/commands/operator)** — операторские команды.
- **[Consul Debug](https://developer.hashicorp.com/consul/commands/debug)** — сбор диагностики.
- **[Consul Keyring](https://developer.hashicorp.com/consul/commands/keyring)** — gossip шифрование.
- **[Consul Snapshot](https://developer.hashicorp.com/consul/commands/snapshot)** — снапшоты.
- **[Consul Troubleshoot](https://developer.hashicorp.com/consul/commands/troubleshoot)** — диагностика сети и Service Mesh.
- **[Consul ACL Reference](./consul_acl.md)** — управление токенами и политиками.
- **[Consul KV Store](./consul_kv_store.md)** — операции с ключами.
- **[Consul Service Catalog](./consul_service_catalog.md)** — каталог сервисов.
- **[Consul Consensus](./consul_consensus.md)** — Raft-консенсус, кворум.
- **[Consul Disaster Recovery](./consul-disaster-recovery.md)** — восстановление после сбоев.
- **[Consul Backup Verification](./consul_backup_verification.md)** — проверка снапшотов.
