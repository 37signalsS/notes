# HAProxy

**Надёжность:** 10 (SSoT + Обзор HAProxy 3.4 LTS 2026)
**Свежесть:** Июль 2026

## Определение

HAProxy ([haproxy.org](https://www.haproxy.org/)) — высокопроизводительный балансировщик нагрузки и прокси-сервер для TCP/HTTP-приложений. Стандарт де-факто для распределения трафика в высоконагруженных системах. Обеспечивает отказоустойчивость, горизонтальное масштабирование и интеллектуальную маршрутизацию запросов. Начиная с версии 3.4 LTS (2026), поддерживает динамическое управление бэкендами через API без перезагрузки.

## Основные концепции

HAProxy распределяет входящие запросы между бэкенд-серверами, повышая производительность и отказоустойчивость приложений. Для обеспечения высокой доступности самого балансировщика часто используется в связке с [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md).

### Архитектура и схема работы

Основные компоненты конфигурации:

- **`global`** — общесистемные параметры (процессы, потоки, безопасность). В современных версиях рекомендуется использовать многопоточность (`nbthread`) вместо нескольких процессов.
- **`frontend`** — точка входа, определяет IP/порт для приёма запросов и правила маршрутизации (ACL).
- **`backend`** — группа серверов, обрабатывающих запросы.
- **`listen`** — объединяет frontend и backend (для простых конфигураций).
- **`defaults`** — параметры по умолчанию для всех секций.

**Схема работы в многопоточном режиме (Multithreading):**
HAProxy использует одну событийную петлю (event loop) на поток. Параметры `nbthread` и `cpu-map auto` позволяют эффективно использовать современные многоядерные CPU, минимизируя переключения контекста.

Схема обработки запроса:

1. Клиент отправляет запрос на виртуальный IP-адрес (VIP).
2. HAProxy принимает запрос, выполняет TLS-терминацию (если настроено) и анализирует заголовки (в `mode http`).
3. На основе ACL выбирается нужный `backend` и алгоритм балансировки.
4. Запрос перенаправляется на сервер, ответ возвращается клиенту.

### Режимы работы (mode)

| Режим | Уровень OSI | Что анализирует | Особенности |
| :--- | :--- | :--- | :--- |
| **`mode tcp`** | L4 (транспортный) | IP, порт, SNI, TLS-рукопожатие | Максимальная производительность, прозрачность для TLS |
| **`mode http`** | L7 (прикладной) | Заголовки, path, cookies, методы | Поддержка HTTP/2 и HTTP/3 (QUIC), ACL по контенту |

**Критично для ACL:** если прокси работает в `mode tcp`, правила ACL по HTTP-заголовкам, path или cookies **не сработают**.

### Наблюдаемость (Observability)

Современный HAProxy (v3.2+) предоставляет мощные инструменты мониторинга:

- **Prometheus Native Exporter:** встроенная поддержка экспорта метрик без дополнительных агентов.
- **OpenTelemetry (OTel):** нативная поддержка отправки трейсов и метрик в OTel-совместимые коллекторы.
- **Runtime API:** управление состоянием серверов, просмотр статистики и изменение весов в реальном времени через CLI или сокет.

### Безопасность

- **Валидация JWT:** возможность проверки токенов авторизации на уровне балансировщика перед проксированием.
- **Stick Tables:** механизм отслеживания активности клиентов для защиты от DDoS, перебора паролей (Brute-force) и ограничения скорости (Rate Limiting).
- **SSL/TLS Hardening:** поддержка TLS 1.3, автоматизация ACME (Let's Encrypt) и строгие профили шифрования.

### Алгоритмы балансировки

Основные алгоритмы распределения нагрузки:

| Алгоритм | Описание | Сценарий |
| :--- | :--- | :--- |
| **`roundrobin`** | Запросы распределяются поочерёдно, поддержка весов | По умолчанию, подходит для большинства HTTP-приложений |
| **`leastconn`** | Запрос идёт на сервер с наименьшим числом активных соединений | Длинные TCP-сессии (БД, FTP), HTTP с переменной нагрузкой |
| **`source`** | Хеширование IP клиента → фиксированный сервер | Session affinity без cookies |
| **`uri`** | Хеширование URI → один ресурс на один сервер | Кэширование, CDN |
| **`url_param`** | Балансировка по параметру URL | Персонализированная маршрутизация |
| **`hdr`** | Хеширование HTTP-заголовка (User-Agent, Cookie) | A/B тестирование, канареечные релизы |
| **`first`** | Заполнение сервера до лимита, затем следующий | Экономия ресурсов, консолидация нагрузки |
| **`random`** | Случайный выбор сервера | Простые сценарии без требований к стейту |

Выбор алгоритма зависит от специфики приложения: для HTTP — `roundrobin` или `leastconn`, для сессионных приложений — `source` или `hdr`.

### ACL и маршрутизация

ACL — это механизм фильтрации и маршрутизации на основе условий запроса.

**Синтаксис:**

```haproxy
frontend http_frontend
    bind *:80
    mode http

    acl is_api path_beg /api
    acl blocked_ip src 10.0.0.100

    http-request deny if blocked_ip
    use_backend api_backend if is_api
    default_backend web_backend
```

**Порядок правил:** HAProxy читает конфигурацию **сверху вниз**. Если правило завершает обработку (например, `deny`), следующие правила не выполняются.

**Распространённые ошибки:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| ACL не срабатывает | Неправильный `mode` (tcp вместо http) | Использовать `mode http` для L7-правил |
| Запрос уходит не в тот backend | Нарушен порядок правил | Специфичные правила размещать перед общими |
| `http-request` игнорируется | Правило после `use_backend` | `http-request` должны быть перед выбором backend |

### Проверка состояния (Health Checks)

HAProxy регулярно проверяет доступность бэкендов:

- **TCP check:** проверка доступности порта
- **HTTP check:** запрос к health endpoint, проверка статуса/тела ответа
- **SSL check:** проверка SSL-сертификата бэкенда

Недоступные серверы автоматически исключаются из ротации и возвращаются при восстановлении.

## Практические сценарии

### Базовая балансировка HTTP (L7)

```haproxy
frontend http_frontend
    bind *:80
    mode http
    default_backend http_backend

backend http_backend
    mode http
    balance leastconn
    server web01 192.168.131.33:8080 check
    server web02 192.168.131.34:8080 check
```

- `mode http` — анализ HTTP-заголовков, поддержка ACL
- `balance leastconn` — запросы на сервер с наименьшим числом сессий

### Балансировка TCP (L4)

```haproxy
frontend tcp_frontend
    bind *:8080
    mode tcp
    default_backend tcp_backend

backend tcp_backend
    mode tcp
    balance roundrobin
    server db01 192.168.131.33:5432 check
    server db02 192.168.131.34:5432 check
```

- `mode tcp` — балансировка любых TCP-протоколов (БД, SSH, VPN)
- `balance roundrobin` — поочерёдное распределение

### Терминация SSL/TLS

HAProxy расшифровывает HTTPS-трафик и передаёт на бэкенды по HTTP, снимая нагрузку с серверов приложений.

```haproxy
frontend https_frontend
    bind *:443 ssl crt /etc/haproxy/certs/your_domain.pem
    mode http
    default_backend http_backend

backend http_backend
    mode http
    balance leastconn
    server web01 192.168.131.33:8080 check
    server web02 192.168.131.34:8080 check
```

- `ssl crt` — путь к PEM-файлу (сертификат + ключ)
- Трафик между HAProxy и бэкендом идёт по HTTP

### Проброс SSL/TLS (Passthrough)

HAProxy пробрасывает зашифрованный трафик напрямую к бэкендам без расшифровки.

```haproxy
frontend https_passthrough
    bind *:443
    mode tcp
    default_backend https_backend

backend https_backend
    mode tcp
    balance leastconn
    server web01 192.168.131.33:443 check
    server web02 192.168.131.34:443 check
```

- `mode tcp` — HAProxy не анализирует содержимое трафика
- SSL-терминирование происходит на бэкендах

### Балансировка kube-apiserver (bare-metal)

В bare-metal кластерах Kubernetes HAProxy обеспечивает отказоустойчивый доступ к API-серверу.

- **Режим:** L4 (`mode tcp`)
- **VIP:** управляется [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md)
- **Порт бэкенда:** `6443` (kube-apiserver)
- **Health checks:** проверка доступности API

> Подробное руководство: [Настройка High Availability API-сервера с Keepalived и HAProxy](../Kubernetes/Installation/kubeadm/ha_concepts.md).

### Отказоустойчивая балансировка PostgreSQL (Patroni)

Сценарий для высоконагруженного кластера БД, использующего **Patroni** для управления состоянием. HAProxy опрашивает API Patroni (порт 8008) для определения текущего лидера.

#### 1. Конфигурация `haproxy.cfg`

```haproxy
global
    maxconn 4096              # Максимальное количество одновременных соединений
    nbthread 4                # Использование 4 потоков для обработки трафика
    cpu-map auto:1/1-4 0-3    # Автоматическая привязка потоков к ядрам CPU

defaults
    mode tcp                  # Для БД используем L4 проксирование
    timeout connect 5s
    timeout client 50s
    timeout server 50s

listen stats
    bind *:8443
    stats enable
    stats uri /stats
    stats refresh 10s
    # Нативный экспорт метрик для Prometheus
    http-request use-service promo-metrics if { path /metrics }

frontend postgres_frontend
    bind *:5432
    default_backend postgres_backend

backend postgres_backend
    option httpchk            # Используем HTTP-проверки для Patroni API
    http-check expect status 200
    balance roundrobin
    
    # inter 3s - интервал проверки
    # fall 3 - узел считается мертвым после 3 провалов
    # on-marked-down shutdown-sessions - принудительно закрыть активные сессии при падении узла
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
    
    # Проверка выполняется на порту 8008 (Patroni REST API)
    server pg_node1 192.168.10.10:5432 maxconn 100 check port 8008
    server pg_node2 192.168.10.11:5432 maxconn 100 check port 8008
```

#### 2. Развертывание через Docker Compose

```yaml
version: "3.9"
services:
  haproxy:
    image: haproxy:3.4-slim
    volumes:
      - ./config/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    ports:
      - "8443:8443"           # Страница статистики и метрики
      - "5432:5432"           # Порт PostgreSQL
    restart: always
```

**Особенности настройки:**
- **`option httpchk`**: Patroni возвращает HTTP 200 только на мастере, что позволяет HAProxy мгновенно переключать трафик при смене лидера.
- **`on-marked-down shutdown-sessions`**: Критически важно для БД. Если мастер упал, HAProxy должен немедленно разорвать все текущие соединения клиентов, чтобы они могли переподключиться к новому лидеру.
- **`maxconn`**: Регулируйте в зависимости от ресурсов сервера и настроек `max_connections` в PostgreSQL.

> Подробнее об архитектуре кластера: **[Отказоустойчивость PostgreSQL](../Databases/PostgreSQL/Concepts/high_availability.md)**.

## Дополнительная информация

### Ключевые особенности

- **Производительность:** событийная модель (event loop), многопоточность (`nbthread`), миллионы запросов/сек при минимальном потреблении памяти.
- **Надёжность:** стандарт де-факто для критически важных нагрузок с поддержкой LTS версий до 5 лет (например, 3.4 LTS до 2031 года).
- **Динамичность:** управление бэкендами и серверами через Runtime API без перезагрузки процесса (Dynamic Backends).
- **Безопасность:** встроенная валидация JWT, защита от DDoS через Stick Tables, автоматизация SSL (ACME/Let's Encrypt).
- **Оптимизация:** полная поддержка HTTP/2 и HTTP/3 (QUIC), TLS 1.3, сжатие gzipped-контента.
- **Наблюдаемость:** нативная поддержка OpenTelemetry и встроенный экспортер для Prometheus.
- **Гибкость:** продвинутые ACL для маршрутизации по любым атрибутам запроса (заголовки, cookies, IP, полезная нагрузка).

### Сравнение с Nginx

HAProxy — это «скальпель» балансировки, в то время как Nginx — «швейцарский нож» (универсальный веб-сервер). 

| Характеристика | HAProxy | Nginx (OSS) |
| :--- | :--- | :--- |
| **Специализация** | Только балансировка и проксирование | Веб-сервер + балансировщик |
| **Алгоритмы** | Огромный выбор (leastconn, uri, hdr, stick) | Ограниченный набор (round-robin, ip_hash) |
| **Здоровье бэкендов** | Глубокие проверки (L4, L7, скрипты) | Базовые проверки (passive) |
| **Мониторинг** | Богатая встроенная статистика и OTel | Базовая страница `stub_status` |

Подробное сравнение: [Nginx Load Balancing — Additional Info](./Nginx/Proxy/Load_Balancing/additional_info_and_comparisons.md).
