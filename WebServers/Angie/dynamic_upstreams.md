# Динамические группы проксируемых серверов в Angie

## Определения

- **Upstream (группа вышестоящих серверов)** — именованная группа бэкенд-серверов, между которыми балансировщик распределяет входящие запросы.
- **Динамический Upstream** — группа серверов, состав которой (IP-адреса, порты, веса) обновляется автоматически без перезагрузки конфигурации.
- **Обнаружение сервисов (Service Discovery)** — процесс автоматического поиска адресов экземпляров сервисов в распределённой сети.

## Основные концепции

В современных [микросервисных архитектурах](../../Concepts/monolith_vs_microservices.md) экземпляры приложений постоянно создаются и уничтожаются (масштабирование, рестарты, обновление версий). Использование статически прописанных IP-адресов в конфигурации балансировщика приводит к ошибкам при изменении инфраструктуры.

Динамические апстримы позволяют Angie адаптироваться к изменениям в реальном времени, используя внешние источники данных как реестр сервисов (DNS, Docker API). Это избавляет от необходимости генерировать новые конфигурационные файлы и выполнять `reload` сервера.

## Практические сценарии

### Сценарий 1: Динамическое разрешение DNS (A/AAAA)

Angie периодически опрашивает DNS-сервер для обновления IP-адресов бэкендов. Этот метод эффективен для простых сред с фиксированными портами.

**Конфигурация:**

```nginx
http {
    # Резолвер обязателен для работы параметра resolve
    resolver 1.1.1.1 valid=10s;

    upstream backend {
        zone backend 64k;
        # server разрешает домен один раз при старте, resolve — периодически
        server backend.example.com resolve;
    }

    server {
        listen 80;
        location / {
            proxy_pass http://backend;
        }
    }
}
```

Подробное описание механизма, параметров `resolver` и `resolve`: [Динамическое разрешение DNS в Nginx/Angie](../Nginx/Proxy/Load_Balancing/dynamic_dns_resolution.md).

### Сценарий 2: Использование DNS SRV-записей

Более гибкий метод, позволяющий через DNS передавать не только IP-адрес, но и порт, вес и приоритет каждого сервера. Это стандартный способ обнаружения сервисов в таких системах, как [Consul](../../Consul/consul_overview.md).

**Пример SRV-записи:**
`_http._tcp.backend.local. 60 IN SRV 10 60 8080 s1.local.`

**Конфигурация Angie:**

```nginx
http {
    resolver 10.0.0.1;

    upstream backend_srv {
        zone backend_srv 64k;
        # Параметр service указывает на использование SRV-записей
        server backend.local resolve service=http;
    }
}
```

Подробнее о структуре записей: [Типы записей DNS — SRV](../../Networking/Protocols/DNS/dns_records.md#записи-для-сервисов).

### Сценарий 3: Интеграция с Docker Labels

Angie может напрямую подключаться к Docker API (через сокет), отслеживать запуск контейнеров и автоматически добавлять их в апстрим на основе меток (labels). Это избавляет от зависимости от внешнего DNS.

**Конфигурация Docker (labels):**

```yaml
services:
  app_v1:
    image: my-app:latest
    labels:
      - "angie.http.upstreams.webapp.server=app_v1:8080"
      - "angie.http.upstreams.webapp.weight=2"
      - "angie.http.upstreams.webapp.max_fails=3"
```

**Конфигурация Angie:**

```nginx
http {
    # Путь к сокету Docker (требуются права на чтение/запись)
    docker endpoint unix:/var/run/docker.sock;

    upstream webapp {
        zone webapp 64k;
        # Список серверов формируется автоматически из labels
    }

    server {
        listen 80;
        location / {
            proxy_pass http://webapp;
        }
    }
}
```

Основы сетевого взаимодействия в контейнерах: [DNS и Service Discovery в Docker](../../Docker/Docker_network/dns_and_service_discovery.md).

## Дополнительная информация

- **Мониторинг:** актуальное состояние динамических групп (список активных серверов, их веса и статус) доступно через модуль статистики [Angie Console Light](./angie_monitoring/angie_monitoring_console.md).
- **Лимиты:** использование динамических апстримов требует выделения разделяемой памяти через директиву `zone`.
- **Смежные темы:**
  - [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)
  - [Балансировка и проксирование L4 (TCP/UDP)](./l4_balancing_and_proxying.md)
  - [Миграция с Nginx на Angie](./migration_from_nginx.md)
