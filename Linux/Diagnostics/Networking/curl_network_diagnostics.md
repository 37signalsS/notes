# Диагностика HTTP-задержек: сеть или приложение

## Определения

**Диагностика HTTP-задержек** — процесс идентификации этапа, на котором происходит замедление обработки запроса: на уровне сетевой инфраструктуры (DNS, TCP/UDP), протоколов безопасности (TLS/QUIC) или внутри самого приложения (бэкенда).

Основным инструментом для решения этой задачи является **curl**. Благодаря опции `-w` (`--write-out`), утилита позволяет извлекать точные временные метрики и метаданные для каждого этапа жизненного цикла запроса, включая современные протоколы HTTP/2 и HTTP/3 (QUIC).

## Основные концепции

### Логика разделения слоев

Любой HTTP-запрос проходит через последовательные стадии, каждую из которых можно измерить автономно:

1.  **Сетевой слой (Network Layer):** включает разрешение имен (DNS) и установку соединения (TCP 3-way handshake или UDP для QUIC).
2.  **Слой безопасности (Security Layer):** время на выполнение TLS-рукопожатия (для HTTPS) или интегрированного QUIC-рукопожатия (для HTTP/3). Включает проверку цепочек сертификатов и OCSP-запросы.
3.  **Слой приложения (Application Layer):** время ожидания первого байта ответа (**TTFB — Time to First Byte**) после завершения всех сетевых и криптографических процедур.
4.  **Итог (Total Time):** общее время от запуска команды до завершения передачи последнего байта данных.

### DNS-резолвинг в curl: nsswitch, systemd-resolved и Happy Eyeballs

**DNS-резолвинг** в контексте curl сложнее, чем кажется: утилита использует системный вызов `getaddrinfo()`, который проходит через всю цепочку NSS (Name Service Switch), а не только `/etc/resolv.conf`.

**Путь разрешения имени в Linux:**
1.  **NSS (`/etc/nsswitch.conf`):** порядок поиска. Типичная строка `hosts: files mdns4_minimal [NOTFOUND=return] dns myhostname` означает, что перед DNS проверяется `/etc/hosts`, затем mDNS (`.local`), и только потом внешние резолверы.
2.  **systemd-resolved:** если используется, `/etc/resolv.conf` обычно указывает на `127.0.0.53`. Запрос уходит в кэш systemd-resolved, который сам идет в upstream DNS. Это добавляет latency, которую невозможно увидеть в `dig` напрямую.
3.  **Happy Eyeballs (RFC 8305):** при наличии AAAA записи curl параллельно запускает запросы A (IPv4) и AAAA (IPv6). Победитель определяется по первому ответу с таймаутом `--happy-eyeballs-timeout-ms` (по умолчанию 200 мс). Если AAAA не отвечает, curl ждет таймаут, что искусственно завышает `time_namelookup`.

**Диагностика пути разрешения:**
```bash
# strace показывает, какие файлы открывает curl при резолве
strace -e openat curl -s -o /dev/null https://example.com 2>&1 | grep -E "hosts|resolv.conf"

# Сравнение с системным резолвером (прходит через весь NSS)
time getent hosts example.com

# Прямой DNS-запрос (минует NSS и кэш)
time dig example.com +short

# Разница между getent и dig указывает на overhead NSS / systemd-resolved
```

**Типичные симптомы:**
- `time_namelookup` высокий при быстром `dig` → проблема в NSS (например, `mdns4_minimal` зависает на `.local` запросах) или systemd-resolved.
- `time_namelookup` скачкообразный → возможен overflow кэша или медленный upstream DNS.

### Влияние прокси-серверов на измеримые метрики

В корпоративных средах curl часто работает через прокси. Это вносит дополнительный "слой" в каждый запрос, и метрики нужно интерпретировать с учетом топологии:

- **HTTP-прокси для HTTPS (CONNECT tunnel):** curl сначала открывает TCP-соединение к прокси (`time_connect`), затем отправляет `CONNECT example.com:443 HTTP/1.1`, и только после успеха (`200 Connection Established`) выполняет TLS-рукопожатие к origin через туннель. Таким образом, `time_appconnect` отражает TLS до origin, а не до прокси.
- **HTTP-прокси для HTTP:** curl отправляет полный запрос прокси напрямую. `time_connect` — до прокси, `time_starttransfer` — включает задержку прокси + origin.
- **SOCKS5:** аналогично CONNECT, но на транспортном уровне. `time_connect` — до SOCKS5-прокси, `time_appconnect` — TLS через туннель.
- **Прозрачный прокси / WAF:** если прокси стоит на пути и невидим для curl (на уровне сети), он НЕ виден в метриках curl, но влияет на `time_starttransfer`.

**Диагностика прокси-задержки:**
```bash
# Базовый запрос через прокси (HTTP)
curl -w "Connect: %{time_connect}s | TLS: %{time_appconnect}s | TTFB: %{time_starttransfer}s\n" \
  --proxy http://proxy.corp:8080 -o /dev/null -s https://example.com

# Сравнение: прямой запрос (если доступен)
curl -w "Direct: Connect: %{time_connect}s | TLS: %{time_appconnect}s | TTFB: %{time_starttransfer}s\n" \
  --noproxy '*' -o /dev/null -s https://example.com

# Разница TTFB показывает overhead прокси/WAF
```

### Keepalive и пул соединений: почему последовательные curl дают разные цифры

По умолчанию **curl не переиспользует TCP-соединения** между отдельными вызовами. Каждый запуск `curl` создает новое соединение, выполняет запрос и закрывает его. Это означает, что стандартные замеры `time_connect` и `time_appconnect` всегда отражают "холодный старт".

**HTTP Persistent Connection (Keepalive)** — это механизм, при котором TCP-соединение остается открытым после завершения запроса для последующих запросов. Но curl использует его только если:
1.  В командной строке передано **несколько URL** (curl закроет соединение только после обработки всех).
2.  Используется `--next` (curl 7.85+).
3.  Включен `--parallel` и `--parallel-immediate` (curl 7.66+).

**Сравнение холодного и теплого соединения:**
```bash
# Холодный старт (новое соединение)
curl -w "Cold Total: %{time_total}s | Connect: %{time_connect}s\n" \
  -o /dev/null -s https://example.com

# Теплый старт (переиспользование в рамках одной команды)
curl -w "Warm Total: %{time_total}s | Connect: %{time_connect}s\n" \
  -o /dev/null -s https://example.com https://example.com/image.jpg https://example.com/style.css

# HTTP/2 мультиплексирование (один connect, несколько streams)
curl --http2 -w "HTTP/2 Total: %{time_total}s | Connect: %{time_connect}s\n" \
  -o /dev/null -s https://example.com https://example.com/1.png https://example.com/2.png https://example.com/3.png
```

**Интерпретация для SRE:**
- Если `time_connect` в "холодном" замере значительно выше, чем в "теплом" — проблема в настройках TCP-стека (например, низкий `tcp_syn_retries`) или высокой латентности сети для новых соединений.
- Если TTFB не меняется, а общее время снижается при reuse —瓶颈 в TCP/TLS установке, а не в бэкенде.

### HTTP/2, HTTP/3 и особенности замера

**HTTP/2:**
- Использует бинарный фрейминг через одно TCP/TLS соединение.
- ALPN (Application-Layer Protocol Negotiation) происходит во время TLS-рукопожатия. Если сервер предлагает `h2`, curl принимает его.
- **Head-of-Line Blocking на уровне TCP:** медленный stream может блокировать передачу данных в других streams, так как они share один TCP-поток.
- `time_starttransfer` в HTTP/2 измеряет время до первого байта в ОТВЕТЕ на конкретный stream, но если сервер переполнен, TTFB может быть высоким из-за блокировки.

**HTTP/3 (QUIC):**
- TLS 1.3 встроен в QUIC (0-RTT или 1-RTT).
- `time_connect` и `time_appconnect` часто близки или равны, потому что QUIC объединяет транспорт и безопасность.
- Отдельные потоки (streams) QUIC не подвержены Head-of-Line Blocking: потеря пакета влияет только на один stream.

**Практические замеры:**
```bash
# Сравнение HTTP/1.1, HTTP/2, HTTP/3 на одном хосте
for proto in "" "--http1.1" "--http2" "--http3"; do
  label=$(echo $proto | sed 's/--http/HTTP\//' | sed 's/^$/HTTP\/1.1 default/')
  curl -s -o /dev/null -w "$label: Connect=%{time_connect}s TLS=%{time_appconnect}s TTFB=%{time_starttransfer}s Total=%{time_total}s\n" \
    $proto https://example.com
done
```

### Расширенные метрики curl

Для глубокого анализа используются следующие переменные (доступны через `%{variable_name}`):

| Метрика | Описание | Слой |
| :--- | :--- | :--- |
| `time_namelookup` | Время разрешения DNS-имени. Зависит от `/etc/resolv.conf` и внешних резолверов. | Сеть (L3/L7) |
| `time_connect` | Время установки TCP соединения (или UDP для QUIC). | Сеть (L4) |
| `time_appconnect` | Время завершения SSL/TLS/QUIC рукопожатия. На него влияет OCSP Stapling и длина цепочки сертификатов. | Безопасность |
| `time_pretransfer` | Время от старта до момента, когда curl готов начать передачу данных (включает логику клиента и согласование протоколов). | Подготовка |
| `time_redirect` | Суммарное время всех редиректов (нахождение в цепочке 3xx ответов). | Навигация |
| `time_starttransfer` | **TTFB**. Время до получения первого байта ответа. Критическая метрика производительности бэкенда. | Приложение |
| `time_total` | Полное время выполнения всей операции (до последнего байта). | Итого |
| `speed_download` | Средняя скорость загрузки в байтах в секунду. | Пропускная способность |
| `size_header` | Суммарный размер полученных заголовков. | Метаданные |
| `remote_ip` | IP-адрес узла, к которому было выполнено подключение (помогает выявить проблемы с Anycast/CDN). | Диагностика |
| `remote_port` | Порт удаленного узла. | Диагностика |
| `http_version` | Версия протокола (например, `3` для HTTP/3). | Протокол |
| `ssl_verify_result` | Результат проверки сертификата (`0` = успех). | Валидация |
| `num_connects` | Количество установленных соединений (полезно при `--parallel`). | Подготовка |
| `time_appconnect` | Время завершения SSL/TLS/QUIC рукопожатия. | Безопасность |

## Практические сценарии

### 1. Детальный анализ таймингов (Стандартная диагностика)

Использование форматированного вывода для получения точных цифр по слоям:

```bash
curl -w "IP: %{remote_ip} | DNS: %{time_namelookup}s | Connect: %{time_connect}s | TLS: %{time_appconnect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s | Ver: %{http_version}\n" \
  -o /dev/null -s https://example.com
# → IP: 93.184.216.34 | DNS: 0.001234s | Connect: 0.015432s | TLS: 0.045678s | TTFB: 0.089012s | Total: 0.091234s | Ver: 2
```

### 2. Диагностика HTTP/3 (QUIC) и 0-RTT

QUIC объединяет TCP и TLS в один процесс. В режиме **0-RTT** (Resumption) передача данных может начаться одновременно с рукопожатием.

```bash
# Проверка поддержки HTTP/3 и времени рукопожатия
curl -s -o /dev/null --http3 \
  -w "Protocol: HTTP/%{http_version}\nHandshake: %{time_appconnect}s\nConn ID: %{conn_id}\n" \
  https://example.com
```
*Примечание: Если `time_appconnect` значительно ниже, чем сумма `time_connect` + `time_appconnect` в режиме TCP (HTTP/2), это подтверждает эффективность QUIC за счет уменьшения количества round-trips.*

### 3. Изоляция DNS и ALPN (Application-Layer Protocol Negotiation)

Сравнение обычного запроса с запросом по конкретному IP помогает исключить задержки на этапе DNS и проверить корректность выбора протокола (например, h2 или h3).

```bash
# Принудительное разрешение на конкретный IP (bypass DNS)
curl -v --resolve example.com:443:93.184.216.34 https://example.com
# → * ALPN, offering h2
# → * SSL connection using TLSv1.3 / h2
```

### 4. Тестирование стабильности и Tail Latency

Выявление плавающих задержек на балансировщиках нагрузки или "хвостовых" задержек (P99/P99.9) через цикл:

```bash
for i in {1..20}; do \
  curl -o /dev/null -s -w "Attempt $i: Total=%{time_total}s TTFB=%{time_starttransfer}s Code=%{http_code}\n" https://example.com; \
done
```

### 5. Локальный против внешнего TTFB

Позволяет определить, вносится ли задержка сетевым контуром (Firewall, WAF, CDN) или логикой бэкенда.

```bash
# Прямой запрос к приложению (внутри сервера/пода)
curl -o /dev/null -s -w "Internal TTFB: %{time_starttransfer}s\n" http://localhost:8080

# Запрос через внешний балансировщик (Ingress/CDN)
curl -o /dev/null -s -w "External TTFB: %{time_starttransfer}s\n" https://api.example.com
```

### 6. Влияние HSTS и OCSP

Curl может тратить время на чтение HSTS-кеша (`~/.curl_hsts`) и выполнение OCSP-запросов для проверки статуса отзыва сертификата, если OCSP Stapling не настроен на сервере.

```bash
# Использование curl с включенным OCSP-статусом
curl --cert-status -v https://example.com 2>&1 | grep -i "OCSP"
```

### 7. Диагностика прокси и корпоративных шлюзов

В корпоративных сетях прямой доступ в интернет часто запрещён. Прокси добавляет собственную латентность, которую важно отделять от латентности целевого сервиса.

**Измерение задержки прокси:**
```bash
# Запрос через HTTP-прокси (HTTP-сайт)
curl -w "Connect: %{time_connect}s | TTFB: %{time_starttransfer}s\n" \
  --proxy http://proxy.corp:8080 -o /dev/null -s http://httpbin.org/get

# Запрос через HTTPS-прокси (CONNECT tunnel)
curl -w "Connect: %{time_connect}s | TLS: %{time_appconnect}s | TTFB: %{time_starttransfer}s\n" \
  --proxy http://proxy.corp:8080 -o /dev/null -s https://example.com

# Сравнение с прямым доступом (если доступен)
curl -w "Direct: Connect: %{time_connect}s | TLS: %{time_appconnect}s | TTFB: %{time_starttransfer}s\n" \
  --noproxy '*' -o /dev/null -s https://example.com
```

**Проверка аутентификации на прокси:**
```bash
# Задержка от proxy auth
time curl -s -o /dev/null --proxy http://proxy.corp:8080 --proxy-user user:pass https://example.com

# Без аутентификации (если прокси разрешает)
time curl -s -o /dev/null --proxy http://proxy.corp:8080 https://example.com
```

**Типичные проблемы:**
- **Циклический редирект:** прокси возвращает 302 на сам себя. Решение — проверить `no_proxy` и конфигурацию прокси.
- **CONNECT refused:** firewall блокирует порт 443/8443 для CONNECT метод. Решение — `iptables -L` или проверка конфигурации прокси.
- **Нерешенный хост через прокси:** если прокси пытается резолвить DNS вместо клиента (SOCKS5 без `--socks5-hostname`), проверьте upstream DNS прокси.

### 8. Глубокая отладка TLS и HTTP через `--trace`

Опции `--trace` и `--trace-ascii` позволяют увидеть полный обмен данными между curl и сервером, включая TLS-рукопожатие и HTTP-заголовки.

```bash
# Полный trace с временными метками (дельта между пакетами)
curl --trace-time --trace-ascii - https://example.com 2>&1 | head -60

# Извлечение конкретных этапов
curl --trace-ascii - https://example.com 2>&1 | grep -E "TLS|ALPN|Cipher|HTTP"
# → == Info: TLSv1.3 (OUT), TLS handshake, Client hello
# → == Info: TLSv1.3 (IN), TLS handshake, Server hello
# → == Info: ALPN, server accepted h2
```

**Определение версии TLS и cipher suite:**
```bash
curl -v https://example.com 2>&1 | grep -E "SSL connection|Cipher|ALPN"
# → * SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384 / h2
```

**Определение причины отказа TLS:**
```bash
# Если handshake падает, trace покажет точный этап
curl --trace-ascii - https://self-signed.example.com 2>&1 | grep -E "SSL|error|alert"
# → == Info: TLSv1.3 (OUT), TLS alert, handshake failure
```

**Сравнение времени TLS через trace:**
```bash
START=$(date +%s%N)
curl --trace-ascii /dev/null -o /dev/null -s https://example.com 2>&1 | awk '/TLS handshake/ {print $1}'
END=$(date +%s%N)
echo "TLS handshake duration: $(( (END - START) / 1000000 )) ms"
```

### 9. Тестирование IPv6, dual-stack и Happy Eyeballs

Современные серверы часто доступны по IPv4 и IPv6. Разница в латентности или недоступность одного из стеков может быть причиной нестабильной работы.

**Принудительное тестирование по栈:**
```bash
# Только IPv4
curl -4 -w "IPv4: DNS=%{time_namelookup}s Connect=%{time_connect}s Total=%{time_total}s\n" \
  -o /dev/null -s https://example.com

# Только IPv6
curl -6 -w "IPv6: DNS=%{time_namelookup}s Connect=%{time_connect}s Total=%{time_total}s\n" \
  -o /dev/null -s https://example.com

# Автоматический выбор (Happy Eyeballs)
curl -w "Auto: DNS=%{time_namelookup}s Connect=%{time_connect}s Total=%{time_total}s Ver=%{http_version}\n" \
  -o /dev/null -s https://example.com
```

**Корреляция с traceroute:**
```bash
# Если IPv6 значительно медленнее IPv4
mtr -6 -c 10 example.com
mtr -4 -c 10 example.com
```

**Happy Eyeballs timeout:**
```bash
# Уменьшить таймаут Happy Eyeballs (по умолчанию 200 мс)
curl --happy-eyeballs-timeout-ms 50 -6 -w "IPv6 fast fail: Total=%{time_total}s\n" \
  -o /dev/null -s https://example.com
```

### 10. Анализ переиспользования соединений (Keepalive)

Для оценки влияния пула соединений на латентность:

```bash
# 1. Холодный старт (каждый запуск = новое соединение)
for i in 1 2 3; do
  curl -w "Run $i: Connect=%{time_connect}s TTFB=%{time_starttransfer}s\n" \
    -o /dev/null -s https://example.com
done

# 2. Теплый старт (переиспользование в рамках одной команды)
curl -w "Reused: Connect=%{time_connect}s TTFB=%{time_starttransfer}s\n" \
  -o /dev/null -s https://example.com https://example.com/1.png https://example.com/2.png

# 3. HTTP/2 мультиплексирование (один TCP, много streams)
curl --http2 -w "HTTP/2: Connect=%{time_connect}s TTFB=%{time_starttransfer}s\n" \
  -o /dev/null -s https://example.com https://example.com/a.js https://example.com/b.css
```

**Ожидаемый результат:** при reuse `time_connect` должен стремиться к 0, а разница в `time_total` отражает только TTFB бэкенда.

### 11. mTLS и внутренние Certificate Authorities

Внутренние сервисы часто используют mTLS (взаимная аутентификация) или внутренние CA.

**Базовый замер TLS:**
```bash
curl -w "TLS: %{time_appconnect}s Verify: %{ssl_verify_result}\n" \
  --cacert /etc/ssl/certs/internal-ca.crt -o /dev/null -s https://service.corp/api
# ssl_verify_result: 0 = успех, остальное = ошибка валидации
```

**Замер mTLS:**
```bash
curl -w "mTLS: %{time_appconnect}s\n" \
  --cert client.crt --key client.key --cacert ca.crt \
  -o /dev/null -s https://service.corp/api
```

**Сравнение overhead mTLS:**
```bash
# Без клиентского сертификата
curl -w "No mTLS: %{time_appconnect}s\n" --cacert ca.crt -o /dev/null -s https://service.corp/api

# С клиентским сертификатом
curl -w "With mTLS: %{time_appconnect}s\n" --cert client.crt --key client.key --cacert ca.crt -o /dev/null -s https://service.corp/api
```

**Диагностика отзыва сертификата (OCSP):**
```bash
# Проверка OCSP Stapling
curl --cert-status -v https://service.corp/api 2>&1 | grep -i "OCSP"
# → * OCSP response: successful

# Если OCSP не настроен — curl делает внешний запрос к OCSP responder
# Это видно по задержке в time_appconnect
```

### 12. Корреляция curl с ss и tcpdump

Для глубокой диагностики связываем curl-метрики с состоянием сокетов и захватом пакетов.

**Получение endpoint из curl:**
```bash
IP=$(curl -s -o /dev/null -w "%{remote_ip}" https://example.com)
PORT=$(curl -s -o /dev/null -w "%{remote_port}" https://example.com)
echo "Target: $IP:$PORT"
```

**Корреляция с ss:**
```bash
# Просмотр сокета в состоянии ESTABLISHED
sudo ss -tin dst $IP dport = :$PORT
# → cubic wscale:7,7 rto:204 rtt:15.2/0.5 ato:40 mss:1448
# → cwnd:10 bytes_acked:15002048 retrans:0/125 delivery_rate 120Mbps

# Связка с PID приложения (если curl запущен из известного процесса)
sudo ss -tinp | grep "$IP:$PORT"
```

**Корреляция с tcpdump:**
```bash
# Захват handshake для конкретного curl-запроса
sudo tcpdump -i eth0 -nn host $IP and port $PORT -c 10 -w /tmp/curl_debug.pcap

# Анализ в реальном времени
sudo tcpdump -i eth0 -nn host $IP and port $PORT -l | grep -E "SYN|ACK|RTT"
```

**Замер RTT через ss во время curl:**
```bash
# Запуск curl в фоне
curl -s -o /dev/null https://example.com &
CURL_PID=$!

# Сбор RTT из ss (повторяем несколько раз)
for i in 1 2 3 4 5; do
  sudo ss -tin state established '( dport = :443 )' | grep -oP "rtt:\K[\d.]+"
  sleep 0.5
done

wait $CURL_PID
```

### 13. Оценка пропускной способности и деградации линии

**Измерение скорости загрузки:**
```bash
# Скорость в байтах/сек
curl -o /dev/null -s -w "Speed: %{speed_download} bytes/sec\n" https://example.com/large-file.iso

# В человекочитаемом виде
curl -o /dev/null -s -w "Speed: %{speed_download}\n" https://example.com/large-file.iso | \
  awk '{print $1/1024/1024 " MB/s"}'
```

**Искусственное ограничение скорости:**
```bash
# Ограничение до 1 MB/s
curl --limit-rate 1M -o /dev/null -s -w "Limited: %{speed_download} bytes/sec\n" https://example.com/large-file

# Сравнение без ограничения
curl -o /dev/null -s -w "Unlimited: %{speed_download} bytes/sec\n" https://example.com/large-file
```

**Пороговая скорость и прерывание:**
```bash
# Прервать, если скорость упадет ниже 100 KB/s на 30 секунд
curl --speed-limit 100000 --speed-time 30 -o /dev/null -s -w "Exit code: %{exitcode}\n" https://example.com
# Exit code 28 = operation timeout
```

### 14. Диагностика кэширования и валидации (ETag, Last-Modified)

Curl по умолчанию не кэширует ответы, но может использоваться для тестирования поведения кэширующих прокси и CDN.

**Получение валидаторов:**
```bash
# ETag и Last-Modified
curl -sI https://api.example.com/data | grep -iE "etag|last-modified"
# → ETag: "33a64df551425fcc55e4d42a148795d9f25f89d4"
# → Last-Modified: Wed, 21 Oct 2015 07:28:00 GMT
```

**Условный запрос (If-None-Match):**
```bash
ETAG=$(curl -sI https://api.example.com/data | grep -i etag | tr -d '\r' | awk '{print $2}')
curl -sI -H "If-None-Match: $ETAG" https://api.example.com/data
# → HTTP/1.1 304 Not Modified (если данные не изменились)
# → time_starttransfer будет значительно ниже, чем при полной загрузке
```

**Условный запрос по времени (If-Modified-Since):**
```bash
curl -sI -H "If-Modified-Since: Wed, 21 Oct 2015 07:28:00 GMT" https://api.example.com/data
```

**Проверка Cache-Control:**
```bash
curl -sI https://example.com/static/app.js | grep -i "cache-control"
# → Cache-Control: public, max-age=31536000, immutable
```

**Использование файла для условного запроса (`-z`):**
```bash
touch -d "2024-01-01" local_copy.html
curl -z local_copy.html -o local_copy.html -w "Downloaded: %{size_download} bytes\n" https://example.com/
# Скачает только если удаленный файл новее 2024-01-01
```

### 15. Автоматизированные скрипты для SRE

Скрипты для регулярной диагностики и мониторинга.

**Скрипт сбора метрик в JSON:**
```bash
#!/bin/bash
# curl_diag_collector.sh
TARGET=${1:-https://example.com}
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

curl -s -o /dev/null -w '{\
  "timestamp": "%{time_starttransfer}",\
  "url": "'"$TARGET"'",\
  "dns_ms": %{time_namelookup}*1000,\
  "connect_ms": %{time_connect}*1000,\
  "tls_ms": %{time_appconnect}*1000,\
  "ttfb_ms": %{time_starttransfer}*1000,\
  "total_ms": %{time_total}*1000,\
  "http_version": %{http_version},\
  "remote_ip": "%{remote_ip}",\
  "http_code": %{http_code},\
  "size_download": %{size_download},\
  "speed_download_bps": %{speed_download}\
}\n' "$TARGET" | jq .
```

**Скрипт мониторинга с алертингом:**
```bash
#!/bin/bash
# curl_health_check.sh
TARGETS=(
  "https://example.com|200|0.5"
  "https://api.example.com/health|200|0.3"
)

ALERT_WEBHOOK="https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"

for entry in "${TARGETS[@]}"; do
  IFS='|' read -r url expected_code max_ttfb <<< "$entry"
  
  ttfb=$(curl -s -o /dev/null -w "%{time_starttransfer}" "$url")
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  
  if [ "$code" != "$expected_code" ] || (( $(echo "$ttfb > $max_ttfb" | bc -l) )); then
    MESSAGE="ALERT: $url Code=$code TTFB=${ttfb}s (threshold ${max_ttfb}s)"
    curl -s -X POST -H 'Content-type: application/json' \
      --data "{\"text\":\"$MESSAGE\"}" "$ALERT_WEBHOOK"
  fi
done
```

**Мониторинг через systemd-timer:**
```ini
# /etc/systemd/system/curl-health-check.service
[Unit]
Description=HTTP Health Check via curl

[Service]
Type=oneshot
ExecStart=/usr/local/bin/curl_health_check.sh

# /etc/systemd/system/curl-health-check.timer
[Unit]
Description=Run health check every 60 seconds

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
Persistent=true

[Install]
WantedBy=timers.target
```

## Дополнительная информация

### Расширенная матрица устранения неисправностей

| Симптом | Вероятная причина | Рекомендуемые действия |
| :--- | :--- | :--- |
| **Высокий `namelookup`** | Медленный DNS, IPv6 timeout (если AAAA не отвечает), проблемы в `/etc/resolv.conf`, systemd-resolved lag. | Проверить **[Обзор DNS](./dns/overview.md)**, использовать флаг `-4` для теста, сравнить с `getent hosts` и `dig`. |
| **Высокий `pretransfer`** | Прокси-авторизация, TLS session reuse miss, OCSP-запрос, задержка ALPN. | Проверить proxy logs, `ssl_verify_result`, `--cert-status`. |
| **Высокий `connect`** | Сетевые потери, перегрузка канала, Firewall, SYN-queue переполнение. | Проверить **[mtr / traceroute](./traceroute_mtr.md)**, **[ss](./ss.md)** (`ss -s`, `ss -tin`), `nstat -az \| grep Retrans`. |
| **Высокий `appconnect`** | CPU-bound сервер (TLS), отсутствие OCSP Stapling, длинные цепочки сертификатов, mTLS overhead. | Обновить до TLS 1.3, проверить **[Оптимизация TLS](../../../WebServers/Concepts/web_performance/tls_optimization.md)**, протестировать с `--trace`. |
| **Высокий `starttransfer`** | Медленный бэкенд, блокировки в БД, внешние API-вызовы внутри запроса, Head-of-Line Blocking в HTTP/2. | Анализ логов приложения, профилирование, сравнение локального и внешнего TTFB. |
| **Высокий `redirect`** | Неоптимальная цепочка перенаправлений (например, HTTP -> HTTPS -> WWW). | Исправить конфигурацию веб-сервера (Angie/Nginx) на прямой редирект, использовать `-L --max-redirs 5`. |
| **Низкий `speed_download`** | Ограничение bandwidth на стороне сервера, утечка TCP, фрагментация, плохой канал. | Проверить `ss -ti` (cwnd, delivery_rate), `ethtool -S`, `tc -s qdisc`. |
| **HTTP/1.1 вместо HTTP/2** | ALPN не сработал, старый curl, сервер не поддерживает h2. | Проверить `curl --version | grep HTTP2`, `-v` на предмет `ALPN, offering h2`. |
| **HTTP/3 не работает** | Блокировка UDP порта 443 на Firewall или проблемы с MTU (пакеты QUIC отбрасываются). | Проверить `nc -zu host 443` и `tracepath`. |
| **TLS handshake failure (exit 35)** | Несовместимость cipher, устаревший TLS, неправильный SNI. | `openssl s_client -connect host:443 -servername host`, проверить `--trace`. |
| **SSL certificate problem (exit 60)** | Самоподписанный сертификат, неверный CA bundle, истекший срок. | Использовать `--cacert`, `--insecure` (только для отладки). |
| **Operation timeout (exit 28)** | `--max-time` истек, очень медленная сеть, зависший TCP retransmit. | Увеличить таймаут, проверить `ss -s` (time-wait, orphaned). |
| **Couldn't connect to host (exit 7)** | Хост недоступен, порт закрыт, firewall DROP. | `nc -zv host port`, `ss -ltnp`, `iptables -L`. |

### Важное для 2026 года: Стабильность и безопасность

*   **CVE-2026-11352:** Убедитесь, что используете **curl 8.21.0** или выше. В более ранних версиях обработка пустых UDP-датаграмм в QUIC приводила к бесконечному циклу (busy-loop), что искусственно завышало CPU-метрики и задержки.
*   **ALPN (Application-Layer Protocol Negotiation):** Всегда проверяйте в `-v`, какой протокол был выбран. Использование HTTP/1.1 там, где ожидается HTTP/2, является частой причиной высокого TTFB из-за отсутствия мультиплексирования.
*   **BBRv3 и L4S:** Современные ядра Linux (5.20+) используют BBRv3 по умолчанию. Это влияет на `cwnd` и `delivery_rate`, видимые в `ss -ti`. Если после обновления ядра TTFB вырос — проверьте, не переключился ли congestion control на более консервативный алгоритм (например, Cubic).
*   **TLS 1.3 deprecation of TLS 1.0/1.1:** Все современные сборки curl отключают старые версии по умолчанию. Если `curl -v` показывает `SSL connection using TLSv1.2`, а ожидается 1.3 — проверяйте cipher suites на сервере.

### Пограничные случаи и ограничения curl

1.  **Коды возврата (Exit Codes):** curl возвращает различные коды при сбоях. В скриптах всегда проверяйте `$?` или используйте `-f` (`--fail`), чтобы превратить HTTP 4xx/5xx в ненулевой exit code.
    - `0` — успех.
    - `6` — couldn't resolve host (DNS).
    - `7` — couldn't connect to host (TCP).
    - `28` — operation timeout.
    - `35` — SSL connect error (TLS handshake failed).
    - `60` — SSL certificate problem.
    - `22` — HTTP page not retrieved (с `-f` при 4xx/5xx).
2.  **Одновременный запуск нескольких curl:** при использовании `--parallel` метрики `time_connect` и `time_appconnect` усредняются или показывают максимальные значения, что делает их менее полезными для детального анализа.
3.  **DNS over HTTPS/TLS:** если в системе используется DoH или DoT через systemd-resolved, `time_namelookup` включает задержку TLS-рукопожатия к резолверу. Это может маскировать реальную DNS-латентность.
4.  **Unix-сокеты:** при использовании `--unix-socket` метрики `time_namelookup` и `time_connect` равны 0, так как сетевой стек не участвует.
5.  **HTTP/2 Server Push:** curl получает pushed ресурсы как обычные ответы. `time_starttransfer` для pushed ресурсов включает время, которое сервер затратил на генерацию, но не сетевую латентность (так как push идет по тому же соединению).
6.  **Многопоточные приложения:** `ss -p` показывает только основной поток процесса. Для всех потоков используйте `ss -p` + `pthread` IDs или `lsof -p <pid>`.

### Мониторинг и алертинг

**Интеграция с Prometheus (Pushgateway):**
```bash
#!/bin/bash
# push_curl_metrics.sh
METRICS=$(curl -s -o /dev/null -w \
  "curl_ttfb_seconds{url=\"$1\"} %{time_starttransfer}\n\
   curl_total_seconds{url=\"$1\"} %{time_total}\n\
   curl_connect_seconds{url=\"$1\"} %{time_connect}\n" \
  "$1")

echo "$METRICS" | curl --data-binary @- http://pushgateway:9091/metrics/job/curl_diag
```

**Alertmanager правило (пример):**
```yaml
groups:
  - name: curl_diag_alerts
    rules:
      - alert: HighCurlTtfb
        expr: curl_ttfb_seconds > 0.5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High TTFB for {{ $labels.url }}"
          description: "TTFB is {{ $value }}s."
```

### Связанные инструменты

- **[cURL: справочник опций](../../Networking/Tools/http_clients/curl.md)** — общие команды.
- **[mtr / traceroute](./traceroute_mtr.md)** — диагностика L3/L4 пути.
- **[ss](./ss.md)** — детальный анализ TCP-сокетов (SSoT).
- **[nstat](./network_cli_tools.md)** — просмотр счетчиков сетевого стека.
- **[tcpdump](./tcpdump.md)** — захват трафика для корреляции с метриками curl.
- **[traceroute и mtr](./traceroute_mtr.md)** — диагностика сетевого пути.
- **[DNS: обзор](./dns/overview.md)** — понимание разрешения имен.
- **[Оптимизация TLS](../../../WebServers/Concepts/web_performance/tls_optimization.md)** — настройка безопасности.
- **[openssl s_client](https://man.openbsd.org/openssl/openssl-s_client)** — ручная проверка TLS.
