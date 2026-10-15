# Apache: Обратное проксирование — продвинутые сценарии

**Актуально для:** Apache HTTP Server 2.4.x (тестировалось на 2.4.58 – 2.4.63, Debian 12 / Ubuntu 24.04 / RHEL 9)

---

## Определения

**Reverse Proxy (обратный прокси-сервер)** — топологический шлюз прикладного уровня (Layer 7), принимающий внешние клиентские запросы и транслирующий их на один или несколько внутренних целевых сервисов (бэкендов). Для внешнего клиента обратный прокси выступает конечной точкой обслуживания (терминация TLS, инспекция трафика, фильтрация заголовков, кэширование).

**`mod_proxy`** — базовый модульный фреймворк Apache HTTP Server, реализующий общее управление пулами соединений (connection pools), абстракцию воркеров, балансировку и синтаксический анализ директив `ProxyPass` / `ProxyPassReverse`. Не обрабатывает прикладные протоколы самостоятельно, делегируя передачу данных специализированным субмодулям.

**Модули протоколов `mod_proxy_*`**:
- `mod_proxy_http` — реализация протоколов HTTP/1.0 и HTTP/1.1 для проксирования к веб-приложениям. Начиная с Apache 2.4.47, поддерживает туннелирование WebSocket через параметр `upgrade=websocket`.
- `mod_proxy_http2` — реализация клиентской части протокола HTTP/2 для взаимодействия с бэкендами по защищенному (`h2://`) или открытому (`h2c://`) каналу, а также для обслуживания gRPC-трафика.
- `mod_proxy_wstunnel` — специализированный модуль для двунаправленного туннелирования протокола WebSocket (`ws://` и `wss://`).
- `mod_proxy_fcgi` — адаптер протокола FastCGI (взаимодействие с PHP-FPM).
- `mod_proxy_uwsgi` — адаптер протокола uWSGI для стеков Python/Ruby.

**`ProxyPass`** — ключевая директива конфигурации, сопоставляющая путь в URL входящего клиентского запроса с сетевым адресом (URL или Unix Domain Socket) целевого бэкенда.

**`ProxyPass ... !`** — нотация безусловного исключения («not proxied»). Отменяет проксирование для конкретного префикса пути, передавая обработку запроса локальным модулям Apache (например, `mod_alias`, статическим файлам из `DocumentRoot` или статусным страницам).

**`ProxyPassMatch`** — директива проксирования с поддержкой регулярных выражений (POSIX Regex / PCRE). Применяется к URI запроса для сложного динамического роутинга и маппинга параметров через группы захвата (`$1`, `$2`).

**`ProxyPassReverse`** — директива перезаписи заголовков ответа бэкенда (`Location`, `Content-Location`, `URI`). Заменяет внутренние адреса бэкенда (например, `http://10.0.0.5:8080/`) на внешний публичный URL прокси-сервера (`https://app.example.com/`), предотвращая раскрытие внутренней топологии сети и некорректные редиректы клиента.

**`ProxyPassReverseCookieDomain` / `ProxyPassReverseCookiePath`** — директивы перезаписи атрибутов `Domain` и `Path` в заголовках ответа `Set-Cookie`. Обеспечивают корректную установку сессионных cookie в браузере клиента при несовпадении внутренних и внешних доменных имен или префиксов путей.

**`ProxyPreserveHost`** — директива, определяющая значение заголовка `Host`, передаваемого бэкенду. При значении `On` Apache передает исходный заголовок `Host`, полученный от клиента. При значении `Off` (по умолчанию) в заголовок `Host` подставляется имя хоста из URL директивы `ProxyPass`.

**`ProxyErrorOverride`** — переключатель перехвата ошибок бэкенда. При значении `On` Apache подавляет страницы ошибок с HTTP-кодами 4xx и 5xx, возвращенные бэкендом, и генерирует собственные страницы в соответствии с директивами `ErrorDocument`.

**Connection Pool Worker** — управляемый пул постоянных TCP-соединений (Keep-Alive) к конкретному бэкенду, разделяемый между рабочими потоками Apache MPM (Worker/Event). Настраивается параметрами директивы `ProxyPass` (`min`, `smax`, `max`, `acquire`, `ttl`, `retry`, `timeout`).

**Unix Domain Socket (UDS)** — механизм межпроцессного взаимодействия (IPC) в Unix-подобных ОС. В контексте `mod_proxy` позволяет проксировать трафик в локальный файл-сокет (`unix:/run/app.sock|http://localhost/`), исключая накладные расходы сетевого стека TCP/IP и устраняя риск исчерпания эфемерных портов.

---

## Архитектура и принцип работы

### Жизненный цикл проксируемого запроса

Обработка запроса обратным прокси-сервером Apache проходит через цепочку внутренних хуков (Request Processing Pipeline):

```
[ Входящий клиентский запрос ]
        │
        ▼ (Хук ap_hook_post_read_request)
[ SSL/TLS Терминация + Инспекция входящих заголовков ]
        │
        ▼ (Хук ap_hook_translate_name)
[ Сопоставление маршрутов (URI Mapping) ]
   ├── Проверка исключений "ProxyPass /path/ !" ──► [ Локальный Handler: static / DocumentRoot ]
   ├── Проверка ProxyPassMatch (regex)
   └── Проверка ProxyPass (порядок в конфигурации)
        │
        ▼ (Выбран бэкенд / воркер)
[ Выделение соединения из Connection Pool ]
   ├── UDS сокет: прямое подключение к файловой системе (/run/app.sock)
   └── TCP сокет:
         ├── Поиск свободного соединения в пуле (smax/max)
         ├── Проверка DNS-имени (если не закэшировано)
         ├── Handshake: TCP Handshake + TLS Handshake (если SSLProxyEngine On)
         └── CPing / CPong (если включен параметр ping=...)
        │
        ▼ (Генерация запроса к бэкенду)
[ Модификация заголовков (Header Manipulation) ]
   ├── Добавление X-Forwarded-For, X-Forwarded-Host, X-Forwarded-Proto (ProxyAddHeaders)
   ├── Формирование RFC 7239 "Forwarded" (если сконфигурировано)
   ├── Установка или передача Host (ProxyPreserveHost)
   └── Удаление внутренних / недоверенных заголовков (RequestHeader unset)
        │
        ▼ (Трансляция полезной нагрузки)
[ Отправка тела запроса и ожидание ответа ] ──► [ Целевой бэкенд (Go, Python, Java, Node.js) ]
        │
        ▼ (Обработка ответа бэкенда)
[ Фильтрация и перехват ответа ]
   ├── Проверка HTTP-статуса: если 4xx/5xx и ProxyErrorOverride On ──► [ Локальный ErrorDocument ]
   ├── Перезапись заголовков Location, Content-Location (ProxyPassReverse)
   ├── Перезапись cookie: Domain, Path (ProxyPassReverseCookie*)
   └── Буферизация / Потоковая передача тела (flushpackets / ProxyReceiveBufferSize)
        │
        ▼
[ Отправка ответа клиенту + Возврат сокета в Connection Pool ]
```

### Порядок и специфичность правил маршрутизации

Директивы `ProxyPass` обрабатываются в порядке их объявления в файле конфигурации сверху вниз до первого совпадения префикса пути.

1. **Правило исключения `!`:** Должно объявляться выше любых обобщающих правил.
2. **Специфичность путей:** Более длинные и вложенные пути обязаны располагаться раньше коротких корневых путей. Корневой маршрут `ProxyPass /` объявляется последним.
3. **Опасность слеша на конце (Trailing Slash Semantics):**
   - Если в `ProxyPass` путь на фронтенде заканчивается слешем, путь к бэкенду **обязан** заканчиваться слешем:
     ```apacheconf
     # Корректно:
     ProxyPass /api/ http://backend.internal:8080/api/
     ProxyPassReverse /api/ http://backend.internal:8080/api/
     ```
   - Если слеш опущен на одном из концов (`ProxyPass /api http://backend.internal:8080/`), запрос к `/apigateway` будет ошибочно переслан на бэкенд как `http://backend.internal:8080/gateway`.
   - Если фронтенд настроен как `ProxyPass /app/ http://backend:8080/`, а клиент запрашивает `/app`, Apache не перехватит запрос этим правилом, что приведет либо к 404, либо к передаче запроса в `DocumentRoot`.

### Архитектура пула соединений (Connection Pooling)

По умолчанию для каждого определения `ProxyPass` создается пул постоянных соединений, привязанный к рабочим процессам Apache MPM. Если параметры пула не заданы, воркеры создают соединения динамически без ограничений, что под нагрузкой приводит к лавинообразному росту сокетов в состоянии `TIME_WAIT` и ошибкам `AH01114: HTTP: failed to make connection`.

| Параметр воркера | Назначение | Значение по умолчанию | Рекомендация для Production |
|---|---|---|---|
| `min` | Минимальное число постоянно удерживаемых открытых TCP-соединений в пуле | `0` | `5`–`10` для прогрева пула |
| `smax` | «Мягкий» лимит соединений. Соединения сверх этого числа закрываются при простое | Равно числу потоков процесса (`ThreadsPerChild`) | Равно средней нагрузке (например, `25`–`50`) |
| `max` | Жесткий потолок одновременных TCP-соединений воркера на процесс MPM | Равно числу потоков процесса | Расчет от емкости бэкенда (`max = Backend_Max_Conn / MPM_Processes`) |
| `ttl` | Время жизни (в секундах) неиспользуемых соединений сверх лимита `smax` | `0` (бессрочно) | `60`–`120` сек |
| `acquire` | Таймаут (в миллисекундах) ожидания освобождения соединения из пула при достижении `max` | `-1` (не ждать, ошибка сразу) | `1000`–`5000` мс (предотвращает отказ при всплесках) |
| `timeout` | Таймаут ожидания ответа от бэкенда (в секундах) | Значение глобального `ProxyTimeout` (по умолчанию `Timeout`, 60 сек) | Задается индивидуально (`5`–`30` сек) |
| `retry` | Время ожидания (в секундах) перед повторной попыткой обращения к бэкенду, перешедшему в статус Error | `60` сек | `5`–`10` сек (ускоряет самовосстановление) |
| `keepalive` | Включение механизма TCP Keepalive на уровне ядра ОС для обнаружения зависших полуоткрытых сокетов | `Off` | `On` |
| `ping` | Время ожидания ответа на предварительную проверку (CPing/CPong или 100-Continue) перед передачей тела | `0` (отключено) | `500ms`–`1s` (защита от отправки больших payload на мертвый узел) |
| `disablereuse` | Принудительное закрытие сокета после каждого запроса (отключение пулинга) | `Off` | `Off`. Включать (`On`) только при работе через промежуточные L4-балансировщики с коротким idle timeout |
| `flushpackets` | Режим сброса буфера сетевого пакета при потоковой передаче (`on`, `off`, `auto`) | `off` | `on` для SSE (Server-Sent Events) и потокового API |
| `flushwait` | Время задержки перед принудительным сбросом буфера потока (в миллисекундах) | `10` мс | `10` для SSE/микропакетов |

### Взаимодействие с бэкендами по TLS (SSLProxyEngine и mTLS)

В Apache HTTP Server клиентская часть TLS для проксирования изолирована от серверной части:
- Серверная директива `SSLEngine on` активирует прием HTTPS-трафика от клиентов.
- Для инициации HTTPS-соединений к бэкендам требуется отдельная директива: `SSLProxyEngine on`.
- **Проверка подлинности сертификата бэкенда:** По умолчанию в устаревших конфигурациях проверка отключена. В защищенном периметре обязательна валидация цепочки доверия и имени хоста (SNI):
  - `SSLProxyVerify require` — проверка подлинности сертификата бэкенда через CA.
  - `SSLProxyCheckPeerName on` — проверка совпадения доменного имени бэкенда с полем SAN (Subject Alternative Name) сертификата.
  - `SSLProxyCheckPeerExpire on` — блокировка просроченных сертификатов бэкендов.
- **Взаимная аутентификация (mTLS к бэкенду):** Если бэкенд требует аутентификации прокси по клиентскому сертификату, Apache передает объединенный файл сертификата и закрытого ключа через `SSLProxyMachineCertificateFile`.

### WebSockets и Server-Sent Events (SSE)

1. **WebSocket:** Двунаправленный полнодуплексный протокол. Клиент отправляет запрос HTTP/1.1 с заголовками `Upgrade: websocket` и `Connection: Upgrade`.
   - В Apache >= 2.4.47 модуль `mod_proxy_http` перехватывает этот запрос при указании параметра `upgrade=websocket` (или `upgrade=any`) без необходимости использования отдельного модуля `mod_proxy_wstunnel`.
   - Для длительных WebSocket-сессий критично настроить `ProxyTimeout` (или параметр воркера `timeout`), иначе неактивные сокеты будут принудительно разорваны по стандартному 60-секундному таймауту.
2. **Server-Sent Events (SSE):** Однонаправленный поток событий поверх стандартного HTTP/1.1 (`text/event-stream`).
   - Главная проблема SSE за обратным прокси — буферизация. Если Apache накапливает чанки в системном буфере (`ProxyReceiveBufferSize`), клиент не получает события в реальном времени.
   - Решение: включение немедленного сброса сетевых буферов параметрами воркера: `flushpackets=on flushwait=10`.

### HTTP/2 и gRPC через `mod_proxy_http2`

gRPC функционирует строго поверх HTTP/2, используя фреймы HEADERS, DATA и концевые заголовки (HTTP/2 Trailers) для передачи статуса вызова (`grpc-status`, `grpc-message`).
- Модуль `mod_proxy_http2` поддерживает две схемы подключения к бэкендам:
  - `h2://` — HTTP/2 поверх TLS (требует `SSLProxyEngine on`).
  - `h2c://` — HTTP/2 Cleartext (без шифрования, стандарт для локальных сервисов и приватных подсетей).
- При проксировании gRPC Apache мультиплексирует несколько параллельных RPC-стримов в единый TCP-коннект к бэкенду, снижая накладные расходы на handshake.

---

## Практические сценарии

### Сценарий 1: Высокопроизводительный Reverse Proxy с отдачей статики и UDS-сокетом к приложению

**Контекст:** На сервере под управлением Debian 12 / RHEL 9 развернуто приложение (Gunicorn / Node.js / Go), слушающее локальный Unix Domain Socket `/run/app/app.sock`. Статические файлы отдаются напрямую через Apache. Доступ к служебным адресам `/admin/internal-metrics` заблокирован с проксированием в 403.

```apacheconf
# /etc/apache2/sites-available/app-production.conf (Debian/Ubuntu)
# или /etc/httpd/conf.d/app-production.conf (RHEL)

<VirtualHost *:80>
    ServerName app.example.com
    ServerAdmin admin@example.com

    # Логирование с детализацией задержки ответа (%D — микросекунды)
    LogFormat "%h %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\" %D us" combined_timing
    CustomLog /var/log/apache2/app_access.log combined_timing
    ErrorLog /var/log/apache2/app_error.log

    # 1. Отдача локальной статики без обращения к бэкенду
    Alias /static/ /var/www/app/static/
    <Directory "/var/www/app/static">
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
        
        # Кэширование статических ассетов
        <IfModule mod_expires.c>
            ExpiresActive On
            ExpiresDefault "access plus 30 days"
        </IfModule>
    </Directory>
    ProxyPass /static/ !

    # 2. Исключение и блокировка служебных путей
    <Location "/admin/internal-metrics">
        Require ip 10.0.10.0/24 127.0.0.1
    </Location>

    # 3. Базовые глобальные параметры проксирования
    ProxyPreserveHost On
    ProxyAddHeaders On

    # 4. Проксирование всего остального трафика в Unix Domain Socket
    # Синтаксис UDS: unix:/path/to/socket.sock|http://dummy-hostname/
    ProxyPass / unix:/run/app/app.sock|http://localhost/ min=5 smax=20 max=100 ttl=60 acquire=2000 timeout=30 keepalive=On
    ProxyPassReverse / unix:/run/app/app.sock|http://localhost/

    # Перезапись cookies при необходимости
    ProxyPassReverseCookieDomain localhost app.example.com
    ProxyPassReverseCookiePath / /
</VirtualHost>
```

Проверка конфигурации и прав на UDS-сокет:
```bash
# Проверка прав доступа веб-сервера к сокету (Apache должен иметь rw права)
ls -la /run/app/app.sock
# → srwxrwx--- 1 www-data www-data 0 Oct 14 19:35 /run/app/app.sock

# Валидация синтаксиса
apachectl configtest
# → Syntax OK

# Проверка ответа фронтенда
curl -sI http://app.example.com/static/css/main.css | grep -E "HTTP/|Content-Type"
# → HTTP/1.1 200 OK
# → Content-Type: text/css
```

---

### Сценарий 2: Защищенный шлюз с терминацией TLS и Upstream mTLS (Mutual TLS к бэкенду)

**Контекст:** Внешние клиенты подключаются по HTTPS к публичному Apache. Для соответствия требованиям безопасности внутренней сети трафик от Apache к внутреннему защищенному кластеру (`https://secure-api.internal:8443`) передается строго по TLS с обязательной двусторонней проверкой сертификатов (mTLS).

```apacheconf
<VirtualHost *:443>
    ServerName api.example.com

    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/api.example.com.crt
    SSLCertificateKeyFile /etc/ssl/private/api.example.com.key
    SSLCACertificateFile /etc/ssl/certs/public-client-ca.crt

    # 1. Активация клиентского TLS-движка mod_proxy
    SSLProxyEngine on

    # 2. Проверка сертификата внутреннего бэкенда (Server Authentication)
    SSLProxyVerify require
    SSLProxyVerifyDepth 2
    SSLProxyCACertificateFile /etc/ssl/internal-ca/internal-ca-chain.crt
    SSLProxyCheckPeerName on
    SSLProxyCheckPeerExpire on

    # 3. Аутентификация Apache перед бэкендом (Client Authentication / mTLS)
    # Файл должен содержать клиентский сертификат Apache и его приватный ключ
    SSLProxyMachineCertificateFile /etc/ssl/proxy-client/apache-backend-identity.pem

    # 4. Настройка воркера проксирования
    ProxyPreserveHost On
    ProxyPass / https://secure-api.internal:8443/ min=2 smax=10 max=50 ttl=120 acquire=3000 timeout=15 retry=5 ping=1s
    ProxyPassReverse / https://secure-api.internal:8443/

    # Санитизация заголовков аутентификации перед отправкой
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Client-Verify "%{SSL_CLIENT_VERIFY}s"
    RequestHeader set X-Client-DN "%{SSL_CLIENT_S_DN}s"
</VirtualHost>
```

Диагностика внутреннего mTLS-соединения:
```bash
# Проверка возможности подключения сертификатом Apache напрямую к бэкенду
openssl s_client -connect secure-api.internal:8443 \
    -cert /etc/ssl/proxy-client/apache-backend-identity.pem \
    -key /etc/ssl/proxy-client/apache-backend-identity.pem \
    -CAfile /etc/ssl/internal-ca/internal-ca-chain.crt -quiet
# → depth=2 C = US, O = Internal Root CA
# → depth=1 C = US, O = Internal Intermediate CA
# → depth=0 CN = secure-api.internal
# → verify return:1
```

---

### Сценарий 3: Шлюз реального времени (WebSockets + Server-Sent Events)

**Контекст:** Веб-сервер обслуживает интерактивную платформу. Пути `/ws/` требуют постоянного WebSocket-соединения, путь `/events/stream` отдает непрерывный поток данных SSE, а остальные запросы обрабатываются стандартным HTTP API.

```apacheconf
<VirtualHost *:443>
    ServerName realtime.example.com
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/realtime.crt
    SSLCertificateKeyFile /etc/ssl/private/realtime.key

    # Длительный таймаут для сессий реального времени
    ProxyTimeout 3600

    # 1. Проксирование WebSocket (нативно через mod_proxy_http в Apache 2.4.47+)
    # Используем upgrade=websocket для явного указания протокола
    ProxyPass /ws/ ws://127.0.0.1:8080/ws/ timeout=3600 retry=3
    ProxyPassReverse /ws/ ws://127.0.0.1:8080/ws/

    # 2. Проксирование Server-Sent Events (SSE)
    # flushpackets=on обеспечивает немедленную доставку чанков в браузер без буферизации
    ProxyPass /events/stream http://127.0.0.1:8080/events/stream flushpackets=on flushwait=10 timeout=1800
    ProxyPassReverse /events/stream http://127.0.0.1:8080/events/stream

    # 3. Стандартный REST API (короткий таймаут, пулинг)
    ProxyPass /api/ http://127.0.0.1:8080/api/ min=10 smax=30 max=100 ttl=60 acquire=1000 timeout=10
    ProxyPassReverse /api/ http://127.0.0.1:8080/api/
</VirtualHost>
```

Проверка установления WebSocket Upgrade через curl:
```bash
# Проверка ответа сервера на Upgrade-запрос
curl -i -N \
     -H "Connection: Upgrade" \
     -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" \
     -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
     https://realtime.example.com/ws/
# → HTTP/1.1 101 Switching Protocols
# → Upgrade: websocket
# → Connection: Upgrade
# → Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
```

---

### Сценарий 4: gRPC и HTTP/2 Reverse Proxy к внутренним микросервисам

**Контекст:** Apache принимает внешний защищенный трафик HTTP/2 (ALPN `h2`) и выполняет обратное проксирование вызовов gRPC на внутренний Go-микросервис, работающий по открытому HTTP/2 Cleartext (`h2c://127.0.0.1:50051`).

```apacheconf
# Требуются модули: proxy, proxy_http, proxy_http2, http2, ssl
LoadModule http2_module modules/mod_http2.so
LoadModule proxy_http2_module modules/mod_proxy_http2.so

<VirtualHost *:443>
    ServerName grpc.example.com
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/grpc.example.com.crt
    SSLCertificateKeyFile /etc/ssl/private/grpc.example.com.key

    # Включение протокола HTTP/2 на фронтенде
    Protocols h2 http/1.1

    # Запрет буферизации для потоковых RPC
    SetEnv proxy-nokeepalive 0

    # Проксирование gRPC сервиса (по префиксу пакета proto или пути)
    # Протокол h2c указывает на чистый HTTP/2 без TLS к локальному бэкенду
    ProxyPass /user.UserService/ h2c://127.0.0.1:50051/user.UserService/
    ProxyPassReverse /user.UserService/ h2c://127.0.0.1:50051/user.UserService/

    # Маршрутизация REST-шлюза на альтернативный порт
    ProxyPass /rest/ http://127.0.0.1:8080/
    ProxyPassReverse /rest/ http://127.0.0.1:8080/
</VirtualHost>
```

Проверка доступности gRPC через `grpcurl`:
```bash
# Вызов gRPC метода через внешний интерфейс Apache
grpcurl -cacert /etc/ssl/certs/ca.crt grpc.example.com:443 list
# → grpc.reflection.v1alpha.ServerReflection
# → user.UserService

# Вызов конкретного RPC метода
grpcurl -cacert /etc/ssl/certs/ca.crt -d '{"user_id": 1001}' grpc.example.com:443 user.UserService/GetUser
# → {
# →   "id": 1001,
# →   "name": "Alex DevOps",
# →   "email": "alex@example.com"
# → }
```

---

### Сценарий 5: Enterprise Security Gateway — Санитизация заголовков и RFC 7239

**Контекст:** Прокси-сервер развернут на периметре корпоративной инфраструктуры. Необходимо:
1. Защититься от спуфинга заголовков: удалить входящие от клиента служебные заголовки `X-Forwarded-*` и внутренние токены.
2. Сформировать стандартизированный заголовок RFC 7239 `Forwarded`.
3. Добавить сквозной идентификатор запроса (`X-Request-ID`) на базе `mod_unique_id`.
4. Удалить из ответа бэкенда сведения о технологическом стеке (`Server`, `X-Powered-By`).

```apacheconf
<VirtualHost *:443>
    ServerName portal.example.com
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/portal.crt
    SSLCertificateKeyFile /etc/ssl/private/portal.key

    # 1. Генерация уникального ID запроса
    # Требует LoadModule unique_id_module modules/mod_unique_id.so
    RequestHeader set X-Request-ID "%{UNIQUE_ID}e"

    # 2. Санитизация опасных заголовков клиента перед отправкой бэкенду
    RequestHeader unset X-Internal-Token
    RequestHeader unset X-Authenticated-User
    RequestHeader unset Forwarded

    # 3. Формирование RFC 7239 "Forwarded"
    # forward-for, proto, host
    RequestHeader set Forwarded "for=%{REMOTE_ADDR}s;proto=https;by=%{SERVER_ADDR}s;host=\"%{HTTP_HOST}e\""

    # 4. Стандартные X-Forwarded-*
    ProxyAddHeaders Off
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Host "%{HTTP_HOST}e"
    RequestHeader set X-Forwarded-Port "443"

    # 5. Проксирование
    ProxyPreserveHost On
    ProxyPass / http://10.10.20.10:8080/ min=5 smax=20 max=80 ttl=60 acquire=2000 timeout=20
    ProxyPassReverse / http://10.10.20.10:8080/

    # 6. Защита заголовков ответа (Information Disclosure Protection)
    Header always unset X-Powered-By
    Header always unset X-Runtime
    Header always unset X-Version
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
</VirtualHost>
```

Проверка заголовков ответа через curl:
```bash
# Проверка очистки заголовков в ответе сервера
curl -sI https://portal.example.com/api/status | grep -E "X-|Server"
# → Server: Apache
# → X-Frame-Options: SAMEORIGIN
# → X-Content-Type-Options: nosniff
# (Заголовки X-Powered-By и X-Runtime удалены из вывода)
```

---

### Сценарий 6: Динамическая маршрутизация с `ProxyPassMatch` и интерполяцией переменных

**Контекст:** Организация маршрутизации API-запросов версий v1 и v2 на разные микросервисы, отсечение статических медиа-файлов по расширению с динамической подстановкой IP бэкенда через переменные окружения ОС (`systemd`).

```apacheconf
# Разрешение интерполяции системных переменных в директивах mod_proxy
ProxyPassInterpolateEnv On

<VirtualHost *:80>
    ServerName routing.example.com

    # Переменная может быть задана в /etc/default/apache2 или через SetEnv
    # Например: SetEnv BACKEND_HOST "10.10.30.50"
    SetEnv BACKEND_IP "10.10.30.50"

    # 1. Маршрутизация медиа-контента напрямую в файловый сервис
    # Группа $1 передает имя файла
    ProxyPassMatch "^/media/(.*?\.(jpg|jpeg|png|gif|webp|svg))$" "http://${BACKEND_IP}:9001/images/$1" interpolate=On
    ProxyPassReverse "^/media/(.*?\.(jpg|jpeg|png|gif|webp|svg))$" "http://${BACKEND_IP}:9001/images/$1" interpolate=On

    # 2. Роутинг версионированного API: /api/v1/... -> port 8001, /api/v2/... -> port 8002
    ProxyPassMatch "^/api/v1/(.*)$" "http://${BACKEND_IP}:8001/$1" interpolate=On
    ProxyPassReverse "^/api/v1/(.*)$" "http://${BACKEND_IP}:8001/$1" interpolate=On

    ProxyPassMatch "^/api/v2/(.*)$" "http://${BACKEND_IP}:8002/$1" interpolate=On
    ProxyPassReverse "^/api/v2/(.*)$" "http://${BACKEND_IP}:8002/$1" interpolate=On

    # 3. Дефолтный маршрут
    ProxyPass / "http://${BACKEND_IP}:8080/" interpolate=On
    ProxyPassReverse / "http://${BACKEND_IP}:8080/" interpolate=On
</VirtualHost>
```

---

### Сценарий 7: Перехват ошибок бэкенда (`ProxyErrorOverride`) и отказоустойчивые заглушки

**Контекст:** Если внутренний бэкенд возвращает ошибки 500, 502 или 503, пользователи не должны видеть сырые стек-трейсы Java/Python или технические страницы. Apache перехватывает коды ошибок бэкенда и отдает брендированные статические страницы обслуживания.

```apacheconf
<VirtualHost *:80>
    ServerName service.example.com

    # Включение перехвата статус-кодов ошибок бэкенда
    ProxyErrorOverride On

    # Определение локальных страниц ошибок
    ErrorDocument 500 /errors/500.html
    ErrorDocument 502 /errors/502.html
    ErrorDocument 503 /errors/503.html
    ErrorDocument 504 /errors/504.html

    # Исключение каталога ошибок из проксирования!
    Alias /errors/ /var/www/html/errors/
    <Directory "/var/www/html/errors">
        Require all granted
    </Directory>
    ProxyPass /errors/ !

    # Проксирование приложения
    ProxyPass / http://10.10.40.15:8080/ min=5 smax=20 max=50 timeout=10 retry=5
    ProxyPassReverse / http://10.10.40.15:8080/
</VirtualHost>
```

Тестирование перехвата ошибки (эмуляция отказа бэкенда):
```bash
# При отключенном бэкенде Apache выдает локальную страницу 503
curl -s -o /dev/null -w "%{http_code}\n" http://service.example.com/api/test
# → 503

# Проверка содержимого ответа
curl -s http://service.example.com/api/test | grep "<title>"
# → <title>503 Service Unavailable — Maintenance in Progress</title>
```

---

## Операции и команды

| Команда / Проверка | Описание действия | Ожидаемый результат |
|---|---|---|
| `apachectl -M \| grep -E "proxy|ssl|http2"` | Проверка загруженных модулей обратного проксирования в ядро | `proxy_module (shared)`<br>`proxy_http_module (shared)`<br>`proxy_http2_module (shared)` |
| `apachectl configtest` | Валидация синтаксической корректности всех конфигурационных файлов | `Syntax OK` |
| `apachectl -S` или `httpd -S` | Дамп виртуальных хостов, проверка привязки IP:порт и перекрытий имен | `VirtualHost configuration:`<br>`*:443 app.example.com (/etc/apache2/sites-enabled/app.conf:1)` |
| `ss -tnp '( sport = :80 or sport = :443 )'` | Просмотр активных клиентских соединений к фронтенду Apache | Список сокетов с дескрипторами процессов `httpd`/`apache2` |
| `ss -tnp '( dport = :8080 or dport = :8443 )'` | Анализ установленных соединений из пула Apache к целевым бэкендам | `ESTAB 0 0 10.0.0.2:48124 10.0.0.10:8080 users:(("apache2",pid=1420,fd=12))` |
| `ss -x src /run/app/app.sock` | Проверка соединений через Unix Domain Sockets | `u_str ESTAB 0 0 /run/app/app.sock 12345 * 12344` |
| `curl -sI -o /dev/null -w "%{http_code} %{time_total}s\n" http://127.0.0.1/` | Замер времени сквозного прохождения запроса через прокси | `200 0.014210s` |
| `curl -I -H "Host: app.example.com" http://127.0.0.1/static/img.png` | Проверка работы исключения `ProxyPass ... !` (отдача локального файла) | `HTTP/1.1 200 OK`<br>`Server: Apache` (без заголовков бэкенда) |
| `tail -f /var/log/apache2/error.log \| grep -E "proxy|AH0"` | Мониторинг системных ошибок `mod_proxy` в реальном времени | Лог ошибок соединения, сброса воркеров или DNS |

---

## Типичные ошибки и диагностика

| Симптом / AH-код | Первопричина | Метод диагностики | Практическое решение |
|---|---|---|---|
| `AH00898: DNS lookup failure for: backend.internal` | DNS-сервер не может разрешить имя хоста бэкенда при инициализации или запросе | `dig @127.0.0.53 backend.internal +short`<br>`getent hosts backend.internal` | 1. Добавить запись в `/etc/hosts` или проверить `resolv.conf`.<br>2. Использовать IP-адрес в `ProxyPass`, если DNS нестабилен. |
| `AH01114: HTTP: failed to make connection to backend: 10.0.0.10:8080` | Целевой порт закрыт, сервис бэкенда остановлен или заблокирован локальным сетевым экраном (UFW/firewalld) | `nc -zv 10.0.0.10 8080`<br>`curl -I http://10.0.0.10:8080/` | 1. Запустить процесс бэкенда (`systemctl status app`).<br>2. Проверить `iptables -L -n -v` или сетевую связность между хостами. |
| `AH00959: ap_proxy_connect_backend disabling worker for (backend.internal)` | Воркер бэкенда переведен в состояние «Error» после нескольких неудачных попыток коннекта | Анализ `error.log` на предшествующие таймауты | 1. Уменьшить параметр `retry` (например, `retry=5`), чтобы Apache быстрее проверял восстановление узла.<br>2. Устранить первопричину сбоев на бэкенде. |
| `AH01075: Error dispatching request to the process (proxy: UDS socket)` | Ошибка отправки запроса в сокет `unix:/run/app.sock`: сокет не существует либо у процесса Apache (`www-data`/`apache`) нет прав `w` на файл сокета | `ls -l /run/app.sock`<br>`namei -l /run/app.sock` | 1. Проверить права каталога и сокета: `chown www-data:www-data /run/app.sock`.<br>2. Если включен SELinux — проверить `audit2allow` или выставить контекст `httpd_var_run_t`. |
| `AH02808: SSL Proxy: Peer certificate CN mismatch` (или SAN mismatch) | Сертификат бэкенда не содержит доменное имя, указанное в `ProxyPass https://...` | `openssl s_client -connect backend:8443 </dev/null \| openssl x509 -noout -text \| grep -A1 "Subject Alternative Name"` | 1. Перевыпустить сертификат бэкенда с верным SAN.<br>2. Временно отключить проверку имени: `SSLProxyCheckPeerName off` (только для тестовых сред). |
| `502 Bad Gateway` при тяжелых POST-запросах (`AH01097: pass request body failed`) | Бэкенд преждевременно разорвал TCP-соединение во время передачи тела запроса (превышение размера body или лимита памяти бэкенда) | Логи бэкенда: `Client disconnected / Request entity too large` | 1. Увеличить `LimitRequestBody` в Apache и лимиты бэкенда (например, `client_max_body_size` или `max_content_length`).<br>2. Проверить параметры воркера: `ping=1s`. |
| `504 Gateway Timeout` | Время выполнения операции на бэкенде превысило таймаут проксирования | Замер времени: `curl -w "%{time_total}\n"` возвращает ровно 60 сек | Увеличить таймаут для воркера: `ProxyPass / ... timeout=120` или глобальный `ProxyTimeout 120`. |
| Циклический редирект на внутренний адрес (`http://backend:8080/path`) | Отсутствует или некорректно настроена директива `ProxyPassReverse` | `curl -sI https://example.com/login` возвращает заголовок `Location: http://10.0.0.10:8080/...` | Добавить `ProxyPassReverse / http://10.0.0.10:8080/` с точным совпадением адреса. |
| Сессионные Cookie не сохраняются в браузере клиента | В заголовке `Set-Cookie` бэкенда указан внутренний домен (`Domain=backend.internal`) | Инспекция заголовков: `curl -i https://app.example.com \| grep -i set-cookie` | Сконфигурировать `ProxyPassReverseCookieDomain backend.internal app.example.com`. |
| WebSocket соединение обрывается ровно через 60 секунд | Отсутствует трафик в канале, срабатывает дефолтный `ProxyTimeout` | Анализ тайминга разрыва соединения клиентом | Увеличить `ProxyTimeout 3600` в виртуальном хосте и настроить периодический ping/pong (heartbeat) в приложении. |
| gRPC возвращает `HTTP 415 Unsupported Media Type` или `HTTP 501` | Запрос gRPC отправлен через обычный `mod_proxy_http` вместо `mod_proxy_http2` | Проверка протокола в логе (`HTTP/1.1` вместо `HTTP/2`) | Использовать схему `h2c://` или `h2://` с загруженным модулем `mod_proxy_http2` и включенным `Protocols h2 http/1.1`. |

---

## Лучшие практики (DevOps / SRE / Sysadmin)

1. **Строгое управление пулами воркеров:** Ни при каких обстоятельствах не оставляйте параметры `ProxyPass` со значениями по умолчанию в высоконагруженных окружениях. Всегда явно задавайте `min`, `smax`, `max`, `acquire` и `timeout`. Расчет жесткого максимума (`max`):
   $$\text{max per worker} = \frac{\text{Максимальное количество воркеров бэкенда}}{\text{Количество процессов Apache MPM}}$$
2. **Изоляция исключений через `ProxyPass ... !`:** Все статические ресурсы, robots.txt, favicon и страницы проверки работоспособности (liveness probe) должны обслуживаться Apache локально и исключаться из проксирования до общих правил.
3. **Безопасная обработка заголовков (Header Hardening):**
   - Всегда принудительно очищайте потенциально опасные входящие заголовки клиента (`RequestHeader unset X-Forwarded-For`), если перед Apache нет доверенного внешнего L4-балансировщика.
   - Используйте `ProxyPreserveHost On` только тогда, когда бэкенд явно использует виртуальный хостинг на базе имени или генерирует абсолютные URL для клиентов.
4. **Применение Unix Domain Sockets для локальных бэкендов:** Если сервер приложений (Python/Node/Go/Ruby) расположен на том же физическом хосте или внутри одного системного пространства, используйте сокеты `unix:/path/socket.sock|http://...`. Это снижает CPU overhead на 15–20% и полностью исключает риск исчерпания диапазона TCP-портов (`net.ipv4.ip_local_port_range`).
5. **Настройка TCP Keepalive на уровне сокетов:** Обязательно указывайте флаг `keepalive=On` в параметрах воркеров. Это активирует probes на уровне сетевого стека ядра Linux (`SO_KEEPALIVE`), своевременно выявляя мертвые соединения через межсетевые экраны со сброшенным состоянием conntrack.
6. **Защита от утечки внутренней топологии сети:**
   - Отключайте заголовок `Via`: директива `ProxyVia Off` предотвращает передачу внутренней версии Apache наружу.
   - Включайте `ProxyErrorOverride On` и собственные шаблоны `ErrorDocument`, чтобы скрыть информацию о фреймворках бэкенда и номерах строк при непредвиденных исключениях.
7. **Контроль SELinux в дистрибутивах RHEL / Rocky / AlmaLinux:** По умолчанию SELinux запрещает процессу httpd сетевые исходящие подключения. Разрешите их системной командой:
   ```bash
   setsebool -P httpd_can_network_connect 1
   ```

---

## Дополнительная информация

### См. также
* [Архитектура и базовые концепции Apache HTTP Server](./apache_overview.md) — фундаментальные основы, модульная структура, модель MPM Event.
* [Балансировка нагрузки в Apache (mod_proxy_balancer)](./apache_load_balancing.md) — алгоритмы балансировки, sticky sessions, failover и активные health-checks.
* [Прямое проксирование (Forward Proxy)](./apache-forward-proxy.md) — директивы `ProxyRequests`, метод `CONNECT` и защита от open proxy.
* [Тонкая настройка производительности Apache](./apache_performance_tuning.md) — тюнинг MPM, расчет лимитов соединений и дескрипторов файлов.
* [Харденинг и безопасность Apache](./apache_hardening.md) — минимизация привилегий, защита от атак, безопасная фильтрация запросов.
* [Модуль mod_rewrite и правила перенаправления](./apache_rewrite_and_redirects.md) — использование флага `[P]` (proxy throughput) и расширенные правила маршрутизации.
* [Порядок слияния конфигурации Apache](./apache-config-merge-order.md) — особенности наследования и переопределения контекстов `<Proxy>` и `<Location>`.