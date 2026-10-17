# Проверки состояния и мониторинг балансировщика Nginx

**Актуально для:** Nginx 1.26+ (OSS/Plus) / Angie 1.6+

---

## Определения

- **Проверка состояния (Health Check)** — систематический процесс контроля доступности и корректности функционирования upstream-серверов балансировщиком нагрузки с целью автоматического исключения неисправных узлов из пула маршрутизации.
- **Пассивная проверка (Passive Health Check / Circuit Breaker)** — метод контроля жизнеспособности бэкенда, основанный на анализе результатов обработки реальных пользовательских запросов. Выполняется без создания дополнительного синтетического трафика, регистрируя сетевые ошибки, таймауты и специфические HTTP-коды возврата.
- **Активная проверка (Active Health Check / Synthetic Probing)** — механизм проактивного мониторинга, при котором балансировщик с заданной периодичностью отправляет синтетические служебные запросы (пробы) к каждому бэкенду независимо от наличия клиентского трафика.
- **Зона разделяемой памяти (Upstream Shared Memory Zone / `zone`)** — область оперативной памяти IPC (`shm`), выделяемая директивой `zone` в блоке `upstream` и разделяемая между всеми worker-процессами Nginx/Angie для атомарной синхронизации счетчиков сбоев, динамических весов, таймеров и списков активных серверов.
- **Плавный старт (Slow Start)** — алгоритм постепенного линейного наращивания нагрузки на восстановившийся или введенный в строй бэкенд от нуля до номинального веса, предотвращающий деградацию ненагретого сервиса («шоковый старт»).
- **Upstream (Бэкенд-пул)** — группа серверов приложений, объединенных в единый логический пул для распределения входящих запросов по заданному алгоритму балансировки.
- **Проба (Health Probe)** — служебный запрос (HTTP GET/HEAD, TCP handshake, UDP пакет, FastCGI или SQL ping), инициируемый балансировщиком для проверки доступности сокета или сервисного эндпоинта приложения.
- **Флапинг (Flapping / Дребезг состояния)** — циклическое высокочастотное переключение статуса сервера между состояниями `UP` (доступен) и `DOWN` (недоступен), вызванное пограничными задержками ответов, плавающими сбоями или некорректно заниженными порогами проверок.
- **Каскадный отказ (Cascading Failure / Retry Storm)** — лавинообразное падение всех бэкендов кластера, возникающее при перегрузке оставшихся узлов трафиком упавшего сервера или из-за шторма повторных запросов (`proxy_next_upstream`).
- **Телеметрия балансировщика (Upstream Telemetry)** — комплекс метрик состояния соединений, очередей, задержек и кодов ответов в разрезе серверов и апстрим-групп, собираемый через `stub_status`, модуль VTS, Status API или Prometheus-экспортеры.

---

## Архитектура и принципы работы

### Пассивная проверка состояния (Passive Health Checks)

Пассивный мониторинг встроен в ядро Nginx OSS, Nginx Plus и Angie OSS. Он работает на уровне обратного проксирования (`ngx_http_proxy_module`, `ngx_http_upstream_module`, `ngx_stream_proxy_module`) и управляется параметрами директивы `server` в блоке `upstream`:

- `max_fails=N`: предельное число неудачных попыток взаимодействия с сервером, произошедших за окно времени `fail_timeout` (по умолчанию `1`). Значение `0` полностью отключает регистрацию сбоев.
- `fail_timeout=T`: временной интервал, в течение которого накапливаются сбои `max_fails`, а также длительность периода, на который узел исключается из ротации при фиксации отказа (по умолчанию `10s`).

```
Клиентский запрос ──► Nginx Worker ──► Выбор узла из Upstream
                           │
      ┌────────────────────┴────────────────────┐
      ▼                                         ▼
Успешный ответ (2xx/3xx/4xx)           Сбой (TCP RST, Timeout, 5xx)
      │                                         │
      ▼                                         ▼
Счетчик сбоев не растет               Инкремент счетчика сбоев
                                                │
                                    ┌───────────┴───────────┐
                                    ▼                       ▼
                         fails < max_fails       fails >= max_fails
                                    │                       │
                                    ▼                       ▼
                         Повтор на др. узел      Сервер помечается DOWN
                         (proxy_next_upstream)   на время fail_timeout
```

#### Влияние разделяемой памяти (`zone`) на пассивные проверки

Архитектура хранения состояния проверок принципиально различается в зависимости от наличия директивы `zone`:

1. **Без директивы `zone` (Локальная память процессов):**
   Каждый рабочий процесс (`worker_process`) хранит счетчик `max_fails` в своей собственной приватной памяти. В системе с 16 воркерами и параметром `max_fails=3` для реального отключения неисправного узла должно произойти до:
   $$\text{Всего сбоев} = 16 \times 3 = 48 \text{ клиентских ошибок}$$
   При этом разные воркеры будут направлять запросы на сбойный узел в разное время, вызывая эффект неравномерного распределения ошибок между клиентами.
2. **С директивой `zone` (Разделяемая память IPC):**
   Счетчики сбоев, таймстампы и флаги состояния узлов размещаются в разделяемом сегменте памяти (`shm`), доступном всем воркерам через спинлоки ядра Nginx. При фиксации 3 сбоев суммарно любыми воркерами узел моментально изолируется для всего веб-сервера.

> **Важно:** Директива `zone` является строго обязательной для продакшн-конфигураций любого масштаба.

#### Механизм возврата узла в ротацию

После истечения интервала `fail_timeout` Nginx не возвращает сервер в пул безусловно:
1. Балансировщик снимает с сервера блокировку и разрешает направить на него **ровно один реальный клиентский запрос** (пробный запрос).
2. Если этот запрос завершается успешно — счетчик сбоев сервера сбрасывается в `0`, и сервер восстанавливает полноценное участие в балансировке.
3. Если пробный запрос завершается ошибкой — сервер немедленно блокируется повторно на следующий полный период `fail_timeout`, а клиентский запрос перенаправляется на резервный или следующий узел через механизм `proxy_next_upstream`.

#### Взаимодействие с механизмом `proxy_next_upstream`

Директива `proxy_next_upstream` настраивается в блоках `http`, `server` или `location` и определяет, какие условия считаются неудачной попыткой для передачи запроса следующему серверу:

- Условия: `error` (ошибка установки соединения, сброс TCP), `timeout` (превышение таймаута connect/read/send), `invalid_header` (некорректный HTTP-ответ бэкенда), `http_500`, `http_502`, `http_503`, `http_504`, `http_403`, `http_404`, `http_429`.
- Лимитирование повторов:
  - `proxy_next_upstream_tries N`: максимальное число попыток обработки запроса (включая первую попытку). По умолчанию `0` (число попыток не ограничено, перебираются все серверы пула).
  - `proxy_next_upstream_timeout T`: общее суммарное время, выделенное на все попытки передачи запроса по цепочке. По умолчанию `0` (таймаут отключен).

```nginx
location /api/ {
    proxy_pass http://backend_pool;
    proxy_next_upstream error timeout http_502 http_503 http_504;
    proxy_next_upstream_tries 3;
    proxy_next_upstream_timeout 8s;
}
```

#### Ограничение буферизации и неидемпотентные методы

1. **Буферизация (`proxy_buffering`):** Если Nginx начал передавать тело ответа клиенту (например, при отключенной буферизации `proxy_buffering off;` или при переполнении буферов `proxy_buffers`), передача запроса на другой сервер **невозможна**. В логах фиксируется ошибка `transferring response: client closed connection / upstream prematurely closed connection`, а клиенту отдается разорванное соединение.
2. **Неидемпотентные методы (`POST`, `LOCK`, `PATCH`):** По стандарту RFC Nginx не повторяет запросы с неидемпотентными методами, если часть тела запроса уже была отправлена бэкенду, во избежание дублирования транзакций (например, повторного списания средств). Флаг `non_idempotent` принудительно разрешает повтор таких запросов:
   ```nginx
   proxy_next_upstream error timeout http_502 http_503 non_idempotent;
   ```
   > **Предостережение SRE:** Включайте `non_idempotent` только в том случае, если приложение на бэкенде поддерживает сквозные ключи идемпотентности (`Idempotency-Key`).

---

### Активная проверка состояния (Active Health Checks / Probing)

В отличие от пассивных проверок, активные проверки выполняются специализированным таймером веб-сервера. Они с заданной периодичностью генерируют синтетические пакеты или HTTP-запросы к выделенным health-эндпоинтам бэкендов.

#### Архитектурные особенности реализаций

| Критерий | Nginx OSS (штатный) | Nginx OSS + `check_module` | Angie OSS | Nginx Plus |
| :--- | :--- | :--- | :--- | :--- |
| **Поддержка из коробки** | Отсутствует | Требует пересборки из исходников | **Встроена нативно** | Встроена нативно |
| **Синтаксис настройки** | — | Директива `check` в `upstream` | Директива `check` в `upstream` | Директива `health_check` в `location` |
| **Поддерживаемые типы** | — | HTTP, TCP, SSL Hello, FastCGI, MySQL, AJP | HTTP, TCP, MySQL, FastCGI, PostgreSQL | HTTP, TCP, UDP, gRPC |
| **Фильтрация дребезга** | — | Параметры `rise` и `fall` | Параметры `rise` и `fall` | Параметры `passes` и `fails` |
| **Потребление ресурсов** | Минимальное | 1 поток/таймер на upstream-сервер | 1 таймер на upstream-сервер в master/worker | 1 таймер на upstream-сервер |
| **Спецификация ответа** | — | Коды HTTP (`check_http_expect_alive`) | Коды HTTP (`check_http_expect_alive`) | Блоки `match` (код, заголовки, regex тела) |

#### Принцип фильтрации дребезга (Debounce via Rise / Fall)

Для предотвращения флапинга активные проверки используют конечный автомат состояний:

- **Порог отказа (`fall`):** Количество последовательных неудачных проверок, необходимое для признания сервера неисправным и исключения его из ротации.
- **Порог восстановления (`rise`):** Количество последовательных успешных проверок подряд, необходимое для возврата сервера в активный статус.

```
       [ Состояние: UP ] ──( 1 сбой )──► [ Проверка нестабильна ]
              ▲                                     │
              │                                ( 2-й сбой )
        ( 2 успеха                                  │
          подряд )                                  ▼
              │                          [ Состояние: DOWN ]
              └──────────────── ( fall=2 достигнут, узел исключен )
```

---

### Плавный старт (Slow Start)

Плавный старт решает проблему отказа бэкендов в момент их запуска или возврата в строй после инцидента. Приложения на Java (JVM), Python, Node.js или PHP-FPM при холодном старте требуют времени на прогрев JIT-компилятора, заполнение пулов соединений с базами данных и наполнение локальных кэшей. Если такой сервер сразу получит 100% своей доли трафика, его очередь запросов переполнится, вызвав всплеск ошибок `502/504`.

Параметр `slow_start=T` директивы `server` плавно увеличивает эффективный вес узла от 0 до номинального значения `weight` в течение времени $T$:

$$W_{\text{eff}}(t) = W_{\text{nominal}} \times \frac{t - t_{\text{recovery}}}{T_{\text{slow\_start}}}$$

**Ограничения Slow Start:**
1. Требует обязательного наличия разделяемой памяти `zone` в блоке `upstream`.
2. Работает только с пропорциональными алгоритмами распределения: Round Robin (весовой) и Least Connections (`least_conn`).
3. Несовместим с методами детерминированного хеширования (`ip_hash`, `hash $key`). Если в пуле используется `hash`, параметр `slow_start` игнорируется.

---

### Архитектура телеметрии и мониторинга Upstream

Для оценки состояния пула балансировки применяются четыре уровня наблюдаемости:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Nginx / Angie Master                          │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                 Shared Memory Zone (shm / slab)                │   │
│   │   - Состояние узлов (UP / DOWN / DRAINING)                     │   │
│   │   - Счетчики: requests, responses, codes (1xx/2xx/3xx/4xx/5xx) │   │
│   │   - Тайминги: connect_time, header_time, response_time         │   │
│   └────────────────────────────────┬───────────────────────────────┘   │
│                                    │                                   │
│            ┌───────────────────────┼────────────────────────┐          │
│            ▼                       ▼                        ▼          │
│   [ stub_status ]           [ Angie API ]           [ VTS Module ]     │
│   (Базовый OSS:             (Нативный JSON и        (shm rbtree:       │
│    Active conns,            Prometheus metrics      Server zones,      │
│    Accepts, Handled)        по всем upstream)       Upstream stats)    │
│            │                       │                        │          │
└────────────┼───────────────────────┼────────────────────────┼──────────┘
             ▼                       ▼                        ▼
    nginx-exporter           Prometheus Scrape        Prometheus Scrape
    (:9113/metrics)          (:9113/metrics)          (:8080/status/format/prometheus)
```

1. **Базовый модуль `ngx_http_stub_status_module`:**
   Предоставляет 7 базовых числовых метрик на уровне всего инстанса Nginx (активные соединения, общее число принятых/обработанных запросов, соединения в фазах reading/writing/waiting). Не содержит данных по upstream-группам и отдельным бэкендам.
2. **Модуль `nginx-module-vts` (Virtual Host Traffic Status):**
   Сторонний динамический C-модуль для Nginx OSS. Организует в shm красно-черное дерево со счетчиками трафика, кодов ответов и гистограммами задержек для каждого upstream-сервера. Детально рассмотрен в [Настройка мониторинга Nginx с VTS-модулем, Prometheus и Grafana](../../Operations/nginx_vts_monitoring_setup.md).
3. **Нативный Status API и Prometheus в Angie:**
   Включает сбор статистики для блоков `upstream`, виртуальных хостов (`server`) и путей (`location`) через директиву `status_zone`. Экспортирует состояние в формате JSON через эндпоинт `api /status/` и в формате OpenMetrics/Prometheus через директиву `prometheus all;`.
4. **Утилита `nginx-prometheus-exporter`:**
   Официальный Go-демон, опрашивающий эндпоинт `stub_status` Nginx OSS по HTTP и транслирующий его в метрики Prometheus.

---

## Практические сценарии

### Сценарий 1: Отказоустойчивая конфигурация пассивных проверок (Circuit Breaker)

Сценарий обеспечивает изоляцию сбоящих узлов, ограничение времени зависания клиентских запросов и прозрачное переключение на резервный узел без каскадной перегрузки.

**Конфигурация `/etc/nginx/conf.d/circuit_breaker.conf`:**

```nginx
upstream production_backend {
    # Зона разделяемой памяти: 256 КБ достаточно для хранения состояния ~1000 серверов
    zone prod_backend_zone 256k;

    # Основные узлы пула
    # При 3 ошибках за 10 секунд сервер исключается на 15 секунд
    server 10.10.1.11:8080 weight=5 max_fails=3 fail_timeout=15s;
    server 10.10.1.12:8080 weight=5 max_fails=3 fail_timeout=15s;

    # Резервный узел (получает трафик ТОЛЬКО при отказе всех основных серверов)
    server 10.10.1.99:8080 backup;

    # Поддержание постоянных соединений для снижения задержек
    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}

server {
    listen 80;
    server_name api.company.internal;

    location / {
        proxy_pass http://production_backend;

        # Протокол HTTP/1.1 и сброс Connection для работы keepalive
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Жесткие сетевые таймауты для быстрого обнаружения сбоя
        proxy_connect_timeout 2s;
        proxy_send_timeout 5s;
        proxy_read_timeout 5s;

        # Условия переключения на следующий узел
        proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;

        # Защита от шторма повторов: максимум 3 попытки, суммарно не более 6 секунд
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 6s;
    }
}
```

**Валидация синтаксиса:**
```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

---

### Сценарий 2: Активные HTTP- и TCP-проверки в Angie OSS

Angie OSS содержит встроенный модуль активных проверок. Настройка выполняется непосредственно в блоке `upstream`.

**Конфигурация `/etc/angie/http.d/active_checks.conf`:**

```nginx
# HTTP-пул с проверкой специализированного эндпоинта
upstream web_app_cluster {
    zone web_app_zone 256k;

    server 10.20.1.11:8080;
    server 10.20.1.12:8080;
    server 10.20.1.13:8080;

    # Активная проверка: интервал 3с, 2 успеха для UP, 3 сбоя для DOWN, таймаут пробы 1.5с
    check interval=3000 rise=2 fall=3 timeout=1500 type=http;

    # Формирование корректного HTTP/1.1 запроса с обязательным заголовком Host
    check_http_send "GET /healthz HTTP/1.1\r\nHost: web-app.internal\r\nConnection: close\r\nUser-Agent: Angie-HealthCheck\r\n\r\n";

    # Сервер считается живым при кодах 2xx и 3xx
    check_http_expect_alive http_2xx http_3xx;
}
```

**Конфигурация для TCP в `/etc/angie/stream.d/tcp_checks.conf`:**

```nginx
stream {
    upstream postgres_cluster {
        zone pg_zone 128k;

        server 10.20.2.21:5432;
        server 10.20.2.22:5432;

        # TCP handshake проверка: интервал 2с, таймаут 1с
        check interval=2000 rise=2 fall=2 timeout=1000 type=tcp;
    }

    server {
        listen 5432;
        proxy_pass postgres_cluster;
        proxy_connect_timeout 1s;
        proxy_timeout 1h;
    }
}
```

**Валидация синтаксиса и перезагрузка:**
```bash
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

angie -s reload
# → # конфигурация успешно обновлена без обрыва соединений
```

---

### Сценарий 3: Активные проверки в Nginx OSS через `nginx_upstream_check_module`

Если инфраструктура зафиксирована на стандартном Nginx OSS, активные проверки развертываются через компиляцию Nginx с модулем `nginx_upstream_check_module` (репозиторий yaoweibin).

**Конфигурация `/etc/nginx/conf.d/oss_active_check.conf`:**

```nginx
upstream legacy_service {
    # Директива zone строго рекомендуется
    zone legacy_service_zone 128k;

    server 10.30.1.10:8000;
    server 10.30.1.11:8000;

    # Проверка каждые 3 секунды, падение после 3 ошибок, подъем после 2 успехов
    check interval=3000 rise=2 fall=3 timeout=1000 type=http;
    check_http_send "HEAD /health HTTP/1.0\r\nHost: legacy.internal\r\n\r\n";
    check_http_expect_alive http_2xx;
}

server {
    listen 80;
    server_name legacy.internal;

    location / {
        proxy_pass http://legacy_service;
    }

    # Эндпоинт статуса модуля проверок (HTML / JSON)
    location /upstream_status {
        check_status;
        access_log off;
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        deny all;
    }
}
```

---

### Сценарий 4: Плавный старт (Slow Start) в Angie и Nginx Plus

Защита сервисов на базе ресурсоемких сред исполнения (JVM, CLR, Node.js) при возврате узлов в ротацию.

**Конфигурация `/etc/angie/http.d/slow_start.conf`:**

```nginx
upstream java_app_pool {
    zone java_pool_zone 256k;

    # Используем least_conn для равномерного распределения с учетом медленных ответов
    least_conn;

    # Параметр slow_start=45s: вес плавно растет в течение 45 секунд
    # Параметр max_conns ограничивает пиковую емкость одного экземпляра
    server 10.40.1.11:8080 weight=10 max_conns=150 max_fails=2 fail_timeout=10s slow_start=45s;
    server 10.40.1.12:8080 weight=10 max_conns=150 max_fails=2 fail_timeout=10s slow_start=45s;
    server 10.40.1.13:8080 weight=10 max_conns=150 max_fails=2 fail_timeout=10s slow_start=45s;
}

server {
    listen 80;
    server_name billing.company.internal;

    location / {
        proxy_pass http://java_app_pool;
        proxy_next_upstream error timeout http_502 http_503;
        proxy_next_upstream_tries 2;
    }
}
```

---

### Сценарий 5: Экспорт метрик в Prometheus и мониторинг через API

Настройка сквозного экспорта телеметрии балансировщика в систему мониторинга Prometheus.

#### Вариант А: Нативный экспорт метрик в Angie OSS

Angie предоставляет единый управляющий порт для отдачи нативного Prometheus-скрейпа и детального JSON REST API.

**Конфигурация `/etc/angie/http.d/monitoring.conf`:**

```nginx
# В основном контексте объявляем status_zone для виртуального хоста
server {
    listen 80;
    server_name shop.company.internal;
    status_zone shop_frontend;

    location /api/ {
        status_zone shop_api_location;
        proxy_pass http://shop_api_upstream;
    }
}

upstream shop_api_upstream {
    zone shop_api_upstream_zone 256k;
    server 10.50.1.10:8080;
    server 10.50.1.11:8080;
}

# Служебный хост мониторинга (доступен только для скрейпа Prometheus и локальной отладки)
server {
    listen 127.0.0.1:9113;
    server_name 127.0.0.1;
    access_log off;

    # Нативный Prometheus эндпоинт
    location = /metrics {
        prometheus all;
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        deny all;
    }

    # REST API статуса Angie в формате JSON
    location /status/ {
        api /status/;
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        deny all;
    }
}
```

#### Вариант Б: Экспорт метрик Nginx OSS через `nginx-prometheus-exporter`

Для стандартного Nginx OSS активируется модуль `stub_status`, к которому подключается демон `nginx-prometheus-exporter`.

1. **Конфигурация виртуального хоста `/etc/nginx/conf.d/stub_status.conf`:**
   ```nginx
   server {
       listen 127.0.0.1:8080;
       server_name localhost;
       access_log off;

       location = /stub_status {
           stub_status;
           allow 127.0.0.1;
           deny all;
       }
   }
   ```

2. **Systemd unit экспортера `/etc/systemd/system/nginx-prometheus-exporter.service`:**
   ```ini
   [Unit]
   Description=Nginx Prometheus Exporter
   After=network.target nginx.service

   [Service]
   Type=simple
   User=prometheus
   Group=prometheus
   ExecStart=/usr/local/bin/nginx-prometheus-exporter \
       -nginx.scrape-uri=http://127.0.0.1:8080/stub_status \
       -web.listen-address=:9113
   Restart=on-failure
   RestartSec=5s

   [Install]
   WantedBy=multi-user.target
   ```

3. **Запуск и проверка сервиса:**
   ```bash
   systemctl daemon-reload
   systemctl enable --now nginx-prometheus-exporter
   systemctl status nginx-prometheus-exporter --no-pager
   # → Active: active (running) since Sat 2026-10-17 14:00:00 UTC; 5s ago
   # → Main PID: 4521 (nginx-prometheu)
   ```

---

### Сценарий 6: Graceful Maintenance (Вывод узла из пула без разрыва сессий)

При проведении плановых технических работ на сервере приложений узел необходимо вывести из балансировки так, чтобы текущие активные запросы завершились штатно, а новые перестали поступать.

#### Способ 1: Статический флаг `down` в Nginx OSS / Angie

1. Редактируется конфигурационный файл `/etc/nginx/conf.d/upstream.conf`:
   ```nginx
   upstream app_cluster {
       zone app_cluster_zone 128k;
       server 10.0.0.1:8080;
       server 10.0.0.2:8080 down; # Узел помечен как административно отключенный
   }
   ```
2. Применяется reload:
   ```bash
   nginx -t && nginx -s reload
   # → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
   # → nginx: configuration file /etc/nginx/nginx.conf test is successful
   # → # Мастер-процесс плавно завершает обслуживание воркеров без разрыва активных соединений
   ```

#### Способ 2: Динамический вывод через REST API (Angie / Nginx Plus)

В Angie узел переводится в состояние `down` на лету через HTTP-запрос без перезагрузки веб-сервера:

```bash
# Перевод сервера в режим административного выключения (down)
curl -X PATCH -d '{"down": true}' \
     -H "Content-Type: application/json" \
     http://127.0.0.1:9113/status/http/upstreams/app_cluster/servers/10.0.0.2:8080
# → {"down":true,"weight":1,"max_conns":0,"max_fails":1,"fail_timeout":10}

# Возврат сервера в строй после обслуживания
curl -X PATCH -d '{"down": false}' \
     -H "Content-Type: application/json" \
     http://127.0.0.1:9113/status/http/upstreams/app_cluster/servers/10.0.0.2:8080
# → {"down":false,"weight":1,"max_conns":0,"max_fails":1,"fail_timeout":10}
```

---

## Операции и команды

### Валидация синтаксиса и безопасный reload

Перед применением любых изменений в upstream или health checks обязательна проверка конфигурационных файлов:

```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

nginx -s reload
# → # сигнал SIGHUP отправлен мастер-процессу, воркеры перезапущены без разрыва соединений
```

Для серверов Angie:
```bash
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

angie -s reload
# → # мастер-процесс Angie обновил конфигурацию на лету
```

---

### Запрос статуса Upstream через REST API Angie

```bash
curl -s http://127.0.0.1:9113/status/http/upstreams/shop_api_upstream | jq .
# → {
# →   "peers": [
# →     {
# →       "id": 0,
# →       "server": "10.50.1.10:8080",
# →       "state": "up",
# →       "active": 4,
# →       "requests": 14250,
# →       "responses": { "1xx": 0, "2xx": 14210, "3xx": 10, "4xx": 25, "5xx": 5 },
# →       "health": { "fails": 0, "passes": 1420 }
# →     },
# →     {
# →       "id": 1,
# →       "server": "10.50.1.11:8080",
# →       "state": "up",
# →       "active": 6,
# →       "requests": 14310,
# →       "responses": { "1xx": 0, "2xx": 14280, "3xx": 5, "4xx": 20, "5xx": 5 },
# →       "health": { "fails": 0, "passes": 1425 }
# →     }
# →   ],
# →   "keepalive": 18,
# →   "zombies": 0
# → }
```

---

### Проверка базовых счетчиков `stub_status`

```bash
curl -s http://127.0.0.1:8080/stub_status
# → Active connections: 42
# → server accepts handled requests
# →  125430 125430 384120
# → Reading: 2 Writing: 8 Waiting: 32
```

---

### Сбор метрик Prometheus

```bash
# Запрос нативных метрик апстримов Angie
curl -s http://127.0.0.1:9113/metrics | grep -E "^angie_http_upstreams" | head -n 6
# → angie_http_upstreams_server_state{upstream="shop_api_upstream",server="10.50.1.10:8080"} 1
# → angie_http_upstreams_server_state{upstream="shop_api_upstream",server="10.50.1.11:8080"} 1
# → angie_http_upstreams_server_requests_total{upstream="shop_api_upstream",server="10.50.1.10:8080"} 14250
# → angie_http_upstreams_server_requests_total{upstream="shop_api_upstream",server="10.50.1.11:8080"} 14310
# → angie_http_upstreams_server_responses_total{code="2xx",upstream="shop_api_upstream",server="10.50.1.10:8080"} 14210
# → angie_http_upstreams_server_responses_total{code="5xx",upstream="shop_api_upstream",server="10.50.1.10:8080"} 5
```

---

### Трассировка работы Upstream в логах доступа

Рекомендуемый расширенный формат логирования в `/etc/nginx/nginx.conf`:

```nginx
log_format upstream_telemetry '$remote_addr - [$time_local] "$request" '
                              'status=$status upstream_status=$upstream_status '
                              'backend="$upstream_addr" response_time=$upstream_response_time '
                              'connect_time=$upstream_connect_time header_time=$upstream_header_time';
```

Команды анализа логов:

```bash
# Поиск запросов, в которых происходило переключение на резервный узел или повтор
awk '$0 ~ /upstream_status=[0-9]+, / {print $0}' /var/log/nginx/access.log | head -n 2
# → 192.168.1.50 - [17/Oct/2026:14:10:02 +0000] "GET /api/v1/items HTTP/1.1" status=200 upstream_status=502, 200 backend="10.10.1.11:8080, 10.10.1.12:8080" response_time=0.002, 0.045 connect_time=0.001, 0.002 header_time=0.002, 0.044

# Топ 5 самых медленных ответов бэкендов (> 1.5 секунды)
awk '$upstream_response_time > 1.5 {print $upstream_response_time, $upstream_addr, $request}' /var/log/nginx/access.log | sort -rn | head -n 5
# → 3.450 10.10.1.11:8080 GET /api/v1/reports/pdf HTTP/1.1
# → 2.120 10.10.1.12:8080 POST /api/v1/checkout HTTP/1.1

# Анализ распределения трафика по узлам пула
awk '{for(i=1;i<=NF;i++) if($i ~ /^backend=/) print $i}' /var/log/nginx/access.log | sort | uniq -c | sort -rn
# → 45210 backend="10.10.1.11:8080"
# → 44980 backend="10.10.1.12:8080"
```

---

### Анализ сетевых сокетов к Upstream

```bash
# Проверка количества активных TCP-соединений между Nginx и бэкендами
ss -tnp '( dport = :8080 )' | head -n 3
# → State    Recv-Q   Send-Q     Local Address:Port      Peer Address:Port   Process
# → ESTAB    0        0            10.10.1.5:41234        10.10.1.11:8080    users:(("nginx",pid=1542,fd=12))
# → ESTAB    0        0            10.10.1.5:41236        10.10.1.12:8080    users:(("nginx",pid=1542,fd=14))

# Подсчет соединений в разрезе статусов TCP
ss -tan '( dport = :8080 )' | awk '{print $1}' | sort | uniq -c
# → 1 State
# → 34 ESTAB
# → 4 TIME-WAIT
```

---

### Тестирование health-эндпоинта бэкенда напрямую

```bash
# Проверка ответа целевого узла в обход балансировщика
curl -Iv -H "Host: api.company.internal" http://10.10.1.11:8080/healthz
# → *   Trying 10.10.1.11:8080...
# → * Connected to 10.10.1.11 (10.10.1.11) port 8080
# → > GET /healthz HTTP/1.1
# → > Host: api.company.internal
# → > User-Agent: curl/8.5.0
# → > Accept: */*
# → < HTTP/1.1 200 OK
# → < Content-Type: application/json
# → < Content-Length: 15
# → {"status":"ok"}
```

---

### Имитация сбоя узла (Failover Test)

```bash
# 1. Остановка целевого сервиса на ноде бэкенда
systemctl stop backend-app@node1
# → # служба остановлена

# 2. Выполнение запроса через балансировщик и проверка статуса ответа
curl -s -o /dev/null -w "HTTP: %{http_code} | Total time: %{time_total}s\n" http://api.company.internal/api/v1/ping
# → HTTP: 200 | Total time: 0.015s

# 3. Проверка в логе ошибок Nginx факта фиксации сбоя и переключения
grep -E "connect\(\) failed|upstream.*failed" /var/log/nginx/error.log | tail -n 1
# → 2026/10/17 14:15:30 [error] 1542#1542: *1042 connect() failed (111: Connection refused) while connecting to upstream, client: 192.168.1.100, server: api.company.internal, request: "GET /api/v1/ping HTTP/1.1", subrequest: "", upstream: "http://10.10.1.11:8080/api/v1/ping", host: "api.company.internal"
```

---

## Диагностика и устранение неполадок

### Сводная таблица неисправностей

| Симптом | Первопричина | Диагностика | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Флапинг сервера (Up/Down flapping)** | Занижен `fail_timeout`, нестабильный endpoint или пограничный `proxy_connect_timeout`. | `grep "upstream server" /var/log/nginx/error.log` циклические сообщения отключения/включения. | Увеличить `fail_timeout` до 30s-60s; поднять таймаут пробы; стабилизировать код бэкенда. |
| **«Эффект черной дыры» при `least_conn`** | Сбойный бэкенд мгновенно рвет соединение (RST). Алгоритм считает узел свободным (0 активных сокетов) и шлет туда все запросы. | `awk` по логам: 90%+ клиентских запросов направляются на один сбоящий сервер с 502/RST. | Обязательно добавить `max_fails=3 fail_timeout=15s;` и настроить `proxy_next_upstream error timeout http_502;`. |
| **Retry Storm / Каскадное падение кластера** | `proxy_next_upstream` не ограничен параметрами `tries` и `timeout`. При сбое одного узла клиенты начинают перебирать все остальные. | Всплеск задержек `upstream_response_time`, массовые `504 Gateway Timeout` по всем серверам. | Жестко задать `proxy_next_upstream_tries 3;` и `proxy_next_upstream_timeout 5s;`. |
| **Рассинхронизация счетчиков отказов воркеров** | Отсутствует директива `zone` в блоке `upstream`. Каждый воркер ведет отдельный учет сбоев. | Клиенты продолжают получать спорадические ошибки 502 спустя долгое время после падения бэкенда. | Добавить директиву `zone <name> 256k;` во все блоки `upstream`. |
| **`502 Bad Gateway` после включения slow_start** | Время `slow_start` слишком мало, приложение не успело прогреть JVM/кэш/пулы. | Ошибки `502` возникают ровно через 5-10 секунд после перехода сервера в статус UP. | Увеличить `slow_start` до 45s-90s в зависимости от реального профиля разогрева сервиса. |
| **`504 Gateway Timeout` при живом бэкенде** | Завышен `proxy_read_timeout` при подвисании запроса в очереди приложения. | `curl -w "%{time_total}"` показывает зависание на 60с (стандартный таймаут Nginx). | Снизить `proxy_read_timeout` до разумного SLA (5s-10s); настроить таймауты внутри бэкенда. |
| **POST-запросы падают без переключения** | Неидемпотентный метод не повторяется по умолчанию при сетевом сбое. | В логах ошибка 502 без повторной попытки передачи на следующий узел (`upstream_addr` содержит только один IP). | Добавить флаг `non_idempotent` в `proxy_next_upstream` (при условии поддержки идемпотентности бэкендом). |
| **Активные проверки не ходят или фейлятся** | Ошибка синтаксиса `check_http_send`, отсутствует заголовок `Host`, или сервер возвращает код не из `expect_alive`. | Запрос `/status/` возвращает статус `down` при доступном сокете; проверка через `curl` на healthz возвращает 400 Bad Request. | Проверить `check_http_send`: использовать HTTP/1.1 с явным заголовком `Host:` и двойным переводом строки `\r\n\r\n`. |
| **Разрыв соединения вместо переключения upstream** | Отключена буферизация (`proxy_buffering off`) или переполнен `proxy_buffer_size`. | В логе ошибок: `transferring response: ... upstream prematurely closed connection`. | Включить `proxy_buffering on;` и увеличить буферы `proxy_buffer_size 16k;`, `proxy_buffers 8 32k;`. |

---

### Диагностические команды SRE

```bash
# 1. Поиск критических ошибок upstream в error.log
grep -E "(no live upstreams|connect\(\) failed|upstream timed out)" /var/log/nginx/error.log | tail -n 2
# → 2026/10/17 14:20:10 [error] 1542#1542: *1120 no live upstreams while connecting to upstream, client: 192.168.1.5, server: api.company.internal, request: "GET /api/v1/status HTTP/1.1", upstream: "http://production_backend/api/v1/status", host: "api.company.internal"

# 2. Проверка заполнения буферов proxy на диск (признак нехватки памяти под заголовки/тело)
grep "buffered to a temporary file" /var/log/nginx/error.log | wc -l
# → 0

# 3. Проверка превышения заголовков upstream
grep "upstream sent too big header" /var/log/nginx/error.log
# → # пустой вывод означает, что размер proxy_buffer_size достаточен

# 4. Анализ кодов ответов апстрима по логу доступа
awk '{for(i=1;i<=NF;i++) if($i ~ /^upstream_status=/) print $i}' /var/log/nginx/access.log | sort | uniq -c
# → 142050 upstream_status=200
# → 120 upstream_status=404
# → 12 upstream_status=502
```

---

## Рекомендации и Best Practices

### Надежность и SRE-практики

1. **Разделение Liveness и Readiness проверок:**
   - **Liveness (Живучесть процесса):** Быстрый легковесный пинг (например, `/healthz/live`), проверяющий исключительно то, что веб-сервер бэкенда запущен и event loop не заблокирован. Этот эндпоинт никогда не должен проверять внешние зависимости (СУБД, Redis, сторонние API).
   - **Опасность Deep Health Checks:** Если эндпоинт проверки бэкенда делает запрос в PostgreSQL, то при временной недоступности базы данных балансировщик снимет **все** веб-серверы кластера. В результате вместо корректной деградации приложения (с выдачей страницы ошибки или кэшированного контента) наступает полная недоступность инфраструктуры с кодом 502 на уровне Nginx.
2. **Правило суммарного бюджета времени (SLA Budget):**
   Суммарное время перебора узлов не должно превышать таймаут клиентского соединения. Формула проверки:
   $$\text{Client Timeout} \ge \text{proxy\_next\_upstream\_tries} \times \text{proxy\_connect\_timeout} + \text{proxy\_read\_timeout}$$
   Если `proxy_connect_timeout` равен 2с, а число попыток равно 3, то только на подключение может уйти 6 секунд. Значение `proxy_next_upstream_timeout` должно жестко ограничивать этот процесс.
3. **Изоляция Backup-узлов:**
   Не используйте резервные узлы (`backup`) для части регулярного трафика. Резервный узел должен быть готов принять 100% критического трафика при падении основных серверов, либо возвращать статическую страницу заглушки (Maintenance page).
4. **Оповещения (Prometheus Alerting Rules):**
   Настройте алерты на следующие критические условия:
   - Доля недоступных серверов в пуле $\ge 30\%$ (риск деградации емкости).
   - Рост 5xx ошибок от бэкендов $> 1\%$ за 5 минут.
   - Срабатывание `no live upstreams` (полный отказ сервиса).

### Производительность

1. **Использование `zone` во всех блоках `upstream`:**
   Разделяемая память исключает расщепление счетчиков сбоев между процессами и обеспечивает атомарную изоляцию упавших нод.
2. **Пул постоянных соединений (`keepalive`):**
   Включение `keepalive` в `upstream` обязательно для высоконагруженных сервисов. Это устраняет оверхед на TCP handshake и TLS negotiation на каждый клиентский запрос:
   ```nginx
   upstream app_pool {
       zone app_pool_zone 256k;
       server 10.10.1.11:8080;
       server 10.10.1.12:8080;
       keepalive 64;
   }
   ```
3. **Оптимизация интервалов активных проверок:**
   Не устанавливайте интервалы проверки ниже 1–2 секунд без крайней необходимости. При кластере из 10 балансировщиков и интервале 200мс бэкенд будет получать 50 проверочных запросов в секунду только от систем мониторинга, что создает паразитную нагрузку.

### Безопасность

1. **Защита интерфейсов телеметрии:**
   Эндпоинты `/metrics`, `/stub_status` и `/status/` должны быть жестко изолированы. Привязывайте их к `127.0.0.1`, выделенному management-интерфейсу или закрывайте директивами `allow/deny` и базовой аутентификацией `auth_basic`.
2. **Скрытие служебных заголовков бэкендов:**
   Используйте `proxy_hide_header` для маскирования внутренней информации инфраструктуры:
   ```nginx
   proxy_hide_header X-Powered-By;
   proxy_hide_header Server;
   ```
3. **Защита health-эндпоинтов приложения:**
   Синтетические проверки не должны содержать чувствительных данных (ключи API, внутренние токены) в query-параметрах URI.

---

## Дополнительная информация

### См. также

- [Алгоритмы балансировки нагрузки](./algorithms.md) — обзор Round Robin, Least Connections, IP Hash и консистентного хеширования.
- [Практическая конфигурация балансировки](./practical_configuration.md) — архитектура директив `upstream`, `proxy_pass` и тонкая настройка параметров соединения.
- [Основные концепции балансировки](./overview_concepts.md) — терминология, многоуровневая балансировка и эталонные модели.
- [Динамическое разрешение DNS в Upstream](./dynamic_dns_resolution.md) — работа с директивами `resolver`, параметром `resolve` и Service Discovery.
- [Сессионная липкость (Sticky Sessions)](./sticky_sessions.md) — маршрутизация клиентов по cookies и механизмам `sticky`.
- [Дополнительная информация и сравнение балансировщиков](./additional_info_and_comparisons.md) — архитектурные различия Nginx, HAProxy, Envoy и Traefik.
- [Мониторинг Nginx с VTS-модулем, Prometheus и Grafana](../../Operations/nginx_vts_monitoring_setup.md) — развертывание модуля VTS, дашборды и PromQL метрики.
- [Анализ и парсинг логов Nginx](../../Operations/nginx_log_analysis.md) — методы обработки access и error логов утилитами CLI и GoAccess.
- [Диагностика и устранение неисправностей Nginx](../../Operations/nginx_troubleshooting.md) — систематический траблшутинг сетевых и системных сбоев веб-сервера.
