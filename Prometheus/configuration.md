# Конфигурация Prometheus

## Определения

**Конфигурация Prometheus** — это набор инструкций, определяющих, как Prometheus собирает, хранит и обрабатывает метрики, а также как управляет оповещениями. Она состоит из двух основных частей:
1.  **Конфигурационный файл `prometheus.yml`**: Основной файл в формате YAML, описывающий цели для сбора метрик, правила алертинга, и интеграции с внешними системами.
2.  **Ключи (флаги) запуска**: Параметры командной строки, которые управляют поведением самого процесса Prometheus, например, путем к хранилищу данных и его настройками.

## Базовые концепции

### Структура файла `prometheus.yml`

Основной конфигурационный файл имеет иерархическую структуру. В файле не допускаются символы табуляции, только пробелы.

```yaml
# Глобальные настройки.
global:
  scrape_interval: 1m
  evaluation_interval: 1m
  external_labels:
    monitor: 'my-prometheus'

# Пути к файлам с правилами записи и алертинга. Поддерживаются glob-паттерны.
rule_files:
  - 'rules/*.rules.yml'

# Конфигурация для обнаружения и сбора метрик (scrape).
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

# Настройки для взаимодействия с Alertmanager.
alerting:
  alertmanagers:
  - static_configs:
      - targets: ['localhost:9093']

# Настройки для отправки данных во внешние хранилища (LTS).
remote_write:
  - url: "http://remote-storage.example.com/write"

# Настройки для чтения данных из внешних хранилищ.
remote_read:
  - url: "http://remote-storage.example.com/read"
```

### Ключевые секции `prometheus.yml`

*   `global`: Глобальные параметры, которые применяются ко всем остальным настройкам, если не переопределены локально.
    *   `scrape_interval`: Как часто собирать метрики с таргетов по умолчанию.
    *   `evaluation_interval`: Как часто вычислять [правила](./rules.md).
    *   `external_labels`: Метки, которые добавляются ко всем временным рядам.
*   `rule_files`: Список файлов с [правилами записи (recording) и алертинга (alerting)](./rules.md).
*   `scrape_configs`: Список "заданий" (jobs) по сбору метрик. Это сердце конфигурации, где настраивается [Service Discovery и Relabeling](./service_discovery_and_relabeling.md).
*   `alerting`: Настройки для взаимодействия с [Alertmanager](./alertmanager.md).
*   `remote_write` / `remote_read`: Конфигурация для интеграции с долгосрочными хранилищами (LTS). Подробнее см. в [Prometheus Remote Read/Write](./scaling/remote_read_write.md).

### Ключи запуска (флаги)

Наиболее часто используемые флаги командной строки. Полный список можно получить с помощью `prometheus --help`.

| Флаг | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `--config.file` | `prometheus.yml` | Путь к конфигурационному файлу. |
| `--web.listen-address` | `0.0.0.0:9090` | Адрес и порт для UI, [API](./prometheus_api.md) и метрик самого Prometheus. |
| `--storage.tsdb.path` | `data/` | Путь к каталогу для хранения [TSDB](./concepts/tsdb.md). |
| `--storage.tsdb.retention.time` | `15d` | Как долго хранить данные метрик (по умолчанию 15 дней). |
| `--storage.tsdb.retention.size`| `0B` | **[Экспер.]** Максимальный размер хранилища (например, `50GB`). |
| `--rules.alert.for-outage-tolerance` | `1h` | Допустимое время простоя Prometheus для восстановления состояния `for`. |
| `--rules.alert.for-grace-period`| `10m` | Минимальный период для восстановления состояния алерта. |
| `--rules.alert.resend-delay` | `1m` | Задержка перед повторной отправкой уведомлений в [Alertmanager](./alertmanager.md). |
| `--alertmanager.notification-queue-capacity` | `10000` | Размер очереди уведомлений для [Alertmanager](./alertmanager.md). |
| `--alertmanager.timeout` | `10s` | Таймаут для запросов к [Alertmanager](./alertmanager.md). |
| `--query.timeout` | `2m` | Максимальное время выполнения [PromQL](./concepts/promql.md)-запроса. |
| `--query.max-concurrency` | `20` | Максимальное количество одновременных запросов. |
| `--log.level` | `info` | Уровень логирования (`debug`, `info`, `warn`, `error`). |

## Практические сценарии

### Пример базовой конфигурации

Этот `prometheus.yml` настраивает Prometheus на сбор метрик с самого себя и с `node_exporter`, запущенного на том же хосте.

```yaml
global:
  scrape_interval: 15s # Собирать метрики каждые 15 секунд

rule_files:
  # - "first.rules"
  # - "second.rules"

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "node_exporter"
    static_configs:
      - targets: ["localhost:9100"]
```
В данном примере:
- Глобальный `scrape_interval` установлен в `15s`.
- Определены два задания (`jobs`): `prometheus` и `node_exporter`.
- Для каждого задания статически (`static_configs`) определена одна цель (`target`) для сбора метрик.

## Дополнительная информация

*   **Проверка конфигурации**: Перед применением изменений всегда проверяйте корректность конфигурационного файла и файлов с правилами с помощью утилиты `promtool`. Это помогает избежать ошибок, которые могут остановить сбор метрик.
    ```bash
    promtool check config /path/to/prometheus.yml
    promtool check rules /path/to/rules.yml
    ```
    Подробнее см. в заметке [promtool и лучшие практики](./promtool_and_best_practices.md).