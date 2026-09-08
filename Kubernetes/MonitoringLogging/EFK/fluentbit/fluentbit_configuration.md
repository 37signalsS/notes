# Конфигурация Fluent Bit

## Определения

**Секция `[SERVICE]` (или `service:`)** — блок глобальных настроек движка Fluent Bit, определяющий интервалы сброса данных, уровни логирования, параметры буферизации, HTTP-сервер для мониторинга и механизмы перезагрузки.

**Секция `[INPUT]` (или `inputs:`)** — блок конфигурации источников данных (плагинов ввода). Каждому входу присваивается тег (Tag) для дальнейшей маршрутизации. Поддерживает базовые параметры буферизации и контроля обратного давления.

**Секция `[FILTER]` (или `filters:`)** — правила модификации, обогащения или фильтрации записей. Применяются ко всем записям, теги которых соответствуют параметру `Match`. Порядок фильтров критичен — они выполняются последовательно.

**Секция `Processors` (версия 3.0+)** — механизм обработки данных, доступный только в YAML-конфигурации. Процессоры привязываются напрямую к конкретному плагину ввода или вывода и работают в его потоке, снижая нагрузку на основной цикл событий.

**Секция `[OUTPUT]` (или `outputs:`)** — блок конфигурации назначений (плагинов вывода) для отправки данных в системы хранения или анализа. Поддерживает собственные настройки буферизации и повторных попыток.

**Секция `[PARSER]` (или `parsers:`)** — определения именованных правил разбора логов (парсеров). Используются плагинами ввода и фильтрами для структурирования неструктурированных данных. Детали в [parsing.md](./parsing.md).

**Hot Reload** — механизм применения изменений в конфигурации без полной остановки и перезапуска процесса Fluent Bit. Активируется через сигнал `SIGHUP` или HTTP API (`/api/v2/reload`).

**Environment Variables** — переменные окружения, которые можно использовать в конфигурационных файлах через синтаксис `${VARIABLE}` или `${VARIABLE:-default_value}`.

**Include Directives** — директивы `@include` (Classic) или `includes:` (YAML) для разбиения конфигурации на логические файлы и переиспользования общих секций.

---

## Основные концепции

### Форматы конфигурации

Fluent Bit поддерживает два основных формата конфигурации:

1.  **Classic (INI-подобный)**: Использует расширение `.conf`. Традиционный формат, простой, но не поддерживает новые функции, такие как процессоры (v3.0+).
    ```ini
    [SERVICE]
        Flush         5
        Log_Level     info
        HTTP_Server   On
        HTTP_Port     2020

    [INPUT]
        Name          tail
        Path          /var/log/containers/*.log
        Tag           kube.*

    [OUTPUT]
        Name          es
        Match         kube.*
        Host          elasticsearch.logging.svc
    ```

2.  **YAML (YAML Ain't Markup Language)**: Использует расширение `.yaml`. Рекомендуемый формат для современных развертываний (v3.x+), так как он поддерживает типизацию сигналов (логи, метрики, трассировки), процессоры и более читаемую структуру.
    ```yaml
    service:
        flush: 5
        log_level: info
        http_server: on
        http_port: 2020

    pipeline:
        inputs:
            - name: tail
              path: /var/log/containers/*.log
              tag: kube.*

        outputs:
            - name: es
              match: kube.*
              host: elasticsearch.logging.svc
    ```

### Жизненный цикл записи

Каждая запись проходит через строго определенную последовательность этапов в конвейере (pipeline):

```
[INPUT] → [PROCESSORS] → [FILTER] → [PROCESSORS] → [OUTPUT]
   ↓          ↓             ↓             ↓            ↓
  Сбор    →  Разбор      → Обработка   → Финализация → Отправка
```

**Подробности:** Механизмы буферизации, повторных попыток и маршрутизации описаны в [buffering_routing.md](./buffering_routing.md). Механизмы парсинга и декодирования — в [parsing.md](./parsing.md).

### Секция `service`: Глобальные настройки

Полный список параметров секции `service`:

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `flush` | Интервал сброса данных из буфера в секундах. Определяет, как часто Fluent Bit будет пытаться отправить накопленные данные. | `5` |
| `daemon` | Режим запуска: `on` — фоновый демон (вramework), `off` — передний план (foreground). В контейнерах рекомендуется `off`. | `off` |
| `log_level` | Уровень логирования: `error`, `warning`, `info`, `debug`, `trace`. `trace` генерирует огромный объем данных — использовать только для диагностики. | `info` |
| `parsers_file` | Путь к файлу с определениями парсеров. Поддерживает как `.conf` (Classic), так и `.yaml` (v3.x+) форматы. | `parsers.conf` |
| `http_server` | Включение HTTP-сервера для метрик и API управления. | `off` |
| `http_listen` | IP-адрес для прослушивания HTTP-запросов. `0.0.0.0` — все интерфейсы. | `0.0.0.0` |
| `http_port` | Порт HTTP-сервера. | `2020` |
| `health_check` | Включение health-check эндпоинта (`/api/v1/health`) для оркестраторов (Kubernetes liveness/readiness probes). | `off` |
| `hot_reload` | Включение горячей перезагрузки через `SIGHUP` или HTTP API (`POST /api/v2/reload`). | `off` |
| `grace` | Время ожидания (секунды) при завершении работы для завершения активных операций. | `5` |
| `storage.path` | Путь к директории на диске для файловой буферизации. Без этого параметра filesystem-буферизация недоступна. | *не задано* |
| `storage.sync` | Режим синхронизации с диском: `normal` (по умолчанию), `full` (полная синхронизация, медленнее, но надежнее). | `normal` |
| `storage.checksum` | Контрольная сумма чанков: `off`, `crc32`. Защита от повреждения данных при записи на диск. | `off` |
| `storage.max_chunks_up` | Лимит чанков, которые могут одновременно находиться в памяти. При превышении новые чанки записываются только на диск. | `128` |
| `storage.backlog.mem_limit` | Лимит памяти для подгрузки старых данных (бэклога) после перезапуска агента. | `5M` |
| `storage.inherit` | Наследуют ли плагины ввода `storage.type` из глобальных настроек. При `on` входы без явного `storage.type` используют глобальное значение. | `off` |
| `storage.type` | Режим буферизации по умолчанию: `memory`, `filesystem`, `memrb` (Memory Ring Buffer, v5.1+). | `memory` |
| `scheduler.cap` | Максимальное время ожидания перед повторной попыткой (секунды). | `2000` |
| `scheduler.base` | База экспоненциального отката для расчета времени повторной попытки. | `5` |
| `storage.total_limit_size` | Глобальный лимит дискового пространства для всех очередей. | *без ограничений* |
| `storage.keep.rejected` | Сохранять отброшенные чанки в DLQ (Dead Letter Queue) после исчерпания попыток. | `off` |

**Пример полной конфигурации (YAML):**

```yaml
service:
    flush:           1
    daemon:          off
    log_level:       info
    grace:           5

    # Путь к файлу с определениями парсеров
    parsers_file:    parsers.yaml

    # HTTP-сервер для мониторинга и API
    http_server:     on
    http_listen:     0.0.0.0
    http_port:       2020
    health_check:    on

    # Горячая перезагрузка
    hot_reload:      on

    # Глобальные настройки хранения (Storage Layer)
    storage.path:              /var/lib/fluent-bit/storage/
    storage.type:              filesystem
    storage.sync:              normal
    storage.backlog.mem_limit: 128M
    storage.max_chunks_up:     256
    storage.inherit:           on
    storage.checksum:          crc32
    storage.keep.rejected:     on

    # Настройка повторных попыток
    scheduler.cap:  30
    scheduler.base: 3
```

**Пример полной конфигурации (Classic):**

```ini
[SERVICE]
    Flush                     1
    Daemon                    Off
    Log_Level                 info
    Grace                     5
    Parsers_File              parsers.conf
    HTTP_Server               On
    HTTP_Listen               0.0.0.0
    HTTP_Port                 2020
    Health_Check              On
    Hot_Reload                On
    Storage.Path              /var/lib/fluent-bit/storage/
    Storage.Type              filesystem
    Storage.Sync              normal
    Storage.Backlog.Mem_Limit 128M
    Storage.Max_Chunks_Up     256
    Storage.Inherit           on
    Storage.Checksum          crc32
    Storage.Keep.Rejected     on
    Scheduler.Cap             30
    Scheduler.Base            3
```

> **Примечание:** Несмотря на переход на YAML, Fluent Bit сохраняет обратную совместимость, поэтому директива `parsers_file: parsers.conf` (Classic формат) по-прежнему широко встречается и корректно обрабатывается движком.

### Секция `pipeline`: Сбор и обработка

#### Ввод данных (Inputs) и Процессоры

В версии 3.x+ процессоры позволяют выполнять тяжелые операции (например, SQL-фильтрацию или разбор JSON) непосредственно в потоке плагина ввода, не нагружая основной цикл событий.

```yaml
pipeline:
    inputs:
        - name: tail
          tag:  kube.*
          path: /var/log/containers/*.log
          # Использование процессоров (только в YAML, v3.0+)
          processors:
              logs:
                  - name: content_modifier
                    action: insert
                    key: cluster_name
                    value: production-01
```

**Примечание:** Подробности разбора строк и использования регулярных выражений приведены в [parsing.md](./parsing.md).

#### Фильтрация и обогащение (Filters)

Классический способ обработки, основанный на тегах. Плагин `kubernetes` является стандартом для обогащения логов метаданными из Kubernetes API.

```yaml
    filters:
        - name: kubernetes
          match: kube.*
          merge_log: on
          keep_log: off
          # Использовать аннотации подов для выбора парсера
          k8s-logging.parser: on
```

#### Доставка данных (Outputs)

```yaml
    outputs:
        - name:  es
          match: kube.*
          host:  elasticsearch-master.logging.svc
          port:  9200
          logstash_format: on
          logstash_prefix: k8s-logs
          # Бесконечные попытки отправки при сбоях
          retry_limit:     false
          # Количество потоков для параллельной отправки
          workers:         2
```

Детали механизмов надежности и дисковой буферизации описаны в [buffering_routing.md](./buffering_routing.md).

---

## Основные плагины ввода (INPUT)

Fluent Bit включает более 30 плагинов ввода. Ниже описаны наиболее широко используемые в контексте DevOps/SRE.

### Плагин `tail` — чтение файлов логов

Основной плагин для сбора логов из файлов. Используется для чтения логов контейнеров (Kubernetes), системных логов и логов приложений.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `path` | Путь к файлу или маска (glob). Несколько путей через запятую. | *обязательный* |
| `tag` | Тег для маршрутизации. Поддерживает wildcard `*`. | *обязательный* |
| `parser` | Имя парсера для разбора строк. Детали в [parsing.md](./parsing.md). | *нет* |
| `multiline.parser` | Имя многострочного парсера (одно или через запятую). | *нет* |
| `read_from_head` | Начать чтение с начала файла (а не только новых строк). | `false` |
| `refresh_interval` | Интервал проверки наличия новых данных (секунды). | `10` |
| `skip_long_lines` | Пропускать строки длиннее `buffer_max_size`. | `off` |
| `buffer_max_size` | Максимальный размер буфера (в байтах, с суффиксами: `KB`, `MB`). | `32K` |
| `mem_buf_limit` | Лимит памяти для данных плагина. При достижении — пауза ввода. | `0` (без ограничений) |
| `db` | Путь к файлу позиций (SQLite). Сохраняет позицию чтения между перезапусками. | *нет* |
| `db.locking` | Включить эксклюзивную блокировку БД позиций. | `false` |
| `db.journal_mode` | Режим_journal SQLite: `delete`, `wal`, `truncate`, `memory`. | `delete` |
| `db.sync` | Режим синхронизации SQLite: `off`, `normal`, `full`. | `normal` |
| `storage.type` | Режим буферизации: `memory`, `filesystem`, `memrb`. | `memory` |
| `path_key` | Ключ для сохранения имени файла в записи. | *нет* |
| `rotate_wait` | Время ожидания (секунды) после ротации файла перед его закрытием. | `5` |

**Пример конфигурации (Kubernetes):**

```yaml
pipeline:
    inputs:
        - name: tail
          tag: kube.*
          path: /var/log/containers/*.log
          parser: cri
          read_from_head: false
          refresh_interval: 5
          skip_long_lines: on
          buffer_max_size: 512K
          mem_buf_limit: 50MB
          db: /var/lib/fluent-bit/tail.db
          db.journal_mode: wal
          storage.type: filesystem
          multiline.parser: java, python
```

**Сбор логов Kubernetes (DaemonSet):**

```yaml
pipeline:
    inputs:
        - name: tail
          tag: kube.*
          path: /var/log/containers/*.log
          parser: cri
          exclude_path: '["/var/log/containers/*kube-system*.log"]'
          skip_long_lines: on
          mem_buf_limit: 50MB
          db: /var/fluent-bit/state/flb_kube.db
          db.journal_mode: wal
          storage.type: filesystem
```

### Плагин `systemd` — чтение из systemd journal

Сбор логов из системного journal (systemd). Используется на хостах с systemd (большинство современных Linux-дистрибутивов).

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `tag` | Тег для маршрутизации. | *обязательный* |
| `systemd_filter` | Фильтр по полю journal (например, `_SYSTEMD_UNIT=nginx.service`). | *нет* |
| `path` | Путь к файлу journal. По умолчанию используется системный. | *нет* |
| `max_field_size` | Максимальный размер поля (байты). | `8192` |
| `strip_underscores` | Удалять начальное подчеркивание из имён полей. | `off` |

**Пример:**

```yaml
pipeline:
    inputs:
        - name: systemd
          tag: host.*
          systemd_filter: _SYSTEMD_UNIT=nginx.service
          strip_underscores: on
```

### Плагин `forward` —接收 от Forward-клиентов

Плагин для получения данных от Forward-клиентов (Fluentd, Fluent Bit). Используется для построения каскадных архитектур (agent → aggregator).

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `listen` | IP-адрес для прослушивания. | `0.0.0.0` |
| `port` | Порт для прослушивания. | `24224` |
| `tag` | Тег по умолчанию для записей без тега. | *нет* |
| `chunk_size` | Размер чанка для передачи (байты). | `8192` |

### Плагин `netif` — сетевые метрики

Сбор метрик сетевых интерфейсов (байты, пакеты, ошибки).

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `tag` | Тег для маршрутизации. | *обязательный* |
| `interface` | Имя интерфейса. `*` — все интерфейсы. | *обязательный* |
| `interval_sec` | Интервал сбора (секунды). | `1` |
| `interval_nsec` | Интервал сбора (наносекунды). | `0` |

### Плагин `proc` — метрики процессов

Сбор метрик о конкретных процессах по PID или имени.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `tag` | Тег для маршрутизации. | *обязательный` |
| `proc_name` | Имя процесса для мониторинга. | *обязательный` |
| `pid` | PID процесса (альтернатива `proc_name`). | *нет* |
| `interval_sec` | Интервал сбора (секунды). | `1` |

### Плагин `collectd_metrics` — метрики Collectd

Получение метрик от Collectd через Unix-сокет или TCP.

### Плагин `node_exporter_metrics` — метрики узла

Сбор системных метрик (CPU, RAM, диск, сеть) в формате, совместимом с Prometheus Node Exporter.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `tag` | Тег для маршрутизации. | *обязательный* |
| `scrape_interval` | Интервал сбора метрик (секунды). | `5` |
| `path.procfs` | Путь к `/proc`. | `/proc` |
| `path.sysfs` | Путь к `/sys`. | `/sys` |

### Плагин `statsd` — метрики StatsD

Приём метрик в формате StatsD (counters, gauges, timers).

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `listen` | IP-адрес для прослушивания. | `0.0.0.0` |
| `port` | Порт для прослушивания. | `8125` |
| `protocol` | Протокол: `udp`, `tcp`. | `udp` |

### Плагин `prometheus_scrape` — scrape метрик Prometheus

Сбор метрик с эндпоинтов Prometheus (pull-модель).

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `host` | Хост для scrape. | *обязательный* |
| `port` | Порт для scrape. | *обязательный* |
| `scrape_interval` | Интервал сбора (секунды). | `30` |
| `metrics_path` | Путь к метрикам. | `/metrics` |

### Плагин `random` — тестовые данные

Генерация случайных записей для тестирования. Не используется в production.

---

## Основные плагины фильтров (FILTER)

Фильтры модифицируют, обогащают или фильтруют записи после сбора. Порядок фильтров в конфигурации определяет порядок их выполнения — это критически важно для корректной работы.

### Фильтр `kubernetes` — обогащение метаданными Kubernetes

Стандартный плагин для обогащения логов метаданными из Kubernetes API (имя пода, неймспейс, аннотации, лейблы).

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `match` | Тег для сопоставления записей. Поддерживает wildcard `*`. | *обязательный* |
| `kube_url` | URL API-сервера Kubernetes. | `https://kubernetes.default.svc:443` |
| `kube_token_file` | Путь к файлу с токеном ServiceAccount. | `/var/run/secrets/kubernetes.io/serviceaccount/token` |
| `kube_ca_file` | Путь к CA-сертификату API-сервера. | `/var/run/secrets/kubernetes.io/serviceaccount/ca.crt` |
| `kube_tag_prefix` | Префикс тега для извлечения имени контейнера. | `kube.var.log.containers.` |
| `merge_log` | Объединить поле `log` с метаданными Kubernetes. | `on` |
| `merge_log_key` | Ключ для объединения лога с метаданными. | `log` |
| `keep_log` | Сохранять исходное поле `log` после объединения. | `off` |
| `k8s-logging.parser` | Включить чтение аннотаций для выбора парсера. | `off` |
| `k8s-logging.exlude` | Включить чтение аннотаций для исключения подов. | `off` |
| `labels` | Включить добавление лейблов пода в метаданные. | `on` |
| `annotations` | Включить добавление аннотаций пода в метаданные. | `off` |
| `kube_meta_cache_ttl` | Время жизни кеша метаданных (секунды). | `60` |
| `dummy_meta` | Генерировать фиктивные метаданные (для тестирования без API). | `off` |

**Пример:**

```yaml
filters:
    - name: kubernetes
      match: kube.*
      merge_log: on
      keep_log: off
      k8s-logging.parser: on
      k8s-logging.exlude: on
      labels: on
      annotations: off
      kube_meta_cache_ttl: 120
```

### Фильтр `grep` — фильтрация по значениям полей

Фильтрация записей на основе строковых совпадений в полях. Поддерживает регулярные выражения.

| Параметр | Описание |
|:---|:---|
| `match` | Тег для сопоставления записей. |
| `regex` | Регулярное выражение для поля (например, `level ^ERROR$`). |
| `exclude` | Исключить записи, совпадающие с regex. |
| `logic` | Логика комбинирования: `and`, `or`. |

**Пример (только ERROR и CRITICAL):**

```yaml
filters:
    - name: grep
      match: app.*
      regex: level ^(ERROR|CRITICAL)$
```

### Фильтр `record_modifier` — модификация полей

Добавление, удаление или изменение полей в записях. Один из самых гибких фильтров.

| Параметр | Описание |
|:---|:---|
| `match` | Тег для сопоставления. |
| `record` | Ключ-значение для добавления/изменения (многократно). |
| `remove_key` | Ключ для удаления (многократно). |
| `remove_regex` | Regex для удаления ключей. |
| `rename_key` | Переименование ключа: `old_name new_name` (многократно). |

**Пример:**

```yaml
filters:
    - name: record_modifier
      match: app.*
      record: environment production
      record: team backend
      remove_regex: ^debug_
      rename_key: host hostname
```

### Фильтр `modify` — модификация полей (альтернатива)

Плагин для модификации полей с поддержкой операций `add`, `remove`, `rename`, `set`, `copy`, `hash`, `uuid`.

**Пример:**

```yaml
filters:
    - name: modify
      match: app.*
      add: cluster prod-eu-1
      remove: debug_info
      rename: old_field new_field
```

### Фильтр `nest` — работа с вложенными полями

Преобразование вложенных структур данных (поднятие вложенных полей на верхний уровень или опускание полей во вложенность).

| Параметр | Описание |
|:---|:---|
| `operation` | Операция: `lift` (поднятие), `nest` (опускание). |
| `wildcard` | Маска ключей для операции. |
| `nested_under` | Ключ-родитель для вложенности. |
| `prefix` | Префикс для поднятых ключей. |

**Пример (поднятие полей из `kubernetes`):**

```yaml
filters:
    - name: nest
      match: kube.*
      operation: lift
      nested_under: kubernetes
      prefix: k8s_
```

### Фильтр `lua` — выполнение Lua-скриптов

Выполнение пользовательских Lua-скриптов для сложной обработки записей. Позволяет реализовать произвольную логику, которая недоступна встроенным фильтрам.

| Параметр | Описание |
|:---|:---|
| `match` | Тег для сопоставления. |
| `script` | Путь к Lua-скрипту (или inline через `call` + `code`). |
| `call` | Имя функции Lua для вызова. |
| `time_as_table` | Передавать время как таблицу Lua (а не как число). |
| `reserve_data` | Сохранять оригинальные поля после обработки. |

**Пример Lua-скрипта:**

```lua
-- /etc/fluent-bit/transform.lua
function transform(tag, timestamp, record)
    record["processed_at"] = os.time()
    record["env"] = "production"
    return 1, timestamp, record
end
```

**Конфигурация:**

```yaml
filters:
    - name: lua
      match: app.*
      script: /etc/fluent-bit/transform.lua
      call: transform
      reserve_data: on
```

### Фильтр `parser` — применение парсера к полю

Применение именованного парсера к конкретному текстовому полю записи. Позволяет распарсить вложенные данные после первичного сбора. Детали в [parsing.md](./parsing.md).

| Параметр | Описание |
|:---|:---|
| `match` | Тег для сопоставления. |
| `key_name` | Имя поля для парсинга. |
| `parser` | Имя парсера. |
| `reserve_data` | Сохранять оригинальные поля. |
| `preserve_key` | Сохранять оригинальное ключевое поле. |
| `replace_invalid_char` | Заменять невалидные UTF-8 символы. |

### Фильтр `rewrite_tag` — перезапись тегов

Динамическое изменение тега записи на основе её содержимого. Позволяет реализовать сложную маршрутизацию.

| Параметр | Описание |
|:---|:---|
| `match` | Тег для сопоставления. |
| `rule` | Правило перезаписи: `$field regex new_tag keep` |
| `emitter_name` | Имя эмиттера для метрик. |

**Пример:**

```yaml
filters:
    - name: rewrite_tag
      match: kube.*
      rule: $level ^(ERROR)$ alert.error false
      rule: $level ^(WARN)$ alert.warn false
      emitter_name: re_emitted
```

### Фильтр `throttle` — ограничение скорости

Ограничение количества записей в секунду. Полезен для предотвращения перегрузки хранилища.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `rate` | Максимальное количество запросов в секунду. | *обязательный* |
| `window` | Временное окно (секунды). | `60` |
| `interval` | Интервал сброса (секунды). | `1` |
| `print_status` | Печатать статус ограничения каждые `interval` секунд. | `true` |
| `key` | Поле для группировки (например, по namespace). | *нет* |

### Фильтр `kubernetes_events` — события Kubernetes

Сбор событий Kubernetes API и преобразование их в лог-записи.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `tag` | Тег для маршрутизации. | *обязательный* |
| `kube_url` | URL API-сервера. | `https://kubernetes.default.svc:443` |
| `kube_token_file` | Путь к файлу с токеном. | `/var/run/secrets/kubernetes.io/serviceaccount/token` |
| `kube_ca_file` | Путь к CA-сертификату. | `/var/run/secrets/kubernetes.io/serviceaccount/ca.crt` |
| `kube_namespace` | Фильтр по неймспейсу. | *все* |
| `kube_pod` | Фильтр по поду. | *все* |
| `kube_node_name` | Фильтр по нодам. | *все* |
| `interval_sec` | Интервал опроса API (секунды). | `30` |

---

## Основные плагины вывода (OUTPUT)

Плагины вывода отправляют обработанные данные в различные хранилища и системы анализа.

### Плагин `es` (Elasticsearch) — отправка в Elasticsearch/OpenSearch

Отправка логов в Elasticsearch или OpenSearch.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `match` | Тег для сопоставления записей. | *обязательный* |
| `host` | Хост Elasticsearch. | `127.0.0.1` |
| `port` | Порт Elasticsearch. | `9200` |
| `http_user` | Пользователь для аутентификации. | *нет* |
| `http_passwd` | Пароль для аутентификации. | *нет` |
| `index` | Имя индекса. | `fluent-bit` |
| `type` | Тип документа. | `_doc` |
| `logstash_format` | Использовать формат имени индекса Logstash (prefix-YYYY.MM.DD). | `off` |
| `logstash_prefix` | Префикс для имени индекса. | `fluent-bit` |
| `logstash_dateformat` | Формат даты для имени индекса. | `%Y.%m.%d` |
| `template_name` | Имя шаблона индекса. | *нет* |
| `template_file` | Путь к файлу шаблона. | *нет* |
| `retry_limit` | Количество повторных попыток: число, `false` (бесконечно), `no_retries`. | `1` |
| `workers` | Количество потоков для параллельной отправки. | `1` |
| `buffering` | Включить буферизацию перед отправкой. | `on` |
| `total_limit_size` | Максимальный размер буфера (например, `500MB`). | *без ограничений* |

**Пример:**

```yaml
outputs:
    - name: es
      match: kube.*
      host: elasticsearch-master.logging.svc
      port: 9200
      logstash_format: on
      logstash_prefix: k8s-logs
      logstash_dateformat: '%Y.%m.%d'
      retry_limit: false
      workers: 2
      total_limit_size: 1G
```

### Плагин `loki` — отправка в Grafana Loki

Отправка логов в Grafana Loki с поддержкой динамических меток и сжатия. Подробности интеграции в [fluentbit_integration.md](../../../Loki/fluentbit_integration.md).

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `match` | Тег для сопоставления. | *обязательный* |
| `host` | Хост Loki. | `127.0.0.1` |
| `port` | Порт Loki. | `3100` |
| `labels` | Метки для Loki (через запятую). | *нет* |
| `label_keys` | Ключи из записи для использования как меток. | *нет* |
| `remove_keys` | Ключи для удаления перед отправкой. | *нет` |
| `auto_kubernetes_labels` | Автоматически добавлять лейблы Kubernetes. | `off` |
| `tenant_id` | ID тенанта для multi-tenant Loki. | *нет* |
| `batch_wait` | Максимальное время ожидания формирования пакета (мс). | `1000` |
| `batch_size` | Максимальный размер пакета (байты). | `1048576` (1MB) |
| `line_format` | Формат строки лога (`key=value`, `json`). | `key=value` |
| `workers` | Количество потоков. | `1` |

**Пример:**

```yaml
outputs:
    - name: loki
      match: kube.*
      host: loki.logging.svc
      port: 3100
      labels: job=fluent-bit,namespace=$kubernetes['namespace_name'],pod=$kubernetes['pod_name']
      auto_kubernetes_labels: on
      line_format: json
      batch_wait: 500
      batch_size: 1024000
      workers: 2
```

### Плагин `stdout` — вывод в консоль

Вывод записей в STDOUT. Используется для отладки и тестирования. **Не рекомендуется для production** — генерирует огромный объем логов.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `match` | Тег для сопоставления. | `*` |
| `format` | Формат вывода: `json`, `key_value`, `csv`. | `json` |

### Плагин `file` — запись в файл

Запись логов в файлы на диске.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `match` | Тег для сопоставления. | *обязательный* |
| `path` | Директория для записи файлов. | *обязательный` |
| `file` | Имя файла (без расширения). | *нет* |
| `format` | Формат: `json`, `plain`, `csv`. | `json` |
| `delimiter` | Разделитель полей (для `csv`). | `,` |
| `label_escaping` | Экранирование меток: `off`, `dashed`, `tag`, `dashed,tag`. | `off` |
| `timestamp_key` | Ключ для временной метки. | `date` |
| `rotate_wait` | Время ожидания (секунды) перед записью в новый файл после ротации. | `5` |

**Пример:**

```yaml
outputs:
    - name: file
      match: app.*
      path: /var/log/fluent-bit
      file: app_logs
      format: json
      rotate_wait: 10
```

### Плагин `kafka` — отправка в Apache Kafka

Отправка логов в Kafka-топики.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `match` | Тег для сопоставления. | *обязательный* |
| `brokers` | Список брокеров Kafka (через запятую). | *обязательный* |
| `topics` | Имя топика (или список через запятую для маршрутизации по тегам). | *обязательный` |
| `message_key` | Ключ сообщения в Kafka. | *нет* |
| `required_acks` | Требуемое количество подтверждений: `1`, `all`, `0`. | `1` |
| `queue_full_retries` | Количество попыток при переполнении очереди. | `10` |
| `retry_full_lag_ms` | Задержка (мс) между попытками при переполнении. | `10000` |

### Плагин `forward` — отправка Forward-агентам

Отправка данных другому агенту Fluentd/Fluent Bit (каскадная архитектура).

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `match` | Тег для сопоставления. | *обязательный* |
| `host` | Хост接收ателя. | `127.0.0.1` |
| `port` | Порт接收ателя. | `24224` |
| `shared_key` | Общий ключ для аутентификации. | *нет* |
| `self_host_name` | Имя текущего хоста для идентификации. | *автоматически* |

### Плагин `http` — отправка по HTTP

Универсальный плагин для отправки данных по HTTP (webhook-интеграции).

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `match` | Тег для сопоставления. | *обязательный* |
| `host` | Хост接收ателя. | `127.0.0.1` |
| `port` | Порт接收ателя. | `80` |
| `uri` | URI для отправки. | `/` |
| `format` | Формат тела: `json`, `msgpack`. | `json` |
| `tls` | Включить TLS. | `off` |
| `tls.verify` | Проверять сертификаты. | `on` |

### Плагин `prometheus_remote_write` — отправка в Prometheus (remote write)

Отправка метрик в Prometheus через remote write API.

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `match` | Тег для сопоставления. | *обязательный* |
| `host` | Хост接收ателя. | *обязательный* |
| `port` | Порт接收ателя. | `9090` |
| `uri` | URI для remote write. | `/api/v1/write` |
| `http_user` | Пользователь для аутентификации. | *нет* |
| `http_passwd` | Пароль для аутентификации. | *нет* |
| `tls` | Включить TLS. | `off` |

---

## Процессоры (Processors)

Процессоры (v3.0+, только YAML) выполняются в потоке плагина ввода или вывода, минуя основной конвейер событий. Это снижает накладные расходы и повышает производительность.

### Основные процессоры

#### `content_modifier` — модификация содержимого

Добавление, изменение или удаление полей в записи.

```yaml
processors:
    logs:
        - name: content_modifier
          action: insert
          key: cluster
          value: prod-01

        - name: content_modifier
          action: upsert
          key: environment
          value: production

        - name: content_modifier
          action: remove
          key: debug_info
```

**Действия (action):**
- `insert` — добавить новое поле (не перезаписывает существующее)
- `upsert` — добавить или обновить поле
- `update` — обновить только существующее поле
- `remove` — удалить поле

#### `sql` — SQL-фильтрация

Фильтрация записей с использованием SQL-подобных запросов. Поддерживает операторы `WHERE`, `AND`, `OR`, `IN`, `LIKE`.

```yaml
processors:
    logs:
        - name: sql
          query: "SELECT * WHERE level IN ('ERROR', 'CRITICAL')"
```

**Примеры запросов:**

```sql
-- Только ошибки
SELECT * WHERE level = 'ERROR'

-- Ошибки в production
SELECT * WHERE level = 'ERROR' AND environment = 'production'

-- Исключение debug-логов
SELECT * WHERE level NOT IN ('DEBUG', 'TRACE')

-- Поиск по подстроке
SELECT * WHERE message LIKE '%timeout%'
```

#### `grep` — фильтрация по regex

Фильтрация записей на основе регулярных выражений.

```yaml
processors:
    logs:
        - name: grep
          regex: "level (ERROR|CRITICAL)"
```

#### `metrics_selector` — фильтрация метрик

Фильтрация и отбор метрик (не для логов).

```yaml
processors:
    metrics:
        - name: metrics_selector
          match: cpu.*
          action: include
          regex: "^cpu_.*"
```

#### `label` — работа с метками

Добавление или изменение меток (labels) для OpenTelemetry.

```yaml
processors:
    logs:
        - name: label
          action: upsert
          key: service.name
          value: my-service
```

### Порядок выполнения процессоров

Процессоры выполняются в порядке объявления:

```yaml
pipeline:
    inputs:
        - name: tail
          path: /var/log/app.log
          tag: app.logs
          processors:
              logs:
                  # 1. Сначала парсинг
                  - name: parser
                    parser: json

                  # 2. Затем модификация
                  - name: content_modifier
                    action: upsert
                    key: cluster
                    value: prod-01

                  # 3. Фильтрация
                  - name: sql
                    query: "SELECT * WHERE level IN ('ERROR', 'CRITICAL')"
```

### Выводы с процессорами

Процессоры также могут работать на этапе вывода:

```yaml
outputs:
    - name: es
      match: kube.*
      host: elasticsearch.logging.svc
      processors:
          logs:
              - name: content_modifier
                action: insert
                key: index_pattern
                value: k8s-logs-%Y.%m.%d
```

---

## Includes и Environment Variables

### Include Directives

Fluent Bit поддерживает разбиение конфигурации на отдельные файлы для модульности и переиспользования.

**Classic формат:**

```ini
# main.conf
@include inputs/*.conf
@include filters/*.conf
@include outputs/*.conf
```

**YAML формат:**

```yaml
includes:
    - inputs/*.yaml
    - filters/*.yaml
    - outputs/*.yaml
```

**Пример структуры:**

```
/etc/fluent-bit/
├── fluent-bit.yaml          # Основной файл
├── parsers.yaml             # Парсеры
├── inputs/
│   ├── tail_kubernetes.yaml
│   └── systemd_host.yaml
├── filters/
│   ├── kubernetes.yaml
│   └── geoip.yaml
└── outputs/
    ├── elasticsearch.yaml
    └── loki.yaml
```

**Ограничения:**
- `@include` поддерживает подстановочные символы (`*.conf`).
- Порядок включения файлов определяется сортировкой имён файлов.
- Рекурсивные включения (включение файла, который включает другие) не поддерживаются.

### Environment Variables

Fluent Bit поддерживает использование переменных окружения в конфигурационных файлах.

**Синтаксис:**

```yaml
service:
    log_level: ${LOG_LEVEL:-info}

outputs:
    - name: es
      host: ${ELASTICSEARCH_HOST:-elasticsearch.logging.svc}
      port: ${ELASTICSEARCH_PORT:-9200}
      http_user: ${ES_USER}
      http_passwd: ${ES_PASSWORD}
```

**Классический формат:**

```ini
[SERVICE]
    Log_Level ${LOG_LEVEL:info}

[OUTPUT]
    Name      es
    Host      ${ELASTICSEARCH_HOST:elasticsearch.logging.svc}
    Port      ${ELASTICSEARCH_PORT:9200}
    HTTP_User ${ES_USER}
    HTTP_Passwd ${ES_PASSWORD}
```

**Особенности:**
- Синтаксис: `${VARIABLE}` — переменная обязательна (запуск завершится с ошибкой, если не задана).
- Синтаксис: `${VARIABLE:-default}` — значение по умолчанию, если переменная не задана или пустая.
- Переменные окружения читаются только при запуске процесса — динамическое обновление не поддерживается.

---

## Валидация и диагностика конфигурации

### Проверка конфигурации

1. **Синтаксическая проверка (dry-run):**
    ```bash
    # YAML
    fluent-bit --config /etc/fluent-bit/fluent-bit.yaml --dry-run
    # Classic
    fluent-bit --config /etc/fluent-bit/fluent-bit.conf --dry-run
    ```
    При успешной проверке Fluent Bit выведет `configuration test is successful`. При ошибке — указание на строку и тип ошибки.

2. **Проверка доступных плагинов:**
    ```bash
    # Все плагины
    fluent-bit -L
    # Фильтрация по типу
    fluent-bit -L | grep -E "input|filter|output"
    ```

3. **Проверка парсеров:**
    ```bash
    fluent-bit -L parsers
    # Или
    fluent-bit -L | grep parser
    ```

4. **Тестовый запуск с выводом в STDOUT:**
    ```bash
    fluent-bit --config /etc/fluent-bit/test.yaml -o stdout -f
    ```

### HTTP API для диагностики

При включенном `http_server` доступны следующие эндпоинты:

| Эндпоинт | Описание |
|:---|:---|
| `GET /api/v1/health` | Health check (200 OK — здоров). |
| `GET /api/v1/metrics` | Текущие метрики в JSON. |
| `GET /api/v1/metrics/prometheus` | Метрики в формате Prometheus. |
| `GET /api/v1/plugins` | Список активных плагинов. |
| `GET /api/v1/storage` | Статус буферов и очередей. |
| `GET /api/v1/trace` | Трассировка обработки записей. |
| `POST /api/v2/reload` | Горячая перезагрузка конфигурации. |

**Примеры:**

```bash
# Проверка здоровья
curl -s http://localhost:2020/api/v1/health

# Метрики
curl -s http://localhost:2020/api/v1/metrics | jq

# Метрики Prometheus
curl -s http://localhost:2020/api/v1/metrics/prometheus

# Статус хранилища
curl -s http://localhost:2020/api/v1/storage | jq

# Список плагинов
curl -s http://localhost:2020/api/v1/plugins | jq

# Горячая перезагрузка
curl -X POST http://localhost:2020/api/v2/reload
```

### Уровни логирования для диагностики

| Уровень | Когда использовать |
|:---|:---|
| `error` | Только ошибки — нормальная работа. |
| `warning` | Предупреждения — начальная диагностика. |
| `info` | Информационные сообщения — рекомендуется для production. |
| `debug` | Подробная диагностика — для разработки и отладки. |
| `trace` | Максимальная детализация — только для временной отладки (генерирует огромный объем логов). |

**Временное включение debug-режима (без перезапуска):**

```bash
# Через API
curl -X POST http://localhost:2020/api/v2/log-level?level=debug
```

---

## Развёртывание

### Установка на Linux

**Debian/Ubuntu:**

```bash
# Добавление официального репозитория
curl https://packages.fluentbit.io/fluentbit.key | gpg --dearmor > /usr/share/keyrings/fluentbit-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/fluentbit-keyring.gpg] https://packages.fluentbit.io/ubuntu/jammy jammy main" > /etc/apt/sources.list.d/fluent-bit.list

# Установка
apt-get update && apt-get install fluent-bit
```

**RHEL/CentOS/Fedora:**

```bash
# Добавление репозитория
cat > /etc/yum.repos.d/fluent-bit.repo << 'EOF'
[fluent-bit]
name=Fluent Bit
baseurl=https://packages.fluentbit.io/centos/9/
gpgcheck=1
gpgkey=https://packages.fluentbit.io/fluentbit.key
enabled=1
EOF

# Установка
yum install fluent-bit
```

**Проверка:**

```bash
fluent-bit --version
# → Fluent Bit v5.1.1
```

### Systemd Service

После установки Fluent Bit доступен как systemd-сервис:

```bash
# Запуск
systemctl start fluent-bit

# Автозапуск
systemctl enable fluent-bit

# Статус
systemctl status fluent-bit

# Логи
journalctl -u fluent-bit -f
```

**Конфигурация systemd (если требуется кастомизация):**

```ini
# /etc/systemd/system/fluent-bit.service.d/override.conf
[Service]
ExecStart=
ExecStart=/opt/fluent-bit/bin/fluent-bit -c /etc/fluent-bit/fluent-bit.yaml
Restart=always
RestartSec=5
LimitNOFILE=65536
```

### Docker

```bash
# Базовый запуск
docker run -v /var/log:/var/log \
           -v /etc/fluent-bit:/fluent-bit/etc \
           fluent/fluent-bit:latest \
           /fluent-bit/bin/fluent-bit -c /fluent-bit/etc/fluent-bit.yaml

# С port-forward для метрик
docker run -p 2020:2020 \
           -v /var/log:/var/log \
           -v /etc/fluent-bit:/fluent-bit/etc \
           fluent/fluent-bit:latest \
           /fluent-bit/bin/fluent-bit -c /fluent-bit/etc/fluent-bit.yaml
```

### Kubernetes (DaemonSet)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: logging
  labels:
    app: fluent-bit
spec:
  selector:
    matchLabels:
      app: fluent-bit
  template:
    metadata:
      labels:
        app: fluent-bit
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "2020"
        prometheus.io/path: "/api/v1/metrics/prometheus"
    spec:
      serviceAccountName: fluent-bit
      containers:
        - name: fluent-bit
          image: fluent/fluent-bit:5.1.1
          ports:
            - containerPort: 2020
              name: http-metrics
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          livenessProbe:
            httpGet:
              path: /api/v1/health
              port: 2020
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /api/v1/health
              port: 2020
            initialDelaySeconds: 5
            periodSeconds: 10
          volumeMounts:
            - name: config
              mountPath: /fluent-bit/etc/
            - name: varlog
              mountPath: /var/log
              readOnly: true
            - name: containers
              mountPath: /var/lib/docker/containers
              readOnly: true
            - name: state
              mountPath: /var/fluent-bit/state
      volumes:
        - name: config
          configMap:
            name: fluent-bit-config
        - name: varlog
          hostPath:
            path: /var/log
        - name: containers
          hostPath:
            path: /var/lib/docker/containers
        - name: state
          hostPath:
            path: /var/fluent-bit/state
      terminationGracePeriodSeconds: 30
      tolerations:
        - effect: NoSchedule
          operator: Exists
```

---

## Best Practices

### Структура конфигурации

1. **Разделяйте конфигурацию по логическим блокам:** Используйте `@include` для разделения inputs, filters, outputs в отдельные файлы.
2. **Выносите парсеры в отдельный файл:** `parsers.yaml` или `parsers.conf` для переиспользования.
3. **Используйте Environment Variables:** Для секретов (пароли, токены) и параметров, различающихся между окружениями.

### Производительность

1. **Предпочитайте JSON:** Если приложение может логировать в JSON — используйте парсер `json` вместо `regex`.
2. **Избегайте тяжёлых regex:** Regex-операции потребляют CPU. Используйте только когда нет альтернативы.
3. **Используйте processors для v3.x+:** Они работают в потоке плагина, минуя основной цикл событий.
4. **Устанавливайте `storage.type: filesystem` в production:** Для обеспечения персистентности данных.

### Обратное давление (Backpressure)

1. **`mem_buf_limit`:** Устанавливайте на уровне 60-70% от лимита памяти контейнера.
2. **`storage.pause_on_chunks_overlimit: on`:** Включайте в критичных сценариях для полной остановки при переполнении.
3. **`storage.total_limit_size`:** Всегда устанавливайте для каждого вывода для контроля дискового пространства.

### Безопасность

1. **Не храните пароли в конфигурации:** Используйте переменные окружения или Kubernetes Secrets.
2. **Включайте TLS:** Для отправки данных по незащищенным сетям.
3. **Ограничивайте права ServiceAccount:** Минимальные права для чтения логов и API-сервера.

### Мониторинг

1. **Включайте HTTP-сервер:** `http_server: on` для метрик и health-check.
2. **Настройте Health Check:** Для Kubernetes liveness/readiness probes.
3. **Экспортируйте метрики в Prometheus:** Для централизованного мониторинга.
4. **Отслеживайте ключевые метрики:** `fluentbit_output_errors_total`, `fluentbit_output_retries_total`, `fluentbit_storage_layer_chunks_up`.

---

## Типовые ошибки конфигурации

### Ошибка 1: `configuration test is successful` не выводится

**Причина:** Синтаксическая ошибка в конфигурации.

**Диагностика:**
```bash
fluent-bit --config /etc/fluent-bit/fluent-bit.yaml --dry-run 2>&1
```

**Типичные причины:**
- Неверный отступ в YAML (пробелы вместо табуляции).
- Невалидный синтаксис переменных окружения.
- Несуществующий плагин или параметр.

### Ошибка 2: `permission denied` при чтении логов

**Причина:** Недостаточные права доступа к файлам логов.

**Решение:**
```yaml
# Добавить securityContext в Pod
securityContext:
  runAsUser: 0  # root
  readOnlyRootFilesystem: true
```

Или убедиться, что пользователь Fluent Bit имеет группу `adm` (Debian) или `systemd-journal` (RHEL).

### Ошибка 3: `failed to connect to upstream` в логах

**Причина:** Недоступен endpoint (Elasticsearch, Loki, Kafka).

**Диагностика:**
```bash
# Проверка DNS
nslookup elasticsearch.logging.svc

# Проверка порта
nc -zv elasticsearch.logging.svc 9200

# Проверка логов Fluent Bit
kubectl logs -n logging -l app=fluent-bit --tail=100
```

### Ошибка 4: `out of memory` (OOMKill)

**Причина:** Превышен лимит памяти контейнера.

**Решение:**
1. Увеличить `limits.memory` в контейнере.
2. Установить `mem_buf_limit` на 60-70% от лимита.
3. Включить `storage.pause_on_chunks_overlimit: on`.
4. Переключиться на `storage.type: filesystem`.

### Ошибка 5: `tag not matched` — записи не попадают в output

**Причина:** Тег входа не соответствует правилу `match` в output.

**Диагностика:**
```bash
# Включить debug для просмотра маршрутизации
fluent-bit --config /etc/fluent-bit/fluent-bit.yaml --dry-run -p log_level=debug
```

**Решение:** Проверить, что `match` в output соответствует `tag` в input. Использовать `match: *` для перехвата всех записей.

### Ошибка 6: `multiline_truncated: true` — обрезанные стектрейсы

**Причина:** Превышен лимит `multiline_buffer_limit` (по умолчанию 2MB).

**Решение:**
```yaml
service:
    multiline_buffer_limit: 4MB  # Увеличить лимит
```

Или уменьшить `Flush_Timeout` в многострочном парсере.

### Ошибка 7: Время в логах не распознается

**Причина:** Несоответствие `Time_Format` реальному формату времени в логе.

**Диагностика:**
```bash
# Проверить формат времени в логе
head -1 /var/log/app.log
```

**Решение:** Убедиться, что `Time_Format` точно соответствует формату, включая дробные секунды (`%L`), разделители и суффикс часовой зоны (`%z`).

---

## Дополнительная информация

- [Парсинг логов в Fluent Bit](./parsing.md) — детальное описание работы с парсерами, декодерами и регулярными выражениями.
- [Буферизация и маршрутизация во Fluent Bit](./buffering_routing.md) — механизмы обеспечения надежности, слои хранения и управление очередями.
- [Сравнение Fluent Bit и Fluentd](./fluent_comparison.md) — критерии выбора между легким агентом и полнофункциональным агрегатором.
- [Интеграция Fluent Bit с Loki](../../../Loki/fluentbit_integration.md) — настройка отправки логов в Grafana Loki.
- [Пайплайн Fluent Bit → Kafka → Vector → OpenSearch](../../../../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md) — детальное руководство по развертыванию инфраструктуры.
