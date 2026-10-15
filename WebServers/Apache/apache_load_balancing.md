# Apache: Балансировка нагрузки (mod_proxy_balancer)

**Актуально для:** Apache HTTP Server 2.4.x (включая mod_proxy_hcheck в 2.4.31+)

---

## Определения

**mod_proxy_balancer** — модуль расширения `mod_proxy`, обеспечивающий распределение входящих запросов между группой бэкенд-серверов на прикладном уровне (L7 OSI). Работает совместно с протокольными модулями `mod_proxy_http`, `mod_proxy_ajp`, `mod_proxy_fcgi` и `mod_proxy_wstunnel`.

**Balancer (`balancer://`)** — виртуальный целевой URI и логический кластер, объединяющий группу рабочих узлов (`BalancerMember`), на которые Apache распределяет сетевой трафик.

**BalancerMember** — отдельный рабочий узел (worker/бэкенд) внутри балансировщика. Характеризуется сетевым адресом (IP:порт, FQDN или путь к Unix Domain Socket), весовым коэффициентом (`loadfactor`), приоритетной группой (`lbset`) и административным статусом.

**`mod_slotmem_shm`** — модуль провайдера разделяемой памяти (shared memory scoreboard). Критически необходим для синхронизации состояния воркеров, счетчиков переданных байт, количества ошибок и динамических изменений между процессами MPM (event/worker) и при graceful-перезагрузках.

**`mod_lbmethod_*`** — семейство подключаемых модулей алгоритмов балансировки: `byrequests` (по взвешенному числу запросов), `bytraffic` (по объёму трафика в байтах), `bybusyness` (по числу активных запросов в обработке) и `heartbeat` (по внешним сигналам загрузки).

**Sticky Session (сессионная привязка)** — механизм направления повторных запросов одного и того же клиента на конкретный бэкенд на время сессии (через Cookie или параметр в URI с заданным суффиксом маршрута `route`).

**`mod_proxy_hcheck`** — модуль активных проверок работоспособности (Active Health Checks, доступен с Apache 2.4.31). Выполняет периодические независимые фоновые HTTP/TCP-запросы к узлам вне клиентского трафика.

**`lbset` (Load Balancer Set)** — числовой уровень приоритета группы серверов (0, 1, 2...). Запросы направляются на воркеры с наименьшим номером `lbset`, пока среди них доступен хотя бы один узел; более высокие `lbset` используются как резервные пулы.

**Drain mode (`+N`)** — режим плавного вывода воркера из эксплуатации для планового обслуживания (rolling update): принимает только существующие сессии (по sticky route), отклоняя все новые запросы в пользу других узлов кластера.

---

## Основные концепции

### Архитектура и взаимодействие компонентов

Apache выполняет роль L7-балансировщика: принимает клиентские TCP/TLS-соединения, парсит HTTP-заголовки и cookie, выбирает целевой бэкенд по алгоритму `lbmethod` с учетом sticky-маршрута и пересылает запрос по HTTP/HTTPS, AJP13 или FastCGI.

```text
[Клиенты]
   │
   ▼
[Apache HTTP Server 2.4 (MPM event / worker)]
   │
   ├──► [mod_slotmem_shm] ─── (Разделяемая память: статусы, счетчики, веса)
   │
   ├──► [mod_proxy_balancer] ── (Выбор алгоритма: byrequests / bybusyness / bytraffic)
   │         │
   │         ├──► lbset=0 (Основной рабочий пул)
   │         │       ├──► BalancerMember 1: 10.0.0.11:8080 (route=node1, loadfactor=1)
   │         │       ├──► BalancerMember 2: 10.0.0.12:8080 (route=node2, loadfactor=2)
   │         │       └──► BalancerMember 3: 10.0.0.13:8080 (status=+R — Hot Spare)
   │         │
   │         └──► lbset=1 (Резервный аварийный пул / DR)
   │                 └──► BalancerMember 4: 10.0.0.21:8080 (status=+H — Hot Standby)
   │
   └──► [mod_proxy_hcheck] ── (Фоновый watchdog: активные healthcheck GET /healthz)
```

#### Роль разделяемой памяти (`mod_slotmem_shm`)

В многопроцессных архитектурах Apache (MPM `event` и `worker`) обслуживание запросов распределено между несколькими процессами ОС. Без общей памяти каждый процесс вел бы собственные независимые счетчики запросов и не знал бы об отключении воркеров другими процессами.

`mod_slotmem_shm` создает сегмент памяти (scoreboard), в котором хранятся:
- текущие флаги статуса каждого `BalancerMember` (`+E`, `+D`, `+N`, `+H` и т. д.);
- счетчики переданных и принятых байт, число активных коннектов (`busy`) и число обработанных запросов;
- параметры, измененные динамически через веб-интерфейс `balancer-manager`.

Благодаря `mod_slotmem_shm` состояние кластера не теряется при выполнении `apachectl graceful` (перезагрузка без разрыва соединений). Файлы сегментов создаются в системном каталоге рантайма (например, `/run/httpd/` в RHEL или `/var/run/apache2/` в Debian).

#### Пул соединений к бэкенду (Connection Pooling)

Каждый рабочий процесс Apache поддерживает пул постоянных TCP-соединений к каждому `BalancerMember`. Параметры пула настраиваются директивами воркера:
- `min` — минимальное число соединений, удерживаемых открытыми (по умолчанию 0);
- `smax` — мягкий лимит соединений; соединения сверх `smax` закрываются по истечении таймаута неактивности `ttl`;
- `max` — жесткий лимит одновременных открытых соединений на один рабочий процесс;
- `acquire` — максимальное время ожидания (в миллисекундах или секундах) свободного слота из пула перед возвратом ошибки клиенту;
- `ttl` — время жизни неактивного соединения в пуле (сек);
- `keepalive=On` — удерживать открытые TCP-сессии к бэкенду между последовательными запросами клиентов.

---

### Алгоритмы выбора (lbmethod)

Алгоритм балансировки задается параметром `lbmethod` в директиве `<Proxy balancer://...>` или `ProxySet`:

| Метод | Модуль | Принцип работы | Оптимальное применение |
|---|---|---|---|
| `byrequests` | `mod_lbmethod_byrequests` (по умолчанию) | Взвешенный циклический перебор (Weighted Round Robin) на основе числа запросов и `loadfactor` | Однородные бэкенды и короткие запросы одинаковой вычислительной сложности |
| `bytraffic` | `mod_lbmethod_bytraffic` | Ротация с учетом суммарного сетевого объема (байт отправлено/получено) | Отдача статики, медиафайлов или генерация ответов сильно различающегося размера |
| `bybusyness` | `mod_lbmethod_bybusyness` | Направление запроса на узел с наименьшим числом текущих активных задач (`busy workers`) | Тяжелые API, сложные вычисления в СУБД, запросы с непрогнозируемым временем обработки |
| `heartbeat` | `mod_lbmethod_heartbeat` | Выбор воркера на основе коэффициентов загрузки, получаемых через `mod_heartmonitor` | Продвинутые динамические фермы серверов с частым изменением нагрузки |

**Расчет весов (`loadfactor`):**
Параметр `loadfactor` задается целым числом (от 1 до 100). При `byrequests` сервер с `loadfactor=2` получит вдвое больше запросов, чем сервер с `loadfactor=1`. При алгоритме `bybusyness` сервер с более высоким `loadfactor` допускает пропорционально большее количество параллельных активных соединений до переключения на соседа.

---

### Статусы воркеров и многоуровневый Failover

Каждый `BalancerMember` имеет набор флагов состояния. Флаги можно задать статически в конфигурации параметром `status` либо переключать в рантайме через `balancer-manager`.

Префикс `+` устанавливает флаг, префикс `-` снимает его. Несколько флагов можно комбинировать (например, `status=+D+H`).

| Флаг | Официальное название | Назначение и поведение |
|---|---|---|
| `+D` | Disabled | Воркер отключен. Не принимает новые запросы общего пула, но **продолжает обслуживать запросы с существующей sticky-сессией**, адресованной именно ему |
| `+S` | Stopped | Воркер остановлен административно. Не принимает никаких запросов вообще, включая sticky-сессии |
| `+I` | Ignore Errors | Режим игнорирования сбоев. Воркер никогда не переводится в статус ошибки (`+E`) при сетевых или HTTP-сбоях |
| `+R` | Hot Spare | Горячий резерв внутри своего `lbset`. Активируется только в случае, если хотя бы один рабочий узел того же `lbset` вышел из строя (`+E`), выведен на обслуживание (`+D`/`+N`) или остановлен (`+S`) |
| `+H` | Hot Standby | Глобальный резерв балансировщика. Получает трафик исключительно тогда, когда **все** остальные воркеры и резервы (`+R`) в пуле недоступны |
| `+E` | Error | Воркер находится в состоянии сбоя. Запросы на него не направляются в течение времени `retry` (по умолчанию 60 сек). Выставляется Apache автоматически при разрыве связи, таймауте или кодах `failonstatus` |
| `+N` | Drain Mode | Режим плавного дренажа (Rolling Update). Воркер обслуживает **только** свои существующие sticky-сессии. Все новые сессии направляются на соседние доступные узлы |

#### Приоритетные группы (`lbset`)

Параметр `lbset` (целое число, по умолчанию 0) позволяет реализовать каскадную схему отказоустойчивости:
1. Трафик направляется на воркеры с наименьшим номером `lbset` (например, `lbset=0`).
2. Если в `lbset=0` падают один или несколько узлов, но настроен воркер с `status=+R` (в том же `lbset=0`), трафик перехватывает он.
3. Только когда **все** члены `lbset=0` оказываются в статусе ошибки (`+E`) или остановлены, балансировщик переключает поток запросов на следующий уровень — `lbset=1` (например, резервный ЦОД или аварийные серверы).
4. Как только хотя бы один узел в `lbset=0` восстанавливается (по истечении `retry` или прохождению проверки `mod_proxy_hcheck`), Apache автоматически возвращает трафик на `lbset=0`.

---

### Sticky Sessions (Сессионная привязка)

Для приложений с хранением сессии в локальной памяти конкретного бэкенда (in-memory sessions без общей БД или Redis) необходима фиксация клиента за одним сервером.

```apacheconf
ProxySet stickysession=JSESSIONID|jsessionid
ProxySet stickysessionsep=.
ProxySet scolonpathdelim On
ProxySet nofailover=On
```

1. **Разделитель `|` в имени:** первая часть задает имя Cookie (`JSESSIONID`), вторая — имя GET/POST/Path-параметра (`jsessionid`) для клиентов с отключенными cookies.
2. **Маршрутизация по суффиксу:** бэкенд формирует значение сессии с суффиксом узла через точку: `<session_id>.<route_name>` (например, `s59a8c1f.node1`). Параметр `route=node1` директивы `BalancerMember` указывает Apache, что данный запрос принадлежит этому воркеру.
3. **Разделитель маршрута (`stickysessionsep`):** по умолчанию используется символ точки `.`. Для серверов Oracle WebLogic или старых версий JBoss/WebSphere используется восклицательный знак (`stickysessionsep=!`) либо `Off`.
4. **Параметры пути через точку с запятой (`scolonpathdelim`):** при `scolonpathdelim On` Apache поддерживает URL вида `/app/path;JSESSIONID=xyz.node1`.
5. **Поведение при сбое узла (`nofailover`):**
   - `nofailover=Off` (по умолчанию) — если целевой узел упал (`+E`), запрос перенаправляется на любой другой живой узел (пользователь может потерять несохраненные данные в сессии, но не получит HTTP 503).
   - `nofailover=On` — если целевой узел недоступен, запрос сразу возвращает клиенту ошибку `503 Service Unavailable`, не пытаясь отправить его на другой узел. Это предотвращает порчу данных в распределенных приложениях без синхронизации сессий.

---

### Параметры таймингов и защита от зависаний пула

Для предотвращения исчерпания потоков MPM (Thread Starvation) при зависании бэкендов настраиваются жесткие таймауты:

- `connectiontimeout` (сек) — время ожидания завершения TCP-рукопожатия (SYN-ACK) с бэкендом. В локальной сети рекомендуется ставить 1–3 секунды, чтобы быстро детектировать отключенные или зависшие узлы.
- `timeout` (сек) — таймаут чтения и записи данных после установки соединения. Если бэкенд не ответил в течение этого времени, возвращается HTTP 504/502.
- `ping` (сек) — превентивная проверка сокета перед отправкой тела запроса:
  - Для HTTP: отправка `100-Continue` перед телом запроса POST/PUT.
  - Для AJP: отправка тестового пакета `CPing` и ожидание ответа `CPong`.
  - Значение `ping=1` указывает ждать подтверждения до 1 секунды.
- `retry` (сек) — время, в течение которого воркер в статусе `+E` считается недоступным и не опрашивается клиентами (по умолчанию 60 сек).
- `failonstatus` — список HTTP-кодов ошибок бэкенда (например, `500,502,503`), при получении которых узел немедленно переводится в статус ошибки `+E`.
- `failontimeout=On` — при наступлении IO-таймаута чтения ответа переводить узел в статус ошибки `+E`.
- `forcerecovery` — поведение при отказе всех воркеров:
  - `forcerecovery=On` (по умолчанию) — если все узлы в ошибке, немедленно пробовать посылать запросы, игнорируя `retry`.
  - `forcerecovery=Off` — строго выдерживать `retry` для каждого воркера, защищая перегруженные серверы от эффекта «лавины» (Thundering Herd).

---

## Практические сценарии

### 1. Отказоустойчивый пул HTTP/HTTPS с защитой от зависания

Балансировка веб-приложений с проверкой соединения, быстрыми таймаутами и алгоритмом наименее загруженного узла (`bybusyness`).

```apacheconf
# /etc/apache2/conf-available/load-balancer.conf (Debian/Ubuntu)
# или /etc/httpd/conf.d/load-balancer.conf (RHEL/Rocky)

<Proxy balancer://app_cluster>
    # Основные рабочие узлы
    BalancerMember http://10.0.0.11:8080 loadfactor=1 route=node1 connectiontimeout=2 timeout=30 ping=1 retry=10
    BalancerMember http://10.0.0.12:8080 loadfactor=1 route=node2 connectiontimeout=2 timeout=30 ping=1 retry=10

    # Алгоритм распределения: наименее загруженный узел
    ProxySet lbmethod=bybusyness
    
    # Фиксация сбоев: при кодах 500/502/503 или таймауте узел уходит в +E на retry=10 сек
    ProxySet failonstatus=500,502,503
    ProxySet failontimeout=On
    
    # Максимальное число попыток перебора узлов при ошибке
    ProxySet maxattempts=2
</Proxy>

# Проксирование входящего трафика
ProxyPass / balancer://app_cluster/
ProxyPassReverse / balancer://app_cluster/
```

Включение необходимых модулей в системе:

```bash
# Debian / Ubuntu:
sudo a2enmod proxy proxy_balancer proxy_http slotmem_shm lbmethod_bybusyness
# → Enabling module proxy.
# → Enabling module proxy_balancer.
# → Enabling module proxy_http.
# → Enabling module slotmem_shm.
# → Enabling module lbmethod_bybusyness.

sudo apache2ctl configtest
# → Syntax OK

sudo systemctl reload apache2
# → (перезагрузка конфигурации без разрыва существующих соединений)
```

```bash
# RHEL / Rocky Linux / AlmaLinux:
# Убедитесь, что модули раскомментированы в /etc/httpd/conf.modules.d/00-proxy.conf
sudo apachectl configtest
# → Syntax OK

sudo systemctl reload httpd
# → (успешное применение конфигурации)
```

---

### 2. Многоуровневый кластер: основной пул (lbset=0), Hot Spare (+R) и аварийный DR (lbset=1, +H)

Сценарий с основным пулом из двух серверов, одним локальным горячим резервом и внешней аварийной нодой в DR-локации.

```apacheconf
<Proxy balancer://ha_production>
    # --- Уровень 0: Основные серверы площадки ---
    BalancerMember http://10.0.1.11:8080 loadfactor=10 lbset=0 route=prod01
    BalancerMember http://10.0.1.12:8080 loadfactor=10 lbset=0 route=prod02
    
    # --- Уровень 0: Горячий резерв внутри площадки (+R) ---
    # Активируется только при падении prod01 или prod02
    BalancerMember http://10.0.1.13:8080 status=+R lbset=0 route=prod_spare
    
    # --- Уровень 1: Аварийная нода в резервном ЦОД (+H) ---
    # Получает трафик только если упали prod01, prod02 И prod_spare
    BalancerMember http://10.0.2.11:8080 status=+H lbset=1 route=dr_node
    
    ProxySet lbmethod=byrequests
    ProxySet timeout=10
    ProxySet retry=15
</Proxy>

ProxyPass /api/ balancer://ha_production/api/
ProxyPassReverse /api/ balancer://ha_production/api/
```

---

### 3. Активные Health Checks через mod_proxy_hcheck

В отличие от пассивных проверок (`failonstatus`), модуль `mod_proxy_hcheck` отправляет фоновые независимые запросы через watchdog-поток. Клиенты никогда не получают ошибку из-за проверки упавшего узла.

```apacheconf
# Включение модулей: proxy_hcheck и watchdog
LoadModule watchdog_module modules/mod_watchdog.so
LoadModule proxy_hcheck_module modules/mod_proxy_hcheck.so

# Определение выражений валидации ответа (ProxyHCExpr)
# Проверка HTTP-статуса (2xx или 3xx)
ProxyHCExpr ok234 {%{REQUEST_STATUS} =~ /^[234][0-9][0-9]$/}

# Проверка содержимого JSON-тела ответа (например, {"status":"UP"})
ProxyHCExpr json_up {%{BODY} =~ /"status":\s*"UP"/}

<Proxy balancer://hcheck_cluster>
    BalancerMember http://10.0.0.11:8080 route=app1 \
        hcmethod=GET hcuri=/healthz hcinterval=5 hcexpr=json_up hcfails=3 hcpasses=2
        
    BalancerMember http://10.0.0.12:8080 route=app2 \
        hcmethod=GET hcuri=/healthz hcinterval=5 hcexpr=json_up hcfails=3 hcpasses=2

    ProxySet lbmethod=bybusyness
</Proxy>

ProxyPass / balancer://hcheck_cluster/
ProxyPassReverse / balancer://hcheck_cluster/
```

- `hcmethod=GET` — метод проверки (`GET`, `HEAD`, `OPTIONS`, `TCP`);
- `hcuri=/healthz` — URI эндпоинта проверки;
- `hcinterval=5` — интервал опроса (каждые 5 секунд);
- `hcexpr=json_up` — применяемое правило проверки;
- `hcfails=3` — после 3 подряд неудачных проверок узел маркируется как упавший;
- `hcpasses=2` — после 2 успешных проверок узел автоматически возвращается в ротацию.

---

### 4. Zero-Downtime Rolling Update: вывод воркера в режим Drain (`+N`)

Режим дренажа (`+N`) позволяет администраторам обновлять бэкенды без сброса активных клиентских сессий и без генерации ошибок 502/503.

```
+──────────────────────────+
│ 1. Установка status=+N   │ ──► Новые сессии уходят на node2.
│    на узле node1         │     Клиенты с cookie node1 продолжают работать с node1.
+──────────────────────────+
             │
             ▼
+──────────────────────────+
│ 2. Ожидание завершения   │ ──► Мониторинг соединений через ss / balancer-manager.
│    активных соединений   │     Достижение BusyWorkers = 0.
+──────────────────────────+
             │
             ▼
+──────────────────────────+
│ 3. Обновление и деплой   │ ──► Остановка приложения на node1, накат релиза,
│    на узле node1         │     запуск и локальная проверка (curl http://localhost:8080).
+──────────────────────────+
             │
             ▼
+──────────────────────────+
│ 4. Снятие флага (-N)     │ ──► Узел node1 снова принимает новые соединения кластера.
+──────────────────────────+
```

Пошаговые команды для SRE/DevOps инженера приведены в разделе [Операции и команды](#операции-и-команды).

---

### 5. Балансировка локальных сервисов через Unix Domain Sockets (UDS)

Для сервисов на том же хосте (PHP-FPM пулы, Gunicorn, Uvicorn) обращение через UDS исключает оверхед сетевого стека loopback, утилизацию TCP-портов и проблему TIME_WAIT.

```apacheconf
<Proxy balancer://php_uds_pool>
    # Балансировка между двумя сокетами PHP-FPM с весами
    BalancerMember unix:/run/php/php8.2-fpm-pool1.sock|fcgi://localhost loadfactor=1
    BalancerMember unix:/run/php/php8.2-fpm-pool2.sock|fcgi://localhost loadfactor=1
    
    ProxySet lbmethod=bybusyness
</Proxy>

# Передача обработки PHP файлов в балансировщик сокетов
<FilesMatch \.php$>
    SetHandler "proxy:balancer://php_uds_pool"
</FilesMatch>
```

Для HTTP-серверов (например, Python/Node.js) используется схема `unix:/path.sock|http://localhost/`.

---

### 6. Защищенный `balancer-manager` и управление через CLI

Модуль веб-интерфейса `balancer-manager` позволяет в режиме реального времени просматривать метрики, менять веса воркеров и переключать статусы (`Drain`, `Disable`, `Stop`) без перезапуска веб-сервера.

```apacheconf
# /etc/apache2/conf-available/balancer-manager.conf

<Location "/balancer-manager">
    SetHandler balancer-manager
    
    # Защита от CSRF атак через UUID-токен
    # Параметр задается в блоке <Proxy>: ProxySet nonce=<auto|None|secret_string>
    
    # Ограничение доступа: только локальный хост и сеть управления (Jump host)
    Require ip 127.0.0.1 ::1 192.168.10.0/24
    
    # Опционально: базовая аутентификация для дополнительной защиты
    AuthType Basic
    AuthName "Load Balancer Administration"
    AuthUserFile /etc/apache2/.htpasswd-admin
    Require valid-user
</Location>
```

---

### 7. Балансировка Tomcat по протоколу AJP13

AJP13 — бинарный протокол взаимодействия веб-сервера с сервлетами Apache Tomcat.

```apacheconf
LoadModule proxy_ajp_module modules/mod_proxy_ajp.so

<Proxy balancer://tomcat_cluster>
    BalancerMember ajp://10.0.0.21:8009 route=tomcat1 secret=StrongSecretKey ping=1
    BalancerMember ajp://10.0.0.22:8009 route=tomcat2 secret=StrongSecretKey ping=1
    BalancerMember ajp://10.0.0.23:8009 status=+H secret=StrongSecretKey
    
    ProxySet stickysession=JSESSIONID
    ProxySet lbmethod=byrequests
    ProxySet timeout=60
    ProxySet retry=10
</Proxy>

ProxyPass /app/ balancer://tomcat_cluster/app/
ProxyPassReverse /app/ balancer://tomcat_cluster/app/
```

> [!NOTE]
> При использовании Apache Tomcat 8.5.51+, 9.0.31+ обязателен параметр `secret` (директива `secretRequired="true"` в `server.xml` Tomcat). Подробное описание приведено в руководстве [AJP-интеграция Tomcat](./apache-tomcat-ajp.md).

---

### 8. Сквозные сессии на стороне Apache (`mod_session`)

Если бэкенды не поддерживают сессионную репликацию и не умеют выставлять sticky-маршруты, Apache может самостоятельно шифровать сессию и хранить ее в клиентском Cookie:

```apacheconf
LoadModule session_module modules/mod_session.so
LoadModule session_cookie_module modules/mod_session_cookie.so
LoadModule session_crypto_module modules/mod_session_crypto.so

Session On
SessionCryptoPassphrase "c4a7f920b1e449a5b39e6a98df123456"
SessionCookieName session path=/; HttpOnly; Secure; SameSite=Lax

# Запросы можно распределять на любой бэкенд без sticky-сессий
ProxyPass / balancer://app_cluster/
ProxyPassReverse / balancer://app_cluster/
```

Подробнее о криптографической защите сессий см. [Аутентификация: mod_session](./apache_authentication.md).

---

## Операции и команды

### Сводная таблица команд администратора

| Команда | Назначение | Ожидаемый вывод (`# → result`) |
|---|---|---|
| `apachectl -M \| grep -E 'proxy\|slotmem\|lbmethod'` | Проверка загруженных модулей балансировки | `# → proxy_module (shared)`<br>`# → proxy_balancer_module (shared)`<br>`# → slotmem_shm_module (shared)`<br>`# → lbmethod_bybusyness_module (shared)` |
| `apachectl configtest` | Валидация синтаксиса конфигурации | `# → Syntax OK` |
| `apachectl graceful` | Мягкая перезагрузка без разрыва соединений клиентов | `# → (код возврата 0, процессы обновлены без сброса scoreboard)` |
| `curl -s "http://127.0.0.1/server-status?auto" \| grep -A 5 "Proxy LoadBalancer"` | Просмотр состояния балансировщиков в mod_status | `# → ServerVersion: Apache/2.4.62`<br>`# → Proxy LoadBalancer [balancer://app_cluster]`<br>`# → Member[http://10.0.0.11:8080]: Elected[1420] Sent[1.4M] Rcvd[8.2M]` |
| `ss -tnp state established '( dport = :8080 )'` | Просмотр активных соединений пула Apache к бэкенду | `# → ESTAB 0 0 10.0.0.1:45120 10.0.0.11:8080 users:(("httpd",pid=1240,fd=28))` |
| `ls -la /run/httpd/slotmem* /var/run/apache2/slotmem* 2>/dev/null` | Проверка файлов разделяемой памяти scoreboard | `# → -rw-r--r-- 1 root root 4096 Oct 14 12:00 /run/httpd/slotmem-shm-p9f3c1b8_balancer.shm` |

---

### Автоматизация Drain-режима через CLI / curl

Перевод воркера в режим обслуживания через API `balancer-manager` (для использования в bash-скриптах и CI/CD пайплайнах):

```bash
#!/usr/bin/env bash
set -euo pipefail

BALANCER_URL="http://127.0.0.1/balancer-manager"
BALANCER_NAME="app_cluster"
WORKER_URL="http://10.0.0.11:8080"

# 1. Получение актуального защитного токена nonce из страницы balancer-manager
NONCE=$(curl -s "$BALANCER_URL" | grep -oP 'name="nonce" value="\K[^"]+' | head -n1)
echo "Получен CSRF nonce: ${NONCE}"
# → Получен CSRF nonce: e7b10294-814d-4c31-9f93-01824efc981a

# 2. Перевод воркера в режим DRAIN (+N)
# w_status_N=1 включает флаг дренажа
curl -s -X POST "$BALANCER_URL" \
    -d "b=${BALANCER_NAME}" \
    -d "w=${WORKER_URL}" \
    -d "nonce=${NONCE}" \
    -d "w_status_N=1" \
    -d "w_status_D=0" \
    -d "w_status_S=0" > /dev/null

echo "Воркер ${WORKER_URL} переведен в режим DRAIN (+N)"
# → Воркер http://10.0.0.11:8080 переведен в режим DRAIN (+N)

# 3. Ожидание оттока активных соединений (BusyWorkers = 0)
while true; do
    BUSY=$(curl -s "${BALANCER_URL}?b=${BALANCER_NAME}&w=${WORKER_URL}" | grep -oP 'Busy:[^0-9]*\K[0-9]+' || echo "0")
    if [ "$BUSY" -eq 0 ]; then
        echo "Все активные сессии завершены. Можно безопасно обновлять сервис."
        break
    fi
    echo "Ожидание завершения соединений... Активно: ${BUSY}"
    sleep 2
done

# 4. После завершения обновления: возврат воркера в активный режим (-N)
curl -s -X POST "$BALANCER_URL" \
    -d "b=${BALANCER_NAME}" \
    -d "w=${WORKER_URL}" \
    -d "nonce=${NONCE}" \
    -d "w_status_N=0" > /dev/null

echo "Воркер ${WORKER_URL} возвращен в активную ротацию кластера."
# → Воркер http://10.0.0.11:8080 возвращен в активную ротацию кластера.
```

---

### Структурированное логирование балансировщика для SRE

`mod_proxy_balancer` экспортирует переменные окружения, позволяющие зафиксировать в логах точный маршрут и поведение sticky-сессии:

```apacheconf
# /etc/apache2/conf-available/log-balancer.conf

# Формат лога с информацией о балансировке
LogFormat "%h %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\" \
worker=\"%{BALANCER_WORKER_NAME}e\" \
route=\"%{BALANCER_WORKER_ROUTE}e\" \
sticky=\"%{BALANCER_SESSION_STICKY}e\" \
sticky_route=\"%{BALANCER_SESSION_ROUTE}e\" \
route_changed=\"%{BALANCER_ROUTE_CHANGED}e\" \
latency_ms=%D" balancer_combined

CustomLog /var/log/apache2/balancer-access.log balancer_combined
```

Пример записи в логе:
```text
192.168.1.50 - - [14/Oct/2026:14:10:05 +0300] "GET /api/cart HTTP/1.1" 200 1450 "-" "Mozilla/5.0" worker="http://10.0.0.11:8080" route="node1" sticky="JSESSIONID" sticky_route="node1" route_changed="0" latency_ms=18400
```
- `BALANCER_WORKER_NAME` — адрес реального воркера, обработавшего запрос;
- `BALANCER_WORKER_ROUTE` — route воркера;
- `BALANCER_SESSION_STICKY` — имя использованной сессионной cookie;
- `BALANCER_ROUTE_CHANGED` — флаг `1`, если узел сменился из-за сбоя исходного сервера (failover).

---

## Типичные ошибки и диагностика

| Симптом / Ошибка | Первопричина | Команда диагностики | Способ устранения |
|---|---|---|---|
| `503 Service Unavailable`<br>`AH01174: no member is available for balancer` | Все члены пула помечены как неработающие (`+E`), либо выведены в `+D`/`+S` | `curl -s http://127.0.0.1/balancer-manager \| grep -E 'Status\|Worker'` | 1. Проверить доступность портов бэкендов (`nc -zvw2 10.0.0.11 8080`).<br>2. Проверить `retry` — уменьшить с 60 до 5–10 сек.<br>3. Убедиться, что `failonstatus` не срабатывает на штатные ответы приложения. |
| `AH01114: HTTP: failed to make a connection to backend` | Бэкенд не принимает TCP-соединение (SYN timeout, переполнен backlog, бэкенд остановлен) | `ss -tulpn \| grep :8080`<br>`dmesg \| grep -i syn` | 1. Запустить процесс бэкенда.<br>2. Увеличить `somaxconn` в `/etc/sysctl.conf` на бэкенде.<br>3. Выставить `connectiontimeout=2` для быстрого перехода на запасной узел. |
| `AH02611: create: apr_shm_create() failed / Slotmem empty` | Не загружен модуль `mod_slotmem_shm`, либо нет прав на каталог `/run/httpd/`, либо исчерпаны лимиты IPC | `ipcs -m`<br>`ls -ld /run/httpd /var/run/apache2` | 1. Загрузить `mod_slotmem_shm`.<br>2. Проверить права каталога рантайма (`chown www-data /var/run/apache2` или `apache /run/httpd`).<br>3. Очистить зависшие сегменты памяти (`ipcrm -m <shmid>`). |
| Sticky sessions не работают: запросы переключаются между серверами | 1. Не совпадает суффикс `route` и имя в Cookie.<br>2. Приложение использует разделитель `!` вместо точки `.`.<br>3. Отсутствует имя сессии в `stickysession`. | `curl -sI -H "Cookie: JSESSIONID=abc.node1" http://127.0.0.1/`<br>Проверить заголовки `Set-Cookie` от бэкенда | 1. Согласовать параметр `route=node1` с конфигурацией бэкенда (`jvmRoute="node1"` в Tomcat).<br>2. Указать `ProxySet stickysessionsep=!` при необходимости.<br>3. Добавить разделитель пути `stickysession=JSESSIONID\|jsessionid`. |
| Исчерпание потоков Apache при деградации одного бэкенда | Отсутствуют таймауты подключения: потоки MPM зависают в ожидании ответов деградировавшего узла | `curl -s http://127.0.0.1/server-status?auto \| grep BusyWorkers`<br>`ss -tnp \| grep :8080` | 1. Настроить жесткие таймауты: `connectiontimeout=2 timeout=30 ping=1`.<br>2. Задействовать `mod_proxy_hcheck` для независимой изоляции проблемных узлов. |
| Неравномерная загрузка серверов при `byrequests` | Запросы имеют кардинально разное время обработки (один запрос висит 5 секунд, другой — 10 мс) | `curl -s "http://127.0.0.1/server-status?auto"` | Заменить алгоритм `byrequests` на `bybusyness` (`ProxySet lbmethod=bybusyness`), который учитывает реально занятые сокеты. |
| Thundering Herd (лавинная перегрузка) при подъеме упавших узлов | Параметр `forcerecovery=On` заставляет Apache мгновенно направлять всю массу запросов на восстановившийся узел | Анализ всплеска CPU и логов бэкенда в момент перезапуска | Установить `ProxySet forcerecovery=Off`. Apache будет соблюдать интервалы `retry` и плавно распределять запросы. |

---

## Лучшие практики

1. **Всегда загружать `mod_slotmem_shm`:**
   В MPM `event` и `worker` разделяемая память обязательна. Без нее кластер деградирует в несвязанные сегменты процессов, а graceful-перезагрузки сбрасывают состояние балансировщика.

2. **Задавать защитную триаду таймингов:**
   Для каждого `BalancerMember` явно указывайте:
   ```apacheconf
   BalancerMember http://10.0.0.11:8080 connectiontimeout=2 timeout=30 ping=1 retry=10
   ```
   Это предотвращает ступор веб-сервера при падении промежуточных сетевых шлюзов или бэкенд-демонов.

3. **Использовать Drain (`+N`) вместо Disable (`+D`) при деплоях:**
   Режим `+D` не дает новым пользователям зайти, но и не гарантирует корректную изоляцию в сценариях без явных cookies. Флаг `+N` (Drain) спроектирован специально для бесшовного обновления: существующие сессии отрабатывают до конца, новые клиенты получают свежие ноды.

4. **Выбирать `bybusyness` для динамических приложений:**
   Для микросервисов, REST API и приложений с переменным временем ответа алгоритм `bybusyness` обеспечивает наименьшее время отклика (p95/p99 latency) по сравнению с примитивным `byrequests`.

5. **Ограничивать и изолировать `balancer-manager`:**
   Никогда не публикуйте интерфейс `balancer-manager` в Интернет. Размещайте его исключительно на внутреннем порту управления, защищайте через `Require ip` доверенной подсети администраторов, TLS и Basic Auth. Проверяйте наличие автоматического токена `ProxySet nonce=<auto>`.

6. **Включать `ProxyStatus On` для интеграции с Prometheus:**
   Директива `ProxyStatus On` включает экспорт детальной статистики балансировщика в `mod_status` (`/server-status?auto`). Утилита `apache_exporter` считывает метрики каждого воркера (`apache_worker_status`, `apache_worker_elected`, `apache_worker_sent_bytes`), позволяя настраивать алерты в Alertmanager при переходе узлов в статус `+E`.

7. **Защита от Thundering Herd:**
   Для тяжелых приложений с долгим прогревом кэша и инициализацией пулов БД выставляйте `ProxySet forcerecovery=Off`.

---

## Дополнительная информация

### См. также

*   [Обзор Apache HTTP Server](./apache_overview.md) — общая архитектура, MPM-модули и базовая конфигурация.
*   [Обратное проксирование: продвинутые сценарии](./apache-reverse-proxy-advanced.md) — маппинг путей `ProxyPassMatch`, перезапись заголовков и cookies (`ProxyPassReverseCookieDomain`).
*   [AJP-интеграция Tomcat](./apache-tomcat-ajp.md) — детальная настройка протокола AJP13, `secret` и `jvmRoute`.
*   [Аутентификация: mod_session](./apache_authentication.md) — серверные и зашифрованные клиентские сессии для балансировки без session-stickiness.
*   [Тюнинг производительности Apache](./apache_performance_tuning.md) — оптимизация пулов соединений, MPM event и сокетов ОС.
*   [Харденинг и безопасность Apache](./apache_hardening.md) — изоляция интерфейсов управления, минимизация прав и заголовки безопасности.
*   [Миграция с Apache на Nginx](../Nginx/Scenarios/nginx-migration-from-apache.md) — сопоставление директив `mod_proxy_balancer` и `upstream`.
*   [Обзор и концепции балансировки Nginx](../Nginx/Proxy/Load_Balancing/overview_concepts.md) — архитектурные отличия балансировки Nginx и Apache.
*   [Балансировка нагрузки HTTP в Angie](../Angie/angie_http_load_balancing.md) — сравнение механизмов upstream, shared memory zones и проверок доступности.