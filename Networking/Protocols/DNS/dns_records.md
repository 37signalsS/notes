# Типы DNS-записей

## Определения

**Ресурсная запись (Resource Record, RR)** — атомарная единица данных в системе DNS, определяющая конкретный атрибут домена. Формат записи строго регламентирован (RFC 1035).

*   **NAME:** доменное имя, к которому относится запись.
*   **TYPE:** двухбайтовое поле, определяющее формат данных (A, MX, TXT и др.).
*   **CLASS:** класс сети (почти всегда `IN` — Internet).
*   **TTL (Time To Live):** время в секундах, в течение которого запись может храниться в кэше резолверов.
*   **RDATA:** данные, специфичные для конкретного типа записи (например, IP-адрес или имя хоста).

**Приклеенные записи (Glue Records)** — A или AAAA-записи, предоставляемые вместе с NS-записью для предотвращения циклической зависимости. Необходимы, если сервер имён (NS) находится внутри делегируемой зоны (например, `ns1.example.com` для зоны `example.com`). Без них резолвер не смог бы найти IP-адрес NS-сервера, чтобы спросить у него этот же IP. Глубже: [Зоны DNS и SOA](./dns_zones.md#делегирование-и-glue-записи).

**Wildcard-записи (Символы подстановки)** — записи, использующие символ `*` (например, `*.example.com`). Позволяют отвечать на запросы для любых несуществующих поддоменов одним набором данных. Символ `*` работает только как крайний левый элемент имени. *Важно:* wildcard работает **только для несуществующих** имён — если для `sub.example.com` есть прямая A-запись, wildcard `*.example.com` на неё не отвечает.

**Canonical Name (CNAME)** — псевдоним, указывающий на другое каноническое имя. Запись CNAME **исключает** наличие любых других записей для того же имени (RFC 1034 §3.6.2). Это фундаментальное ограничение: корень зоны (Apex, например, `example.com`) обязан содержать NS и SOA, поэтому CNAME на Apex невозможен.

**Alias / ANAME** — нестандартная запись, разрабатываемая провайдерами (Cloudflare, AWS Route53, DNSimple) для решения проблемы Apex CNAME. Провайдер выполняет CNAME-follow на стороне своего сервера и отдаёт клиенту итоговую A/AAAA-запись, что позволяет «приклеить» Apex к CDN без нарушения RFC.

## Базовые концепции

### Основные типы записей

| Тип | Назначение | Технические нюансы |
| :--- | :--- | :--- |
| **A** | IPv4-адрес (32 бита) | Связывает имя с 32-битным адресом. Может быть несколько записей для одного имени (Round Robin DNS для балансировки L7). |
| **AAAA** | IPv6-адрес (128 бит) | Связывает имя с 128-битным адресом. Используется параллельно с A (Dual Stack). Современные резолверы отдают приоритет IPv6 (Алгоритм Happy Eyeballs, RFC 8305). |
| **CNAME** | Псевдоним (Alias) | Указывает на другое каноническое имя. **Apex Restriction:** не может быть установлен для корня домена. Причина: если у имени есть CNAME, у него не может быть никаких других записей. Но корень зоны (Apex) обязан содержать NS и SOA. |
| **ALIAS / ANAME** | Псевдо-запись (нестандартная) | Внутренний механизм провайдеров. Провайдер резолвит CNAME на стороне и отдаёт A/AAAA. Решает проблему Apex, не нарушая RFC. Подробнее: [Продвинутые сценарии](./dns_advanced.md). |
| **MX** | Почтовый сервер | Формат: `[priority] [hostname]`. Приоритет от 0 до 65535, чем меньше число, тем выше приоритет. Hostname должен указывать на A/AAAA-запись; использование CNAME в MX запрещено RFC 2181. |
| **NS** | Сервер имён | Указывает авторитетные серверы для зоны. Делегирование подзоны происходит через NS-записи в родительской зоне. |
| **PTR** | Указатель (Pointer) | Обратное разрешение IP → FQDN. Работает в специальных зонах `in-addr.arpa` (IPv4) и `ip6.arpa` (IPv6). Критично для проверок почтовыми серверами. Подробнее: [Обратная зона](../../../Linux/Networking/Services/BIND/reverse_zone_configuration.md). |
| **SOA** | Начало зоны | Метаданные о зоне (Serial, Refresh, Retry, Expire, Minimum/Negative Cache TTL). Подробнее: [Зоны DNS и SOA](./dns_zones.md). |
| **TXT** | Текстовые данные | Произвольные данные. Сегодня的主要 роль — SPF, DKIM, DMARC, верификация доменов (ACME/Let's Encrypt, Google Search Console). |

### Записи для сервисов и протоколов

*   **SRV (Service Record):** определяет хост и порт для служб (LDAP, SIP, XMPP, Consul, Kubernetes).
    *   Формат: `_service._proto.name TTL IN SRV priority weight port target`.
    *   `priority`: как в MX (ниже = лучше).
    *   `weight`: пропорциональное распределение нагрузки между серверами с одинаковым приоритетом.
    *   *Пример:* `_ldap._tcp.dc._msdcs.example.com IN SRV 0 0 389 dc1.example.com.`
*   **NAPTR (Naming Authority Pointer, RFC 3403):** трансформация имён. Используется в ENUM (T telephone E164 N numbering, RFC 6116) для преобразования телефонных номеров в SIP-URI. Также применяется в Service Discovery (RFC 3958 — DDDS).
    *   *Пример:* `0.1.0.0.0.9.1.6.4.e164.arpa. IN NAPTR 100 10 "u" "E2U+sip" "!^.*$!sip:info@example.com!" .`
*   **SVCB / HTTPS (RFC 9460):** современные записи для Service Binding и оптимизации HTTPS.
    *   **Параметры:** ALPN (поддержка HTTP/2, HTTP/3), ECH (Encrypted Client Hello), IPv4Hint, IPv6Hint, port.
    *   **CNAME at Apex:** позволяют «псевдо-алиасить» корень домена на CDN без ALIAS/ANAME.
    *   **Ускорение Handshake:** клиент узнает о поддержке HTTP/3 (h3) и параметрах ECH прямо из DNS-ответа, экономя RTT.
    *   Подробнее: [Продвинутые сценарии](./dns_advanced.md).

### Записи безопасности и DNSSEC

*   **CAA (Certification Authority Authorization, RFC 8659):** ограничение списка CA, имеющих право выпускать сертификаты. Защищает от несанкционированного выпуска сертификатов взломанным CA.
    *   Формат: `name IN CAA flags tag "value"`.
    *   Теги: `issue` (разрешённые CA), `issuewild` (для wildcard), `iodef` (отчёт об ошибке).
*   **TLSA (DANE, RFC 6698):** хеш сертификата для проверки через DNSSEC. Позволяет полностью отказаться от публичных CA.
    *   Формат: `_port._proto.name IN TLSA usage selector matching-type cert-data`.
    *   Подробнее: [Безопасность DNS](./dns_security.md).
*   **SSHFP:** отпечаток SSH-ключа сервера. Позволяет клиенту автоматически проверять подлинность сервера при первом подключении.
*   **DNAME (RFC 6672):** псевдоним для целого поддерева имён. В отличие от CNAME, работает для всех имён под указанным доменом.
    *   *Пример:* `example.com. IN DNAME redirect.example.net.` — запрос на `foo.example.com` будет перенаправлен на `foo.redirect.example.net`.
    *   *Важно:* DNAME не конфликтует с NS/SOA родительской зоны (в отличие от CNAME).

### Записи DNSSEC

| Тип | Назначение | Описание |
| :--- | :--- | :--- |
| **DNSKEY** | Публичный ключ | Содержит публичный ключ для проверки подписей RRSIG. Два типа: KSK (Key Signing Key) и ZSK (Zone Signing Key). |
| **DS (Delegation Signer)** | Хеш ключа | Хранится в родительской зоне. Содержит хеш KSK дочерней зоны, создавая «цепочку доверия» (Chain of Trust). |
| **RRSIG** | Цифровая подпись | Электронная подпись данных. Каждая RRSIG-запись ссылается на DNSKEY, которым она была подписана. |
| **NSEC / NSEC3** | Доказательство отсутствия | NSEC — цепочка по порядку алфавита (позволяет перебор имён). NSEC3 — хеширование (защита от zone walking). |

### Типы CNAME: ограничения и альтернативы

| Механизм | Apex CNAME | Одновременно с NS/SOA | Стандарт |
| :--- | :--- | :--- | :--- |
| **CNAME** | Невозможен | Невозможен | RFC 1034 |
| **ALIAS / ANAME** | Возможен | Возможен | Нестандартный |
| **SVCB / HTTPS** | Возможен | Возможен | RFC 9460 |
| **DNAME** | Возможен (для поддерева) | Возможен | RFC 6672 |

### Нюансы TTL и кэширования

*   **TTL (Time To Live):** определяет время нахождения записи в кэше рекурсивного резолвера.
    *   *Низкий TTL (60–300с):* используется для GSLB, балансировки или при подготовке к миграции сервера на новый IP.
    *   *Высокий TTL (3600с+):* для стабильных записей (MX, TXT). Снижает нагрузку на DNS-серверы и ускоряет резолвинг для пользователей.
*   **Negative Caching (RFC 2308):** кэширование отрицательного ответа (NXDOMAIN). Время жизни такого кэша берётся из поля Minimum TTL записи SOA.
*   **Наследование TTL:** при рекурсивном разрешении резолвер использует **минимальный TTL** из всей цепочки (например, если NS-записи TTL = 3600, а A-записи TTL = 300, итоговый TTL будет 300).

### Порядок приоритетов при ответе

Когда для имени существует несколько записей одного типа, резолвер и клиент используют следующую логику:
1.  **A/AAAA (Dual Stack):** Happy Eyeballs (RFC 8305) — одновременный запрос A и AAAA, предпочтение быстрому соединению (обычно IPv6 при равных условиях).
2.  **MX:** выбор по приоритету (число ниже = приоритет выше). При одинаковом приоритете — случайный выбор (Round Robin).
3.  **SRV:** сначала по priority, затем по weight (пропорциональное распределение).
4.  **CNAME:** всегда одна запись (одно имя не может иметь двух CNAME).

## Практические сценарии

### 1. Полный пример зоны с пояснениями

```dns
$TTL 3600                                        ; Глобальный TTL для всех записей
$ORIGIN example.com.                             ; Корневое имя зоны

; === SOA-запись (обязательна) ===
@       IN  SOA     ns1.example.com. admin.example.com. (
                    2025072701  ; Serial (YYYYMMDDNN)
                    3600        ; Refresh (как часто Secondary проверяет обновления)
                    900         ; Retry (повтор при ошибке трансфера)
                    1209600     ; Expire (2 недели — срок жизни данных Secondary)
                    3600        ; Minimum TTL / Negative Cache TTL
)

; === NS-записи (обязательны) ===
@       IN  NS      ns1.example.com.
@       IN  NS      ns2.example.com.

; === Glue Records (IP для NS-серверов) ===
ns1     IN  A       192.0.2.1
ns2     IN  A       192.0.2.2

; === A/AAAA-записи ===
@       IN  A       192.0.2.10            ; Apex (example.com)
@       IN  AAAA    2001:db8::10          ; Dual Stack
www     IN  A       192.0.2.10            ; www → A
mail    IN  A       192.0.2.20            ; Почтовый сервер
db      IN  A       192.0.2.30            ; База данных

; === MX-записи (почта) ===
@       IN  MX      10 mail.example.com.  ; Приоритет 10 (основной)
@       IN  MX      20 mail2.example.com. ; Приоритет 20 (запасной)

; === CNAME (псевдонимы) ===
ftp     IN  CNAME   www.example.com.      ; ftp → www (тот же IP)
cdn     IN  CNAME   d1234.cloudfront.net. ; Внешний CDN

; === SRV-записи (сервисы) ===
_ldap._tcp    IN  SRV  0 0 389 dc1.example.com.
_xmpp._tcp    IN  SRV  10 0 5222 xmpp.example.com.

; === TXT-записи (SPF/DKIM/DMARC) ===
@       IN  TXT     "v=spf1 mx ip4:192.0.2.0/24 -all"
_dmarc  IN  TXT     "v=DMARC1; p=reject; aspf=s; adkim=s; rua=mailto:dmarc@example.com"
selector._domainkey IN TXT (
    "v=DKIM1; h=sha256; k=rsa; p=MIIBIjANBgkqh..."
)

; === CAA (сертификаты) ===
@       IN  CAA     0 issue "letsencrypt.org"
@       IN  CAA     0 issuewild ";"
@       IN  CAA     0 iodef "mailto:security@example.com"

; === Wildcard ===
*.dev   IN  A       192.0.2.100           ; Любой *.dev → 192.0.2.100

; === SVCB (HTTP/3 + ECH) ===
@       IN  HTTPS   1 . alpn="h3,h2" ipv4hint="192.0.2.10"
```

### 2. Настройка CAA для Let's Encrypt

```dns
example.com.  IN  CAA  0 issue "letsencrypt.org"
example.com.  IN  CAA  0 issuewild ";"
example.com.  IN  CAA  0 iodef "mailto:security@example.com"
```

*   `issue "letsencrypt.org"` — только Let's Encrypt может выпускать сертификаты.
*   `issuewild ";"` — запрет на wildcard-сертификаты.
*   `iodef "mailto:..."` — куда слать отчёты о попытках нарушения.

### 3. Полный набор записей безопасности почты (SPF + DKIM + DMARC)

```dns
; SPF: разрешить почтовые серверы из MX и Google Workspace, остальных отклонять
@       IN  TXT     "v=spf1 mx include:_spf.google.com -all"

; DKIM: открытый ключ (строка разбита для читаемости)
default._domainkey IN TXT (
    "v=DKIM1; h=sha256; k=rsa; "
    "p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA..."
)

; DMARC: строгая политика — отклонять письма без подписи, отчёты в Aggregate
_dmarc  IN  TXT     "v=DMARC1; p=reject; aspf=s; adkim=s; rua=mailto:reports@example.com; ruf=mailto:forensics@example.com"

; BIMI (Brand Indicators for Message Identification): логотип бренда в почтовом клиенте
default._bimi IN TXT "v=BIMI1; l=https://example.com/bimi/logo.svg; a=https://example.com/bimi/vmc.pem"
```

### 4. Делегирование поддомена с Glue Records

```dns
; В родительской зоне example.com (управляется регистратором)
sub     IN  NS      ns1.sub.example.com.
sub     IN  NS      ns2.sub.example.com.
ns1.sub IN  A       203.0.113.10          ; Glue Record для NS1
ns2.sub IN  A       203.0.113.11          ; Glue Record для NS2
```

### 5. Подготовка к миграции домена (Снижение TTL)

*   **Действие:** за 24–48 часов до переезда установите TTL для A/AAAA-записей в 60–300 секунд.
*   **Результат:** к моменту переключения кэш у большинства резолверов истечёт, и они запросят новый адрес почти сразу.
*   **После миграции:** верните TTL на 3600+ секунд.

```bash
# Проверка текущего TTL
dig example.com A +ttlunits +short
# → example.com. 300 IN A 192.0.2.10   (TTL = 300 секунд)
```

### 6. Проверка всех типов записей через dig

```bash
# A/AAAA
dig example.com A +short
dig example.com AAAA +short

# MX (почтовые серверы)
dig example.com MX +short
# → 10 mail.example.com.
# → 20 mail2.example.com.

# TXT (SPF, DKIM, DMARC)
dig example.com TXT +short
dig _dmarc.example.com TXT +short
dig selector._domainkey.example.com TXT +short

# NS (серверы имён)
dig example.com NS +short
# → ns1.example.com.
# → ns2.example.com.

# SOA (метаданные зоны)
dig example.com SOA +multiline
# → example.com. 3600 IN SOA ns1.example.com. admin.example.com. (
#                 2025072701 ; Serial
#                 3600       ; Refresh
#                 900        ; Retry
#                 1209600    ; Expire
#                 3600       ; Minimum
#                 )

# SRV (сервисы)
dig _ldap._tcp.example.com SRV +short
# → 0 0 389 dc1.example.com.

# CAA (сертификаты)
dig example.com CAA +short
# → 0 issue "letsencrypt.org"

# SVCB/HTTPS (HTTP/3)
dig example.com HTTPS +short
# → 1 . alpn="h3,h2" ipv4hint="192.0.2.10"

# TLSA (DANE)
dig _443._tcp.example.com TLSA +short

# SSHFP
dig example.com SSHFP +short

# PTR (обратное разрешение)
dig -x 192.0.2.20 +short
# → mail.example.com.

# ANY (все записи — может быть ограничен сервером RFC 8482)
dig example.com ANY +short

# Трассировка: цепочка NS-серверов
dig example.com +trace

# Полный ответ (секция Authority и Additional)
dig example.com ANY +noall +answer +authority +additional
```

### 7. Проверка CNAME vs ALIAS vs SVCB

```bash
# CNAME-цепочка: dig автоматически следует за CNAME
dig www.example.com A +short
# → www.example.com.  300  IN  CNAME  cdn.example.net.
# → cdn.example.net.  300  IN  A      198.51.100.1

# Apex: если здесь CNAME — ошибка (RFC нарушается)
dig example.com A +short
# → example.com.  3600  IN  A  192.0.2.10  ← A-запись, не CNAME

# SVCB: показывает параметры HTTP/3 и ECH
dig example.com HTTPS +noall +answer
# → example.com.  300  IN  HTTPS  1  .  alpn="h3,h2" ipv4hint="192.0.2.10"
```

## Типичные ошибки и их решение

### CNAME на Apex (root domain)

**Симптом:** попытка добавить CNAME для `example.com` (Apex) приводит к ошибке `named-checkzone` или SERVFAIL.

**Причина:** Apex обязан содержать NS и SOA. RFC 1034 запрещает CNAME рядом с любыми другими записями для того же имени.

**Решения (от худшего к лучшему):**
1.  **A/AAAA + ручное обновление:** дублировать IP вручную при изменении (ненадёжно).
2.  **ALIAS/ANAME:** использовать поддержку провайдера (Cloudflare, Route53, DNSimple).
3.  **SVCB/HTTPS (RFC 9460):** современный стандарт, работает как «псевдо-CNAME» для Apex.
4.  **CNAME Flattening:** механизм резолвера (Cloudflare) — резолвит CNAME на стороне и отдаёт A/AAAA.

### CNAME рядом с другими записями

**Симптом:** `named-checkzone` выдаёт ошибку: `CNAME and other data`.

**Решение:** удалить конфликтующие записи (MX, TXT, NS и др.) или заменить CNAME на A/AAAA-запись.

### MX указывает на CNAME

**Симптом:** почтовые серверы не могут доставить письма (RFC 2181 запрещает CNAME в MX).

**Решение:**
```dns
; Неправильно:
@   IN  MX  10 mail.example.com.
mail IN CNAME  web.example.com.

; Правильно:
@   IN  MX  10 mail.example.com.
mail IN  A   192.0.2.20
```

### Низкий TTL и DDOS-нагрузка на DNS

**Симптом:** при TTL < 60 секунд DNS-сервер получает экстремальную нагрузку.

**Причина:** каждый клиент запрашивает IP слишком часто, создавая DDoS-like трафик на DNS.

**Решение:** не опускайте TTL ниже 60 секунд без крайней необходимости. Для GSLB используйте 60–300 секунд, для миграций — 300–600 секунд за 24–48 часов до переезда.

### Wildcard не работает

**Симптом:** `dig sub.example.com` возвращает NXDOMAIN, хотя настроен wildcard `*.example.com`.

**Причины:**
1.  **Есть прямая запись:** для `sub.example.com` существует A-запись — wildcard не используется для уже существующих имён.
2.  **Wildcard не в корне зоны:** `*.sub.example.com` отвечает только для `x.sub.example.com`, но не для `sub.example.com` (Apex).
3.  **Нет точки в конце:** `*.example.com` (без точки в конце) интерпретируется как `*.example.com.$ORIGIN`.

**Решение:** проверьте, нет ли прямой записи; убедитесь, что wildcard задан на правильном уровне.

### DNSSEC: RRSIG отсутствует

**Симптом:** `delv` или `dig` показывают `unsigned` или `bogus`.

**Причина:** RRSIG-записи не сгенерированы или устарели (Serial не увеличен после подписания).

**Решение:**
```bash
# Переподпись зоны
sudo rndc signing -list example.com       # проверить текущие подписи
sudo rndc sign example.com               # переподписать
dig example.com RRSIG +short             # проверить наличие RRSIG
```

## Лучшие практики

*   **Не используйте CNAME на Apex:** если провайдер не поддерживает ALIAS/ANAME/SVCB — используйте A/AAAA-записи с ручным обновлением (или настройте автоматизацию через API).
*   **SPF + DKIM + DMARC:** тройная защита почты обязательна для всех доменов, отправляющих письма. Начните с `p=none` (мониторинг), затем `p=quarantine`, затем `p=reject`.
*   **CAA:** ограничьте выдачу сертификатов одним CA. Даже если CA будет скомпрометирован, сертификат не будет выпущен для вашего домена.
*   **TTL:** не опускайте ниже 60 секунд без необходимости. Для стабильных записей (MX, TXT, NS) — 3600–86400 секунд.
*   **SRV:** используйте для служб (LDAP, SIP, XMPP), но не для HTTP (для HTTP — A/AAAA или SVCB).
*   **DNAME:** используйте для реорганизации поддоменов (например, при слиянии компаний) — DNAME автоматически перенаправляет все имена поддерева.
*   **DNSSEC:** подписывайте зоны. NSEC3 защищает от перебора имён (zone walking). Подробнее: [Безопасность DNS](./dns_security.md).
*   **Не используйте ANY:** RFC 8482 разрешает серверам игнорировать ANY-запросы. Используйте конкретные типы.

## Дополнительная информация

*   **Ключевые RFC:**
    *   **RFC 1034 / 1035:** базовая спецификация DNS и типов записей.
    *   **RFC 1996:** NOTIFY (уведомление об обновлении зоны).
    *   **RFC 2181:** уточнения по формату записей (запрет CNAME в MX).
    *   **RFC 2308:** Negative Caching (кэширование NXDOMAIN).
    *   **RFC 3403:** NAPTR (трансформация имён).
    *   **RFC 6672:** DNAME (псевдоним для поддерева).
    *   **RFC 8482:** ограничение ANY-запросов.
    *   **RFC 8659:** CAA (Certification Authority Authorization).
    *   **RFC 9460:** SVCB/HTTPS (Service Binding).
*   [Протокол DNS](./dns.md) — транспорт и архитектура резолвинга.
*   [Зоны DNS и SOA](./dns_zones.md) — управление структурой зон и трансферами.
*   [Безопасность DNS](./dns_security.md) — DNSSEC механизмы (RRSIG, NSEC3, DS).
*   [Детальный анализ с dig](../../../Linux/Diagnostics/Networking/dns/dig_tool.md) — руководство по диагностике записей.
*   [Продвинутые сценарии](./dns_advanced.md) — ALIAS/ANAME маршрутизация, GeoDNS, SVCB.
