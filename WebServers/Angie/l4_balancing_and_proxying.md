# Балансировка и проксирование L4-трафика (TCP/UDP) в Angie

## Определения

**Модуль `stream` в Angie** — расширение функциональности, предоставляющее возможности балансировки нагрузки и проксирования трафика на **уровне L4 (Transport layer)**. Позволяет работать с протоколами, не основанными на HTTP: базами данных (MySQL, PostgreSQL), DNS, NTP, SSH и др.

**L4 vs L7 проксирование:**

- **L7 (Application layer):** Angie работает с HTTP-трафиком в контексте `http`, обрабатывая запросы на уровне приложения.
- **L4 (Transport layer):** Модуль `stream` работает на уровне транспорта (TCP/UDP), проксируя соединения без разбора содержимого.
- **Ключевые отличия:**
  - Уровень работы: L4 (TCP/UDP) вместо L7 (HTTP/S)
  - Протоколы: любые TCP/UDP-протоколы (базы данных, DNS, NTP, SSH)
  - Обработка: сессии подключения вместо отдельных запросов
  - Ресурсы: меньше накладных расходов, так как не требуется разбор протокола приложения

## Основные концепции

Функциональность проксирования на уровне L4 в [Angie](./angie_overview.md) полностью унаследована от Nginx и работает идентично. Все директивы (`server`, `upstream`, `proxy_pass`, `ssl_preread`, `limit_conn`) и переменные в модуле `stream` полностью совпадают.

Подробный разбор синтаксиса, флагов и детальные сценарии использования приведены в основном справочнике: [Балансировка и проксирование L4-трафика (TCP/UDP) в Nginx](../Nginx/Proxy/nginx_l4_proxying.md).

### Конфигурация и основные директивы

Для использования L4-функциональности в `angie.conf` должен присутствовать блок `stream`.

```nginx
# /etc/angie/angie.conf
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time "$upstream_addr"';

    access_log /var/log/angie/stream-access.log basic;

    # Включение конфигураций из stream.d
    include /etc/angie/stream.d/*.conf;
}
```

### Инфраструктурные особенности Angie

| Компонент | Путь в Angie |
| :--- | :--- |
| Главный конфигурационный файл | `/etc/angie/angie.conf` |
| Директория для `stream` конфигов | `/etc/angie/stream.d/` |
| Лог доступа `stream` | `/var/log/angie/stream-access.log` |
| Лог ошибок `stream` | `/var/log/angie/stream-error.log` |

### Ограничение подключений

В модуле `stream` можно ограничивать количество одновременных подключений (`limit_conn`), но не частоту запросов (`limit_req`).

```nginx
stream {
    limit_conn_zone $binary_remote_addr zone=per_ip:10m;

    server {
        listen 12345;
        limit_conn per_ip 10;
        proxy_pass backend_service;
    }
}
```

## Практические сценарии

### Сценарий 1: Проксирование MySQL (TCP) с балансировкой master/slave

Распределение трафика между мастером (на запись) и репликами (на чтение) с использованием [Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md).

**Конфигурация (`/etc/angie/stream.d/mysql.conf`):**

```nginx
upstream mysql_master {
    zone mysql_master_zone 64k;
    server 192.168.77.14:3307 proxy_protocol;
}

upstream mysql_slave {
    zone mysql_slave_zone 64k;
    server 192.168.77.12:3308 proxy_protocol;
    server 192.168.77.13:3309 proxy_protocol;
}

server {
    listen 6306;
    proxy_pass mysql_master;
    status_zone mysql_master_status;
}

server {
    listen 6307;
    proxy_pass mysql_slave;
    status_zone mysql_slave_status;
}
```

### Сценарий 2: SSL Pre-read (HTTPS и SSH на одном порту)

Маршрутизация трафика на основе анализа начала TCP-соединения без его терминации.

```nginx
map $ssl_preread_protocol $backend_by_protocol {
    "TLSv1.2"  http_backend;
    "TLSv1.3"  http_backend;
    default    ssh_backend;
}

upstream http_backend { server 127.0.0.1:8443; }
upstream ssh_backend  { server 127.0.0.1:22; }

server {
    listen 443;
    ssl_preread on;
    proxy_pass $backend_by_protocol;
}
```

### Сценарий 3: Проксирование UDP (DNS)

Для UDP важно ограничивать количество ответов и устанавливать тайм-ауты.

```nginx
upstream dns_servers {
    server 8.8.8.8:53;
    server 1.1.1.1:53;
}

server {
    listen 53 udp;
    listen 53; # TCP
    proxy_responses 1;
    proxy_timeout 3s;
    proxy_pass dns_servers;
}
```

## Дополнительная информация

### Мониторинг L4-трафика

Для сбора метрик используется директива `status_zone`. Метрики доступны через API Angie и могут быть интегрированы с внешними системами мониторинга.

Подробнее: [Мониторинг Angie](./angie_monitoring/angie_monitoring_concepts.md).

### См. также

- [Основы Angie](./angie_overview.md)
- [Балансировка и проксирование L4-трафика в Nginx](../Nginx/Proxy/nginx_l4_proxying.md)
- [Концепции проксирования](../../../Networking/Concepts/proxy.md)
