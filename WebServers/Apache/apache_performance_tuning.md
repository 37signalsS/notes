# Apache: Настройка производительности (Performance Tuning)

**Актуально для:** Apache HTTP Server 2.4.x

---

## Определения

**MPM (Multi-Processing Module)** — модульная архитектура Apache HTTP Server, определяющая механизм привязки сетевых сокетов к процессам и потокам операционной системы, а также модель обработки параллельных соединений (`event`, `worker`, `prefork`).

**event MPM** — асинхронный гибридный многопроцессно-многопоточный модуль MPM по умолчанию в Apache 2.4. Использует механизм мультиплексирования событий ввода-вывода (epoll в Linux, kqueue в FreeBSD) и выделенный поток-слушатель (listener thread) для удержания Keep-Alive и ожидания записи без блокировки рабочих потоков (worker threads).

**prefork MPM** — однопоточная многопроцессная модель без многопоточности, где каждый процесс обрабатывает строго одно клиентское соединение. Используется исключительно в устаревших системах ради обратной совместимости с потоконебезопасными библиотеками (например, `mod_php`).

**worker MPM** — гибридная многопроцессно-многопоточная модель, где каждый дочерний процесс запускает фиксированное число потоков. В отличие от `event`, Keep-Alive соединения блокируют рабочий поток до истечения таймаута.

**Scoreboard** — сегмент разделяемой памяти (Shared Memory, SHM) Apache, в котором родительский процесс и воркеры в реальном времени фиксируют статус каждого слота обработки (`idle`, `busy`, `reading`, `writing`, `keepalive` и др.). Считывается модулем `mod_status`.

**MaxRequestWorkers** — ключевая директива лимитирования параллелизма, задающая абсолютный предел одновременно обслуживаемых запросов (число доступных рабочих потоков/процессов).

**ServerLimit** — жесткая верхняя граница числа дочерних процессов Apache, выделяемая в Scoreboard при инициализации сервера.

**ThreadLimit** — жесткая верхняя граница числа рабочих потоков на один процесс в Scoreboard. Задает предел для директивы `ThreadsPerChild`.

**AsyncRequestWorkerFactor** — коэффициент `event MPM`, определяющий, сколько соединений в состоянии Keep-Alive и ожидания завершения записи может удерживать listener-поток сверх `MaxRequestWorkers` в расчете на свободные потоки.

**ListenBacklog** — длина очереди ожидающих подтверждения соединений (SYN/ACK queue) на слушающем сокете ядра ОС до вызова `accept()`.

**SSLSessionCache** — кэш параметров возобновления TLS-сессий (Session Resumption via Session ID/Tickets) в разделяемой памяти (`shmcb`), исключающий полный асимметричный TLS-handshake при повторных подключениях.

**BufferedLogs** — директива `mod_log_config`, переключающая запись логов доступа из синхронного режима с блокирующими вызовами `write()` в режим буферизации в оперативной памяти с пакетным сбросом на диск.

---

## Основные концепции

### Архитектура MPM и модели многозадачности

Apache HTTP Server 2.4 поддерживает три ключевые модели MPM:

```
                        [ Master Process (root) ]
                         │ (fork / IPC / SHM)
        ┌────────────────┼────────────────────────┐
        ▼                ▼                        ▼
  [ Child Process ] [ Child Process ]      [ Child Process ]
   (httpd user)      (httpd user)           (httpd user)
   ├── Listener      ├── Listener           ├── Listener
   │   (epoll)       │   (epoll)            │   (epoll)
   └── Workers       └── Workers            └── Workers
       Thread 1          Thread 1               Thread 1
       Thread 2          Thread 2               Thread 2
       ...               ...                    ...
       Thread N          Thread N               Thread N
```

| Параметр | `event` | `worker` | `prefork` |
|---|---|---|---|
| **Модель параллелизма** | Процессы + Потоки + Асинхронный epoll/kqueue | Процессы + Потоки | Изолированные однопоточные процессы |
| **Потоков на процесс** | Задается через `ThreadsPerChild` (обычно 32–64) | Задается через `ThreadsPerChild` | Строго 1 поток |
| **Обработка Keep-Alive** | Асинхронно: поток-слушатель через epoll; рабочий поток освобождается | Синхронно: рабочий поток заблокирован на все время Keep-Alive | Синхронно: весь процесс заблокирован на все время Keep-Alive |
| **Расход RAM на соединение** | Минимальный (~10–50 КБ на дескриптор/буфер) | Средний (~1–5 МБ на поток) | Критически высокий (~20–80 МБ на процесс) |
| **Поддержка HTTP/2 (`h2`)** | Полная (рекомендованный стандарт) | Ограниченная (высокий риск блокировки пула) | Не поддерживается |
| **Область применения** | Стандарт RHEL 9+, Debian 12+, Ubuntu 22.04+; PHP-FPM, Reverse Proxy | Устаревшие многопоточные среды без `epoll` | Исключительно legacy `mod_php` |

#### Механизм работы event MPM

В модуле `mpm_event` каждый дочерний процесс содержит:
1. **Выделенный поток-слушатель (Listener Thread):** слушает дескрипторы входящих сокетов и сокетов в состоянии Keep-Alive через системный вызов ядра `epoll_wait(2)` (в Linux).
2. **Пул рабочих потоков (Worker Threads):** как только в сокете появляются входящие байты запроса, listener передает дескриптор свободному рабочему потоку.
3. **Возврат в epoll:** после отправки ответа клиенту, если соединение остается в режиме Keep-Alive, рабочий поток не ждет следующий запрос, а возвращает сокет обратно под контроль listener-потока и немедленно берет в работу другой запрос.
4. **Write Completion:** если клиент читает ответ медленно (медленный канал/буфер сокета полон), рабочий поток передает сокет обратно слушателю до момента готовности сокета к записи (`EPOLLOUT`), предотвращая удержание потоков медленными клиентами (защита от Slowloris / Slow Write).

### Внутреннее устройство Scoreboard и слоты воркеров

Scoreboard — предварительно выделенный массив структур в разделяемой памяти. Размер массива фиксируется при запуске демона:
- Максимальное число процессов = `ServerLimit`
- Максимальное число потоков в процессе = `ThreadLimit`
- Общее число доступных слотов = `ServerLimit × ThreadLimit`

Каждый рабочий слот находится в одном из состояний:

| Символ | Состояние | Описание для SRE / Инженера |
|---|---|---|
| `_` | `Waiting for Connection` | Слот свободен и ожидает назначения сокета (Idle Worker) |
| `S` | `Starting up` | Дочерний процесс или поток инициализируется |
| `R` | `Reading Request` | Чтение HTTP-заголовков или тела запроса от клиента |
| `W` | `Sending Reply` | Формирование и передача HTTP-ответа клиенту (активная работа) |
| `K` | `Keepalive (read)` | Ожидание следующего запроса в Keep-Alive (в `worker`/`prefork` удерживает воркер) |
| `D` | `DNS Lookup` | Выполняется блокирующий обратный резолв IP (при `HostnameLookups On`) |
| `C` | `Closing connection` | Завершение TCP-сессии и сброс сокета |
| `L` | `Logging` | Запись строки в `access_log` (может блокироваться медленным I/O) |
| `G` | `Gracefully finishing` | Воркер завершает текущий запрос перед перезапуском |
| `I` | `Idle cleanup` | Очистка ресурсов простаивающего потока |
| `.` | `Open slot` | Незанятый слот в пределах `ServerLimit × ThreadLimit`, процесс не запущен |

```bash
# Просмотр реального состояния Scoreboard через curl
curl -s http://127.0.0.1/server-status?auto | grep -E "Scoreboard|Workers"
# → BusyWorkers: 124
# → IdleWorkers: 388
# → Scoreboard: ________________________WWWWWWWWWWWWWWWRRRRRRRRRRRRRRRRKKKKK...........
```

Если в Scoreboard преобладают символы `R` и `W`, сервер упирается в пропускную способность или процессинг. Если преобладают `L` — диск не справляется с записью логов. Если `.` отсутствуют, а `BusyWorkers` приближается к максимуму — пул исчерпан.

### Расчёт пула воркеров и бюджетирование ресурсов

Ошибочный расчет директив MPM приводит либо к деградации производительности (`AH00161: server reached MaxRequestWorkers setting`), либо к уничтожению процессов демона ядром Linux через OOM Killer.

#### Математическая модель расчета

1. **`MaxRequestWorkers`** — предел одновременно обрабатываемых активных запросов:
   $$\text{MaxRequestWorkers} = \text{ServerLimit} \times \text{ThreadsPerChild}$$
2. **Лимит по доступной оперативной памяти:**
   $$\text{MaxProcesses} \le \frac{\text{RAM}_{\text{available}} - \text{RAM}_{\text{OS/Other}}}{\text{RSS}_{\text{child}}}$$
   *Для `event MPM`:* каждый дочерний процесс потребляет в среднем 30–80 МБ RSS независимо от числа открытых клиентских соединений, так как сокеты обслуживаются потоками в едином адресном пространстве процесса.
3. **Согласование `ThreadLimit` и `ThreadsPerChild`:**
   `ThreadLimit` по умолчанию равен **64** в `mpm_event`. Если в конфигурации задать `ThreadsPerChild 128`, но не указать `ThreadLimit 128` (до строки с `ThreadsPerChild`), Apache выдаст предупреждение и принудительно урежет число потоков до 64!
4. **Согласование `ServerLimit`:**
   `ServerLimit` по умолчанию равен **16** в `mpm_event`. При `ThreadsPerChild 64` максимальный `MaxRequestWorkers` без изменения `ServerLimit` составит $16 \times 64 = 1024$. Для увеличения `MaxRequestWorkers` до 2048 необходимо явно объявить `ServerLimit 32`.
5. **Роль `AsyncRequestWorkerFactor`:**
   В `mpm_event` реальная емкость сервера по соединениям значительно превышает `MaxRequestWorkers`:
   $$\text{MaxConcurrentConnections} = (\text{AsyncRequestWorkerFactor} + 1) \times \text{MaxRequestWorkers}$$
   При значении по умолчанию `AsyncRequestWorkerFactor 2` и `MaxRequestWorkers 1024` сервер удерживает до **3072** одновременных TCP-соединений, если соединения находятся в фазе Keep-Alive или ожидания записи.

#### Защита от утечек памяти: `MaxConnectionsPerChild`

Директива `MaxConnectionsPerChild` задает количество запросов, после обработки которых дочерний процесс принудительно и плавно (graceful) завершается, а мастер-процесс запускает новый:
- Значение `0` (по умолчанию) означает неограниченное время жизни.
- Рекомендуемое производственное значение: `10000`–`50000`. Это защищает от фрагментации памяти и утечек в системных библиотеках (OpenSSL, glibc, libapr).

### Исключение накладных расходов файловой системы (Syscall Optimization)

В неоптимизированной конфигурации Apache тратит до 60% времени CPU на избыточные системные вызовы ядра Linux (`stat`, `lstat`, `open`, `close`).

#### 1. Отключение `.htaccess` (`AllowOverride None`)
При значении `AllowOverride All` Apache для каждого входящего запроса (например, к `/var/www/html/app/images/banner.jpg`) обязан проверить наличие файла `.htaccess` на **каждом** уровне иерархии:
1. `stat("/var/.htaccess")`
2. `stat("/var/www/.htaccess")`
3. `stat("/var/www/html/.htaccess")`
4. `stat("/var/www/html/app/.htaccess")`
5. `stat("/var/www/html/app/images/.htaccess")`

На каждый запрос генерируется от 5 до 10 дисковых системных вызовов. Выставление `AllowOverride None` в корневом каталоге `<Directory />` полностью отключает этот механизм.

#### 2. Оптимизация символических ссылок (`FollowSymLinks`)
- `Options SymLinksIfOwnerMatch` заставляет Apache выполнять системный вызов `lstat()` для каждого компонента пути, проверяя, совпадает ли владелец ссылки с владельцем целевого файла.
- `Options FollowSymLinks` разрешает переход по ссылкам без проверок владельца, экономя системные вызовы.

#### 3. Отключение обратных DNS-запросов (`HostnameLookups Off`)
При `HostnameLookups On` Apache при каждом входящем подключении вызывает функцию `gethostbyaddr()`, пытаясь определить доменное имя клиента для записи в лог. Если DNS-сервер отвечает медленно или недоступен, рабочий поток блокируется на таймаут до нескольких секунд. Должно быть строго `HostnameLookups Off`.

### Сетевой стек ядра Linux и буферизация ввода-вывода (I/O & Socket Queues)

#### Согласование очередей сокетов: `ListenBacklog` и `somaxconn`
Когда клиент инициирует TCP-соединение:
1. Ядро обрабатывает SYN и помещает полуоткрытое соединение в SYN-backlog (`net.ipv4.tcp_max_syn_backlog`).
2. После завершения трехстороннего рукопожатия (3-way handshake) соединение переходит в очередь готовых соединений (`net.core.somaxconn`).
3. Директива Apache `ListenBacklog` задает максимальный размер этой очереди для сокета httpd.
4. Если `ListenBacklog` превышает `somaxconn`, ядро молча урезает очередь до значения `somaxconn`. При переполнении очереди клиенты получают таймауты подключения или ошибки `Connection refused`.

```
[ Client SYN ] ──► [ tcp_max_syn_backlog ]
                         │
                   [ 3-Way Handshake OK ]
                         ▼
                   [ somaxconn / ListenBacklog ] ──► [ Apache accept() ]
```

#### Zero-Copy передача статических файлов: `EnableSendfile` и `EnableMMAP`
- **`EnableSendfile On`**: использует системный вызов ядра `sendfile(2)`. Данные передаются из кэша страниц ядра напрямую в буфер сетевой карты без копирования в адресное пространство процесса Apache (zero-copy), что радикально разгружает CPU.
  > [!WARNING]
  > Директива `EnableSendfile` должна быть установлена в `Off` для сетевых файловых систем (NFS, SMB/CIFS) и виртуальных общих папок (VirtualBox vboxsf, 9p), где сетевой кэш страниц десинхронизируется, приводя к битым файлам или зависанию воркеров.
- **`EnableMMAP On`**: отображает статические файлы в виртуальную память через системный вызов `mmap(2)`. Оптимально для небольших часто запрашиваемых файлов.

### Оптимизация протокола HTTP/2 (`mod_http2`)

Протокол HTTP/2 мультиплексирует сотни потоков (streams) внутри единого TCP-соединения. Для эффективной работы HTTP/2 требуется модуль `mpm_event` и модуль `mod_http2`.

Ключевые директивы:
- `Protocols h2 http/1.1` — объявляет поддержку HTTP/2 поверх TLS (ALPN-согласование) и откат на HTTP/1.1.
- `H2MaxSessionStreams` — лимит параллельных потоков внутри одной сессии (рекомендуется `100`).
- `H2MaxWorkers` — максимальное количество рабочих потоков для обработки HTTP/2 на один дочерний процесс.
- `H2MinWorkers` — минимальное число удерживаемых потоков HTTP/2.
- `H2StreamMaxMemSize` — лимит памяти (в байтах) на буферизацию одного потока перед сбросом в сеть. Защищает от DoS-атак переполнением буфера со стороны медленных клиентов.

### Управление соединениями Keep-Alive и апстрим-пулы

#### Клиентский Keep-Alive
- `KeepAlive On` — разрешает повторное использование TCP-сессии для нескольких HTTP-запросов.
- `KeepAliveTimeout` — таймаут ожидания следующего запроса от клиента в секундах. В `mpm_event` удержание сокета дешево, однако значение выше `5` секунд не рекомендуется: мобильные клиенты часто разрывают сессии без отправки FIN/RST, загрязняя таблицу дескрипторов. Оптимально: `2–5`.
- `MaxKeepAliveRequests` — количество запросов в рамках одной сессии. Рекомендуется от `500` до `1000` для снижения накладных расходов на TLS-рукопожатия.

#### Пул соединений к бэкендам в `mod_proxy`
При проксировании запросов на внутренние сервисы (например, Tomcat, Node.js, Go-микросервисы) постоянное открытие новых TCP-соединений создает перегрузку по портам и задержкам (RTT):
- Директива `ProxyPass` поддерживает параметры пулинга соединений:
  - `keepalive=On` — активация TCP Keep-Alive зондов на уровне ОС.
  - `smax` — мягкий лимит постоянно удерживаемых открытых соединений к бэкенду.
  - `max` — жесткий максимум соединений на один процесс Apache.
  - `ttl` — время жизни неактивного соединения в секундах.
  - `acquire` — максимальное время ожидания свободного соединения из пула (в миллисекундах).

### TLS-оптимизация и кэширование сессий

Установление TLS-соединения требует дополнительных RTT и криптографических вычислений на CPU.

```
[ TLS 1.2 Full Handshake ] ──► 2 RTT (CPU-емкий асимметричный RSA/ECDHE)
[ TLS 1.3 Full Handshake ] ──► 1 RTT
[ Resumption (Session ID/Ticket) ] ──► 0-1 RTT (симметричный ключ из кэша)
```

1. **Кэширование сессий через разделяемую память (`shmcb`):**
   `SSLSessionCache shmcb:/run/httpd/sslcache(512000)` выделяет циклический буфер размером 512 КБ в SHM. Этого достаточно для хранения ~4000 активных сессий без блокировок между процессами.
2. **Session Tickets (RFC 5077):**
   `SSLSessionTickets On` позволяет клиенту хранить зашифрованный тикет сессии, передавая его при повторном подключении, разгружая оперативную память сервера.
3. **OCSP Stapling:**
   `SSLUseStapling On` заставляет веб-сервер самостоятельно запрашивать и кэшировать статус валидности сертификата у CA и отдавать клиенту в процессе TLS-рукопожатия, исключая блокировку браузера на внешний DNS и OCSP-сервер.

### Оптимизация подсистемы логирования

Синхронная запись логов на диск при нагрузках свыше 5 000 rps создает дисковые очереди ввода-вывода (I/O wait).
- **`BufferedLogs On`**: включает буферизацию записей `mod_log_config` в памяти процесса с периодическим пакетным сбросом на диск, снижая число системных вызовов `write()`.
- **Фильтрация малозначимых событий:** запросы проверок работоспособности (Health checks балансировщиков) генерируют гигантский объем мусорных логов. Исключение через переменную окружения `dontlog` разгружает I/O и снижает размер файлов журналов.

---

## Практические сценарии

### Сценарий 1: Производственная конфигурация `mpm_event` для высокой нагрузки

Конфигурация рассчитана на сервер с 8–16 CPU ядрами и объемом свободной оперативной памяти от 4 ГБ под задачи веб-сервера. Целевой параллелизм: до 2048 активных запросов и до 6000 Keep-Alive соединений.

Создать drop-in файл конфигурации MPM:

```apacheconf
# RHEL/Rocky Linux: /etc/httpd/conf.modules.d/00-mpm-tuning.conf
# Debian/Ubuntu:    /etc/apache2/mods-available/mpm_event.conf

<IfModule mpm_event_module>
    # Жесткие пределы Scoreboard (обязаны объявляться до ThreadsPerChild и MaxRequestWorkers)
    ServerLimit              32
    ThreadLimit             128

    # Первоначальный и резервный пулы
    StartServers              4
    ThreadsPerChild          64
    MinSpareThreads         128
    MaxSpareThreads         512

    # Максимальный параллелизм: ServerLimit (32) * ThreadsPerChild (64) = 2048
    MaxRequestWorkers      2048

    # Плавная ротация воркеров для устранения фрагментации памяти
    MaxConnectionsPerChild 20000

    # Емкость асинхронного обслуживания Keep-Alive: (3 + 1) * 2048 = 8192 соединений
    AsyncRequestWorkerFactor 3

    # Очередь подключений сокета (согласована с net.core.somaxconn ядра)
    ListenBacklog          2048
</IfModule>
```

Проверка синтаксиса и перезапуск:
```bash
# Проверка синтаксиса конфигурации
apachectl -t
# → Syntax OK

# Применение конфигурации MPM требует полного перезапуска демона
sudo systemctl restart httpd || sudo systemctl restart apache2
```

### Сценарий 2: Комплексная системная оптимизация ядра Linux и systemd

Для того чтобы Apache мог открывать десятки тысяч соединений и файлов без падений с ошибкой `Too many open files` или `unable to create worker thread`, необходимо поднять лимиты ядра и сервиса.

#### 1. Тюнинг параметров ядра Linux

Создать файл `/etc/sysctl.d/99-apache-performance.conf`:

```ini
# Максимальный размер очереди входящих соединений на слушающем сокете
net.core.somaxconn = 65535

# Длина очереди входящих пакетов для сетевой карты
net.core.netdev_max_backlog = 16384

# Длина очереди полуоткрытых соединений (SYN-пакеты)
net.ipv4.tcp_max_syn_backlog = 16384

# Быстрое повторное использование TIME_WAIT сокетов для исходящих подключений
net.ipv4.tcp_tw_reuse = 1

# Сокращение таймаута удержания сокета в состоянии FIN-WAIT-2
net.ipv4.tcp_fin_timeout = 15

# Диапазон локальных динамических портов для исходящих запросов
net.ipv4.ip_local_port_range = 10240 65535

# Глобальный лимит дескрипторов файлов в операционной системе
fs.file-max = 2097152
```

Применение параметров:
```bash
sudo sysctl -p /etc/sysctl.d/99-apache-performance.conf
# → net.core.somaxconn = 65535
# → net.core.netdev_max_backlog = 16384
# → net.ipv4.tcp_max_syn_backlog = 16384
# → net.ipv4.tcp_tw_reuse = 1
# → net.ipv4.tcp_fin_timeout = 15
# → net.ipv4.ip_local_port_range = 10240 65535
# → fs.file-max = 2097152
```

#### 2. Тюнинг лимитов systemd

Создать drop-in оверрайд для сервиса Apache:

```bash
sudo systemctl edit httpd || sudo systemctl edit apache2
```

Внести блок ограничений:

```ini
[Service]
# Лимит открытых файловых дескрипторов (файлы + сетевые сокеты)
LimitNOFILE=1048576

# Лимит процессов и потоков (предотвращает ошибку apr_thread_create)
LimitNPROC=65535

# Снятие ограничения systemd cgroup pids на создание потоков
TasksMax=infinity
```

Применение и проверка лимитов работающего процесса:
```bash
sudo systemctl daemon-reload
sudo systemctl restart httpd || sudo systemctl restart apache2

# Проверка реальных лимитов мастер-процесса
cat /proc/$(pgrep -f -o "httpd|apache2")/limits | grep -E "open files|max processes"
# → Max processes             65535                65535                processes 
# → Max open files             1048576              1048576              files     
```

### Сценарий 3: Настройка Apache как Reverse Proxy с пулом соединений к бэкенду

Оптимальная схема проксирования с повторным использованием TCP-сессий к upstream-серверу и раздельными таймаутами.

```apacheconf
# /etc/httpd/conf.d/proxy-performance.conf или /etc/apache2/conf-available/proxy-performance.conf

<VirtualHost *:80>
    ServerName api.example.local

    # Глобальные параметры таймаутов прокси
    ProxyTimeout 60
    ProxyBadHeader Ignore

    # Определение балансировщика / пула бэкендов
    <Proxy "balancer://app_cluster">
        # Воркер 1 с пулом соединений
        BalancerMember http://192.168.10.11:8080 route=node1 \
            connectiontimeout=5 timeout=60 retry=1 \
            keepalive=On ttl=60 smax=32 max=128 acquire=5000

        # Воркер 2 с пулом соединений
        BalancerMember http://192.168.10.12:8080 route=node2 \
            connectiontimeout=5 timeout=60 retry=1 \
            keepalive=On ttl=60 smax=32 max=128 acquire=5000

        ProxySet lbmethod=byrequests
    </Proxy>

    # Проксирование с сохранением Keep-Alive
    ProxyPass / balancer://app_cluster/
    ProxyPassReverse / balancer://app_cluster/

    # Отключение проверок .htaccess в корне
    <Directory />
        AllowOverride None
        Require all denied
    </Directory>
</VirtualHost>
```

### Сценарий 4: Оптимизация виртуального хоста для экстремальной отдачи статики и TLS

Конфигурация с включенным HTTP/2, кэшированием TLS-сессий, OCSP Stapling, zero-copy отдачей и полным отключением избыточных дисковых вызовов `stat()`.

```apacheconf
# /etc/httpd/conf.d/static-vhost.conf или /etc/apache2/sites-available/static-vhost.conf

# Глобальные параметры TLS-производительности
SSLSessionCache         shmcb:/run/httpd/sslcache(1048576)
SSLSessionCacheTimeout  86400
SSLSessionTickets       On
SSLUseStapling          On
SSLStaplingCache        "shmcb:/run/httpd/stapling_cache(262144)"
SSLStaplingResponseMaxAge 900

<VirtualHost *:443>
    ServerName static.example.local
    DocumentRoot /var/www/static

    # Протоколы: HTTP/2 с откатом на HTTP/1.1
    Protocols h2 http/1.1
    H2MaxSessionStreams 100
    H2StreamMaxMemSize  65536

    # TLS сертификаты
    SSLEngine on
    SSLCertificateFile    /etc/pki/tls/certs/static.crt
    SSLCertificateKeyFile /etc/pki/tls/private/static.key

    # Оптимизация сетевых и файловых системных вызовов
    HostnameLookups Off
    EnableSendfile  On
    EnableMMAP      On

    # Настройки каталога: устранение проверок .htaccess и lstat()
    <Directory "/var/www/static">
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted

        # Точный индексный файл без перебора
        DirectoryIndex index.html
    </Directory>

    # Настройки клиентского Keep-Alive
    KeepAlive On
    KeepAliveTimeout 3
    MaxKeepAliveRequests 500

    # Буферизованное логирование с фильтрацией проверок балансировщика
    BufferedLogs On
    SetEnvIf Request_URI "^/healthz$" dontlog
    CustomLog logs/static_access.log combined env=!dontlog
    ErrorLog logs/static_error.log
    LogLevel warn
</VirtualHost>
```

---

## Операции и команды

Сводка утилит и команд runtime-диагностики производительности:

| Команда | Назначение | Ожидаемый результат / Целевое значение |
|---|---|---|
| `apachectl -V \| grep -E "MPM\|Server version"` | Проверка версии сервера и активного MPM | `Server version: Apache/2.4.62 (Unix)`<br>`Server MPM: event` |
| `apachectl -M \| grep -E "event\|worker\|prefork"` | Контроль загруженного модуля MPM | `mpm_event_module (shared)` |
| `curl -s http://127.0.0.1/server-status?auto` | Снятие моментальных метрик воркеров | `BusyWorkers: 42`, `IdleWorkers: 214` |
| `ss -lnt '( sport = :80 or sport = :443 )'` | Проверка текущей очереди сокета (`Send-Q`/`Recv-Q`) | `Send-Q` равен значению `ListenBacklog` |
| `netstat -s \| grep -i "listen"` | Проверка фактов отбрасывания пакетов из-за очереди | `0 times the listen queue of a socket overflowed` |
| `openssl s_client -connect 127.0.0.1:443 -reconnect 2>&1 \| grep "Reused"` | Проверка работоспособности TLS Session Cache | `Reused, TLSv1.3, Cipher is ...` |
| `cat /proc/$(pgrep -f -o "httpd\|apache2")/limits` | Проверка примененных лимитов ядра к демону | `Max open files: 1048576` |
| `pidstat -p $(pgrep -d, -f "httpd\|apache2") 1 3` | Замер использования CPU и потоков воркерами | Процент утилизации %usr и %system |

### Детальные сценарии диагностики с примерами вывода

#### 1. Мониторинг воркеров через `mod_status`
```bash
# Получение числовых метрик для систем мониторинга
curl -s "http://127.0.0.1/server-status?auto"
# → Total Accesses: 1845920
# → Total kBytes: 9482710
# → Uptime: 86400
# → ReqPerSec: 21.3648
# → BytesPerSec: 112543
# → BytesPerReq: 5267.7
# → BusyWorkers: 38
# → IdleWorkers: 474
# → Scoreboard: ________________________________WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW................
```

#### 2. Диагностика очереди слушающих сокетов
```bash
# Проверка сокетов 80 и 443: Recv-Q показывает текущий размер очереди сокета
ss -lnt '( sport = :80 or sport = :443 )'
# → State  Recv-Q Send-Q Local Address:Port  Peer Address:Port
# → LISTEN 0      2048         0.0.0.0:80        0.0.0.0:*    
# → LISTEN 0      2048         0.0.0.0:443       0.0.0.0:*    

# Проверка наличия переполнений очереди сокетов на уровне ядра Linux
netstat -s | grep -E "overflowed|dropped"
# → 0 times the listen queue of a socket overflowed
# → 0 SYNs to LISTEN sockets dropped
```
*Интерпретация:* если `Recv-Q > 0` стабильно удерживается высоким, или счетчик `overflowed` растет — воркеры Apache не успевают выполнять `accept()`, необходимо увеличивать `MaxRequestWorkers` и проверять задержки бэкендов.

#### 3. Нагрузочное тестирование конфигурации (Benchmark)
```bash
# Тестирование пропускной способности через wrk (12 потоков, 400 соединений, 30 секунд)
wrk -t12 -c400 -d30s --latency http://127.0.0.1/
# → Running 30s test @ http://127.0.0.1/
# →   12 threads and 400 connections
# →   Thread Stats   Avg      Stdev     Max   +/- Stdev
# →     Latency     4.12ms   1.89ms  38.45ms   74.20%
# →     Req/Sec     8.15k    1.02k   11.40k    68.90%
# →   Latency Distribution
# →      50%    3.80ms
# →      75%    5.10ms
# →      90%    6.45ms
# →      99%   11.20ms
# →   2921540 requests in 30.05s, 1.48GB read
# → Requests/sec:  97222.69
# → Transfer/sec:     50.41MB
```

#### 4. Профилирование системных вызовов через `strace`
```bash
# Подсчет системных вызовов дочернего процесса за 5 секунд нагрузки
sudo strace -c -p $(pgrep -f "httpd|apache2" | tail -n 1) sleep 5
# → % time     seconds  usecs/call     calls    errors syscall
# → ------ ----------- ----------- --------- --------- ----------------
# →  48.12    0.042100           3     14033           epoll_wait
# →  21.40    0.018720           1     18720           read
# →  19.10    0.016710           1     18720           writev
# →   7.20    0.006300           2      3150           sendfile
# →   4.18    0.003650           1      3650           epoll_ctl
# → ------ ----------- ----------- --------- --------- ----------------
# → 100.00    0.087480                 58273           total
```
*Интерпретация:* отсутствие системных вызовов `stat` и `lstat` подтверждает корректность настройки `AllowOverride None` и `FollowSymLinks`.

---

## Типичные ошибки и диагностика

| Симптом и код ошибки | Первопричина | Метод экспресс-диагностики | Способ устранения |
|---|---|---|---|
| `[mpm_event:error] AH00161: server reached MaxRequestWorkers setting, consider raising the MaxRequestWorkers setting` | Текущий трафик превысил расчетное значение `MaxRequestWorkers`, либо воркеры зависли в ожидании медленных бэкендов | `curl -s http://127.0.0.1/server-status?auto \| grep BusyWorkers`<br>Проверка `ss -tnp \| grep :80 \| wc -l` | 1. Увеличить `ServerLimit` и `MaxRequestWorkers` в конфигурации MPM.<br>2. Уменьшить `KeepAliveTimeout` до 2–3 сек.<br>3. Настроить жесткие таймауты бэкендов в `ProxyPass` (`timeout=15`). |
| `(11)Resource temporarily unavailable: AH00056: connect to listener failed` / `apr_thread_create: unable to create worker thread` | Исчерпан лимит потоков/процессов ядра Linux (`LimitNPROC` или `TasksMax` в systemd) | `systemctl show httpd -p TasksCurrent -p TasksMax`<br>`cat /proc/sys/kernel/threads-max` | 1. Добавить `TasksMax=infinity` и `LimitNPROC=65535` в `systemctl edit httpd`.<br>2. Проверить лимит `sysctl kernel.pid_max`. |
| `(24)Too many open files: AH00056: connect to listener failed` | Превышен лимит открытых файловых дескрипторов процесса (`RLIMIT_NOFILE`) | `cat /proc/$(pgrep -f -o "httpd\|apache2")/limits \| grep "open files"` | 1. Установить `LimitNOFILE=1048576` в systemd unit override.<br>2. Проверить `sysctl fs.file-max`. |
| Падение производительности отдачи статики с NFS/CIFS, повреждение бинарных файлов | Использование вызова `sendfile(2)` поверх сетевой файловой системы с рассинхронизированным page cache | Проверка точки монтирования: `df -T /var/www` | Добавить `EnableSendfile Off` внутри директивы `<Directory>` для сетевых точек монтирования. |
| Резкий рост TTFB (Time To First Byte) и задержек при TLS-подключениях | Отсутствует или переполнен `SSLSessionCache`, клиенты выполняют полный TLS handshake | `openssl s_client -connect 127.0.0.1:443 -reconnect 2>&1 \| grep Reused` | Настроить `SSLSessionCache shmcb:/run/httpd/sslcache(1048576)` и включить `SSLSessionTickets On`. |
| Высокий I/O Wait дисковой подсистемы (`wa%` в `top`), зависание в слотах `L` | Синхронная запись access.log на медленный накопитель при высоком RPS | `iotop -o -P -b -n 1 \| grep httpd`<br>Проверка `Scoreboard` на наличие символа `L` | 1. Включить `BufferedLogs On`.<br>2. Исключить health-check проверки из логирования (`env=!dontlog`).<br>3. Перенести логи на выделенный быстрый диск или RAM-диск `/run`. |
| Ошибки `502 Bad Gateway` / `504 Gateway Timeout` при обратном проксировании | Исчерпание соединений в пуле `ProxyPass` или зависание сокетов в `TIME_WAIT` | `ss -s \| grep TIME-WAIT`<br>Логи: `[proxy:error] AH00898: DNS lookup failure` или `AH01114` | 1. Включить `sysctl net.ipv4.tcp_tw_reuse=1`.<br>2. Настроить пул `ProxyPass ... smax=64 max=256 ttl=60 keepalive=On`. |

---

## Лучшие практики

1. **Использовать исключительно `event MPM`:** переводить все PHP-приложения на `PHP-FPM` через сокет FastCGI (`proxy_fcgi`). Использование `prefork` на production-серверах недопустимо.
2. **Соблюдать иерархию лимитов Scoreboard:** всегда объявлять `ServerLimit` и `ThreadLimit` выше или равными `MaxRequestWorkers / ThreadsPerChild` и `ThreadsPerChild` соответственно.
3. **Отключать накладные расходы файловой системы в корне:**
   ```apacheconf
   <Directory />
       AllowOverride None
       Options -Indexes +FollowSymLinks
       Require all denied
   </Directory>
   ```
4. **Синхронизировать очереди сокетов:** значение `ListenBacklog` в конфигурации MPM должно быть согласовано с параметром ядра `net.core.somaxconn` (например, 2048 или 4096).
5. **Ограничивать время жизни воркера:** выставлять `MaxConnectionsPerChild` в диапазоне `10000–50000` для предотвращения деградации по памяти из-за скрытых утечек в сторонних библиотеках.
6. **Настраивать буферизацию логов и фильтрацию probes:** не логировать регулярные ping/health-check запросы балансировщиков (`env=!dontlog`) и использовать `BufferedLogs On`.
7. **Разделять статику и динамику:** для отдачи тяжелой статики использовать `EnableSendfile On`, но гарантированно отключать его (`EnableSendfile Off`) для сетевых каталогов NFS/GlusterFS/SMB.
8. **Включать кэширование TLS-сессий и OCSP Stapling:** обязательное использование `SSLSessionCache shmcb` и `SSLUseStapling On` экономит до 30% мощности CPU на криптографических операциях.
9. **Контролировать лимиты сервиса через systemd:** всегда задавать `LimitNOFILE=1048576` и `TasksMax=infinity` в drop-in файле `/etc/systemd/system/httpd.service.d/override.conf`.
10. **Экспорт метрик в Prometheus:** подключить `apache_exporter` к эндпоинту `mod_status` (`/server-status?auto`) и настроить алерты на утилизацию воркеров (`BusyWorkers / MaxRequestWorkers > 0.85`) и рост ошибок `AH00161`.

---

## Дополнительная информация

### См. также

*   [Обзор Apache](./apache_overview.md) — общая архитектура, базовая установка, модули и виртуальные хосты.
*   [Серверное кэширование в Apache](./apache_caching.md) — глубокая настройка `mod_cache`, `mod_cache_disk`, `mod_cache_socache` и утилиты `htcacheclean`.
*   [Безопасность и харденинг Apache](./apache_hardening.md) — ограничение прав, защита от Slowloris (`mod_reqtimeout`), заголовки безопасности.
*   [Балансировка нагрузки в Apache](./apache_load_balancing.md) — модуль `mod_proxy_balancer`, алгоритмы распределения и health-check.
*   [Обратное проксирование: продвинутые сценарии](./apache-reverse-proxy-advanced.md) — WebSocket, gRPC через HTTP/2, переопределение ошибок.
*   [Сборка Apache из исходников](./apache-install-from-source.md) — компиляция с кастомными флагами оптимизации (GCC, PGO) и статическими модулями.
*   [Оптимизация TLS для производительности](../Concepts/web_performance/tls_optimization.md) — протоколы TLS 1.3, 0-RTT, Session Tickets и OCSP Stapling.
*   [Сжатие веб-контента](../Concepts/web_performance/server_compression.md) — алгоритмы gzip/brotli через `mod_deflate` и `mod_brotli`.
*   [Пул соединений upstream](../Concepts/web_performance/upstream_keepalive_and_pooling.md) — концепция connection reuse и TIME_WAIT сокетов.
*   [Экспортёры Prometheus для веб-серверов](../../Prometheus/Exporters/other_exporters.md) — установка и настройка `apache_exporter`, мониторинг Scoreboard.