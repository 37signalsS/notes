# Полезные ссылки и инструментарий веб-серверов и анализа производительности

**Актуально для:** Nginx 1.26+ / Angie 1.8+ / HAProxy 3.0+ / Apache 2.4 / Traefik 3.x / Caddy 2.11+ / Linux 5.x/6.x

## Определения

**Веб-сервер** — программное обеспечение, принимающее клиентские сетевые запросы по протоколам HTTP/HTTPS, осуществляющее обработку и отдачу статических ресурсов или делегирующее исполнение запросов бэкенд-приложениям через стандартные интерфейсы (FastCGI, WSGI, ASGI, SCGI, HTTP Reverse Proxy).

**Reverse Proxy (Обратный прокси-сервер)** — промежуточный сервер, расположенный перед внутренней инфраструктурой приложений. Принимает клиентские запросы из внешней сети, маршрутизирует их к целевым серверам бэкенда, выполняет терминирование TLS, кэширование, компрессию, ограничение интенсивности запросов (Rate Limiting) и сокрытие внутренней топологии сети.

**Static Analysis (Статический аудит конфигураций)** — метод инспекции файлов конфигурации веб-сервера без запуска рабочего процесса или передачи сетевого трафика. Проверяет синтаксические деревья (AST), порядок обработки правил, уязвимости директив (Alias Traversal, SSRF, небезопасные регулярные выражения, инъекции заголовков).

**AST (Abstract Syntax Tree, абстрактное синтаксическое дерево)** — древовидная структура данных, формируемая анализатором из текстовых директив конфигурации веб-сервера для глубокого контекстного анализа областей видимости (`http`, `server`, `location`, `frontend`, `backend`).

**Synthetic Monitoring (Синтетический мониторинг)** — метод активного тестирования веб-серверов и сервисов путем периодической эмуляции клиентских запросов по заданным сценариям из контролируемых тестовых зон для измерения доступности, времени отклика и соответствия SLA/SLO.

**RUM (Real User Monitoring)** — пассивный сбор и анализ телеметрии производительности, отправляемой реальными браузерами и клиентами конечных пользователей через специализированные браузерные Performance API.

**Core Web Vitals** — стандартизированный набор метрик клиентской производительности:
- **LCP (Largest Contentful Paint):** время отрисовки самого крупного визуального блока контента в области просмотра (целевое значение: <= 2.5 с).
- **INP (Interaction to Next Paint):** отзывчивость страницы на действия пользователя (клик, нажатие клавиши) до момента визуального обновления экрана (целевое значение: <= 200 мс).
- **CLS (Cumulative Layout Shift):** суммарный сдвиг визуальной разметки страницы в процессе загрузки (целевое значение: <= 0.1).

**TTFB (Time to First Byte)** — длительность временного интервала от момента отправки первого байта HTTP-запроса клиентом до момента получения первого байта ответа от веб-сервера. Включает время сетевой передачи, задержки очередей и время генерации ответа бэкендом.

**Coordinated Omission (Скоординированный пропуск)** — фундаментальная погрешность измерений задержки в бенчмаркерах с закрытым циклом нагрузки (Closed Loop). При возникновении задержки ответа сервера нагрузчик приостанавливает генерацию последующих запросов, что исключает из финальной статистики запросы, которые должны были поступить по расписанию, и занижает перцентили задержки (p95, p99).

**Closed Loop vs Open Loop Testing**:
- **Closed Loop (модель с фиксированной конкурентностью):** новый запрос инициируется только после завершения предыдущего. Скорость подачи нагрузки напрямую зависит от времени ответа тестируемой системы.
- **Open Loop (модель с заданным темпом / Rate-based):** запросы генерируются со строго фиксированной частотой независимо от текущей скорости ответа сервера. Позволяет выявлять реальные деградации очередей и каскадные отказы.

---

## Архитектура и классификация экосистемы

### Архитектурные модели веб-серверов и прокси

Инструменты обработки трафика и балансировки различаются базовыми моделями обработки ввода-вывода (I/O) операционной системы:

| Модель архитектуры | Представители | Механизм I/O ядра Linux | Характеристики и область применения |
| :--- | :--- | :--- | :--- |
| **Event-driven (Single-threaded / Multi-worker)** | Nginx, Angie, Lighttpd | `epoll`, `kqueue`, неблокирующие сокеты | Минимальное потребление памяти на соединение, устойчивость к C10K/C1000K, эффективная отдача статики и reverse proxy. |
| **Event-driven High Performance Proxy (C)** | HAProxy | `epoll`, специализированный планировщик событий, zero-copy splice | Предельная пропускная способность L4/L7, детальный ACL-движок, минимальный latency jitter. |
| **Process/Thread-based (Hybrid Worker/Event)** | Apache HTTP Server (`mpm_event`, `mpm_worker`) | Сочетание пула потоков с `epoll` для keep-alive соединений | Высокая модульность (`.htaccess`, runtime-модули языков), выше накладные расходы RAM на поток. |
| **Goroutine / Go Runtime** | Traefik, Caddy | Go runtime network poller (`epoll`), управляемые горутины | Встроенная динамическая маршрутизация, нативный автоматический ACME/TLS, быстрая расширяемость плагинами. |

### Многоуровневая модель аудита и валидации

Комплексный аудит веб-сервера в SRE/DevOps-практике состоит из последовательных фаз проверки:

```
[Фаза 1: Синтаксис]    → Проверка синтаксиса файлов конфигурации (CLI syntax gates)
       ↓
[Фаза 2: AST-аудит]    → Статический анализ директив и безопасности (Gixy-Next, линтеры)
       ↓
[Фаза 3: Криптография] → Аудит TLS/SSL, протоколов, cipher suites и OCSP (testssl.sh, SSL Labs)
       ↓
[Фаза 4: Заголовки]    → Валидация HTTP-заголовков безопасности (CSP, HSTS, Security Headers)
       ↓
[Фаза 5: Сетевые фазы] → Декомпозиция таймингов TCP/TLS/TTFB (curl, ngrep, tcpdump)
       ↓
[Фаза 6: Бенчмаркинг]  → Нагрузочные испытания открытого цикла (wrk2, Vegeta, k6)
       ↓
[Фаза 7: Мониторинг]   → Профилирование access-логов и телеметрии (GoAccess, metrics)
```

---

## Практические сценарии и конфигурация

### Сценарий 1: Автоматизированный статический аудит конфигураций (Gixy-Next)

Оригинальный анализатор Gixy (Yandex) устарел и не поддерживается в современных дистрибутивах Linux. Актуальным поддерживаемым форком для аудита конфигураций Nginx и Angie является **Gixy-Next** на базе Python 3.

Инструмент строит абстрактное синтаксическое дерево (AST) конфигурации и проверяет директивы на критические уязвимости:
- **Alias Traversal:** обход каталогов при отсутствии завершающего слэша в директиве `location` при наличии завершающего слэша в `alias`.
- **SSRF (Server-Side Request Forgery):** небезопасное использование непроверенных клиентских переменных в директиве `proxy_pass`.
- **HTTP Response Splitting:** инъекция символов переноса строки (`\r\n`) через заголовки или переменные.
- **Multiline Regex Flaw:** использование `.*` в регулярных выражениях директив `rewrite` без якорей строк `^` и `$`.

**Установка и запуск Gixy-Next в изолированном окружении:**

```bash
# Создание виртуального окружения и установка Gixy-Next
python3 -m venv /opt/gixy-env
/opt/gixy-env/bin/pip install --upgrade pip
/opt/gixy-env/bin/pip install gixy-next

# Запуск проверки конфигурационного файла
/opt/gixy-env/bin/gixy /etc/nginx/nginx.conf
# → ====================
# → Total issues: 1
# → ====================
# → >> Issue: [alias_traversal] Path traversal via misconfigured alias
# → Severity: HIGH
# → Location: /etc/nginx/conf.d/static.conf:14
# → Directive: alias /data/images/;
# → Reason: location /img does not end with a slash while alias /data/images/ does.
```

**Исправление обнаруженного дефекта Alias Traversal:**

```nginx
# ОШИБКА: Запрос /img../secret.txt транслируется в /data/images/../secret.txt
location /img {
    alias /data/images/;
}

# КОРРЕКТНАЯ КОНФИГУРАЦИЯ: Обязательное совпадение завершающих слэшей
location /img/ {
    alias /data/images/;
}
```

### Сценарий 2: Комплексный локальный аудит SSL/TLS через testssl.sh (On-premise / CI/CD)

В отличие от публичных онлайн-сканеров, утилита `testssl.sh` является автономным Bash-скриптом, использующим локальный binary OpenSSL. Она не отправляет доменные имена и IP-адреса третьим сторонам, поддерживает проверку любых TCP-портов (HTTPS, SMTPS, IMAPS, FTPS, LDAPS), работает внутри изолированных периметров (DMZ, корпоративные сети) и интегрируется в пайплайны автоматизации.

**Установка и проведение комплексного сканирования:**

```bash
# Клонирование стабильной ветки репозитория
git clone --depth 1 https://github.com/drwetter/testssl.sh.git /opt/testssl.sh
cd /opt/testssl.sh

# Запуск проверки хоста с генерацией структурированного JSON-отчета
./testssl.sh --fast --pfs --hsts --headers --jsonfile /tmp/tls_audit.json https://web.internal.local:443
# → Testing protocols via sockets except NPN+ALPN
# → SSLv2      not offered (OK)
# → SSLv3      not offered (OK)
# → TLS 1      not offered
# → TLS 1.1    not offered
# → TLS 1.2    offered (OK)
# → TLS 1.3    offered (OK): final
# →
# → Testing cipher categories
# → NULL ciphers (no encryption)                  not offered (OK)
# → Anonymous NULL Ciphers (no authentication)    not offered (OK)
# → Export ciphers (w/o 56-bit DES)               not offered (OK)
# → LOW: 64 Bit + DES, RC[2,4]                    not offered (OK)
# → Triple DES Ciphers / SWEET32                  not offered (OK)
# → High grade encryption (AES, Camellia, ChaCha)  offered (OK)
# →
# → Testing vulnerabilities
# → Heartbleed (CVE-2014-0160)                    not vulnerable (OK)
# → CCS (CVE-2014-0224)                           not vulnerable (OK)
# → ROBOT                                         not vulnerable (OK)
# → Secure Renegotiation (RFC 5746)               supported (OK)
# → Forward Secrecy / PFS                         supported (OK)
```

### Сценарий 3: Профилирование сетевых фаз HTTP/HTTPS через curl

Для детальной диагностики сетевых задержек, разрешения DNS, установления TCP-сессии и времени TLS-рукопожатия используется встроенный механизм форматирования вывода `curl` без привлечения сторонних агентов.

**Создание файла шаблона форматирования (`/tmp/curl-format.txt`):**

```text
    Время разрешения DNS:      %{time_namelookup}s
    Установление TCP сокета:   %{time_connect}s
    Завершение TLS handshake:  %{time_appconnect}s
    Подготовка запроса:        %{time_pretransfer}s
    Время до первого байта:    %{time_starttransfer}s
    -------------------------------------------------
    Суммарное время ответа:    %{time_total}s
    Код ответа HTTP:           %{http_code}
    Скорость загрузки:         %{speed_download} B/s
```

**Выполнение замера сетевых фаз:**

```bash
curl -w "@/tmp/curl-format.txt" -o /dev/null -s -S https://web.internal.local/healthz
# →     Время разрешения DNS:      0.002145s
# →     Установление TCP сокета:   0.005312s
# →     Завершение TLS handshake:  0.021480s
# →     Подготовка запроса:        0.021540s
# →     Время до первого байта:    0.048910s
# →     -------------------------------------------------
# →     Суммарное время ответа:    0.049320s
# →     Код ответа HTTP:           200
# →     Скорость загрузки:         18420.000 B/s
```

**Интерпретация результатов фаз:**
- `time_connect - time_namelookup` = сетевой RTT (Round Trip Time) TCP-сессии до сервера.
- `time_appconnect - time_connect` = чистая длительность TLS-рукопожатия (при TLS 1.3 занимает 1 RTT, при TLS 1.2 — 2 RTT).
- `time_starttransfer - time_appconnect` = чистый серверный TTFB (время ожидания генерации ответа бэкендом).

### Сценарий 4: Генерация эталонной конфигурации TLS через профили Mozilla

Генератор конфигураций Mozilla Security ([Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)) определяет три профиля криптографической стойкости для веб-серверов:

1. **Modern:** исключительно TLS 1.3 (и ограниченно TLS 1.2 с современными AEAD-шифрами). Обеспечивает максимальную безопасность и минимальную задержку (1-RTT handshake, 0-RTT resumption), но отсекает устаревших клиентов.
2. **Intermediate:** стандартный профиль для производственных сред общего назначения. Поддерживает TLS 1.2 и TLS 1.3 с безопасными наборами шифров ECDHE, исключая CBC-шифры и RC4/3DES.
3. **Old:** профиль обратной совместимости с унаследованными ОС и клиентами (Windows 7 / OpenSSL 0.9.8). Не рекомендуется для новых инсталляций.

**Пример конфигурации Intermediate для Nginx/Angie:**

```nginx
# Ограничение поддерживаемых версий протоколов
ssl_protocols TLSv1.2 TLSv1.3;

# Безопасные наборы шифров для TLSv1.2 (в TLSv1.3 наборы шифров определяются автоматически)
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers off;

# Оптимизация кэширования сессий TLS
ssl_session_timeout 1d;
ssl_session_cache shared:SSL:10m;
ssl_session_tickets off;

# Включение валидации статуса сертификата (OCSP Stapling)
ssl_stapling on;
ssl_stapling_verify on;
resolver 127.0.0.1 1.1.1.1 valid=300s;
resolver_timeout 5s;

# Принудительная активация HSTS на 1 год
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

### Сценарий 5: Локальный интерактивный мониторинг access-логов в реальном времени через GoAccess

Для локального SRE/Sysadmin-анализа трафика на сервере без необходимости экспорта сырых логов во внешние системы применяется **GoAccess**.

```bash
# Установка в Debian/Ubuntu
sudo apt install -y goaccess

# Запуск интерактивного консольного интерфейса (TUI) с разбором Combined лога
goaccess /var/log/nginx/access.log --log-format=COMBINED

# Генерация автономного HTML-отчета для разового инцидентного разбора
goaccess /var/log/nginx/access.log --log-format=COMBINED -o /var/www/html/report.html
# → Parsing... [452,109] [115,000/s]
# → Format Errors - 0
# → Parsed 452109 lines in 3.93 seconds
```

### Сценарий 6: Контролируемое нагрузочное тестирование с постоянным темпом (Vegeta / wrk2)

Для корректного измерения задержек под нагрузкой без искажений Coordinated Omission применяется модель с фиксированным темпом запросов (Open Loop).

**Тестирование с помощью Vegeta:**

```bash
# Установка бинарного файла Vegeta
curl -sSfL https://github.com/tsenart/vegeta/releases/download/v12.12.0/vegeta_12.12.0_linux_amd64.tar.gz | tar -xz -C /usr/local/bin/ vegeta

# Проведение теста с темпом 500 запросов в секунду длительностью 30 секунд
echo "GET http://127.0.0.1:8080/api/v1/ping" | vegeta attack -rate=500/1s -duration=30s | vegeta report -type=text
# → Requests      [total, rate, throughput]         15000, 500.03, 500.01
# → Duration      [total, attack, wait]             30.001s, 29.998s, 2.812ms
# → Latencies     [min, mean, 50, 90, 95, 99, max]  1.12ms, 2.45ms, 2.10ms, 3.80ms, 4.95ms, 8.12ms, 24.15ms
# → Bytes In      [total, mean]                     240000, 16.00
# → Bytes Out     [total, mean]                     0, 0.00
# → Success       [ratio]                           100.00%
# → Status Codes  [code:count]                      200:15000
```

---

## Операции и команды быстрой диагностики

### Проверка синтаксиса конфигурационных файлов веб-серверов

Перед перезагрузкой или применением изменений в production-контурах обязательна валидация файлов конфигурации:

| Веб-сервер / ПО | Команда валидации синтаксиса | Ожидаемый вывод при успехе |
| :--- | :--- | :--- |
| **Nginx** | `nginx -t -c /etc/nginx/nginx.conf` | `syntax is ok / test is successful` |
| **Angie** | `angie -t` | `syntax is ok / test is successful` |
| **Apache HTTP Server** | `apachectl configtest` (или `httpd -t`) | `Syntax OK` |
| **HAProxy** | `haproxy -c -f /etc/haproxy/haproxy.cfg` | `Configuration file is valid` |
| **Caddy** | `caddy validate --config /etc/caddy/Caddyfile` | `Valid configuration` |
| **Lighttpd** | `lighttpd -t -f /etc/lighttpd/lighttpd.conf` | `Syntax OK` |
| **Traefik** | `traefik --configFile=/etc/traefik/traefik.yml` (в режиме валидации) | Код возврата 0 / отсутствие ошибок парсинга |

### Экспресс-диагностика TLS и сертификатов через OpenSSL CLI

```bash
# Проверка цепочки сертификатов и срока действия без браузера
openssl s_client -connect web.internal.local:443 -servername web.internal.local -showcerts </dev/null 2>/dev/null | openssl x509 -noout -dates -subject -issuer
# → notBefore=Oct 15 00:00:00 2026 GMT
# → notAfter=Jan 13 23:59:59 2027 GMT
# → subject=CN = web.internal.local
# → issuer=C = US, O = Let's Encrypt, CN = R10

# Проверка поддержки конкретной версии TLS (например, TLS 1.3)
openssl s_client -connect web.internal.local:443 -servername web.internal.local -tls1_3 </dev/null 2>/dev/null | grep -E "Protocol|Cipher"
# →     New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
# →     Protocol  : TLSv1.3
# →     Cipher    : TLS_AES_256_GCM_SHA384

# Проверка работы OCSP Stapling на сервере
openssl s_client -connect web.internal.local:443 -servername web.internal.local -status </dev/null 2>/dev/null | grep -A 17 "OCSP response:"
# → OCSP response:
# → ======================================
# → OCSP Response Data:
# →     OCSP Response Status: successful (0x0)
# →     Cert Status: good
```

### Экспресс-аудит заголовков безопасности через curl

```bash
# Проверка заголовков ответа сервера (HSTS, CSP, X-Frame-Options)
curl -I -s -S https://web.internal.local/
# → HTTP/2 200
# → server: nginx
# → date: Thu, 15 Oct 2026 09:20:00 GMT
# → content-type: text/html; charset=UTF-8
# → strict-transport-security: max-age=31536000; includeSubDomains
# → x-content-type-options: nosniff
# → x-frame-options: DENY
# → content-security-policy: default-src 'self'; frame-ancestors 'none'
```

---

## Диагностика и устранение неисправностей

### Ошибка 1: `testssl.sh: Unable to open a socket` / `Connection refused`

**Симптомы:** При запуске `testssl.sh https://target.domain/` утилита завершает работу с ошибкой соединения или зависает на этапе тестирования сокетов.

**Причины:**
1. Не совпадает имя Server Name Indication (SNI): веб-сервер настроен на обслуживание нескольких виртуальных хостов и сбрасывает соединение при обращении по голому IP или неподходящему имени.
2. Локальный фаервол (iptables, nftables) или WAF блокирует быстрое сканирование портов от единичного IP-адреса.
3. Проверяется нестандартный порт без явного указания.

**Решение:**
1. Передайте явный заголовок SNI с помощью ключа `--sneaky` или укажите полный URI:
   ```bash
   ./testssl.sh --ip 192.168.1.50 --name web.internal.local https://web.internal.local:443
   ```
2. Отключите проверки некритичных протоколов (STARTTLS для почтовых служб) и ограничьте интенсивность:
   ```bash
   ./testssl.sh --fast --connect-timeout 5 https://web.internal.local:443
   ```

### Ошибка 2: Ложные срабатывания (False Positives) в Gixy / Gixy-Next на динамических upstream

**Симптомы:** Анализатор выдает критическую ошибку `[ssrf] Server-Side Request Forgery` на строках вида `proxy_pass http://$upstream_backend;`, хотя список бэкендов жестко валидируется через директиву `map`.

**Причины:** Статический парсер анализирует AST изолированно для каждого блока `location` и не всегда связывает динамическую переменную с таблицей разрешений `map` в родительском контексте `http`.

**Решение:**
1. Проверьте, что в конфигурации отсутствует прямая подстановка `$request_uri` или клиентских заголовков в `proxy_pass`:
   ```nginx
   # ОПАСНО: злоумышленник может передать целевой IP через URI
   proxy_pass http://$http_host$request_uri;

   # БЕЗОПАСНО: перечисление доверенных бэкендов через map
   map $target_service $backend_pool {
       default       127.0.0.1:8080;
       "billing"     10.0.10.5:8080;
       "catalog"     10.0.10.6:8080;
   }
   ```
2. Подавите ложное предупреждение для верифицированного блока, добавив комментарий директивы подавления:
   ```nginx
   # gixy: disable=ssrf
   proxy_pass http://$backend_pool;
   ```

### Ошибка 3: Блокировки и ошибки тайм-аута при использовании внешних сканеров (SSL Labs, Observatory)

**Симптомы:** Qualys SSL Labs возвращает ошибку `Assessment failed: Unable to connect to the server`, Mozilla Observatory возвращает `HTTP 502/504`.

**Причины:**
1. Целевой хост находится в приватной сети (адреса RFC 1918 / RFC 6598) и недоступен из публичного интернета.
2. Rate Limiting или модуль защиты от ботов на стороне Nginx/Angie блокирует сканирующие IP-пулы Qualys или Mozilla.
3. Отсутствие или блокировка DNS-записи IPv6 (AAAA), если сканер отдает предпочтение IPv6.

**Решение:**
1. Для внутренних контуров используйте локальные автономные утилиты (`testssl.sh`, `gixy-next`, `curl`).
2. Для публичных хостов временно добавьте диапазоны сканеров в белый список ограничений (`geo` / `allow`).
3. Проверьте валидность AAAA-записей домена (`dig AAAA yourdomain.com +short`). При неработающем IPv6 на веб-сервере удалите AAAA-запись до устранения проблемы.

### Ошибка 4: Исчерпание портов и сетевых сокетов при бенчмаркинге (`TIME_WAIT exhaustion`)

**Симптомы:** При нагрузочном тестировании через `wrk`, `ab` или `vegeta` клиент начинает массово генерировать ошибки:
`connect() failed (99: Cannot assign requested address)` или `socket: too many open files`.

**Причины:**
1. Клиент исчерпал диапазон эфемерных портов TCP (`ip_local_port_range`), так как закрытые соединения удерживаются в состоянии `TIME_WAIT` в течение 60 секунд.
2. Превышен системный лимит открытых файловых дескрипторов (`ulimit -n`).

**Решение:**
1. Нагрузочный узел обязан использовать повторное использование сокетов и расширенный диапазон портов:
   ```bash
   sysctl -w net.ipv4.ip_local_port_range="1024 65535"
   sysctl -w net.ipv4.tcp_tw_reuse=1
   ulimit -n 1000000
   ```
2. В сценариях нагрузочного тестирования включайте постоянные соединения (Keep-Alive):
   - В `ab`: ключ `-k`.
   - В `wrk`: включен по умолчанию.
   - В `vegeta`: ключ `-keep-alive=true` (по умолчанию включен).

### Ошибка 5: Несоответствие формата логов в GoAccess (`Token doesn't match specifier`)

**Симптомы:** GoAccess при запуске рапортует `Parsed 0 lines`, `Format Errors - 100%`.

**Причины:** Строка формата лога в конфигурации веб-сервера отличается от стандартного `COMBINED` (например, добавлены переменные времени отклика `$request_time`, `$upstream_response_time` или заголовок X-Forwarded-For).

**Решение:**
1. Задайте явный шаблон разбора для GoAccess в файле `~/.goaccessrc` или через аргумент `--log-format`:
   ```bash
   # Для Nginx c кастомным временем ответа в конце строки:
   # log_format custom '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent" $request_time';
   goaccess /var/log/nginx/access.log --log-format='%h %^[%d:%t %^] "%r" %s %b "%R" "%u" %T' --date-format='%d/%b/%Y' --time-format='%H:%M:%S'
   ```

---

## Лучшие практики

1. **Принцип "Check-then-Deploy" в пайплайнах автоматизации:**
   Любое изменение конфигурационных файлов веб-серверов в Git должно проходить обязательные проверки в pre-commit хуках или CI/CD до попадания на серверы:
   - Шаг 1: Валидация синтаксиса (`nginx -t` / `haproxy -c` / `caddy validate`) в изолированном контейнере.
   - Шаг 2: Статический анализ безопасности (запуск `gixy-next`).
   - Шаг 3: Проверка отсутствия незакрытых директив `location` и утечек приватных путей.

2. **Изоляция и приоритет локального аудита:**
   - Для инспекции внутренней инфраструктуры избегайте публичных веб-сканеров во избежание утечки внутренних доменных имен, приватных IP-адресов и структуры сервисов.
   - Используйте `testssl.sh`, локальные инспекторы OpenSSL и headless браузеры внутри изолированного контура.

3. **Разделение окружений при бенчмаркинге:**
   - Никогда не запускайте генератор нагрузки (`wrk`, `k6`, `vegeta`) на том же физическом сервере или виртуальной машине, где запущен тестируемый веб-сервер.
   - Агент нагрузки потребляет ядра CPU, память и блокирует системные сетевые вызовы ядра Linux, что искажает профиль задержек сервера на величину до 300%.

4. **Системный тюнинг ядра Linux для нагрузочного и диагностического узла:**
   Для предотвращения искусственных узких мест на стороне тестирующего сервера примените следующие параметры `/etc/sysctl.d/99-benchmark.conf`:
   ```ini
   # Расширение диапазона эфемерных портов
   net.ipv4.ip_local_port_range = 1024 65535

   # Быстрое переиспользование сокетов в состоянии TIME_WAIT
   net.ipv4.tcp_tw_reuse = 1

   # Увеличение размера очереди входящих соединений ядра
   net.core.somaxconn = 65535
   net.ipv4.tcp_max_syn_backlog = 65535

   # Увеличение системных буферов TCP
   net.ipv4.tcp_rmem = 4096 87380 16777216
   net.ipv4.tcp_wmem = 4096 65536 16777216
   ```

5. **Обязательная проверка Baseline (базового уровня):**
   Перед проведением тестов производительности зафиксируйте текущие эталонные показатели системы (CPU idle, Context switches/sec, Memory usage, Network drops). Измеряйте производительность короткими ступенчатыми итерациями (Ramp-up), а не подавайте пиковую нагрузку мгновенно.

---

## Каталог ресурсов и полезных ссылок

### Официальная документация веб-серверов и балансировщиков

- **Nginx Documentation**
  Официальная спецификация, справочник директив, модулей HTTP/Stream и руководств по настройке.
  - Ссылка: [https://nginx.org/en/docs/](https://nginx.org/en/docs/)
  - Подробности в базе: [Nginx — архитектура и руководство](./Nginx/Core/nginx_overview.md)

- **Angie Documentation**
  Официальная документация форка Nginx от бывших разработчиков ядра. Включает описание динамической реконфигурации апстримов, консоли мониторинга, метрик Prometheus и нативной поддержки протокола HTTP/3.
  - Ссылка: [https://angie.software/docs/](https://angie.software/docs/)
  - Подробности в базе: [Angie — полный обзор и архитектура](./Angie/angie_overview.md)

- **Apache HTTP Server Documentation**
  Полное официальное руководство по веб-серверу Apache 2.4: модули MPM (`mpm_event`, `mpm_worker`), проксирование (`mod_proxy`), перенаправления (`mod_rewrite`) и безопасность.
  - Ссылка: [https://httpd.apache.org/docs/2.4/](https://httpd.apache.org/docs/2.4/)
  - Подробности в базе: [Apache — обзор и администрирование](./Apache/apache_overview.md)

- **HAProxy Documentation**
  Официальная документация высокопроизводительного балансировщика нагрузки и L4/L7 прокси. Полное руководство по директивам конфигурации, механизмам Stick Tables и Runtime API.
  - Ссылка: [https://docs.haproxy.org/](https://docs.haproxy.org/)
  - Подробности в базе: [HAProxy — архитектура и руководство](./haproxy_overview.md)

- **Traefik Documentation**
  Документация современного Edge Router и обратного прокси. Архитектура маршрутизации (Routers, Middlewares, Services), автоматическое управление TLS и поддержка провайдеров конфигурации.
  - Ссылка: [https://doc.traefik.io/traefik/](https://doc.traefik.io/traefik/)
  - Подробности в базе: [Traefik — обзор и эксплуатация](./Traefik/traefik_overview.md)

- **Caddy Server Documentation**
  Официальное руководство по веб-серверу Caddy на языке Go с автоматическим выпуском сертификатов через ACME, встроенной поддержкой HTTP/3 и декларативным синтаксисом Caddyfile.
  - Ссылка: [https://caddyserver.com/docs/](https://caddyserver.com/docs/)

- **Lighttpd Documentation**
  Официальная вики-документация легковесного высокопроизводительного веб-сервера, оптимизированного для встраиваемых систем и серверов с жесткими ограничениями памяти.
  - Ссылка: [https://redmine.lighttpd.net/projects/lighttpd/wiki](https://redmine.lighttpd.net/projects/lighttpd/wiki)
  - Подробности в базе: [Lighttpd — обзор и архитектура](./Lighttpd/lighttpd_overview.md)

- **Envoy Proxy Documentation**
  Официальная документация высокопроизводительного C++ L4/L7 прокси-сервера, спроектированного для сервисных коммуникаций, ingress-шлюзов и управления трафиком с динамическим API (xDS).
  - Ссылка: [https://www.envoyproxy.io/docs/envoy/latest/](https://www.envoyproxy.io/docs/envoy/latest/)

### Стандарты и спецификации IETF RFC

- **RFC 9110 (HTTP Semantics)** — базовая семантика протокола HTTP: методы (GET, POST, PUT, DELETE, HEAD, OPTIONS), статусы ответов и поля заголовков.
  - Ссылка: [https://www.rfc-editor.org/rfc/rfc9110.html](https://www.rfc-editor.org/rfc/rfc9110.html)
- **RFC 9111 (HTTP Caching)** — спецификация механизмов кэширования HTTP: директивы `Cache-Control`, `Age`, валидаторы `ETag`, `Last-Modified`.
  - Ссылка: [https://www.rfc-editor.org/rfc/rfc9111.html](https://www.rfc-editor.org/rfc/rfc9111.html)
- **RFC 9112 (HTTP/1.1)** — спецификация синтаксиса и формата сообщений протокола HTTP/1.1 (Chunked Transfer Encoding, pipelining).
  - Ссылка: [https://www.rfc-editor.org/rfc/rfc9112.html](https://www.rfc-editor.org/rfc/rfc9112.html)
- **RFC 9113 (HTTP/2)** — спецификация протокола HTTP/2: бинарное фреймирование, мультиплексирование потоков в рамках одного TCP-соединения, сжатие заголовков HPACK.
  - Ссылка: [https://www.rfc-editor.org/rfc/rfc9113.html](https://www.rfc-editor.org/rfc/rfc9113.html)
- **RFC 9114 (HTTP/3)** — спецификация протокола HTTP/3, функционирующего поверх транспортного протокола QUIC (UDP), устраняющего проблему блокировки начала очереди (Head-of-Line Blocking).
  - Ссылка: [https://www.rfc-editor.org/rfc/rfc9114.html](https://www.rfc-editor.org/rfc/rfc9114.html)
- **RFC 8446 (The TLS Protocol Version 1.3)** — стандарт криптографического протокола TLS 1.3: удаление небезопасных шифров, обязательный Forward Secrecy, рукопожатие за 1 RTT.
  - Ссылка: [https://www.rfc-editor.org/rfc/rfc8446.html](https://www.rfc-editor.org/rfc/rfc8446.html)

### Безопасность, SSL/TLS и аудит конфигураций

- **Gixy-Next**
  Актуальный поддерживаемый статический анализатор конфигурационных файлов Nginx и Angie на базе Python 3. Выявляет уязвимости SSRF, обхода каталогов (Alias Traversal) и расщепления HTTP-запросов.
  - Ссылка: [https://github.com/GixyNext/gixy-next](https://github.com/GixyNext/gixy-next)
  - Архивный оригинал: [https://github.com/yandex/gixy](https://github.com/yandex/gixy)

- **testssl.sh**
  Автономная консольная утилита командной строки для комплексного аудита TLS/SSL шифров, протоколов и криптографических уязвимостей на любых TCP-портах. Работает в закрытых контурах без передачи данных внешним службам.
  - Ссылка: [https://testssl.sh/](https://testssl.sh/)
  - Исходный код: [https://github.com/drwetter/testssl.sh](https://github.com/drwetter/testssl.sh)
  - Подробности в базе: [Настройка и аудит TLS в Angie](./Angie/angie_tls_setup.md)

- **Mozilla SSL Configuration Generator**
  Официальный инструмент Mozilla для генерации надежных, проверенных конфигураций TLS/SSL (профили Modern, Intermediate, Old) для Nginx, Apache, HAProxy, Caddy, Lighttpd.
  - Ссылка: [https://ssl-config.mozilla.org/](https://ssl-config.mozilla.org/)

- **SSLyze**
  Быстрый сканер и библиотека Python для автоматизации анализа конфигураций SSL/TLS (проверка протоколов, cipher suites, валидация цепочек доверия).
  - Ссылка: [https://github.com/nabla-c0d3/sslyze](https://github.com/nabla-c0d3/sslyze)

- **Mozilla Observatory**
  Строгий сканер безопасности, оценивающий HTTP-заголовки безопасности, параметры TLS и Content Security Policy (CSP).
  - Ссылка: [https://observatory.mozilla.org/](https://observatory.mozilla.org/)

- **Security Headers**
  Онлайн-инструмент для быстрой валидации заголовков безопасности веб-приложений (HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy).
  - Ссылка: [https://securityheaders.com/](https://securityheaders.com/)

- **Qualys SSL Labs (SSL Server Test)**
  Глубокий анализ конфигурации SSL/TLS публичных серверов: проверка цепочек сертификатов, симуляция сотен клиентов, проверка устойчивости к известным атакам.
  - Ссылка: [https://www.ssllabs.com/ssltest/](https://www.ssllabs.com/ssltest/)

### Анализ производительности и Core Web Vitals

- **Google PageSpeed Insights**
  Анализ скорости загрузки страниц на базе движка Lighthouse и данных реальных пользователей из Chrome User Experience Report (CrUX).
  - Ссылка: [https://pagespeed.web.dev/](https://pagespeed.web.dev/)
  - Подробности в базе: [PageSpeed Insights — руководство](./Concepts/web_performance/pagespeed_insights.md)

- **WebPageTest**
  Профессиональная платформа для детального анализа производительности из различных географических точек на реальных устройствах. Поддерживает визуализацию Waterfall, покадровую съемку и анализ протоколов HTTP/2 и HTTP/3. Доступна версия для локального self-hosted развертывания.
  - Ссылка: [https://www.webpagetest.org/](https://www.webpagetest.org/)
  - Открытый репозиторий: [https://github.com/WPO-Foundation/webpagetest](https://github.com/WPO-Foundation/webpagetest)
  - Подробности в базе: [WebPageTest — глубокий анализ](./Concepts/web_performance/webpagetest.md)

- **Lighthouse CI (LHCI)**
  Пакет утилит с открытым исходным кодом для автоматической интеграции аудита производительности, доступности и лучших практик Lighthouse в локальные пайплайны CI/CD.
  - Ссылка: [https://github.com/GoogleChrome/lighthouse-ci](https://github.com/GoogleChrome/lighthouse-ci)

- **Pingdom Website Speed Test**
  Тест скорости загрузки веб-страниц с декомпозицией по типам контента и размерам передаваемых данных.
  - Ссылка: [https://tools.pingdom.com/](https://tools.pingdom.com/)

- **GTmetrix**
  Инструмент комплексного отслеживания истории производительности и визуальных отчетов по скорости загрузки страниц.
  - Ссылка: [https://gtmetrix.com/](https://gtmetrix.com/)

### Нагрузочное тестирование и бенчмаркинг

- **k6 (by Grafana)**
  Инструмент нагрузочного тестирования как кода (Testing as Code) на базе Go и JavaScript/TypeScript. Поддерживает сценарии сложной пользовательской логики, HTTP/1.1, HTTP/2, gRPC и WebSocket.
  - Ссылка: [https://k6.io/](https://k6.io/)
  - Исходный код: [https://github.com/grafana/k6](https://github.com/grafana/k6)

- **wrk**
  Высокопроизводительный HTTP/1.1 бенчмаркер с многопоточной архитектурой на базе `epoll`/`kqueue`, способный генерировать экстремальный RPS при минимальном потреблении CPU.
  - Ссылка: [https://github.com/wg/wrk](https://github.com/wg/wrk)

- **wrk2 / wrkx**
  Форк wrk с поддержкой генерации нагрузки с постоянным темпом (Constant Request Rate), устраняющий искажения Coordinated Omission и формирующий гистограммы задержек высокой точности (HDR Histogram).
  - Ссылка: [https://github.com/giltene/wrk2](https://github.com/giltene/wrk2)

- **Vegeta**
  Консольная утилита на языке Go для проведения нагрузочного тестирования с фиксированным темпом запросов (Rate-based Open Loop). Идеальна для проверки стабильности очередей под предсказуемой нагрузкой.
  - Ссылка: [https://github.com/tsenart/vegeta](https://github.com/tsenart/vegeta)

- **Bombardier**
  Быстрый кроссплатформенный инструмент бенчмаркинга HTTP/1.1 и HTTP/2 на языке Go с использованием оптимизированного сетевого стека fasthttp.
  - Ссылка: [https://github.com/codesenberg/bombardier](https://github.com/codesenberg/bombardier)

- **Apache Benchmark (ab)**
  Классическая однопоточная консольная утилита из пакета `apache2-utils` для быстрой проверки RPS и устойчивости к базовой нагрузке по HTTP/1.1.
  - Документация: [https://httpd.apache.org/docs/2.4/programs/ab.html](https://httpd.apache.org/docs/2.4/programs/ab.html)

- Подробный обзор в базе: [Инструменты бенчмаркинга веб-серверов](./webserver_benchmarking.md)

### Анализ логов и сетевая диагностика

- **GoAccess**
  Интерактивный анализатор access-логов веб-серверов в реальном времени с поддержкой TUI-режима в терминале и экспорта в статичные HTML-отчеты.
  - Ссылка: [https://goaccess.io/](https://goaccess.io/)
  - Исходный код: [https://github.com/allinurl/goaccess](https://github.com/allinurl/goaccess)
  - Подробности в базе: [Анализ access-логов (GoAccess и CLI)](./Nginx/Operations/nginx_log_analysis.md)

- **curl**
  Стандартный сетевой клиент для передачи данных и низкоуровневой проверки HTTP-заголовков, фаз TLS-соединения и замеров задержек сетевого стека.
  - Ссылка: [https://curl.se/docs/](https://curl.se/docs/)

- **ngrep (Network Grep)**
  Сетевой анализатор пакетов, позволяющий применять регулярные выражения непосредственно к содержимому полезной нагрузки HTTP-пакетов на сетевом интерфейсе без изменения конфигурации веб-сервера.
  - Ссылка: [https://github.com/jpr5/ngrep](https://github.com/jpr5/ngrep)

### Смежные материалы базы знаний

- [Инструменты бенчмаркинга веб-серверов](./webserver_benchmarking.md) — методология нагрузочного тестирования, архитектура открытого/закрытого циклов, тюнинг ядра Linux и сравнение нагрузчиков.
- [HAProxy — архитектура и руководство](./haproxy_overview.md) — балансировка L4/L7, Stick Tables, Runtime API и интеграция с Prometheus.
- [Диагностика и устранение неисправностей веб-серверов](./Concepts/webserver_troubleshooting.md) — алгоритмы расследования 5xx/4xx ошибок, таймаутов и сетевых сбоев.
- [Уязвимости SSRF и защита веб-серверов](./Concepts/ssrf.md) — векторы атак через обратный прокси и методы изоляции локальных адресов.
- [Защита от нежелательных ботов и парсеров](./Concepts/bot_protection.md) — поведенческий анализ заголовков, ограничение частоты запросов и валидация User-Agent.
- [Оптимизация TLS в веб-серверах](./Concepts/web_performance/tls_optimization.md) — кэширование сессий, OCSP Stapling, выбор криптографических наборов и сеансовые билеты.
- [Протоколы HTTP/2 и HTTP/3 в production](./Concepts/web_performance/http2_http3.md) — мультиплексирование, приоритезация потоков и специфика UDP/QUIC.
