# Протоколы HTTP/2 и HTTP/3 в веб-производительности

Полное сравнение версий протоколов доступно в руководстве [эволюция HTTP](../../../Networking/Protocols/HTTP/http_versions.md), детали настройки серверов — в статье [конфигурация HTTP/2 и HTTP/3 в Nginx/Angie](../../Nginx/Performance/nginx_http_versions.md), а углубленный разбор оптимизации транспорта — в документе [оптимизация производительности HTTP](../../../Networking/Protocols/HTTP/http_protocols_optimization.md).

## Определения

**HTTP/2 (Hypertext Transfer Protocol Version 2)** — бинарная версия протокола HTTP (RFC 9113), основанная на мультиплексировании потоков данных в рамках одного TCP-соединения. Вводит фреймирование данных и сжатие заголовков (HPACK). В браузерах доступен только через шифрованное соединение (ALPN `h2`).

**HTTP/3 (Hypertext Transfer Protocol Version 3)** — версия протокола на базе транспорта **QUIC** (RFC 9114), работающая поверх UDP. QUIC интегрирует TLS 1.3 и реализует собственные механизмы надежной доставки, контроля потока и управления перегрузкой, устраняя архитектурные ограничения TCP.

**QUIC (Quick UDP Internet Connections)** — транспортный протокол (RFC 9000) на базе UDP, объединяющий мультиплексирование потоков, контроль перегрузок (BBRv3, RFC 9002) и встроенное TLS 1.3 шифрование. Фундамент для HTTP/3.

**HPACK (Header Compression for HTTP/2)** — алгоритм сжатия заголовков для HTTP/2, использующий статический и динамический словари для уменьшения накладных расходов на повторяющиеся заголовки.

**QPACK (Header Compression for HTTP/3)** — алгоритм сжатия заголовков для HTTP/3, адаптированный для работы с независимыми потоками QUIC без блокировки декодера при потери пакетов.

**ALPN (Application-Layer Protocol Negotiation)** — расширение TLS, позволяющее клиенту и серверу согласовать используемый протокол прикладного уровня (h2, h3) непосредственно в процессе TLS-рукопожатия. Критично для корректной работы HTTP/2 и HTTP/3.

**Head-of-Line Blocking (HOL)** — задержка обработки данных из-за потери или блокировки первого пакета в очереди.
- В **HTTP/1.1** HOL присутствует на уровне соединения (последовательная обработка).
- В **HTTP/2** HOL сохраняется на уровне TCP: потеря одного пакета блокирует все мультиплексированные потоки в соединении.
- В **HTTP/3 (QUIC)** HOL устранена на уровне транспорта: потеря UDP-пакета блокирует только потоки, к которым принадлежали содержащиеся в нем данные.

**0-RTT (Zero Round Trip Time)** — режим возобновления сессии в TLS 1.3 и QUIC, позволяющий клиенту отправить полезную нагрузку (HTTP-запрос) в первом же пакете установки соединения. Экономит один RTT, но создает риск **Replay-атак** (RFC 9001).

**Connection Migration** — уникальная особенность HTTP/3: привязка соединения к Connection ID (CID) вместо 4-компонентного кортежа (Src IP, Src Port, Dst IP, Dst Port) позволяет сохранять сессию при смене сети (Wi-Fi → LTE) без разрыва стриминга или загрузки.

**Alt-Svc (Alternative Services)** — HTTP-заголовок ответа, информирующий клиент о доступных альтернативных протоколах или конечных точках (например, поддержка HTTP/3 на том же хосте). `ma` (max-age) определяет срок кэширования этой информации.

## Основные концепции

### Техническое сравнение протоколов (2026)

| Характеристика | HTTP/1.1 | HTTP/2 | HTTP/3 |
| :--- | :--- | :--- | :--- |
| **Транспортный протокол** | TCP | TCP (обязательный TLS 1.2+ для браузеров) | **QUIC (UDP)** со встроенным TLS 1.3 |
| **Механизм надежности** | TCP Stack (ядро ОС) | TCP Stack (ядро ОС) | **QUIC Stack (User-space)** |
| **HOL Blocking** | Уровень соединения | Уровень TCP-пакета | **Устранена** (независимые потоки QUIC) |
| **Идентификация сессии** | 4-tuple (IP/Port) | 4-tuple (IP/Port) | **Connection ID (CID)** — независим от IP-адреса |
| **Сжатие заголовков** | Нет | HPACK | **QPACK** (устойчив к неупорядоченной доставке) |
| **Приоритизация** | Нет | Деревья зависимостей и веса | **Extensible Prioritization** (RFC 9218): `u` (urgency 0–7), `i` (incremental) |
| **Рукопожатие (Latency)** | 1–2 RTT (TCP + TLS) | 2–3 RTT (TCP + TLS) | **1 RTT** (совмещенный) или **0-RTT** (повторное) |
| **Миграция сессии** | Нет | Нет | **Да** (Connection Migration) |
| **Контроль перегрузки** | TCP CUBIC/Reno | TCP CUBIC/Reno | **BBRv3** (RFC 9002) |
| **Стандарт** | RFC 9110 | RFC 9113 | RFC 9114, RFC 9000 |

### Архитектура QUIC и User-space стек

QUIC реализует все функции транспорта, шифрования и управления потоками в пользовательском пространстве (User-space), что дает преимущества в гибкости, но накладывает нагрузку на CPU (в 2–3 раза выше, чем эквивалентный TCP-трафик).

**Оптимизации User-space стека:**
- **Generic Segmentation Offload (GSO):** Снижает количество системных вызовов, позволяя передавать группы UDP-пакетов ядру одним вызовом.
- **eBPF (`quic_bpf`):** Директива, позволяющая ядру Linux направлять пакеты определенного Connection ID тому же воркеру Nginx/Angie, который начал сессию. Без этого `reload` конфигурации привел бы к разрыву всех HTTP/3 соединений.
- **Kernel TLS (kTLS):** Переносит симметричное шифрование в ядро ОС, позволяя использовать `sendfile()` для прямой передачи данных из дискового кэша в сетевую карту без копирования в адресное пространство приложения. Снижает нагрузку на CPU до 20–30%.

### Влияние на производительность веб-приложений

**1. Снижение задержки в нестабильных сетях:**
В мобильных сетях и сетях с потерями пакетов (>1%) HTTP/3 обеспечивает снижение LCP (Largest Contentful Paint) до 40–60% по сравнению с HTTP/2. Это достигается за счет устранения TCP HOL-блокировки и алгоритма контроля перегрузки **BBRv3**, который максимизирует пропускную способность, избегая переполнения буферов (Bufferbloat).

**2. Connection Migration:**
При смене сети (например, переключение смартфона с Wi-Fi на 4G) QUIC-соединение не разрывается, так как сервер и клиент продолжают узнавать друг друга по Connection ID (CID). Для пользователя это выглядит как мгновенное переключение без зависания стриминга или загрузки страницы. Процесс включает Path Validation для подтверждения нового маршрута.

**3. 0-RTT и Early Data:**
Использование 0-RTT (`ssl_early_data`) сокращает TTFB до минимума при повторном соединении, но вводит риск **Replay-атак**. Серверы должны разрешать 0-RTT только для идемпотентных методов (GET, HEAD) и проверять свежесть тикетов.

**4. Защита от UDP-флуда:**
Директива `quic_retry on;` заставляет клиент решать вычислительную задачу перед установкой соединения, защищая сервер от UDP-амплификации и флуда.

### Приоритизация ресурсов (RFC 9218)

В отличие от сложной системы приоритизации HTTP/2 (деревья зависимостей и веса), в 2026 году используется упрощенная схема Extensible Prioritization:
- **Параметр `u` (Urgency):** Приоритет от 0 (наивысший) до 7. `u=0` для критического CSS, `u=4` для фоновых задач.
- **Параметр `i` (Incremental):** Булево значение, указывающее, можно ли обрабатывать ресурс по частям (например, прогрессивные изображения).

Это позволяет браузерам и серверам более эффективно управлять полосой пропускания, гарантируя, что критический контент доставляется раньше фоновых задач.

### Механизмы обнаружения HTTP/3

Первый запрос клиента всегда идет по TCP (так как клиент не знает о поддержке UDP). Используются механизмы анонсирования:

1. **Заголовок `Alt-Svc`:**
   ```http
   Alt-Svc: h3=":443"; ma=86400, h3-29=":443"; ma=86400
   ```
   Сообщает браузеру о наличии HTTP/3. `ma` (max-age) кэширует эту информацию.

2. **HTTPS Resource Record (DNS, RFC 9460):**
   Самый быстрый метод. Позволяет браузеру узнать о поддержке h3 еще до отправки первого запроса.
   ```dns
   example.com. HTTPS 1 . alpn="h3,h2"
   ```

3. **Speculation Rules API:**
   Браузер может пререндерить страницу, если сервер анонсирует поддержку HTTP/3 через заголовки или DNS.

### Влияние на Core Web Vitals

| Метрика | Влияние HTTP/2 | Влияние HTTP/3 |
| :--- | :--- | :--- |
| **LCP** | Мультиплексирование ускоряет загрузку критических ресурсов за счет одного соединения. HPACK снижает overhead заголовков. | Устранение TCP HOL-блокировки в мобильных сетях снижает LCP на 40–60% при потерях >1%. BBRv3 минимизирует Bufferbloat. |
| **INP** | Приоритизация потоков позволяет доставлять критический JS раньше. | Отсутствие блокировки на уровне TCP снижает задержку до первого байта (TTFB), что напрямую улучшает INP. |
| **CLS** | Server Push (устарел) и Early Hints ускоряют доставку CSS, предотвращая нестилизованный контент (FOUT). | 0-RTT ускоряет повторные посещения, снижая вероятность сдвигов из-за медленной загрузки шрифтов. |

## Практические сценарии

### Сценарий 1: Валидация поддержки HTTP/3 в продакшене

**Цель:** Подтвердить, что сервер корректно анонсирует HTTP/3 и клиенты могут подключаться по QUIC.

**Шаги:**
1. Проверить открытие UDP-порта 443:
   ```bash
   ss -ulpn | grep :443
   # → UNCONN 0 0 0.0.0.0:443 ... users:(("nginx",pid=1234,fd=8))
   ```

2. Проверить ALPN для HTTP/3:
   ```bash
   openssl s_client -connect example.com:443 -alpn h3 -servername example.com -brief
   # → ALPN protocol: h3
   ```

3. Проверить заголовок Alt-Svc:
   ```bash
   curl -sI https://example.com/ | grep -i alt-svc
   # → Alt-Svc: h3=":443"; ma=86400
   ```

4. Проверить HTTP/3 через curl (требуется curl с поддержкой HTTP/3):
   ```bash
   curl --http3 -I https://example.com
   # → HTTP/3 200
   ```

### Сценарий 2: Нагрузочное тестирование HTTP/2 и HTTP/3

**Цель:** Сравнить производительность протоколов в контролируемых условиях.

```bash
# h2load: специализированный бенчмарк для HTTP/2 и HTTP/3 (часть nghttp2)
h2load -n 10000 -c 100 --h2 https://example.com/
# → завершено 10000 запросов за 2.3s (RPS: 4347)

h2load -n 10000 -c 100 --h3 https://example.com/
# → завершено 10000 запросов за 1.8s (RPS: 5555)

# wrk: универсальный бенчмарк с поддержкой Lua-скриптов
wrk -t4 -c100 -d30s -H "Accept-Encoding: gzip" https://example.com
# → Running 30s test @ https://example.com/
# → 4 threads and 100 connections
# → 125432.5 requests in 30.00s, 1.05GB read

# hey: простая альтернатива ab с поддержкой HTTP/2
hey -n 1000 -c 100 https://example.com
# → Total: 1.2342s
# → Slowest: 0.2341s
# → Fastest: 0.0123s
# → Average: 0.0567s
```

### Сценарий 3: Валидация 0-RTT и Connection Migration

**Цель:** Подтвердить работу 0-RTT и устойчивость соединения при смене сети.

```bash
# 1. Проверка 0-RTT через curl (curl 8.x с поддержкой Early Data)
curl --early-data /tmp/empty_file --include https://example.com/ -I
# → HTTP/3 200
# → Early-Data: 1 (если сервер принял 0-RTT)

# 2. Проверка Connection Migration
# Подключиться по Wi-Fi
curl --http3 https://example.com/api/health -w "\nTime: %{time_total}s\n"
# Отключить Wi-Fi, включить LTE
# Повторить запрос — соединение не должно разрываться (CID сохраняется)
ss -u -a | grep :443
# → udp UNCONN 0 0 ... quic (CID активен)
```

### Сценарий 4: Эмуляция потерь пакетов для оценки HTTP/3

**Цель:** Подтвердить преимущества HTTP/3 в сетях с высоким процентом потерь.

```bash
# Эмуляция 5% потерь пакетов на интерфейсе
sudo tc qdisc add dev eth0 root netem loss 5%

# Тест HTTP/2
curl -s -o /dev/null -w "HTTP/2 TTFB: %{time_starttransfer}s\n" --http2 https://example.com/api/data
# → HTTP/2 TTFB: 0.845s

# Тест HTTP/3
curl -s -o /dev/null -w "HTTP/3 TTFB: %{time_starttransfer}s\n" --http3 https://example.com/api/data
# → HTTP/3 TTFB: 0.312s

# Очистка
sudo tc qdisc del dev eth0 root
```

### Сценарий 5: Мониторинг adoption HTTP/3 в продакшене

**Цель:** Отслеживать процент клиентов, использующих QUIC, и динамику перехода.

**Данные для сбора:**
- ALPN из логов Nginx/Angie (`$ssl_alpn`)
- User-Agent и версия протокола (`$server_protocol`)
- Географическое распределение по протоколам

**Пример логирования:**
```nginx
log_format main_ext '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    'alpn=$ssl_alpn protocol=$server_protocol';

access_log /var/log/nginx/access.log main_ext;
```

**Валидация:**
```bash
# Процент HTTP/3 от общего трафика
awk -F'alpn=' '{print $2}' /var/log/nginx/access.log | awk '{print $1}' | sort | uniq -c | sort -rn
# → 45231 h3
# → 38902 h2
# → 1245 http/1.1
# → Adoption: 52.3% HTTP/3
```

## Операции и команды

### Валидация конфигурации и модулей

| Команда | Назначение | Пример вывода |
| :--- | :--- | :--- |
| `nginx -t` | Проверка синтаксиса | `nginx: the configuration file /etc/nginx/nginx.conf syntax is ok` |
| `nginx -V 2>&1 \| grep -o 'http_v2_module'` | Проверка модуля HTTP/2 | `http_v2_module` |
| `nginx -V 2>&1 \| grep -o 'http_v3_module'` | Проверка модуля HTTP/3 | `http_v3_module` (отсутствует, если не собран) |
| `nginx -V 2>&1 \| grep -o 'built with OpenSSL [0-9.]\+'` | Версия OpenSSL | `built with OpenSSL 3.2.1` |

### Диагностика соединений

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ss -tnp \| grep :443` | TCP-соединения (HTTP/1.1, HTTP/2) | `LISTEN 0 128 0.0.0.0:443 ... users:(("nginx",pid=1234,fd=6))` |
| `ss -ulpn \| grep :443` | UDP-соединения (HTTP/3, QUIC) | `UNCONN 0 0 0.0.0.0:443 ... users:(("nginx",pid=1234,fd=8))` |
| `ss -u -a \| grep :443` | Все UDP-соединения и слушатели | `udp UNCONN 0 0 *:quic *:*` |
| `openssl s_client -connect example.com:443 -alpn h2 -servername example.com -brief` | Проверка ALPN для HTTP/2 | `ALPN protocol: h2` |
| `openssl s_client -connect example.com:443 -alpn h3 -servername example.com -brief` | Проверка ALPN для HTTP/3 | `ALPN protocol: h3` |
| `curl --http2 -I https://example.com` | Проверка HTTP/2 | `HTTP/2 200` |
| `curl --http3 -I https://example.com` | Проверка HTTP/3 | `HTTP/3 200` |
| `curl -I -H "Alt-Used: example.com:443" https://example.com` | Проверка Alt-Svc заголовка | `Alt-Svc: h3=":443"; ma=86400` |
| `nghttp -nv https://example.com/` | Специализированный клиент HTTP/2/3 | `[HTTP/3] 200 OK`, `[Header] content-encoding: br` |

### Диагностика производительности и задержек

```bash
# Полный тайминг запроса (TTFB, TLS, DNS)
curl -o /dev/null -s -w "\
  DNS: %{time_namelookup}s\n\
  TCP: %{time_connect}s\n\
  TLS: %{time_appconnect}s\n\
  TTFB: %{time_starttransfer}s\n\
  Total: %{time_total}s\n" https://example.com/
# → DNS: 0.012s
# → TCP: 0.045s
# → TLS: 0.078s
# → TTFB: 0.245s
# → Total: 0.312s

# Если TTFB > 500 мс — проблема на стороне бэкенда или БД
# Если TLS > 100 мс — требуется оптимизация TLS (OCSP Stapling, session tickets, kTLS)
```

### TCP/QUIC тюнинг для операторов

```bash
# /etc/sysctl.d/99-web-performance.conf
# Увеличение лимитов соединений для высоконагруженных серверов
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_max_syn_backlog = 65535

# Ускорение переиспользования сокетов
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 600

# Оптимизация для QUIC (UDP)
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.ip_local_port_range = 1024 65535

# Отключение slow start после idle (для постоянных соединений)
net.ipv4.tcp_slow_start_after_idle = 0

# Применение
sysctl --system
sysctl net.core.somaxconn
# → net.core.somaxconn = 65535
```

### Проверка MTU и фрагментации (критично для QUIC)

```bash
# QUIC требует MTU >= 1280 байт. Проверка через ping с запретом фрагментации
ping -M do -s 1400 example.com
# → если нет ответа — MTU ниже требуемого

# Проверка текущего MTU на интерфейсе
ip link show eth0 | grep mtu
# → mtu 1500

# Временное увеличение MTU (если поддерживается сетью)
sudo ip link set eth0 mtu 9000
```

## Мониторинг и алертинг

### Ключевые метрики для SRE

Web Vitals в контексте SRE — это SLI для фронтенда. HTTP/2 и HTTP/3 влияют на метрики следующим образом:

| Метрика | Цель (SLO) | Влияние протокола |
| :--- | :--- | :--- |
| **LCP** | p75 < 2.5 с | HTTP/3 снижает задержку в нестабильных сетях |
| **INP** | p75 < 200 мс | Мультиплексирование и приоритизация ускоряют доставку JS |
| **TTFB** | p75 < 500 мс | 0-RTT и kTLS сокращают handshake |
| **Cache Hit Ratio** | > 90% | Мультиплексирование позволяет агрессивнее кэшировать |
| **HTTP/3 Adoption** | > 50% | Показывает покрытие QUIC-совместимыми клиентами |

### Prometheus метрики для HTTP/2/3

```yaml
# Recording rules
- record: job:frontend_lcp_good_ratio
  expr: sum(rate(lcp_good[28d])) / sum(rate(lcp_total[28d]))

- record: job:frontend_inp_good_ratio
  expr: sum(rate(inp_good[28d])) / sum(rate(inp_total[28d]))

- record: job:frontend_cls_good_ratio
  expr: sum(rate(cls_good[28d])) / sum(rate(cls_total[28d]))

# Error Budget Burn Rate алерты
- alert: FrontendLCPErrorBudgetBurn
  expr: job:frontend_lcp_good_ratio < 0.99   # SLO 99%
  for: 1h
  annotations:
    summary: "LCP SLO нарушен ({{ $value }})"
    severity: "sev2"

- alert: FrontendINPErrorBudgetBurn
  expr: job:frontend_inp_good_ratio < 0.99
  for: 1h
  annotations:
    summary: "INP SLO нарушен ({{ $value }})"
    severity: "sev2"
```

### Логирование для анализа протоколов

```nginx
# Расширенный формат лога с протокольными метриками
log_format main_ext '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    'rt=$request_time '
                    'alpn=$ssl_alpn protocol=$server_protocol '
                    'ssl_cipher=$ssl_cipher';

access_log /var/log/nginx/access.log main_ext;
```

### Мониторинг через ss и nstat

```bash
# Статистика TCP-соединений
ss -tnp | grep :443 | wc -l
# → 342 (активные HTTP/2 соединения)

# Статистика UDP/QUIC
ss -ulpn | grep :443 | wc -l
# → 89 (активные HTTP/3 соединения)

# Счетчики сетевых ошибок (переполнения буферов, ошибки UDP)
nstat -az | grep -E "UdpNoPort|UdpInErrors|TcpExtListenOverflows|TcpExtListenDrops"
# → UdpNoPort: 1245
# → TcpExtListenOverflows: 89
# → TcpExtListenDrops: 45
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий LCP** | LCP > 2.5 с, медленная загрузка основного контента | Chrome DevTools → Network → фильтр по LCP | CDN, `fetchpriority="high"`, кэширование, HTTP/3 |
| **Высокий TTFB** | LCP > 2.5 с, медленный первый байт | `curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s" URL` | Оптимизация запросов к БД, кэширование, kTLS |
| **HTTP/2 не активируется** | `curl -I` возвращает HTTP/1.1 | `openssl s_client -connect example.com:443 -alpn h2 -servername example.com` | Обновить Nginx до 1.25.1+, проверить OpenSSL 1.1.1+ |
| **HTTP/3 недоступен** | `curl --http3` возвращает ошибку | `ss -ulpn \| grep :443`, `nginx -V \| grep http_v3_module` | Открыть UDP 443, собрать Nginx с `http_v3_module`, использовать Angie |
| **Replay-атака 0-RTT** | Дублирование запросов POST/PUT | Проверить `ssl_early_data` в конфигурации | Отключить 0-RTT для методов с побочными эффектами, использовать Idempotency Key |
| **HTTP/2 Bomb / Flood** | Высокая нагрузка на CPU, отказ в обслуживании | Мониторинг RPS, анализ логов | `http2_max_requests 1000;`, `http2_max_concurrent_streams 128;`, `limit_req` |
| **HPACK-бомба** | Потребление памяти, падение воркеров | `nginx -T \| grep max_headers` | `max_headers 100;`, ограничение размера заголовков |
| **Cache Stampede** | Всплеск нагрузки на Origin | Мониторинг Origin CPU/RPS | `proxy_cache_lock on;`, Jitter TTL, `stale-while-revalidate` |
| **UDP-фрагментация** | Нестабильный HTTP/3, потери пакетов | `ping -M do -s 1400 example.com` | Убедиться, что MTU >= 1280, включить PMTUD |
| **Domain Sharding в коде** | Использование `static1.`, `static2.` | Аудит HTML/CSS/JS | Удалить разделение по поддоменам — антипаттерн в 2026 году |
| **Устаревший Server Push** | Использование `http2_push` | Аудит конфигурации | Заменить на 103 Early Hints (Server Push удален из HTTP/3) |

## Рекомендации

### Базовые правила

1. **Приоритизируйте LCP-ресурс:** Используйте `fetchpriority="high"` для Hero-image, `preload` для критических шрифтов.
2. **Включайте HTTP/2 на всех HTTPS-серверах:** Минимальная конфигурация — `listen 443 ssl http2;`. Браузеры не поддерживают HTTP/2 без шифрования.
3. **Включайте HTTP/3 только после валидации:** Проверьте поддержку UDP 443 на целевых сетях (мобильные, корпоративные). Используйте Alt-Svc с `ma=86400` (сутки).
4. **Отключайте Domain Sharding:** Используйте один домен с HTTP/2 multiplexing. Разделение по поддоменам вредит производительности в 2026 году.
5. **Используйте 103 Early Hints вместо Server Push:** Server Push удален из HTTP/3 и игнорируется браузерами. Early Hints не принуждают браузер к загрузке и не конфликтуют с кэшем.
6. **Настройте TLS 1.3:** Уберите TLS 1.0/1.1. TLS 1.3 сокращает handshake до 1 RTT и необходим для HTTP/3.
7. **Используйте 0-RTT только для идемпотентных операций:** Разрешайте Early Data только для GET/HEAD. Настройте `max_early_data_size` и проверку тикетов.
8. **Настраивайте Alt-Svc с разумным `ma`:** Сутки (`86400`) — оптимально. Слишком долгий `ma` приведет к распространению устаревшей конфигурации при изменении серверов.
9. **Мониторьте ALPN adoption:** Отслеживайте процент клиентов, использующих h2 vs h3, через логи (`$ssl_alpn`).
10. **Включайте BBRv3:** Для серверов с высокой пропускной способностью и сетями с потерями пакетов. Проверьте поддержку: `sysctl net.ipv4.tcp_congestion_control`.

### Для DevOps/SRE/SysAdmin

*   **Валидация после деплоя:** Проверяйте заголовки Alt-Svc, ALPN и статус протокола через `curl -I` после каждого деплоя.
*   **Мониторинг UDP-порта 443:** Убедитесь, что firewall не блокирует UDP/443 на всех промежуточных балансировщиках и серверах.
*   **QUIC eBPF для стабильности:** Включайте `quic_bpf on;` для сохранения активных HTTP/3 сессий при `reload` конфигурации. Требует Linux 5.7+.
*   **QUIC GSO для производительности:** Включайте `quic_gso on;` для снижения количества системных вызовов при передаче UDP-пакетов.
*   **TCP Tuning:** Настройте `initcwnd` на 14–30 сегментов для доставки небольших ответов за 1 RTT. Включите `tcp_fastopen` для снижения задержки рукопожатия.
*   **Kernel TLS (kTLS):** Включайте для снижения нагрузки на CPU при отдаче статики и кэшированных ответов. Требует OpenSSL 3.0+ и Linux 5.10+.
*   **Мониторинг QUIC-потоков:** Используйте `ss -u -a` для мониторинга UDP-соединений. Отслеживайте `stateless reset` и `connection close` в логах.
*   **Нагрузочное тестирование:** Используйте `h2load` для HTTP/2/3 бенчмарков. Для HTTP/3 тестирования на основе libcurl используйте `curl --http3`.
*   **Аудит Domain Sharding:** Регулярно проверяйте код фронтенда на наличие разделения статики по поддоменам (`static1.`, `static2.`). Удалите при обнаружении.
*   **Алертинг на HTTP/3 Adoption:** Настройте алерты при падении доли HTTP/3 ниже ожидаемого уровня — это может указывать на проблемы с сетью или балансировщиками.

## Дополнительная информация

### RFC и спецификации

| RFC | Название / Тема | Статус в 2026 |
| :--- | :--- | :--- |
| **RFC 9113** | HTTP/2 (Specification) | Стандарт |
| **RFC 9114** | HTTP/3 (Specification) | Стандарт |
| **RFC 9218** | Extensible Prioritization Scheme for HTTP | Активный |
| **RFC 8297** | 103 Early Hints | Активный |
| **RFC 9659** | Zstandard Content-Encoding | Активный |
| **RFC 9509** | Compression Dictionary Transport | Активный |
| **RFC 9330** | L4S Architecture | Активный |
| **RFC 9002** | QUIC: Loss Detection and Congestion Control | Стандарт |
| **RFC 9435** | Encrypted Client Hello (ECH) | Активный |
| **RFC 9460** | Service Binding and Registry Specification (HTTPS DNS) | Активный |
| **RFC 9000** | QUIC: A UDP-Based Multiplexed and Secure Transport | Стандарт |
| **RFC 9001** | QUIC: Using TLS to Secure QUIC | Стандарт |
| **RFC 9213** | CDN-Cache-Control заголовок | Активный |

### Рекомендации 2026 года

*   **Page Experience:** Google использует мобильные данные CrUX как первичный фактор для mobile-first индексации. Все три метрики (LCP, INP, CLS) должны проходить порог одновременно. HTTP/3 напрямую влияет на LCP и INP в нестабильных сетях.
*   **75-й перцентиль:** Оценка строится по 75-му перцентилю реальных посещений за скользящее окно 28 дней. Даже если медианные значения хороши, деградация нижнего квартиля disqualifies страницу.
*   **Fetch Priority:** атрибут `fetchpriority="high"` для LCP-изображения — стандарт де-факто. Использование `loading="lazy"` для LCP-элемента — критическая ошибка.
*   **Shared Dictionaries (RFC 9509):** механизм сжатия дельт при обновлении SPA-приложений, радикально снижающий объем передаваемых данных.
*   **L4S (RFC 9330):** технология «Low Latency, Low Loss, Scalable throughput». Позволяет сети и серверу взаимодействовать через ECN-метки, поддерживая сверхнизкую задержку (Jitter < 10 мс) даже при полной загрузке канала.
*   **BBRv3:** алгоритм контроля перегрузки от Google, максимизирующий пропускную способность в сетях с потерями пакетов. Стандарт для QUIC в 2026 году.

### Граничные случаи и ограничения

1. **HTTP/2 с очень старыми клиентами:** Windows XP, Android < 4.3 не поддерживают ALPN. Для таких клиентов автоматически используется HTTP/1.1.
2. **UDP-фрагментация и MTU:** QUIC-пакеты превышают стандартный MTU (1500), что приводит к фрагментации на IP-уровне. Настройте PMTU discovery (PLPMTUD, RFC 8899). QUIC требует MTU >= 1280 байт.
3. **0-RTT и Replay Attacks:** Даже для GET-запросов 0-RTT может быть опасен (например, повторная отправка формы через JavaScript API). Используйте Anti-Replay механизмы на уровне приложения.
4. **Connection ID exhausting:** При очень большом количестве уникальных клиентов может исчерпаться пространство Connection ID. Мониторьте метрики.
5. **HPACK Bomb:** Динамическая таблица HPACK может быть переполнена вредоносными запросами. Ограничьте количество заголовков (`max_headers`) и размер тела запроса.
6. **NAT rebinding и QUIC:** При изменении NAT-таблицы провайдера (смена порта) QUIC-соединение может быть разорвано. Connection Migration помогает, но требует Path Validation.
7. **Версионная несовместимость QUIC:** Разные версии QUIC (draft-29, v1, v2) несовместимы. Убедитесь, что клиент и сервер используют совместимые версии через Version Negotiation.
8. **TLS session resumption across versions:** Тикеты TLS 1.2 не работают для TLS 1.3 и QUIC. Настройте отдельное кэширование тикетов для TLS 1.3 (`ssl_session_cache`).
9. **Редиректы с HTTP/3:** При 301/302 редиректе клиент может вернуться на HTTP/2. Настройте сервер для приёма Alt-Svc на всех версиях.
10. **gRPC и HTTP/2 flow control:** gRPC использует HTTP/2 с большими сообщениями. Настройте `SETTINGS_MAX_FRAME_SIZE` и мониторьте `WINDOW_UPDATE`, чтобы избежать зависаний потоков.
11. **L4S и устаревшее оборудование:** L4S требует поддержки ECN на всех маршрутизаторах в пути. Устаревшее оборудование может сбрасывать пакеты с установленным ECN-битом.
12. **QUIC обработка CPU:** Обработка QUIC в User-space потребляет до 2–3 раз больше CPU, чем эквивалентный TCP-трафик. Мониторьте нагрузку на CPU при включении HTTP/3.

### Связанные разделы

- [Обзор производительности веб-приложений](./overview.md) — фундаментальные аспекты, Critical Rendering Path.
- [Ключевые метрики Web Vitals](./web_vitals.md) — детальный разбор LCP, INP, CLS, FCP, TBT.
- [Тестирование производительности](./testing_principles.md) — разница между RUM и синтетикой, методология.
- [Лучшие практики оптимизации](./best_practices.md) — пошаговое руководство по оптимизации.
- [Сжатие контента на веб-сервере](./server_compression.md) — Brotli, Zstd, Shared Dictionaries.
- [Оптимизация TLS для производительности](./tls_optimization.md) — OCSP Stapling, 0-RTT, session tickets, kTLS.
- [Инструменты анализа (DevTools, PageSpeed)](./chrome_devtools.md) — методология поиска узких мест.
- [Конфигурация HTTP/2 и HTTP/3 в Nginx/Angie](../../Nginx/Performance/nginx_http_versions.md) — детальная настройка серверов.
- [Оптимизация производительности HTTP](../../../Networking/Protocols/HTTP/http_protocols_optimization.md) — глубокий анализ транспорта, BBRv3, L4S.
- [Настройка TLS в Angie](../../WebServers/Angie/angie_tls_setup.md) — HTTP/3, kTLS, ACME, QUIC eBPF.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — graceful reload и worker_shutdown_timeout.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — логи и анализ.
