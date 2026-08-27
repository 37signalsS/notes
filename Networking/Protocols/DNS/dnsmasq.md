# dnsmasq — локальный DNS/DHCP-сервер

## Определения

**dnsmasq** — легковесный DNS/DHCP-сервер, предназначенный для локальных сетей. Обеспечивает: кэширование DNS-записей, разрешение имён из `/etc/hosts`, раздачу IP-адресов через DHCP, PXE-загрузку и conditional forwarding. Идеален для небольших сетей, контейнеров и встраиваемых систем.

**Conditional Forwarding** — механизм пересылки DNS-запросов для определённых доменов на конкретные серверы. Например, запросы к `corp.local` пересылаются на внутренний DNS, а все остальные — на публичный резолвер (8.8.8.8).

**DNS Rebind Protection** — защита от атак DNS Rebinding, при которых злоумышленник перенаправляет DNS-имена на внутренние IP-адреса (например, `192.168.1.1`). dnsmasq блокирует ответы, указывающие на private IP-адреса извне доверенной сети.

**PXE (Preboot Execution Environment)** — протокол загрузки операционной системы по сети. dnsmasq может работать как ProxyDHCP-сервер, раздавая IP-адреса и указывая на TFTP-сервер для загрузки.

---

## Базовые концепции

### Архитектура dnsmasq

```text
┌──────────────────────────┐
│       Клиенты LAN        │
│  (компьютеры, телефоны)  │
└────────────┬─────────────┘
             │ UDP/TCP :53 (DNS) + UDP :67 (DHCP)
┌────────────▼─────────────┐
│        dnsmasq            │
│  ┌──────────┐            │
│  │ DNS кэш  │            │
│  └──────────┘            │
│  ┌──────────┐            │
│  │ DHCP     │            │
│  │ pool     │            │
│  └──────────┘            │
│  ┌──────────┐            │
│  │ /etc/hosts│           │
│  └──────────┘            │
└────────────┬─────────────┘
             │ UDP/TCP :53
┌────────────▼─────────────┐
│   Публичные резолверы    │
│   (8.8.8.8, 9.9.9.9)    │
└──────────────────────────┘
```

### dnsmasq vs Unbound vs BIND

| Критерий | dnsmasq | Unbound | BIND |
| :--- | :--- | :--- | :--- |
| **Назначение** | Локальный DNS + DHCP | Рекурсивный резолвер | Универсал |
| **DHCP** | Да | Нет | Нет |
| **Кэширование** | Да (простое) | Да (продвинутое) | Да (продвинутое) |
| **Рекурсия** | Нет (только forward) | Да | Да |
| **Авторитативные зоны** | Ограниченные (address) | Нет | Да |
| **DNSSEC** | Нет | Да | Да |
| **RRL** | Нет | Да | Да |
| **PXE** | Да (ProxyDHCP) | Нет | Нет |
| **Размер конфига** | Маленький | Маленький | Большой |
| **Производительность** | Низкая | Высокая | Средняя |
| **Использование** | Домашние сети, контейнеры | Крупные сети, ISP | Крупные инфраструктуры |

### Когда использовать dnsmasq

**Используйте dnsmasq когда:**
- Нужен простой DNS + DHCP для локальной сети
- Требуется conditional forwarding (внутренние домены -> корпоративный DNS)
- Нужна PXE-загрузка (вместе с TFTP)
- Хотите кэшировать DNS-запросы для контейнеров
- Работаете на роутере (OpenWrt) или встраиваемой системе

**Не используйте dnsmasq когда:**
- Нужен рекурсивный резолвер — используйте Unbound
- Нужен авторитативный сервер для зон — используйте BIND или PowerDNS
- Требуется DNSSEC — используйте Unbound или BIND
- Нужна высокая производительность (>10K QPS) — используйте Unbound

---

## Практические сценарии

### Предусловия

```bash
# Debian/Ubuntu
sudo apt install dnsmasq

# RHEL/CentOS
sudo yum install dnsmasq

# Проверка версии
dnsmasq -v
# → Dnsmasq version 2.x
```

### 1. Базовая конфигурация

**Конфигурация `/etc/dnsmasq.conf`:**
```bash
# Слушать на всех интерфейсах
listen-address=0.0.0.0
bind-interfaces

# Использовать /etc/hosts для разрешения имён
no-resolv
no-poll

# Публичные резолверы
server=8.8.8.8
server=9.9.9.9
server=1.1.1.1

# Кэширование (1000 записей по умолчанию)
cache-size=1000

# Время жизни кэша (по умолчанию = TTL ответа)
# cache-ttl=3600

# Логирование DNS-запросов (для отладки)
log-queries
log-facility=/var/log/dnsmasq.log

# DHCP (если нужен)
# dhcp-range=192.168.1.100,192.168.1.200,255.255.255.0,12h
# dhcp-option=option:router,192.168.1.1
# dhcp-option=option:dns-server,192.168.1.1
```

**Применение:**
```bash
# Валидация конфигурации
sudo dnsmasq --test
# → dnsmasq: syntax check OK

# Перезапуск
sudo systemctl restart dnsmasq

# Проверка
dig @127.0.0.1 google.com +short
# → 142.250.185.78
```

### 2. Conditional Forwarding (внутренние домены)

```bash
# В /etc/dnsmasq.conf:

# Все запросы идут на публичные резолверы
server=8.8.8.8
server=9.9.9.9

# Внутренние домены пересылаются на корпоративный DNS
server=/corp.local/10.0.0.53
server=/internal.company.com/10.0.0.54
server=/10.in-addr.arpa/10.0.0.53
```

```bash
# Проверка
dig @127.0.0.1 intranet.corp.local +short
# → 192.168.1.100  (от 10.0.0.53)

dig @127.0.0.1 google.com +short
# → 142.250.185.78  (от 8.8.8.8)
```

### 3. Статические DNS-записи (address)

```bash
# В /etc/dnsmasq.conf:
address=/myserver.local/192.168.1.50
address=/printer.local/192.168.1.60
address=/nas.local/192.168.1.70

# Или через /etc/hosts:
# 192.168.1.50  myserver.local
# 192.168.1.60  printer.local
# 192.168.1.70  nas.local
```

```bash
# Проверка
dig @127.0.0.1 myserver.local +short
# → 192.168.1.50

# Проверка через getent (учитывает /etc/hosts)
getent hosts myserver.local
# → 192.168.1.50       myserver.local
```

### 4. DHCP-сервер

```bash
# В /etc/dnsmasq.conf:

# Диапазон IP-адресов
dhcp-range=192.168.1.100,192.168.1.200,255.255.255.0,12h

# Шлюз
dhcp-option=option:router,192.168.1.1

# DNS-сервер (указать dnsmasq)
dhcp-option=option:dns-server,192.168.1.1

# Доменное имя
dhcp-option=option:domain-name,local.lan

# Статические IP для конкретных устройств
dhcp-host=AA:BB:CC:DD:EE:FF,myserver,192.168.1.50,infinite
dhcp-host=11:22:33:44:55:66,printer,192.168.1.60,infinite
```

```bash
# Просмотр DHCP-арендов
cat /var/lib/misc/dnsmasq.leases
# → 1680000000 aa:bb:cc:dd:ee:ff 192.168.1.100 hostname *
```

### 5. PXE-загрузка (ProxyDHCP)

```bash
# В /etc/dnsmasq.conf:

# ProxyDHCP (не раздаёт IP, только указывает TFTP)
dhcp-range=192.168.1.0,proxy

# TFTP-сервер
dhcp-option=66,192.168.1.10    # TFTP server IP
dhcp-option=67,pxelinux.0      # Boot filename
```

### 6. Диагностика проблем

```bash
# Проверка логов
tail -f /var/log/dnsmasq.log
# → Aug 25 12:00:00 dnsmasq[1234]: query[A] google.com from 192.168.1.100
# → Aug 25 12:00:00 dnsmasq[1234]: forwarded google.com to 8.8.8.8
# → Aug 25 12:00:00 dnsmasq[1234]: reply google.com is 142.250.185.78

# Проверка кэша
dnsmasq --print-cache | head -20
# → показывает текущие записи в кэше

# Проверка слушающих портов
sudo ss -ulnp | grep dnsmasq
# → UDP  *:53    *:*    users:(("dnsmasq",pid=1234,fd=5))

# Проверка конфликтов портов
sudo ss -ulnp | grep :53
# → Если есть другой процесс на порту 53 — конфликт
```

### 7. Интеграция с Docker

```bash
# Запуск dnsmasq в контейнере
docker run -d \
  --name dnsmasq \
  --net=host \
  -v /etc/dnsmasq.conf:/etc/dnsmasq.conf \
  -v /etc/hosts:/etc/hosts \
  jpillora/dnsmasq

# Или через docker-compose
```

```yaml
# docker-compose.yml
version: '3'
services:
  dnsmasq:
    image: jpillora/dnsmasq
    ports:
      - "53:53/udp"
      - "53:53/tcp"
    volumes:
      - ./dnsmasq.conf:/etc/dnsmasq.conf
      - /etc/hosts:/etc/hosts
    restart: unless-stopped
```

### 8. Оптимизация кэша

```bash
# Размер кэша (по умолчанию 1000 записей)
cache-size=2000

# Время жизни кэша (по умолчанию = TTL ответа)
# cache-ttl=3600  # Все записи живут 1 час

# Отключение негативного кэшира (для отладки)
# negative-ttl=0

# Отключение кэширования (для отладки)
# no-cache
```

---

## Лучшие практики

*   **Используйте `bind-interfaces`:** Это предотвращает утечку DNS-запросов на другие интерфейсы. Без этого dnsmasq может отвечать на запросы из нежелательных сетей.
*   **Настройте `cache-size`:** 1000 — минимум для домашней сети, 2000-5000 — для офиса. Кэш хранится в RAM; каждая запись занимает ~100-200 байт.
*   **Используйте conditional forwarding вместо所有的 DNS на 8.8.8.8:** Это ускоряет разрешение внутренних имён и снижает зависимость от внешних резолверов.
*   **Включайте `log-queries` только для отладки:** Логирование каждого запроса нагружает диск. В продакшене отключайте.
*   **Не используйте dnsmasq для крупных сетей (>100 хостов):** Он однопоточный и не масштабируется. Для крупных сетей — Unbound или BIND.
*   **Проверяйте конфликты с systemd-resolved:** На Ubuntu 22.04+ dnsmasq может конфликтовать с systemd-resolved на порту 53. Решение: `sudo systemctl stop systemd-resolved` или использовать dnsmasq как backend для systemd-resolved.
*   **Бэкапьте конфигурацию:** `/etc/dnsmasq.conf` — единственный файл конфигурации. Сделайте бэкап перед изменениями.
*   **Используйте `/etc/dnsmasq.d/`:** Выносите дополнительные настройки в отдельные файлы в `/etc/dnsmasq.d/` для удобства управления.

---

## Дополнительная информация

### Инструментарий

- **dnsmasq:** Основной бинарник.
- **dnsmasq --test:** Валидация конфигурации.
- **dnsmasq --print-cache:** Просмотр кэша.
- **dnsmasq --no-daemon:** Запуск в foreground (для отладки).

### Ключевые RFC

- **RFC 2131:** Dynamic Host Configuration Protocol (DHCP).
- **RFC 1035:** Domain Names - Implementation and Specification.
- **RFC 3445:** Limitations of DNSSEC (для понимания ограничений dnsmasq).

### Связанные разделы

- [Протокол DNS](./dns.md) — общая архитектура и порты.
- [Unbound — рекурсивный резолвер](./unbound_resolver.md) — альтернатива для крупных сетей.
- [Docker: DNS и Service Discovery](../../../Docker/Docker_network/dns_and_service_discovery.md) — DNS в контейнерах.
- [Docker: Проблемы DNS](../../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md) — конфликты dnsmasq с Docker.
- [PXE-загрузка](../../../Linux/Networking/Concepts/pxe_boot.md) — dnsmasq как ProxyDHCP.
