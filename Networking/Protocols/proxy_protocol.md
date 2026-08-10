# Proxy Protocol

> **Reliability Score: 10** (SSoT + Industry Standard + Verified RFCs)

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

```haproxy
backend app_nodes
    mode tcp
    # send-proxy    -> v1 (текстовый)
    # send-proxy-v2 -> v2 (бинарный, рекомендуется)
    server node1 192.168.1.10:80 check send-proxy-v2
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

### Ручная проверка (v1)
```bash
# Симуляция балансировщика
echo -ne "PROXY TCP4 1.2.3.4 5.6.7.8 12345 80\r\nGET / HTTP/1.1\r\nHost: test.local\r\n\r\n" | nc 127.0.0.1 80
```

## Безопасность

### Уязвимость: IP Spoofing
Если сервер принимает Proxy Protocol от любого источника, атакующий может отправить заголовок с произвольным IP (например, `127.0.0.1`), обходя ACL и механизмы защиты.

**Защитные меры:**
1. **Строгий список доверия:** Использовать директивы `trustedIPs` / `set_real_ip_from` для ограничения источников.
2. **Сетевая изоляция:** Балансировщик и бэкенд должны находиться в изолированной подсети, недоступной напрямую извне.
3. **Согласованность версий:** Ошибка в выборе версии (v1 vs v2) приведет к тому, что заголовок будет воспринят как данные приложения, что может вызвать ошибки парсинга или XSS в логах.

## Дополнительная информация

### Спецификации и ссылки
- **[HAProxy Proxy Protocol Spec](https://www.haproxy.org/download/1.8/doc/proxy-protocol.txt):** Первоисточник.
- **[AWS Knowledge Base](https://aws.amazon.com/premiumsupport/knowledge-center/elb-capture-client-ip-address/):** Реализация в Elastic Load Balancing.
- **[Traefik Proxy Protocol Guide](https://doc.traefik.io/traefik/routing/entrypoints/#proxyprotocol):** Официальная документация.
