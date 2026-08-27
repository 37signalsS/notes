# Unbound — рекурсивный DNS-резолвер

## Определения

**Unbound** — высокопроизводительный рекурсивный DNS-резолвер, разработанный NLnet Labs. Отличается от авторитативных серверов (BIND master/slave) тем, что выполняет полную рекурсию от корневых серверов до целевого домена. Не хранит зоны — только кэширует результаты.

**Рекурсивный резолвер (Recursive Resolver)** — DNS-сервер, который принимает запросы от клиентов и самостоятельно выполняет полный путь разрешения имени: от корневых серверов через TLD до авторитативного сервера. В отличие от кэширующего прокси, не зависит от внешних серверов для рекурсии.

**Кэширующий резолвер (Caching Resolver)** — DNS-сервер, который хранит результаты предыдущих запросов и возвращает их без обращения к authoritative-серверам. Unbound сочетает рекурсию и кэширование.

**RRL (Response Rate Limiting)** — механизм защиты от DNS-амплификации и water torture атак. Ограничивает количество одинаковых ответов в секунду для предотвращения abuse.

**DNS Cache Snooping** — атака, при которой злоумышленник определяет, какие домены уже запрашивались другими клиентами, по времени ответа (кэш-попадание vs. рекурсия). Unbound защищён от этой атаки по умолчанию.

---

## Базовые концепции

### Архитектура Unbound

Unbound работает как **единственный процесс** с event-driven архитектурой. В отличие от BIND, который может быть одновременно авторитативным сервером, рекурсивным резолвером и мастером зон, Unbound — чистый рекурсивный резолвер.

```text
┌─────────────────────────────────────┐
│            Клиенты                   │
│  (getaddrinfo, dig, браузеры)       │
└──────────────┬──────────────────────┘
               │ UDP/TCP :53
┌──────────────▼──────────────────────┐
│          Unbound                     │
│  ┌──────────┐  ┌──────────────────┐ │
│  │  Кэш     │  │  Рекурсивный     │ │
│  │  (RAM)   │──│  движок          │ │
│  └──────────┘  └──────────────────┘ │
│                                     │
│  ┌──────────┐  ┌──────────────────┐ │
│  │  RRL     │  │  DNSSEC          │ │
│  │  (защита)│  │  валидация       │ │
│  └──────────┘  └──────────────────┘ │
└──────────────┬──────────────────────┘
               │ UDP/TCP :53
┌──────────────▼──────────────────────┐
│     Корневые / TLD / Авторитативные │
│     серверы (root hints)            │
└─────────────────────────────────────┘
```

### Unbound vs BIND vs dnsmasq

| Критерий | Unbound | BIND (recursive) | dnsmasq |
| :--- | :--- | :--- | :--- |
| **Назначение** | Рекурсивный резолвер | Универсал (master/slave/recursive) | Локальный кэш + DHCP |
| **Производительность** | Высокая (event-driven) | Средняя (threaded) | Низкая (однопоточный) |
| **DNSSEC** | Полная валидация | Полная валидация | Нет |
| **RRL** | Встроен | Встроен | Нет |
| **Кэш** | Большой, оптимизированный | Настраиваемый | Маленький |
| **Рекурсия** | Да (основная функция) | Опционально | Нет |
| **Авторитативные зоны** | Нет | Да | Ограниченные |
| **Размер конфига** | Маленький | Большой | Средний |
| **Сложность настройки** | Низкая | Высокая | Средняя |

### Когда использовать Unbound

**Используйте Unbound когда:**
- Нужен быстрый рекурсивный резолвер для внутренней сети
- Требуется DNSSEC-валидация
- Нужна защита от DNS-атак (RRL, cache snooping)
- Нет необходимости в авторитативных зонах
- Хотите заменить публичные резолверы (8.8.8.8) собственным

**Не используйте Unbound когда:**
- Нужен авторитативный сервер (для зон) — используйте BIND или PowerDNS
- Нужна интеграция с DHCP — используйте dnsmasq илиkea
- Нужен минимальный footprint на embedded-устройствах — используйте dnsmasq

---

## Практические сценарии

### Предусловия

```bash
# Debian/Ubuntu
sudo apt install unbound unbound-anchor

# RHEL/CentOS
sudo yum install unbound unbound-anchor

# Проверка версии
unbound -V
# → Version 1.x.x
```

### 1. Установка и базовая конфигурация

**Конфигурация `/etc/unbound/unbound.conf`:**
```yaml
# Основные настройки
server:
    verbosity: 1
    interface: 0.0.0.0
    port: 53
    do-ip4: yes
    do-ip6: no
    do-udp: yes
    do-tcp: yes

    # Безопасность
    harden-glue: yes
    harden-dnssec-stripped: yes
    harden-referral-path: yes
    harden-algo-downgrade: yes
    use-caps-for-id: yes

    # Кэш
    msg-cache-size: 128m
    rrset-cache-size: 256m
    cache-max-ttl: 86400
    cache-min-ttl: 60
    prefetch: yes
    prefetch-key: yes

    # RRL (Response Rate Limiting)
    ratelimit: 1000
    minimal-responses: yes

    # Приватность
    qname-minimisation: yes
    qname-minimisation-strict: no

    # DNSSEC
    auto-trust-anchor-file: /var/lib/unbound/root.key

    # Адресные шаблоны (защита от spoofing)
    access-control: 127.0.0.0/8 allow
    access-control: 10.0.0.0/8 allow
    access-control: 192.168.0.0/16 allow
    access-control: 0.0.0.0/0 refuse

    # Логирование
    log-queries: no
    log-replies: no
    log-servfail: yes

    # Производительность
    num-threads: 4
    so-reuseport: yes
    msg-cache-slabs: 8
    rrset-cache-slabs: 8

# Пересылка в публичные резолверы (fallback)
forward-zone:
    name: "."
    forward-addr: 9.9.9.9
    forward-addr: 1.1.1.1
    forward-first: yes
```

**Применение:**
```bash
# Валидация конфигурации
sudo unbound-checkconf /etc/unbound/unbound.conf
# → no errors in /etc/unbound/unbound.conf

# Перезапуск
sudo systemctl restart unbound

# Проверка статуса
sudo systemctl status unbound
# → Active: active (running)
```

### 2. Настройка DNSSEC-валидации

```bash
# Генерация trust anchor (если не создан автоматически)
sudo unbound-anchor -a /var/lib/unbound/root.key

# Проверка trust anchor
sudo unbound-anchor -v -a /var/lib/unbound/root.key
# → [1680000000] trust anchor for . is valid

# Проверка DNSSEC через dig
dig @127.0.0.1 dnssec-failed.org +dnssec +cd
# → CD flag set (bypass validation)

dig @127.0.0.1 dnssec-failed.org +dnssec
# → SERVFAIL (DNSSEC validation failed — это правильное поведение)
```

### 3. Управление кэшем

```bash
# Просмотр статистики кэша
unbound-control stats_noreset
# → num.query.type.A: 15234
# → num.query.type.AAAA: 8912
# → num.cache.hits: 12345
# → num.cache.misses: 2889
# → mem.cache.rrset: 45 MB
# → mem.cache.message: 23 MB

# Очистка всего кэша
sudo unbound-control flush_zone .
# → ok: cache for . flushed

# Очистка кэша для конкретного домена
sudo unbound-control flush_zone example.com
# → ok: cache for example.com flushed

# Очистка всех записей
sudo unbound-control flush_stats all
```

### 4. Настройка пересылки (Forwarding)

```yaml
# Основной forwarder
forward-zone:
    name: "."
    forward-addr: 9.9.9.9
    forward-addr: 1.1.1.1
    forward-first: yes
```

**Режимы:**
- `forward-first: yes` — сначала пересылает, при неудаче делает рекурсию сам
- `forward-first: no` — только пересылает (forward-only)

**Условная пересылка (conditional forwarding):**
```yaml
# Внутренние домены — рекурсия без пересылки
forward-zone:
    name: "internal.company.com"
    # Нет forward-addr — прямая рекурсия

# Внешние домены — пересылка в Quad9
forward-zone:
    name: "."
    forward-addr: 9.9.9.9
    forward-first: yes
```

### 5. Диагностика проблем

```bash
# Проверка доступности
dig @127.0.0.1 google.com +noall +stats
# → Query time: 23 msec

# Проверка SERVFAIL
dig @127.0.0.1 nonexistent.example.com +noall +header
# → flags: qr rd ra; status: SERVFAIL;

# Анализ логов
sudo journalctl -u unbound -n 50
# → info: service stopped
# → info: starting Unbound
# → info: generate key for zone .
# → info: validation success

# Проверка RRL (Response Rate Limiting)
# Отправьте 100 одинаковых запросов
for i in $(seq 1 100); do
  dig @127.0.0.1 test$i.example.com +noall +stats &
done
# → Unbound должен начать отвечать REFUSED или замедлять ответы

# Проверка DNSSEC
dig @127.0.0.1 example.com +dnssec +noall +answer
# → должен содержать RRSIG-записи
```

### 6. Интеграция с systemd-resolved

```bash
# Настройка systemd-resolved использовать Unbound
# В /etc/systemd/resolved.conf:
# [Resolve]
# DNS=127.0.0.1
# FallbackDNS=
# DNSSEC=allow-downgrade
# DNSOverTLS=opportunistic

# Перезапуск
sudo systemctl restart systemd-resolved

# Проверка
resolvectl status
# → Global: DNS Servers: 127.0.0.1
```

### 7. Мониторинг Unbound

```yaml
# В unbound.conf — включение remote control
remote-control:
    control-enable: yes
    control-interface: 127.0.0.1
    control-port: 8953
    server-key-file: "/etc/unbound/unbound_server.key"
    server-cert-file: "/etc/unbound/unbound_server.pem"
    control-key-file: "/etc/unbound/unbound_control.key"
    control-cert-file: "/etc/unbound/unbound_control.pem"
```

```bash
# Просмотр метрик
unbound-control stats_noreset | head -20
# → num.query: 15234
# → num.answer: 15234
# → num.cache.hits: 12345
# → num.cache.misses: 2889
# → num.prefetch: 1234
# → num.zero_ttl: 0
```

### 8. Бенчмаркинг Unbound

```bash
# Тест производительности
dnspyre --server 127.0.0.1 --queries 10000 --concurrency 100 example.com
# → QPS: 8923.4  p99: 1.45ms

# Сравнение с BIND
dnspyre --server 10.0.0.53 --queries 10000 --concurrency 100 example.com
# → QPS: 4523.1  p99: 3.21ms

# Unbound обычно быстрее для рекурсивных запросов
```

---

## Лучшие практики

*   **Используйте `forward-first: yes`:** Это позволяет Unbound делать рекурсию сам, если forwarder недоступен. В `forward-only` режиме запросы завершаются SERVFAIL при недоступности forwarder.
*   **Настройте RRL (ratelimit):** Значение 1000 — хорошая отправная точка. Снизьте до 100 для агрессивной защиты от DDoS.
*   **Включите `prefetch: yes`:** Unbound будет обновлять популярные записи в кэше до истечения их TTL, что снижает задержки для клиентов.
*   **Используйте `qname-minimisation`:** Это повышает приватность, отправляя минимум информации на каждом уровне рекурсии.
*   **Размер кэша:** `msg-cache-size: 128m` и `rrset-cache-size: 256m` — хорошие значения для сервера с 4+ ГБ RAM. На меньше — уменьшите.
*   **Не используйте `0.0.0.0` для `access-control` без `refuse`:** По умолчанию Unbound拒绝ает все подключения. Явно указывайте `allow` для доверенных сетей.
*   **Мониторьте `num.cache.misses`:** Если промахи растут — возможно, кэш слишком мал или TTL слишком низкий.
*   **Проверяйте DNSSEC:** Unbound должен отвечать SERVFAIL для доменов с неправильными подписями. Это правильное поведение, не ошибка.

---

## Дополнительная информация

### Инструментарий

- **unbound:** Основной бинарник.
- **unbound-control:** Управление кэшем и статистикой.
- **unbound-checkconf:** Валидация конфигурации.
- **unbound-anchor:** Управление trust anchor для DNSSEC.
- **unbound-host:** Проверка разрешения имён.

### Ключевые RFC

- **RFC 7706:** Local DNS Root Zone Deployment.
- **RFC 8020:** NXDOMAIN: There Really Is Nothing Underneath.
- **RFC 8198:** Aggressive Use of DNSSEC-Validated Cache.
- **RFC 9156:** DNS Queries over HTTPS (DoH) for Recursive Resolvers.

### Связанные разделы

- [Протокол DNS](./dns.md) — общая архитектура и порты.
- [Петли перенаправления DNS](./dns_forwarding_loops.md) — как избежать петель с Unbound.
- [Тестирование производительности DNS](./dns_performance_testing.md) — бенчмаркинг Unbound.
- [Безопасность DNS](./dns_security.md) — DNSSEC и защита от атак.
- [Мониторинг DNS](./dns_monitoring.md) — метрики и алертинг.
- [BIND: Перенаправляющий сервер](../../../Linux/Networking/Services/BIND/forwarding_server.md) — сравнение с BIND forwarding.
