# Установка Promtail в Kubernetes (Legacy)

## Определения

**Promtail** — специализированный агент для сбора логов и их отправки в систему Loki. В архитектуре Kubernetes он развертывается как DaemonSet, обеспечивая сбор логов со всех узлов кластера.

**Важное примечание (весна 2026):** Поддержка Promtail официально прекращена. Для всех новых инсталляций и при плановом обновлении инфраструктуры необходимо использовать **Grafana Alloy**. Данный документ сохраняется исключительно для обслуживания и эксплуатации существующих legacy-систем.

**Статус:** Helm-чарт `grafana/promtail` переведен в архивный режим. Обновления безопасности и функционала не выпускаются.

**Подробнее:** [Статус агентов сбора](../loki_overview.md#важные-изменения)

## Основные концепции

### Архитектура Promtail

Агент читает файлы логов из директории `/var/log/pods` на хосте, обогащает их метаданными из API Kubernetes и отправляет пакеты (batches) в Loki через балансировщик (Gateway).

```
┌─────────────┐     ┌──────────────┐     ┌─────────┐
│ Файлы логов │────→│   Promtail   │────→│  Loki   │
│ /var/log/*  │     │  (DaemonSet) │     │ Gateway │
└─────────────┘     └──────────────┘     └─────────┘
     │                     │
     │              positions.yaml
     │            (отслеживание чтения)
```

### Ключевые компоненты конфигурации

| Компонент | Назначение |
| :--- | :--- |
| **`clients`** | Настройка адресов Loki и параметров аутентификации |
| **`scrape_configs`** | Правила обнаружения источников (Service Discovery) и парсинга |
| **`pipeline_stages`** | Этапы обработки строки: парсинг JSON, обработка многострочных логов (multiline), фильтрация |
| **`positions`** | Файл для хранения смещения (offset) в каждом читаемом файле |

### Сравнение с Grafana Alloy

| Характеристика | Promtail | Grafana Alloy |
| :--- | :--- | :--- |
| **Тип данных** | Только логи | Универсальный: логи, метрики, трассировки, профили |
| **Язык конфигурации** | YAML (статический) | River (динамический, HCL-подобный) |
| **Производительность** | Средняя | Высокая (оптимизировано под Go и OTel) |
| **Жизненный цикл** | Устарело (Deprecated) | Стандарт индустрии (Current) |

## Практические сценарии

### Сценарий 1: Эксплуатация Promtail в существующем кластере

Для поддержки работоспособности агента в старых окружениях необходимо использовать фиксированные версии чарта.

**Подготовка:**

```bash
# Использование legacy-репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Получение текущих значений
helm show values grafana/promtail > promtail_values.yaml
```

**Пример конфигурации для многострочных логов (Java Stacktrace):**

```yaml
config:
  clients:
    - url: http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push
      batchwait: 1s
      batchsize: 1048576 # 1MB

  snippets:
    pipelineStages:
      - multiline:
          firstline: '^\[\d{4}-\d{2}-\d{2}' # Начало строки с датой
          max_wait_time: 3s
      - json:
          expressions:
            level: level
            msg: message

    scrape_configs:
      - job_name: kubernetes-pods
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_namespace]
            target_label: namespace
          - source_labels: [__meta_kubernetes_pod_name]
            target_label: pod
```

### Сценарий 2: Безопасность и права доступа (RBAC)

Promtail требует доступа к API Kubernetes для получения метаданных подов и узлов.

**Настройка ServiceAccount в `values.yaml`:**
```yaml
serviceAccount:
  create: true
  name: promtail-agent

rbac:
  create: true # Создает ClusterRole с правами на pods, nodes, namespaces
```

Если в кластере включены жесткие политики безопасности (PodSecurityPolicy или Admission Controllers), убедитесь, что Promtail имеет доступ к `/var/log/pods` и `/var/lib/docker/containers` через `hostPath` тома.

### Сценарий 3: Оптимизация и управление ресурсами

В высоконагруженных кластерах Promtail может потреблять значительный объем памяти при буферизации.

```yaml
resources:
  limits:
    cpu: 200m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 256Mi

# Настройка backoff при недоступности Loki
config:
  clients:
    - url: http://loki:3100/loki/api/v1/push
      backoff_config:
        min_period: 100ms
        max_period: 10s
        max_retries: 10
```

### Диагностика и устранение неисправностей

| Проблема | Причина | Способ решения |
| :--- | :--- | :--- |
| **"Entry out of order"** | Логи с одинаковыми метками приходят не в хронологическом порядке | Добавьте уникальную метку (например, `pod`) или используйте стадию `timestamp` для парсинга времени из тела лога. |
| **Поды в Pending** | Taints на мастер-нодах или отсутствие ресурсов | Добавьте `tolerations: - operator: "Exists"` в values.yaml. Проверьте ResourceQuotas в namespace. |
| **Пропуски данных** | Сбой файла `positions.yaml` | Проверьте монтирование HostPath для персистентности файла позиций. Убедитесь, что у Promtail есть права на запись в этот файл. |
| **Ошибка 429** | Превышение лимитов в Loki | Увеличьте `ingestion_rate_mb` в конфигурации Loki или уменьшите `batchsize` в Promtail. |

### Сценарий 4: Переход на Grafana Alloy

Миграция рекомендуется как единственный путь обеспечения безопасности и масштабируемости.

1.  **Экспорт конфигурации:**
    ```bash
    kubectl get configmap -n logging promtail -o jsonpath='{.data["promtail\.yaml"]}' > legacy_promtail.yaml
    ```
2.  **Конвертация:**
    Используйте встроенную утилиту Alloy (или онлайн-версию):
    ```bash
    alloy convert --source-format=promtail --output=config.alloy legacy_promtail.yaml
    ```
3.  **Валидация и проверка лейблов:**
    Проверьте полученный файл `config.alloy`. Убедитесь, что логика `relabel_configs` сохранилась, так как изменение лейблов приведет к разрыву исторических данных (созданию новых потоков в Loki).
4.  **Развертывание:**
    Инструкции по установке нового агента доступны в [Руководстве по Alloy](alloy_installation.md).

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Установка Grafana Alloy](alloy_installation.md) | Рекомендуемый современный агент для сбора телеметрии |
| [Конвертер Promtail к Alloy](https://grafana.com/docs/alloy/latest/tasks/migrate/) | Официальный инструмент миграции от Grafana Labs |
| [Обзор Loki](../loki_overview.md) | Общая архитектура системы логирования |
| [Установка Loki](loki_installation.md) | Развертывание бэкенда в Kubernetes |
| [Grafana Alloy — обзор](../../Grafana/grafana_alloy_overview.md) | Детальное описание преимуществ и языка River |
