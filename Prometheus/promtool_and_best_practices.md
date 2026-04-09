# Prometheus: promtool и лучшие практики

Утилита `promtool` и ключевые практики эксплуатации [Prometheus](./overview.md).

## Definitions

| Термин | Описание |
|---|---|
| **`promtool`** | CLI-утилита для статической проверки конфигурации, правил и метрик Prometheus |
| **Кардинальность** | Количество уникальных временных рядов. Критический фактор потребления ресурсов. Подробности: [Labels & Cardinality](./concepts/labels_and_cardinality.md) |
| **Долгосрочное хранение (LTS)** | Сохранение метрик за пределами локальной TSDB. Подробности: [Remote Read/Write](./scaling/remote_read_write.md), [Scaling](./scaling/overview.md) |

## Basic Concepts

### Валидация конфигурации

Ошибки в конфигурации/правилах останавливают сбор метрик. Статическая проверка через `promtool` — обязательный шаг перед применением изменений.

### Управление ресурсами

Prometheus требователен к CPU и RAM. В контейнеризированных средах всегда задавать явные `requests`/`limits`. Подробности: [QoS, Limits, Requests](../Kubernetes/Scheduling/qos_limit_and_requests.md).

### Контроль кардинальности

Высокая кардинальность — главная причина деградации производительности.

**Запрещено** в лейблах:
- ID пользователей, email, хэши запросов
- URL с динамическими сегментами (`/api/users/12345`)

**Рекомендовано:**
- Шаблонизация URL (`/api/users/:id`) на этапе [relabeling](./service_discovery_and_relabeling.md)
- Мониторинг churn rate через `promtool tsdb analyze`

### Отказоустойчивость и LTS

Локальная [TSDB](./concepts/tsdb.md) не предназначена для долгосрочного хранения и не кластеризуется. Для production — внешние хранилища через `remote_write`.

## Practical Scenarios

### Проверка конфигурации

```bash
promtool check config /etc/prometheus/prometheus.yml
```

### Проверка файлов с правилами

```bash
promtool check rules /etc/prometheus/rules/*.yml
```

### Валидация метрик экспортеров

Проверка метрик на соответствие стандартам Prometheus (разработка кастомных экспортеров):

```bash
curl -s http://localhost:9100/metrics | promtool check metrics
```

### Анализ TSDB

Поиск метрик с высокой кардинальностью:

```bash
promtool tsdb analyze /path/to/tsdb/data
promtool tsdb analyze --block-id <block-id> /path/to/tsdb/data
```

### Дамп данных TSDB

```bash
promtool tsdb dump /path/to/tsdb/data
```

### Управление конфигурацией через GitOps

Хранить `prometheus.yml`, `*.rules.yml` в Git, использовать [GitOps](../GitOps/GitOps_overview.md) для развёртывания.

### Лимиты ресурсов в Kubernetes

```yaml
resources:
  requests:
    memory: "2Gi"
    cpu: "500m"
  limits:
    memory: "4Gi"
    cpu: "1"
```

### Версионирование образов

Не использовать `latest`. Закреплять конкретную версию:

```
image: prom/prometheus:v3.10.0
```

### Настройка Remote Write для LTS

Отправка метрик во внешнее хранилище через секцию `remote_write`.

Подробно: [Remote Read/Write](./scaling/remote_read_write.md), [Scaling](./scaling/overview.md).

## Additional Information

### Сводка команд promtool

| Команда | Описание |
|---|---|
| `promtool check config <file>` | Валидация конфигурации |
| `promtool check rules <file>` | Валидация файлов правил |
| `promtool check metrics` | Валидация метрик (stdin) |
| `promtool tsdb analyze <path>` | Анализ блоков TSDB |
| `promtool tsdb dump <path>` | Дамп данных TSDB |

### Решения для долгосрочного хранения

| Решение | Подход | Особенности |
|---|---|---|
| [VictoriaMetrics](../VictoriaMetrics/overview.md) | `remote_write` | Высокая производительность, простота |
| [Thanos](./scaling/thanos_overview.md) | Sidecar + S3 | Интеграция с объектными хранилищами |
| [Grafana Mimir](../Mimir/mimir_overview.md) | `remote_write` | Горизонтальное масштабирование |

Подробное сравнение: [Scaling Overview](./scaling/overview.md#решения-для-долгосрочного-хранения-long-term-storage).
