# BIND: Расширенные возможности

---

## Определения

**Views (Представления)** — механизм в **BIND (Berkeley Internet Name Domain)**, позволяющий серверу предоставлять разные наборы данных (зон или параметров) в зависимости от источника **DNS (Domain Name System)** запроса (например, **IP-адреса** клиента).

**ACL (Access Control List)** — именованный список IP-адресов, сетей или ключей, используемый для разграничения доступа к функциям сервера (рекурсии, трансферу зон, динамическим обновлениям).

**RPZ (Response Policy Zones)** — механизм "DNS Firewall", позволяющий изменять ответы DNS-сервера или блокировать запросы к определённым доменам на основе локальных или внешних списков угроз.

**Catalog Zones (CatZ)** — современный метод (RFC 9432) автоматизации управления вторичными серверами, при котором список зон передается как данные специальной зоны, избавляя от необходимости вручную править конфиги на всех узлах.

**dnssec-policy** — декларативный механизм BIND 9.18+ для автоматизации управления ключами DNSSEC и подписи зон через политики жизненного цикла ключей.

**QNAME Minimization** — техника (RFC 7816 / RFC 9156), при которой резолвер на каждом этапе иерархии отправляет только необходимую часть имени, снижая утечку данных о полном имени пользователя.

**RRL (Response Rate Limiting)** — механизм защиты от DNS Amplification-атак путём ограничения количества ответов сервера для одного источника.

**ECS (EDNS Client Subnet, RFC 7871)** — расширение протокола DNS, позволяющее рекурсивному резолверу передавать часть IP-адреса клиента авторитативному серверу.

**NTA (Negative Trust Anchor)** — механизм отключения валидации DNSSEC для конкретных зон при проблемах с цепочкой доверия.

**DNS64/NAT64** — механизмы перевода запросов A-записей в AAAA для IPv6-only клиентов через синтез адресов.

---

## Базовые концепции

### Сценарии использования Views

| Сценарий | Описание |
| :--- | :--- |
| **Split-horizon DNS** | Внутренние клиенты получают локальные адреса (например, 10.x.x.x), внешние — публичные IP тех же ресурсов. |
| **Геораспределение (Geo-DNS)** | Направление клиентов на ближайшие CDN-узлы на основе их географического положения. |
| **Изоляция сред** | Разделение пространств имён для Dev/Test/Prod окружений на одном физическом сервере. |
| **View-specific forwarding** | Внутренние клиенты рекурсивно разрешают имена, внешние — получают ответ только из авторитативных зон. |

### Расширенные ACL

Помимо простых IP-адресов, ACL могут содержать ключи TSIG и ссылаться на другие ACL:

```conf
acl "trusted-secondaries" {
    192.168.1.2;
    192.168.1.3;
};

acl "internal-clients" {
    localhost;
    localnets;
    !"blocked-ranges";
    trusted-secondaries;
};

acl "blocked-ranges" {
    192.168.100.0/24;  # Внутренний диапазон для блокировки
};
```

**Именованные ключи (TSIG) в ACL:**
```conf
key "transfer-key" {
    algorithm hmac-sha256;
    secret "base64-encoded-secret==";
};

acl "authorized-transfers" {
    192.168.1.2 key "transfer-key";
    192.168.1.3 key "transfer-key";
};
```

### Стандартные ACL

BIND предоставляет встроенные списки доступа:
*   `any` — разрешает доступ всем.
*   `none` — запрещает доступ всем.
*   `localhost` — разрешает доступ только с IP-адресов локальных интерфейсов сервера.
*   `localnets` — разрешает доступ из всех сетей, к которым напрямую подключён сервер.

### Архитектурные стандарты

**RFC 9704** (2025) описывает современные подходы к реализации **Split-horizon DNS**, минимизирующие риски утечки внутренней структуры сети наружу.

---

## Практические сценарии

### 1. Настройка Split-horizon DNS (Views)

При использовании `view` **все** зоны (включая стандартные) должны быть описаны внутри блоков представлений.

**Конфигурация в `/etc/bind/named.conf.local`:**

```conf
acl "internal-clients" {
    192.168.0.0/24;
    127.0.0.1;
};

view "internal" {
    match-clients { internal-clients; };
    recursion yes;

    zone "corp.local" {
        type master;
        file "/etc/bind/zones/db.corp.local.internal";
    };

    include "/etc/bind/named.conf.default-zones";
};

view "external" {
    match-clients { any; };
    recursion no; // Защита от использования сервера для DDoS-атак типа DNS Amplification

    zone "corp.local" {
        type master;
        file "/etc/bind/zones/db.corp.local.external";
    };
};
```

### 2. View-specific forwarding

Внутренние клиенты могут использовать рекурсию, а внешние — только авторитативные ответы:

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

### 3. Автоматизация DNSSEC (dnssec-policy)

В BIND 9.18+ управление ключами и подписью зоны автоматизировано через политики.

**Настройка в `/etc/bind/named.conf.options`:**

```conf
dnssec-policy "standard-policy" {
    keys {
        ksk lifetime unlimited algorithm rsasha256 2048;
        zsk lifetime P60D algorithm rsasha256 1024;
    };
};

zone "example.com" {
    type master;
    file "/etc/bind/zones/db.example.com";
    dnssec-policy "standard-policy";
    inline-signing yes; // Автоматическая подпись без изменения исходного файла базы зоны
};
```

#### Офлайн-роллинг KSK с CDS/CDNSKEY

Для зон с высокими требованиями к безопасности используйте CDS/CDNSKEY-записи для автоматического обновления DS-записей в родительской зоне:

```conf
dnssec-policy "standard-policy" {
    keys {
        ksk lifetime P365D algorithm ecdsa-p256 256;
        zsk lifetime P30D algorithm ecdsa-p256 256;
    };
    cds-policy "cds-policy";  # Автоматическая публикация CDS/CDNSKEY
};
```

**Ручной роллинг KSK (если требуется offline-процедура):**
```bash
# 1. Генерация нового KSK
dnssec-keygen -a ECDSA-P256-SHA256 -b 256 -f KSK example.com.

# 2. Добавление нового ключа в зону (метод "double-DS")
cat Kexample.com.+013+65432.key >> /etc/bind/zones/db.example.com

# 3. rndc loadkeys для предварительной загрузки
sudo rndc loadkeys example.com

# 4. Обновление DS-записи в родительской зоне (через регистратора)

# 5. Удаление старого KSK после распространения (обычно 48 часов)
rndc loadkeys example.com  # BIND автоматически очистит старые ключи
```

### 4. Настройка Catalog Zones (CatZ)

Позволяет Master-серверу передавать список всех зон Slave-серверам автоматически.

**На Master-сервере:**
```conf
zone "catalog.example" {
    type master;
    file "/var/lib/bind/db.catalog.example";
    allow-transfer { 192.168.1.2; }; // IP вторичного сервера
};
```

**На Slave-сервере:**
```conf
catalog-zones {
    zone "catalog.example" {
        default-masters { 192.168.1.1; };
        zone-directory "/var/lib/bind/secondary";
        in-memory no;
    };
};
```

#### Catalog Zones с Views

Для изоляции сред используйте CatZ внутри Views:

```conf
view "internal" {
    match-clients { internal-clients; };
    catalog-zones {
        zone "catalog.internal.example" {
            default-masters { 192.168.1.1; };
            zone-directory "/var/lib/bind/internal-zones";
        };
    };
};

view "external" {
    match-clients { any; };
    catalog-zones {
        zone "catalog.external.example" {
            default-masters { 192.168.1.1; };
            zone-directory "/var/lib/bind/external-zones";
        };
    };
};
```

### 5. Расширенная конфигурация RPZ (BIND-specific)

Помимо базовой политики, BIND поддерживает тонкую настройку RPZ:

```conf
options {
    response-policy {
        zone "rpz.example.com" \
            policy { max-policy-ttl 300; qname-wait-recurse yes; } \
            nsip-enable yes nsdname-enable yes;
    };
};
```

**Параметры политики:**
*   `max-policy-ttl` — максимальный TTL для RPZ-ответов (защита от длительного кэширования блокировок).
*   `qname-wait-recurse` — ждать завершения рекурсии перед применением RPZ (точность, но задержка).
*   `nsip-enable` — проверять IP-адреса NS-записей (блокировка по NS-серверу вредоносного домена).
*   `nsdname-enable` — проверять имена NS-записей.

**Логирование RPZ-решений:**
```conf
logging {
    channel "rpz_log" {
        file "/var/log/named/rpz.log" versions 3 size 10m;
        severity info;
        print-time yes;
    };
    category "rpz" { "rpz_log"; };
};
```

### 6. Расширенные сценарии rndc

| Команда | Описание |
| :--- | :--- |
| `sudo rndc reload` | Полная перезагрузка конфигурации и всех зон. |
| `sudo rndc reload <zone>` | Перезагрузка конкретной зоны. |
| `sudo rndc flush` | Очистка всего кэша резолвера. |
| `sudo rndc flushname <name>` | Очистка конкретного имени из кэша. |
| `sudo rndc status` | Вывод статистики и времени работы сервера. |
| `sudo rndc querylog` | Включение/выключение записи всех входящих запросов в системный журнал. |
| `sudo rndc reconfig` | Перечитывание только конфигов (без проверки файлов зон). |
| `sudo rndc sync <zone>` | Принудительная синхронизация журнала (.jnl) с файлом зоны. |
| `sudo rndc notify <zone>` | Принудительная отправка NOTIFY-сообщений Slave-серверам. |
| `sudo rndc freeze <zone>` | Приостановка динамических обновлений зоны (для резервного копирования). |
| `sudo rndc thaw <zone>` | Возобновление динамических обновлений. |
| `sudo rndc signing -list <zone>` | Список текущих подписей DNSSEC для зоны. |
| `sudo rndc sign <zone>` | Переподписание зоны (если используется dnssec-policy). |
| `sudo rndc stats` | Запись статистики в `named.stats`. |
| `sudo rndc dumpdb -zones` | Дамп всех зон в `named_dump.db`. |
| `sudo rndc zonestatus <zone>` | Статус конкретной зоны (Serial, тип, masters). |

### 7. QNAME Minimization в BIND

Включение в `named.conf.options`:

```conf
options {
    qname-minimization strict;  # RFC 9156: максимальная минимизация
    # Или "relaxed" для совместимости с несовременными серверами
};
```

**Проверка:**
```bash
# Включение отладки QNAME
sudo rndc querylog on
dig @localhost a.b.c.d.e.f.g.example.com +trace
# На каждом этапе запрашивается только достаточная часть имени
```

### 8. Response Rate Limiting (RRL)

Защита от DNS Amplification-атак:

```conf
options {
    rate-limit {
        responses-per-second 5;   # Лимит ответов в секунду на клиента
        window 5;                  # Окно усреднения (секунды)
        slip 2;                    # Каждый 2-й ответ замедляется (RFC 5459)
        max-table-size 20000;      # Максимальный размер таблицы отслеживания
        log-only no;               # false = блокировать, true = только логировать
    };
};
```

**Валидация:**
```bash
# Тест RRL (массовые запросы с одного источника)
for i in $(seq 1 20); do dig @localhost example.com A +short; done
# После 5 запросов в течение 5 секунд ответы начнут замедляться или возвращаться с slip
```

### 9. EDNS Client Subnet (ECS) в BIND

Для авторитативного сервера (отдача ECS клиентам):
```conf
options {
    ecs-address <ipv4-address>;
    ecs-prefix <length>;        # Максимальная длина префикса для ответов
    ecs-prefix-v6 <length>;     # Для IPv6
};
```

Для рекурсивного сервера (передача ECS вверх):
```conf
options {
    ecs yes;                    # Включить передачу ECS
    ecs-address 0.0.0.0/0;      # Источник для поиска ближайшего сервера
    ecs-prefix 24;              # Максимальный префикс для IPv4
};
```

### 10. TCP Fast Open (TFO)

BIND 9.18+ поддерживает TCP Fast Open для снижения задержки при повторных TCP-соединениях:

```conf
options {
    tcp-fast-open yes;
    tcp-fast-open-queue-size 4096;  # Размер очереди TFO cookie
};
```

**Примечание:** TFO требует поддержки ядром Linux (>= 4.11) и включенного параметра `net.ipv4.tcp_fastopen`.

### 11. DNS64/NAT64

Синтез AAAA-записей для IPv6-only клиентов:

```conf
options {
    dns64 64:ff9b::/96 {
        clients { any; };
        mapped { 10.0.0.0/8; };    # Внутренние IPv4-адреса для синтеза
        exclude { 10.0.0.1; };     # Исключить конкретные адреса
        recursive-only yes;
    };
};
```

**Проверка:**
```bash
dig @localhost ipv4-only-host.example.com AAAA +short
# → 64:ff9b::a00:1  (синтезированный адрес)
```

### 12. NTA (Negative Trust Anchor)

Для временного отключения валидации DNSSEC проблемной зоны:

```bash
# Добавить NTA для зоны с битой подписью
sudo rndc nta -add example.com "KSK rollover in progress"

# Просмотр активных NTA
sudo rndc nta -list

# Удалить NTA после исправления
sudo rndc nta -dump example.com
```

### 13. Мониторинг через Statistics Channel

**Включение в `named.conf.options`:**
```conf
statistics-channels {
    inet 127.0.0.1 port 8053 allow { 127.0.0.1; };
    inet 10.0.0.1 port 8053 allow { 10.0.0.0/24; };  # Для мониторинга
};
```

**Ключевые метрики (JSON):**
```bash
curl -s http://127.0.0.1:8053/json | python3 -m json.tool | jq '.counters."QUERY"'
# → общее количество запросов

# Распределение RCODE
curl -s http://127.0.0.1:8053/json | jq '.counters."RESERVED11"'

# Размер кэша
curl -s http://127.0.0.1:8053/json | jq '.memory."Cache"'
```

### 14. Производительность и масштабирование

**Основные параметры в `options`:**
```conf
options {
    # UDP: размер буфера
    udp-receive-buffer 4m;

    # TCP: количество клиентских соединений
    tcp-clients 100;

    # Рекурсия: лимит параллельных клиентов
    recursive-clients 1000;

    # Предвыборка популярных записей
    prefetch 2 90;  # Когда TTL < 90 сек, предзагрузить через 2 запроса

    # Отдача устаревших записей при недоступности источника
    stale-cache-enable yes;
    stale-answer-ttl 30;

    # Размер кэша
    max-cache-size 512m;
    max-cache-ttl 3600;
    max-ncache-ttl 600;

    # Формат файлов зон (raw ускоряет загрузку)
    masterfile-format raw;
};
```

**Рекомендации по ресурсам (SRE):**
*   **RAM:** 1 GB минимум для авторитативного сервера; +1 GB на каждые 1 млн записей в зонах; +2 GB для кэша резолвера на 1 млн запросов/день.
*   **CPU:** BIND преимущественно однопоточный на обработку запроса; `tcp-clients` и `recursive-clients` распределяются по потокам, но пиковые нагрузки требуют быстрых ядер.
*   **Disk:** Используйте SSD для высоконагруженных Slave-серверов с частыми IXFR; `masterfile-format raw;` ускоряет загрузку.

### 15. Управление ключами DNSSEG через dnssec-keymgr

Для сложных сценариев используйте `dnssec-keymgr` для автоматизации роллинга:

```bash
# 1. Создание политики
cat > /etc/bind/policy.conf <<EOF
policy "example.com" {
    algorithm RSASHA256;
    keysize 2048;
    lifetime P365D;
    rollover-style pre-publish;
    parent-propagation-delay 12h;
    zone-propagation-delay 1h;
};
EOF

# 2. Генерация ключей
dnssec-keymgr -t example.com

# 3. Проверка статуса ключей
sudo rndc signing -list example.com
# → KSK: active, expires 2026-07-27
# → ZSK: active, expires 2025-10-27
```

### 16. DDoS-защита и брандмауэр для DNS

#### Типы DDoS-атак на DNS

| Атака | Механизм | Защита |
| :--- | :--- | :--- |
| **DNS Amplification** | Запрос с поддельным IP к открытому резолверу; ответ в 50-100 раз больше запроса | RRL, `recursion no`, `allow-query` |
| **Water Torture** | Массовые запросы к несуществующим поддоменам (`abc123.example.com`) | Aggressive negative cache (NSEC3), rate-limit |
| **NXDOMAIN Flood** | Массовые запросы к несуществующим именам | `max-ncache-ttl`, RRL |
| **TCP SYN Flood** | Заваливание TCP-соединениями | `tcp-clients`, firewall, `tcp-fast-open` |
| **Cache Poisoning** | Подмена DNS-ответа для внедрения ложных данных | DNSSEC, Source Port Randomization |

#### Комплексная конфигурация защиты

```conf
options {
    // 1. Запрет рекурсии (для публичных авторитативных серверов)
    recursion no;
    allow-query { any; };

    // 2. RRL — защита от амплификации
    rate-limit {
        responses-per-second 5;
        window 5;
        slip 2;
        max-table-size 20000;
        log-only no;
    };

    // 3. Ограничение размера кэша (защита от memory exhaustion)
    max-cache-size 256m;
    max-cache-ttl 3600;
    max-ncache-ttl 600;

    // 4. Ограничение TCP-соединений
    tcp-clients 150;
    recursive-clients 1000;
    clients-per-query 10;
    max-clients-per-query 100;

    // 5. Скрытие версии (скрытие информации от атакующих)
    version "none";

    // 6. Ограничение трансферов
    allow-transfer { none; };

    // 7. Запрет ANY-запросов (защита от амплификации)
    // Через RPZ:
    // response-policy { zone "rpz.example.com"; };
};
```

#### Фаервол-правила (iptables/nftables)

```bash
# iptables: ограничение UDP DNS с одного IP
sudo iptables -A INPUT -p udp --dport 53 -m limit --limit 100/s --limit-burst 200 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 53 -j DROP

# iptables: ограничение TCP DNS
sudo iptables -A INPUT -p tcp --dport 53 -m connlimit --connlimit-above 50 -j DROP
sudo iptables -A INPUT -p tcp --dport 53 -j ACCEPT

# nftables (современный)
sudo nft add rule inet filter input udp dport 53 meter dns-rate { ip saddr limit rate 100/second burst 200 packets } accept
sudo nft add rule inet filter input udp dport 53 drop
```

#### Мониторинг атак

```bash
# Обнаружение амплификации
sudo tcpdump -i eth0 port 53 -nn -c 1000 | \
  awk '{print $5}' | cut -d. -f1-4 | sort | uniq -c | sort -rn | head -10
# → Если IP-адрес встречается > 50 раз — подозрительно

# Мониторинг RRL-срабатываний
sudo rndc status | grep -i "rate limit"
# → Rate limit events: X

# Через Prometheus
rate(named_query_rejects_total[5m]) > 10  # Алерт на массовое отклонение
```

### 17. RPZ: интеграция с Threat Intelligence Feed

RPZ может загружать списки угроз из внешних источников (threat intelligence feeds):

#### Источники RPZ-фидов

| Источник | URL | Описание |
| :--- | :--- | :--- |
| ** Spamhaus DBL** | `https://www.spamhaus.org/dbl/` | Домены, связанные со спамом и фишингом |
| **SURBL** | `https://surbl.org/` | Домены в спам-письмах |
| **PhishTank** | `https://phishtank.org/` | Фишинговые сайты |
| **URLhaus** | `https://urlhaus.abuse.ch/` | Вредоносные URL |
| **RPZ.dev** | `https://rpz.dev/` | Агрегатор RPZ-фидов |

#### Настройка автоматической загрузки

**Файл `/opt/rpz-update/update-rpz.sh`:**

```bash
#!/bin/bash
# update-rpz.sh — загрузка и обновление RPZ-зоны из threat intelligence feed
set -euo pipefail

FEED_URL="https://www.spamhaus.org/dbl/listings/dbl.txt"
ZONE_FILE="/var/lib/bind/db.rpz.example.com"
TMP_FILE="/tmp/rpz-feed.txt"

# Загрузка фида
curl -sf "$FEED_URL" -o "$TMP_FILE" || { echo "Failed to download feed"; exit 1; }

# Конвертация в формат BIND zone
cat > "$ZONE_FILE" <<EOF
\$TTL 300
@   IN  SOA ns1.example.com. admin.example.com. (
        $(date +%Y%m%d)01  ; Serial
        3600                ; Refresh
        900                 ; Retry
        1209600             ; Expire
        300                 ; Negative TTL
)
@   IN  NS  ns1.example.com.
EOF

# Конвертация записей
while IFS= read -r domain; do
    [[ "$domain" =~ ^[[:space:]]*# ]] && continue  # Пропуск комментариев
    [[ -z "$domain" ]] && continue
    echo "$domain. IN A 127.0.0.1" >> "$ZONE_FILE"
done < "$TMP_FILE"

# Валидация
named-checkzone rpz.example.com "$ZONE_FILE" || { echo "Zone validation failed"; exit 1; }

# Применение
rndc reload rpz.example.com
logger -t rpz-update "RPZ zone updated: $(wc -l < "$TMP_FILE") records"

rm -f "$TMP_FILE"
```

**Cron (обновление каждые 6 часов):**

```bash
0 */6 * * * /opt/rpz-update/update-rpz.sh >> /var/log/rpz-update.log 2>&1
```

#### Продвинутая конфигурация RPZ с фидами

```conf
// named.conf.options
options {
    response-policy {
        zone "rpz.local" policy { qname-wait-recurse yes; };
        zone "rpz.feed" policy { max-policy-ttl 300; nsip-enable yes; };
    };
};

// named.conf.local
zone "rpz.local" {
    type master;
    file "/var/lib/bind/db.rpz.local";    // Локальные правила
    allow-transfer { none; };
};

zone "rpz.feed" {
    type master;
    file "/var/lib/bind/db.rpz.feed";    // Из threat intelligence feed
    allow-transfer { none; };
};
```

### 18. HSM и offline KSK для DNSSEC

Для зон с максимальными требованиями к безопасности KSK-ключ хранится в HSM (Hardware Security Module) или на offline-машине:

#### Архитектура offline KSK

```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Offline KSK   │────>│  Online ZSK      │────>│  DNS Clients    │
│   (HSM/airgap)  │     │  (BIND server)   │     │                 │
│                 │     │                  │     │                 │
│  dnssec-keygen  │     │  dnssec-signzone │     │  Проверка       │
│  CDS/CDNSKEY    │     │  RRSIG           │     │  RRSIG/DS       │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

#### Использование PKCS#11 с HSM

```conf
// named.conf.local
zone "example.com" {
    type master;
    file "/var/lib/bind/db.example.com";
    key-directory "/etc/bind/keys";
    dnssec-policy "hsm-policy";
    inline-signing yes;
};

dnssec-policy "hsm-policy" {
    keys {
        ksk key-directory lifetime unlimited algorithm ecdsa-p256;
        zsk key-directory lifetime P30D algorithm ecdsa-p256;
    };
};
```

```bash
# Генерация ключа в HSM (пример с SoftHSM для тестов)
softhsm2-util --init-token --slot 0 --label "bind-dnssec" --pin 1234 --so-pin 5678

# Генерация ключа через PKCS#11
dnssec-keygen -3 -n ZONE -K /etc/bind/keys example.com

# Проверка ключа
dnssec-keygen -L example.com
```

#### Автоматический CDS/CDNSKEY (RFC 7344)

Для автоматического обновления DS-записей в родительской зоне:

```conf
dnssec-policy "cds-policy" {
    keys {
        ksk key-directory lifetime P365D algorithm ecdsa-p256;
        zsk key-directory lifetime P30D algorithm ecdsa-p256;
    };
    cds-policy cdslifecycle;
};
```

### 19. Полный сценарий Split-horizon DNS (продакшен)

Полный пример для корпоративной среды с внутренними и внешними клиентами:

```conf
// named.conf

acl "internal-net" {
    10.0.0.0/8;
    172.16.0.0/12;
    192.168.0.0/16;
};

acl "dns-cluster" {
    10.0.0.1;    // ns1
    10.0.0.2;    // ns2
};

// Внутренний view (корпоративная сеть)
view "internal" {
    match-clients { internal-net; };
    recursion yes;
    allow-recursion { internal-net; };
    allow-query { internal-net; };

    // Корпоративные зоны с приватными IP
    zone "corp.local" {
        type master;
        file "/var/lib/bind/internal/db.corp.local";
        allow-transfer { key "transfer-key"; };
    };

    zone "dev.corp.local" {
        type master;
        file "/var/lib/bind/internal/db.dev.corp.local";
    };

    // Forwarding для внешних имен
    forwarders { 8.8.8.8; 1.1.1.1; };
    forward only;

    include "/etc/bind/named.conf.default-zones";
};

// Внешний view (интернет)
view "external" {
    match-clients { any; };
    recursion no;
    allow-query { any; };
    allow-transfer { none; };

    // Публичные зоны с публичными IP
    zone "corp.local" {
        type master;
        file "/var/lib/bind/external/db.corp.local";
    };

    // RPZ для блокировки вредоносных доменов
    zone "rpz.example.com" {
        type master;
        file "/var/lib/bind/external/db.rpz.example.com";
        allow-query { any; };
    };
};
```

**Зоны:**

```dns
; /var/lib/bind/internal/db.corp.local
$TTL 300
@   IN  SOA ns1.corp.local. admin.corp.local. (2026091501 3600 900 1209600 300)
    IN  NS  ns1.corp.local.
    IN  NS  ns2.corp.local.
ns1 IN  A   10.0.0.1
ns2 IN  A   10.0.0.2
    IN  A   10.0.1.10       ; Внутренний IP
www IN  A   10.0.1.20       ; Внутренний IP
mail IN A   10.0.1.30

; /var/lib/bind/external/db.corp.local
$TTL 300
@   IN  SOA ns1.corp.local. admin.corp.local. (2026091501 3600 900 1209600 300)
    IN  NS  ns1.ext.example.com.
    IN  NS  ns2.ext.example.com.
ns1 IN  A   203.0.113.1     ; Публичный IP
ns2 IN  A   203.0.113.2     ; Публичный IP
    IN  A   203.0.113.10    ; Публичный IP (NAT)
www IN  A   203.0.113.10    ; Публичный IP (NAT)
mail IN A   203.0.113.20    ; Публичный IP (NAT)
```

### 20. Troubleshooting для Views, CatZ и RPZ

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Внешний клиент получает внутренний IP** | View не покрывает IP клиента (нет `match-clients`), порядок Views нарушен. | Проверьте порядок `view` (первый совпадающий wins), добавьте IP в ACL. |
| **CatZ: вторичные зоны не создаются** | Serial каталога не увеличен, TTL не истёк, `allow-transfer` не включает IP. | `rndc reload catalog.example`, проверка `journalctl -u named | grep catalog`. |
| **RPZ не применяется** | `recursion no` без RPZ-правил, опечатка в имени зоны RPZ, ACL запрещает запросы. | Проверьте `response-policy { zone "..."; }`, `allow-query { any; }` для RPZ-зоны. |
| **DNSSEC: SERVFAIL после роллинга KSK** | DS-запись в родительской зоне не обновлена, старый KSK удалён раньше времени. | Проверьте `dig parent DS +dnssec`, верните старый KSK или добавьте NTA. |
| **ECS: клиент получает неправильный регион** | ECS-префикс слишком широкий или узкий, сервер не поддерживает ECS. | Настройте `ecs-prefix` на авторитативном сервере, проверьте `dig +subnet`. |
| **QNAME Minimization: SERVFAIL на легитимных доменах** | Несовместимый authoritative сервер (не поддерживает RFC 9156). | Используйте `qname-minimization relaxed` или исключите проблемные зоны через `minimal-responses no`. |
| **RRL: легитимные клиенты получают slowed ответы** | Слишком низкий `responses-per-second` для корпоративной сети. | Увеличьте лимит для доверенных ACL или отключите RRL для внутренних клиентов. |

---

## Дополнительная информация

### Связанные разделы (BIND)

*   **[DoT/DoH сервер](./dot-doh-server.md)** — настройка DNS over TLS и DNS over HTTPS на стороне сервера.
*   **[Логирование и мониторинг](./logging-and-monitoring.md)** — настройка логов, Prometheus-метрик, Grafana-дашбордов.
*   **[Автоматизация (IaC)](./automation-iac.md)** — управление BIND через Ansible.
*   **[TSIG-ключи](./tsig-key-management.md)** — ротация ключей и автоматизация.
*   **[Реагирование на инциденты](./incident-response.md)** — live-отладка и postmortem.
*   **[Troubleshooting](./troubleshooting.md)** — диагностика ошибок BIND.

### Связанные разделы (DNS)

*   **[Протокол DNS](../../../../Networking/Protocols/DNS/dns.md)** — общая архитектура и порты.
*   **[Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md)** — DNSSEC, DoH/DoT/DoQ, TSIG, DANE.
*   **[Мониторинг DNS](../../../../Networking/Protocols/DNS/dns_monitoring.md)** — SLA, Prometheus, Grafana.
*   **[Балансировка через DNS](../../../../Networking/Protocols/DNS/dns_load_balancing.md)** — round-robin, weighted, GSLB.
*   **[Диагностика DNS](../../../Diagnostics/Networking/dns/overview.md)** — инструменты `dig`, `delv`, `tcpdump`.

*   **Производительность:** BIND 9.20+ использует оптимизированные структуры **QP-trie** для обработки миллионов записей при минимальном потреблении ресурсов.
*   **Диагностика:** Используйте `named-checkconf` перед каждым применением изменений. Подробнее в разделе **[Диагностика BIND](./troubleshooting.md)**.
*   **Безопасность:** Рекомендуется комбинировать Views с **[DNSSEC](../../../../Networking/Protocols/DNS/dns_security.md)** для защиты от подмены ответов.
*   **Best Practices:**
    *   Используйте `dnssec-policy` вместо ручного управления ключами (BIND 9.18+).
    *   Включайте `qname-minimization strict` на всех рекурсивных серверах.
    *   Настраивайте RRL на всех публичных авторитативных серверах.
    *   Используйте Catalog Zones при управлении более 10 зонами.
    *   Комбинируйте Views с CatZ для изоляции сред (Dev/Prod).
    *   Используйте `inline-signing yes` с `dnssec-policy` для автоматизации DNSSEC.
    *   Включайте Statistics Channel (порт 8053) для интеграции с мониторингом (Prometheus exporter).
    *   Для IPv6-only инфраструктуры используйте DNS64/NAT64 вместо двойного стека.
    *   Включайте `tcp-fast-open` для снижения задержки на высоконагруженных резолверах.
    *   Настраивайте RPZ с threat intelligence feed для блокировки вредоносных доменов.
    *   Используйте HSM или offline-машину для хранения KSK в критичных зонах.
    *   Автоматизируйте управление BIND через Ansible (см. [Автоматизация](./automation-iac.md)).
