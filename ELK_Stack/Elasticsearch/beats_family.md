# Beats Family: Metricbeat, Heartbeat, Auditbeat, Packetbeat, Winlogbeat

**Актуально для:** Beats 9.5.x (текущий минор 9.5.5, октябрь 2026) / 8.19 LTS (8.19.23)

> Обзор семейства Beats помимо Filebeat. Рассматриваются Metricbeat, Heartbeat, Auditbeat, Packetbeat, Winlogbeat и их использование в production.
>
> Связанные темы: Filebeat — [Filebeat Overview](../filebeat_overview.md); Elastic Agent — [Elastic Agent and Fleet](./elastic_agent_and_fleet.md); Stack Monitoring — [Stack Monitoring](./elasticsearch_stack_monitoring.md).

## Определения

* **Beats** — легковесные агенты сбора данных (shippers) для Elasticsearch. Каждый Beat специализируется на типе данных.
* **Metricbeat** — сбор метрик систем и сервисов (CPU, memory, disk, HTTP, databases).
* **Heartbeat** — мониторинг доступности сервисов (HTTP, TCP, ICMP).
* **Auditbeat** — сбор данных аудита (системные события, целостность файлов).
* **Packetbeat** — анализ сетевого трафика (HTTP, DNS, MySQL, etc.).
* **Winlogbeat** — сбор событий Windows Event Log (Application, Security, System).
* **Module** — предконфигурированный набор inputs и dashboards для конкретного сервиса.
* **Metricset** — набор метрик внутри модуля.

## Обзор Beats

| Beat | Тип данных | Использование | Замена в Elastic Agent |
|------|-----------|---------------|----------------------|
| Filebeat | Логи | Сбор и парсинг логов | Filestream input |
| Metricbeat | Метрики | Системные и сервисные метрики | Metricsets (input `system/metrics`) |
| Heartbeat | Uptime | Мониторинг доступности | Elastic Synthetics |
| Auditbeat | Аудит | Системный аудит, FIM | System Audit integration |
| Packetbeat | Сеть | Анализ сетевого трафика | Network Packet Capture integration |
| Winlogbeat | Windows events | События Windows Event Log | Custom Windows Event Logs (`winlog`) / Windows integration |
| Functionbeat | Serverless | Сбор из cloud functions | Не поддерживается |

## Требования и привилегии

Beats — статически скомпилированные бинарники (Go), Java не требуется. Поддерживаемые платформы: Linux (x86_64, arm64), Windows (x86_64), macOS (x86_64, arm64) — актуальная матрица в Elastic Support Matrix. На POSIX-системах конфиг проверяется на владельца и права: владелец — root или пользователь, запускающий beat; запись только владельцу (при пакетной установке: root:root 0644). Отключение проверок: `--strict.perms=false` (не рекомендуется). Типичные ошибки: `config file ("metricbeat.yml") must be owned by the beat user (uid=501) or root` и `config file can only be writable by the owner`.

| Beat | Требования |
|------|-----------|
| Metricbeat | Чтение `/proc`, `/sys`; `docker.sock` для docker-модуля; доступ к API Kubernetes для kubernetes-модуля |
| Heartbeat | Root для `icmp`-мониторов; CA-сертификат для HTTPS-проверок |
| Auditbeat | `file_integrity` — чтение контролируемых путей (`fsnotify`); `CAP_SYS_ADMIN` для `kprobes`/`ebpf`; `auditd` — `CAP_AUDIT_READ` (multicast) или `CAP_AUDIT_CONTROL` (unicast) |
| Packetbeat | Root или `CAP_NET_RAW` (pcap/af_packet); `CAP_NET_ADMIN` для promiscuous mode; mirror-порт при развёртывании на трафике всей сети |
| Winlogbeat | Windows; чтение нужных event log channels |

## Metricbeat

### Установка

```bash
# Debian/Ubuntu — ключ в keyring (apt-key deprecated)
curl -fsSL https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo gpg --dearmor -o /usr/share/keyrings/elasticsearch-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/elasticsearch-keyring.gpg] https://artifacts.elastic.co/packages/9.x/apt stable main" | sudo tee /etc/apt/sources.list.d/elastic-9.x.list
sudo apt update && sudo apt install metricbeat

metricbeat --version
# → metricbeat version 9.5.5 (amd64), libbeat 9.5.5

# Или через Docker
docker pull docker.elastic.co/beats/metricbeat:9.5.5
```

### Конфигурация

```yaml
# metricbeat.yml
metricbeat.config.modules:
  path: ${path.config}/modules.d/*.yml
  reload.enabled: false

output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  username: "metricbeat"
  password: "${ES_METRICBEAT_PASSWORD}"
  # Альтернатива паролю: api_key: "id:api_key"
  # preset: balanced   # performance preset: balanced/throughput/scale/latency (default: custom)

setup.kibana:
  host: "https://kibana:5601"

setup.dashboards.enabled: true
```

### Модули

```bash
# Список доступных модулей
metricbeat modules list

# Включение модуля
metricbeat modules enable system
metricbeat modules enable nginx
metricbeat modules enable mysql
metricbeat modules enable docker
metricbeat modules enable kubernetes

# Отключение модуля
metricbeat modules disable docker

# Тестовый запуск модуля/metricset: применяет настройки, получает метрики, выводит их
metricbeat test modules system cpu
metricbeat test modules nginx
```

### System Module

```yaml
# modules.d/system.yml
- module: system
  period: 10s
  metricsets:
    - cpu
    - load
    - memory
    - network
    - process
    - process_summary
    - socket_summary
    - uptime
    - diskio
    - filesystem
    - fsstat
  processors:
    - add_host_metadata: ~
```

Дефолтные metricsets: `cpu, load, memory, network, process, process_summary, socket_summary, filesystem, fsstat, uptime`. Полный список также включает `core`, `entropy`, `raid`, `service`, `socket`, `users`, `network_summary` и `ntp` (beta с 9.2). `users` (beta) — сессии через dbus/logind, только Linux. Большинство metricsets не требуют elevated permissions; `process`, `socket` и `service` — доступа к чужим процессам/сокетам (запуск от root или с нужными правами). AppArmor/LSM может блокировать `ptrace_may_access()` для `process` даже без прямого использования ptrace.

Полезные опции system-модуля:

```yaml
- module: system
  period: 10s
  metricsets: [cpu, load, memory, network, process, process_summary, socket_summary]
  cpu.metrics: ["percentages", "normalized_percentages"]  # также ticks
  # core.metrics: ["percentages"]
  # use_performance_counters: false  # Windows: производительность на машинах >64 ядер
  process.include_top_n:              # топ-N процессов в process_summary
    by_cpu: 5
    by_memory: 5
  # process.include_cpu_ticks: false  # сырые CPU tick-значения (default: только проценты)
  # process.cgroups.enabled: true     # метрики cgroup для процессов (Linux, default: true)
  # process.env.whitelist: ['^PATH$', '^SSH_.*']  # whitelist переменных окружения
  degrade_on_partial: false  # помечать metricset как degraded при частичных метриках
  hostfs: "/hostfs"          # mount point хостовой ФС при мониторинге из контейнера
```

Шипаемый `modules.d/system.yml` в 9.x использует три блока с разными периодами: `10s` (cpu/load/memory/network/process/process_summary/socket_summary), `1m` (filesystem/fsstat — с `drop_event` для виртуальных ФС `^/(sys|cgroup|proc|dev|etc|host|lib|snap)($|/)`), `15m` (uptime).

### Docker Module

```yaml
# modules.d/docker.yml
- module: docker
  metricsets:
    - container
    - cpu
    - diskio
    - healthcheck
    - info
    - memory
    - network
  hosts: ["unix:///var/run/docker.sock"]
  period: 10s
```

### Kubernetes Module

```yaml
# modules.d/kubernetes.yml
- module: kubernetes
  metricsets:
    - node
    - system
    - pod
    - container
    - volume
  period: 10s
  host: ${NODE_NAME}
  hosts: ["https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}"]
```

### HTTP Module

```yaml
# modules.d/http.yml
- module: http
  metricsets:
    - json
  period: 10s
  hosts: ["http://localhost:8080"]
  namespace: "json_namespace"
  path: "/"
  body: ""
  method: "GET"
```

### Процессоры

```yaml
processors:
  - add_host_metadata:
      netinfo.enabled: true
  - add_cloud_metadata: ~
  - add_docker_metadata: ~
  - add_kubernetes_metadata:
      host: ${NODE_NAME}
      include_annotations: ["annotation1"]
  - drop_fields:
      fields: ["host.name", "agent.version"]
  - rename:
      fields:
        - from: "system.cpu.total.pct"
          to: "cpu.usage"
```

## Heartbeat

### Установка

```bash
sudo apt install heartbeat-elastic
# пакет называется heartbeat-elastic, чтобы не конфликтовать с пакетом heartbeat из Debian/Ubuntu
```

### Конфигурация

```yaml
# heartbeat.yml
heartbeat.monitors:
  - type: http
    id: my-website
    name: My Website
    urls: ["https://my-website.com"]
    schedule: '@every 30s'
    timeout: 10s
    check.response:
      status: 200
      body:
        - positive: "Welcome"
    ssl:
      certificate_authorities: ["/path/to/ca.crt"]

  - type: tcp
    id: my-database
    name: PostgreSQL
    hosts: ["my-db-host"]
    ports: [5432]
    schedule: '@every 60s'

  - type: icmp
    id: my-server
    name: Server Ping
    hosts: ["10.0.0.1"]
    schedule: '@every 10s'

# Внешние файлы мониторов с горячей перезагрузкой (альтернатива inline-описанию)
heartbeat.config.monitors:
  path: ${path.config}/monitors.d/*.yml
  reload.enabled: true
  reload.period: 1s

# Лимит одновременно выполняемых задач (0 — без лимита)
heartbeat.scheduler:
  limit: 10

output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  username: "heartbeat"
  password: "${ES_HEARTBEAT_PASSWORD}"
```

### Типы мониторов

| Тип | Описание | Использование |
|-----|----------|---------------|
| `http` | HTTP/HTTPS запрос | Веб-сайты, API |
| `tcp` | TCP соединение | Базы данных, сервисы |
| `icmp` | ICMP ping | Доступность хостов (требует root) |
| `browser` | Synthetics в реальном браузере | Удалён после 8.4 — для browser-проверок используйте Synthetics в Kibana |

### Общие опции мониторов

| Опция | Описание |
|-------|----------|
| `type` | Тип монитора (http/tcp/icmp) |
| `id` | Уникальный идентификатор. **Задавайте явно**: без `id` он хешируется из конфига и меняется при любой правке — агрегации по времени становятся невозможны. Для мониторинга одного endpoint из нескольких локаций используйте одинаковые `id` (различайте локации через `host.geo.name`) |
| `name` | Человеко-читаемое имя (`monitor.name`) |
| `service.name` | Имя APM-сервиса — интеграция Uptime и APM в Kibana |
| `enabled` | default true |
| `schedule` | cron-подобное выражение (реализация cronexpr) + расширение `@every`. Примеры: `@every 30s` — каждые 30 секунд от старта Heartbeat; `* */5 * * * * * *` — каждые 5 секунд по расписанию (7 полей с секундами); `0 9-17 * * 1-5` — будни 9:00–17:00 |
| `maintenance_windows` | Периоды паузы монитора (реализовано через rrule) |

`heartbeat.run_once: true` (experimental) — выполнить мониторы ровно один раз при старте (полезно в CI). `tcp` и `http` мониторы поддерживают SSL/TLS и настройки proxy.

### HTTP Monitor с детальной проверкой

```yaml
heartbeat.monitors:
  - type: http
    id: api-health
    name: API Health Check
    urls: ["https://api.company.com/health"]
    schedule: '@every 30s'
    timeout: 10s
    check.request:
      method: GET
      headers:
        Authorization: "Bearer ${API_TOKEN}"
    check.response:
      status: 200
      json:
        - description: "Status is healthy"
          expression: 'status == "healthy"'
      headers:
        content-type: "application/json"
```

`condition:` в `check.response.json` deprecated — используйте `expression` (язык выражений, например `expression: 'status == "healthy"'`; выражения поддерживают jsonpath-синтаксис). `check.response.headers` — словарь обязательных заголовков ответа (имя → значение), а не список условий. `check.request.method` поддерживает `HEAD`, `GET`, `POST`, `PUT`, `DELETE`, `CONNECT`, `TRACE` и `OPTIONS`.

Семантика проверок:
* `check.response.status` — **список** ожидаемых кодов (`status: [200, 201]`). Коды 4xx и 5xx по умолчанию считаются down, остальные — up.
* `check.response.body` — список регулярных выражений; достаточно совпадения **одного**. Поддерживает ключи `positive:` (аналог plain-списка) и `negative:` — инвертированная проверка: совпадение считается падением («match failed if single expression matches»). Тело ответа поддерживается до 100 MiB.
* `check.request.body` — тело запроса (для `POST`), например `body: "name=first&email=someemail%40example.com"` с заголовком `Content-Type: application/x-www-form-urlencoded`.
* `response.include_body` — индексировать ли тело ответа в поле `http.response.body.contents`: при ошибке проверки (default) / `never` / `always`.

Регулярные выражения Heartbeat основаны на **RE2** — оборачивайте паттерны в одинарные кавычки (`'^[?[0-9][0-9]:?[0-9][0-9]'`), чтобы обойти экранирование в YAML.

## Auditbeat

### Установка

```bash
sudo apt install auditbeat
```

### Конфигурация

```yaml
# auditbeat.yml
auditbeat.modules:
  - module: auditd
    # multicast (default) — сосуществует с системным auditd;
    # unicast — Auditbeat сам управляет правилами (остановите системный auditd)
    audit_rules: |
      # Изменения идентификации
      -w /etc/passwd -p wa -k identity
      -w /etc/group -p wa -k identity
      -w /etc/shadow -p wa -k identity
      # Неудачные попытки доступа к файлам
      -a always,exit -F arch=b64 -S open,creat,truncate,ftruncate,openat -F exit=-EACCES -F auid>=1000 -F auid!=4294967295 -F key=access
      # Запуск процессов
      -a always,exit -F arch=b64 -S execve,execveat -F key=exec

  - module: file_integrity
    paths:
      - /bin
      - /usr/bin
      - /etc
    backend: fsnotify
    exclude_files:
      - '(?i)\.sw[nop]$'
      - '~$'
    scan_at_start: true
    scan_rate_per_sec: 50 MB
    max_file_size: 100 MB
    hash_types: [sha256]
    recursive: true

  - module: system
    datasets:
      - host
      - login
      - package
      - process
      - socket
      - user
    state.period: 12h
    user.detect_password_changes: true

output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  username: "auditbeat"
  password: "${ES_AUDITBEAT_PASSWORD}"
```

### File Integrity Monitoring (FIM)

```yaml
- module: file_integrity
  paths:
    - /etc/nginx
    - /etc/ssl
    - /opt/myapp
  scan_at_start: true
  hash_types: [sha256]
```

**Важно:** FIM может генерировать много данных при первом сканировании. Используйте `exclude_files` для временных файлов.

**Backend** (`backend`): Linux — `auto`/`fsnotify` (default, inotify, без дополнительных привилегий), `kprobes` (требует `CAP_SYS_ADMIN`, tracefs), `ebpf` (требует `CAP_SYS_ADMIN` + `CAP_BPF`, ядро 5.10.16+); Windows — `fsnotify` (`ReadDirectoryChangesW`) или `etw` (с 9.2, Administrator). **Не используйте модуль на сетевых файловых системах** (официальное ограничение). Поддерживаемые хеши: `md5`, `sha1`, `sha224/256/384/512`, `blake2b_256/384/512`, `sha3_224/256/384/512`, `xxh64`. Дополнительно: `include_files` (whitelist-регулярки), `file_parsers` (парсинг форматов файлов).

### System Module

> Модуль `system` в Auditbeat находится в статусе **Beta** (по данным документации Elastic).

| Dataset | Описание |
|---------|----------|
| `host` | Информация о хосте |
| `login` | Логины/логауты |
| `package` | Установленные пакеты |
| `process` | Процессы |
| `socket` | Сетевые соединения |
| `user` | Пользователи |

### Auditd Module (Linux Audit Framework)

Модуль `auditd` получает события из Linux Audit Framework (часть ядра). Подписка на события ядра, а не polling — опция `period` не используется.

**Привилегии:**
* `socket_type: multicast` (default) — требуется `CAP_AUDIT_READ`; работает параллельно с системным демоном `auditd`
* `socket_type: unicast` — требуется `CAP_AUDIT_CONTROL` и начальное PID namespace (root на хосте или `--pid=host` в Docker); только один процесс может получать события — остановите системный `auditd` (`service auditd status` / `service auditd stop`)

**Ключевые опции:** `audit_rules` (формат `auditctl`, одна строка на правило; задание правил заменяет все существующие — `-D` не нужен), `audit_rule_files` (файлы правил), `resolve_ids` (резолв UID/GID, default true), `failure_mode` (`silent`/`log`/`panic`), `backlog_limit` (8192), `rate_limit` (0), `backpressure_strategy` (`auto`/`kernel`/`userspace`/`both`/`none`), `immutable` (правила неизменяемы до перезагрузки).

```bash
# Диагностика состояния kernel audit subsystem
auditbeat show auditd-rules   # аналог auditctl -l
auditbeat show auditd-status  # аналог auditctl -s

# Экономия CPU/диска: отключить прослушивание audit-сообщений journald
systemctl mask systemd-journald-audit.socket
```

**Docker:** multicast — `--cap-add=AUDIT_READ`; unicast — `--cap-add=AUDIT_CONTROL --cap-add=AUDIT_READ --pid=host`.

Дополнительные опции модуля `auditd`: `include_raw_message` (false — сырое сообщение ядра в поле `message`), `include_warnings` (false), `keep_null` (публиковать поля с null), `datatype` (`list` — формат публикации правил). Глобальные опции: `auditbeat.config.modules` (внешние файлы модулей: `path: ${path.config}/modules.d/*.yml`, `reload.period: 10s`, `reload.enabled: false` — аналогично `metricbeat.config.modules`), `auditbeat.max_start_delay: 10s` (задержка старта для распределения нагрузки при массовом старте агентов).

## Winlogbeat

Сбор событий Windows Event Log (Application, Security, System и любые custom channels). Устанавливается как Windows service; позиция чтения сохраняется на диске (registry) и восстанавливается после перезапуска.

Список доступных каналов: `Get-WinEvent -ListLog * | Format-List -Property LogName`.

```yaml
# winlogbeat.yml
winlogbeat.event_logs:
  - name: Application
  - name: Security
  - name: System
    ignore_older: 72h
  # Типичная практика — аудит PowerShell и Sysmon:
  - name: Windows PowerShell
    event_id: 400, 403, 600, 800
    ignore_older: 72h
  - name: Microsoft-Windows-PowerShell/Operational
    event_id: 4103, 4104, 4105, 4106
  - name: Microsoft-Windows-Sysmon/Operational
    ignore_older: 24h
  - name: ForwardedEvents
    tags: [forwarded]

output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  username: "winlogbeat"
  password: "${ES_WINLOGBEAT_PASSWORD}"
```

Опции `event_logs`:

| Опция | Описание |
|-------|----------|
| `name` | Имя канала (обязательно, если не задан `query`) |
| `id` | Уникальный идентификатор записи |
| `ignore_older` | Игнорировать события старше указанного времени (ns/us/ms/s/m/h) — полезно при первом запуске на канале с историей |
| `event_id` | Фильтр по ID: список `4624, 4625`, диапазоны `4700-4800`, исключения через `-4735`, `-4701-4710` |
| `level` | Уровни: `critical`(1), `error`(2), `warning`(3), `information`(0 или 4), `verbose`(5); разделитель — запятая |
| `provider` | Список провайдеров (source names) |
| `language` | ID языка рендеринга (например `0x0409` — en-US); default 0 — язык системы |
| `query` | Произвольный XML-запрос; взаимоисключающий с `name`/`event_id`/`ignore_older`/`level`/`provider`, требует `id` |
| `ignore_missing_channel` | Не падать при отсутствии канала (полезно при развёртывании на разнородных хостах) |
| `forwarded` | Пометить события как forwarded |
| `processors`, `tags`, `index` | Процессоры, теги и переопределение индекса для этого канала |

Фильтрация событий на стороне агента — через процессоры, например:

```yaml
processors:
  - drop_event:
      when:
        and:
          - equals:
              winlog.event_id: 4672
          - equals:
              winlog.event_data.SubjectUserName: 'LOCAL SERVICE'
```

Замена в Elastic Agent: интеграции **Custom Windows Event Logs** (`winlog`) и **Windows**.

## Packetbeat

### Установка

```bash
sudo apt install packetbeat
```

### Конфигурация

```yaml
# packetbeat.yml
packetbeat.interfaces.device: any
# Альтернативы: default_route, default_route_ipv4, default_route_ipv6 — интерфейс с маршрутом по умолчанию
# ВНИМАНИЕ: device: any не работает на macOS
# Более быстрый sniffer на Linux (вместо pcap): packetbeat.interfaces.type: af_packet
# packetbeat.interfaces.snaplen: 65535       # макс. размер пакета (default)
# packetbeat.interfaces.buffer_size_mb: 30   # shared memory kernel↔userspace (только af_packet)
# packetbeat.interfaces.metrics_interval: 5s # период метрик интерфейса (только af_packet)
# packetbeat.interfaces.fanout_group: ~    # 0-65535, Linux/af_packet: kernel распределяет пакеты
                                           # между инстансами Packetbeat по flow hash
# packetbeat.interfaces.with_vlans: true   # автоматический BPF-фильтр с VLAN-тегами
# packetbeat.interfaces.bpf_filter: ...    # переопределить автоматически сгенерированный BPF-фильтр
# packetbeat.interfaces.internal_networks: [private]  # CIDR «внутренних» сетей для классификации perimeter
# packetbeat.interfaces.auto_promisc_mode: true  # не работает с device: any

# Обогащение событий процессом-источником (Linux/Windows, default: false)
packetbeat.procs.enabled: true
# Не индексировать исходящий трафик самого хоста (при нескольких shipper'ах)
packetbeat.ignore_outgoing: false

packetbeat.flows:
  enabled: true
  timeout: 30s
  period: 10s        # -1s — отправлять только завершённые (killed) flows
  # keep_null: false
  # index: my-custom-flow-index
  # allow_mismatched_eth: false  # конструировать flow по L7-деталям при разных src/dst на обратном маршруте

packetbeat.overwrite_pipelines: false  # перезаписывать ingest pipelines при каждом подключении к ES

packetbeat.protocols:
  - type: http
    ports: [80, 8080, 8000, 5000, 8002]
    send_headers: ["User-Agent", "Cookie"]
    send_all_headers: false
    redact_authorization: true                     # маскировать Authorization/Proxy-Authorization
    # redact_headers: ["X-API-Key"]                # обнулить значение указанных заголовков
    hide_keywords: ['pass', 'password', 'passwd']  # маскировать чувствительные параметры URL/форм
    include_body_for: ["text/html"]
    # include_request_body_for: ["application/json"]
    # include_response_body_for: ["application/json"]
    # decode_body: true            # распаковывать gzip/deflate при экспорте body
    # split_cookie: false          # разбивать Cookie/Set-Cookie на отдельные значения
    # real_ip_header: "X-Forwarded-For"  # → network.forwarded_ip (geo за reverse proxy)
    send_request: false            # сырое сообщение запроса (поле request)
    send_response: false           # сырое сообщение ответа (поле response)
    transaction_timeout: 10s
    max_message_size: 10MB         # default 10485760 байт; больше — обрезается
    # index: my-custom-http-index  # переопределить индекс для этого протокола

  - type: dns
    ports: [53]

  - type: mysql
    ports: [3306, 3307]

  - type: pgsql
    ports: [5432]

  - type: redis
    ports: [6379]

  - type: tls
    ports: [443, 993, 995, 5223, 8443, 8883, 9243]
    # fingerprints: [sha256]         # sha1/sha256/md5 — алгоритмы fingerprint сертификатов
    # send_certificates: true        # отправлять сертификаты и цепочки (default: true)
    # include_raw_certificates: false  # сырые сертификаты в PEM под ключом raw
```

### Поддерживаемые протоколы

| Протокол | Порт | Информация |
|----------|------|------------|
| HTTP | 80, 8080, etc. | Запросы/ответы, latency |
| DNS | 53 | Запросы DNS |
| MySQL | 3306, 3307 | Запросы, latency |
| PgSQL (PostgreSQL) | 5432 | Запросы, latency |
| Redis | 6379 | Команды, latency |
| MongoDB | 27017 | Запросы |
| AMQP | 5672 | Очереди сообщений |
| Cassandra | 9042 | Запросы |
| Thrift-RPC | 9090 | RPC-вызовы |
| Memcache | 11211 | Команды |
| NFS | 2049 | Файловые операции |
| DHCP | 67, 68 | DHCPv4 |
| TLS | 443, 993, 995, 5223, 8443, 8883, 9243 | TLS handshake, сертификаты |
| ICMP | - | Ping (v4/v6) |
| SIP/SDP | 5060 | beta; `transport_protocol: tcp` (default udp) |

Общие опции любого протокола в `packetbeat.protocols`: `enabled` (default true), `ports`, `send_request`/`send_response` (сырые сообщения), `keep_null`, `transaction_timeout` (10s), `index` (переопределение индекса для протокола).

Протоколоспецифичные опции:

| Протокол | Ключевые опции |
|----------|----------------|
| DNS | `include_authorities`, `include_additionals` (default false), `send_request`/`send_response` |
| AMQP | `max_body_length` (1000), `parse_headers`, `parse_arguments`, `hide_connection_information` (true) |
| Cassandra | `send_request`/`send_response` (true), `compressor: snappy`, `ignored_ops` |
| Memcache | `maxvalues` (-1/0/N), `maxbytespervalue`, `udptransactiontimeout` (200ms) |
| MongoDB | `max_docs` (10), `max_doc_length` (5000) |
| Redis | `queue_max_bytes` (1MB), `queue_max_messages` (20000) — буфер корреляции |
| Thrift | `transport_type` (socket/framed), `protocol_type` (binary), `idl_files`, `string_max_size` (200), `collection_max_size` (15), `capture_reply`, `obfuscate_strings`, `drop_after_n_struct_fields` (500) |
| TLS | `fingerprints`, `send_certificates`, `include_raw_certificates` |

### Flows (NetFlow-like)

```yaml
packetbeat.flows:
  timeout: 30s
  period: 10s
```

Flows агрегирует сетевые соединения без deep packet inspection.

## Сравнение Metricbeat и Packetbeat

| Критерий | Metricbeat | Packetbeat |
|----------|------------|------------|
| Тип данных | Метрики (числа) | Транзакции (события) |
| Уровень | Приложение/ОС | Сеть (L7) |
| Overhead | Низкий | Заметно выше (DPI, зависит от объёма трафика) |
| Использование | Capacity planning, тренды | Troubleshooting, анализ инцидентов |
| Развёртывание | На каждом хосте | На хосте или на выделенном mirror-порту |

## Docker и Kubernetes

### Metricbeat в Docker

```yaml
# docker-compose.yml
metricbeat:
  image: docker.elastic.co/beats/metricbeat:9.5.5
  user: root
  volumes:
    - ./metricbeat.yml:/usr/share/metricbeat/metricbeat.yml:ro
    - /var/run/docker.sock:/var/run/docker.sock
    - /sys/fs/cgroup:/hostfs/sys/fs/cgroup
    - /proc:/hostfs/proc
    - /:/hostfs
  environment:
    - ELASTICSEARCH_HOSTS=https://elasticsearch:9200
```

### Metricbeat в Kubernetes (DaemonSet)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: metricbeat
  namespace: kube-system
spec:
  template:
    spec:
      containers:
        - name: metricbeat
          image: docker.elastic.co/beats/metricbeat:9.5.5
          # для system-модуля добавьте монтирование /proc, /sys и cgroup хоста в /hostfs
          volumeMounts:
            - name: config
              mountPath: /usr/share/metricbeat/metricbeat.yml
              subPath: metricbeat.yml
            - name: dockersock
              mountPath: /var/run/docker.sock
      volumes:
        - name: config
          configMap:
            name: metricbeat-config
        - name: dockersock
          hostPath:
            path: /var/run/docker.sock
```

Полный пример развёртывания стека в Docker (с hostfs-монтированием) — в [Tutorial: практическая настройка Docker](../Tutorials/practical_setup_with_docker.md).

## Индексы для Beats

| Beat | Индекс | ILM |
|------|--------|-----|
| Filebeat | filebeat-* | filebeat |
| Metricbeat | metricbeat-* | metricbeat |
| Heartbeat | heartbeat-* | heartbeat |
| Auditbeat | auditbeat-* | auditbeat |
| Packetbeat | packetbeat-* | packetbeat |
| Winlogbeat | winlogbeat-* | winlogbeat |

С включённым ILM индексы имеют вид `metricbeat-9.5.5-2026.09.04-000001` и управляются через data stream `metricbeat-*`.

## ILM Policies для Beats

```bash
PUT _ilm/policy/metricbeat
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "50GB",
            "max_age": "30d"
          },
            "set_priority": { "priority": 100 }
        }
      },
      "warm": {
        "min_age": "30d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 }
        }
      },
      "delete": {
        "min_age": "365d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

Действие `freeze` удалено вместе с frozen tier. Актуальные ILM-действия: allocate, delete, force merge, migrate, read only, rollover, downsample, searchable snapshot, set priority, shrink, unfollow, wait for snapshot. Для холодного хранения добавьте фазу `cold` с `searchable_snapshot` (требует настроенного snapshot repository) или `migrate` для перемещения между data tier.

## Выходы (Outputs)

Помимо `output.elasticsearch` (примеры в секциях выше), Beats поддерживают:

```yaml
# Logstash — когда нужна обработка/агрегация перед Elasticsearch
output.logstash:
  hosts: ["logstash:5044"]
  loadbalance: false        # распределять события между хостами
  pipelining: 2             # асинхронные батчи
  bulk_max_size: 2048
  ttl: 30s                  # 0s — без переподключения
  # index: 'metricbeat'     # переопределение индекса
  ssl.enabled: true
  ssl.certificate_authorities: ["/etc/pki/root/ca.pem"]

# Kafka (libbeat)
#output.kafka:
#  hosts: ["kafka:9092"]
#  topic: 'metricbeat'
#  compression: gzip
```

Ключевые опции `output.elasticsearch`: `preset` (`balanced`/`throughput`/`scale`/`latency`/`custom`, default `custom`), `loadbalance` (true), `bulk_max_size` (1600), `max_retries` (3), `backoff.init` (1s) / `backoff.max` (60s), `idle_connection_timeout` (3s), `timeout` (90s), `compression_level` (1), `proxy_url` / `proxy_disable`, `allow_older_versions` (true). TLS: `ssl.verification_mode` (`full` — default / `strict` / `certificate` / `none` — только для диагностики), `ssl.certificate_authorities`, `ssl.certificate` + `ssl.key` (client auth), `ssl.supported_protocols`, `ssl.restart_on_cert_change`.

Вариант доставки через промежуточный слой (beats input Logstash, выбор между прямым `output.elasticsearch` и маршрутизацией через Logstash) — в [Logstash: Входы, выходы и маршрутизация](../Logstash/logstash_inputs_outputs.md).

## Операции и команды (CLI)

Все Beats предоставляют единый набор команд libbeat:

| Команда | Описание |
|---------|----------|
| `run` | Запуск beat (используется по умолчанию без указания команды) |
| `setup` | Первичная настройка: index template, ILM policy + write alias, дашборды Kibana |
| `test config` | Проверка синтаксиса конфига |
| `test output` | Проверка подключения к output (включая credentials) |
| `test modules [MODULE] [METRICSET]` | Тестовый запуск модуля (только Metricbeat): применяет настройки, получает метрики, выводит их |
| `modules list/enable/disable` | Управление модулями (только Metricbeat) |
| `export config` | Вывод эффективной конфигурации в stdout |
| `export template [--es.version X.Y]` | Вывод index template в stdout (`--dir` — экспорт в директорию) |
| `export dashboard --id="DASHBOARD_ID"` | Экспорт дашборда из Kibana в JSON |
| `keystore create/add/list/remove` | Управление хранилищем секретов |
| `show auditd-rules` / `show auditd-status` | Состояние kernel audit subsystem (только Auditbeat; аналог `auditctl -l` / `auditctl -s`) |
| `version` | Версия beat и libbeat |
| `help [COMMAND]` | Справка по команде |

Глобальные флаги: `-c, --config` (путь к конфигу), `-e` (foreground, лог в stderr), `--strict.perms=false`, `-E "key=value"` (переопределение настройки), `--path.config/--path.data/--path.logs`.

### Keystore (хранилище секретов)

```bash
metricbeat keystore create          # создаёт keystore в директории path.data
metricbeat keystore add ES_PWD      # интерактивный ввод значения
metricbeat keystore add ES_PWD --force        # перезаписать существующий ключ
cat /file/with/value | metricbeat keystore add ES_PWD --stdin --force
metricbeat keystore list            # список ключей (без значений)
metricbeat keystore remove ES_PWD
```

В конфиге ключ используется как `${ES_PWD}` — разрешается **до** переменных окружения. Keystore должен создаваться тем же пользователем, что запускает beat. Отличается от keystore Elasticsearch: здесь произвольные имена ключей для настроек beat.

### Управление сервисом (systemd)

```bash
sudo systemctl enable --now metricbeat
sudo systemctl status metricbeat
journalctl -u metricbeat -f          # логи
sudo systemctl restart metricbeat    # после правок конфига
```

После изменения конфига — обязательная проверка перед рестартом: `metricbeat test config && metricbeat test output`.

### Проверка работоспособности (Validation)

```bash
# Данные появились в Elasticsearch:
curl -s https://elasticsearch:9200/metricbeat-*/_search?size=1 | jq '.hits.hits[0]._source'

# Количество документов за последний час:
curl -s https://elasticsearch:9200/metricbeat-*/_count -H 'Content-Type: application/json' -d '
{"query": {"range": {"@timestamp": {"gte": "now-1h"}}}}'

# Статус конкретного монитора Heartbeat:
curl -s https://elasticsearch:9200/heartbeat-*/_search?size=1 \
  -H 'Content-Type: application/json' -d '{"query": {"term": {"monitor.id": "my-website"}}}'
```

Ожидаемый результат: документы с полями `@timestamp`, `agent.version`, `host.name`, `event.dataset` (например `system.cpu`); для Heartbeat — `monitor.id`, `monitor.status` (`up`/`down`), `http.response.status_code`. Дашборды: Metricbeat → *System Overview*, Heartbeat → приложение *Uptime* в Kibana.

## Best Practices

### Общие

1. **Используйте modules** — вместо ручной настройки, когда возможно
2. **Настройте ILM** — автоматическое управление retention
3. **Processors** — обогащайте данные на уровне агента
4. **Мониторинг** — следите за здоровьем Beats через Stack Monitoring
5. **Безопасность** — TLS, API keys вместо паролей (`output.elasticsearch.api_key: "id:api_key"`)
6. **Секреты** — в Beats keystore (`metricbeat keystore create/add/list`), а не в YAML
7. **Проверка перед запуском** — `test config` и `test output` после любых правок
8. **Откат и очистка** — конфиги в `/etc/{beat}/` держите под версионированием; откат = восстановить конфиг → `test config` → `systemctl restart`. Удаление данных: `DELETE _data_stream/metricbeat-*` (или `DELETE metricbeat-*`); удаление beat: `sudo apt remove metricbeat` (конфиги остаются; `purge` — удаляет и их)

### Metricbeat

1. **System module** — включен по умолчанию, не отключайте
2. **Kubernetes module** — для K8s мониторинга
3. **Docker module** — для Docker контейнеров
4. **period: 10s** — хороший баланс между granularity и overhead

### Heartbeat

1. **Уникальный id** для каждого монитора
2. **check.response** — проверяйте не только status code
3. **ssl** — всегда указывайте CA для production
4. **schedule** — не слишком агрессивно (<30s для critical, <5m для остальных)

### Auditbeat

1. **FIM** — ограничивайте paths для избежания перегрузки
2. **hash_types** — sha256 для безопасности, sha1 для скорости
3. **exclude_files** — исключайте временные и изменяющиеся файлы

### Packetbeat

1. **DPI overhead** — учитывайте CPU usage при включении на всех хостах
2. **include_body_for** — ограничивайте для снижения объема данных
3. **Flows** — менее resource-intensive, чем DPI

## Граничные случаи и ограничения

* **FIM на сетевых ФС.** `file_integrity` не предназначен для мониторинга путей на сетевых файловых системах (официальное ограничение).
* **Конфликт auditd.** В `unicast`-режиме только один процесс может получать kernel audit events — остановите системный `auditd`, иначе события теряются.
* **Browser-мониторы Heartbeat** — удалены после 8.4; для E2E-проверок в браузере используйте Synthetics в Kibana.
* **Packetbeat и `any`.** `auto_promisc_mode` не работает с `device: any` — настраивайте promiscuous mode вручную на конкретном интерфейсе.
* **Metricbeat `process` metricset.** AppArmor/LSM может блокировать `ptrace_may_access()` — процессы других пользователей недоступны без соответствующих прав.
* **Metricbeat `process` metricset — delta-метрики.** Процесс должен появиться минимум дважды, чтобы рассчитать `system.process.cpu.total.norm.pct` — при короткоживущих процессах поле отсутствует.
* **Первый запуск FIM.** При `scan_at_start: true` первое сканирование генерирует событие для каждого файла — планируйте объём индекса.
* **CVE-2026-26932 (Packetbeat pgsql).** Некорректная валидация индекса в парсере PostgreSQL-протокола — DoS через специально сформированный пакет (panic процесса). Затронуты версии до 8.19.10 / 9.2.4 включительно; требуется явно включённый протокол `pgsql` на мониторимом порту. Обновитесь или отключите `pgsql`, если он не нужен.

## Troubleshooting

### Данные не появляются в Elasticsearch

1. Проверить конфиг: `metricbeat test config`
2. Проверить подключение к ES: `metricbeat test output` (проверяет output и credentials)
3. Проверить network connectivity
4. Логи: `/var/log/metricbeat/metricbeat` или `journalctl -u metricbeat`
5. Дашборды/шаблон: `metricbeat setup` (загружает index template и dashboards в Kibana)

### High CPU usage

1. Увеличить `period`
2. Отключить неиспользуемые модули
3. Ограничить Packetbeat DPI
4. Проверить `max_file_size` для Auditbeat FIM

### ILM не применяется

1. Проверить policy: `GET _ilm/policy/metricbeat`
2. Проверить статус: `GET _ilm/status`
3. Диагностика индекса: `GET metricbeat-*/_ilm/explain`
4. Проверить permissions для ILM (`manage_ilm`)

## См. также

* **[Filebeat: Обзор](../filebeat_overview.md)** — Filebeat для сбора логов.
* **[Elastic Agent и Fleet](./elastic_agent_and_fleet.md)** — замена Beats на Elastic Agent.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — мониторинг Beats.
* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — дашборды для Beats.
* **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — шаблоны для Beats индексов.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — ILM для Beats данных.
