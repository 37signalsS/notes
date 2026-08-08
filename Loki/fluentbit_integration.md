# Интеграция Fluent Bit с Loki

## Определения

**Fluent Bit** — высокопроизводительный, легковесный агент и агрегатор телеметрии (логи, метрики, трассировки). Написан на языке C, что обеспечивает минимальное потребление ресурсов CPU и RAM, делая его идеальным решением для развертывания в качестве DaemonSet в кластерах Kubernetes.

**Output-плагин `loki`** — встроенный компонент Fluent Bit для передачи данных в Grafana Loki. Плагин поддерживает группировку сообщений в пакеты (batching), сжатие и динамическое назначение меток (labels).

**Структурированные метаданные (Structured Metadata)** — функция Loki 3.x, поддерживаемая Fluent Bit, которая позволяет передавать дополнительные атрибуты лога без создания новых индексов в хранилище. Это решает проблему высокой кардинальности меток.

**Подробнее:** [Обзор Grafana Loki](./loki_overview.md), [Конфигурация Fluent Bit](../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md)

## Основные концепции

### Версии и поддержка

| Версия | Статус | Рекомендация |
| :--- | :--- | :--- |
| **Fluent Bit v3.x** | Текущая (Stable) | Рекомендуется для всех новых развертываний. Включает поддержку процессоров и улучшенную работу с OTLP. |
| **Fluent Bit v2.x** | Поддерживается | Стабильная версия, широко распространенная в существующих окружениях. |
| **grafana/fluent-bit** | Устарело (Deprecated) | Специализированный образ от Grafana Labs более не требуется, так как плагин `loki` интегрирован в официальный бинарный файл Fluent Bit. |

### Ограничения Loki: Индексация и лейблы

Loki индексирует только метаданные (лейблы), а не текст лога. Это накладывает два критических ограничения при интеграции с Fluent Bit:

1.  **Порядок логов (Out of Order):** Loki требует, чтобы логи внутри одного потока (уникальный набор лейблов) поступали в хронологическом порядке. Если несколько экземпляров Fluent Bit отправляют данные с идентичными статичными лейблами одновременно, может возникнуть конфликт.
2.  **Кардинальность (Cardinality):** Создание уникального лейбла для каждого идентификатора запроса (например, `request_id`) приведет к взрывному росту индекса и отказу Querier.

**Решение:** Используйте динамические лейблы для идентификации источника (под, контейнер) и структурированные метаданные для передачи детального контекста.

### Сравнение Fluent Bit и Grafana Alloy

| Критерий | Fluent Bit | Grafana Alloy |
| :--- | :--- | :--- |
| **Язык разработки** | C | Go |
| **Конфигурация** | Classic (INI / YAML / TOML) | River (декларативный граф) |
| **Область применения** | Преимущественно логи и базовые метрики | Полноценная наблюдаемость (логи, метрики, трейсы, профили) |
| **Интеграция с Loki** | Через плагин вывода | Нативный компонент `loki.write` |
| **Рекомендация** | Стандарт для систем, где критично минимальное потребление RAM | Рекомендуемый выбор для современных LGTM-стеков (Loki, Grafana, Tempo, Mimir) |

## Безопасность и права доступа (RBAC)

Для работы Fluent Bit в Kubernetes требуются права на чтение логов и взаимодействие с API-сервером для получения метаданных.

### ClusterRole и ServiceAccount

**Пример манифеста:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: fluent-bit
  namespace: logging

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: fluent-bit-read
rules:
- apiGroups: [""]
  resources: ["pods", "namespaces"]
  verbs: ["get", "list", "watch"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: fluent-bit-read
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: fluent-bit-read
subjects:
- kind: ServiceAccount
  name: fluent-bit
  namespace: logging
```

## Мониторинг и проверка состояния

Fluent Bit предоставляет встроенные метрики в формате Prometheus для мониторинга производительности и здоровья конвейеров.

### Настройка HTTP-сервера метрик

```ini
[SERVICE]
    HTTP_Server  On
    HTTP_Listen  0.0.0.0
    HTTP_Port    2020
    Health_Check On
```

### Ключевые метрики

| Метрика | Описание |
| :--- | :--- |
| `fluentbit_input_records_total` | Общее количество прочитанных записей. |
| `fluentbit_output_errors_total` | Количество ошибок при отправке в Loki (4xx, 5xx). |
| `fluentbit_output_retries_total`| Количество повторных попыток отправки. |
| `fluentbit_storage_layer_chunks`| Количество чанков в хранилище (Backpressure). |

## Практические сценарии

### Сценарий 1: Сбор логов Kubernetes с поддержкой Loki 3.x

Пример конфигурации для Fluent Bit v3.x, который собирает логи контейнеров, обогащает их метаданными Kubernetes и отправляет в Loki, используя структурированные метаданные для меток с высокой кардинальностью.

**Файл `fluent-bit.conf`:**

```ini
[SERVICE]
    Flush         1
    Log_Level     info
    Daemon        off
    Parsers_File  parsers.conf
    HTTP_Server   On
    HTTP_Listen   0.0.0.0
    HTTP_Port     2020

[INPUT]
    Name              tail
    Tag               kube.*
    Path              /var/log/containers/*.log
    Parser            docker
    DB                /var/log/flb_kube.db
    Mem_Buf_Limit     50MB
    Skip_Long_Lines   On
    Refresh_Interval  10

[FILTER]
    Name                kubernetes
    Match               kube.*
    Kube_URL            https://kubernetes.default.svc:443
    Merge_Log           On
    Keep_Log            Off
    K8S-Logging.Parser  On
    K8S-Logging.Exclude On

[OUTPUT]
    Name                   loki
    Match                  kube.*
    Host                   loki-gateway.logging.svc.cluster.local
    Port                   80
    # Лейблы определяют индекс (низкая кардинальность)
    Labels                 job=fluent-bit, namespace=$kubernetes['namespace_name'], pod=$kubernetes['pod_name']
    # Структурированные метаданные (Loki 3.x) — не индексируются, но доступны для быстрого поиска
    Structured_Metadata    container=$kubernetes['container_name'], node=$kubernetes['host']
    Auto_Kubernetes_Labels On
    Line_Format            json
    LogLevel               info
```

### Сценарий 2: Мультиарендность (Multi-tenancy)

Маршрутизация логов в разные тенанты Loki на основе пространства имен Kubernetes.

```ini
[FILTER]
    Name    rewrite_tag
    Match   kube.*
    Rule    $kubernetes['namespace_name'] ^(prod)$  tenant.prod.kube.$TAG false
    Rule    $kubernetes['namespace_name'] ^(dev)$   tenant.dev.kube.$TAG  false

[OUTPUT]
    Name     loki
    Match    tenant.prod.*
    Host     loki-gateway.logging.svc.cluster.local
    Port     80
    TenantID team-production
    Labels   env=prod, namespace=$kubernetes['namespace_name']

[OUTPUT]
    Name     loki
    Match    tenant.dev.*
    Host     loki-gateway.logging.svc.cluster.local
    Port     80
    TenantID team-development
    Labels   env=dev, namespace=$kubernetes['namespace_name']
```

### Сценарий 3: Обработка системных журналов (Journald)

Сбор логов операционной системы с нод Kubernetes.

```ini
[INPUT]
    Name           systemd
    Tag            host.*
    Systemd_Filter _SYSTEMD_UNIT=kubelet.service
    Read_From_Tail On

[OUTPUT]
    Name   loki
    Match  host.*
    Host   loki-gateway.logging.svc.cluster.local
    Port   80
    Labels job=systemd, unit=$_SYSTEMD_UNIT, hostname=$hostname
```

### Сценарий 4: Production-конфигурация для Linux-сервера (без K8s)

Пример конфигурации, собирающей системный журнал и логи Nginx с маскированием чувствительных данных.

**Файл `fluent-bit.conf`:**
```ini
[SERVICE]
    Flush           5
    Daemon          Off
    Log_Level       info
    Parsers_File    parsers.conf
    storage.path    /var/log/flb-storage/  # Буферизация на диске для надежности
    storage.sync    normal

[INPUT]
    Name            systemd
    Tag             systemd.*
    DB              /var/log/flb_journal.db
    Read_From_Tail  On
    Strip_Underscores On

[INPUT]
    Name            tail
    Path            /var/log/nginx/access.log
    Tag             nginx.access
    DB              /var/log/flb_nginx.db
    Parser          nginx

[FILTER]
    Name            lua
    Match           *
    script          /etc/fluent-bit/redact.lua
    call            redact_pci

[OUTPUT]
    Name            loki
    Match           *
    Host            loki.internal
    Port            3100
    Labels          job=fluent-bit, host=${HOSTNAME}
    line_format     json
```

**Маскирование данных (redact.lua):**
```lua
-- Lua-фильтр для маскирования номеров карт
function redact_pci(tag, timestamp, record)
    if record["message"] then
        -- Заменяет 16-значные числа на маску
        record["message"] = string.gsub(record["message"], "%d%d%d%d%s?%d%d%d%d%s?%d%d%d%d%s?%d%d%d%d", "****-****-****-****")
    end
    return 1, timestamp, record
end
```

### Настройка производительности и буферизации

Для высоконагруженных сред необходимо настроить гибридную буферизацию (Memory + Disk):

```ini
[INPUT]
    Name          tail
    Path          /var/log/app.log
    storage.type  filesystem  # Использовать диск при переполнении RAM
    Mem_Buf_Limit 50MB        # Лимит в оперативной памяти
    Buffer_Max_Size 5MB       # Размер чанка
```

| Параметр | Описание |
| :--- | :--- |
| `storage.path` | Директория для хранения буферов при сбоях сети. |
| `Mem_Buf_Limit` | Предотвращает OOM-killer при резких всплесках объема логов. |
| `Flush` | Интервал сброса данных в Loki (обычно 1-5 сек). |

## Устранение неполадок

### Ошибки при передаче данных

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **413 Request Entity Too Large** | Батч логов превышает лимит Loki или Ingress | Увеличьте `http_listen_max_body_size` в Loki или добавьте аннотацию `proxy-body-size` в Nginx Ingress. |
| **429 Too Many Requests** | Превышен лимит скорости записи (Ingestion Rate) | Настройте `ingestion_rate_mb` в `limits_config` на стороне Loki. |
| **Error parsing labels** | Ошибка в синтаксисе обращения к переменным | Проверьте, что переменные (например, `$kubernetes['pod_name']`) доступны после работы фильтра. |
| **Out of Order Entries** | Несколько потоков пишут в один Stream без уникальных меток | Добавьте метку с именем ноды или идентификатором реплики агента. |

### Проверка конфигурации Ingress

Для корректной работы Fluent Bit с внешним Loki через Ingress, необходимо настроить таймауты и лимиты тела запроса.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: loki-ingress
  namespace: logging
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
spec:
  rules:
    - host: loki.internal.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: loki-gateway
                port:
                  number: 80
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Grafana Loki](./loki_overview.md) | Архитектура системы, типы хранилищ и язык LogQL |
| [Установка Grafana Alloy](./loki_stack_setup/alloy_installation.md) | Описание рекомендуемого агента для новых систем |
| [Документация Fluent Bit: Loki](https://docs.fluentbit.io/manual/pipeline/outputs/loki) | Официальный справочник параметров плагина вывода |
| [Примеры LogQL запросов](./loki_stack_setup/logql_examples.md) | Как анализировать логи, собранные Fluent Bit |
