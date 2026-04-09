# Pushgateway

Компонент-посредник в экосистеме [Prometheus](./overview.md) для приёма метрик от короткоживущих задач.

## Definitions

| Термин | Описание |
|---|---|
| **Pushgateway** | Приёмник метрик для ephemeral/batch-задач, которые завершаются до очередного scrape |
| **Группировка** | Механизм изоляции метрик по комбинации `job` + кастомные лейблы из URL |
| **Порт** | `9091` |
| **Репозиторий** | [prometheus/pushgateway](https://github.com/prometheus/pushgateway) |

> **Установка:** [Pushgateway Installation](./installation/pushgateway_installation.md).

## Basic Concepts

### Принцип работы

Pushgateway решает проблему pull-модели для задач, которые не могут быть опрошены:

| Шаг | Действие |
|---|---|
| 1 | Короткоживущая задача завершает работу и **push** отправляет метрики в Pushgateway |
| 2 | Prometheus по расписанию **pull** опрашивает Pushgateway и забирает сохранённые метрики |

Подробно: [Scrape-модель](./overview.md#scrape-модель), [Стратегии сбора метрик](../Concepts/Observability_and_Monitoring/metrics_collection_strategies.md).

### Когда использовать

**Единственный легитимный сценарий** — сбор метрик от сервисов, которые **не могут быть опрошены**:
- Batch-задачи (cron jobs), выполняющиеся реже интервала скрейпинга
- Эфемерные задачи, недоступные для scrape
- Сервисы за firewall

### Анти-паттеры

Использование Pushgateway для перевода Prometheus на push-модель — архитектурная ошибка.

| Проблема | Описание |
|---|---|
| **Потеря метрики `up`** | Prometheus показывает `up=1` для Pushgateway, но это не отражает состояние исходной задачи |
| **Единая точка отказа** | Сбой Pushgateway = потеря метрик всех задач |
| **«Вечное» хранение** | Метрики не удаляются автоматически после сбора — устаревшие данные продолжают собираться |
| **Сложная группировка** | Клиенты сами управляют лейблами (особенно `instance`), что усложняет конфигурацию |

**Правило:** если сервис можно опросить — его нужно опрашивать. Pushgateway — только для короткоживущих задач.

### Группировка метрик

Ключ группировки — метка `job` + кастомные лейблы из URL.

| URL | Группа |
|---|---|
| `/metrics/job/backup/instance/db1` | `job="backup", instance="db1"` |
| `/metrics/job/backup/instance/db2` | `job="backup", instance="db2"` |

Спецсимволы в значениях лейблов кодируются в **base64** с суффиксом `@base64`:

```
/metrics/job/my_job/path@base64/L3Zhci9sb2c=
```

### HTTP API

| Метод | Поведение |
|---|---|
| `POST` | Добавляет/обновляет метрики в группе. Существующие метрики, не переданные в запросе, сохраняются |
| `PUT` | Полностью заменяет все метрики в группе. `PUT` с пустым телом = удаление группы |
| `DELETE` | Удаляет всю группу метрик по URL |

### Управление жизненным циклом метрик

Pushgateway не удаляет метрики автоматически. Задача должна удалять свои метрики перед завершением:

```bash
curl -X DELETE http://localhost:9091/metrics/job/my_batch_job/instance/server1
```

Подробнее: [Pushgateway Installation — API](./installation/pushgateway_installation.md#api-pushgateway).

## Practical Scenarios

### Отправка метрик от batch-задачи

```bash
cat <<EOF | curl --data-binary @- http://localhost:9091/metrics/job/backup/instance/db-server
# HELP backup_duration_seconds Duration of backup job
# TYPE backup_duration_seconds gauge
backup_duration_seconds 34.4
# HELP backup_status Status of backup (1=success, 0=failure)
# TYPE backup_status gauge
backup_status 1
EOF
```

`job/backup` и `instance/db-server` станут метками `job="backup"`, `instance="db-server"`.

### Настройка Prometheus

```yaml
scrape_configs:
  - job_name: 'pushgateway'
    honor_labels: true  # Сохраняет лейблы job/instance, установленные клиентом
    static_configs:
      - targets: ['localhost:9091']
```

> **Конфигурация в Kubernetes:** [Kube-Prometheus-Stack Components](./kubernetes/Kube_Prometheus_Stack_Helm/other_components_config.md).

## Additional Information

### Альтернативы для сбора метрик

| Решение | Подход | Сценарий |
|---|---|---|
| Pushgateway | Промежуточное хранилище | Cronjobs, batch-задачи |
| [Telegraf](../Concepts/Observability_and_Monitoring/metrics_collection_strategies.md) | Универсальный конвертер/агрегатор | Множество источников, фильтрация |
| [StatsD Exporter](./Exporters/other_exporters.md) | Конвертер StatsD → Prometheus | Приложения, уже использующие StatsD |

### Параметры запуска

Полный список: [Pushgateway Installation — параметры запуска](./installation/pushgateway_installation.md#параметры-запуска).

Ключевые:

| Флаг | По умолчанию | Описание |
|---|---|---|
| `--web.listen-address` | `:9091` | Адрес и порт |
| `--persistence.file` | `-` | Файл для сохранения метрик между перезапусками |
| `--persistence.interval` | `5m` | Интервал сохранения |
| `--web.enable-admin-api` | `false` | Включить admin API (очистка всех метрик) |

### Связанные темы

- [Scrape-модель](./overview.md#scrape-модель) — альтернативные способы скрапинга
- [Observability Definitions](../Concepts/Observability_and_Monitoring/observability_definitions.md) — концепция наблюдаемости
- [Масштабирование](./scaling/overview.md) — проектирование мониторинга в распределённых системах
