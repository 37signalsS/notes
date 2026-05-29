# Определения

**Каталог служб (Service Catalog)** в Consul — это централизованный реестр, который хранит информацию обо всех зарегистрированных сервисах, их экземплярах (инстансах), метаданных, местоположении (IP (Internet Protocol), порт) и [состоянии здоровья](./consul_health_checks.md). Это ядро механизма обнаружения сервисов (Service Discovery).

# Основные концепции

## Ключевые сущности каталога

| Сущность | Описание | Ключевые поля |
| :--- | :--- | :--- |
| **Datacenter (DC)** | Логическая группа узлов, обычно соответствующая физическому ЦОД (Центр Обработки Данных) или региону облака. | `name` |
| **Node** | Узел (хост), на котором запущен агент Consul и зарегистрированы сервисы. | `Node`, `Address`, `Meta` |
| **Service** | Экземпляр приложения, доступный по сети. | `Name`, `ID`, `Address`, `Port`, `Tags`, `Meta` |
| **Check** | Проверка состояния, привязанная к сервису или узлу. | `Status`, `Type`, `Interval` |
| **Partition/Namespace** | Административные границы для изоляции каталогов (функция Consul Enterprise). | `namespace`, `partition` |

**Name vs ID:**

- `Name` — логическое имя сервиса (например, `api-gateway`).
- `ID` — уникальный идентификатор конкретного экземпляра (например, `api-gateway-1`).
Несколько экземпляров с одинаковым `Name` образуют пул для балансировки нагрузки.

## Регистрация сервисов

Сервисы могут быть зарегистрированы несколькими способами:

- **Статически:** через конфигурационные файлы агента (например, в `/etc/consul.d/`). Подходит для долгоживущих сервисов.
- **Динамически:** через HTTP (HyperText Transfer Protocol) API (Application Programming Interface) или CLI (Command Line Interface) локального агента. Используется для эфемерных сервисов (например, в контейнерах).
- **Автоматически:** через интеграции, например, с Kubernetes (`consul-k8s`) или Nomad.

# Практические сценарии

## Регистрация сервиса с проверкой

Пример определения сервиса в формате HCL (HashiCorp Configuration Language). Файл `web.hcl`:

```hcl
service {
  name    = "web"
  id      = "web-1"
  address = "10.0.1.12"
  port    = 80
  tags    = ["frontend", "v2"]
  meta    = { team = "webapp", version = "2.1.0" }

  check {
    name     = "http-health"
    http     = "http://10.0.1.12/health"
    interval = "10s"
    timeout  = "2s"
  }
}
```

Регистрация через CLI:

```bash
consul services register ./web.hcl
# -> Registered service: web
```

## Обнаружение сервисов

### Через HTTP API

- **Все сервисы:** `GET /v1/catalog/services`
- **Экземпляры сервиса:** `GET /v1/catalog/service/<service_name>`
- **"Здоровые" экземпляры:** `GET /v1/health/service/<service_name>`

По умолчанию API-запросы обслуживаются в режиме `stale` (нестрогая согласованность) для скорости. Для получения гарантированно актуальных данных добавьте параметр `?consistent`.

Пример запроса через `curl`:

```bash
curl http://127.0.0.1:8500/v1/health/service/web?passing
# -> [{"Node":{...},"Service":{"ID":"web-1","Service":"web","Tags":["frontend","v2"],"Address":"10.0.1.12","Port":80,...},"Checks":[...]}]
```

### Через CLI

```bash
# Список сервисов
consul catalog services
# -> consul
# -> web

# Узлы с сервисом
consul catalog nodes -service web
# -> Node   ID        Address    Service
# -> node1  a1b2c3d4  10.0.1.12  web

# "Здоровые" экземпляры
consul health service web --passing
# -> Node   Check         Status
# -> node1  http-health   passing
```

### DNS (Domain Name System) интерфейс

Агент Consul предоставляет DNS-сервер (по умолчанию на порту `8600`) для обнаружения сервисов через стандартные DNS-запросы:

- **A-записи:** `web.service.consul` возвращает IP-адреса "здоровых" экземпляров.
- **SRV (Service Record) записи:** `_web._tcp.service.consul` возвращает IP, порты, веса и приоритеты.

Примеры запросов:

```bash
# A-запись
dig @127.0.0.1 -p 8600 web.service.consul
# -> web.service.consul. 0 IN A 10.0.1.12

# SRV-запись
dig @127.0.0.1 -p 8600 _web._tcp.service.consul SRV
# -> _web._tcp.service.consul. 0 IN SRV 1 1 80 node1.node.dc1.consul.
```

DNS-ответы по умолчанию включают только экземпляры со статусом `passing`.

### Фильтрация

- **По тегам:** `v2.web.service.consul` возвращает только экземпляры с тегом `v2`.
- **По состоянию:** DNS по умолчанию возвращает только `passing`. API позволяет запрашивать все и фильтровать на стороне клиента.
- **По метаданным:** API поддерживает язык выражений `filter` для гибкой фильтрации по полям `Meta`.

# Дополнительная информация

- **[Обзор Consul](./consul_overview.md)** — общая архитектура и компоненты.
- **[HashiCorp: Discover Services](https://developer.hashicorp.com/consul/tutorials/service-discovery/discover-services)** — официальный туториал по обнаружению.
- **[HashiCorp: DNS Interface](https://developer.hashicorp.com/consul/docs/discovery/dns)** — спецификация DNS-интерфейса.
