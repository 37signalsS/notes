# Apache: Прямое проксирование (Forward Proxy) и защита от open proxy

**Актуально для:** Apache HTTP Server 2.4.x

---

## Определения

**Forward Proxy (прямой прокси-сервер)** — промежуточный сетевой узел, функционирующий на стороне клиента (или во внутреннем сетевом периметре), который принимает исходящие HTTP/HTTPS-запросы от доверенных клиентов и пересылает их во внешние сети от своего имени. Клиенты настраиваются на использование прокси явно (через переменные окружения `http_proxy`/`https_proxy`, настройки операционной системы или браузера).

**Reverse Proxy (обратный прокси-сервер)** — прокси-сервер, размещаемый перед внутренними серверами приложений (бэкендами), принимающий входящие запросы из внешней сети и маршрутизирующий их к соответствующим сервисам (директивы `ProxyPass`, `ProxyPassReverse`). Подробные концептуальные различия описаны в [Концепции проксирования](../../Networking/Concepts/proxy.md).

**Open Proxy (открытый прокси)** — некорректно сконфигурированный прокси-сервер, принимающий и исполняющий запросы от любых внешних неаутентифицированных клиентов из сети Интернет. Критический дефект безопасности, приводящий к компрометации IP-репутации хоста, использованию сервера в качестве плацдарма для DDoS-атак, спам-рассылок и обхода сетевых ограничений.

**`ProxyRequests`** — директива ядра `mod_proxy`, переключающая режим работы Apache между прямым (`On`) и обратным (`Off`) проксированием. По умолчанию имеет значение `Off`.

**HTTP CONNECT** — метод протокола HTTP (RFC 9110, RFC 2817), предназначенный для установки сквозного двунаправленного TCP-туннеля через прокси-сервер (преимущественно для протокола TLS/HTTPS).

**`AllowCONNECT`** — директива модуля `mod_proxy_connect`, определяющая строгий список TCP-портов назначения, на которые прокси-серверу разрешено открывать туннели методом `CONNECT`.

**`ProxyBlock`** — директива `mod_proxy`, задающая список доменных имен, подстрок или IP-адресов, доступ к которым через прямой прокси безусловно запрещен (возвращается HTTP 403 Forbidden).

**`ProxyRemote`** — директива `mod_proxy` для организации каскадного (chained) проксирования, определяющая вышестоящий (upstream) прокси-сервер для заданных URL или протоколов.

**Hop-by-hop заголовки** — заголовки HTTP (RFC 9110), имеющие значение только для одного транспортного соединения между двумя узлами и подлежащие обязательному удалению прокси-сервером перед повторной отправкой запроса (`Connection`, `Keep-Alive`, `Proxy-Authenticate`, `Proxy-Authorization`, `TE`, `Trailers`, `Transfer-Encoding`, `Upgrade`).

**HTTP 407 Proxy Authentication Required** — код состояния HTTP, возвращаемый прямым прокси-сервером, требующим предъявления учетных данных через заголовок `Proxy-Authorization`.

---

## Архитектура и принцип работы

### Архитектурная модель прямого проксирования

В режиме прямого проксирования Apache HTTP Server выступает в роли шлюза прикладного уровня (Layer 7), разделяющего одно сквозное соединение на два независимых TCP-сокета:

```
[ Клиент (LAN) ] 
       │  TCP Handshake (Hop 1)
       │  GET http://target.example.org/index.html HTTP/1.1
       ▼
[ Apache Forward Proxy (mod_proxy + mod_proxy_http) ]
       │  1. Проверка прав доступа (<Proxy *>, Require ip, Auth)
       │  2. Проверка черных списков (ProxyBlock)
       │  3. Резолвинг DNS целевого хоста (getaddrinfo)
       │  4. Удаление hop-by-hop заголовков
       │  5. Добавление заголовка Via (если ProxyVia On)
       │  TCP Handshake (Hop 2)
       │  GET /index.html HTTP/1.1
       ▼
[ Целевой веб-сервер (target.example.org:80) ]
```

Ключевые отличия от обратного проксирования на уровне протокола:
- **Формат URI в строке запроса:** При прямом проксировании клиент отправляет абсолютный URI (`GET http://target.example.org/path HTTP/1.1`). При обратном проксировании клиент обращается к самому серверу и передает относительный путь (`GET /path HTTP/1.1`).
- **Модульная структура:** Ядро `mod_proxy` не реализует протоколы передачи данных самостоятельно. Оно предоставляет абстракцию и контекст `<Proxy>`. Для обработки HTTP-схем (`http://`) обязательно требуется модуль `mod_proxy_http`. Для туннелирования HTTPS/TLS методом `CONNECT` требуется модуль `mod_proxy_connect`.

### Сравнение режимов Forward и Reverse Proxy в Apache

| Параметр | Forward Proxy (`ProxyRequests On`) | Reverse Proxy (`ProxyPass`) |
|---|---|---|
| **Расположение** | Периметр локальной сети клиента / Egress-шлюз | Перед пулом серверов приложений (бэкендов) |
| **Управляющая директива** | `ProxyRequests On` внутри выделенного `<VirtualHost>` | `ProxyPass`, `ProxyPassReverse` |
| **Контейнер политик** | `<Proxy *>` или `<ProxyMatch>` | `<Location>`, `<Directory>`, `BalancerMember` |
| **Адресация запроса** | Абсолютный URL (`http://ext.example.com/file`) | Относительный путь (`/api/v1/users`) |
| **Инициатор настройки** | Клиент (настройки ОС, браузера, переменные окружения) | Администратор сервера / DNS входящего домена |
| **Поддержка CONNECT** | Да (`mod_proxy_connect` для сквозного TLS) | Нет (SSL терминируется на самом сервере или проксируется через SNI на L4) |
| **Кэширование ответов** | Кэширование внешнего контента для многих клиентов | Кэширование ответов локальных сервисов |

### Механизм туннелирования HTTPS (Метод CONNECT)

Поскольку трафик HTTPS зашифрован протоколом TLS, прямой прокси-сервер не может прочитать URI ресурса или заголовки запроса без перехвата сертификатов (TLS Interception). Стандартный механизм работы с HTTPS строится на создании «слепого» байтового туннеля (RFC 2817 / RFC 9110):

```
Клиент                    Apache Proxy (mod_proxy_connect)           Целевой узел:443
  │                                      │                                  │
  │── CONNECT target.example.org:443 ───>│                                  │
  │   Host: target.example.org:443       │                                  │
  │                                      │── TCP SYN target.example.org:443>│
  │                                      │<─ TCP SYN+ACK ───────────────────│
  │                                      │── TCP ACK ──────────────────────>│
  │<─ HTTP/1.1 200 Connection Established│                                  │
  │                                      │                                  │
  │══════════════════════ TLS Handshake (ClientHello) ═════════════════════>│
  │<═════════════════════ TLS Handshake (ServerHello + Cert) ═══════════════│
  │══════════════════════ Зашифрованные HTTP-запросы ══════════════════════>│
  │<═════════════════════ Зашифрованные HTTP-ответы ════════════════════════│
```

1. Клиент устанавливает обычное TCP-соединение с Apache на порт прокси (например, 3128) и отправляет запрос:
   ```http
   CONNECT target.example.org:443 HTTP/1.1
   Host: target.example.org:443
   ```
2. Apache проверяет директиву `AllowCONNECT`. Если порт запроса отсутствует в разрешенном списке, сервер возвращает статус `403 Forbidden` и закрывает сокет.
3. Apache выполняет проверку прав клиента (`Require ip`, `Require valid-user`).
4. Модуль `mod_proxy_connect` инициирует исходящий TCP-сокет к `target.example.org:443`.
5. После успешного открытия сокета Apache возвращает клиенту:
   ```http
   HTTP/1.1 200 Connection Established
   ```
6. С этого момента Apache прекращает парсинг HTTP и переходит в режим двунаправленной пересылки сырых байтов между клиентским и серверным сокетами до закрытия соединения одной из сторон.

> [!WARNING]
> Если директива `AllowCONNECT` не настроена строго (по умолчанию разрешены только 443 и 563), или если администратор разрешает все порты, злоумышленники могут использовать метод `CONNECT` для создания произвольных исходящих TCP-туннелей (например, к внешним SMTP-серверам для рассылки спама, SSH-серверам или внутренним серверам управления в обход межсетевых экранов).

### Механизм аутентификации на прямом прокси (HTTP 407)

В отличие от стандартной аутентификации на веб-сервере (код `401 Unauthorized`), взаимодействие с прокси регламентируется кодом `407 Proxy Authentication Required`:

```
Клиент                             Apache Proxy
  │                                      │
  │── GET http://example.org/ HTTP/1.1 ─>│
  │                                      │
  │<─ HTTP/1.1 407 Proxy Auth Required ──│
  │   Proxy-Authenticate: Basic realm=.. │
  │                                      │
  │── GET http://example.org/ HTTP/1.1 ─>│
  │   Proxy-Authorization: Basic dXNlcjp │
  │                                      │── Исходящий запрос к example.org ──>
```

Apache автоматически генерирует статус 407 и заголовок `Proxy-Authenticate`, если директивы авторизации (`AuthType Basic`, `Require valid-user`) размещены внутри секции `<Proxy *>` при активном `ProxyRequests On`.

---

## Практические сценарии и настройка

### Необходимые модули ядра

Перед настройкой прямого проксирования необходимо убедиться в наличии и загрузке модулей:
- `mod_proxy` — базовый диспетчер проксирования.
- `mod_proxy_http` — обработчик протокола HTTP для исходящих запросов.
- `mod_proxy_connect` — обработчик туннелирования CONNECT для HTTPS.
- `mod_auth_basic`, `mod_authn_file`, `mod_authz_user`, `mod_authz_core` — модули для реализации базовой аутентификации.

Активация в дистрибутивах Debian/Ubuntu:
```bash
sudo a2enmod proxy proxy_http proxy_connect auth_basic authn_file authz_user authz_core headers
sudo systemctl restart apache2
```

Активация в дистрибутивах RHEL/Rocky Linux:
```apacheconf
# /etc/httpd/conf.modules.d/00-proxy.conf
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_http_module modules/mod_proxy_http.so
LoadModule proxy_connect_module modules/mod_proxy_connect.so
```

---

### Сценарий 1: Изолированный Forward Proxy для доверенной локальной сети

Размещение прямого прокси в глобальном контексте конфигурации сервера или на стандартных портах 80/443 категорически не рекомендуется. Лучшая практика — выделение отдельного сетевого порта (традиционно 3128 или 8080) и привязка к внутреннему интерфейсу.

Конфигурационный файл `/etc/apache2/sites-available/forward-proxy.conf` (или `/etc/httpd/conf.d/forward-proxy.conf`):

```apacheconf
# Прослушивание только внутреннего интерфейса локальной сети
Listen 10.10.20.10:3128

<VirtualHost 10.10.20.10:3128>
    ServerName proxy.corp.local
    ServerAdmin admin@corp.local

    # Включение прямого проксирования строго внутри данного VirtualHost
    ProxyRequests On
    ProxyVia On
    ProxyTimeout 60

    # Строгое ограничение портов для метода CONNECT (только HTTPS)
    AllowCONNECT 443 563

    # Защита от уязвимости httpoxy (RFC 7230)
    <IfModule mod_headers.c>
        RequestHeader unset Proxy early
    </IfModule>

    # Безусловная блокировка доступа к внутренним петлевым адресам и локальным хостам
    ProxyBlock 127.0.0.1 localhost .corp.local

    # Авторизация клиентов по IP-адресам локальных подсетей
    <Proxy "*">
        Require ip 10.10.20.0/24
        Require ip 10.10.30.0/24
        Require ip 127.0.0.1
    </Proxy>

    # Настройки логирования с фиксацией времени обработки
    LogFormat "%h %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\" %D" proxy_combined
    CustomLog ${APACHE_LOG_DIR}/proxy_access.log proxy_combined
    ErrorLog ${APACHE_LOG_DIR}/proxy_error.log
    LogLevel warn
</VirtualHost>
```

---

### Сценарий 2: Forward Proxy с обязательной Basic-аутентификацией

Если прокси-сервер должен обслуживать мобильные рабочие станции или пользователей, находящихся в динамических подсетях, доступ ограничивается по паролю с генерацией хэшей через bcrypt (`htpasswd -B`).

1. Создание файла учетных записей:
```bash
sudo htpasswd -c -B /etc/apache2/.proxy_htpasswd proxyuser
# New password: ...
# Re-type new password: ...
sudo chmod 640 /etc/apache2/.proxy_htpasswd
sudo chown root:www-data /etc/apache2/.proxy_htpasswd
```

2. Конфигурация блока `<Proxy *>`:
```apacheconf
<VirtualHost 10.10.20.10:3128>
    ServerName proxy.corp.local
    ProxyRequests On
    AllowCONNECT 443

    <Proxy "*">
        AuthType Basic
        AuthName "Corporate Secure Proxy"
        AuthBasicProvider file
        AuthUserFile /etc/apache2/.proxy_htpasswd
        
        # Требовать успешную аутентификацию для любых обращений
        Require valid-user
    </Proxy>

    # Опционально: комбинирование белого списка IP и авторизации по паролю:
    # Клиенты из подсети 10.10.20.0/24 пропускаются без пароля, остальные — по паролю
    # <Proxy "*">
    #     AuthType Basic
    #     AuthName "Corporate Secure Proxy"
    #     AuthBasicProvider file
    #     AuthUserFile /etc/apache2/.proxy_htpasswd
    #     <RequireAny>
    #         Require ip 10.10.20.0/24
    #         Require valid-user
    #     </RequireAny>
    # </Proxy>
</VirtualHost>
```

---

### Сценарий 3: Защита инфраструктуры от SSRF и блокировка целевых ресурсов

При прямом проксировании существует риск того, что скомпрометированный клиент или вредоносный скрипт воспользуется прокси-сервером для отправки запросов к внутренним панелям управления, СУБД или оборудованию, недоступному клиенту напрямую.

Для превентивной блокировки применяются директива `ProxyBlock` и фильтрация через регулярные выражения в `<ProxyMatch>`:

```apacheconf
<VirtualHost 10.10.20.10:3128>
    ProxyRequests On

    # 1. Глобальная блокировка хостов, подсетей и доменных суффиксов
    # Любой запрос к хосту, содержащему подстроку, блокируется со статусом 403 Forbidden
    ProxyBlock 127.0.0.1 localhost 192.168.1.1 .secret.corp internal-switch.corp

    # 2. Тонкая блокировка протоколов и портов через регулярные выражения
    # Запрет любых обращений к схеме file://, gopher:// или ftp://
    <ProxyMatch "^(file|gopher|ftp)://">
        Require all denied
    </ProxyMatch>

    # 3. Запрет обращений к стандартным портам внутренних СУБД и очередей через прокси
    <ProxyMatch ":(3306|5432|6379|27017|9200|11211)/">
        Require all denied
    </ProxyMatch>

    <Proxy "*">
        Require ip 10.10.20.0/24
    </Proxy>
</VirtualHost>
```

---

### Сценарий 4: Каскадное проксирование (Chained Upstream Proxy)

В корпоративных инфраструктурах серверы DMZ часто не имеют прямого доступа в интернет и обязаны пересылать исходящий трафик через централизованный межсетевой шлюз безопасности.

Директива `ProxyRemote` связывает Apache с вышестоящим прокси-сервером:

```apacheconf
<VirtualHost 10.10.20.10:3128>
    ProxyRequests On
    AllowCONNECT 443

    # Перенаправлять все запросы (*) на центральный корпоративный прокси
    ProxyRemote * http://border-proxy.corp.internal:8080

    # Исключение: локальные ресурсы компании запрашивать напрямую без upstream
    ProxyRemoteMatch "^https?://.*\.corp\.internal" "!"

    <Proxy "*">
        Require ip 10.10.20.0/24
    </Proxy>
</VirtualHost>
```

---

### Сценарий 5: Кэширование исходящего веб-трафика на прямом прокси

Для экономии внешней полосы пропускания и ускорения повторной загрузки статических файлов (дистрибутивы, обновления ОС, документация) прямой прокси комбинируется с модулями `mod_cache` и `mod_cache_disk`.

```apacheconf
<VirtualHost 10.10.20.10:3128>
    ProxyRequests On
    AllowCONNECT 443

    <IfModule mod_cache.c>
        <IfModule mod_cache_disk.c>
            CacheRoot /var/cache/apache2/proxy
            CacheEnable disk http://
            CacheDirLevels 2
            CacheDirLength 1
            CacheDefaultExpire 3600
            CacheMaxExpire 86400
            
            # Не кэшировать ответы, если в URL присутствуют динамические параметры запроса
            CacheIgnoreCacheControl On
            CacheIgnoreNoLastMod On
            
            # Добавление отладочного заголовка статуса кэша (HIT/MISS)
            CacheHeader On
            CacheDetailHeader On
        </IfModule>
    </IfModule>

    <Proxy "*">
        Require ip 10.10.20.0/24
    </Proxy>
</VirtualHost>
```

Каталог кэша должен принадлежать пользователю веб-сервера:
```bash
sudo mkdir -p /var/cache/apache2/proxy
sudo chown -R www-data:www-data /var/cache/apache2/proxy
sudo chmod 700 /var/cache/apache2/proxy
```

---

## Операции и команды

### Валидация и диагностика на стороне сервера

Проверка корректности синтаксиса конфигурационных файлов:
```bash
apachectl configtest
# → Syntax OK
```

Проверка списка активных модулей, критически необходимых для forward proxy:
```bash
apachectl -M | grep -E 'proxy|auth'
# → proxy_module (shared)
# → proxy_http_module (shared)
# → proxy_connect_module (shared)
# → auth_basic_module (shared)
# → authz_core_module (shared)
```

Проверка прослушиваемого порта и сокетов:
```bash
ss -tulpn | grep :3128
# → tcp   LISTEN 0      511    10.10.20.10:3128      0.0.0.0:*    users:(("apache2",pid=14201,fd=4))
```

Мониторинг активных клиентских сессий и установленных туннелей в реальном времени:
```bash
ss -tnp '( sport = :3128 )'
# → ESTAB 0 0 10.10.20.10:3128 10.10.20.45:49152 users:(("apache2",pid=14205,fd=12))
```

---

### Тестирование прокси-сервера через curl

1. Тестирование обычного HTTP-запроса через прокси:
```bash
curl -v -x http://10.10.20.10:3128 http://example.org/ -I
# → * Connected to 10.10.20.10 (10.10.20.10) port 3128
# → > GET http://example.org/ HTTP/1.1
# → > Host: example.org
# → > User-Agent: curl/7.88.1
# → < HTTP/1.1 200 OK
# → < Via: 1.1 proxy.corp.local
# → < Content-Type: text/html; charset=UTF-8
```

2. Тестирование HTTPS-туннелирования методом CONNECT:
```bash
curl -v -p -x http://10.10.20.10:3128 https://example.org/ -I
# → * Connected to 10.10.20.10 (10.10.20.10) port 3128
# → * allocate connect buffer!
# → > CONNECT example.org:443 HTTP/1.1
# → > Host: example.org:443
# → < HTTP/1.1 200 Connection Established
# → * Proxy replied 200 to CONNECT request
# → * ALPN: server accepted h2
# → * Server certificate:
# → *  subject: CN=example.org
# → < HTTP/2 200
```

3. Тестирование аутентификации (проверка ответа 407 и флага `-U`):
```bash
# Попытка запроса без учетных данных:
curl -i -x http://10.10.20.10:3128 http://example.org/
# → HTTP/1.1 407 Proxy Authentication Required
# → Proxy-Authenticate: Basic realm="Corporate Secure Proxy"
# → Content-Length: 485

# Успешный запрос с передачей реквизитов через флаг -U (--proxy-user):
curl -i -x http://10.10.20.10:3128 -U proxyuser:SecretPass123 http://example.org/
# → HTTP/1.1 200 OK
# → Content-Type: text/html; charset=UTF-8
```

4. Проверка блокировки неразрешенного CONNECT-порта (например, попытка туннелирования к SSH на порт 22):
```bash
curl -v -p -x http://10.10.20.10:3128 https://target.example.org:22/
# → > CONNECT target.example.org:22 HTTP/1.1
# → < HTTP/1.1 403 Forbidden
# → < Content-Type: text/html; charset=iso-8859-1
# → * Received HTTP code 403 from proxy after CONNECT
```

5. Проверка блокировки хоста из `ProxyBlock`:
```bash
curl -i -x http://10.10.20.10:3128 http://127.0.0.1/
# → HTTP/1.1 403 Forbidden
# → Content-Type: text/html; charset=iso-8859-1
# → <title>403 Forbidden</title>
# → <p>Your cache administrator is admin@corp.local.</p>
```

---

### Аудит безопасности и сканирование на Open Proxy

Проверка уязвимости к открытому проксированию с помощью Nmap:
```bash
nmap -p 3128 --script http-open-proxy --script-args "proxy.url=http://example.org" 10.10.20.10
# → PORT     STATE SERVICE
# → 3128/tcp open  squid-http
# → |_http-open-proxy: Potentially OPEN proxy.
#   (Если сервер закрыт правилами доступа, скрипт выведет: "Proxy is closed" или не вернет уязвимость)
```

---

## Типичные ошибки и диагностика

| Симптом / Код ошибки | Вероятная причина | Диагностика и метод устранения |
|---|---|---|
| **HTTP 403 Forbidden** при любом запросе клиента | IP-адрес клиента отсутствует в блоке `Require ip`, либо запрос заблокирован директивой `ProxyBlock` / `<ProxyMatch>`. | Проверить `${APACHE_LOG_DIR}/proxy_error.log` на наличие записи: `client denied by server configuration: proxy:http://...`. Добавить подсеть клиента в секцию `<Proxy *>`. |
| **HTTP 407 Proxy Authentication Required** | Клиент не передал заголовок `Proxy-Authorization`, либо использован неверный пароль. | В утилите `curl` для аутентификации на прокси используется аргумент `-U` (`--proxy-user`), а не `-u` (который предназначен для целевого бэкенда). Проверить права на чтение файла `.proxy_htpasswd` процессом `www-data`/`apache`. |
| **HTTP 500 Internal Server Error** / `No protocol handler was valid for the URL` | Не загружен модуль `mod_proxy_http` для протокола HTTP, либо `mod_proxy_connect` для метода CONNECT. | Убедиться через `apachectl -M`, что загружены оба модуля. Выполнить `a2enmod proxy_http proxy_connect` и перезапустить сервис. |
| **HTTP 403 Forbidden** при попытке открыть HTTPS-ресурс | Порт назначения отсутствует в списке директивы `AllowCONNECT`. По умолчанию разрешен только 443 (и 563). | Если требуется туннелирование нестандартных защищенных сервисов (например, 8443), явно указать их: `AllowCONNECT 443 8443`. Не указывать небезопасные порты (21, 22, 25). |
| **HTTP 502 Bad Gateway** / `DNS lookup failure` | Apache не может разрешить доменное имя целевого узла через системный DNS-резолвер (`/etc/resolv.conf`). | Проверить резолвинг с хоста прокси: `getent hosts target.example.org`. Проверить доступность DNS-серверов и таймауты в `systemd-resolved` или `named`. |
| **HTTP 504 Gateway Timeout** | Время ожидания ответа от удаленного сервера превысило лимит директивы `ProxyTimeout` (или глобального `Timeout`). | Проверить сетевую связность между прокси и внешним миром (`traceroute`, `ping`). При необходимости увеличить `ProxyTimeout 120` внутри `<VirtualHost>`. |
| **Утечка заголовка `Proxy` (httpoxy)** | Клиент передает собственный заголовок `Proxy: ...`, который интерпретируется уязвимыми CGI/PHP скриптами как локальный прокси. | Добавить в конфигурацию сервера: `RequestHeader unset Proxy early` при помощи `mod_headers`. |
| **Исчерпание рабочих потоков MPM (`MaxRequestWorkers`)** | Клиенты удерживают открытые соединения CONNECT в туннеле бесконечно, либо внешние серверы медленно отвечают. | Настроить агрессивные таймауты в `mpm_event`: `KeepAliveTimeout 5`, `ProxyTimeout 60`. Контролировать лимиты через модуль `mod_status`. |

---

## Лучшие практики (DevOps / SRE / Sysadmin)

1. **Никогда не включать `ProxyRequests On` глобально:** Директива `ProxyRequests On` должна объявляться исключительно внутри изолированного контейнера `<VirtualHost>`, привязанного к закрытому интерфейсу и выделенному порту. В глобальном файле `apache2.conf` / `httpd.conf` значение всегда должно оставаться `ProxyRequests Off`.
2. **Сетевая изоляция и фаервол на уровне ядра:** Доступ к порту прокси (3128) должен фильтроваться средствами `iptables` / `nftables` до того, как пакет попадет в сокет веб-сервера. Запрещается слушать интерфейс `0.0.0.0`, если хост имеет публичный IP-адрес.
3. **Строгая фильтрация `AllowCONNECT`:** Метод `CONNECT` должен быть жестко ограничен портом `443`. Разрешение произвольных портов превращает сервер в релей для спама (порт 25) или неконтролируемого исходящего туннелирования.
4. **Защита от SSRF и сканирования интранета:** Обязательно используйте `ProxyBlock 127.0.0.1 localhost` и маски внутренних управляющих подсетей, чтобы предотвратить обращение внутренних клиентов к локальным сервисам хоста (сервисы метрик, локальные базы данных, IPMI).
5. **Управление дескрипторами и MPM Event:** В режиме forward proxy Apache удерживает поток на протяжении всего сеанса передачи данных (особенно в сессиях CONNECT). Для предотвращения дефицита воркеров используйте MPM Event (`mpm_event`), настройте адекватные лимиты `ThreadsPerChild` и `MaxRequestWorkers`, а также ограничьте время жизни сессий через `ProxyTimeout`.
6. **Санитизация служебных заголовков:** Всегда очищайте заголовок `Proxy` на входе (`RequestHeader unset Proxy early`) во избежание эксплуатации уязвимости класса httpoxy.
7. **Аудит и централизованное логирование:** Логируйте время ответа `%D` (в микросекундах), имя авторизованного пользователя `%u`, заголовок `Via` и точный HTTP-метод. В логах прокси-сервера фиксируются все внешние обращения клиентов, что критически важно для расследования инцидентов информационной безопасности.
8. **Архитектурные границы решения:** Apache HTTP Server отлично справляется с функциями forward proxy для небольших и средних офисов, межсерверных шлюзов и изолированных сред сборки CI/CD. Однако при нагрузках свыше десятков тысяч одновременных долгоживущих соединений или необходимости глубокого контентного анализа трафика (DPI, антивирусная фильтрация) целесообразно использовать специализированные прокси-серверы (Squid, Envoy).

---

## Дополнительная информация

### См. также в базе знаний

* [Концепции проксирования](../../Networking/Concepts/proxy.md) — сетевые модели L4/L7, прозрачное проксирование, классификация прямых и обратных прокси.
* [Харденинг Apache HTTP Server](./apache_hardening.md) — комплексное ужесточение безопасности, запрет уязвимости httpoxy, оптимизация прав доступа.
* [Обзор Apache HTTP Server](./apache_overview.md) — модульная архитектура, жизненный цикл запроса, управление MPM.
* [Кэширование в Apache](./apache_caching.md) — детальная настройка модулей `mod_cache` и `mod_cache_disk`.
* [Продвинутое обратное проксирование](./apache-reverse-proxy-advanced.md) — сопоставление `ProxyPassMatch`, перезапись заголовков и WebSocket.

### Нормативные документы и спецификации

* **RFC 9110 (HTTP Semantics):** Спецификация семантики HTTP, правила обработки hop-by-hop заголовков и методы авторизации.
* **RFC 2817:** Использование метода CONNECT для туннелирования TLS через HTTP-прокси.
* **RFC 7230:** Архитектура и маршрутизация сообщений HTTP/1.1 через промежуточные узлы (прокси и шлюзы).
* **CVE-2016-5387 (httpoxy):** Спецификация уязвимости подделки заголовка Proxy в приложениях CGI/FastCGI.