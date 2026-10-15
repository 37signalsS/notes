# HAProxy

**Актуально для:** HAProxy 3.4 LTS / 3.2 LTS / 3.0 LTS

## Определения

**HAProxy (High Availability Proxy)** — высокопроизводительный специализированный балансировщик нагрузки и прокси-сервер с открытым исходным кодом для сетевых протоколов TCP (L4) и HTTP (L7). Работает на основе управляемой событиями однопоточной/многопоточной архитектуры, обеспечивая минимальные задержки и высокую пропускную способность в bare-metal и виртуализированных инфраструктурах.

**Frontend** — секция конфигурации, определяющая сетевые сокеты (IP-адреса и порты) для приема входящих соединений от клиентов, политики безопасности, правила обработки заголовков и маршрутизацию запросов к бэкендам на основе ACL.

**Backend** — секция конфигурации, описывающая пул целевых серверов приложений (узлов обработки), алгоритм распределения входящего трафика между ними, параметры активных проверок работоспособности (Health Checks) и поведение при отказах.

**Listen (Listener)** — компактная секция конфигурации, объединяющая функции frontend и backend в едином блоке. Применяется для простых TCP-прокси (базы данных, SSH, внутренние RPC) или вспомогательных сервисов (панель статистики, Prometheus endpoint).

**ACL (Access Control List)** — механизм условной логики в HAProxy, позволяющий анализировать атрибуты входящих пакетов и запросов (IP-адрес источника, SNI, HTTP-метод, URL-путь, заголовки, cookies, значения счетчиков) для динамического принятия решений о маршрутизации, блокировке или модификации трафика.

**Stick Table** — встроенное высокопроизводительное key-value хранилище в разделяемой оперативной памяти процесса HAProxy. Используется для привязки клиентских сессий (Session Persistence/Affinity), трекинга поведения пользователей, ограничения интенсивности запросов (Rate Limiting) и отражения атак без обращения к внешним базам данных.

**Sticky Counter (`sc0`–`sc2` / `sc3`–`sc9`)** — числовой дескриптор, связывающий обрабатываемую сессию или запрос с определенной записью в Stick Table для инкрементации счетчиков и проверки пороговых значений.

**Runtime API (Stats Socket)** — административный интерфейс взаимодействия через локальный UNIX domain socket (или сетевой TCP-сокет), предоставляющий доступ к управлению процессами, пулами серверов, весами балансировки и Stick Tables в режиме реального времени без перезапуска службы.

**PROMEX (Prometheus Native Exporter)** — нативный встроенный модуль экспорта метрик производительности и состояния HAProxy в формате Prometheus, компилируемый с директивой `USE_PROMEX=1` и активируемый директивой `http-request use-service prometheus-exporter`.

**OpenTelemetry Filter** — нативный модуль фильтрации, обеспечивающий генерацию и передачу распределенных трассировок и телеметрии в формате OTLP непосредственно из конвейера обработки запросов балансировщика.

**Seamless Reload (Master-Worker)** — режим управления процессами (`-W` / `-Ws`), позволяющий мастер-процессу запускать новый рабочий процесс с обновленной конфигурацией и бесшовно передавать ему слушающие сокеты через UNIX-сокет без сброса активных клиентских TCP-соединений.

**SPOE (Stream Processing Offload Engine)** — механизм выноса ресурсоемких операций обработки сетевого потока (проверка спама, внешняя аутентификация, интеграция с WAF, анализ сигнатур) во внешние вспомогательные сервисы без блокировки основного цикла событий балансировщика.

**PROXY Protocol (v1/v2)** — сетевой протокол, разработанный HAProxy Technologies, передающий метаданные исходного клиентского соединения (реальный IP-адрес клиента, порт, IP-адрес прокси, информацию о TLS-сессии) в заголовке TCP перед полезной нагрузкой.

**Connection Pooling (`http-reuse`)** — механизм повторного использования установленных TCP/TLS-соединений между HAProxy и серверами приложений для снижения накладных расходов на рукопожатия и предотвращения исчерпания сетевых портов.

**Health Check (Проверка жизнеспособности)** — периодический опрос целевых серверов на L4 (TCP/SSL handshake) или L7 (HTTP-запрос с проверкой статус-кода и тела ответа) для автоматического исключения неисправных узлов из ротации.

---

## Основные концепции

### Архитектура и событийная модель (Event Loop)

HAProxy спроектирован вокруг архитектуры, управляемой событиями (Event-Driven Architecture), использующей неблокирующие системные вызовы ввода-вывода (`epoll` в Linux, `kqueue` в BSD).

```
                      ┌──────────────────────────────────────┐
                      │      Master Process (PID 1200)       │
                      │  - Управление жизненным циклом       │
                      │  - Чтение конфигурации и валидация   │
                      │  - Перезагрузка без простоя (SIGUSR2)│
                      └──────────────────┬───────────────────┘
                                         │ UNIX Socket (Передача дескрипторов)
                      ┌──────────────────┴───────────────────┐
                      │      Worker Process (PID 1201)       │
                      │                                      │
  ┌───────────────────┼───────────────────┬──────────────────┼───────────────────┐
  │ Thread 1 (Core 0) │ Thread 2 (Core 1) │ Thread 3 (Core 2)│ Thread 4 (Core 3) │
  │ - Event Loop      │ - Event Loop      │ - Event Loop     │ - Event Loop      │
  │ - File Descriptors│ - File Descriptors│ - File Descriptors│ - File Descriptors│
  │ - Stick Table Sync│ - Stick Table Sync│ - Stick Table Sync│ - Stick Table Sync│
  └───────────────────┴───────────────────┴──────────────────┴───────────────────┘
```

1. **Master-Worker модель:**
   - **Master-процесс** запускается под учетной записью `root` (при необходимости привязки к привилегированным портам < 1024), читает конфигурацию, открывает сокеты и порождает непривилегированные worker-процессы (`user haproxy`, `group haproxy`).
   - При получении сигнала `SIGUSR2` мастер считывает обновленный файл конфигурации, проверяет его валидность, запускает новый рабочий процесс, передает ему слушающие сокеты через дескрипторы сокетов (`-x /run/haproxy/haproxy.sock`) и отправляет старому процессу сигнал `SIGUSR1` для плавного завершения существующих сессий.
2. **Многопоточность (Multithreading):**
   - Директива `nbthread` определяет количество параллельных потоков внутри одного рабочего процесса. Каждый поток исполняет независимый цикл `epoll`.
   - Директива `cpu-map auto:1/1-4 0-3` осуществляет жесткую привязку (affinity) потоков к конкретным физическим или логическим ядрам CPU, исключая переключение контекста планировщиком ОС и промахи кэша CPU (L1/L2/L3).
3. **Управление памятью:**
   - HAProxy выделяет оперативную память пулами фиксированных буферов (`buffer pooling`). Запросы используют буферы из заранее выделенного пула и возвращают их по окончании сессии, что исключает фрагментацию памяти и снижает накладные расходы на вызовы `malloc()` и `free()`.

### Режимы работы (mode)

HAProxy функционирует в одном из двух ключевых режимов проксирования:

| Параметр | `mode tcp` (L4) | `mode http` (L7) |
| :--- | :--- | :--- |
| **Уровень OSI** | Транспортный (Layer 4) | Прикладной (Layer 7) |
| **Анализируемые данные** | IP-адреса, порты, TCP-флаги, SNI в TLS ClientHello | HTTP-методы, пути (URI), заголовки, куки, тело запроса |
| **Модификация данных** | Нет (прозрачный байтовый поток) | Полная (вставка/удаление заголовков, перезапись путей) |
| **Поддержка протоколов** | Любые поверх TCP: PostgreSQL, MySQL, Redis, SSH, AMQP | HTTP/1.0, HTTP/1.1, HTTP/2, HTTP/3 (QUIC), WebSocket, gRPC |
| **Производительность** | Экстремальная (минимальная утилизация CPU) | Высокая (требует CPU для синтаксического анализа протокола) |
| **TLS-терминация** | Возможен Passthrough (проброс без расшифровки) | Требуется терминация или повторное шифрование |

> [!WARNING]
> Если frontend или backend настроен в `mode tcp`, любые директивы прикладного уровня (`http-request`, `http-response`, проверка заголовков `hdr()` или путей `path`) завершаются ошибкой парсинга конфигурации либо игнорируются во время выполнения.

### Жизненный цикл обработки запроса

Прохождение клиентского запроса через конвейер HAProxy включает строго детерминированные стадии:

```
Клиентский трафик
  │  (TCP SYN -> ACK)
  ▼
[1. Listener / Frontend]
  │  - Прием TCP соединения
  │  - TLS Handshake & ALPN (если включен SSL)
  │  - PROXY Protocol parsing (если accept-proxy)
  ▼
[2. Frontend Rules]
  │  - Заполнение Stick Table (http-request track-sc0)
  │  - Проверка Rate Limiting и фильтрация (http-request deny)
  │  - Модификация заголовков (http-request set-header)
  ▼
[3. Routing (Выбор Backend)]
  │  - Оценка правил use_backend по ACL
  │  - Назначение default_backend при отсутствии совпадений
  ▼
[4. Backend Selection & Load Balancing]
  │  - Проверка состояния серверов (UP/DOWN по health check)
  │  - Вычисление целевого сервера по алгоритму балансировки
  │  - Повторное использование TCP-пула (http-reuse)
  ▼
[5. Forwarding & Response]
  │  - Передача запроса на сервер бэкенда
  │  - Чтение и парсинг HTTP-ответа
  │  - Модификация заголовков ответа (http-response set-header)
  ▼
Возврат ответа клиенту -> Запись события в Syslog (%ts, тайминги)
```

### Алгоритмы балансировки

Выбор алгоритма распределения нагрузки определяется директивой `balance` в секциях `backend` или `listen`:

| Алгоритм | Принцип распределения | Состояние (State) | Рекомендуемое применение |
| :--- | :--- | :--- | :--- |
| **`roundrobin`** | Циклический опрос серверов с учетом их относительных весов. | Динамический (допускает плавное изменение весов на лету через сокет) | Stateless веб-сервисы, REST API с предсказуемым временем ответа. |
| **`leastconn`** | Направление запроса серверу с минимальным количеством текущих активных соединений. | Динамический | Длительные TCP-сессии: WebSocket, пулы подключений к СУБД, ресурсоемкие HTTP-запросы. |
| **`source`** | Хеширование IP-адреса клиента для привязки к конкретному бэкенду. | Статический или консистентный (`hash-type consistent`) | Простая фиксация клиентских сессий без использования HTTP-кук (например, для L4/TCP). |
| **`uri`** | Хеширование пути HTTP-запроса (левой части URI до знака вопроса). | Консистентный | Кэширующие прокси (Varnish, Squid), медиа-хранилища (гарантирует попадание в кэш одного узла). |
| **`url_param`** | Хеширование значения определенного GET/POST параметра в строке запроса. | Консистентный | Маршрутизация сессий пользователей по идентификатору `user_id` или `session_id`. |
| **`hdr(<name>)`** | Хеширование значения указанного HTTP-заголовка. | Консистентный | A/B-тестирование, канареечные релизы по заголовку версии (`X-App-Version`), мобильные клиенты. |
| **`first`** | Заполнение первого доступного сервера до лимита `maxconn`, затем переключение на следующий. | Статический | Экономия ресурсов виртуализации, автомасштабирование (упрощает усыпление неиспользуемых нод). |
| **`random`** | Псевдослучайный выбор сервера с поправкой на веса. | Динамический | Большие пулы серверов (сотни узлов), распределение микросервисного трафика. |

### Механизмы проверок доступности (Health Checks)

1. **L4 Проверки:**
   - Базовая проверка установления TCP-сокета (`check`). Если хост сбрасывает соединение (`RST`) или не отвечает до истечения `timeout check`, сервер помечается сбойным.
2. **L7 HTTP Проверки:**
   - Директива `option httpchk` или блок `http-check`:
     ```haproxy
     option httpchk
     http-check send meth GET uri /healthz ver HTTP/1.1 hdr Host srv.local
     http-check expect status 200
     ```
3. **Каскадное отключение и плавный ввод (Graceful Behavior):**
   - `on-marked-down shutdown-sessions` — немедленно прерывает существующие клиентские TCP-соединения к серверу при фиксации его падения, предотвращая зависание запросов.
   - `on-marked-up slowstart 60s` — при восстановлении сервера трафик на него подается постепенно в течение 60 секунд, предотвращая перегрузку «холодного» приложения (прогрев JIT, пул соединений СУБД).

### Отказоустойчивость и кластеризация (HA)

В production-инфраструктурах HAProxy разворачивается парами на независимых bare-metal серверах под управлением **Keepalived** с плавающим виртуальным IP-адресом (VIP):

```
                        [ Входящий сетевой трафик ]
                                    │
                         VIP: 192.168.1.100 (VRRP)
                                    │
              ┌─────────────────────┴─────────────────────┐
              ▼                                           ▼
      ┌───────────────┐                           ┌───────────────┐
      │ HAProxy Node1 │◄═══════ Peers Sync ══════►│ HAProxy Node2 │
      │  (MASTER)     │   (Stick Tables / TCP)    │  (BACKUP)     │
      └───────┬───────┘                           └───────┬───────┘
              │                                           │
              └─────────────────────┬─────────────────────┘
                                    ▼
                          [ Серверы приложений ]
```

- **Keepalived:** Отслеживает доступность локального процесса HAProxy через health-check скрипт (`vrrp_script`). В случае падения процесса на мастере VIP мгновенно мигрирует на резервный узел без разрыва сети.
- **Peers-синхронизация:** Секция `peers` синхронизирует содержимое Stick Tables между балансировщиками по протоколу TCP. Если клиент исчерпал лимит запросов на узле Node1, узел Node2 сразу знает об этом при переключении VIP.

### Анализ уязвимостей и безопасность (CVE)

Как ключевой рубеж инфраструктуры, балансировщик подвержен атакам на сетевой стек и парсеры протоколов:

- **HTTP Request Smuggling (десинхронизация запросов):** Возникает при несогласованности разбора заголовков `Content-Length` и `Transfer-Encoding: chunked`. В HAProxy встроен строгий парсер HTX (Native HTTP Representation), который жестко отсекает некорректные и двоякие заголовки.
- **CVE-2023-45539:** Уязвимость обхода списков контроля доступа (ACL) из-за некорректной нормализации путей с символом `#` перед query string. Закрыта в актуальных версиях.
- **CVE-2026-55203:** Переполнение буфера при разборе FastCGI-ответов от нестандартных бэкендов в версиях до 3.4.0.
- **CVE-2026-55204:** Неконтролируемое потребление памяти в таблице динамического сжатия заголовков HPACK (HTTP/2). Устранено в обновлении 3.4.1.

Рекомендуется всегда использовать последние минорные релизы веток LTS (3.0.x, 3.2.x, 3.4.x) и запрещать устаревшие протоколы TLS ниже 1.2.

---

## Установка и базовая конфигурация

### Установка на Linux

#### Debian / Ubuntu

Рекомендуется использовать официальный репозиторий проекта HAProxy (Debian package repository от Vincent Bernat) для получения актуальных сборок LTS:

```bash
apt update && apt install -y curl gnupg2 ca-certificates lsb-release
# → Пакеты предварительных зависимостей установлены

curl -fsSL https://haproxy.debian.net/bernat.gpg | gpg --dearmor -o /usr/share/keyrings/haproxy.gpg
# → Ключ репозитория добавлен

echo "deb [signed-by=/usr/share/keyrings/haproxy.gpg] http://haproxy.debian.net $(lsb_release -cs)-backports-3.4 main" > /etc/apt/sources.list.d/haproxy.list
apt update && apt install -y haproxy=3.4.*
# → HAProxy 3.4 установлен

haproxy -vv | head -n 3
# → HAProxy version 3.4.0-1~bpo12+1 2026/06/03 - https://haproxy.org/
# → Status: long-term supported branch - > support until Q2 2031.
# → Known bugs: http://www.haproxy.org/bugs/bugs-3.4.0.html
```

#### RHEL / AlmaLinux / Rocky Linux

```bash
dnf install -y epel-release
dnf install -y haproxy socat
# → Пакет haproxy установлен

systemctl enable haproxy
# → Created symlink /etc/systemd/system/multi-user.target.wants/haproxy.service
```

#### On-Premise Docker контейнер

Для bare-metal узлов, использующих контейнеризацию, критически важно предоставлять хостовую сеть (`--net=host`) для максимальной производительности:

```bash
docker run -d \
  --name haproxy \
  --restart always \
  --net=host \
  --cap-add=NET_ADMIN \
  -v /etc/haproxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro \
  -v /var/run/haproxy:/var/run/haproxy:rw \
  haproxy:3.4-alpine
# → d1e5927b8cf6b489d81d4a66e481bfd2371295b3fef37cb019ad74e5a9526781
```

### Структура конфигурационного файла

Файл `/etc/haproxy/haproxy.cfg` разделен на логические блоки:

```haproxy
# 1. Глобальные системные параметры процесса
global
    log /dev/log local0 info
    log /dev/log local1 notice
    chroot /var/lib/haproxy
    user haproxy
    group haproxy
    daemon
    master-worker

    # Производительность и ресурсы
    maxconn 100000
    nbthread 4
    cpu-map auto:1/1-4 0-3

    # Интерфейс управления
    stats socket /var/run/haproxy/admin.sock mode 660 level admin expose-fd listeners
    stats timeout 30s

    # Безопасность SSL/TLS
    ssl-default-bind-ciphersuites TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256
    ssl-default-bind-options ssl-min-ver TLSv1.2 no-tls-tickets

# 2. Значения по умолчанию для frontend и backend
defaults
    log     global
    mode    http
    option  httplog
    option  dontlognull
    option  http-server-close
    option  redispatch
    retries 3

    # Оптимальные таймауты
    timeout connect        5s
    timeout client         30s
    timeout server         30s
    timeout http-request   10s
    timeout http-keep-alive 15s
    timeout queue          30s
    timeout check          5s
    maxconn                50000
```

---

## Практические сценарии

### 1. Балансировка HTTP/HTTPS с терминацией TLS 1.3 и ALPN

Полноценная конфигурация фронтенда с автоматическим перенаправлением с HTTP на HTTPS, поддержкой протоколов HTTP/2 и HTTP/1.1, а также пробросом клиентских заголовков.

```haproxy
frontend fe_web_secure
    bind *:80
    bind *:443 ssl crt /etc/haproxy/certs/site.pem alpn h2,http/1.1
    mode http

    # Принудительный редирект с HTTP на HTTPS
    http-request redirect scheme https code 301 unless { ssl_fc }

    # Безопасные заголовки
    http-request set-header X-Forwarded-Proto https if { ssl_fc }
    http-request set-header X-Forwarded-Port %[dst_port]
    http-request add-header X-Real-IP %[src]

    # Маршрутизация по хостам
    acl host_api hdr(host) -i api.example.local
    use_backend be_api if host_api

    default_backend be_web

backend be_web
    mode http
    balance roundrobin
    option forwardfor
    cookie WEBSRV insert indirect nocache
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions

    server web01 192.168.10.11:8080 check cookie s1 maxconn 250
    server web02 192.168.10.12:8080 check cookie s2 maxconn 250
    server web_backup 192.168.10.13:8080 check backup

backend be_api
    mode http
    balance leastconn
    option forwardfor
    server api01 192.168.10.21:8000 check maxconn 500
    server api02 192.168.10.22:8000 check maxconn 500
```

### 2. Поддержка HTTP/3 (QUIC) на Bare-Metal

HAProxy 3.0+ поддерживает HTTP/3 поверх UDP с использованием библиотеки OpenSSL 3.2+ или QuicTLS. Требуется объявление двух портов: стандартного TCP и UDP.

```haproxy
frontend fe_http3
    # Слушатель TCP (HTTP/1.1, HTTP/2)
    bind *:443 ssl crt /etc/haproxy/certs/site.pem alpn h2,http/1.1
    # Слушатель UDP (HTTP/3)
    bind quic4@*:443 ssl crt /etc/haproxy/certs/site.pem alpn h3

    mode http

    # Анонсирование поддержки HTTP/3 клиентам через заголовок Alt-Svc
    http-after-response add-header Alt-Svc 'h3=":443"; ma=86400; persist=1'

    default_backend be_web
```

> [!IMPORTANT]
> При использовании QUIC необходимо открыть UDP-порт 443 на внешнем межсетевом экране (iptables/nftables) и корректно настроить размер буферов UDP ядра (`net.core.rmem_max`, `net.core.wmem_max`).

### 3. L4 Passthrough и маршрутизация по SNI

Проброс зашифрованного TLS-трафика без расшифровки на балансировщике. Роутинг осуществляется на основе имени хоста из поля Server Name Indication (SNI) пакета ClientHello.

```haproxy
frontend fe_tls_passthrough
    bind *:443
    mode tcp
    tcp-request inspect-delay 5s
    tcp-request content accept if { req_ssl_hello_type 1 }

    # Извлечение SNI
    acl is_portal req_ssl_sni -i portal.example.local
    acl is_mail   req_ssl_sni -i mail.example.local

    use_backend be_portal_tls if is_portal
    use_backend be_mail_tls   if is_mail
    default_backend be_default_tls

backend be_portal_tls
    mode tcp
    balance roundrobin
    server portal01 10.10.1.10:443 check check-ssl verify none
    server portal02 10.10.1.11:443 check check-ssl verify none

backend be_mail_tls
    mode tcp
    balance leastconn
    server mail01 10.10.2.10:443 check
```

### 4. Балансировка Kubernetes Control Plane (`kube-apiserver`)

Отказоустойчивая балансировка запросов к API-серверам bare-metal кластера Kubernetes с глубокой проверкой работоспособности эндпоинта `/readyz`.

```haproxy
frontend fe_k8s_api
    bind 192.168.1.100:6443
    mode tcp
    option tcplog
    default_backend be_k8s_api

backend be_k8s_api
    mode tcp
    balance roundrobin
    option httpchk GET /readyz HTTP/1.1\r\nHost:\ cluster.local
    http-check expect status 200
    default-server inter 2s fall 2 rise 2 check check-ssl verify none

    server master01 192.168.1.11:6443
    server master02 192.168.1.12:6443
    server master03 192.168.1.13:6443
```

### 5. Высокодоступный пул PostgreSQL с Patroni

Маршрутизация трафика базы данных на основе ответов REST API демона Patroni. Мастер принимает запись и чтение, реплики обслуживают только чтение.

```haproxy
# Пул для записи (Read/Write - Primary)
listen pg_cluster_write
    bind 192.168.10.100:5432
    mode tcp
    balance roundrobin
    option httpchk GET /primary
    http-check expect status 200
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions

    server pg01 192.168.10.31:5432 maxconn 200 check port 8008
    server pg02 192.168.10.32:5432 maxconn 200 check port 8008
    server pg03 192.168.10.33:5432 maxconn 200 check port 8008

# Пул для аналитики и чтения (Read-Only - Replicas)
listen pg_cluster_read
    bind 192.168.10.100:5433
    mode tcp
    balance roundrobin
    option httpchk GET /replica
    http-check expect status 200
    default-server inter 3s fall 3 rise 2

    server pg01 192.168.10.31:5432 check port 8008
    server pg02 192.168.10.32:5432 check port 8008
    server pg03 192.168.10.33:5432 check port 8008
```

### 6. Оптимизация пулов соединений (`http-reuse`)

Повторное использование соединений между HAProxy и приложениями снижает утилизацию CPU и нагрузку на сокеты сервера.

```haproxy
backend be_microservice
    mode http
    balance roundrobin

    # Режимы http-reuse:
    # - never: соединение закрывается после каждого запроса
    # - safe: повторное использование только для идемпотентных запросов или до отправки данных
    # - aggressive: немедленное использование любого освободившегося сокета пула
    # - always: постоянный пул
    http-reuse safe
    pool-max-conn 500

    server app01 10.0.1.10:8080 check maxconn 100
    server app02 10.0.1.11:8080 check maxconn 100
```

### 7. Защита от DDoS и Brute-Force через Stick Tables

Ограничение частоты запросов (Rate Limiting) по IP-адресу клиента на скользящем 10-секундном интервале с автоматическим возвратом кода HTTP 429:

```haproxy
frontend fe_public_api
    bind *:80
    mode http

    # Инициализация таблицы в оперативной памяти
    stick-table type ip size 500k expire 30s store http_req_rate(10s),conn_cur,conn_rate(3s)

    # Привязка входящего IP к счетчику sc0
    http-request track-sc0 src

    # Блокировка: более 100 запросов за 10 секунд
    acl is_rate_exceeded sc_http_req_rate(0) gt 100
    # Блокировка: более 30 параллельных TCP соединений с одного IP
    acl is_conn_cur_high sc_conn_cur(0) gt 30

    # Возврат кастомной ошибки 429 без проксирования к бэкенду
    http-request deny deny_status 429 default-errorfiles if is_rate_exceeded
    http-request deny deny_status 429 default-errorfiles if is_conn_cur_high

    default_backend be_api
```

### 8. Интеграция с PROXY Protocol v2

Использование PROXY Protocol позволяет передавать исходный IP клиента сквозь цепочки прокси-серверов.

```haproxy
# Прием трафика от вышестоящего L4 балансировщика
frontend fe_internal_gateway
    bind *:8443 accept-proxy
    mode http
    default_backend be_backend_with_proxy_protocol

# Отправка трафика на нижестоящий Nginx/Web-сервер с внедрением заголовка v2
backend be_backend_with_proxy_protocol
    mode http
    balance roundrobin
    server web01 10.0.2.10:80 check send-proxy-v2
    server web02 10.0.2.11:80 check send-proxy-v2
```

### 9. Балансировка WebSocket и gRPC

```haproxy
# WebSocket балансировка с расширенным таймаутом туннелирования
frontend fe_ws
    bind *:8080
    mode http
    timeout tunnel 1h
    acl is_websocket hdr(Upgrade) -i WebSocket
    use_backend be_ws if is_websocket
    default_backend be_web

backend be_ws
    mode http
    balance source
    server ws01 10.0.3.10:8080 check
    server ws02 10.0.3.11:8080 check

# gRPC балансировка (требует HTTP/2)
frontend fe_grpc
    bind *:50051 proto h2
    mode http
    timeout connect 5s
    timeout client  300s
    timeout server  300s
    default_backend be_grpc

backend be_grpc
    mode http
    balance roundrobin
    server grpc01 10.0.4.10:50051 proto h2 check
    server grpc02 10.0.4.11:50051 proto h2 check
```

### 10. Высокая доступность HAProxy через Keepalived

Конфигурация `/etc/keepalived/keepalived.conf` для создания отказоустойчивой пары балансировщиков:

```ini
vrrp_script check_haproxy {
    script "/usr/bin/killall -0 haproxy"
    interval 2
    weight 2
}

vrrp_instance VI_STATIC {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass Secr3tP@ss
    }

    virtual_ipaddress {
        192.168.1.100/24 dev eth0
    }

    track_script {
        check_haproxy
    }
}
```

---

## Операции и команды

### Управление службой через systemd

```bash
# Проверка текущего статуса
systemctl status haproxy
# → ● haproxy.service - HAProxy Load Balancer
# →    Loaded: loaded (/lib/systemd/system/haproxy.service; enabled; vendor preset: enabled)
# →    Active: active (running) since Wed 2026-10-15 08:30:12 MSK; 1h ago

# Бесшовная перезагрузка конфигурации (Zero-Downtime Reload)
systemctl reload haproxy
# → [OK] Мастер-процесс перечитал конфигурацию и запустил нового воркера

# Полный перезапуск с разрывом текущих соединений (применяется при смене системных лимитов)
systemctl restart haproxy
# → [OK] Процесс перезапущен
```

### Валидация и диагностика конфигурации

Всегда выполняйте проверку синтаксиса перед применением изменений:

```bash
# Валидация конфигурационного файла
haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Детальная проверка с выводом предупреждений и парсинга секций
haproxy -c -V -f /etc/haproxy/haproxy.cfg
# → Warnings were found during configuration processing: 0
# → Configuration file is valid
```

### Управление через Runtime API (UNIX Domain Socket)

Для взаимодействия с сокетом используется утилита `socat`:

```bash
# Просмотр общей информации о процессе (версия, аптайм, утилизация пулов)
echo "show info" | socat stdio /var/run/haproxy/admin.sock | head -n 6
# → Name: HAProxy
# → Version: 3.4.0
# → Release_date: 2026/06/03
# → Uptime_sec: 4230
# → Process_num: 1
# → Pid: 12450

# Получение CSV-статистики всех серверов и бэкендов
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | head -n 2
# → # pxname,svname,qcur,qmax,scur,smax,slim,stot,bin,bout,dreq,dresp,ereq,econ,eresp,wretr,wredis,status...
# → be_web,web01,0,2,14,250,250,15420,12504820,98402104,0,0,0,0,2,0,0,UP...

# Вывод сервера из балансировки для обслуживания (Drain - новые соединения не идут, старые дорабатывают)
echo "set server be_web/web01 state drain" | socat stdio /var/run/haproxy/admin.sock
# → [OK]

# Полный перевод сервера в статус обслуживания (Maintenance)
echo "set server be_web/web01 state maint" | socat stdio /var/run/haproxy/admin.sock
# → [OK]

# Возврат сервера в активную ротацию
echo "set server be_web/web01 state ready" | socat stdio /var/run/haproxy/admin.sock
# → [OK]

# Динамическое изменение веса сервера (например, 10% для канареечного релиза)
echo "set server be_web/web01 weight 10" | socat stdio /var/run/haproxy/admin.sock
# → [OK]

# Просмотр содержимого Stick Table (IP-адреса и значения счетчиков)
echo "show table fe_public_api" | socat stdio /var/run/haproxy/admin.sock
# → # table: fe_public_api, type: ip, size:512000, used:2
# → 0x7f8a94002340: key=192.168.1.50 use=0 exp=24250 http_req_rate(10000)=4 conn_cur=1 conn_rate(3000)=1
# → 0x7f8a940034a0: key=10.0.0.12 use=0 exp=28100 http_req_rate(10000)=122 conn_cur=5 conn_rate(3000)=15

# Принудительная очистка записи в Stick Table для заблокированного IP
echo "clear table fe_public_api key 10.0.0.12" | socat stdio /var/run/haproxy/admin.sock
# → [OK]

# Просмотр последних зафиксированных сетевых ошибок
echo "show errors" | socat stdio /var/run/haproxy/admin.sock | head -n 10
# → Total events captured on [15/Oct/2026:08:35:10]: 0
```

### Автоматизация Rolling Deploy (Скрипт Graceful Draining)

Production-скрипт инженера SRE для поочередного бесшовного обновления нод кластера:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKEND="be_web"
SERVERS=("web01" "web02" "web03")
SOCK="/var/run/haproxy/admin.sock"
DRAIN_TIMEOUT=30

for SRV in "${SERVERS[@]}"; do
    echo "=== [1/4] Перевод $SRV в режим DRAIN ==="
    echo "set server ${BACKEND}/${SRV} state drain" | socat stdio "$SOCK"

    echo "=== [2/4] Ожидание завершения активных соединений ($DRAIN_TIMEOUT сек) ==="
    sleep "$DRAIN_TIMEOUT"

    echo "=== [3/4] Перевод $SRV в MAINT для деплоя ==="
    echo "set server ${BACKEND}/${SRV} state maint" | socat stdio "$SOCK"

    # Выполнение команд деплоя (например, перезапуск локального демона приложения)
    ssh "app@$SRV" "systemctl restart my-web-app"

    echo "=== [4/4] Возврат $SRV в ротацию (READY) ==="
    echo "set server ${BACKEND}/${SRV} state ready" | socat stdio "$SOCK"
    sleep 5
done
echo "Rolling deployment успешно завершен!"
```

---

## Устранение неисправностей

### Диагностическая матрица проблем

| Симптом | Вероятная причина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Служба не стартует при reload** | Ошибка синтаксиса или конфликт портов (`bind`) | `haproxy -c -f /etc/haproxy/haproxy.cfg` и `journalctl -u haproxy -e` | Исправить опечатку в директивах; проверить занятость портов через `ss -tulpn`. |
| **Сервер бэкенда переходит в DOWN** | Сбой health check, таймаут или неверный HTTP-код | `echo "show stat" \| socat stdio /run/haproxy/admin.sock` | Проверить логи бэкенда; проверить доступность URL проверки вручную: `curl -iv http://backend:port/healthz`. |
| **Ошибки HTTP 502 Bad Gateway** | Бэкенд сбросил TCP-соединение или вернул некорректный ответ | Анализ поля `%ts` в syslog (флаги `sH`, `sC`, `sR`) | Увеличить `timeout server`; проверить лимит соединений бэкенда (max clients / pool exhausted). |
| **Ошибки HTTP 503 Service Unavailable** | Все серверы в статусе DOWN или переполнена очередь `queue` | Флаг `%ts` = `sQ` или `SC` | Проверить `maxconn` бэкенда; проверить доступность бэкендов; настроить backup-сервер. |
| **Ошибки HTTP 504 Gateway Timeout** | Время ответа бэкенда превысило `timeout server` | Флаг `%ts` = `sT` | Оптимизировать медленные запросы в приложении или увеличить `timeout server` для конкретного пути. |
| **Исчерпание портов (EADDRNOTAVAIL)** | Слишком много коротких соединений к бэкенду без Keep-Alive | `dmesg \| grep "TCP: too many orphan sockets"` | Включить `http-reuse safe`, активировать `net.ipv4.tcp_tw_reuse = 1` в sysctl. |

### Расшифровка флагов завершения сессий (%ts)

В стандартном формате логов HAProxy поле `%ts` (Termination Flags) состоит из двух символов и является главным инструментом расследования инцидентов SRE-инженером:

```
Первый символ: Какая сторона инициировала закрытие сессии
Второй символ: В каком состоянии находилась сессия в момент завершения
```

```
           ┌── Символ 1: Кто закрыл сессию (s = server, c = client, C = connection error, P = proxy)
           │┌─ Символ 2: В каком состоянии (H = headers, D = data, Q = queue, R = response)
           ▼▼
   ... "GET /api/v1/data" 502 432 "sH" ...
```

1. **`sH` (Server Header Timeout/Error):**
   - **Значение:** Сервер бэкенда закрыл соединение или произошел таймаут (`timeout server`) во время ожидания HTTP-заголовков ответа.
   - **Решение:** Проверить падения приложения (OOM Killer, segmentation fault), увеличить `timeout server`.
2. **`sC` (Server Connection Closed):**
   - **Значение:** Сервер разорвал соединение во время передачи тела ответа.
   - **Решение:** Проверить логи приложения на предмет аварийного завершения рабочего потока.
3. **`sQ` (Server Queue Timeout):**
   - **Значение:** Запрос простоял в локальной очереди бэкенда дольше `timeout queue`, так как все серверы исчерпали свои лимиты `maxconn`.
   - **Решение:** Добавить серверы в пул, оптимизировать время обработки запросов бэкендом, увеличить `maxconn` при наличии запаса ресурсов.
4. **`cD` (Client Data Closed):**
   - **Значение:** Клиент оборвал соединение (например, нажал «Отмена» в браузере или таймаут HTTP-клиента) во время передачи данных.
   - **Решение:** Нормальное явление для публичного трафика; если всплеск массовый — проверить сетевую задержку на пути к клиентам.
5. **`PR` (Proxy Rejected):**
   - **Значение:** Запрос заблокирован самим HAProxy на основе правил ACL (`http-request deny`).
   - **Решение:** Проверить соответствие запроса правилам безопасности и лимитам Rate Limiting.
6. **`SC` (Server Connection Error):**
   - **Значение:** HAProxy не смог установить TCP-соединение с бэкендом (Connection Refused).
   - **Решение:** Приложение не слушает порт или перегружена очередь сокета `backlog`.

---

## Лучшие практики

### Тюнинг ядра Linux (sysctl)

Создайте конфигурационный файл `/etc/sysctl.d/99-haproxy.conf`:

```ini
# Разрешение биндинга на IP-адрес, которого еще нет на интерфейсе (критично для Keepalived VIP)
net.ipv4.ip_nonlocal_bind = 1

# Максимальный размер очереди не принятых слушающим сокетом соединений
net.core.somaxconn = 65535

# Максимальное количество открытых файловых дескрипторов в системе
fs.file-max = 2097152

# Разрешение повторного использования сокетов в состоянии TIME_WAIT для исходящих TCP-соединений
net.ipv4.tcp_tw_reuse = 1

# Очередь полуоткрытых соединений (защита от SYN Flood)
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_syncookies = 1

# Диапазон локальных динамических портов для исходящих подключений к бэкендам
net.ipv4.ip_local_port_range = 1024 65535

# Буферы сетевых сокетов для обеспечения высокой пропускной способности (10G/40G)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

Применение изменений без перезагрузки:

```bash
sysctl --system
# → * Applying /etc/sysctl.d/99-haproxy.conf ...
# → net.ipv4.ip_nonlocal_bind = 1
# → net.core.somaxconn = 65535
# → ...
```

### Системные лимиты (systemd Limits)

Для обслуживания сотен тысяч одновременных подключений процессу HAProxy требуются увеличенные системные лимиты. Создайте drop-in оверлей `/etc/systemd/system/haproxy.service.d/limits.conf`:

```ini
[Service]
LimitNOFILE=1048576
LimitNPROC=524288
LimitMEMLOCK=infinity
```

Применение лимитов:

```bash
systemctl daemon-reload && systemctl restart haproxy
# → [OK] Новые лимиты дескрипторов применены
```

### Настройка таймаутов (SRE Guidelines)

| Директива | Рекомендуемое значение | Обоснование |
| :--- | :--- | :--- |
| `timeout connect` | `3s – 5s` | Должен быть коротким. Если локальный бэкенд не принял TCP SYN за 5 секунд, узел неисправен. |
| `timeout client` | `30s – 60s` | Время ожидания очередного пакета от клиента. Слишком большие значения ведут к утечке файловых дескрипторов из-за медленных клиентов. |
| `timeout server` | `30s – 60s` | Должен соответствовать максимальному допустимому SLA времени генерации ответа приложением. |
| `timeout http-request` | `5s – 10s` | Защита от Slowloris-атак (медленная отправка заголовков клиентом). |
| `timeout http-keep-alive` | `10s – 15s` | Поддержание постоянного соединения с клиентом в открытом состоянии для повторных запросов. |
| `timeout queue` | `15s – 30s` | Время ожидания в очереди бэкенда при переполнении `maxconn`. Защищает от лавинообразного роста задержек. |
| `timeout tunnel` | `1h – 24h` | Время простоя двунаправленных сессий WebSocket или gRPC. |
| `timeout check` | `3s – 5s` | Таймаут проверки здоровья. Обязан быть меньше интервала `inter`. |

### Hardening и безопасность

1. **Изоляция файловой системы:** Всегда используйте директиву `chroot /var/lib/haproxy`.
2. **Сброс привилегий:** Обязательно указывайте `user haproxy` и `group haproxy`. Ни один рабочий поток не должен выполняться с правами суперпользователя.
3. **Безопасность сокета:** Права на UNIX-сокет должны быть ограничены (`mode 660 level admin`), группа владельца — доверенные администраторы (`haproxy` или `wheel`).
4. **Профили шифрования:** Запрещайте устаревшие протоколы SSLv3, TLS 1.0, TLS 1.1 и небезопасные шифры CBC/RC4/3DES:
   ```haproxy
   ssl-default-bind-options ssl-min-ver TLSv1.2 no-tls-tickets
   ```
5. **Защита панели статистики:** Никогда не публикуйте `/stats` и `/metrics` в открытый интернет без аутентификации:
   ```haproxy
   listen stats
       bind 127.0.0.1:8405
       mode http
       stats enable
       stats uri /stats
       stats auth admin:SuperSecurePassword123
       http-request use-service prometheus-exporter if { path /metrics }
   ```

---

## Дополнительная информация

### Сравнение балансировщиков: HAProxy vs Nginx vs Envoy vs Traefik

| Критерий | HAProxy | Nginx (OSS) | Envoy Proxy | Traefik |
| :--- | :--- | :--- | :--- | :--- |
| **Основная специализация** | Выделенный высокопроизводительный балансировщик (L4/L7) | Универсальный веб-сервер, обратный прокси, кэш | Сервисный прокси для Service Mesh (Sidecar) | Cloud-Native Edge Router для микросервисов |
| **Архитектура** | Однопроцессная/многопоточная (Event-loop + `nbthread`) | Многопроцессная (Master-Worker, процесс на ядро) | Многопоточная на C++ (Event-driven, `libevent`) | Многопоточная на Go (Goroutines) |
| **Health Checks** | Глубокие активные проверки (L4/L7/Agent/Expect) | Только пассивные проверки (активные — в Nginx Plus) | Активные и пассивные (Outlier Detection) | Базовые активные проверки |
| **Управление на лету** | Нативный Runtime API (сокет, изменение весов, drain) | Требует Nginx Plus (в OSS — только reload) | Динамический xDS API (gRPC) | Динамическое чтение провайдеров (Docker, K8s) |
| **Расход ресурсов** | Минимальный footprint CPU и RAM | Низкий | Средний | Средний (overhead рантайма Go GC) |
| **Сложные алгоритмы** | Широчайший выбор (leastconn, uri, hdr, stick) | Ограниченный набор (round-robin, ip_hash, random) | Round robin, Maglev, Ring Hash, Least Request | Round robin, WRR |

### См. также

- **[Мониторинг HAProxy](./Concepts/haproxy_monitoring.md)** — полное руководство по PROMEX, дашбордам Grafana, алертам Alertmanager и парсингу расширенных логов (%ts, тайминги).
- **[Балансировка нагрузки между локациями с HAProxy](./Concepts/haproxy_multi_location_load_balancing.md)** — синхронизация Stick Tables через Peers, защита от каскадного перегруза (Probabilistic Shedding) и BGP Anycast.
- **[Keepalived: Обзор и настройка](../Networking/ServicesAndTools/keepalived_overview.md)** — организация отказоустойчивого плавающего IP-адреса (VRRP VIP) для HAProxy.
- **[Отказоустойчивость PostgreSQL](../Databases/PostgreSQL/Concepts/high_availability.md)** — архитектура высокой доступности СУБД с Patroni и балансировкой через HAProxy.
- **[Полезные ссылки для веб-серверов](./webservers_useful_links.md)** — официальные спецификации, бенчмарки и инструменты аудита конфигураций.
