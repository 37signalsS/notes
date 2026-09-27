# Конфигурация Prometheus

## Определения

**Конфигурация Prometheus** — совокупность параметров, определяющих поведение сервера при сборе, хранении и обработке метрик, а также при взаимодействии с внешними системами. Начиная с версии **Prometheus v3.x**, конфигурация была значительно упрощена за счёт стабилизации экспериментальных функций и добавления механизмов автоматического управления ресурсами.

Настройка осуществляется двумя способами:

1.  **`prometheus.yml`** — основной конфигурационный файл в формате YAML. Определяет задания сбора (scrape jobs), правила (rules), интеграцию с Alertmanager и удалёнными хранилищами (Remote Write/Read).
2.  **CLI-флаги** — параметры командной строки при запуске. Определяют настройки TSDB, параметры веб-интерфейса, режимы работы (Server/Agent) и ограничения ресурсов.

> **См. также:** [Обзор Prometheus](./overview.md), [TSDB](./concepts/tsdb.md), [Alertmanager](./alertmanager.md)

## Основные концепции

### Структура файла prometheus.yml

```yaml
global:
  scrape_interval: 1m
  evaluation_interval: 1m
  # В v3 переменные окружения в external_labels разворачиваются автоматически
  external_labels:
    monitor: 'my-prometheus'
    cluster: '${CLUSTER_NAME}'

rule_files:
  - 'rules/*.rules.yml'

# Настройка встроенного OTLP-приемника (v3)
otlp:
  promote_resource_attributes:
    - service.name
    - k8s.namespace.name

scrape_configs:
  - job_name: 'prometheus'
    scrape_native_histograms: true # Включение сбора нативных гистограмм (v3)
    static_configs:
      - targets: ['localhost:9090']

alerting:
  alertmanagers:
  - api_version: v2            # В v3 поддержка v1 удалена
    static_configs:
      - targets: ['localhost:9093']

remote_write:
  - url: "http://remote-storage.example.com/write"
    # Настройки очередей для оптимизации передачи
    queue_config:
      max_samples_per_send: 500
```

| Блок | Назначение |
|---|---|
| `global` | Глобальные параметры: `scrape_interval`, `evaluation_interval`. В v3 поддерживается автоматический эскейпинг `external_labels` |
| `otlp` | (v3+) Управление маппингом атрибутов OpenTelemetry в лейблы Prometheus. |
| `rule_files` | Пути к файлам с [правилами записи и алертинга](./rules.md). Поддерживаются glob-шаблоны |
| `scrape_configs` | Конфигурация заданий (jobs). В v3 добавлена поддержка `fallback_scrape_protocol` и `scrape_native_histograms` |
| `alerting` | Настройки [Alertmanager](./alertmanager.md). **Важно:** в v3 требуется `api_version: v2` |
| `remote_write` / `remote_read` | Интеграция с LTS ([Mimir](../Mimir/mimir_overview.md), [VictoriaMetrics](../VictoriaMetrics/overview.md)). Подробнее: [Remote Read/Write](./scaling/remote_read_write.md) |

### Блок scrape_configs — параметры скрейпинга

Каждый `job` в `scrape_configs` поддерживает параметры, управляющие частотой, объёмом, форматом сбора данных и обработкой меток. В Prometheus v3 появилась поддержка нативных гистограмм, приоритизации протоколов и контроля честности меток.

```yaml
scrape_configs:
  - job_name: 'app-service'
    # Частота и таймаут
    scrape_interval: 15s          # Как часто опрашивать таргет
    scrape_timeout: 10s           # Таймаут одного запроса (должен быть < scrape_interval)
    # Протокол и формат
    metrics_path: '/metrics'      # Путь эндпоинта метрик
    scheme: 'http'                # http или https
    scrape_protocols:
      - OpenMetricsText            # Приоритет: OpenMetrics 2.0 (v3)
      - PrometheusText             # Фоллбэк на классический текст
      - Protobuf                   # OTLP/Protobuf (если экспортёр поддерживает)
    # Поведение при конфликте меток
    honor_labels: false           # false = Prometheus перезаписывает job/instance
    honor_timestamps: true        # Использовать timestamp из экспортёра
    # Нативные гистограммы и exemplars
    scrape_native_histograms: true # Включить сбор нативных гистограмм (v3)
    exemplars:
      max_exemplars: 100000       # Лимит exemplars на одну метрику
    # Лимиты кардинальности
    sample_limit: 10000           # Максимум samples с одного таргета за scrape
    target_limit: 100             # Максимум таргетов в задании
    label_limit: 40               # Лимит лейблов на одну метрику
    body_size_limit: 15MB         # Максимальный размер HTTP-ответа от таргета

    static_configs:
      - targets: ['app1:8080', 'app2:8080']
        labels:
          env: 'production'
```

**Пояснение ключевых параметров:**

| Параметр | Назначение | Рекомендация |
|---|---|---|
| `scrape_interval` | Частота опроса таргетов. | 15–30s для production; < 10s — только для критичных сервисов. |
| `scrape_timeout` | Таймаут одного HTTP-запроса. | Должен быть минимум на 2–3s меньше `scrape_interval`. |
| `metrics_path` | Путь эндпоинта экспортёра. | По умолчанию `/metrics`. |
| `scheme` | Протокол передачи. | `https` для удалённых таргетов через публичную сеть. |
| `scrape_protocols` | Приоритет форматов ответа. | В v3 используйте `OpenMetricsText` > `PrometheusText` > `Protobuf`. |
| `honor_labels` | Доверять ли меткам от экспортёра. | `false` для большинства случаев; `true` для Pushgateway и кастомных экспортёров. |
| `honor_timestamps` | Использовать ли timestamp экспортёра. | `true` для точности; `false` если экспортёр генерирует устаревшие timestamps. |
| `scrape_native_histograms` | Сбор нативных гистограмм. | `true` в v3 — снижает кардинальность и размер TSDB. |
| `sample_limit` | Максимум samples с одного таргета за scrape. | Защита от high cardinality; при превышении таргет переходит в `DOWN`. |
| `body_size_limit` | Максимальный размер ответа `/metrics`. | `0` = без ограничений (опасно). В production задавайте явно. |

**Особенности v3:**
- Prometheus v3 не добавляет порты по умолчанию (80/443) автоматически. Если порт не передан через Service Discovery или не указан явно в `__address__`, скрейпинг завершится ошибкой.
- При превышении `sample_limit` таргет переходит в статус `DOWN` с ошибкой `sample limit exceeded`. Отслеживайте по метрике `prometheus_target_scrapes_exceeded_sample_limit_total`.

### Блок query — ограничения PromQL

Блок `query` (v3+) управляет ресурсами, потребляемыми при выполнении PromQL-запросов. Это критично для защиты от «взрыва кардинальности» при сложных запросах в Grafana или алертах.

```yaml
query:
  max_concurrency: 20           # Максимум параллельных запросов
  max_samples: 50000000         # Максимум samples, обрабатываемых за один запрос
  timeout: 2m                   # Таймаут выполнения запроса
  lookback_delta: 5m            # Окно поиска данных при отсутствии точного timestamp
```

| Параметр | По умолчанию | Описание |
|---|---|---|
| `max_concurrency` | `false` (без лимита) | Максимум одновременно выполняющихся запросов. Защита от исчерпания CPU. |
| `max_samples` | `50000000` | Максимум сэмплов, которые могут быть прочитаны за один запрос. |
| `timeout` | `2m` | Таймаут выполнения PromQL-выражения. |

**Рекомендации:**
- `max_concurrency: 20` достаточен для большинства сред. Увеличивайте только при наличии мощного железа и низкой кардинальности.
- `max_samples` ограничивает глубину запросов с `rate()` и `histogram_quantile()` на больных дашбордах.
- `timeout` защищает от зависаний при heavy aggregation (`sum by (job) (rate(...[30d]))`).

### Блок storage.tsdb — параметры TSDB

Блок `storage` в `prometheus.yml` позволяет тонко настраивать внутреннюю базу данных временных рядов без использования CLI-флагов.

```yaml
storage:
  tsdb:
    wal-compression: true        # Сжатие WAL (экономит 30–50% диска)
    min-block-duration: 2h       # Минимальный размер блока перед compaction
    max-block-duration: 2h       # Максимальный размер блока
    out-of-order-window: 30m     # Окно для приёма данных из прошлого (v3)
```

| Параметр | По умолчанию | Описание |
|---|---|---|
| `wal-compression` | `false` | Сжатие Write-Ahead Log. Рекомендуется `true` для экономии диска. |
| `min-block-duration` | `2h` | Минимальное время, после которого Head Block записывается на диск. |
| `max-block-duration` | `2h` | Максимальное время жизни Head Block. |
| `out-of-order-window` | `0` (отключено) | Окно, в течение которого Prometheus принимает данные с прошлыми timestamp. |

**Важно:** `out-of-order-window` включен по умолчанию только в Agent Mode. В Server Mode он может потреблять дополнительные ресурсы при больших окнах.

### Recording Rules

Блок `rule_files` указывает пути к файлам с правилами записи (recording rules) и алертинга (alerting rules). Recording Rules предварительно вычисляют сложные PromQL-выражения и сохраняют результаты как новые метрики, снижая нагрузку на сервер при построении дашбордов и алертов.

**Пример файла `recording_rules.yml`:**

```yaml
groups:
  - name: node.recording
    interval: 30s               # Интервал вычисления правил (не влияет на scrape)
    rules:
      # Утилизация CPU в процентах
      - record: node:cpu_utilization:ratio
        expr: |
          100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

      # Доступная память в процентах
      - record: node:memory_utilization:ratio
        expr: |
          1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
```

**Подключение в `prometheus.yml`:**

```yaml
rule_files:
  - 'recording_rules.yml'
  - 'alerting_rules.yml'
```

**Рекомендации:**
- `interval` в группе правил может быть больше `evaluation_interval`, если вычисление дорогое. Если не задан, используется глобальный `evaluation_interval`.
- Используйте recording rules для часто используемых в дашбордах выражений с высокой кардинальностью.
- Валидация: `promtool check rules /etc/prometheus/recording_rules.yml`.

Подробнее: [Правила: Recording и Alerting](./rules.md).

### Alerting — настройка Alertmanager

Блок `alerting` определяет, куда Prometheus отправляет сработавшие алерты для обработки (дедупликации, группировки, маршрутизации).

```yaml
alerting:
  alertmanagers:
    - api_version: v2           # В Prometheus v3 API v1 удалена
      static_configs:
        - targets: ['localhost:9093']
      timeout: 10s              # Таймаут отправки алерта
```

**Параметры `alertmanagers`:**

| Параметр | Описание |
|---|---|
| `api_version` | Версия API Alertmanager. В v3 требуется `v2`. |
| `static_configs` | Фиксированный список экземпляров Alertmanager. |
| `timeout` | Таймаут HTTP-запроса к Alertmanager. По умолчанию `10s`. |
| `scheme` | `http` или `https`. |
| `tls_config` | TLS-настройки для защищённого соединения. |

**HA-режим (кластер Alertmanager):** В production разворачивайте минимум 3 экземпляра Alertmanager. Они синхронизируют состояние через gossip-протокол. Prometheus автоматически распределяет алерты между доступными инстансами.

Подробнее: [Установка Alertmanager](./installation/alertmanager_installation.md), [Alertmanager](./alertmanager.md).

### Service Discovery — обзор

Service Discovery (SD) — механизм автоматического обнаружения целей (targets) для скрейпинга. Вместо статического перечисления IP-адресов Prometheus получает актуальный список эндпоинтов от внешних систем.

**Основные механизмы:**

| Механизм | Описание |
|---|---|
| `static_configs` | Фиксированный список `host:port` в конфигурации. |
| `file_sd_configs` | Чтение целей из JSON/YAML-файлов. Prometheus автоматически подхватывает изменения. |
| `dns_sd_configs` | Обнаружение через DNS-записи (SRV, A). |
| `kubernetes_sd_configs` | Обнаружение Pod, Service, Endpoints через K8s API. |
| `consul_sd_configs` | Обнаружение через Consul. |
| `http_sd_configs` | Опрос внешнего HTTP-эндпоинта (CMDB). |
| `docker_sd_configs` | Обнаружение контейнеров через Docker Engine API. |

**Важно:** Детальная конфигурация SD, фильтрация целей через `relabel_configs` и `metric_relabel_configs` описаны в отдельном руководстве: [Service Discovery и Relabeling](./service_discovery_and_relabeling.md).

### Exemplars

Exemplars — это отдельные точки данных внутри гистограммы, показывающие конкретный trace ID или пример запроса, который попал в корзину. В Prometheus v3 поддержка exemplars включена по умолчанию при использовании нативных гистограмм.

```yaml
scrape_configs:
  - job_name: 'service-with-traces'
    scrape_native_histograms: true
    exemplars:
      max_exemplars: 100000  # Лимит exemplars на одну метрику
    static_configs:
      - targets: ['app:8080']
```

**Ограничения:**
- Exemplars хранятся в отдельном блоке Head в TSDB и потребляют дополнительную память. При высокой кардинальности снизьте `max_exemplars`.
- При Remote Write exemplars отправляются только если бэкенд поддерживает protobuf и флаг `send_exemplars: true`.

## Практические сценарии

### Режим агента (Agent Mode)

Режим Agent оптимизирован для использования в качестве Forwarder'а: он собирает метрики и сразу отправляет их по Remote Write, не сохраняя данные локально (кроме краткосрочного буфера WAL) и не вычисляя правила. Это снижает потребление памяти на 30–50%.

**Запуск:**
```bash
prometheus --agent --config.file=agent.yml
```

**Особенности:**
- Отсутствует блок `rule_files`.
- Недоступны запросы через веб-интерфейс (нет TSDB).
- Обязательно наличие блока `remote_write`.

### Интеграция с OpenTelemetry (OTLP)

Prometheus v3 может принимать метрики напрямую от приложений, использующих SDK OpenTelemetry, без необходимости установки OTLP Collector.

**Настройка:**
1. Запустите Prometheus с флагом `--web.enable-otlp-receiver`.
2. Настройте блок `otlp` в `prometheus.yml` для извлечения нужных метаданных в метки:
   ```yaml
   otlp:
     promote_resource_attributes:
       - service.name
       - service.version
   ```
3. Направьте OTLP экспортёр на эндпоинт `http://<prometheus-ip>:9090/api/v1/otlp/v1/metrics`.

### Recording Rules

Recording Rules предварительно вычисляют сложные PromQL-выражения, снижая нагрузку на сервер при построении дашбордов и алертов.

**1. Создание файла правил:**
```yaml
# /etc/prometheus/recording_rules.yml
groups:
  - name: node.recording
    interval: 30s
    rules:
      # Утилизация CPU в процентах
      - record: node:cpu_utilization:ratio
        expr: |
          100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

      # Доступная память в процентах
      - record: node:memory_utilization:ratio
        expr: |
          1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
```

**2. Подключение в `prometheus.yml`:**
```yaml
rule_files:
  - 'recording_rules.yml'
  - 'alerting_rules.yml'
```

**3. Валидация и применение:**
```bash
# Проверка синтаксиса
promtool check rules /etc/prometheus/recording_rules.yml
# → SUCCESS: 2 rules found

# Горячая перезагрузка конфигурации
curl -X POST http://localhost:9090/-/reload
```

Подробнее: [Правила: Recording и Alerting](./rules.md).

### Управление хранением данных (Retention)

Параметры определяют стратегию удаления старых данных. Если заданы оба параметра, удаление произойдет по первому наступившему условию.

| Метод | Команда / Настройка |
|---|---|
| По времени | `--storage.tsdb.retention.time=30d` |
| По объему | `--storage.tsdb.retention.size=100GB` |
| Комбинированный | Удалять данные старше 14 дней ИЛИ если база превысит 200ГБ |

### Лимиты сбора (Scrape Limits)

Лимиты защищают сервер от «взрыва кардинальности» (high cardinality) и исчерпания памяти при опросе слишком тяжелых экспортеров.

```yaml
scrape_configs:
  - job_name: "dynamic-service"
    sample_limit: 10000        # Максимум метрик с одного таргета
    target_limit: 50           # Максимум таргетов в задании
    label_limit: 40            # Лимит лейблов на одну метрику
    body_size_limit: 15MB      # Максимальный размер HTTP-ответа от таргета
    scrape_native_histograms: true
```

**Рекомендации v3:**
- Используйте `scrape_native_histograms` для перехода на более эффективный формат хранения гистограмм.
- При превышении `sample_limit` таргет переходит в статус `DOWN` с ошибкой `sample limit exceeded`. Состояние можно отследить по метрике `prometheus_target_scrapes_exceeded_sample_limit_total`.
- `body_size_limit` критичен для защиты от неконтролируемого роста ответов от `/metrics` (по умолчанию 0, т.е. без ограничений).

### Миграция с Prometheus v2 на v3

Переход на Prometheus v3 требует проверки конфигурации на предмет устаревших параметров и поведения.

**Основные изменения:**
1.  **Alertmanager API v1 удалена.** В `alerting.alertmanagers` требуется явно указывать `api_version: v2`.
2.  **UTF-8 включена по умолчанию.** Имена метрик и меток могут содержать любые символы. Проверьте дашборды и алерты на совместимость.
3.  **Нативные гистограммы.** Для использования переключите `scrape_native_histograms: true` в нужных jobs. Классические `_bucket`-метрики продолжают работать.
4.  **Автоматическое управление ресурсами.** Флаги `--auto-gomemlimit` и `--auto-gomaxprocs` включены по умолчанию.
5.  **Переменные окружения в `external_labels`.** Интерполяция `${VAR}` работает автоматически без дополнительных флагов.
6.  **Нет портов по умолчанию.** Prometheus v3 не добавляет порты 80/443 автоматически. Указывайте порт явно в `__address__`.

**План миграции:**
1. Сделайте бэкап `prometheus.yml` и TSDB.
2. Запустите Prometheus v3 с параметром `--storage.tsdb.retention.time` равным текущему retention, чтобы старые данные оставались доступными.
3. Постепенно включайте `scrape_native_histograms` для отдельных jobs и наблюдайте за кардинальностью.
4. Проверьте дашборды и алерты на корректность отображения метрик с UTF-8.
5. После стабилизации увеличьте retention до нужного значения.

## Дополнительная информация

### Валидация конфигурации

Используйте `promtool` для проверки синтаксиса перед перезагрузкой. В v3 `promtool` также проверяет соответствие UTF-8 стандартам.

```bash
# Проверка конфигурации (Server Mode)
promtool check config /etc/prometheus/prometheus.yml

# Проверка конфигурации (Agent Mode)
promtool check config --agent /etc/prometheus/agent.yml

# Проверка нативных гистограмм в TSDB
promtool tsdb analyze /var/lib/prometheus
```

> **Подробнее:** [promtool и лучшие практики](./promtool_and_best_practices.md)

### Перезагрузка без остановки (Hot Reload)

Обновление параметров `prometheus.yml` (кроме CLI-флагов) возможно без перезапуска процесса.

**Способы:**
1. **HTTP API (рекомендуется):** требуется флаг `--web.enable-lifecycle`.
   ```bash
   curl -X POST http://localhost:9090/-/reload
   ```
2. **Systemd:**
   ```bash
   sudo systemctl reload prometheus
   ```

> **Примечание:** При изменении CLI-флагов (например, параметров Retention или порта) перезапуск процесса **обязателен**.

### Устранение неполадок конфигурации

| Проблема | Причина | Проверка | Решение |
|---|---|---|---|
| `config reload failed` | Ошибка в `prometheus.yml` или правах | `journalctl -u prometheus -f` | Проверить YAML-синтаксис, права на файл (`chmod 644`) |
| Targets в `DOWN` | Неправильный `metrics_path` или порт | `curl -v http://target:9100/metrics` | Проверить `relabel_configs` и сетевую доступность |
| `scrape timeout` | Большая кардинальность или медленный экспортер | `curl -w "%{time_total}" https://target:9100/metrics` | Увеличить `scrape_timeout`, оптимизировать экспортер |
| `sample limit exceeded` | Превышен `sample_limit` в job | Метрика `prometheus_target_scrapes_exceeded_sample_limit_total` | Увеличить `sample_limit` или добавить `metric_relabel_configs` |
| `OTLP endpoint not found` | Флаг `--web.enable-otlp-receiver` не включен | `curl http://localhost:9090/api/v1/status/flags` | Добавить флаг в команду запуска |
| `secret leaked in /-/config` | Секреты указаны в `prometheus.yml` | `curl http://localhost:9090/api/v1/status/config` | Перенести секреты в `credentialsFile` или env vars |
| `prometheus_http_requests_total{code="403"}` | Попытки доступа к защищенному эндпоинту без кредов | Проверить логи доступа | Добавить авторизацию в клиенты или настроить `web-config.yml` |
| UTF-8 имена не работают | Экспортёр не поддерживает UTF-8 или старый парсер | `curl -v http://target:9100/metrics` | Обновить экспортёр; проверять `Accept: text/plain; version=1.0.0; escaping=allow-utf-8` |
| `query timeout` | Слишком сложный PromQL или большой `max_samples` | `promtool query instant` | Уменьшить окно агрегации, добавить recording rules |
| WAL corruption | Аварийное завершение, диск переполнен | `prometheus --log.level=debug` | Проверить `prometheus_tsdb_wal_size_bytes`; восстановить из снапшота |

### Рекомендации по управлению конфигурацией

**1. Разделение окружений:**
Используйте отдельные файлы или директории для dev/staging/production. Различайте конфиги через `--config.file` или переменные окружения.

**2. Контроль версий:**
Храните `prometheus.yml`, файлы правил и `web-config.yml` в Git. Используйте branching model (main → staging → production).

**3. Валидация в CI/CD:**
Автоматически проверяйте конфигурацию и правила при каждом коммите:
```bash
promtool check config prometheus.yml
promtool check rules rules/*.yml
```

**4. Изоляция секретов:**
Никогда не коммитьте пароли и токены в репозиторий. Используйте:
- `credentialsFile` (Prometheus v3) для секретов в YAML.
- Внешние файлы, монтируемые в контейнер (`:ro`).
- Переменные окружения, передаваемые через оркестратор.

**5. Документирование изменений:**
Ведите changelog конфигурации. Каждое изменение `scrape_interval`, `retention` или `relabel_configs` должно иметь обоснование.

**6. Мониторинг конфигурации:**
Собирайте метрику `prometheus_config_last_reload_successful` (gauge: 1 = успех, 0 = ошибка) и настраивайте алерт на её падение.

### Паттерны GitOps и автоматизации

**Ansible:**
```yaml
- name: Развёртывание конфигурации Prometheus
  ansible.builtin.copy:
    src: prometheus.yml
    dest: /etc/prometheus/prometheus.yml
    owner: prometheus
    group: prometheus
    mode: '0644'
  notify: reload prometheus
```

**Helm (Kubernetes):**
Конфигурация Prometheus в Kubernetes передаётся через ConfigMap. Используйте `additionalScrapeConfigs` для сложных job-ов, не поддерживаемых CRD.

**Terraform + local-exec:**
```hcl
resource "local_file" "prometheus_config" {
  content  = templatefile("${path.module}/prometheus.yml.tftpl", { ... })
  filename = "${path.module}/generated/prometheus.yml"
}
```

### См. также

*   [Обзор Prometheus](./overview.md)
*   [TSDB](./concepts/tsdb.md)
*   [Alertmanager](./alertmanager.md)
*   [Правила: Recording и Alerting](./rules.md)
*   [Service Discovery и Relabeling](./service_discovery_and_relabeling.md)
*   [Remote Read/Write](./scaling/remote_read_write.md)
*   [promtool и лучшие практики](./promtool_and_best_practices.md)
*   [Установка Alertmanager](./installation/alertmanager_installation.md)
*   [Безопасность Prometheus](./security.md)
*   [Формат экспозиции метрик](./concepts/metric_types/exposition_format.md)
