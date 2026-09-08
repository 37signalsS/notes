# Буферизация и маршрутизация в Fluent Bit

## Определения

**Буферизация (Buffering)** — механизм временного хранения записей логов перед их отправкой в место назначения. Необходим для предотвращения потери данных при сбоях сети или недоступности хранилища. Буферизованные данные используют внутреннее бинарное представление Fluent Bit и являются неизменяемыми (immutable).

**Слой хранения (Storage Layer)** — подсистема Fluent Bit, управляющая жизненным циклом чанков (chunks) данных в памяти или на диске. Реализует гибридную модель хранения с автоматическим управлением движением данных между уровнями.

**Чанк (Chunk)** — логический блок данных, содержащий группу записей логов. Средний размер чанка — 2 MB. Минимальная единица обработки для системы хранения. Чанки могут находиться в двух состояниях: `up` (одновременно в памяти и на диске) и `down` (только на диске).

**Тег (Tag)** — строковый идентификатор, присваиваемый каждой записи при сборе. Основной ключ для определения маршрута движения данных. Тег назначается в плагине ввода и используется для сопоставления с правилами маршрутизации.

**Маршрутизация (Routing)** — процесс сопоставления тега записи с правилами `Match` или `Match_Regex` в плагинах вывода. Поддерживает три подхода: маршрутизацию по тегам (tag-based), условную маршрутизацию (conditional) и маршрутизацию по меткам (label-based).

**Обратное давление (Backpressure)** — состояние, при котором скорость поступления данных превышает скорость их обработки или отправки, что требует механизмов регулирования нагрузки для предотвращения переполнения памяти (OOM).

**Планировщик (Scheduler)** — компонент Fluent Bit, управляющий моментом сброса (flush) данных и планированием повторных попыток (retries) при ошибках доставки. Использует алгоритм экспоненциального отката с джиттером (exponential backoff with jitter).

**Dead Letter Queue (DLQ)** — очередь для хранения записей, которые не удалось доставить после исчерпания всех повторных попыток. Активируется параметром `storage.keep.rejected` в секции `service`.

## Основные концепции

### Модели хранения данных

Fluent Bit поддерживает три режима буферизации, различающиеся балансом между производительностью и надежностью:

#### Memory-only (только в памяти)

*   Данные хранятся в RAM (Random Access Memory).
*   Максимальная производительность, минимальные накладные расходы.
*   **Риск**: При сбое процесса или перезагрузке узла данные будут безвозвратно утеряны.
*   Используется по умолчанию.

#### Filesystem (дисковый буфер — гибридный режим)

*   Использует механизм Memory-mapped files (mmap) для записи на диск.
*   **Персистентность**: Данные сохраняются между перезапусками агента.
*   **Управление очередью**: Работает по принципу FIFO (First In, First Out).
*   Если в памяти достаточно места, на диск пишется дубликат чанка (`up` chunk). Если памяти мало, чанк остается только на диске (`down` chunk) и подгружается в память только при необходимости обработки.

#### Memory Ring Buffer (кольцевой буфер — memrb)

*   Данные хранятся в фиксированном кольцевом буфере фиксированного размера в памяти.
*   При заполнении буфера автоматически удаляются самые старые чанки для освобождения места для новых.
*   **Риск**: Потеря данных при заполнении буфера (старые записи отбрасываются).
*   Метрики потерь: `memrb_dropped_chunks`, `memrb_dropped_bytes`.
*   Подходит для сценариев, где важна непрерывность сбора данных, а потеря части истории допустима (например, метрики, мониторинг).

**Сравнение режимов:**

| Параметр | Memory-only | Filesystem | Memory Ring Buffer |
|:---|:---|:---|:---|
| Производительность | Максимальная | Средняя | Высокая |
| Надежность доставки | Низкая | Высокая | Средняя |
| Потеря данных при сбое | Да | Нет | Да (старые чанки) |
| Использование памяти | Фиксированное | Фиксированное (max_chunks_up) | Фиксированное (размер буфера) |
| Каскадное удаление | Нет | Нет | Да (LRU) |
| По умолчанию | Да | Нет | Нет |

### Жизненный цикл чанков

1.  **Создание**: Плагин ввода создает чанк и присваивает ему тег.
2.  **Буферизация**: Чанк попадает в буфер (память или диск в зависимости от `storage.type`).
3.  **Обработка**: Фильтры и парсеры модифицируют данные в чанке.
4.  **Маршрутизация**: Планировщик выбирает чанк для отправки на основе правил `Match`.
5.  **Отправка**: Плагин вывода отправляет данные в хранилище.
6.  **Подтверждение**: При успешной отправке — чанк удаляется из буфера.
7.  **Повторная попытка**: При ошибке — планировщик планирует повторную отправку.
8.  **Удаление**: После исчерпания попыток или при превышении лимита очереди — чанк удаляется (или помещается в DLQ при `storage.keep.rejected`).

### Глобальные настройки слоя хранения (`service:`)

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `storage.path` | Путь к директории на диске для хранения чанков. Без этого параметра filesystem-буферизация недоступна. | Не задано |
| `storage.type` | Режим буферизации по умолчанию для всех входов: `memory`, `filesystem`, `memrb`. | `memory` |
| `storage.inherit` | Наследуют ли плагины ввода `storage.type` из глобальных настроек. При `on` входы без явного `storage.type` используют глобальное значение. | `off` |
| `storage.sync` | Режим синхронизации с диском: `normal` (по умолчанию), `full` (полная синхронизация, медленнее, но надежнее). | `normal` |
| `storage.checksum` | Контрольная сумма чанков при записи на диск: `off`, `crc32`. Защита от повреждения данных. | `off` |
| `storage.max_chunks_up` | Лимит чанков, которые могут одновременно находиться в памяти. При превышении новые чанки записываются только на диск. | `128` |
| `storage.backlog.mem_limit` | Лимит памяти для подгрузки старых данных (бэклога) после перезапуска агента. | `5M` |
| `scheduler.cap` | Максимальное время ожидания перед повторной попыткой (секунды). | `2000` |
| `scheduler.base` | База экспоненциального отката для расчета времени повторной попытки. | `5` |

### Параметры ввода (per-input)

Плагины ввода имеют собственные параметры для контроля буферизации:

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `storage.type` | Режим буферизации для данного ввода: `memory`, `filesystem`, `memrb`. Переопределяет глобальное значение. | `memory` |
| `mem_buf_limit` | Лимит памяти для данных плагина. При достижении: для `memory` — пауза ввода; для `memrb` — удаление старых чанков. | `0` (без ограничений) |
| `storage.pause_on_chunks_overlimit` | Поведение при превышении `storage.max_chunks_up`: `on` — полная остановка ввода; `off` — запись только на диск. | `off` |
| `rate_gate` | Включение Rate Gate — контроля скорости поступления данных. При превышении лимита — пауза ввода. | `false` |
| `rate_gate.max_bytes` | Максимальная скорость поступления байтов в секунду. `0` — без ограничений. | `0` |
| `rate_gate.max_records` | Максимальная скорость поступления записей в секунду. `0` — без ограничений. | `0` |
| `rate_gate.resume_ratio` | Порог возобновления ввода (отношение к лимиту). Ввод возобновляется, когда скорость падает ниже этого порога. | `0.80` |
| `rate_window` | Окно времени для расчета скорости поступления (секунды). | `1s` |
| `rate_gate.backpressure` | Учет давления повторных попыток и активных чанков при расчете эффективной скорости. | `true` |

### Параметры вывода (per-output)

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `storage.total_limit_size` | Максимальный размер очереди чанков на диске для данного вывода. При достижении — удаление самых старых чанков. | Без ограничений |
| `retry_limit` | Максимальное количество повторных попыток: `N` (число), `false`/`no_limits` (бесконечно), `no_retries` (без повторов). | `1` |

### Механизм управления нагрузкой (Backpressure)

Для предотвращения падения агента по OOM (Out of Memory) используются несколько уровней защиты:

1.  **Лимит плагина ввода (`mem_buf_limit`)**: Ограничивает объем данных, который плагин может держать в памяти. При достижении лимита:
    *   В режиме `memory`: плагин переходит в состояние `pause`.
    *   В режиме `memrb`: старые чанки автоматически удаляются.

2.  **Лимит активных чанков (`storage.max_chunks_up`)**: Если активных чанков в RAM больше лимита, новые чанки записываются **только на диск** (состояние `down`), минуя память. Поведение при превышении зависит от `storage.pause_on_chunks_overlimit`.

3.  **Rate Gate (v5.1+)**: Контроль скорости поступления данных. При превышении заданной скорости (байты/с или записи/с) плагин ввода автоматически ставится на паузу. Возобновление происходит, когда скорость падает ниже порога `resume_ratio`.

4.  **Лимит очереди вывода (`storage.total_limit_size`)**: При превышении размера очереди для конкретного вывода самые старые чанки удаляются, чтобы освободить место для новых.

5.  **Принудительная пауза (`storage.pause_on_chunks_overlimit`)**: Если включено (`on`), входной плагин полностью останавливает прием данных, пока количество активных чанков не снизится.

### Механизм повторных попыток (Retries)

При ошибке отправки данных планировщик планирует повторную попытку с экспоненциальным откатом и джиттером:

*   Время ожидания — случайное число между `scheduler.base` (нижняя граница) и `min(base * 2^N, scheduler.cap)` (верхняя граница), где N — номер попытки.
*   Пример: `base=5`, `cap=300`:
    *   1-я попытка: случайное число от 5 до 10 секунд.
    *   2-я попытка: от 5 до 20 секунд.
    *   3-я попытка: от 5 до 40 секунд.
    *   ...
    *   N-я попытка: от 5 до 300 секунд (верхняя граница `cap`).

**Настройка retry_limit для вывода:**

| Значение | Поведение |
|:---|:---|
| `N` (число >= 1) | Максимум N повторных попыток, затем данные отбрасываются. |
| `false` или `no_limits` | Бесконечные повторные попытки (данные никогда не отбрасываются). |
| `no_retries` | Повторы отключены. При первой ошибке данные отбрасываются немедленно. |

**Dead Letter Queue**: Для сохранения отброшенных данных включите `storage.keep.rejected: on` в секции `service`. Отброшенные чанки сохраняются на диске для последующего анализа.

### Логика маршрутизации

Fluent Bit поддерживает три подхода к маршрутизации:

#### Маршрутизация по тегам (Tag-based)

Классический подход, основанный на сопоставлении тегов:

*   **Match**: Использует маски (`*` — один сегмент, `**` — любой путь). Пример: `kube.*` соответствует `kube.prod` и `kube.dev`.
*   **Match_Regex**: Использует регулярные выражения для более сложных правил (например, исключение определенных пространств имен).

#### Условная маршрутизация (Conditional — v4.2+)

Маршрутизация на уровне отдельных записей на основе их содержимого. Определяется в блоке `routes` внутри конфигурации плагина ввода.

**Операторы сравнения:** `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `regex`, `not_regex`.

**Контексты (context):** `body` (по умолчанию), `metadata`, `group_attributes`, `group_metadata`, `otel_resource_attributes`, `otel_scope_attributes`, `otel_scope_metadata`.

#### Маршрутизация по меткам (Label-based — v4.2+)

Автоматически используется при условной маршрутизации. Сохраняет метки (labels) и имена плагинов в метаданных чанков, обеспечивая стабильную маршрутизацию после перезапусков и изменений конфигурации.

**Порядок сопоставления:** alias -> сгенерированное имя (`{plugin}.{sequence}`) -> числовой ID.

## Практические сценарии

### Сценарий 1: Конфигурация для высоконагруженных Production-сред

Настройка с максимальной надежностью и защитой от переполнения памяти.

```yaml
service:
  flush: 1
  log_level: info
  http_server: on
  http_listen: 0.0.0.0
  http_port: 2020

  # Глобальные настройки хранения
  storage.path: /var/lib/fluent-bit/storage/
  storage.type: filesystem
  storage.inherit: on
  storage.sync: normal
  storage.max_chunks_up: 256
  storage.backlog.mem_limit: 15M

  # Настройка повторных попыток
  scheduler.base: 3
  scheduler.cap: 30

pipeline:
  inputs:
    - name: tail
      tag: kube.*
      path: /var/log/containers/*.log
      parser: cri
      storage.type: filesystem
      mem_buf_limit: 20MB

  outputs:
    - name: es
      match: kube.*
      host: elasticsearch.logging.svc
      port: 9200
      retry_limit: false
      storage.total_limit_size: 500MB
```

**Эквивалент в Classic формате:**

```ini
[SERVICE]
    Flush                     1
    Log_Level                 info
    HTTP_Server               On
    HTTP_Listen               0.0.0.0
    HTTP_Port                 2020
    Storage.Path              /var/lib/fluent-bit/storage/
    Storage.Type              filesystem
    Storage.Inherit           on
    Storage.Sync              normal
    Storage.Max_Chunks_Up     256
    Storage.Backlog.Mem_Limit 15M
    Scheduler.Base            3
    Scheduler.Cap             30

[INPUT]
    Name                      tail
    Tag                       kube.*
    Path                      /var/log/containers/*.log
    Parser                    cri
    Storage.Type              filesystem
    Mem_Buf_Limit             20MB

[OUTPUT]
    Name                      es
    Match                     kube.*
    Host                      elasticsearch.logging.svc
    Port                      9200
    Retry_Limit               False
    Storage.Total_Limit_Size  500MB
```

### Сценарий 2: Маршрутизация на основе пространств имен (Namespaces)

Разделение потоков данных для разных команд.

```yaml
pipeline:
  inputs:
    - name: tail
      tag: kube.*
      path: /var/log/containers/*.log
      parser: cri

  filters:
    - name: kubernetes
      match: kube.*
      merge_log: on

  outputs:
    # Логи безопасности (namespace: security)
    - name: es
      match_regex: ^kube\.var\.log\.containers\..*_security_.*$
      host: es-security.internal
      index: security-logs
      logstash_format: on

    # Все остальные логи
    - name: es
      match: kube.*
      host: es-general.internal
      index: general-logs
      logstash_format: on
```

### Сценарий 3: Динамическая маршрутизация через Rewrite_Tag

Изменение тега записи на основе её содержимого (например, уровня логирования).

```yaml
pipeline:
  inputs:
    - name: tail
      tag: kube.*
      path: /var/log/containers/*.log
      parser: cri

  filters:
    - name: kubernetes
      match: kube.*
      merge_log: on

    - name: rewrite_tag
      match: kube.*
      rule: $level ^(ERROR)$ alert.error false
      rule: $level ^(WARN)$ alert.warn false

  outputs:
    - name: slack
      match: alert.error
      webhook: https://hooks.slack.com/services/XXX/YYY/ZZZ

    - name: es
      match: kube.*
      host: elasticsearch.logging.svc
      index: all-logs
      logstash_format: on
```

### Сценарий 4: Условная маршрутизация (Conditional Routing)

Маршрутизация записей по содержимому поля `level` без использования фильтра `rewrite_tag`.

```yaml
pipeline:
  inputs:
    - name: tail
      path: /var/log/app/*.log
      tag: app.logs
      routes:
        logs:
          - name: error_logs
            condition:
              op: or
              rules:
                - field: "$level"
                  op: eq
                  value: "error"
                - field: "$level"
                  op: eq
                  value: "fatal"
            to:
              outputs:
                - error_destination

          - name: info_logs
            condition:
              op: and
              rules:
                - field: "$level"
                  op: eq
                  value: "info"
            to:
              outputs:
                - info_destination

          - name: default_logs
            condition:
              default: true
            to:
              outputs:
                - default_destination

  outputs:
    - name: es
      alias: error_destination
      host: errors.example.com
      index: error-logs
      logstash_format: on
      retry_limit: false

    - name: es
      alias: info_destination
      host: logs.example.com
      index: info-logs
      logstash_format: on

    - name: stdout
      alias: default_destination
```

### Сценарий 5: Условная маршрутизация по нескольким полям

Комбинирование условий для точной фильтрации: ошибки в production с временем ответа > 5 секунд.

```yaml
pipeline:
  inputs:
    - name: tail
      path: /var/log/app/*.log
      tag: app.logs
      routes:
        logs:
          - name: high_priority_errors
            condition:
              op: and
              rules:
                - field: "$level"
                  op: eq
                  value: "error"
                - field: "$environment"
                  op: eq
                  value: "production"
                - field: "$response_time"
                  op: gt
                  value: 5000
            to:
              outputs:
                - pagerduty_output
                - elasticsearch_output

          - name: all_logs
            condition:
              default: true
            to:
              outputs:
                - elasticsearch_output

  outputs:
    - name: http
      alias: pagerduty_output
      host: events.pagerduty.com
      uri: /v2/enqueue
      format: json

    - name: es
      alias: elasticsearch_output
      host: logs.example.com
      index: application-logs
      logstash_format: on
```

### Сценарий 6: Rate Gate — контроль скорости входа (v5.1+)

Ограничение скорости поступления данных для предотвращения перегрузки агента.

```yaml
pipeline:
  inputs:
    - name: forward
      tag: logs.*
      rate_window: 1s
      rate_gate: true
      rate_gate.max_bytes: 5M
      rate_gate.max_records: 10000
      rate_gate.resume_ratio: 0.80

  outputs:
    - name: es
      match: logs.*
      host: elasticsearch.logging.svc
      retry_limit: false
```

**Classic формат:**

```ini
[INPUT]
    Name                     forward
    Tag                      logs.*
    Rate_Window              1s
    Rate_Gate                true
    Rate_Gate.Max_Bytes      5M
    Rate_Gate.Max_Records    10000
    Rate_Gate.Resume_Ratio   0.80

[OUTPUT]
    Name        es
    Match       logs.*
    Host        elasticsearch.logging.svc
    Retry_Limit False
```

### Сценарий 7: Memory Ring Buffer для метрик

Использование кольцевого буфера для сбора метрик, где допустима потеря старых данных.

```yaml
service:
  storage.path: /var/lib/flb-storage/
  storage.max_chunks_up: 64

pipeline:
  inputs:
    - name: cpu
      tag: metrics.cpu
      storage.type: memrb
      mem_buf_limit: 10M

    - name: mem
      tag: metrics.mem
      storage.type: memrb
      mem_buf_limit: 10M

  outputs:
    - name: prometheus_remote_write
      match: metrics.*
      host: prometheus.internal
      port: 9090
      storage.total_limit_size: 50M
      retry_limit: 3
```

### Сценарий 8: Dead Letter Queue (DLQ)

Сохранение отброшенных данных для последующего анализа.

```yaml
service:
  storage.path: /var/lib/flb-storage/
  storage.type: filesystem
  storage.keep.rejected: on

pipeline:
  inputs:
    - name: tail
      tag: app.*
      path: /var/log/app/*.log
      storage.type: filesystem

  outputs:
    - name: es
      match: app.*
      host: elasticsearch.logging.svc
      retry_limit: 5
```

Отброшенные чанки сохраняются в директории `storage.path/rejected/` и могут быть проанализированы позднее.

### Сценарий 9: Маршрутизация с Regex для безопасности

Маршрутизация событий безопасности на основе содержимого сообщения.

```yaml
pipeline:
  inputs:
    - name: tail
      path: /var/log/app/*.log
      tag: app.logs
      routes:
        logs:
          - name: security_events
            condition:
              op: or
              rules:
                - field: "$message"
                  op: regex
                  value: "(?i)(unauthorized|forbidden|authentication failed)"
                - field: "$event_type"
                  op: regex
                  value: "^security\\."
            to:
              outputs:
                - security_output

          - name: other_logs
            condition:
              default: true
            to:
              outputs:
                - general_output

  outputs:
    - name: splunk
      alias: security_output
      host: security-splunk.example.com
      port: 8088
      tls: on

    - name: es
      alias: general_output
      host: logs.example.com
      index: app-logs
      logstash_format: on
```

### Сценарий 10: label-based matching для стабильной маршрутизации

Использование alias для обеспечения стабильной маршрутизации после перезапусков.

```yaml
pipeline:
  inputs:
    - name: tail
      path: /var/log/app/*.log
      tag: app.logs
      routes:
        logs:
          - name: production_logs
            condition:
              op: and
              rules:
                - field: "$environment"
                  op: eq
                  value: "production"
            to:
              outputs:
                - prod_logs_output

          - name: development_logs
            condition:
              op: and
              rules:
                - field: "$environment"
                  op: eq
                  value: "development"
            to:
              outputs:
                - dev_logs_output

  outputs:
    - name: es
      alias: prod_logs_output
      host: prod-logs.example.com
      index: production-logs

    - name: es
      alias: dev_logs_output
      host: dev-logs.example.com
      index: development-logs
```

Метки (`prod_logs_output`, `dev_logs_output`) сохраняются в метаданных чанков и используются для восстановления маршрутизации после перезапусков.

## Валидация и диагностика

### Проверка конфигурации

1.  **Синтаксическая проверка:**
    ```bash
    # Проверка YAML-конфигурации
    fluent-bit --config /etc/fluent-bit/fluent-bit.yaml --dry-run
    # Проверка Classic-конфигурации
    fluent-bit --config /etc/fluent-bit/fluent-bit.conf --dry-run
    ```

2.  **Проверка доступных плагинов:**
    ```bash
    fluent-bit -L | grep -E "storage|buffer"
    ```

### Мониторинг через HTTP API

Fluent Bit предоставляет API для диагностики буферизации и маршрутизации:

```bash
# Статус хранилища (количество чанков up/down)
curl -s http://localhost:2020/api/v1/storage | jq

# Метрики (включая метрики маршрутизации v4.2+)
curl -s http://localhost:2020/api/v1/metrics | jq

# Метрики в формате Prometheus
curl -s http://localhost:2020/api/v1/metrics/prometheus
```

### Ключевые метрики для мониторинга

| Метрика | Описание | Норма |
|:---|:---|:---|
| `fluentbit_storage_layer_chunks_up` | Активные чанки в памяти | < `storage.max_chunks_up` |
| `fluentbit_storage_layer_chunks_down` | Чанки только на диске | Стабильное или убывающее |
| `fluentbit_storage_layer_total_chunks` | Общее количество чанков | Не растет монотонно |
| `fluentbit_output_errors_total` | Ошибки отправки | 0 |
| `fluentbit_output_retries_total` | Количество повторных попыток | Стабильное |
| `fluentbit_routing_logs_records_total` | Записи, маршрутизированные по маршрутам | Растет линейно |
| `fluentbit_routing_logs_drop_records_total` | Записи, отброшенные при маршрутизации | 0 |
| `memrb_dropped_chunks` | Чанки, отброшенные кольцевым буфером | 0 (для memrb) |
| `memrb_dropped_bytes` | Байты, отброшенные кольцевым буфером | 0 (для memrb) |

## Типовые ошибки и их решение

### Ошибка 1: OOM Kill агента Fluent Bit

**Симптом:** Процесс Fluent Bit убит ядром Linux (OOM Killer).

**Причины:**
*   `mem_buf_limit` не установлен или слишком велик.
*   `storage.max_chunks_up` слишком велик для доступной памяти.
*   Фильтры потребляют слишком много памяти (например, тяжелые regex-операции).

**Решение:**
1.  Установить `mem_buf_limit` на уровне 60-70% от лимита контейнера.
2.  Уменьшить `storage.max_chunks_up` (например, с 128 до 64).
3.  Включить `storage.pause_on_chunks_overlimit: on` для полной остановки при переполнении.
4.  Переключиться на `storage.type: filesystem` для тяжелых нагрузок.

### Ошибка 2: Данные не доходят до хранилища

**Симптом:** Логи есть в `journalctl`, но отсутствуют в Elasticsearch/Loki.

**Диагностика:**
1.  Проверить метрику `fluentbit_output_errors_total`.
2.  Проверить метрику `fluentbit_output_retries_total` — если растет, хранилище недоступно.
3.  Проверить доступность хранилища: `curl -I http://elasticsearch:9200`.

**Решение:**
*   При недоступности хранилища: установить `retry_limit: false` для бесконечных повторов.
*   При проблемах с сетью: увеличить `scheduler.cap` для более длительного ожидания.
*   Включить `storage.keep.rejected: on` для сохранения отброшенных данных.

### Ошибка 3: Старые данные не загружаются после перезапуска

**Симптом:** После перезапуска Fluent Bit теряет данные, которые были в буфере.

**Причина:** `storage.backlog.mem_limit` слишком мал для объема незавершенных данных.

**Решение:**
1.  Увеличить `storage.backlog.mem_limit` (например, с `5M` до `128M`).
2.  Убедиться, что `storage.path` указан и директория доступна для записи.
3.  Проверить права доступа к директории хранения.

### Ошибка 4: Записи отбрасываются при маршрутизации

**Симптом:** Метрика `fluentbit_routing_logs_drop_records_total` растет.

**Причины:**
*   Тег записи не соответствует ни одному правилу `Match`/`Match_Regex`.
*   При условной маршрутизации: запись не соответствует ни одному условию и нет маршрута по умолчанию.

**Решение:**
1.  Добавить маршрут по умолчанию (`condition: default: true`).
2.  Проверить правила `Match` на соответствие тегам входов.
3.  Включить `log_level: debug` для просмотра ошибок маршрутизации.

### Ошибка 5: Высокое потребление дискового пространства

**Симптом:** Директория `storage.path` стремительно растет.

**Причины:**
*   Хранилище недоступно, данные накапливаются в очередях.
*   `storage.total_limit_size` не установлен для выводов.

**Решение:**
1.  Установить `storage.total_limit_size` для каждого вывода.
2.  Проверить доступность хранилища и исправить проблемы сети.
3.  Настроить мониторинг дискового пространства и алертирование.

### Ошибка 6: Memory Ring Buffer отбрасывает слишком много данных

**Симптом:** Метрики `memrb_dropped_chunks` и `memrb_dropped_bytes` растут.

**Причина:** Размер кольцевого буфера (`mem_buf_limit`) слишком мал для объема поступающих данных.

**Решение:**
1.  Увеличить `mem_buf_limit` для входа.
2.  Оптимизировать обработку данных (фильтры, парсеры) для ускорения сброса.
3.  Рассмотреть использование filesystem-буфера вместо memrb.

## Best Practices и особенности

### Производительность

1.  **Filesystem для Production**: Всегда используйте `storage.type: filesystem` в Production-средах. Это обеспечивает персистентность данных между перезапусками и защиту от потерь.
2.  **Memory-only для разработки**: Используйте `storage.type: memory` только в dev/test средах, где потеря данных допустима.
3.  **memrb для метрик**: Кольцевой буфер подходит для метрик и телеметрии, где важна непрерывность сбора, а потеря части истории допустима.
4.  **`storage.inherit: on`**: Установите этот параметр, чтобы не указывать `storage.type` для каждого входа отдельно.

### Управление обратным давлением

1.  **`mem_buf_limit`**: Устанавливайте на уровне 60-70% от лимита памяти контейнера. Остальное — для фильтров и метаданных.
2.  **`storage.pause_on_chunks_overlimit: on`**: Включите в критичных сценариях для полной остановки при переполнении, чтобы избежать OOM.
3.  **Rate Gate (v5.1+)**: Используйте для контроля скорости поступления данных от источников с всплесками нагрузки (bursty sources).
4.  **`storage.total_limit_size`**: Всегда устанавливайте для каждого вывода, чтобы контролировать дисковое пространство.

### Маршрутизация

1.  **Tag-based для простых случаев**: Когда маршрутизация определяется источником данных (input tag).
2.  **Conditional routing (v4.2+)**: Когда нужно маршрутизировать по содержимому записи (уровень лога, имя сервиса,环境).
3.  **Label-based matching**: Всегда используйте `alias` для выводов при условной маршрутизации — это обеспечивает стабильную маршрутизацию после перезапусков.
4.  **Маршрут по умолчанию**: Всегда определяйте маршрут по умолчанию (`condition: default: true`) для условной маршрутизации, чтобы избежать потери записей.

### Повторные попытки

1.  **`retry_limit: false`**: Для критичных данных (аудит, безопасность), где потеря недопустима.
2.  **`retry_limit: N`**: Для некритичных данных (метрики, debug-логи), где старые данные теряют ценность.
3.  **`storage.keep.rejected: on`**: Включайте для сохранения отброшенных данных и последующего анализа.
4.  **`scheduler.base` и `scheduler.cap`**: Настраивайте в зависимости от характера сбоев (кратковременные vs длительные).

### Edge Cases и ограничения

*   **Размер чанка**: Средний размер чанка — 2 MB. Один чанк не может быть разбит для частичной отправки.
*   **Irrecoverable чанки**: При повреждении структуры чанка (неверный layout или заголовок) Fluent Bit помечает его как irrecoverable и отбрасывает с логированием ошибки.
*   **Условная маршрутизация (v4.2+)**: Поддерживается только для логов. Для метрик и трассировок условная маршрутизация пока не реализована.
*   **`storage.total_limit_size`**: Работает только при включенной filesystem-буферизации. Для memory-only режима этот параметр игнорируется.
*   **Rate Gate (v5.1+)**: Доступен только в Fluent Bit 5.1 и выше. Для более ранних версий используйте `mem_buf_limit` и `storage.pause_on_chunks_overlimit`.
*   **`storage.inherit`**: При `off` каждый вход использует `storage.type: memory` по умолчанию, даже если глобально задан другой режим.
*   **Dead Letter Queue**: Отброшенные чанки хранятся в `storage.path/rejected/`. При нехватке дискового пространства они будут удалены без уведомления.

## Дополнительная информация

*   [Конфигурация Fluent Bit](./fluentbit_configuration.md) — детали настройки секций `[SERVICE]` и `[INPUT]`.
*   [Парсинг логов в Fluent Bit](./parsing.md) — как структурировать данные для эффективной маршрутизации.
*   [Сравнение Fluent Bit и Fluentd](./fluent_comparison.md) — почему Fluent Bit эффективнее для буферизации на узлах.
