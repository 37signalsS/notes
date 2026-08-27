# Продвинутые сценарии использования DNS

## Определения

**Anycast DNS** — технология сетевой маршрутизации, позволяющая нескольким географически распределённым серверам использовать один и тот же IP-адрес. Сеть (через протокол BGP) автоматически направляет запрос пользователя к топологически ближайшему узлу. Anycast работает на уровне **L3 (Сетевой уровень)**. Первоисточник по BGP: [Протокол BGP](../../Protocols/bgp.md).

**Geo-DNS (Географический DNS / Geo Steering)** — механизм на уровне DNS-сервера, который возвращает разные IP-адреса для одного имени на основе IP-адреса клиента (или его резолвера), обеспечивая региональную балансировку. Работает на уровне **L7 (Прикладной уровень)** и логики ответов DNS-сервера.

**GSLB (Global Server Load Balancing)** — глобальная балансировка нагрузки, использующая DNS для распределения трафика между несколькими дата-центрами (ЦОД) с учётом их доступности, загрузки и близости к пользователю.

**ECS (EDNS Client Subnet, RFC 7871)** — расширение протокола DNS, позволяющее рекурсивному резолверу передавать часть IP-адреса клиента (подсеть) авторитативному серверу для более точного Geo-позиционирования.

**Split-horizon DNS (Split DNS)** — конфигурация, при которой DNS-сервер отдаёт разные ответы для внутренних и внешних клиентов (например, локальный IP для сотрудников и публичный IP для интернета). В BIND реализуется через **Views**. Подробнее: [BIND: Расширенные возможности](../../../Linux/Networking/Services/BIND/advanced_topics.md).

**Extended DNS Errors (EDE, RFC 8914)** — механизм возврата детальных кодов ошибок (например, ошибки валидации DNSSEC или блокировки по цензурным соображениям) в секции OPT DNS-ответа.

**SVCB / HTTPS (RFC 9460)** — типы ресурсных записей, позволяющие объединять параметры подключения (порт, протокол h3, ключи шифрования) и обеспечивать CNAME-подобную функциональность на уровне Apex-домена.

**RPZ (Response Policy Zones)** — механизм «DNS Firewall», позволяющий изменять ответы DNS-сервера или блокировать запросы к определённым доменам на основе локальных или внешних списков угроз. Подробнее: [BIND: RPZ](../../../Linux/Networking/Services/BIND/advanced_topics.md).

## Базовые концепции

### Anycast: Сетевая балансировка и безопасность

*   **Механизм:** Все узлы в Anycast-группе анонсируют один и тот же IP-префикс. Интернет-маршрутизаторы выбирают путь с минимальным количеством переходов (AS Path).
*   **Преимущества:**
    *   **Снижение задержки (Latency):** Пакеты идут по кратчайшему пути.
    *   **Отказоустойчивость:** Если узел падает, BGP-анонс прекращается, и трафик мгновенно переключается на следующий ближайший узел.
    *   **DDoS-устойчивость:** Атака локализуется в конкретном регионе, не затрагивая глобальную доступность сервиса.
*   **Риски:** **BGP Hijacking**. Если злоумышленник анонсирует ваш IP-префикс с более коротким AS Path, часть трафика уйдет на его серверы. Защита: RPKI (ROA/ROV) и мониторинг BGP-анонсов. Подробнее: [Безопасность BGP](../../Protocols/bgp.md#безопасность-bgp-rpki-roa-и-aspa).

#### Мониторинг BGP-анонсов

```bash
# Проверка текущих BGP-анонсов вашего префикса (через RIPE RIS)
curl -s "https://stat.ripe.net/data/bgplay/data.json?resource=192.0.2.0/24&start=-2h" | python3 -m json.tool | grep -A2 "path"

# Мониторинг через BGPStream (рекурсивное обновление)
bgpstream -B -p 192.0.2.0/24 -t csv 2>/dev/null | head -5

# Проверка RPKI-статуса вашего префикса (Krill / Routinator)
dig 2.0.192.in-addr.arpa TXT +short
# → Ответ с RPKI-статусом (Valid/Invalid/NotFound)
```

### Geo-DNS и GSLB: Прикладная балансировка

В отличие от Anycast, Geo-DNS работает на уровне логики ответов DNS-сервера.
*   **Механизм:** Сервер сопоставляет IP клиента с Geo-IP базой и выбирает лучший IP-адрес из пула.
*   **Multi-Cloud GSLB:** Позволяет строить гибридные схемы (On-premise + Cloud). DNS-сервер выполняет роль интеллектуального маршрутизатора, который может перенаправить трафик в облако, если локальный ЦОД перегружен.
*   **Health Checks:** GSLB-решения интегрируют проверки состояния. Если эндпоинт в Европе не отвечает на HTTP-запрос, DNS-сервер временно исключает его IP из ответов.

#### Типы Health Check для GSLB

| Тип проверки | Описание | Интервал | Пример |
| :--- | :--- | :--- | :--- |
| **ICMP (Ping)** | Проверка доступности хоста | 10–30 сек | `ping -c 3 192.0.2.10` |
| **TCP Connect** | Проверка доступности порта | 15–60 сек | `nc -zv 192.0.2.10 443` |
| **HTTP(S)** | Проверка HTTP-кода ответа | 30–120 сек | `curl -sf -o /dev/null -w "%{http_code}" http://192.0.2.10/health` |
| **DNS** | Проверка ответа DNS-сервера | 60–300 сек | `dig @192.0.2.10 example.com A +short` |

#### Пример GSLB-конфигурации (nsupdate с Health Check)

```bash
#!/bin/bash
# health-check.sh — проверка здоровья эндпоинта и обновление DNS
ENDPOINT="192.0.2.10"
HEALTH_URL="http://${ENDPOINT}/health"
DNS_NAME="api.example.com"
TTL=60

HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 5 "$HEALTH_URL" 2>/dev/null)

if [ "$HTTP_CODE" -ne 200 ]; then
    echo "Health check failed (HTTP $HTTP_CODE), removing $ENDPOINT from DNS"
    nsupdate -l <<EOF 2>/dev/null
server 127.0.0.1
zone example.com
update delete $DNS_NAME A $ENDPOINT
send
EOF
else
    echo "Health check passed, ensuring $ENDPOINT is in DNS"
    nsupdate -l <<EOF 2>/dev/null
server 127.0.0.1
zone example.com
update delete $DNS_NAME A $ENDPOINT
update add $DNS_NAME $TTL A $ENDPOINT
send
EOF
fi
```

### EDNS Client Subnet (ECS) и современные альтернативы

ECS решает проблему «неправильной» геолокации при использовании публичных резолверов (Google DNS, Cloudflare).

#### Анализ конфиденциальности ECS

| Маска | Раскрываемые данные | Риск | Рекомендация |
| :--- | :--- | :--- | :--- |
| **/32 (IPv4)** | Полный IP клиента | Критический — полная деанонимизация | Никогда не используйте |
| **/24** | Подсеть (/24 = 256 адресов) | Средний — примерная геолокация | Минимально допустимо |
| **/20** | Регион | Низкий | Рекомендуется для CDN |
| **/0** | Ничего (пустой подсеть) | Отсутствует | Идеально для приватности |

*   **Oblivious DNS (ODoH):** Полное сокрытие IP клиента через прокси (RFC 9250). Клиент → Прокси → Resolver → Authoritative. Ни один участник не видит и клиента, и запрос одновременно.
*   **Anycast CDN:** Вместо Geo-DNS на стороне клиента используется Anycast-IP CDN-провайдера, что делает ECS ненужным. Подробнее: [CDN — Обзор](../../../CDN/cdn_overview.md).

### Split-horizon и облачная изоляция

В современных средах Split-horizon эволюционировал в **Private DNS Zones**:
*   **Cloud Native:** AWS Route53 Private Hosted Zones или Azure Private DNS. Позволяют использовать одни и те же имена внутри VPC (с приватными IP) и снаружи (с публичными IP).
*   **Service Mesh:** Локальное перехватывание запросов (Sidecar DNS) для реализации Service Discovery без обращения к центральному серверу. См. [DNS в Kubernetes](../../../Kubernetes/Networking/dns_deep_dive.md).
*   **RFC 9704 (2025):** современные подходы к реализации Split-horizon DNS, минимизирующие риски утечки внутренней структуры сети наружу.

### Extended DNS Errors (EDE): Полная таблица кодов

| Код | Название | Описание | Пример использования |
| :--- | :--- | :--- | :--- |
| 0 | Other | Неопределённая ошибка | Баг сервера |
| 1 | Unsupported DNSKEY Algorithm | Неподдерживаемый алгоритм DNSSEC | Устаревший DS-записи |
| 2 | Unsupported DS Digest Type | Неподдерживаемый тип хеша DS | Рассинхрон DNSSEC-ключей |
| 3 | Stale Answer | Устаревший ответ из кэша | DNSSEC не прошёл, но данных в кэше нет |
| 4 | Forged Answer | Подделанный ответ | RPZ перехватил запрос |
| 5 | DNSSEC Bogus | Поддельная DNSSEC-подпись | Атака на DNSSEC |
| 6 | DNSSEC Indeterminate | Неопределённый статус DNSSEC | Нет DS-записи для родительской зоны |
| 7 | DNSSEC Bogus (NXDOMAIN) | DNSSEC bogus для NXDOMAIN | Запрос к несуществующему домену |
| 8 | DNSSEC Bogus (NODATA) | DNSSEC bogus для NODATA | Запрос к существующему домену без нужного типа |
| 9 | DNSSEC Bogus (Not Authoritative) | DNSSEC bogus для неавторитетного ответа | Цепочка подписей не проходит |
| 10 | DNSSEC Bogus (Not Zone) | DNSSEC bogus для имени вне зоны | Имя выходит за пределы делегирования |
| 11 | DNSSEC Bogus (Signature Expired) | Срок действия подписи истёк | RRSIG просрочен |
| 12 | DNSSEC Bogus (Signature Not Yet Valid) | Подпись ещё не действительна | RRSIG ещё не начал действовать |
| 13 | DNSSEC Bogus (DS Key Not Found) | Ключ DS не найден | Отсутствует делегирование DNSSEC |
| 14 | DNSSEC Bogus (RRSIG Not Found) | Подпись RRSIG не найдена | Зона не подписана, а должна быть |
| 15 | DNSSEC Bogus (No Zone Key Bit Set) | Бит Zone Key не установлен | DNSKEY без флага ZSK/KSK |
| 16 | DNSSEC Bogus (NSEC Missing) | NSEC/NSEC3 отсутствует | Нет доказательства отсутствия |
| 17 | Cached Stale | Устаревший кэшированный ответ | DNS-сервер отдал stale вместо FAIL |
| 18 | Blocked | Заблокировано политикой | RPZ, ACL или родительский контроль |
| 19 | Censored | Заблокировано цензурой | Государственная фильтрация DNS |
| 20 | Filtered | Заблокировано фильтром | Корпоративный фильтр (например, Webroot) |
| 21 | Prohibited | Запрещено политикой | Запрос запрещён администратором |
| 22-49 | Reserved | Зарезервировано | RFC 8914 |
| 50 | Not Ready | Сервис не готов | DNS-сервер в процессе загрузки |
| 51 | Blocked (Query Type) | Заблокирован тип запроса | Запрет ANY, DNSKEY и т.д. |
| 52 | Blocked (EDNS Policy) | Заблокировано политикой EDNS | ECS запрещён или DPI |
| 53 | Stale (SOA) | Устаревший ответ по SOA | Сервер вернул SOA вместо FAIL |
| 256-65535 | Private Use | Приватные коды | Используются вендорами (Cloudflare: 32768–65279) |

### Catalog Zones (RFC 9432) и XoT

Технология для автоматизации масштабирования DNS-инфраструктуры.
*   **Механизм:** Master-сервер хранит список всех зон в специальной «каталожной» зоне. Вторичные серверы подписываются на изменения этой зоны и автоматически создают/удаляют подчиненные зоны.
*   **Безопасность (XoT, RFC 9103):** Передача зон (AXFR/IXFR) через TLS (DNS over TLS) критична для Catalog Zones, так как утечка списка всех доменов компании является угрозой безопасности.
*   **Связь с Views:** ВBIND можно комбинировать CatZ с Views для изоляции сред (Dev/Prod). Подробнее: [BIND: Views](../../../Linux/Networking/Services/BIND/advanced_topics.md#настройка-split-horizon-dns-views).

### Оптимизация через SVCB и HTTPS записи

Записи **SVCB (Service Binding)** и **HTTPS** решают фундаментальные проблемы старого DNS:
*   **CNAME at Apex:** Позволяют «псевдо-алиасить» корень домена (example.com) на CDN без использования нестандартных записей типа ALIAS/ANAME.
*   **Ускорение Handshake:** Клиент узнает о поддержке HTTP/3 (h3) и параметрах ECH (Encrypted Client Hello) прямо из DNS-ответа, экономя время на RTT при установке соединения.
*   **Параметры:** ALPN (h2, h3), ECH, IPv4Hint, IPv6Hint, port, no-default-alpn. Подробнее: [Типы DNS-записей](./dns_records.md).

#### SVCB: Сравнение параметров

| Параметр | RFC | Описание | Пример |
| :--- | :--- | :--- | :--- |
| **alpn** | 9460 | Поддерживаемые протоколы | `alpn="h3,h2"` |
| **port** | 9460 | Порт подключения | `port="8443"` |
| **ipv4hint** | 9460 | IPv4-адреса для подключения | `ipv4hint="192.0.2.10,192.0.2.11"` |
| **ipv6hint** | 9460 | IPv6-адреса для подключения | `ipv6hint="2001:db8::10"` |
| **ech** | 9460 | Encrypted Client Hello (HTTPS-records) | `ech="AEX+DQBBq..."` |
| **mandatory** | 9460 | Обязательные параметры | `mandatory="alpn"` |
| **no-default-alpn** | 9460 | Отключение ALPN по умолчанию | Для не-HTTP протоколов |

## Практические сценарии

### 1. Диагностика ошибок через Extended DNS Errors (EDE)

```bash
# Запрос к серверу с поддержкой EDE
dig @9.9.9.9 broken-dnssec.example.com +nsid

# В ответе ищите секцию OPT с кодом:
# ; EDE: 6 (DNSSEC Bogus): (validation failure)
# ; EDE: 17 (Cached Stale): (stale answer served)

# Полный вывод EDE через delv (DNSSEC-валидатор)
delv @9.9.9.9 example.com A +rtrace 2>&1 | grep "EDE"

# Проверка EDE на разных серверах для сравнения
for resolver in 1.1.1.1 8.8.8.8 9.9.9.9; do
    echo "=== $resolver ==="
    dig @$resolver blocked-domain.example.com +nsid +short
done
```

### 2. Настройка SVCB/HTTPS для HTTP/3 и ECH

```dns
; Корневая запись: HTTP/3 + ECH
@           IN  HTTPS   1 . alpn="h3,h2" ipv4hint="192.0.2.10" ipv6hint="2001:db8::10" ech="AEX+DQBBqQ..."

; С альтернативным портом
api         IN  HTTPS   1 . alpn="h2" port="8443" ipv4hint="192.0.2.20"

; С привязкой к конкретному CDN-узлу (вместо CNAME)
cdn         IN  HTTPS   1 cdn.provider.net. alpn="h3,h2" ipv4hint="1.2.3.4"

; Приоритеты: 1 = основной, 2 = запасной
@           IN  HTTPS   1 . alpn="h3,h2" ipv4hint="192.0.2.10"
@           IN  HTTPS   2 . alpn="h2" ipv4hint="192.0.2.20"

; Для SVCB (не-HTTP): SIP-сервис
_sip._tcp   IN  SVCB    1 sip.example.com. port="5060"
```

### 3. Проверка SVCB через dig

```bash
# Полный вывод SVCB/HTTPS с параметрами
dig example.com HTTPS +noall +answer +comments
# → example.com.  300  IN  HTTPS  1  .  alpn="h3,h2" ipv4hint="192.0.2.10" ech="AEX+..."

# Только параметры (без заголовков)
dig example.com HTTPS +short
# → 1 . alpn="h3,h2" ipv4hint="192.0.2.10"

# Проверка SVCB для не-HTTP сервисов
dig _sip._tcp.example.com SVCB +short
# → 1 sip.example.com. port="5060"

# Сравнение ответов разных резолверов
for r in 1.1.1.1 8.8.8.8; do
    echo "=== $r ==="
    dig @$r example.com HTTPS +short
done
```

### 4. Отладка Catalog Zones (BIND)

```bash
# Проверка содержимого каталожной зоны на вторичном сервере
sudo rndc dumpdb -zones
# Ищите записи в зоне catalog.example, указывающие на добавленные зоны

# Просмотр зон, управляемых CatZ
sudo rndc zonestatus catalog.example
# → Categories: 1
# → Members:    3
# → Zones:      example.com, api.example.com, dev.example.com

# Принудительное обновление каталога
sudo rndc reload catalog.example

# Проверка, что вторичные зоны созданы автоматически
sudo rndc zonestatus example.com | grep "catalog-zone"
# → catalog-zone: catalog.example
```

### 5. Динамический Failover через GSLB

```bash
# Симуляция проверки здоровья (Health Check)
curl -sf -o /dev/null -w "%{http_code}" http://region-a.api.example.com/health

# Если ответ != 200, обновляем DNS:
nsupdate -k key.file <<EOF
server 127.0.0.1
zone example.com
update delete api.example.com A 10.1.1.1
update add api.example.com 60 A 10.2.2.2
send
EOF

# Проверка текущего состояния DNS
dig api.example.com +short
# → 10.2.2.2

# Логирование GSLB-событий
logger -t gslb "Failed health check for region-a (10.1.1.1), switched to region-b (10.2.2.2)"
```

### 6. Диагностика Anycast

```bash
# Traceroute до Anycast-сервера (покажет ближайший узел)
traceroute -n 192.0.2.1
# → Первый hop — ближайший Anycast-узел

# Сравнение задержки до разных Anycast-узлов
for ip in 192.0.2.1 192.0.2.2 192.0.2.3; do
    echo "=== $ip ==="
    ping -c 3 $ip | tail -1
done

# Проверка AS Path до Anycast-префикса (BGPlay)
curl -s "https://stat.ripe.net/data/bgplay/data.json?resource=192.0.2.0/24" | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print('AS Path:', d['data']['tables'][0]['rib_entries'][0]['path'])" 2>/dev/null

# Проверка, что ответ пришёл из ближайшего узла
dig @192.0.2.1 whoami.example.com TXT +short
# → "server=ams-01"  (AMS = Amsterdam数据中心)
```

### 7. Диагностика ECS

```bash
# Проверка, передаёт ли резолвер ECS
dig @8.8.8.8 cdn.example.com A +subnet=1.2.3.0/24 +short

# Сравнение ответов с разными ECS
echo "=== Без ECS ==="
dig @8.8.8.8 cdn.example.com A +short
# → 198.51.100.10 (US)

echo "=== С ECS из Европы ==="
dig @8.8.8.8 cdn.example.com A +subnet=185.12.64.0/24 +short
# → 198.51.100.20 (EU)

echo "=== С ECS из Азии ==="
dig @8.8.8.8 cdn.example.com A +subnet=103.1.2.0/24 +short
# → 198.51.100.30 (APAC)

# Проверка, какой resolver используется ( authoritative видит )
# На авторитативном сервере проверьте query log
grep "ecs" /var/log/named/queries.log
```

### 8. Конфигурация RPZ (Response Policy Zones)

```dns
; RPZ-зона (блокировка вредоносных доменов)
rpz.example.com.   IN  SOA  ns1.example.com. admin.example.com. (
                    2025072701  ; Serial
                    3600        ; Refresh
                    900         ; Retry
                    1209600     ; Expire
                    3600        ; Negative TTL
)

; Блокировка конкретного домена
malware.com.            IN  A     127.0.0.1
*.malware.com.          IN  A     127.0.0.1

; Перенаправление на страницу блокировки
phishing.example.com.   IN  CNAME block.example.com.
block.example.com.      IN  A     192.0.2.99

; PASSTHRU (разрешить, несмотря на политику)
trusted-malware.example.com.  IN  A  192.0.2.100

; NODATA (вернуть пустой ответ вместо NXDOMAIN)
ads.example.com.        IN  A     0.0.0.0
```

```bash
# Проверка RPZ через dig
dig @localhost blocked-malware.com +short
# → 127.0.0.1  (RPZ перехватил)

# Проверка EDE при блокировке
dig @localhost blocked-malware.com +nsid +short
# → ; EDE: 18 (Blocked): (rpz: triggered)
```

**Интеграция RPZ в named.conf (BIND):**

```dns
// named.conf.local — объявление RPZ-зоны
zone "rpz.example.com" {
    type master;
    file "/etc/bind/zones/rpz.example.com.db";
    allow-query { any; };
    allow-transfer { none; };
};
```

```dns
// named.conf.options — включение response-policy
options {
    // ... другие опции ...
    recursion yes;
    allow-query { any; };

    // Подключение RPZ-политики
    response-policy { zone "rpz.example.com"; };
};
```

```bash
# Валидация конфигурации
sudo named-checkconf
# → no errors

# Применение
sudo rndc reload

# Проверка, что RPZ активна
dig @localhost malware.com +short
# → 127.0.0.1  (RPZ заблокировал)
```

## Типичные ошибки и их решение

### Anycast: разная задержка в разных регионах

**Симптом:** В Европе задержка 5ms, в Азии — 200ms.

**Причина:** Anycast-узлы распределены неравномерно; Азия не имеет локального PoP.

**Решение:** добавьте Anycast-узлы в недостающие регионы или используйте Anycast + GeoDNS: Anycast для отказоустойчивости, GeoDNS для точного распределения.

### GeoDNS: клиент за VPN получает неправильный ответ

**Симптом:** Пользователь VPN-клиента подключён к серверу в другом регионе; GeoDNS возвращает IP этого региона, а не пользователя.

**Причина:** GeoDNS определяет геолокацию по IP резолвера, а не клиента. VPN-резолвер может находиться в другом регионе.

**Решение:** использовать ECS (RFC 7871) для передачи подсети клиента, или перейти на Anycast CDN.

### ECS: конфликт с приватностью

**Симптом:** Корпоративный резолвер не поддерживает ECS; пользователи за пределами офиса получают неправильные ответы.

**Причина:** Некоторые резолверы (Quad9) по умолчанию не передают ECS из соображений приватности.

**Решение:** использовать собственный резолвер с ECS или настроить CDN на Anycast (без ECS).

### SVCB/HTTPS: клиент не поддерживает RFC 9460

**Симптом:** Старые клиенты (Windows 10, браузеры < 2023) игнорируют HTTPS-записи.

**Причина:** SVCB/HTTPS — новый стандарт; старые клиенты не распознают этот тип записи.

**Решение:** оставить A/AAAA-записи как fallback. HTTPS-записи обрабатываются только новыми клиентами; старые используют A/AAAA.

### Catalog Zones: вторичные зоны не создаются

**Симптом:** После добавления зоны в каталог она не появляется на вторичном сервере.

**Причины:**
1. **Serial не увеличен** — каталог не обновился.
2. **TTL каталога ещё не истёк** — вторичный сервер ещё не перечитал каталог.
3. **Нет доступа** — `allow-transfer` не включает IP вторичного сервера.

**Решение:**
```bash
# Увеличить Serial и перезагрузить каталог
sudo rndc reload catalog.example
# Дождаться истечения TTL каталога (обычно 60–300 сек)
# Проверить логи
journalctl -u named -n 50 | grep "catalog"
```

### RPZ: ложные срабатывания

**Симптом:** Легитимный домен заблокирован RPZ.

**Причина:** RPZ-запись конфликтует с реальным доменом (например, `example.com` заблокирован, а сайт используется в корпоративной сети).

**Решение:** добавить PASSTHRU-запись для разрешённых доменов:
```dns
trusted.example.com.    IN  A     192.0.2.100  ; PASSTHRU
```

## Лучшие практики

*   **Anycast + GeoDNS:** используйте комбинацию для отказоустойчивости + точного распределения. Anycast даёт отказоустойчивость, GeoDNS — географическую точность.
*   **ECS:** всегда используйте широкую маску (/20–/24), никогда /32. Рассмотрите ODoH (RFC 9250) для максимальной приватности.
*   **SVCB/HTTPS:** оставляйте A/AAAA как fallback для старых клиентов. Используйте `mandatory="alpn"` для гарантии поддержки HTTP/3.
*   **RPZ:** комбинируйте с внешними списками угроз (SURBL, Spamhaus DBL) и периодически проверяйте ложные срабатывания. Подробнее: [BIND: RPZ](../../../Linux/Networking/Services/BIND/advanced_topics.md).
*   **Catalog Zones:** используйте для управления >10 зон. Для менее чем 10 зон ручное управление проще.
*   **XoT (RFC 9103):** всегда используйте TLS для трансферов зон, особенно с Catalog Zones.
*   **BGP Hijacking:** включайте RPKI (ROA/ROV) на маршрутизаторах. Подробнее: [Безопасность BGP](../../Protocols/bgp.md#безопасность-bgp-rpki-roa-и-aspa).
*   **Health Checks:** настраивайте GSLB с интервалом 30–60 сек; комбинируйте ICMP + HTTP.

## Дополнительная информация

*   **RFC 7871:** Client Subnet in DNS Queries (ECS).
*   **RFC 8914:** Extended DNS Errors (EDE).
*   **RFC 9103:** DNS Zone Transfer over TLS (XoT).
*   **RFC 9250:** Oblivious DNS over HTTPS (ODoH).
*   **RFC 9432:** DNS Catalog Zones.
*   **RFC 9460:** Service Binding and Parameter Priority Settings in DNS (SVCB/HTTPS).
*   **RFC 9660:** Dry-Run DNSSEC (Метод безопасного тестирования подписей).
*   **RFC 9704:** Split-horizon DNS Best Practices (2025).
*   [Протокол DNS](./dns.md) — транспорт и архитектура резолвинга.
*   [Типы DNS-записей](./dns_records.md) — справочник всех RR.
*   [Безопасность DNS](./dns_security.md) — DNSSEC, DoH, DoT, DoQ.
*   [Зоны DNS и SOA](./dns_zones.md) — управление структурой зон.
*   [DNS в Kubernetes](../../../Kubernetes/Networking/dns_deep_dive.md) — специфика Service Discovery в кластерах.
*   [CDN — Обзор](../../../CDN/cdn_overview.md) — архитектура CDN и Anycast.
*   [Протокол BGP](../../Protocols/bgp.md) — Anycast, RPKI, безопасность.
*   [BIND: Расширенные возможности](../../../Linux/Networking/Services/BIND/advanced_topics.md) — Views, ACL, RPZ, CatZ в BIND.
*   [Балансировка нагрузки через DNS](./dns_load_balancing.md) — round-robin, weighted, health-check failover.
*   [Unbound — рекурсивный резолвер](./unbound_resolver.md) — альтернатива BIND для рекурсивного резолвинга.
