# Сравнение Fluentd и Fluent Bit

## Определения

**Fluentd** — полнофункциональный агрегатор логов с открытым исходным кодом, написанный на Ruby и C. Предназначен для создания центральных узлов маршрутизации, сложной обработки и веерной отправки данных в различные хранилища. Является выпускником CNCF (Cloud Native Computing Foundation) и.deployed более чем на 15 миллиардов узлов по всему миру.

**Fluent Bit** — высокопроизводительный агент и агрегатор для логов, метрик и трассировок, написанный на языке C. С версии 3.x является полноценной альтернативой Fluentd, обладая поддержкой OpenTelemetry и расширяемостью через WASM (WebAssembly). Также является выпускником CNCF и.deployed более чем на 15 миллиардов узлов по всему миру.

**Агент сбора логов (Log Shipper)** — компонент, развернутый непосредственно в источнике данных (например, на каждом узле кластера) для первичного чтения, парсинга и пересылки данных. В контексте Kubernetes通常 развертывается как DaemonSet.

**Центральный агрегатор (Aggregator)** — промежуточный слой, который принимает потоки данных от множества агентов, выполняет их объединение, сложную фильтрацию и доставку в системы хранения. В контексте Kubernetes通常 развертывается как Deployment с репликами.

**CNCF (Cloud Native Computing Foundation)** — некоммерческая организация, часть Linux Foundation, которая поддерживает развитие проектов в области облачных вычислений. Оба инструмента — выпускники CNCF (Graduated projects), что гарантирует зрелость, безопасность и долгосрочную поддержку.

**Экосистема плагинов** — совокупность доступных расширений для чтения, обработки и отправки данных. Определяет гибкость инструмента и его применимость к различным источникам и хранилищам данных.

## Основные концепции

### Архитектурные различия (Актуально на 2026 год)

Fluent Bit перестал быть только "легким агентом" и теперь успешно выполняет роль агрегатора в высоконагруженных средах. Fluentd остается предпочтительным для сред с крайне сложной бизнес-логикой на Ruby.

| Критерий | Fluent Bit (v3.x+) | Fluentd (v1.17+) |
|:---|:---|:---|
| **Основная роль** | Универсальный агент и агрегатор | Центральный агрегатор, Router |
| **Потребление RAM** | ~1–50 МБ (минимальное) | >100 МБ (зависит от Ruby-плагинов) |
| **Потребление CPU** | Минимальное (}<1% на узле) | Среднее (2–5% при обработке) |
| **Поддержка сигналов** | Логи, Метрики, Трассировки (OpenTelemetry) | Преимущественно логи |
| **Многопоточность** | Да (Threaded Inputs/Outputs) | Да (Worker processes) |
| **Расширяемость** | Lua, WASM (Go, Rust, C++), C | Ruby (1000+ плагинов) |
| **Конфигурация** | YAML (рекомендуется), Classic INI | Ruby DSL, XML-подобный формат |
| **Обработка данных** | SQL-запросы (Stream Processor), Processors, Filters | Фильтры, Ruby-скрипты |
| **Зависимости** | Нулевые (включены в бинарник) | Зависит от Ruby Gem'ов |
| **Размер бинарника** | ~1–5 MB | >50 MB (с зависимостями) |
| **Пропускная способность** | Высокая (100K+ events/sec) | Средняя (10K–50K events/sec) |

### Модели развёртывания

| Параметр | Fluent Bit | Fluentd |
|:---|:---|:---|
| **Kubernetes** | DaemonSet (по узлу) | Deployment (aggrepоды) |
| **VM / Bare Metal** | Systemd-сервис | Systemd-сервис |
| **Контейнеры** | Образ ~5 MB | Образ ~150 MB |
| **Edge / IoT** | Подходит (минимальные требования) | Не рекомендуется (тяжелый) |
| **Ресурсы (min)** | 64 MB RAM, 0.1 CPU | 256 MB RAM, 0.5 CPU |

### Сходства инструментов

Оба инструмента разработаны под эгидой CNCF и разделяют общие принципы:

- **Конвейерная обработка:** данные проходят этапы `input → filter/processor → output`.
- **Маршрутизация по тегам:** использование меток для определения пути следования данных.
- **Надежность:** поддержка TLS (Transport Layer Security), механизмы повторных попыток (retries) и буферизация.
- **Гибкость:** разбор структурированных (JSON, Logfmt) и неструктурированных данных.
- **Протокол Forward:** нативная поддержка протокола Forward для обмена данными между агентами и агрегаторами.

Детали парсинга данных описаны в [parsing.md](./parsing.md).

### Процессоры vs Фильтры в Fluent Bit 3.x

Ключевое нововведение Fluent Bit 3.x — **Processors**. В отличие от старых фильтров, они:
1.  Привязаны напрямую к плагинам ввода (`Input`) или вывода (`Output`).
2.  Выполняются в том же потоке, что и плагин, исключая задержки на переключение контекста.
3.  Поддерживают SQL-синтаксис для трансформации данных.
4.  Работают в YAML-конфигурации (Classic формат не поддерживается).

### Сравнение экосистемы плагинов

| Категория | Fluent Bit | Fluentd |
|:---|:---|:---|
| **Входы (Input)** | tail, systemd, docker, forward, http, udp, tcp, node_exporter_metrics, proc, rand, dummy, wal, processory | forward, http, tail, systemd, docker, syslog, tcp, udp, exec, windowsevent |
| **Фильтры** | kubernetes, grep, nest, parser, record_modifier, modify, lua, exception, tape, logfmt, pest, throttler, typeconv, tag, sql | grep, record_transformer, parser, kubernetes_metadata, modify, lua, record_modifier, nest, nest_insert |
| **Выходы (Output)** | es, opensearch, loki, kafka, s3, azure, gcs, prometheus, slack, http, forward, file, null, syslog, mqtt, splunk, datadog, newrelic, ecs, trellix | elasticsearch, opensearch, loki, kafka, s3, azure, gcs, prometheus, slack, http, forward, file, null, syslog, mqtt, splunk, datadog, newrelic, mongo, redis, amqp, kafka |
| **Процессоры** | content_modifier, metrics_selector, selector, sql (Fluent Bit 3.x+) | Нет прямого аналога |

### Сравнение механизмов буферизации

| Характеристика | Fluent Bit | Fluentd |
|:---|:---|:---|
| **Буфер по умолчанию** | В памяти (`memory`) | На диске (`file`) для большинства плагинов |
| **Типы буферизации** | `memory`, `filesystem` (дисковая) | `memory`, `file` |
| **Защита от перегрузки** | `mem_buf_limit`, Backpressure, Rate Gate (v5.1+) | `overflow_action`, блокировка очереди |
| **Надежность доставки** | Высокая (при `storage.type: filesystem`) | Очень высокая (механизм `retry_forever`) |
| **Контроль скорости** | Rate Gate (v5.1+) | `buffer_chunk_limit`, `buffer_queue_limit` |
| **Retry** | Экспоненциальный откат с джиттером | Фиксированные интервалы с `retry_forever` |

Подробности настройки буферов Fluent Bit приведены в [buffering_routing.md](./buffering_routing.md).

### Сравнение конфигурации

| Параметр | Fluent Bit (YAML) | Fluentd (Ruby DSL) |
|:---|:---|:---|
| **Синтаксис** | YAML (рекомендуется) | Ruby DSL |
| **Валидация** | `--dry-run` | Встроенная (Ruby) |
| **Hot Reload** | `SIGUSR2` или HTTP API | `SIGUSR0` (ограниченно) |
| **Шаблонизация** | YAML-якоря, переменные окружения | Ruby-переменные, ERB-шаблоны |
| **Читаемость** | Высокая (декларативный) | Средняя (императивный) |
| **Сложные условия** | Ограничена (простые условия) | Гибкая (полная мощь Ruby) |

Примеры конфигурации Fluent Bit приведены в [fluentbit_configuration.md](./fluentbit_configuration.md).

## Практические сценарии

### Сценарий 1: Современный стек Kubernetes (Cloud Native)

**Задача:** Сбор логов, метрик и трассировок в формате OpenTelemetry.
**Выбор:** **Fluent Bit**.
**Обоснование:**
- Нативная поддержка протокола OTLP.
- Использование WASM для специфической логики парсинга.
- Минимальное потребление ресурсов при высокой пропускной способности через `Output Workers`.
- Простое развертывание как DaemonSet с минимальыми ресурсами.

**Рекомендуемая конфигурация:**
```yaml
# DaemonSet Fluent Bit
resources:
  requests:
    cpu: 100m
    memory: 64Mi
  limits:
    cpu: 500m
    memory: 128Mi
```

### Сценарий 2: Гибридная архитектура для Enterprise (Legacy + Cloud)

**Задача:** Сбор данных из облачных кластеров и устаревших On-premise серверов, требующих сложной трансформации на Ruby.
**Выбор:** **Fluent Bit (агенты) → Fluentd (агрегаторы)**.

**Архитектурная схема:**

```
            KUBERNETES CLUSTER / VM
┌─────────────────────────────────────────────┐
│  [Node 1]      [Node 2]      [VM / Edge]    │
│  Fluent Bit →  Fluent Bit →  Fluent Bit ──┐ │
└───────│───────────│───────────│───────────┘ │
        └───────────┼───────────┘             │
                    │ (Протокол Forward)      │
            ┌───────▼───────┐                 │
            │    Fluentd    │ (Слой агрегации)│
            │  (Aggregator) │                 │
            └───────┬───────┘                 │
      ┌─────────────┼─────────────┐           │
      │             │             │           │
┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐   │
│ Elasticsearch │ │    S3     │ │   Kafka   │   │
└─────────────┘ └─────────────┘ └─────────────┘
```

**Преимущества подхода:**
1. **Слой совместимости:** Fluentd выступает как "умный шлюз", адаптируя данные под старые системы хранения.
2. **Изоляция:** Агенты на узлах защищены от сбоев центральных систем благодаря буферизации во Fluentd.
3. **Ruby-экосистема:** Возможность использовать редкие плагины (например, для специфических БД), которых нет во Fluent Bit.

Детали реализации сценария с NFS приведены в [fluentbit_to_fluentd_nfs_scenario.md](../fluentbit_to_fluentd_nfs_scenario.md).

### Сценарий 3: On-premise среда с выделенными серверами

**Задача:** Сбор логов с физических серверов (CentOS/RHEL) в центре обработки данных.
**Выбор:** **Fluent Bit** (агенты) + **Fluentd** (агрегаторы, опционально).

**Обоснование:**
- Минимальное потребление ресурсов на серверах.
- Systemd-интеграция для автозапуска.
- Простая конфигурация через YAML.
- При необходимости сложной маршрутизации — добавление Fluentd как агрегатора.

**Пример конфигурации агента:**
```yaml
# /etc/fluent-bit/fluent-bit.yaml
service:
  flush: 5
  daemon: on
  log_level: info

pipeline:
  inputs:
    - name: tail
      tag: system.*
      path: /var/log/messages,/var/log/secure
      parser: syslog
      storage.type: filesystem

  outputs:
    - name: forward
      match: '*'
      host: fluentd-aggregator.internal
      port: 24224
      retry_limit: false
```

### Сценарий 4: Edge / IoT устройства

**Задача:** Сбор логов с edge-устройств (роутеры, контроллеры, IoT-шлюзы) с минимальыми ресурсами.
**Выбор:** **Fluent Bit**.

**Обоснование:**
- Бинарник ~1–5 MB, минимальное потребление RAM/CPU.
- Нулевые зависимости (static build).
- Поддержка ARM (aarch64) и других архитектур.
- WASM для кастомной логики парсинга на edge.

**Особенности конфигурации:**
```yaml
service:
  flush: 10
  daemon: on
  log_level: warn
  storage.path: /tmp/flb-storage/
  storage.type: filesystem
  storage.max_chunks_up: 16

pipeline:
  inputs:
    - name: tail
      tag: edge.*
      path: /var/log/app.log
      parser: json
      mem_buf_limit: 5M

  outputs:
    - name: forward
      match: '*'
      host: central-logging.internal
      port: 24224
      storage.total_limit_size: 50M
```

### Сценарий 5: Миграция с Fluentd на Fluent Bit

**Задача:** Постепенный переход с Fluentd на Fluent Bit для снижения потребления ресурсов.
**Подход:** Параллельная работа с поэтапным переключением.

**Этапы миграции:**

1. **Этап 1:** Развернуть Fluent Bit на новых узлах параллельно с Fluentd.
2. **Этап 2:** Настроить Forward от Fluent Bit к существующему Fluentd (временная связка).
3. **Этап 3:** Переключить часть узлов на прямую отправку в хранилище.
4. **Этап 4:** Полная замена Fluentd (при условии отсутствия Ruby-зависимостей).

**Схема миграции:**
```
Этап 1-2:
[Fluent Bit] → [Fluentd] → [Storage]

Этап 3:
[Fluent Bit] → [Storage] (прямая)
[Fluentd] → [Storage] (оставшиеся)

Этап 4:
[Fluent Bit] → [Storage] (полная замена)
```

**Валидация на каждом этапе:**
```bash
# Проверка количества записей
curl -s http://localhost:2020/api/v1/metrics | jq '.input.records'

# Сравнение с Fluentd
curl -s http://fluentd:24220/api/plugins.json | jq '.plugins[] | select(.type == "forward")'
```

## Валидация и диагностика

### Проверка конфигурации

**Fluent Bit:**
```bash
# Проверка синтаксиса YAML
fluent-bit --config /etc/fluent-bit/fluent-bit.yaml --dry-run

# Проверка синтаксиса Classic
fluent-bit --config /etc/fluent-bit/fluent-bit.conf --dry-run

# Просмотр доступных плагинов
fluent-bit -L
```

**Fluentd:**
```bash
# Проверка конфигурации
fluentd --config /etc/fluentd/fluentd.conf --dry-run

# Просмотр доступных плагинов
fluent-gem list | grep fluent-plugin
```

### Мониторинг производительности

**Fluent Bit (HTTP API):**
```bash
# Метрики в формате Prometheus
curl -s http://localhost:2020/api/v1/metrics/prometheus

# Статус хранилища
curl -s http://localhost:2020/api/v1/storage | jq
```

**Fluentd (Monitor Agent):**
```bash
# Метрики в формате JSON
curl -s http://localhost:24220/api/plugins.json | jq

# Мониторинг через Prometheus
curl -s http://localhost:24231/metrics
```

### Ключевые метрики для сравнения

| Метрика | Fluent Bit | Fluentd | Норма |
|:---|:---|:---|:---|
| Потребление RAM | `< 50 MB` | `< 200 MB` | Стабильное |
| Потребление CPU | `< 2%` | `< 5%` | Стабильное |
| Пропускная способность | `> 100K events/sec` | `> 10K events/sec` | Линейное |
| Ошибки доставки | `0` | `0` | Отсутствуют |
| Retry попытки | Стабильное | Стабильное | Не растет |
| Размер буфера | Ограничен `mem_buf_limit` | Ограничен `buffer_queue_limit` | Не растет монотонно |

## Типовые ошибки и их решение

### Ошибка 1: Fluent Bit потребляет слишком много памяти

**Причина:** Не установлен `mem_buf_limit` или фильтры потребляют много ресурсов.

**Решение:**
1. Установить `mem_buf_limit: 10M–50M` для каждого входа.
2. Использовать `storage.type: filesystem` для снятия нагрузки с памяти.
3. Оптимизировать фильтры (убрать тяжелые regex-операции).

### Ошибка 2: Fluentd падает при высокой нагрузке

**Причина:** Ruby-интерпретер не справляется с потоком данных, GC (Garbage Collection) вызывает задержки.

**Решение:**
1. Увеличить количество Worker processes: `<worker> 0-3 </worker>`.
2. Ограничить буфер: `buffer_chunk_limit 2MB`, `buffer_queue_limit 64`.
3. Использовать файловый буфер с `flush_thread_count 2`.
4. Рассмотреть замену на Fluent Bit (при отсутствии Ruby-зависимостей).

### Ошибка 3: Данные не доходят до хранилища (оба инструмента)

**Диагностика:**
```bash
# Fluent Bit
curl -s http://localhost:2020/api/v1/metrics | jq '.output'

# Fluentd
curl -s http://localhost:24220/api/plugins.json | jq '.plugins[] | select(.output == true)'
```

**Решение:**
1. Проверить доступность хранилища: `curl -I http://elasticsearch:9200`.
2. Проверить логи Fluent Bit: `journalctl -u fluent-bit -f`.
3. Проверить логи Fluentd: `journalctl -u fluentd -f`.
4. Увеличить `retry_limit` или установить `retry_limit: false`.

### Ошибка 4: Конфликт тегов при маршрутизации

**Причина:** Несколько выводов с пересекающимися правилами `Match`.

**Решение:**
1. Использовать `Match_Regex` для более точных правил.
2. Порядок выводов важен — первый matching output получает данные.
3. Добавить уникальные теги для каждого источника.

### Ошибка 5: Высокая задержка доставки (Fluentd)

**Причина:** Маленький `flush_interval` или проблемы с сетью.

**Решение:**
1. Увеличить `flush_interval 5s` (по умолчанию 1s).
2. Использовать `flush_thread_count 2` для параллельной отправки.
3. Проверить сеть: `ping elasticsearch`, `traceroute elasticsearch`.
4. Рассмотреть Fluent Bit для снижения задержки.

## Best Practices и особенности

### Выбор инструмента

1. **Fluent Bit по умолчанию:** Начинайте с Fluent Bit, если нет специфических требований к Ruby-плагинам.
2. **Fluentd для сложной логики:** Используйте Fluentd только когда нужна сложная трансформация данных на Ruby.
3. **Гибрид для Enterprise:** Используйте Fluent Bit (агенты) + Fluentd (агрегаторы) для максимальной гибкости.
4. **Fluent Bit для edge/IoT:** Единственный подходящий вариант для устройств с ограниченными ресурсами.

### Производительность

1. **JSON предпочтительнее Regex:** Если приложение может логировать в JSON — используйте парсер `json`. Это самый производительный вариант.
2. **Минимум фильтров:** Каждый фильтр добавляет задержку. Используйте только необходимые.
3. **Processors вместо Filters:** В Fluent Bit 3.x+ используйте Processors для лучшей производительности.
4. **Threaded Outputs:** Используйте `workers` для параллельной отправки в несколько хранилищ.

### Надежность

1. **Filesystem буфер:** Всегда используйте `storage.type: filesystem` в Production для Fluent Bit.
2. **Retry Limit:** Настройте `retry_limit` в зависимости от критичности данных.
3. **Backpressure:** Включите `storage.pause_on_chunks_overlimit: on` для защиты от OOM.
4. **Dead Letter Queue:** Используйте `storage.keep.rejected: on` для сохранения отброшенных данных.

### Безопасность

1. **TLS:** Всегда используйте TLS для Forward-соединений: `tls on`, `tls.verify off` (в dev), `tls.verify on` (в production).
2. **Аутентификация:** Используйте `shared_key` для аутентификации Forward-соединений.
3. **Разделение прав:** Запускайте Fluent Bit от непривилегированного пользователя.

### Edge Cases и ограничения

*   **Fluent Bit 3.x+:** Процессоры (Processors) доступны только в YAML-конфигурации. Classic формат не поддерживается.
*   **Fluentd и Windows:** Fluentd имеет ограниченную поддержку Windows. Fluent Bit работает на Windows нативно.
*   **Размер буфера Fluentd:** При `buffer_type: file` Fluentd создает файлы фиксированного размера. Нехватка дискового пространства может привести к блокировке.
*   **Ruby-зависимости Fluentd:** Обновление Ruby-плагинов может сломать конфигурацию. Тестируйте обновления в dev-среде.
*   **Forward-протокол:** Оба инструмента используют одинаковый протокол Forward, что обеспечивает совместимость при миграции.
*   **OpenTelemetry:** Fluent Bit имеет нативную поддержку OTLP. Fluentd требует дополнительных плагинов.

## Дополнительная информация

- [Конфигурация Fluent Bit](./fluentbit_configuration.md) — базовые настройки и структура файлов.
- [Буферизация и маршрутизация во Fluent Bit](./buffering_routing.md) — глубокое погружение в работу с очередями.
- [Парсинг логов во Fluent Bit](./parsing.md) — примеры регулярных выражений и разбора CRI.
