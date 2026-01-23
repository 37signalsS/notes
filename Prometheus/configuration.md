# Конфигурация Prometheus

## 1. Базовые концепции и структура `prometheus.yml`

Основной конфигурационный файл Prometheus имеет формат YAML. Путь к нему задается через флаг `--config.file`, а его корректность можно проверить с помощью утилиты [[./promtool_and_best_practices.md|promtool]]. В файле не допускаются символы табуляции, только пробелы.

### Структура файла

```yaml
# Глобальные настройки.
global:
  # Как часто собирать метрики с таргетов по умолчанию. Основа pull-модели, подробнее в [[./overview.md|обзоре Prometheus]].
  [ scrape_interval: <duration> | default = 1m ]

  # Таймаут для одного скрейп-запроса по умолчанию.
  [ scrape_timeout: <duration> | default = 10s ]

  # Как часто вычислять [[./rules.md|правила (rules)]].
  [ evaluation_interval: <duration> | default = 1m ]

  # Внешние метки, которые добавляются ко всем временным рядам.
  external_labels:
    [ <labelname>: <labelvalue> ... ]

# Список файлов с [[./rules.md|правилами записи (recording) и алертинга (alerting)]].
# Поддерживает glob-паттерны.
rule_files:
  [ - <filepath_glob> ... ]

# Конфигурация для обнаружения и сбора метрик (scrape).
# Здесь настраивается [[./service_discovery_and_relabeling.md|Service Discovery и Relabeling]].
scrape_configs:
  [ - <scrape_config> ... ]

# Настройки для взаимодействия с [[./alertmanager.md|Alertmanager]].
alerting:
  alert_relabel_configs:
    [ - <relabel_config> ... ]
  alertmanagers:
    [ - <alertmanager_config> ... ]

# Настройки для отправки данных во внешние хранилища (LTS).
# Подробнее см. в [[./scaling/remote_read_write.md|Prometheus Remote Read/Write]].
remote_write:
  [ - <remote_write> ... ]

# Настройки для чтения данных из внешних хранилищ.
# Подробнее см. в [[./scaling/remote_read_write.md|Prometheus Remote Read/Write]].
remote_read:
  [ - <remote_read> ... ]
```

**Ключевые секции, которые нужно запомнить:**

*   `scrape_interval`: Как часто Prometheus опрашивает источники данных.
*   `scrape_configs`: Список источников данных (таргетов) и правила их обнаружения.
*   `rule_files`: Пути к файлам с правилами алертинга.

## Ключи (флаги) запуска Prometheus

Ниже приведен список наиболее часто используемых флагов командной строки. Полный список можно получить с помощью команды `prometheus --help`. Их значения также можно посмотреть через [[./prometheus_api.md|HTTP API]].

| Флаг | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `--config.file` | `prometheus.yml` | Путь к конфигурационному файлу. Рекомендуется проверять с помощью `promtool check config` (см. [[./promtool_and_best_practices.md|утилита promtool]]). |
| `--web.listen-address` | `0.0.0.0:9090` | Адрес и порт, по которому доступны UI, [[./prometheus_api.md|API]] и метрики самого Prometheus. |
| `--web.read-timeout` | `5m` | Максимальное время ожидания для запросов и неактивных соединений. |
| `--storage.tsdb.path` | `data/` | Путь к каталогу для хранения [[./concepts/tsdb.md|базы данных временных рядов (TSDB)]]. |
| `--storage.tsdb.retention.time` | `15d` | Как долго хранить данные метрик (по умолчанию 15 дней). |
| `--storage.tsdb.retention.size`| `0B` | **[Экспериментальный]** Максимальный размер хранилища метрик (например, `50GB`). При превышении старые данные удаляются. |
| `--rules.alert.for-outage-tolerance` | `1h` | Максимальное время, в течение которого Prometheus может быть недоступен, чтобы состояние `for` для алерта было восстановлено. |
| `--rules.alert.for-grace-period`| `10m` | Минимальный период для восстановления состояния алерта. |
| `--rules.alert.resend-delay` | `1m` | Минимальная задержка перед повторной отправкой уведомлений в [[./alertmanager.md|Alertmanager]]. |
| `--alertmanager.notification-queue-capacity` | `10000` | Размер очереди уведомлений, ожидающих отправки в [[./alertmanager.md|Alertmanager]]. |
| `--alertmanager.timeout` | `10s` | Таймаут для запросов к [[./alertmanager.md|Alertmanager]]. |
| `--query.timeout` | `2m` | Максимальное время выполнения [[./concepts/promql.md|PromQL]]-запроса. |
| `--query.max-concurrency` | `20` | Максимальное количество одновременно выполняющихся запросов. |
| `--log.level` | `info` | Уровень логирования (`debug`, `info`, `warn`, `error`). |
| `--log.format` | `logfmt` | Формат логов (`logfmt` или `json`). |
