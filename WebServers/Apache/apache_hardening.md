# Укрепление безопасности Apache

**Актуально для:** Apache HTTP Server 2.4.x (2.4.62+)

---

## Определения

**Укрепление безопасности Apache (Apache Hardening)** — комплекс архитектурных, системных и конфигурационных мер, направленных на уменьшение поверхности атаки веб-сервера, изоляцию процессов от операционной системы и нейтрализацию типовых векторов угроз прикладного уровня (L7).

**Принцип наименьших привилегий (PoLP — Principle of Least Privilege)** — концепция безопасности, при которой процессу веб-сервера (`apache` / `www-data`) и его дочерним обработчикам предоставляется минимально необходимый набор системных прав (чтение без возможности записи в `DocumentRoot`, ограниченный набор Linux capabilities, запрет на повышение привилегий).

**Эшелонированная оборона (Defense-in-Depth)** — многоуровневая модель безопасности:
1. *Уровень ядра и LSM:* изоляция через SELinux (домен `httpd_t`) или профили AppArmor.
2. *Уровень системного менеджера:* sandboxing службы через systemd unit override (`ProtectSystem`, `ProtectHome`, `PrivateTmp`, `CapabilityBoundingSet`).
3. *Сетевой уровень и ОС:* фильтрация нежелательного трафика файрволом (`nftables` / `firewalld`) и демоном автоматического реагирования `Fail2Ban`.
4. *Уровень веб-сервера:* минимальный набор модулей, строгие лимиты буферов, защита от медленных соединений, безопасная конфигурация TLS 1.3/1.2.
5. *Прикладной уровень:* контроль заголовков браузерной безопасности (`mod_headers`), фильтрация запросов WAF (`mod_security`).

**Slowloris и Slow POST** — атаки типа DoS (Denial of Service), основанные на медленной отправке заголовков или тела HTTP-запроса байт за байтом с целью удержания открытых сокетов и исчерпания пула рабочих потоков/процессов веб-сервера.

**HTTP/2 Rapid Reset (CVE-2023-44487)** — DoS-атака на реализацию протокола HTTP/2, при которой атакующий инициирует множество параллельных потоков и мгновенно сбрасывает их фреймом `RST_STREAM`, создавая критическую нагрузку на CPU веб-сервера без достижения лимитов одновременных сессий.

**`mod_reqtimeout`** — встроенный модуль Apache, задающий жесткие ограничения по времени и минимальной скорости передачи для заголовков и тела клиентских запросов.

**`mod_evasive`** — модуль защиты от DoS, brute-force и L7-флуда, обеспечивающий динамический учет обращений к страницам и сайту с автоматической временной блокировкой IP-адресов нарушителей (HTTP 403).

**`mod_security`** — встраиваемый WAF (Web Application Firewall) прикладного уровня. Детальные настройки правил и OWASP CRS — в [Обзор WAF](../../Security/ApplicationSecurity/waf.md).

**`mod_remoteip`** — модуль корректной замены клиентского IP-адреса на реальный адрес, передаваемый промежуточным балансировщиком или реверс-прокси в заголовках `X-Forwarded-For` / `X-Real-IP`.

**Systemd Sandboxing** — комплекс встроенных в systemd директив изоляции службы на уровне пространств имен Linux (namespaces), ограничений системных вызовов (seccomp) и фильтрации capabilities.

**Fail2Ban** — сервис мониторинга журналов, обнаруживающий аномалии и попытки подбора учетных данных с автоматическим внесением IP-адресов в черный список пакетного фильтра (`nftables`, `ipset`, `iptables`). Детали — в [Fail2Ban](../../Linux/Security/Tools/fail2ban.md).

---

## Основные концепции

### Расположение конфигурационных файлов

В дистрибутивах Linux на базе RHEL и Debian организация конфигурационных файлов существенно различается:

| Компонент | RHEL / Rocky Linux / AlmaLinux | Debian / Ubuntu |
|---|---|---|
| Главный конфигурационный файл | `/etc/httpd/conf/httpd.conf` | `/etc/apache2/apache2.conf` |
| Каталог дополнительных конфигов | `/etc/httpd/conf.d/*.conf` | `/etc/apache2/conf-available/*.conf` |
| Конфигурации виртуальных хостов | `/etc/httpd/conf.d/*.conf` | `/etc/apache2/sites-available/*.conf` |
| Активация виртуальных хостов | Автоматически (`IncludeOptional`) | Симлинки в `/etc/apache2/sites-enabled/` (`a2ensite`) |
| Каталог конфигураций модулей | `/etc/httpd/conf.modules.d/*.conf` | `/etc/apache2/mods-available/*.load`, `*.conf` |
| Активация модулей | Директива `LoadModule` в файле | Симлинки в `/etc/apache2/mods-enabled/` (`a2enmod`) |
| Журнал ошибок (ErrorLog) | `/var/log/httpd/error_log` | `/var/log/apache2/error.log` |
| Журнал доступа (AccessLog) | `/var/log/httpd/access_log` | `/var/log/apache2/access.log` |
| Системный пользователь и группа | `apache:apache` | `www-data:www-data` |
| Служба systemd | `httpd.service` | `apache2.service` |
| Каталог systemd drop-in override | `/etc/systemd/system/httpd.service.d/` | `/etc/systemd/system/apache2.service.d/` |

### Задачи харденинга в практике DevOps, SRE и SysAdmin

По умолчанию Apache поставляется с настройками, ориентированными на максимальную совместимость, что приводит к избыточной открытости сервиса:
- Сервер сообщает полные версии ПО, ОС и модулей в заголовках ответов и страницах ошибок.
- Включены небезопасные методы запросов (`TRACE`, `TRACK`), способствующие атакам Cross-Site Tracing (XST).
- Разрешен переход по символическим ссылкам на системные каталоги (`FollowSymLinks`).
- Включен листинг содержимого директорий при отсутствии индексного файла (`Options +Indexes`).
- Отсутствуют жесткие таймауты на чтение заголовков, что делает сервер беззащитным перед атаками типа Slowloris.
- Рабочие процессы службы имеют доступ ко многим участкам файловой системы хоста.

Системный харденинг решает пять ключевых задач:
1. **Минимизация поверхности атаки** — удаление неиспользуемых модулей, отключение опасных директив и ограничение разрешенных HTTP-методов.
2. **Изоляция скомпрометированного процесса** — при успешной эксплуатации уязвимости в веб-приложении злоумышленник не должен получить доступ к чтению чужих данных, конфигурационных паролей, системных файлов или права записи в исполняемые скрипты.
3. **Отказоустойчивость и защита от DoS** — конфигурация буферов, ограничение скорости и времени ожидания соединений.
4. **Контроль целостности и предотвращение утечек** — сокрытие внутренней архитектуры, маскировка версий, защита служебных файлов (`.git`, `.env`).
5. **Аудит и детектирование инцидентов** — формирование информативных структурированных логов для передачи в SIEM / системы агрегации логов и оперативное реагирование через Fail2Ban.

### Аудит и минимизация используемых модулей

Каждый загруженный модуль Apache увеличивает потребление оперативной памяти каждым процессом и расширяет поверхность атаки. Модули должны активироваться по принципу строгой необходимости.

**Обязательные модули безопасности:**
- `mod_ssl` — терминация TLS/HTTPS, управление сертификатами и безопасными шифрами.
- `mod_headers` — управление HTTP-заголовками ответа (HSTS, CSP, X-Frame-Options и др.).
- `mod_reqtimeout` — защита пула соединений от атак Slowloris и Slow POST.
- `mod_remoteip` — определение реального IP клиента за обратным прокси или балансировщиком.
- `mod_authz_core`, `mod_authz_host` — базовое разграничение доступа (директивы `Require`).

**Модули, подлежащие отключению в production (если не требуются явно):**
- `mod_autoindex` — генерирует HTML-листинг каталогов при отсутствии индексного файла.
- `mod_info` — раскрывает полные сведения о конфигурации сервера по URL `/server-info`.
- `mod_userdir` — сопоставляет URL `~username` с каталогами `/home/username/public_html`.
- `mod_cgi` / `mod_cgid` — устаревшие интерфейсы запуска CGI-скриптов с повышенным риском RCE.
- `mod_status` — мониторинг воркеров. Если требуется для Prometheus `apache_exporter`, должен быть строго изолирован на `127.0.0.1` с обязательной аутентификацией.
- `mod_actions`, `mod_asis`, `mod_speling` — неиспользуемые вспомогательные обработчики.

Отключение модулей:
- **Debian / Ubuntu:** `sudo a2dismod autoindex status info userdir cgi`
- **RHEL / Rocky Linux:** закомментировать строки `LoadModule` в файлах `/etc/httpd/conf.modules.d/*.conf`.

### Модель MPM и устойчивость к DoS

Модель многопроцессорной обработки (MPM) определяет способность сервера выдерживать пиковые нагрузки и L7-атаки:

| MPM | Архитектура | Устойчивость к Slow DoS | Область применения |
|---|---|---|---|
| **`event`** (рекомендуется) | Асинхронные выделенные потоки для Keep-Alive и ожидания запросов (epoll/kqueue) | **Высокая.** Соединение не блокирует рабочий поток до поступления реальных данных. | Стандарт для всех современных систем (RHEL 9+, Ubuntu 22.04+, Debian 12+). Интеграция с PHP через PHP-FPM (`mod_proxy_fcgi`). |
| **`worker`** | Пул процессов, каждый из которых порождает пул потоков | **Средняя.** Потоки блокируются при медленной передаче. | Сбалансированный вариант для модулей, не поддерживающих async event. |
| **`prefork`** (устарел) | Один процесс обрабатывает ровно одно соединение без многопоточности | **Критически низкая.** Атака медленными запросами исчерпывает `MaxRequestWorkers` за считанные секунды. | Исключительно legacy-системы с потоконебезопасным `mod_php`. Не рекомендуется к использованию в открытых сетях. |

### Соответствие стандартам безопасности (CIS Benchmark, PCI DSS)

Конфигурация Apache должна отвечать требованиям профилей CIS Apache HTTP Server Benchmark и стандарту PCI DSS 4.0:
- **CIS 2.1 / PCI DSS 2.2.4:** Отключение неиспользуемых сервисов и модулей сервера.
- **CIS 2.2 / PCI DSS 2.2.5:** Отключение `TraceEnable` (предотвращение Cross-Site Tracing).
- **CIS 2.3:** Маскировка версионной информации (`ServerTokens Prod`, `ServerSignature Off`).
- **CIS 3.1 / PCI DSS 10.2:** Централизованное ведение журнала доступа и ошибок, запрет на изменение логов процессом веб-сервера.
- **CIS 5.1 / PCI DSS 4.1:** Использование только защищенных версий протоколов (TLS 1.2 и TLS 1.3) и стойких криптографических наборов шифров.
- **CIS 5.5:** Ограничение максимального размера тела запроса (`LimitRequestBody`).
- **CIS 6.1:** Установка ограничивающих прав DAC на каталоги и файлы конфигурации (владелец `root`, запрет записи группе и остальным).

---

## Практические сценарии

### Сценарий 1: Разграничение прав на файловой системе (DAC) и безопасный umask

Веб-процесс Apache (`apache` на RHEL или `www-data` на Debian) не должен являться владельцем файлов `DocumentRoot`. Если скомпрометированный веб-скрипт имеет права записи в корень сайта, злоумышленник может перезаписать файлы `.htaccess`, `index.php` или внедрить постоянный веб-шелл.

**Правило:** Владелец файлов `DocumentRoot` — системный пользователь или `root`. Группа — группа веб-сервера с правами только на чтение. Права записи предоставляются исключительно изолированным каталогам загрузки (`uploads`), где принудительно отключено исполнение скриптов.

```bash
# Настройка базовых прав для Debian/Ubuntu (для RHEL заменить www-data на apache)
sudo chown -R root:www-data /var/www/html

# Каталоги: 750 (drwxr-x---) — чтение и вход для веб-сервера, запрет для остальных
sudo find /var/www/html -type d -exec chmod 750 {} \;

# Обычные файлы: 640 (-rw-r-----) — чтение для веб-сервера, запрет модификации
sudo find /var/www/html -type f -exec chmod 640 {} \;

# Выделенный каталог загрузки файлов приложения (требует записи)
sudo chown -R www-data:www-data /var/www/html/uploads
sudo chmod 750 /var/www/html/uploads

# Установка безопасного umask (0027) для процесса Apache через systemd override,
# чтобы создаваемые сервером временные файлы не были доступны другим пользователям ОС
sudo mkdir -p /etc/systemd/system/apache2.service.d
sudo tee /etc/systemd/system/apache2.service.d/umask.conf <<'EOF'
[Service]
UMask=0027
EOF
sudo systemctl daemon-reload
```

В каталоге загрузок необходимо гарантированно запретить исполнение любых интерпретируемых файлов (CGI, PHP, SSI):

```apacheconf
# /etc/apache2/conf-available/secure-uploads.conf (или /etc/httpd/conf.d/secure-uploads.conf)
<Directory "/var/www/html/uploads">
    # Запрет выполнения скриптов и листинга файлов
    Options -ExecCGI -Includes -Indexes -FollowSymLinks
    AllowOverride None

    # Принудительное отключение обработчиков скриптов
    <FilesMatch "\.(php|phtml|php3|php4|php5|php7|php8|phps|cgi|pl|py|sh|bash)$">
        Require all denied
    </FilesMatch>

    # Для PHP-FPM — отмена передачи запроса через прокси
    SetHandler default-handler
</Directory>
```

### Сценарий 2: Глобальная изоляция корня и скрытие служебной информации

Основополагающее правило безопасности Apache: весь доступ к файловой системе сервера по умолчанию блокируется, а разрешения выдаются строго точечно для каждого рабочего `DocumentRoot`.

```apacheconf
# Базовая защита в основном конфигурационном файле (httpd.conf / apache2.conf)

# 1. Запрет доступа ко всей файловой системе сервера
<Directory />
    AllowOverride None
    Require all denied
    Options None
</Directory>

# 2. Разрешение доступа строго к DocumentRoot
<Directory "/var/www/html">
    # Запрет листинга (-Indexes)
    # Замена FollowSymLinks на SymLinksIfOwnerMatch для защиты от подмены файлов
    Options -Indexes -FollowSymLinks +SymLinksIfOwnerMatch -ExecCGI -Includes
    AllowOverride None
    Require all granted
</Directory>

# 3. Скрытие версии сервера и ОС
ServerTokens Prod
ServerSignature Off

# 4. Отключение метода TRACE (защита от Cross-Site Tracing / XST)
TraceEnable Off

# 5. Предотвращение утечки номеров inode через заголовок ETag
# В кластерных средах ETag на базе inode различается на разных нодах, ломая кэширование
FileETag MTime Size
```

**Значения директивы `ServerTokens`:**
- `Prod` — `Server: Apache` (рекомендуется для production, скрывает подверсию и дистрибутив).
- `Major` — `Server: Apache/2`.
- `Minor` — `Server: Apache/2.4`.
- `Minimal` — `Server: Apache/2.4.62`.
- `OS` — `Server: Apache/2.4.62 (Debian)`.
- `Full` — `Server: Apache/2.4.62 (Debian) OpenSSL/3.0.13 mod_perl/2.0.13` (крайне небезопасно, раскрывает полный вектор атаки).

### Сценарий 3: Защита скрытых файлов, репозиториев и служебных копий

Служебные файлы систем контроля версий (`.git`, `.svn`), файлы конфигурации (`.env`, `config.json`), бэкапы текстовых редакторов (`.bak`, `.swp`, `~`) часто случайно попадают в `DocumentRoot` и содержат пароли к базам данных и ключи API.

```apacheconf
# /etc/httpd/conf.d/security-files.conf или /etc/apache2/conf-available/security-files.conf

# Блокировка доступа ко всем файлам и каталогам, начинающимся с точки (.git, .env, .htaccess)
<FilesMatch "^\.">
    Require all denied
</FilesMatch>

# Блокировка доступа к исходникам, архивам, логам и служебным дампам
<FilesMatch "(^#.*#|\.(bak|config|dist|fla|inc|ini|log|psd|sh|sql|sw[op]|yaml|yml)|~)$">
    Require all denied
</FilesMatch>

# Блокировка прямых обращений к служебным каталогам систем сборки и контроля версий
<DirectoryMatch "/(\.git|\.svn|\.hg|\.bzr|\.vscode|\.idea)">
    Require all denied
</DirectoryMatch>
```

Проверка запрета доступа:
```bash
curl -I -s http://localhost/.env | grep "HTTP/"
# → HTTP/1.1 403 Forbidden

curl -I -s http://localhost/.git/config | grep "HTTP/"
# → HTTP/1.1 403 Forbidden
```

### Сценарий 4: Ограничение HTTP-методов и безопасная политика CORS

Если веб-приложение принимает только запросы на чтение и стандартную отправку форм, обработку всех нестандартных и модифицирующих методов (`PUT`, `DELETE`, `CONNECT`, `PATCH`) следует отключить на уровне веб-сервера.

```apacheconf
<Directory "/var/www/html">
    # Разрешены только безопасные базовые методы
    <LimitExcept GET POST HEAD OPTIONS>
        Require all denied
    </LimitExcept>
</Directory>

# Для каталогов REST API методы задаются в соответствии со спецификацией
<Directory "/var/www/html/api">
    <LimitExcept GET POST PUT DELETE PATCH HEAD OPTIONS>
        Require all denied
    </LimitExcept>
</Directory>
```

Безопасная конфигурация заголовков CORS (Cross-Origin Resource Sharing) без подстановочного символа `*`:

```apacheconf
<Location "/api">
    <IfModule mod_headers.c>
        # Разрешение только для доверенного внутреннего домена
        SetEnvIf Origin "^https://(app\.internal\.corp|admin\.internal\.corp)$" ORIGIN_SUB_DOMAIN=$0
        Header always set Access-Control-Allow-Origin "%{ORIGIN_SUB_DOMAIN}e" env=ORIGIN_SUB_DOMAIN
        Header always set Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS"
        Header always set Access-Control-Allow-Headers "Content-Type, Authorization, X-Requested-With"
        Header always set Access-Control-Allow-Credentials "true"
        Header always set Access-Control-Max-Age "86400"
    </IfModule>
</Location>
```

### Сценарий 5: Лимиты ресурсов и защита от переполнения буферов

Атаки, направленные на исчерпание памяти или дискового пространства через отправку гигантских тел запросов (upload bombs), невалидных заголовков или чрезмерно длинных URI, блокируются директивами группы `LimitRequest*`:

```apacheconf
# /etc/httpd/conf.d/limits.conf или /etc/apache2/conf-available/limits.conf

# 1. Максимальный размер тела запроса (в байтах): 10 МБ для всего сервера
LimitRequestBody 10485760

# 2. Максимальное число полей HTTP-заголовков в запросе (по умолчанию 100)
LimitRequestFields 50

# 3. Максимальный размер одного поля заголовка (в байтах, по умолчанию 8190)
LimitRequestFieldSize 8190

# 4. Максимальная длина строки HTTP-запроса (URI + метод, по умолчанию 8190)
LimitRequestLine 8190

# 5. Лимит на тело XML-запроса (защита от XML Entity Expansion / Billion Laughs)
LimitXMLRequestBody 1048576

# Точечное переопределение для разделов загрузки больших файлов
<Location "/uploads/video">
    # 100 МБ для видеоматериалов
    LimitRequestBody 104857600
</Location>
```

Диагностика превышения лимита:
```bash
# Тест отправки данных сверх установленного лимита
curl -X POST -d @/dev/urandom --limit-rate 5M http://localhost/ --max-time 2 -s -o /dev/null -w "%{http_code}\n"
# → 413
```

### Сценарий 6: Защита от Slow DoS (Slowloris, Slow POST) через `mod_reqtimeout`

Атаки Slowloris и Slow POST удерживают соединения в открытом состоянии, передавая данные крайне маленькими порциями (по 1 байту раз в несколько секунд), что приводит к заполнению слотов `MaxRequestWorkers` легитимных клиентов.

```apacheconf
# Подключение модуля mod_reqtimeout (в Debian обычно включен по умолчанию)
<IfModule mod_reqtimeout.c>
    # Синтаксис: RequestReadTimeout header=таймаут[-макс_таймаут][,MinRate=скорость_байт_сек]
    #                             body=таймаут[-макс_таймаут][,MinRate=скорость_байт_сек]
    # Клиент имеет 20 секунд на отправку заголовков. Каждые переданные 500 байт
    # добавляют 1 секунду, но не более 40 секунд суммарно.
    # Для тела запроса: 20 секунд ожидания первого байта, далее минимальная скорость 500 Б/сек.
    RequestReadTimeout header=20-40,MinRate=500 body=20-40,MinRate=500
</IfModule>

# Настройка KeepAlive в контексте защиты от DoS
# Не отключайте KeepAlive целиком при использовании event MPM, но уменьшите время удержания
KeepAlive On
MaxKeepAliveRequests 100
KeepAliveTimeout 3
```

### Сценарий 7: Защита протокола HTTP/2 от атак исчерпания потоков (Rapid Reset)

В Apache 2.4.58+ включена встроенная защита от атаки HTTP/2 Rapid Reset (CVE-2023-44487). Для предотвращения истощения CPU и памяти при мультиплексировании запросов необходима тонкая настройка модуля `mod_http2`:

```apacheconf
# /etc/httpd/conf.d/http2-hardening.conf или /etc/apache2/conf-available/http2-hardening.conf
<IfModule mod_http2.c>
    Protocols h2 http/1.1

    # Запрет прямого HTTP/2 без предварительного согласования через TLS ALPN
    H2Direct off

    # Максимальное количество одновременных активных потоков на одну HTTP/2 сессию (клиент)
    # По умолчанию 100; уменьшение до 50 снижает пиковую нагрузку при флуде
    H2MaxSessionStreams 50

    # Объем памяти под буфер потока (в байтах)
    H2StreamMaxMemSize 65536

    # Размер начального окна управления потоком (flow control window)
    H2WindowSize 65535

    # Минимальная скорость передачи данных в потоке (байт/сек),
    # при нарушении соединение закрывается по таймауту аналогично mod_reqtimeout
    H2MinDataRate 500
</IfModule>
```

### Сценарий 8: Ограничение скорости (Rate Limiting) и защита от L7 DoS

Для предотвращения выкачивания статических файлов ботами и защиты от перебора паролей используются встроенный `mod_ratelimit` и модуль `mod_evasive`.

#### 1. Ограничение пропускной способности (`mod_ratelimit`)

```apacheconf
<IfModule mod_ratelimit.c>
    # Ограничение скорости отдачи файлов для каталога загрузок до 100 КБ/сек на поток
    <Location "/downloads">
        SetOutputFilter RATE_LIMIT
        SetEnv rate-limit 100
        # Опционально: начальный всплеск без ограничений в КБ
        SetEnv rate-initial-burst 512
    </Location>
</IfModule>
```

#### 2. Защита от L7-флуда и сканирования (`mod_evasive`)

```apacheconf
# Конфигурация /etc/httpd/conf.d/mod_evasive.conf или /etc/apache2/mods-available/evasive.conf
<IfModule mod_evasive20.c>
    # Размер хэш-таблицы для отслеживания IP (простое число)
    DOSHashTableSize 3097

    # Порог для одного и того же URI: не более 5 запросов за интервал DOSPageInterval
    DOSPageCount 5
    DOSPageInterval 1

    # Общий порог запросов к сайту: не более 50 запросов за интервал DOSSiteInterval
    DOSSiteCount 50
    DOSSiteInterval 1

    # Длительность блокировки нарушителя в секундах (возвращается 403 Forbidden)
    DOSBlockingPeriod 30

    # Каталог временных файлов блокировок (должен принадлежать пользователю apache/www-data)
    DOSLogDir "/var/log/mod_evasive"

    # Белые списки: шлюзы, локалхост и внутренний периметр мониторинга
    DOSWhitelist 127.0.0.1
    DOSWhitelist 10.0.0.0/8
    DOSWhitelist 192.168.0.0/16

    # Оповещение по почте или выполнение внешнего скрипта при блокировке
    # DOSEmailNotify alert@example.corp
    # DOSSystemCommand "/usr/local/bin/notify_security.sh %s"
</IfModule>
```

Создание каталога для хранения блокировок с корректными правами:
```bash
sudo mkdir -p /var/log/mod_evasive
# Для Debian/Ubuntu
sudo chown -R www-data:www-data /var/log/mod_evasive
# Для RHEL/Rocky
# sudo chown -R apache:apache /var/log/mod_evasive
sudo chmod 700 /var/log/mod_evasive
```

### Сценарий 9: Современные заголовки безопасности HTTP (`mod_headers`)

Модуль `mod_headers` обеспечивает передачу директив защиты клиенту, предотвращая кликджекинг, атаки по внедрению скриптов (XSS) и кражу контекста.

```apacheconf
# /etc/httpd/conf.d/security-headers.conf или /etc/apache2/conf-available/security-headers.conf
<IfModule mod_headers.c>
    # 1. HSTS — принудительный переход на HTTPS на 2 года, включая поддомены, с готовностью к preload
    Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"

    # 2. Защита от Clickjacking: запрет встраивания сайта во фреймы со сторонних доменов
    Header always set X-Frame-Options "SAMEORIGIN"

    # 3. Запрет MIME-sniffing: браузер обязан следовать указанному Content-Type
    Header always set X-Content-Type-Options "nosniff"

    # 4. Referrer Policy: передача только источника (origin) при межсайтовых запросах
    Header always set Referrer-Policy "strict-origin-when-cross-origin"

    # 5. Permissions-Policy: отключение неиспользуемых аппаратных возможностей браузера
    Header always set Permissions-Policy "geolocation=(), camera=(), microphone=(), payment=(), usb=()"

    # 6. Изоляция контекста браузера (Spectre / cross-origin защита)
    Header always set Cross-Origin-Opener-Policy "same-origin"
    Header always set Cross-Origin-Resource-Policy "same-origin"

    # 7. Content Security Policy (CSP) — базовая строгая политика
    Header always set Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self';"

    # 8. Удаление заголовков, раскрывающих технологии бэкенда
    Header unset X-Powered-By
    Header always unset X-Powered-By
</IfModule>
```

Проверка заголовков ответа:
```bash
curl -I -k https://localhost/ | grep -iE "strict-transport|x-frame|x-content-type|referrer|content-security"
# → Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
# → X-Frame-Options: SAMEORIGIN
# → X-Content-Type-Options: nosniff
# → Referrer-Policy: strict-origin-when-cross-origin
# → Content-Security-Policy: default-src 'self'; ...
```

### Сценарий 10: Харденинг SSL/TLS (`mod_ssl`)

Конфигурация TLS должна исключать устаревшие протоколы (SSLv3, TLS 1.0, TLS 1.1) и уязвимые блочные шифры в режиме CBC. Используются только криптографические протоколы TLS 1.2 и TLS 1.3 с AEAD-шифрами (GCM, ChaCha20).

```apacheconf
# /etc/httpd/conf.d/ssl-hardening.conf или /etc/apache2/conf-available/ssl-hardening.conf
<IfModule mod_ssl.c>
    # Глобальные параметры SSL

    # Разрешены только TLS 1.2 и TLS 1.3
    SSLProtocol -all +TLSv1.2 +TLSv1.3

    # Шифры для TLS 1.2 (AEAD ECDHE)
    SSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384

    # Приоритет шифров сервера для TLS 1.2
    SSLHonorCipherOrder on

    # Отключение сжатия SSL (защита от атаки CRIME)
    SSLCompression off

    # Запрет небезопасного повторного согласования сессии (renegotiation)
    SSLInsecureRenegotiation off

    # Разделяемая память для кэша TLS-сессий
    # RHEL: shmcb:/run/httpd/sslcache(512000), Debian: shmcb:${APACHE_RUN_DIR}/ssl_scache(512000)
    SSLSessionCache "shmcb:/var/run/httpd-ssl-cache(512000)"
    SSLSessionCacheTimeout 300

    # Отключение тикетов сессий (Session Tickets), если не настроена ротация ключей тикетов,
    # для гарантии совершенной прямой секретности (PFS)
    SSLSessionTickets off

    # OCSP Stapling (ускорение рукопожатия и защита приватности валидации сертификатов)
    SSLUseStapling on
    SSLStaplingResponderTimeout 5
    SSLStaplingReturnResponderErrors off
    SSLStaplingCache "shmcb:/var/run/ocsp-stapling-cache(128000)"
</IfModule>
```

Конфигурация виртуального хоста HTTPS:
```apacheconf
<VirtualHost *:443>
    ServerName secure.example.corp
    DocumentRoot /var/www/html

    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/server.crt
    SSLCertificateKeyFile /etc/ssl/private/server.key
    SSLCertificateChainFile /etc/ssl/certs/chain.crt

    # Права на server.key должны быть строго 600 или 640 (root:root / root:apache)
</VirtualHost>
```

### Сценарий 11: Харденинг Reverse Proxy и модуля `mod_remoteip`

Неправильно настроенный прокси-модуль `mod_proxy` превращает сервер в **Open Proxy**, используемый злоумышленниками для атак на внешние цели или обхода периметра безопасности (SSRF).

#### 1. Запрет Open Proxy

```apacheconf
# Критически важное правило: прямое проксирование ОБЯЗАНО быть отключено!
ProxyRequests Off

# Запрет на передачу заголовка Proxy (защита от уязвимости httpoxy / RFC 7230)
<IfModule mod_headers.c>
    RequestHeader unset Proxy early
</IfModule>
```

#### 2. Защита от SSRF (Server-Side Request Forgery)

При настройке обратного проксирования (`ProxyPass`) необходимо блокировать обращение к внутренним портам управления и локальной петле `127.0.0.1`:

```apacheconf
<VirtualHost *:443>
    ServerName app.example.corp

    # Запрет проксирования служебных URI
    ProxyPassMatch "^/(status|server-status|metrics|internal-api)" "!"

    # Проксирование к выделенному бэкенду
    ProxyPass "/" "http://10.10.20.15:8080/" timeout=30 keepalive=On
    ProxyPassReverse "/" "http://10.10.20.15:8080/"
</VirtualHost>
```

#### 3. Безопасная настройка `mod_remoteip`

Без указания доверенных прокси любой клиент может подделать заголовок `X-Forwarded-For`, обойдя IP-фильтры в директивах `Require ip`:

```apacheconf
<IfModule mod_remoteip.c>
    # Заголовок, из которого берется реальный IP
    RemoteIPHeader X-Forwarded-For

    # IP-адреса НАШИХ доверенных балансировщиков (HAProxy / Nginx / внутренний ingress)
    # Только для этих адресов Apache заменит remote_ip на значение из заголовка
    RemoteIPTrustedProxy 10.10.10.1
    RemoteIPTrustedProxy 10.10.10.2
    RemoteIPTrustedProxy 127.0.0.1
</IfModule>
```

### Сценарий 12: Защита служебных эндпоинтов (`/server-status`, `/server-info`)

Модули `mod_status` и `mod_info` раскрывают активные подключения, внутренние URL, клиентские IP-адреса и конфигурацию. Они должны быть полностью заблокированы для внешнего мира.

```apacheconf
# /etc/httpd/conf.d/status-hardening.conf или /etc/apache2/conf-available/status-hardening.conf

# Полностью отключаем mod_info в production
<Location "/server-info">
    Require all denied
</Location>

# mod_status разрешен только для локального сбора метрик (например, prometheus node_exporter)
<Location "/server-status">
    SetHandler server-status
    # Запрет для всех по умолчанию
    Require all denied
    # Разрешено только с loopback и адреса сервера мониторинга
    Require local
    Require ip 127.0.0.1
    Require ip ::1
    Require ip 10.10.50.25

    # Требовать обязательную Basic-аутентификацию даже для внутренних сетей
    AuthType Basic
    AuthName "Prometheus Exporter Access Only"
    AuthUserFile /etc/httpd/.htpasswd-status
    Require valid-user
</Location>
```

Создание файла паролей:
```bash
sudo htpasswd -cB /etc/httpd/.htpasswd-status prometheus_scraper
# Права на файл паролей: только root и чтение веб-сервером
sudo chown root:apache /etc/httpd/.htpasswd-status
sudo chmod 640 /etc/httpd/.htpasswd-status
```

### Сценарий 13: Изоляция процессов на уровне ОС через systemd unit override (Sandboxing)

Современный systemd предоставляет мощный механизм sandboxing на уровне пространств имен Linux. При компрометации процесса Apache изоляция блокирует чтение домашних каталогов пользователей, перемонтирует системные каталоги `/usr` и `/etc` в режим Read-Only и блокирует опасные системные вызовы.

> [!IMPORTANT]
> При настройке `CapabilityBoundingSet` для службы Apache нельзя оставлять только `CAP_NET_BIND_SERVICE`. Главный процесс Apache стартует от имени `root` для привязки к 80/443 портам, после чего сбрасывает привилегии для воркеров на пользователя `apache` / `www-data` через системные вызовы `setuid()` / `setgid()`. Лишение процесса возможностей `CAP_SETUID` и `CAP_SETGID` приведет к аварийной остановке сервера при запуске!

Создание override-файла изоляции службы:

```ini
# /etc/systemd/system/httpd.service.d/hardening.conf (для Debian: /etc/systemd/system/apache2.service.d/hardening.conf)
[Service]
# Лимит на количество открытых файлов (дескрипторов)
LimitNOFILE=65535

# Запрет доступа к /home, /root и /run/user
ProtectHome=true

# Монтирование файловой системы в режиме строгого Read-Only
# Запись разрешается ТОЛЬКО явно через ReadWritePaths
ProtectSystem=strict

# Разрешенные пути для записи (логи, рантайм сокеты, кэш, каталоги загрузок)
ReadWritePaths=/var/log/httpd /var/log/apache2 /var/run /run /var/cache/httpd /var/cache/apache2 /var/www/html/uploads /var/log/mod_evasive

# Изолированный временный каталог (/tmp и /var/tmp)
PrivateTmp=true

# Запрет доступа к физическим устройствам (/dev)
PrivateDevices=true

# Запрет изменения параметров ядра через /proc/sys, /sys
ProtectKernelTunables=true

# Запрет загрузки модулей ядра Linux
ProtectKernelModules=true

# Запрет модификации контрольных групп cgroups
ProtectControlGroups=true

# Запрет на получение новых привилегий дочерними процессами (через SUID/SGID)
NoNewPrivileges=true

# Запрет использования realtime-планирования
RestrictRealtime=true

# Разрешенные семейства сетевых сокетов (только IPv4, IPv6 и локальные Unix-сокеты)
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

# Минимально необходимый набор Linux capabilities для работы Apache:
# - CAP_NET_BIND_SERVICE: привязка к портам 80 и 443
# - CAP_SETUID, CAP_SETGID: сброс привилегий дочерних воркеров на apache/www-data
# - CAP_KILL: передача сигналов дочерним воркерам при ротации и reload
# - CAP_SYS_RESOURCE: управление лимитами процессов и разделяемой памятью
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID CAP_KILL CAP_SYS_RESOURCE
```

Применение конфигурации systemd:
```bash
sudo systemctl daemon-reload
sudo systemctl restart httpd   # или sudo systemctl restart apache2

# Проверка применения ограничений процесса
systemctl show httpd -p ProtectSystem -p ProtectHome -p PrivateTmp -p NoNewPrivileges
# → ProtectSystem=strict
# → ProtectHome=yes
# → PrivateTmp=yes
# → NoNewPrivileges=yes
```

### Сценарий 14: Принудительный контроль доступа (SELinux и AppArmor)

Мандатный контроль доступа гарантирует, что даже пользователь `root` или скомпрометированный веб-сервер не смогут выйти за границы разрешенной политики безопасности ядра.

#### 1. SELinux (RHEL, AlmaLinux, Rocky Linux)

Apache работает в домене безопасности `httpd_t`.

**Контексты файлов:**
- `httpd_sys_content_t` — статические файлы и скрипты, доступные только на чтение.
- `httpd_sys_rw_content_t` — каталоги с правом записи для Apache (каталоги загрузки, локальный кэш).
- `httpd_log_t` — журналы сервера в `/var/log/httpd`.

```bash
# Проверка текущих контекстов файлов
ls -Z /var/www/html
# → system_u:object_r:httpd_sys_content_t:s0 index.html

# Назначение постоянного контекста чтения для нестандартного каталога
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/web/html(/.*)?"
sudo restorecon -Rv /srv/web/html

# Назначение контекста записи для каталога uploads
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/www/html/uploads(/.*)?"
sudo restorecon -Rv /var/www/html/uploads
```

**Критически важные SELinux Booleans:**

```bash
# Разрешить исходящие TCP-подключения к бэкендам (PHP-FPM, Node.js, реверс-прокси)
sudo setsebool -P httpd_can_network_connect on

# Разрешить прямое подключение к базам данных (PostgreSQL, MariaDB)
sudo setsebool -P httpd_can_network_connect_db on

# ЗАПРЕТИТЬ доступ к домашним каталогам пользователей (защита от утечки /home)
sudo setsebool -P httpd_enable_homedirs off

# ЗАПРЕТИТЬ чтение пользовательского контента вне DocumentRoot
sudo setsebool -P httpd_read_user_content off

# Просмотр статуса булеанов
getsebool httpd_can_network_connect httpd_can_network_connect_db httpd_enable_homedirs
# → httpd_can_network_connect --> on
# → httpd_can_network_connect_db --> on
# → httpd_enable_homedirs --> off
```

#### 2. AppArmor (Debian, Ubuntu)

В Debian/Ubuntu используется AppArmor. Профиль Apache располагается в `/etc/apparmor.d/usr.sbin.apache2`.

```bash
# Проверка статуса профиля Apache
sudo aa-status | grep apache2
# → /usr/sbin/apache2 (enforce)

# Перевод профиля в строгий режим блокировки при необходимости
sudo aa-enforce /usr/sbin/apache2

# Просмотр блокировок в системном журнале
sudo dmesg | grep -i apparmor | grep apache2
```

### Сценарий 15: Интеграция с Fail2Ban для автоматической блокировки атак

Fail2Ban считывает журналы ошибок и доступа Apache, определяя попытки подбора паролей к `.htpasswd`, сканирование уязвимостей и DoS-аномалии, после чего мгновенно блокирует IP нарушителя в пакетном фильтре `nftables`.

```ini
# /etc/fail2ban/jail.d/apache-hardening.local

[DEFAULT]
# Использование современного бэкенда nftables
banaction = nftables-multiport

# 1. Защита от перебора HTTP Basic Auth
[apache-auth]
enabled  = true
port     = http,https
filter   = apache-auth
logpath  = %(apache_error_log)s
maxretry = 3
findtime = 600
bantime  = 3600

# 2. Блокировка сканеров уязвимостей и подозрительных ботов
[apache-badbots]
enabled  = true
port     = http,https
filter   = apache-badbots
logpath  = %(apache_access_log)s
maxretry = 1
bantime  = 86400

# 3. Защита от попыток эксплуатации переполнения буферов
[apache-overflows]
enabled  = true
port     = http,https
filter   = apache-overflows
logpath  = %(apache_error_log)s
maxretry = 2
bantime  = 7200

# 4. Блокировка попыток запуска несуществующих скриптов (CGI/PHP probe)
[apache-noscript]
enabled  = true
port     = http,https
filter   = apache-noscript
logpath  = %(apache_error_log)s
maxretry = 5
findtime = 300
bantime  = 3600
```

Управление и аудит Fail2Ban:
```bash
# Перезапуск и проверка статуса джейлов
sudo systemctl restart fail2ban
sudo fail2ban-client status apache-auth
# → Status for the jail: apache-auth
# |- Filter
# |  |- Currently failed: 0
# |  |- Total failed:     12
# `- Actions
#    |- Currently banned: 1
#    |- Total banned:     1
#    `- Banned IP list:   198.51.100.42

# Ручная разблокировка ложного срабатывания
sudo fail2ban-client unban 198.51.100.42
```

### Сценарий 16: Аудитное и защищенное логирование (SIEM / Observability)

Для качественного расследования инцидентов и выявления медленных атак формат логов должен содержать тайминги ответа (в микросекундах `%D` или миллисекундах `%{ms}T`), информацию о TLS и реальный IP. Для защиты от удаления логов скомпрометированным сервером потоки логирования направляются в централизованный демон `rsyslog` или `vector`.

```apacheconf
# /etc/httpd/conf.d/logging.conf или /etc/apache2/conf-available/logging.conf

# 1. Расширенный текстовый формат с таймингами обработки (%D — микросекунды)
LogFormat "%a %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\" %D %{SSL_PROTOCOL}x %{SSL_CIPHER}x" hardened_combined

# 2. Структурированный JSON-формат для Elasticsearch, Vector, Graylog
LogFormat "{\"timestamp\":\"%{%Y-%m-%dT%H:%M:%S%z}t\",\"client_ip\":\"%a\",\"forwarded_for\":\"%{X-Forwarded-For}i\",\"method\":\"%m\",\"uri\":\"%U\",\"query\":\"%q\",\"protocol\":\"%H\",\"status\":%>s,\"bytes\":%B,\"duration_us\":%D,\"referer\":\"%{Referer}i\",\"user_agent\":\"%{User-Agent}i\",\"vhost\":\"%v\"}" json_audit

# Запись в локальные файлы
CustomLog "/var/log/httpd/access.log" hardened_combined
CustomLog "/var/log/httpd/access_json.log" json_audit

# 3. Безопасная отправка логов через pipe в локальный syslog с изоляцией
# Процесс Apache не имеет прямого дескриптора на модификацию архивов логов
CustomLog "|/usr/bin/logger -p local5.info -t apache_access" hardened_combined
ErrorLog "|/usr/bin/logger -p local5.err -t apache_error"
```

Настройка ротации логов (`/etc/logrotate.d/httpd`):
```text
/var/log/httpd/*log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    sharedscripts
    create 0640 root root
    postrotate
        /usr/bin/systemctl reload httpd.service > /dev/null 2>/dev/null || true
    endscript
}
```

### Сценарий 17: Автоматизация харденинга через Ansible (IaC)

Пример Ansible-плейбука для автоматического применения базовых мер укрепления на серверах RHEL и Debian:

```yaml
---
- name: Hardening веб-сервера Apache
  hosts: webservers
  become: true
  vars:
    apache_pkg: "{{ 'httpd' if ansible_os_family == 'RedHat' else 'apache2' }}"
    apache_user: "{{ 'apache' if ansible_os_family == 'RedHat' else 'www-data' }}"
    apache_conf_dir: "{{ '/etc/httpd/conf.d' if ansible_os_family == 'RedHat' else '/etc/apache2/conf-available' }}"

  tasks:
    - name: Создание каталога systemd override
      ansible.builtin.file:
        path: "/etc/systemd/system/{{ apache_pkg }}.service.d"
        state: directory
        owner: root
        group: root
        mode: '0755'

    - name: Установка параметров sandboxing в systemd override
      ansible.builtin.copy:
        dest: "/etc/systemd/system/{{ apache_pkg }}.service.d/hardening.conf"
        content: |
          [Service]
          LimitNOFILE=65535
          ProtectHome=true
          ProtectSystem=strict
          ReadWritePaths=/var/log/{{ apache_pkg }} /run /var/cache/{{ apache_pkg }} /var/www/html/uploads
          PrivateTmp=true
          PrivateDevices=true
          ProtectKernelTunables=true
          ProtectKernelModules=true
          ProtectControlGroups=true
          NoNewPrivileges=true
          RestrictRealtime=true
          RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
          CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID CAP_KILL CAP_SYS_RESOURCE
        owner: root
        group: root
        mode: '0644'
      notify: Reload systemd and restart apache

    - name: Применение строгих прав на каталог DocumentRoot
      ansible.builtin.file:
        path: /var/www/html
        owner: root
        group: "{{ apache_user }}"
        mode: '0750'
        state: directory

    - name: Развертывание базовой конфигурации безопасности Apache
      ansible.builtin.copy:
        dest: "{{ apache_conf_dir }}/00-hardening.conf"
        content: |
          ServerTokens Prod
          ServerSignature Off
          TraceEnable Off
          FileETag MTime Size
          <Directory />
              AllowOverride None
              Require all denied
              Options None
          </Directory>
          <FilesMatch "^\.">
              Require all denied
          </FilesMatch>
        owner: root
        group: root
        mode: '0644'
      notify: Reload apache

  handlers:
    - name: Reload systemd and restart apache
      ansible.builtin.systemd:
        name: "{{ apache_pkg }}"
        state: restarted
        daemon_reload: true

    - name: Reload apache
      ansible.builtin.systemd:
        name: "{{ apache_pkg }}"
        state: reloaded
```

---

## Операции и команды

### Валидация и аудит конфигурации

| Команда | Назначение | Ожидаемый результат |
|---|---|---|
| `apachectl configtest` / `httpd -t` | Проверка синтаксиса конфигурационных файлов | `Syntax OK` |
| `apachectl -V` | Анализ параметров компиляции, путей и MPM | Вывод версии, `Server MPM: event`, `HTTPD_ROOT` |
| `apachectl -M` | Список всех активных статических и shared модулей | Алфавитный перечень модулей `..._module (shared)` |
| `apachectl -S` | Проверка виртуальных хостов, портов и перекрытий | Таблица VHost: сопоставление IP:Port, ServerName и файлов |
| `systemd-analyze security httpd` | Аудит уровня защищенности сервиса systemd | Численный рейтинг экспозиции службы (например `1.8 OK`) |

Пример вывода проверки конфигурации:
```bash
apachectl configtest
# → Syntax OK
```

Пример аудита безопасности службы systemd:
```bash
systemd-analyze security httpd.service | grep -E "ProtectSystem|ProtectHome|PrivateTmp|NoNewPrivileges"
# → ✗ ProtectSystem=                          strict                                           0.2
# → ✗ ProtectHome=                            yes                                              0.2
# → ✗ PrivateTmp=                             yes                                              0.4
# → ✗ NoNewPrivileges=                        yes                                              0.2
```

### Инспекция безопасности во время работы

| Команда | Назначение | Пример команды и вывода |
|---|---|---|
| Проверка открытых портов | Контроль сетевых интерфейсов процесса | `ss -tlpn \| grep -E "httpd\|apache2"`<br>`# → LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("httpd",pid=1024,fd=4))` |
| Проверка лимитов процесса | Контроль применения `LimitNOFILE` | `cat /proc/$(pgrep -f -o "httpd\|apache2")/limits \| grep "open files"`<br>`# → Max open files 65535 65535 files` |
| Аудит отказов SELinux | Поиск свежих блокировок операций Apache | `sudo ausearch -m avc -ts recent \| grep httpd`<br>`# → <no matches> (при отсутствии блокировок)` |
| Проверка шифров TLS | Тест поддерживаемого протокола и шифра | `openssl s_client -connect 127.0.0.1:443 -tls1_3`<br>`# → Protocol  : TLSv1.3`<br>`# → Cipher    : TLS_AES_256_GCM_SHA384` |
| Тест маскировки версии | Проверка заголовка Server | `curl -I -s http://localhost/ \| grep -i "Server:"`<br>`# → Server: Apache` |

### Экстренный Runbook при L7 DoS / атаке на истощение соединений

В случае резкого роста latency, недоступности воркеров или лавинообразного роста 503/504 кодов:

```bash
# Шаг 1: Анализ распределения соединений по удаленным IP-адресам
ss -tan state established '( dport = :80 or dport = :443 )' | awk '{print $4}' | cut -d: -f1 | sort | uniq -c | sort -nr | head -20
# →  1420 198.51.100.77
# →   850 198.51.100.89
# →     5 10.10.10.25

# Шаг 2: Мгновенный сброс соединений и блокировка атакующего IP через nftables
sudo nft add element inet filter blackhole { 198.51.100.77 }
# Или через firewalld на RHEL:
sudo firewall-cmd --add-rich-rule='rule family="ipv4" source address="198.51.100.77" drop' --timeout=3600

# Шаг 3: Проверка состояния пула воркеров через mod_status
curl -s http://127.0.0.1/server-status?auto | grep -E "BusyWorkers|IdleWorkers|ConnsTotal"
# → BusyWorkers: 15
# → IdleWorkers: 85
# → ConnsTotal: 25

# Шаг 4: Принудительный мягкий перезапуск без разрыва существующих сессий
sudo apachectl graceful
```

---

## Диагностика и устранение неисправностей

### 1. Ошибка HTTP 403 Forbidden

**Типовые причины:**
- Отсутствие разрешающего правила для конкретного каталога при активном `<Directory /> Require all denied`.
- Включен `Options -Indexes`, а индексный файл (`index.html`, `index.php`) в каталоге отсутствует.
- Права доступа на файловой системе запрещают чтение пользователю `apache` / `www-data`.
- Блокировка подсистемы SELinux (неверный контекст файла).
- Срабатывание директивы `<LimitExcept>`.

**Алгоритм диагностики:**

```bash
# 1. Поиск точной причины в error_log
sudo tail -n 20 /var/log/httpd/error_log | grep -i "authz_core:error\|client denied by server configuration"
# → [authz_core:error] [pid 1234:tid 5678] [client 192.0.2.1:54321] AH01630: client denied by server configuration: /var/www/html/secret.txt

# 2. Проверка прав DAC на путь к файлу
namei -l /var/www/html/secret.txt
# → f: /var/www/html/secret.txt
# → drwxr-xr-x root root /
# → drwxr-xr-x root root var
# → drwxr-xr-x root root www
# → drwxr-x--- root www-data html
# → -rw-r----- root www-data secret.txt

# 3. Проверка отказов SELinux
sudo ausearch -m avc -ts recent | grep httpd
# → type=AVC msg=audit(1690000000.123:456): avc:  denied  { read } for  pid=1234 comm="httpd" name="secret.txt" dev="sda1" ino=98765 scontext=system_u:system_r:httpd_t:s0 tcontext=unconfined_u:object_r:user_home_t:s0 tclass=file permissive=0

# Исправление контекста SELinux:
sudo restorecon -v /var/www/html/secret.txt
# → Relabeled /var/www/html/secret.txt from unconfined_u:object_r:user_home_t:s0 to unconfined_u:object_r:httpd_sys_content_t:s0
```

### 2. Ошибка HTTP 500 Internal Server Error

**Типовые причины:**
- Недопустимая директива в локальном `.htaccess` при запрещающей директиве `AllowOverride None`.
- Сбой выполнения скрипта FastCGI/PHP-FPM или недоступность его сокета.
- Блокировка создания процессов через systemd `NoNewPrivileges` или нехватка памяти cgroup.

**Алгоритм диагностики:**

```bash
# Проверка error_log на ошибки парсинга .htaccess
sudo tail -n 20 /var/log/httpd/error_log | grep -i "alert"
# → [core:alert] [pid 1234:tid 5678] [client 192.0.2.1:54322] /var/www/html/.htaccess: Option Indexes not allowed here

# Решение: Удалить неразрешенные директивы из .htaccess или отключить чтение .htaccess (AllowOverride None)
```

### 3. Ошибка HTTP 413 Payload Too Large

**Симптом:** Пользователи или API-клиенты не могут загрузить файлы, запрос прерывается веб-сервером.
**Причина:** Размер тела запроса превышает значение директивы `LimitRequestBody`.
**Диагностика:** В журнале ошибок фиксируется сообщение: `Request body exceeds LimitRequestBody grant`.
**Решение:** Увеличить значение `LimitRequestBody` для конкретного URL в контейнере `<Location>` или `<Directory>`.

### 4. Ошибка запуска systemd: `setuid: Operation not permitted`

**Симптом:** Служба не стартует после настройки systemd drop-in override, статус `failed` с кодом ошибки exit-code.
**Причина:** В параметре `CapabilityBoundingSet` не указаны `CAP_SETUID` и `CAP_SETGID`. Главный процесс `root` не может переключиться на пользователя `apache` / `www-data`.
**Диагностика:**
```bash
journalctl -u httpd.service -n 25 --no-pager | grep -i "setuid"
# → AH00057: setuid: unable to change to uid: 48
```
**Решение:** Добавить `CAP_SETUID CAP_SETGID` в `CapabilityBoundingSet` файла `/etc/systemd/system/httpd.service.d/hardening.conf`, выполнить `systemctl daemon-reload` и перезапустить службу.

### 5. Ошибка запуска: `Address already in use: AH00072`

**Симптом:** Apache не может привязаться к порту 80 или 443.
**Причина:** Порт занят другим веб-сервером (Nginx, HAProxy), зависшим старым процессом `httpd` или сокет находится в затянувшемся состоянии `TIME_WAIT`.

```bash
# Определение процесса, удерживающего порт
sudo ss -tlpn sport = :80 or sport = :443
# → LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=789,fd=6))

# Остановка конфликтующего сервиса
sudo systemctl stop nginx
sudo systemctl restart httpd
```

### 6. Сбои SSL/TLS: Handshake Failure / Невозможно прочитать ключ

**Симптом:** Браузер возвращает ошибку `SSL_ERROR_NO_CYPHER_OVERLAP` или сервис не стартует с сообщением `Cannot load private key`.
**Причина:** Права на `server.key` запрещают чтение процессу Apache при старте (если сброшен root), либо клиент пытается подключиться по запрещенному протоколу TLS 1.0/1.1.

```bash
# Проверка прав на приватный ключ
sudo ls -l /etc/pki/tls/private/server.key
# → -rw-r----- 1 root apache 1704 Jan 15 10:00 /etc/pki/tls/private/server.key

# Проверка синтаксиса SSL-модуля
apachectl configtest
```

---

## Лучшие практики

1. **Никакого прямого редактирования на продакшене без валидации**
   Любое изменение конфигурации должно сопровождаться проверкой синтаксиса `apachectl configtest` перед отправкой сигнала `apachectl graceful`. Применение изменений через IaC (Ansible/Git) исключает ошибки ручного ввода.

2. **Запрет `.htaccess` в production (`AllowOverride None`)**
   Отключение `.htaccess` глобально в `<Directory />` не только закрывает критический вектор атак (переопределение настроек безопасности через загруженные файлы), но и дает прирост производительности на 15–25%, избавляя Apache от поиска `.htaccess` во всех вложенных каталогах.

3. **Использование `SymLinksIfOwnerMatch` вместо `FollowSymLinks`**
   Никогда не используйте `Options FollowSymLinks` в каталогах, куда возможна загрузка файлов пользователями. `SymLinksIfOwnerMatch` разрешает переход по ссылке только в том случае, если владелец ссылки совпадает с владельцем целевого файла.

4. **Строгая изоляция служебных страниц**
   Эндпоинты `/server-status` и `/server-info` должны быть либо полностью отключены, либо привязаны строго к интерфейсу `127.0.0.1` с обязательной HTTP Basic/Digest аутентификацией.

5. **Обязательная связка TLS 1.3 + TLS 1.2 с HSTS Preload**
   Запрещайте все версии протокола ниже TLS 1.2. Включайте заголовок HSTS с директивой `preload` и отправляйте домен в [список HSTS Preload](https://hstspreload.org).

6. **Минимизация привилегий службы через systemd drop-in**
   Используйте `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true` и `NoNewPrivileges=true`. Ограничивайте права записи процесса строго директориями `/var/log` и каталогами загрузок через `ReadWritePaths`.

7. **Не запускайте воркеры от имени `root`**
   Процессы воркеров всегда должны функционировать от непривилегированного пользователя (`apache` или `www-data`). Запрещайте процессу веб-сервера интерактивный шелл (`/sbin/nologin` или `/usr/sbin/nologin` в `/etc/passwd`).

8. **Защита от Slow DoS через `mod_reqtimeout`**
   Включайте модуль `mod_reqtimeout` на всех публичных инсталляциях. Устанавливайте агрессивные таймауты ожидания первого байта и минимальную скорость передачи для защиты пула соединений.

9. **Централизация и иммутабельность журналов**
   Логи доступа и ошибок должны направляться в централизованную систему агрегации (syslog/vector/ELK). На локальном хосте права на каталоги логов должны предотвращать удаление или модификацию записей веб-пользователем.

10. **Регулярный аудит и сканирование уязвимостей**
    Проверяйте актуальность версий пакетов `httpd`/`apache2` и `openssl`. Используйте локальные сканеры уязвимостей для контроля открытых заголовков и конфигурации TLS.

---

## Дополнительная информация

### Матрица Single Source of Truth (SSoT)

| Тематика | SSoT-документ | Зона ответственности |
|---|---|---|
| Архитектура Apache и базовые директивы | [Обзор Apache](./apache_overview.md) | Архитектура MPM, базовые VirtualHost, компиляция |
| Межсетевой экран приложений WAF | [Обзор WAF](../../Security/ApplicationSecurity/waf.md) | Архитектура WAF, правила ModSecurity, CRS OWASP |
| Аутентификация и авторизация | [Аутентификация в Apache](./apache_authentication.md) | Модули LDAP/AD, Basic/Digest auth, mTLS сертификаты |
| Настройка производительности | [Производительность Apache](./apache_performance_tuning.md) | Тюнинг воркеров MPM event, буферы, кэширование |
| Защита обратного и прямого прокси | [Прямое проксирование Apache](./apache-forward-proxy.md) | Защита от Open Proxy, директива ProxyRequests, CONNECT |
| Мандатный контроль SELinux | [SELinux](../../Linux/Security/Mechanisms/SELinux.md) | Архитектура LSM, домены, генерация политик audit2allow |
| Мандатный контроль AppArmor | [AppArmor](../../Linux/Security/Mechanisms/AppArmor.md) | Профили безопасности для Debian/Ubuntu |
| Автоматизация блокировок | [Fail2Ban](../../Linux/Security/Tools/fail2ban.md) | Фильтры регулярных выражений, интеграция с nftables |
| Управление Linux Capabilities | [Capabilities](../../Linux/Security/Mechanisms/Capabilities.md) | Ограничение привилегий ядра для процессов |
| Системная изоляция systemd | [Безопасность systemd](../../Linux/Security/Concepts/systemd_security.md) | Sandboxing директивы, изоляция файловой системы |
| Сравнение с альтернативами | [Харденинг Nginx](../Nginx/Security/nginx_security_guide.md) | Сравнение практик безопасности с Nginx |

### См. также

*   **[Обработчики и MIME в Apache](./apache-handlers-and-mime.md)** — безопасное сопоставление типов файлов, изоляция CGI и SSI.
*   **[SSO через OIDC (mod_auth_openidc)](./apache-oidc-sso.md)** — федеративная аутентификация в корпоративной среде.
*   **[Кэширование в Apache](./apache_caching.md)** — настройка серверного кэша и htcacheclean.
*   **[WebDAV в Linux](../../Linux/Networking/Services/webdav/webdav_overview.md)** — безопасная настройка и разграничение прав доступа к WebDAV.
*   **[Защита от Brute-force](../../Security/Concepts/brute_force_attacks.md)** — концепции предотвращения атак перебором.
