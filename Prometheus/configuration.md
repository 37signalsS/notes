# Конфигурация Prometheus

## Определения

**Конфигурация Prometheus** — это набор инструкций, определяющих, как [Prometheus](./overview.md) собирает, хранит и обрабатывает метрики, а также как управляет оповещениями. Она состоит из двух основных частей:

1. **Конфигурационный файл `prometheus.yml`**: Основной файл в формате YAML, описывающий цели для сбора метрик, пути к файлам с правилами и интеграции с внешними системами.
2. **Флаги запуска (Command-line flags)**: Параметры командной строки, которые управляют поведением самого процесса Prometheus, например, путем к хранилищу данных ([TSDB](./concepts/tsdb.md)) и его настройками.

## Основные концепции

### Структура `prometheus.yml`

Основной конфигурационный файл имеет иерархическую структуру в формате YAML.

```yaml
# Глобальные настройки, применяемые ко всем, если не переопределены.
global:
  scrape_interval: 1m
  evaluation_interval: 1m
  external_labels:
    monitor: 'my-prometheus'

# Пути к файлам с правилами. Поддерживаются glob-паттерны.
rule_files:
  - 'rules/*.rules.yml'

# Конфигурация для обнаружения и сбора метрик.
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

# Настройки для взаимодействия с Alertmanager.
alerting:
  alertmanagers:
  - static_configs:
      - targets: ['localhost:9093']

# Настройки для отправки данных во внешние LTS.
remote_write:
  - url: "http://remote-storage.example.com/write"

# Настройки для чтения данных из внешних LTS.
remote_read:
  - url: "http://remote-storage.example.com/read"
```

* `global`: Глобальные параметры (`scrape_interval`, `evaluation_interval`).
* `rule_files`: Список файлов с [правилами записи и алертинга](./rules.md).
* `scrape_configs`: "Сердце" конфигурации. Здесь настраиваются "задания" (jobs) по сбору метрик, включая [Service Discovery и Relabeling](./service_discovery_and_relabeling.md).
* `alerting`: Настройки для отправки алертов в [Alertmanager](./alertmanager.md).
* `remote_write` / `remote_read`: Конфигурация для интеграции с долгосрочными хранилищами (LTS), такими как [Mimir](../Mimir/mimir_overview.md) или [VictoriaMetrics](../VictoriaMetrics/overview.md). Подробнее см. в [Remote Read/Write](./scaling/remote_read_write.md).

### Флаги запуска

Наиболее важные флаги, передаваемые процессу Prometheus при старте.

| Флаг | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `--config.file` | `prometheus.yml` | Путь к конфигурационному файлу. |
| `--web.listen-address` | `0.0.0.0:9090` | Адрес и порт для UI и [API](./prometheus_api.md). |
| `--storage.tsdb.path` | `data/` | Путь к каталогу для хранения [TSDB](./concepts/tsdb.md). |
| `--storage.tsdb.retention.time` | `15d` | Срок хранения данных (например, `30d`, `2y`). |
| `--storage.tsdb.retention.size`| `0B` | Максимальный размер хранилища (например, `50GB`). |
| `--query.timeout` | `2m` | Максимальное время выполнения [PromQL](./concepts/promql.md)-запроса. |
| `--query.max-concurrency` | `20` | Максимальное количество одновременных запросов. |
| `--log.level` | `info` | Уровень логирования (`debug`, `info`, `warn`, `error`). |

## Практические сценарии

### Пример базовой конфигурации

Этот `prometheus.yml` настраивает Prometheus на сбор метрик с самого себя и с `node_exporter`.

```yaml
global:
  scrape_interval: 15s # Собирать метрики каждые 15 секунд по умолчанию

scrape_configs:
  # Задание для сбора метрик с самого Prometheus
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  # Задание для сбора метрик с node_exporter
  - job_name: "node_exporter"
    static_configs:
      - targets: ["localhost:9100"]
```

### Управление хранением данных (Retention)

Срок хранения данных (retention) в Prometheus — это ключевой параметр, влияющий на использование дискового пространства и производительность. Он управляется флагом `--storage.tsdb.retention.time`.

* **Значение по умолчанию**: `15d` (15 дней).

#### Способы настройки

1. **CLI-параметр**: Указывается при запуске процесса Prometheus.

    ```bash
    prometheus --storage.tsdb.retention.time=30d
    ```

2. **Конфигурация в Docker/CI/CD**: Параметр передается в `command` контейнера.

    ```yaml
    # Пример для Docker Compose
    services:
      prometheus:
        image: prom/prometheus
        command:
          - '--storage.tsdb.retention.time=7d' # 7 дней (168 часов)
          - '--storage.tsdb.retention.size=10GB' # Опционально: ограничение по размеру
    ```

    Для CI/CD-пайплайнов, где актуальность данных важнее долгосрочного хранения, часто устанавливают короткие периоды (например, `12h` или `24h`).

#### Важность настройки

* **Оптимизация дискового пространства**: Большие периоды хранения требуют значительного объема диска.
* **Производительность запросов**: Длительное хранение может замедлять выполнение PromQL-запросов, особенно при работе с большими временными диапазонами.

#### Проверка текущего значения

Текущее значение параметра `--storage.tsdb.retention.time` можно проверить в веб-интерфейсе Prometheus:

1. Перейдите в раздел **Status → Command-Line Flags**.
2. Найдите в списке флаг `storage.tsdb.retention.time`.

### Важные параметры `scrape_configs`

Каждое задание в `scrape_configs` может иметь множество параметров для тонкой настройки.

| Параметр | Назначение |
| :--- | :--- |
| `scrape_interval` | Частота опроса цели (переопределяет глобальное значение). |
| `scrape_timeout` | Таймаут HTTP-запроса; должен быть меньше `scrape_interval`. |
| `metrics_path` | Путь к эндпоинту метрик (по умолчанию `/metrics`). |
| `scheme` | Протокол `http` или `https`. |
| `honor_labels` | `true`: сохранять метки из цели при конфликте с внешними. |
| `relabel_configs` | Правила для модификации меток **до** сбора метрик. См. [Service Discovery и Relabeling](./service_discovery_and_relabeling.md). |
| `metric_relabel_configs` | Правила для модификации меток **после** сбора метрик. |

## Дополнительная информация

### Проверка конфигурации

Перед применением изменений всегда проверяйте корректность синтаксиса конфигурационного файла и файлов с правилами с помощью утилиты `promtool`. Это помогает избежать ошибок, которые могут остановить сбор метрик.

* **Проверка основного конфига:**

    ```bash
    promtool check config /path/to/prometheus.yml
    ```

* **Проверка файлов с правилами:**

    ```bash
    promtool check rules /path/to/rules.yml
    ```

Подробнее об этом и других возможностях `promtool` см. в заметке [promtool и лучшие практики](./promtool_and_best_practices.md).

### Перезагрузка конфигурации

Для применения изменений в `prometheus.yml` не обязательно перезапускать сервис. Можно отправить сигнал `SIGHUP` или выполнить команду:

```bash
# Для systemd
sudo systemctl reload prometheus

# С помощью curl
curl -X POST http://localhost:9090/-/reload
```

Это вызовет "горячую" перезагрузку конфигурации без прерывания сбора метрик.
