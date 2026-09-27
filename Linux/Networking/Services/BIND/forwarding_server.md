# BIND: Перенаправляющий сервер

---

## Определения

**Forwarding DNS-сервер (Domain Name System)** — рекурсивный сервер, который перенаправляет все входящие запросы внешним DNS-серверам (форвардерам), вместо выполнения полной итеративной рекурсии самостоятельно. В режиме `forward only` сервер работает как чистый прокси; в режиме `forward first` выполняет fallback-рекурсию при недоступности апстримов.

**Форвардер (Forwarder)** — внешний DNS-сервер, которому делегируется выполнение рекурсивного поиска (например, публичные серверы Quad9, Cloudflare или корпоративные апстримы). В BIND список форвардеров задаётся в блоке `options { forwarders { ... }; };` и применяется глобально или в рамках `view`.

**Условная пересылка (Conditional Forwarding)** — механизм, при котором запросы к определённым доменам или подсетям направляются на специализированные серверы, а все остальные — на глобальные форвардеры. В BIND реализуется через отдельные блоки `zone` с директивой `forwarders` или через `view`.

**QNAME Minimization (Query Name Minimization)** — механизм обеспечения приватности (RFC 7816 / RFC 9156), при котором сервер отправляет вышестоящим инстанциям только минимально необходимую часть доменного имени. В BIND управляется параметром `qname-minimization` (`strict`, `relaxed`, `disabled`).

**Stale Cache** — механизм отдачи устаревших записей из кэша при недоступности форвардеров, доступный в BIND 9.18+ через `stale-cache-enable yes;`. Повышает отказоустойчивость, позволяя клиентам получать ответы даже при сбоях апстримов.

**Prefetch** — упреждающее обновление популярных записей в кэше до истечения их TTL. В BIND настраивается через `prefetch <код> <ttl>`, где `<код>` — количество запросов за `<ttl>` секунд, при котором запись считается популярной.

---

## Архитектура и принцип работы

### Поток запроса в forwarding-режиме

При получении запроса клиент BIND выполняет следующие шаги:

1. **Проверка локального кэша:** если ответ есть в кэше и его TTL не истёк — возвращается немедленно.
2. **Проверка условной пересылки:** если запрос соответствует домену, для которого configured conditional forwarder — направляется на указанный сервер.
3. **Глобальная пересылка:** если запрос не попал под условные правила — направляется на серверы из `forwarders { ... };`.
4. **Обработка ответа:** ответ кэшируется с учётом `max-cache-ttl` и возвращается клиенту.
5. **Fallback (только `forward first`):** если все форвардеры недоступны — выполняется итеративная рекурсия самостоятельно.

### Взаимодействие с системным резолвером

В современных дистрибутивах (Ubuntu 18.04+, Debian 10+, RHEL 8+) по умолчанию запущен `systemd-resolved`, который занимает порт `53/udp` на адресе `127.0.0.53`. Для работы BIND как полноценного forwarding-сервера необходимо либо отключить `systemd-resolved`, либо переконфигурировать порт listening.

Техническая причина конфликта: `systemd-resolved` создаёт stub-зоне на `127.0.0.53:53` и перехватывает все DNS-запросы через NSS (Name Service Switch). BIND не может привязаться к порту 53, пока stub активен.

### Кэширование в forwarding-режиме

В отличие от авторитативного режима, в forwarding-режиме кэш является основным источником производительности. BIND хранит в кэше:
- Полные ответы от форвардеров (RRset + TTL)
- NS-записи, полученные в Additional-секции
- Отрицательные кэшированные ответы (NXDOMAIN)

Размер кэша управляется через `max-cache-size` (абсолютное значение или процент RAM) и `max-cache-ttl` (максимальное время жизни записи в кэше).

---

## Основные концепции

### Режимы перенаправления

| Режим | Описание | Конфигурация |
| :--- | :--- | :--- |
| **Forward only** | Сервер только перенаправляет запросы. Если все форвардеры недоступны, клиент получит ошибку (**SERVFAIL**). Идеально для изоляции от прямого доступа в интернет. | `forward only;` |
| **Forward first** | Сначала выполняется попытка перенаправления. При неудаче (тайм-аут) сервер пытается выполнить итеративную рекурсию самостоятельно. | `forward first;` |

**Выбор режима для SRE:**
- **Forward only** — предпочтителен для производственных сред с жёсткими требованиями к безопасности и предсказуемости. Ошибки конфигурации (петли, недоступные апстримы) становятся явными мгновенно.
- **Forward first** — удобен для лабораторных сред и филиалов с нестабильным каналом, где fallback на прямую рекурсию критичен. В production используйте только с мониторингом задержек.

### Условная пересылка (Conditional Forwarding)

В BIND условная пересылка реализуется двумя способами:

**Способ 1: zone-specific forwarders**
```conf
zone "internal.corp" {
    type forward;
    forwarders { 10.0.0.53; };
    forward only;
};
```

**Способ 2: View-specific forwarding**
```conf
view "internal" {
    match-clients { internal-clients; };
    recursion yes;
    forwarders { 10.0.0.1; 10.0.0.2; };
    forward only;
};

view "external" {
    match-clients { any; };
    recursion no;
    allow-query { any; };
};
```

### Преимущества архитектуры

*   **Снижение сетевой нагрузки:** сервер не опрашивает корневые и TLD-серверы напрямую, отправляя один пакет форвардеру.
*   **Агрегированное кэширование:** повторные запросы разных клиентов обслуживаются мгновенно из локальной оперативной памяти.
*   **Безопасность:** возможность централизованной фильтрации трафика через специализированные сервисы (например, Quad9 с блокировкой вредоносных доменов).
*   **Устойчивость (Stale Cache):** в современных версиях BIND (9.18+) поддерживается отдача устаревших данных из кэша, если форвардеры недоступны.
*   **Централизованный контроль:** все внешние запросы проходят через единый узел, что упрощает аудит, логирование и применение политик безопасности.

### Ограничения

*   **Single point of failure:** если все форвардеры недоступны, `forward only` блокирует разрешение для всех клиентов.
*   **Дополнительная задержка:** каждый запрос добавляет минимум один network RTT к форвардеру.
*   **Зависимость от апстримов:** поведение сервера определяется политиками и доступностью внешних резолверов.
*   **Ограничение ECS:** не все публичные форвардеры поддерживают EDNS Client Subnet (ECS). При использовании `forwarders { 9.9.9.9; };` клиентский subnet не передаётся апстриму.

---

## Практические сценарии

### 0. Предварительные проверки

Перед настройкой forwarding-режима убедитесь, что среда подготовлена:

```bash
# 1. Порт 53 свободен
sudo ss -ulnp | grep :53
# → если видите systemd-resolved или другой процесс — требуется отключение

# 2. Установлен NTP-клиент (критично для DNSSEC и TSIG)
sudo apt install -y chrony   # Debian/Ubuntu
sudo dnf install -y chrony   # RHEL

# 3. Firewall разрешает UDP/TCP 53 на внешний интерфейс (если требуется)
sudo iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
sudo iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT
```

### 1. Базовая конфигурация перенаправляющего сервера (forward only)

**Файл `/etc/bind/named.conf.options`:**
```conf
acl "trusted_clients" {
    192.168.1.0/24;
    127.0.0.1;
    10.0.0.0/24;
};

options {
    directory "/var/cache/bind";

    // Список форвардеров (минимум два для отказоустойчивости)
    forwarders {
        9.9.9.9;         // Quad9 (Безопасность + Приватность)
        1.1.1.1;         // Cloudflare
    };
    forward only;

    // Оптимизация кэширования (BIND 9.18+)
    prefetch 2 3600;     // Обновление популярных записей до истечения TTL
    stale-cache-enable yes; // Разрешить отдачу данных из кэша при сбоях апстримов
    max-cache-size 512M; // Лимит оперативной памяти под кэш
    max-cache-ttl 86400; // Максимальное время жизни записи в кэше (1 день)

    // Приватность и безопасность
    qname-minimization relaxed;
    dnssec-validation auto;

    recursion yes;
    allow-query { trusted_clients; };
    listen-on { any; };
    allow-transfer { none; }; // Запретить трансферы для forwarding-сервера
    version "none";
};
```

**Валидация и применение:**
```bash
# Проверка синтаксиса
sudo named-checkconf
# → (no output)

# Применение без остановки службы
sudo rndc reconfig
# → server reload successful

# Проверка статуса
sudo rndc status
# → number of zones: 2
# → recursive clients: 0/0/1000
```

### 2. Конфигурация с fallback (forward first)

Для филиалов с нестабильным каналом:

```conf
options {
    directory "/var/cache/bind";

    forwarders {
        10.0.1.10;       // Корпоративный апстрим (основной)
        10.0.1.11;       // Корпоративный апстрим (резервный)
    };
    forward first;

    // Если апстримы недоступны, выполняем рекурсию сами
    // Stale cache помогает обслуживать клиентов при сбоях
    stale-cache-enable yes;
    max-cache-size 256M;
    max-cache-ttl 86400;

    recursion yes;
    allow-query { internal_clients; };
    listen-on { 10.0.1.20; };
};
```

**Важно:** в режиме `forward first` при недоступности всех форвардеров сервер переходит на прямую рекурсию. Это может создавать скрытые задержки (5–15 секунд) и неожиданную нагрузку на канал. Мониторьте метрику `recursive clients` через `rndc status`.

### 3. Условная пересылка (Conditional Forwarding)

Сценарий: внутренние домены разрешаются через корпоративный DNS, внешние — через публичные резолверы.

```conf
acl "internal_clients" {
    192.168.0.0/24;
    127.0.0.1;
};

options {
    directory "/var/cache/bind";

    // Глобальные форвардеры для внешних доменов
    forwarders {
        9.9.9.9;
        1.1.1.1;
    };
    forward only;

    recursion yes;
    allow-query { internal_clients; };
    listen-on { any; };
};

// Условная пересылка для внутренних доменов
zone "corp.local" {
    type forward;
    forwarders { 10.0.0.53; };
    forward only;
};

zone "10.in-addr.arpa" {
    type forward;
    forwarders { 10.0.0.53; };
    forward only;
};
```

**Валидация:**
```bash
# Внутренний домен — должен разрешаться через 10.0.0.53
dig @127.0.0.1 server01.corp.local +noall +answer
# → server01.corp.local. 3600 IN A 10.0.1.10

# Внешний домен — через 9.9.9.9
dig @127.0.0.1 google.com +noall +answer
# → google.com. 300 IN A 142.250.185.14
```

### 4. View-specific forwarding (Split-horizon)

Внутренние клиенты получают доступ к внутренним доменам и внешним через корпоративные апстримы; внешние клиенты не имеют рекурсии.

```conf
acl "internal_clients" {
    192.168.0.0/24;
    127.0.0.1;
};

view "internal" {
    match-clients { internal_clients; };
    recursion yes;
    forwarders { 10.0.0.1; 10.0.0.2; };
    forward only;

    zone "corp.local" {
        type master;
        file "/etc/bind/zones/db.corp.local.internal";
    };

    include "/etc/bind/named.conf.default-zones";
};

view "external" {
    match-clients { any; };
    recursion no;
    allow-query { any; };

    zone "corp.local" {
        type master;
        file "/etc/bind/zones/db.corp.local.external";
    };
};
```

### 5. Конфигурация для DMZ (с изоляцией)

Сценарий: сервер в DMZ перенаправляет запросы на внешние апстримы, но не имеет доступа к внутренней сети.

```conf
acl "dmz_clients" {
    172.16.0.0/24;
    127.0.0.1;
};

options {
    directory "/var/cache/bind";

    forwarders {
        9.9.9.9;
        1.1.1.1;
    };
    forward only;

    // Жёсткое ограничение: только клиенты из DMZ
    recursion yes;
    allow-query { dmz_clients; };
    allow-query-cache { dmz_clients; };
    listen-on { 172.16.0.10; };

    // Безопасность: запретить ANY-запросы (anti-amplification)
    allow-query-cache { dmz_clients; };
    rate-limit {
        responses-per-second 10;
        window 5;
    };
};
```

### 6. Использование RPZ (Response Policy Zones) с forwarding

Для централизованной фильтрации вредоносных доменов на forwarding-сервере:

```conf
options {
    directory "/var/cache/bind";

    forwarders {
        9.9.9.9;
        1.1.1.1;
    };
    forward only;

    recursion yes;
    allow-query { trusted_clients; };
};

// RPZ-зона (локальный список блокировок)
zone "rpz" {
    type master;
    file "/etc/bind/zones/db.rpz";
};

// Глобальная политика
response-policy {
    zone "rpz";
};
```

### 7. Проверка и применение изменений

```bash
# Проверка синтаксиса (отсутствие вывода означает успех)
sudo named-checkconf
# → (empty)

# Перечитывание конфигурации без остановки службы
sudo rndc reconfig
# → server reload successful
```

### 8. Верификация разрешения имён

```bash
dig @127.0.0.1 google.com
# → status: NOERROR
# → flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
```

**Анализ ответа:**
- `status: NOERROR` — запрос успешно выполнен.
- `flags: ra` (**Recursion Available**) — сервер подтвердил готовность выполнять рекурсию.
- `AUTHORITY: 0` — признак того, что ответ получен из кэша или от форвардера (ответ не является авторитетным).

### 9. Проверка условной пересылки

```bash
# Внутренний домен — должен разрешаться через условного форвардера
dig @127.0.0.1 server01.corp.local +noall +answer
# → server01.corp.local. 3600 IN A 10.0.1.10

# Внешний домен — через глобального форвардера
dig @127.0.0.1 google.com +noall +answer
# → google.com. 300 IN A 142.250.185.14
```

---

## Мониторинг и метрики

### Статистический канал (Statistics Channel)

Включите в `named.conf.options`:
```conf
statistics-channels {
    inet 127.0.0.1 port 8053 allow { 127.0.0.1; };
};
```

**Проверка:**
```bash
curl -s http://127.0.0.1:8053/ | python3 -m json.tool | grep -E "cache|recursive|queries"
```

Ключевые метрики для forwarding-сервера:
- `Server Statistics` → `queries` — общее количество запросов
- `Server Statistics` → `recursive-clients` — активные рекурсивные запросы
- `Cache Statistics` → `cache size` — размер кэша
- `Server Statistics` → `qtypes` — распределение типов запросов (A, AAAA, MX)

### Мониторинг через rndc

```bash
# Общий статус
sudo rndc status
# → version: BIND 9.18.x
# → number of zones: 2
# → recursive clients: 0/0/1000
# → number of TCP connections: 0

# Включение лога запросов (временная отладка)
sudo rndc querylog on

# Дump кэша для анализа
sudo rndc dumpdb -cache /var/cache/bind/named_dump.db
# → dumped database to /var/cache/bind/named_dump.db

# Статус конкретной зоны (если используются forward-zone)
sudo rndc zonestatus rpz
```

### Скрипт health-check для мониторинга

```bash
#!/bin/bash
# /usr/local/bin/bind-forwarder-health.sh

FORWARDERS="9.9.9.9 1.1.1.1"
LOCAL_RESOLVER="127.0.0.1"
ALERT_THRESHOLD=2 # секунд

for fw in $FORWARDERS; do
    time_direct=$(dig @$fw google.com +noall +stats | grep "Query time:" | awk '{print $4}')
    time_local=$(dig @$LOCAL_RESOLVER google.com +noall +stats | grep "Query time:" | awk '{print $4}')

    if [ -z "$time_direct" ] || [ -z "$time_local" ]; then
        echo "CRITICAL: Cannot resolve via $fw or local resolver"
        exit 1
    fi

    latency_diff=$((time_local - time_direct))
    if [ $latency_diff -gt $ALERT_THRESHOLD ]; then
        echo "WARNING: Latency via forwarder $fw is ${time_local}ms (direct ${time_direct}ms)"
    else
        echo "OK: Forwarder $fw latency ${time_local}ms"
    fi
done
```

---

## Управление кэшем

### Параметры кэширования

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `max-cache-size` | Лимит оперативной памяти под кэш. | 50%–70% доступной **RAM**. Можно указать в байтах или процентах (например, `512M`). |
| `max-cache-ttl` | Максимальное время жизни записи в кэше. | `86400` (1 день). Большие значения повышают риск неактуальности данных. |
| `prefetch` | Упреждающее обновление популярных записей. | `prefetch 2 3600;` — активируйте для высоконагруженных резолверов. |
| `stale-cache-enable` | Разрешить отдачу устаревших данных при сбоях апстримов. | `yes` для повышения отказоустойчивости. |
| `stale-answer-ttl` | Время, в течение которого устаревший ответ может отдаваться клиенту. | `30` (секунд) по умолчанию; уменьшите для более строгого контроля. |
| `max-ncache-ttl` | Время хранения отрицательных ответов в кэше. | `10800` (3 часа) — достаточно для большинства сценариев. |

### Очистка кэша

```bash
# Очистка всего кэша
sudo rndc flush
# → all caches flushed

# Очистка конкретного имени из кэша
sudo rndc flushname example.com
# → flushed name 'example.com' from cache

# Очистка конкретного домена
sudo rndc flushtree example.com
# → flushed tree 'example.com' from cache
```

---

## Безопасность

### Ограничение доступа

Всегда используйте ACL для ограничения клиентов, которым разрешена рекурсия:

```conf
acl "trusted_clients" {
    192.168.1.0/24;
    127.0.0.1;
    !blocked_ranges; // Запрет для конкретных подсетей
};
```

### Защита от амплификации

Forwarding-сервер может быть использован для DNS Amplification-атак. Ограничьте:

```conf
options {
    recursion yes;
    allow-query { trusted_clients; }; // Только доверенные подсети
    allow-query-cache { trusted_clients; };
    rate-limit {
        responses-per-second 10;
        window 5;
    };
};
```

### DNSSEG и валидация

Включайте DNSSEC-валидацию для защиты от подделки ответов:

```conf
options {
    dnssec-validation auto;
    trust-anchors {
        // Явное указание trust-anchor (если auto недоступен)
        ". 257 3 8 ...";
    };
};
```

### Изоляция от прямого доступа в интернет

Для максимальной безопасности используйте `forward only` и разместите сервер в отдельной VLAN/DMZ без маршрута по умолчанию. Это гарантирует, что при сбое апстримов сервер вернёт `SERVFAIL`, а не начнёт выполнять полную рекурсию.

---

## Производительность и масштабирование

### Рекомендации по производительности

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `max-cache-size` | Лимит RAM под кэш. | 50%–70% доступной RAM. |
| `prefetch` | Упреждающее обновление популярных записей. | `prefetch 2 3600;` для высоконагруженных серверов. |
| `stale-cache-enable` | Отдача устаревших данных при сбоях апстримов. | `yes` для повышения отказоустойчивости. |
| `qname-minimization` | Приватность запросов к апстримам. | `relaxed` (баланс приватности и совместимости). |
| `dnssec-validation` | Валидация DNSSEC-подписей. | `auto` (использует trust-anchor от IANA). |
| `resolver-query-timeout` | Таймаут запроса к апстриму (мс). | `7000` (по умолчанию 10 сек). |
| `max-recursion-depth` | Максимальная глубина рекурсии (fallback). | `32` (по умолчанию 7 — для `forward first`). |

### Масштабирование

При росте числа клиентов (>10 000) рассмотрите:
- **Разделение на multiple forwarding-серверы** с round-robin через DNS Round Robin или GSLB.
- **Увеличение max-cache-size** до 70% RAM для уменьшения количества запросов к апстримам.
- **Использование TCP Fast Open (TFO)** — BIND 9.20+ поддерживает TFO для снижения latency при повторных TCP-соединениях.
- **Локализация апстримов:** разместите форвардеры в той же дата-центрской зоне, что и клиенты, для снижения RTT.

---

## Резервное копирование и откат

### Экспорт конфигурации

```bash
# Создание резервной копии конфигурации
sudo tar -czf /backup/bind-forwarder-$(date +%Y%m%d).tar.gz \
    /etc/bind/named.conf.options \
    /etc/bind/named.conf.local \
    /etc/bind/zones/
```

### Восстановление

```bash
# Распаковка и восстановление
sudo tar -xzf /backup/bind-forwarder-20260912.tar.gz -C /
sudo named-checkconf && sudo rndc reconfig
```

### Откат изменений

```bash
# Если новая конфигурация сломала разрешение — вернитесь к предыдущей
sudo cp /etc/bind/named.conf.options.bak /etc/bind/named.conf.options
sudo rndc reconfig
```

---

## Диагностика и отладка

### Методология диагностики для forwarding-сервера

При проблемах с разрешением имён через forwarding-сервер:

1. **Триаж:** определите масштаб (один клиент, подсеть, все клиенты).
2. **Проверка доступности апстримов:** `dig @9.9.9.9 google.com` — работает ли прямой запрос к форвардеру.
3. **Валидация конфигурации:** `named-checkconf` — нет ли опечаток в `forwarders`.
4. **Анализ логов:** `journalctl -u bind9 -n 100 | grep -E "forward|SERVFAIL|timeout"`.
5. **Запрос-ответ:** `dig @127.0.0.1 google.com +stats` — сравните RTT с прямым запросом к апстриму.
6. **Статистика:** `rndc status`, `rndc dumpdb -cache`.
7. **Исправление и валидация:** внесите изменения, `rndc reconfig`, повторите тест.

### Типичные проблемы и решения

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `SERVFAIL` на все запросы | `forward only` + недоступный форвардер или петля | `dig @127.0.0.1 google.com +noall +header` | Проверьте `forwarders`, убедитесь что порт 53 открыт на апстриме |
| Задержка 5+ сек | `forward first` + таймаут апстрима | `dig @127.0.0.1 google.com +stats` | Проверьте доступность апстримов, рассмотрите `forward only` |
| `SERVFAIL` только для внутренних доменов | Неверная conditional forwarding | `dig @127.0.0.1 server01.corp.local` | Проверьте блок `zone "corp.local" { type forward; ... };` |
| `REFUSED` от апстрима | IP попал в черный список | `dig @9.9.9.9 google.com` | Используйте другой апстрим или запросийте снятие блокировки |
| `NXRRSET` / `NOTAUTH` | Ошибка в конфигурации зоны | `named-checkconf` | Проверьте синтаксис блоков `zone` |
| `too many open files` | Петля перенаправления | `journalctl -u bind9 \| grep "too many open"` | Удалите `127.0.0.1` из `forwarders` |
| Медленный старт | Большой кэш на HDD | `time sudo systemctl restart bind9` | Перенесите `/var/cache/bind` на SSD или уменьшите `max-cache-size` |

### Диагностика через dig

```bash
# Проверка статуса ответа
dig @127.0.0.1 google.com +noall +header
# → status: NOERROR
# → flags: qr rd ra

# Измерение задержки
dig @127.0.0.1 google.com +noall +stats
# → Query time: 23 msec

# Сравнение с прямым запросом к апстриму
dig @9.9.9.9 google.com +noall +stats
# → Query time: 18 msec

# Проверка DNSSEC-валидации
dig @127.0.0.1 google.com +dnssec +noall +answer +ad
# → ad флаг присутствует, если ответ аутентичен

# Проверка через TCP (если UDP заблокирован)
dig @127.0.0.1 google.com +tcp

# Проверка ECS-поддержки
dig @127.0.0.1 cdn.example.com A +subnet=192.0.2.0/24 +noall +answer
```

### Проверка доступности апстримов

```bash
# UDP 53
dig @9.9.9.9 google.com +noall +stats
# → Query time: 18 msec

# TCP 53 (для AXFR/больших ответов)
dig @9.9.9.9 google.com +tcp +noall +stats

# Проверка DNSSEC через апстрим
dig @9.9.9.9 google.com +dnssec +noall +answer
```

### Анализ логов

```bash
# Последние ошибки
sudo journalctl -u bind9 -p err -n 50

# Фильтр по пересылке и таймаутам
sudo journalctl -u bind9 -n 200 | grep -E "forward|timeout|SERVFAIL|network unreachable"

# Логи запросов (если включено)
sudo tail -f /var/log/named/query.log | grep "google.com"
```

### Dump кэша

```bash
# Дамп всего кэша
sudo rndc dumpdb -cache /var/cache/bind/named_dump.db

# Поиск конкретного имени
grep "google.com" /var/cache/bind/named_dump.db
# → google.com. 300 IN A 142.250.185.14
```

---

## Риски: Петли перенаправления (Forwarding Loops)

Одной из самых опасных ошибок конфигурации является указание локального адреса сервера (`127.0.0.1` или собственного IP) в списке `forwarders`. Это создает бесконечный цикл запросов, приводящий к:
- Исчерпанию ресурсов (CPU, дескрипторы файлов).
- Огромным задержкам (Latency) при разрешении имен.
- Ошибкам `SERVFAIL` (в режиме `forward only`).

Подробный разбор сценариев, методов диагностики (tcpdump) и способов предотвращения петель представлен в SSoT-файле: **[Петли перенаправления DNS](../../../../Networking/Protocols/DNS/dns_forwarding_loops.md)**.

---

## Связанные темы

*   **[Обзор BIND](./overview.md)** — архитектура, роли и базовые настройки.
*   **[Установка BIND](./installation.md)** — установка пакетов и устранение конфликтов с systemd-resolved.
*   **[Продвинутые возможности](./advanced_topics.md)** — Views, RPZ, Catalog Zones, dnssec-policy.
*   **[Диагностика BIND](./troubleshooting.md)** — глубокий анализ ошибок и кодов RCODE.
*   **[Петли перенаправления DNS](../../../../Networking/Protocols/DNS/dns_forwarding_loops.md)** — диагностика и предотвращение петель.
*   **[Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md)** — настройка шифрования DNS-трафика (**DoH/DoT**), QNAME Minimization, DNS Cookies.
*   **[Протокол DNS](../../../../Networking/Protocols/DNS/dns.md)** — фундаментальные принципы и иерархия системы.
*   **[Разрешение DNS](../../../../Networking/Protocols/DNS/dns_resolution.md)** — механизмы рекурсии, кэширования и современные оптимизации.
