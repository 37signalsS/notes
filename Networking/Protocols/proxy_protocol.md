# Proxy Protocol

## Определения

**Proxy Protocol** — протокол, передающий информацию о первоначальном соединении (IP-адреса клиента и сервера, порты) в начале TCP-соединения через L4-прокси.

**Проблема:** При использовании L4-балансировщиков (HAProxy, Nginx stream, AWS ELB) бэкенд-сервер видит только IP-адрес прокси, а не реального клиента. Это ломает:

- Логирование реальных IP
- Rate limiting по IP
- Геолокацию
- ACL и firewall rules

**Решение:** Proxy Protocol добавляет заголовок **перед** данными приложения, сохраняя метаданные соединения.

## Базовые концепции

### Версии протокола

#### Proxy Protocol v1 (текстовый)

Человекочитаемый заголовок в начале соединения:

```
PROXY TCP4 192.168.0.1 192.168.0.11 56324 443\r\n
```

**Формат:**

```
PROXY <protocol> <client-IP> <server-IP> <client-port> <server-port>\r\n
```

**Типы протоколов:**

- `TCP4` — TCP over IPv4
- `TCP6` — TCP over IPv6
- `UNKNOWN` — нет информации (используется для совместимости)

**Преимущества:**

- Простая отладка (видно в tcpdump)
- Легкая реализация

**Недостатки:**

- Больше размер (до 108 байт)
- Нет расширения для дополнительных данных

#### Proxy Protocol v2 (бинарный)

Компактный бинарный формат с поддержкой расширений:

```
\x0D\x0A\x0D\x0A\x00\x0D\x0A\x51\x55\x49\x54\x0A  (signature)
\x21\x11\x00\x0C  (version+command, family+protocol, length)
<client-IP> <server-IP> <client-port> <server-port>  (data)
```

**Преимущества:**

- Компактный (минимум 16 байт)
- Поддержка **TLV** (Type-Length-Value) для дополнительных данных:
  - SSL/TLS информация (cipher, version, client certificate)
  - Авторизация (username)
  - NetNS ID
  - Custom metadata

**Формат заголовка v2:**

| Поле | Размер | Описание |
|------|--------|----------|
| **Signature** | 12 байт | `\x0D\x0A\x0D\x0A\x00\x0D\x0A\x51\x55\x49\x54\x0A` |
| **Version+Command** | 1 байт | Версия (0x2) + команда (LOCAL/PROXY) |
| **Family+Protocol** | 1 байт | AF_INET/AF_INET6 + STREAM/DGRAM |
| **Length** | 2 байта | Длина данных |
| **Data** | var | Адреса и порты + опционально TLV |

### Когда используется

| Сценарий | Описание |
|----------|----------|
| **L4 Балансировка** | HAProxy/Nginx в режиме `stream` передают TCP-трафик |
| **Сохранение IP клиента** | Бэкенд видит реальный IP для логирования и ACL |
| **Цепочки прокси** | Информация передаётся через несколько уровней |
| **Kubernetes Ingress** | Ingress-контроллеры передают IP клиента подам |
| **Yandex Cloud Load Balancer** | Поддерживает Proxy Protocol для сохранения IP клиента |

## Практические сценарии

### Настройка HAProxy → Nginx

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
        
        # Реальный IP клиента теперь доступен
        set_real_ip_from 192.168.1.0/24;
        real_ip_header proxy_protocol;
        
        location / {
            # $remote_addr содержит реальный IP клиента
            access_log /var/log/nginx/access.log;
        }
    }
}
```

### Настройка для PostgreSQL

PostgreSQL поддерживает Proxy Protocol через расширение `pg_proxy_protocol` или нативно в новых версиях:

```postgresql
# postgresql.conf
listen_addresses = '*'

# pg_hba.conf
host    all    all    0.0.0.0/0    md5
```

**Пример с HAProxy:**

```haproxy
frontend postgres
    bind *:5432
    mode tcp
    server db1 192.168.1.20:5432 send-proxy-v2
```

PostgreSQL будет видеть реальный IP клиента в `pg_stat_activity`.

### Диагностика и troubleshooting

**Проверка заголовка v1:**

```bash
# Подключиться и увидеть заголовок
telnet backend.example.com 80
PROXY TCP4 192.168.1.100 10.0.0.1 54321 80

# Или через tcpdump
tcpdump -i eth0 -A port 80 | head -20
```

**Проверка заголовка v2:**

```bash
# Бинарный заголовок не виден в текстовом виде
tcpdump -i eth0 -X port 80 | head -30
# Искать signature: 0D 0A 0D 0A 00 0D 0A 51 55 49 54 0A
```

**Типичные проблемы:**

| Проблема | Симптомы | Решение |
|----------|----------|---------|
| **Бэкенд не ожидает Proxy Protocol** | Ошибки соединения, таймауты | Включить поддержку на бэкенде |
| **Несоответствие версий** | v2 отправляется на v1-получатель | Настроить совместимую версию |
| **Отсутствие заголовка** | Бэкенд ждёт, но не получает | Проверить `send-proxy` на балансировщике |

### Безопасность

**Риски:**

- **IP spoofing:** Злоумышленник может отправить поддельный Proxy Protocol заголовок
- **DoS:** Отправка некорректных заголовков для нарушения работы бэкенда

**Защита:**

1. **Доверенная сеть:** Proxy Protocol должен использоваться только между доверенными узлами
2. **Firewall rules:** Разрешить соединения только от балансировщиков
3. **Валидация:** Бэкенд должен отбрасывать заголовки от недоверенных источников

**Пример (Nginx):**

```nginx
# Принимать Proxy Protocol только от доверенных IP
set_real_ip_from 10.0.0.0/8;
set_real_ip_from 192.168.0.0/16;
# Все остальные IP будут отклонены
```

## Дополнительная информация

### Поддержка в ПО

| Отправители | Получатели |
|------------|-----------|
| HAProxy (v1, v2) | Nginx (v1, v2) |
| Nginx (v2) | HAProxy (v1, v2) |
| Envoy (v2) | Apache (mod_remoteip, v1) |
| Yandex Cloud Load Balancer (v2) | PostgreSQL (native/plugin) |
| Kubernetes Ingress | MySQL (plugin) |
| | Redis (plugin) |

### Связанные документы

- [HTTP](./http.md) — прикладной уровень
- [TCP](./TCP/overview.md) — транспортный уровень
- [Load Balancing](../Concepts/proxy.md) — балансировка нагрузки

### Спецификации

- **HAProxy Proxy Protocol:** [Официальная спецификация](https://www.haproxy.org/download/1.8/doc/proxy-protocol.txt)
- **RFC:** Не является RFC, де-факто стандарт
