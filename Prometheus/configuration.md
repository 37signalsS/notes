# Конфигурация Prometheus

## Определения

**Конфигурация Prometheus** — совокупность параметров, определяющих поведение сервера при сборе, хранении и обработке метрик, а также при взаимодействии с внешними системами. Настройка осуществляется двумя способами:

1. **`prometheus.yml`** — основной конфигурационный файл в формате YAML. Определяет задания сбора (scrape jobs), правила (rules), интеграцию с Alertmanager и удалёнными хранилищами (LTS).
2. **CLI-флаги** — параметры командной строки при запуске исполняемого файла. Определяют настройки TSDB (путь, время хранения), параметры веб-интерфейса, ограничения ресурсов и уровни логирования.

> **См. также:** [Обзор Prometheus](./overview.md), [TSDB](./concepts/tsdb.md), [Alertmanager](./alertmanager.md)

## Основные концепции

### Структура файла prometheus.yml

```yaml
global:
  scrape_interval: 1m
  evaluation_interval: 1m
  external_labels:
    monitor: 'my-prometheus'

rule_files:
  - 'rules/*.rules.yml'

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

alerting:
  alertmanagers:
  - static_configs:
      - targets: ['localhost:9093']

remote_write:
  - url: "http://remote-storage.example.com/write"

remote_read:
  - url: "http://remote-storage.example.com/read"
```

| Блок | Назначение |
|---|---|
| `global` | Глобальные параметры по умолчанию: `scrape_interval` (интервал опроса), `evaluation_interval` (интервал вычисления правил), `external_labels` (метки для внешних систем) |
| `rule_files` | Пути к файлам с [правилами записи и алертинга](./rules.md). Поддерживаются glob-шаблоны |
| `scrape_configs` | Конфигурация заданий (jobs) для сбора метрик. Включает статические цели и механизмы [Service Discovery и Relabeling](./service_discovery_and_relabeling.md) |
| `alerting` | Настройки взаимодействия с [Alertmanager](./alertmanager.md) для отправки оповещений |
| `remote_write` / `remote_read` | Интеграция с системами долгосрочного хранения (LTS), такими как [Mimir](../Mimir/mimir_overview.md) или [VictoriaMetrics](../VictoriaMetrics/overview.md). Подробнее: [Remote Read/Write](./scaling/remote_read_write.md) |

### Флаги запуска (CLI-флаги)

Параметры запуска процесса Prometheus. Изменения требуют перезапуска сервиса.

| Флаг | По умолчанию | Описание |
|---|---|---|
| `--config.file` | `prometheus.yml` | Путь к основному файлу конфигурации |
| `--web.listen-address` | `0.0.0.0:9090` | Адрес и порт веб-интерфейса и [API](./prometheus_api.md) |
| `--storage.tsdb.path` | `data/` | Директория для хранения данных [TSDB](./concepts/tsdb.md) |
| `--storage.tsdb.retention.time` | `15d` | Срок хранения данных в TSDB (например, `30d`, `2y`) |
| `--storage.tsdb.retention.size` | `0B` | Максимальный размер хранилища (например, `50GB`). 0B — без ограничений |
| `--query.timeout` | `2m` | Максимальное время выполнения PromQL-запроса |
| `--query.max-concurrency` | `20` | Максимальное количество одновременно выполняемых запросов |
| `--log.level` | `info` | Уровень детализации логов (`debug`, `info`, `warn`, `error`) |

> **Примечание:** Расширенные параметры настройки блоков и WAL см. в разделе [Внутреннее устройство TSDB](./concepts/tsdb.md#настройка-retention-period).

## Практические сценарии

### Базовая настройка сбора метрик

Пример конфигурации для сбора метрик с самого Prometheus и системного экспортера:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "node_exporter"
    static_configs:
      - targets: ["localhost:9100"]
```

> **См. также:** [Автоматизация мониторинга большого количества ВМ](./service_discovery_and_relabeling.md#автоматизация-мониторинга-большого-количества-вм-100-в-день) через Service Discovery.

### Управление хранением данных (Retention)

Параметры Retention определяют, как долго и в каком объеме хранятся данные на диске.

| Параметр | По умолчанию | Описание |
|---|---|---|
| `--storage.tsdb.retention.time` | `15d` | Удаление данных старше указанного срока |
| `--storage.tsdb.retention.size` | `0B` | Удаление старых данных при достижении указанного объема TSDB |

**Примеры настройки:**

| Метод | Пример |
|---|---|
| Командная строка | `prometheus --storage.tsdb.retention.time=30d` |
| Docker Compose | `command: ['--storage.tsdb.retention.time=7d', '--storage.tsdb.retention.size=10GB']` |
| Среды разработки/CI | Короткий retention (`12h`–`24h`) для экономии ресурсов |

**Проверка текущих настроек:** в веб-интерфейсе **Status → Command-Line Flags**.

### Параметры блока scrape_configs

Индивидуальная настройка заданий сбора:

| Параметр | Назначение |
|---|---|
| `scrape_interval` | Интервал опроса целей этого задания (переопределяет `global.scrape_interval`) |
| `scrape_timeout` | Таймаут ожидания ответа (должен быть меньше `scrape_interval`) |
| `metrics_path` | Путь к эндпоинту с метриками (по умолчанию `/metrics`) |
| `scheme` | Протокол взаимодействия (`http` или `https`) |
| `honor_labels` | `true` — сохранять метки из приложения при конфликте с метками Prometheus |
| `relabel_configs` | Модификация меток **до** выполнения сбора. См. [Relabeling](./service_discovery_and_relabeling.md) |
| `metric_relabel_configs` | Модификация меток **после** выполнения сбора (перед записью в TSDB) |

### Лимиты сбора (Scrape Limits)

Лимиты предотвращают взрыв кардинальности и перегрузку Prometheus при аномальном поведении таргетов. Указываются в `scrape_config`:

```yaml
scrape_configs:
  - job_name: "some-service"
    sample_limit: 5000         # Лимит уникальных временных рядов с одного таргета
    target_limit: 100          # Лимит таргетов для этой job
    label_limit: 30            # Лимит лейблов на одну метрику
    label_name_length_limit: 200   # Максимальная длина имени лейбла
    label_value_length_limit: 400  # Максимальная длина значения лейбла
```

| Параметр | По умолчанию | Описание |
|---|---|---|
| `sample_limit` | `0` (нет лимита) | Если после `metric_relabel_configs` осталось больше рядов, все метрики этого таргета отбрасываются. Защита от взрыва кардинальности |
| `target_limit` | `0` (нет лимита) | Максимальное количество таргетов для job. Если SD возвращает больше, лишние игнорируются |
| `label_limit` | `0` (нет лимита) | Максимум лейблов (включая `__name__`) на одну метрику |
| `label_name_length_limit` | `0` (нет лимита) | Максимальная длина строки имени лейбла |
| `label_value_length_limit` | `0` (нет лимита) | Максимальная длина строки значения лейбла |

**Рекомендации:**

- `sample_limit` — **обязателен** для любых job, чьи таргеты не находятся под вашим контролем (сторонние экспортеры, SaaS).
- `sample_limit` применяется **после** `metric_relabel_configs`, поэтому в комбинации с фильтрацией ненужных метрик он защищает только от неожиданных «взрывов» кардинальности.
- `target_limit` критичен в динамических средах (Kubernetes), где Service Discovery может вернуть тысячи таргетов.
- При превышении лимита метрики таргета не сохраняются, что отслеживается через `prometheus_target_scrapes_exceeded_sample_limit_total`.
- Комбинация `sample_limit` + `target_limit` задаёт верхнюю границу потребления памяти Prometheus.

## Дополнительная информация

### Валидация конфигурации

Используйте утилиту `promtool` для проверки синтаксиса перед применением настроек:

```bash
# Проверка основного файла
promtool check config /etc/prometheus/prometheus.yml

# Проверка файлов правил
promtool check rules /etc/prometheus/rules.yml
```

Подробнее: [promtool и лучшие практики](./promtool_and_best_practices.md)

### Перезагрузка без остановки (Hot Reload)

Prometheus поддерживает обновление конфигурации (кроме CLI-флагов) без перезапуска процесса.

**Способы перезагрузки:**

1. **Сигналы ОС (systemd):**

   ```bash
   sudo systemctl reload prometheus
   ```

2. **HTTP API:**
   Требуется запуск с флагом `--web.enable-lifecycle`.

   ```bash
   curl -X POST http://localhost:9090/-/reload
   ```

«Горячая» перезагрузка позволяет избежать пропусков в сборе метрик (scrape gaps) при изменении конфигурации.
