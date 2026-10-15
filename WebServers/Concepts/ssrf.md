# SSRF: Server-Side Request Forgery для веб-серверов

**Актуально для:** Nginx 1.26+, Angie 1.8+, HAProxy 3.0+, Squid 6.x, Linux kernel 6.x

## Определения

- **SSRF (Server-Side Request Forgery)** — архитектурная уязвимость веб-приложений и веб-серверов, при которой атакующий манипулирует параметрами запроса так, чтобы инициировать сетевое соединение от имени уязвимого сервера к непреднамеренному внутреннему или стороннему сетевому ресурсу.
- **Blind SSRF (Вслепую / Out-of-Band SSRF / OAST)** — тип SSRF-атаки, при котором веб-сервер отправляет запрос к целевому ресурсу, но не передает тело или заголовки ответа обратно клиенту. Успешность атаки фиксируется через сторонние каналы (DNS-запросы к подконтрольному серверу, задержки ответа, сетевой мониторинг).
- **DNS Rebinding (TOCTOU в DNS)** — метод обхода валидации IP-адресов, основанный на race condition между моментом проверки имени (Time-of-Check) и моментом отправки реального HTTP-запроса (Time-of-Use). Злоумышленник настраивает авторитативный DNS-сервер так, чтобы первый запрос возвращал легитимный публичный IP с минимальным TTL (0 или 1 секунда), а повторный запрос от того же процесса — внутренний адрес (например, `127.0.0.1`).
- **Alternate IP Encodings (Нестандартные форматы записи IP)** — эквивалентные строковые представления IPv4/IPv6-адресов, которые корректно интерпретируются функциями системного резолвинга (`inet_aton`, `getaddrinfo`), но часто не распознаются наивными регулярными выражениями: целочисленный (Dword), восьмеричный (Octal), шестнадцатеричный (Hex), сокращенный (`127.1`) и IPv4-mapped IPv6 (`::ffff:127.0.0.1`).
- **URL Parser Differential (Рассинхронизация парсеров URL)** — расхождение в разборе компонентов URI (схема, authority, порт, путь) между граничным обратным прокси (Reverse Proxy) и внутренним бэкендом из-за различий в обработке спецсимволов (`@`, `#`, `?`, `\`, двойной слэш).
- **Egress Filtering (Фильтрация исходящего периметра)** — комплекс правил межсетевого экрана (L3/L4 `nftables`/`iptables`) и шлюзов прикладного уровня (L7 Forward Proxy), блокирующий несанкционированные исходящие соединения от серверов демилитаризованной зоны (DMZ) к внутренним сегментам сети и узлам управления.
- **Systemd Socket / Cgroup Sandboxing** — изоляция сетевого контекста процессов веб-сервера на уровне ядра Linux средствами systemd (`IPAddressDeny`, `IPAddressAllow`), запрещающая worker-процессам открывать сокеты к запрещенным подсетям независимо от конфигурации приложения.
- **Internal Management Plane (Плоскость локального управления)** — служебные сетевые интерфейсы и службы инфраструктуры локального дата-центра (IPMI/BMC, Docker socket over HTTP, Kubelet, etcd, Consul, Vault, порты метрик Prometheus, локальные СУБД и кэши), не защищенные строгой аутентификацией и рассчитанные на изоляцию сетевым периметром.

---

## Архитектура и принципы работы

### Механика возникновения SSRF на веб-сервере

В контексте системного администрирования и SRE атака SSRF на уровне веб-сервера возникает в двух ключевых архитектурных паттернах:

```text
[ Клиент / Атакующий ]
         │
         │ 1. HTTP-запрос с целевым URL: ?target=http://127.0.0.1:2375/version
         ▼
[ Граничный веб-сервер / Reverse Proxy (Nginx / HAProxy) ]
   ├── Уязвимость: proxy_pass к переменной без валидации ($arg_target)
   ├── Уязвимость: следование HTTP-редиректам (301/302) во внутреннюю сеть
   └── Уязвимость: конфигурация Open Proxy
         │
         │ 2. Сервер самостоятельно открывает TCP-сокет
         ├──────────────────────────────────────────────┬──────────────────────────────┐
         ▼                                              ▼                              ▼
[ Loopback (127.0.0.1) ]                      [ Интранет (RFC 1918) ]       [ Управляющий сегмент ]
  ├── Docker API (2375)                         ├── Kubelet (10250/10255)     ├── IPMI / iLO / BMC
  ├── Redis / Memcached (6379/11211)            ├── etcd кластер (2379)       ├── Proxmox / ESXi
  └── Prometheus metrics (9090/9100)            └── Consul / Vault (8500/8200)└── Маршрутизаторы
```

1. **Динамический Reverse Proxy:** Использование пользовательских данных в директивах маршрутизации (например, `proxy_pass $arg_target;` в Nginx или `use_backend` на основе параметров в HAProxy) без привязки к жесткому белому списку разрешенных хостов.
2. **Open Forward Proxy:** Ошибки конфигурации модулей `ngx_http_proxy_module` или Apache `mod_proxy`, превращающие публичный сервер в открытый шлюз, принимающий методы `CONNECT` или абсолютные URI (`GET http://internal-server/ HTTP/1.1`).
3. **Обработка HTTP-редиректов (Redirect Following):** Если веб-сервер или связанный upstream-сервис (генератор PDF, конвертер изображений, парсер вебхуков) настроен автоматически следовать перенаправлениям `301/302/307`, атакующий указывает публичный адрес, возвращающий `Location: http://127.0.0.1:6379/`.
4. **Протокольные инъекции (CRLF / Smuggling):** Внедрение последовательностей `\r\n` в заголовки или пути, позволяющее сформировать произвольные текстовые команды для внутренних сервисов с примитивными протоколами (Redis, Memcached, SMTP).

---

### Каталог внутренних целей в локальной инфраструктуре (On-Premises / Bare-Metal)

В корпоративной инфраструктуре без использования облачных сервисов SSRF направлен на атаку служебных интерфейсов, систем оркестрации, мониторинга и аппаратного управления:

| Сервис / Протокол | Порт по умолчанию | Характер угрозы при SSRF |
| :--- | :--- | :--- |
| **Docker Engine Daemon API** | `TCP 2375` (без TLS) | Полный захват хоста: запуск привилегированного контейнера с монтированием корня хоста (`/`). |
| **Kubernetes Kubelet API** | `TCP 10250`, `10255` | Чтение логов, инспекция подов (`/pods`), выполнение команд в контейнерах через `exec` (на 10250). |
| **etcd Cluster API** | `TCP 2379`, `2380` | Чтение и модификация конфигурации кластера, извлечение секретов, токенов сервисных аккаунтов. |
| **HashiCorp Consul** | `TCP 8500` | Чтение Key-Value хранилища (`/v1/kv/`), манипуляция Service Catalog, удаленное выполнение через Services. |
| **HashiCorp Vault** | `TCP 8200` | Извлечение неинициализированных данных, инспекция состояния распечатывания (`/v1/sys/health`). |
| **Prometheus / Exporters** | `TCP 9090`, `9100`, `9115` | Сбор системных метрик (`node_exporter`), аварийное завершение (`/-/quit`), сброс конфига (`/-/reload`). |
| **Redis (in-memory)** | `TCP 6379` | Чтение данных сессий, перезапись ключей, вызов `CONFIG SET` для записи SSH-ключей или cron-задач. |
| **Memcached** | `TCP 11211` | Извлечение кэша авторизации, отравление данных (Cache Poisoning) через текстовые команды. |
| **Elasticsearch / OpenSearch** | `TCP 9200` | Неавторизованный поиск по внутренним индексам, чтение системных логов, удаление данных. |
| **ClickHouse HTTP Interface** | `TCP 8123` | Выполнение аналитических запросов без пароля по умолчанию (`?query=SHOW+DATABASES`). |
| **IPMI / BMC / iLO / iDRAC Web** | `TCP 80`, `443` | Доступ к интерфейсу аппаратного управления сервером, vKVM, перезагрузка по питанию. |
| **SMTP Relay (локальный)** | `TCP 25` | Отправка фишинговых писем или спама от доверенного локального адреса без авторизации. |

---

### Анатомия обхода фильтров (Bypass Mechanics)

Примитивная фильтрация на базе черных списков (Blacklist) регулярными выражениями легко нейтрализуется знанием архитектуры стека TCP/IP и различий в парсинге URL.

```
       [ Запрос: "http://0177.0.0.1/" ]
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
[ Регулярное выражение ]    [ Системный вызов inet_aton() ]
  Шаблон: ^127\.0\.0\.1$      Интерпретация: Восьмеричный формат
  Результат: ПРОПУЩЕНО        Результат: 127.0.0.1 (Loopback)
                             ▼
                     [ Успешный взлом ]
```

#### 1. Альтернативные форматы IP-адресов

Сетевые библиотеки Linux (`glibc`) поддерживают множественные форматы записи адресов:

- **Восьмеричный (Octal):** Лидирующий ноль переключает парсер в восьмеричную систему.
  - `http://0177.0.0.1/` → `127.0.0.1`
  - `http://017700000001/` → `127.0.0.1` (единое число)
- **Шестнадцатеричный (Hex):** Префикс `0x`.
  - `http://0x7f.0.0.1/` → `127.0.0.1`
  - `http://0x7f000001/` → `127.0.0.1`
- **Целочисленный (Dword / Decimal IP):** IP-адрес пересчитывается по формуле `(A * 256^3) + (B * 256^2) + (C * 256) + D`.
  - `http://2130706433/` → `127.0.0.1`
  - `http://2886729729/` → `172.16.0.1`
- **Сокращенная запись (Class B / Class A shorthand):**
  - `http://127.1/` → `127.0.0.1`
  - `http://10.1/` → `10.0.0.1`
- **Нулевой адрес (Zero address):** В Linux адрес `0.0.0.0` или просто `0` разрешается ядром как обращение к локальному интерфейсу:
  - `http://0/` → `0.0.0.0` (фактически `127.0.0.1`)
  - `http://0.0.0.0:6379/`

#### 2. Особенности стека IPv6

- **Локальный адрес IPv6:** `http://[::1]/` или `http://[0:0:0:0:0:0:0:1]/`.
- **Any-адрес IPv6:** `http://[::]/`.
- **IPv4-mapped IPv6:** Включение IPv4-адреса в структуру IPv6:
  - `http://[::ffff:127.0.0.1]/`
  - `http://[::ffff:7f00:1]/`
- **Локальные диапазоны IPv6 (ULA и Link-Local):** `fc00::/7` (Unique Local) и `fe80::/10` (Link-Local). Если в черном списке блокируются только `10.0.0.0/8` и `192.168.0.0/16`, внутренняя сеть по IPv6 остается уязвимой.

#### 3. DNS Rebinding

Если приложение выполняет резолвинг имени хоста для валидации, а затем передает исходный URL в клиентскую библиотеку (curl, Nginx upstream, urllib) для выполнения запроса:

1. **Шаг проверки (Check):** Клиент запрашивает DNS для домена `rebind.attacker.com`. Авторитативный сервер атакующего отдает `203.0.113.10` с `TTL=0`. Фильтр приложения видит публичный IP и одобряет запрос.
2. **Шаг выполнения (Use):** HTTP-клиент перед отправкой пакета делает повторный резолвинг (так как TTL истек). DNS-сервер атакующего отдает `127.0.0.1`. Запрос отправляется на локальный порт хоста.

#### 4. Рассинхронизация парсеров (Parser Confusion)

Разница в стандартах RFC 3986 и WhatWG URL API:
- `http://trusted-domain.com@127.0.0.1/` — некоторые парсеры считают хостом `trusted-domain.com`, а HTTP-клиент использует его как userinfo, отправляя запрос на `127.0.0.1`.
- `http://127.0.0.1#@trusted-domain.com/` — фрагмент `#` отсекается до отправки, но может обмануть валидатор пути.
- Использование обратных слэшей: `http://trusted-domain.com\127.0.0.1/`.

---

## Практические сценарии

### Сценарий 1: Защита Nginx / Angie при динамическом обратном проксировании

**Задача:** Реализовать безопасное динамическое проксирование входящих запросов к внешним партнерским сервисам без риска SSRF во внутреннюю сеть дата-центра.

#### Архитектурное решение
- Использование строгой `map`-таблицы для нормализации и белого списка доменов.
- Запрет ненормализованных URL, запрет символов `@`, `#`, `\`.
- Отключение автоматического следования редиректам на бэкенде.
- Переопределение DNS-резолвера с запретом IPv6 (если внутренний периметр защищен только по IPv4).

#### Конфигурация `/etc/nginx/conf.d/secure_proxy.conf`

```nginx
# 1. Белый список разрешенных целевых доменов
map $arg_target_host $allowed_upstream_host {
    default                  "";
    "api.partner-service.ru" "api.partner-service.ru";
    "metrics.external.org"   "metrics.external.org";
    "cdn.trusted-assets.net" "cdn.trusted-assets.net";
}

# 2. Блокировка попыток внедрения IP-адресов в любых форматах
map $arg_target_host $is_ip_address {
    default 0;
    # Детектирование стандартных IPv4, hex/octal префиксов и IPv6
    "~*^[0-9.]+$"            1;
    "~*^0x"                  1;
    "~*[:\[\]]"              1;
}

server {
    listen 80;
    server_name gateway.corp.internal;

    # Изолированный внешний DNS-сервер с жестким таймаутом
    resolver 1.1.1.1 8.8.8.8 valid=60s ipv6=off;
    resolver_timeout 3s;

    location /proxy-gateway {
        # Валидация метода
        limit_except GET POST {
            deny all;
        }

        # Отсечение попыток внедрения IP или подозрительных символов
        if ($is_ip_address) {
            return 403 "Forbidden: IP addresses are not permitted as upstream targets\n";
        }

        # Проверка по белому списку
        if ($allowed_upstream_host = "") {
            return 403 "Forbidden: Target host is not authorized\n";
        }

        # Отсечение попыток обхода через userinfo (@) или фрагменты (#)
        if ($arg_target_host ~* "[\@\#\\\/]") {
            return 400 "Bad Request: Malformed target host\n";
        }

        # Формирование безопасного URI
        # Переменная в proxy_pass принуждает Nginx использовать директиву resolver
        proxy_pass https://$allowed_upstream_host$uri$is_args$args;

        # Защита от перехвата редиректов (SSRF через Location Header)
        proxy_intercept_errors on;
        proxy_redirect off;

        # Очистка заголовков от инъекций
        proxy_set_header Host $allowed_upstream_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Жесткие сетевые таймауты
        proxy_connect_timeout 3s;
        proxy_read_timeout 5s;
        proxy_send_timeout 5s;
    }

    # Ловушка для перехваченных кодов перенаправления
    error_page 301 302 307 308 = @deny_redirect;
    location @deny_redirect {
        return 502 "Bad Gateway: Upstream redirects are blocked by security policy\n";
    }
}
```

#### Проверка корректности работы

```bash
# Тест 1: Попытка прямого обращения к локальному сокету через IP
curl -s -i "http://127.0.0.1/proxy-gateway?target_host=127.0.0.1"
# → HTTP/1.1 403 Forbidden
# → Forbidden: IP addresses are not permitted as upstream targets

# Тест 2: Попытка обхода через восьмеричную запись
curl -s -i "http://127.0.0.1/proxy-gateway?target_host=0177.0.0.1"
# → HTTP/1.1 403 Forbidden

# Тест 3: Обращение к неизвестному хосту
curl -s -i "http://127.0.0.1/proxy-gateway?target_host=evil-attacker.com"
# → HTTP/1.1 403 Forbidden
# → Forbidden: Target host is not authorized

# Тест 4: Запрос к разрешенному хосту из белого списка
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1/proxy-gateway?target_host=api.partner-service.ru"
# → 200
```

---

### Сценарий 2: L7-фильтрация и защита от SSRF в HAProxy

**Задача:** Защитить балансировщик HAProxy от атак SSRF при проксировании запросов, валидируя заголовки `Host`, пути и предотвращая обращение к локальным служебным сокетам.

#### Конфигурация `/etc/haproxy/haproxy.cfg`

```haproxy
global
    log /dev/log local0 info
    chroot /var/lib/haproxy
    user haproxy
    group haproxy
    daemon
    stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners

defaults
    log     global
    mode    http
    option  httplog
    option  dontlognull
    timeout connect 3s
    timeout client  10s
    timeout server  10s

# Разрешение внешних имен через выделенный резолвер
resolvers internal_dns
    nameserver dns1 1.1.1.1:53
    nameserver dns2 8.8.8.8:53
    resolve_retries 3
    timeout retry   1s
    hold valid      30s
    hold refused    5s
    hold nx         5s

frontend fe_edge
    bind :80
    mode http

    # 1. Защита от CRLF / Header Smuggling
    http-request deny deny_status 400 if { capture.req.uri -m reg [\r\n] }

    # 2. Определение попыток обращения к приватным сетям и Loopback
    acl acl_target_localhost  url_reg -i (127\.[0-9]+|0x7f|0177|\[::1\]|0\.0\.0\.0|^0$)
    acl acl_target_rfc1918_10 url_reg -i (10\.[0-9]+\.[0-9]+\.[0-9]+|0x0a|012\.)
    acl acl_target_rfc1918_172 url_reg -i (172\.(1[6-9]|2[0-9]|3[0-1])\.[0-9]+\.[0-9]+)
    acl acl_target_rfc1918_192 url_reg -i (192\.168\.[0-9]+\.[0-9]+)
    acl acl_target_internal_ports url_reg -i :(2375|2379|6379|8200|8500|9090|9100|10250|10255)

    # 3. Белый список хостов для динамических эндпоинтов
    acl acl_allowed_destinations hdr(Host) -i -m reg ^([a-zA-Z0-9-]+\.)*trusted-partner\.ru$

    # 4. Блокировка опасных запросов
    http-request deny deny_status 403 if acl_target_localhost
    http-request deny deny_status 403 if acl_target_rfc1918_10
    http-request deny deny_status 403 if acl_target_rfc1918_172
    http-request deny deny_status 403 if acl_target_rfc1918_192
    http-request deny deny_status 403 if acl_target_internal_ports

    # Пропуск разрешенных хостов
    use_backend be_external_partner if acl_allowed_destinations
    default_backend be_main_app

backend be_external_partner
    mode http
    # Изолированный пул с резолвингом через безопасный DNS
    server srv_partner api.trusted-partner.ru:443 check ssl verify required ca-file /etc/ssl/certs/ca-certificates.crt resolvers internal_dns

backend be_main_app
    mode http
    server srv_app 127.0.0.1:8080 check
```

#### Проверка синтаксиса и запуск

```bash
# Валидация файла конфигурации HAProxy
haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Проверка блокировки запроса с попыткой атаки на локальный порт etcd
curl -s -i -H "Host: 127.0.0.1:2379" "http://127.0.0.1/"
# → HTTP/1.1 403 Forbidden
```

---

### Сценарий 3: Выделенный изолированный Egress Forward Proxy на Squid

**Задача:** Запретить всем бэкенд-сервисам и веб-серверам напрямую инициировать исходящие HTTP/HTTPS-соединения в Интернет. Маршрутизировать весь исходящий трафик через шлюз Squid, жестко блокирующий любые обращения к внутренним подсетям предприятия.

#### Конфигурация `/etc/squid/squid.conf`

```squid
# Определение стандартных безопасных портов
acl Safe_ports port 80          # http
acl Safe_ports port 443         # https
acl SSL_ports  port 443

# Запрет нестандартных портов (блокировка доступа к 2375, 6379, 9090 и т.д.)
http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports

# Определение приватных и служебных IP-подсетей предприятия
acl local_loopback dst 127.0.0.0/8
acl local_loopback6 dst ::1/128
acl local_rfc1918_10 dst 10.0.0.0/8
acl local_rfc1918_172 dst 172.16.0.0/12
acl local_rfc1918_192 dst 192.168.0.0/16
acl local_linklocal dst 169.254.0.0/16
acl local_ipv6_ula dst fc00::/7
acl local_ipv6_link dst fe80::/10

# Клиентская подсеть DMZ, которой разрешено обращаться к прокси
acl dmz_webservers src 172.20.10.0/24

# 1. Полный запрет доступа к внутренним IP-адресам через прокси
http_access deny local_loopback
http_access deny local_loopback6
http_access deny local_rfc1918_10
http_access deny local_rfc1918_172
http_access deny local_rfc1918_192
http_access deny local_linklocal
http_access deny local_ipv6_ula
http_access deny local_ipv6_link

# 2. Разрешение доступа веб-серверам из DMZ к внешним ресурсам
http_access allow dmz_webservers

# 3. Запрет всего остального трафика по умолчанию (Default Deny)
http_access deny all

# Прослушивание порта прокси только на внутреннем интерфейсе
http_port 172.20.10.1:3128

# Сокрытие следов и внутренних заголовков
forwarded_for delete
via off
```

#### Проверка применения правил в Squid

```bash
# Проверка конфигурации Squid
squid -k parse
# → Processing: acl Safe_ports port 80 ... [OK]

# Перезагрузка сервиса без разрыва активных сессий
systemctl reload squid

# Тестирование: попытка через прокси достучаться до Kubelet в локальной сети
curl -s -i -x http://172.20.10.1:3128 "http://10.96.0.1:10255/pods"
# → HTTP/1.1 403 Forbidden
# → X-Squid-Error: ERR_ACCESS_DENIED 0

# Тестирование: легитимный исходящий запрос во внешнюю сеть
curl -s -o /dev/null -w "%{http_code}\n" -x http://172.20.10.1:3128 "http://example.com"
# → 200
```

---

### Сценарий 4: Системная изоляция веб-сервера через Systemd (Cgroups / Sandboxing)

**Задача:** Ограничить сетевой доступ для worker-процессов Nginx на уровне ядра Linux, гарантируя, что даже при полной компрометации процесса веб-сервер не сможет отправить IP-пакет на loopback или в управляющие подсети.

#### Переопределение сервиса `/etc/systemd/system/nginx.service.d/override.conf`

```ini
[Service]
# Блокировка всех исходящих и входящих IP-соединений по умолчанию
IPAddressDeny=any

# Белый список: разрешить входящий трафик от клиентов и исходящий к внешнему шлюзу
# Разрешено слушать на внешнем интерфейсе DMZ
IPAddressAllow=172.20.10.15/32

# Разрешено отправлять запросы ТОЛЬКО в сеть публичных DNS и доверенный Egress Proxy
IPAddressAllow=1.1.1.1/32
IPAddressAllow=8.8.8.8/32
IPAddressAllow=172.20.10.1/32

# Полный запрет доступа к Loopback (127.0.0.1, ::1) на уровне eBPF cgroup
# (Любая попытка connect() к 127.0.0.1 вернет ошибку EPERM на системном вызове)
IPAddressDeny=127.0.0.0/8
IPAddressDeny=::1/128
IPAddressDeny=10.0.0.0/8
IPAddressDeny=192.168.0.0/16
IPAddressDeny=172.16.0.0/12

# Дополнительное ограничение привилегий процесса
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
```

#### Применение и тестирование блокировки

```bash
# Применение обновленной конфигурации systemd
systemctl daemon-reload
# → result: конфигурация перечитана

# Перезапуск сервиса Nginx
systemctl restart nginx

# Проверка статуса сервиса
systemctl status nginx --no-pager
# → Active: active (running)

# Проверка блокировки: попытка процесса nginx отправить запрос к локальному Redis (порт 6379)
sudo -u www-data nc -zv 127.0.0.1 6379
# → nc: connect to 127.0.0.1 port 6379 (tcp) failed: Operation not permitted
```

---

### Сценарий 5: Блокировка SSRF на уровне ядра Linux через `nftables`

**Задача:** Запретить процессам веб-сервера (пользователь `www-data` или `nginx`) отправлять сетевые пакеты во внутренние сегменты сети дата-центра, разрешая только общение с клиентами и выделенным апстримом.

#### Конфигурация `/etc/nftables.conf`

```nftables
#!/usr/sbin/nft -f

flush ruleset

table inet filter {
    # Список запрещенных приватных сетей интранета
    set private_networks {
        type ipv4_addr
        flags interval
        elements = {
            10.0.0.0/8,
            172.16.0.0/12,
            192.168.0.0/16,
            127.0.0.0/8,
            169.254.0.0/16
        }
    }

    # Разрешенные доверенные адреса внутренних бэкендов (только эти IP доступны веб-серверу)
    set authorized_upstreams {
        type ipv4_addr
        elements = {
            172.16.101.50,
            172.16.101.51
        }
    }

    chain input {
        type filter hook input priority filter; policy drop;

        # Разрешить установленные соединения и loopback для служебных нужд ядра
        ct state established,related accept
        iif "lo" accept

        # Входящие HTTP/HTTPS запросы от клиентов
        tcp dport { 80, 443 } accept
        # Входящий SSH
        tcp dport 22 accept
    }

    chain output {
        type filter hook output priority filter; policy accept;

        # Разрешить установленные сессии
        ct state established,related accept

        # Блокировка SSRF для процессов веб-сервера
        # Если пакет создан процессом с UID nginx/www-data:
        skuid "nginx" ip daddr @authorized_upstreams accept
        skuid "nginx" ip daddr @private_networks drop
        skuid "nginx" ip6 daddr { ::1, fc00::/7, fe80::/10 } drop

        # Разрешить исходящие запросы к DNS (порт 53)
        udp dport 53 accept
        tcp dport 53 accept
    }
}
```

#### Загрузка правил и верификация

```bash
# Проверка синтаксиса и загрузка правил
nft -c -f /etc/nftables.conf
# → Configuration valid

nft -f /etc/nftables.conf

# Просмотр активной цепочки output
nft list chain inet filter output
# → chain output {
# →     type filter hook output priority filter; policy accept;
# →     ct state established,related accept
# →     skuid "nginx" ip daddr @authorized_upstreams accept
# →     skuid "nginx" ip daddr @private_networks drop
# → }
```

---

## Диагностика и устранение неисправностей

### Сводная таблица инцидентов и проблем безопасности

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **504 Gateway Timeout** при запросе пользователя | Веб-сервер пытается подключиться к несуществующему или защищенному внутреннему IP (SSRF probe) | Анализ `error.log`: `connect() failed (110: Connection timed out) while connecting to upstream` | Настроить `resolver_timeout 2s;`, запретить неразрешенные хосты через `map`. |
| **403 Forbidden** на легитимные запросы к партнерам | Строгий regex заблокировал легитимный домен или порт партнера | Проверка access.log с логированием переменной `$allowed_upstream_host` | Добавить домен в белый список `map`, расширить список разрешенных портов. |
| Утечка данных метрик Prometheus через обратный прокси | В `location /` используется `proxy_pass http://$http_host;` без санитизации | `curl -H "Host: 127.0.0.1:9090" http://gateway/metrics` | Исключить прямое проксирование пользовательского `Host`, принудительно задавать апстрим. |
| Обход блокировки через DNS Rebinding | Приложение резолвит хост один раз, а HTTP-клиент повторно выполняет запрос | Мониторинг DNS-запросов утилитой `tcpdump -nn -i any port 53` | Использовать DNS-pinning, настроить внутренний резолвер с игнорированием TTL=0 или кэшированием на L7. |
| Ошибка `Operation not permitted` при обращении к бэкенду | `IPAddressDeny` в systemd или `nftables` блокирует легитимный адрес нового upstream | `dmesg \| grep -i nftables` или логи auditd | Добавить новый IP в `IPAddressAllow` в `override.conf` сервиса. |

---

### Анализ журналов веб-сервера на предмет попыток SSRF

Для оперативного обнаружения атак дежурному инженеру (On-call / SRE) рекомендуется выполнять регулярный мониторинг access-логов:

```bash
# 1. Поиск попыток обращения к внутренним IP-адресам в параметрах запросов
grep -E -i "(\b127\.|0177|0x7f|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.|192\.168\.|localhost|::1)" /var/log/nginx/access.log | head -n 5
# → 198.51.100.24 - - [15/Oct/2026:08:12:01 +0300] "GET /proxy?url=http://127.0.0.1:2375/version HTTP/1.1" 403 45 "-" "curl/7.88.1"

# 2. Поиск попыток внедрения нестандартных протоколов (gopher, dict, file, ldap)
grep -E -i "(\b(gopher|dict|file|ldap|tftp)://)" /var/log/nginx/access.log
# → [пусто, если попыток не зафиксировано]

# 3. Выявление запросов с инъекцией CRLF в заголовках или строке запроса
grep -P "%0d|%0a|\r|\n" /var/log/nginx/access.log
# → [пусто, если атаки отсекаются на L7]
```

---

### Инструментальное тестирование устойчивости к DNS Rebinding

Проверка локального резолвера на уязвимость к подмене IP-адреса:

```bash
# Запрос к специализированному тестовому сервису DNS Rebinding (или внутреннему Bind9)
dig +short A 127.0.0.1.nip.io
# → 127.0.0.1

# Проверка реакции веб-сервера на домен с wildcard-разрешением в локальный IP
curl -s -i "http://127.0.0.1/proxy-gateway?target_host=test.127.0.0.1.nip.io"
# → HTTP/1.1 403 Forbidden
# → Forbidden: Target host is not authorized
```

---

## Лучшие практики

1. **Архитектурный принцип Default Deny для исходящего трафика (Egress Default Deny):** Любой веб-сервер в демилитаризованной зоне (DMZ) не должен иметь сетевых маршрутов во внутреннюю сеть дата-центра, к управляющим портам hypervisors или в сегмент баз данных. Все внешние запросы должны идти строго через выделенный шлюз.
2. **Белые списки (Whitelist) вместо черных списков (Blacklist):** Регулярные выражения для фильтрации IP-адресов неэффективны из-за многообразия форматов представления адресов в стеке TCP/IP. Разрешайте только строго зафиксированный список доменных имен и портов.
3. **Запрет следования редиректам (Follow Redirects):** Всегда отключайте автоматическую обработку заголовков `Location` (`proxy_redirect off;`, `proxy_intercept_errors on;` в Nginx, запрет `CURLOPT_FOLLOWLOCATION` в приложениях).
4. **Валидация IP-адреса на этапе установки сокета (Socket-level Pinning):** Если приложение вынуждено выполнять запросы к внешним URL, валидация должна производиться системной функцией `getaddrinfo()`, после чего сокет открывается непосредственно к проверенному IP-адресу, без повторного DNS-запроса (защита от DNS Rebinding).
5. **Изоляция на уровне ядра (Defense-in-Depth):** Настройка сетевых ограничений через systemd (`IPAddressDeny`) или `nftables` гарантирует защиту даже при наличии критических уязвимостей в коде веб-сервера или веб-приложения.
6. **Отказ от небезопасных протоколов:** Блокируйте поддержку любых схем, кроме `http://` и `https://`. Схемы `gopher://`, `dict://`, `file://` должны быть жестко отключены на уровне парсера URL.
7. **Аутентификация для внутренних сервисов:** Никогда не полагайтесь исключительно на сетевой периметр. Все внутренние сервисы (Prometheus endpoints, Docker daemon, Redis, Consul, Vault) должны требовать аутентификацию (токены, пароли, взаимный TLS / mTLS) даже для соединений с `127.0.0.1`.

---

## Граничные случаи и эксплуатационные риски

1. **TOCTOU в коде микросервисов:** Распространенная ошибка разработчиков — валидировать URL в одном модуле (например, проверка IP по regex), а затем вызывать стандартный HTTP-клиент, который выполняет повторный резолвинг DNS. В промежутке между вызовами DNS-запись меняется через технику Rebinding.
2. **Локальные сокеты UNIX (UDS):** Если веб-сервер имеет доступ к файловой системе, где расположены служебные сокеты (`/var/run/docker.sock` или сокеты баз данных), атака через `file://` или специфические модули проксирования может привести к прямой передаче команд в сокет в обход сетевого стека.
3. **Обход через Wildcard DNS:** Злоумышленники используют сервисы вроде `nip.io`, `sslip.io` или собственный домен `*.attacker.com`, возвращающий `127.0.0.1`. Имя выглядит как публичный FQDN, но транслируется в loopback-адрес.
4. **Взаимодействие с IPv6-стеком на серверах Dual-Stack:** Если администратор настроил правила `iptables` только для IPv4, запрос к домену с AAAA-записью `::1` или `fe80::1` успешно пройдет на loopback-интерфейс сервера по IPv6. Всегда синхронизируйте правила для обоих протоколов (`nftables` таблица `inet`).
5. **Мультиплексирование соединений в HTTP/2 (Connection Reuse):** В протоколе HTTP/2 клиент может использовать одно существующее TLS-соединение для отправки запросов к разным виртуальным хостам, если сертификат сервера покрывает оба домена (SAN). Это может обойти проверки раздельных upstream-пулов.

---

## Дополнительная информация

- **[Защита веб-серверов от ботов](./bot_protection.md)** — фильтрация L7-аномалий, rate limiting, FCrDNS.
- **[Runbooks и Incident Response для веб-серверов](./runbooks_incident_response.md)** — регламенты реагирования на инциденты доступности и безопасности.
- **[Руководство по безопасности Nginx](../Nginx/Security/nginx_security_guide.md)** — изоляция процессов, минимизация заголовков и аудит директив.
- **[Харденинг прямого прокси Apache](../Apache/apache-forward-proxy.md)** — предотвращение атак класса Open Proxy и фильтрация `mod_proxy`.
- **[Конфигурация Reverse Proxy в Angie](../Angie/angie_reverse_proxy.md)** — безопасная маршрутизация апстримов и управление заголовками.
- **[Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md)** — правила WAF, ModSecurity CRS против SSRF (Rule 941).
- **[Концепции прокси-серверов и архитектура](../../Networking/Concepts/proxy.md)** — различия Forward/Reverse Proxy, изоляция сетевого периметра.
