# Защита веб-серверов от ботов

**Актуально для:** Nginx 1.26+, Angie 1.8+, HAProxy 3.0+, CrowdSec 1.6+, Linux 6.x

## Определения

**Bot (Бот)** — автономный программный клиент (скрипт, парсер, краулер, автоматизированный headless-браузер), выполняющий сетевые HTTP-запросы без прямого интерактивного участия человека.

**Good Bot (Легитимный бот)** — поисковые роботы индексации (Googlebot, Bingbot, YandexBot), внешние системы синтетического мониторинга и валидаторы ссылок, соблюдающие `robots.txt`, передающие достоверный `User-Agent` и подтверждающие подлинность через обратные DNS-записи.

**Bad Bot (Вредоносный бот)** — автоматизированный агент, нарушающий безопасность, доступность или бизнес-логику веб-ресурса: L7 HTTP-флудеры, скраперы закрытого или авторского контента, credential stuffing/brute-force скрипты, парсеры цен, сканеры уязвимостей (Nikto, SQLMap, Nuclei) и спам-боты.

**FCrDNS (Forward-Confirmed Reverse DNS)** — двухэтапная криптографически и инфраструктурно независимая проверка подлинности сетевого узла: получение доменного имени по IP-адресу клиента через запрос PTR, с последующим A/AAAA-запросом к полученному имени. Если конечный IP совпадает с исходным, а домен принадлежит доверенной зоне (например, `*.googlebot.com`), бот считается верифицированным.

**TLS Fingerprinting (JA3 / JA4)** — метод пассивной идентификации клиента на этапе TLS Handshake до отправки HTTP-заголовков. Хеш формируется на основе версии TLS, списка поддерживаемых Cipher Suites, расширений (Extensions), эллиптических кривых и форматов точек в пакете `Client Hello`. Позволяет выявлять скрипты на Python (`urllib`, `requests`), Go, Node.js или cURL, маскирующие свой `User-Agent` под легитимный браузер.

**Honeypot (Приманка / Ловушка)** — скрытый от легитимных пользователей ресурс (невидимая ссылка в DOM-дереве, путь в `robots.txt` под запретом `Disallow`, фиктивный эндпоинт `/wp-login.php` на платформе без WordPress). Любой запрос к ловушке однозначно идентифицирует автоматизированного сканера и инициирует немедленную блокировку.

**Proof-of-Work (PoW) Challenge** — механизм защиты без привлечения сторонних облачных сервисов, при котором сервер выдает браузеру клиента вычислительную задачу (поиск хеша SHA-256 с заданным числом нулевых бит). Человек в браузере решает ее за 50–200 мс без прерывания интерфейса (в фоновом Web Worker), тогда как для оператора ботнета генерация миллионов решений становится экономически нецелесообразной по затратам CPU.

**JS / Cookie Challenge** — механизм проверки поддержки клиентского JavaScript и работы с cookies. Веб-сервер возвращает промежуточный ответ с криптографически подписанным токеном и коротким JS-сценарием, который вычисляет значение и отправляет его обратно в cookies или заголовках. Примитивные HTTP-библиотеки не исполняют JS и отсекаются на первом шаге.

**Host-based IPS (Intrusion Prevention System — CrowdSec / Fail2ban)** — локальный сервис безопасности, анализирующий журналы доступа и метрики веб-сервера в реальном времени, выявляющий вредоносные паттерны (высокая частота 404-ошибок, перебор учетных записей, запрещенные сигнатуры) и транслирующий блокировки на уровень ядра Linux (`nftables`, `ipset`).

---

## Архитектура и принципы работы

### Многоуровневый конвейер фильтрации ботов (On-Premises Defense-in-Depth)

Защита веб-сервера от ботов без использования внешних облачных провайдеров организуется по эшелонированному принципу:

```
[ Трафик из Интернет ]
         │
         ▼
[ Уровень 1: L3/L4 Ядро Linux (nftables / ipset) ]
  ├── Блокировка публичных списков угроз (Spamhaus DROP, Tor exit nodes, FireHOL)
  └── Динамические блокировки от CrowdSec / Fail2ban
         │ (пропущен легитимный трафик)
         ▼
[ Уровень 2: L7 Edge Reverse Proxy (Nginx / Angie / HAProxy) ]
  ├── Проверка аномалий TLS (JA3/JA4, устаревшие шифры)
  ├── Нормализация и валидация HTTP-заголовков (User-Agent, Accept, Sec-Fetch-*)
  ├── Проверка подлинности поисковиков (FCrDNS / верификация подсетей)
  └── Rate Limiting с дифференциацией по типам клиентов
         │
         ▼
[ Уровень 3: Активная проверка и Challenge-Response ]
  ├── Honeypot-эндпоинты (мгновенная передача в бан-лист)
  ├── Stateless Cookie Challenge / Self-hosted PoW (Altcha / mCaptcha)
  └── ModSecurity / Coraza (OWASP CRS Scanner Detection)
         │
         ▼
[ Уровень 4: Приложение / Upstream ]
  └── Обработка подтвержденных пользовательских сессий
```

### Анализ клиентских заголовков и аномалий протокола

Простые боты и сканеры уязвимостей часто используют утилиты командной строки (`curl`, `wget`) или скриптовые библиотеки (`python-requests`, `aiohttp`, `Go-http-client`). Их ключевые маркеры:

1. **Отсутствие или искажение стандартных заголовков браузера:** Современные десктопные и мобильные браузеры всегда передают семейство заголовков `Sec-Ch-Ua`, `Sec-Ch-Ua-Mobile`, `Sec-Ch-Ua-Platform`, а также `Accept-Language` и `Sec-Fetch-*` (`Sec-Fetch-Site`, `Sec-Fetch-Mode`, `Sec-Fetch-Dest`). Бот, отправляющий заголовок `User-Agent: Mozilla/5.0...`, но не имеющий `Sec-Fetch-Mode` или `Accept-Language`, детектируется как подделка.
2. **Пустой или отсутствующий `User-Agent`:** Браузеры никогда не отправляют пустой заголовок клиента.
3. **Несоответствие версии HTTP:** Использование HTTP/1.0 без заголовка `Host` для современных веб-приложений указывает на устаревший автоматизированный зонд.

### Верификация легитимных поисковых ботов (FCrDNS)

Злоумышленники регулярно используют подмену строки идентификатора: `User-Agent: Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)`. Доверять строке `User-Agent` без верификации сетевого адреса запрещено.

Алгоритм проверки:
1. Запрос PTR для входящего IP-адреса клиента (`$remote_addr`).
2. Проверка соответствия полученного доменного суффикса официальным зонам:
   - Google: `.googlebot.com` или `.google.com`.
   - Yandex: `.yandex.ru`, `.yandex.net`, `.yandex.com`.
   - Bing: `.search.msn.com`.
3. Запрос A/AAAA-записи для подтвержденного доменного имени.
4. Сравнение IP-адреса из A-записи с исходным `$remote_addr`. При несовпадении запрос считается фальсификацией и блокируется.

Для снижения накладных расходов на DNS-запросы в высоконагруженных окружениях адреса верифицированных поисковых ботов кэшируются в локальной памяти прокси-сервера либо синхронизируются по расписанию в списки CIDR (модуль `geo` в Nginx/Angie).

### Идентификация по отпечаткам TLS (JA3 / JA4)

Библиотеки языка Python (OpenSSL), Go (`crypto/tls`) и Java имеют строго фиксированный порядок шифров и наборов TLS-расширений, отличающийся от реализаций BoringSSL (Google Chrome) или NSS (Mozilla Firefox).

Снятие отпечатка JA3 строится по конкатенации полей пакета `Client Hello`:
`SSLVersion,Ciphers,Extensions,EllipticCurves,EllipticCurvePointFormats`

Хеш MD5 от этой строки дает идентификатор клиента. Если входящий запрос содержит строку браузера Chrome, но его JA3-хеш совпадает с отпечатком стандартной библиотеки Python `requests` или headless-инструмента Puppeteer, запрос отсекается до передачи в бэкенд.

---

## Практические сценарии

### Сценарий 1: Фильтрация плохих ботов и аномалий заголовков в Nginx / Angie

Комплексная трехуровневая фильтрация: блокировка известных сигнатур сканеров, обнаружение отсутствующих обязательных браузерных заголовков и изоляция пустых User-Agent.

```nginx
# /etc/nginx/conf.d/bot_detection.conf

# 1. Сигнатурный анализ User-Agent
map $http_user_agent $is_malicious_scanner {
    default 0;
    ~*(?i)(nikto|sqlmap|masscan|acunetix|havij|nmap|zgrab|nuclei|openvas) 1;
    ~*(?i)(dirbuster|gobuster|wfuzz|burpcollaborator|wprecon) 1;
    ~*(?i)(scrapy|python-requests|aiohttp|httpclient|libwww-perl) 1;
    ~*(?i)(bytespider|gptbot|claudebot|ccbot|semrushbot|ahrefsbot) 1;
}

# 2. Проверка пустого User-Agent
map $http_user_agent $is_empty_ua {
    default 0;
    ""      1;
    "-"     1;
}

# 3. Эвристика: проверка браузерной мимикрии при отсутствии Accept-Language
# Настоящий браузер всегда присылает Accept-Language
map $http_user_agent $is_browser_fake {
    default 0;
    "~*Mozilla/.*(Windows|Macintosh|Linux|Android|iPhone)" $missing_accept_language;
}

map $http_accept_language $missing_accept_language {
    default 0;
    ""      1;
}

# 4. Агрегация флагов блокировки
map "$is_malicious_scanner:$is_empty_ua:$is_browser_fake" $bot_block_action {
    default 0;
    "~1"    1;
}

# 5. Дифференцированный Rate Limiting для ботов
map $bot_block_action $limit_key {
    0 "";
    1 $binary_remote_addr;
}

limit_req_zone $limit_key zone=bots_tight_limit:10m rate=1r/m;
```

Интеграция в конфигурацию виртуального хоста:

```nginx
# /etc/nginx/conf.d/vhost.example.com.conf
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name example.com;

    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    # Мгновенный сброс TCP-соединения для доказанных сканеров (код 444 экономит трафик)
    if ($is_malicious_scanner) {
        return 444;
    }

    # Отклонение пустых или поддельных браузерных заголовков
    if ($bot_block_action) {
        return 403 "Forbidden: Automated client detected\n";
    }

    location / {
        proxy_pass http://backend_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Проверка конфигурации и тестирование поведения:**

```bash
# 1. Проверка синтаксиса и перезагрузка
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

systemctl reload nginx

# 2. Запрос от имени сканера sqlmap (ожидается сброс соединения 444)
curl -k -I -A "sqlmap/1.7#stable" https://example.com/
# → curl: (52) Empty reply from server

# 3. Запрос с пустым User-Agent (ожидается 403)
curl -k -I -A "" https://example.com/
# → HTTP/2 403
# → content-type: text/plain

# 4. Запрос с браузерным UA, но без заголовка Accept-Language (ожидается 403)
curl -k -I -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" https://example.com/
# → HTTP/2 403

# 5. Легитимный браузерный запрос с Accept-Language (ожидается 200)
curl -k -I -A "Mozilla/5.0 (X11; Linux x86_64)" -H "Accept-Language: ru-RU,ru;q=0.9" https://example.com/
# → HTTP/2 200
```

---

### Сценарий 2: Поведенческая защита от ботов и сканеров в HAProxy с помощью Stick-Tables

HAProxy отслеживает частоту запросов и аномальную генерацию HTTP-ошибок (404/403) со стороны клиента через скользящее окно в памяти (`stick-table`). Бот, сканирующий пути веб-приложения на уязвимости, блокируется автоматически до попадания в бэкенд.

```haproxy
# /etc/haproxy/haproxy.cfg

frontend fe_https
    bind :443 ssl crt /etc/ssl/certs/site.pem alpn h2,http/1.1
    mode http

    # Таблица для отслеживания IP-адресов клиентов
    # Хранит счетчик запросов за 10 сек и количество ошибок 4xx за 10 сек
    stick-table type ip size 200k expire 5m store http_req_rate(10s),http_err_rate(10s)
    http-request track-sc0 src

    # Выявление ботов по статическим сигнатурам User-Agent
    acl acl_bad_bots hdr_sub(User-Agent) -i -f /etc/haproxy/bad_bots.lst
    http-request deny deny_status 403 if acl_bad_bots

    # Блокировка клиента при превышении частоты 4xx ошибок (более 15 ошибок за 10 секунд = сканер путей)
    acl acl_scanner_probing sc_http_err_rate(0) gt 15
    http-request deny deny_status 429 hdr "Retry-After" 300 if acl_scanner_probing

    # Ограничение общей интенсивности запросов (не более 60 запросов за 10 секунд)
    acl acl_rate_exceeded sc_http_req_rate(0) gt 60
    http-request deny deny_status 429 hdr "Retry-After" 60 if acl_rate_exceeded

    default_backend be_servers

backend be_servers
    mode http
    balance roundrobin
    server srv1 10.0.0.11:8080 check
    server srv2 10.0.0.12:8080 check
```

Создание списка запрещенных сигнатур:

```bash
cat << 'EOF' > /etc/haproxy/bad_bots.lst
nikto
sqlmap
nuclei
masscan
bytespider
python-requests
EOF

systemctl reload haproxy
```

**Проверка отслеживания через сокет управления HAProxy:**

```bash
# Просмотр записей stick-table в реальном времени
echo "show table fe_https" | socat stdio /run/haproxy/admin.sock
# → # table: fe_https, type: ip, size:204800, used:1
# → 0x7f83b4001990: key=198.51.100.42 use=0 exp=298 http_req_rate(10s)=64 http_err_rate(10s)=18
```

---

### Сценарий 3: Автоматизированная система активной защиты на базе CrowdSec и Nftables Bouncer

CrowdSec анализирует журналы веб-сервера, выявляет краулеров, сканеров и атакующих по заранее определенным сценариям (`scenarios`) и передает решение о блокировке в компонент локального файрвола (`crowdsec-firewall-bouncer`) для сброса пакетов на уровне `nftables`.

#### Шаг 1: Установка CrowdSec и Bouncer в Linux

```bash
# Установка официального репозитория CrowdSec (Debian/Ubuntu)
curl -s https://install.crowdsec.net | bash
apt-get install -y crowdsec crowdsec-firewall-bouncer-nftables

# Проверка статуса сервиса
systemctl status crowdsec --no-pager
# → Active: active (running)
```

#### Шаг 2: Установка коллекций защиты веб-серверов

```bash
# Установка сценариев для выявления плохих User-Agent, сканирования и агрессивного скрапинга
cscli collections install crowdsecurity/nginx
cscli scenarios install crowdsecurity/http-bad-user-agent
cscli scenarios install crowdsecurity/http-crawl-non_statics
cscli scenarios install crowdsecurity/http-probing

systemctl reload crowdsec
```

#### Шаг 3: Проверка сценариев и управление активными решениями (Decisions)

```bash
# Просмотр активных сценариев
cscli scenarios list
# → ----------------------------------------------------------------------------------------------------------
# →  NAME                                 📦 STATUS    VERSION  LOCAL PATH
# → ----------------------------------------------------------------------------------------------------------
# →  crowdsecurity/http-bad-user-agent    ✔️  enabled   0.3      /etc/crowdsec/scenarios/http-bad-user-agent.yaml
# →  crowdsecurity/http-probing           ✔️  enabled   0.2      /etc/crowdsec/scenarios/http-probing.yaml
# →  crowdsecurity/http-crawl-non_statics ✔️  enabled   0.3      /etc/crowdsec/scenarios/http-crawl-non_statics.yaml
# → ----------------------------------------------------------------------------------------------------------

# Ручное добавление тестовой блокировки бота на 4 часа
cscli decisions add --ip 198.51.100.55 --reason "aggressive_bot_scraping" --duration 4h
# → 13:45:00 [INFO] Decision successfully added

# Просмотр активных блокировок
cscli decisions list
# → +----+------------------+---------------+-------------------------+------------------------+--------+---------+----+
# → | ID |      SOURCE      |  SCOPE:VALUE  |         REASON          |       ACTION           | COUNTRY| EXPIRE  |    |
# → +----+------------------+---------------+-------------------------+------------------------+--------+---------+----+
# → | 1  | cscli            | Ip:198.51.100.55| aggressive_bot_scraping | ban                    | -      | 3h59m   |    |
# → +----+------------------+---------------+-------------------------+------------------------+--------+---------+----+

# Проверка отражения блокировки в nftables
nft list set inet crowdsec crowdsec_blocklist
# → table inet crowdsec {
# →     set crowdsec_blocklist {
# →         type ipv4_addr
# →         flags timeout
# →         elements = { 198.51.100.55 timeout 3h59m45s }
# →     }
# → }
```

---

### Сценарий 4: Honeypot-ловушки с автоматической изоляцией через Fail2ban

Создание ловушек на частые цели автоматизированных сканеров (CMS, конфигурационные файлы) и немедленный бан атакующего IP в сетевом экране.

#### Шаг 1: Конфигурация ловушек в Nginx / Angie

```nginx
# /etc/nginx/conf.d/honeypot_traps.conf
server {
    listen 80;
    listen 443 ssl;
    server_name example.com;

    # Специальный формат журнала для ловушек
    access_log /var/log/nginx/honeypot.log combined;

    # Ловушка 1: Запрещенный путь в robots.txt
    location = /secret-trap-path-bot/ {
        access_log /var/log/nginx/honeypot_triggers.log combined;
        return 403;
    }

    # Ловушка 2: Поиск уязвимых файлов и панелей управления
    location ~* ^/(\.env|\.git|wp-login\.php|xmlrpc\.php|phpmyadmin|actuator|telescope) {
        access_log /var/log/nginx/honeypot_triggers.log combined;
        return 403;
    }

    # Публичный robots.txt, указывающий ботам не заходить в ловушку
    location = /robots.txt {
        return 200 "User-agent: *\nDisallow: /secret-trap-path-bot/\n";
    }
}
```

#### Шаг 2: Фильтр и правило (Jail) Fail2ban с использованием Nftables

```ini
# /etc/fail2ban/filter.d/nginx-honeypot.conf
[Definition]
failregex = ^<HOST> -.*"(GET|POST|HEAD) /(secret-trap-path-bot|\.env|\.git|wp-login\.php|xmlrpc\.php|phpmyadmin)
ignoreregex =
```

```ini
# /etc/fail2ban/jail.d/nginx-honeypot.local
[nginx-honeypot]
enabled  = true
port     = http,https
filter   = nginx-honeypot
logpath  = /var/log/nginx/honeypot_triggers.log
maxretry = 1
bantime  = 86400
findtime = 600
banaction = nftables-multiport
```

Применение и валидация:

```bash
fail2ban-client reload
# → Reload all: OK

# Проверка статуса ловушки
fail2ban-client status nginx-honeypot
# → Status for the jail: nginx-honeypot
# → |- Filter
# → |  |- Currently failed: 0
# → |  |- Total failed:     0
# → |  `- File list:        /var/log/nginx/honeypot_triggers.log
# → `- Actions
# →    |- Currently banned: 0
# →    |- Total banned:     0
# →    `- Banned IP list:

# Тестовая провокация ловушки с внешнего хоста
curl -k -I https://example.com/.env
# → HTTP/2 403

# Проверка регистрации бана
fail2ban-client status nginx-honeypot
# → Status for the jail: nginx-honeypot
# → `- Actions
# →    |- Currently banned: 1
# →    |- Total banned:     1
# →    `- Banned IP list:   198.51.100.42
```

---

### Сценарий 5: Защита чувствительных эндпоинтов через Self-Hosted Proof-of-Work (Altcha / mCaptcha)

В отличие от сторонних проприетарных сервисов (Google reCAPTCHA), автономные системы Proof-of-Work полностью размещаются на собственных серверах и не передают пользовательские данные сторонним компаниям.

Архитектура процесса:
1. Клиент запрашивает защищенную форму (например, `/auth/login`).
2. Сервер возвращает одноразовый криптографический вызов (challenge nonce, сгенерированный с использованием серверного HMAC-секрета и метки времени).
3. Виджет на JavaScript в браузере пользователя находит число, удовлетворяющее условию сложности (например, SHA-256(challenge + number) начинается с N нулей). Время вычисления: 100–300 мс на одном ядре.
4. Браузер отправляет payload формы вместе с вычисленным решением.
5. Веб-сервер или бэкенд за 0.05 мс проверяет корректность HMAC и соответствие хеша. Если решение неверно или отсутствует — запрос отклоняется.

Интеграция на уровне Nginx (с использованием NJS для валидации):

```nginx
# /etc/nginx/conf.d/pow_verification.conf

# Загрузка модуля njs
load_module modules/ngx_http_js_module.so;

http {
    js_path "/etc/nginx/njs/";
    js_import pow from bot_pow_validator.js;

    server {
        listen 443 ssl;
        server_name example.com;

        location = /api/v1/auth/login {
            # Валидация PoW перед передачей в бэкенд
            js_content pow.validateChallenge;
        }

        location @upstream_login {
            proxy_pass http://backend_login_cluster;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```

```javascript
// /etc/nginx/njs/bot_pow_validator.js
function validateChallenge(r) {
    var payload = r.requestText;
    var signature = r.headersIn['X-Altcha-Signature'];

    if (!signature) {
        r.return(400, JSON.stringify({ error: "Missing Proof-of-Work verification" }));
        return;
    }

    // Проверка HMAC и повторного использования токена (защита от replay-атак)
    var isValid = verifySignatureAndHash(signature, payload);
    if (!isValid) {
        r.return(403, JSON.stringify({ error: "Proof-of-Work challenge verification failed" }));
        return;
    }

    r.internalRedirect('@upstream_login');
}

export default { validateChallenge };
```

---

## Операции и команды

Сводка команд администратора для мониторинга активности ботов и оперативного управления блокировками:

### Анализ логов доступа на предмет ботов

```bash
# 1. Топ-20 самых активных User-Agent в журнале доступа
awk -F'"' '{print $6}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -n 20
# →  45210 Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
# →  12400 Googlebot/2.1 (+http://www.google.com/bot.html)
# →   8430 python-requests/2.31.0
# →   3120 Scrapy/2.11.0 (+https://scrapy.org)

# 2. Поиск IP-адресов, генерирующих аномальное количество 404/403 ошибок (сканеры)
awk '($9 ~ /403|404/) {print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -n 10
# →    1820 198.51.100.99
# →     940 203.0.113.12
# →     412 192.0.2.14

# 3. Выявление запросов с пустым значением заголовка User-Agent
awk -F'"' '($6 == "-" || $6 == "") {print $1, $4, $6}' /var/log/nginx/access.log | head -n 5
# → 198.51.100.104 [14/Oct/2026:14:10:22 +0300] -
```

### Управление списками блокировок (Nftables, CrowdSec, Fail2ban)

```bash
# 1. Просмотр заблокированных IP в CrowdSec
cscli decisions list -a
# → Displays list of all active crowdsec bans

# 2. Снятие блокировки с IP-адреса (ложное срабатывание) в CrowdSec
cscli decisions delete --ip 198.51.100.42
# → 14:15:00 [INFO] Decision(s) deleted: 1

# 3. Просмотр активных блокировок в Fail2ban
fail2ban-client status nginx-honeypot
# → Banned IP list: 198.51.100.99

# 4. Снятие блокировки IP в Fail2ban
fail2ban-client set nginx-honeypot unbanip 198.51.100.99
# → 1

# 5. Инспекция набора заблокированных IP-адресов на уровне ядра
nft list set inet filter bad_bots
# → table inet filter {
# →     set bad_bots {
# →         type ipv4_addr
# →         flags timeout
# →         elements = { 198.51.100.99 timeout 23h58m }
# →     }
# → }
```

---

## Диагностика и устранение неисправностей

### Проблема 1: Ложные срабатывания (False Positives) для пользователей за корпоративным NAT

**Симптомы:** Легитимные сотрудники крупной организации или клиенты мобильных провайдеров массово получают ответы `429 Too Many Requests` или `403 Forbidden`.
**Причина:** Тысячи клиентов обращаются в интернет через один общий внешний IP-адрес шлюза. Лимит `rate=10r/s` на основе `$binary_remote_addr` быстро исчерпывается.
**Решение:**
1. Разделение ключа rate limiting: использовать не только IP, но и сессионный cookie пользователя:
   ```nginx
   # Идентификатор: связка IP + Cookie сессии
   map $cookie_session_id $session_limiter_key {
       default $binary_remote_addr;
       "~.+"   "$binary_remote_addr:$cookie_session_id";
   }
   limit_req_zone $session_limiter_key zone=smart_users:20m rate=15r/s;
   ```
2. Настройка списков исключений (`geo` white-listing) для доверенных корпоративных офисов, партнеров и систем мониторинга:
   ```nginx
   geo $is_whitelisted_ip {
       default        0;
       192.0.2.0/24   1; # Офисная подсеть
       198.51.100.0/24 1; # Сеть мониторинга
   }

   map $is_whitelisted_ip $dynamic_limit_key {
       0 $binary_remote_addr;
       1 ""; # Пустой ключ отключает limit_req
   }
   ```

### Проблема 2: Подделка User-Agent поисковых роботов (Fake Googlebot / Bingbot)

**Симптомы:** Всплеск трафика от User-Agent `Googlebot`, парсинг каталогов товаров и создание паразитной нагрузки на базу данных.
**Причина:** Скрапер скопировал User-Agent официального краулера для обхода базовых проверок.
**Диагностика:** Выполнить ручную верификацию FCrDNS:
```bash
# Шаг 1: Получение имени хоста по IP
host 198.51.100.42
# → 42.100.51.198.in-addr.arpa domain name pointer attacker-vps.example.com.
# Имя не оканчивается на googlebot.com или google.com -> Бот поддельный!
```
**Решение:**
Внедрить проверку списка официальных подсетей поисковых систем (актуализируются через cron раз в сутки) или проверять FCrDNS через NJS/Lua:
```nginx
# /etc/nginx/conf.d/search_engine_subnets.conf
geo $is_real_googlebot {
    default        0;
    66.249.64.0/19 1;
    66.249.80.0/20 1;
    # Полный список подсетей Google
}

map "$http_user_agent:$is_real_googlebot" $fake_googlebot {
    default 0;
    "~*Googlebot:0" 1; # Заявляет, что он Googlebot, но IP не из пула Google
}

server {
    if ($fake_googlebot) {
        return 403 "Forbidden: Spoofed Search Engine User-Agent\n";
    }
}
```

### Проблема 3: Высокая утилизация CPU регулярными выражениями в Nginx

**Симптомы:** Процессы `nginx: worker process` потребляют 100% CPU при росте трафика до 5000+ rps.
**Причина:** Директива `map` выполняет последовательный перебор сотен регулярных выражений вида `~*(?i)...` для каждого запроса.
**Решение:**
1. Оптимизировать хеш-таблицы директивы `map`:
   ```nginx
   map_hash_bucket_size 128;
   map_hash_max_size 4096;
   ```
2. Разделять точные строковые сопоставления (работают через O(1) хеш-таблицу) и регулярные выражения:
   ```nginx
   # Сначала поиск по точному совпадению (O(1))
   map $http_user_agent $exact_bad_bot {
       hostnames;
       default 0;
       "curl/7.88.1" 1;
       "Wget/1.21.3" 1;
   }
   ```
3. Делегировать блокировку повторяющихся нарушителей с L7 (Nginx) на уровень L3/L4 (`nftables` через CrowdSec или Fail2ban). Отбрасывание пакетов ядром Linux на раннем этапе не расходует ресурсы воркеров Nginx.

---

## Лучшие практики

1. **Эшелонирование защиты (L3/L4 против L7):** Не обрабатывайте запросы агрессивных ботов бесконечно на уровне веб-сервера. Если клиент идентифицирован как сканер, передайте его IP в `nftables` / `ipset` на срок от 1 до 24 часов.
2. **Изоляция аналитики и метрик SRE:** Боты искажают бизнес-метрики (конверсия, глубина просмотров) и технические SLI/SLO (время ответа, процент 4xx/5xx). Маркируйте бот-трафик в журналах доступа через специальную переменную:
   ```nginx
   log_format main_with_bots '$remote_addr - $remote_user [$time_local] "$request" '
                             '$status $body_bytes_sent "$http_referer" '
                             '"$http_user_agent" is_bot=$bot_block_action';
   ```
3. **Использование кода 444 в Nginx/Angie для злонамеренных зондов:** Директива `return 444` закрывает TCP-соединение без передачи HTTP-заголовков ответа клиенту. Это экономит сетевой трафик сервера и затрудняет анализ поведения защитных механизмов для атакующего.
4. **Контроль crawl-бюджета легитимных ботов:** Не блокируйте поисковых роботов полностью. Для предотвращения деградации производительности бэкенда задавайте корректные директивы `Crawl-Delay` в файле `robots.txt` и выделяйте отдельную щадящую зону `limit_req` для подтвержденных поисковых IP-адресов.
5. **Защита от обхода через смену User-Agent:** Никогда не используйте фильтрацию по строке `User-Agent` как единственный рубеж защиты. Комбинируйте ее с проверкой наличия браузерных заголовков (`Sec-Fetch-*`), honeypot-ловушками и профилированием ошибок 4xx.
6. **Отказ от внешних облачных зависимостей:** Использование собственных PoW-механизмов (Altcha, mCaptcha) и локальных баз репутации (CrowdSec) гарантирует независимость инфраструктуры от доступности зарубежных облачных CDN, сохраняет конфиденциальность данных пользователей и устраняет риски блокировок сетевых запросов к сторонним API.

---

## Дополнительная информация

### Связанные материалы в базе знаний

- **[Rate Limiting и защита от ботов в веб-серверах](webserver_rate_limiting.md)** — алгоритмы Token Bucket/Leaky Bucket, настройка зон `limit_req` и `limit_conn`.
- **[Защита от DoS-атак в Angie](../Angie/High_Load/dos_protection.md)** — защита транспортного и прикладного уровней, кластерная синхронизация зон и противодействие L7-флуду.
- **[Безопасность веб-сервера Nginx и Angie](../Nginx/Security/nginx_security_guide.md)** — комплексное руководство по харденингу веб-серверов, настройке WAF (ModSecurity / Coraza) и заголовков изоляции.
- **[fail2ban](../../Linux/Security/Tools/fail2ban.md)** — архитектура демона, настройка джейлов и интеграция с `nftables`.
- **[Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md)** — стандарты настройки защитных заголовков и WAF.

### Внешние ресурсы

- **[OWASP Automated Threats to Web Applications](https://owasp.org/www-project-automated-threats-to-web-applications/)** — официальная таксономия автоматизированных угроз и атак ботов (OAT).
- **[CrowdSec Documentation](https://docs.crowdsec.net/)** — руководство по развертыванию бессерверной совместной системы защиты от вторжений.
- **[Altcha Documentation](https://altcha.org/docs/)** — спецификация и интеграция автономного Proof-of-Work механизма защиты форм.
- **[HAProxy Stick-Table Documentation](https://docs.haproxy.org/3.0/configuration.html#stick-table)** — официальная документация по таблицам состояний и счетчикам аномалий.
