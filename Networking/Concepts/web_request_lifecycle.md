# Жизненный цикл веб-запроса

## Определения

**Жизненный цикл веб-запроса (Web Request Lifecycle)** — это полная последовательность этапов, которую проходит запрос от момента инициации пользователем (ввод URL в адресную строку или клик по ссылке) до финальной отрисовки полученного контента в браузере.

Этот процесс, занимающий от десятков до сотен миллисекунд, вовлекает множество сетевых узлов и протоколов:

1.  **Клиент (User Agent):** Браузер или CLI-утилита (`curl`, `wget`) на устройстве пользователя. Клиент формирует HTTP-запрос, управляет кэшированием, обрабатывает редиректы и выполняет рендеринг полученного контента.
2.  **Локальная сеть (LAN — Local Area Network):** Домашний или офисный роутер, коммутаторы, беспроводные точки доступа. Обеспечивает физическую и канальную связность через Ethernet или Wi-Fi.
3.  **Интернет-провайдер (ISP — Internet Service Provider):** Узел доступа к глобальной сети (Edge Router). Обеспечивает маршрутизацию трафика в глобальной сети через BGP.
4.  **Магистральные сети и IXP (Internet Exchange Points — точки обмена трафиком):** Глобальная инфраструктура передачи данных, связывающая провайдеров через протокол **BGP (Border Gateway Protocol)**.
5.  **CDN (Content Delivery Network — сеть доставки контента) / Edge Nodes:** Промежуточные серверы, кэширующие контент ближе к пользователю для снижения **RTT (Round Trip Time)**. Современные CDN также выполняют Edge Computing — обработку запросов на граничных узлах.
6.  **Сервер-источник (Origin Server):** Целевой веб-сервер, балансировщик нагрузки (**Load Balancer**) или кластер приложений, где формируется финальный ответ.

---

## Основные концепции

### Разрешение доменного имени (DNS)

Для установления соединения браузеру необходимо преобразовать доменное имя (например, `google.com`) в IP-адрес.

1.  **Локальное кэширование:**
    *   **Кэш браузера:** Проверка внутренних записей (собственный TTL браузера). Современные браузеры поддерживают HSTS-презагрузку и DNS-кэш с изоляцией по сайтам.
    *   **Кэш ОС и файл `hosts`:** Проверка системной таблицы соответствий (в Linux — через `nsswitch.conf`). Файл `/etc/hosts` имеет приоритет над DNS и используется для локальной разработки и блокировки.
    *   **Локальный резолвер:** Запрос к локальной службе (например, `systemd-resolved`, `dnsmasq` или DNS-сервер на роутере). В Linux настройки хранятся в `/etc/resolv.conf`.

2.  **Рекурсивный поиск:**
    *   Если адрес не найден, запрос отправляется к **рекурсивному резолверу** провайдера или публичным сервисам (Cloudflare `1.1.1.1`, Google `8.8.8.8`).
    *   **Рекурсивный vs Итеративный (нерекурсивный) запросы**: 
        *   **Рекурсивный**: Резолвер берет на себя всю работу по поиску и обязан вернуть либо готовый IP-адрес, либо ошибку. Флаг `RD=1` (Recursion Desired).
        *   **Итеративный**: Сервер возвращает не сам IP, а «отсылку» (referral) к другому DNS-серверу, который стоит ближе к цели в иерархии.
    *   **Anycast:** Современные DNS-серверы используют технологию Anycast, позволяющую одному IP-адресу принадлежать множеству физических серверов по всему миру. Запрос направляется к ближайшему узлу на основе метрик BGP.

3.  **Безопасность и современные протоколы (Актуально на 2026):**
    *   **DoH (DNS over HTTPS):** Инкапсуляция DNS-запросов в HTTPS-трафик для защиты от перехвата и подмены (порт 443). Предотвращает слежку со стороны провайдера.
    *   **DoT (DNS over TLS):** Передача запросов через выделенный зашифрованный канал (порт 853). Использует отдельный порт, что позволяет идентифицировать DNS-трафик.
    *   **DoQ (DNS over QUIC):** Современный стандарт (RFC 9250), обеспечивающий минимальную латентность за счет исключения Head-of-Line blocking и поддержки **0-RTT**.
    *   **Happy Eyeballs v3:** Алгоритм параллельного разрешения имен (одновременный запрос `A` и `AAAA` записей) с выбором наиболее быстрого протокола (IPv6 или IPv4) на основе реального RTT и истории успеха соединений. В 2026 году приоритет IPv6 с задержкой 150-300 мс.
    *   **SVCB/HTTPS-записи DNS:** Современные записи, позволяющие DNS-серверу сообщить параметры TLS, поддержку HTTP/3 (QUIC), альтернативные порты и ECH-конфигурацию в одном запросе, исключая лишние редиректы.

4.  **Иерархический поиск:** Резолвер последовательно опрашивает корневые серверы (**Root**), серверы доменных зон (**TLD**) и, наконец, авторитативный сервер владельца домена. Подробный разбор процесса см. в **[Процесс разрешения имён в DNS](../Protocols/DNS/dns_resolution.md)**.

### Межсетевое взаимодействие (ARP и IP)

1.  **Маршрутизация:** ОС определяет, находится ли целевой IP в локальной подсети путем сравнения с маской подсети. Если адрес назначения не в локальной сети, пакеты направляются на **шлюз по умолчанию** (Default Gateway). Таблица маршрутизации проверяется командой `ip route get <destination>`.
2.  **Протокол ARP (Address Resolution Protocol):** Для передачи данных внутри сегмента Ethernet необходим физический **MAC-адрес**. Компьютер отправляет широковещательный запрос (`ff:ff:ff:ff:ff:ff`) в LAN, чтобы узнать MAC-адрес шлюза. Ответ кэшируется в ARP-таблице (`arp -n` или `ip neigh`). Подробнее см. **[ARP](../Protocols/arp.md)**.
    *   **Gratuitous ARP:** Широковещательное объявление о смене MAC-адреса, используется при failover и для обнаружения конфликтов IP.
    *   **Proxy ARP:** Режим, при котором роутер отвечает на ARP-запросы за другие узлы, обеспечивая прозрачную маршрутизацию.
3.  **IP-пакетизация:** Данные упаковываются в IP-пакеты, содержащие адреса источника и назначения, TTL (Time To Live) пакета и флаги фрагментации. Поле TTL уменьшается на каждом маршрутизаторе (hop) — при достижении нуля пакет отбрасывается с отправкой ICMP Time Exceeded.

### Установка соединения и безопасность (TCP/QUIC и TLS)

1.  **Транспортный уровень:**
    *   **TCP (Transmission Control Protocol):** Традиционный метод с трехэтапным рукопожатием (SYN, SYN-ACK, ACK). Обеспечивает надежную доставку и контроль потока.
        *   **TCP Fast Open (TFO):** Позволяет передавать данные в первом пакете SYN, экономя 1 RTT. Требует поддержки сервером и клиентом.
        *   **SYN Cookies:** Механизм защиты от SYN-flood атак, позволяющий серверу обрабатывать SYN-запросы без сохранения состояния в памяти.
    *   **QUIC (UDP-based):** Основа **HTTP/3**. Устраняет проблему Head-of-Line blocking на уровне TCP и поддерживает **Connection Migration** (сохранение соединения при смене IP-адреса клиента). Включает встроенное шифрование TLS 1.3.
2.  **Рукопожатие TLS (Transport Layer Security):**
    *   **TLS 1.3:** Сокращает рукопожатие до 1 RTT и поддерживает режим **0-RTT** (Early Data) для ускорения повторных соединений. Обязательно использует Perfect Forward Secrecy (PFS).
    *   **Handshake:** Согласование версии протокола, обмен ключами через **ECDHE** (Elliptic Curve Diffie-Hellman Ephemeral) и проверка сертификата сервера.
    *   **SNI (Server Name Indication):** Позволяет клиенту указать имя хоста в начале рукопожатия, что необходимо для работы нескольких сайтов на одном IP. Передается открытым текстом в ClientHello.
    *   **ECH (Encrypted Client Hello):** Современное расширение (RFC 9460), шифрующее всё сообщение ClientHello, включая SNI. Решает проблему приватности, скрывая имя целевого сервера от провайдера.
    *   **OCSP Stapling:** Механизм, при котором сервер сам предоставляет доказательство валидности своего сертификата. Подробнее см. **[TLS — Transport Layer Security](../Protocols/tls.md)**.
3.  **Алгоритмы контроля перегрузки (Congestion Control):**
    *   В 2026 году стандартом является **BBRv3**, который ориентируется на реальный RTT и пропускную способность, а не на потери пакетов, что критично для стабильности веб-приложений в мобильных сетях.
    *   **L4S (Low Latency, Low Loss, Scalable throughput):** Технология, позволяющая сети и серверу взаимодействовать через ECN-метки для поддержания сверхнизкой задержки.
4.  **HTTP-обмен:**
    *   **Запрос:** Браузер отправляет заголовки (Headers), куки (Cookies) и тело запроса.
    *   **HSTS (HTTP Strict Transport Security):** Заголовок, предписывающий браузеру всегда использовать HTTPS. Поддерживает механизм preloading — список сайтов, жестко зашитый в браузерах.
    *   **Мультиплексирование:** В **HTTP/2** и **HTTP/3** запросы передаются параллельно через одно соединение. HTTP/2 использует бинарный фрейминг, HTTP/3 — изолированные потоки QUIC.
    *   **103 Early Hints:** Сервер может отправить промежуточный ответ с заголовками `Link` для предзагрузки критических ресурсов до формирования основного ответа.

### Обработка на стороне сервера и рендеринг

1.  **Серверная обработка:**
    *   Запрос принимается балансировщиком (L4 или L7):
        *   **L4-балансировка:** Работает на транспортном уровне, перенаправляет TCP/UDP-соединения без анализа содержимого. Примеры: IPVS, Nginx stream.
        *   **L7-балансировка:** Анализирует HTTP-заголовки, куки, URL. Позволяет маршрутизировать запросы на основе содержимого. Примеры: Nginx http, HAProxy http.
    *   Обратный прокси (Nginx, Angie, HAProxy) выполняет TLS-терминацию, компрессию, кэширование и проксирование к бэкендам.
    *   Приложение (Backend) обрабатывает запрос, взаимодействуя с базами данных и кэшем. Для обработки тысяч соединений применяются механизмы **[мультиплексирования ввода-вывода (select, poll, epoll)](./io_multiplexing.md)**.
2.  **Рендеринг в браузере (Critical Rendering Path):**
    *   **DOM (Document Object Model):** Парсинг HTML и построение дерева объектов. Блокирующие ресурсы (CSS, синхронные JS) задерживают парсинг.
    *   **CSSOM (CSS Object Model):** Обработка стилей. CSS блокирует рендеринг, но не парсинг HTML.
    *   **Render Tree:** Комбинация DOM и CSSOM для определения видимых элементов.
    *   **Layout (Reflow):** Расчет геометрии и позиций каждого элемента. Самая ресурсоемкая операция при изменениях DOM.
    *   **Paint:** Отрисовка пикселей на экране — заполнение цветами, текстурами, тенями.
    *   **Compositing:** Наложение слоев с использованием GPU-акселерации. Только transform и opacity выполняются на композитном слое без перерисовки.

---

## Практические сценарии

### Сценарий 1: Запрос через VPN (WireGuard)

Когда вы используете **VPN** (например, [WireGuard](../../Vpn/wireguard.md)), процесс усложняется из-за туннелирования и инкапсуляции.

#### Подготовка и DNS
1. **Туннель:** VPN-клиент уже установил зашифрованный канал. Маршрутизация направляет трафик в виртуальный интерфейс (`wg0`).
2. **DNS через VPN:** Запрос инкапсулируется в зашифрованный UDP-пакет VPN. VPN-сервер декапсулирует его и отправляет на свой резолвер, предотвращая **DNS-leak**.

#### Установка соединения и передача данных
1. **Инкапсуляция TCP:** Исходный TCP SYN-пакет упаковывается в VPN-пакет.
2. **Сквозное TLS:** TLS-соединение устанавливается **между браузером и целевым сервером**. VPN-сервер не может расшифровать этот трафик, он лишь пересылает зашифрованные пакеты.

#### Схема трафика через VPN:
```text
┌─────────────┐
│  Браузер    │  https://google.com
└──────┬──────┘
       │ DNS-запрос / TCP SYN / TLS Handshake
       ▼
┌─────────────────────────────────┐
│  Сетевой стек ОС (Маршрутизация)│
│  dev wg0 (VPN Interface)        │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  VPN-клиент (Инкапсуляция)      │
│  Шифрование (ChaCha20-Poly1305) │
└──────────────┬──────────────────┘
               │ Зашифрованный пакет
               ▼
┌─────────────────────────────────┐
│  Интернет-провайдер (ISP)       │
│  Видит только VPN-трафик        │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  VPN-сервер (Декапсуляция)      │
└──────────────┬──────────────────┘
               │ Оригинальный пакет
               ▼
┌─────────────────────────────────┐
│  Целевой сервер (google.com)    │
└─────────────────────────────────┘
```

#### Валидация работы VPN-туннеля
```bash
# Проверка интерфейса WireGuard
sudo wg show

# Проверка маршрутизации через VPN
ip route get 8.8.8.8
# → 8.8.8.8 via <VPN_GATEWAY> dev wg0

# Проверка DNS без утечки
dig +short whoami.cloudflare @1.1.1.1
# → Должен вернуть IP VPN-сервера, а не ваш реальный

# Проверка через curl
curl -s https://ipinfo.io/ip
# → Должен показать IP VPN-сервера
```

---

### Сценарий 2: Полная диагностика через curl

Команда `curl` с опциями детального вывода позволяет проанализировать каждый этап жизненного цикла запроса.

#### Измерение таймингов по этапам

```bash
curl -w "\
DNS Resolution:    %{time_namelookup}s\n\
TCP Connect:       %{time_connect}s\n\
TLS Handshake:     %{time_appconnect}s\n\
Time to First Byte:%{time_starttransfer}s\n\
Total Time:        %{time_total}s\n\
Protocol:          HTTP/%{http_version}\n\
Remote IP:         %{remote_ip}\n\
" -o /dev/null -s https://example.com

# → DNS Resolution:    0.005s
# → TCP Connect:       0.025s
# → TLS Handshake:     0.065s
# → Time to First Byte:0.120s
# → Total Time:        0.150s
# → Protocol:          HTTP/2
# → Remote IP:         93.184.216.34
```

#### Детальный вывод с проверкой TLS

```bash
curl -v --resolve example.com:443:93.184.216.34 https://example.com 2>&1

# → * Resolving timed out; проверить DNS при высоком time_namelookup
# → *   Trying 93.184.216.34:443...
# → * Connected to (93.184.216.34) port 443
# → * ALPN, offering h2
# → * TLSv1.3 (OUT), TLS handshake, Client hello
# → * TLSv1.3 (IN), TLS handshake, Server hello
# → * SSL connection using TLSv1.3 / TLS_AES_128_GCM_SHA256 / h2
# → * Certificate: subject: CN=example.com; issuer: CN=DigiCert; expire: 2025-01-01
# → > GET / HTTP/2
# → > Host: example.com
# → < HTTP/2 200
```

#### Проверка поддержки HTTP/3 (QUIC)

```bash
# Проверка HTTP/3 с измерением времени
curl -s -o /dev/null --http3 \
  -w "Protocol: HTTP/%{http_version}\nHandshake: %{time_appconnect}s\n" \
  https://example.com

# Сравнение с HTTP/2 для оценки выгоды QUIC
curl -s -o /dev/null \
  -w "HTTP/2: %{time_appconnect}s (TLS) + %{time_connect}s (TCP)\n" \
  --http2 https://example.com
```

#### Диагностика проблем с сертификатом

```bash
# Проверка цепочки сертификатов
echo | openssl s_client -connect example.com:443 -servername example.com -brief

# Проверка срока действия
echo | openssl s_client -connect example.com:443 2>/dev/null | openssl x509 -noout -dates
# → notBefore=Jan  1 00:00:00 2024 GMT
# → notAfter=Jan  1 00:00:00 2025 GMT

# Проверка OCSP Stapling
curl --cert-status -v https://example.com 2>&1 | grep -i "OCSP"
# → * OCSP response: successful
```

---

### Сценарий 3: Анализ трафика через Wireshark и tshark

Для глубокого анализа полного цикла запроса используется захват и анализ пакетов.

#### Захват и анализ HTTPS-запроса

```bash
# Захват трафика на интерфейсе с фильтром по хосту
sudo tshark -i eth0 -f "host example.com" -w /tmp/capture.pcap

# Анализ TLS handshake
tshark -r /tmp/capture.pcap -Y "tls.handshake.type == 1" -T fields \
  -e ip.src -e ip.dst -e tls.handshake.extensions_server_name
# → Клиент отправляет ClientHello с SNI

# Извлечение HTTP-запросов
tshark -r /tmp/capture.pcap -Y "http.request" -T fields \
  -e http.host -e http.request.method -e http.request.uri
# → example.com GET /

# Анализ HTTP-ответов
tshark -r /tmp/capture.pcap -Y "http.response" -T fields \
  -e http.response.code -e http.content_type
# → 200 text/html
```

#### Измерение задержек между этапами

```bash
# Фильтр для поиска задержек в TLS handshake
tshark -r /tmp/capture.pcap -Y "tls" -t ad \
  -T fields -e frame.time_relative -e tls.record.content_type
# → Время между ClientHello и ServerHello = время TLS handshake

# Статистика по TCP-соединениям
tshark -r /tmp/capture.pcap -q -z conv,tcp
# → Показывает все TCP-сессии с объемом данных и длительностью
```

#### Расшифровка TLS для анализа HTTP/2

```bash
# Экспорт ключей из браузера
export SSLKEYLOGFILE=~/tls-keys.log
google-chrome --user-data-dir=/tmp/debug

# В Wireshark: Edit → Preferences → Protocols → TLS → (Pre)-Master-Secret log filename
# Затем фильтры http2 покажут расшифрованный трафик
```

Подробнее см. **[Wireshark — практические сценарии](../ServicesAndTools/Wireshark/practical_scenarios.md)**.

---

### Сценарий 4: Диагностика проблем с DNS

#### Проверка цепочки разрешения имен

```bash
# Трассировка полного пути от корня до авторитетного сервера
dig +trace example.com

# Результат показывает:
# → . (root) → .com (TLD) → example.com (authoritative)

# Проверка конкретной записи у авторитетного сервера
dig @ns1.example.com example.com A +norec
# → Флаг AA (Authoritative Answer) подтверждает авторитетность
```

#### Сравнение ответов разных резолверов

```bash
# Сравнение Cloudflare, Google и провайдера
echo "Cloudflare:"; dig @1.1.1.1 example.com A +short
echo "Google:"; dig @8.8.8.8 example.com A +short
echo "Provider:"; dig example.com A +short

# Проверка IPv6
dig @1.1.1.1 example.com AAAA +short
```

#### Проверка кэширования и TTL

```bash
# Множественный запрос для проверки кэша
for i in {1..3}; do
  echo "Attempt $i:"; dig example.com | grep "Query time"
done
# → Первый запрос медленный (рекурсивный), последние быстрые (кэш)
```

#### Проверка DoH/DoT

```bash
# Тест DoT через kdig (или dig +tls)
dig @1.1.1.1 example.com +tls -p 853

# Проверка через curl с DoH
curl -H 'accept: application/dns-json' \
  'https://cloudflare-dns.com/dns-query?name=example.com&type=A'
```

---

### Сценарий 5: Оптимизация производительности запроса

#### Анализ Core Web Vitals

```bash
# Измерение всех фаз запроса
curl -w "\
DNS Lookup:        %{time_namelookup}s\n\
TCP Handshake:     %{time_connect}s\n\
TLS Handshake:     %{time_appconnect}s - %{time_connect}s = %{time_appconnect}s\n\
TTFB:              %{time_starttransfer}s\n\
Download:          %{time_total}s - %{time_starttransfer}s\n\
" -o /dev/null -s https://example.com
```

#### Проверка и включение оптимизаций

```bash
# Проверка поддержки HTTP/2
curl -s -o /dev/null -w "HTTP/%{http_version}\n" https://example.com
# → 2 (хорошо) или 1.1 (требуется оптимизация)

# Проверка сжатия
curl -s -H "Accept-Encoding: br,gzip" -o /dev/null \
  -w "Encoding: %{size_download} bytes\n" https://example.com

# Проверка Keep-Alive / Connection reuse
curl -v https://example.com https://example.com 2>&1 | grep -E "Re-using|Connected"
# → * Re-using existing connection! подтверждает мультиплексирование
```

#### Валидация оптимизации критического пути рендеринга

```bash
# Проверка наличия заголовков для предзагрузки
curl -sI https://example.com | grep -i "link:"
# → Link: </critical.css>; rel=preload; as=style

# Проверка Early Hints (103)
curl -sI https://example.com | grep -i "103 early hints"

# Проверка HSTS
curl -sI https://example.com | grep -i "strict-transport-security"
# → Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
```

---

## Валидация и диагностика

### Проверка каждого этапа жизненного цикла

| Этап | Команда | Ожидаемый результат | Диагностика при сбое |
| :--- | :--- | :--- | :--- |
| **DNS** | `dig example.com +short` | IP-адрес | Проверить `/etc/resolv.conf`, firewall для порта 53 |
| **TCP** | `nc -zv example.com 443` | `succeeded` | Проверить маршрутизацию, firewall, доступность порта |
| **TLS** | `openssl s_client -connect example.com:443 -brief` | `Verification: OK` | Проверить срок действия сертификата, SNI, цепочку |
| **HTTP** | `curl -o /dev/null -w "%{http_code}" https://example.com` | `200` или ожидаемый код | Проверить логи сервера, upstream |
| **Рендеринг** | DevTools → Network | Все ресурсы загружены | Проверить консоль на ошибки, блокирующие ресурсы |

### Комплексная проверка безопасности

```bash
# Проверка TLS-конфигурации
nmap --script ssl-enum-ciphers -p 443 example.com

# Проверка HTTP-заголовков безопасности
curl -sI https://example.com | grep -iE "strict|x-frame|x-content|content-security"

# Проверка сертификата
echo | openssl s_client -connect example.com:443 2>/dev/null | openssl x509 -noout -text | grep -A2 "Subject Alternative Name"
```

### Метрики производительности

| Метрика | Хорошо | Требует внимания | Критично |
| :--- | :--- | :--- | :--- |
| **DNS Lookup** | < 50ms | 50-200ms | > 200ms |
| **TCP Connect** | < 100ms | 100-300ms | > 300ms |
| **TLS Handshake** | < 150ms | 150-400ms | > 400ms |
| **TTFB** | < 200ms | 200-500ms | > 500ms |
| **Total (страница)** | < 1s | 1-3s | > 3s |

---

## Устранение неполадок

### Типичные проблемы и решения

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Медленный DNS** | Перегруженный резолвер, проблемы с IPv6 | `dig example.com` — высокий Query time | Использовать быстрый резолвер (1.1.1.1), проверить AAAA-записи |
| **Connection timeout** | Firewall, недоступность сервера, маршрутизация | `mtr example.com`, `nc -zv example.com 443` | Проверить маршрут, firewall rules, статус сервера |
| **TLS handshake failed** | Истекший сертификат, неверный SNI, несовместимость версий | `openssl s_client -connect`, `curl -v` | Обновить сертификат, проверить настройки TLS |
| **502 Bad Gateway** | Бэкенд недоступен для прокси | `curl http://upstream:port/health`, логи nginx | Проверить upstream, healthcheck, соединение с бэкендом |
| **Ошибка сертификата** | Истекший срок, несоответствие имени, недоверенный CA | `openssl x509 -noout -dates`, `curl -v` | Обновить сертификат, проверить SAN/CN, цепочку |
| **Медленная загрузка** | Блокирующие ресурсы, отсутствие кэша, медленный бэкенд | DevTools → Network, `curl -w` тайминги | Включить компрессию, кэширование, HTTP/2 |
| **Connection refused** | Сервер не слушает порт, firewall REJECT | `ss -tlnp`, `nc -zv example.com 443` | Запустить сервис, проверить bind address |

### Диагностика сетевого пути

```bash
# Трассировка маршрута с информацией о каждом hop
mtr -r -c 10 example.com

# Проверка MTU на пути
tracepath example.com

# Проверка конкретного порта
nmap -p 443 --reason example.com
```

### Проблемы с HTTP/2 и HTTP/3

```bash
# Проверка причины отсутствия HTTP/2
curl -v https://example.com 2>&1 | grep -i "ALPN"
# → Если "offering h2" но результат HTTP/1.1 — проблема в настройках сервера

# Проверка HTTP/3
curl -s -o /dev/null --http3 -w "%{http_version}" https://example.com
# → Если не 3 — проверить UDP/443 firewall, поддержку сервером
```

---

## Дополнительная информация

### Рекомендации по оптимизации

1. **DNS:** Использовать быстрые резолверы, включить DNS-кэширование на уровне ОС (`systemd-resolved`, `dnsmasq`), использовать DNS-prefetch в браузере.
2. **TCP:** Включить TCP Fast Open (`sysctl net.ipv4.tcp_fastopen=3`), увеличить Initial Congestion Window до 10-30 сегментов.
3. **TLS:** Использовать TLS 1.3, включить OCSP Stapling, Session Resumption (tickets), ECH для приватности.
4. **HTTP:** Мигрировать на HTTP/2 или HTTP/3, включить компрессию (Brotli для статики, Zstd для динамики), использовать 103 Early Hints.
5. **Кэширование:** Настроить Cache-Control, ETag, stale-while-revalidate. Использовать CDN для статики.
6. **Критический путь рендеринга:** Инлайнить критический CSS, отложить некритический JavaScript (`async`/`defer`), предзагрузить ключевые ресурсы.

### Ограничения и граничные случаи

1. **CVE-2026-11352:** В curl версиях ниже 8.21.0 обработка пустых UDP-датаграмм в QUIC приводила к бесконечному циклу. Требуется обновление.
2. **Happy Eyeballs fallback:** При проблемах с IPv6 алгоритм может задерживать соединение на 150-300 мс перед переключением на IPv4.
3. **0-RTT replay attacks:** Режим 0-RTT в TLS 1.3 уязвим к атакам повторной передачи для неидемпотентных запросов.
4. **MTU и фрагментация:** При использовании VPN или GRE-туннелей уменьшение MTU может вызывать фрагментацию и снижение производительности. Рекомендуется настроить MSS clamping.
5. **SNI inspection:** Некоторые сети блокируют трафик на основе SNI. ECH решает эту проблему, но требует поддержки со стороны сервера и DNS.

### См. также
- **[Модель OSI — теоретический фундамент](../OSI_TCP_IP_Model/osi_model.md)**
- **[Протоколы HTTP — оптимизация](../Protocols/HTTP/http_protocols_optimization.md)**
- **[TLS — Transport Layer Security](../Protocols/tls.md)**
- **[Процесс разрешения имён в DNS](../Protocols/DNS/dns_resolution.md)**
- **[Диагностика HTTP-задержек через curl](../../Linux/Diagnostics/Networking/curl_network_diagnostics.md)**
- **[Wireshark — практические сценарии](../ServicesAndTools/Wireshark/practical_scenarios.md)**

### Первоисточники
- **RFC 8305**: Happy Eyeballs v2.
- **RFC 8446**: The Transport Layer Security (TLS) Protocol Version 1.3.
- **RFC 9000**: QUIC: A UDP-Based Multiplexed and Secure Transport.
- **RFC 9110-9114**: HTTP Semantics, Caching, HTTP/1.1, HTTP/2, HTTP/3.
- **RFC 9250**: DNS over QUIC (DoQ).
- **RFC 9460**: Encrypted Client Hello (ECH).