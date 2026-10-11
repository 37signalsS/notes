# Filebeat: Обзор и конфигурация

**Актуально для:** Filebeat 8.x / 9.x

> Эта заметка является авторитетным источником по вопросам сбора и пересылки логов с использованием Filebeat. Она описывает архитектуру, современные методы идентификации файлов и практические сценарии развертывания в различных средах. Текущий GA-релиз на момент написания — 9.5.5 (ветка 8.19 также поддерживается).

## Определения

* **Filebeat** — легковесный агент (shipper), написанный на Go, предназначенный для сбора, фильтрации и отправки логов в Elasticsearch, Logstash или Kafka.
* **Filestream** — основной и рекомендуемый тип входных данных (input) в Filebeat 8.x/9.x. Тип `log` объявлен устаревшим в 7.16 и отключён в 9.0 (доступен только с `allow_deprecated_use: true`, исключительно для миграции).
* **Prospector (Сканер)** — компонент filestream, который сканирует `paths` по расписанию (`prospector.scanner.check_interval`, дефолт 10s), находит новые и изменённые файлы и передаёт их harvester'у.
* **Harvester (Сборщик)** — процесс внутри Filebeat, отвечающий за чтение одного конкретного файла построчно. Один harvester — один открытый файл; количество одновременных harvester'ов на input ограничивается `harvester_limit`.
* **Registry (Реестр)** — файл состояний (offset) для каждого отслеживаемого файла в формате append-only log: инкрементальные обновления вместо полной перезаписи JSON, как в старом `log` input. Расположение: `${path.data}/registry`, сброс на диск — `filebeat.registry.flush` (дефолт 1s), права — `filebeat.registry.file_permissions` (дефолт 0600). С 9.5 доступен backend `memlog` (technical preview).
* **File Identity (Идентификация файлов)** — метод определения, что два наблюдения файла — это один и тот же файл. `native` (inode + device) — дефолт до 9.0; `fingerprint` (SHA-256 хеш байтового диапазона) — дефолт с 9.0; `path` и `inode_marker` — альтернативы для нестабильных inode.
* **Fingerprinting** — метод идентификации файла путём хеширования его начального блока (дефолт: первые 1024 байта; `length` не может быть меньше 64). С 9.5 включён growing fingerprint: файлы меньше размера фингерпринта отслеживаются по имеющимся байтам и мигрируют на полный SHA-256 при достижении размера, без дублирования данных.
* **Backpressure (Обратное давление)** — механизм, при котором Filebeat замедляет чтение данных, если система-приемник перегружена, предотвращая потерю событий и переполнение памяти.
* **Ingest Pipeline** — конвейер обработки данных в Elasticsearch, который выполняет преобразования (парсинг, обогащение, фильтрацию) перед индексацией. Filebeat может загружать pipelines автоматически при использовании модулей (`filebeat setup -e`).

## Основные концепции

### Архитектура входа Filestream

Вход `filestream` заменяет устаревший тип `log`. Его ключевые особенности:
1.  **Порядок обработки**: настраиваемая цепочка парсеров (например, сначала `ndjson`, затем `multiline`), что было невозможно в старых версиях.
2.  **Идентификация (File Identity)**: с 9.0 по умолчанию — **fingerprint**.
    *   *Проблема 1KB (9.0–9.4)*: Filebeat не начинает читать новый файл, пока тот не достигнет размера `offset + length` (дефолт 1024 байта). Для мелких логов уменьшите `prospector.scanner.fingerprint.length` (минимум 64) или верните native-идентификацию: `file_identity.native: ~` + `prospector.scanner.fingerprint.enabled: false`.
    *   *С 9.5*: growing fingerprint (дефолт) снимает ограничение — мелкие файлы читаются сразу.
3.  **Registry Performance**: формат реестра исключает перезапись огромных JSON-файлов, выполняя только инкрементальные обновления, что критично при мониторинге тысяч файлов.
4.  **Clean Options**: поведение при обнаружении удалённых/переименованных файлов:
    *   `clean_removed: true` (дефолт) — удалять состояние файлов, исчезнувших с диска;
    *   `clean_renamed: false` (дефолт) — удалять состояние переименованных файлов;
    *   `clean_inactive: -1` (дефолт, отключено) — удалять состояние файлов, не изменявшихся дольше указанного времени. Значение должно быть больше `ignore_older + check_interval`, иначе файлы будут перечитываться с начала.
5.  **Закрытие файлов** (`close.on_state_change.*`): `removed: true` (дефолт), `renamed: false` (дефолт), `eof: false` (дефолт); `close.timeout` (дефолт отключён, потенциальная потеря данных).

### Сравнение типов входов

| Характеристика | `filestream` (рекомендуемый) | `log` (устаревший) |
| :--- | :--- | :--- |
| **Статус** | Текущий input | Deprecated в 7.16, отключён в 9.0 (`allow_deprecated_use: true` только для миграции) |
| **Идентификация файлов** | Fingerprint (дефолт с 9.0) или native | inode + device (native) |
| **Парсеры** | Цепочка (ndjson → multiline → container → syslog) | Ограниченный набор |
| **Производительность** | Высокая (инкрементальный реестр) | Средняя (полная перезапись реестра при каждом ACK) |
| **Ротация файлов** | Полная поддержка через `clean_*` и `close.on_state_change.*` | Базовая поддержка |
| **Миграция** | `take_over.enabled: true` (beta) | Не поддерживается |

### Вход journald (systemd journal)

Помимо файловых входов Filebeat умеет читать журнал systemd напрямую — это основной способ собирать логи сервисов, которые пишут в stdout/stderr и управляются systemd, без промежуточных файлов ротации:

```yaml
filebeat.inputs:
  - type: journald
    id: host-journald              # идентификатор состояния в registry
    paths:                         # каталоги с journal-файлами
      - /var/log/journal
      - /run/log/journal
    seek: end                      # head | tail | since
    units: [nginx.service, app.service]   # только перечисленные юниты
    syslog_identifiers: [sshd]             # фильтр по syslog-идентификатору
    facilities: [auth, daemon]             # фильтр по facility
    include_matches:                       # произвольные совпадения по полям записи
      CONTAINER_NAME: my-app
```

Параметры и нюансы:

*   **`id`** — ключ состояния в реестре. При изменении `id` (другая конфигурация) Filebeat начинает с «чистого» курсора и читает журнал заново — учтите это при правках конфигурации, иначе получите повторное чтение старых записей (источник дублей, см. [Семантика доставки и дедупликация](log-delivery-and-deduplication.md)).
*   **`seek`** — откуда начинать: `head` (с начала), `tail` (с конца — дефолт), `since` (с момента, заданного `since`, например `since: 2h`). Для догона исторических данных используйте `head`/`since` осознанно: большой журнал = большой первый bulk.
*   **`paths`** — каталоги journal-файлов (поддержка каталогов — GA с 9.0); без них Filebeat ищет журнал в стандартных путях дистрибутива.
*   **`units` / `syslog_identifiers` / `facilities` / `include_matches`** — фильтрация на входе: не тащите в ELK весь журнал рабочего хоста, если нужны только приложения — экономия трафика, места и индексации.
*   **`journalctl_path`** — читать журнал через вызов `journalctl` (нужен на хостах, где прямое чтение файлов невозможно); **`chroot`** — изолированная директория для чтения журнала (типовой случай — контейнер, которому примонтирован хостовый журнал).
*   В контейнерах доступ к журналу хоста даётся примонтированием `/var/log/journal` (и/или `/run/log/journal`) с правами на чтение — иначе вход не увидит записей.
*   Разбор временных меток journald-записей и поведение `@timestamp` проверяйте на тестовом событии ([Логи: временные метки](log-timestamps-and-late-events.md)).

### Автоматическое обнаружение (Autodiscover)

Filebeat поддерживает динамическое обнаружение источников логов в контейнерных средах. Hints ищутся в аннотациях Pod / метках Docker с префиксом `co.elastic.logs.`; дефолтный input для hints — `filestream`.

#### Пример autodiscover для Docker

```yaml
filebeat.autodiscover:
  providers:
    - type: docker
      hints.enabled: true
      hints.default_config:
        type: filestream
        id: container-${data.container.id}
        close.on_state_change.removed: false
        prospector.scanner.symlinks: true
        parsers:
          - container: ~
        paths:
          - /var/lib/docker/containers/${data.container.id}/*.log
```

#### Пример autodiscover для Kubernetes

```yaml
filebeat.autodiscover:
  providers:
    - type: kubernetes
      node: ${NODE_NAME}
      hints.enabled: true
      hints.default_config:
        type: filestream
        id: container-${data.kubernetes.container.id}
        close.on_state_change.removed: false
        prospector.scanner.symlinks: true
        parsers:
          - container: ~
        paths:
          - /var/log/containers/*-${data.kubernetes.container.id}.log
```

Пояснения:
* `parsers: - container: ~` разбирает строки Docker/CRI-логов (временные метки, stream) до line-фильтрации, multiline и JSON — это замена удалённому `container` input.
* `prospector.scanner.symlinks: true` нужен, потому что `/var/log/containers/*.log` — симлинки на `/var/log/pods/...`.
* С 9.5 `hints.input_allow_list` ограничивает типы input'ов, которые могут быть запущены из hints (по умолчанию выключен).

### Безопасность и хранение секретов

Для предотвращения утечки паролей в конфигурационных файлах используется **Filebeat Keystore**:
* Позволяет хранить API-ключи и пароли в зашифрованном виде.
* Обращение к секретам в YAML через синтаксис `${SECRET_NAME}`.

```bash
# Создание keystore
filebeat keystore create

# Добавление секрета (интерактивный ввод значения)
filebeat keystore add ES_API_KEY

# Просмотр списка (без значений)
filebeat keystore list

# Удаление секрета
filebeat keystore remove ES_API_KEY
```

Дополнительно:
* Конфиг `filebeat.yml` должен принадлежать пользователю, запускающему Filebeat (обычно root), и не быть доступным на запись группе/остальным — иначе Filebeat отказывается запускаться (`strict.perms`). В Docker обходят флагом `-strict.perms=false`.
* HTTP-эндпоинт метрик по умолчанию выключен и должен биндиться на `localhost` (см. Мониторинг).
* CVE-2026-78588 (HTTP Endpoint input): специально сформированные сжатые запросы к эндпоинту ingestion могут исчерпать память процесса — не открывайте HTTP Endpoint input наружу и обновляйте Filebeat.

### Процессоры (Processors)

Processors выполняют обогащение, фильтрацию и преобразование событий перед отправкой:

* **add_host_metadata** — добавляет информацию о хосте (IP, имя, ОС).
* **add_docker_metadata** — добавляет информацию о Docker-контейнере (имя, лейблы, образ).
* **add_kubernetes_metadata** — добавляет информацию о Kubernetes Pod (имя, namespace, лейблы).
* **decode_json_fields** — декодирует JSON-строки в указанных полях (альтернатива ndjson-парсеру для уже собранных данных).
* **drop_fields** — удаляет ненужные поля для уменьшения размера события.
* **rename** — переименовывает поля для соответствия ECS (Elastic Common Schema).
* **fingerprint** — генерирует хеш указанных полей события (дефолт SHA-256) для дедупликации.

## Требования и предварительная подготовка

### Системные требования

* **ОС**: Linux (amd64, arm64), macOS (amd64, arm64), Windows (amd64)
* **RAM**: минимум 256 MiB; в Kubernetes — 200–300 MiB (кеш фингерпринтов и реестр потребляют RAM пропорционально количеству файлов)
* **Диск**: место под бинарник + реестр (`${path.data}/registry`, размер зависит от количества отслеживаемых файлов)
* **Сеть**: доступ к Elasticsearch/Logstash/Kafka (порты 9200/5044/9092)

### Установка

```bash
# Debian/Ubuntu (современный способ — keyring вместо deprecated apt-key)
wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo gpg --dearmor -o /usr/share/keyrings/elasticsearch-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/elasticsearch-keyring.gpg] https://artifacts.elastic.co/packages/9.x/apt stable main" | sudo tee -a /etc/apt/sources.list.d/elastic-9.x.list
sudo apt-get update && sudo apt-get install filebeat

# RHEL/CentOS
sudo rpm --import https://artifacts.elastic.co/GPG-KEY-elasticsearch
sudo tee /etc/yum.repos.d/elastic.repo <<EOF
[elastic-9.x]
name=Elastic repository for 9.x packages
baseurl=https://artifacts.elastic.co/packages/9.x/yum
gpgcheck=1
gpgkey=https://artifacts.elastic.co/GPG-KEY-elasticsearch
enabled=1
autorefresh=1
type=rpm-md
EOF
sudo yum install filebeat

# Автозапуск
sudo systemctl enable --now filebeat
```

PGP-ключ Elastic: D88E42B4, fingerprint `4609 5ACC 8548 582C 1A26 99A9 D27D 666C D88E 42B4`. Для существующих установок 8.x репозиторий `packages/8.x/apt` остаётся актуальным (ветка 8.19 поддерживается).

### Проверка работоспособности

```bash
# Проверка конфигурации
sudo filebeat test config
# → Config OK

# Проверка подключения к выходу
sudo filebeat test output
# → elasticsearch: OK

# Просмотр разрешённой конфигурации (с подставленными дефолтами)
filebeat export config

# Просмотр логов в реальном времени
journalctl -u filebeat -f
```

## Практические сценарии

### 1. Настройка входа filestream с парсингом JSON

Пример для Filebeat 9.x с уникальным ID и миграцией со старого типа `log`.

```yaml
filebeat.inputs:
- type: filestream
  id: "app-prod-v1" # Уникальный ID обязателен
  paths:
    - /var/log/myapp/*.log

  # Миграция: забирает состояния файлов из остановленных входов 'log' (beta)
  take_over:
    enabled: true

  prospector.scanner.check_interval: 10s
  prospector.scanner.exclude_files: ['.gz$']
  prospector.scanner.fingerprint.length: 1024 # Можно уменьшить до 64 для мелких файлов (9.0–9.4); в 9.5+ growing fingerprint читает мелкие файлы сразу

  parsers:
    - ndjson:
        target: "" # Раскрывать JSON в корень документа
        overwrite_keys: true
    - multiline:
        type: pattern
        pattern: '^\['
        negate: true
        match: after

output.elasticsearch:
  hosts: ["https://es-cluster:9200"]
  api_key: "${ES_API_KEY}" # Секрет из Keystore
  ssl.certificate_authorities: ["/etc/filebeat/certs/ca.crt"]
```

Пояснения:
* `take_over` работает только с остановленными входами: захват состояний активных `log`/`filestream` input'ов не поддерживается и приводит к дублированию или потере данных.
* Чтение сжатых (gzip) логов: `compression: auto` на уровне input'а (каждый harvester gzip-файла потребляет ~100 КБ дополнительной памяти).
* Максимальный размер одного события — `max_bytes` (дефолт 10 МБ; всё, что больше, отбрасывается).

### 2. Использование модулей (Nginx)

Модули включают в себя Ingest Pipelines для Elasticsearch и готовые дашборды для Kibana.

```bash
# 1. Включение модуля
filebeat modules enable nginx

# 2. Настройка путей (в /etc/filebeat/modules.d/nginx.yml)
# - module: nginx
#   access:
#     enabled: true
#     var.paths: ["/var/log/nginx/access.log*"]

# 3. Загрузка ресурсов в ES и Kibana (требуется настроенный setup.kibana.host)
filebeat setup -e

# Список доступных модулей
filebeat modules list
```

### 3. Глобальные процессоры для обогащения данных

```yaml
processors:
  - add_host_metadata: ~
  - add_docker_metadata: ~
  - drop_fields:
      fields: ["agent.ephemeral_id", "agent.id", "ecs.version"]
      ignore_missing: true
```

### 4. Отправка данных через Logstash

Когда возможностей Filebeat недостаточно для парсинга:

```yaml
output.logstash:
  hosts: ["logstash1:5044", "logstash2:5044"]
  loadbalance: true
  bulk_max_size: 1600
  pipelining: 2
  compression_level: 3
```

### 5. Отправка данных через Kafka

Для высоконагруженных сред с буферизацией:

```yaml
output.kafka:
  hosts: ["kafka1:9092", "kafka2:9092"]
  topic: "logs-%{[agent.version]}"
  partition.round_robin:
    reachable_only: true
  required_acks: 1
  compression: gzip
  max_message_bytes: 1000000
```

### 6. Развертывание в Docker

Для сбора логов контейнеров с хоста:

```yaml
services:
  filebeat:
    image: elastic/filebeat:9.5.5
    container_name: filebeat-logger
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./filebeat/filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - ./filebeat/registry:/usr/share/filebeat/data
    user: root
    command: filebeat -e -strict.perms=false # монтируемый конфиг не принадлежит root внутри контейнера
    restart: unless-stopped
```

### 7. Развертывание в Kubernetes (DaemonSet)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: filebeat
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: filebeat
  template:
    metadata:
      labels:
        app: filebeat
    spec:
      containers:
      - name: filebeat
        image: elastic/filebeat:9.5.5
        args: ["-c", "/etc/filebeat/filebeat.yml", "-e"]
        resources:
          limits:
            memory: 300Mi
          requests:
            memory: 200Mi
        volumeMounts:
        - name: varlog
          mountPath: /var/log
        - name: containers
          mountPath: /var/lib/docker/containers
          readOnly: true
        - name: filebeat-config
          mountPath: /etc/filebeat/filebeat.yml
          subPath: filebeat.yml
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
      - name: containers
        hostPath:
          path: /var/lib/docker/containers
      - name: filebeat-config
        configMap:
          name: filebeat-config
```

## Устранение неполадок

### Типичные ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `data path already locked` | Другой экземпляр Filebeat уже запущен | Остановите предыдущий процесс или проверьте `ps aux \| grep filebeat` |
| `config file must be owned by the user...` (strict.perms) | `filebeat.yml` принадлежит не тому пользователю или доступен на запись другим | `chown root:root filebeat.yml && chmod 640 filebeat.yml`; в Docker — `-strict.perms=false` |
| `no modules or inputs enabled...` | Нет включённых input'ов/модулей и не настроен autodiscover | Проверьте `enabled: true` хотя бы в одном input или настройте `filebeat.autodiscover` |
| `Could not find index pattern` | Kibana не содержит шаблон индекса | Выполните `filebeat setup --dashboards` |
| `no outputs are defined` | Output не настроен или опечатка | Проверьте секцию `output` в `filebeat.yml` |
| `connection refused` | Elasticsearch/Logstash недоступен | Проверьте сетевую доступность: `curl -I http://es:9200` |
| `certificate signed by unknown authority` | Проблема с TLS-сертификатом | Укажите правильный CA в `ssl.certificate_authorities` |
| `permission denied` | Нет прав на чтение лог-файлов | Запустите от root или добавьте пользователя в группу |
| Файлы < 1024 байт не читаются (9.0–9.4) | Дефолтный fingerprint ждёт роста файла | Уменьшите `prospector.scanner.fingerprint.length` (мин. 64) или обновитесь до 9.5 (growing fingerprint) |

### Отладка

```bash
# Включение отладочного логирования (все селекторы)
filebeat -e -d "*"

# Отладка конкретных компонентов через конфиг
# logging.level: debug
# logging.selectors: ["publish", "registrar"]

# Отладка конкретного модуля
filebeat -e -d "publish"

# Переопределение настройки из CLI (полезно для тестов)
filebeat -e -E logging.level=debug

# Для теста — вывод событий в stdout вместо отправки (в filebeat.yml):
# output.console:
#   pretty: true
```

### Мониторинг Filebeat

Filebeat предоставляет HTTP-эндпоинт для сбора метрик (technical preview, по соображениям безопасности выключен по умолчанию):

```yaml
http.enabled: true
http.host: localhost # рекомендуется оставлять localhost
http.port: 5066
```

Эндпоинты: `/` — информация о beat'е, `/stats` — внутренние метрики (JSON; `?pretty` для форматирования). Для unix-сокета: `http.host: unix:///var/run/filebeat.sock`, запрос — `curl --unix-socket /var/run/filebeat.sock 'http:/stats/?pretty'`. Опция `http.pprof.enabled` включает `/debug/pprof/` (только на localhost).

Ключевые метрики из `/stats`:
* `filebeat.harvester.open_files` / `filebeat.harvester.running` / `filebeat.harvester.started` / `filebeat.harvester.closed` / `filebeat.harvester.skipped` — состояние harvester'ов
* `filebeat.events.added` / `filebeat.events.done` / `filebeat.events.active` — события на входе
* `registrar.states.current` — количество отслеживаемых файлов в реестре
* `registrar.writes.success` / `registrar.writes.total` — записи реестра
* `libbeat.pipeline.events.published` / `filtered` / `dropped` / `failed` / `retry` — поток событий через pipeline
* `libbeat.output.events.acked` / `failed` / `dropped` — подтверждения от выхода
* `libbeat.output.read.bytes` / `libbeat.output.write.bytes` — сетевой трафик
* `beat.memstats.rss` / `beat.runtime.goroutines` / `system.load.1` — ресурсы

Каждые 30 секунд Filebeat также логирует сводку изменившихся метрик в JSON (INFO-уровень, `log.logger: monitoring`); управляется настройкой `logging.metrics`.

## Граничные случаи и ограничения

### Ротация файлов

* **Рекомендуемая стратегия**: rename + create (logrotate по умолчанию). Filebeat распознаёт переименованный файл и продолжает чтение с последнего offset, новый файл подхватывает при следующем сканировании.
* **Избегайте copytruncate**: стратегия copy+truncate может терять строки, записанные между копированием и усечением (а в версиях < 9.0 с native-идентификацией ещё и дублировать события). Если приложение не умеет переоткрывать файлы и copytruncate неизбежен, помогите Filebeat отличить активный файл от ротированных:

```yaml
filebeat.inputs:
- type: filestream
  id: "copytruncate-app"
  paths:
    - /var/log/app/*.log
  rotation.external.strategy.copytruncate:
    suffix_regex: '\.\d+$' # ротированные файлы вида app.log.1, app.log.2
    # dateformat: -20060102 # если суффикс — дата
```

* **Windows**: используйте даты в именах ротированных файлов — Windows не позволяет переиспользовать имя, пока файл открыт другим процессом.
* **Закрытие при ротации**: `close.on_state_change.renamed` (дефолт `false`) и `close.on_state_change.removed` (дефолт `true`) определяют, когда закрывать harvester после ротации.

### Большие файлы

* Filebeat не загружает весь файл в память — чтение идёт построчно
* Для очень больших файлов (>100 GiB) настройте `close_inactive` (дефолт 5m) для освобождения ресурсов
* Максимальный размер одного события — `max_bytes` (дефолт 10 МБ); строки длиннее отбрасываются
* Сжатые логи: `compression: auto` включает чтение gzip-файлов (~100 КБ дополнительной памяти на harvester)

### Многострочные логи (Multiline)

Конфигурация для склеивания Stack Traces:

```yaml
parsers:
  - multiline:
      type: pattern
      pattern: '^\d{4}-\d{2}-\d{2}' # Начало нового события
      negate: true
      match: after
```

Типы multiline: `pattern`, `count` (`count_lines: N`), `while`, `until`. Дополнительные опции: `flush_pattern`, `max_lines`, `timeout`.

Склеивание многострочных событий на стороне Logstash (multiline codec) и сравнение подходов — в [Logstash: Многострочные сообщения](./Logstash/logstash_inputs_outputs.md#многострочные-сообщения-multiline-codec).

### Кодировки файлов

Filebeat не определяет кодировку автоматически — она задаётся явно на уровне input'а (не парсера). Дефолт — `plain` (ASCII). Поддерживаются `utf-8`, `utf-16be`/`utf-16le` (с BOM и без), `gbk`, `gb18030`, `big5`, `euc-kr`, `euc-jp`, `shift-jis`, `koi8r`, `koi8u`, `windows-1251` и другие из рекомендаций W3C для HTML5:

```yaml
filebeat.inputs:
- type: filestream
  id: "gbk-app"
  paths:
    - /var/log/gbk-app/*.log
  encoding: gbk
```

### Идентификация файлов и inode reuse

* На Linux inode переиспользуются: если файл удалён и создан новый с тем же inode, native-идентификация может пропустить строки. Fingerprint-идентификация (дефолт с 9.0) устойчива к этому.
* Смена метода file identity при рестарте: Filebeat мигрирует offset'ы только при переходе на fingerprint (с native/path); обратный переход приведёт к перечитыванию всех файлов с начала.
* `include_file_fingerprint: true` (дефолт) добавляет в событие поле `log.file.fingerprint` — хеш содержимого файла.

## Рекомендации по тюнингу производительности

1.  **Queue**: внутренняя очередь `queue.mem` буферизует события в памяти. Дефолты: `events: 3200`, `flush.min_events: 2048` (legacy-параметр — глобальный максимум размера батча; новые конфигурации управляют размером через `bulk_max_size`), `flush.timeout: 10s`. Для сохранения событий при перезапуске — `queue.disk` (persistent queue: `path`, `max_size`, `segment_size: 1GB`, `read_ahead: 512`).
2.  **Batch Size**: `bulk_max_size` в output (дефолт 1600) должен соответствовать возможностям кластера.
3.  **Memory Limits**: в Kubernetes устанавливайте `resources.limits.memory` не менее 200–300 MiB, так как кеширование фингерпринтов и реестра потребляет RAM пропорционально количеству файлов.
4.  **Harvester Limit**: `harvester_limit` ограничивает количество одновременных harvester'ов на один input (дефолт `0` — без ограничений). Установите значение для контроля потребления CPU и файловых дескрипторов.
5.  **Scan Frequency**: интервал сканирования новых файлов — `prospector.scanner.check_interval` (дефолт 10s). Уменьшите для более быстрого обнаружения, увеличьте для снижения нагрузки на диск.
6.  **Graceful shutdown**: `shutdown_timeout` задаёт ожидание завершения отправки событий при остановке (по умолчанию отключён — Filebeat не ждёт publisher).

## Cleanup — возврат настроек и удаление тестовых артефактов

```bash
# 1. Остановить Filebeat перед изменением реестра
sudo systemctl stop filebeat

# 2. Полный сброс состояния чтения (перечитать все файлы с начала)
sudo mv /var/lib/filebeat/registry /var/lib/filebeat/registry.bak
sudo systemctl start filebeat

# 3. Отключить тестовый input (enabled: false) или удалить его из filebeat.yml,
#    затем проверить конфигурацию
sudo filebeat test config
# → Config OK

# 4. Удалить тестовые индексы в Elasticsearch (если тестировали с output.elasticsearch)
curl -u elastic:$PASS -k -X DELETE "https://es-cluster:9200/filebeat-*"
# → {"acknowledged":true}

# 5. Удалить keystore-секреты, добавленные для теста
filebeat keystore remove TEST_API_KEY
```

Пояснения:
* Реестр всегда обновляется при штатной остановке Filebeat; при аварийной остановке события, отправленные после последнего flush (`filebeat.registry.flush`, дефолт 1s), будут отправлены повторно.
* `filebeat.registry.migrate_file` позволяет указать путь к старому файлу реестра при переносе данных Filebeat на новый хост.

## Ссылки и взаимосвязи

* **[Обзор Elastic Stack](./elk_stack_overview.md)** — архитектура и место Filebeat в системе.
* **[Beats Family](./Elasticsearch/beats_family.md)** — Metricbeat, Heartbeat, Auditbeat, Packetbeat для метрик и аудита.
* **[Elastic Agent и Fleet](./Elasticsearch/elastic_agent_and_fleet.md)** — замена Beats, централизованное управление через Fleet.
* **[Миграция log/container → filestream](https://www.elastic.co/docs/reference/beats/filebeat/migrate-to-filestream)** — официальное руководство Elastic.
* **[Логирование в Docker](../Docker/Docker_logs/docker_agent_based_logging.md)** — детально про сбор через сокет.
* **[Logstash: Фильтрация и роутинг](./Logstash/logstash_pipelines.md)** — если возможностей Filebeat недостаточно.
* **[Grok и Dissect Patterns](./grok_dissect_patterns.md)** — коллекция паттернов для парсинга логов.
* **[Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md)** — обработка документов в Elasticsearch.
* **[Семантика доставки и дедупликация](./log-delivery-and-deduplication.md)** — откуда берутся дубли при at-least-once и как сделать приём идемпотентным (fingerprint → `_id`).
* **[Логи: временные метки и запоздавшие события](./log-timestamps-and-late-events.md)** — `@timestamp`/`event.ingested`, запоздавшие события.
* **[Официальная документация Filebeat](https://www.elastic.co/docs/reference/beats/filebeat)**.
