# Безопасность DNS

## Определения

**DNSSEC (Domain Name System Security Extensions)** — набор расширений (RFC 4033, 4034, 4035), обеспечивающих аутентификацию источника и целостность данных в DNS с помощью цифровых подписей. Защищает от подмены ответов (Spoofing), но не обеспечивает конфиденциальность (данные передаются в открытом виде). Не шифрует трафик — для конфиденциальности используются DoH, DoT, DoQ.

**DoT (DNS over TLS, RFC 7858)** — шифрование DNS-запросов через TLS на выделенном порту 853. Обеспечивает приватность канала между клиентом и резолвером. Легко блокируется файрволами, так как использует отдельный порт. Защищает только от перехвата и подмены трафика; не обеспечивает аутентификацию записей, поэтому при компрометации DNS-сервера атаку не обнаружить. Для аутентификации записей требуется DNSSEC.

**DoH (DNS over HTTPS, RFC 8484)** — инкапсуляция DNS в HTTPS-трафик (порт 443). Скрывает DNS-активность за стандартным веб-трафиком, что затрудняет фильтрацию и цензуру. Поддерживается современными браузерами (Firefox, Chrome) и ОС (Windows, macOS, iOS, Android). Как и DoT, защищает только канал передачи; при компрометации DNS-сервера атаку не обнаружить без DNSSEC.

**DoQ (DNS over QUIC, RFC 9250)** — современный стандарт, использующий QUIC (UDP) для шифрования. Устраняет проблему Head-of-Line Blocking (характерную для TCP/TLS) и ускоряет установку соединения за счет 0-RTT. Использует порт 853 (или 784).

**ODoH (Oblivious DoH, RFC 9230)** — расширение DoH, использующее промежуточный прокси-сервер для разделения IP-адреса клиента и содержания его DNS-запросов. Резолвер видит запрос, но не знает автора; прокси знает автора, но не видит запрос. Поддерживается Cloudflare и Apple.

**TSIG (Transaction Signature, RFC 8945)** — механизм аутентификации сообщений DNS на основе общих секретных ключей (Shared Secrets). Используется для защиты трансфера зон (AXFR/IXFR) и динамических обновлений (RFC 2136). Работает на уровне транзакции, а не на уровне соединения.

**DANE (DNS-based Authentication of Named Entities, RFC 6698)** — протокол, позволяющий привязывать сертификаты TLS (или их хеши) к доменным именам через DNSSEC, уменьшая зависимость от публичных удостоверяющих центров (CA). Критичен для почтовых серверов (SMTP DANE) и веб-сервисов, где контроль над CA является угрозой.

**XoT (Zone Transfer over TLS, RFC 9103)** — шифрование зонных передач (AXFR/IXFR) через TLS. Критичен для Catalog Zones и скрытых зон — утечка полного списка доменов компании является угрозой безопасности.

## Базовые концепции

### Векторы атак на DNS

| Угроза | Описание | Метод защиты | Уровень опасности |
| :--- | :--- | :--- | :--- |
| **Cache Poisoning (атака Каминского)** | Внедрение ложных записей в кэш резолвера через подделку ответов с подстановкой случайных транзакционных ID. Атакующий отправляет массовые запросы на несуществующие поддомены, одновременно подбрасывая поддельные ответы. | DNSSEC, Source Port Randomization, 0x20 encoding (дополнительные биты в имени). | Критическая |
| **DNS Amplification** | DDoS-атака: запрос с поддельным IP жертвы к открытому резолверу вызывает огромный ответ (коэффициент амплификации до 50x для DNSSEC-записей). | RRL (Response Rate Limiting), закрытие Open Resolvers, BCP38 (фильтрация на входе провайдера). | Высокая |
| **DNS Water Torture** | Атака на резолвер путем массовых запросов случайных несуществующих поддоменов (`abc123.example.com`). Перегружает авторитетные серверы и резолвер. | Агрессивное кэширование NSEC3 (отрицательный кэш), лимиты на итерации, Rate Limiting. | Средняя |
| **DNS Tunneling** | Передача данных (например, команд C2) внутри TXT или других записей для обхода Firewall. Использует стеганографию: данные маскируются под легитимный DNS-трафик. | Анализ энтропии имен, DPI, лимиты на длину имен, мониторинг аномального трафика. | Средняя |
| **DNS Rebinding** | Перехват контроля над локальными сервисами браузером через быструю смену IP в DNS-ответе. Атакующий регистрирует домен с TTL=0, жертва обращается к нему, получает IP атакующего, а затем DNS-ответ меняется на локальный IP (127.0.0.1 / 192.168.x.x). | Проверка заголовка `Host`, запрет приватных IP в ответах внешних DNS, DNS Rebinding Shield (в браузерах). | Средняя |
| **DNS Hijacking** | Перехват или перенаправление DNS-запросов через перехват на уровне сети (MITM), заражение роутера или изменение настроек DNS в системе. | DoH/DoT/DoQ (шифрование), проверка целостности конфигурации DNS, DNSSEC. | Высокая |
| **NXDOMAIN Attack** | Массовые запросы к несуществующим именам для перегрузки авторитетных серверов и заполнения кэша резолвера мусорными записями. | NSEC3 с aggressive negative caching (RFC 8198), Rate Limiting. | Средняя |

### Механизмы DNSSEC: Цепочка доверия

DNSSEC не шифрует данные, а подписывает их. Ключевые компоненты:
*   **RRset:** группа записей одного типа (например, все A-записи для `example.com`), которая подписывается как единое целое.
*   **RRSIG (Resource Record Signature):** цифровая подпись для RRset. Содержит временные метки ( inception / expiration ), алгоритм подписи и серийный номер ключа.
*   **DNSKEY:** открытый ключ сервера, используемый для проверки RRSIG.
    *   **ZSK (Zone Signing Key):** ключ для подписи данных зоны. Часто ротируется (обычно каждые 30–90 дней).
    *   **KSK (Key Signing Key):** ключ для подписи самих ключей DNSKEY. Ротируется реже (обычно раз в год). Имеет флаг SEP (Secure Entry Point).
*   **DS (Delegation Signer):** хеш KSK дочерней зоны, размещенный в родительской зоне. Это связующее звено создает **Цепочку доверия (Chain of Trust)** от корня `.` до конечного имени.
*   **NSEC / NSEC3:** записи для подтверждения отсутствия данных. NSEC (RFC 4034) хранит имена в открытом виде (позволяет Zone Walking). NSEC3 (RFC 5155) использует хеширование для защиты от **Zone Walking** (перебора всех имен в зоне).
*   **CDNSKEY / CDS:** записи для автоматического обновления DS-записей в родительской зоне (RFC 7344). Позволяет автоматизировать делегирование DNSSEC без ручного вмешательства.

#### Алгоритмы DNSSEC

| Алгоритм | RFC | Статус | Рекомендация |
| :--- | :--- | :--- | :--- |
| **RSA/SHA-256 (8)** | RFC 3110 + 5155 | Рекомендуется | Широко поддерживается, проверенная безопасность |
| **ECDSAP256SHA256 (13)** | RFC 6605 | Рекомендуется | Компактные подписи (64 байта vs 256 для RSA), быстрая валидация |
| **Ed25519 (15)** | RFC 8080 | Современный | Самые компактные подписи (64 байта), высокая производительность. Ограниченная поддержка |
| **RSA/SHA-1 (5)** | RFC 3110 | Устаревший | Уязвим к коллизиям SHA-1. Рекомендуется миграция |
| **DSA (3)** | RFC 2536 | Запрещён | RFC 6781. Не использовать |

### Механизмы шифрования DNS: Сравнение протоколов

| Протокол | Порт | Транспорт | Приватность | Скрытость от DPI | 0-RTT | HOL Blocking | Поддержка |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **DNS (классический)** | 53 | UDP/TCP | Нет | Нет (легко блокируется) | Да (UDP) | Нет (UDP) | Универсальная |
| **DoT** | 853 | TCP+TLS | Да | Нет (отдельный порт, который легко блокируется) | Нет | Да (TCP) | systemd-resolved, Android, iOS |
| **DoH** | 443 | TCP+HTTPS | Да | Да (маскируется под HTTPS) | Нет | Да (TCP) | Браузеры, Windows, macOS, Android |
| **DoQ** | 853/784 | UDP+QUIC | Да | Нет (отдельный порт) | Да | Нет (QUIC) | Современные резолверы |
| **ODoH** | 443 | TCP+HTTPS+Proxy | Максимальная | Да | Нет | Да | Cloudflare, Apple |

#### Когда какой протокол выбирать

*   **Корпоративная сеть (контроль трафика):** DoH (маскируется под HTTPS, не блокируется файрволами).
*   **Мобильные устройства:** DoH или DoQ (устойчивость к переключению сетей, 0-RTT для DoQ).
*   **Максимальная приватность:** ODoH через Cloudflare или Apple Private Relay.
*   **Высокая производительность:** DoQ (0-RTT, без HOL blocking).
*   **Простота настройки:** DoT (нативная поддержка в systemd-resolved).
*   **Комбинированная защита:** Рекомендуется использовать DNSSEC совместно с DoT/DoH/DoQ. Шифрование защищает от перехвата и MITM, а цифровые подписи DNSSEC — от подмены ответов при компрометации сервера.

#### Формат сообщений DoH

DoH определяет два способа передачи DNS-запроса в HTTP-сообщении:

*   **GET:** DNS-запрос кодируется в Base64URL и передаётся в параметре URL `?dns=...`. Подходит для кэширования, так как запрос идемпотентен.
*   **POST:** Бинарный DNS-пакет передаётся в теле сообщения без изменений. Рекомендуется для больших ответов и снижения загрузки URL-парсеров.

Заголовок запроса:
```http
POST /dns-query HTTP/1.1
Host: dns.example.com
Content-Type: application/dns-message
Accept: application/dns-message
```

Тело запроса и ответа — бинарный DNS-пакет в том же формате, что и при классическом DNS. Размер сообщений может выравниваться до фиксированных блоков (Padding, RFC 8467) для защиты от анализа трафика по размеру.

Рекомендуется использовать HTTP/2 или HTTP/3, так как DNS является бинарным протоколом и выигрывает от бинарной инкапсуляции без base64-накладных расходов.

#### Открытые серверы DoT/DoH

Примеры публичных резолверов с поддержкой шифрования:

| Сервис | DoT (порт 853) | DoH (порт 443) |
| :--- | :--- | :--- |
| **Google** | `dns.google` | `https://dns.google/dns-query` |
| **Cloudflare** | `1.1.1.1` | `https://cloudflare-dns.com/dns-query` |
| **Yandex** | `dns.yandex.com` | `https://dns.yandex.com/dns-query` |
| **AdGuard** | `dns.adguard.com` | `https://dns.adguard.com/dns-query` |
| **Quad9** | `dns.quad9.net` | `https://dns.quad9.net/dns-query` |

При использовании DoT клиент подключается к серверу на порт 853 и сразу выполняет TLS-рукопожатие; сервер не ожидает обычный DNS-запрос до установки шифрованного канала.

### Механизмы повышения приватности

*   **QNAME Minimization (RFC 7816 / RFC 9156):** резолвер отправляет на каждом этапе иерархии только необходимую часть имени. При запросе `foo.bar.example.com` корень получит только запрос про `.com`. Снижает утечку данных о полном имени пользователя на каждом уровне иерархии.
*   **DNS Cookies (RFC 7873):** защита от IP-спуфинга и некоторых видов DDoS за счет обмена 64-битными токенами между клиентом и сервером. Клиент генерирует Cookie, сервер добавляет свой. Поддельные ответы без правильного Cookie отбрасываются.
*   **Padding (RFC 8467):** выравнивание размера зашифрованных (DoH/DoT) пакетов до стандартного размера (например, 128, 256, 512 байт) для предотвращения анализа трафика по размеру сообщений (traffic analysis).
*   **NSID (RFC 5001):** механизм идентификации DNS-сервера в ответах. Позволяет администратору узнать, какой конкретно сервер обработал запрос (полезно для диагностики anycast-кластеров). Передается в опции EDNS0.

### DANE и TLSA

DANE решает проблему «спущенного доверия» к публичным CA: если CA скомпрометирован, атакующий может выпустить легитимный сертификат для вашего домена. DANE привязывает сертификат к DNS-записи, подписанной через DNSSEC.

**Формат записи TLSA:**
```
_port._proto.name  IN  TLSA  usage selector matching-type cert-data
```

| Параметр | Значения | Описание |
| :--- | :--- | :--- |
| **usage** | 0 (PKIX-TA) | Trust Anchor: проверка через PKIX + сверка с TLSA |
| | 1 (PKIX-EE) | End Entity: проверка через PKIX + сверка с TLSA |
| | 2 (DANE-TA) | Trust Anchor: DANE заменяет CA |
| | 3 (DANE-EE) | End Entity: DANE заменяет CA для конкретного сертификата |
| **selector** | 0 (Full) | Хешируется весь сертификат |
| | 1 (SPKI) | Хешируется только публичный ключ (рекомендуется) |
| **matching-type** | 0 (Full) | Полное совпадение (хеш не используется) |
| | 1 (SHA-256) | SHA-256 хеш (рекомендуется) |
| | 2 (SHA-512) | SHA-512 хеш |

**Практическое значение:** DANE критичен для SMTP ( STARTTLS downgrade attack): почтовые серверы могут использовать TLSA-записи для защиты от перехвата почты.

## Практические сценарии

### 1. Hardening (укрепление) сервера BIND

Базовые меры защиты для авторитативного сервера:

```conf
# /etc/bind/named.conf.options
options {
    # Запрет рекурсии для публичных серверов (защита от амплификации)
    recursion no;
    allow-query { any; };

    # Ограничение частоты ответов (RRL) — защита от DNS Amplification
    rate-limit {
        responses-per-second 5;
        window 5;
        slip 2;          # Каждый второй ответ замедляется (RFC 5459)
        max-table-size 20000;
    };

    # Скрытие версии сервера
    version "none";

    # Поддержка DNSSEC с автоматической политикой
    dnssec-validation auto;

    # Ограничение трансферов зон (только доверенные вторичные серверы)
    allow-transfer { none; };    # По умолчанию запретить все

    # Включение логирования для аудита
    querylog yes;

    # Ограничение размера кэша (защита от memory exhaustion)
    max-cache-size 256m;
    max-cache-ttl 3600;          # Максимальный TTL в кэше (1 час)
    max-ncache-ttl 600;          # Максимальный TTL для отрицательных ответов (10 мин)
};
```

### 2. Настройка TSIG для трансфера зон

Защита AXFR между Master и Slave серверами:

```bash
# 1. Генерация ключа (на любом сервере)
tsig-keygen -a HMAC-SHA256 transfer-key > /etc/bind/transfer.key
# → Ключ сохраняется в формате, пригодном для include
```

```conf
# 2. Подключение ключа (на обоих серверах)
include "/etc/bind/transfer.key";

# 3. Применение в конфигурации Master-сервера
zone "example.com" {
    type master;
    file "/var/lib/bind/db.example.com";
    allow-transfer { key "transfer-key"; };
};

# 4. Применение в конфигурации Slave-сервера
zone "example.com" {
    type slave;
    file "/var/lib/bind/db.example.com";
    masters { 192.168.1.1 key "transfer-key"; };
};
```

**Валидация:**
```bash
# Проверка TSIG-ключа на Master-сервере
sudo rndc tsig-list | grep transfer-key
# → transfer-key. HMAC-SHA256: ACTIVE

# Проверка трансфера
dig @192.168.1.1 example.com AXFR -k /etc/bind/transfer.key
```

### 3. Полная процедура подписания зоны через DNSSEC

Пошаговая инструкция для BIND 9.18+:

```bash
# 1. Генерация ключей (выполняется один раз)
cd /etc/bind/zones

# Генерация KSK (Key Signing Key) — RSA 2048
dnssec-keygen -a RSASHA256 -b 2048 -f KSK example.com.
# → Kexample.com.+008+12345.key / .private

# Генерация ZSK (Zone Signing Key) — RSA 1024 (для скорости ротации)
dnssec-keygen -a RSASHA256 -b 1024 example.com.
# → Kexample.com.+008+54321.key / .private

# 2. Добавление ключей в файл зоны
cat >> db.example.com <<EOF
\$INCLUDE "Kexample.com.+008+12345.key"    ; KSK
\$INCLUDE "Kexample.com.+008+54321.key"    ; ZSK
EOF

# 3. Подпись зоны
dnssec-signzone -A -3 $(head -c 1000 /dev/urandom | sha1sum | cut -b 1-16) \
    -N INCREMENT -o example.com -t db.example.com
# → Создаёт файл db.example.com.signed и.key (DS-записи для родителя)

# 4. Проверка DS-записей (нужно передать в родительскую зону/регистратор)
cat db.example.com.key
# → example.com. IN DS 12345 8 2 <SHA-256 хеш KSK>

# 5. Обновление конфигурации BIND
# В named.conf.local:
# zone "example.com" {
#     type master;
#     file "/etc/bind/zones/db.example.com.signed";
# };
```

**Валидация:**
```bash
# Проверка подписей
dig @localhost example.com A +dnssec +short
# → 192.0.2.1

# Проверка RRSIG
dig @localhost example.com A +dnssec | grep RRSIG
# → example.com. 3600 IN RRSIG A 8 2 3600 20250830000000 20250727000000 54321 example.com. <подпись>

# Глубокая валидация через delv
delv @localhost example.com A +rdata
# → fully validated (если цепочка доверия от корня до зоны корректна)
```

### 4. Валидация DNSSEC через dig и delv

```bash
# Проверка DNSSEC-подписей
dig @8.8.8.8 example.com A +dnssec
# → В секции Answer: A-запись + RRSIG
# → В заголовке: flags: aa ad (AD = Authenticated Data)

# Проверка DNSKEY
dig @8.8.8.8 example.com DNSKEY +dnssec +short
# → 256 3 8 <открытый ключ ZSK>
# → 257 3 8 <открытый ключ KSK> (флаг 257 = KSK)

# Проверка DS-записи (в родительской зоне)
dig @8.8.8.8 com DS +dnssec +short
# → <хеш>  ; итог = chain of trust

# Глубокая валидация через delv (автоматически строит цепочку)
delv @8.8.8.8 example.com A +rdata
# → fully validated (все подписи от корня до хоста верны)
# → bogus (цепочка нарушена)
# → insecure (DNSSEC не включён для этого домена)

# Проверка с флагом cd (Checking Disabled) — отключает валидацию DNSSEC
dig @8.8.8.8 example.com A +cd
# → Позволяет увидеть данные, даже если DNSSEC-валидация провалилась
```

### 5. Настройка шифрованного DNS (DoT/DoH) на клиенте

DoT и DoH дополняют друг друга: DoT подходит для системной настройки через `systemd-resolved`, а DoH — для браузеров и контейнерных сред. В корпоративных средах рекомендуется применять оба протокола совместно с DNSSEC.

**systemd-resolved (Linux):**
```ini
# /etc/systemd/resolved.conf
[Resolve]
# DNS over TLS (DoT)
DNS=1.1.1.1#cloudflare-dns.com
DNSOverTLS=yes

# DNS over QUIC (DoQ) — поддержка в современных реализациях (v255+)
# DNS=quic://dns.adguard-dns.com

# DNSSEC
DNSSEC=allow-downgrade
```

```bash
# Перезапуск и проверка
sudo systemctl restart systemd-resolved
resolvectl status | grep -A5 "DNS Servers"
# → 1.1.1.1:853 (tls,.cloudflare-dns.com)
```

**Windows 11:**
```powershell
# Включение DoH
Set-DnsClientDohServerAddress -ServerAddress "1.1.1.1" -DohTemplate "https://cloudflare-dns.com/dns-query" -AllowFallbackToUdp $false -AutoUpgrade $true

# Настройка сетевого адаптера
Set-DnsClientServerAddress -InterfaceAlias "Ethernet" -ServerAddresses ("1.1.1.1")
```

**curl (проверка DoH из командной строки):**

```bash
# DoH через метод POST
curl -H 'Content-Type: application/dns-message' \
  --data "$(dig example.com A +binary)" \
  https://dns.google/dns-query
# → Бинарный ответ DNS; для декодирования можно использовать drill или dig +buffer

# DoH через метод GET
curl "https://cloudflare-dns.com/dns-query?name=example.com&type=A&do=1"
# → Параметр do=1 запрашивает DNSSEC-данные
```

**Brave/Chrome/Firefox (браузерный DoH):**

```bash
# Chrome: chrome://settings/security → «Use secure DNS»
# Выбрать провайдера или указать собственный URL:
# https://dns.yandex.com/dns-query
# Формат для произвольного сервера: https://<ip-адрес>/dns-query

# Firefox: about:config → network.trr.mode = 2 (зависит от DNS over HTTPS)
# network.trr.uri = https://dns.google/dns-query
```

**macOS:**
```bash
# Через системные настройки или networksetup
networksetup -setdnsservers Wi-Fi 1.1.1.1 1.0.0.1
# DoH настраивается через профиль MDM или Safari/Chrome settings
```

### 6. Анализ DoH-трафика в Wireshark

DoH (DNS over HTTPS) инкапсулирует DNS-запросы в HTTPS-трафик (порт 443). В Wireshark такая последовательность выглядит как обычное HTTPS-соединение, что делает DoH неотличимым от веб-трафика на сетевом уровне.

**Структура пакета DoH:**
```
IP → TCP → TLS → HTTP/2 → DNS
```

DNS-запрос вложен в тело HTTP/2-сообщения (секция `DATA`). Без расшифровки TLS виден только IP-адрес DNS-сервера и порт 443; содержимое запроса скрыто.

**Фильтры Wireshark для DoH:**

| Фильтр | Назначение |
| :--- | :--- |
| `dns` | Все DNS-запросы и ответы (включая DoH после расшифровки) |
| `http2` | HTTP/2-трафик, в котором транспортируется DoH |
| `tls.handshake` | TLS-рукопожатия при установке DoH-соединения |
| `ip.addr == <dns-server-ip>` | Фильтр по IP-адресу конкретного DoH-сервера |

**Расшифровка TLS для инспекции DoH:**

Для просмотра содержимого DNS-запроса внутри HTTPS необходимо экспортировать сессионные ключи TLS в Wireshark (через переменную окружения `SSLKEYLOGFILE` или встроенную конфигурацию Wireshark `(Pre)-Master-Secret log filename`).

После расшифровки в деталях пакета видна иерархия:
```
Frame: Ethernet II → IP → TCP → TLS Record: Application Data → HTTP/2 → DNS
```

В секции `HTTP/2` тело запроса содержит параметр `:method: POST` и путь `/dns-query`. DNS-данные передаются с заголовком `Content-Type: application/dns-message`.

**Пример анализа запроса:**
```
POST /dns-query HTTP/2
Host: dns.yandex.com
Content-Type: application/dns-message

Тело — бинарный DNS-запрос: type A, networks-course.ru
```

**Пример анализа ответа:**
```
HTTP/2 200 OK
Content-Type: application/dns-message

Тело — бинарный DNS-ответ: 4 A-записи (IP-адреса)
```

**Ключевое наблюдение:** если не расшифровывать TLS, DoH-трафик идентичен обычному HTTPS-трафику к веб-сайту. Это обеспечивает маскировку DNS-активности и усложняет фильтрацию на уровне файрволов. При наблюдении в Wireshark без расшифровки обращение идёт на порт 443 к IP-адресу DNS-сервера, что внешне ничем не отличается от захода на обычный сайт.

### 7. Проверка DANE/TLSA-записей

```bash
# Проверка TLSA-записи для SMTP
dig _25._tcp.mail.example.com TLSA +short
# → 3 1 1 E3B0C44298FC1C...

# Проверка TLSA для HTTPS
dig _443._tcp.example.com TLSA +short

# Проверка через openssl (с DANE)
openssl s_client -connect mail.example.com:25 -starttls smtp \
    -verify_return_error -tlsextdebug 2>&1 | grep -i "TLSA\|dane"

# Проверка через test-dane SMTP
# Отправка тестового письма с DANE-валидацией
swaks --to user@example.com --from test@example.org \
    --server mail.example.com --port 25 --tls --tls-verify
```

## Типичные ошибки и их решение

### DNSSEC: SERVFAIL после подписания зоны

**Симптом:** после подписания зоны DNSSEC, `dig` возвращает `SERVFAIL`.

**Причины:**
1. **Не обновлён DS-запись** в родительской зоне — цепочка доверия разорвана.
2. **Неверный алгоритм** — родительская зона подписана другим алгоритмом.
3. **Рассинхронизация ключей** — KSK/ZSK не добавлены в файл зоны.

**Решение:**
```bash
# 1. Проверка DS-записи в родительской зоне
dig com DS +short
# 2. Проверка DNSKEY
dig example.com DNSKEY +short
# 3. Убедитесь, что ключи включены в зону (grep KEY db.example.com)
# 4. Проверьте подписи: dnssec-signzone -g -o example.com -t db.example.com
```

### DoT/DoH: резолвер не работает после включения шифрования

**Симптом:** после включения DoT/DoH в systemd-resolved, все DNS-запросы завершаются таймаутом.

**Причины:**
1. **Блокировка порта 853** файрволом (для DoT).
2. **Проблема с сертификатом** резолвера (для DoT).
3. **Блокировка HTTPS** прокси (для DoH).

**Решение:**
```bash
# 1. Проверка связности с DoT-сервером
openssl s_client -connect 1.1.1.1:853 -brief 2>&1 | head -5
# → TLSv1.3 ... OK

# 2. Проверка логов
journalctl -u systemd-resolved -n 50 | grep -i "tls\|error\|fail"

# 3. Временный fallback на незашифрованный DNS
resolvectl dns eth0 8.8.8.8
```

### TSIG: трансфер зоны завершается с REFUSED

**Симптом:** `dig @master example.com AXFR` возвращает `REFUSED`, несмотря на правильный `allow-transfer`.

**Причина:** clocks skew — расхождение часов между серверами нарушает временные метки TSIG (допустимое расхождение: 5 минут по умолчанию).

**Решение:**
```bash
# 1. Синхронизация времени (обязательно для TSIG)
sudo chronyc makestep    # или ntpdate pool.ntp.org

# 2. Проверка TSIG-ключа на обоих серверах
sudo rndc tsig-list

# 3. Проверка расхождения часов
chronyc tracking | grep "System time"
```

### DNS Rebinding: локальные сервисы недоступны через браузер

**Симптом:** приложение не может обратиться к `localhost:8080` или `192.168.1.1` через веб-интерфейс.

**Причина:** DNS Rebinding — браузер разрешил внешнее имя в локальный IP, но политика безопасности блокирует такой запрос.

**Решение:**
```bash
# Проверка DNS-ответа
dig evil.example.com +short
# → 192.168.1.1 (подмена!)

# Включение DNS Rebinding Shield (Chrome)
# chrome://flags/#dns-rebinding-shield

# Или используйте DoH с проверкой IP
```

### NSEC3: Zone Walking всё ещё возможен

**Симптом:** despite NSEC3, злоумышленник перебирает имена зоны.

**Причина:** NSEC3 без `opt-out` позволяет перебор через хеширование (если зона небольшая). Также атакующий может использовать Old Data (до ротации NSEC3).

**Решение:**
```bash
# 1. Включить opt-out (RFC 5155) — уменьшает количество NSEC3-записей
# 2. Регулярно ротировать盐 NSEC3
dnssec-signzone -3 $(openssl rand -hex 16) -o example.com -t db.example.com

# 3. Проверка количества NSEC3-записей
dig example.com NSEC3PARAM +short
```

### DNS-утечки через VPN (DNS Leaks)

**Симптом:** VPN-туннель активен, но DNS-запросы идут мимо туннеля (через хостовый DNS). Провайдер видит все запрошенные домены.

**Причина:** `systemd-resolved` автоматически добавляет DNS-серверы VPN-интерфейса в глобальный список резолверов. Запросы шлются через физический интерфейс, минуя туннель.

**Диагностика:**
```bash
# Проверка текущих DNS-серверов
resolvectl status | grep "DNS Servers"
# → 100.64.0.2 (Tailscale) + 192.168.1.1 (Router) ← проблема

# Проверка через dnsleaktest.com
# → Если видите IP вашего провайдера — утечка

# Проверка маршрутизации DNS-трафика
ip route get 100.64.0.2
# → 100.64.0.2 dev tun0 src 100.64.0.1 ← правильно
```

**Решение:**
```bash
# WireGuard: указать DNS в конфигурации туннеля
# [Interface]
# DNS = 100.64.0.2

# Tailscale: отключить перехват системного DNS
sudo tailscale set --accept-dns=false

# Явная привязка DNS к VPN-интерфейсу
resolvectl dns tun0 100.64.0.2
resolvectl domain tun0 "~corp.local"

# iptables: принудительная маршрутизация DNS через туннель
sudo iptables -t nat -A OUTPUT -p udp --dport 53 -j DNAT --to-destination 100.64.0.2:53
sudo iptables -t nat -A OUTPUT -p tcp --dport 53 -j DNAT --to-destination 100.64.0.2:53
```

### Browser-level DNS Leak (DoH)

**Симптом:** VPN-туннель активен, DNS через VPN настроен, но браузер использует свой собственный DoH-резолвер и обходит VPN.

**Причина:** Chrome/Firefox/Edge по умолчанию могут использовать DoH (DNS over HTTPS), который отправляет DNS-запросы напрямую на резолвер браузера (1.1.1.1, 8.8.8.8), минуя системный DNS и VPN.

**Решение:**
```bash
# Chrome: отключить DoH
# chrome://settings/security → отключить "Use secure DNS"

# Firefox: отключить DoH
# about:config → network.trr.mode → 0 (отключить)

# Или принудительно направить DoH через VPN
# chrome://flags → "Auto-discover DoH servers" → Disabled
```

## Лучшие практики

*   **Включайте DNSSEC** на всех авторитативных серверах. Используйте автоматизированное управление ключами (dnssec-policy в BIND 9.18+).
*   **Используйте DoH или DoT** на всех клиентах для предотвращения перехвата DNS-трафика.
*   **Защищайте трансферы зон** через TSIG + allow-transfer (никогда не используйте `allow-transfer { any; }`).
*   **Настройте RRL** на авторитативных серверах для защиты от DNS Amplification.
*   **Регулярно ротируйте ключи DNSSEC:** ZSK — каждые 30–90 дней, KSK — раз в год.
*   **Используйте NSEC3 вместо NSEC** для защиты от Zone Walking (если конфиденциальность имён важна).
*   **Настройте DANE/TLSA** для SMTP-серверов для защиты от STARTTLS downgrade attack.
*   **Мониторинг:** отслеживайте SERVFAIL и DNSSEC-bogus ответы для выявления атак. Подробнее: [Диагностика DNS](../../../Linux/Diagnostics/Networking/dns/overview.md).

## Дополнительная информация

### Ключевые RFC

*   **RFC 4033/4034/4035:** DNSSEC Mechanisms.
*   **RFC 5155:** NSEC3 (DNSSEC Hashed Authenticated Denial of Existence).
*   **RFC 6698:** DANE/TLSA.
*   **RFC 7344:** Automated DNSSEC Maintenance (CDNSKEY/CDS).
*   **RFC 7816 / 9156:** QNAME Minimization.
*   **RFC 7858:** DNS over TLS (DoT).
*   **RFC 7873:** DNS Cookies.
*   **RFC 8198:** Aggressive Use of DNSSEC-Validated Cache.
*   **RFC 8467:** Padding for DNS over TLS.
*   **RFC 8484:** DNS over HTTPS (DoH).
*   **RFC 8914:** Extended DNS Errors (EDE).
*   **RFC 8945:** TSIG.
*   **RFC 9103:** DNS Zone Transfer over TLS (XoT).
*   **RFC 9230:** Oblivious DNS over HTTPS (ODoH).
*   **RFC 9250:** DNS over QUIC (DoQ).

### Связанные разделы

*   [Протокол DNS](./dns.md) — базовые сведения и порты.
*   [Типы DNS-записей](./dns_records.md) — детали записей DNSKEY, DS, RRSIG, TLSA, NSEC3.
*   [Продвинутые сценарии](./dns_advanced.md) — EDE, XoT, ECS, Anycast.
*   [Диагностика DNS](../../../Linux/Diagnostics/Networking/dns/overview.md) — инструменты `dig`, `delv`, `drill`.
*   [DNS-клиент в Linux](../../../Linux/Networking/Concepts/dns_client.md) — настройка DoT/DoH/DoQ на клиенте.
*   [DNS в Kubernetes](../../../Kubernetes/Networking/dns_deep_dive.md) — безопасность CoreDNS.
*   [Мониторинг и наблюдаемость DNS](./dns_monitoring.md) — SLA, Prometheus, Grafana, алертинг.
