# Proxy Protocol

## Определения

**Proxy Protocol** — сетевой протокол, разработанный командой HAProxy, предназначенный для передачи метаданных о первоначальном соединении (IP-адреса и порты клиента и сервера) через цепочки прокси-серверов или балансировщиков нагрузки.

**Главное назначение:** сохранение идентичности клиента при проксировании на **транспортном уровне (L4)**, где прикладные заголовки (например, HTTP `X-Forwarded-For`) недоступны или нежелательны из-за накладных расходов на парсинг.

### Сравнение механизмов передачи Source IP

| Характеристика | Proxy Protocol (L4) | X-Forwarded-For (L7) |
| :--- | :--- | :--- |
| **Уровень OSI** | Layer 4 (TCP/UDP) | Layer 7 (HTTP) |
| **Оверхед** | Минимальный (однократная вставка в начало) | Высокий (парсинг и модификация каждого запроса) |
| **Протоколы** | Любые поверх TCP/UDP (MySQL, DNS, SMTP) | Только HTTP/gRPC/Websocket |
| **Видимость** | Невидим для приложения (нужна поддержка в сервере) | Виден приложению как стандартный заголовок |
| **Безопасность** | Сложнее подделать (требует контроля соединения) | Легко инъектировать в HTTP-запрос |

> **См. также:** **[Прокси-серверы — концепции](../../Networking/Concepts/proxy.md)**, **[Протокол TCP](./TCP/overview.md)**, **[Nginx L4 Proxying](../../WebServers/Nginx/Proxy/nginx_l4_proxying.md)**

## Основные концепции

### Версии протокола

#### Proxy Protocol v1 (текстовый)
Человекочитаемый формат, представляющий собой одну строку в формате ASCII, которая отправляется **сразу после установки TCP-соединения**, перед любыми данными приложения.

- **Формат:** `PROXY <protocol> <src-IP> <dst-IP> <src-port> <dst-port>\r\n`
- **Пример:** `PROXY TCP4 192.168.1.50 10.0.0.1 56324 443\r\n`
- **Особенности:** прост в отладке через `tcpdump` или `nc`. Максимальная длина ограничена 108 байтами.

#### Proxy Protocol v2 (бинарный)
Оптимизированный бинарный формат с поддержкой расширений. Рекомендуется для высоконагруженных систем и сложных топологий.

- **Магическая подпись (Signature):** 12 байт `\x0D\x0A\x0D\x0A\x00\x0D\x0A\x51\x55\x49\x54\x0A` (ASCII: `\r\n\r\n\0\r\nQUIT\n`). Позволяет серверу мгновенно отличить протокол от данных приложения.
- **Поддержка протоколов:** TCP/UDP поверх IPv4/IPv6, UNIX-сокеты.

#### Механизм TLV (Type-Length-Value) в v2
Позволяет передавать дополнительные атрибуты соединения без изменения структуры заголовка:
- **0x01 (ALPN):** Согласованный протокол (например, `h2`, `http/1.1`).
- **0x02 (Authority):** Hostname, переданный клиентом (SNI).
- **0x20-0x2F (SSL):** Детали TLS-соединения (версия, шифр, статус проверки клиентского сертификата).
- **0xEA (Unique ID):** Уникальный ID запроса для трассировки (используется в AWS, GCP).

#### Структура v2 заголовка (байтовое представление)

```
Proxy Protocol v2 — бинарный заголовок (16 + 0-16 байт TLV):

 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+                                                               +
|                    Signature (12 bytes)                        |
+                       0x0D 0A 0D 0A 0x00 0D 0A 51 55 49 54 0A+
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Version(4b)  |  Command(4b)  |  Protocol(4b) | Addr LEN(4b)  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     Command-specific data (variable length)                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     TLV extensions (variable length)                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

Поля заголовка:
  Signature:   12 байт — `\r\n\r\n\0\r\nQUIT\n` (идентификация протокола)
  Version:     4 бита  — текущая версия = 0x2
  Command:     4 бита  — 0x0 = PROXY (проксирование), 0x1 = LOCAL (собственное соединение)
  Protocol:    4 бита  — 0x0 = AF_UNSPEC, 0x1 = AF_INET, 0x2 = AF_INET6, 0x3 = AF_UNIX
  Addr LEN:    4 бита  — длина адресных полей (3*4=12 для IPv4, 3*16=48 для IPv6, без TLV)

TLV-расширения (опционально):
  Каждый TLV: 3 байта заголовок + данные
  ┌──────────┬──────────┬──────────────────┐
  │ Type(1b) │ Length(2b)│ Value (N bytes) │
  └──────────┴──────────┴──────────────────┘
  Known Types:
    0x01 - ALPN (согласованный протокол)
    0x02 - Authority (SNI hostname)
    0x03 - CRC32c (checksum)
    0x04 - NoOp
    0x20 - SSL (begin)
    0x21 - SSL version
    0x22 - SSL CN
    0x23 - SSL cipher
    0x24 - SSL sig-alg
    0x25 - SSL key-alg
    0x26 - SSL verify result
    0x27 - SSL verify peer fingerprint
    0x28 - SSL verify subject
    0xEA - Unique ID (AWS/GCP)
```

### Сценарии использования

| Сценарий | Описание |
| :--- | :--- |
| **Cloud Load Balancing** | Получение реального IP за NLB (Network Load Balancer) в AWS, GCP или Yandex Cloud. |
| **Kubernetes Ingress** | Передача IP от внешнего балансировщика к контроллеру (Nginx, Traefik). Альтернатива `externalTrafficPolicy: Local`. |
| **Базы данных и очереди** | Логирование реальных IP для PostgreSQL, MySQL, Redis, работающих за L4-балансировщиком. |
| **SSL Passthrough** | Сохранение IP клиента при пробросе зашифрованного TCP-потока (без терминации TLS на прокси). |

## Практическая реализация

### Настройка в Nginx / Angie (Получатель)

```nginx
# Модуль stream (L4)
stream {
    server {
        listen 12345 proxy_protocol;
        proxy_pass backend_service;
        
        # Разрешаем Proxy Protocol только от доверенного балансировщика
        set_real_ip_from 10.0.0.0/8;
    }
}

# Модуль http (L7)
http {
    server {
        listen 80 proxy_protocol;
        
        set_real_ip_from 10.0.0.0/8;
        real_ip_header proxy_protocol;
        
        location / {
            # Теперь $remote_addr содержит IP реального клиента
            add_header X-Client-IP $remote_addr;
        }
    }
}
```

### Настройка в HAProxy (Отправитель)

#### Базовая конфигурация

```haproxy
backend app_nodes
    mode tcp
    # send-proxy    -> v1 (текстовый)
    # send-proxy-v2 -> v2 (бинарный, рекомендуется)
    server node1 192.168.1.10:80 check send-proxy-v2
```

#### Полный пример haproxy.cfg (Frontend + Backend)

```haproxy
global
    log /dev/log local0
    maxconn 10000

defaults
    log     global
    mode    tcp
    option  tcplog
    timeout connect 5s
    timeout client  30s
    timeout server  30s

# Frontend: принимает входящий трафик
frontend ft_web
    bind *:80
    bind *:443
    default_backend bk_web

# Backend: проксирует на серверы с Proxy Protocol v2
backend bk_web
    balance roundrobin
    option httpchk GET /health
    http-check expect status 200

    # send-proxy-v2 — отправляем Proxy Protocol v2
    # check — включена проверка здоровья
    # inter 5s — интервал проверки
    # fall 3 — после 3 неудачных проверок сервер помечается как DOWN
    # rise 2 — после 2 успешных проверок сервер снова UP
    server web1 192.168.1.10:8080 check inter 5s fall 3 rise 2 send-proxy-v2
    server web2 192.168.1.11:8080 check inter 5s fall 3 rise 2 send-proxy-v2
```

#### Варианты send-proxy

| Опция | Описание | Когда использовать |
| :--- | :--- | :--- |
| `send-proxy` | Proxy Protocol v1 (текстовый) | Legacy-системы, не поддерживающие v2 |
| `send-proxy-v2` | Proxy Protocol v2 (бинарный) | Рекомендуется для всех новых deployments |
| `send-proxy-v2-ssl` | v2 + TLV с SSL-информацией | Нужна детальная информация о TLS |
| `send-proxy-v2-health-checks` | v2 только для health-check | Оптимизация: health-checkы без PP, трафик с PP |
| `accept-proxy` | Приём Proxy Protocol (на стороне сервера) | HAProxy как получатель от LB |

#### Сравнение HAProxy как отправителя и получателя

**Отправитель (frontend -> backend с PP):**
```haproxy
# Frontend (принимает трафик без PP)
frontend ft_plain
    bind *:80
    default_backend bk_with_pp

# Backend (отправляет PP v2 на серверы)
backend bk_with_pp
    server srv1 10.0.0.10:8080 send-proxy-v2
```

**Получатель (принимает PP от внешнего LB):**
```haproxy
# Frontend (принимает PP от внешнего балансировщика)
frontend ft_from_lb
    bind *:80 accept-proxy
    default_backend bk_app

# Примечание: accept-proxy заставляет HAProxy ожидать
# Proxy Protocol v1/v2 заголовок в начале соединения
```

### Настройка в Traefik (Kubernetes Ingress)

```yaml
# Доверенные IP для EntryPoint
entryPoints:
  websecure:
    address: ":443"
    proxyProtocol:
      trustedIPs:
        - "10.0.0.0/8"
        - "192.168.0.0/16"
```

### Настройка в Envoy Proxy

Envoy широко используется в service mesh (Istio, Consul Connect) и как L4/L7 прокси. Envoy поддерживает как отправку, так и приём Proxy Protocol.

#### Отправитель (Envoy -> Backend)

```yaml
# envoy.yaml — кластер с Proxy Protocol v2
static_resources:
  listeners:
  - name: listener_proxy_protocol
    address:
      socket_address:
        address: 0.0.0.0
        port_value: 8080
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: ingress_http
          route_config:
            name: local_route
            virtual_hosts:
            - name: backend
              domains: ["*"]
              routes:
              - match: { prefix: "/" }
                route:
                  cluster: upstream_cluster
          http_filters:
          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
      transport_socket:
        name: envoy.transport_sockets.upstream_proxy_protocol
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.transport_sockets.proxy_protocol.v3.ProxyProtocolUpstreamTransport
          version: V2

  clusters:
  - name: upstream_cluster
    type: STATIC
    load_assignment:
      cluster_name: upstream_cluster
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: 10.0.0.10
                port_value: 9000
```

#### Получатель (Envoy принимает Proxy Protocol)

```yaml
# envoy.yaml — Listener с Proxy Protocol
static_resources:
  listeners:
  - name: listener_with_pp
    address:
      socket_address:
        address: 0.0.0.0
        port_value: 8080
    listener_filters:
    - name: envoy.filters.listener.proxy_protocol
      typed_config:
        "@type": type.googleapis.com/envoy.extensions.filters.listener.proxy_protocol.v3.ProxyProtocol
        rules:
        - name: src
          on_cluster: source_cluster
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: ingress
          route_config:
            name: local_route
            virtual_hosts:
            - name: all
              domains: ["*"]
              routes:
              - match: { prefix: "/" }
                route:
                  cluster: local_service
          http_filters:
          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
```

### Kubernetes: MetalLB и AWS NLB

#### MetalLB (bare-metal)

MetalLB поддерживает Proxy Protocol через `externalTrafficPolicy: Local` или аннотации:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
  annotations:
    metallb.universe.tf/allow-shared-ip: "shared"
    metallb.universe.tf/loadBalancerIPs: "203.0.113.10"
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local
  ports:
  - port: 443
    targetPort: 8443
  selector:
    app: my-app
```

> **Примечание:** MetalLB в режиме L2 передаёт Source IP напрямую. Proxy Protocol не требуется. В режиме BGP — рекомендуется Proxy Protocol для сохранения Source IP.

#### AWS NLB + EKS

```yaml
# Service с Proxy Protocol v2 через аннотацию AWS
apiVersion: v1
kind: Service
metadata:
  name: nginx-ingress
  annotations:
    # Включает Proxy Protocol v2 на NLB
    service.beta.kubernetes.io/aws-load-balancer-proxy-protocol: "*"
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local
  ports:
  - port: 443
    targetPort: 8443
  selector:
    app: ingress-nginx
---
# Конфигурация Ingress Controller (Nginx)
# В Ingress-NGINX ConfigMap:
apiVersion: v1
kind: ConfigMap
metadata:
  name: ingress-nginx-controller
data:
  use-proxy-protocol: "true"
  real-ip-header: "proxy_protocol"
  forwarded-for-header: "X-Forwarded-For"
  proxy-real-ip-cidr: "10.0.0.0/8"  # CIDR доверенных прокси (VPC CIDR)
```

#### AWS ALB + EKS (L7)

```yaml
# ALB Ingress Controller аннотации
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    # X-Forwarded-For автоматически обрабатывается ALB
    alb.ingress.kubernetes.io/load-balancer-attributes: >
      routing.http2.enabled=true
spec:
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-service
            port:
              number: 80
```

> **Различие:** ALB (L7) передаёт X-Forwarded-For автоматически. NLB (L4) требует Proxy Protocol для сохранения Source IP.

### Практические сценарии: Базы данных за L4-балансировщиком

#### PostgreSQL за HAProxy с Proxy Protocol

**HAProxy:**
```haproxy
# postgresql.cfg
listen pgsql_cluster
    bind *:5432
    mode tcp
    option tcp-check

    # TCP health check для PostgreSQL
    tcp-check connect
    tcp-check send-binary 530000001000000000000000000000000000000000000000000000000000
    tcp-check expect binary 520000000a353030303030303000

    server pg1 10.0.0.10:5432 check inter 3s fall 3 rise 2 send-proxy-v2
    server pg2 10.0.0.11:5432 check inter 3s fall 3 rise 2 send-proxy-v2 backup
```

**PostgreSQL (получатель):**
```ini
# postgresql.conf
# Включаем логирование реального IP клиента
log_line_prefix = '%t [%p]: user=%u,db=%d,app=%a,client=%h '
```

> **Примечание:** PostgreSQL нативно не поддерживает Proxy Protocol. Используйте `pg_hba.conf` для управления доступом по IP. Если нужен реальный IP клиента в логах PostgreSQL — используйте `pg_hba.conf` с IP прокси ( доверенная подсеть HAProxy) и Proxy Protocol на уровне приложения (например, через PgBouncer).

#### PgBouncer с Proxy Protocol

PgBouncer (connection pooler) может работать как получатель Proxy Protocol:

```ini
# pgbouncer.ini
[databases]
mydb = host=10.0.0.10 port=5432 dbname=mydb

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
# Принимаем Proxy Protocol от HAProxy
proxy_protocol = 1
# Доверенные прокси (CIDR)
proxy_allowed = 10.0.0.0/8
```

#### Redis за HAProxy

```haproxy
# redis_cluster.cfg
listen redis_cluster
    bind *:6379
    mode tcp
    option tcp-check

    # Redis PING health check
    tcp-check connect
    tcp-check send PING\r\n
    tcp-check expect string +PONG

    server redis1 10.0.0.20:6379 check inter 2s send-proxy-v2
    server redis2 10.0.0.21:6379 check inter 2s send-proxy-v2
```

> **Примечание:** Redis не поддерживает Proxy Protocol. Используйте `protected-mode no` и ограничивайте доступ через `bind` / firewall. Реальный IP клиента будет виден только на уровне HAProxy (логи, ACL).

### Сценарий: AWS Network Load Balancer (NLB)

В AWS NLB Proxy Protocol v2 включается одной опцией:

```hcl
# Terraform
resource "aws_lb" "app" {
  name               = "app-nlb"
  internal           = false
  load_balancer_type = "network"
  
  enable_proxy_protocol_v2 = true
  
  subnet_mapping {
    subnet_id = aws_subnet.public.id
  }
}

resource "aws_lb_listener" "app" {
  load_balancer_arn = aws_lb.app.arn
  port              = "443"
  protocol          = "TCP"
  
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
```

**На стороне получения (nginx):**
```nginx
stream {
    upstream backend {
        server 10.0.1.10:443;
    }
    
    server {
        listen 443 proxy_protocol;
        proxy_pass backend;
        
        # AWS NLB CIDR (области)
        set_real_ip_from 10.0.0.0/8;
        set_real_ip_from 100.64.0.0/10;  # Carrier-grade NAT
    }
}
```

### Сценарий: PostgreSQL за L4-балансировщиком

**Проблема:** PostgreSQL логирует IP подключения. Без Proxy Protocol логи показывают IP балансировщика, а не реального клиента.

**Решение (HAProxy → PgBouncer/PostgreSQL):**
```haproxy
# HAProxy конфигурация
listen postgresql
    mode tcp
    bind *:5432
    option tcplog
    option pgsql-check user haproxy
    
    # PostgreSQL не поддерживает Proxy Protocol
    # Используем TCP-проксирование с сохранением source IP через TCP options
    timeout client 3600s
    timeout server 3600s
    
    server pg1 10.0.1.10:5432 check
    server pg2 10.0.1.11:5432 check backup
```

**На стороне PostgreSQL (логирование):**
```sql
-- Включение логирования подключений
ALTER SYSTEM SET log_connections = on;
ALTER SYSTEM SET log_disconnections = on;
ALTER SYSTEM SET log_line_prefix = '%m [%p] %u@%d ';

-- Перезапуск для применения
SELECT pg_reload_conf();
```

### Сценарий: MySQL/MariaDB за HAProxy

```haproxy
# HAProxy для MySQL с Proxy Protocol
listen mysql
    mode tcp
    bind *:3306
    
    # Для MySQL Proxy Protocol не поддерживается
    # Используем option source for source IP preservation
    option source
    source 0.0.0.0 usesrc clientip
    
    timeout client 28800s
    timeout server 28800s
    
    server mysql1 10.0.1.20:3306 check
    server mysql2 10.0.1.21:3306 check backup
```

### Сценарий: Redis Sentinel за балансировщиком

```haproxy
# HAProxy для Redis с Proxy Protocol v2
frontend redis_front
    mode tcp
    bind *:6379
    default_backend redis_back
    
    # Опционально: передача Proxy Protocol
    # option tcplog

backend redis_back
    mode tcp
    balance roundrobin
    option tcp-check
    
    # Redis не поддерживает Proxy Protocol
    # Используем option source для сохранения IP
    option source
    
    server redis1 10.0.1.30:6379 check
    server redis2 10.0.1.31:6379 check
    server redis-sentinel 10.0.1.32:26379 check
```

## Диагностика и отладка

### Анализ через tcpdump

Для **v1 (ASCII)**:
```bash
sudo tcpdump -i any -A port 80 | grep "PROXY"
```

Для **v2 (Binary)**:
```bash
# Ищем магическую подпись "QUIT"
sudo tcpdump -i any -X port 443 | grep "5155 4954 0a"
```

### Детальный анализ Proxy Protocol v2

```bash
# Анализ бинарного формата v2
sudo tcpdump -i any -X port 443 -c 10 | head -100

# Поиск магической подписи Proxy Protocol v2
# 0d 0a 0d 0a 00 0d 0a 51 55 49 54 0a
sudo tcpdump -i any -X port 443 | grep -A2 "0d0a 0d0a 000d"

# Анализ только Proxy Protocol заголовков
sudo tcpdump -i any -s 100 -X port 443 | grep -B1 -A5 "PROXY"
```

### Ручная проверка (v1)

```bash
# Симуляция балансировщика
echo -ne "PROXY TCP4 1.2.3.4 5.6.7.8 12345 80\r\nGET / HTTP/1.1\r\nHost: test.local\r\n\r\n" | nc 127.0.0.1 80

# Проверка только заголовка (без HTTP)
echo -ne "PROXY TCP4 10.0.0.1 192.168.1.1 12345 443\r\n" | nc 127.0.0.1 443

# Проверка через openssl (для TLS)
echo -ne "PROXY TCP4 1.2.3.4 5.6.7.8 12345 443\r\n" | openssl s_client -connect 127.0.0.1:443 -quiet
```

### Ручная проверка (v2)

```bash
# Генерация Proxy Protocol v2 заголовка (bash)
# SIG (12 bytes) + VERSION+CMD (1 byte) + FAMILY+PROTOCOL (1 byte) + LENGTH (2 bytes) + ADDR (12 bytes)
printf '\x0d\x0a\x0d\x0a\x00\x0d\x0a\x51\x55\x49\x54\x0a\x21\x11\x00\x0c\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c' | nc 127.0.0.1 443
```

### Диагностический скрипт

```bash
#!/bin/bash
# Proxy Protocol Diagnostics Script
TARGET="${1:-127.0.0.1}"
PORT="${2:-80}"

echo "=== Proxy Protocol Diagnostics for $TARGET:$PORT ==="

# 1. Проверка доступности порта
echo ""
echo "--- Port Connectivity ---"
nc -z -w 2 $TARGET $PORT && echo "  Port $PORT is open" || echo "  Port $PORT is closed"

# 2. Проверка Proxy Protocol v1
echo ""
echo "--- Proxy Protocol v1 Test ---"
RESPONSE=$(echo -ne "PROXY TCP4 1.2.3.4 5.6.7.8 12345 $PORT\r\n" | nc -w 3 $TARGET $PORT 2>/dev/null)
if echo "$RESPONSE" | grep -q "PROXY"; then
    echo "  Server responded to Proxy Protocol v1"
else
    echo "  Server did not respond to Proxy Protocol v1"
fi

# 3. Проверка HTTP-ответа
echo ""
echo "--- HTTP Response ---"
RESPONSE=$(echo -ne "GET / HTTP/1.1\r\nHost: test.local\r\n\r\n" | nc -w 3 $TARGET $PORT 2>/dev/null)
echo "$RESPONSE" | head -3

# 4. Проверка логов (если доступны)
echo ""
echo "--- Recent Logs (nginx) ---"
if [ -f /var/log/nginx/access.log ]; then
    tail -5 /var/log/nginx/access.log | grep -i "proxy"
else
    echo "  nginx log not found"
fi

echo ""
echo "=== Diagnostics Complete ==="
```

### Проверка в Kubernetes (Ingress Controller)

```bash
# Проверка Proxy Protocol в Ingress Controller
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx | grep -i "proxy"

# Проверка конфигурации Ingress
kubectl get ingress -o yaml | grep -A5 "proxy-protocol"

# Просмотр реальных IP в логах
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx | awk '{print $1}' | sort | uniq -c | sort -rn
```

## Безопасность

### Уязвимость: IP Spoofing
Если сервер принимает Proxy Protocol от любого источника, атакующий может отправить заголовок с произвольным IP (например, `127.0.0.1`), обходя ACL и механизмы защиты.

**Защитные меры:**
1. **Строгий список доверия:** Использовать директивы `trustedIPs` / `set_real_ip_from` для ограничения источников.
2. **Сетевая изоляция:** Балансировщик и бэкенд должны находиться в изолированной подсети, недоступной напрямую извне.
3. **Согласованность версий:** Ошибка в выборе версии (v1 vs v2) приведет к тому, что заголовок будет воспринят как данные приложения, что может вызвать ошибки парсинга или XSS в логах.

### Инъекция и подмена Proxy Protocol

| Атака | Описание | Защита |
| :--- | :--- | :--- |
| **IP Spoofing** | Подстановка произвольного IP в заголовке | `set_real_ip_from`, сетевая изоляция |
| **Protocol Injection** | Отправка поддельного Proxy Protocol v1/v2 заголовка | Принимать PP только от доверенных IP |
| **Version Mismatch** | Клиент отправляет v1, сервер ожидает v2 (или наоборот) | Согласовать версию на обоих концах |
| **TLV Injection** | Поддельные TLV-расширения для обхода фильтров | Валидировать TLV на стороне получателя |

### Цепочка прокси

В средах с несколькими уровнями прокси (CDN -> LB -> Ingress -> Backend) Proxy Protocol может передавать только **один** исходный IP. Для цепочки прокси:

1. **Внешний LB** отправляет Proxy Protocol с реальным IP клиента.
2. **Внутренний прокси** использует `X-Forwarded-For` для добавления промежуточных IP.
3. **Backend** получает: `X-Forwarded-For: <клиент>, <LB IP>, <прокси IP>`.

> **Важно:** Proxy Protocol и X-Forwarded-For **не конфликтуют** — они работают на разных уровнях. PP работает на L4 (TCP), XFF — на L7 (HTTP).

## Диагностика и troubleshooting

### Частые проблемы

| Проблема | Симптомы | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Version Mismatch** | Сервер парсит PP как данные приложения | Клиент отправляет v1, сервер ожидает v2 | Согласовать версию: `send-proxy-v2` на клиенте, `real_ip_header proxy protocol v2` на сервере |
| **Соединение разрывается сразу** | TCP-соединение устанавливается и сразу закрывается | Сервер не ожидает PP, но получает заголовок | Убрать `proxy_protocol` со стороны сервера или `send-proxy` со стороны клиента |
| **Адрес клиента = 0.0.0.0** | `$remote_addr` = 0.0.0.0 | PP v2 с протоколом AF_UNSPEC (0x0) | Использовать AF_INET/AF_INET6, проверить конфигурацию отправителя |
| **Неверный порт клиента** | Порт = 0 или неверный | PP v1 с протоколом TCP4, но IPv6 соединение | Убедиться, что протокол в PP соответствует реальному соединению |
| **PP не распознаётся** | Логи показывают PP как plaintext | Сервер не поддерживает PP | Включить поддержку PP на сервере или отключить PP на отправителе |
| **Странные символы в логах** | `PROXY TCP4` в access.log | PP v1 не распознан сервером | Проверить версию PP, настроить `real_ip_header proxy_protocol` |

### Команды диагностики

#### Проверка наличия Proxy Protocol на порту

```bash
# Проверка слушает ли порт с PP (Linux)
ss -tlnp | grep :80
# → LISTEN  0  511  0.0.0.0:80  0.0.0.0:*  users:(("nginx",pid=1234,fd=6))

# Проверка через netcat (отправляем PP v1 заголовок)
echo -ne "PROXY TCP4 1.2.3.4 5.6.7.8 12345 80\r\n" | nc -v 10.0.0.10 80

# Проверка через netcat (отправляем PP v2 заголовок)
printf '\x0d\x0a\x0d\x0a\x00\x0d\x0a\x51\x55\x49\x54\x0a\x02\x11\x00\x0c\xac\x10\x00\x01\x0a\x00\x00\x50\x00' | nc -v 10.0.0.10 80
```

#### Анализ через tcpdump

```bash
# Захват PP v1 (текстовый протокол — виден в plaintext)
sudo tcpdump -i eth0 -A port 80 | grep -E "^PROXY"

# Захват PP v2 (бинарный — ищем сигнатуру)
sudo tcpdump -i eth0 -X port 443 | grep -A2 "5155 4954 0a"

# Захрат и парсинг с сохранением в файл
sudo tcpdump -i eth0 -w pp_capture.pcap port 80 &
# После анализа в Wireshark: фильтр "tcp.port == 80 && tcp[0:12] == 0d:0a:0d:0a:00:0d:0a:51:55:49:54:0a"
```

#### Логирование реального IP

**Nginx:**
```nginx
# Формат лога с реальным IP
log_format proxy '$remote_addr - $remote_user [$time_local] '
                 '"$request" $status $body_bytes_sent '
                 '"$http_referer" "$http_user_agent" '
                 'upstream=$upstream_addr '
                 'request_time=$request_time';

# Использование в server/http
access_log /var/log/nginx/proxy_access.log proxy;
```

**HAProxy:**
```haproxy
global
    log /dev/log local0

defaults
    log global
    option tcplog
    option logasap
    log-format "%ci:%cp [%t] %ft %b/%s %Tq %Tw %Tc %Tr %Ta %ST %B %CC %cl"

# %ci = client IP (реальный IP клиента через PP)
# %cp = client port
```

### Проверка корректности работы

```bash
# На стороне получателя (Nginx)
# 1. Проверяем логи — виден ли реальный IP
tail -f /var/log/nginx/proxy_access.log | head -5
# → 203.0.113.50 - - [25/Aug/2026:10:30:00 +0000] "GET / HTTP/1.1" 200 ...

# 2. Проверяем переменную $remote_addr
curl -H "Host: test.example.com" http://10.0.0.10/
# → В логах: remote_addr = реальный IP клиента (не IP прокси)

# На стороне отправителя (HAProxy)
# 3. Проверяем статус бэкенд-серверов
echo "show stat" | socat stdio /var/run/haproxy/admin.sock
# → web1 bk_web 0 0 0 0 ... UP ...

# 4. Проверяем, что send-proxy-v2 активен
echo "show servers state" | socat stdio /var/run/haproxy/admin.sock
```

### Типичные ошибки конфигурации

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `bad proxy protocol` в логах | Сервер не ожидает Proxy Protocol | Добавить `proxy_protocol` в `listen` директиву |
| Все клиенты видят IP балансировщика | Proxy Protocol не включен на отправителе | Включить `send-proxy-v2` в HAProxy |
| Ошибка парсинга (v1 vs v2) | Несоответствие версий | Убедиться, что отправитель и получатель используют одну версию |
| Высокий latency | Proxy Protocol v1 (текстовый) | Перейти на v2 (бинарный) |
| TCP RST после Proxy Protocol заголовка | Сервер не поддерживает Proxy Protocol | Отключить Proxy Protocol или добавить поддержку на сервере |

### Валидация Proxy Protocol v2

```bash
# Проверка магической подписи
echo -ne "PROXY TCP4 1.2.3.4 5.6.7.8 12345 80\r\n" | xxd | head -1
# → 00000000: 5052 4f58 5920 5443 5034 2031 2e32 ...PROXY TCP4 1.2

# Проверка бинарной версии
printf '\x0d\x0a\x0d\x0a\x00\x0d\x0a\x51\x55\x49\x54\x0a' | xxd | head -1
# → 00000000: 0d0a 0d0a 000d 0a51 5549 540a .......QUIT.
```

## Дополнительная информация

### Рекомендации по внедрению (Best Practices)

1. **Версия протокола:** Всегда используйте **v2 (бинарный)**. v1 (текстовый) — legacy, уязвим к инъекциям (limitations в парсинге), ограничен 108 байтами.

2. **Принцип наименьших привилегий:** Бэкенд-серверы должны принимать Proxy Protocol **только от доверенных IP**. Настройте `set_real_ip_from` / `trustedIPs` строго на CIDR балансировщика.

3. **Согласованность версий:** Убедитесь, что отправитель и получатель используют одну версию. Несоответствие приводит к тому, что PP-заголовок воспринимается как данные приложения.

4. **Цепочка прокси:** В многослойной архитектуре (CDN -> LB -> Ingress -> App) Proxy Protocol работает только на **одном** уровне. Используйте:
   - Proxy Protocol (L4) на внешнем LB
   - `X-Forwarded-For` (L7) между прокси внутри сети

5. **Health-checks:** Используйте `send-proxy-v2-health-checks` для оптимизации — health-checkы не передают PP-заголовок, уменьшая оверхед.

6. **Мониторинг:** Логируйте не только `$remote_addr`, но и `$http_x_forwarded_for` для полной картины.

7. **Безопасность:**
   - Балансировщик и бэкенд — в изолированной подсети, недоступной извне.
   - Используйте firewall для ограничения доступа к портам бэкендов.
   - Регулярно проверяйте логи на аномалии (подозрительные IP, нестандартные порты).

8. **Тестирование:** Перед запуском в production протестируйте конфигурацию:
   - Отправьте PP v1/v2 заголовок через `nc` или `socat`.
   - Убедитесь, что `$remote_addr` содержит реальный IP.
   - Проверьте поведение при отсутствии PP-заголовка.

### Связанные темы

- **[Прокси-серверы — концепции](../Concepts/proxy.md)** — общая архитектура проксирования, типы прокси, заголовки.
- **[HTTP-серверы и прокси](./HTTP/http_servers_proxies.md)** — настройка Nginx/Apache как reverse proxy, `X-Forwarded-For`, `real_ip_header`.
- **[L4-балансировка и проксирование](../../WebServers/Angie/l4_balancing_and_proxying.md)** — pratique сценарии балансировки PostgreSQL, Redis с Proxy Protocol.
- **[Nginx L4 Proxying](../../WebServers/Nginx/Proxy/nginx_l4_proxying.md)** — детали работы модуля `stream`, Proxy Protocol в L4.
- **[Transport Layer Security (TLS)](./tls.md)** — терминация TLS и её связь с Proxy Protocol.
