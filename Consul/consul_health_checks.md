**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

# Consul Health Checks

## Определения

**Проверки состояния (Health Checks)** в Consul — это распределенный механизм непрерывного мониторинга работоспособности узлов и сервисов. На основе результатов этих проверок Consul динамически обновляет [каталог служб](./consul_service_catalog.md), исключая неисправные экземпляры из пула балансировки трафика. Проверки состояния являются фундаментом для реализации паттернов отказоустойчивости, динамической маршрутизации и [наблюдаемости (Observability)](../Concepts/Observability_and_Monitoring/observability_definitions.md).

## Предварительные требования

Перед настройкой Health Checks убедитесь, что среда соответствует следующим требованиям:

- **Версия Consul:** 1.19.x или новее. Catalog v2 с multi-port services доступен с Consul 1.22+.
- **Сеть:** Открыты порты 8300 (RPC), 8301 (Serf LAN), 8302 (Serf WAN), 8500 (HTTP), 8502 (gRPC), 8600 (DNS).
- **NTP-синхронизация:** Расхождения времени между узлами >1s приводят к некорректной работе TTL и heartbeat. Используйте `chrony` или `systemd-timesyncd`.
- **Ресурсы агента:** Для Script/Docker проверок учитывайте нагрузку на CPU и память агента. Рекомендуемый минимум: 1 CPU core и 512MB RAM на 100 сервисов с проверками.
- **Docker socket:** Для Docker-проверок пользователь, под которым запущен `consul`, должен иметь права на доступ к `/var/run/docker.sock`.
- **ACL:** При включенных ACL создайте политики с правами `node:read`, `service:read` для доступа к результатам проверок.

## Основные концепции

### Классификация уровней проверок

1.  **Node-level Checks:** Мониторинг здоровья самого хоста/узла (доступность диска, использование памяти, статус системных служб). Если проверка узла переходит в статус `critical`, все сервисы на этом узле автоматически помечаются как недоступные.
2.  **Service-level Checks:** Мониторинг конкретного экземпляра приложения (HTTP эндпоинты, gRPC статусы). Влияет только на доступность конкретного сервиса.

### Статусы проверок и влияние на DNS

Результат каждой проверки относится к одному из четырех состояний:
- `passing`: Компонент полностью работоспособен. Только такие экземпляры возвращаются через DNS-интерфейс и стандартные API-запросы.
- `warning`: Сервис работает с отклонениями. Трафик продолжает поступать, но статус служит триггером для алертинга.
- `critical`: Сервис неисправен. Consul автоматически исключает его из результатов обнаружения (Service Discovery).
- `unknown`: Переходное состояние (например, во время инициализации).

**Влияние на DNS:** При запросе `myservice.service.consul`, Consul фильтрует записи и возвращает только те IP-адреса, все проверки которых находятся в статусе `passing`. Если ни один экземпляр не здоров, DNS вернет пустой ответ (NXDOMAIN/NODATA).

### Механизм Анти-энтропии (Anti-entropy)

Это ключевой процесс синхронизации локального состояния агента с глобальным каталогом на серверах.
- **Принцип работы:** Агент хранит локальную копию состояния здоровья своих сервисов и периодически отправляет отчет (state sync) на сервер.
- **Разрешение конфликтов:** Если данные в каталоге сервера и локальном состоянии агента расходятся, сервер считает свои данные авторитетными для состава сервисов, но данные агента — для их статуса здоровья.
- **Streaming (v1.20+):** В современных кластерах анти-энтропия работает через gRPC-стриминг, что снижает нагрузку на CPU серверов и сетевой трафик до 3 раз по сравнению с классическим блокирующим опросом.

### Пороги срабатывания (Thresholds)

Для предотвращения "дребезга" (flapping) — частой смены статуса из-за краткосрочных сбоев — используются пороги:
- `success_before_passing`: Количество последовательных успешных проверок для перехода из `critical/warning` в `passing`. Доступно для HTTP, TCP, gRPC, Docker и Monitor проверок (с Consul 1.7.0+).
- `failures_before_critical`: Количество последовательных неудачных проверок для перехода в статус `critical`. Доступно для HTTP, TCP, gRPC, Docker и Monitor проверок (с Consul 1.7.0+).

### Переменная окружения `CONSUL_HTTP_CHECK_AUTH`

Consul поддерживает переменную окружения `CONSUL_HTTP_CHECK_AUTH` для передачи Basic Auth учетных данных в HTTP health checks. Это позволяет проверять эндпоинты, защищенные базовой аутентификацией, без указания учетных данных в конфигурации HCL.

## Типы проверок

Consul предоставляет широкий спектр проберов, адаптированных под различные типы нагрузки:

| Тип | Особенности | Сценарий использования |
| :--- | :--- | :--- |
| **HTTP/HTTPS** | Код 2xx — `passing`, 429 — `warning`, остальные — `critical`. Поддерживает заголовки и `tls_skip_verify`. | Веб-сервисы, REST API. |
| **TCP** | Проверка открытия сокета. | Базы данных, кэши, прокси. |
| **gRPC** | Нативный протокол `grpc.health.v1`. Поддерживает TLS и выбор конкретного сервиса. | Микросервисы на gRPC. |
| **H2ping** | Проверка через HTTP/2 PING-фреймы. | Высокопроизводительные HTTP/2 соединения. |
| **TTL (Push)** | Сервис сам отправляет статус "живучести" через HTTP API. | Cron-задачи, асинхронные рабочие очереди. |
| **Alias** | Статус проверки зависит от здоровья другого сервиса или узла. | Sidecar-контейнеры, связанные компоненты. |
| **Script/Args** | Выполнение внешней команды/скрипта. Код 0 — успех. | Сложные проверки логики, доступность ресурсов ОС. |
| **Docker** | Выполнение команды внутри контейнера через `docker exec`. Требует доступа агента к докер-сокету. | Контейнеризированные приложения без сетевого API. |
| **OSService** | Нативная проверка системных служб (Systemd, Windows Services). | Системные демоны. |

**Значения по умолчанию для `timeout`:** Script — 30s; HTTP, TCP, UDP, gRPC, H2ping — 10s.

**Важно:** Начиная с Consul 1.0, рекомендуется использовать поле `args` вместо устаревшего `script` для определения команды проверки. Это позволяет запускать проверки без оболочки shell и повышает безопасность.

### Health Checks в Catalog v2 (Consul 1.22+)

С внедрением **Catalog v2** (Multi-port services) проверки состояния по-прежнему привязываются к **экземпляру сервиса (Service Instance)**.
- Если у сервиса зарегистрировано несколько портов (например, `http`, `grpc`, `admin`), и проверка хотя бы одного из них провалена, весь экземпляр помечается как `critical`.
- **Envoy Aggregation:** В Service Mesh Envoy-прокси может агрегировать проверки здоровья приложения, передавая их в Consul через единый канал Consul Dataplane, что снижает нагрузку на Control Plane.

## Практические сценарии

### Расширенная HTTP-проверка

Пример настройки проверки с использованием кастомных заголовков и игнорированием невалидных TLS-сертификатов (полезно для staging-окружений):

```hcl
check {
  id       = "api-health"
  http     = "https://localhost:8443/v1/health"
  method   = "GET"
  interval = "10s"
  timeout  = "1s"
  
  header = {
    "X-Check-Source" = ["Consul-Agent"]
  }
  
  tls_skip_verify = true
}
```

**Валидация:**
```bash
# Проверка статуса проверки
consul health checks api-service
# → CheckID: api-health, Status: passing

# Проверка через API
curl -s http://localhost:8500/v1/health/checks/api-service | jq .
# → [{"CheckID":"api-health","Status":"passing",...}]
```

### Проверка в Docker-контейнере

Если приложение не предоставляет сетевого интерфейса для проверки, можно использовать `docker_container_id` и `args` для выполнения команды внутри контейнера:

```hcl
check {
  id                 = "db-check"
  docker_container_id = "my-app-container"
  shell              = "/bin/sh"
  args               = ["/usr/bin/pg_isready", "-U", "postgres"]
  interval           = "30s"
}
```

**Валидация:**
```bash
# Проверка статуса Docker-проверки
consul health checks db-service
# → CheckID: db-check, Status: passing

# Проверка доступности docker.sock
ls -la /var/run/docker.sock
# → srw-rw---- 1 root docker 0 Sep 29 12:00 /var/run/docker.sock
```

### Настройка отказоустойчивой gRPC-проверки

Пример конфигурации для современного микросервиса с использованием TLS и защитой от дребезга:

```hcl
service {
  name = "order-processor"
  port = 50051
  
  check {
    id     = "grpc-check"
    name   = "gRPC Health Probe"
    grpc   = "localhost:50051"
    grpc_use_tls = true
    
    # Проверка конкретного сервиса внутри gRPC сервера
    grpc_health_check_service = "OrderService"
    
    interval = "5s"
    timeout  = "1s"
    
    success_before_passing = 3
    failures_before_critical = 2
    
    # Удаление сервиса, если он мертв более 10 минут
    deregister_critical_service_after = "10m"
  }
}
```

**Валидация:**
```bash
# Проверка статуса gRPC-проверки
consul health checks order-processor
# → CheckID: grpc-check, Status: passing

# Проверка через API с фильтром
curl -s "http://localhost:8500/v1/health/checks/order-processor?passing" | jq .
# → [{"CheckID":"grpc-check","Status":"passing",...}]
```

### Использование TTL для мониторинга бэкапов

Сценарий для скрипта, который выполняется раз в сутки. Если скрипт не сообщит об успехе в течение 25 часов, статус станет `critical`.

```hcl
check {
  id    = "nightly-backup"
  name  = "Database Backup Status"
  ttl   = "25h"
  notes = "Обновляется внешним скриптом после завершения dump/upload"
}
```

**Обновление из скрипта (bash):**
```bash
curl --request PUT http://localhost:8500/v1/agent/check/pass/nightly-backup?note="Backup success at $(date)"
```

**Валидация:**
```bash
# Проверка статуса TTL-проверки
consul health checks nightly-backup
# → CheckID: nightly-backup, Status: passing

# Принудительная установка статуса critical для тестирования
curl --request PUT http://localhost:8500/v1/agent/check/fail/nightly-backup?note="Test failure"
consul health checks nightly-backup
# → CheckID: nightly-backup, Status: critical
```

## Лучшие практики

1.  **Избегайте сложных Script-проверок:** Запуск внешнего процесса (fork/exec) каждые несколько секунд создает значительную нагрузку на CPU при большом количестве сервисов. Отдавайте приоритет HTTP или gRPC проверкам.
2.  **Настраивайте `deregister_critical_service_after`:** В динамических средах (Kubernetes, Nomad) это критически важно для предотвращения "засорения" каталога записями от удаленных или переехавших подов. Рекомендуемое значение: 5–15 минут.
3.  **Используйте Consul ESM для внешних ресурсов:** Для мониторинга SaaS или баз данных (RDS) без агентов используйте **Consul External Service Monitor (ESM)**. В версии 1.21+ ESM поддерживает прямое подключение к серверам (Direct Mode).
4.  **Тайм-ауты:** Всегда устанавливайте `timeout` меньше, чем `interval`. Оптимальное соотношение: `timeout = 1/3 * interval`.
5.  **Пороги срабатывания:** Используйте `success_before_passing: 3` и `failures_before_critical: 2` для предотвращения дребезга статусов.
6.  **Логирование вывода:** Убедитесь, что `OutputMaxSize` достаточен для сохранения полезной информации об ошибках (по умолчанию 4KB).
7.  **ACL-политики:** Минимизируйте права агентов. Для проверок достаточно прав `node:read` и `service:read`.
8.  **Мониторинг проверок:** Настройте алерты на количество `critical` проверок и частоту смены статусов (flapping).

## Проверка и валидация

### Проверка статуса всех проверок

```bash
# Все проверки в статусе critical
consul health state critical
# → [{"CheckID":"service:redis","Status":"critical","Output":"connection refused",...}]

# Все проверки узла
consul health state critical -node=web-01
# → [{"CheckID":"service:api","Status":"critical","Output":"HTTP 500",...}]
```

### Проверка конкретного сервиса

```bash
# Проверка конкретного сервиса (только passing)
consul health service api-service -passing=true
# → [{"Node":"web-01","Service":{"ID":"api-service-1",...}}]

# Проверка конкретного сервиса (все статусы)
consul health service api-service -passing=false
# → [{"Node":"web-01","Service":{"ID":"api-service-1",...},"CheckID":"service:api","Status":"critical"}]
```

### Диагностика через CLI

Чтобы понять, почему проверка провалена, используйте команду для просмотра вывода (stdout/stderr) проверки:

```bash
# Посмотреть детальный вывод конкретной проверки для сервиса
consul health service api-service -passing=false
# В выводе будет поле `Output`, содержащее HTTP-тело ответа или ошибку скрипта.
```

### Проверка через HTTP API

```bash
# Получение всех проверок для сервиса
curl -s http://localhost:8500/v1/health/checks/api-service | jq .
# → [{"CheckID":"service:api","Status":"passing","Output":"",...}]

# Фильтрация по статусу passing
curl -s "http://localhost:8500/v1/health/checks/api-service?passing" | jq .
# → [{"CheckID":"service:api","Status":"passing",...}]

# Получение всех проверок узла
curl -s http://localhost:8500/v1/health/node/web-01 | jq .
# → [{"CheckID":"service:api","Status":"passing",...}]
```

### Проверка Envoy Sidecar (Service Mesh)

Для Service Mesh проверки здоровья агрегируются Envoy-прокси:

```bash
# Статус здоровья апстримов
curl localhost:19000/clusters | jq '.cluster_statuses[] | {name: .name, healthy: (.host_statuses | map(.health_status.flags) | any(. == "healthy"))}'
# → {"name":"api-service.default.dc1.internal.xxx.consul","healthy":true}

# Проверка mTLS сертификатов
curl localhost:19000/certs | jq '.certificates[] | {subject: .subject_alt_names, expiration: .validity.expiration_date}'
# → SPIFFE ID и срок действия корректны
```

## Устранение неполадок (Troubleshooting)

### Симптом: "Дребезг" статусов (Flapping)

Если сервис часто переходит из `passing` в `critical` и обратно, это дестабилизирует Service Discovery.
- **Решение:** Используйте пороги срабатывания. Настройте `success_before_passing: 3`, чтобы сервис возвращался в ротацию только после серии стабильных ответов.

### Диагностика через CLI

Чтобы понять, почему проверка провалена, используйте команду для просмотра вывода (stdout/stderr) проверки:

```bash
# Посмотреть все нездоровые проверки
consul health state critical

# Посмотреть детальный вывод конкретной проверки для сервиса
consul health service order-processor -passing=false
```
В выводе будет поле `Output`, содержащее HTTP-тело ответа или ошибку скрипта.

### Изоляция сетевых проблем

Помните, что проверку выполняет **Consul Agent**, а не ваш компьютер или сервер Consul.
- Если проверка `http` отдает `critical`, попробуйте выполнить `curl` непосредственно с узла, где запущен агент.
- Для Docker-проверок убедитесь, что пользователь, под которым запущен `consul`, имеет права на доступ к `/var/run/docker.sock`.

### Диагностика CA и сертификатов

- **Просмотр конфигурации CA:**
  ```bash
  consul connect ca get-config
  ```
- **Проверка сертификатов в Envoy:**
  Используйте `curl localhost:19000/certs` для просмотра текущих SVID и сроков их действия. Убедитесь, что поле `serial_number` и `subject` соответствуют ожидаемому сервису (SPIFFE ID).
- **Логи ротации:** Серверы Consul логируют процесс обновления корневого сертификата. Ищите записи `Connect CA rotation started`.

## Анти-паттерны

- **Проверка внешних зависимостей:** Сервис не должен помечать себя как `critical`, если недоступна база данных, если эта БД сама зарегистрирована в Consul. Используйте механизмы Failover или Circuit Breaking на уровне приложения.
- **Слишком частые проверки:** Интервал менее `1s` может создать эффект "шторма" запросов в крупных кластерах. Оптимальное значение: 5–30 секунд.
- **Регистрация без health check:** Сервис зарегистрирован, но не проверяется. Реестр содержит "мёртвые" записи.
- **Единый эндпоинт для Liveness и Readiness:** Использование одного и того же эндпоинта для обеих проверок. Если сервис "прогревается" долго, readiness-проверка будет падать, а liveness-проверка вызовет бесконечные рестарты.

## Граничные случаи

- **TTL и перезапуск агента:** При перезапуске Consul агента TTL-проверки сбрасываются в `critical`. Убедитесь, что внешние скрипты вызывают `PUT /v1/agent/check/pass/<check-id>` сразу после восстановления агента.
- **Script-проверки и shell-инъекции:** Избегайте использования поля `script` (устаревшее). Используйте `args` с явным путем к интерпретатору: `args = ["sh", "-c", "..."]`. Это предотвращает выполнение произвольного кода через переменные окружения.
- **Docker-проверки и права доступа:** Агент Consul должен иметь доступ к `/var/run/docker.sock`. При запуске в контейнере используйте `privileged` mode или mount socket с правильными правами.
- **gRPC-проверки и версии protobuf:** Убедитесь, что gRPC-сервис реализует стандартный интерфейс `grpc.health.v1.Health`. Кастомные реализации без этого интерфейса не будут работать с Consul health checks.
- **H2ping и HTTP/2 negotiated:** H2ping требует, чтобы целевой сервис поддерживал HTTP/2. Если сервис работает только на HTTP/1.1, проверка будет падать с ошибкой таймаута.
- **Alias-проверки и циклические зависимости:** При настройке Alias проверок избегайте циклических зависимостей (service A зависит от service B, а service B зависит от service A). Это приведет к неопределенному статусу.
- **Catalog v2 и multi-port:** При использовании Catalog v2 (Consul 1.22+) с multi-port services убедитесь, что каждая проверка явно привязана к соответствующему порту. Проверка, привязанная к несуществующему порту, будет находиться в статусе `critical`.
- **Anti-entropy и сетевые разрывы:** При длительных сетевых разрывах (>30s) между агентом и сервером локальное состояние проверок может расходиться с каталогом. После восстановления связи Consul выполнит полную синхронизацию, что может привести к кратковременному `unknown` статусу всех проверок.

## Дополнительная информация

- **[Обзор архитектуры](./consul_architecture.md)** — механизмы передачи статусов.
- **[Каталог служб](./consul_service_catalog.md)** — как Service Discovery использует данные о здоровье.
- **[Service Mesh: основные концепции](../Service_Mesh/service_mesh_concepts.md)** — как Envoy агрегирует проверки здоровья в mesh-средах.
- **[Consul ESM](./consul_esm.md)** — мониторинг внешних ресурсов без агентов (Enterprise).
- **[Consul External Service Monitor](https://developer.hashicorp.com/consul/docs/connect/external-monitor)** — официальная документация.
- **[Официальная документация: Health Checks](https://developer.hashicorp.com/consul/docs/discovery/checks)**.
- **[Официальная документация: Check configuration reference](https://developer.hashicorp.com/consul/docs/reference/service/health-check)**.
