**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

# Каталог служб Consul (Service Catalog)

## Определения

**Каталог служб (Service Catalog)** в Consul — централизованный реестр, содержащий информацию обо всех зарегистрированных сервисах, их экземплярах, метаданных, сетевых адресах и [статусах работоспособности](./consul_health_checks.md). Каталог является фундаментом для механизмов обнаружения сервисов (Service Discovery) и управления связностью в распределенных системах.

В современных версиях (Consul 1.22+) каталог перешел на архитектуру **Catalog v2**, которая разделяет понятия "сервис" (логическое описание) и "нагрузка" (workload — физическая единица, например, процесс или экземпляр приложения), позволяя более гибко управлять мультипортовыми приложениями и мультикластерными топологиями.

**Ключевые термины:**
- **Datacenter (DC):** Логическая группа узлов с низкой сетевой задержкой.
- **Admin Partition:** (Enterprise) Высший уровень изоляции для разделения административных границ.
- **Namespace:** Логическая изоляция внутри раздела для разных команд или окружений.
- **Workload:** (Catalog v2) Физический экземпляр приложения (например, процесс или Pod).
- **Node:** Узел (хост), на котором запущен агент Consul.
- **Service:** Логическое определение приложения, объединяющее один или несколько портов.
- **Service Instance:** Конкретный экземпляр сервиса с уникальным `ServiceID` на узле.
- **Sameness Group:** Механизм логического объединения идентичных сервисов по разным разделам или кластерам.

## Предварительные требования

Перед настройкой Service Catalog убедитесь, что среда соответствует следующим требованиям:

- **Версия Consul:** 1.19.x или новее. Catalog v2 с multi-port services доступен с Consul 1.22+.
- **Сеть:** Открыты порты 8300 (RPC), 8301 (Serf LAN), 8302 (Serf WAN), 8500 (HTTP), 8502 (gRPC), 8600 (DNS).
- **NTP-синхронизация:** Расхождения времени между узлами >1s приводят к некорректной работе TTL и anti-entropy. Используйте `chrony` или `systemd-timesyncd`.
- **Ресурсы сервера:** Для кластеров >50 узлов рекомендуется минимум 2 CPU cores и 4GB RAM на сервер. Catalog v2 увеличивает объем метаданных на экземпляр.
- **ACL:** При включенных ACL создайте политики с правами `service:read`, `service:write`, `node:read` для операций с каталогом.
- **Enterprise:** Для Admin Partitions, Namespaces, DNS Views и Sameness Groups требуется лицензия Consul Enterprise.

## Основные концепции

### Эволюция: Catalog v1 vs Catalog v2

- **Catalog v1 (Legacy):** Каждый экземпляр сервиса жестко привязан к одной паре IP:Port. Чтобы приложение слушало HTTP и gRPC, нужно было регистрировать два независимых сервиса, что усложняло настройку [ACL](./consul_acl.md) и мониторинг.
- **Catalog v2 (Modern):** Вводит абстракцию **Workload**. Один инстанс нагрузки (Workload) может иметь множество именованных портов. Это позволяет обращаться к разным интерфейсам приложения через единую сущность в каталоге, упрощая инъекцию сайдкаров и управление трафиком.

### Ключевые сущности каталога

| Сущность | Описание | Основные поля |
| :--- | :--- | :--- |
| **Datacenter (DC)** | Логическая группа узлов с низкой сетевой задержкой. | `name` |
| **Admin Partition** | (Enterprise) Высший уровень изоляции для разделения административных границ. | `name` |
| **Namespace** | Логическая изоляция внутри раздела для разных команд или окружений. | `name`, `partition` |
| **Workload** | (Catalog v2) Физический экземпляр приложения. | `WorkloadIdentity`, `Ports` |
| **Node** | Узел (хост), на котором запущен агент Consul. | `Node`, `Address`, `Meta` |
| **Service** | Логическое определение приложения, объединяющее один или несколько портов. | `Name`, `ID`, `Tags`, `Meta` |

### Группы идентичности (Sameness Groups)

Механизм логического объединения идентичных сервисов, распределенных по разным разделам (Partitions) или пиринговым кластерам (Peers).
- **Единое пространство:** Позволяют рассматривать набор инстансов в разных регионах как один глобальный сервис.
- **Глобальный Failover:** Автоматическое переключение трафика на резервные инстансы в другом кластере при сбое локальных без изменения конфигурации клиента.
- **Упрощение политик:** Intentions (права доступа) можно задавать сразу для всей группы, а не для каждого кластера по отдельности.

### Жизненный цикл записи в каталоге

1. **Регистрация:** Сервис добавляется в каталог через `/v1/agent/service/register` или статическую конфигурацию.
2. **Распространение:** Агент отправляет локальное состояние на серверы через RPC (порт 8300).
3. **Репликация:** Лидер Raft реплицирует изменения на follower-серверы.
4. **Anti-entropy:** Периодическая сверка локального состояния агента с глобальным каталогом для исправления расхождений.
5. **Фильтрация по здоровью:** При запросах через DNS или HTTP API Consul возвращает только инстансы со статусом `passing` (если не указан флаг `?passing=false`).
6. **Дерегистрация:** При корректном завершении (`consul leave`) или по истечении `deregister_critical_service_after` запись удаляется из каталога.

## Практические сценарии

### Регистрация мультипортового сервиса (HCL)

Пример конфигурации современного приложения (`order-service.hcl`) с использованием метаданных для фильтрации:

```hcl
service {
  name    = "order-service"
  id      = "order-node-01" # Уникальный ID обязателен для предотвращения конфликтов
  address = "10.42.0.25"
  
  # Определение списка портов (Consul 1.22+)
  ports = [
    {
      name    = "http"
      port    = 8080
      default = true  # Основной порт для обычных DNS-запросов (A-записи)
    },
    {
      name = "metrics"
      port = 9090
    }
  ]

  tags = ["v2", "stable"]
  meta = { 
    team = "billing"
    version = "2.4.1"
    environment = "production"
  }

  check {
    name     = "HTTP Health Check"
    http     = "http://10.42.0.25:8080/health"
    interval = "10s"
    deregister_critical_service_after = "5m" # Автоудаление "призраков"
  }
}
```

### Динамическая регистрация через HTTP API

Регистрация сервиса через curl:

```bash
curl --request PUT http://localhost:8500/v1/agent/service/register -d '{
  "ID": "redis-01",
  "Name": "redis",
  "Tags": ["primary", "v1"],
  "Address": "10.0.0.12",
  "Port": 6379,
  "Meta": {
    "team": "platform",
    "tier": "cache"
  },
  "Check": {
    "HTTP": "http://10.0.0.12:8080/health",
    "Interval": "10s"
  }
}'
# → 200 OK
```

Проверка регистрации:

```bash
curl -s http://localhost:8500/v1/catalog/service/redis | jq .
# → [{"ID":"redis-01","Service":"redis","Address":"10.0.0.12","Port":6379,...}]
```

### Дерегистрация сервиса

```bash
curl --request PUT http://localhost:8500/v1/agent/service/deregister/redis-01
# → 200 OK

# Проверка удаления
curl -s http://localhost:8500/v1/catalog/service/redis | jq .
# → []
```

### DNS Интерфейс (Рекомендуемый)

Consul предоставляет встроенный DNS-сервер (порт 8600) с поддержкой различных типов запросов:
- **A-записи:** `order-service.service.consul` (вернет IP всех здоровых инстансов и `default` порт).
- **SRV-записи:** Позволяют получить полную информацию о портах и весах.

```bash
dig @127.0.0.1 -p 8600 order-service.service.consul A
# → ANSWER SECTION:
#   order-service.service.consul. 0 IN A 10.42.0.25

dig @127.0.0.1 -p 8600 _http._tcp.order-service.service.consul SRV
# → ANSWER SECTION:
#   _http._tcp.order-service.service.consul. 0 IN SRV 1 1 8080 order-node-01.node.dc1.consul.
```

- **Sameness Group:** `order-service.billing-group.sg.consul` (глобальный поиск инстансов по всем кластерам группы).

### DNS Views (Enterprise)

Позволяют реализовать **Split-horizon DNS**: возвращать разные IP-адреса для одного и того же сервиса в зависимости от того, откуда пришел запрос.
- **Сценарий:** Клиентам из внутренней сети возвращаются приватные IP, а запросам из сегмента DMZ — IP-адреса прокси-шлюзов.
- **Настройка:** Привязка DNS-ответов к конкретным `Admin Partitions` или IP-диапазонам.

### HTTP API

- **Все инстансы сервиса:** `GET /v1/catalog/service/order-service`
- **Фильтрация по метаданным:**
```bash
# Поиск инстансов только команды billing
curl -s "http://localhost:8500/v1/catalog/service/order-service?filter=Service.Meta.team==\"billing\"" | jq .
# → [{"ID":"order-node-01","Service":"order-service","Address":"10.42.0.25",...}]
```
- **Consistent чтение:** Используйте параметр `?consistent`, чтобы гарантированно получить данные от лидера Raft, исключая возможность чтения устаревших данных из-за репликации.

### Подготовленные запросы (Prepared Queries)

Позволяют создавать шаблоны запросов со сложной логикой переключения (failover).

```json
{
  "Name": "order-geo-failover",
  "Service": {
    "Service": "order-service",
    "OnlyPassing": true,
    "SamenessGroup": "global-order-group"
  },
  "DNS": { "TTL": "10s" }
}
```

Создание Prepared Query через API:

```bash
curl --request PUT http://localhost:8500/v1/query -d @prepared-query.json
# → [{"ID":"8f6b775e-1c7b-4c8e-9b8a-123456789abc",...}]
```

Запрос через DNS: `order-geo-failover.query.consul`.

### Конфигурация Catalog Sync (Kubernetes)

Механизм `consul-k8s sync` автоматически транслирует K8s Services и Endpoints в каталог Consul, обеспечивая связность между legacy-инфраструктурой и кластерами Kubernetes. Настройка в values-файле Helm:

```yaml
syncCatalog:
  enabled: true
  service:
    name: "consul-k8s-sync"
  source: "Kubernetes"
  destination: "Consul"
  consulAddress: " consul-server:8500"
```

## Проверка и валидация

### Проверка статуса всех сервисов

```bash
# Список всех сервисов в каталоге
curl -s http://localhost:8500/v1/catalog/services | jq .
# → {"redis":[],"order-service":[],"postgres":[],...}

# Все инстансы конкретного сервиса
curl -s http://localhost:8500/v1/catalog/service/order-service | jq .
# → [{"ID":"order-node-01","Service":"order-service","Address":"10.42.0.25","Port":8080,...}]
```

### Проверка конкретного узла

```bash
# Все сервисы на узле
curl -s http://localhost:8500/v1/catalog/node/web-01 | jq .
# → {"Node":"web-01","Services":{"redis":{"ID":"redis-01",...},...},...}
```

### Проверка через CLI

```bash
# Список всех сервисов
consul catalog services
# → redis
#   order-service
#   postgres

# Список инстансов сервиса
consul catalog nodes -service=order-service
# → web-01 10.42.0.25  alive  true
#   web-02 10.42.0.26  alive  true

# Детали узла
consul catalog node web-01
# → Node: web-01
#   Address: 10.42.0.25
#   Services:
#     redis:
#       ID: redis-01
#       Service: redis
#       Port: 6379
```

### Валидация фильтрации по здоровью

```bash
# Проверка, что DNS возвращает только passing-инстансы
dig @127.0.0.1 -p 8600 order-service.service.consul A
# → 10.42.0.25 (только healthy инстансы)

# Проверка всех инстансов через API (включая critical)
curl -s "http://localhost:8500/v1/health/service/order-service?passing=false" | jq .
# → [{"Node":"web-01","Service":{"ID":"order-node-01",...},"CheckID":"service:redis","Status":"critical"}]
```

### Проверка Prepared Queries

```bash
# Список всех подготовленных запросов
consul query list
# → 8f6b775e-1c7b-4c8e-9b8a-123456789abc  order-geo-failover

# Выполнение запроса
dig @127.0.0.1 -p 8600 order-geo-failover.query.consul A
# → IP адрес из глобальной группы sameness
```

## Устранение неполадок (Troubleshooting)

### Симптом: Ghost/Stale Services («Сервисы-призраки»)

В каталоге отображаются инстансы сервисов, которые физически не существуют (например, старые поды в K8s).
- **Причина:** Узел или сервис были удалены некорректно (без выполнения команды `consul leave`), и сервер не получил уведомление о завершении работы.
- **Решение:** 
    - Всегда настраивайте параметр `deregister_critical_service_after` в [Health Checks](./consul_health_checks.md). Это заставит Consul автоматически вычищать неисправные записи через заданное время.
    - Ручное удаление через HTTP API:
      ```bash
      curl --request PUT http://localhost:8500/v1/catalog/deregister -d '{"Node": "node-name", "ServiceID": "service-id"}'
      # → 200 OK
      ```
    - Проверка после удаления:
      ```bash
      curl -s http://localhost:8500/v1/catalog/service/service-id | jq .
      # → []
      ```

### Симптом: Расхождения в ответах DNS и HTTP API

DNS возвращает пустой список, в то время как HTTP API (`/v1/catalog/service/...`) показывает наличие инстансов.
- **Причина:** DNS-интерфейс по умолчанию возвращает **только** инстансы со статусом `passing`. Если сервис находится в состоянии `warning` или `critical`, он будет исключен из DNS-ответа.
- **Диагностика:** Используйте HTTP API с фильтром, чтобы увидеть реальное состояние всех инстансов:
    ```bash
    curl -s "http://localhost:8500/v1/health/service/order-service?passing=false" | jq .
    # → [{"Node":"web-01","Service":{"ID":"order-node-01",...},"CheckID":"service:redis","Status":"critical"}]
    ```

### Проблемы с задержкой DNS

Клиенты продолжают обращаться к старому IP-адресу после перемещения или удаления сервиса.
- **Причина:** Слишком высокий TTL в кэше клиента или локального резолвера ОС.
- **Решение:** Убедитесь, что Consul настроен на низкий TTL (по умолчанию 0s для DNS-интерфейса), и проверьте конфигурацию `systemd-resolved` или аналогичных служб на стороне клиентов.

```bash
# Проверка TTL DNS-записей
dig @127.0.0.1 -p 8600 order-service.service.consul A
# → ANSWER SECTION:
#   order-service.service.consul. 0 IN A 10.42.0.25

# Настройка systemd-resolved для корректного обновления
sudo resolvectl flush-caches
```

### Anti-entropy расхождения

Локальное состояние агента расходится с каталогом после длительного сетевого разрыва.
- **Причина:** При разрыве связи >30s агент не может синхронизировать состояние с сервером. После восстановления Consul выполнит полную синхронизацию, что может привести к кратковременному `unknown` статусу проверок.
- **Диагностика:** Проверьте логи агента на предмет ошибок синхронизации:
    ```bash
    journalctl -u consul -f | grep -i "anti-entropy\|sync"
    # → [INFO] agent: Syncing state for service "redis"
    # → [WARN] agent: State sync failed: connection refused
    ```
- **Решение:** Убедитесь, что порт 8300 (RPC) открыт между агентами и серверами. Проверьте NTP-синхронизацию.

## Лучшие практики

- **Используйте уникальные ID:** Всегда задавайте `id`, включающий имя хоста или UUID, чтобы избежать конфликтов при регистрации нескольких инстансов одного сервиса на одном узле.
- **Настраивайте `deregister_critical_service_after`:** В динамических средах (Kubernetes, Nomad) это критически важно для предотвращения "засорения" каталога записями от удаленных или переехавших подов. Рекомендуемое значение: 5–15 минут.
- **DNS Caching:** Настраивайте минимальный TTL (1–5 сек) на стороне клиентов, если инфраструктура не поддерживает нулевой TTL, для обеспечения баланса между нагрузкой на Consul и скоростью реакции.
- **Здоровье прежде всего:** Приложения-потребители должны использовать DNS или API с обязательной фильтрацией по статусу здоровья, чтобы минимизировать ошибки соединения.
- **Catalog v2 для multi-port:** Если приложение использует несколько портов (HTTP, gRPC, metrics), используйте Catalog v2 с явным указанием именованных портов.
- **Anti-entropy мониторинг:** Настройте алерты на ошибки синхронизации состояния агента. Это указывает на сетевые проблемы или нехватку ресурсов.
- **Consistent чтение для критичных операций:** Используйте параметр `?consistent` в API-запросах для операций, где важна актуальность данных (например, проверка наличия сервиса перед развертыванием).

## Граничные случаи

- **Multi-port services и Catalog v1:** В Catalog v1 multi-port не поддерживается. Если вы попытаетесь зарегистрировать сервис с несколькими портами в старом формате, Consul проигнорирует все порты кроме первого. Используйте Catalog v2 (Consul 1.22+) для multi-port сценариев.
- **DNS Views и лицензирование:** DNS Views требуют лицензии Consul Enterprise. В Community Edition запросы DNS возвращают одинаковые ответы для всех клиентов.
- **Sameness Groups и сетевые разрывы:** При разрыве связи между кластерами Sameness Group продолжает возвращать локальные инстансы, даже если глобальные инстансы в другом кластере здоровы. После восстановления связи происходит автоматическое переключение.
- **Anti-entropy и производительность:** При большом количестве сервисов (>1000) anti-entropy может создавать значительную нагрузку на CPU агента. Используйте streaming-режим (Consul 1.20+) для снижения нагрузки.
- **Deregister и Prepared Queries:** После ручного удаления сервиса через `/v1/catalog/deregister` Prepared Queries, ссылающиеся на этот сервис, продолжают существовать. Удалите их явно через `/v1/query/:id/delete`.
- **Consistent чтение и задержки:** Параметр `?consistent` увеличивает задержку запроса, так как требует подтверждения от лидера Raft. Используйте его только для критичных операций, а не для частых health-check запросов.
- **Catalog Sync и метаданные:** При использовании `consul-k8s sync` метаданные K8s Services (аннотации) могут не полностью транслироваться в Consul. Проверяйте поля `Meta` в каталоге после синхронизации.
- **WorkloadIdentity и ACL:** В Catalog v2 поле `WorkloadIdentity` используется для идентификации нагрузки в Service Mesh. Убедитесь, что ACL-политики разрешают доступ к `workload:read` для корректной работы mesh-сценариев.

## Дополнительная информация

- **[Обзор архитектуры](./consul_architecture.md)** — механизмы репликации каталога и anti-entropy.
- **[Проверки состояния](./consul_health_checks.md)** — как статусы здоровья влияют на видимость в каталоге.
- **[Service Mesh: основные концепции](../Service_Mesh/service_mesh_concepts.md)** — как Envoy агрегирует проверки здоровья в mesh-средах.
- **[Consul Consensus](./consul_consensus.md)** — Raft-репликация и согласованность данных.
- **[Consul ACL](./consul_acl.md)** — управление доступом к каталогу.
- **[Consul Network Segments](./consul_network_segments.md)** — разбиение gossip-пула для больших кластеров.
- **[Consul DNS Caching Strategies](./consul_dns_caching.md)** — стратегии кэширования DNS.
- **[DNS Interface Specification](https://developer.hashicorp.com/consul/docs/discovery/dns)** — подробный справочник по форматам запросов.
- **[Consul Catalog API](https://developer.hashicorp.com/consul/api-docs/catalog)** — документация по HTTP API каталога.
- **[Cluster Peering](./consul_overview.md#мультикластерность)** — федерация каталогов между независимыми кластерами.
