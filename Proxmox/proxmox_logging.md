# Логирование Proxmox VE

**Актуально для:** Proxmox VE 9.2 (Debian 13 trixie; PVE 8 — Debian 12 bookworm)

## Определения

**journald** — системный журнал systemd. На PVE хранит логи сервисов (`pveproxy`, `pvedaemon`, `pve-ha-crm`, `corosync` и др.), строк запуска/остановки задач и ядра. В GUI вкладка «Syslog» узла читает именно журнал, а не `/var/log/syslog`.

**Task log (лог задачи)** — полный вывод операции PVE (запуск VM, бэкап, миграция), хранимый отдельным файлом под `/var/log/pve/tasks/` и адресуемый идентификатором **UPID**.

**UPID** — уникальный идентификатор задачи PVE, кодирует узел, PID, время запуска, тип операции, VMID и пользователя: `UPID:pve1:0003A2F1:01C7E4B2:66F5A1C0:vzdump:101:root@pam:`.

**pveproxy access.log** — журнал HTTP-доступа к веб-интерфейсу и API (формат, близкий к Apache), путь жёстко зашит в `pveproxy`: `/var/log/pveproxy/access.log`. Не пишется в journald.

**syslog** — протокол пересылки логов (RFC 5424/3164). На PVE пересылку реализует `rsyslog`; теория и механика — в [rsyslog](../Linux/SystemAdministration/Logging/rsyslog.md).

**Loki** — агрегация логов от Grafana Labs: индексирует метаданные (labels), не полный текст; дешевле ELK по хранению. Обзор — [Loki](../Loki/loki_overview.md).

**Fluent Bit** — лёгкий агент сбора и пересылки логов (journald, файлы → Loki, Elasticsearch, S3). Механика — [Fluent Bit](../Linux/SystemAdministration/Logging/fluent_bit.md).

**LogQL** — язык запросов Loki (логические фильтры `|=`, `|~`, преобразования `| json`, метрические функции `count_over_time`).

## Источники логов в Proxmox VE

Логирование на PVE распределено: сервисы пишут в журнал, операции — в отдельные файлы. Понимание этой распределённости — основа диагностики.

| Что | Где хранится | Как читать |
| :--- | :--- | :--- |
| Сервисы: `pveproxy`, `pvedaemon`, `pvestatd`, `pvescheduler`, `pve-firewall`, `pve-ha-crm`, `pve-ha-lrm`, `spiceproxy`, `qmeventd` | journald | `journalctl -u pveproxy`, `-u pvedaemon`, … |
| Строка запуска/завершения каждой задачи, результат `vzdump` (одна строка) | journald | `journalctl -t pveproxy -t task-updates` |
| Полный вывод задачи (бэкап, миграция, start/stop, снапшот) | `/var/log/pve/tasks/` | `pvenode task log <UPID>` |
| Индекс завершённых задач | `/var/log/pve/tasks/index`, `active` | `pvenode task list` |
| stdout/stderr монитора QEMU гостя | `/var/log/qemu-server/<VMID>.log` | `less`, `tail -f` |
| Лог контейнера LXC | `/var/log/lxc/<CTID>.log` | `less`, `tail -f` |
| Последний запуск `vzdump` гостя | `/var/log/vzdump/qemu-<VMID>.log`, `lxc-<CTID>.log` | `less` |
| HTTP-доступ к GUI/API (и SPICE) | `/var/log/pveproxy/access.log` | `less`, `tail -f` |
| Пакетный лог firewall PVE (по умолчанию выключен) | `/var/log/pve-firewall.log` | `tail -f` |
| Corosync, pve-cluster | journald | `journalctl -u corosync -u pve-cluster` |
| Ceph (если используется) | `/var/log/ceph/` | `less` |
| PBS (если установлен на узел) | `/var/log/proxmox-backup/` | `less` |
| Ядро, ZFS events | journald | `journalctl -k` |
| Аутентификация API (`authentication failure`, `successful auth`) | journald (`pvedaemon`) | `journalctl -u pvedaemon -g 'authentication failure'` |
| SSH, PAM | journald / `auth.log` | `journalctl -u sshd` |

Ключевой принцип: **журнал сообщает, что задача завершилась (в одну строку); файл задачи объясняет, почему**. При разборе сбоя начинают с journal (найти UPID), затем читают полный task log.

Пути к логам `pveproxy` и `/var/log/pve/` зашиты в исходниках `pve-manager` и не переконфигурируются; при нехватке места на разделе `/var` переносите их симлинком на другой том (осторожно: `pveproxy` не стартует, если не может создать `access.log`, владелец файла — `www-data`).

## Система задач PVE (task log и UPID)

Каждая операция из GUI, API или CLI, выполняемая через `pvedaemon`/`pveproxy`, становится задачей с UPID. Это первый источник при post-mortem: именно здесь полный вывод `vzdump`, миграции или `qm start`.

### Формат UPID

```text
UPID:pve1:0003A2F1:01C7E4B2:66F5A1C0:vzdump:101:root@pam:
│     │    │         │         │         │      │    │
│     │    │         │         │         │      │    └ user@realm
│     │    │         │         │         │      └ VMID (для гостевых задач)
│     │    │         │         │         └ тип задачи (vzdump, qmstart, qmigrate…)
│     │    │         │         └ время запуска (hex, Unix time)
│     │    │         └ старт процесса (hex)
│     │    └ PID (hex)
│     └ узел, выполнивший задачу
└ маркер
```

### CLI: поиск и чтение

`pvenode task` работает локально на узле; те же данные доступны через API (`/nodes/<node>/tasks`, кластерно `/cluster/tasks`).

```bash
# Ошибки за последние сутки (UNIX epoch)
SINCE=$(date -d '24 hours ago' +%s)
pvenode task list --errors --since "$SINCE" --limit 50
# → UPID:pve1:0003A2F1:01C7E4B2:66F5A1C0:vzdump:101:root@pam:  66F5A210 ERROR

# Все задачи конкретного гостя
pvenode task list --vmid 101 --typefilter vzdump --limit 20

# Полный вывод задачи
pvenode task log 'UPID:pve1:0003A2F1:01C7E4B2:66F5A1C0:vzdump:101:root@pam:'
# → INFO: starting new backup job: vzdump 101 --storage local-lvm --mode snapshot
# → …
# → ERROR: job failed with err -5 - Input/output error

# Статус (у работающейся задачи — progress)
pvenode task status 'UPID:pve1:0003A2F1:01C7E4B2:66F5A1C0:vzdump:101:root@pam:'
```

Дополнительные фильтры `pvenode task list`: `--userfilter`, `--statusfilter`, `--typefilter`, `--source archive|active|all`, `--until`. Для кластерного поиска «на каком узле это было» используйте `pvesh get /cluster/tasks --errors 1 --since $SINCE`.

### Физическое хранение и ретеншн

- Файлы задач лежат в 16 подкаталогах `0`–`F` (`/var/log/pve/tasks/<N>/`) — по последнему hex-разряду времени старта.
- `active` — сейчас выполняющиеся задачи (перезаписывается, не использовать как журнал).
- `index` — построчный индекс завершённых задач (UPID + время завершения + статус `OK`/`WARN`/`ERR`); при размере ~50 КБ переименовывается в `index.1` и начинается новый.
- Старые task-файлы удаляет ежедневная служебная очистка; на диске остаётся порядка последних тысяч задач. **Task-логи — не архив для compliance**: долгосрочную историю выгружайте в централизованную систему (Fluent Bit + Loki).

### vzdump: лог конкретного бэкапа

`/var/log/vzdump/qemu-<VMID>.log` (или `lxc-<CTID>.log`) перезаписывается при каждом запуске бэкапа гостя — хранит только последний запуск. При бэкапе на directory-хранилище копия лога кладётся рядом с архивом как `vzdump-qemu-<VMID>-<YYYY_MM_DD-HH_MM_SS>.log`. В PBS-сценарии полный вывод остаётся в task log; в сам PBS логи попадают через `/var/log/proxmox-backup/`.

## Архитектура централизованного логирования

```text
Proxmox-ноды (n)            Агрегация                 Хранение и визуализация
┌───────────────────┐      ┌───────────────────┐     ┌───────────────────┐
│ journald           │      │ Fluent Bit (n)    │     │ Loki              │
│ pveproxy access.log│─────>│  - journald       │────>│  - chunks + labels│
│ /var/log/pve/tasks │      │  - files          │     │  - retention      │
│ /var/log/qemu-*,lxc│      │  - buffer on disk │     │                   │
│ auditd (опц.)      │      └───────────────────┘     └─────────┬─────────┘
└───────────────────┘                                          │
                                                        ┌───────▼───────┐
                                                        │ Grafana       │
                                                        │ Explore/Alert │
                                                        └───────────────┘
```

Общая теория централизованного логирования и варианты стеков (ELK, Vector и др.) — в [logging_overview](../Linux/SystemAdministration/Logging/logging_overview.md). Ниже — только PVE-специфика сбора и запросов.

## Практические сценарии

### 1. journald на PVE — базовая настройка

PVE по умолчанию пишет журнал на диск (`/var/log/journal`); при отсутствии каталога журнал эфемерный (`/run/systemd/journal`) и теряется после перезагрузки — создайте каталог и перезапустите `systemd-journald`, если нужны персистентные логи.

```bash
# Активные параметры journald
cat /etc/systemd/journald.conf | grep -v '^#' | grep -v '^$'

# Рекомендуемый профиль для узла с ограниченным /var
cat > /etc/systemd/journald.conf.d/pve.conf << 'EOF'
[Journal]
Storage=persistent
SystemMaxUse=2G
SystemMaxFileSize=256M
MaxRetentionSec=30day
MaxFileSec=1day
RateLimitIntervalSec=30s
RateLimitBurst=10000
# ForwardToSyslog=yes  # только если установлен rsyslog и он нужен
EOF

systemctl restart systemd-journald
journalctl --disk-usage
# → Archived and active journals take up 512.0M in the file system.
```

Теория `Storage`/`SplitMode`/rate limiting — в [journald](../Linux/SystemAdministration/Logging/journald.md).

### 2. Разбор инцидента: упавший бэкап (SRE-сценарий)

```bash
# 1. Найти ошибочные задачи за сутки
pvenode task list --errors --since "$(date -d '24 hours ago' +%s)"

# 2. Почитать полный вывод
pvenode task log 'UPID:pve1:...:vzdump:101:root@pam:'

# 3. Сверить с журналом сервисов за то же время
journalctl -u pvestatd -u pvedaemon --since "2026-10-17 02:00" --until "2026-10-17 03:00"

# 4. Проверить лог самого vzdump-прогона (последняя попытка)
less /var/log/vzdump/qemu-101.log

# 5. Корреляция с централизованными логами (если настроен pipeline)
#    искать UPID в Loki: {job="proxmox"} |= "UPID:pve1:...:vzdump:101:"
```

### 3. Syslog forwarding (rsyslog)

Пересылка на удалённый syslog-сервер; конфигурация `rsyslog` подробно — в [rsyslog](../Linux/SystemAdministration/Logging/rsyslog.md).

```bash
# /etc/rsyslog.d/50-pve-forward.conf
# TCP (@@) — надёжнее UDP; для шифрования используйте omfwd + TLS
# (gtls) — см. rsyslog.md
:programname, isequal, "pveproxy"    @@logserver.internal:514
:programname, isequal, "pvedaemon"   @@logserver.internal:514
:programname, isequal, "corosync"    @@logserver.internal:514
:programname, isequal, "task-updates" @@logserver.internal:514

systemctl restart rsyslog
```

Фильтр по facility/tag надёжнее, чем `*.*` с последующим `stop`: он не отправляет на сервер весь шум узла. Пакет `rsyslog` на свежем PVE может не быть установлен — это нормально, журнал полон; ставьте его только при явной необходимости файловой пересылки.

### 4. Fluent Bit: сбор с PVE → Loki

Установка на Debian (PVE 9 — trixie, PVE 8 — bookworm). Актуальный список дистрибутивов сверяйте на [packages.fluentbit.io](https://packages.fluentbit.io/fluentbit/debian/); если для trixie ещё нет пакета, используйте пакеты bookworm (совместимы) или официальный install script.

```bash
. /etc/os-release
echo "deb [signed-by=/usr/share/keyrings/fluentbit-keyring.gpg] https://packages.fluentbit.io/fluentbit/debian ${VERSION_CODENAME}" > /etc/apt/sources.list.d/fluentbit.list
curl -fsSL https://packages.fluentbit.io/fluentbit.key | gpg --dearmor -o /usr/share/keyrings/fluentbit-keyring.gpg
apt update && apt install -y fluent-bit
```

Конфигурация — PVE-специфичные входы; общие секции pipeline описаны в [fluent_bit](../Linux/SystemAdministration/Logging/fluent_bit.md):

```ini
# /etc/fluent-bit/fluent-bit.conf
[SERVICE]
    Flush         5
    Log_Level     info
    Daemon        off
    Parsers_File  parsers.conf
    HTTP_Server   On
    HTTP_Listen   127.0.0.1
    HTTP_Port     2020
    storage.path  /var/lib/fluent-bit/
    storage.sync  normal
    storage.checksum off

# Журнал: сервисы PVE + ядро
[INPUT]
    Name          systemd
    Tag           pve.*
    Systemd_Filter _SYSTEMD_UNIT=pveproxy.service
    Systemd_Filter _SYSTEMD_UNIT=pvedaemon.service
    Systemd_Filter _SYSTEMD_UNIT=pvestatd.service
    Systemd_Filter _SYSTEMD_UNIT=pvescheduler.service
    Systemd_Filter _SYSTEMD_UNIT=pve-firewall.service
    Systemd_Filter _SYSTEMD_UNIT=pve-ha-crm.service
    Systemd_Filter _SYSTEMD_UNIT=pve-ha-lrm.service
    Systemd_Filter _SYSTEMD_UNIT=pve-cluster.service
    Systemd_Filter _SYSTEMD_UNIT=corosync.service
    Systemd_Filter _SYSTEMD_UNIT=spiceproxy.service
    Read_From_Tail On
    Path_Key      __path__

# HTTP-доступ к API/GUI (жёсткий путь, ротируется logrotate)
[INPUT]
    Name          tail
    Tag           pve.access
    Path          /var/log/pveproxy/access.log
    Parser        pve-access
    DB            /var/lib/fluent-bit/pve-access.db

# Индекс задач (не-JSON: берём строку как есть)
[INPUT]
    Name          tail
    Tag           pve.tasks
    Path          /var/log/pve/tasks/index
    DB            /var/lib/fluent-bit/pve-tasks.db
    Parser        none
    Path_Key      __path__

# Логи гостей
[INPUT]
    Name          tail
    Tag           pve.qemu
    Path          /var/log/qemu-server/*.log
    Parser        ltrim
    DB            /var/lib/fluent-bit/pve-qemu.db

[INPUT]
    Name          tail
    Tag           pve.lxc
    Path          /var/log/lxc/*.log
    Parser        ltrim
    DB            /var/lib/fluent-bit/pve-lxc.db

[OUTPUT]
    Name          loki
    Match         pve.*
    Labels        job=proxmox
    Label_Keys    $node,__path__
    Remove_Keys   node,__path__
    Line_Format   json
    Url           http://loki.internal:3100/loki/api/v1/push
    storage.total_limit_size 512M

[OUTPUT]
    Name          stdout
    Match         *
    Limit         5
```

Парсеры (`/etc/fluent-bit/parsers.conf` или дополнение к `parsers.conf`):

```ini
# Формат access.log PVE: без referer/UA, дата с числовым днём
# 192.168.1.5 - root@pam [28/09/2026:09:14:02 +0000] "GET /api2/json/... HTTP/1.1" 200 1894
[PARSER]
    Name        pve-access
    Format      regex
    Regex       ^(?<client>\S+) \S+ (?<user>\S+) \[(?<time>[^\]]+)\] "(?<method>\S+) (?<uri>\S+) (?<proto>[^"]+)" (?<status>\d+) (?<bytes>\d+)
    Time_Key    time
    Time_Format %d/%b/%Y:%H:%M:%S %z

[PARSER]
    Name        ltrim
    Format      regex
    Regex       ^(?<time>\S+\s+\S+)\s+(?<msg>.*)$
```

```bash
# Проверка конфигурации и запуск
fluent-bit -c /etc/fluent-bit/fluent-bit.conf -T
systemctl enable --now fluent-bit
```

**Важно про LXC:** контейнер ведёт собственный журнал *внутри гостя*; хост его не собирает. На хосте виден только `/var/log/lxc/<CTID>.log` (stdout контейнерного стека), не журнал сервисов гостя. Для сервисов внутри LXC либо ставьте агент в гость, либо настройте приложение писать наружу (syslog/HTTP).

### 5. Loki: размещение и ретеншн

Установка и полный конфиг Loki — в [Loki](../Loki/loki_overview.md); ниже — минимальный single-binary конфиг с ретеншном, релевантный выделенному лог-серверу (не на PVE-ноду).

```yaml
# /etc/loki/config.yml (существенные параметры)
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /var/lib/loki
  storage:
    filesystem:
      chunks_directory: /var/lib/loki/chunks
      rules_directory: /var/lib/loki/rules
  replication_factor: 1
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  retention_period: 720h   # 30 дней

compactor:
  working_directory: /var/lib/loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  delete_request_store: filesystem
```

Актуальную версию бинарника берите с [releases Grafana Loki](https://github.com/grafana/loki/releases) (на момент написания — ветка 3.x; схема `tsdb` + `v13` поддерживается). Доступность: `curl -s http://loki.internal:3100/ready` → `ready`.

### 6. Grafana: подключение Loki и LogQL

Datasource: GUI Grafana → Connections → Data Sources → Loki → URL `http://loki.internal:3100`. Через provisioning:

```yaml
# /etc/grafana/provisioning/datasources/loki.yml
apiVersion: 1
datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki.internal:3100
    editable: true
```

Примеры LogQL, адаптированные под метки pipeline из раздела 4 (`job=proxmox`, `__path__` содержит исходный файл):

```logql
# Всё о PVE с выбранной ноды (имя узла — в __path__ / message)
{job="proxmox"} |= "pve1"

# Ошибки сервисов
{job="proxmox"} |= "error"

# Неудачная аутентификация API
{job="proxmox"} |= "authentication failure"

# Задачи конкретного гостя по UPID/VMID
{job="proxmox", __path__=~".*tasks.*"} |= "vzdump:101:"

# HTTP 5xx к API
{job="proxmox", __path__=~".*pveproxy.*"} | regexp `"(?<method>\S+) (?<uri>\S+)[^"]*" (?<status>\d+)` | status >= 500

# Активность root@pam в access.log
{job="proxmox", __path__=~".*pveproxy.*"} |= "root@pam"

# QEMU-лог гостя 101
{job="proxmox", __path__=~".*qemu-server/101.log"}

# Счётчик ошибок по узлам за час (метрический запрос LogQL)
sum by (__path__) (count_over_time({job="proxmox"} |= "error" [1h]))
```

Не создавайте label из `vmid`, `user` или `uri` — каждый уникальный комбинар размножает streams (cardinality explosion); фильтруйте через `|=` / `| json` в теле запроса.

### 7. Алертинг на логи (Loki ruler / Grafana)

**Prometheus не умеет выполнять запросы к логам** — синтаксис `|= "error"` принадлежит LogQL, а не PromQL. Алерты на логи настраиваются двумя путями:

1. **Loki Ruler** — правила в LogQL metric-формате, отдающие алерты в Alertmanager (тот же Alertmanager, что для Prometheus).
2. **Grafana Alerting** — правило с datasource = Loki, удобно для UI-ориентированных команд.

Пример правил Loki ruler (`/etc/loki/rules/proxmox.yml`):

```yaml
groups:
  - name: proxmox-logs
    rules:
      - alert: ProxmoxHighErrorRate
        expr: sum by (__path__) (count_over_time({job="proxmox"} |= "error" [5m])) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error log rate ({{ $labels.__path__ }})"
          description: "More than 0.1 error lines/sec for 5 minutes"

      - alert: ProxmoxAuthFailures
        expr: sum(count_over_time({job="proxmox"} |= "authentication failure" [5m])) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "API authentication failures spike"
```

Метрики *состояния* PVE (кворум, диски, HA) алертить логами не нужно — для них есть Prometheus exporter; см. [Мониторинг Proxmox](./proxmox_monitoring.md). Лог-алерты дополняют метрики, не заменяют их. Подробнее — [Loki Alerting](../Loki/loki_alerting_guide.md).

### 8. Аудит и расследования

Правила `auditd` для `/etc/pve`, `pveproxy`, SSH-ключей — в [Безопасность Proxmox](./proxmox_security.md) (раздел Auditd). Здесь — типовой поиск:

```bash
# Изменения конфигурации кластера (ключ proxmox_config из security.md)
ausearch -k proxmox_config --interpret
ausearch -k ssh_keys --interpret
ausearch -ts recent -k pve_api_logs

aureport --summary

# Кто и когда запускал задачи (по журналу)
journalctl -t task-updates --since "7 days ago" | grep -E 'UPID.*(vzdump|qmigrate)'

# Брутфорс API по журналу
journalctl -u pvedaemon -g 'authentication failure' --since "1 day ago"

# HTTP-аудит по access.log
awk '$6 == 401 || $6 == 403' /var/log/pveproxy/access.log | tail -50
```

Расследование «кто удалил VM»: `pvenode task list --typefilter qmdestroy --since …` → UPID (в нём user) → полный лог → корреляция в Loki по UPID.

## Диагностика и устранение неполадок

### journald не записывает логи

```bash
cat /etc/systemd/journald.conf /etc/systemd/journald.conf.d/*.conf 2>/dev/null | grep -v '^#' | grep -v '^$'
journalctl --disk-usage
ls -la /var/log/journal/          # каталога нет → журнал эфемерный
systemctl status systemd-journald
journalctl -p err -b              # ошибки за текущую загрузку
systemctl restart systemd-journald
```

Причина «после перезагрузки пусто»: `Storage=auto` + отсутствие `/var/log/journal`. Решение: создать каталог, выставить `Storage=persistent`, перезапустить сервис.

### Fluent Bit не отправляет логи

```bash
systemctl status fluent-bit
journalctl -u fluent-bit --since "5 minutes ago"
fluent-bit -c /etc/fluent-bit/fluent-bit.conf -T   # dry-run конфигурации
curl -s http://127.0.0.1:2020/api/v1/metrics       # внутренние метрики агента
curl -s http://loki.internal:3100/ready            # доступность Loki
ls -la /var/lib/fluent-bit/                        # state-файлы tail-входов
```

### Loki не принимает или не отдаёт логи

```bash
curl -s http://localhost:3100/ready
journalctl -u loki --since "5 minutes ago"
df -h /var/lib/loki
# Проверка, что данные вообще приходят: LogQL за последние 5 минут
# {job="proxmox"} [5m]
```

### pveproxy не стартует: нет access.log

```bash
ls -la /var/log/pveproxy/
# access.log должен существовать и принадлежать www-data:www-data
# Порт по умолчанию занят или каталог не создан — pveproxy падает на старте
journalctl -u pveproxy -e
```

Не удаляйте `/var/log/pveproxy/` и не монтируйте tmpfs безuid=33,gid=33 — иначе GUI/API недоступны (симптом обсуждается в [форуме Proxmox](https://forum.proxmox.com/threads/pve-logging.144215/)).

## Лучшие практики

1. **Сначала журнал, потом агенты.** Настройте персистентный journald и охватите все `pve*`-юниты — это закрывает 80% диагностики без единого дополнительного демона. Централизацию добавляйте после.
2. **Task log — первый источник при разборе сбоев.** Не ищите «почему упал бэкап» в syslog: journal даёт только UPID и одну строку результата.
3. **Не полагайтесь на локальный ретеншн task-логов.** Ежедневная очистка оставляет тысячи задач, не десятки тысяч; для аудита и пост-фактум расследований выгружайте `index` и journal в Loki.
4. **LXC-гость — отдельный журнал.** Хост не собирает systemd-журнал контейнера; учитывайте это в design централизованного логирования.
5. **Ретеншн-пирог:** journal (7–30 дней локально) → Loki (30–90 дней) → холодное хранилище/S3-слой при compliance; task-логи и `vzdump`-файлы не заменяют эти уровни.
6. **Метки Loki — дёшево и немного.** `job`, узел, сервис. VMID/user/URI — через фильтры запроса, не через labels.
7. **Синхронизация времени.** Корреляция journal ↔ access.log ↔ task-логов между нодами требует chrony на всех узлах (см. [Кластер Proxmox](./proxmox_cluster.md)).
8. **Пересылка по TCP/TLS.** UDP теряет пакеты под нагрузкой; шифрование каналов пересылки обязательно для нелокальных сетей (пример TLS — в [rsyslog](../Linux/SystemAdministration/Logging/rsyslog.md), [fluent_bit](../Linux/SystemAdministration/Logging/fluent_bit.md)).
9. **Конфиденциальность.** Task-логи и access.log содержат токены в URL, данные гостевых ОС, имена пользователей; доступ к Loki/API логов — по ролям, маскирование PII — в [pii_masking](../Linux/SystemAdministration/Logging/pii_masking.md).
10. **Проверяйте pipeline.** Планово генерируйте тестовую ошибку и убеждайтесь, что она дошла до Loki и подхватилась алертом; сломанный пайплайн обнаруживается в момент инцидента, иначе — никогда.
11. **Собственник и документ.** Зафиксируйте: кто владеет лог-сервером, сколько хранится, какие легенды меток. Карта источников этого файла — готовая основа.

## Граничные случаи

- **Cardinality explosion в Loki.** Label на каждый `vmid`/`user`/`uri` создаёт миллионы streams и убивает индекс; только `|=`/`| json` в запросе.
- **`index` задач не для машинного парсинга как JSON.** Формат «UPID + hex-time + статус», не JSON; tail-агент должен читать его как сырой текст.
- **Эфемерный журнал.** Без `/var/log/journal` все «холодные» инциденты после reboot недоказуемы.
- **`access.log` растёт быстро** на оживлённых API; локально его режет logrotate PVE (rotate 7, daily, create 640 www-data www-data) — глубже недели данных на узле не будет, выгружайте в Loki.
- **tmpfs вместо `/var/log`** экономит SSD, но при переполнении RAM логи и `pveproxy` ломаются; применяйте только с жёстким ротационным бюджетом и мониторингом.
- **Fluent Bit и права.** Агент должен читать `/var/log/pveproxy/access.log` (640 www-data) — запускайте от root или добавьте в группу www-data; state-базы tail-входов — на постоянный диск.
- **Компрессия Loki.** Сниппеты пишутся snappy-компрессией; реальная степень зависит от энтропии логов — планируйте диск по худшему сценарию, не по маркетинговым ratios.
- **Syslog: TCP vs UDP.** UDP проще, но теряет пакеты при переполнении очереди приемника; для критичных логов — TCP или RELP.
- **Старые PVE без rsyslog.** Отсутствие `/var/log/syslog` не означает потерю данных — истина в journal.

## Дополнительная информация

### Связанные темы

- [Мониторинг Proxmox через Prometheus и Grafana](./proxmox_monitoring.md)
- [Безопасность Proxmox](./proxmox_security.md) — auditd, fail2ban
- [Кластер Proxmox](./proxmox_cluster.md) — корреляция с corosync/HA
- [Обзор логирования (Linux)](../Linux/SystemAdministration/Logging/logging_overview.md)
- [journald](../Linux/SystemAdministration/Logging/journald.md)
- [rsyslog](../Linux/SystemAdministration/Logging/rsyslog.md)
- [Fluent Bit](../Linux/SystemAdministration/Logging/fluent_bit.md)
- [logrotate](../Linux/SystemAdministration/Logging/logrotate.md)
- [Structured Logging](../Linux/SystemAdministration/Logging/structured_logging.md)
- [auditd](../Linux/SystemAdministration/Logging/auditd.md)
- [Обзор Grafana Loki](../Loki/loki_overview.md)
- [Loki Alerting](../Loki/loki_alerting_guide.md)
- [Обзор ELK Stack](../ELK_Stack/elk_stack_overview.md)
