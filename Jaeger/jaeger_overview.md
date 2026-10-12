# Обзор Jaeger

**Актуально для:** Jaeger v2.x

> **Статус:** Документация описывает **Jaeger v2** на базе кодовой базы OpenTelemetry Collector. Классическая ветка Jaeger v1 достигла статуса **EOL (End of Life)**; разрозненные бинарные компоненты (jaeger-agent, jaeger-collector, jaeger-query v1) заменены единым бинарным дистрибутивом. Все архитектурные решения и сценарии ориентированы на on-premise и bare-metal инфраструктуру (Linux, systemd, Docker, self-hosted Kubernetes) без вендорных облачных зависимостей и AI-компонентов.

**Jaeger** — распределенная система трассировки с открытым исходным кодом для мониторинга, профилирования и локализации неполадок в микросервисных и сервисно-ориентированных архитектурах. Проект входит в экосистему CNCF (Cloud Native Computing Foundation).

В версии v2 Jaeger претерпел фундаментальную трансформацию, став специализированным дистрибутивом **OpenTelemetry Collector**. Это обеспечило нативную поддержку протокола OTLP (OpenTelemetry Protocol), упростило эксплуатацию инфраструктуры за счет использования единого бинарного файла и открыло доступ ко всей экосистеме процессоров, коннекторов и расширений OpenTelemetry.

Основная задача Jaeger в контуре DevOps и SRE — предоставить сквозную наблюдаемость (observability) потоков выполнения транзакций, выявлять задержки на критическом пути выполнения (Critical Path), анализировать каскадные сбои и обеспечивать корреляцию между распределенными компонентами без привязки к внешним SaaS-решениям.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Распределенная трассировка (Distributed Tracing)** | Метод мониторинга и профилирования распределенных систем, позволяющий отслеживать путь прохождения транзакции через совокупность независимых сетевых узлов и микросервисов |
| **Trace (Трасса)** | Направленный ациклический граф (DAG) спанов, представляющий собой сквозной путь запроса через систему. Идентифицируется уникальным глобальным `trace_id` (16 байт / 128 бит) |
| **Span (Спан)** | Атомарная единица работы в рамках трассы (HTTP-обработчик, запрос к базе данных, вызов RPC, фоновая задача). Содержит имя операции, временные метки начала и конца, атрибуты, события и статус |
| **Context Propagation (Распространение контекста)** | Механизм передачи идентификаторов трассировки (`trace_id`, `span_id`) и управляющих флагов между сервисами через метаданные транспортных протоколов (заголовки HTTP, метаданные gRPC, заголовки сообщений брокеров) |
| **W3C Trace Context** | Отраслевой стандарт распространения контекста. Заголовок `traceparent` имеет формат `00-<trace_id>-<parent_id>-<flags>`. Обеспечивает сквозную совместимость между разнородными сервисами |
| **Baggage** | Механизм передачи произвольных пользовательских метаданных (формат `key=value`) по всей цепочке вызовов вместе с контекстом трассировки. Не предназначен для передачи конфиденциальных данных (PII, секреты) |
| **Span Kind** | Категория спана в спецификации OpenTelemetry, определяющая его роль в архитектуре: `Server`, `Client`, `Producer`, `Consumer`, `Internal` |
| **Span Events** | Структурированные события внутри спана с точными временными метками для фиксации дискретных фактов (например, `exception`, `cache.hit`, `db.connect.fail`) |
| **Span Links** | Ссылки между спанами, не находящимися в отношениях «родитель-потомок». Критичны для асинхронных контуров (Kafka, очереди задач), пакетной обработки и связывания независимых потоков |
| **Span Status** | Код результата выполнения спана: `Unset`, `Ok` или `Error`. Используется бэкендами и UI для мгновенной фильтрации проблемных участков цепи |
| **Unified Binary** | Архитектурная модель Jaeger v2, при которой единый скомпилированный исполняемый файл выполняет роли шлюза приема, коллектора, конвейера обработки и Query UI в зависимости от переданной YAML-конфигурации |
| **Storage Extension (`jaeger_storage`)** | Расширение среды исполнения Jaeger v2, инкапсулирующее пулы соединений и драйверы записи/чтения постоянных хранилищ (ClickHouse, Elasticsearch, Badger, Memory) |
| **Storage Exporter (`jaeger_storage_exporter`)** | Экспортер конвейера трассировки в Jaeger v2, перенаправляющий спаны из OTel-пайплайна в зарегистрированный бэкенд `jaeger_storage` |
| **Query Extension (`jaeger_query`)** | Расширение Jaeger v2, предоставляющее встроенный веб-интерфейс (порт 16686) и gRPC Query API v3 (порт 16685) для выполнения выборок трасс из постоянного хранилища |
| **Critical Path (Критический путь)** | Самая длинная последовательная цепочка зависимых операций внутри трассы, определяющая минимально возможное общее время ответа всей системы |
| **Clock Skew (Сдвиг часов)** | Рассинхронизация системных часов между серверами инфраструктуры. Приводит к искажениям временной шкалы (спаны потомков визуально начинаются раньше родительских или имеют отрицательную длительность) |
| **Backpressure (Обратное давление)** | Состояние насыщения внутренних очередей коллектора при превышении пропускной способности сети или дисковой подсистемы хранилища, ведущее к отбрасыванию входящих спанов |
| **Memory Limiter** | Системный процессор OpenTelemetry Collector (`memory_limiter`), защищающий процесс Jaeger от аварийной остановки Linux OOM Killer путем упреждающего сброса данных или временного отказа в приеме спанов |
| **Semantic Conventions (Семантические конвенции)** | Официальные спецификации OpenTelemetry по стандартизации названий атрибутов (`http.request.method`, `server.address`, `db.system.name`) для обеспечения единообразия аналитики |

---

## Базовые концепции

### Трансформация в Jaeger v2

Jaeger v2 полностью переведен на кодовую базу и архитектурные принципы **OpenTelemetry Collector**. Ключевые изменения по сравнению с устаревшей веткой v1:

*   **Нативный OTLP как основной транспорт:** Входные потоки данных обрабатываются по протоколу OTLP (gRPC на порту 4317, HTTP на порту 4318) без накладных расходов на Thrift-конвертацию.
*   **Модульные пайплайны OpenTelemetry:** Любые процессоры из upstream-экосистемы OTel (батчинг, обогащение атрибутами через `transform`, фильтрация, сэмплирование) подключаются непосредственно в YAML-конфигурации.
*   **Единый бинарный дистрибутив:** Один бинарный файл `jaeger` заменяет отдельные процессы `jaeger-agent`, `jaeger-collector` и `jaeger-query`. Роль инстанса определяется составом включенных секций в конфигурационном файле.
*   **Модель расширений (Extensions):** Подключение хранилищ (`jaeger_storage`), поискового API (`jaeger_query`) и адаптивного сэмплирования (`jaeger_sampling`) реализовано через расширения OTel Collector.

```
[Приложения / OTel SDK] 
       │ (OTLP gRPC :4317 / HTTP :4318)
       ▼
┌────────────────────────────────────────────────────────┐
│               Jaeger v2 (Unified Binary)               │
│                                                        │
│  [Receivers: otlp, jaeger-legacy, zipkin]              │
│       │                                                │
│  [Processors: memory_limiter → batch → tail_sampling]  │
│       │                                                │
│  [Exporters: jaeger_storage_exporter]                  │
│       │                                                │
│  [Extension: jaeger_storage] ────── [Extension: query] │
└───────┬────────────────────────────────────────┬───────┘
        ▼                                        ▼
[ClickHouse / ES / Badger]               [Web UI / Query API]
                                            (HTTP :16686 / gRPC :16685)
```

### Анатомия спана и модели данных

Jaeger v2 использует модель данных OpenTelemetry Tracing. Каждый спан содержит фиксированный набор идентификаторов, временных отметок и метаданных:

| Поле | Описание | Пример значения |
| :--- | :--- | :--- |
| `trace_id` | Глобальный уникальный идентификатор всей трассы (16 байт, 32 hex-символа) | `4bf92f3577b34da6a3ce929d0e0e4736` |
| `span_id` | Идентификатор конкретной операции (8 байт, 16 hex-символов) | `00f067aa0ba902b7` |
| `parent_span_id` | Идентификатор родительского спана (отсутствует у корневого спана транзакции) | `00c4711b5e7a9f1a` |
| `name` | Наименование операции (низкая кардинальность) | `POST /api/v1/orders` |
| `start_time` / `end_time` | Метки времени начала и окончания операции в наносекундах (Unix Epoch) | `1710000000000000000` |
| `kind` | Архитектурная роль спана (`Server`, `Client`, `Producer`, `Consumer`, `Internal`) | `Server` |
| `attributes` | Набор пар ключ-значение для контекстной фильтрации | `http.response.status_code=500` |
| `events` | Массив дискретных временных событий со своими метками времени | `exception.type=NullPointerException` |
| `links` | Ссылки на связанные спаны других трасс (асинхронная обработка) | `trace_id=... span_id=...` |
| `status` | Результат выполнения операции: `Ok`, `Error` или `Unset` | `Error` |

Семантическая типизация через **Span Kind** определяет способ построения топологии зависимостей в Jaeger UI:
*   **Server:** Обработка входящего синхронного сетевого запроса (HTTP-роут, gRPC-метод).
*   **Client:** Исходящий синхронный сетевой вызов (обращение к микросервису, запрос к СУБД, обращение к кэшу).
*   **Producer:** Асинхронная отправка сообщения в брокер очередей (Kafka, RabbitMQ).
*   **Consumer:** Извлечение и начало асинхронной обработки сообщения из очереди.
*   **Internal:** Внутренние вычисления или критические блоки логики внутри одного процесса.

### Распространение контекста (Context Propagation)

Сквозная связность трассы между изолированными процессами опирается на внедрение (injection) и извлечение (extraction) контекста на транспортном уровне:

1.  **W3C Trace Context (`traceparent`):** Общепринятый отраслевой стандарт. Заголовок HTTP/gRPC имеет жесткую структуру:
    ```
    traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
                 └┬┘└───────────────┬────────────────┘└───────┬────────┘└┬┘
               версия            trace_id                  span_id    флаги
    ```
    Поле флагов `01` обозначает `sampled` (трасса отобрана для сохранения).
2.  **W3C Trace State (`tracestate`):** Передает специфичные для вендоров или систем маршрутизации непрозрачные пары ключ-значение.
3.  **W3C Baggage (`baggage`):** Передает контекст приложения (например, `tenant_id=corp_a,region=eu-dc1`). Значения доступны всем дочерним сервисам цепи вызовов.

**Требование к сетевой инфраструктуре SRE/SysAdmin:**
Все внутренние обратные прокси (Nginx, HAProxy, Envoy, Traefik) и балансировщики нагрузки обязаны беспрепятственно пропускать заголовки `traceparent`, `tracestate` и `baggage`. Затирание или блокировка этих заголовков приводит к немедленному разрыву трассы и деградации наблюдаемости.

### Сетевая матрица портов Jaeger v2

Для настройки локальных сетевых экранов (iptables, nftables), конфигурации Kubernetes Service и балансировщиков нагрузки используется следующая схема сетевых портов:

| Порт | Протокол | Направление | Компонент | Назначение |
| :--- | :--- | :--- | :--- | :--- |
| **4317** | TCP / gRPC | Inbound | OTLP Receiver | Прием телеметрии по нативному OTLP gRPC (основной рабочий порт) |
| **4318** | TCP / HTTP | Inbound | OTLP Receiver | Прием телеметрии по OTLP HTTP (Protobuf или JSON payload) |
| **16686** | TCP / HTTP | Inbound | `jaeger_query` Extension | Доступ к веб-интерфейсу Jaeger UI и HTTP REST Query API |
| **16685** | TCP / gRPC | Inbound | `jaeger_query` Extension | Высокопроизводительный gRPC Query API v3 (для интеграции с Grafana) |
| **13133** | TCP / HTTP | Inbound | `healthcheckv2` Extension | Проверка жизнеспособности процесса (Liveness / Readiness probes) |
| **8888** | TCP / HTTP | Inbound | Prometheus Telemetry | Экспорт внутренних метрик производительности коллектора (`otelcol_*`) |
| **14250** | TCP / gRPC | Inbound | `jaeger` Legacy Receiver | Прием спанов от устаревших агентов Jaeger v1 (Thrift/Proto over gRPC) |
| **14268** | TCP / HTTP | Inbound | `jaeger` Legacy Receiver | Прием спанов от устаревших клиентов Jaeger v1 (Thrift over HTTP) |

### Хранилища и бэкенды (Storage Backends)

В Jaeger v2 подключение к СУБД изолировано внутри расширения `jaeger_storage`. Поддерживаемые бэкенды для on-premise развертываний:

| Бэкенд | Область применения | Преимущества | Ограничения и особенности |
| :--- | :--- | :--- | :--- |
| **ClickHouse** | Production (рекомендуется с v2.20+) | Колоночное хранение с экстремальной компрессией; высокая скорость агрегаций и аналитики; минимальный TCO | Требует создания таблиц схемы `jaeger_v2` (движок MergeTree с партиционированием по дням) |
| **Elasticsearch / OpenSearch** | Корпоративные среды | Полнотекстовая индексация всех строковых атрибутов спанов; развитый поиск | Высокие требования к оперативной памяти (JVM Heap) и дисковым операциям IOPS |
| **Badger** | Standalone-серверы, тестовые стенды | Встроенная база данных (LSM-tree); сохраняет данные между перезапусками процесса | Локальное дисковое хранилище без встроенной кластеризации; один узел |
| **Memory** | Локальная отладка, CI/CD конвейеры | Нулевые требования к инфраструктуре; мгновенный запуск | Данные полностью утрачиваются при перезапуске процесса Jaeger |

**Буферизация через Kafka:** При потоке телеметрии свыше 10 000 спанов в секунду запись напрямую в СУБД может приводить к всплескам латентности или исчерпанию пула соединений. В таких архитектурах Jaeger Collector направляет спаны в очередь Kafka, откуда выделенные инстансы Jaeger Ingester выполняют асинхронную батчевую вставку в ClickHouse.

### Стратегии сэмплирования в v2

Сэмплирование позволяет управлять объемом сохраняемой телеметрии, предотвращая перегрузку хранилища и сети:

| Стратегия | Место принятия решения | Нагрузка на ресурсы | Плюсы | Минусы | Рекомендации SRE |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Head-based** | OTel SDK в сервисе или первый Collector | Минимальная (CPU/RAM клиента) | Предотвращает генерацию лишнего трафика в сети | Трасса с ошибкой может быть отброшена еще до ее возникновения | Применяется при стабильном монотонном фоне (например, сохранение 1–5% успешных запросов) |
| **Adaptive** | Jaeger Collector via Extension | Средняя (расчет лимитов на коллекторе) | Автоматически удерживает целевое количество трейсов/сек на операцию | Требует постоянного канала связи SDK с эндпоинтом sampling | Среды со скачкообразной или сезонной нагрузкой |
| **Tail-based** | Collector via `tail_sampling` processor | Высокая (требует буферизации трейсов в RAM) | Гарантированное сохранение 100% сбоев и аномально медленных запросов | Риск переполнения RAM при задержках в получении финальных спанов | Критичные платежные и транзакционные контуры |

### Сравнение с Grafana Tempo

Jaeger и **[Grafana Tempo](../Tempo/index.md)** представляют два различных архитектурных подхода к задаче распределенной трассировки:

| Критерий | Jaeger v2 | Grafana Tempo |
| :--- | :--- | :--- |
| **Подход к индексации** | Индексирует метаданные спанов в структурированной СУБД (ClickHouse, Elasticsearch) | Минимальная индексация; данные группируются в блоки Parquet |
| **Хранилище** | Реляционная или колоночная СУБД (ClickHouse, Elasticsearch, Badger) | Объектное блочное хранилище (MinIO, Ceph S3) |
| **Поисковые возможности** | Мгновенный отбор по тегам, операциям, статусам через Web UI и Query API | Поиск по Trace ID или через язык запросов TraceQL |
| **Аппаратные затраты (TCO)** | Выше из-за требований СУБД к дисковой подсистеме и памяти | Минимальные за счет дешевого on-premise S3 (MinIO) |
| **Пользовательский интерфейс** | Самодостаточный полнофункциональный веб-интерфейс Jaeger UI | Ориентирован на визуализацию внутри Grafana Explore |

### Возможности визуализации в Jaeger UI

Веб-интерфейс Jaeger предоставляет специализированные инструменты анализа производительности:

*   **Timeline Diagram (Gantt Chart):** Временная шкала распределения спанов, наглядно выделяющая критический путь и точки синхронного ожидания между микросервисами.
*   **Dependency Graph:** Автоматически формируемый ориентированный граф сетевых взаимосвязей между сервисами, вычисленный на основе накопленных трасс.
*   **Trace Comparison:** Сравнение двух трасс одной и той же операции с подсветкой структурных расхождений и деградации времени ответа.
*   **Trace Statistics:** Агрегированная сводка по процентному вкладу каждого сервиса и типа операции в общую длительность транзакции.
*   **Side Panel Details:** Боковая панель детального разбора атрибутов, стеков вызовов исключений (Events) и ссылок (Links) без потери контекста таймлайна.

### Архитектурные ограничения и краевые случаи

1.  **Clock Skew (рассинхронизация времени):** Jaeger UI применяет внутренние эвристики для корректировки временных смещений, однако при значительном расхождении системных часов между хостами (>100 мс) дочерние спаны визуально опережают родительские. Обязательна синхронизация системного времени через `chrony` на уровне ядра Linux.
2.  **Потребление памяти процессором `tail_sampling`:** Для принятия решения о сохранении трассы процессор удерживает все входящие спаны в оперативной памяти на интервал `decision_wait` (обычно 5–15 секунд). При высоком объеме RPS это приводит к гигабайтным аллокациям RAM.
3.  **Переполнение внутренних очередей:** При деградации бэкенда хранения спаны накапливаются в очередях `jaeger_storage_exporter`. При исчерпании лимита очереди коллектор начинает отбрасывать спаны, вызывая рост счетчика `otelcol_exporter_enqueue_failed_spans`.
4.  **Сетевой оверхед сериализации:** Передача неструктурированных тяжелых полезных нагрузок (дампы JSON-запросов, тела ответов) в атрибутах спанов приводит к резкому росту сетевого трафика и утилизации CPU при парсинге Protobuf.

---

## Практические сценарии

### Сценарий 1: Диагностика критического пути (Critical Path)

**Ситуация:** По данным мониторинга, время ответа эндпоинта оформления заказа `POST /api/v1/orders` возросло с 200 мс до 3.5 с. Логи компонентов не фиксируют ошибок.

| Шаг | Действие инженера | Результат / Диагностика |
| :--- | :--- | :--- |
| **1** | В Jaeger UI выбрать сервис `order-gateway`, операцию `POST /api/v1/orders`, задать `Min Duration: 2s` | Получен список аномально долгих трасс |
| **2** | Открыть таймлайн наиболее длительной трассы | Корневой спан занимает 3420 мс; дочерний спан `inventory-service` занимает 3100 мс |
| **3** | Раскрыть дерево вызовов внутри `inventory-service` | Обнаружено 45 последовательных вызовов спанов типа `Client` к локальной СУБД (`SELECT ... FROM stock`) длительностью по 65 мс каждый |
| **4** | Локализация корневой причины | Проблема «N+1 запросов к базе данных» в цикле проверки наличия позиций заказа |
| **5** | Решение | Замена цикла в коде `inventory-service` на единый батчевый запрос `WHERE item_id IN (...)` |

### Сценарий 2: Поиск причин распределенных сбоев через Span Events

**Ситуация:** Пользователи спорадически получают HTTP 500 при аутентификации. Входной шлюз фиксирует ошибку, но стека вызова в его логах нет.

| Шаг | Действие инженера | Результат / Диагностика |
| :--- | :--- | :--- |
| **1** | Выполнить поиск в Jaeger UI по тегам: `service=auth-proxy`, `error=true` за последний 1 час | Локализована трасса с кодом ошибки |
| **2** | Найти самый глубокий спан в дереве вызовов, подсвеченный красным маркером ошибки | Спан сервиса `ldap-connector` (`Span Kind: Client`) завершился со статусом `Error` |
| **3** | Развернуть блок **Events** внутри спана `ldap-connector` | Зафиксировано событие `exception` со стеком вызова: `SocketTimeoutException: connect timed out to ldap-node-02:389` |
| **4** | Анализ Baggage (если передан) | Атрибут `baggage.datacenter=dc-east` подтвердил, что таймаут возникает только при маршрутизации в резервный ЦОД |
| **5** | Решение | Восстановление сетевой связности между кластером приложений и сервером каталогов `ldap-node-02` |

### Сценарий 3: Локальное стендовое развертывание All-in-One через Docker Compose

**Ситуация:** Инженеру требуется поднять локальный стенд Jaeger v2 с поддержкой протоколов OTLP gRPC/HTTP и встроенным хранилищем Badger (данные сохраняются между перезапусками контейнера).

Создайте конфигурационный файл для Jaeger v2:

```yaml
# /opt/jaeger/config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    send_batch_size: 1024
    timeout: 1s

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      local_badger:
        badger:
          ephemeral: false
          directory_key: /var/lib/jaeger/data/keys
          directory_value: /var/lib/jaeger/data/values
          maintenance_interval: 5m
  jaeger_query:
    storage:
      traces: local_badger
    http:
      endpoint: 0.0.0.0:16686

exporters:
  jaeger_storage_exporter:
    trace_storage: local_badger

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: 0.0.0.0
                port: 8888
```

Создайте манифест Docker Compose:

```yaml
# /opt/jaeger/docker-compose.yml
services:
  jaeger:
    image: jaegertracing/jaeger:2.3.0
    container_name: jaeger-v2
    restart: unless-stopped
    command: ["--config=/etc/jaeger/config.yaml"]
    ports:
      - "4317:4317"     # OTLP gRPC
      - "4318:4318"     # OTLP HTTP
      - "16686:16686"   # Jaeger Web UI
      - "13133:13133"   # Healthcheck probe
      - "8888:8888"     # Prometheus метрики
    environment:
      - GOMEMLIMIT=1800MiB
      - GOGC=100
    volumes:
      - ./config.yaml:/etc/jaeger/config.yaml:ro
      - jaeger-data:/var/lib/jaeger/data
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:13133/"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s

volumes:
  jaeger-data:
    driver: local
```

Запуск и валидация стенда:

```bash
# Запуск сервиса в фоновом режиме
docker compose -f /opt/jaeger/docker-compose.yml up -d
# → Container jaeger-v2  Started

# Проверка статуса контейнера и healthcheck
docker ps --filter "name=jaeger-v2" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# → NAMES       STATUS                    PORTS
# → jaeger-v2   Up 12 seconds (healthy)   0.0.0.0:4317->4317/tcp, 0.0.0.0:4318->4318/tcp, 0.0.0.0:8888->8888/tcp, 0.0.0.0:13133->13133/tcp, 0.0.0.0:16686->16686/tcp

# Проверка healthcheck через HTTP
curl -s -i http://localhost:13133/
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → {"status":"Server available"}

# Проверка доступности API сервисов в Web UI
curl -s http://localhost:16686/api/services
# → {"data":[],"total":0,"limit":0,"offset":0,"errors":null}
```

### Сценарий 4: Настройка конвейера обработки с `tail_sampling` и экспортом в ClickHouse

**Ситуация:** Высоконагруженный контур (10 000 RPS). Требуется сохранять 100% трасс с ошибками, 100% трасс с задержкой выше 1500 мс, а для штатных запросов сохранять 2%. Спаны записываются в кластер ClickHouse.

```yaml
# /etc/jaeger/collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  # Защита от аварийной остановки ядра по OOM
  memory_limiter:
    check_interval: 500ms
    limit_percentage: 80
    spike_limit_percentage: 20

  # Tail-based сэмплирование по результатам выполнения трассы
  tail_sampling:
    decision_wait: 10s
    num_traces: 50000
    expected_new_traces_per_sec: 2000
    policies:
      - name: errors-policy
        type: status_code
        status_code: { status_codes: [ ERROR ] }
      - name: latency-policy
        type: latency
        latency: { threshold_ms: 1500 }
      - name: probabilistic-policy
        type: probabilistic
        probabilistic: { sampling_percentage: 2.0 }

  # Группировка перед записью в ClickHouse
  batch:
    send_batch_size: 8192
    timeout: 2s

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      clickhouse_prod:
        clickhouse:
          endpoint: "tcp://192.168.10.25:9000"
          database: "jaeger_v2"
          username: "jaeger_writer"
          password: "SecureClickHousePassword"
          connection_limit: 64
  jaeger_query:
    storage:
      traces: clickhouse_prod
    http:
      endpoint: 0.0.0.0:16686
    grpc:
      endpoint: 0.0.0.0:16685

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_prod

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, tail_sampling, batch]
      exporters: [jaeger_storage_exporter]
```

Валидация работы политик сэмплирования:

```bash
# Проверка счетчиков сработавших политик tail_sampling
curl -s http://localhost:8888/metrics | grep "processor_tail_sampling_count_traces_sampled"
# → processor_tail_sampling_count_traces_sampled{policy="errors-policy"} 342
# → processor_tail_sampling_count_traces_sampled{policy="latency-policy"} 118
# → processor_tail_sampling_count_traces_sampled{policy="probabilistic-policy"} 2045

# Проверка общего числа спанов, переданных в хранилище ClickHouse
curl -s http://localhost:8888/metrics | grep "otelcol_exporter_sent_spans_total"
# → otelcol_exporter_sent_spans_total{exporter="jaeger_storage_exporter"} 89450
```

### Сценарий 5: Системный мониторинг и валидация ресурсов Jaeger v2 (SRE / SysAdmin)

**Ситуация:** Администратору необходимо проверить утилизацию системных ресурсов (память, файловые дескрипторы) и метрики сетевого приема процесса Jaeger v2 на Linux-хосте.

```bash
# 1. Проверка использования портов процессом jaeger
ss -tulnp | grep -E ':(4317|4318|16686|13133|8888)\b'
# → tcp   LISTEN 0      128          0.0.0.0:4317       0.0.0.0:*    users:(("jaeger",pid=2841,fd=9))
# → tcp   LISTEN 0      128          0.0.0.0:4318       0.0.0.0:*    users:(("jaeger",pid=2841,fd=10))
# → tcp   LISTEN 0      128          0.0.0.0:8888       0.0.0.0:*    users:(("jaeger",pid=2841,fd=14))
# → tcp   LISTEN 0      128          0.0.0.0:13133      0.0.0.0:*    users:(("jaeger",pid=2841,fd=11))
# → tcp   LISTEN 0      128          0.0.0.0:16686      0.0.0.0:*    users:(("jaeger",pid=2841,fd=12))

# 2. Проверка метрик RSS памяти процесса и лимитов Go runtime
curl -s http://localhost:8888/metrics | grep -E '(process_resident_memory_bytes|otelcol_process_uptime)'
# → process_resident_memory_bytes 475684864
# → otelcol_process_uptime 86420

# 3. Проверка счетчиков приема спанов и отказов на приемнике
curl -s http://localhost:8888/metrics | grep -E 'otelcol_receiver_(accepted|refused)_spans'
# → otelcol_receiver_accepted_spans{receiver="otlp",transport="grpc"} 154200
# → otelcol_receiver_refused_spans{receiver="otlp",transport="grpc"} 0
```

---

## Операции и команды

Справочник базовых операций системного инженера при эксплуатации бинарного дистрибутива Jaeger v2 на Linux:

| Действие | Команда | Ожидаемый результат / Примечание |
| :--- | :--- | :--- |
| **Проверка версии дистрибутива** | `jaeger --version` | `# → jaeger version 2.3.0` |
| **Валидация синтаксиса конфигурации** | `jaeger validate --config /etc/jaeger/config.yaml` | `# → Configuration is valid` |
| **Запуск процесса под systemd** | `systemctl restart jaeger.service` | Перезапуск службы коллектора |
| **Проверка статуса службы** | `systemctl status jaeger.service --no-pager` | `# → Active: active (running) since ...` |
| **Просмотр системного журнала службы** | `journalctl -u jaeger -n 50 --no-pager` | Вывод последних 50 строк журнала инициализации |
| **Проверка статуса healthcheck** | `curl -s http://127.0.0.1:13133/` | `# → {"status":"Server available"}` |
| **Запрос списка зарегистрированных сервисов** | `curl -s http://127.0.0.1:16686/api/services` | `# → {"data":["api-gateway","order-service"]...}` |
| **Тестовая отправка спана по OTLP HTTP** | См. команду ниже | Отправка тестового OTLP JSON-спана без сторонних SDK |

Отправка синтетического OTLP HTTP JSON спана для проверки сквозного прохождения данных:

```bash
curl -s -i -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{
    "resourceSpans": [{
      "resource": {
        "attributes": [
          {"key": "service.name", "value": {"stringValue": "synthetic-probe"}}
        ]
      },
      "scopeSpans": [{
        "spans": [{
          "traceId": "5b8aa5a2d2c872e83032f75cb6378394",
          "spanId": "051581bf3fe556f0",
          "name": "health-check-probe",
          "kind": 1,
          "startTimeUnixNano": "1710000000000000000",
          "endTimeUnixNano": "1710000000050000000",
          "status": {"code": 1}
        }]
      }]
    }]
  }'
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → {}
```

Проверка появления синтетического сервиса в хранилище:

```bash
curl -s http://localhost:16686/api/services | grep -o "synthetic-probe"
# → synthetic-probe
```

---

## Типичные проблемы и устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Разорванные трейсы (Missing Links)** | Прокси-сервер (Nginx, Envoy) обрезает заголовок `traceparent` или сервис не передает контекст | Проверить заголовки на стороне сервера:<br>`tcpdump -nn -A -i any 'port 8080 and tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x47455420'` | Включить проброс заголовков `traceparent`, `tracestate`, `baggage` в конфигурации обратного прокси (`proxy_set_header`) |
| **Clock Skew (Отрицательная длительность)** | Рассинхронизация системного времени между серверами | Проверить статус демона времени Linux:<br>`chronyc tracking`<br>`# → System time : 0.000012 seconds slow of NTP` | Настроить синхронизацию времени через `chrony` или `systemd-timesyncd` на всех хостах кластера |
| **`failed to get trace storage: backend not found`** | Имя бэкенда в `jaeger_storage_exporter` не совпадает с ключом в `extensions.jaeger_storage.backends` | Изучить журнал запуска процесса:<br>`journalctl -u jaeger -n 50 \| grep "trace storage"` | Синхронизировать символьные имена бэкенда между секциями `backends` и `trace_storage` в YAML |
| **Спаны отбрасываются (Backpressure)** | Исчерпан размер внутренней очереди `jaeger_storage_exporter` из-за латентности СУБД | Запросить метрики сброса:<br>`curl -s http://localhost:8888/metrics \| grep "otelcol_exporter_enqueue_failed_spans"` | Увеличить `queue_size` в экспортере, настроить пул соединений к ClickHouse или внедрить Kafka-буфер |
| **Аварийное завершение процесса OOMKilled** | Отсутствует процессор `memory_limiter` при интенсивном Tail-sampling | Проверить системный лог ядра Linux:<br>`dmesg -T \| grep -i oom`<br>`# → Out of memory: Killed process ... (jaeger)` | Сконфигурировать процессор `memory_limiter` в качестве первого шага в `pipelines.traces.processors` |
| **Медленная отрисовка поиска в Web UI** | Отсутствие индексов по атрибутам или чрезмерное окно выборки в СУБД | Проверить статус запросов в ClickHouse:<br>`clickhouse-client --query "SELECT query_duration_ms, query FROM system.query_log WHERE type=2 ORDER BY event_time DESC LIMIT 5"` | Добавить Bloom-фильтры по часто запрашиваемым атрибутам (`service_name`, `tags['http.status_code']`) и настроить TTL |
| **Сервис не отображается в UI** | Экспортер не сбросил батч или спаны не дошли до приемника | Проверить счетчик принятых спанов:<br>`curl -s http://localhost:8888/metrics \| grep "otelcol_receiver_accepted_spans"` | Убедиться в корректности сетевого адреса приемника в SDK (порт 4317 gRPC или 4318 HTTP) |

---

## Лучшие практики

1.  **Принцип «OTLP-First»:** Направляйте всю первичную телеметрию приложений исключительно на порты 4317 (gRPC) и 4318 (HTTP) в стандарте OpenTelemetry. Устаревшие библиотеки Jaeger и порты 14250/14268 используйте только для временной поддержки легаси-систем.
2.  **Строгая защита от OOM через `memory_limiter`:** В каждом конвейере трассировки первым процессором всегда должен быть объявлен `memory_limiter`. Настройте `limit_percentage: 80` и `spike_limit_percentage: 20`, чтобы процесс Jaeger сбрасывал нагрузку до того, как ядро Linux инициирует OOM Killer.
3.  **Соблюдение семантических конвенций OpenTelemetry:** Задавайте атрибуты спанов строго в соответствии со стандартами OTel (`http.request.method`, `http.response.status_code`, `db.system.name`, `server.address`). Это гарантирует корректную работу автоматических графов зависимостей и сквозных дашбордов Grafana.
4.  **Аппаратная синхронизация времени хостов:** На всех bare-metal и виртуальных серверах инфраструктуры разверните службу `chrony` с единым источником NTP. Максимальное расхождение системного времени между узлами не должно превышать 10 миллисекунд.
5.  **Разделение путей записи и чтения (CQRS):** В высоконагруженных окружениях разделяйте инстансы Jaeger на специализированные роли:
    *   *Ingestion-пул:* инстансы Jaeger без расширения UI, обрабатывающие только OTLP-прием, батчинг и запись в ClickHouse.
    *   *Query-пул:* инстансы Jaeger с расширением `jaeger_query`, обслуживающие инженеров и Grafana без нагрузки по приему трафика.
6.  **Буферизация через Kafka при потоках >10k spans/sec:** Для предотвращения потери данных во время регламентных работ на базе данных или пиковых всплесков трафика внедряйте Kafka-топик между входными коллекторами и постоянным хранилищем.
7.  **Очистка тестового стенда после валидации:**
    ```bash
    # Остановка и удаление контейнеров
    docker compose -f /opt/jaeger/docker-compose.yml down

    # Удаление томов с сохраненными данными трассировки
    docker volume rm jaeger_jaeger-data
    ```

---

## Дополнительная информация

**Специализированные руководства по Jaeger:**

*   Детальный разбор компонентов, очередей и архитектурных потоков данных: **[Архитектура Jaeger](./jaeger_architecture.md)**
*   Сценарии развертывания под systemd, Docker и на bare-metal: **[Варианты развертывания](./jaeger_deployment_options.md)**
*   Оркестрация через OpenTelemetry Operator: **[Интеграция с Kubernetes](./jaeger_kubernetes_integration.md)**
*   Профилирование, анализ критического пути и латентности: **[Анализ производительности](./jaeger_performance_analysis.md)**
*   Спецификация REST и gRPC Query API v3: **[Query API Jaeger](./jaeger_query_api.md)**
*   Пошаговая инструкция по миграции с ветки v1: **[Миграция Jaeger v1 → v2](./jaeger_migration_v1_to_v2.md)**
*   Расчет аппаратных ресурсов, CPU, RAM и дисковой емкости: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
*   Низкоуровневая настройка ClickHouse, Elasticsearch и Kafka: **[Storage Deep Dive](./jaeger_storage_deep_dive.md)**
*   Кластеризация, отказоустойчивость и Disaster Recovery: **[High Availability и DR](./jaeger_high_availability.md)**
*   Стратегии сэмплирования и 2-Tier кластер: **[Стратегии сэмплирования в Jaeger](./jaeger_sampling_strategies.md)**
*   Диагностика и устранение разрывов трасс: **[Broken Traces & Context Propagation](./jaeger_context_propagation_troubleshooting.md)**
*   Подключение Jaeger к Grafana и корреляция Trace-to-Metrics: **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)**
*   Настройка трассировки в Istio и Envoy: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**
*   Конфигурация протокола OTLP, буферов и сжатия: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
*   Автоматическая инструментация трассировки через eBPF: **[eBPF и автоматическая инструментация](./jaeger_ebpf_auto_instrumentation.md)**
*   Изоляция тенантов и управление доступом к трейсам: **[Multi-tenancy и изоляция](./jaeger_multi_tenancy.md)**
*   Аутентификация, mTLS и защита сетевого контура: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**

**Смежные разделы базы знаний:**

*   Базовые принципы распределенной телеметрии: **[OpenTelemetry Overview](../OpenTelemetry/opentelemetry_overview.md)**
*   Спецификация и формат передачи данных: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**
*   Альтернативное блочное хранилище трасс: **[Архитектура и эксплуатация Grafana Tempo](../Tempo/architecture_operations.md)**

### См. также

*   [Официальная документация Jaeger Tracing](https://www.jaegertracing.io/docs/)
*   [Репозиторий проекта Jaeger на GitHub](https://github.com/jaegertracing/jaeger)
*   [Спецификация OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)

