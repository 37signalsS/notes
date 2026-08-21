# Агентный сбор логов Docker

## Определения

**Агентный сбор логов (Agent-based Logging)** — архитектурный подход, при котором сбор, обработка и отправка телеметрии выполняются специализированным приложением (агентом), работающим независимо от Docker Engine.

**Node-агент** — экземпляр агента, запущенный на каждом хосте (в контейнере или как системный сервис), который собирает логи всех контейнеров данного узла. Это наиболее эффективный и масштабируемый метод для Docker-сред.

**Sidecar-агент** — запуск агента в отдельном контейнере рядом с конкретным приложением. Используется редко, обычно для изоляции критических сервисов или при отсутствии доступа к файловой системе хоста.

**Позиционный файл (Checkpoint/Position file)** — персистентный файл, в котором агент сохраняет смещение (offset) последнего успешно обработанного байта для каждого лог-файла. Обеспечивает возобновление чтения после перезагрузки без потери данных и дублирования записей.

**Multiline-склейка** — механизм агента, объединяющий несколько последовательных строк лога (например, Java Stack Trace) в одно логическое событие перед отправкой в хранилище.

## Предпосылки

- **Docker Engine** версии 20.10 или выше (для поддержки Dual Logging и стабильного формата файлов логов)
- **Права root** или членство в группе `docker` для чтения файлов в `/var/lib/docker/containers/`
- **Доступ к Docker Socket** (`/var/run/docker.sock`) — необходим для агентов, использующих Docker API для обнаружения контейнеров и получения метаданных
- **Доступ к хранилищу логов** (Loki, Elasticsearch, ClickHouse и т.д.) по сети из Docker-хоста
- **Достаточный объём диска** для хранения позиционных файлов и временной буферизации (при использовании агентов с disk-backed буфером)
- **Docker Compose** (рекомендуется) — для декларативного управления контейнером агента

**Проверка доступа к лог-файлам:**
```bash
# Убедитесь, что файлы логов доступны для чтения
ls -la /var/lib/docker/containers/*/*-json.log | head -3
# → -rw-r----- 1 root root 12345 ... /var/lib/docker/containers/.../-json.log

# Проверка доступа к Docker Socket
ls -la /var/run/docker.sock
# → srw-rw---- 1 root docker 0 ... /var/run/docker.sock
```

## Базовые концепции

Основная идея — разделение ответственности (Decoupling). Docker Engine отвечает за работу контейнеров и запись их `STDOUT/STDERR` в локальные файлы, а агент — за чтение этих файлов, их парсинг, обогащение метаданными и доставку в систему хранения.

**Схема работы:**
`Приложение → STDOUT/STDERR → Docker Engine (json-file driver) → Локальный диск (/var/lib/docker/containers/) → Агент → Сеть → Система хранения`

### Механизмы сбора: Файлы vs API

Агенты могут собирать логи двумя способами:
1.  **Прямое чтение файлов (Tail)**: Агент монтирует `/var/lib/docker/containers/` и читает файлы напрямую. Это максимально производительный метод, не нагружающий Docker API. Файлы имеют формат JSON: каждая строка — JSON-объект с полями `log`, `stream`, `time`.
2.  **Docker API (Events/Logs)**: Агент подключается к `/var/run/docker.sock` и получает поток логов через вызовы API (`/containers/{id}/logs`). Это проще в настройке прав доступа, но создает нагрузку на Docker Engine при больших объемах данных.

**Рекомендация:** Используйте прямое чтение файлов (Tail) для production — это минимизирует нагрузку на Docker daemon и обеспечивает максимальную производительность.

### Чекпоинты (Checkpointing) и надежность

Для предотвращения потери данных и дубликатов агенты используют **позиционные файлы (checkpoints)**.
*   **Механизм**: Агент записывает смещение (offset) последнего прочитанного байта каждого файла на персистентный диск.
*   **Отказоустойчивость**: После перезагрузки агента или хоста чтение возобновляется строго с места остановки.
*   **Важно**: Позиционные файлы необходимо выносить на Volume хоста, иначе при пересоздании контейнера агента он начнет читать все логи заново.

**Примеры позиционных файлов:**
| Агент | Файл позиций | Формат |
| :--- | :--- | :--- |
| **Grafana Alloy** | `alloy-positions.json` | JSON (смещение + timestamp) |
| **Vector** | `vector_positions.json` | JSON |
| **Fluentd** | `fluentd-docker.pos` | `path offset inode` (текст) |
| **Filebeat** | `registry/filebeat/log.json` | JSON (внутренний реестр) |

### Преимущества агентного подхода

- **Надежность**: Локальная буферизация на диске (средствами Docker Engine) позволяет переживать сбои сети или временную недоступность хранилища.
- **Гибкость**: Возможность сложной обработки (парсинг JSON, маскирование паролей, фильтрация ненужных логов) до их отправки в сеть.
- **Метаданные**: Автоматическое добавление меток (имя контейнера, образ, лейблы, ID) через интеграцию с Docker API.
- **Multiline**: Склеивание многострочных логов (stack traces, логи приложений) в одно событие — невозможно с лог-драйверами.
- **Фильтрация**: Отправка только нужных логов (по имени контейнера, лейблам, содержимому), что снижает нагрузку на хранилище и сеть.

## Практические сценарии

### Сценарий 1: Grafana Alloy (рекомендуется для Loki и Grafana Stack)

В 2026 году Alloy — стандарт для стека Grafana, объединяющий возможности Promtail и OTel. Является официальным преемником Promtail (EOL весна 2026). Подробнее: **[Grafana Alloy: Обзор](../../Grafana/grafana_alloy_overview.md)**.

**`docker-compose.yml` (Node-агент):**
```yaml
services:
  alloy:
    image: grafana/alloy:v1.9.0
    container_name: alloy-logger
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - ./alloy/positions:/var/lib/alloy/positions
    command:
      - run
      - --storage.path=/var/lib/alloy/positions
      - --disable-reporting
      - /etc/alloy/config.alloy
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

**`config.alloy`:**
```alloy
// Обнаружение контейнеров через Docker API
discovery.docker "local" {
  host = "unix:///var/run/docker.sock"
}

// Сбор логов
loki.source.docker "logs" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.docker.local.targets
  forward_to = [loki.process.main.receiver]
}

// Обработка и добавление метаданных
loki.process "main" {
  stage.docker { }
  forward_to = [loki.write.loki_backend.receiver]
}

// Отправка в Loki
loki.write "loki_backend" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
  external_labels = {
    source = "docker-alloy",
    env    = "prod",
  }
}
```

**Валидация:**
```bash
# Проверка статуса агента
docker logs alloy-logger --tail 50

# Проверка доступности Debug UI
curl -s http://localhost:12345/metrics | head -5

# Проверка отправки логов
docker logs -f alloy-logger | grep -i "loki"
```

### Сценарий 2: Vector (максимальная производительность)

Vector (написан на Rust) потребляет в 10 раз меньше ресурсов, чем Fluentd, и не имеет пауз GC.

**`docker-compose.yml`:**
```yaml
services:
  vector:
    image: timberio/vector:0.42.0-debian
    container_name: vector-logger
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./vector/vector.yaml:/etc/vector/vector.yaml:ro
      - ./vector/positions:/var/lib/vector/positions
    command: ["--config", "/etc/vector/vector.yaml"]
    restart: unless-stopped
```

**`vector.yaml`:**
```yaml
sources:
  docker:
    type: docker_logs
    docker_host: "unix:///var/run/docker.sock"
    exclude_containers:
      - vector-logger   # Исключаем сам агент

transforms:
  process:
    type: remap
    inputs: [docker]
    source: |
      . = parse_json!(.message)
      .app_name = .container_name
      .timestamp = now()

sinks:
  loki:
    type: loki
    inputs: [process]
    endpoint: "http://loki:3100"
    labels:
      container: "{{ container_name }}"
      image: "{{ image }}"
    encoding:
      codec: json
    batch:
      max_bytes: 1048576
      timeout_secs: 2
    buffer:
      type: memory
      max_events: 5000
```

**Валидация:**
```bash
# Проверка конфигурации
docker exec vector-logger vector validate --config /etc/vector/vector.yaml

# Проверка состояния агента
docker logs vector-logger --tail 30
```

### Сценарий 3: Fluentd (сложные энтерпайз-решения)

Fluentd остается стандартом для сложных энтерпрайз-решений благодаря огромному количеству плагинов (500+).

**`docker-compose.yml`:**
```yaml
services:
  fluentd:
    image: fluent/fluentd:v1.19.3-debian-1
    container_name: fluentd-logger
    volumes:
      - /var/lib/docker/containers:/fluentd/log/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./fluentd/pos:/fluentd/pos
      - ./fluentd/conf:/fluentd/etc:ro
    user: root
    restart: unless-stopped
```

**`fluent.conf`:**
```conf
<source>
  @type tail
  path /fluentd/log/containers/*/*-json.log
  pos_file /fluentd/pos/docker-logs.pos
  tag docker.*
  <parse>
    @type json
    time_format %Y-%m-%dT%H:%M:%S.%NZ
  </parse>
</source>

<filter docker.**>
  @type record_transformer
  <record>
    container_id ${tag_parts[2]}
    node_name "#{Socket.gethostname}"
  </record>
</filter>

<match docker.**>
  @type elasticsearch
  host "elasticsearch:9200"
  logstash_format true
  flush_interval 5s
</match>
```

**Валидация:**
```bash
# Проверка конфигурации
docker exec fluentd-logger fluentd --dry-run --config /fluentd/etc/fluent.conf

# Проверка позиционного файла
cat ./fluentd/pos/docker-logs.pos
```

### Сценарий 4: Filebeat (Elastic Stack)

Filebeat — максимально простое решение для интеграции с ELK.

**`filebeat.yml`:**
```yaml
filebeat.inputs:
- type: container
  paths:
    - '/var/lib/docker/containers/*/*.log'
  stream: all

processors:
  - add_docker_metadata:
      host: "unix:///var/run/docker.sock"
  - decode_json_fields:
      fields: ["message"]
      target: "data"

output.logstash:
  hosts: ["logstash:5044"]
```

**`docker-compose.yml`:**
```yaml
services:
  filebeat:
    image: elastic/filebeat:8.15.0
    container_name: filebeat-logger
    volumes:
      - /var/lib/docker/containers:/usr/share/dockerlogs:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./filebeat/filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - ./filebeat/registry:/usr/share/filebeat/data
    user: root
    restart: unless-stopped
```

### Работа с многострочными логами (Multiline)

Одна из главных задач агента — склеивание Stack Traces в одно событие.
*   **Проблема**: Docker пишет каждую строку трейса как отдельный JSON-объект.
*   **Решение**: Использование Multiline-фильтров по паттерну начала строки (обычно дата).

**Пример для Grafana Alloy:**
```alloy
loki.process "multiline" {
  stage.multiline {
    firstline = "^[\\d{4}-\\d{2}-\\d{2}]" // Начало строки: 2026-08-03
    max_wait  = "3s"
  }
}
```

**Пример для Fluentd:**
```conf
<filter docker.**>
  @type concat
  key log
  multiline_start_regexp /^\d{4}-\d{2}-\d{2}/
  flush_interval 3s
</filter>
```

**Пример для Vector:**
```yaml
transforms:
  multiline:
    type: remap
    inputs: [docker]
    source: |
      # Vector обрабатывает multiline через VRL
      if includes(["ERROR", "Exception"], .message) {
        .group = "error"
      }
```

### Фильтрация логов по контейнерам

Частая задача — собирать логи только от определённых контейнеров, исключая системные сервисы.

**Alloy (по лейблам):**
```alloy
discovery.docker "filtered" {
  host = "unix:///var/run/docker.sock"
  // Фильтрация по лейблам Docker
  filters = [
    { name = "label", values = ["logging=enabled"] },
  ]
}
```

**Vector (по именам контейнеров):**
```yaml
sources:
  docker:
    type: docker_logs
    exclude_containers:
      - alloy-logger
      - prometheus
      - grafana
```

**Fluentd (по тегам):**
```conf
<source>
  @type tail
  path /fluentd/log/containers/*/*-json.log
  exclude_path ["/fluentd/log/containers/fluentd*"]
</source>
```

## Дополнительная информация

### Сравнение современных агентов (2026)

| Критерий | Fluentd | Filebeat | Grafana Alloy | Vector |
| :--- | :--- | :--- | :--- | :--- |
| **Язык** | Ruby / C | Go | Go | Rust |
| **Потребление RAM** | 200-500 МБ | 50-100 МБ | 100-300 МБ | 20-80 МБ |
| **Потребление CPU** | Среднее / Высокое | Низкое | Среднее | Экстремально низкое |
| **Сложная логика** | Плагины Ruby | Скрипты (ограничено) | River (декларативно) | VRL (очень мощно) |
| **Multiline** | Встроенный (concat) | Встроенный | Встроенный (stage.multiline) | Встроенный |
| **Фильтрация** | Плагины Ruby | processors | loki.process / discovery | VRL transforms |
| **Позиционный файл** | Текстовый (`pos_file`) | JSON (registry) | JSON (`alloy-positions.json`) | JSON (`vector_positions.json`) |
| **Disk-backed буфер** | Да (buffer_type file) | Нет | Нет (RAM-only) | Да (buffer.type disk) |
| **Hot reload** | Да | Нет (требует restart) | Да (hot reload) | Да |
| **Экосистема** | Максимальная (500+ плагинов) | Elastic | Grafana / OTel | Универсальная |
| **Статус (2026)** | Актуальный | Актуальный | **Рекомендуемый** | Актуальный |

### Рекомендации по выбору агента

| Сценарий | Рекомендуемый агент | Обоснование |
| :--- | :--- | :--- |
| **Grafana Stack (Loki)** | **Grafana Alloy** | Нативная интеграция, OTel, Debug UI, миграция с Promtail. |
| **Elastic Stack (ELK)** | **Filebeat** | Бесшовная интеграция с Kibana и Elasticsearch. |
| **Высокая нагрузка (>10K логов/сек)** | **Vector** | Rust, нет GC, disk-backed буфер, минимум ресурсов. |
| **Сложные Enterprise-трансформации** | **Fluentd** | 500+ плагинов, кодируемый pipeline на Ruby. |
| **Минимум ресурсов (IoT, Edge)** | **Vector** | 20-80 МБ RAM, <1% CPU. |
| **Совместимость с OTel** | **Grafana Alloy** | Нативная поддержка OpenTelemetry Protocol. |

### Лучшие практики

1.  **Используйте Node-агент, а не Sidecar** — один экземпляр агента на хост эффективнее, чем запуск отдельного агента для каждого контейнера.
2.  **Выносите позиционные файлы на Volume** — иначе при пересоздании контейнера агента будут дублироваться все логи.
3.  **Настройте фильтрацию** — исключайте контейнеры самого агента и служебных сервисов (Prometheus, Grafana) из сбора логов.
4.  **Настройте Multiline** для приложений, генерирующих stack traces (Java, Python, Go).
5.  **Используйте disk-backed буфер** (Vector) для production — RAM-буфер теряет логи при перезагрузке.
6.  **Мониторьте агента**: настройте метрики Prometheus для агента (Alloy: `:12345/metrics`, Vector: `:9598/metrics`).
7.  **Версионируйте конфигурацию** агента в Git и используйте `docker-compose` для воспроизводимого развертывания.
8.  **Ротируйте локальные логи Docker** даже при использовании агента — агент читает файлы, которые может расти бесконечно. Подробнее: **[Управление ротацией логов Docker](./docker_log_rotation.md)**.

### Ограничения и известные проблемы

1.  **Docker Socket — это root-доступ**: Монтирование `/var/run/docker.sock` в контейнер агента даёт полный контроль над Docker Engine. Ограничивайте доступ через AppArmor/SELinux и не используйте это в multi-tenant средах без изоляции.
2.  **Задержка сбора (Latency)**: Агент читает файлы с задержкой (обычно 1-5 секунд). Для real-time требований (аудит, security) рассмотрите Loki Docker Driver: **[Настройка лог-драйвера Grafana Loki](./loki_logging_driver_setup.md)**.
3.  **Дублирование при ошибке позиционного файла**: Если Volume с позиционным файлом удалён или повреждён, агент начнёт чтение с начала всех файлов, что приведёт к массовым дубликатам в хранилище.
4.  **Формат JSON-only**: Агенты работают с форматом JSON-драйвера Docker. Если приложение пишет бинарные данные в stdout, формат файла может быть повреждён.
5.  **Multiline-склейка не универсальна**: Паттерны склейки зависят от формата логов приложения. Java stack traces, Python Traceback, Go panics — всё требует разных regex-паттернов.
6.  **Docker Desktop (macOS/Windows)**: Файлы логов хранятся внутри VM, а не на файловой системе хоста. Монтирование `/var/lib/docker/containers` работает через виртуальный диск с пониженной производительностью.
7.  **Рост позиционных файлов**: При большом количестве контейнеров (>100) позиционные файлы могут занимать >100 МБ. Регулярно очищайте устаревшие записи (Alloy делает это автоматически, Fluentd — нет).

### Типичные ошибки и решения

| Ошибка / Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Агент не видит контейнеры** | Нет доступа к Docker Socket или неправильный путь. | Проверьте монтирование `/var/run/docker.sock` и права пользователя (`docker` группа). |
| **Дублирование логов после перезагрузки** | Позиционный файл не сохранён на персистентный Volume. | Вынесите позиционные файлы на Volume хоста (см. `docker-compose.yml` выше). |
| **Агент потребляет >500 МБ RAM** | Слишком много целей или отсутствие фильтрации. | Настройте фильтрацию (exclude_containers), уменьшите batch size, включите disk-backed буфер (Vector). |
| **Логи приходят с задержкой >30 сек** | Проблемы с сетью или перегрузка хранилища. | Проверьте сеть (ping, traceroute), увеличьте batch timeout, проверьте статус хранилища (Loki/ES). |
| **`permission denied` при чтении логов** | Контейнер агента запущен от неправильного пользователя. | Используйте `user: root` в `docker-compose.yml` или добавьте агента в группу `docker`. |
| **Multiline не работает** | Неправильный regex `firstline` / `multiline_start_regexp`. | Проверьте формат логов (`docker logs <container>`), адаптируйте regex под формат даты вашего приложения. |
| **Агент падает с OOMKilled** | Слишком много логов или слишком большой batch. | Увеличьте `memory.limits` в Docker Compose / Kubernetes, уменьшите `max_batch_size`. |
| **`error connecting to docker`** | Docker Socket недоступен или daemon остановлен. | `sudo systemctl start docker`, проверьте права доступа к сокету. |
| **Файлы логов повреждены ( truncated JSON)** | Docker Engine перезаписал файл при ротации до завершения чтения агентом. | Используйте Dual Logging (Docker 20.10+), настройте ротацию: **[Управление ротацией логов Docker](./docker_log_rotation.md)**. |
| **Высокая нагрузка CPU на Docker daemon** | Агент использует Docker API (Events/Logs) вместо чтения файлов. | Переключите агента на прямое чтение файлов (Tail) вместо Docker API. |

### Безопасность

- **Docker Socket = root-доступ**: Любой процесс с доступом к `/var/run/docker.sock` может управлять Docker Engine (запускать/останавливать контейнеры, загружать образы). Ограничивайте доступ:
  ```bash
  # Создайте группу docker-logs с ограниченными правами
  sudo groupadd docker-logs
  sudo usermod -aG docker-logs $USER
  
  # Ограничьте права на сокет (только чтение логов)
  sudo setfacl -m u:alloy:r /var/run/docker.sock
  ```
- **Секреты в логах**: Настройте фильтрацию для маскирования паролей, токенов и других секретов перед отправкой в хранилище.
- **TLS для удалённых хранилищ**: Используйте HTTPS при отправке логов по сети (Loki, Elasticsearch).

### Производительность и масштабирование

| Параметр | Рекомендация |
| :--- | :--- |
| **Количество агентов** | 1 экземпляр на хост (Node-агент). |
| **Batch size** | 400-1000 записей (Alloy), 1000-5000 (Vector). |
| **Batch timeout** | 1-5 секунд. |
| **RAM лимит** | 256-512 МБ для <100 контейнеров; 512 МБ-1 ГБ для >100 контейнеров. |
| **CPU лимит** | 0.5-1.0 CPU для <100 контейнеров; 1.0-2.0 CPU для >100 контейнеров. |
| **Disk (позиционные файлы)** | 1-10 МБ на 100 контейнеров. |

**Рекомендация по масштабированию**: При >500 контейнеров на хост используйте Vector с disk-backed буфером и кластеризацией, или Alloy с clustering mode.

### Ссылки на смежные темы
*   **[Обзор драйверов логирования Docker](./docker_logging_drivers_overview.md)** — база и сравнение методов.
*   **[Настройка лог-драйвера Grafana Loki для Docker](./loki_logging_driver_setup.md)** — альтернативный подход прямой отправки.
*   **[Управление ротацией логов Docker](./docker_log_rotation.md)** — защита диска от переполнения.
*   **[Централизованное логирование Docker: Лог-драйверы](./docker_centralized_logging.md)** — лог-драйверы (GELF, Syslog, Fluentd).
*   **[Vector: Обзор и архитектура](../../Vector/vector_overview.md)** — документация Vector.
*   **[Grafana Alloy: Обзор](../../Grafana/grafana_alloy_overview.md)** — документация Alloy.
*   **[Logstash: Обзор и ключевые концепции](../../ELK_Stack/Logstash/logstash_overview.md)** — документация Logstash.
*   **[Grafana Loki: обзор системы](../../Loki/loki_overview.md)** — документация Loki.
