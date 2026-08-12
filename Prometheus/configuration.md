# Конфигурация Prometheus

## Определения

**Конфигурация Prometheus** — совокупность параметров, определяющих поведение сервера при сборе, хранении и обработке метрик, а также при взаимодействии с внешними системами. Начиная с версии **Prometheus v3.x**, конфигурация была значительно упрощена за счёт стабилизации экспериментальных функций и добавления механизмов автоматического управления ресурсами.

Настройка осуществляется двумя способами:

1. **`prometheus.yml`** — основной конфигурационный файл в формате YAML. Определяет задания сбора (scrape jobs), правила (rules), интеграцию с Alertmanager и удалёнными хранилищами (Remote Write/Read).
2. **CLI-флаги** — параметры командной строки при запуске. Определяют настройки TSDB, параметры веб-интерфейса, режимы работы (Server/Agent) и ограничения ресурсов.

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

### Флаги запуска (CLI-флаги)

В Prometheus v3 многие флаги функций (`--enable-feature`) стали параметрами по умолчанию или выделенными флагами.

| Флаг | По умолчанию | Описание |
|---|---|---|
| `--config.file` | `prometheus.yml` | Путь к файлу конфигурации |
| `--agent` | `false` | Запуск в [режиме агента](#режим-агента-agent-mode) (без локальной TSDB и правил) |
| `--web.enable-remote-write-receiver` | `false` | Позволяет Prometheus принимать данные от других серверов по Remote Write |
| `--web.enable-otlp-receiver` | `false` | Включает прием метрик по протоколу OpenTelemetry (OTLP) |
| `--storage.tsdb.retention.time` | `15d` | Срок хранения данных в TSDB |
| `--storage.tsdb.retention.size` | `0B` | Максимальный размер TSDB (например, `50GB`) |
| `--auto-gomemlimit` | `true` | (v3+) Автоматическая настройка лимита памяти на основе контейнерных лимитов |
| `--auto-gomaxprocs` | `true` | (v3+) Автоматическая настройка CPU потоков |
| `--log.level` | `info` | Уровень логирования (`debug`, `info`, `warn`, `error`) |

### Управление функциями (Feature Flags)

Развитие Prometheus v3.x направлено на стабилизацию функций.
*   **Включено по умолчанию:** Поддержка UTF-8 в именах метрик и меток.
*   **Стабилизировано (больше не требует `--enable-feature` в новых релизах v3.x):** `native-histograms` (включается через конфиг скрейпинга) и `out-of-order-window` (настраивается в блоке `tsdb`).

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
