# Балансировка нагрузки между локациями с HAProxy

**Актуально для:** HAProxy 2.8 LTS / 3.0+ / 3.2+

Материал основан на архитектурных паттернах распределения трафика и докладе Максима Куприянова «Использование HAProxy для балансировки нагрузки между локациями». Описанные механизмы (stick table, peers, конвертеры значений, разделение проверок `track`) являются штатными возможностями линеек HAProxy 2.x и 3.x. Базовые принципы работы балансировщика представлены в [обзоре HAProxy](../haproxy_overview.md).

## Определения

**RPS (Requests Per Second)** — количество входящих HTTP-запросов, обрабатываемых системой за одну секунду. Базовая метрика интенсивности входящего сетевого трафика.

**Stick Table** — высокопроизводительное key-value хранилище в разделяемой оперативной памяти процесса HAProxy. Применяется для rate limiting, фиксации пользовательских сессий (session persistence), отслеживания метрик и защиты от перегрузок без обращения к внешним СУБД.

**Sticky counter (`sc0`–`sc2` / `sc3`–`sc9`)** — указатель (дескриптор), связывающий обрабатываемый запрос с определенной записью в stick table. В базовой сборке HAProxy доступно до 8 параллельных счетчиков на запрос (в HAProxy Enterprise — до 12), предел задается флагом компиляции `MAX_SESS_STKCTR`.

**ACL (Access Control List)** — логические предикаты и условия в конфигурации HAProxy, анализирующие свойства запроса (IP-адрес, URL-путь, заголовки, значения счетчиков) для принятия решений о маршрутизации, блокировке или модификации сессии.

**Peers** — встроенный протокол и секция конфигурации HAProxy для межхостовой синхронизации содержимого stick tables между независимыми инстансами по протоколу TCP.

**Вероятностное сбрасывание (Probabilistic shedding)** — алгоритмическая техника защиты бэкендов от каскадной перегрузки: при превышении номинальной пропускной способности балансировщик отбрасывает (например, ответом HTTP 429) псевдослучайную долю входящих запросов, строго пропорциональную величине перегруза, сохраняя работоспособность целевого сервиса.

**`track`** — параметр директивы `server`, позволяющий наследовать статус проверки доступности (health check) из другого бэкенда. Исключает дублирование сетевых проверок одних и тех же хостов.

**BGP Anycast** — сетевой механизм маршрутизации на уровне L3, при котором один и тот же IP-адрес анонсируется маршрутизаторами нескольких географически распределенных дата-центров, направляя клиента по кратчайшему сетевому маршруту (AS-Path / IGP-метрика).

**Split-Brain (расщепление кластера)** — сетевая изоляция между дата-центрами при нарушении WAN-связности, при которой инстансы HAProxy в изолированных сегментах перестают получать обновления пиров и принимают решения только на базе локальных данных.

**Runtime API (Stats Socket)** — административный интерфейс через UNIX- или TCP-сокет, позволяющий инспектировать состояние peers, просматривать и сбрасывать записи stick tables, а также динамически менять веса и состояния серверов без перезапуска процесса.

---

## Основные концепции

### Роль внешнего балансировщика между дата-центрами

В мультисайтовой инфраструктуре (несколько собственных дата-центров, colocation-площадок или выделенных серверов у независимых хостинг-провайдеров) внешний L7-балансировщик решает задачи глобального распределения потоков:

- **Независимость от локальных отказов площадок.** При аварии магистрального канала, сбое питания или деградации оборудования в одном дата-центре балансировщик перенаправляет трафик на резервные площадки.
- **Минимизация сетевой задержки (Latency).** Запросы клиентов с Урала и Дальнего Востока обрабатываются локальным пулом серверов в восточном дата-центре, не проходя транзитом через центральные узлы в Москве или Санкт-Петербурге.
- **Защита периметра и терминация TLS.** На внешнем рубеже выполняются ресурсоемкие операции шифрования, фильтрация паразитного трафика и защита от всплесков нагрузки при сетевых инцидентах.
- **Единая точка управления политиками трафика.** Балансировщик унифицирует правила маршрутизации, отдавая трафик на любые внутренние платформы: bare-metal серверы, виртуальные машины KVM или кластеры контейнерной оркестрации.

```
                              [ Клиентский трафик ]
                                        │
                         ┌──────────────┴──────────────┐
                         ▼                             ▼
                 [ BGP Anycast / GeoDNS ]      [ BGP Anycast / GeoDNS ]
                         │                             │
                   Локация 1 (СПб)              Локация 2 (Владивосток)
                         │                             │
             ┌───────────▼───────────┐     ┌───────────▼───────────┐
             │   HAProxy Node 1/2    │◄───►│   HAProxy Node 3/4    │
             │   (Keepalived VIP)    │ TCP │   (Keepalived VIP)    │
             └───────────┬───────────┘Peers└───────────┬───────────┘
                         │                             │
            ┌────────────┴────────────┐   ┌────────────┴────────────┐
            ▼                         ▼   ▼                         ▼
      [ App Server 1 ]          [ App Server 2 ]            [ App Server 3 ]
```

### Архитектурные особенности и производительность HAProxy

HAProxy спроектирован по однопроцессной событийной модели (event loop) с поддержкой потоков операционной системы (`nbthread`), написан на языке C и ориентирован на минимальный оверхед по памяти и процессорным тактам:

- **Пропускная способность.** В официальных тестах производительности HAProxy 2.x/3.x демонстрирует пропускную способность свыше 2 млн HTTPS-запросов в секунду и 100 Gbps проксируемого трафика на 64-ядерных серверах при объектах размером 30 КБ.
- **Оптимизация памяти (структура `stkctr`).** Переменная счетчика сессии (`stkctr`) хранит составной указатель на запись stick table. В 64-битных архитектурах (x86-64, AArch64) указатели на структуры выравниваются по границе как минимум 4 или 8 байт, поэтому младшие 2 бита указателя всегда равны нулю. Ядро HAProxy использует эти два бита для упаковки служебных флагов состояния счетчика. Это позволяет избежать добавления отдельных полей с учетом паддинга компилятора и экономит мегабайты памяти при миллионах активных записей.
- **Многопоточность.** Директива `nbthread` распределяет обработку сетевых событий между ядрами CPU внутри одного процесса без дублирования памяти. Устаревший режим разделения на процессы (`nbproc`) был полностью удален в HAProxy 2.5, так как он препятствовал разделению stick tables между воркерами.

### Математическая модель вероятностного сбрасывания (Probabilistic Shedding)

Стандартное ограничение по IP-адресу (Fixed Window / Token Bucket) не подходит для защиты сервиса от глобального перегруза:
1. За одним корпоративным шлюзом или провайдерским CGNAT находятся тысячи легитимных клиентов с общим публичным IP.
2. При жестком лимите клиент блокируется целиком (100% отказов), даже если сервису не хватает всего 10% емкости.

**Вероятностное сбрасывание** устраняет эти недостатки на уровне кластера:

1. Известна суммарная номинальная емкость бэкендов $C$ (например, 100 RPS на кластер).
2. Балансировщик измеряет фактический текущий поток запросов $R$ (например, 150 RPS).
3. Для каждого входящего запроса генерируется псевдослучайное целое число $U$ в интервале $[0, R)$.
4. Если $U \ge C$, запрос признается избыточным и немедленно отклоняется с кодом `429 Too Many Requests`.
5. Если $U < C$, запрос передается на бэкенд.

Доля отсекаемых запросов рассчитывается по формуле:

$$P(\text{drop}) = \frac{R - C}{R}$$

При $R = 150$ и $C = 100$:

$$P(\text{drop}) = \frac{150 - 100}{150} = \frac{50}{150} = 33.3\%$$

Сервис продолжает получать ровно 100 RPS, нагрузка на бэкенды стабилизируется, а клиенты получают равномерное распределение успешных и отложенных попыток без жестких банов подсетей.

### Синхронизация stick tables через протокол Peers

Секция `peers` организует полносвязную топологию (full mesh) между узлами HAProxy по протоколу TCP:

- **Модель Multi-Master без агрегации.** При изменении счетчика узел рассылает дельту или новое значение всем подключенным пирам. Принимающий узел **перезаписывает** значение ключа в локальной копии таблицы. Автоматического сложения или усреднения значений между узлами в протоколе peers нет.
- **Раздельные таблицы для исключения коллизий.** Если два балансировщика будут писать свои измерения в одну и ту же запись одной таблицы, они будут затирать данные друг друга. Для вычисления глобального RPS каждый узел кластера обязан писать метрики в **собственную** выделенную таблицу (`tb1_s1`, `tb2_s1`), а для подсчета суммы — читать значения из таблиц всех пиров.
- **Сглаживание сетевой задержки (WAN Jitter).** При передаче пакетов между удаленными дата-центрами (например, RTT 100 мс между Москвой и Хабаровском) мгновенный счетчик `http_req_rate(1s)` дает ложные колебания из-за неравномерности доставки TCP-пакетов peers. Для межсайтовой балансировки применяется окно скользящего среднего в 5 или 10 секунд (`http_req_rate(5s)`), значение которого делится на соответствующий коэффициент конвертером `div(5)`.
- **Передача состояния при Reload.** При выполнении graceful reload (`systemctl reload haproxy`) старый мастер-процесс передает все активные записи stick tables новому процессу через локальный peers-сокет без сброса накопленной статистики.

---

## Практические сценарии

### Системные требования и тюнинг ядра Linux

Перед запуском высоконагруженных инстансов HAProxy в мультилокационной схеме примените сетевые параметры ядра Linux в файле `/etc/sysctl.d/99-haproxy.conf`:

```ini
# Разрешить привязку к нелокальным IP-адресам (необходимо для VRRP/Keepalived VIP)
net.ipv4.ip_nonlocal_bind = 1

# Повторное использование TCP-сокетов в состоянии TIME_WAIT для исходящих соединений
net.ipv4.tcp_tw_reuse = 1

# Расширение диапазона эфемерных портов для бэкенд-соединений
net.ipv4.ip_local_port_range = 1024 65535

# Увеличение очереди входящих сетевых соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# Максимальные размеры буферов сетевого стека (16 МБ)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# Отключение медленного старта TCP после простоя
net.ipv4.tcp_slow_start_after_idle = 0
```

Примените параметры:

```bash
sysctl -p /etc/sysctl.d/99-haproxy.conf
# → net.ipv4.ip_nonlocal_bind = 1
# → net.ipv4.tcp_tw_reuse = 1
# → net.ipv4.ip_local_port_range = 1024 65535
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_max_syn_backlog = 65535
# → net.core.rmem_max = 16777216
# → net.core.wmem_max = 16777216
# → net.ipv4.tcp_slow_start_after_idle = 0
```

Настройте лимиты файловых дескрипторов для systemd в `/etc/systemd/system/haproxy.service.d/limits.conf`:

```ini
[Service]
LimitNOFILE=1048576
```

---

### Сценарий 1: Локальная вероятностная защита от перегруза (один узел)

Конфигурация защищает бэкенд от всплесков трафика с помощью счетчика запросов в единственной записи таблицы (`size 1`) и арифметических конвертеров.

```haproxy
global
    log /dev/log local0 info
    chroot /var/lib/haproxy
    user haproxy
    group haproxy
    daemon
    stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners
    stats timeout 30s
    maxconn 100000

defaults
    log     global
    mode    http
    option  httplog
    option  dontlognull
    timeout connect 5s
    timeout client  50s
    timeout server  50s
    retries 3

frontend fe_main
    bind *:80
    mode http

    # Таблица на 1 запись. Ключ — целое число, период устаревания — 1 секунда.
    # store http_req_rate(1s) накапливает средний RPS за последнюю секунду.
    stick-table type integer size 1 expire 1s store http_req_rate(1s)

    # Все входящие запросы фиксируются в записи с фиксированным ключом 1
    http-request track-sc0 int(1)

    # Считываем текущий суммарный RPS в переменную транзакции
    http-request set-var(txn.rps) sc_http_req_rate(0)

    # Генерация случайного числа:
    # rand — sample fetch, генерирует uint32 в диапазоне [0, 2^32)
    # mod — конвертер, вычисляет остаток от деления rand на txn.rps
    http-request set-var(txn.rand) rand
    http-request set-var(txn.shed) var(txn.rand),mod(txn.rps)

    # Условия:
    # 1. Текущий RPS превышает лимит пропускной способности (100 RPS)
    acl is_overload var(txn.rps) gt 100
    # 2. Вычисленный остаток попадает в диапазон сброса [100, rps)
    acl is_unlucky  var(txn.shed) ge 100

    # Если система перегружена И запрос выбран генератором — отправляем в бэкенд сброса
    use_backend be_shedding if is_overload is_unlucky
    default_backend be_app

backend be_shedding
    mode http
    # Отдаем стандартизированный ответ 429 с заголовком Retry-After
    http-request set-header Retry-After 1
    http-request return status 429 content-type text/plain lf-string "429 Too Many Requests - System Capacity Exceeded\n"

backend be_app
    mode http
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200
    default-server inter 2s fall 3 rise 2
    server app1 10.0.0.11:8080 check maxconn 50
    server app2 10.0.0.12:8080 check maxconn 50
```

---

### Сценарий 2: Кластер из двух балансировщиков с peers-синхронизацией по TLS

В продакшн-окружении узлы балансировки обмениваются данными peers через незащищенные каналы связи между стойками или площадками. Начиная с HAProxy 2.0, секция `peers` поддерживает шифрование и взаимную аутентификацию (mTLS).

```haproxy
global
    log /dev/log local0 info
    chroot /var/lib/haproxy
    user haproxy
    group haproxy
    daemon
    stats socket /run/haproxy/admin.sock mode 660 level admin
    # Определение локального имени ноды (должно совпадать с именем в peers)
    localpeer lb1

# Секция peers с mTLS
peers cluster_peers
    # Локальный сокет прослушивания peers-трафика
    bind :10000 ssl crt /etc/haproxy/certs/peers.pem ca-file /etc/haproxy/certs/ca.crt verify required
    # Настройки по умолчанию для подключения к удаленным пирам
    default-server ssl ca-file /etc/haproxy/certs/ca.crt verify required

    peer lb1 10.0.0.1:10000
    peer lb2 10.0.0.2:10000

    # Каждый балансировщик пишет только в СВОЮ таблицу
    table tb_lb1 type integer size 1 expire 5s store http_req_rate(5s)
    table tb_lb2 type integer size 1 expire 5s store http_req_rate(5s)

frontend fe_main
    bind *:80
    mode http

    # На lb1 пишем в таблицу cluster_peers/tb_lb1.
    # На lb2 в конфиге генерируется: track-sc0 int(1) table cluster_peers/tb_lb2
    http-request track-sc0 int(1) table cluster_peers/tb_lb1

    # Читаем локальный и удаленный rate за 5 секунд, конвертируем в RPS делением на 5
    http-request set-var(txn.rps_lb1) sc_http_req_rate(0,cluster_peers/tb_lb1),div(5)
    http-request set-var(txn.rps_lb2) sc_http_req_rate(0,cluster_peers/tb_lb2),div(5)

    # Вычисляем суммарный кластерный RPS
    http-request set-var(txn.total_rps) var(txn.rps_lb1),add(var(txn.rps_lb2))

    # Вероятностный расчет для кластерного лимита (200 RPS)
    http-request set-var(txn.rand) rand
    http-request set-var(txn.shed) var(txn.rand),mod(txn.total_rps)

    acl is_cluster_overload var(txn.total_rps) gt 200
    acl is_unlucky          var(txn.shed) ge 200

    use_backend be_shedding if is_cluster_overload is_unlucky
    default_backend be_app

backend be_shedding
    mode http
    http-request return status 429 content-type text/plain lf-string "429 Cluster Rate Limit Exceeded\n"

backend be_app
    mode http
    balance roundrobin
    server app1 10.0.1.10:8080 check
    server app2 10.0.1.11:8080 check
```

---

### Сценарий 3: Мультилокационная балансировка между двумя дата-центрами (СПб и Владивосток)

Топология:
- Два сайта: Локация 1 (Санкт-Петербург, `s1`) и Локация 2 (Владивосток, `s2`).
- На каждой площадке развернуто по 2 балансировщика HAProxy (`lb1_s1`, `lb2_s1` в СПб; `lb1_s2`, `lb2_s2` во Владивостоке).
- Трафик клиентов обслуживается локальным дата-центром до тех пор, пока средняя нагрузка на один активный сервер локации не превысит 50 RPS.
- При перегрузе или массовом сбое серверов трафик плавно перетекает на удаленную площадку.
- Бэкенды получают заголовок `X-HAProxy-Rps` для включения режима деградации (Graceful Degradation).

Конфигурация для первого балансировщика в СПб (`lb1_s1`):

```haproxy
global
    log /dev/log local0 info
    chroot /var/lib/haproxy
    user haproxy
    group haproxy
    daemon
    stats socket /run/haproxy/admin.sock mode 660 level admin
    localpeer lb1_s1

peers cross_dc_peers
    bind :10000 ssl crt /etc/haproxy/certs/peers.pem ca-file /etc/haproxy/certs/ca.crt verify required
    default-server ssl ca-file /etc/haproxy/certs/ca.crt verify required

    peer lb1_s1 10.1.0.11:10000
    peer lb2_s1 10.1.0.12:10000
    peer lb1_s2 10.2.0.11:10000
    peer lb2_s2 10.2.0.12:10000

    # 4 таблицы для 4 инстансов (окно 5 секунд сглаживает задержки WAN)
    table tb_lb1_s1 type integer size 1 expire 5s store http_req_rate(5s)
    table tb_lb2_s1 type integer size 1 expire 5s store http_req_rate(5s)
    table tb_lb1_s2 type integer size 1 expire 5s store http_req_rate(5s)
    table tb_lb2_s2 type integer size 1 expire 5s store http_req_rate(5s)

# Пул всех серверов всех локаций: выполняет централизованные health checks
backend be_all_sites
    mode http
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200
    default-server check inter 3s fall 3 rise 2

    # Серверы локации 1 (СПб)
    server app1_s1 10.1.1.21:8080
    server app2_s1 10.1.1.22:8080
    # Серверы локации 2 (Владивосток)
    server app1_s2 10.2.1.21:8080
    server app2_s2 10.2.1.22:8080

# Пул только локальных серверов: наследует результаты проверок через `track`
backend be_local_s1
    mode http
    balance roundrobin

    # Параметр track связывает статус сервера со статусом в be_all_sites
    server app1_s1 10.1.1.21:8080 track be_all_sites/app1_s1
    server app2_s1 10.1.1.22:8080 track be_all_sites/app2_s1

frontend fe_main
    bind *:80
    mode http

    # Локальный балансировщик регистрирует запрос в своей таблице
    http-request track-sc0 int(1) table cross_dc_peers/tb_lb1_s1

    # Чтение метрик всех 4 балансировщиков и перевод в секунды (div 5)
    http-request set-var(txn.rps_l1) sc_http_req_rate(0,cross_dc_peers/tb_lb1_s1),div(5)
    http-request set-var(txn.rps_l2) sc_http_req_rate(0,cross_dc_peers/tb_lb2_s1),div(5)
    http-request set-var(txn.rps_r1) sc_http_req_rate(0,cross_dc_peers/tb_lb1_s2),div(5)
    http-request set-var(txn.rps_r2) sc_http_req_rate(0,cross_dc_peers/tb_lb2_s2),div(5)

    # Агрегация: RPS текущего сайта и суммарный RPS по всем площадкам
    http-request set-var(txn.rps_site) var(txn.rps_l1),add(var(txn.rps_l2))
    http-request set-var(txn.rps_all)  var(txn.rps_site),add(var(txn.rps_r1)),add(var(txn.rps_r2))

    # Передача телеметрии бэкендам для отключения «тяжелых» функций
    http-request set-header X-HAProxy-Global-Rps var(txn.rps_all)

    # Подсчет числа живых серверов в локальном пуле через srv_is_up (возвращает 1 или 0)
    http-request set-var(txn.up_local) srv_is_up(be_local_s1/app1_s1),add(srv_is_up(be_local_s1/app2_s1))

    # Расчет средней нагрузки на один живой сервер локации
    http-request set-var(txn.avg_load) var(txn.rps_site),div(var(txn.up_local))

    # Критерий переключения: средняя нагрузка >= 50 RPS на сервер.
    # Если все локальные серверы упали, txn.up_local = 0.
    # Конвертер div в HAProxy при делении на 0 возвращает максимальное целое (2^63 - 1),
    # что заведомо больше 50, вызывая мгновенный failover на be_all_sites.
    acl is_site_overloaded var(txn.avg_load) ge 50

    use_backend be_all_sites if is_site_overloaded
    default_backend be_local_s1
```

---

### Сценарий 4: Комплексная схема — мультилокационная балансировка + каскадный Failover + Probabilistic Shedding

В случае масштабной аварии переключение трафика с отказавшей локации на уцелевшую может вызвать «эффект домино» (Cascading Failure): суммарный трафик двух дата-центров мгновенно выведет из строя серверы оставшейся площадки. 

Решение — объединение каскадного перехода в общий пул с последующим вероятностным сбросом избыточного трафика, превышающего совокупную емкость всех дата-центров.

```haproxy
frontend fe_combined
    bind *:80
    mode http

    # 1. Трекинг входящего запроса
    http-request track-sc0 int(1) table cross_dc_peers/tb_lb1_s1

    # 2. Вычисление метрик (RPS сайтов и глобальный RPS)
    http-request set-var(txn.rps_l1) sc_http_req_rate(0,cross_dc_peers/tb_lb1_s1),div(5)
    http-request set-var(txn.rps_l2) sc_http_req_rate(0,cross_dc_peers/tb_lb2_s1),div(5)
    http-request set-var(txn.rps_r1) sc_http_req_rate(0,cross_dc_peers/tb_lb1_s2),div(5)
    http-request set-var(txn.rps_r2) sc_http_req_rate(0,cross_dc_peers/tb_lb2_s2),div(5)

    http-request set-var(txn.rps_local_site) var(txn.rps_l1),add(var(txn.rps_l2))
    http-request set-var(txn.rps_global)     var(txn.rps_local_site),add(var(txn.rps_r1)),add(var(txn.rps_r2))

    # 3. Проверка локальной емкости
    http-request set-var(txn.up_local) srv_is_up(be_local_s1/app1_s1),add(srv_is_up(be_local_s1/app2_s1))
    http-request set-var(txn.avg_local) var(txn.rps_local_site),div(var(txn.up_local))
    acl is_local_exhausted var(txn.avg_local) ge 50

    # 4. Проверка глобальной емкости всей инфраструктуры (максимум 200 RPS на оба сайта)
    http-request set-var(txn.rand) rand
    http-request set-var(txn.global_shed) var(txn.rand),mod(txn.rps_global)

    acl is_global_overload var(txn.rps_global) gt 200
    acl is_global_unlucky  var(txn.global_shed) ge 200

    # Правила маршрутизации по приоритету:
    # Шаг 1: Если инфраструктура глобально перегружена, отсекаем долю запросов кодом 429
    use_backend be_global_shedding if is_global_overload is_global_unlucky

    # Шаг 2: Если локальный сайт перегружен, уходим в глобальный пул серверов
    use_backend be_all_sites if is_local_exhausted

    # Шаг 3: В штатном режиме остаемся на локальном сайте
    default_backend be_local_s1

backend be_global_shedding
    mode http
    http-request return status 429 content-type application/json lf-string '{"error":"Too Many Requests","message":"Global capacity exceeded","retry_after":2}\n'
```

---

## Операции и команды

Управление, инспекция и эксплуатация HAProxy производятся через стандартные утилиты ОС и встроенный Runtime API сокет.

### Проверка конфигурации и управление процессом

Проверка синтаксиса конфигурационного файла перед применением изменений:

```bash
haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file /etc/haproxy/haproxy.cfg is valid
```

Мягкая перезагрузка демона без потери активных соединений (Hitless Reload):

```bash
systemctl reload haproxy
systemctl status haproxy --no-pager
# → Active: active (running) since Wed 2026-10-14 21:00:00 MSK; 15min ago
# → Process: 14210 ExecReload=/usr/sbin/haproxy -c -f /etc/haproxy/haproxy.cfg && /bin/kill -USR2 $MAINPID
```

### Диагностика Peers и Stick Tables через Runtime API

Для взаимодействия с Runtime API используется утилита `socat`:

Проверка статуса подключения межхостовых пиров:

```bash
echo "show peers" | socat stdio /run/haproxy/admin.sock
# → Peers section cross_dc_peers
# →   peer lb1_s1: status=ESTA, addr=10.1.0.11:10000, reconnect=0s, flags=0x0
# →   peer lb2_s1: status=ESTA, addr=10.1.0.12:10000, reconnect=0s, flags=0x0
# →   peer lb1_s2: status=ESTA, addr=10.2.0.11:10000, reconnect=0s, flags=0x0
# →   peer lb2_s2: status=ESTA, addr=10.2.0.12:10000, reconnect=0s, flags=0x0
```

Инспекция содержимого распределенной таблицы и счетчиков RPS:

```bash
echo "show table cross_dc_peers/tb_lb1_s1" | socat stdio /run/haproxy/admin.sock
# → # table: cross_dc_peers/tb_lb1_s1, type: integer, size:1, used:1
# → 0x7f9a20010a30: key=1 use=0 exp=4521 http_req_rate(5000)=245
```

Сброс записей таблицы при тестировании или аварийном восстановлении:

```bash
echo "clear table cross_dc_peers/tb_lb1_s1 key 1" | socat stdio /run/haproxy/admin.sock
# → 
```

### Вывод сервера в технологическое обслуживание

Плавный вывод сервера из балансировки (Drain mode — завершение текущих сессий без приема новых):

```bash
echo "set server be_all_sites/app1_s1 state drain" | socat stdio /run/haproxy/admin.sock
# → 
```

Полный перевод сервера в режим обслуживания (Maintenance):

```bash
echo "set server be_all_sites/app1_s1 state maint" | socat stdio /run/haproxy/admin.sock
# → 
```

Возврат сервера в активную работу:

```bash
echo "set server be_all_sites/app1_s1 state ready" | socat stdio /run/haproxy/admin.sock
# → 
```

---

## Валидация и тестирование

### 1. Проверка связности и состояния протокола Peers

Убедитесь, что все пиры находятся в статусе `ESTA` (Established). Если статус отображается как `CONN` или `DISC`:

```bash
echo "show peers" | socat stdio /run/haproxy/admin.sock | grep "status="
# →   peer lb1_s1: status=ESTA, addr=10.1.0.11:10000, reconnect=0s, flags=0x0
# →   peer lb2_s1: status=ESTA, addr=10.1.0.12:10000, reconnect=0s, flags=0x0
# →   peer lb1_s2: status=ESTA, addr=10.2.0.11:10000, reconnect=0s, flags=0x0
# →   peer lb2_s2: status=ESTA, addr=10.2.0.12:10000, reconnect=0s, flags=0x0
```

### 2. Тестирование вероятностного сбрасывания

Подайте синтетическую нагрузку 150 RPS при установленном лимите 100 RPS и проверьте распределение статус-кодов ответов:

```bash
# Генерация 1500 запросов с интенсивностью 150 req/sec с помощью утилиты hey
hey -n 1500 -q 150 -c 10 http://127.0.0.1/
# → Summary:
# →   Total:        10.0125 secs
# →   Slowest:      0.0451 secs
# →   Fastest:      0.0012 secs
# →   Average:      0.0054 secs
# →   Requests/sec: 149.81
# → Status code distribution:
# →   [200] 1004 responses
# →   [429] 496 responses
```

Доля ответов с кодом `429` составляет ~33%, сервис пропустил ровно 100 RPS целевого трафика, подтверждая математическую модель.

### 3. Тестирование автоматического межсайтового Failover

Имитируйте отказ локальных сервисов, переведя локальные серверы в режим обслуживания:

```bash
echo "set server be_all_sites/app1_s1 state maint" | socat stdio /run/haproxy/admin.sock
echo "set server be_all_sites/app2_s1 state maint" | socat stdio /run/haproxy/admin.sock

# Проверка наследования статуса через track
echo "show stat" | socat stdio /run/haproxy/admin.sock | grep -E "app[12]_s1" | cut -d',' -f1,2,18
# → be_all_sites,app1_s1,MAINT
# → be_all_sites,app2_s1,MAINT
# → be_local_s1,app1_s1,MAINT
# → be_local_s1,app2_s1,MAINT

# Отправка тестового запроса — трафик перенаправляется на удаленную площадку s2
curl -i http://127.0.0.1/
# → HTTP/1.1 200 OK
# → X-Backend-Server: app1_s2
```

---

## Устранение неисправностей

| Проблема | Диагностика | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Пиры затирают данные друг друга** | Значение счетчика в `show table` хаотично падает и скачет; сумма не сходится | Несколько инстансов пишут в одну и ту же таблицу; протокол peers перезаписывает ключи без агрегации | Выделить каждому инстансу собственную таблицу (`tb_lb1`, `tb_lb2`). Писать только в свою, читать все |
| **Пиры в статусе `CONN` или `DISC`** | `echo "show peers" \| socat ...` возвращает `status=CONN` или ошибку handshake | 1. Имя хоста не совпадает со строкой `peer` или `localpeer`.<br>2. Закрыт TCP-порт 10000 на сетевом экране.<br>3. Ошибка mTLS (истек сертификат или не совпадает CA) | Проверить имя узла (`hostname`), настройки фаервола (`nftables`/`iptables`) и валидность TLS-сертификатов (`openssl verify -CAfile ca.crt peers.pem`) |
| **Ошибка Runtime API `Permission denied`** | `socat` выдает `connect: Permission denied` при обращении к сокету | Недостаточно прав у пользователя на UNIX-сокет `/run/haproxy/admin.sock` | В секции `global` указать `stats socket ... mode 660 level admin group haproxy` и добавить пользователя в группу `haproxy` |
| **Каскадное падение кластера при перегрузе** | При падении сайта 1 сайт 2 мгновенно перегружается и отдает `503 Service Unavailable` | Отсутствует вероятностное сбрасывание на уровне общего пула `be_all_sites` | Реализовать Сценарий 4: ограничить глобальный RPS и отбрасывать излишек запросов с кодом `429` |
| **Деление на ноль при отказе всех серверов** | Локальные серверы недоступны, проверка `acl is_site_overloaded` не срабатывает | Ожидание ошибки в `div(0)` | В HAProxy конвертер `div` при делителе 0 возвращает максимальное целое $2^{63}-1$. Проверять условие через `ge <threshold>` |
| **Резкие скачки счетчиков при межсайтовом трафике** | Метрика RPS колеблется с большой амплитудой каждые несколько секунд | Использование 1-секундного окна `http_req_rate(1s)` через канал с высокой сетевой задержкой (WAN RTT > 50 мс) | Использовать окно 5 или 10 секунд (`http_req_rate(5s)`), делить результат конвертером `div(5)` для усреднения джиттера |
| **ACL по заголовкам/URL не работают** | Правила `http-request track-sc0 path` игнорируются, запросы не трекаются | Фронтенд работает в режиме `mode tcp` | Переключить секции `frontend` и `backend` в `mode http` для возможности разбора заголовков и L7-структур |

---

## Лучшие практики

- **Генерация конфигурационных файлов через IaC.** Не редактируйте секцию `peers` вручную на каждом сервере. Используйте шаблонизаторы (Ansible / Jinja2), чтобы список пиров был строго идентичен на всех узлах, а директива `localpeer` и строка `track-sc0 ... table <локальная_таблица>` подставлялись автоматически на основе имени хоста.
- **Обязательный mTLS для межхостового обмена.** Если трафик peers передается через публичные сети или межцодовые каналы передачи данных (L2/L3 VPN), используйте опции `bind ... ssl` и `default-server ssl verify required` с выделенным внутренним центром сертификации (CA).
- **Синхронизация времени (NTP/Chrony).** Рассинхронизация системных часов между серверами приводит к преждевременному удалению записей из stick table по таймауту `expire`. Поддерживайте смещение часов в пределах не более 5 миллисекунд.
- **Единые health checks через `track`.** Не настраивайте независимые проверки одних и тех же бэкендов в нескольких секциях. Выносите проверки в базовый пул (`be_all_sites`), а в рабочих бэкендах ссылайтесь на них через `server ... track <proxy>/<server>`. Это снижает паразитный трафик на бэкенды в $N$ раз.
- **Контроль деградации через HTTP-заголовки.** Добавляйте агрегированный RPS в заголовки запросов к приложениям (`http-request set-header X-HAProxy-Global-Rps`). Это позволяет микросервисам динамически отключать вторичные тяжелые функции (фоновые расчеты, сбор аналитики, построение рекомендаций) при глобальном росте трафика.
- **Отказоустойчивость уровня узла.** Внутри каждого дата-центра развертывайте пару инстансов HAProxy под управлением Keepalived (VRRP) с плавающим виртуальным IP-адресом (VIP), предотвращая простой сервиса при перезагрузке единичного сервера балансировки.

---

## Дополнительная информация

- **[HAProxy — обзор](../haproxy_overview.md)** — архитектура, основы ACL, алгоритмы балансировки и базовый Runtime API.
- **[Мониторинг HAProxy](./haproxy_monitoring.md)** — PROMEX, Runtime API, экспорт метрик в Prometheus и разбор termination flags.
- **[Keepalived: обзор и настройка](../../Networking/ServicesAndTools/keepalived_overview.md)** — настройка плавающего VIP для локальной отказоустойчивости балансировщиков.
- **[BGP и динамическая маршрутизация](../../Networking/Protocols/bgp.md)** — построение L3 Anycast инфраструктуры для глобальной доставки трафика.
- **[VRRP и отказоустойчивость шлюзов](../../Networking/Protocols/vrrp_hsrp_glbp.md)** — теория резервирования шлюзов и балансировки на сетевом уровне.
- **[Балансировка нагрузки DNS](../../Networking/Protocols/DNS/dns_load_balancing.md)** — механизмы GeoDNS и GSLB для распределения клиентов между дата-центрами.
- **[Отказоустойчивость и предотвращение Split-Brain](./ha_split_brain_fencing.md)** — архитектурные подходы к изоляции сбойных узлов и кворумным решениям.
- [HAProxy Configuration Manual — Peers and Stick Tables](https://docs.haproxy.org/3.2/configuration.html#peers) — официальное руководство по настройке секции `peers` и репликации таблиц.
- [HAProxy Stick Table Mutators and Converters](https://docs.haproxy.org/3.2/configuration.html#7.3.1) — спецификация встроенных конвертеров `div`, `mod`, `add`, `rand`.
