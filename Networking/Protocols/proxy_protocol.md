# Proxy Protocol

## Definitions

**Proxy Protocol** — протокол, передающий информацию о первоначальном соединении (IP-адреса клиента и сервера, порты) в начале TCP-соединения через L4-прокси.

**Проблема:** при использовании L4-балансировщиков (HAProxy, Nginx stream, AWS ELB) бэкенд видит только IP прокси, а не реального клиента. Это ломает логирование, rate limiting, геолокацию, ACL и firewall rules.

**Решение:** Proxy Protocol добавляет заголовок **перед** данными приложения, сохраняя метаданные соединения.

## Basic Concepts

### Версии протокола

#### Proxy Protocol v1 (текстовый)

Человекочитаемый заголовок в начале соединения:

```
PROXY TCP4 192.168.0.1 192.168.0.11 56324 443\r\n
```

**Формат:** `PROXY <protocol> <client-IP> <server-IP> <client-port> <server-port>\r\n`

**Типы протоколов:** `TCP4` (TCP/IPv4), `TCP6` (TCP/IPv6), `UNKNOWN` (нет информации, для совместимости).

**Преимущества:** простая отладка (видно в tcpdump), лёгкая реализация.

**Недостатки:** размер до 108 байт, нет расширения для дополнительных данных.

#### Proxy Protocol v2 (бинарный)

Компактный бинарный формат с поддержкой TLV-расширений:

```
\x0D\x0A\x0D\x0A\x00\x0D\x0A\x51\x55\x49\x54\x0A  (signature, 12 байт)
\x21\x11\x00\x0C  (version+command, family+protocol, length)
<client-IP> <server-IP> <client-port> <server-port>  (address data)
[TLV blocks...]  (опционально)
```

**Преимущества:** компактный (минимум 16 байт), поддержка **TLV** (Type-Length-Value): SSL/TLS-информация (cipher, version, клиентский сертификат), авторизация (username), NetNS ID, custom metadata.

**Формат заголовка v2:**

| Поле | Размер | Описание |
|------|--------|----------|
| Signature | 12 байт | `\x0D\x0A\x0D\x0A\x00\x0D\x0A\x51\x55\x49\x54\x0A` |
| Version+Command | 1 байт | Версия (0x2) + команда (LOCAL/PROXY) |
| Family+Protocol | 1 байт | AF_INET/AF_INET6 + STREAM/DGRAM |
| Length | 2 байта | Длина данных |
| Data | var | Адреса, порты + опционально TLV |

### Сценарии использования

| Сценарий | Описание |
|----------|----------|
| L4-балансировка | HAProxy/Nginx `stream` передают TCP-трафик с IP клиента |
| Сохранение IP клиента | Бэкенд видит реальный IP для логирования и ACL |
| Цепочки прокси | Метаданные передаются через несколько уровней |
| Kubernetes Ingress | Ingress-контроллеры передают IP клиента подам |
| Yandex Cloud Load Balancer | Поддержка v2 для сохранения IP клиента |

## Practical Scenarios

### HAProxy → Nginx

**HAProxy (отправитель):**

```haproxy
frontend https
    bind *:443
    mode tcp
    server backend1 192.168.1.10:8443 send-proxy-v2
```

**Nginx (получатель):**

```nginx
stream {
    server {
        listen 8443 proxy_protocol;
        proxy_pass http://backend;
    }
}

http {
    server {
        listen 443 ssl proxy_protocol;

        set_real_ip_from 192.168.1.0/24;
        real_ip_header proxy_protocol;

        location / {
            # $remote_addr содержит реальный IP клиента
            access_log /var/log/nginx/access.log;
        }
    }
}
```

### HAProxy → PostgreSQL

PostgreSQL поддерживает Proxy Protocol через расширение `pg_proxy_protocol` или нативно в новых версиях.

```haproxy
frontend postgres
    bind *:5432
    mode tcp
    server db1 192.168.1.20:5432 send-proxy-v2
```

PostgreSQL видит реальный IP клиента в `pg_stat_activity`. Настройка `pg_hba.conf` и `postgresql.conf` стандартная.

### Диагностика

**Проверка v1:**

```bash
telnet backend.example.com 80
# PROXY TCP4 192.168.1.100 10.0.0.1 54321 80

tcpdump -i eth0 -A port 80 | head -20
```

**Проверка v2:**

```bash
tcpdump -i eth0 -X port 80 | head -30
# Signature: 0D 0A 0D 0A 00 0D 0A 51 55 49 54 0A
```

**Типичные проблемы:**

| Проблема | Симптомы | Решение |
|----------|----------|---------|
| Бэкенд не ожидает Proxy Protocol | Ошибки соединения, таймауты | Включить поддержку на бэкенде |
| Несоответствие версий | v2 на v1-получателе | Настроить совместимую версию |
| Отсутствует заголовок | Бэкенд ждёт, но не получает | Проверить `send-proxy` на балансировщике |

### Безопасность

**Риски:** IP spoofing (поддельные заголовки), DoS (некорректные заголовки).

**Защита:** доверенная сеть (только между доверенными узлами), firewall rules (разрешить соединения только от балансировщиков), валидация (отбрасывать заголовки от недоверенных источников).

```nginx
set_real_ip_from 10.0.0.0/8;
set_real_ip_from 192.168.0.0/16;
```

## Additional Information

### Поддержка в ПО

Отправители: HAProxy (v1, v2), Nginx (v2), Envoy (v2), Yandex Cloud Load Balancer (v2), Kubernetes Ingress. Получатели: Nginx (v1, v2), HAProxy (v1, v2), Apache (mod_remoteip, v1), PostgreSQL/MySQL/Redis (native/plugin).

### Связанные документы

[Proxy Server](../../Concepts/proxy.md) — типы прокси-серверов, [TCP](./TCP/overview.md) — транспортный уровень, [HTTP](./HTTP/http_basics.md) — прикладной уровень, [HAProxy Overview](../../WebServers/haproxy_overview.md) — основной отправитель, [Nginx L4 Proxying](../../WebServers/Nginx/Proxy/nginx_l4_proxying.md) — настройка L4.

### Спецификация

[HAProxy Proxy Protocol (официальная спецификация)](https://www.haproxy.org/download/2.0/doc/proxy-protocol.txt) — де-факто стандарт, не RFC.
