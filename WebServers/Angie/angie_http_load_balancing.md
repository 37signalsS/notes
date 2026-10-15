# Балансировка нагрузки HTTP в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

- **Балансировка нагрузки HTTP в Angie (L7)** — процесс распределения входящих клиентских HTTP/HTTPS-запросов между пулом бэкенд-серверов на прикладном уровне модели OSI с возможностью инспекции URI, заголовков, Cookie и состояния сокетов.
- **Upstream** — именованная логическая группа серверов приложений в конфигурации Angie, между которыми осуществляется распределение трафика по заданному алгоритму.
- **Зона разделяемой памяти (`zone`)** — сегмент оперативной памяти (shared memory), доступный всем рабочим процессам (`worker processes`) Angie. В ней хранятся общие счетчики соединений, метрики RTT, состояние проверок доступности и таблицы сессий. Без объявления `zone` расширенные механизмы балансировки и статистика недоступны.
- **Keepalive-пул** — кэш открытых TCP/TLS-соединений между рабочими процессами Angie и бэкенд-серверами. Позволяет повторно использовать установленные сетевые сессии, устраняя накладные расходы на трехэтапное TCP-рукопожатие и TLS handshake при каждом запросе.
- **Пассивные проверки (Passive Health Checks)** — механизм мониторинга, при котором Angie оценивает доступность сервера на основе результатов реальных клиентских запросов (`max_fails` и `fail_timeout`). Ошибочные ответы или таймауты приводят к временной изоляции узла.
- **Активные проверки (Active Health Checks)** — механизм проактивного мониторинга, при котором Angie периодически генерирует собственные проверочные HTTP/TCP-запросы («зонды») к бэкендам независимо от клиентского трафика (в OSS — через встроенный модуль `check`, в PRO — через директиву `upstream_probe`).
- **Алгоритм Least Time** — метод балансировки, направляющий запрос узлу с минимальным средним временем ответа (TTFB или полный ответ) с возможностью учета незавершенных запросов (`inflight`). Включен в базовую версию Angie OSS.
- **Dynamic Feedback** — алгоритм балансировки в Angie PRO, корректирующий распределение нагрузки на основе метрик загрузки (CPU, очередь, latency), передаваемых самими серверами приложений.
- **Sticky-сессии (Session Affinity)** — механизм привязки сессии клиента к определенному серверу из группы upstream на основе Cookie или параметров запроса (методы `cookie`, `route`, `learn`).
- **Slow Start** — механизм плавного ввода бэкенда в работу после старта или восстановления, при котором поток запросов на узел нарастает постепенно в течение заданного времени, предотвращая перегрузку «холодного» приложения.
- **Drain** — режим вывода сервера из эксплуатации, при котором узел перестает принимать новые сессии, но продолжает корректно обслуживать уже привязанные sticky-запросы до завершения работы.
- **Circuit Breaker (Предохранитель)** — паттерн отказоустойчивости, предотвращающий каскадный сбой инфраструктуры путем быстрого прерывания запросов к деградирующему бэкенду и перенаправления их на резервные узлы (`backup`).
- **`proxy_next_upstream`** — механизм перенаправления запроса на следующий сервер группы в случае сбоя или возврата ошибки текущим бэкендом.

Общие фундаментальные принципы L7-балансировки изложены в **[обзоре балансировки L7 в Nginx](../Nginx/Proxy/Load_Balancing/overview_concepts.md)**.

## Архитектура и базовые концепции

### Архитектура L7-балансировки и жизненный цикл запроса

Angie функционирует как полнофункциональный обратный прокси-сервер с асинхронной неблокирующей архитектурой на базе событийных циклов (`epoll` в Linux). 

```
                              Клиентский трафик
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │    Angie L7 Reverse Proxy     │
                      │  (Master + N Worker Processes)│
                      └───────────────┬───────────────┘
                                      │
                     Shared Memory Zone (`zone app 128k`)
            ┌─────────────────────────┴─────────────────────────┐
            │ - Состояние пиров (UP / DOWN / DRAINING)          │
            │ - Текущие активные соединения (`active`)           │
            │ - Статистика времени ответа (`least_time RTT`)     │
            │ - Таблицы сессий (`sticky learn`)                  │
            │ - Счетчики ошибок и статусы проверок              │
            └─────────────────────────┬─────────────────────────┘
                                      │
             ┌────────────────────────┼────────────────────────┐
             ▼                        ▼                        ▼
     ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
     │ Backend App 1 │        │ Backend App 2 │        │ Backend App 3 │
     │  (Primary)    │        │  (Primary)    │        │   (Backup)    │
     │ Keepalive Pool│        │ Keepalive Pool│        │  Cold Standby │
     └───────────────┘        └───────────────┘        └───────────────┘
```

**Жизненный цикл проксирования и балансировки запроса:**

1. **Прием и обработка клиентского соединения:** Рабочий процесс Angie принимает входящее TCP-соединение, при необходимости выполняет TLS-терминацию (с поддержкой аппаратной акселерации `kTLS`), считывает заголовки HTTP-запроса.
2. **Маршрутизация и выбор upstream:** На основе блока `location` запрос ассоциируется с целевым блоком `upstream`.
3. **Разрешение сессионной привязки (Session Affinity):** Если в группе включен `sticky`, Angie проверяет наличие идентификатора сервера в Cookie или хеш-таблице `sticky learn`. Если привязанный сервер доступен, запрос направляется ему.
4. **Применение алгоритма балансировки:** Если привязка отсутствует или не сработала, балансировщик выбирает узел согласно настроенному правилу (`round_robin`, `least_conn`, `least_time`, `hash`). Для узлов с активным `slow_start` вес динамически масштабируется.
5. **Взаимодействие через Keepalive-пул:**
   - Angie проверяет локальный пул открытых постоянных соединений текущего воркера к выбранному бэкенду.
   - Если свободный сокет найден — запрос немедленно отправляется в него без задержек на рукопожатие.
   - Если пустой сокет отсутствует, но лимит соединений `max_conns` не исчерпан — открывается новое TCP/TLS-соединение.
6. **Контроль таймаутов и отказоустойчивость:** Если бэкенд не отвечает в течение `proxy_connect_timeout` или возвращает ошибку из перечня `proxy_next_upstream`, Angie инициирует повторную попытку на соседний узел (с учетом `proxy_next_upstream_tries`).
7. **Буферизация и возврат соединения:** Ответ бэкенда считывается в буферы (`proxy_buffer_size`, `proxy_buffers`) и передается клиенту. Сетевой сокет возвращается в keepalive-пул воркера, если не был превышен лимит `keepalive_requests` или `keepalive_time`.

### Разделяемая память (`zone`) и межпроцессная синхронизация

В классическом Nginx OSS без разделяемой памяти каждый рабочий процесс (`worker`) ведет собственный независимый учет соединений и ошибок бэкендов. Это порождает проблему рассинхронизации: при 16 воркерах сервер должен совершить $16 \times \text{max\_fails}$ ошибок, прежде чем будет окончательно изолирован.

В Angie директива `zone` внутри `upstream` выделяет именованный сегмент памяти в `/dev/shm`:
- Все воркеры оперируют единым состоянием группы в режиме реального времени через атомарные операции и блокировки (spinlocks/rwlocks).
- Единый глобальный учет `max_fails`: сбой на любом воркере немедленно регистрируется для всего сервера.
- Корректная работа `least_time`: скользящее среднее времени ответа и счетчик `inflight` рассчитываются централизованно.
- База для REST API и Prometheus: модуль `/status/` берет актуальные счетчики напрямую из сегмента `zone`.

**Расчет размера зоны:**
- Базовый оверхед блока `upstream`: ~32–64 КБ.
- Запись одного сервера (`peer`): ~512–1024 байт.
- Таблица сессий `sticky learn`: ~256 байт на активную клиентскую сессию.
- Стандартное правило сайзинга: **128 КБ** достаточно для 100–200 бэкендов; при использовании `sticky learn` на 10 000 сессий выделяется не менее **2–4 МБ**.

### Алгоритмы распределения нагрузки

Подробный теоретический анализ алгоритмов приведен в документе **[Алгоритмы балансировки Nginx и Angie](../Nginx/Proxy/Load_Balancing/algorithms.md)**.

| Алгоритм | Директива | Редакция | Принцип работы | Сфера применения в SRE/DevOps |
| :--- | :--- | :--- | :--- | :--- |
| **Round Robin (Weighted)** | По умолчанию (без директивы) | OSS / PRO | Последовательный опрос серверов с учетом их коэффициентов `weight`. | Однородные бэкенды с одинаковым временем обработки запросов. |
| **Least Connections** | `least_conn;` | OSS / PRO | Запрос передается серверу с наименьшим числом активных соединений. | Запросы с непредсказуемой длительностью (длинные выгрузки, сложные SQL-выборки). |
| **Least Time** | `least_time header \| last_byte [inflight];` | OSS / PRO (в Angie OSS с v1.2+) | Выбирает сервер с минимальным RTT ответа с опциональным учетом незавершенных запросов. | Высоконагруженные API, микросервисы с неравномерной отзывчивостью узлов. |
| **IP Hash** | `ip_hash;` | OSS / PRO | Хеширование первых 3 октетов IPv4 или полного IPv6 клиента. | Примитивная сессионная привязка без Cookie; плохо работает за корпоративными NAT. |
| **Generic Hash** | `hash $key [consistent];` | OSS / PRO | Хеширование произвольного ключа. Параметр `consistent` включает алгоритм Ketama. | Шардирование кэша, маршрутизация по заголовку (`$http_x_user_id`), сессионным токенам. |
| **Random with Two Choices** | `random [two [least_conn \| least_time ...]];` | OSS / PRO | Случайный выбор двух серверов и направление запроса лучшему из них (Power of Two Choices). | Распределенные высоконагруженные кластеры, предотвращение эффекта стада (thundering herd). |
| **Dynamic Feedback** | `feedback;` | Angie PRO | Динамический расчет веса узла на основе данных метрик от приложения. | Автоматическая разгрузка узлов при росте CPU/памяти на хосте бэкенда. |

### Пул постоянных соединений (Keepalive) к бэкендам

Управление соединениями между прокси и бэкендами — один из наиболее критичных аспектов сетевой подсистемы Linux. По умолчанию обратный прокси закрывает TCP-соединение после каждого HTTP-запроса, что при 5 000 RPS приводит к созданию и закрытию 5 000 сокетов в секунду, вызывая лавинообразный рост сокетов в состоянии `TIME_WAIT` и исчерпание эфемерных портов хоста (`EADDRNOTAVAIL`).

```nginx
upstream backend_api {
    zone backend_api 128k;

    server 192.168.10.11:8080 max_conns=200;
    server 192.168.10.12:8080 max_conns=200;

    # Максимальное количество неактивных постоянных соединений к upstream
    # сохраняемых в кэше КАЖДОГО рабочего процесса (worker)
    keepalive 64;

    # Максимальное число запросов через одно соединение до его ротации
    keepalive_requests 10000;

    # Максимальное время жизни открытого соединения
    keepalive_time 1h;

    # Таймаут простоя соединения в пуле
    keepalive_timeout 60s;
}
```

> [!IMPORTANT]
> Директива `keepalive` в блоке `upstream` настраивает только размер пула сокетов. Для фактической активации постоянных соединений в блоке `location` **строго обязательны** следующие строки:
> ```nginx
> proxy_http_version 1.1;
> proxy_set_header Connection "";
> ```
> Без сброса заголовка `Connection: close` (который Angie по умолчанию выставляет для совместимости с HTTP/1.0) бэкенд будет закрывать TCP-соединение сразу после отдачи ответа!

### Отказоустойчивость и стратегия переключений (`proxy_next_upstream`)

SRE-подход требует строгого разграничения идемпотентных и неидемпотентных операций при повторе запросов:

- По умолчанию Angie повторяет запрос (`error`, `timeout`), только если клиенту еще не было передано ни одного байта ответа.
- Если бэкенд упал во время генерации тела ответа, запрос не повторяется во избежание дублирования данных на клиенте.
- Директива `proxy_next_upstream_tries` предотвращает каскадное «заклинивание» прокси, ограничивая число попыток обращения к серверам группы.
- Директива `proxy_next_upstream_timeout` задает суммарный бюджет времени на все попытки failover для одного входящего клиентского запроса.

```nginx
location /api/ {
    proxy_pass http://backend_api;
    proxy_http_version 1.1;
    proxy_set_header Connection "";

    # Условия передачи запроса следующему бэкенду
    proxy_next_upstream error timeout http_502 http_503 http_504;
    
    # Ограничение попыток: не более 3 узлов
    proxy_next_upstream_tries 3;
    
    # Жесткий таймаут на все попытки суммарно
    proxy_next_upstream_timeout 4s;
    
    # Таймаут на установку TCP-соединения с бэкендом
    proxy_connect_timeout 1s;
    proxy_read_timeout 5s;
    proxy_send_timeout 3s;
}
```

> [!WARNING]
> Опция `non_idempotent` в `proxy_next_upstream` разрешает повтор запросов с методами `POST`, `LOCK`, `PATCH`. Включайте ее **исключительно** в случаях, когда на уровне приложения реализованы механизмы дедупликации (Idempotency Keys). В противном случае сетевой таймаут может привести к повторному списанию средств или дублированию записей в БД!

### Сравнение механизмов проверки доступности (Health Checks)

Детальное описание проверок доступности приведено в **[Проверки состояния и мониторинг](../Nginx/Proxy/Load_Balancing/health_checks_and_monitoring.md)**.

```
+----------------------------------------------------------------------------------+
|                              Проверки доступности                                |
+----------------------------------------+-----------------------------------------+
|    Пассивные (Passive Health Checks)   |    Активные (Active Health Checks)      |
|  - Встроены в OSS и PRO                |  - Angie OSS: upstream_check_module     |
|  - Анализируют реальный трафик         |  - Angie PRO: upstream_probe в location |
|  - Реагируют ПОСЛЕ ошибки клиента      |  - Проверяют ДО прихода клиента         |
|  - Параметры: max_fails, fail_timeout  |  - Изолируют упавший узел превентивно   |
+----------------------------------------+-----------------------------------------+
```

1. **Пассивные проверки:**
   - Настраиваются директивой `server ... max_fails=N fail_timeout=Ts;`.
   - Если сервер вернул `max_fails` ошибок за интервал `fail_timeout`, он выводится из ротации ровно на `fail_timeout`.
   - По истечении таймера Angie отправляет на сервер ровно один клиентский запрос. Если он успешен — сервер признается рабочим; если нет — узел изолируется еще на один период `fail_timeout`.
2. **Активные проверки Angie OSS (`upstream_check_module`):**
   - Интегрированы в открытый дистрибутив Angie.
   - Опрашивают бэкенды независимым пулом проверок (`check interval=...`).
   - Поддерживают контроль HTTP-статусов (`check_http_expect_rescode 200 204`).
3. **Активные проверки Angie PRO (`upstream_probe`):**
   - Настраиваются внутри контекста `location`.
   - Поддерживают гибкие предикаты условий (`test=$var`), валидацию регулярными выражениями тела ответа (`max_body`), режимы работы `always`, `idle` (только при отсутствии рабочего трафика) и `onfail` (активируются при сбое пассивных проверок).

### Параметры директивы `server` в блоке `upstream`

| Параметр | Назначение | Значение по умолчанию | Доступность |
| :--- | :--- | :--- | :--- |
| `weight=N` | Весовой коэффициент сервера в алгоритме распределения. | `1` | Все версии |
| `max_conns=N` | Жесткий лимит одновременных активных соединений к данному бэкенду. | `0` (без лимита) | Все версии |
| `max_fails=N` | Число ошибок за `fail_timeout` для признания узла нерабочим. | `1` | Все версии |
| `fail_timeout=T` | Временное окно для `max_fails` и время удержания узла в статусе DOWN. | `10s` | Все версии |
| `slow_start=T` | Время постепенного вывода веса узла с 0 до номинала после восстановления. | `0` (отключено) | Angie OSS / PRO |
| `backup` | Помечает сервер как резервный. Получает трафик только если все основные узлы лежат. | Не задано | Все версии |
| `down` | Принудительный вывод узла из ротации системным администратором. | Не задано | Все версии |
| `drain` | Плавный вывод: узел обслуживает только текущие sticky-сессии. | Не задано | Angie PRO |

---

## Практические сценарии и конфигурация

Все сценарии ориентированы на эксплуатацию в Linux-окружении (bare-metal, локальные серверы, KVM-виртуализация) под управлением systemd без привязки к внешним облачным сервисам.

### Сценарий 1: Высоконагруженный пул API с `least_time last_byte inflight` и ограничением `max_conns`

Конфигурация оптимизирована для критичных микросервисов с неравномерным временем обработки запросов. Алгоритм направляет трафик серверам, способным быстрее отдать полный ответ клиенту, защищая каждый узел от перегрузки пула потоков с помощью `max_conns`.

```nginx
# /etc/angie/http.d/api_upstream.conf

upstream backend_api_cluster {
    # Зона разделяемой памяти: обязательна для least_time и мониторинга
    zone backend_api_cluster 256k;

    # Балансировка по времени передачи последнего байта с учетом запросов в обработке
    least_time last_byte inflight;

    # Серверы пула с ограничением максимального числа одновременных соединений
    server 192.168.10.21:8080 max_conns=250 max_fails=3 fail_timeout=15s;
    server 192.168.10.22:8080 max_conns=250 max_fails=3 fail_timeout=15s;
    server 192.168.10.23:8080 max_conns=250 max_fails=3 fail_timeout=15s;

    # Резервный узел: включается только при отказе всех трех основных
    server 192.168.10.29:8080 backup;

    # Пул постоянных соединений: по 64 сокета на каждый воркер
    keepalive 64;
    keepalive_requests 5000;
    keepalive_timeout 60s;
}

server {
    listen 192.168.10.10:80;
    server_name api.internal.corp;

    location / {
        proxy_pass http://backend_api_cluster;

        # Критичные параметры для работы пула keepalive
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Проброс заголовков реального клиента
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Тайм-ауты проксирования
        proxy_connect_timeout 1s;
        proxy_send_timeout 5s;
        proxy_read_timeout 10s;

        # Политика отказоустойчивости
        proxy_next_upstream error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 6s;
    }
}
```

**Валидация конфигурации и метрик:**
```bash
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

sudo systemctl reload angie

# Проверка состояния пиров и времени отклика через REST API
curl -s http://127.0.0.1:8888/status/http/upstreams/backend_api_cluster/ | jq '.peers[] | {server, state, active, requests, time}'
# → { "server": "192.168.10.21:8080", "state": "up", "active": 12, "requests": 45102, "time": 14 }
# → { "server": "192.168.10.22:8080", "state": "up", "active": 8, "requests": 46210, "time": 11 }
# → { "server": "192.168.10.23:8080", "state": "up", "active": 19, "requests": 44890, "time": 18 }
# → { "server": "192.168.10.29:8080", "state": "backup", "active": 0, "requests": 0, "time": 0 }
```

---

### Сценарий 2: Комплексная отказоустойчивость бэкендов с активными проверками в OSS

В данном сценарии активные проверки зондируют эндпоинт `/healthz`. Если узел начинает возвращать ошибку 500 или зависает, он изолируется до того, как на него поступит пользовательский запрос.

```nginx
# /etc/angie/http.d/ha_healthchecks.conf

upstream critical_service {
    zone critical_service 128k;

    server 10.10.1.11:8080 weight=2 max_fails=2 fail_timeout=10s;
    server 10.10.1.12:8080 weight=2 max_fails=2 fail_timeout=10s;
    server 10.10.1.13:8080 weight=1 max_fails=2 fail_timeout=10s;

    # Активные проверки Angie OSS (модуль check)
    # Интервал: 3 сек, 2 успешных ответа для поднятия, 3 ошибки для падения, таймаут зонда: 1 сек
    check interval=3000 rise=2 fall=3 timeout=1000 type=http;
    check_http_send "GET /healthz HTTP/1.1\r\nHost: health.internal\r\nConnection: close\r\nUser-Agent: Angie-HealthCheck\r\n\r\n";
    check_http_expect_rescode 200;

    keepalive 32;
}

server {
    listen 80;
    server_name service.internal.corp;

    location / {
        proxy_pass http://critical_service;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_next_upstream error timeout http_500 http_502 http_503;
        proxy_next_upstream_tries 2;
    }
}
```

**Валидация статусов активных проверок:**
```bash
# Получение статуса здоровья серверов через API Angie
curl -s http://127.0.0.1:8888/status/http/upstreams/critical_service/ | jq '.peers[] | {server, state, health: .health}'
# → {
# →   "server": "10.10.1.11:8080",
# →   "state": "up",
# →   "health": { "fails": 0, "passes": 1420, "unavailable": 0 }
# → }
```

---

### Сценарий 3: Stateful-приложение с механизмом `sticky learn` и `slow_start`

Приложение хранит локальные сессии пользователей в JVM-памяти. Angie отслеживает Cookie `JSESSIONID`, выставляемый сервером, формирует таблицу привязки в shared memory и обеспечивает плавный прогрев (`slow_start`) узлов после перезапуска.

```nginx
# /etc/angie/http.d/stateful_app.conf

upstream stateful_cluster {
    zone stateful_cluster 512k;

    # Отслеживание сессий по Cookie от бэкенда
    # create: переменная с Cookie бэкенда при создании сессии
    # lookup: переменная с Cookie клиента при повторном запросе
    # zone: именованная зона для хранения соответствий сессия -> сервер
    sticky learn 
           create=$upstream_cookie_jsessionid
           lookup=$cookie_jsessionid
           zone=client_sessions:4m
           timeout=3h;

    # slow_start=60s позволяет прогреть JIT-компилятор и пул соединений к СУБД
    server 192.168.20.101:8080 weight=10 max_conns=300 slow_start=60s;
    server 192.168.20.102:8080 weight=10 max_conns=300 slow_start=60s;

    keepalive 48;
}

server {
    listen 443 ssl;
    server_name crm.internal.corp;

    ssl_certificate /etc/ssl/certs/crm.crt;
    ssl_certificate_key /etc/ssl/private/crm.key;

    location / {
        proxy_pass http://stateful_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Подробный разбор методов session affinity приведен в **[Сессионная привязка (Sticky Sessions)](../Nginx/Proxy/Load_Balancing/sticky_sessions.md)**.

---

### Сценарий 4: Консистентное шардирование кэша через `hash $request_uri consistent`

Для пула локальных серверов кэширования или рендеринга контента критично, чтобы один и тот же URL всегда попадал на один и тот же узел. Использование алгоритма Ketama (`consistent`) гарантирует, что при добавлении или падении одного сервера перераспределится не более $1/N$ ключей кэша.

```nginx
# /etc/angie/http.d/cache_sharding.conf

upstream cache_tier {
    zone cache_tier 128k;

    # Кольцевое консистентное хеширование по нормализованному URI
    hash $uri consistent;

    server 192.168.30.11:8080;
    server 192.168.30.12:8080;
    server 192.168.30.13:8080;
    server 192.168.30.14:8080;

    keepalive 128;
}

server {
    listen 80;
    server_name static-cache.internal.corp;

    location /media/ {
        proxy_pass http://cache_tier;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Не переключать при 404 (это легитимный ответ кэша)
        proxy_next_upstream error timeout http_502 http_503;
    }
}
```

---

### Сценарий 5: Zero-Downtime деплоймент: Canary и Blue-Green с `drain` (Angie PRO)

Организация плавного обновления приложения на выделенных серверах без прерывания пользовательских транзакций.

```nginx
# /etc/angie/http.d/blue_green.conf

upstream production_service {
    zone production_service 256k;

    # Sticky сессии для сохранения пользовательского контекста
    sticky cookie srv_id expires=1h domain=.internal.corp path=/;

    # Синее окружение (текущая стабильная версия)
    server 10.20.1.11:8080 weight=100;
    server 10.20.1.12:8080 weight=100;

    # Зеленое окружение (новая версия: canary 5% трафика)
    server 10.20.2.11:8080 weight=5 slow_start=30s;
    server 10.20.2.12:8080 weight=5 slow_start=30s;

    keepalive 64;
}
```

**Команды переключения трафика в runtime:**

1. **Этап Canary (тестирование под 5% нагрузки):** Анализ логов ошибок и p99 latency зеленого окружения.
2. **Этап Drain (вывод старых синих нод):**
   В Angie PRO старые серверы переводятся в режим `drain` через REST API. Новые пользователи направляются на зеленую версию, а пользователи с существующими Cookie продолжают обслуживаться старыми нодами:
   ```bash
   # Перевод узла синего окружения в режим плавного завершения (drain)
   curl -s -X PATCH http://127.0.0.1:8888/config/http/upstreams/production_service/servers/0 \
     -H "Content-Type: application/json" \
     -d '{"drain": true}'
   # → {"server": "10.20.1.11:8080", "weight": 100, "drain": true, "state": "draining"}
   ```
3. **Этап полного переключения:**
   Увеличение веса зеленых нод до 100 и вывод старых в `down`:
   ```bash
   # Выключение старого сервера после исчерпания сессий
   curl -s -X PATCH http://127.0.0.1:8888/config/http/upstreams/production_service/servers/0 \
     -H "Content-Type: application/json" \
     -d '{"down": true}'
   # → {"server": "10.20.1.11:8080", "state": "down"}
   ```

---

### Сценарий 6: Runtime-управление и инспекция через REST API

Настройка защищенного внутреннего интерфейса управления Angie для системных администраторов и скриптов автоматизации.

```nginx
# /etc/angie/http.d/management_api.conf

server {
    listen 127.0.0.1:8888;
    server_name localhost;

    # Только локальный доступ и внутренняя сеть управления
    allow 127.0.0.1;
    allow 10.250.0.0/24;
    deny all;

    location /status/ {
        # Включение API в режиме чтения (OSS) или конфигурации (PRO при api /config/;)
        api /status/;
    }

    # Интегрированная консоль мониторинга Angie
    location = /console.html {
        root /usr/share/angie-console-light/html;
    }
}
```

Подробная документация по REST API доступна в **[Мониторинг Angie — API](./angie_monitoring/angie_monitoring_api.md)**.

---

### Сценарий 7: Защита бэкендов от каскадных сбоев (Circuit Breaker и ограничение очередей)

При резком всплеске нагрузки (DDoS, рекламная акция или сбой внешнего сервиса) бэкенды могут уйти в каскадный перезапуск из-за нехватки памяти (OOM) или исчерпания пула потоков. Архитектура SRE требует жесткого отсечения избыточного трафика на входе.

```nginx
# /etc/angie/http.d/circuit_breaker.conf

# Ограничение частоты запросов с одного IP: 50 r/s
limit_req_zone $binary_remote_addr zone=api_ratelimit:10m rate=50r/s;

# Ограничение одновременных сетевых соединений с одного IP: не более 20
limit_conn_zone $binary_remote_addr zone=ip_conn_limit:10m;

upstream app_resilient_pool {
    zone app_resilient_pool 128k;

    # max_conns ограничивает нагрузку на конкретный бэкенд
    server 192.168.50.11:8080 max_conns=150 max_fails=3 fail_timeout=10s;
    server 192.168.50.12:8080 max_conns=150 max_fails=3 fail_timeout=10s;

    # Быстрый fallback: локальный статический ответ или заглушка при отказе основных
    server 127.0.0.1:8089 backup;

    keepalive 32;
}

server {
    listen 80;
    server_name app.internal.corp;

    # Возврат кастомной ошибки 429 при превышении лимита
    limit_req_status 429;
    limit_conn_status 429;

    location / {
        limit_req zone=api_ratelimit burst=100 nodelay;
        limit_conn ip_conn_limit 20;

        proxy_pass http://app_resilient_pool;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Агрессивные таймауты: не ждать зависший бэкенд дольше 1 секунды
        proxy_connect_timeout 800ms;
        proxy_read_timeout 2s;
        proxy_send_timeout 2s;

        proxy_next_upstream error timeout http_502 http_503;
        proxy_next_upstream_tries 2;
        proxy_next_upstream_timeout 2500ms;
    }
}

# Локальный сервер-заглушка (Circuit Breaker Fallback)
server {
    listen 127.0.0.1:8089;
    default_type application/json;

    location / {
        return 503 '{"error": "Service Temporarily Unavailable", "code": 503, "retry_after": 10}';
    }
}
```

---

## Операции и команды

### Валидация и перезагрузка конфигурации

| Команда | Ожидаемый результат / Описание |
| :--- | :--- |
| `sudo angie -t` | `angie: configuration file /etc/angie/angie.conf test is successful` — проверка синтаксиса |
| `sudo angie -T \| grep -E 'upstream\|zone'` | Вывод скомпилированного дерева конфигурации с проверкой зон и блоков upstream |
| `sudo systemctl reload angie` | Бесшовное перечитывание конфигурации мастер-процессом без разрыва клиентских соединений |
| `sudo systemctl status angie` | `Active: active (running)` с отображением PID мастера и воркеров |

### Инспекция состояния апстримов через REST API

```bash
# Получение общего списка всех настроенных upstream
curl -s http://127.0.0.1:8888/status/http/upstreams/ | jq 'keys'
# → [ "backend_api_cluster", "critical_service", "stateful_cluster" ]

# Детальный статус серверов в конкретной группе: активные соединения, RTT, падения
curl -s http://127.0.0.1:8888/status/http/upstreams/backend_api_cluster/ | jq '.peers[] | {server, state, active, requests, fails: .health.fails}'
# → { "server": "192.168.10.21:8080", "state": "up", "active": 4, "requests": 15024, "fails": 0 }
# → { "server": "192.168.10.22:8080", "state": "up", "active": 2, "requests": 14980, "fails": 0 }

# Мониторинг использования постоянных соединений keepalive
curl -s http://127.0.0.1:8888/status/http/upstreams/backend_api_cluster/ | jq '.keepalive'
# → 18  # текущее число открытых свободных сокетов в пуле
```

### Мониторинг сетевых сокетов и пула соединений на уровне ОС

```bash
# Подсчет количества активных соединений от процессов Angie к целевым бэкендам
ss -tnp | grep angie | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn
# →    142 192.168.10.21
# →    138 192.168.10.22
# →    135 192.168.10.23

# Проверка сокетов в состоянии TIME_WAIT (детекция утечки соединений без keepalive)
ss -tan state time-wait | wc -l
# → 45  # значение в пределах нормы (при отсутствии keepalive здесь тысячи сокетов)

# Проверка очереди сокета Angie на прием входящих соединений (ListenBacklog)
ss -ltn '( sport = :80 or sport = :443 )'
# → State   Recv-Q  Send-Q  Local Address:Port  Peer Address:Port
# → LISTEN  0       4096    192.168.10.10:80    0.0.0.0:*
```

### Метрики Prometheus для SRE-мониторинга

При использовании встроенного модуля Prometheus в Angie метрики собираются напрямую по эндпоинту `/metrics`:

```bash
# Опрос метрик доступности бэкендов в формате Prometheus
curl -s http://127.0.0.1:8888/metrics | grep angie_upstream_peers
# → # HELP angie_upstream_peers_status Upstream peer status (1 = up, 0 = down)
# → # TYPE angie_upstream_peers_status gauge
# → angie_upstream_peers_status{upstream="backend_api_cluster",peer="192.168.10.21:8080"} 1
# → angie_upstream_peers_status{upstream="backend_api_cluster",peer="192.168.10.22:8080"} 1
# → angie_upstream_peers_requests_total{upstream="backend_api_cluster",peer="192.168.10.21:8080"} 15024
# → angie_upstream_peers_response_time_seconds{upstream="backend_api_cluster",peer="192.168.10.21:8080"} 0.014
```

### Анализ логов доступа и детекция проблем с upstream

Включение специализированных переменных `$upstream_*` в лог-формат позволяет точно локализовать медленные или сбойные бэкенды:

```nginx
# Определение SRE-ориентированного формата логов в /etc/angie/angie.conf
log_format upstream_perf '$remote_addr - [$time_local] "$request" '
                         '$status $body_bytes_sent '
                         'rt=$request_time uct=$upstream_connect_time '
                         'uht=$upstream_header_time urt=$upstream_response_time '
                         'us=$upstream_status addr=$upstream_addr';
```

```bash
# Мониторинг в реальном времени времени ответа бэкендов (urt) и их статусов (us)
tail -f /var/log/angie/access.log | awk '{print "URI:", $7, "Status:", $9, "UpstreamAddr:", $NF, "RespTime:", $(NF-2)}'
# → URI: /api/v1/orders Status: 200 UpstreamAddr: 192.168.10.21:8080 RespTime: urt=0.012
# → URI: /api/v1/users Status: 502 UpstreamAddr: 192.168.10.22:8080 RespTime: urt=0.002

# Поиск ошибок 502/504 в журнале ошибок Angie
grep -E 'upstream timed out|connect\(\) failed|no live upstreams' /var/log/angie/error.log | tail -n 10
# → [error] 12450#12450: *45109 connect() failed (111: Connection refused) while connecting to upstream, client: 10.0.1.5, server: api.internal.corp, request: "GET /data HTTP/1.1", upstream: "http://192.168.10.22:8080/data"
```

### Мониторинг сегментов разделяемой памяти

```bash
# Проверка размещения сегментов памяти Angie в виртуальной ФС
ls -la /dev/shm/ | grep angie
# → -rw------- 1 angie angie 262144 Oct 14 14:10 angie_zone_backend_api_cluster

# Контроль общего объема памяти /dev/shm
df -h /dev/shm
# → Filesystem      Size  Used Avail Use% Mounted on
# → tmpfs           7.8G  1.2M  7.8G   1% /dev/shm
```

---

## Устранение неисправностей

### 1. Ошибки `502 Bad Gateway` при исчерпании `max_conns`

- **Симптомы:** Клиенты периодически получают HTTP-код 502. В `error.log` фиксируются записи `no live upstreams while connecting to upstream`.
- **Причина:** Все бэкенды в группе достигли предельного количества одновременных соединений, заданного параметром `max_conns`. Новые запросы отклоняются Angie, так как в OSS-версии отсутствует буферизирующая очередь (`queue`).
- **Диагностика:**
  ```bash
  curl -s http://127.0.0.1:8888/status/http/upstreams/backend_api_cluster/ | jq '.peers[] | {server, active, max_conns}'
  # → { "server": "192.168.10.21:8080", "active": 250, "max_conns": 250 }
  # → { "server": "192.168.10.22:8080", "active": 250, "max_conns": 250 }
  ```
- **Решение:**
  1. В Angie OSS: увеличить значение `max_conns` в соответствии с реальной емкостью пула потоков бэкенда или добавить сервер `backup`:
     ```nginx
     server 192.168.10.21:8080 max_conns=400;
     server 192.168.10.29:8080 backup;
     ```
  2. В Angie PRO: активировать директиву очереди ожидания внутри `upstream`:
     ```nginx
     queue 500 timeout=10s;
     ```
  3. Проверить, что включен `keepalive` к бэкендам — повторное использование соединений снижает всплески активных сокетов.

---

### 2. Ошибки `504 Gateway Timeout` из-за зависших бэкендов

- **Симптомы:** Запросы выполняются ровно 60 секунд (значение по умолчанию) и завершаются ошибкой 504.
- **Причина:** Бэкенд принял соединение, но заблокировался на выполнении тяжелой операции (Deadlock в БД, сетевой вызов к внешнему сервису) и не передает данные.
- **Диагностика:**
  ```bash
  # Проверка времени задержки в логе Angie (поле urt)
  awk '$9 == "504" {print $0}' /var/log/angie/access.log | tail -n 5
  
  # Проверка состояния потоков приложения на целевом бэкенде
  curl -s http://192.168.10.21:8080/actuator/threaddump | jq '.threads[] | select(.threadState == "BLOCKED")'
  ```
- **Решение:**
  Уменьшить таймауты ожидания ответа и включить автоматический сброс на соседний узел:
  ```nginx
  proxy_connect_timeout 1s;
  proxy_read_timeout 5s;
  proxy_send_timeout 3s;
  proxy_next_upstream timeout http_504;
  ```

---

### 3. Исчерпание портов и шторм сокетов в состоянии `TIME_WAIT`

- **Симптомы:** В `error.log` появляется критическая ошибка `105: Cannot assign requested address while connecting to upstream`.
- **Причина:** Отсутствие или некорректная настройка пула `keepalive`. Angie открывает новое TCP-соединение на каждый запрос, и при его закрытии порт переходит в тайм-аут `TIME_WAIT` (60 секунд по стандарту TCP), исчерпывая диапазон эфемерных портов Linux.
- **Диагностика:**
  ```bash
  # Проверка количества сокетов в TIME_WAIT
  ss -tan state time-wait | wc -l
  # → 28540  # критическое значение!
  
  # Проверка диапазона локальных портов
  sysctl net.ipv4.ip_local_port_range
  # → net.ipv4.ip_local_port_range = 32768 60999  # доступно всего ~28 000 портов
  ```
- **Решение:**
  1. Настроить keepalive в `upstream` и в `location`:
     ```nginx
     upstream backend_pool {
         keepalive 128;
     }
     location / {
         proxy_http_version 1.1;
         proxy_set_header Connection "";
     }
     ```
  2. Выполнить тюнинг сетевого стека ядра Linux в `/etc/sysctl.d/99-angie-network.conf`:
     ```ini
     # Расширение диапазона эфемерных портов
     net.ipv4.ip_local_port_range = 10240 65535
     # Разрешение повторного использования сокетов TIME_WAIT для исходящих соединений
     net.ipv4.tcp_tw_reuse = 1
     # Сокращение таймаута удержания закрываемого сокета
     net.ipv4.tcp_fin_timeout = 15
     ```
     Применить: `sudo sysctl --system`.

---

### 4. Сброс и неравномерное распределение sticky-сессий

- **Симптомы:** Пользователи сообщают о внезапном сбросе авторизации во время работы с приложением; запросы прыгают между бэкендами.
- **Причина:** Недостаточный размер зоны разделяемой памяти для `sticky learn`, из-за чего старые сессии принудительно вытесняются по алгоритму LRU; либо прокси перезаписывает/удаляет заголовок `Set-Cookie`.
- **Диагностика:**
  ```bash
  # Проверка заполненности таблицы sticky-сессий
  curl -s http://127.0.0.1:8888/status/http/upstreams/stateful_cluster/ | jq '.sticky'
  # → { "total": 16384, "used": 16384, "drops": 4510 }  # drops > 0 означает вытеснение сессий!
  ```
- **Решение:**
  1. Увеличить размер зоны памяти `zone=client_sessions:4m` -> `16m` в директиве `sticky learn`.
  2. Убедиться, что в блоке `location` не включено скрытие заголовков:
     ```nginx
     proxy_pass_header Set-Cookie;
     ```

---

### 5. Флаппинг (flapping) бэкендов при пассивных проверках

- **Симптомы:** Сервер постоянно переходит из состояния `up` в `down` и обратно каждые 10 секунд.
- **Причина:** При пассивной проверке с дефолтными значениями `max_fails=1 fail_timeout=10s` единичная случайная задержка ответа приводит к бану узла на 10 секунд. Сразу после разбана на узел обрушивается пачка накопленных запросов, вызывая повторный сбой.
- **Диагностика:**
  ```bash
  grep -E 'upstream.*down|upstream.*up' /var/log/angie/error.log
  ```
- **Решение:**
  Увеличить порог ошибок, включить `slow_start` и настроить активные проверки:
  ```nginx
  server 10.10.1.11:8080 max_fails=5 fail_timeout=30s slow_start=30s;
  ```

---

### 6. Рост latency (p99) при использовании `least_conn`

- **Симптомы:** Общий RPS стабилен, среднее время ответа (p50) в норме, но p99 latency подскакивает до секунд.
- **Причина:** Алгоритм `least_conn` учитывает только *количество* соединений, но не учитывает их скорость. Если один из серверов аппаратно деградировал (троттлинг CPU, медленный диск), он медленно обрабатывает запросы, но формально держит мало соединений, из-за чего Angie продолжает направлять на него новые запросы.
- **Диагностика:**
  ```bash
  curl -s http://127.0.0.1:8888/status/http/upstreams/backend_api_cluster/ | jq '.peers[] | {server, time, active}'
  # → Node 1: time=12ms, active=10
  # → Node 2: time=850ms, active=4  <-- деградирующий узел!
  ```
- **Решение:**
  Переключиться на алгоритм `least_time` с флагом `inflight`:
  ```nginx
  least_time last_byte inflight;
  ```

---

### 7. Преждевременный разрыв и неэффективность keepalive-соединений

- **Симптомы:** В `error.log` появляются предупреждения `upstream prematurely closed connection while reading response header`.
- **Причина:** Значение таймаута простоя сокета в бэкенд-сервере (например, Tomcat, Gunicorn, Node.js) меньше, чем `keepalive_timeout` в Angie. Бэкенд закрывает сокет по своему таймауту, в то время как Angie пытается отправить в него новый запрос из пула.
- **Диагностика:**
  ```bash
  # Снятие дампа TCP RST-пакетов между Angie и бэкендом
  sudo tcpdump -nn -i any 'tcp[tcpflags] & tcp-rst != 0 and host 192.168.10.21'
  ```
- **Решение:**
  Правило SRE: **Таймаут keepalive на стороне прокси ВСЕГДА должен быть меньше таймаута на стороне бэкенда!**
  Если на бэкенде таймаут равен 65 секундам, в Angie устанавливается:
  ```nginx
  keepalive_timeout 60s;
  ```

---

## Лучшие практики

### Архитектура и надежность (SRE)

1. **Всегда объявляйте `zone`:** Зона разделяемой памяти — фундамент предсказуемого поведения кластера. Без нее каждый рабочий процесс живет в изолированном контексте, умножая ошибки и искажая балансировку.
2. **Используйте `slow_start` для всех Java/Node.js/Go бэкендов:** Холодный старт виртуальной машины (JIT-компиляция, наполнение пулов соединений HikariCP) требует времени. `slow_start=30s`–`60s` полностью устраняет просадки при раскатке новых версий.
3. **Настраивайте резервные узлы (`backup`):** Наличие хотя бы одного резервного сервера (или легковесного локального обработчика с отдачей статического fallback JSON) предотвращает отдачу клиентам системных страниц 502 при авариях в инфраструктуре.
4. **Контролируйте бюджет повторных попыток:** Никогда не оставляйте `proxy_next_upstream_tries` без ограничений. Стандартное промышленное правило: число попыток равно 2 или 3, а `proxy_next_upstream_timeout` составляет не более 50% от суммарного клиентского таймаута.

### Производительность и сайзинг

1. **Сайзинг пула `keepalive`:**
   Значение директивы `keepalive` задается в расчете на **один рабочий процесс**:
   $$\text{Всего соединений в кэше} = \text{worker\_processes} \times \text{keepalive}$$
   Для 8 воркеров и `keepalive 64;` в кэше будет удерживаться до 512 открытых соединений. Не задавайте слишком большие значения (более 256 на воркер), чтобы не расходовать память бэкендов на удержание пустых сессий.
2. **Буферизация ответов:** Оставляйте `proxy_buffering on;` включенным. Это освобождает рабочий поток бэкенда мгновенно после генерации ответа, поручая медленную передачу данных клиенту сетевым буферам Angie.

### Тюнинг сетевого стека ядра Linux

Для узла балансировки нагрузки с интенсивным L7-трафиком примените следующие параметры в файле `/etc/sysctl.d/99-angie-lb.conf`:

```ini
# Максимальное число открытых файлов в системе
fs.file-max = 2097152

# Размер очереди входящих соединений к сокету
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# Буферы приема и отправки TCP
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Диапазон исходящих эфемерных портов
net.ipv4.ip_local_port_range = 10240 65535

# Повторное использование сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1

# Сокращение времени удержания закрытых соединений
net.ipv4.tcp_fin_timeout = 15

# Защита от переполнения таблицы conntrack (если включен фаервол)
net.netfilter.nf_conntrack_max = 1048576
```

Лимиты файловых дескрипторов процесса в `/etc/security/limits.d/angie.conf`:
```ini
angie       soft    nofile   65536
angie       hard    nofile   65536
```

Директива в глобальном блоке `/etc/angie/angie.conf`:
```nginx
worker_processes auto;
worker_rlimit_nofile 65536;

events {
    worker_connections 16384;
    use epoll;
    multi_accept on;
}
```

### Безопасность

1. **Изоляция бэкендов в локальной сети:** Серверы upstream не должны иметь публичных IP-адресов. Весь трафик принимается только от IP-адресов балансировщика Angie.
2. **Фильтрация и санитизация заголовков:** Всегда очищайте и явно перезаписывайте доверенные заголовки:
   ```nginx
   proxy_set_header X-Real-IP $remote_addr;
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   ```
3. **Защита management API:** Эндпоинты `/status/` и `/metrics` должны быть закрыты от внешней сети с помощью директив `allow`/`deny` или вынесены на отдельный внутренний порт/сокет.

---

## Дополнительная информация

### Сравнение возможностей редакций

| Функция | Nginx OSS | Nginx Plus | Angie OSS | Angie PRO |
| :--- | :--- | :--- | :--- | :--- |
| **Зона разделяемой памяти (`zone`)** | Ограничено | Встроено | **Встроено** | **Встроено** |
| **Алгоритм Least Time (`least_time`)** | Нет | Есть | **Есть (с 1.2+)** | **Есть** |
| **Активные проверки доступности** | Только сторонние модули | Директива `health_check` | **Модуль `check`** | **`upstream_probe` в location** |
| **Сессионная привязка `sticky learn`** | Нет | Есть | **Есть** | **Есть** |
| **Плавный старт (`slow_start`)** | Нет | Есть | **Есть** | **Есть** |
| **Плавный вывод (`drain`)** | Нет | Есть | Нет | **Есть** |
| **Мониторинг REST API и Prometheus** | Нет (базовый stub_status) | REST API JSON | **REST API + Prometheus** | **REST API + Prometheus + Metrics Zone** |
| **Модификация upstream на лету (без reload)** | Нет | Да (HTTP API) | Нет (read-only API) | **Да (`api /config/;`)** |

### См. также

- **[Обзор возможностей Angie](./angie_overview.md)** — архитектура и ключевые отличия от Nginx.
- **[Обратный прокси в Angie](./angie_reverse_proxy.md)** — основы проксирования, буферизация и управление заголовками.
- **[Динамические апстримы и Service Discovery](./dynamic_upstreams.md)** — динамическое DNS-разрешение (`resolve`) и автообнаружение бэкендов.
- **[Мониторинг Angie — API](./angie_monitoring/angie_monitoring_api.md)** — полное описание эндпоинтов и форматов метрик REST API.
- **[Мониторинг Angie — возможности Angie Pro](./angie_monitoring/angie_monitoring_pro.md)** — директива `upstream_probe` и управление через `api /config/;`.
- **[Алгоритмы балансировки Nginx и Angie](../Nginx/Proxy/Load_Balancing/algorithms.md)** — математика и алгоритмический анализ методов распределения нагрузки.
- **[Проверки состояния и мониторинг](../Nginx/Proxy/Load_Balancing/health_checks_and_monitoring.md)** — детальный обзор пассивных и активных проверок.
- **[Сессионная привязка (Sticky Sessions)](../Nginx/Proxy/Load_Balancing/sticky_sessions.md)** — детальная настройка методов cookie, route, learn.
- **[Оптимизация производительности Angie](./High_Load/performance_optimization.md)** — тюнинг для работы под экстремальными нагрузками.
- **[L4-балансировка и проксирование (Stream)](./l4_balancing_and_proxying.md)** — балансировка сырых TCP и UDP потоков.
- **[Angie с Keepalived для HA](./angie_ha_with_keepalived.md)** — обеспечение отказоустойчивости самого балансировщика через VRRP.
