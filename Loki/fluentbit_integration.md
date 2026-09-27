# Интеграция Fluent Bit с Loki

## Определения

**Fluent Bit** — высокопроизводительный, легковесный агент и агрегатор телеметрии (логи, метрики, трассировки). Написан на языке C, что обеспечивает минимальное потребление ресурсов CPU и RAM, делая его идеальным решением для развертывания в качестве DaemonSet в кластерах Kubernetes.

**Output-плагин `loki`** — встроенный компонент Fluent Bit для передачи данных в Grafana Loki. Плагин поддерживает группировку сообщений в пакеты (batching), сжатие и динамическое назначение меток (labels).

**Структурированные метаданные (Structured Metadata)** — функция Loki 3.x, поддерживаемая Fluent Bit, которая позволяет передавать дополнительные атрибуты лога без создания новых индексов в хранилище. Это решает проблему высокой кардинальности меток.

**Backpressure (Обратное давление)** — механизм управления потоком данных, при котором потребитель (хранилище Loki) сигнализирует производителю (Fluent Bit) о невозможности обработать данные с текущей скоростью. Правильная обработка backpressure критична: агент должен либо буферизовать данные на диске, либо отбрасывать логи, либо блокировать источник.

**Stream (Поток)** — уникальная комбинация лейблов (labels), которая определяет группу логов в Loki. Все логи с одинаковым набором лейблов принадлежат одному потоку. Индексация строится именно вокруг streams.

**Подробнее:** [Обзор Grafana Loki](./loki_overview.md), [Конфигурация Fluent Bit](../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md)

## Предварительные требования

### Железо и ресурсы

| Компонент | Минимум | Рекомендуется | Обоснование |
| :--- | :--- | :--- | :--- |
| **Fluent Bit (на хост)** | 1 vCPU, 256 MB RAM | 2 vCPU, 512 MB RAM | C-агент потребляет мало ресурсов, но при высокой нагрузке (>10K events/s) требуется больше CPU для парсинга и батчинга. |
| **Диск для буферов** | 5 GB | 20–50 GB | Filesystem-буфер (`storage.path`) защищает от потерь при сбоях сети. При высоком логе (500MB+/час) увеличивайте лимит. |
| **Сеть** | 1 Gbps | 10 Gbps | Сжатие gzip/snappy снижает объем, но при >1GB/час логов требуется пропускная способность. |
| **Loki (ingestion)** | 2 vCPU, 4 GB RAM | 4 vCPU, 8 GB RAM | Зависит от объема ingestion. При >5GB/час требуется масштабирование ingester'ов. |

### Программное обеспечение

| Компонент | Версия | Примечание |
| :--- | :--- | :--- |
| **Fluent Bit** | v3.x (стабильная) | Включает процессоры, улучшенный OTLP, нативную поддержку structured metadata. |
| **Loki** | 3.x | Поддержка `allow_structured_metadata`, Bloom-фильтры, TSDB Index. |
| **Kubernetes** | ≥ 1.28 | Для DaemonSet и RBAC. |
| **Prometheus** | ≥ 2.40 | Для сбора метрик Fluent Bit через `/api/v1/metrics/prometheus`. |
| **Grafana** | ≥ 10.0 | Для визуализации логов через LogQL и корреляции с метриками. |

### Инициализация окружения

```bash
# Проверка версии Fluent Bit
fluent-bit --version
# → Fluent Bit v3.x.x

# Проверка доступных плагинов
fluent-bit -L | grep -E "loki|kubernetes|tail|systemd"

# Проверка доступности Loki
curl -s http://loki.internal:3100/ready
# → HTTP/1.1 200 OK
```

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

### Архитектура интеграции

Типичный поток данных от источника к хранилищу:

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐
│   Источник  │────→│  Fluent Bit  │────→│    Loki      │────→│ Grafana  │
│             │     │   (Agent)    │     │  (Backend)   │     │ (UI)     │
│ • stdout    │     │              │     │              │     │          │
│ • journald  │     │ [INPUT]      │     │ Distributor  │     │ Explore  │
│ • файлы     │     │ [FILTER]     │     │ Ingester     │     │ LogQL    │
│             │     │ [OUTPUT:loki]│     │ Querier      │     │          │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────┘
```

**Этапы обработки:**

1.  **Сбор (INPUT):** Плагин `tail` или `systemd` читает логи из файлов или journald. Каждому входу присваивается тег (Tag) для маршрутизации.
2.  **Обогащение (FILTER):** Плагин `kubernetes` запрашивает API-сервер и добавляет метаданные (`namespace_name`, `pod_name`, `container_name`).
3.  **Форматирование (OUTPUT:loki):** Плагин `loki` формирует пакеты, применяет labels и structured_metadata, сжимает и отправляет через HTTP POST на `/loki/api/v1/push`.
4.  **Индексация и хранение:** Loki индексирует только labels, сжимает логи в чанки и сохраняет в объектное хранилище.
5.  **Запрос:** Grafana выполняет LogQL-запросы через Querier, используя индексы и Bloom-фильтры для быстрого поиска.

### Сравнение Fluent Bit и Grafana Alloy

| Критерий | Fluent Bit | Grafana Alloy |
| :--- | :--- | :--- |
| **Язык разработки** | C | Go |
| **Конфигурация** | Classic (INI / YAML / TOML) | River (декларативный граф) |
| **Область применения** | Преимущественно логи и базовые метрики | Полноценная наблюдаемость (логи, метрики, трейсы, профили) |
| **Интеграция с Loki** | Через плагин вывода | Нативный компонент `loki.write` |
| **Рекомендация** | Стандарт для систем, где критично минимальное потребление RAM | Рекомендуемый выбор для современных LGTM-стеков (Loki, Grafana, Tempo, Mimir) |

### Жизненный цикл записи в Loki через Fluent Bit

Каждая запись проходит через строго определенную последовательность:

```
[INPUT] → [FILTER] → [OUTPUT:loki]
   ↓         ↓           ↓
 Сбор    → Обработка → Отправка
```

**Важно:** Fluent Bit отправляет данные пакетами (batches). Размер пакета и интервал сброса (`Flush`) определяют латентность доставки. При недоступности Loki пакеты буферизуются на диске (`storage.path`), обеспечивая семантику at-least-once.

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

### Аутентификация в Loki

Для защиты эндпоинта `/loki/api/v1/push` используйте один из методов:

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Bearer Token** | JWT-токен в заголовке `Authorization` | Интеграция с Kubernetes service accounts через IRSA. |
| **Basic Auth** | Логин/пароль в заголовке `Authorization` | Простые развертывания, внутренние сети. |
| **TLS mTLS** | Взаимная аутентификация по сертификатам | Высокобезопасные окружения, compliance. |

**Пример конфигурации Fluent Bit с TLS:**
```ini
[OUTPUT]
    Name                   loki
    Match                  kube.*
    Host                   loki-gateway.logging.svc.cluster.local
    Port                   3100
    Labels                 job=fluent-bit, namespace=$kubernetes['namespace_name']
    tls                    On
    tls.verify             On
    tls.ca_file            /etc/fluent-bit/ca.crt
    tls.crt_file           /etc/fluent-bit/tls.crt
    tls.key_file           /etc/fluent-bit/tls.key
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

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `fluentbit_input_records_total` | Общее количество прочитанных записей. | Снижение > 30% за 5 минут. |
| `fluentbit_output_errors_total` | Количество ошибок при отправке в Loki (4xx, 5xx). | > 0 за 5 минут. |
| `fluentbit_output_retries_total` | Количество повторных попыток отправки. | Рост > 10 за минуту. |
| `fluentbit_storage_layer_chunks` | Количество чанков в хранилище (Backpressure). | Рост > 100 за 5 минут. |
| `fluentbit_output_processed_bytes_total` | Объем отправленных данных. | Снижение > 50%. |

### Пример Prometheus-правил для мониторинга Fluent Bit

```yaml
groups:
- name: fluent-bit-monitoring
  rules:
  - alert: FluentBitOutputErrors
    expr: rate(fluentbit_output_errors_total[5m]) > 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Fluent Bit has output errors"
      
  - alert: FluentBitHighRetries
    expr: rate(fluentbit_output_retries_total[5m]) > 10
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Fluent Bit retry rate is high"
```

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
    storage.type      filesystem

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
    compress               gzip
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
    storage.type   filesystem

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
    storage.type    filesystem

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
    compress        gzip
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

### Сценарий 5: Склейка многострочных логов (Java Stack Traces)

**Задача:** настроить Fluent Bit для склейки многострочных Java stack traces в единое событие.

**Проблема:** Без настройки multiline каждая строка stack trace попадает в Loki как отдельное событие, что делает чтение невозможным.

**Конфигурация Fluent Bit:**
```ini
[FILTER]
    Name                   multiline
    Match                  *
    multiline.key_content  log
    multiline.parser       java

[OUTPUT]
    Name                   loki
    Match                  *
    Host                   loki-gateway.logging.svc.cluster.local
    Port                   80
    Labels                 job=java-app
    Auto_Kubernetes_Labels On
```

### Настройка производительности и буферизации

Для высоконагруженных сред необходимо настроить гибридную буферизацию (Memory + Disk):

```ini
[SERVICE]
    storage.path    /var/lib/fluent-bit/storage/
    storage.type    filesystem
    storage.sync    normal

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
| `storage.total_limit_size` | Глобальный лимит дискового пространства для всех очередей. |
| `storage.keep.rejected` | Сохранять отброшенные чанки в DLQ (Dead Letter Queue) после исчерпания попыток. |

## Валидация и верификация

### Проверка конфигурации

1. **Синтаксическая проверка (dry-run):**
    ```bash
    # Classic
    fluent-bit --config /etc/fluent-bit/fluent-bit.conf --dry-run
    # → configuration test is successful

    # YAML
    fluent-bit --config /etc/fluent-bit/fluent-bit.yaml --dry-run
    ```

2. **Проверка доступных плагинов:**
    ```bash
    fluent-bit -L | grep loki
    # → [input] tail, [filter] kubernetes, [output] loki
    ```

3. **Тестовый запуск с выводом в STDOUT:**
    ```bash
    fluent-bit --config /etc/fluent-bit/fluent-bit.conf -o stdout -f
    # Отправьте тестовый лог и проверьте вывод
    ```

### Проверка доставки данных

```bash
# 1. Проверка здоровья Loki
curl -s http://loki.internal:3100/ready
# → HTTP/1.1 200 OK

# 2. Проверка метрик Fluent Bit
curl -s http://localhost:2020/api/v1/metrics | jq '.output'
# Должен показать records_sent, errors, retries

# 3. Проверка поступления логов в Loki
curl -s "http://loki.internal:3100/loki/api/v1/query?query={job=\"fluent-bit\"}" | jq '.data.result'
# Должен вернуть потоки (streams) с лейблами

# 4. Проверка structured metadata
curl -s "http://loki.internal:3100/loki/api/v1/query?query={job=\"fluent-bit\"} | json | container=\"my-app\"" | jq
```

### Валидация DaemonSet в Kubernetes

```bash
# Проверка статуса DaemonSet
kubectl get ds fluent-bit -n logging
# → fluent-bit   3   3   3   3   3   <age>

# Проверка логов пода
kubectl logs -n logging -l app=fluent-bit --tail=100

# Проверка метрик Prometheus
curl -s http://fluent-bit-prometheus-exporter:9200/metrics | grep fluentbit_output
```

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

### Диагностика backpressure и потерь данных

```bash
# Проверка статуса хранилища Fluent Bit
curl -s http://localhost:2020/api/v1/storage | jq

# Проверка ошибок в логах агента
journalctl -u fluent-bit -n 100 --no-pager | grep -E "error|warn"

# Проверка целостности базы позиций (Tail DB)
file /var/log/fluent-bit-positions.db
# → /var/log/fluent-bit-positions.db: SQLite 3.x database

# Проверка сетевой доступности Loki
curl -I http://loki.internal:3100/ready

# Проверка лимитов Loki
curl -s http://loki.internal:3100/loki/api/v1/limits | jq
```

### Чек-лист быстрой проверки

1.  **Конфигурация:** синтаксис проверен (`fluent-bit --dry-run`).
2.  **Сеть:** доступность Loki (`curl -I http://loki:3100/ready`).
3.  **Диск:** свободное место в `storage.path` (`df -h /var/lib/fluent-bit`).
4.  **Агент:** логи ошибок (`journalctl -u fluent-bit`).
5.  **Метрики:** `fluentbit_output_errors_total`, `fluentbit_storage_layer_chunks`.
6.  **Loki:** лимиты ingestion (`/loki/api/v1/limits`).

## Рекомендации и процедуры очистки

### Лучшие практики

1.  **Обязательное disk-backed буферирование:** В production всегда используйте `storage.type filesystem` и выделяйте диск не менее 10–20 GB. Это защищает от потерь при сетевых сбоях.
2.  **Низкая кардинальность лейблов:** В `Labels` указывайте только статические или низкокардинальные поля (`namespace`, `pod_name`, `job`). Динамические идентификаторы (`trace_id`, `request_id`) переносите в `Structured_Metadata` или тело лога.
3.  **Уникальные stream'ы:** При использовании нескольких реплик Fluent Bit добавляйте в лейблы идентификатор ноды (`node=$kubernetes['host']`) или имени пода, чтобы избежать конфликтов `Out of Order`.
4.  **Сжатие:** Включайте `compress gzip` в OUTPUT-секции для снижения сетевого трафика.
5.  **Структурированные логи:** Приложения должны писать в `stdout/stderr` в формате JSON. Это исключает необходимость в сложных парсерах на стороне сбора.
6.  **Мониторинг:** Настройте алерты на `fluentbit_output_errors_total`, `fluentbit_output_retries_total` и рост `fluentbit_storage_layer_chunks`.
7.  **Версионирование конфигурации:** Храните конфигурации Fluent Bit в Git. Используйте Hot Reload (`POST /api/v2/reload`) для применения изменений без перезапуска пода.
8.  **Безопасность:** Не передавайте секреты и PII в лейблы Loki — они индексируются и могут быть доступны широкому кругу лиц. Используйте маскирование в Lua-фильтрах.

### Откат изменений

```bash
# 1. Откат конфигурации DaemonSet
kubectl rollout undo daemonset/fluent-bit -n logging

# 2. Проверка статуса после отката
kubectl get ds fluent-bit -n logging
kubectl rollout status daemonset/fluent-bit -n logging

# 3. Проверка логов
kubectl logs -n logging -l app=fluent-bit --tail=50

# 4. Очистка временных файлов буферизации (при необходимости)
kubectl exec -n logging <pod-name> -- rm -rf /var/lib/fluent-bit/storage/*
```

### Очистка окружения после тестирования

```bash
# Удаление тестовых логов из Loki (через LogQL)
# В Grafana Explore: {job="fluent-bit"} | json | test="true" | line_format "json"

# Удаление временных баз данных Fluent Bit
sudo rm -f /var/log/flb_kube.db
sudo rm -f /var/log/flb_journal.db
sudo rm -f /var/log/flb_nginx.db

# Очистка хранилища
sudo rm -rf /var/lib/fluent-bit/storage/*
```

## Граничные случаи и известные ограничения

### Out of Order Entries

**Симптом:** Loki возвращает ошибку `entry out of order` или `too far behind`.

**Причина:** Несколько экземпляров Fluent Bit отправляют логи с одинаковым набором лейблов, но разными временными метками. Это происходит при:
- Отсутствии уникального идентификатора ноды/пода в лейблах.
- Резком сбросе времени (NTP) на одном из узлов.
- Перезапуске пода Fluent Bit с последующим повторением событий из файла.

**Решение:**
1. Добавьте `node=$kubernetes['host']` или `agent=${HOSTNAME}` в `Labels`.
2. Настройте `read_from_head: false` и корректную базу позиций (`DB`).
3. Используйте `storage.type filesystem` для сохранения порядка при ретраях.

### Потеря логов при переполнении диска

Если `storage.path` размещен на разделе, который заполняется, Fluent Bit перестает писать буферы и начинает отбрасывать логи. Мониторьте использование диска и настройте `storage.total_limit_size`.

### Проблемы с парсингом многострочных логов

Многие приложения (Java, Python, Go) генерируют многострочные логи — стеки вызовов, traceback. Без склейки каждая строка попадает в Loki как отдельное событие.

**Решение:** Используйте `multiline.parser` в плагине `tail` или `[FILTER] Name multiline`.

### Высокое потребление RAM при больших батчах

Параметр `mem_buf_limit` ограничивает потребление RAM плагином `tail`. При его достижении плагин приостанавливает чтение до освобождения памяти. Настройте значение исходя из доступных ресурсов (обычно 50–100 MB на экземпляр).

### Поведение при изменении формата логов приложением

Если приложение изменит формат логов (например, с plain text на JSON), существующий парсер может перестать работать. Используйте аннотации `fluentbit.io/parser` на подах Kubernetes для гибкого управления парсерами без перезапуска агента.

### См. также

- [Обзор Grafana Loki](./loki_overview.md)
- [Установка Grafana Alloy](./loki_stack_setup/alloy_installation.md)
- [Примеры LogQL запросов](./loki_stack_setup/logql_examples.md)
- [Документация Fluent Bit: Loki](https://docs.fluentbit.io/manual/pipeline/outputs/loki)
- [Конфигурация Fluent Bit](../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md)
- [Диагностика логирования](../Linux/Diagnostics/Troubleshooting/logging_troubleshooting.md)
