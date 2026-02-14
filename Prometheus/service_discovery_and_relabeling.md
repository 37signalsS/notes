# Service Discovery и Relabeling в Prometheus

> Эта заметка описывает общие принципы. Для специфики работы в Kubernetes см. **[Обнаружение сервисов в Kubernetes](./kubernetes/service_discovery.md)**.

## Определения

**Service Discovery (Обнаружение сервисов)** — это механизм, который [Prometheus](./overview.md) использует для автоматического нахождения целей (targets) для сбора метрик. Вместо ручного перечисления хостов в [конфигурации](./configuration.md), Prometheus запрашивает у внешних систем (API облаков, Kubernetes, [Consul](../Consul/consul_overview.md)) актуальный список эндпоинтов.

**Relabeling (Перемаркировка)** — это процесс модификации меток, связанных с целью. Он позволяет фильтровать цели, стандартизировать метки и обогащать их метаданными, полученными в процессе Service Discovery.

## Основные концепции

### Жизненный цикл обнаружения и перемаркировки
1.  **Обнаружение:** Prometheus обращается к настроенному источнику (например, `kubernetes_sd_configs`).
2.  **Метаданные:** Источник возвращает список целей с набором временных меток, имеющих префикс `__meta_` (например, `__meta_kubernetes_pod_name`).
3.  **Перемаркировка (`relabel_configs`):** Prometheus применяет правила из секции `relabel_configs` для фильтрации и преобразования целей и их меток *до* сбора метрик.
4.  **Сбор метрик (Scrape):** Prometheus опрашивает финальный список целей.
5.  **Перемаркировка метрик (`metric_relabel_configs`):** Prometheus применяет правила из `metric_relabel_configs` для фильтрации и преобразования уже собранных временных рядов *до* их сохранения в базу данных.

### `relabel_configs` vs `metric_relabel_configs`
Это два разных этапа с разными задачами:

1.  **`relabel_configs`** (управление **целями**):
    *   Выполняется **до** сбора метрик.
    *   Решает, **будет ли** Prometheus опрашивать цель (`action: keep/drop`).
    *   Устанавливает адрес цели (формирует метку `__address__`).
    *   Преобразует метаданные (`__meta_*`) в постоянные метки цели (например, `pod_name`). Это помогает управлять [кардинальностью](./concepts/labels_and_cardinality.md).

2.  **`metric_relabel_configs`** (управление **метриками**):
    *   Выполняется **после** сбора метрик, но **до** сохранения в TSDB.
    *   Фильтрует ненужные **временные ряды**.
    *   Изменяет или удаляет метки у уже собранных метрик.
    *   **Важно:** Использовать аккуратно, так как это создает дополнительную нагрузку на Prometheus.

## Практические сценарии

### Механизмы Service Discovery
Все механизмы настраиваются в секции `scrape_configs` файла `prometheus.yml`.

#### `static_configs`
Самый простой способ, подходит для статичной инфраструктуры.
```yaml
scrape_configs:
  - job_name: 'node_exporter'
    static_configs:
      - targets: ['192.168.1.10:9100', '192.168.1.11:9100']
        labels:
          env: 'production'
```

#### `file_sd_configs`
Prometheus периодически читает YAML/JSON файлы со списками целей. Позволяет изменять цели без перезагрузки Prometheus.

**Шаг 1: Создать файл с целями (`/etc/prometheus/sd/hosts.yml`)**
```yaml
- targets:
  - 'server1.example.com:9100'
  - 'server2.example.com:9100'
  labels:
    service: 'backend'
```

**Шаг 2: Настроить Prometheus**
```yaml
scrape_configs:
  - job_name: 'file_sd'
    file_sd_configs:
      - files:
        - '/etc/prometheus/sd/*.yml'
        refresh_interval: 2m
```

#### Обнаружение через API (`consul_sd_config`)
Пример интеграции с Consul для обнаружения сервисов.
```yaml
scrape_configs:
  - job_name: 'consul_services'
    consul_sd_configs:
      - server: 'localhost:8500'
```
Prometheus будет автоматически находить сервисы, зарегистрированные в Consul.

## Дополнительная информация: Действия в `relabel_configs`

#### `keep` / `drop` (Фильтрация целей)
*   `keep`: Оставить только те цели, которые соответствуют `regex`.
*   `drop`: Отбросить цели, которые соответствуют `regex`.

**Пример:** Собирать метрики только с хостов, у которых есть тег `env="production"`.
```yaml
relabel_configs:
  - source_labels: [__meta_consul_tag]
    regex: '.*production.*'
    action: keep
```

#### `replace` (Замена значения метки)
Заменяет или создает `target_label` на основе `regex`, примененного к `source_labels`.
**Пример:** Создать метку `pod_name` из мета-метки `__meta_kubernetes_pod_name`.
```yaml
relabel_configs:
  - source_labels: [__meta_kubernetes_pod_name]
    target_label: pod_name
    action: replace
```

#### `labelmap` (Копирование меток)
Копирует метки, имена которых соответствуют `regex`. Часто используется для преобразования `__meta_` меток в постоянные.
**Пример:** Превратить `__meta_kubernetes_pod_label_app` в `app`.
```yaml
relabel_configs:
  - regex: __meta_kubernetes_pod_label_(.+)
    replacement: '$1'
    action: labelmap
```
Это правило найдет все метки вида `__meta_kubernetes_pod_label_*` и создаст новые, убрав префикс.

#### `labeldrop` / `labelkeep` (Удаление меток)
*   `labeldrop`: Удалить все метки, имена которых соответствуют `regex`.
*   `labelkeep`: Сохранить только те метки, имена которых соответствуют `regex`.

**Пример:** Удалить все мета-метки Kubernetes после того, как нужные из них были скопированы.
```yaml
relabel_configs:
  # ... другие правила ...
  - regex: __meta_kubernetes_.+
    action: labeldrop
```
> **Внимание!** Используйте `labelkeep` с осторожностью, чтобы случайно не удалить служебные метки, такие как `__address__`, что сделает сбор метрик невозможным.