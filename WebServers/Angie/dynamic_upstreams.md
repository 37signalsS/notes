# Динамические группы проксируемых серверов в Angie

## Определения

- **Upstream (группа вышестоящих серверов)**: Именованная группа бэкенд-серверов в конфигурации [Angie](./angie_overview.md)/Nginx, между которыми распределяется нагрузка. Подробнее: [Балансировка нагрузки HTTP(S) в Angie](./angie_http_load_balancing.md).
- **Динамический Upstream**: Upstream-группа, состав которой может изменяться автоматически "на лету" на основе внешних источников данных (DNS, API), без необходимости ручной перезагрузки конфигурации.

## Основные концепции

Механизм динамических апстримов является реализацией концепции **обнаружения сервисов (Service Discovery)**. В современных [микросервисных архитектурах](../../Concepts/monolith_vs_microservices.md) экземпляры сервисов могут часто создаваться и уничтожаться. Жестко прописанные IP-адреса в конфигурации балансировщика становятся неэффективными.

Angie решает эту проблему, предоставляя несколько встроенных способов автоматического обнаружения бэкендов.

## Практические сценарии

### Сценарий 1: Использование DNS A-записей

Самый простой способ. За одной DNS A-записью закрепляется несколько IP-адресов, и Angie периодически опрашивает DNS для обновления списка серверов.

#### Конфигурация

В `http` блоке указывается `resolver` (DNS-сервер), а в блоке `upstream` используется доменное имя с параметром `resolve`.

```nginx
http {
    # ...
    
    resolver 1.1.1.1 valid=5s; # Указываем адрес DNS-сервера, valid - время кеширования ответа

    upstream backend {
        zone backend 64k;
        server backend.example.com resolve; # Флаг, который указывает Angie периодически переопределять DNS-имя в IP-адреса. Время кеширования ответа (TTL) берется из самой DNS-записи.
        # status_zone backend_status; # Опционально: зона для мониторинга в Angie Console Light
    }

    server {
        listen 80;

        location / {
            proxy_pass http://backend;
        }
    }
}
```

Этот метод прост, но не позволяет управлять портами или весами для каждого сервера.

### Сценарий 2: Использование DNS SRV-записей

Более гибкий метод, использующий **[SRV-записи в DNS](../../Networking/Protocols/DNS/dns_records.md)**, которые позволяют указать для службы хост, порт, вес и приоритет каждого сервера.

#### Конфигурация DNS (пример для BIND)

```text
; _http._tcp.backend.local.lan.
_http._tcp.backend.local.lan. 60 IN SRV 10 2 9001 server1.local.lan.
_http._tcp.backend.local.lan. 60 IN SRV 10 1 9002 server2.local.lan.
```

#### Конфигурация Angie

В директиве `server` добавляется параметр `service`.

```nginx
http {
    resolver 10.0.0.1; # Локальный DNS

    upstream backend_srv {
        zone backend_srv 64k;
        server backend.local.lan resolve service=http; # Ищем SRV-запись для службы http
    }
}
```

### Сценарий 3: Использование Docker Labels

В контейнерных средах Angie может подключаться к Docker-сокету, читать метки (labels) у контейнеров и на их основе формировать апстрим-группу.

#### Конфигурация Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  backend1:
    image: my-app:1.0
    networks:
      - app-net
    labels:
      - "angie.http.upstreams.my_app.server=backend1:8080" # Адрес и порт внутри Docker-сети
      - "angie.http.upstreams.my_app.weight=2"
      - "angie.http.upstreams.my_app.max_fails=3"

  backend2:
    image: my-app:1.0
    networks:
      - app-net
    labels:
      - "angie.http.upstreams.my_app.server=backend2:8080"
      - "angie.http.upstreams.my_app.weight=1"

networks:
  app-net:
    driver: bridge
```

**Формат меток:**

- `angie.http.upstreams.<upstream_name>.server=<internal_address>:<internal_port>`: Определяет сервер для апстрима с именем `<upstream_name>`. Адрес — это имя сервиса и *внутренний* порт внутри Docker-сети.
- `angie.http.upstreams.<upstream_name>.<parameter>=<value>`: Задает дополнительные параметры, такие как `weight`, `max_fails` и др.

### Конфигурация Angie

В конфигурации Angie, которая может быть установлена из пакетов (см. [руководство по установке](./angie_installation.md)), необходимо указать путь к Docker-сокету и определить пустой апстрим-блок.

```nginx
# /etc/nginx/conf.d/docker_upstream.conf

http {
    # ...

    # Указываем путь к сокету Docker
    docker endpoint unix:/var/run/docker.sock;

    # Пустой апстрим, который будет заполнен на основе меток
    upstream my_app {
        zone my_app 64k;
        # Серверы будут добавлены автоматически
    }

    server {
        listen 80;
        location / {
            proxy_pass http://my_app;
        }
    }
}
```

**Важно:** Пользователь, от имени которого работает Angie (например, `www-data`), должен иметь права на чтение и запись для Docker-сокета.

## Дополнительная информация

- Функциональность динамического разрешения DNS (`resolve`), ранее доступная только в Nginx Plus, была реализована в open-source версии Angie с самого начала, а позже появилась и в Nginx.
- Альтернативными внешними системами для обнаружения сервисов являются, например, [Consul](../../Consul/consul_overview.md).
- Корректность работы динамических апстримов можно проверить через веб-интерфейс **Angie Console Light**.
