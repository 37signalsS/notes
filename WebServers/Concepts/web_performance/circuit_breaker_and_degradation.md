# Circuit Breaker и Degradation Patterns для веб-производительности

**Актуально для:** Nginx 1.26+, Angie 1.8+ / 1.12.x, HAProxy 2.8+ / 3.0+

## Определения

- **Circuit Breaker (Прерыватель цепи / Автоматический выключатель)** — паттерн архитектурной устойчивости (resilience), предотвращающий лавинообразные обращения к нестабильному или недоступному бэкенду. Автомат состояний отслеживает частоту ошибок и при превышении порога переводит цепь в разомкнутое состояние (**Open**), мгновенно возвращая клиенту запасной ответ (**Fallback**) без передачи запроса деградирующему узлу.
- **Graceful Degradation (Контролируемая деградация)** — стратегия намеренного и управляемого снижения объема или качества предоставляемых сервисом функций при возникновении сбоев, дефиците вычислительных ресурсов или перегрузке. Обеспечивает сохранение работоспособности критического пути обслуживания за счет отключения вторичных сервисов.
- **Fallback (Запасной сценарий / Синтетический ответ)** — резервный механизм формирования ответа клиенту в условиях недоступности основного обработчика. Включает отдачу устаревшего кэша (`stale-if-error`), статических аварийных HTML-страниц или облегченных заглушек данных.
- **Load Shedding (Сброс нагрузки)** — намеренный контролируемый отказ в обработке части входящих запросов на сетевой границе (обычно с кодом `503 Service Unavailable` и заголовком `Retry-After`) при исчерпании системной емкости. В отличие от Circuit Breaker, защищающего систему от *внешней зависимости*, Load Shedding спасает *сам сервис/прокси* от насыщения очередей и исчерпания памяти.
- **Backpressure (Обратное давление)** — механизм сигнализирования нижестоящим компонентам или клиентам о невозможности справиться с текущим объемом нагрузки для регуляции темпа входящего потока.
- **Outlier Detection (Выявление и изоляция аномальных узлов)** — динамический мониторинг пула бэкендов в реальном времени, при котором узлы с аномальным количеством 5xx-ошибок или задержек временно изолируются от балансировки без ожидания планового интервала проверок.
- **Retry Amplification (Усиление повторных попыток / Retry Storm)** — мультипликативный эффект в распределенных системах, при котором повторы неудачных запросов на каждом уровне инфраструктуры многократно умножают входящую нагрузку на деградирующий бэкенд, переводя частичный сбой в полный коллапс.
- **Retry Budget (Бюджет повторов)** — эксплуатационный лимит, ограничивающий долю повторных запросов фиксированным процентом (как правило, не более 10–20%) от суммарного валидного трафика.
- **Failover (Отказоустойчивое переключение)** — процедура прозрачного автоматического перенаправления клиентского запроса на резервный узел (`backup`) или альтернативный сервер группы при фиксации сбоя на выбранном бэкенде.
- **Thundering Herd (Стадо бизонов / Лавина запросов)** — одновременный всплеск однотипных обращений сотен клиентов к источнику данных при инвалидации горячего кэша или возвращении упавшего бэкенда в работу.
- **Stale-If-Error** — стандарт расширения HTTP-кэширования по RFC 5861 / RFC 9111, разрешающий кэширующему прокси отдавать просроченный контент клиенту в случае возврата вышестоящим сервером кодов 5xx или истечения сетевых таймаутов.

## Основные концепции

### Архитектура и конечный автомат Circuit Breaker

Классический Circuit Breaker реализуется в виде конечного автомата с тремя базовыми состояниями:

```
                  ┌────────────────────────────────────────┐
                  │                 Closed                 │
                  │       (Цепь замкнута / Норма)          │
                  └──────┬──────────────────────────▲──────┘
                         │                          │
           Порог ошибок  │                          │ Серия успешных
            превышен     │                          │ пробных запросов
                         ▼                          │
                  ┌──────────────┐          ┌───────┴──────┐
                  │     Open     │          │  Half-Open   │
                  │ (Разомкнута) ├─────────►│(Полуоткрыта) │
                  └──────────────┘ Истек    └───────┬──────┘
                                   таймаут          │
                                   ожидания         │ Единичная
                                                    │ ошибка
                                                    ▼
                                            (Возврат в Open)
```

1. **Closed (Замкнуто):** Нормальное функционирование. Все запросы направляются бэкендам. Статистика сбоев (таймауты, сетевые сбросы, коды 500/502/503/504) аккумулируется в скользящем окне.
2. **Open (Разомкнуто):** Активируется при превышении допустимого порога ошибок (например, более 50% сбоев за 10 секунд или 3 последовательных тайм-аута). Прокси прекращает отправку реального клиентского трафика на данный узел. Все запросы немедленно замыкаются на запасной путь (**Fail-fast** либо **Fallback**), предотвращая накопление зависших соединений.
3. **Half-Open (Полуразомкнуто):** По истечении таймера ожидания (`fail_timeout` в Nginx/Angie, recovery interval) прокси пропускает строго ограниченную порцию запросов (пробный трафик / канареечные зонды) к проверяемому бэкенду. Если эти запросы завершаются успешно — узел признается здоровым, и автомат возвращается в состояние **Closed**. При фиксации хотя бы одной ошибки автомат немедленно возвращается в состояние **Open** с новым интервалом ожидания.

#### Специфика реализации в L7 Reverse Proxy

На уровне высокопроизводительных веб-серверов и прокси (Nginx, Angie, HAProxy) логика Circuit Breaker реализуется через встроенные механизмы пассивных проверок, изоляции пиров и разделяемой памяти:

| Параметр / Характеристика | Nginx OSS | Angie (OSS / PRO) | HAProxy |
| :--- | :--- | :--- | :--- |
| **Синхронизация состояния** | Нет в OSS (учет `max_fails` ведется локально в памяти каждого рабочего процесса `worker`). | Централизованно в Shared Memory через директиву `zone`. Состояние узла общее для всех процессов. | Единый процесс / общий пул потоков; единая таблица состояний прокси. |
| **Критерий размыкания цепи** | `max_fails` последовательных ошибок за интервал `fail_timeout`. | `max_fails` + `fail_timeout` (пассивно) либо проактивный модуль `check` (активно). | Параметры `fall <N>`, `inter <T>` активного мониторинга либо сброс через `stick-table`. |
| **Восстановление (Half-Open)** | По истечении `fail_timeout` первый поступивший клиентский запрос отправляется бэкенду как зонд. | По истечении `fail_timeout` или после `check rise=<N>` проверок. Поддержка `slow_start`. | После `rise <N>` успешных проверок подряд с поддержкой `slowstart`. |
| **Действие при Open** | Исключение пира из балансировки, переключение на соседа или `backup`. | Исключение из пула, автоматический перевод на `backup`, фиксация в REST API. | Перевод в статус `DOWN`, перевод трафика на `backup`, отдача `errorfile 503`. |

> [!WARNING]
> В **Nginx OSS** без разделяемой памяти сервер изолируется каждым воркером независимо. Если у вас 16 воркеров и `max_fails=3`, то сбойный бэкенд получит до $16 \times 3 = 48$ ошибочных клиентских запросов, прежде чем будет временно выведен из строя всеми воркерами. В **Angie** использование директивы `zone` внутри `upstream` гарантирует моментальное отключение узла ровно после 3 ошибок суммарно по всему серверу.

---

### Стратегии Graceful Degradation

Деградация организуется по эшелонированному принципу в зависимости от критичности данных и глубины сбоя инфраструктуры:

```
                            Входящий HTTP-запрос
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │   L7 Прокси / Баланс    │
                        └────────────┬────────────┘
                                     │
                        Бэкенд доступен и здоров?
                                     │
                       ┌─────────────┴─────────────┐
                    Да │                            │ Нет (Сбой / Таймаут)
                       ▼                            ▼
            ┌─────────────────────┐    ┌───────────────────────────┐
            │ Стандартный динамик │    │ Уровень 1: Stale-кэш      │
            │   (200 OK + JSON)   │    │ (stale-if-error, < 50 мс) │
            └─────────────────────┘    └────────────┬──────────────┘
                                                    │
                                         Кэш отсутствует/истек?
                                                    │
                                                    ▼
                                       ┌───────────────────────────┐
                                       │ Уровень 2: Backup-сервер  │
                                       │ (Аварийный теплый узел)   │
                                       └────────────┬──────────────┘
                                                    │
                                         Backup недоступен?
                                                    │
                                                    ▼
                                       ┌───────────────────────────┐
                                       │ Уровень 3: Статика        │
                                       │ (Offline HTML / 503 заглу)│
                                       └────────────┬──────────────┘
                                                    │
                                         Исчерпана емкость узла?
                                                    │
                                                    ▼
                                       ┌───────────────────────────┐
                                       │ Уровень 4: Load Shedding  │
                                       │ (Отсечение второстепенных)│
                                       └───────────────────────────┘
```

1. **Кэширующий уровень (Stale-if-error):**
   При падении бэкенда прокси не возвращает клиенту ошибку 502/504, а отдает последнюю сохраненную в локальном кэше копию данных. Это обеспечивает стабильный TTFB (< 50 мс) и нулевой даунтайм для пользователей контентных сайтов, витрин каталогов и новостных лент.
2. **Резервный уровень (Warm/Cold Backup):**
   Запрос перенаправляется на выделенный резервный узел (директива `backup` в Nginx/Angie/HAProxy), который в обычных условиях не принимает клиентскую нагрузку и сохраняет чистый пул соединений и процессорный резерв.
3. **Статический аварийный уровень (Static Fallback):**
   Отдача предварительно сформированного легковесного автономного HTML/JSON-документа прямо с локального диска прокси (через внутренние локации `error_page ... = @fallback`). Клиент получает структурированное уведомление о проведении регламентных работ без каскадной перегрузки серверных процессов.
4. **Приоритетный сброс нагрузки (Priority Load Shedding):**
   При предельной утилизации CPU/RAM веб-сервер сбрасывает второстепенный трафик (поисковые боты, сбор метрик, неавторизованные запросы, виджеты персональных рекомендаций) с кодом `503 Service Unavailable` и `Retry-After: 30`, высвобождая сетевые сокеты для ядра системы (авторизация, оформление заказов, процессинг транзакций). Подробно архитектура раскрыта в **[Сброс нагрузки (Load Shedding)](../../../CI-CD/Core_Concepts/load_shedding.md)**.

---

### Влияние на Core Web Vitals и пользовательский опыт

Корректность настройки Circuit Breaker и механизмов деградации напрямую определяет ключевые метрики производительности веб-приложений:

| Сценарий обработки | TTFB (Time to First Byte) | LCP (Largest Contentful Paint) | INP (Interaction to Next Paint) | CLS (Cumulative Layout Shift) |
| :--- | :--- | :--- | :--- | :--- |
| **Нормальная работа (Бэкенд в норме)** | 20–100 мс | < 1.2 с (Good) | < 100 мс (Good) | 0.00 (Идеально) |
| **Сбой бэкенда БЕЗ Circuit Breaker** | 10–60 секунд (тайм-аут ОС / прокси) | 10–60 с (Полный провал SLO) | > 500 мс (Интерфейс «зависает») | Не оценивается (экран 504 Gateway Timeout) |
| **С Circuit Breaker + stale-if-error** | < 20 мс (отдача из памяти/диска) | < 1.2 с (Good) | < 100 мс (Good) | 0.00 (Макет стабилен, контент на месте) |
| **С Circuit Breaker + failover на Backup** | 60–150 мс (задержка на попытку) | < 1.8 с (Good) | < 120 мс (Good) | 0.00 (Сдвиги отсутствуют) |
| **С Degradation: Skeleton-страница** | < 50 мс (быстрый возврат каркаса) | 2.5–5.0 с (LCP откладывается до фонового XHR) | 150–300 мс (Ожидание гидратации) | **> 0.25 (POOR)** при отсутствии фиксированных габаритов контейнеров! |
| **С Degradation: Static Offline HTML** | < 30 мс | < 0.8 с (Легковесный документ) | < 50 мс | 0.00 |

#### Ловушка Skeleton-страниц для CLS

Распространенная ошибка фронтенд-деградации — возврат клиенту пустого скелетона (placeholder skeleton) без явной фиксации геометрических размеров контейнеров (`min-height`, `aspect-ratio`).
- Если динамический бэкенд не отвечает, и клиентский скрипт заменяет скелетон на сообщение об ошибке или запоздалый блок данных другого размера, страница испытывает резкую визуальную перекомпоновку.
- Показатель **CLS (Cumulative Layout Shift)** превышает критический порог 0.25, что штрафуется поисковыми алгоритмами и раздражает пользователя.
- **Инженерный стандарт:** Использование `stale-if-error` на прокси предпочтительнее возврата скелетона, так как устаревший валидный контент гарантирует **нулевой сдвиг макета (CLS = 0)**.

---

### Математика Retry Storm, Retry Amplification и защита

Если на бэкенде возникает сбой, наивная настройка автоматических повторных попыток (retries) превращает временное замедление в катастрофический каскадный отказ.

Пусть $RPS_{in}$ — входящий поток запросов, $P_{err}$ — вероятность сбоя бэкенда, $N_{tries}$ — лимит попыток проксирования. Итоговый поток на инфраструктуру бэкендов $RPS_{upstream}$ описывается выражением:

$$RPS_{upstream} = RPS_{in} \cdot \left(1 + P_{err} \cdot (N_{tries} - 1)\right)$$

При 100% сбое бэкенда ($P_{err} = 1$) и значении `proxy_next_upstream_tries 4` входящие 1 000 RPS превратятся в **4 000 RPS** на уже лежащие серверы приложений. Ни один сервер не способен оправиться от перегрузки под таким штормом.

#### Опасность неидемпотентных методов (`non_idempotent`)

По умолчанию Nginx, Angie и HAProxy **никогда не повторяют** запросы с методами `POST`, `LOCK`, `PATCH`, если соединение с upstream уже было установлено и часть данных передана.
- Если бэкенд успел списать средства с карты клиента или создать заказ в базе данных, но оборвал соединение до завершения передачи HTTP-заголовков, автоматический повтор запроса без распределенного ключа идемпотентности приведет к **повторной финансовой транзакции** или дублированию сущностей.
- Флаг `non_idempotent` в директиве `proxy_next_upstream` разрешается использовать исключительно в шлюзах, где прикладной бэкенд аппаратно поддерживает валидацию заголовка `Idempotency-Key`.

#### Концепция Retry Budget (SRE)

В соответствии с практиками Google SRE и стандартами устойчивости распределенных систем, повторные попытки должны квотироваться:
- Доля ретраев в системе не должна превышать **10–20%** от общего пула запросов.
- Если общий процент ошибок системы превышает 10%, все повторы немедленно подавляются, и клиенту возвращается ошибка первого уровня, чтобы дать сервису возможность восстановить соединения.

---

### Защита от Thundering Herd (Лавины запросов)

При восстановлении упавшего бэкенда или истечении срока хранения популярного кэшированного объекта сотни одновременных рабочих процессов прокси могут одновременно ринуться к бэкенду за свежими данными.

Для нейтрализации эффекта применяются три директивы:

```nginx
# 1. Мьютекс на заполнение кэша: только 1 запрос идет к бэкенду, остальные ждут
proxy_cache_lock on;
proxy_cache_lock_timeout 5s;
proxy_cache_lock_age 5s;

# 2. Фоновое асинхронное обновление: клиенты получают stale, пока 1 запрос обновляет кэш
proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
proxy_cache_background_update on;
```

- `proxy_cache_lock on;` заставляет параллельные запросы к одному и тому же URI ждать формирования ответа первым потоком.
- `proxy_cache_background_update on;` полностью скрывает задержку обновления кэша от пользователей.

---

## Практические сценарии

### Сценарий 1: Production-Ready L7 Circuit Breaker в Angie / Nginx

Конфигурация с общей зоной памяти (`zone`), пассивным мониторингом, защитой от лавины ретраев, холодным резервом (`backup`) и отдачей устаревшего кэша при любых сбоях бэкенда.

```nginx
# Определение зоны разделяемой памяти кэша на диске
proxy_cache_path /var/cache/nginx/api_cache 
                 levels=1:2 
                 keys_zone=api_cache_zone:20m 
                 max_size=2g 
                 inactive=1h 
                 use_temp_path=off;

upstream production_api {
    # В Angie/Nginx Plus: разделяемая память исключает рассинхронизацию воркеров
    zone production_api_zone 256k;

    # Основные рабочие узлы
    server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;

    # Резервный узел: трафик идет сюда ТОЛЬКО если оба основных выбиты по max_fails
    server 10.0.1.12:8080 backup;

    # Пул постоянных соединений к бэкендам для снижения оверхеда на handshake
    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}

server {
    listen 80;
    server_name api.internal.net;

    location /v1/ {
        proxy_pass http://production_api;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # --- НАСТРОЙКИ СЕТЕВЫХ ТАЙМАУТОВ ---
        # Быстрый фейл при сбое рукопожатия TCP/TLS
        proxy_connect_timeout 2s;
        proxy_send_timeout 4s;
        proxy_read_timeout 4s;

        # --- CIRCUIT BREAKER & RETRY BUDGET ---
        # Повторять только при явных сетевых ошибках и серверных сбоях 5xx
        proxy_next_upstream error timeout invalid_header http_500 http_502 http_503 http_504;
        
        # Строгое ограничение: суммарно не более 3 попыток (первичная + 2 повтора)
        proxy_next_upstream_tries 3;
        
        # Общий бюджет времени на все попытки (не должен превышать клиентский таймаут)
        proxy_next_upstream_timeout 5s;

        # --- DEGRADATION: STALE-IF-ERROR FALLBACK ---
        proxy_cache api_cache_zone;
        proxy_cache_key "$scheme$request_method$host$request_uri";
        proxy_cache_valid 200 302 10m;
        proxy_cache_valid 404 30s;

        # Отдавать просроченный кэш при сбоях бэкенда или в процессе обновления
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;

        # Защита от Thundering Herd
        proxy_cache_lock on;
        proxy_cache_lock_timeout 3s;
        proxy_cache_lock_age 3s;

        # Информационный заголовок статуса кэша для мониторинга
        add_header X-Cache-Status $upstream_cache_status always;
        add_header X-Upstream-Addr $upstream_addr always;
    }
}
```

#### Валидация работы конфигурации

1. Проверка синтаксиса и перезагрузка конфигурации:
   ```bash
   nginx -t
   # → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
   # → nginx: configuration file /etc/nginx/nginx.conf test is successful

   nginx -s reload
   ```

2. Первичный прогрев кэша (штатный ответ от основного узла):
   ```bash
   curl -i http://api.internal.net/v1/catalog
   # → HTTP/1.1 200 OK
   # → X-Cache-Status: MISS
   # → X-Upstream-Addr: 10.0.1.10:8080
   ```

3. Имитация аварии первого основного узла (блокировка порта на бэкенде):
   ```bash
   # Выполняется на узле 10.0.1.10
   iptables -A INPUT -p tcp --dport 8080 -j DROP
   ```

4. Проверка прозрачного failover на второй основной узел (TTFB минимален):
   ```bash
   curl -i http://api.internal.net/v1/catalog
   # → HTTP/1.1 200 OK
   # → X-Cache-Status: HIT
   # → X-Upstream-Addr: 10.0.1.10:8080, 10.0.1.11:8080
   ```

5. Имитация одновременного падения всех основных узлов:
   ```bash
   # Выполняется на узле 10.0.1.11
   iptables -A INPUT -p tcp --dport 8080 -j DROP

   # Запрос при выбитых основных узлах: отдача устаревшего кэша (Degradation)
   curl -i http://api.internal.net/v1/catalog
   # → HTTP/1.1 200 OK
   # → X-Cache-Status: STALE
   # → X-Upstream-Addr: 10.0.1.10:8080, 10.0.1.11:8080, 10.0.1.12:8080
   ```

---

### Сценарий 2: Bare-Metal Circuit Breaker и Outlier Ejection в HAProxy

HAProxy на bare-metal сервере обеспечивает активный мониторинг, динамическое исключение деградирующих серверов (`Outlier Ejection`), переключение на `backup` и возврат синтетического fallback-ответа при полном отказе пула.

Фрагмент `/etc/haproxy/haproxy.cfg`:

```haproxy
global
    log /dev/log local0 info
    stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners
    stats timeout 30s

defaults
    log     global
    mode    http
    option  httplog
    option  dontlognull
    timeout connect 2s
    timeout client  10s
    timeout server  5s

frontend http_front
    bind 0.0.0.0:80
    default_backend api_cluster

backend api_cluster
    mode http
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200

    # Глобальные параметры проверок для серверов:
    # inter 2s: интервал между проверками
    # fall 3: 3 неудачные проверки переводят узел в DOWN (Circuit Breaker Open)
    # rise 2: 2 успешные проверки возвращают узел в строй (Half-Open -> Closed)
    default-server inter 2s fall 3 rise 2 slowstart 10s maxconn 250

    # Основные рабочие серверы
    server srv1 10.0.2.11:8080 check
    server srv2 10.0.2.12:8080 check

    # Резервный аварийный сервер
    server srv_backup 10.0.2.13:8080 check backup

    # Ограничение повторных попыток при сбое соединения
    retries 2
    option redispatch 1

    # Запасная страница деградации при полном отказе пула (HTTP 503)
    errorfile 503 /etc/haproxy/errors/503_degraded.http
```

Создание шаблона деградированного ответа `/etc/haproxy/errors/503_degraded.http`:

```http
HTTP/1.0 503 Service Unavailable
Cache-Control: no-cache, no-store, must-revalidate
Connection: close
Content-Type: application/json; charset=utf-8
Retry-After: 15

{"status":"degraded","message":"Сервис временно испытывает пиковые нагрузки. Пожалуйста, повторите запрос через 15 секунд.","error_code":"CIRCUIT_BREAKER_ACTIVE"}
```

#### Проверка через Runtime Socket HAProxy:

```bash
# Проверка текущего состояния пиров
echo "show stat" | socat stdio /run/haproxy/admin.sock | cut -d',' -f1,2,18,19,37
# → # pxname,svname,status,weight,check_status
# → api_cluster,srv1,UP,1,L7OK
# → api_cluster,srv2,UP,1,L7OK
# → api_cluster,srv_backup,UP,1,L7OK
# → api_cluster,BACKEND,UP,2,

# Принудительный перевод сервера в режим DRAIN (плановое обслуживание без всплеска 5xx)
echo "set server api_cluster/srv1 state drain" | socat stdio /run/haproxy/admin.sock
# → 

# Проверка обновленного состояния
echo "show servers state api_cluster" | socat stdio /run/haproxy/admin.sock | awk '{print $4, $6}'
# → srv1 2
# → srv2 1
# → srv_backup 1
```

---

### Сценарий 3: Load Shedding и контролируемая деградация на границе Nginx/Angie

При перегрузке инфраструктуры веб-сервер должен сбрасывать низкоприоритетные запросы (тяжелые аналитические выборки, поисковые боты), сохраняя ресурсы для критического бизнес-пути (оплата, оформление заказов).

```nginx
# Определение приоритета запроса по URI и агенту клиента
map $request_uri $is_heavy_request {
    default         0;
    ~^/api/search   1;
    ~^/api/export   1;
    ~^/api/reports  1;
}

# Отдельная зона для жесткого ограничения низкоприоритетных запросов
limit_req_zone $binary_remote_addr zone=heavy_tasks_zone:10m rate=2r/s;
limit_req_status 503;

server {
    listen 80;
    server_name shop.internal.net;

    # Локация для перегруженных/тяжелых эндпоинтов
    location /api/search {
        # При превышении лимита запрос немедленно сбрасывается без очередей
        limit_req zone=heavy_tasks_zone burst=3 nodelay;

        # Перехват ошибки 503 для возврата структурированного fallback
        error_page 503 = @load_shedding_fallback;

        proxy_pass http://backend_cluster;
        proxy_connect_timeout 2s;
        proxy_read_timeout 5s;
    }

    # Fallback-обработчик сброса нагрузки
    location @load_shedding_fallback {
        internal;
        add_header Retry-After 30 always;
        add_header Content-Type "application/json; charset=utf-8" always;
        return 503 '{"error":"Load shedding active","message":"Поисковый сервис временно перегружен. Запрос отклонен для защиты ядра системы. Повторите через 30 с.","retry_after":30}';
    }

    # Критический путь бизнеса (без жесткого shedding)
    location /api/checkout {
        proxy_pass http://backend_cluster;
        proxy_connect_timeout 2s;
        proxy_read_timeout 10s;
    }
}
```

#### Валидация сброса нагрузки через curl:

```bash
# Генерация всплеска запросов на тяжелый эндпоинт
for i in {1..5}; do
  curl -s -i http://shop.internal.net/api/search | grep -E "HTTP/|Retry-After"
done
# → HTTP/1.1 200 OK
# → HTTP/1.1 200 OK
# → HTTP/1.1 503 Service Unavailable
# → Retry-After: 30
# → HTTP/1.1 503 Service Unavailable
# → Retry-After: 30
# → HTTP/1.1 503 Service Unavailable
# → Retry-After: 30
```

---

### Сценарий 4: SSR Degradation со статическим резервом и защитой CLS

При падении Node.js/Next.js/Nuxt SSR-серверов веб-сервер перехватывает ошибки рендеринга и мгновенно отдает статическую версию страницы с фиксированной геометрической сеткой, предотвращая сдвиг макета (CLS).

```nginx
upstream ssr_cluster {
    zone ssr_zone 128k;
    server 127.0.0.1:3000 max_fails=2 fail_timeout=5s;
    server 127.0.0.1:3001 max_fails=2 fail_timeout=5s;
}

server {
    listen 80;
    server_name frontend.internal.net;

    root /var/www/production_build;

    location / {
        proxy_pass http://ssr_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;

        # Быстрый тайм-аут: если SSR не ответил за 1.5 секунды — деградируем
        proxy_connect_timeout 1s;
        proxy_read_timeout 1500ms;

        # Перехват кодов ошибок бэкенда для маршрутизации на fallback
        proxy_intercept_errors on;
        error_page 500 502 503 504 = @static_spa_fallback;
    }

    # Отдача скомпилированного клиентского SPA (Single Page Application)
    # Каркас содержит фиксированные CSS-контейнеры для защиты CLS
    location @static_spa_fallback {
        internal;
        root /var/www/fallback_spa;
        try_files /index.html =503;
        
        # Информирование браузера и CDN о временном характере ответа
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header X-Degradation-Fallback "Static-SPA-Fallback" always;
    }
}
```

---

### Сценарий 5: Мониторинг состояния Circuit Breaker и SRE-алертинг

Для своевременного обнаружения деградации и размыкания цепи на прокси настраивается сбор метрик в Prometheus и правила оповещения Alertmanager.

#### 1. Модуль метрик Angie / Nginx VTS

В Angie OSS метрики апстримов доступны из коробки через REST API:
```nginx
server {
    listen 127.0.0.1:8888;
    location /status/ {
        status;
    }
    location /p_status {
        prometheus all;
    }
}
```

#### 2. Правила Prometheus Alertmanager (`/etc/prometheus/alerts_circuit_breaker.yml`)

```yaml
groups:
  - name: circuit_breaker_alerts
    rules:
      # Алерт: Бэкенд переведен в статус UNHEALTHY / DOWN
      - alert: UpstreamServerDown
        expr: angie_http_upstreams_state{state="unhealthy"} == 1 or haproxy_server_status{state="DOWN"} == 1
        for: 15s
        labels:
          severity: critical
          tier: networking
        annotations:
          summary: "Узел апстрима перешел в состояние DOWN (Circuit Breaker OPEN)"
          description: "Сервер {{ $labels.server }} в группе {{ $labels.upstream }} изолирован балансировщиком из-за серии ошибок."

      # Алерт: Опасный рост Retry Amplification (шторм повторов)
      - alert: HighRetryAmplificationRate
        expr: sum(rate(nginx_upstream_responses_total{status=~"5.."}[1m])) by (upstream) / sum(rate(nginx_upstream_responses_total[1m])) by (upstream) > 0.15
        for: 30s
        labels:
          severity: warning
          tier: sre
        annotations:
          summary: "Высокая доля повторов в апстриме (> 15%)"
          description: "В пуле {{ $labels.upstream }} зафиксирован всплеск 5xx ошибок. Риск каскадного коллапса из-за Retry Amplification."

      # Алерт: Увеличение отдачи устаревшего кэша (индикатор деградации зависимости)
      - alert: HighStaleCacheServingRate
        expr: rate(nginx_cache_status_total{status="STALE"}[2m]) > 50
        for: 1m
        labels:
          severity: warning
          tier: application
        annotations:
          summary: "Сервис работает в режиме деградации (активна отдача stale-кэша)"
          description: "Прокси генерирует более 50 stale-ответов в секунду. Проверьте состояние бэкенда."
```

---

## Операции и команды

### Инспекция состояния апстримов в реальном времени

1. Запрос состояния пула серверов в Angie:
   ```bash
   curl -s http://127.0.0.1:8888/api/status/http/upstreams/production_api/ | jq '.peers[] | {server, state, fails, active, requests}'
   # → {
   # →   "server": "10.0.1.10:8080",
   # →   "state": "unhealthy",
   # →   "fails": 3,
   # →   "active": 0,
   # →   "requests": 1420
   # → }
   # → {
   # →   "server": "10.0.1.11:8080",
   # →   "state": "up",
   # →   "fails": 0,
   # →   "active": 12,
   # →   "requests": 1455
   # → }
   ```

2. Просмотр счетчиков ошибок и состояний серверов в HAProxy:
   ```bash
   echo "show servers state api_cluster" | socat stdio /run/haproxy/admin.sock
   # → 1 api_cluster 1 srv1 10.0.2.11 2 1 1 1 0 0 3 0 0 0 0 0 0 0
   # → 1 api_cluster 2 srv2 10.0.2.12 1 1 1 1 0 0 0 0 0 0 0 0 0 0
   # → 1 api_cluster 3 srv_backup 10.0.2.13 1 1 1 1 0 0 0 0 0 0 0 0 0 0
   ```

3. Быстрая проверка действующих таймаутов и лимитов в активном конфиге Nginx:
   ```bash
   nginx -T 2>&1 | grep -E "proxy_next_upstream|proxy_cache_use_stale|max_fails|fail_timeout|proxy_connect_timeout"
   # → proxy_connect_timeout 2s;
   # → proxy_next_upstream error timeout invalid_header http_500 http_502 http_503 http_504;
   # → proxy_next_upstream_tries 3;
   # → proxy_next_upstream_timeout 5s;
   # → proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
   # → server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
   ```

---

### Эмуляция сетевых аномалий и сбоев на уровне Linux-хоста

Для проведения стресс-тестирования и учений (GameDays) без облачных провайдеров используются стандартные утилиты ядра Linux:

1. Имитация полного разрыва сетевого канала (Blackhole / DROP):
   ```bash
   # Блокировка входящего трафика на порт бэкенда
   iptables -A INPUT -p tcp --dport 8080 -j DROP

   # Проверка срабатывания Circuit Breaker со стороны клиента
   curl -w "@curl-format.txt" -s -o /dev/null http://api.internal.net/v1/catalog
   # → time_namelookup:  0.0012s
   # → time_connect:     0.0018s
   # → time_starttransfer: 0.0154s
   # → time_total:       0.0162s
   # → http_code:        200 (Ответ отдан из кэша либо от резервного узла)

   # Очистка правила
   iptables -D INPUT -p tcp --dport 8080 -j DROP
   ```

2. Имитация аномальной хвостовой задержки (Tail Latency) через `netem`:
   ```bash
   # Внесение сетевой задержки 2500 мс (превышает proxy_connect_timeout)
   tc qdisc add dev eth0 root netem delay 2500ms

   # Проверка поведения прокси: фиксация таймаута и немедленный failover
   tail -n 2 /var/log/nginx/access.log | jq '{upstream_addr, upstream_status, upstream_response_time}'
   # → {
   # →   "upstream_addr": "10.0.1.10:8080, 10.0.1.11:8080",
   # →   "upstream_status": "504, 200",
   # →   "upstream_response_time": "2.001, 0.045"
   # → }

   # Удаление сетевой задержки
   tc qdisc del dev eth0 root
   ```

3. Анализ логов доступа на предмет каскадных ретраев:
   ```bash
   # Поиск запросов, которые совершили более одной попытки обращения к апстримам
   awk -F'|' '$4 ~ /,/ { print "Время: "$1 " | IP: "$2 " | Узлы: "$4 " | Статусы: "$5 }' /var/log/nginx/custom_upstream.log | head -n 5
   # → Время: [14/Oct/2026:16:10:02] | IP: 192.168.1.50 | Узлы: 10.0.1.10:8080, 10.0.1.11:8080 | Статусы: 502, 200
   # → Время: [14/Oct/2026:16:10:03] | IP: 192.168.1.51 | Узлы: 10.0.1.10:8080, 10.0.1.11:8080 | Статусы: 504, 200
   ```

---

## Диагностика ошибок

| Проблема | Симптом | Первичная диагностика | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Retry Storm (Лавина повторов)** | RPS на бэкенды возрастает в 3–5 раз относительно входящего клиентского потока при росте 5xx. | Анализ `$upstream_addr` в `access.log`: множественные адреса через запятую для одного запроса. | Ограничить попытки: `proxy_next_upstream_tries 2` или `3`; задать жесткий `proxy_next_upstream_timeout 5s`. |
| **Circuit Breaker Flapping (Флаппинг)** | Узел циклично переходит из `UP` в `DOWN` и обратно каждые несколько секунд, дестабилизируя пул. | Лог ошибок: постоянные записи `upstream server temporarily disabled while connecting to upstream`. | Увеличить `fail_timeout` с 10s до 30s–60s; включить `slow_start 15s` (Angie/HAProxy) для плавного прогрева сокетов. |
| **Дублирование транзакций (POST Dup)** | Пользователи жалуются на повторные списания средств или дубликаты заказов при медленной сети. | Поиск в access-логах: повторные POST-запросы со статусами `504, 200`. | Убрать `non_idempotent` из `proxy_next_upstream`. Повторять исключительно идемпотентные вызовы (`GET`, `HEAD`, `PUT`, `DELETE`). |
| **Утечка 502/504 к клиентам** | При отказе одного бэкенда клиенты получают 502 Bad Gateway вместо fallback или переключения. | 1. `proxy_next_upstream` не содержит нужных кодов.<br>2. `proxy_next_upstream_tries 1`. | Добавить коды: `proxy_next_upstream error timeout http_500 http_502 http_503 http_504; proxy_next_upstream_tries 3;`. |
| **Катастрофический CLS при Fallback** | Резкий скачок показателя CLS (> 0.25) в метриках при показе skeleton/fallback экранов. | Инспекция через Chrome DevTools Performance: сдвиг верстки из-за динамической вставки заглушек. | 1. Использовать `proxy_cache_use_stale` (сохраняет оригинальный макет).<br>2. Зафиксировать `min-height` и `aspect-ratio` у skeleton. |
| **Thundering Herd на Origin** | Всплеск до десятков тысяч RPS к бэкенду ровно в момент истечения TTL кэша. | Множество одновременных `X-Cache-Status: MISS` в логах для одного и того же URI. | Включить `proxy_cache_lock on;`, `proxy_cache_lock_timeout 5s;` и `proxy_cache_background_update on;`. |
| **Рассинхронизация воркеров (Nginx OSS)** | Сервер сбоит, но не изолируется, так как разные воркеры фиксируют ошибки по отдельности. | Проверка наличия `zone` в блоке `upstream`. В Nginx OSS без Nginx Plus счетчики изолированы. | 1. Перейти на Angie с директивой `zone`.<br>2. В чистом Nginx OSS рассчитывать суммарный порог как $Workers \times max\_fails$. |
| **Зависание на Cache Lock** | Клиенты ждут ответа по 10–30 секунд при зависании фонового обновления кэша. | Клиентский TTFB равен значению `proxy_cache_lock_timeout`. | Уменьшить `proxy_cache_lock_timeout` до 2–3s; настроить `proxy_cache_lock_age 3s`. |

---

## Рекомендации и лучшие практики

### Базовые архитектурные правила

1. **Единое пространство разделяемой памяти:** При использовании Nginx Plus или Angie всегда объявляйте директиву `zone` в блоке `upstream`. Это предотвращает рассинхронизацию между рабочими процессами и обеспечивает атомарное срабатывание Circuit Breaker.
2. **Строгая иерархия таймаутов:**
   Соблюдайте фундаментальное правило построения таймаутов проксирования:
   $$\text{proxy\_connect\_timeout} < \text{proxy\_read\_timeout} \le \text{proxy\_next\_upstream\_timeout} < \text{client\_timeout}$$
   - `proxy_connect_timeout`: не более 1–2 с (локальная сеть дата-центра обязана отвечать на SYN мгновенно).
   - `proxy_read_timeout`: 3–5 с для стандартных API.
   - `proxy_next_upstream_timeout`: суммарный лимит времени на все попытки (не должен превышать клиентский тайм-аут ожидания).
3. **Запрет бесконечных ретраев:**
   Никогда не оставляйте `proxy_next_upstream_tries` в значении по умолчанию `0` (без ограничений). Промышленный стандарт: **2 или 3 попытки**.
4. **Приоритет Stale-кэша перед аварийными заглушками:**
   Для любых данных, допускающих минимальную задержку согласованности (каталог, карточки товаров, статьи), активируйте `proxy_cache_use_stale`. Отдача немного устаревших данных предпочтительнее для пользователя и Core Web Vitals, чем любая страница ошибки.
5. **Защита неидемпотентных методов:**
   Никогда не добавляйте флаг `non_idempotent` в `proxy_next_upstream`, если архитектура сервиса не поддерживает дедупликацию через `Idempotency-Key` на уровне базы данных.

### Для DevOps, SRE и системных администраторов

- **SLO и проектирование порогов:**
  Пороги срабатывания Circuit Breaker (`max_fails`, `fail_timeout`, `fall`) должны рассчитываться исходя из согласованного Error Budget в рамках SLO сервиса. Слишком агрессивный Breaker приведет к ложным изоляциям при единичных сетевых всплесках; слишком медленный — пропустит шторм ошибок к пользователям.
- **Runbook при размыкании цепи:**
  Для дежурной смены SRE должен быть подготовлен регламент действий при срабатывании алерта `UpstreamServerDown`:
  1. Проверить доступность локального сокета приложения через `curl -I http://127.0.0.1:8080/healthz`.
  2. Проверить утилизацию ресурсов хоста (`top -b -n 1`, `vmstat 1 5`, `dmesg -T | grep -i oom`).
  3. Проверить системные журналы сервиса (`journalctl -u backend-api -n 100 --no-pager`).
  4. При необходимости ручного дренажа — перевести сервер в статус `drain` через сокет HAProxy или API Angie.
- **Chaos Engineering и регулярные учения (GameDays):**
  Регулярно тестируйте поведение балансировщиков в условиях контролируемой деградации:
  - Имитируйте потерю пакетов (packet loss) и искусственные задержки с помощью Linux `tc netem`.
  - Отключайте сетевые порты через `iptables`.
  - Убеждайтесь, что клиенты не видят необработанных статус-кодов `502 Bad Gateway` или `504 Gateway Timeout`.

---

## Дополнительная информация

### См. также

- **[Кэширование и Web Vitals](./caching.md)** — реализация директив `stale-while-revalidate` и `stale-if-error` в веб-серверах.
- **[Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md)** — влияние пулов постоянных соединений на устойчивость апстримов.
- **[Health Checks и Readiness](./health_checks_and_readiness.md)** — активный и пассивный мониторинг бэкендов в веб-инфраструктуре.
- **[Zero-Downtime Deployment](./zero_downtime_deployment.md)** — регламент вывода узлов из эксплуатации (drain) без сбоев.
- **[Метрики Web Vitals](./web_vitals.md)** — оптимизация LCP, INP, CLS и методы предотвращения сдвигов макета.
- **[Структурированное логирование для производительности](./structured_logging_for_performance.md)** — мониторинг `$upstream_response_time` и `$upstream_status`.
- **[Балансировка нагрузки HTTP в Angie](../../Angie/angie_http_load_balancing.md)** — эксплуатация зон разделяемой памяти `zone` и модуля `check`.
- **[Maintenance-режим в Nginx](../../Nginx/Scenarios/nginx_maintenance_mode.md)** — управляемое переключение на аварийные страницы и флаг-файлы.
- **[HTTP Rate Limiting и Circuit Breakers](../../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — сетевой уровень устойчивости HTTP-протоколов.
- **[HTTP Health Checks и Readiness](../../../Networking/Protocols/HTTP/http_health_checks_readiness.md)** — архитектура эндпоинтов здоровья.
- **[Паттерны микросервисной архитектуры](../../../Concepts/microservice_patterns.md)** — общесистемные паттерны Circuit Breaker, Bulkhead, Timeouts.
- **[Сброс нагрузки (Load Shedding)](../../../CI-CD/Core_Concepts/load_shedding.md)** — механизмы сброса трафика при исчерпании системной емкости.
- **[Паттерны надёжности (SRE/DevOps)](../../../CI-CD/Core_Concepts/reliability_patterns.md)** — практическое руководство по обеспечению отказоустойчивости.

### RFC и спецификации

- **RFC 9110 (HTTP Semantics)** — коды состояния `503 Service Unavailable`, `502 Bad Gateway`, `504 Gateway Timeout`, `429 Too Many Requests`; заголовок `Retry-After`.
- **RFC 9111 (HTTP Caching)** — спецификация кэширования HTTP и правила обработки устаревших ответов.
- **RFC 5861 (HTTP Cache-Control Extensions for Stale Content)** — директивы `stale-if-error` и `stale-while-revalidate`.
- **RFC 6585 (Additional HTTP Status Codes)** — определение статуса `429 Too Many Requests`.
