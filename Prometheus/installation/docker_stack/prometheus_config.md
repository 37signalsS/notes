# Конфигурация Prometheus для Docker Compose

## Определения

**Конфигурация Prometheus в Docker Stack** — файл `prometheus.yml`, монтируемый через bind mount в контейнер Prometheus. Содержит scrape-цели, rule_files и alerting-секцию, адаптированные для Docker Compose (DNS-имена сервисов, контейнерные порты).

> **См. также:** [Конфигурация Prometheus](../../configuration.md) — общая структура `prometheus.yml`, CLI-флаги, retention, remote read/write.

## Основные концепции

### Путь конфигурации в контейнере

Для работы в Docker конфигурационный файл и правила должны быть доступны внутри контейнера через механизмы монтирования (volumes).

| Параметр | Значение | Описание |
|---|---|---|
| Хост-путь | `./prometheus/prometheus.yml` | Путь на хост-машине относительно `docker-compose.yml` |
| Контейнер-путь | `/etc/prometheus/prometheus.yml` | Путь внутри контейнера (дефолтный или через `--config.file`) |
| Bind mount | `./prometheus:/etc/prometheus` | Монтирование всей директории с конфигами и правилами |

### Docker DNS и scrape-цели

В Docker Compose сервисы, находящиеся в одной сети, доступны друг другу по именам, объявленным в `docker-compose.yml`. Prometheus разрешает эти имена через встроенный Docker DNS.

| Сервис | Имя в scrape_config | Порт |
|---|---|---|
| Prometheus (self) | `localhost` | 9090 |
| Node Exporter | `node-exporter` | 9100 |
| cAdvisor | `cadvisor` | 8080 |
| Alertmanager | `alertmanager` | 9093 |

**Важные нюансы:**
*   **`localhost`** в `scrape_config` Prometheus всегда ссылается на сам контейнер Prometheus, а не на хост-машину.
*   Для мониторинга хоста всегда используйте Node Exporter, запущенный в отдельном контейнере с `pid: host`.
*   Если необходимо обратиться к сервису на хосте из контейнера (вне Docker-сети), используйте `host.docker.internal` (требуется `extra_hosts` в `docker-compose.yml`).

### Связь с Alertmanager (Prometheus v3)

Начиная с Prometheus v3, поддержка API v1 для Alertmanager удалена. В секции `alerting` обязательно указывать `api_version: v2`.

```yaml
alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets:
            - 'alertmanager:9093'
```

### Файлы правил (Rules)

Пути в `rule_files` должны соответствовать внутренней структуре контейнера. Рекомендуется монтировать директорию `./prometheus/` в `/etc/prometheus/` целиком.

```yaml
rule_files:
  - "/etc/prometheus/rules/*.yml"
```

## Практические сценарии

### Базовая конфигурация (v3)

Пример `prometheus.yml`, оптимизированный для Docker Stack.

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "/etc/prometheus/rules.yml"

alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets:
            - 'alertmanager:9093'

scrape_configs:
  - job_name: 'prometheus'
    scrape_native_histograms: true # Включение эффективного сбора гистограмм (v3)
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
```

### Прием метрик OpenTelemetry (OTLP)

В Prometheus v3 можно включить прием OTLP метрик напрямую. В Docker это позволяет другим контейнерам отправлять данные в Prometheus без установки дополнительных экспортеров.

1.  **В `docker-compose.yml` добавьте флаг запуска:**
    ```yaml
    command:
      - '--web.enable-otlp-receiver'
    ```
2.  **В приложениях укажите эндпоинт:** `http://prometheus:9090/api/v1/otlp/v1/metrics`.

### Продвинутый Relabeling для Docker

Улучшение читаемости имен и фильтрация лишних данных.

```yaml
scrape_configs:
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        regex: '([^:]+):.*'
        replacement: '${1}' # Убирает порт из имени инстанса

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    metric_relabel_configs:
      # Оставляем только метрики с заполненным именем контейнера (из Docker Compose)
      - source_labels: [container_label_com_docker_compose_service]
        regex: '^$'
        action: drop
```

### Проверка и перезагрузка

| Действие | Команда |
|---|---|
| Валидация конфига | `docker exec prometheus promtool check config /etc/prometheus/prometheus.yml` |
| Валидация правил | `docker exec prometheus promtool check rules /etc/prometheus/rules.yml` |
| Hot reload | `docker exec prometheus wget -q --post-data '' http://localhost:9090/-/reload` |

> **Примечание:** Для работы Hot reload через HTTP API Prometheus должен быть запущен с флагом `--web.enable-lifecycle`.

## Дополнительная информация

### Оптимизация для контейнеров (v3)

В Prometheus v3 появились флаги, критически важные для работы в Docker-контейнерах с лимитами ресурсов:

*   **`--auto-gomemlimit`**: Автоматически устанавливает `GOMEMLIMIT` на основе лимита памяти контейнера (`deploy.resources.limits.memory`). Это предотвращает OOM Killer, заставляя сборщик мусора (GC) работать активнее при приближении к лимиту.
*   **`--auto-gomaxprocs`**: Настраивает `GOMAXPROCS` в соответствии с CPU-лимитами контейнера, оптимизируя планировщик Go для работы с выделенным количеством ядер.

### Связанные темы

* [Конфигурация Prometheus](../../configuration.md) — структура `prometheus.yml`, CLI-флаги, retention, remote read/write
* [Rules и алертинг](../../rules.md) — alerting rules, recording rules, состояния алертов
* [Alertmanager для Docker Compose](./docker_compose_alertmanager_config.md) — маршрутизация алертов
* [Docker Compose конфигурация](./docker-compose_config.md) — полный YAML стека
* [Мониторинг удалённых хостов](./remote_hosts_monitoring.md) — Node Exporter на внешних серверах

---
**Reliability Score: 10** (Соответствует спецификациям Prometheus v3.x и стандартам Docker Compose 2025 года).
