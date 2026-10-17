# Алгоритмы балансировки нагрузки Nginx и Angie

**Актуально для:** Nginx 1.26+ (OSS/Plus) / Angie 1.6+

## Определения

**Алгоритм балансировки нагрузки (Load Balancing Algorithm)** — детерминированная или адаптивная логика, в соответствии с которой реверс-прокси Nginx/Angie выбирает целевой бэкенд-сервер из пула `upstream` для передачи входящего клиентского запроса или TCP/UDP-потока.

**Upstream-группа (Upstream Pool)** — логический пул серверов приложений, объявленный в блоке `upstream`, для которого задаются алгоритм распределения, параметры отказоустойчивости, ограничения соединений и кэширование сокетов. Подробнее: [Обзор концепций балансировки](./overview_concepts.md).

**Активное соединение (Active Connection)** — установленный сетевой сокет между рабочим процессом Nginx и бэкендом, находящийся в состоянии обработки HTTP-запроса, ожидания ответа или передачи данных. Не включает незанятые соединения в пуле keepalive.

**Зона разделяемой памяти (Shared Memory Zone, `zone`)** — сегмент оперативной памяти, выделяемый master-процессом через системный вызов `mmap()`/`shmget()`, доступный всем рабочим процессам (`worker processes`). Хранит единые счетчики активных соединений, веса, очереди запросов и состояние пассивных/активных проверок доступности.

**Плавный взвешенный Round Robin (Smooth Weighted Round-Robin, SWRR)** — модификация циклического алгоритма Nginx, которая равномерно чередует запросы между узлами с разными весами, полностью исключая пакетную отправку ("скучивание") серии запросов на узел с наибольшим весом.

**Консистентное хеширование (Consistent Hashing, Ketama Ring)** — распределение ключей по виртуальному континууму (хеш-кольцу из 160 виртуальных слотов на сервер). При добавлении или удалении бэкенда переназначается только $1/N$ часть ключей, сохраняя локальность кэша на остальных серверах.

**Принцип выбора из двух случайных (Power of Two Choices)** — вероятностный метод балансировки (`random two`), при котором балансировщик выбирает два узла случайным образом и направляет запрос на узел с наименьшим значением метрики (соединения или задержка), экспоненциально снижая пиковую нагрузку на очереди без глобальной блокировки.

**Наименьшее время отклика (Least Time)** — адаптивный алгоритм Nginx Plus и Angie, направляющий запрос на сервер с минимальной задержкой обработки с учетом текущих соединений и времени ответа (TTFB или полного тела).

**Динамическая обратная связь (Dynamic Feedback)** — алгоритм адаптивной балансировки в Angie PRO (директива `feedback`), динамически корректирующий вес серверов на основе телеметрии, передаваемой бэкендами в HTTP-заголовках ответа (утилизация CPU, глубина очереди задач, latency).

**Дренаж соединений (Connection Draining, `drain`)** — режим постепенного вывода сервера из эксплуатации: узел перестает принимать новые запросы, кроме тех, которые привязаны к нему механизмами sticky-сессий, позволяя завершить активные пользовательские сеансы.

**Плавный запуск (Slow Start, `slow_start`)** — механизм постепенного линейного наращивания веса сервера от 0 до номинального значения в течение заданного интервала времени после его восстановления или ввода в строй, предотвращающий падение "холодного" приложения от мгновенного наплыва трафика.

---

## Основные концепции и архитектура

### Архитектурная модель: Master-Worker и роль Shared Memory

Nginx функционирует по многопроцессорной событийно-ориентированной модели. Главный процесс (`master`) запускает непривилегированные рабочие процессы (`workers`), каждый из которых выполняет независимый неблокирующий цикл обработки событий `epoll` (Linux).

```
БЕЗ ДИРЕКТИВЫ ZONE (Nginx OSS по умолчанию):
┌─────────────────────────┐         ┌─────────────────────────┐
│ Worker Process 1        │         │ Worker Process 2        │
│ - Local conn count: 5   │         │ - Local conn count: 1   │
│ - Local fail count: 1   │         │ - Local fail count: 2   │
└────────────┬────────────┘         └────────────┬────────────┘
             │                                   │
             ▼                                   ▼
      Бэкенд 10.0.0.1                     Бэкенд 10.0.0.1
   (Каждый воркер видит только свою часть картины. least_conn фрагментирован)

С ДИРЕКТИВОЙ ZONE (Angie / Nginx Plus / Nginx Stream):
┌─────────────────────────┐         ┌─────────────────────────┐
│ Worker Process 1        │         │ Worker Process 2        │
└────────────┬────────────┘         └────────────┬────────────┘
             │                                   │
             ▼                                   ▼
    ┌─────────────────────────────────────────────────────┐
    │          Shared Memory Zone (`zone 64k`)            │
    │  - Total Active Connections: 6                      │
    │  - Global Fail Status: Node 2 is DOWN               │
    │  - Shared Dynamic Weights / Ketama Ring             │
    └─────────────────────────────────────────────────────┘
```

#### Влияние директивы `zone` на алгоритмы балансировки:
1. **`least_conn` в многоядерных системах:** Без `zone` каждый рабочий процесс ведет счетчик активных соединений исключительно в локальной памяти. На 16- или 32-ядерном сервере это приводит к статистическому перекосу: запрос направляется на узел, наименее загруженный с точки зрения *данного конкретного воркера*, а не всей системы. Наличие `zone` объединяет учет соединений.
2. **Пассивные проверки (`max_fails`, `fail_timeout`):** Без `zone` сервер помечается временно недоступным только тогда, когда **каждый** рабочий процесс независимо зафиксирует `max_fails` ошибок. В системе с 16 воркерами и `max_fails=3` клиенты получат до $16 \times 3 = 48$ сбоев, прежде чем узел будет изолирован. Директива `zone` делает исключение узла мгновенным для всего сервера.
3. **Расширенные алгоритмы:** Алгоритмы `least_time`, `feedback`, директивы `queue`, `slow_start` и динамический DNS-резолвинг (`resolve`) технически не могут функционировать без `zone`.

### Жизненный цикл обработки запроса в Upstream

```
[Клиентский HTTP-запрос]
         │
         ▼
[Nginx Worker: парсинг HTTP, поиск location]
         │
         ▼
[Подсистема ngx_http_upstream]
         │
         ├─► 1. Проверка доступности пиров (исключение down, fail_timeout, max_conns)
         ├─► 2. Применение алгоритма (RR / least_conn / hash / random / least_time)
         ├─► 3. Проверка локального пула keepalive (переиспользование TCP-сокета)
         │       └─► Если пул пуст: инициализация неблокирующего connect() к бэкенду
         │
         ▼
[Отправка запроса на выбранный бэкенд]
         │
         ├─► [Успешный ответ (2xx/3xx/4xx)] ──► Передача клиенту, сокет -> keepalive
         │
         └─► [Сбой / Ошибка сети / 5xx из proxy_next_upstream]
                 │
                 ├─► Инкремент счетчика сбоев узла в zone (max_fails)
                 ├─► Если попытки не исчерпаны: повторный вызов алгоритма для выбора дублера
                 └─► Если лимит proxy_next_upstream_tries исчерпан: возврат 502/504 клиенту
```

---

## Детальный разбор алгоритмов балансировки

### 1. Round Robin и Smooth Weighted Round Robin

Циклический перебор серверов. Используется по умолчанию при отсутствии иных директив алгоритмов в блоке `upstream`.

#### Математическая модель плавного взвешивания (SWRR)
В классическом взвешенном Round Robin при весах серверов $A=5, B=1, C=1$ последовательность запросов имела бы вид: `A, A, A, A, A, B, C`. Это вызывало всплеск нагрузки на узел $A$ в начале каждого цикла.

Инженеры Nginx реализовали алгоритм Smooth Weighted Round-Robin (исходный код в `ngx_http_upstream_round_robin.c`). Для каждого сервера поддерживаются три переменных:
- `weight` — сконфигурированный статический вес;
- `effective_weight` — текущий рабочий вес (снижается при сетевых сбоях, постепенно восстанавливается при успехе);
- `current_weight` — динамический кумулятивный счетчик (инициализируется нулем).

**Правило шага алгоритма для каждого нового запроса:**
1. Для каждого доступного сервера его `current_weight` увеличивается на его `effective_weight`:
   $$\text{current\_weight}_i = \text{current\_weight}_i + \text{effective\_weight}_i$$
2. Выбирается сервер $k$ с наибольшим значением `current_weight`.
3. Для выбранного сервера $k$ его `current_weight` уменьшается на сумму эффективных весов всех доступных серверов ($\sum \text{effective\_weight}$):
   $$\text{current\_weight}_k = \text{current\_weight}_k - \sum_{i=1}^{n} \text{effective\_weight}_i$$

#### Пример работы для весов {A: 4, B: 2, C: 1} (Сумма весов = 7):

| Шаг | Текущие веса перед выбором (`current_weight += effective_weight`) | Выбранный узел (Max) | Коррекция выбранного узла (`- 7`) |
| :---: | :--- | :---: | :--- |
| **1** | A: 4, B: 2, C: 1 | **A** (4) | A: -3, B: 2, C: 1 |
| **2** | A: 1, B: 4, C: 2 | **B** (4) | A: 1, B: -3, C: 2 |
| **3** | A: 5, B: -1, C: 3 | **A** (5) | A: -2, B: -1, C: 3 |
| **4** | A: 2, B: 1, C: 4 | **C** (4) | A: 2, B: 1, C: -3 |
| **5** | A: 6, B: 3, C: -2 | **A** (6) | A: -1, B: 3, C: -2 |
| **6** | A: 3, B: 5, C: -1 | **B** (5) | A: 3, B: -2, C: -1 |
| **7** | A: 7, B: 0, C: 0 | **A** (7) | A: 0, B: 0, C: 0 |

Итоговая последовательность выбора: **A, B, A, C, A, B, A**. Запросы на узел $A$ распределены идеально равномерно без пачек.

---

### 2. Least Connections (`least_conn`)

Запрос передается бэкенду с наименьшим числом активных соединений, скорректированным на вес узла.

#### Формула выбора:
Выбирается сервер $i$, минимизирующий значение:
$$\text{Metric}_i = \frac{\text{active\_connections}_i + 1}{\text{weight}_i}$$

Если значения метрики у нескольких серверов совпадают, между ними применяется Round Robin.

#### Сценарии применения:
- Длительные HTTP-запросы с непредсказуемым временем ответа (генерация тяжелых PDF-отчетов, аналитические SQL-запросы, файловые выгрузки, WebSocket-сессии).
- Защита серверов с меньшим объемом оперативной памяти или более слабым CPU.

#### Критическая уязвимость: Эффект «Черной дыры» (Black Hole / Fast-Failure Herd)
> [!WARNING]
> Если один из бэкендов падает с мгновенным сбросом TCP (RST) или немедленной отдачей HTTP 500, время его обработки запроса составляет долю миллисекунды. Число его активных соединений моментально падает до 0. В результате `least_conn` начинает с максимальной скоростью стягивать **весь входящий трафик системы** на вышедший из строя сервер!
> 
> **Обязательная защита:** Всегда настраивайте `max_fails`, `fail_timeout` и `proxy_next_upstream`, чтобы Nginx немедленно изолировал сбоящий узел:
> ```nginx
> server 10.0.0.10:8080 max_fails=3 fail_timeout=10s;
> ```

---

### 3. IP Hash (`ip_hash`)

Привязка клиентских сессий к бэкенду на основе вычисления хеша от IP-адреса клиента. Доступен только в модуле HTTP.

#### Внутренний механизм вычисления:
- **IPv4:** Алгоритм использует **первые три октета адреса (сеть /24)**. Например, адреса `198.51.100.14` и `198.51.100.89` дают абсолютно идентичный хеш и направляются на один и тот же бэкенд.
- **IPv6:** Используется полный 128-битный адрес.

#### Ограничения и особенности:
1. **Проблема корпоративного NAT и мобильных операторов:** Если тысячи пользователей выходят в интернет через один корпоративный прокси-шлюз (один внешний IP или подсеть `/24`), все они окажутся на одном бэкенде, вызвав жесткий дисбаланс.
2. **Параметр `backup`:** Не поддерживается совместно с `ip_hash`. Конфигурация с `backup` сервером завершится ошибкой валидации `nginx -t`.
3. **Вывод узла из пула:** Нельзя просто удалять строку `server` из конфига — это изменит хеш-пространство и сбросит сессии всех клиентов. Вместо этого сервер временно помечается параметром `down`:
   ```nginx
   server 10.0.0.11:8080 down;
   ```
   В этом случае Nginx сохраняет распределение хешей, перенаправляя только клиентов с отключенного узла.

---

### 4. Произвольный Хеш и Консистентное Хеширование (`hash ... [consistent]`)

Балансировка на основе строкового хеша от произвольной переменной или их комбинации: `$request_uri`, `$arg_uuid`, `$cookie_session`, `$remote_addr$http_user_agent`.

```nginx
# Обычный модульный хеш
hash $request_uri;

# Консистентный хеш Ketama (рекомендуется)
hash $request_uri consistent;
```

#### Разница между стандартным и консистентным хешем:

| Параметр | Стандартный `hash <key>` | Консистентный `hash <key> consistent` |
| :--- | :--- | :--- |
| **Формула выбора** | $\text{peer\_index} = \text{hash}(\text{key}) \pmod N$ | Проекция хеша на кольцо Ketama (160 точек/узел) |
| **Поведение при смене $N$ (добавлении/удалении ноды)** | Переназначается $\approx \frac{N-1}{N}$ (до 80-95%) ключей | Переназначается только $\approx \frac{1}{N}$ ключей |
| **Нагрузка на кэширующий бэкенд** | Лавинообразный сброс кэша (Cache Stampede) | Минимальные локальные промахи кэша |
| **Расход CPU на расчет** | Минимальный | Незначительно выше при инициализации таблицы |

#### Механика кольца Ketama:
Каждый сервер виртуально дублируется 160 раз в 32-битном адресном пространстве чисел от $0$ до $2^{32}-1$. Хеш от ключа проецируется на круг. Запрос направляется на ближайший сервер по часовой стрелке. При падении сервера ключи, закрепленные за его сегментами, переходят к следующему узлу кольца, в то время как 85–95% ключей остаются на своих прежних серверах.

---

### 5. Random с выбором из двух (`random [two [least_conn | least_time]]`)

Директива `random` выбирает сервер случайным образом с учетом заданных весов.

#### Алгоритм "Power of Two Choices" (`random two least_conn`):
При указании параметра `two` балансировщик псевдослучайным образом выбирает **два** сервера-кандидата из пула, сравнивает их параметры и передает запрос лучшему:
- `random two least_conn` — выбирает из двух серверов тот, у которого меньше активных соединений.
- `random two least_time=header` (Angie / Nginx Plus) — выбирает узел с меньшим временем ответа заголовков.
- `random two least_time=last_byte` — выбирает узел с меньшим временем полной отдачи ответа.

#### Преимущество перед `least_conn` в распределенной инфраструктуре:
Когда несколько независимых балансировщиков Nginx работают перед одним общим пулом бэкендов, глобальный алгоритм `least_conn` часто приводит к эффекту стадного поведения (Herd Effect): все балансировщики одновременно видят один и тот же наименее загруженный сервер и отправляют на него лавину входящих запросов. `random two` гарантирует стохастическую десинхронизацию балансировщиков и доказанно приближает длину очередей к глобальному оптимуму.

---

### 6. Least Time (`least_time`) — Angie и Nginx Plus

Продвинутый алгоритм адаптивного выбора бэкенда на основе динамически измеряемого времени отклика. Требует обязательного объявления директивы `zone`.

#### Синтаксис:
```nginx
upstream dynamic_api {
    zone dynamic_api_zone 128k;
    least_time header | last_byte [inflight];
    server 10.0.0.10:8080;
    server 10.0.0.11:8080;
}
```

#### Параметры оценки задержки:
- `header` — учитывается время от отправки запроса до получения первого байта заголовка ответа от бэкенда (Time to First Byte, TTFB). Идеально для проверки скорости генерации ответа приложением.
- `last_byte` — учитывается время от отправки запроса до получения последнего байта тела ответа (Time to Last Byte, TTLB). Учитывает пропускную способность сетевого канала к бэкенду.
- `inflight` (поддерживается в Angie и Nginx Plus R12+) — в расчет времени ответа дополнительно включаются запросы, находящиеся в обработке в текущий момент. Это предотвращает перегрузку сервера, который внезапно замедлил отдачу, но среднее историческое время ответа которого еще выглядит низким.

---

### 7. Dynamic Feedback (`feedback`) — Angie PRO

Адаптивная балансировка по оперативным показателям утилизации бэкенда, передаваемым в заголовках HTTP-ответов от приложений (CPU load, свободная память, длина очередей worker-пула).

#### Принцип расчета эффективного веса:
Эффективный вес узла пересчитывается динамически с использованием экспоненциально взвешенного скользящего среднего (EWMA):
$$\text{Weight}_{\text{effective}} = \text{Weight}_{\text{static}} \times f(\text{Metric})$$

#### Синтаксис:
```nginx
upstream compute_cluster {
    zone compute_zone 256k;
    server 10.10.0.1:8080 weight=100;
    server 10.10.0.2:8080 weight=100;

    # Считывание метрики из заголовка ответа X-Host-Load (0-100)
    feedback variable=$upstream_http_x_host_load inverse factor=80;
}
```
Параметр `inverse` означает, что чем выше переданное значение нагрузки, тем ниже опускается эффективный вес сервера в пуле балансировки.

---

## Практические сценарии

### Сценарий 1: Отказоустойчивый пул с Smooth Weighted Round Robin и Keepalive

**Задача:** Сбалансировать входящий трафик веб-приложения между тремя серверами разной мощности (веса 3:2:1) с резервным сервером (`backup`), пассивными проверками и keepalive-пулом для исключения исчерпания сокетов.

```nginx
http {
    # Формат лога с отображением выбранного узла и задержки
    log_format lb_combined '$remote_addr - [$time_local] "$request" '
                           '$status $body_bytes_sent '
                           'upstream: $upstream_addr '
                           'status: $upstream_status '
                           'rt: $upstream_response_time';

    upstream production_web {
        # Зона разделяемой памяти обязательна для корректного учета max_fails между воркерами
        zone production_web_zone 128k;

        # Основные узлы с весами и счетчиками сбоев
        server 10.0.1.10:8080 weight=3 max_fails=3 fail_timeout=15s;
        server 10.0.1.11:8080 weight=2 max_fails=3 fail_timeout=15s;
        server 10.0.1.12:8080 weight=1 max_fails=3 fail_timeout=15s;

        # Резервный узел (принимает трафик ТОЛЬКО если все три основных узла недоступны)
        server 10.0.1.99:8080 backup;

        # Пул открытых TCP-соединений к бэкендам на каждый рабочий процесс
        keepalive 64;
        keepalive_requests 1000;
        keepalive_timeout 60s;
    }

    server {
        listen 80;
        server_name app.company.local;
        access_log /var/log/nginx/app_access.log lb_combined;

        location / {
            proxy_pass http://production_web;
            
            # Обязательные директивы для работы keepalive к upstream
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            # Передача оригинальных заголовков клиента
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Параметры автоматического failover
            proxy_next_upstream error timeout invalid_header http_502 http_503;
            proxy_next_upstream_tries 3;
            proxy_next_upstream_timeout 5s;

            proxy_connect_timeout 2s;
            proxy_read_timeout 10s;
            proxy_send_timeout 5s;
        }
    }
}
```

#### Проверка и валидация:
```bash
# Проверка синтаксиса конфигурации
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Безопасное применение конфигурации без разрыва соединений
nginx -s reload
# → signal reload started

# Проверка чередования запросов по алгоритму SWRR (пропорция 3:2:1)
for i in {1..6}; do curl -s -o /dev/null -w "%{http_code}\n" http://app.company.local/; done
tail -n 6 /var/log/nginx/app_access.log | awk '{print $8}'
# → 10.0.1.10:8080
# → 10.0.1.11:8080
# → 10.0.1.10:8080
# → 10.0.1.12:8080
# → 10.0.1.10:8080
# → 10.0.1.11:8080
```

---

### Сценарий 2: Защита бэкендов от перегрузки: лимиты соединений, очереди и плавный ввод

**Задача:** Ограничить число одновременных запросов на бэкенд базы данных/API (`max_conns`), включить очередь ожидания (`queue`) и плавный старт (`slow_start`) для прогрева JIT/пулов памяти.

```nginx
upstream protected_api {
    zone protected_api_zone 256k;
    least_conn;

    # Ограничение до 150 одновременных соединений на сервер
    # slow_start плавно наращивает вес сервера от 0 до номинала за 60 секунд после старта
    server 10.0.2.10:8080 weight=2 max_conns=150 max_fails=2 fail_timeout=10s slow_start=60s;
    server 10.0.2.11:8080 weight=2 max_conns=150 max_fails=2 fail_timeout=10s slow_start=60s;

    # Очередь запросов в разделяемой памяти (доступно в Angie и Nginx Plus)
    # Если оба сервера исчерпали max_conns, до 100 запросов ожидают освобождения слотов до 10 сек
    queue 100 timeout=10s;
    
    keepalive 32;
}

server {
    listen 80;
    server_name api.company.local;

    location /api/ {
        proxy_pass http://protected_api;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;

        # При переполнении очереди возвращается 503
        error_page 503 = /custom_503.json;
    }

    location = /custom_503.json {
        return 503 '{"error": "API rate capacity exceeded. Please retry later."}';
    }
}
```

#### Проверка и нагрузочный тест:
```bash
# Мониторинг очереди и активных соединений через Angie Console / REST API
curl -s http://127.0.0.1:8080/status/http/upstreams/protected_api | jq '.peers[] | {server: .server, active: .active, max_conns: .max_conns}'
# → {
# →   "server": "10.0.2.10:8080",
# →   "active": 142,
# →   "max_conns": 150
# → }
# → {
# →   "server": "10.0.2.11:8080",
# →   "active": 139,
# →   "max_conns": 150
# → }
```

---

### Сценарий 3: Распределенный кэширующий кластер на Ketama Consistent Hashing

**Задача:** Настроить маршрутизацию запросов к локальному кластеру кэширующих демонов (например, Varnish / Nginx Cache nodes) по URI запроса так, чтобы выпадение одного сервера не приводило к сбросу кэша на остальных.

```nginx
upstream cache_tier {
    zone cache_tier_zone 512k;

    # Консистентное хеширование по нормализованному URI без query-параметров
    hash $uri consistent;

    server 127.0.0.1:8081 weight=10;
    server 127.0.0.1:8082 weight=10;
    server 127.0.0.1:8083 weight=10;

    keepalive 128;
}

server {
    listen 80;
    server_name static-cdn.company.local;

    location /media/ {
        proxy_pass http://cache_tier;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;

        # Кэш-промахи и сетевые сбои дублируются на соседний узел
        proxy_next_upstream error timeout http_404 http_502;
        proxy_next_upstream_tries 2;
    }
}
```

#### Проверка консистентности распределения:
```bash
# Отправка серии запросов с разными URI
curl -s -I http://static-cdn.company.local/media/image1.jpg | grep X-Cache-Server
# → X-Cache-Server: 127.0.0.1:8082
curl -s -I http://static-cdn.company.local/media/image2.png | grep X-Cache-Server
# → X-Cache-Server: 127.0.0.1:8081
curl -s -I http://static-cdn.company.local/media/image1.jpg | grep X-Cache-Server
# → X-Cache-Server: 127.0.0.1:8082  (повторный запрос гарантированно попал на тот же узел)
```

---

### Сценарий 4: Снижение стадного эффекта с `random two least_conn`

**Задача:** Сконфигурировать балансировку для группы независимых reverse proxy инстансов, обращающихся к общему кластеру микросервисов, устранив эффект лавинного перекоса нагрузки.

```nginx
upstream microservices_pool {
    zone ms_pool_zone 256k;

    # Случайный выбор двух серверов и отправка на узел с наименьшим числом соединений
    random two least_conn;

    server 10.0.3.10:8000 max_fails=3 fail_timeout=10s;
    server 10.0.3.11:8000 max_fails=3 fail_timeout=10s;
    server 10.0.3.12:8000 max_fails=3 fail_timeout=10s;
    server 10.0.3.13:8000 max_fails=3 fail_timeout=10s;

    keepalive 64;
}

server {
    listen 80;
    server_name ms.company.local;

    location / {
        proxy_pass http://microservices_pool;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }
}
```

---

### Сценарий 5: Адаптивная балансировка `feedback` по метрикам приложения (Angie PRO)

**Задача:** Реализовать динамическую подстройку нагрузки на бэкенды в зависимости от утилизации CPU хоста приложения, передаваемой в заголовке `X-App-CPU-Load`.

```nginx
upstream dynamic_compute {
    zone dynamic_compute_zone 256k;

    server 10.10.1.10:8080 weight=100;
    server 10.10.1.11:8080 weight=100;

    # Переменная $upstream_http_x_app_cpu_load содержит значение от 0 до 100
    # Чем выше значение CPU, тем ниже эффективный вес узла (inverse)
    feedback variable=$upstream_http_x_app_cpu_load inverse factor=90;

    keepalive 32;
}

server {
    listen 80;
    server_name compute.company.local;

    location /task/ {
        proxy_pass http://dynamic_compute;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

---

### Сценарий 6: Безаварийный вывод узла из эксплуатации (`drain` / `down`)

**Задача:** Вывести сервер приложения из обслуживания для планового обновления ОС/пакетов без сброса активных сессий пользователей.

```nginx
upstream cluster_app {
    zone cluster_app_zone 128k;

    # Узел 1 выводится на обслуживание:
    # В Angie / Nginx Plus режим drain завершает существующие sticky-сессии, не принимая новых
    server 10.0.4.10:8080 weight=2 drain;

    # Для Nginx OSS узел помечается флагом down для сохранения пространства ip_hash:
    # server 10.0.4.10:8080 down;

    # Рабочие узлы
    server 10.0.4.11:8080 weight=2;
    server 10.0.4.12:8080 weight=2;
}
```

#### Порядок действий администратора (SRE Runbook):
```bash
# 1. Изменение статуса сервера в конфиге на drain (или через runtime API без reload в Angie/Plus)
curl -X POST -d '{"drain": true}' http://127.0.0.1:8080/api/8/http/upstreams/cluster_app/servers/0
# → {"drain": true, "weight": 2, "server": "10.0.4.10:8080"}

# 2. Мониторинг оттока активных соединений до нуля
while true; do
    active=$(ss -tn state established '( dst 10.0.4.10:8080 )' | wc -l)
    echo "Active connections to backend: $active"
    [ "$active" -le 1 ] && break
    sleep 2
done
# → Active connections to backend: 18
# → Active connections to backend: 7
# → Active connections to backend: 1

# 3. Теперь процесс на бэкенде 10.0.4.10 можно безопасно остановить
systemctl stop application
```

---

## Операции и команды

### Управление и проверка конфигурации

```bash
# Валидация синтаксиса всех блоков upstream перед применением
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка полного результирующего конфига со всеми инклюдами
nginx -T | grep -A 15 "upstream "

# Применение изменений алгоритмов балансировки без простоя
nginx -s reload
# → signal reload started
```

### Анализ распределения трафика по бэкендам

```bash
# Подсчет количества запросов, отправленных на каждый бэкенд (последние 10 000 строк лога)
tail -n 10000 /var/log/nginx/app_access.log | awk '{print $8}' | sort | uniq -c | sort -rn
# → 5012 10.0.1.10:8080
# → 3324 10.0.1.11:8080
# → 1664 10.0.1.12:8080

# Онлайн-мониторинг распределения соединений по серверам (требуется ss)
watch -n 1 "ss -tn state established '( dport = :8080 )' | awk '{print \$4}' | cut -d: -f1 | sort | uniq -c"
```

### Диагностика сетевых соединений и keepalive

```bash
# Проверка количества установленных соединений в сторону бэкенд-пула
ss -s
# → TCP: 1420 (estab 840, closed 210, orphaned 0, timewait 370)

# Проверка отсутствия скопления сокетов в TIME_WAIT между Nginx и бэкендами
# Наличие большого числа TIME_WAIT говорит об отсутствии 'proxy_http_version 1.1' или 'proxy_set_header Connection ""'
ss -tn state time-wait '( daddr = 10.0.1.10 and dport = :8080 )' | wc -l
# → 2  (нормальное состояние при работающем keepalive-пуле)
```

### Сбор телеметрии Angie / Prometheus

```bash
# Получение метрик upstream через Prometheus-эндпоинт Angie
curl -s http://127.0.0.1:8080/p_metrics | grep -E "angie_http_upstream_peers_(requests|fails|active)"
# → angie_http_upstream_peers_requests_total{upstream="production_web",peer="10.0.1.10:8080"} 124502
# → angie_http_upstream_peers_active{upstream="production_web",peer="10.0.1.10:8080"} 14
# → angie_http_upstream_peers_fails_total{upstream="production_web",peer="10.0.1.10:8080"} 0
```

---

## Диагностика и устранение неполадок

### Матрица типовых проблем балансировки

| Симптом | Первопричина | Метод локализации | Способ устранения |
| :--- | :--- | :--- | :--- |
| **502 Bad Gateway** на всех входящих запросах | Все бэкенды в `upstream` недоступны или исчерпали лимит `max_fails` | В логе: `no live upstreams while connecting to upstream`. Проверить сокет бэкенда: `nc -zv 10.0.1.10 8080` | Восстановить бэкенды; временно снизить `max_fails` или увеличить `fail_timeout`; проверить локальный firewall (`iptables`/`nftables`) |
| **504 Gateway Timeout** на отдельных запросах | Время обработки запроса превышает `proxy_read_timeout` | Поиск в error.log: `upstream timed out (110: Connection timed out) while reading response header from upstream` | Оптимизировать медленный SQL/код бэкенда; увеличить `proxy_read_timeout` для тяжелых location |
| **503 Service Unavailable** при пиковой нагрузке | Все узлы достигли предела `max_conns`, директива `queue` не задана или очередь переполнена | В error.log: `no available servers, all connections are busy`. В статусе Angie: `queue.overflows > 0` | Увеличить `max_conns`, добавить директиву `queue 100 timeout=10s;`, масштабировать число бэкенд-узлов |
| **Эффект «черной дыры» при `least_conn`** | Бэкенд возвращает мгновенную ошибку (RST или 500) и притягивает весь трафик пула | `least_conn` направляет до 90% запросов на сбоящий сервер, так как число его активных сокетов равно 0 | Добавить `max_fails=3 fail_timeout=10s;` и директиву `proxy_next_upstream error timeout http_500 http_502;` |
| **Жесткий дисбаланс при `ip_hash`** | Большой поток клиентов поступает из одной корпоративной сети /24 (NAT) | Анализ access.log показывает концентрацию трафика на одном IP бэкенда при разнообразии клиентов | Заменить `ip_hash` на `hash $cookie_jsessionid consistent;` или использовать `hash $remote_addr consistent;` |
| **Шторм запросов к БД при рестарте бэкенда** | "Холодный" сервис не успевает прогреть кэши и JIT-компилятор под полной нагрузкой | Высокий load average и 504 Gateway Timeout сразу после возврата сервера в пул | Использовать параметр `slow_start=60s;` в блоке `server` (требует `zone`) |
| **Лавинообразный сброс кэша при флапе узла** | Использован стандартный алгоритм `hash $request_uri` без параметра `consistent` | При падении одной ноды промахи кэша скачкообразно вырастают до 80-90% на всех узлах | Добавить параметр `consistent` (`hash $request_uri consistent;`) для перехода на кольцо Ketama |
| **Сотни сокетов в `TIME_WAIT` к бэкенду** | Отсутствует keepalive к upstream или не очищен заголовок `Connection` | Команда `ss -s` показывает взрывной рост `timewait` сокетов к портам бэкенда | Добавить `proxy_http_version 1.1; proxy_set_header Connection "";` в location и `keepalive 64;` в upstream |

### Диагностические скрипты для администратора

```bash
# 1. Поиск записей о выводе серверов из строя счетчиком fail_timeout
grep -E "no live upstreams|upstream timed out|connect\(\) failed" /var/log/nginx/error.log | tail -n 30

# 2. Выявление бэкендов с наихудшим временем отклика (TTFB > 2.0s)
awk '$NF > 2.0 {print $0}' /var/log/nginx/app_access.log | head -n 20

# 3. Проверка переполнения временными файлами диска при медленных клиентах
grep "an upstream response is buffered to a temporary file" /var/log/nginx/error.log
```

---

## Лучшие практики

### Производительность (Performance Engineering)
1. **Всегда задавайте `zone`:** Любой production-блок `upstream` должен содержать директиву `zone`. Рекомендуемый размер: `64k` для пулов до 200 серверов, `256k`–`512k` для крупных кластеров с очередями `queue` и метриками.
2. **Обязательный Keepalive:** Всегда активируйте keepalive-пул для HTTP-бэкендов:
   - В блоке `upstream`: `keepalive 64;` (на каждый воркер).
   - В блоке `location`: `proxy_http_version 1.1; proxy_set_header Connection "";`. Это экономит до 30-40% процессорного времени на сборку-разборку TCP/TLS сокетов.
3. **Выбор алгоритма под характер нагрузки:**
   - **Веб-статика и Stateless API:** `Round Robin` (с весами при гетерогенном оборудовании).
   - **Долгие запросы, SQL-генераторы, WebSockets:** `least_conn`.
   - **Кэширующие реверс-прокси и CDN:** `hash $request_uri consistent;`.
   - **Крупные кластеры с несколькими балансировщиками:** `random two least_conn;`.
   - **Stateful-приложения с серверными сессиями:** Модуль `sticky` (Angie / Nginx Plus) или `hash $cookie_SESSIONID consistent;`.

### Отказоустойчивость и надежность (SRE / Reliability)
1. **Тонкая настройка таймаутов соединения:**
   ```nginx
   # Не ждите бэкенд дольше 1-2 секунд на фазе TCP handshake
   proxy_connect_timeout 2s;
   proxy_read_timeout 30s;
   proxy_send_timeout 10s;
   ```
2. **Лимитирование каскадных повторов (`proxy_next_upstream`):**
   Всегда ограничивайте максимальное число попыток и общее время поиска дублера:
   ```nginx
   proxy_next_upstream error timeout http_502 http_503;
   proxy_next_upstream_tries 3;
   proxy_next_upstream_timeout 5s;
   ```
   Без `proxy_next_upstream_tries` при массовом сбое запросы клиентов начнут штурмовать все бэкенды по очереди, вызывая каскадный отказ всей фермы серверов.
3. **Плавный ввод в эксплуатацию:** Всегда защищайте приложения на Java (JVM), Node.js, Python и PHP-FPM параметром `slow_start=30s;`–`60s;` при их возвращении в строй после сбоев.

### Безопасность и эксплуатация (Security & Ops)
1. **Санитизация ключей хеширования:** При использовании `hash $variable consistent;` убедитесь, что значение переменной не может быть сгенерировано злоумышленником с неограниченной энтропией для атаки переполнения хеш-таблицы (HashDoS) или искусственной разбалансировки узлов.
2. **Изоляция административных эндпоинтов:** Доступ к API метрик (`/status`, `/p_metrics`, Angie Console) должен быть строго ограничен локальной сетью управления или защищен авторизацией:
   ```nginx
   location /p_metrics {
       allow 127.0.0.1;
       allow 10.50.0.0/16;
       deny all;
   }
   ```

---

## Сравнение возможностей версий

| Функция / Возможность | Nginx Open Source (1.26+) | Nginx Plus | Angie (1.6+ / 1.12+) |
| :--- | :---: | :---: | :---: |
| **Round Robin (с плавным взвешиванием SWRR)** | Да | Да | Да |
| **Least Connections (`least_conn`)** | Да (локально без `zone`) | Да (синхронизировано) | Да (синхронизировано) |
| **IP Hash (`ip_hash`)** | Да | Да | Да |
| **Generic Hash (`hash <key>`)** | Да | Да | Да |
| **Ketama Consistent Hashing (`consistent`)** | Да | Да | Да |
| **Random (`random`)** | Да | Да | Да |
| **Random Two Choices (`random two least_conn`)** | Да | Да | Да |
| **Random Two Least Time (`random two least_time`)** | Нет | Да | Да |
| **Least Time (`least_time header/last_byte`)** | Нет | Да | Да |
| **Least Time с учетом активных (`inflight`)** | Нет | Да | Да |
| **Динамическая обратная связь (`feedback`)** | Нет | Нет | **Да (Angie PRO)** |
| **Зона разделяемой памяти в HTTP upstream (`zone`)** | Нет (только stream) | Да | Да |
| **Очередь запросов (`queue`)** | Нет | Да | Да |
| **Плавный запуск (`slow_start`)** | Нет | Да | Да |
| **Дренаж соединений (`drain`)** | Нет | Да | Да |
| **Динамическое изменение upstream через REST API** | Нет | Да | Да |
| **Встроенный Prometheus-экспортер метрик** | Нет (сторонние модули) | Да | Да |

---

## Дополнительная информация

### Связанные документы
- **[Обзор концепций балансировки](./overview_concepts.md)** — архитектура подсистемы upstream, L4/L7 различия, жизненный цикл соединений.
- **[Практическая конфигурация балансировки](./practical_configuration.md)** — синтаксис директив `upstream`, `proxy_pass`, keepalive и failover.
- **[Health Checks и мониторинг](./health_checks_and_monitoring.md)** — пассивные и активные проверки жизнеспособности бэкендов.
- **[Липкие сессии (Sticky Sessions)](./sticky_sessions.md)** — реализация Session Affinity через cookie, route и заголовочные токены.
- **[Динамическое разрешение DNS](./dynamic_dns_resolution.md)** — работа директивы `resolve` и резолвинг адресов в runtime.
- **[Сравнение балансировщиков](./additional_info_and_comparisons.md)** — сопоставление архитектуры Nginx, Angie, HAProxy и Traefik.
