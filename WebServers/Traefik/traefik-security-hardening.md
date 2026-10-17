# Security Hardening Traefik: TLS, DDoS, заголовки, аудит

**Актуально для:** Traefik v3.x (протестировано на v3.3–v3.6; совместимость с v2.11)

## Определения

**Security Hardening (Ужесточение безопасности)** — процесс минимизации поверхности атаки информационной системы путем отключения неиспользуемых функций, применения строгих политик аутентификации, шифрования, изоляции среды исполнения и ограничения прав доступа.

**Defense-in-Depth (Эшелонированная защита)** — архитектурная стратегия информационной безопасности, предусматривающая развертывание нескольких независимых слоев контроля (сеть, ОС, контейнер, прокси-сервер, приложение) для предотвращения компрометации при отказе одного из барьеров.

**TLS Hardening** — конфигурация параметров криптографического рукопожатия TLS: фиксация современных версий протокола (TLS 1.2/1.3), выбор стойких наборов шифров (cipher suites) с обязательной поддержкой прямой секретности (PFS), ограничение эллиптических кривых и принудительная строгая валидация Server Name Indication (`sniStrict`).

**PFS (Perfect Forward Secrecy, совершенная прямая секретность)** — свойство криптографических протоколов, гарантирующее, что компрометация долговременного закрытого ключа сервера не позволит расшифровать ранее перехваченный сетевой трафик сессий (реализуется через алгоритмы ECDHE/DHE).

**L7 DoS / DDoS (Application-Level Denial of Service)** — атаки на исчерпание вычислительных ресурсов обратного прокси или бэкенд-серверов (CPU, память, пул соединений, дескрипторы сокетов) с помощью легитимных или полуоткрытых HTTP-запросов высокой интенсивности либо низкой скорости передачи.

**Slowloris** — атака класса Slow HTTP DoS, при которой атакующий медленно передает HTTP-заголовки запроса (по 1 байту в несколько секунд), не закрывая TCP-соединение, что приводит к исчерпанию пула горутин и открытых файловых дескрипторов обратного прокси.

**HTTP Security Headers (Заголовки безопасности HTTP)** — набор стандартизированных директив HTTP-ответа (HSTS, CSP, X-Content-Type-Options, Permissions-Policy, Referrer-Policy), передаваемых браузеру клиента для активации встроенных механизмов защиты от межсайтового скриптинга (XSS), кликджекинга и инъекций контента.

**HSTS Preload** — механизм включения домена в жестко зашитый список браузеров (Chrome, Firefox, Safari), исключающий даже первичный незашифрованный HTTP-запрос при первом обращении пользователя.

**CSP (Content Security Policy)** — заголовок HTTP-ответа, определяющий белый список доверенных источников загрузки исполняемых скриптов, стилей, изображений и фреймов, блокирующий выполнение несанкционированного JavaScript-кода в контексте браузера.

**Docker Socket Proxy** — защитный шлюз для Unix-сокета Docker API (`/var/run/docker.sock`), блокирующий модифицирующие операции (`POST`, `PUT`, `DELETE`) и предоставляющий обратному прокси доступ исключительно к безопасным операциям чтения (`GET`) метаданных контейнеров и сетей.

**InFlightReq** — встроенный middleware Traefik, ограничивающий количество одновременно обрабатываемых запросов на уровне одного клиента, IP-адреса или всего роутера для предотвращения лавинного исчерпания ресурсов.

**Log Redaction (Маскирование журналов)** — автоматическое удаление или замена конфиденциальных данных (паролей, токенов `Authorization`, cookie-сессий, PII) из логов доступа до их записи на диск или передачи в централизованные системы SIEM/ELK.

---

## Архитектура и базовые концепции

### 1. Архитектурная модель эшелонированной защиты (Defense-in-Depth)

Комплексная безопасность точки входа Traefik на bare-metal или виртуальной инфраструктуре строится по принципу изоляции слоев:

```
[ Интернет / Корпоративная сеть ]
                 │
                 ▼  (Слой 1: L3/L4 Ядро и Сеть ОС)
┌─────────────────────────────────────────────────────────────┐
│ Linux Host Kernel: sysctl SYN-cookies, somaxconn, iptables  │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼  (Слой 2: Изоляция процесса и контейнера)
┌─────────────────────────────────────────────────────────────┐
│ Container Runtime / Systemd Sandboxing:                     │
│  - Non-root user (UID 65534) + CAP_NET_BIND_SERVICE         │
│  - read_only rootfs + NoNewPrivileges + Drop All Caps       │
│  - Docker Socket Proxy (доступ только на чтение GET)        │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼  (Слой 3: Точки входа Traefik EntryPoints)
┌─────────────────────────────────────────────────────────────┐
│ EntryPoints Hardening:                                      │
│  - respondingTimeouts (read/write/idle) против Slowloris    │
│  - maxHeaderBytes (защита от переполнения буфера заголовков)│
│  - Изоляция Dashboard/API/Metrics на 127.0.0.1:8080         │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼  (Слой 4: Криптография TLS)
┌─────────────────────────────────────────────────────────────┐
│ TLS Options:                                                │
│  - minVersion: VersionTLS12 / VersionTLS13                  │
│  - sniStrict: true + PFS Cipher Suites                      │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼  (Слой 5: Конвейер L7 Middleware)
┌─────────────────────────────────────────────────────────────┐
│ 1. IPAllowList (быстрое отсечение неразрешенных сетей)       │
│ 2. InFlightReq + RateLimit (защита от всплесков и DoS)      │
│ 3. Security Headers (HSTS, CSP, X-Frame-Options, No-Server) │
│ 4. Authentication (BasicAuth / ForwardAuth SSO)             │
│ 5. WAF / CrowdSec Bouncer (L7 инспекция сигнатур)           │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼  (Слой 6: Наблюдаемость и аудит)
┌─────────────────────────────────────────────────────────────┐
│ AccessLog Engine: JSON, Redact Authorization/Cookie -> SIEM │
└─────────────────────────────────────────────────────────────┘
```

### 2. Защита от L4/L7 DoS, Slowloris и сетевых атак

Обратные прокси-серверы архитектурно подвержены атакам исчерпания файловых дескрипторов и пула горутин Go. При стандартных настройках Traefik удерживает соединение открытым неограниченно долго, если клиент передает данные медленно.

#### Механизм Slowloris и его подавление

В атаке Slowloris атакующий открывает множество TCP-сокетов и отправляет незавершенные HTTP-заголовки с интервалом в десятки секунд (например, `X-Dummy: value\r\n`). Горутины HTTP-сервера Traefik блокируются на операции чтения из сокета (`io.Read`).

Защита реализуется на уровне статической конфигурации точек входа (`entryPoints.<name>.transport.respondingTimeouts`):

| Параметр | По умолчанию | Hardened значение | Назначение в защите |
| :--- | :--- | :--- | :--- |
| `respondingTimeouts.readTimeout` | `0s` (бесконечно) | `10s`–`30s` | Лимит времени на чтение всего запроса (заголовки и тело). Принудительно разрывает сокет медленного атакующего. |
| `respondingTimeouts.writeTimeout` | `0s` (бесконечно) | `10s`–`30s` | Лимит времени на отдачу ответа клиенту. Предотвращает удержание соединений клиентами с искусственно заниженным окном TCP window. |
| `respondingTimeouts.idleTimeout` | `180s` | `30s`–`60s` | Время удержания открытого Keep-Alive соединения без новых запросов. Освобождает неиспользуемые сокеты. |
| `maxHeaderBytes` | `1048576` (1 МБ) | `8192`–`16384` (8–16 КБ) | Ограничение максимального объема заголовков HTTP-запроса. Блокирует DoS-атаки на переполнение оперативной памяти парсера заголовков. |

#### Специфика защиты от DoS/DDoS без облачных сервисов

В автономной on-premise и bare-metal инфраструктуре защита от объемных атак распределяется между сетевым уровнем провайдера и ОС хоста:

1. **Volumetric (L3/L4 флуд канала):** Подавляется на уровне аплинка/ЦОД с помощью BGP Flowspec, RTBH (Remotely Triggered Black Hole) или транзитных центров фильтрации трафика оператора связи. Сам сервер Traefik физически не может обработать объем трафика, превышающий пропускную способность сетевого интерфейса.
2. **SYN Flood (L4):** Отражается ядром Linux хоста через активацию SYN cookies (`net.ipv4.tcp_syncookies = 1`), увеличение очереди неполных соединений (`net.ipv4.tcp_max_syn_backlog = 16384`) и использование механизма `nftables`/`iptables` SYNPROXY до передачи пакетов в сокет Traefik.
3. **L7 HTTP Flood:** Ограничивается комбинацией middleware Traefik:
   - `inFlightReq` — жестко квотирует одновременные соединения с одного источника;
   - `rateLimit` — сглаживает всплески запросов по алгоритму Token Bucket (см. [Rate Limiting в Traefik](./traefik-rate-limiting-deep.md));
   - CrowdSec / WAF — блокирует скомпрометированные IP-адреса на основе репутации и поведенческого анализа (см. [Traefik + CrowdSec](./traefik-edge-security-waf.md)).

### 3. TLS Hardening: соответствие стандартам PCI-DSS и Modern Security

По умолчанию стек Go в Traefik поддерживает обратную совместимость, что может допускать устаревшие шифры TLS 1.2. Промышленный hardening требует явного определения профилей в динамической конфигурации (`tls.options`).

#### Рекомендации по шифрам и криптографическим параметрам

- **Минимальная версия:** `VersionTLS12` (строгий стандарт для публичных сервисов, совместимый с PCI-DSS) или `VersionTLS13` (для внутренних API и микросервисов).
- **TLS 1.3:** Наборы шифров в TLS 1.3 стандартизированы протоколом (IETF) и не настраиваются пользователем — они всегда используют современные AEAD-шифры (`TLS_AES_128_GCM_SHA256`, `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`).
- **TLS 1.2 Cipher Suites:** Допускаются исключительно шифры с прямой секретностью (PFS) и алгоритмами аутентифицированного шифрования (GCM / Poly1305). Любые CBC-шифры (подверженные атакам типа Lucky Thirteen) и статический обмен ключами RSA (без Diffie-Hellman) исключаются:
  - `TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256`
  - `TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256`
  - `TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384`
  - `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`
  - `TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305`
  - `TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305`
- **Строгий SNI (`sniStrict: true`):** Соединения, в которых клиент не передает расширение SNI (Server Name Indication) либо запрашивает домен, для которого у Traefik отсутствует соответствующий сертификат, немедленно сбрасываются с ошибкой TLS alert `unrecognized_name`. Это защищает от сканеров по IP-адресу и предотвращает утечку дефолтного сертификата.
- **Эллиптические кривые (`curvePreferences`):** Явное предпочтение надежных кривых `CurveP384` и `CurveP521`.

### 4. Комплекс защитных заголовков (HTTP Security Headers)

Заголовки безопасности передаются клиенту через middleware `headers`:

| Заголовок | Директива Traefik | Рекомендуемое значение | Назначение |
| :--- | :--- | :--- | :--- |
| **Strict-Transport-Security** | `stsSeconds: 31536000`<br>`stsIncludeSubdomains: true`<br>`stsPreload: true` | `max-age=31536000; includeSubDomains; preload` | Принудительный переход на HTTPS на 1 год вперед с фиксацией в Preload-списках браузеров. |
| **X-Content-Type-Options** | `contentTypeNosniff: true` | `nosniff` | Запрещает браузеру угадывать MIME-тип контента вопреки заголовку `Content-Type`. |
| **X-Frame-Options** | `frameDeny: true` | `DENY` | Полный запрет отображения страниц приложения внутри `<iframe>`, `<frame>`, `<object>`. |
| **Content-Security-Policy** | `contentSecurityPolicy: "..."` | `default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'` | Блокирует выполнение инъекций скриптов и ограничивает источники загрузки ресурсов. Директива `frame-ancestors 'none'` дублирует и усиливает `X-Frame-Options`. |
| **Referrer-Policy** | `referrerPolicy: "..."` | `strict-origin-when-cross-origin` | Передает полный URL только при внутренних переходах; при внешних переходах передает только домен; при переходе на HTTP заголовок отсекается. |
| **Permissions-Policy** | `permissionsPolicy: "..."` | `camera=(), microphone=(), geolocation=(), payment=()` | Блокирует доступ веб-страницы к аппаратным API браузера (камера, микрофон, геолокация). |
| **Сокрытие ПО (Server)** | `customResponseHeaders` | `Server: ""` | Удаляет или перезаписывает идентификационные заголовки бэкендов (`Server`, `X-Powered-By`), снижая эффективность автоматизированного сканирования уязвимостей. |

### 5. Изоляция среды исполнения и Docker Socket

Прямое пробрасывание Unix-сокета `/var/run/docker.sock` в контейнер обратного прокси представляет критическую уязвимость: доступ к сокету эквивалентен полным правам суперпользователя (`root`) на хосте. В случае компрометации Traefik (RCE) злоумышленник может развернуть привилегированный контейнер с монтированием корня хостовой файловой системы.

#### Архитектура изоляции через Socket Proxy

```
┌───────────────────────────────── Traefik Host ────────────────────────────────┐
│                                                                               │
│  [ Публичная сеть ] ───▶ [ Контейнер Traefik ]                                │
│                             - User: 65534 (nobody)                            │
│                             - Read-only root filesystem                       │
│                             - Cap Drop: ALL (+ NET_BIND_SERVICE)              │
│                             - НЕТ доступа к /var/run/docker.sock              │
│                                      │                                        │
│                                      │ TCP :2375 (Внутренняя Docker-сеть)     │
│                                      ▼                                        │
│                          [ Docker Socket Proxy ]                              │
│                             - Монтирует /var/run/docker.sock:ro               │
│                             - Разрешает только: GET /containers, GET /events   │
│                             - Блокирует: POST, PUT, DELETE, EXEC              │
│                                      │                                        │
│                                      ▼                                        │
│                          [ Демон dockerd на хосте ]                           │
└───────────────────────────────────────────────────────────────────────────────┘
```

Для системных сервисов (bare-metal systemd) изоляция реализуется директивами sandboxing: `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true` и запуском от системного пользователя без shell (`/usr/sbin/nologin`).

### 6. Соответствие матрицы рисков OWASP Top 10 (2021)

| Риск OWASP Top 10 | Механизм нейтрализации в Traefik | Архитектурная реализация |
| :--- | :--- | :--- |
| **A01:2021 — Broken Access Control** | `ipAllowList`, `basicAuth`, `forwardAuth` | Фильтрация доверенных IP-диапазонов для административных роутов; интеграция с централизованным IdP (Authelia/OAuth2-Proxy). |
| **A02:2021 — Cryptographic Failures** | TLS Options, mTLS, HSTS | Запрет версий ниже TLS 1.2, исключение CBC-шифров, автоматизация Let's Encrypt / Vault ACME, принудительный редирект на HTTPS. |
| **A03:2021 — Injection** | WAF (CrowdSec AppSec), `maxHeaderBytes` | Синхронная инспекция тела и заголовков запросов по правилам OWASP CRS до передачи в бэкенд; ограничение размера буфера заголовков. |
| **A04:2021 — Insecure Design** | `rateLimit`, `inFlightReq`, CircuitBreaker | Сглаживание трафика, предотвращение каскадных сбоев зависимых микросервисов, локализация отказов. |
| **A05:2021 — Security Misconfiguration** | `api.insecure: false`, скрытие баннеров | Вынос Dashboard на изолированный loopback-порт с парольной защитой; удаление заголовков `Server` и `X-Powered-By`. |
| **A06:2021 — Vulnerable Components** | Фиксация версий, минимальные образы | Запрет использования тега `:latest`; эксплуатация официальных контейнеров на базе `scratch`/`alpine`; аудит плагинов Yaegi. |
| **A07:2021 — Identification & Auth Failures** | Rate limiting на роуты входа, mTLS | Ограничение перебора паролей (brute-force) на `/login`; строгая клиентская сертификатная аутентификация для межсервисного взаимодействия. |
| **A08:2021 — Software & Data Integrity** | TLS, строгий CSP | Проверка целостности бинарных файлов при установке; строгие CSP-директивы для предотвращения подгрузки сторонних скриптов. |
| **A09:2021 — Security Logging & Monitoring** | Структурированный JSON AccessLog | Непрерывная передача логов в SIEM; маскирование (`redact`) авторизационных токенов и Cookie; экспорт метрик 4xx/5xx в Prometheus. |
| **A10:2021 — SSRF (Server-Side Request Forgery)** | Сетевая сегментация upstream | Изоляция Traefik и внутренних микросервисов в выделенных мостовых сетях (bridge networks) без прямого доступа к служебным адресам хоста. |

---

## Практические сценарии

### Сценарий 1: Комплексный Middleware безопасности (Global Security Headers)

Конфигурация формирует эталонный набор заголовков безопасности и принудительно удаляет идентифицирующие заголовки бэкендов (`Server`, `X-Powered-By`).

#### 1. Определение middleware в файловом провайдере: `/etc/traefik/dynamic/security-headers.yml`

```yaml
http:
  middlewares:
    hardening-headers:
      headers:
        # HSTS (RFC 6797)
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        forceSTSHeader: true

        # Защита от MIME-sniffing и Clickjacking
        contentTypeNosniff: true
        frameDeny: true

        # Устаревший X-XSS-Protection (поддерживается старыми клиентами)
        browserXssFilter: true

        # Контроль передачи Referrer
        referrerPolicy: "strict-origin-when-cross-origin"

        # Ограничение возможностей браузера
        permissionsPolicy: "camera=(), microphone=(), geolocation=(), payment=(), usb=()"

        # Content Security Policy (Строгий базовый профиль)
        contentSecurityPolicy: "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self';"

        # Сокрытие информации о серверном стеке
        customResponseHeaders:
          Server: ""
          X-Powered-By: ""
          X-AspNet-Version: ""
```

#### 2. Применение middleware глобально ко всей входной точке: `/etc/traefik/traefik.yml`

```yaml
entryPoints:
  websecure:
    address: ":443"
    http:
      middlewares:
        - hardening-headers@file
```

---

### Сценарий 2: Защита от DoS, Slowloris и ограничение соединений

Сценарий реализует двухуровневую защиту: жесткие таймауты сокетов на уровне статической конфигурации точки входа и цепочку динамических middleware `inFlightReq` + `rateLimit`.

#### 1. Статическая конфигурация: `/etc/traefik/traefik.yml`

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      respondingTimeouts:
        readTimeout: 15s      # Защита от Slowloris: сброс при медленной отправке заголовков/тела
        writeTimeout: 15s     # Защита от медленного вычитывания ответа клиентом
        idleTimeout: 60s      # Освобождение неактивных keep-alive сессий
    http:
      maxHeaderBytes: 8192    # Ограничение размера заголовков (8 КБ)
```

#### 2. Динамическая конфигурация цепочки: `/etc/traefik/dynamic/dos-protection.yml`

```yaml
http:
  middlewares:
    # Ограничение параллельных запросов с одного IP
    limit-inflight:
      inFlightReq:
        amount: 20
        sourceCriterion:
          ipStrategy:
            depth: 1

    # Сглаживание частоты запросов (Token Bucket)
    limit-ratelist:
      rateLimit:
        average: 50
        period: 1s
        burst: 100
        sourceCriterion:
          ipStrategy:
            depth: 1

    # Агрегация в цепочку
    dos-defense-chain:
      chain:
        middlewares:
          - limit-inflight
          - limit-ratelist
```

---

### Сценарий 3: Защищенный запуск Traefik в Docker Compose с Socket Proxy

Производственный манифест `compose.yaml` с полным отключением привилегий root, использованием read-only файловой системы и доступом к Docker API исключительно через прокси в режиме только для чтения.

```yaml
# /opt/infra/traefik/compose.yaml
services:
  # Защитный шлюз к сокету Docker
  socket-proxy:
    image: tecnativa/docker-socket-proxy:0.1.1
    container_name: traefik-socket-proxy
    restart: unless-stopped
    read_only: true
    environment:
      # Разрешаем только минимально необходимые GET-запросы для Traefik
      - CONTAINERS=1
      - NETWORKS=1
      - SERVICES=1
      - TASKS=1
      - NODES=1
      - EVENTS=1
      # Категорически запрещаем любые модифицирующие операции
      - POST=0
      - PUT=0
      - DELETE=0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - socket-net
    security_opt:
      - no-new-privileges:true

  # Основной обратный прокси Traefik v3
  traefik:
    image: traefik:v3.6.4
    container_name: traefik-edge
    restart: unless-stopped
    depends_on:
      - socket-proxy
    # Запуск от непривилегированного пользователя (nobody:nogroup)
    user: "65534:65534"
    # Запрет изменения файлов контейнера
    read_only: true
    security_opt:
      - no-new-privileges:true
    # Сброс всех Linux capabilities и выдача только права биндинга привилегированных портов
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    ports:
      - "80:80"
      - "443:443"
    environment:
      - TZ=Etc/UTC
    volumes:
      # Статическая и динамическая конфигурация
      - /opt/infra/traefik/config/traefik.yml:/etc/traefik/traefik.yml:ro
      - /opt/infra/traefik/config/dynamic:/etc/traefik/dynamic:ro
      # Локальное хранилище сертификатов Let's Encrypt (права строго 0600)
      - /opt/infra/traefik/certs/acme.json:/etc/traefik/acme.json:rw
      # Журналы доступа
      - /opt/infra/traefik/logs:/var/log/traefik:rw
    tmpfs:
      # Временные каталоги в оперативной памяти (noexec, nosuid)
      - /tmp:rw,noexec,nosuid,size=64m
    networks:
      - socket-net
      - public-web

networks:
  socket-net:
    internal: true # Изолированная внутренняя сеть без выхода в интернет
  public-web:
    name: public-web
```

---

### Сценарий 4: Безопасная публикация Dashboard, API и метрик

По умолчанию `api.insecure: true` открывает доступ к административной панели на порту `:8080` без аутентификации. Безопасная конфигурация требует выноса управления на loopback-интерфейс хоста либо принудительную защиту через `basicAuth` и `ipAllowList`.

#### 1. Статическая конфигурация: `/opt/infra/traefik/config/traefik.yml`

```yaml
# Отключение незащищенного режима
api:
  dashboard: true
  insecure: false

# Выделение точки входа для внутреннего управления
entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"
  internal-mgmt:
    address: "127.0.0.1:8080" # Слушать только на локальном интерфейсе

# Привязка встроенных сервисов к внутренней точке входа
ping:
  entryPoint: internal-mgmt

metrics:
  prometheus:
    entryPoint: internal-mgmt
    addEntryPointsLabels: true
    addServicesLabels: true

# Подключение провайдеров
providers:
  docker:
    endpoint: "tcp://socket-proxy:2375" # Работа через socket-proxy
    exposedByDefault: false             # Явная активация только через метки
  file:
    directory: /etc/traefik/dynamic
    watch: true
```

#### 2. Защищенный маршрутизатор Dashboard: `/opt/infra/traefik/config/dynamic/dashboard.yml`

```yaml
http:
  routers:
    traefik-dashboard:
      rule: "Host(`traefik.corp.internal`) && (PathPrefix(`/api`) || PathPrefix(`/dashboard`))"
      entryPoints:
        - websecure
      service: api@internal
      middlewares:
        - mgmt-ip-whitelist
        - mgmt-auth
      tls: {}

  middlewares:
    # Ограничение по служебным подсетям администраторов
    mgmt-ip-whitelist:
      ipAllowList:
        sourceRange:
          - "192.168.10.0/24"
          - "10.100.0.0/16"
        rejectStatusCode: 404 # Возврат 404 скрывает факт существования дашборда

    # Аутентификация по алгоритму bcrypt
    mgmt-auth:
      basicAuth:
        users:
          # admin / StrongPasswordGeneratedByHtpasswd
          - "admin:$2y$10$vN918lS3Z8u5fXQ...XwV4aR4lG"
        removeHeader: true
```

---

### Сценарий 5: Строгий профиль TLS Hardening (PCI-DSS compliant)

Конфигурация отключает устаревшие протоколы (TLS 1.0, 1.1) и ненадежные шифры, активирует `sniStrict` и настраивает профили для разных требований безопасности.

Файл конфигурации: `/etc/traefik/dynamic/tls-hardening.yml`

```yaml
tls:
  options:
    # Профиль по умолчанию: применяется ко всем HTTPS-роутерам
    default:
      minVersion: VersionTLS12
      sniStrict: true
      cipherSuites:
        # Только современные наборы шифров с PFS (GCM / Poly1305)
        - TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256
        - TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
        - TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384
        - TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
        - TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305
        - TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305
      curvePreferences:
        - CurveP384
        - CurveP521

    # Ультрастрогий профиль: только TLS 1.3 для критических API
    modern-strict:
      minVersion: VersionTLS13
      sniStrict: true

http:
  routers:
    critical-payment-api:
      rule: "Host(`pay.example.com`)"
      entryPoints: [websecure]
      service: payment-service
      tls:
        options: modern-strict
```

---

### Сценарий 6: Аудит, структурирование и маскирование Access Log для SIEM

При передаче журналов веб-сервера в системы централизованного мониторинга и SIEM критически важно исключить утечку учетных данных, паролей и токенов сессий, одновременно сохранив структурированные данные для расследования инцидентов.

Файл конфигурации: `/etc/traefik/traefik.yml` (секция `accessLog`)

```yaml
accessLog:
  filePath: "/var/log/traefik/access.log"
  format: json
  bufferingSize: 100 # Буферизация строк в памяти для снижения I/O нагрузки

  # Логировать только запросы с кодами ошибок или с длительностью > 200 мс
  filters:
    statusCodes:
      - "400-599"
    minDuration: "200ms"
    retryAttempts: true

  # Гранулярное управление полями и заголовками
  fields:
    defaultMode: keep
    names:
      ClientUsername: drop # Исключение имен пользователей из URL
    headers:
      defaultMode: drop # По умолчанию заголовки не пишутся в лог
      names:
        User-Agent: keep
        X-Forwarded-For: keep
        X-Real-Ip: keep
        # Маскирование конфиденциальных заголовков
        Authorization: redact
        Proxy-Authorization: redact
        Cookie: redact
        Set-Cookie: redact
        X-Api-Key: redact
```

Пример результирующей записи в `/var/log/traefik/access.log`:

```json
{
  "ClientAddr": "192.0.2.45:49152",
  "ClientHost": "192.0.2.45",
  "Duration": 24510231,
  "OriginStatus": 401,
  "RequestAddr": "api.example.com",
  "RequestMethod": "POST",
  "RequestPath": "/api/v1/auth",
  "RequestProtocol": "HTTP/2.0",
  "RouterName": "api-router@docker",
  "ServiceDuration": 22104500,
  "ServiceName": "api-service@docker",
  "ServiceURL": "http://172.18.0.5:8080",
  "StartLocal": "2026-10-17T20:50:12.124Z",
  "Status": 401,
  "request_Authorization": "[REDACTED]",
  "request_Cookie": "[REDACTED]",
  "request_User-Agent": "Mozilla/5.0 ...",
  "request_X-Forwarded-For": "203.0.113.195"
}
```

---

## Операции и команды

### 1. Верификация TLS конфигурации и наборов шифров

Проверка используемой версии TLS, алгоритма рукопожатия и сертификата:

```bash
# Проверка установленного TLS протокола и шифра
openssl s_client -connect app.example.com:443 -servername app.example.com </dev/null 2>/dev/null | grep -E "Protocol|Cipher"
# →     Protocol  : TLSv1.3
# →     Cipher    : TLS_AES_256_GCM_SHA384

# Проверка реакции на отсутствие SNI (при sniStrict: true)
openssl s_client -connect app.example.com:443 </dev/null 2>&1 | grep -i "alert"
# → 14032458:error:14094458:SSL routines:ssl3_read_bytes:tlsv1 alert unrecognized name:../ssl/record/rec_layer_s3.c:1544:SSL alert number 112

# Сканирование доступных на сервере cipher suites через nmap
nmap --script ssl-enum-ciphers -p 443 app.example.com
# → PORT    STATE SERVICE
# → 443/tcp open  https
# → | ssl-enum-ciphers:
# → |   TLSv1.2:
# → |     ciphers:
# → |       TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256 (secp384r1) - A
# → |       TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384 (secp384r1) - A
# → |   TLSv1.3:
# → |     ciphers:
# → |       TLS_AES_128_GCM_SHA256 (secp384r1) - A
# → |       TLS_AES_256_GCM_SHA384 (secp384r1) - A
# → |_  least strength: A
```

### 2. Аудит HTTP-заголовков безопасности

Проверка отдачи защитных директив и отсутствия идентифицирующих заголовков ПО:

```bash
# Инспекция заголовков ответа
curl -sI https://app.example.com/ | grep -E -i "strict-transport|content-security|x-frame|x-content-type|referrer-policy|permissions-policy|server"
# → strict-transport-security: max-age=31536000; includeSubDomains; preload
# → x-content-type-options: nosniff
# → x-frame-options: DENY
# → content-security-policy: default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self';
# → referrer-policy: strict-origin-when-cross-origin
# → permissions-policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
```

### 3. Тестирование устойчивости к Slowloris

Проверка эффективности `respondingTimeouts` с помощью утилиты `slowhttptest`:

```bash
# Имитация медленной передачи HTTP-заголовков (100 соединений, интервал 10 секунд)
slowhttptest -c 100 -H -g -o /tmp/slow_report -i 10 -r 20 -t GET -u https://app.example.com/ -l 30
# → Initializing test with standard headers...
# → Test ends in 30 seconds
# → Slow HTTP test status:
# →   connected: 0
# →   connecting: 0
# →   closed: 100
# →   service available: YES
# Traefik успешно разорвал все медленные соединения по истечении readTimeout (15s)
```

### 4. Аудит прав и песочницы контейнера Traefik

Проверка привилегий процесса на хосте Linux:

```bash
# 1. Поиск PID процесса Traefik на хосте
PID=$(pgrep -f "traefik")

# 2. Проверка пользователя (должен быть nobody / non-root)
ps -u -p $PID
# → USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
# → 65534       3412  0.2  0.4 789420 38240 ?        Ssl  20:00   0:02 /traefik

# 3. Проверка Linux Capabilities процесса
grep Cap /proc/$PID/status
# → CapInh: 0000000000000000
# → CapPrm: 0000000000000400  # 0x400 соответствует только CAP_NET_BIND_SERVICE
# → CapEff: 0000000000000400
# → CapBnd: 0000000000000400

# 4. Проверка статуса NoNewPrivileges
grep NoNewPrivs /proc/$PID/status
# → NoNewPrivs: 1
```

### 5. Валидация маскирования секретов в Access Log

Проверка отсутствия утечки открытых токенов в журналах:

```bash
# Отправка тестового запроса с токеном Bearer
curl -s -H "Authorization: Bearer secret-admin-token-12345" https://app.example.com/api/test >/dev/null

# Проверка содержимого последней строки access.log через jq
tail -n 1 /var/log/traefik/access.log | jq '{RequestPath, Status, request_Authorization}'
# → {
# →   "RequestPath": "/api/test",
# →   "Status": 200,
# →   "request_Authorization": "[REDACTED]"
# → }
```

---

## Устранение неисправностей

| Симптом / Ошибка | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`remote error: tls: unrecognized name`** | Клиент подключается по IP-адресу или без расширения SNI при активном `sniStrict: true`. | `openssl s_client -connect IP:443` дает ошибку handshake. | Подключаться строго по доменному имени; убедиться, что для домена загружен сертификат в `tls.stores` или ACME. |
| **Обрыв WebSockets / SSE через 15 секунд** | Агрессивные значения `respondingTimeouts.readTimeout` / `writeTimeout` разрывают долгоживущие соединения. | В логах Traefik код `499` или сброс сокета без ошибки бэкенда. | Увеличить `readTimeout` / `writeTimeout` до `60s` или вынести WebSocket на отдельный роутер/entrypoint без жесткого `readTimeout`. |
| **Ложные срабатывания `429 Too Many Requests`** | В `rateLimit` или `inFlightReq` не настроена директива `ipStrategy.depth`, и все клиенты за внешним балансировщиком делят один пул токенов. | Множество легитимных пользователей одновременно получают статус `429`. | Настроить `sourceCriterion.ipStrategy.depth: 1` или `ipStrategy.excludedIPs` с указанием CIDR вышестоящих балансировщиков. |
| **Браузер блокирует скрипты/стили приложения** | Чрезмерно строгий `contentSecurityPolicy` запрещает загрузку необходимых CDN-ассетов или inline-скриптов. | Консоль DevTools браузера сообщает: `Refused to load the script ... because it violates the CSP directive`. | Скорректировать CSP, добавив требуемые доверенные домены в `script-src` / `style-src` либо внедрить хэши/nonce. |
| **Ошибка запуска `permission denied` к сокету Docker** | Контейнер Traefik пытается монтировать сокет напрямую без прав либо socket-proxy не запущен. | Лог Traefik: `Failed to retrieve information of the docker client: permission denied`. | Запускать Traefik через `socket-proxy` по сети TCP (`tcp://socket-proxy:2375`) и не подключать сокет напрямую к Traefik. |
| **`bind: permission denied` при старте на портах 80/443** | Непривилегированный пользователь (`nobody`) не имеет права занимать порты `< 1024`. | Ошибка при старте: `listen tcp :80: bind: permission denied`. | Добавить процессу capability `CAP_NET_BIND_SERVICE` (в Docker: `cap_add: [NET_BIND_SERVICE]`, в systemd: `AmbientCapabilities=CAP_NET_BIND_SERVICE`). |
| **Утечка токенов и Cookie в журнал доступа** | В статической секции `accessLog` не заданы директивы `redact` для чувствительных полей. | Поиск по логу: `grep -i "bearer" /var/log/traefik/access.log` находит реальные токены. | Настроить `accessLog.fields.headers.names` со значениями `redact` для `Authorization`, `Cookie`, `Set-Cookie`. |
| **Служебный Dashboard возвращает 404** | В `ipAllowList` указан `rejectStatusCode: 404`, и IP администратора не входит в доверенный диапазон. | Проверить реальный IP-адрес администратора через `curl ifconfig.me`. | Добавить внешний или VPN IP-адрес администратора в список `sourceRange`. |

---

## Рекомендации и лучшие практики

### 1. Чек-лист аудита безопасности Traefik (Production Readiness)

- [ ] **Конфигурация API:** `api.insecure: false`. Доступ к Dashboard и метрикам защищен аутентификацией и закрыт сетевым фильтром.
- [ ] **Изоляция сокета:** `/var/run/docker.sock` не монтируется в публичный контейнер Traefik; используется `docker-socket-proxy` с флагами `POST=0`, `PUT=0`, `DELETE=0`.
- [ ] **Привилегии процесса:** Контейнер запускается от `user: "65534:65534"` (non-root), `read_only: true`, `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, `cap_add: [NET_BIND_SERVICE]`.
- [ ] **Защита от Slowloris:** На всех публичных entrypoints явно заданы `respondingTimeouts` (`readTimeout: 15s`, `writeTimeout: 15s`, `idleTimeout: 60s`).
- [ ] **Ограничение буферов:** Значение `maxHeaderBytes` ограничено диапазоном `8192`–`16384` байт.
- [ ] **TLS Hardening:** Минимальная версия TLS не ниже `VersionTLS12`; включен `sniStrict: true`; исключены CBC и не-PFS шифры.
- [ ] **Заголовки безопасности:** Применен глобальный middleware с `HSTS` (`includeSubDomains`, `preload`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `CSP`, `Permissions-Policy`.
- [ ] **Сокрытие серверных баннеров:** Удалены заголовки `Server` и `X-Powered-By` через `customResponseHeaders`.
- [ ] **DoS-защита роутеров:** Настроены middleware `inFlightReq` и `rateLimit` для публичных маршрутов аутентификации и API.
- [ ] **Безопасность журналов:** Access Log настроен в формате `json` с буферизацией и обязательным маскированием (`redact`) заголовков `Authorization`, `Cookie`, `Set-Cookie`.
- [ ] **Секреты:** Файл `acme.json` имеет права строго `0600`; токены DNS-провайдеров передаются через защищенные переменные окружения или docker secrets (без открытого текста в git).

### 2. Архитектурные правила для SRE и системных администраторов

1. **Разделение плоскостей управления и данных (Control Plane vs Data Plane):** Служебные интерфейсы (`/dashboard`, `/api`, `/metrics`, `/ping`) никогда не должны публиковаться на тех же точках входа, что и клиентский трафик. Для управления выделяется отдельный entrypoint, слушающий `127.0.0.1` или изолированный VLAN управления.
2. **Fail-Closed подход для конфиденциальных данных:** Если внешний сервис аутентификации (ForwardAuth) или WAF (AppSec) недоступен, политика маршрутизации должна прерывать сессию с ошибкой 401/403, а не пропускать запрос к бэкенду.
3. **Белые списки вместо черных:** В правилах `ipAllowList` и `contentSecurityPolicy` используйте принцип явного разрешения доверенных источников; отказ от запрещающих списков снижает риск обхода фильтрации.
4. **Регулярный автоматизированный аудит:** Настройте периодический запуск `testssl.sh` или интеграцию в CI/CD пайплайны проверок соответствия конфигурации Traefik лучшим практикам OWASP и CIS Benchmarks.

---

## Дополнительная информация

- [TLS Options и mTLS в Traefik](./traefik-tls-options.md) — детальный справочник параметров TLS, клиентской аутентификации и сертификатов.
- [Rate Limiting в Traefik](./traefik-rate-limiting-deep.md) — архитектура Token Bucket, распределенный лимитер с Redis и защита от DoS.
- [Traefik + CrowdSec Edge Security](./traefik-edge-security-waf.md) — развертывание WAF, инспекция AppSec и поведенческий бан атакующих IP.
- [Управление секретами в Traefik](./traefik-secrets.md) — безопасная доставка сертификатов, Vault PKI и защита `acme.json`.
- [Развертывание Traefik в Docker Compose](./traefik_with_docker_compose.md) — эталонные шаблоны compose-файлов и изоляция сервисов.
- [Traefik на Bare-Metal](./traefik-bare-metal.md) — системные настройки sysctl, systemd sandboxing и тюнинг производительности ядра Linux.
- [Middleware безопасности и аутентификации](./traefik-middlewares-security.md) — настройка BasicAuth, ForwardAuth и IPAllowList.
