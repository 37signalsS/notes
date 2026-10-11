# Обзор Prometheus

[Prometheus](./overview.md) — это автономная система мониторинга с открытым исходным кодом, входящая в состав CNCF (второй проект по значимости после [Kubernetes](../Kubernetes/kubernetes_overview.md)), предназначенная для сбора и обработки метрик в реальном времени. Она является стандартом де-факто для сбора временных рядов (Time Series), выполнения запросов на языке PromQL и генерации оповещений в экосистемах на основе открытых стандартов.

> **Важно:** Актуальная документация описывает **Prometheus v3.x** (релиз ноября 2024 года). Версии 2.x перешли в статус поддержки, многие функции (Native Histograms, OTLP) стали стандартными или значительно улучшены.

## Определения

*   **Prometheus** — автономная система мониторинга, которая собирает метрики с контролируемых объектов, сохраняет их в виде временных рядов, позволяет выполнять запросы на языке PromQL и генерировать оповещения.
*   **Prometheus Agent** — режим работы сервера (флаг `--enable-feature=agent`), при котором отключены локальное хранилище запросов и алертинг, а данные сразу пересылаются во внешнее хранилище через [Remote Write](./scaling/remote_read_write.md). Оптимизирован для удаленных филиалов, Edge-вычислений и контейнеризированных сред.
*   **Временной ряд (Time Series)** — последовательность значений одной метрики, распределённых во времени, идентифицируемая уникальным набором меток (labels).
*   **Скрапинг (Scraping)** — основной метод сбора данных в Prometheus, при котором сервер сам опрашивает HTTP-эндпоинты целей.
*   **Экспортер (Exporter)** — вспомогательный агент, который транслирует метрики из сторонних систем (БД, ОС, сети) в формат, понятный Prometheus.
*   **Metadata API** — интерфейс для получения информации о типах метрик, их описаниях и единицах измерения, что критично для интеграции с OpenTelemetry.
*   **TSDB (Time Series Database)** — встроенная база данных временных рядов, спроектированная для эффективной записи, экстремального сжатия метрик и быстрого чтения при запросах. Подробнее: [Внутреннее устройство TSDB](./concepts/tsdb.md).
*   **PromQL** — язык запросов Prometheus, предназначенный для выборки и агрегации временных рядов. Подробнее: [PromQL — функции](./concepts/promql/functions.md).

## Основные концепции

### Многомерная модель данных

Prometheus идентифицирует данные через имя метрики и набор пар `ключ=значение` (labels).
*   **UTF-8 Support (v3.x):** Поддержка любых символов UTF-8 в именах метрик и меток позволяет нативно интегрировать метрики из OpenTelemetry без переименования (например, `http.server.duration` теперь валидное имя).
*   **Кардинальность:** Количество уникальных комбинаций меток напрямую влияет на потребление памяти. Подробнее: [Лейблы и кардинальность](./concepts/labels_and_cardinality.md).

### Методы сбора данных

| Метод | Описание | Применение |
| :--- | :--- | :--- |
| **Pull (Scraping)** | Prometheus опрашивает `/metrics` по HTTP. | Стандарт для долгоживущих сервисов. |
| **Native OTLP (v3.x)** | Прямой приём данных по протоколу OTLP (Push). | Интеграция с OpenTelemetry без лишних агентов. |
| **ScrapeConfigs (v3.x)** | Новый динамический механизм конфигурации сбора. | Упрощение управления сложными флотами целей. |
| **Pushgateway** | Промежуточное звено для кратковременных задач. | Cronjobs, Batch-скрипты. |

### Нативные гистограммы (Native Histograms)

В Prometheus v3.x **Native Histograms** стали стабильной технологией. В отличие от "классических" гистограмм, они:
*   Не требуют ручного определения границ бакетов (`le` label).
*   Занимают значительно меньше места в хранилище (один временной ряд вместо десятков).
*   Обеспечивают высокую точность за счёт динамической экспоненциальной сетки.

### Архитектура системы

| Компонент | Роль в системе | Ссылка |
| :--- | :--- | :--- |
| **Prometheus Server** | Сбор (Scrape/OTLP), хранение (TSDB), вычисления. | — |
| **Prometheus Agent** | Легковесный коллектор для пересылки данных. | [Remote Write](./scaling/remote_read_write.md) |
| **TSDB** | Хранилище с поддержкой Out-of-Order (OOO) данных. | [TSDB — концепции](./concepts/tsdb.md) |
| **PromQL Engine** | Выполнение запросов. В v3 включает "Explain" и Query Builder. | [PromQL](./concepts/promql/functions.md) |
| **Alertmanager** | Дедупликация, группировка и доставка оповещений. | [Alertmanager](./alertmanager.md) |
| **Service Discovery** | Автоматическое обнаружение целей (статический, файловый, Consul, Docker). | [Relabeling](./service_discovery_and_relabeling.md) |
| **Remote Storage** | Использование протокола **Remote Write 2.0** для эффективности. | [Remote Read/Write](./scaling/remote_read_write.md) |

### Пользовательский интерфейс и визуализация

В версии 3.0 представлен обновлённый интерфейс и расширенная экосистема:
*   **New React UI:** Полностью переработанный веб-интерфейс с поддержкой тем и Metrics Explorer.
*   **Explain Tab:** Инструмент для разбора сложности и логики PromQL-запросов.
*   **Визуализация:** Интеграция с Grafana, Perses и другими системами дашбордов.

## Практические сценарии

### Предварительные требования

**Аппаратные требования (single-instance):**
*   **CPU:** 2–4 ядра для средних нагрузок (до 200k samples/s). При >500k samples/s требуется 4–8 ядер.
*   **RAM:** ~1 ГБ на каждые 100 000 активных серий + 4 ГБ базовый overhead. При 1M рядов требуется 16–32 ГБ RAM.
*   **Диск:** NVMe SSD рекомендуется для WAL и TSDB. Требуемый объём зависит от retention и кардинальности. Оценка: ~100–500 МБ/день на 100k активных серий.
*   **Сеть:** Порт `9090` (HTTP API/UI), `9093` (Alertmanager), `9094` (cluster gossip).

**Программные требования:**
*   **ОС:** Linux (Debian 12+, Ubuntu 22.04+, RHEL 9+), BSD или macOS. Для production рекомендуется systemd.
*   **Архитектура:** amd64, arm64, armv7.
*   **Зависимости:** Go 1.21+ (для сборки из исходников), systemd (для управления сервисом).

### Сценарий 1: Установка на физический сервер или VM (bare-metal)

Рекомендуемый метод для production-сред с максимальным контролем.

**Шаг 1. Создание пользователя и каталогов:**
```bash
sudo useradd --no-create-home --shell /bin/false prometheus
sudo mkdir -p /etc/prometheus /var/lib/prometheus
sudo chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
```

**Шаг 2. Загрузка и верификация (v3.13.2):**
```bash
PROMETHEUS_VERSION="3.13.2"
cd /tmp
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/sha256sums.txt
sha256sum --check --ignore-missing sha256sums.txt
# → prometheus-3.13.2.linux-amd64.tar.gz: OK
```

**Шаг 3. Установка файлов:**
```bash
tar xvfz prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
cd prometheus-${PROMETHEUS_VERSION}.linux-amd64
sudo mv prometheus promtool /usr/local/bin/
sudo cp -r consoles console_libraries /etc/prometheus/
sudo cp prometheus.yml /etc/prometheus/
sudo chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
sudo chown prometheus:prometheus /usr/local/bin/prometheus /usr/local/bin/promtool
```

**Шаг 4. Настройка systemd-юнита (`/etc/systemd/system/prometheus.service`):**
```ini
[Unit]
Description=Prometheus Server
Documentation=https://prometheus.io/docs/introduction/overview/
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/var/lib/prometheus/ \
    --storage.tsdb.retention.time=15d \
    --storage.tsdb.wal-compression \
    --web.enable-lifecycle \
    --web.enable-otlp-receiver \
    --web.listen-address=:9090

Restart=always
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Шаг 5. Запуск и проверка:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus
systemctl is-active prometheus
# → active
```

**Шаг 6. Валидация:**
```bash
# Проверка конфигурации
promtool check config /etc/prometheus/prometheus.yml
# → SUCCESS: 0.00 kB ... OK

# Проверка доступности API
curl -s http://localhost:9090/-/healthy
# → healthy

curl -s http://localhost:9090/-/ready
# → ready

# Проверка целей скрапинга
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets | length'
# → 1 (или больше, в зависимости от конфигурации)
```

### Сценарий 2: Установка через Docker или Podman

Используется для быстрого развертывания или изолированных сред. Рекомендуется использовать конкретные теги версий вместо `latest`.

```bash
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml:ro \
  -v prometheus_data:/prometheus \
  prom/prometheus:v3.13.2 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.wal-compression \
  --web.enable-lifecycle
# → Container started with ID ...
```

Для production-стека мониторинга (Prometheus + Grafana + Alertmanager + Node Exporter) используйте готовый шаблон: [Обзор Docker Stack](./installation/docker_stack/overview.md).

### Сценарий 3: Базовый `prometheus.yml` для старта

Минимальная конфигурация для мониторинга хоста и самого Prometheus:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    monitor: 'my-prometheus'
    env: 'production'

rule_files:
  - 'rules/*.rules.yml'

alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets: ['localhost:9093']

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']
    scrape_interval: 30s
```

### Сценарий 4: Валидация и проверка работоспособности

После установки выполните обязательные проверки:

```bash
# 1. Валидация синтаксиса конфигурации
promtool check config /etc/prometheus/prometheus.yml
# → SUCCESS

# 2. Проверка правил алертинга (если есть)
promtool check rules /etc/prometheus/rules/*.yml
# → SUCCESS

# 3. Проверка формата метрик экспортера
curl -s http://localhost:9100/metrics | promtool check metrics
# → SUCCESS

# 4. Проверка доступности всех целей
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, health: .health}'
# → все health: "up"

# 5. Выполнение тестового запроса PromQL
curl -s 'http://localhost:9090/api/v1/query?query=up' | jq '.data.result | length'
# → количество активных целей
```

### Сценарий 5: Самомониторинг Prometheus

Критически важно собирать метрики самого Prometheus для контроля здоровья TSDB:

```yaml
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```

**Ключевые метрики для алертинга:**
*   `prometheus_tsdb_head_series`: Количество активных временных рядов в памяти.
*   `prometheus_tsdb_storage_blocks_bytes`: Общий объем хранилища на диске.
*   `rate(prometheus_tsdb_head_samples_appended_total[5m])`: Скорость записи новых данных.
*   `prometheus_tsdb_wal_size_bytes`: Размер WAL на диске.

### Жизненный цикл метрики

1.  **Инструментация:** Приложение использует клиентскую библиотеку или SDK OpenTelemetry.
2.  **Передача данных:**
    *   *Классика:* Prometheus опрашивает `/metrics` (Pull).
    *   *Современно:* Приложение пушит OTLP-данные напрямую в Prometheus.
3.  **Обработка:** Prometheus применяет [Recording Rules](./rules.md). Благодаря **Metadata API**, сервер сохраняет информацию о единицах измерения (например, `seconds`), что позволяет дашбордам автоматически масштабировать оси.
4.  **Анализ:** Инженер использует PromQL или вкладку "Explain" в Web UI для отладки запроса.
5.  **Оповещение:** При срабатывании [правила алертинга](./rules.md) данные уходят в Alertmanager.

### Сравнение с альтернативами

| Характеристика | Prometheus | Grafana Alloy | VictoriaMetrics | Zabbix |
| :--- | :--- | :--- | :--- | :--- |
| **Роль** | Сервер / Агент | Универсальный коллектор | TSDB / Стек | Мониторинг "все в одном" |
| **Модель сбора** | Pull / OTLP Push | Pull / Push / Logs / Traces | Pull / Push (vmagent) | Гибридная (Agent/SNMP) |
| **Масштабирование** | Remote Write | Горизонтальное (Collector) | Нативное (Cluster) | Прокси / БД кластер |
| **Хранение** | TSDB (локально) | Нет (Forwarding) | TSDB (High density) | SQL / NoSQL |

## Дополнительная информация

### Управление хранением и Retention

| Метод | Команда / Настройка | Примечание |
| :--- | :--- | :--- |
| По времени | `--storage.tsdb.retention.time=30d` | Удаляет данные старше 30 дней |
| По объёму | `--storage.tsdb.retention.size=100GB` | Удаляет данные при превышении 100 ГБ |
| Комбинированный | Оба параметра одновременно | Удаление по первому наступившему условию |

### Пример правила алертинга

```yaml
groups:
  - name: host_alerts
    rules:
      - alert: HostHighCpuLoad
        expr: 100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая нагрузка на CPU ({{ $labels.instance }})"
          description: "CPU usage > 80% на {{ $labels.instance }} в течение 5 минут."
```

Подробнее о синтаксисе и типах правил — в **[Правила алертинга](./rules.md)**. О доставке оповещений — в **[Alertmanager](./alertmanager.md)**.

### Лучшие практики

*   **Запуск от непривилегированного пользователя:** Создавайте отдельного пользователя `prometheus` без прав входа и домашней директории.
*   **Hardening:** Используйте systemd-директивы `NoNewPrivileges=true`, `ProtectSystem=full`, `ProtectHome=true`, `PrivateTmp=true`.
*   **Scrape interval:** Устанавливайте `scrape_interval` не менее 15 секунд для снижения нагрузки на ядро и сеть.
*   **GOMEMLIMIT:** В контейнеризированных средах установите `GOMEMLIMIT` на 10–20% ниже `limits.memory`.
*   **Валидация:** Всегда проверяйте конфигурацию через `promtool check config` перед перезагрузкой.
*   **Мониторинг мониторинга:** Настройте алерты на `up{job="prometheus"} == 0` и на ключевые метрики TSDB.

### Ограничения и граничные случаи

*   **Локальная TSDB не распределена:** Single-instance Prometheus не подходит для кластеров с >500k active series. Используйте [Remote Write](./scaling/remote_read_write.md) или [Federation](./scaling/federation.md).
*   **Задержка данных:** Prometheus не предназначен для высокоточной передачи данных с задержкой менее секунды. Для real-time сценариев используйте Pushgateway или OTLP.
*   **Дублирование данных в HA:** При запуске двух экземпляров Prometheus Grafana видит дубликаты рядов, если не настроен внешний слой дедупликации.
*   **WAL и сбои питания:** При аварийном отключении питания Prometheus восстанавливает Head Block из WAL, но данные, не записанные в блоки, могут быть потеряны. Используйте UPS для критичных серверов.

## Four Golden Signals (Четыре золотых сигнала)

Полное описание методологии Four Golden Signals (Latency, Traffic, Errors, Saturation), процентилей, PromQL-запросов, правил алертинга и дашбордов см. в **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md#3-four-golden-signals-sre-базис-google)** — SSoT для USE/RED/Golden Signals.

## См. также

*   [Конфигурация prometheus.yml](./configuration.md)
*   [Установка Prometheus Server](./installation/prometheus_server_installation.md)
*   [Обзор масштабирования](./scaling/overview.md)
*   [Устранение неполадок](./troubleshooting.md)
*   [Сетевая безопасность](./security_network.md)
*   [Alertmanager](./alertmanager.md) — доставка оповещений по золотым сигналам
*   [VictoriaMetrics](./../VictoriaMetrics/overview.md) — long-term storage для исторических процентилей
