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

Поскольку [Angie](./angie_overview.md) является форком Nginx, её функциональность проксирования на уровне L4 полностью унаследована от Nginx и работает идентично. Все директивы (`server`, `upstream`, `proxy_pass`, `ssl_preread`, `limit_conn`) и переменные в модуле `stream` полностью совпадают.

**Основная документация и детальные сценарии использования:**
> **[Балансировка и проксирование L4-трафика (TCP/UDP) в Nginx](../Nginx/Proxy/nginx_l4_proxying.md)**

Ниже приведены ключевые отличия при настройке L4-проксирования в Angie.

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

### Таблица соответствия путей

| Компонент | Nginx | Angie |
| :--- | :--- | :--- |
| **Главный конфигурационный файл** | `/etc/nginx/nginx.conf` | `/etc/angie/angie.conf` |
| **Директория для `stream` конфигов** | `/etc/nginx/stream.d/` | `/etc/angie/stream.d/` |
| **Лог доступа `stream`** | `/var/log/nginx/stream-access.log` | `/var/log/angie/stream-access.log` |
| **Лог ошибок `stream`** | `/var/log/nginx/stream-error.log` | `/var/log/angie/stream-error.log` |

### Логирование в `stream`

По умолчанию логирование в модуле `stream` отключено. Настраивается через `access_log`. Фиксируются параметры сессии, а не запросов.

**Переменные для логирования:**

- `$remote_addr` — IP-адрес клиента
- `$time_local` — локальное время
- `$protocol` — протокол (TCP/UDP)
- `$status` — статус сессии
- `$bytes_sent` — отправленные байты
- `$bytes_received` — полученные байты
- `$session_time` — продолжительность сессии
- `$upstream_addr` — адрес upstream-сервера

### Ограничение подключений

В `stream` можно ограничивать количество одновременных подключений (`limit_conn`), но не частоту запросов (`limit_req`), так как понятия запроса нет.

```nginx
stream {
    limit_conn_zone $binary_remote_addr zone=per_ip:10m;

    server {
        listen 12345;
        limit_conn per_ip 10; # До 10 подключений с одного IP
        proxy_pass backend_service;
    }
}
```

## Практические сценарии

### Сценарий: проксирование MySQL (TCP) с балансировкой master/slave

Распределение нагрузки между master-сервером БД (на запись) и slave-серверами (на чтение).

**Пример конфигурации (`/etc/angie/stream.d/mysql.conf`):**

```nginx
# Группа для мастера (запись)
upstream mysql_master {
    zone mysql_master_zone 64k;
    server 192.168.77.14:3307 proxy_protocol;
}

# Группа для слейвов (чтение)
upstream mysql_slave {
    zone mysql_slave_zone 64k;
    server 192.168.77.12:3308 proxy_protocol;
    server 192.168.77.13:3309 proxy_protocol;
}

# Виртуальный сервер для мастера
server {
    listen 6306;
    proxy_pass mysql_master;

    # Ограничение подключений для защиты мастера
    limit_conn_zone $binary_remote_addr zone=per_ip_conn:10m;
    limit_conn per_ip_conn 10;

    access_log /var/log/angie/mysql-master-access.log basic;
    error_log /var/log/angie/mysql-master-error.log warn;
    status_zone mysql_master_status;
}

# Виртуальный сервер для слейвов
server {
    listen 6307;
    proxy_pass mysql_slave;
    status_zone mysql_slave_status;
}
```

**Разбор конфигурации:**

1. **Блоки `upstream`:**
   - `zone <name> 64k;` — выделяет общую память для хранения состояния группы (статистика соединений, динамическое управление).
   - `server ... proxy_protocol;` — включает **[Proxy Protocol](../../../Networking/Protocols/proxy_protocol.md)** — добавляет к TCP-соединению заголовок с реальным IP-адресом клиента. Без этого БД видит только IP Angie.

2. **Блоки `server`:**
   - `listen 6306;` — виртуальный TCP-сервер на порту `6306`.
   - `proxy_pass mysql_master;` — направление трафика в upstream `mysql_master`.
   - `limit_conn_*` — ограничение одновременных соединений с одного IP для защиты мастера.
   - `status_zone <name>;` — зона статистики для мониторинга через API Angie.

### Сценарий: SSL/TLS терминация на L4

Angie принимает зашифрованные соединения, расшифровывает и проксирует трафик в открытом виде.

```nginx
# /etc/angie/stream.d/ssl_termination.conf
upstream web_backend {
    server 127.0.0.1:9001;
}

server {
    listen 9443 ssl;
    ssl_certificate /etc/angie/certs/server.crt;
    ssl_certificate_key /etc/angie/certs/server.key;
    proxy_pass web_backend; # Проксирование на незашифрованный бэкенд
}
```

Подробнее: [Настройка TLS в Angie](./angie_tls_setup.md).

### Сценарий: SSL Pre-read (маршрутизация TLS vs SSH)

Функция SSL Pre-read позволяет Angie «заглянуть» в начало TCP-соединения и определить тип трафика без полной терминации сессии.

**Пример: мультиплексирование HTTPS и SSH на одном порту (например, 443)**
Это позволяет обходить ограничения брандмауэров, разрешающих только 443 порт.

```nginx
# /etc/angie/stream.d/ssl_preread.conf
map $ssl_preread_protocol $backend_by_protocol {
    "TLSv1.2"  http_backend;
    "TLSv1.3"  http_backend;
    default    ssh_backend; # Если протокол не распознан как TLS (например, SSH)
}

upstream http_backend {
    server 127.0.0.1:8443;
}
upstream ssh_backend {
    server 127.0.0.1:22;
}

server {
    listen 443;

    ssl_preread on; # Включаем анализ рукопожатия (handshake)
    proxy_pass $backend_by_protocol;

    status_zone ssl_preread_status;
}
```

**Особенности:**

- **`$ssl_preread_protocol`**: переменная содержит версию протокола TLS. Если это не TLS-трафик, переменная будет пустой, и `map` выберет `default` (SSH).
- **Без терминации SSL**: Angie не расшифровывает трафик для `http_backend`, она просто перенаправляет байты после анализа начала сессии.

### Сценарий: проксирование UDP (DNS)

Angie проксирует UDP-трафик, например для DNS-серверов. Поскольку UDP не имеет состояния (без установления соединения), Angie имитирует сессии для управления трафиком.

```nginx
# /etc/angie/stream.d/udp_dns.conf
upstream dns_servers {
    zone dns_upstreams 64k;
    server 8.8.8.8:53;
    server 1.1.1.1:53;
}

server {
    listen 53 udp; # UDP-порт
    listen 53;     # TCP-порт (DNS использует оба)

    # Ожидание ровно одного ответа от бэкенда перед закрытием "сессии"
    proxy_responses 1; 
    
    # Тайм-аут ожидания ответа
    proxy_timeout 3s;

    proxy_pass dns_servers;
}
```

**Особенности:**

- **`proxy_responses`**: Критически важная директива для UDP. Она сообщает Angie, сколько пакетов-ответов ожидать от бэкенда, прежде чем считать транзакцию завершенной. Для DNS это обычно 1.
- **Отсутствие конвертации**: UDP проксируется как UDP, TCP — как TCP. Angie не умеет конвертировать UDP в TCP (например, для DNS over TCP) «из коробки» без дополнительных модулей.

## Дополнительная информация

### Мониторинг L4-трафика

Для сбора метрик используется `status_zone` в блоке `server` модуля `stream`.

```nginx
stream {
    server {
        listen 12345;
        proxy_pass backend_service;
        status_zone my_l4_service; # Зона для сбора метрик
    }
}
```

Метрики (активные соединения, трафик и т.д.) доступны через API Angie (модуль `ngx_http_stub_status_module` или Angie API).

Подробнее: [Мониторинг Angie](./angie_monitoring/angie_monitoring_concepts.md).

### See also

- [Основы Angie](./angie_overview.md)
- [Балансировка и проксирование L4-трафика в Nginx](../Nginx/Proxy/nginx_l4_proxying.md)
- [Концепции проксирования](../../../Networking/Concepts/proxy.md)
