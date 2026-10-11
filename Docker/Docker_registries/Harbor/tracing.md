# Harbor: Распределённая трассировка

**Актуально для:** Harbor 2.4+ (трассировка), Harbor 2.15.x

## Определения

* **Distributed Tracing**: Данные трассировки запросов, проходящих через компоненты Harbor (core, jobservice, registryctl) — для наблюдаемости и диагностики в production.
* **OpenTelemetry SDK**: Harbor экспортирует трейсы через OTel SDK. Трейсы можно отправлять в OpenTelemetry Collector (протокол OTLP), а оттуда — в почти любой on-prem или облачный бэкенд.
* **Jaeger exporter**: Прямой экспорт трейсов в Jaeger (без Collector) — поддерживается из-за популярности Jaeger.
* **X-Request-ID**: Заголовок, добавляемый к каждому HTTP-трейсу — ключ для корреляции трейса с логами Harbor.
* **Sample rate**: Доля трассируемых запросов: `1` — 100% трейсов, `0.5` — 50% и т. д.

## Основные концепции

### Экспортёры и ограничение «один за раз»

Harbor поддерживает **только один экспортёр одновременно** — нельзя включить и Jaeger, и OTel (и нельзя включить трассировку без экспортёра). Если нужны несколько бэкендов — используйте OTel-экспортёр и ретранслируйте трейсы через OpenTelemetry Collector.

Jaeger-экспортёр поддерживает два режима, также включается только один:

| Режим | Параметры | Протокол |
| :--- | :--- | :--- |
| **Endpoint mode** | `jaeger.endpoint` (URL, например `http://127.0.0.1:14268/api/traces`), опционально `username`/`password` | HTTP в Jaeger Collector |
| **Agent mode** | `jaeger.agent_host`, `jaeger.agent_port` | UDP в Jaeger Agent |

### Что трассируется

| Данные | Компонент | Пример |
| :--- | :--- | :--- |
| Полученные HTTP-запросы | Core | Любой запрос: операция в UI, push образа |
| Исходящие HTTP-запросы | Core | Health check, вызов API Job Service |
| DB-транзакции | Core | Создание проекта, push образа |
| Полученные HTTP-запросы | Jobservice | Health check, вызов от core |
| Исходящие HTTP-запросы | Jobservice | Репликация (вызов core API для push), GC (вызов registryctl API) |
| Бэкенд-джобы | Jobservice | Любая задача Job Service |
| Полученные HTTP-запросы | Registryctl | Health check от core, вызов от jobservice |

### Конфигурация harbor.yml

Секция `trace` (не `tracing`) в `harbor.yml`:

```yaml
trace:
  enabled: true
  sample_rate: 1            # 1 = 100% трейсов; 0.5 = 50%
  namespace: harbor         # атрибут service.namespace, различает сервисы
  attributes:               # пользовательские атрибуты во все трейсы
    env: production
  jaeger:                   # ИЛИ otel — только один экспортёр
    endpoint: http://127.0.0.1:14268/api/traces
    # username:             # если Jaeger Collector требует auth
    # password:
    # agent_host:           # режим агента (UDP) — вместо endpoint
    # agent_port: 6831
  # otel:
  #   endpoint: 127.0.0.1:4318
  #   url_path: /v1/traces
  #   compression: true
  #   insecure: false
  #   timeout: 10s
```

Параметры применяются через `./prepare` и перезапуск контейнеров (Docker Compose) или обновление release (Helm).

## Предварительные требования

* **Harbor 2.4+** — трассировка доступна с 2.4; в более ранних версиях отсутствует (см. [upgrade](./operations.md)).
* **Бэкенд трассировки** (Jaeger Collector, OpenTelemetry Collector, Tempo и т. п.) — должен быть доступен из-под контейнеров `core`, `jobservice`, `registryctl`. Проверьте DNS/сеть: `curl -sv <endpoint>/api/traces` (Jaeger) или `curl -sv <endpoint>/v1/traces` (OTel HTTP).
* **Проверьте бэкенд до включения** — если endpoint недоступен, компоненты Harbor стартуют, но трейсы теряются (см. [Troubleshooting](#troubleshooting)). Проверка до `./prepare` экономит время: `curl -sv http://jaeger-collector:14268/api/traces -X POST`.
* **Сертификаты**: если бэкенд требует TLS — настройте `otel.insecure: false` и укажите CA в `harbor.yml` (см. [installation.md](./installation.md)).
* **Ресурсы**: трассировка добавляет CPU/память на компоненты (OpenTelemetry-провайдер встроен в core/jobservice/registryctl). При `sample_rate: 1` на высоконагруженном инстансе — до 10% дополнительной CPU.
* **OpenTelemetry Collector** (опционально, но рекомендуется для production) — см. [Сценарий 5](#сценарий-5-настройка-open-telemetry-collector-production-путь).
* **Инструменты для валидации**: `curl`, доступ к веб-интерфейсу бэкенда трассировки (Jaeger UI / Grafana), лог-агрегатор с индексом `X-Request-ID`.

## Практические сценарии

### Сценарий 1: Трассировка с Jaeger (endpoint mode)

```yaml
# harbor.yml
trace:
  enabled: true
  sample_rate: 1
  namespace: harbor
  jaeger:
    endpoint: http://jaeger-collector.observability.svc:14268/api/traces
```

```bash
sudo ./prepare
sudo docker compose down -v && sudo docker compose up -d
```

### Сценарий 2: Трассировка через OpenTelemetry Collector

Когда трейсы должны попасть в несколько бэкендов (Jaeger + Tempo + Prometheus-метрики):

```yaml
# harbor.yml — OTel-экспортёр в Collector
trace:
  enabled: true
  sample_rate: 0.5
  namespace: harbor
  otel:
    endpoint: otel-collector.observability.svc
    url_path: /v1/traces
    compression: true
    insecure: false
    timeout: 10s
```

Collector ретранслирует трейсы в нужные бэкенды (Jaeger, Tempo, Zipkin).

### Сценарий 3: Jaeger agent mode (UDP)

```yaml
trace:
  enabled: true
  jaeger:
    agent_host: jaeger-agent.observability.svc
    agent_port: 6831
```

UDP-режим не гарантирует доставки — для production с критичными трейсами предпочтительнее endpoint mode (HTTP).

### Сценарий 4: Корреляция трейса с логами по X-Request-ID

1. Каждый HTTP-трейс Harbor снабжается `X-Request-ID`.
2. При диагностику инцидента: возьмите `X-Request-ID` из ответа/лога запроса.
3. Найдите трейс в Jaeger UI по этому ID — полная цепочка core → jobservice → registryctl.
4. Найдите строки лога Harbor с тем же ID — связка «трейс + лог» даёт полную картину запроса.

**Детали propagation (SRE):**
* `X-Request-ID` генерируется в `core` и передаётся при исходящих HTTP-вызовов (в jobservice, registryctl). Registryctl получает его из заголовка — трейсы «сквозные».
* Registry (Docker-registry) не генерирует `X-Request-ID` сам по себе; он передаёт заголовок, полученный от Harbor core, при pull/push через прокси. Конкретное поведение при задании заголовка клиентом напрямую — не документировано официально; проверяйте по логам при необходимости.
* Логи компонентов пишут `X-Request-ID` в стандартный формат — проверьте, что лог-агрегатор (Loki/EFK) индексирует это поле, иначе корреляция вручную не понадобится.

### Сценарий 5: Настройка OpenTelemetry Collector (production-путь)

Когда трейсы должны попасть в несколько бэкендов (Jaeger + Tempo + Prometheus-метрики) или нужна буферизация/retry — разворачивайте Collector отдельно от Harbor:

```yaml
# collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
      http:

processors:
  batch:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 65
    spike_limit_percentage: 20
  # Фильтрация PII из трейсов (пароли, токены в заголовках/URL)
  attributes:
    include:
      keys: [http.request.header.x-request-id, http.url.path]
    exclude:
      keys: [authorization, cookie, proxy-authorization]

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
    namespace: harbor
  jaeger:
    endpoint: jaeger-collector:14250
    tls:
      insecure: true
  logging:

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch, attributes]
      exporters: [jaeger, logging]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus]
```

```yaml
# harbor.yml — экспорт через Collector
trace:
  enabled: true
  sample_rate: 0.2
  namespace: harbor
  attributes:
    env: production
  otel:
    endpoint: otel-collector
    url_path: /v1/traces
    compression: true
    insecure: true
    timeout: 10s
```

* Collector должен быть **доступен из всех компонентов** Harbor (core, jobservice, registryctl) — разместите его в той же сети/кластере.
* `memory_limiter` предотвращает OOM при всплеске трейсов; `batch` — пакетная отправка (снижает overhead).
* Фильтр `attributes` на Collector-уровне — защита от утечки секретов в трейсы (см. [Лучшие практики](#лучшие-практики)).

## Валидация

```bash
# Harbor здоров после включения трассировки
curl -sk https://harbor.corp.local/api/v2.0/health
# → {"status":"healthy"}

# Трейсы появляются в Jaeger UI (Services: harbor-core, harbor-jobservice...)
#   или в бэкенде, куда ретранслирует OTel Collector

# X-Request-ID присутствует в ответе API
curl -skI -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/projects" | grep -i x-request-id
# → X-Request-Id: <uuid>
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Трейсы не приходят в бэкенд | `trace.enabled` не применён | `./prepare` + перезапуск контейнеров; проверьте `trace.enabled: true` |
| Трейсы не приходят | Неверный endpoint/порт, сетевая изоляция | Проверьте доступность Jaeger Collector / OTel Collector с хоста Harbor; проверьте `sample_rate` (при 0 трейсов не будет) |
| Ошибка конфигурации при старте | Включены оба экспортёра (jaeger + otel) | Оставьте только один экспортёр — Harbor поддерживает один за раз |
| Jaeger не получает трейсы | Включены и endpoint, и agent mode | Только один режим Jaeger за раз |
| Мало трейсов | `sample_rate` < 1 | Установите `sample_rate: 1` для полной трассировки (ценой объёма) |

## Граничные случаи

* **Один экспортёр за раз** — ограничение Harbor; для нескольких бэкендов используйте OTel Collector как ретранслятор.
* **Sample rate** влияет на объём трейсов и нагрузку: 100% трассировка на нагруженном инстансе заметно увеличивает трафик к бэкенду.
* **Namespace** (`service.namespace`) различает сервисы Harbor в бэкенде трассировки.
* **Трассировка ≠ аудит-лог**: трейсы — технические данные о запросах и DB-транзакциях; аудит-лог — кто и какой артефакт изменил (см. [operations.md, сценарий 3](./operations.md#сценарий-3-аудит-логи)).
* **Трассировка ≠ метрики**: метрики Prometheus — агрегаты (`harbor_core_http_request_total`); трейсы — отдельные запросы.

## Лучшие практики

* **Production — OTel Collector**, а не прямой экспорт в Jaeger: Collector даёт буферизацию, ретрансляцию в несколько бэкендов, retry, compression.
* **`sample_rate` по нагрузке**: 1.0 — для диагностики инцидентов или низкой нагрузки; 0.1–0.2 — для production с высокой частотой запросов (объём трейсов растёт линейно, бэкенд трассировки — ресурсоёмкий).
* **`namespace` отличает среды** (`harbor-prod`, `harbor-staging`) — один бэкенд на несколько инстансов без путаницы.
* **X-Request-ID как единый ключ**: ищите трейс и логи по одному ID; настройте лог-агрегатор (Loki/EFK) на индексирование этого заголовка.
* **Храните трейсы отдельно от логов**: трейсы — для диагностики latency/ошибок, логи — для деталей; метрики — для SLO.
* **Алерты по трейсам, а не только по метрикам**: при подозрении на деградацию бэкенда storage (см. [storage.md, сценарий 8](./storage.md#сценарий-8-управление-слоями-gc-удаление-health-check)) трейсы показывают, где именно «застрял» запрос.
* **Ограничение PII**: трейсы содержат заголовки и URL; проверьте, что в них не попадают пароли/токены — при необходимости фильтруйте на Collector-уровне.

## Откат

Трассировка включается/отключается в `harbor.yml` (`trace.enabled`). Отключение:

```yaml
# harbor.yml
trace:
  enabled: false
```

```bash
sudo ./prepare
sudo docker compose down -v && sudo docker compose up -d
```

* Отключение трассировки **не влияет** на работу Harbor — компоненты запускаются без OpenTelemetry-провайдера.
* При отключении `trace` целиком — параметры `sample_rate`, `namespace`, `attributes`, `jaeger`, `otel` игнорируются (можно оставить комментариями).
* Если переключаетесь между экспортёрами (Jaeger → OTel) — меняйте только один ключ за раз, иначе ошибка конфигурации при старте (см. [Troubleshooting](#troubleshooting)).
* Для быстрого отката без переконфигурации — отключите трассировку на уровне Collector (отключите receivers/pushers), оставив `trace.enabled: true` в Harbor.

## Дополнительная информация

* Официальная документация: [Distributed Tracing](https://goharbor.io/docs/2.15.0/administration/distributed-tracing/), [Configure the Harbor YML File](https://goharbor.io/docs/2.15.0/install-config/configure-yml-file/).
* **OpenTelemetry Collector** — [OpenTelemetry](../../../OpenTelemetry/opentelemetry_overview.md).
* **Метрики Harbor** — [operations.md, сценарий 2](./operations.md#сценарий-2-мониторинг-и-алерты-prometheus).
* **Аудит-лог** — [operations.md, сценарий 3](./operations.md#сценарий-3-аудит-логи).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — компоненты и наблюдаемость.
* **[Эксплуатация](./operations.md)** — метрики, логи, тюнинг.
* **[Установка](./installation.md)** — применение конфигурации (`./prepare`).
* **[Вопросы на собеседованиях](./harbor_interview_qa.md)** — Q&A по Harbor.
