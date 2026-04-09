# Service Discovery и Relabeling в Prometheus

> Общие концепции. Специфика Kubernetes — в [Service Discovery в Kubernetes](./kubernetes/service_discovery.md).

> **См. также:** [Лейблы и кардинальность](./concepts/labels_and_cardinality.md) — правильное использование лейблов; [Конфигурация Prometheus](./configuration.md) — блок `scrape_configs`.

## Definitions

**Service Discovery (SD)** — механизм автоматического обнаружения целей (targets) для сбора метрик. Prometheus запрашивает у внешних систем (Kubernetes API, [Consul](../Consul/consul_overview.md), файлы, облачные API) актуальный список эндпоинтов вместо ручного перечисления в [конфигурации](./configuration.md).

**Relabeling** — процесс модификации меток цели до и после сбора метрик. Позволяет фильтровать цели, стандартизировать метки, обогащать данные метаданными из SD.

## Basic Concepts

### Жизненный цикл обнаружения и перемаркировки

1. **Обнаружение** — Prometheus обращается к источнику SD (`kubernetes_sd_configs`, `file_sd_configs` и др.).
2. **Метаданные** — источник возвращает список целей с временными метками `__meta_*` (например, `__meta_kubernetes_pod_name`).
3. **`relabel_configs`** — правила модификации меток цели **до** сбора метрик. Решают, будет ли цель опрошена, и формируют её адрес (`__address__`).
4. **Scrape** — Prometheus опрашивает финальный список целей.
5. **`metric_relabel_configs`** — правила модификации меток **после** сбора, но **до** записи в TSDB. Фильтруют временные ряды.

### `relabel_configs` vs `metric_relabel_configs`

| Параметр | `relabel_configs` | `metric_relabel_configs` |
| :--- | :--- | :--- |
| **Когда** | До сбора метрик | После сбора, до записи в TSDB |
| **Что управляет** | Целями (targets) | Метриками (временными рядами) |
| **Типичные задачи** | Фильтрация целей, формирование `__address__`, копирование `__meta_*` → постоянные метки | Удаление лишних метрик, фильтрация временных рядов, управление [кардинальностью](./concepts/labels_and_cardinality.md) |
| **Влияние на производительность** | Минимальное | Дополнительная нагрузка на Prometheus |

### Механизмы Service Discovery

#### `static_configs`

Статическое перечисление целей. Подходит для неизменной инфраструктуры.

```yaml
scrape_configs:
  - job_name: 'node_exporter'
    static_configs:
      - targets: ['192.168.1.10:9100', '192.168.1.11:9100']
        labels:
          env: 'production'
```

#### `file_sd_configs`

Prometheus периодически читает YAML/JSON-файлы со списками целей. Изменения применяются без перезагрузки.

```yaml
scrape_configs:
  - job_name: 'file_sd'
    file_sd_configs:
      - files: ['/etc/prometheus/sd/*.yml']
        refresh_interval: 2m
```

**Файл целей (`/etc/prometheus/sd/hosts.yml`):**

```yaml
- targets:
  - 'server1.example.com:9100'
  - 'server2.example.com:9100'
  labels:
    service: 'backend'
```

#### `consul_sd_configs`

Обнаружение сервисов через Consul API.

```yaml
scrape_configs:
  - job_name: 'consul_services'
    consul_sd_configs:
      - server: 'localhost:8500'
```

#### Другие механизмы

| Механизм | Описание |
| :--- | :--- |
| `kubernetes_sd_configs` | Kubernetes API (pod, service, endpoint, node, ingress). См. [SD в Kubernetes](./kubernetes/service_discovery.md) |
| `ec2_sd_configs` | AWS EC2 API |
| `azure_sd_configs` | Azure API |
| `gce_sd_configs` | Google Compute Engine |
| `dns_sd_configs` | DNS-записи (SRV, A) |
| `http_sd_configs` | HTTP-эндпоинт, возвращающий JSON со списком целей |

### Действия в `relabel_configs`

| Действие | Описание |
| :--- | :--- |
| `keep` | Оставить цели, соответствующие `regex` |
| `drop` | Отбросить цели, соответствующие `regex` |
| `replace` | Заменить/создать метку (`source_labels` → `target_label`) |
| `labelmap` | Копировать метки по regex (часто `__meta_*` → постоянные) |
| `labeldrop` | Удалить метки, имена которых соответствуют `regex` |
| `labelkeep` | Сохранить только метки, имена которых соответствуют `regex` |
| `hashmod` | Хэширование метки с модулем — для шардирования Prometheus |

## Practical Scenarios

### Фильтрация целей — `keep` / `drop`

Собирать метрики только с хостов, у которых тег `production` в Consul:

```yaml
relabel_configs:
  - source_labels: [__meta_consul_tag]
    regex: '.*production.*'
    action: keep
```

### Создание метки из метаданных — `replace`

Создать метку `pod_name` из `__meta_kubernetes_pod_name`:

```yaml
relabel_configs:
  - source_labels: [__meta_kubernetes_pod_name]
    target_label: pod_name
    action: replace
```

### Копирование множества меток — `labelmap`

Префикс `__meta_kubernetes_pod_label_*` → краткие имена:

```yaml
relabel_configs:
  - regex: __meta_kubernetes_pod_label_(.+)
    replacement: '$1'
    action: labelmap
```

Результат: `__meta_kubernetes_pod_label_app` → `app`, `__meta_kubernetes_pod_label_version` → `version`.

### Удаление метаданных — `labeldrop`

Удалить все `__meta_kubernetes_*` после копирования нужных:

```yaml
relabel_configs:
  - regex: __meta_kubernetes_.+
    action: labeldrop
```

> **Внимание:** `labelkeep` используйте с осторожностью — можно удалить служебные метки (`__address__`, `__scheme__`), что сломает сбор метрик.

### Blackbox Exporter — подмена `__address__`

Blackbox Exporter требует передачи целевого URL как параметра. Relabeling подменяет адрес цели:

```yaml
scrape_configs:
  - job_name: 'blackbox-http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets: ['https://example.com', 'https://api.example.com']
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: 'blackbox-exporter:9115'
      - source_labels: [__param_target]
        target_label: instance
```

Логика: оригинальный `__address__` (целевой URL) → `__param_target` → `__address__` заменяется на адрес Blackbox Exporter → `instance` сохраняет оригинальный URL для идентификации.

### Шардирование — `hashmod`

Распределение целей между несколькими экземплярами Prometheus:

```yaml
relabel_configs:
  - source_labels: [__address__]
    modulus: 4
    target_label: __tmp_hash
    action: hashmod
  - source_labels: [__tmp_hash]
    regex: '0'
    action: keep
```

Каждый экземпляр Prometheus получает свой `modulus` (0, 1, 2, 3) и забирает только соответствующие цели.

## Additional Information

### Связанные темы

- [SD в Kubernetes](./kubernetes/service_discovery.md) — специфика `kubernetes_sd_configs`, ServiceMonitor/PodMonitor
- [Blackbox Exporter](./Exporters/blackbox/blackbox_exporter_installation_and_setup.md) — relabeling для probe-мониторинга
- [promtool](./promtool_and_best_practices.md) — валидация конфигурации
- [Remote Write](./scaling/remote_read_write.md) — `write_relabel_configs` для фильтрации перед отправкой
