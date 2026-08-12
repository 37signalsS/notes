# HAProxy

## Определение

HAProxy ([haproxy.org](https://www.haproxy.org/)) — высокопроизводительный балансировщик нагрузки и прокси-сервер для TCP/HTTP-приложений. Стандарт де-факто для распределения трафика в высоконагруженных системах. Обеспечивает отказоустойчивость, горизонтальное масштабирование и интеллектуальную маршрутизацию запросов. Начиная с версии 3.4 LTS (2026), поддерживает динамическое управление бэкендами через API без перезагрузки и полную нативную поддержку HTTP/3 (QUIC).

## Основные концепции

HAProxy распределяет входящие запросы между бэкенд-серверами, повышая производительность и отказоустойчивость приложений. Для обеспечения высокой доступности самого балансировщика часто используется в связке с [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md).

### Архитектура и схема работы

Основные компоненты конфигурации:

- **`global`** — общесистемные параметры (процессы, потоки, безопасность, лимиты). В современных версиях рекомендуется использовать многопоточность (`nbthread`) вместо нескольких процессов.
- **`defaults`** — параметры по умолчанию для всех секций (таймауты, режимы, логирование).
- **`frontend`** — точка входа, определяет IP/порт для приёма запросов и правила маршрутизации (ACL).
- **`backend`** — группа серверов, обрабатывающих запросы, алгоритмы балансировки и проверки состояния.
- **`listen`** — объединяет frontend и backend (удобно для простых TCP/UDP конфигураций).

**Схема работы в многопоточном режиме (Multithreading):**
HAProxy использует одну событийную петлю (event loop) на поток. Параметры `nbthread` и `cpu-map auto` позволяют эффективно использовать современные многоядерные CPU, минимизируя переключения контекста и обеспечивая линейное масштабирование производительности.

**Схема обработки запроса:**
1. Клиент отправляет запрос на виртуальный IP-адрес (VIP).
2. HAProxy принимает запрос, выполняет TLS-терминацию (если настроено) и анализирует заголовки (в `mode http`).
3. На основе ACL выбирается нужный `backend` и алгоритм балансировки.
4. Запрос перенаправляется на сервер, ответ возвращается клиенту.

### Режимы работы (mode)

| Режим | Уровень OSI | Что анализирует | Особенности |
| :--- | :--- | :--- | :--- |
| **`mode tcp`** | L4 (транспортный) | IP, порт, SNI, TLS-рукопожатие | Максимальная производительность, прозрачность для TLS |
| **`mode http`** | L7 (прикладной) | Заголовки, path, cookies, методы | Поддержка HTTP/2 и HTTP/3 (QUIC), ACL по контенту |

**Критично для ACL:** если прокси работает в `mode tcp`, правила ACL по HTTP-заголовкам, path или cookies **не сработают**, так как HAProxy не разбирает протокол прикладного уровня.

### Наблюдаемость (Observability)

Современный HAProxy (v3.2+) предоставляет мощные инструменты мониторинга:

- **Prometheus Native Exporter:** встроенная поддержка экспорта метрик на эндпоинт `/metrics` без дополнительных агентов (используется `http-request use-service promo-metrics`).
- **OpenTelemetry (OTel):** нативная поддержка отправки трейсов и метрик в OTel-совместимые коллекторы для сквозной трассировки.
- **Runtime API:** управление состоянием серверов, просмотр статистики и изменение весов в реальном времени через UNIX-сокет без перезагрузки конфигурации.

### Безопасность

- **Валидация JWT:** возможность проверки токенов авторизации непосредственно на балансировщике перед проксированием запроса к бэкенду.
- **Stick Tables:** механизм хранения состояний в оперативной памяти для защиты от DDoS, перебора паролей (Brute-force) и реализации Rate Limiting (ограничение скорости запросов).
- **SSL/TLS Hardening:** поддержка TLS 1.3, автоматизация ACME (Let's Encrypt), поддержка OCSP Stapling и строгие профили шифрования.

### Алгоритмы балансировки

Основные алгоритмы распределения нагрузки:

| Алгоритм | Описание | Сценарий |
| :--- | :--- | :--- |
| **`roundrobin`** | Запросы распределяются поочерёдно, поддержка весов | По умолчанию, подходит для большинства HTTP-приложений |
| **`leastconn`** | Запрос идёт на сервер с наименьшим числом активных соединений | Длинные TCP-сессии (БД, WebSocket), HTTP с переменной нагрузкой |
| **`source`** | Хеширование IP клиента → фиксированный сервер | Session affinity без использования Cookies |
| **`uri`** | Хеширование URI → один ресурс на один сервер | Оптимизация кэширования, CDN |
| **`url_param`** | Балансировка по параметру в URL | Персонализированная или сегментированная маршрутизация |
| **`hdr`** | Хеширование HTTP-заголовка (User-Agent, Cookie) | A/B тестирование, канареечные релизы |
| **`first`** | Заполнение сервера до лимита `maxconn`, затем переход к следующему | Экономия ресурсов в облаках, консолидация нагрузки |
| **`random`** | Случайный выбор сервера | Простые сценарии без жестких требований к распределению |

### ACL и маршрутизация

ACL (Access Control Lists) — это механизм фильтрации и маршрутизации на основе условий запроса.

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

**Порядок правил:** HAProxy читает конфигурацию **сверху вниз**. Если правило завершает обработку (например, `deny` или `use_backend`), следующие правила не выполняются. Специфичные правила (например, для конкретного пути) должны быть выше общих.

**Распространённые ошибки:**
- ACL не срабатывает из-за неправильного `mode` (tcp вместо http).
- Нарушен порядок правил: общий `default_backend` или широкое правило ACL перехватывает специфичные запросы.
- Директивы `http-request` размещены после `use_backend`.

### Проверка состояния (Health Checks)

- **TCP check:** проверка доступности порта (открытие соединения).
- **HTTP check:** запрос к health-эндпоинту, проверка статус-кода или тела ответа (`http-check expect`).
- **SSL check:** проверка валидности и срока действия сертификата бэкенда.
- **Agent check:** использование внешнего агента на целевом сервере для получения детальных метрик здоровья.

Недоступные серверы автоматически исключаются из ротации и возвращаются при восстановлении (параметры `inter`, `fall`, `rise`).

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
    # Передача реального IP клиента
    option forwardfor
    server web01 192.168.131.33:8080 check
    server web02 192.168.131.34:8080 check
```

### Терминация SSL/TLS и HTTP/2

HAProxy расшифровывает трафик и передаёт на бэкенды по HTTP, снижая нагрузку на CPU серверов приложений.

```haproxy
frontend https_frontend
    # Использование сертификата и объявление поддержки HTTP/2 через ALPN
    bind *:443 ssl crt /etc/haproxy/certs/site.pem alpn h2,http/1.1
    mode http
    
    # Редирект с HTTP на HTTPS
    http-request redirect scheme https unless { ssl_fc }
    
    default_backend http_backend
```

### Настройка HTTP/3 (QUIC)

Требует версии HAProxy 3.0+. Работает по протоколу UDP.

```haproxy
frontend quic_frontend
    # TCP для HTTP/1.1 и HTTP/2
    bind *:443 ssl crt /etc/haproxy/certs/site.pem alpn h3,h2,http/1.1
    # UDP для HTTP/3
    bind *:443 quic4 alpn h3
    
    # Объявление поддержки HTTP/3 клиенту через заголовок Alt-Svc
    http-after-response add-header alt-svc 'h3=":443"; ma=60'
    
    default_backend http_backend
```

### Проброс SSL/TLS (Passthrough)

HAProxy пробрасывает зашифрованный трафик напрямую к бэкендам без расшифровки (режим L4).

```haproxy
frontend https_passthrough
    bind *:443
    mode tcp
    default_backend https_backend

backend https_backend
    mode tcp
    balance roundrobin
    server web01 192.168.131.33:443 check
```

### Балансировка kube-apiserver (bare-metal)

В bare-metal кластерах Kubernetes HAProxy обеспечивает отказоустойчивый доступ к API-серверу на порту 6443. Используется в связке с Keepalived для плавающего VIP.

> Подробное руководство: [Настройка High Availability API-сервера с Keepalived и HAProxy](../Kubernetes/Installation/kubeadm/ha_concepts.md).

### Отказоустойчивая балансировка PostgreSQL (Patroni)

HAProxy опрашивает API Patroni (порт 8008) для определения текущего лидера (Master) кластера.

#### 1. Конфигурация `haproxy.cfg`

```haproxy
global
    maxconn 4096              # Лимит одновременных соединений
    nbthread 4                # Количество потоков
    cpu-map auto:1/1-4 0-3    # Привязка потоков к ядрам

listen stats
    bind *:8443
    stats enable
    stats uri /stats
    stats refresh 10s
    # Экспорт метрик для Prometheus
    http-request use-service promo-metrics if { path /metrics }

backend postgres_backend
    mode tcp
    option httpchk            # HTTP-проверка состояния через Patroni
    http-check expect status 200
    
    # inter 3s - интервал проверки
    # on-marked-down shutdown-sessions - разрыв сессий при падении мастера
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
    
    # Трафик идет на 5432, проверка — на 8008
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
      - "8443:8443"           # Статистика и метрики
      - "5432:5432"           # PostgreSQL порт
    restart: always
```

## Диагностика и устранение неполадок

### Проверка конфигурации и отладка

Перед применением изменений всегда выполняйте проверку синтаксиса:
```bash
haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid
```

**Инструменты реального времени (Runtime API):**
Используйте `socat` для взаимодействия с UNIX-сокетом HAProxy:
- `echo "show stat" | socat /var/run/haproxy.sock stdio` — просмотр статистики.
- `echo "show info" | socat /var/run/haproxy.sock stdio` — общая информация о процессе.
- `echo "set weight backend/server 50" | socat /var/run/haproxy.sock stdio` — изменение веса сервера на лету.

### Анализ логов и флаги завершения

HAProxy предоставляет детальные логи. Флаги в конце лог-строки критичны для диагностики:
- **`CD`**: Соединение было закрыто клиентом (Client Disconnect).
- **`sC`**: Соединение закрыто сервером или таймаут на стороне сервера.
- **`cC`**: Соединение закрыто HAProxy (например, из-за превышения лимитов).
- **`PH`**: Ошибка при разборе заголовков запроса.

## Рекомендации по настройке (Best Practices)

1.  **Таймауты (Timeouts):**
    - `timeout connect 5s`: время на установку соединения с бэкендом.
    - `timeout client 50s`: ожидание данных от клиента.
    - `timeout server 50s`: ожидание ответа от сервера.
    - `timeout http-request 10s`: защита от атак типа Slowloris.
2.  **Системные настройки (sysctl):**
    - `net.ipv4.ip_nonlocal_bind = 1`: позволяет HAProxy запускаться на IP, который еще не назначен интерфейсу (нужно для Keepalived).
    - `fs.file-max`: увеличьте лимит файловых дескрипторов для поддержки большого количества соединений.
3.  **Безопасность:**
    - Изоляция: используйте `chroot /var/lib/haproxy`.
    - Привилегии: запускайте от пользователя `user haproxy` и группы `group haproxy`.
    - `maxconn`: всегда ограничивайте максимальное число соединений на глобальном уровне и для бэкендов.

## Дополнительная информация

### Сравнение с Nginx

HAProxy — это узкоспециализированный балансировщик («скальпель»), в то время как Nginx — универсальный веб-сервер («швейцарский нож»).

| Характеристика | HAProxy | Nginx (OSS) |
| :--- | :--- | :--- |
| **Специализация** | Только балансировка и проксирование | Веб-сервер + балансировщик |
| **Алгоритмы** | Огромный выбор (leastconn, uri, hdr, stick) | Ограниченный набор (round-robin, ip_hash) |
| **Здоровье бэкендов** | Активные глубокие проверки встроены | Только базовые (пассивные) в бесплатной версии |
| **Мониторинг** | Глубокая статистика через сокет и Runtime API | Базовая страница `stub_status` |

**См. также:**
- [Nginx Load Balancing — Additional Info](./Nginx/Proxy/Load_Balancing/additional_info_and_comparisons.md)
- [Отказоустойчивость PostgreSQL](../Databases/PostgreSQL/Concepts/high_availability.md)
- [Keepalived: Обзор и настройка](../Networking/ServicesAndTools/keepalived_overview.md)
