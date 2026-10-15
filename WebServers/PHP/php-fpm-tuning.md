# Тюнинг, сайзинг и эксплуатация PHP-FPM

**Актуально для:** PHP 8.2 / 8.3 / 8.4, systemd 250+, Linux kernel 5.x / 6.x

## Определения

**PHP-FPM (FastCGI Process Manager)** — специализированный менеджер процессов демона PHP, реализующий протокол FastCGI для высокопроизводительной обработки динамических запросов от веб-серверов (Nginx, Angie, Apache). Функционирует как независимый сервис в ОС, обеспечивая изоляцию пользовательских пулов, управление жизненным циклом воркеров и контроль системных ресурсов.

**Master Process** — управляющий привилегированный процесс PHP-FPM (обычно запускается от `root`), отвечающий за чтение конфигурации, открытие сетевых и Unix-сокетов, порождение (`fork`), мониторинг и корректное завершение непривилегированных рабочих процессов.

**Worker Process** — дочерний процесс PHP-FPM, исполняющий прикладной код PHP в изолированном контексте учетной записи ОС (например, `www-data`). Обрабатывает ровно один FastCGI-запрос в единицу времени.

**Process Manager (`pm`)** — алгоритм распределения и масштабирования пула рабочих процессов FPM. Поддерживает три режима: `static` (постоянное фиксированное число воркеров), `dynamic` (автомасштабирование в заданных границах) и `ondemand` (запуск по факту входящего трафика).

**Scoreboard** — структура данных в разделяемой памяти (`mmap`), через которую воркеры атомарно передают мастер-процессу телеметрию о своем текущем состоянии (`Idle`, `Running`, PID, длительность запроса, объем памяти) без блокировок.

**OPcache** — встроенное расширение Zend Engine, кэширующее предварительно скомпилированный байт-код PHP-скриптов в разделяемой оперативной памяти (SHM), исключающее накладные расходы на чтение с диска, лексический анализ и компиляцию при каждом HTTP-запросе.

**OPcache Preloading** — механизм предварительной загрузки классов и функций в постоянную память ядра PHP при старте сервиса, исключающий необходимость разрешения зависимостей в рантайме.

**JIT (Just-In-Time Compiler)** — встроенный в OPcache компилятор (PHP 8.0+), транслирующий байт-код виртуальной машины Zend в машинные инструкции процессора во время выполнения скрипта.

**Realpath Cache** — внутренний кэш PHP, сохраняющий соответствие путей к файлам, каталогам и символическим ссылкам в файловой системе для минимизации системных вызовов `lstat()` и `stat()`.

**Listen Backlog** — системная очередь соединений на уровне сокета ядра Linux, ожидающих вызова `accept()` свободным воркером FPM.

**Slowlog** — встроенный механизм профилирования, сбрасывающий в лог полный PHP-стек вызовов (`backtrace`) для запросов, время исполнения которых превысило порог `request_slowlog_timeout`.

---

## Архитектура и основные концепции

### Архитектура Master-Worker и обработка FastCGI

В классической серверной архитектуре Linux связка веб-сервера и PHP-FPM функционирует по модели разделения обязанностей:

```
[ HTTP Клиент ]
       │
       ▼ (HTTP/1.1, HTTP/2, HTTP/3)
[ Веб-сервер: Nginx / Angie ]
       │
       ▼ FastCGI binary protocol (Unix Domain Socket / TCP)
[ Linux Kernel: Socket Listen Backlog ]
       │
       ├─────────────────────────────────────────┐
       ▼ accept()                                ▼ accept()
[ PHP-FPM Worker 1 ]                     [ PHP-FPM Worker N ]
   (Zend Engine + OPcache)                  (Zend Engine + OPcache)
       │                                         │
       └────────────────────┬────────────────────┘
                            │ Атомарные счетчики
                            ▼
               [ Scoreboard (Shared Memory) ]
                            ▲
                            │ Мониторинг и управление
                 [ PHP-FPM Master Process ]
```

1. **Инициализация:** Мастер-процесс считывает `/etc/php/8.4/fpm/php-fpm.conf` и файлы пулов `/etc/php/8.4/fpm/pool.d/*.conf`, открывает сокеты прослушивания (`listen`) и аллоцирует сегмент разделяемой памяти под Scoreboard и OPcache.
2. **Конкуренция за соединения:** В современных ядрах Linux все дочерние процессы пула разделяют файловый дескриптор сокета, созданный мастером. Воркеры независимо конкурируют за новые входящие соединения через `epoll` с флагом `EPOLLEXCLUSIVE`, предотвращая проблему «стадного чувства» (thundering herd problem).
3. **Обработка запроса:** Свободный воркер вызывает `accept()`, считывает бинарные фреймы FastCGI (`FCGI_BEGIN_REQUEST`, `FCGI_PARAMS`, `FCGI_STDIN`), исполняет целевой PHP-скрипт в контексте Zend Engine, формирует поток вывода (`FCGI_STDOUT`, `FCGI_END_REQUEST`) и возвращается в состояние ожидания (`Idle`).
4. **Сброс состояния:** После завершения запроса PHP очищает суперглобальные массивы, закрывает дескрипторы (если не используются постоянные соединения) и запускает сборщик мусора. При достижении лимита `pm.max_requests` воркер штатно завершается, а мастер порождает новый процесс, нивелируя утечки памяти в нестабильных C-библиотеках.

### Транспорт FastCGI: Unix Domain Socket vs TCP Loopback

Выбор транспорта определяет пропускную способность, задержку и архитектурную масштабируемость:

| Характеристика | Unix Domain Socket (`unix:/run/php/...`) | TCP Loopback (`127.0.0.1:9000`) |
| :--- | :--- | :--- |
| **Накладные расходы ядра** | Минимальные (zero-copy в буфер ядра, нет IP/TCP-стека). | Высокие (генерация TCP-пакетов, контрольные суммы, SYN/ACK). |
| **Задержка (Latency P99)** | На 15–25% ниже по сравнению с TCP. | Выше из-за прохождения сетевых фильтров и стека ядра. |
| **Пропускная способность** | Максимальная (ограничена только скоростью памяти и CPU). | Ограничена системными буферами сокетов и сокетами `TIME_WAIT`. |
| **Риск исчерпания портов** | Отсутствует (файловый дескриптор в VFS). | Высокий при больших RPS (`TIME_WAIT`, нехватка эфемерных портов). |
| **Сетевая изоляция** | Только в пределах одного хоста / пространства имен mount. | Возможность выноса PHP-FPM на отдельный сервер приложений. |
| **Контроль доступа** | Права файловой системы Linux (`chmod`, `chown`). | Межсетевой экран (`nftables`, `iptables`), `listen.allowed_clients`. |

> **Правило SRE:** Для монолитных серверов, где Nginx/Angie и PHP-FPM работают в одной ОС, использование Unix Domain Socket является безальтернативным стандартом. TCP оправдан исключительно при физическом разделении фронтенд-прокси и пула вычислительных серверов FPM.

### Модели управления процессами (`pm`)

Директива `pm` определяет жизненный цикл воркеров внутри пула:

```
static:
[Worker 1][Worker 2][Worker 3] ... [Worker max_children]  (всегда активны в RAM)

dynamic:
[min_spare] <---- автомасштабирование по нагрузке ----> [max_children]

ondemand:
[ 0 воркеров ] ──(пришел запрос)──> [Worker 1] ──(idle > timeout)──> [Уничтожен]
```

1. **`static` (Промышленный стандарт для HighLoad):**
   * Число воркеров фиксировано и равно `pm.max_children`. Процессы создаются при старте службы и никогда не уничтожаются по таймауту простоя.
   * **Преимущества:** Нулевые накладные расходы на системные вызовы `fork()` и завершение процессов при всплесках нагрузки. Память аллоцирована заранее, OPcache и внутренние структуры прогреты. Стабильное и предсказуемое время отклика (P99 latency).
   * **Недостатки:** Постоянно занимает фиксированный объем оперативной памяти, даже в периоды ночного простоя.
   * **Сценарий:** Выделенные production-серверы баз данных и веб-приложений с известным объемом RAM и постоянным трафиком.

2. **`dynamic` (Адаптивный режим):**
   * Количество процессов динамически колеблется между `pm.min_spare_servers` и `pm.max_children`. При старте создается `pm.start_servers`.
   * **Преимущества:** Экономия оперативной памяти во время спада трафика с возможностью масштабирования под пиковые нагрузки.
   * **Недостатки:** При резких всплесках трафика (microbursts) мастер-процесс тратит процессорное время на `fork()`, что приводит к задержкам ответов. Начиная с PHP 8.1 параметр `pm.max_spawn_rate` ограничивает скорость создания процессов (по умолчанию 32 процесса в секунду), предотвращая деградацию хоста от лавины `fork()`.
   * **Сценарий:** Серверы с переменным трафиком, совмещенные среды разработки и тестирования.

3. **`ondemand` (Режим жесткой экономии):**
   * При старте пула воркеры не создаются вовсе (`0` процессов). Соединение принимается мастером, который мгновенно порождает воркер по факту поступления FastCGI-запроса. Если процесс простаивает дольше `pm.process_idle_timeout`, он уничтожается.
   * **Преимущества:** Близкое к нулю потребление RAM в состоянии покоя.
   * **Недостатки:** Максимальная задержка на «холодный старт» (Cold Start) каждого нового запроса. Непригоден для сервисов под непрерывной нагрузкой.
   * **Сценарий:** Размещение сотен низкоактивных сайтов на одном сервере, dev-стенды, редкие административные панели.

### Методология сайзинга памяти и расчет `pm.max_children`

Неверный расчет `pm.max_children` — главная причина двух критических сбоев:
* **Заниженное значение:** Очередь запросов переполняется, веб-сервер возвращает клиентам ошибки `502 Bad Gateway` / `504 Gateway Timeout`.
* **Завышенное значение:** При пиковой нагрузке воркеры FPM исчерпывают физическую оперативную память, ОС начинает активный сброс в Swap (Thrashing), резко падает производительность ввода-вывода, после чего активируется OOM Killer ядра Linux и аварийно завершает процессы базы данных или мастер FPM.

#### 1. Анализ реального потребления памяти воркером (RSS vs PSS)

Стандартная утилита `ps` отображает метрику **RSS (Resident Set Size)**, которая включает в себя разделяемые библиотеки и общий сегмент OPcache. Если 50 процессов используют сегмент OPcache размером 512 МБ, `ps` суммирует эти 512 МБ в RSS каждого процесса, завышая реальное потребление в разы.

Для объективного расчета SRE используют **PSS (Proportional Set Size)** или **USS (Unique Set Size)** через утилиту `smem`:

```bash
# Установка smem в Ubuntu/Debian
sudo apt-get install -y smem
# → Reading package lists... Done

# Анализ потребления пула воркеров PHP-FPM
sudo smem -P php-fpm -c "name pss rss uss" -t -k
# → 
# Name                    Pss          Rss          Uss 
# php-fpm8.4          42.1M        78.4M        35.2M 
# php-fpm8.4          45.8M        82.1M        38.9M 
# ------------------------------------------------------
# 40 processes         1.8G         3.2G         1.5G 
```

* **USS (Unique Set Size):** Чистая приватная память процесса (утечет при завершении).
* **PSS (Proportional Set Size):** Реальная нагрузка на RAM = USS + (Общая разделяемая память / число процессов).

#### 2. Формула безопасного расчета `pm.max_children`

```
Доступная RAM FPM = RAM_Total - (RAM_OS + RAM_Buffer/Cache + RAM_DB/Redis + OPcache_SHM)

pm.max_children = Доступная RAM FPM / Средний PSS воркера под нагрузкой
```

**Практический пример расчета для выделенного сервера приложений (16 GB RAM):**
* Общая физическая память (`RAM_Total`): 16 384 МБ.
* Резерв ОС и системных служб (systemd, sshd, rsyslog): 1 500 МБ.
* Веб-сервер Nginx/Angie (воркеры, буферы соединений): 500 МБ.
* Локальный Redis для кэширования сессий: 1 024 МБ.
* Выделенный буфер OPcache (`opcache.memory_consumption`): 512 МБ.
* **Доступно для пула воркеров FPM:** $16384 - 1500 - 500 - 1024 - 512 = 12\,848\text{ МБ}$.
* Средний PSS тяжелого воркера (Symfony/Laravel под боевой нагрузкой): 60 МБ.
* **Безопасный лимит:** $12848 / 60 \approx 214$.
* **Итоговое значение:** `pm.max_children = 200` (с запасом 7% на кратковременные всплески потребления).

### Внутреннее устройство OPcache, Interned Strings, Preloading и JIT

OPcache размещается в разделяемой памяти и состоит из нескольких функциональных областей:

1. **Сегмент байт-кода (`opcache.memory_consumption`):** Хранит скомпилированное опкод-представление PHP-скриптов. При исчерпании памяти и запрете рестарта OPcache перестает кэшировать новые файлы, переводя воркеры в режим прямой компиляции с диска.
2. **Буфер интернированных строк (`opcache.interned_strings_buffer`):** В современных фреймворках тысячи классов используют одинаковые имена методов, переменных и свойств. PHP выносит повторяющиеся неизменяемые строки в единый глобальный буфер SHM. Если буфер заполнен на 100%, PHP дублирует строки в приватную память каждого воркера, вызывая взрывной рост потребления RAM.
3. **Хеш-таблица ключей файлов (`opcache.max_accelerated_files`):** Таблица ускоренного поиска файлов в кэше. Число слотов в ядре PHP всегда округляется до ближайшего **простого числа** из встроенного списка (`16229`, `32531`, `65407`, `130987`). Если реальное число файлов в проекте превышает этот лимит, поиск замедляется из-за коллизий хеш-таблицы.
4. **OPcache Preloading (PHP 7.4+ / 8.x):** Позволяет загрузить системные библиотеки и ядро фреймворка в постоянную память Zend Engine при старте службы FPM под пользователем `opcache.preload_user = www-data`. Скомпилированные классы становятся постоянно доступны всем воркерам без проверки временных меток файлов.
5. **JIT Compiler (PHP 8.0+):** Компилирует «горячие» участки байт-кода непосредственно в инструкции процессора (x86_64 / ARM64). В режиме `opcache.jit = tracing` профилировщик отслеживает часто исполняемые пути и генерирует машинный код. Для типичных веб-приложений (I/O-bound) выигрыш составляет 3–7%, для вычислительных задач (CPU-bound, обработка изображений, парсинг больших JSON) — до 25–40%.

### Механизм Realpath Cache и атомарные symlink-релизы

При каждом обращении к диску (`require`, `include_once`, доступ к статике) PHP выполняет проверку пути через системные вызовы. `realpath_cache` кэширует разрешенные абсолютные пути и результаты `stat()`:

* **Параметры:** `realpath_cache_size` (размер буфера) и `realpath_cache_ttl` (время жизни записи в секундах).
* **Конфликт с атомарными деплоями:** Системы деплоя (Deployer, Capistrano) переключают версии проекта сменой символической ссылки:
  ```
  /var/www/app/current -> /var/www/app/releases/20261015100000
  ```
* Если Nginx передает в FastCGI `SCRIPT_FILENAME = $document_root$fastcgi_script_name`, где `$document_root` содержит `/current`, воркеры PHP-FPM могут продолжать использовать старый путь из `realpath_cache` в течение `realpath_cache_ttl` секунд, что приводит к состоянию рассинхронизации («split-brain» между старым и новым кодом).
* **Решение:** В конфигурации Nginx/Angie необходимо использовать директиву `$realpath_root`, которая разрешает симлинк на стороне веб-сервера до передачи параметров в PHP:
  ```nginx
  fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
  fastcgi_param DOCUMENT_ROOT $realpath_root;
  ```

### Сквозная цепочка таймаутов (Timeout Chain)

Несогласованность таймаутов в звеньях архитектуры приводит к накоплению зависших воркеров и ошибкам `504 Gateway Timeout`:

```
[ Клиент ] ────────► [ Nginx / Angie ] ────────► [ PHP-FPM Worker ] ────────► [ PostgreSQL / Redis ]
  client_timeout       fastcgi_read_timeout         max_execution_time            statement_timeout
     (60s)                    (30s)                       (20s)                         (10s)
                                                    request_terminate_timeout
                                                              (25s)
```

**Правило согласования для SRE:**
1. `statement_timeout` в СУБД (10s) — запрос к БД должен аварийно обрываться первым.
2. `max_execution_time` в `php.ini` (20s) — встроенный программный таймер PHP прерывает скрипт при превышении лимита времени CPU.
3. `request_terminate_timeout` в `pool.conf` (25s) — жесткий страж на уровне мастера FPM. Срабатывает, если скрипт завис в системном вызове ядра, sleep() или C-расширении (где бессилен `max_execution_time`), отправляя воркеру `SIGKILL`.
4. `fastcgi_read_timeout` в веб-сервере (30s) — веб-сервер должен ждать ответа чуть дольше, чем работает аварийный убийца воркеров FPM, предотвращая генерацию преждевременных `504` ошибок при штатном снятии зависшего процесса.

---

## Практические сценарии и конфигурация

### Сценарий 1: Системная настройка ядра Linux и systemd

Для предотвращения отбрасывания пакетов в очереди сокетов и исчерпания файловых дескрипторов требуется предварительная настройка ОС.

#### 1. Тюнинг параметров ядра (`/etc/sysctl.d/99-php-fpm-tuning.conf`)

```ini
# /etc/sysctl.d/99-php-fpm-tuning.conf

# Максимальный размер очереди не принятых соединений сокета ядра
net.core.somaxconn = 65535

# Глубина очереди входящих пакетов сетевой карты
net.core.netdev_max_backlog = 16384

# Защита от SYN-флуда и расширение очереди полуоткрытых соединений TCP
net.ipv4.tcp_max_syn_backlog = 16384

# Включение переиспользования сокетов в состоянии TIME_WAIT для исходящих TCP-соединений
net.ipv4.tcp_tw_reuse = 1

# Расширение диапазона эфемерных портов для исходящих запросов к БД и внешним API
net.ipv4.ip_local_port_range = 10240 65535

# Общий системный лимит открытых файловых дескрипторов
fs.file-max = 2097152

# Запрет паники ядра при нехватке памяти (режим оверкоммита памяти)
vm.overcommit_memory = 1
```

Применение параметров:

```bash
sudo sysctl -p /etc/sysctl.d/99-php-fpm-tuning.conf
# → net.core.somaxconn = 65535
# → net.core.netdev_max_backlog = 16384
# → net.ipv4.tcp_max_syn_backlog = 16384
# → net.ipv4.tcp_tw_reuse = 1
# → net.ipv4.ip_local_port_range = 10240 65535
# → fs.file-max = 2097152
# → vm.overcommit_memory = 1
```

#### 2. Тюнинг лимитов службы systemd (`override.conf`)

Стандартный сервис `php8.4-fpm.service` часто запускается с консервативными лимитами `LimitNOFILE=1024`. Настраиваем drop-in файл переопределения:

```bash
sudo systemctl edit php8.4-fpm
```

В открывшемся редакторе формируем блок:

```ini
# /etc/systemd/system/php8.4-fpm.service.d/override.conf
[Service]
# Лимиты дескрипторов файлов (соединения, сокеты, файлы скриптов)
LimitNOFILE=131072
LimitNPROC=65535

# Защита от зависания мастер-процесса при рестартах
TimeoutStopSec=15s

# Изоляция временных файлов и защита системных каталогов
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

# Приоритет планировщика ввода-вывода и процессора
Nice=-5
CPUSchedulingPolicy=other
```

Применение изменений:

```bash
sudo systemctl daemon-reload
# → (успешная перезагрузка конфигурации systemd)

sudo systemctl restart php8.4-fpm
# → (перезапуск демона с новыми лимитами)

# Проверка примененных лимитов у запущенного мастер-процесса
cat /proc/$(pgrep -o php-fpm)/limits | grep "Max open files"
# → Max open files            131072               131072               files
```

---

### Сценарий 2: Глобальная конфигурация демона (`php-fpm.conf`)

Файл `/etc/php/8.4/fpm/php-fpm.conf` определяет глобальное поведение мастера, защиту от сбоев и параметры журналирования:

```ini
; /etc/php/8.4/fpm/php-fpm.conf
[global]
pid = /run/php/php8.4-fpm.pid
error_log = /var/log/php8.4-fpm.log

; Уровень детализации журнала (notice, warning, error, alert, debug)
log_level = notice

; Ограничение длины одной строки журнала для предотвращения переполнения буферов
log_limit = 8192

; Буферизация вывода логов для минимизации блокировок ввода-вывода
log_buffering = yes

; Автоматический перезапуск мастера FPM при падении дочерних процессов
; Если 10 воркеров упали по SIGSEGV/SIGBUS за 1 минуту — FPM выполняет аварийный рестарт
emergency_restart_threshold = 10
emergency_restart_interval = 1m

; Таймаут ожидания реакции дочернего процесса на управляющий сигнал мастера
process_control_timeout = 10s

; Запуск в фоновом режиме демона
daemonize = yes

; Системный лимит открытых файлов для мастер-процесса
rlimit_files = 131072

; Подключение пулов приложений
include = /etc/php/8.4/fpm/pool.d/*.conf
```

---

### Сценарий 3: Промышленный пул `static` для стабильной нагрузки

Режим `static` минимизирует задержки в приложениях enterprise-уровня за счет предварительного выделения пула рабочих процессов.

```ini
; /etc/php/8.4/fpm/pool.d/www.conf
[www]
user = www-data
group = www-data

; Транспорт: Unix Domain Socket с согласованными правами доступа
listen = /run/php/php8.4-fpm.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660

; Максимальный размер очереди сокета (согласован с net.core.somaxconn)
listen.backlog = 65535

; Фиксированная модель управления процессами
pm = static
pm.max_children = 120

; Ротация воркеров для гарантированного предотвращения деградации по памяти
pm.max_requests = 1000

; Эндпоинты самодиагностики и проверки жизнеспособности (доступ закрыт снаружи)
pm.status_path = /fpm-status
ping.path = /ping
ping.response = pong

; Сквозные таймауты и профилирование медленных запросов
request_terminate_timeout = 35s
request_slowlog_timeout = 5s
slowlog = /var/log/php8.4-fpm/slowlog-www.log
request_slowlog_trace_depth = 25

; Ограничения дескрипторов и дампов памяти на уровне воркера
rlimit_files = 65535
rlimit_core = 0

; Перехват стандартных потоков stdout/stderr воркеров
catch_workers_output = yes
decorate_workers_output = no

; Очистка переменных окружения для защиты секретов ОС
clear_env = no

; Настройки PHP-рантайма для пула
php_admin_value[memory_limit] = 256M
php_admin_value[max_execution_time] = 30
php_admin_value[max_input_time] = 30
php_admin_value[post_max_size] = 32M
php_admin_value[upload_max_filesize] = 32M
php_admin_value[expose_php] = Off
php_admin_flag[display_errors] = Off
php_admin_flag[log_errors] = On
php_admin_value[error_log] = /var/log/php8.4-fpm/www-error.log
```

---

### Сценарий 4: Промышленный пул `dynamic` с защитой от лавины `fork()`

Конфигурация для серверов с выраженными суточными колебаниями трафика:

```ini
; /etc/php/8.4/fpm/pool.d/dynamic.conf
[dynamic]
user = www-data
group = www-data

listen = /run/php/php8.4-fpm-dynamic.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660
listen.backlog = 65535

pm = dynamic
pm.max_children = 80
pm.start_servers = 16
pm.min_spare_servers = 8
pm.max_spare_servers = 24

; Защита от шторма fork() при резких скачках нагрузки (PHP 8.1+)
pm.max_spawn_rate = 32

; Таймаут освобождения простаивающих процессов
pm.process_idle_timeout = 10s

pm.max_requests = 1500

pm.status_path = /fpm-status
ping.path = /ping

request_terminate_timeout = 30s
request_slowlog_timeout = 4s
slowlog = /var/log/php8.4-fpm/slowlog-dynamic.log
request_slowlog_trace_depth = 20

rlimit_files = 65535
catch_workers_output = yes
decorate_workers_output = no

php_admin_value[memory_limit] = 192M
php_admin_value[max_execution_time] = 25
```

---

### Сценарий 5: Тонкая настройка OPcache, Preloading и JIT в PHP 8.x

Конфигурационный файл модуля OPcache (`/etc/php/8.4/mods-available/opcache.ini`):

```ini
; /etc/php/8.4/mods-available/opcache.ini
[opcache]
opcache.enable = 1
opcache.enable_cli = 0

; Выделение памяти под скомпилированный байт-код (МБ)
opcache.memory_consumption = 512

; Буфер интернированных строк для имен классов и методов (МБ)
; Критически важен для Symfony, Laravel, Magento (минимум 32-64 МБ)
opcache.interned_strings_buffer = 64

; Емкость хеш-таблицы кэшируемых файлов (простое число)
; Значения: 7963, 16229, 32531, 65407, 130987
opcache.max_accelerated_files = 65407

; Процент потерянной памяти для инициализации автоматического перезапуска кэша
opcache.max_wasted_percentage = 10

; Проверка изменений файлов на диске
; В боевом production с immutable-деплоем рекомендуется отключать:
opcache.validate_timestamps = 0
opcache.revalidate_freq = 0

; Обязательно сохранять комментарии и аннотации (PHP Attributes)
opcache.save_comments = 1

; Быстрая проверка существования файлов
opcache.enable_file_override = 1

; Использование Huge Pages ядра Linux для ускорения трансляции адресов TLB
opcache.huge_code_pages = 1

; Механизм Preloading: предварительная компиляция ядра приложения при старте
; opcache.preload = /var/www/app/releases/current/config/preload.php
; opcache.preload_user = www-data

; Конфигурация JIT-компилятора (PHP 8.0+)
; 1254 (tracing JIT: оптимальный баланс профилирования и ускорения)
opcache.jit = 1254
opcache.jit_buffer_size = 128M
```

> **Важно:** При `opcache.validate_timestamps = 0` любые изменения в PHP-файлах на диске игнорируются до тех пор, пока не будет выполнен `systemctl reload php8.4-fpm`. Это идеальный режим для production, исключающий накладные вызовы `stat()` ядра на каждый запрос.

---

### Сценарий 6: Профилирование медленных запросов через Slowlog

Включение Slowlog позволяет выявлять блокирующие узкие места в приложении (тяжелые SQL-запросы, зависшие внешние HTTP-клиенты, неоптимальные циклы):

```ini
; В конфигурации пула pool.d/www.conf
request_slowlog_timeout = 3s
slowlog = /var/log/php8.4-fpm/slowlog.log
request_slowlog_trace_depth = 30
```

Пример содержимого журнала `/var/log/php8.4-fpm/slowlog.log`:

```
[15-Oct-2026 10:14:02]  [pool www] pid 24912
script_filename = /var/www/app/public/index.php
[0x00007f3d8e21a0a0] curl_exec() /var/www/app/src/Service/PaymentClient.php:48
[0x00007f3d8e21a180] sendPaymentRequest() /var/www/app/src/Controller/CheckoutController.php:82
[0x00007f3d8e21a240] handleCheckout() /var/www/app/vendor/symfony/http-kernel/HttpKernel.php:163
```

**Анализ SRE:** Воркер завис на 48 строке `PaymentClient.php` внутри функции `curl_exec()`. Причина — отсутствие таймаута соединения (`CURLOPT_CONNECTTIMEOUT_MS` / `CURLOPT_TIMEOUT`) при взаимодействии со сторонним платежным шлюзом.

---

## Эксплуатация и команды администрирования

### Управление демоном и сигналами (Graceful Reload)

PHP-FPM поддерживает стандартные сигналы POSIX для управления жизненным циклом:

| Сигнал | Назначение | Команда POSIX |
| :--- | :--- | :--- |
| **`SIGUSR2`** | Плавный перезапуск без потери запросов (Graceful Reload). | `kill -USR2 $(cat /run/php/php8.4-fpm.pid)` |
| **`SIGQUIT`** | Плавное завершение процессов после отдачи текущих ответов. | `kill -QUIT $(cat /run/php/php8.4-fpm.pid)` |
| **`SIGTERM` / `SIGINT`** | Немедленная аварийная остановка мастера и всех воркеров. | `kill -TERM $(cat /run/php/php8.4-fpm.pid)` |
| **`SIGUSR1`** | Переоткрытие лог-файлов (используется для logrotate). | `kill -USR1 $(cat /run/php/php8.4-fpm.pid)` |

**Порядок выполнения Graceful Reload в systemd:**

```bash
# 1. Проверка синтаксиса перед перезапуском
sudo php-fpm8.4 -t
# → [15-Oct-2026 10:15:30] NOTICE: configuration file /etc/php/8.4/fpm/php-fpm.conf test is successful

# 2. Плавная перезагрузка конфигурации (отправляет SIGUSR2 мастер-процессу)
sudo systemctl reload php8.4-fpm
# → (код возврата 0, активные запросы не сбрасываются)

# 3. Проверка статуса службы после перезагрузки
sudo systemctl status php8.4-fpm --no-pager
# → Active: active (running) since ...
```

### Валидация конфигурации и инспекция запущенных пулов

```bash
# Просмотр активных пулов и директив через CLI
sudo php-fpm8.4 -tt 2>&1 | grep -E "pm\.max_children|listen\.backlog"
# → pm.max_children = 120
# → listen.backlog = 65535

# Проверка прослушиваемого сокета в ОС
sudo ss -l -x -p | grep php
# → u_str LISTEN 0 65535 /run/php/php8.4-fpm.sock 142109 users:(("php-fpm8.4",pid=1204,fd=7))

# Мониторинг распределения процессов FPM в дереве процессов
pstree -p $(pgrep -o php-fpm)
# → php-fpm8.4(1204)───┬───php-fpm8.4(1205)
#                      ├───php-fpm8.4(1206)
#                      └───php-fpm8.4(1207)
```

### Ротация журналов (`logrotate`)

Файл конфигурации ротации логов `/etc/logrotate.d/php-fpm`:

```ini
# /etc/logrotate.d/php-fpm
/var/log/php8.4-fpm/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        /usr/lib/php/php-fpm-reopenlogs || kill -USR1 $(cat /run/php/php8.4-fpm.pid 2>/dev/null) 2>/dev/null || true
    endscript
}
```

Тестирование корректности ротации:

```bash
sudo logrotate -d /etc/logrotate.d/php-fpm
# → reading config file /etc/logrotate.d/php-fpm
# → handling said file...
```

---

## Диагностика и устранение неисправностей

### Сводная матрица типовых инцидентов

| Симптом / Ошибка | Первопричина | Алгоритм решения SRE / Sysadmin |
| :--- | :--- | :--- |
| **`502 Bad Gateway`**<br>`connect() to unix:... failed (11: Resource temporarily unavailable)` | Переполнена системная очередь Listen Backlog сокета ядра. Воркеры не успевают вызывать `accept()`. | 1. Увеличить `net.core.somaxconn` в `/etc/sysctl.conf`.<br>2. Увеличить `listen.backlog` в `pool.conf`.<br>3. Увеличить `pm.max_children`. |
| **`502 Bad Gateway`**<br>`connect() to unix:... failed (13: Permission denied)` | Неверные права доступа или владелец Unix-сокета. Веб-сервер не может открыть файл сокета. | 1. Проверить `ls -la /run/php/php8.4-fpm.sock`.<br>2. Выставить `listen.owner = www-data`, `listen.group = www-data`, `listen.mode = 0660`. |
| **`502 Bad Gateway`**<br>`recv() failed (104: Connection reset by peer)` | Дочерний воркер FPM аварийно завершился во время выполнения (Segmentation fault, OOM Killer). | 1. Проверить системный лог: `sudo dmesg -T \| grep -i -E "oom\|segfault"`.<br>2. Проверить `/var/log/php8.4-fpm.log`. |
| **`504 Gateway Timeout`** | Воркер заблокирован на внешнем вызове (СУБД, Redis, curl API), веб-сервер разорвал соединение по `fastcgi_read_timeout`. | 1. Проверить `/var/log/php8.4-fpm/slowlog.log`.<br>2. Настроить сквозную цепочку таймаутов (`request_terminate_timeout`). |
| **`WARNING: [pool ...] server reached pm.max_children setting`** | Пул воркеров полностью загружен. Новые запросы накапливаются в очереди ожидания. | 1. Проверить через `smem` доступную RAM.<br>2. Увеличить `pm.max_children` либо оптимизировать время ответа медленных эндпоинтов. |
| **`Zend OPcache buffer is full, cannot allocate`** | Закончилась память `opcache.memory_consumption` или буфер `interned_strings_buffer`. | 1. Проверить статус через `opcache_get_status()`.<br>2. Увеличить `opcache.memory_consumption` и `opcache.interned_strings_buffer`. |

---

### Анализ зависших воркеров через `strace`, `gdb` и procfs

Если воркер зависает со 100% утилизацией CPU или находится в состоянии `D` (Uninterruptible Sleep):

#### 1. Трассировка системных вызовов в реальном времени (`strace`)

```bash
# Поиск PID процессов, потребляющих больше всего CPU
top -b -n 1 -o %CPU | grep php-fpm
# → 24912 www-data  20   0  350M  85M  12M R  98.2   1.1  0:45.12 php-fpm8.4

# Подключение к работающему процессу без его остановки
sudo strace -p 24912 -s 256 -f -T
# → poll([{fd=9, events=POLLIN|POLLERR|POLLHUP}], 1, 10000) = 0 (Timeout) <10.001245>
# → write(2, "Database connection timeout...", 31) = 31 <0.000042>
```

#### 2. Инспекция файловых дескрипторов и сетевых соединений процесса

```bash
# Просмотр открытых сокетов и файлов конкретного воркера
sudo ls -l /proc/24912/fd
# → lrwx------ 1 www-data www-data 64 Oct 15 10:18 0 -> /dev/null
# → lr-x------ 1 www-data www-data 64 Oct 15 10:18 3 -> /run/php/php8.4-fpm.sock
# → lrwx------ 1 www-data www-data 64 Oct 15 10:18 4 -> socket:[145129] (TCP соединение к Postgres:5432)

# Проверка текущего состояния сокета
ss -t -a | grep 145129
# → ESTAB 0 128 10.0.1.15:48210 10.0.2.50:5432
```

#### 3. Извлечение PHP Backtrace из упавшего процесса через `gdb`

При аварийном завершении по Segfault можно подключить `gdb` и вызвать встроенную функцию отладки Zend Engine:

```bash
sudo gdb /usr/sbin/php-fpm8.4 --pid 24912 --batch \
  -ex "set pagination off" \
  -ex "print zend_print_zval(*executor_globals.current_execute_data, 1)" \
  -ex "bt"
# → #0  0x00007f3d8d1024a1 in zend_mm_alloc_small () from /usr/sbin/php-fpm8.4
# → #1  0x00007f3d8d123b56 in ...
```

---

### Диагностика переполнения очереди сокета (`ListenBacklog`)

Для контроля состояния очередей сокетов на уровне ядра используется утилита `ss`:

```bash
# Просмотр состояния Unix-сокета PHP-FPM
sudo ss -l -x src /run/php/php8.4-fpm.sock
# → Netid  State   Recv-Q  Send-Q   Local Address:Port   Peer Address:Port
# → u_str  LISTEN  128     65535    /run/php/php8.4-fpm.sock 142109 * 0
```

* **`Send-Q`:** Максимальный размер очереди сокета (`listen.backlog`).
* **`Recv-Q`:** Текущее количество ожидающих соединений, которые еще не были приняты воркерами FPM через `accept()`.
* **Интерпретация:** Если в выводе `Recv-Q > 0`, пул воркеров работает на пределе возможностей. Если `Recv-Q == Send-Q`, ядро Linux отбрасывает новые входящие подключения, а клиенты немедленно получают ошибки `502 Bad Gateway`.

---

## Рекомендации и Best Practices

### Производственный чек-лист SRE / Sysadmin

- [ ] **Модель пула:** Для production-серверов с известными ресурсами зафиксирован `pm = static`.
- [ ] **Расчет памяти:** Параметр `pm.max_children` рассчитан по метрике PSS через `smem`, а не по RSS.
- [ ] **Транспорт:** Для локального взаимодействия настроен Unix Domain Socket с правами `0660`.
- [ ] **Очереди ядра:** Значение `listen.backlog` синхронизировано с системным параметром `net.core.somaxconn` (например, `65535`).
- [ ] **Предотвращение утечек:** Параметр `pm.max_requests` выставлен в диапазоне `1000–3000`.
- [ ] **Лимиты systemd:** Для службы FPM переопределены `LimitNOFILE` (не менее `65535`) и `LimitNPROC`.
- [ ] **OPcache Memory:** Буфер `opcache.memory_consumption` достаточен для проекта, процент утилизации не превышает 85%.
- [ ] **Interned Strings:** Буфер `opcache.interned_strings_buffer` увеличен минимум до 32–64 МБ.
- [ ] **OPcache Files:** Параметр `opcache.max_accelerated_files` превышает общее число файлов проекта и выставлен в простое число.
- [ ] **Immutable Production:** Директива `opcache.validate_timestamps = 0` включена в боевой среде (с обязательным `systemctl reload` при деплое).
- [ ] **Симлинки и пути:** В конфигурации веб-сервера используется `$realpath_root` для корректной работы `realpath_cache`.
- [ ] **Цепочка таймаутов:** Настроена согласованность: `statement_timeout` < `max_execution_time` < `request_terminate_timeout` < `fastcgi_read_timeout`.
- [ ] **Slowlog:** Профилирование включено с порогом `request_slowlog_timeout = 3s–5s` и достаточной глубиной трейса.

### Антипаттерны эксплуатации

1. **Использование `pm = ondemand` на высоконагруженных проектах.** Приводит к постоянным задержкам на создание процессов (`fork()`) и сбросу кэшей рантайма.
2. **Одинаковые значения таймаутов.** Настройка `max_execution_time = 30` и `fastcgi_read_timeout = 30` приводит к состоянию гонки: веб-сервер закрывает сокет раньше, чем FPM успевает сгенерировать понятный лог ошибки.
3. **Бесконечный `pm.max_requests = 0`.** Даже качественный прикладной код со временем фрагментирует кучу C-библиотек; отказ от периодического рестарта воркеров ведет к прогрессирующей деградации RAM.
4. **Хранение логов в корневом разделе без ротации.** Неконтролируемый рост `/var/log/php8.4-fpm/slowlog.log` может привести к заполнению диска (`No space left on device`) и аварийной остановке всего сервера.
5. **Игнорирование метрики `interned_strings_buffer`.** Нехватка этого буфера переводит интернирование строк в локальную память каждого воркера, увеличивая средний PSS процесса на 30–50%.

---

## Дополнительная информация

### См. также

* **[Мониторинг PHP-FPM](./php-fpm-monitoring.md)** — глубокий мониторинг пулов, нативные метрики OpenMetrics, Prometheus-алерты и дашборды Grafana.
* **[FastCGI и PHP-FPM в Angie](../Angie/angie-fastcgi-php-fpm.md)** — детальная настройка веб-сервера Angie для взаимодействия с пулами FPM, балансировка и кэширование FastCGI.
* **[Сравнение веб-серверов](../Concepts/webserver_comparison.md)** — архитектурные модели обработки запросов, место FastCGI/PHP-FPM в современном веб-стеке.
* **[Тюнинг производительности Nginx](../Nginx/Performance/nginx_performance_tuning.md)** — оптимизация параметров буферизации, keepalive-соединений к апстримам и сокетов.
* **[Бенчмаркинг веб-серверов](../webserver_benchmarking.md)** — методология нагрузочного тестирования пропускной способности стека Nginx/Angie + PHP-FPM.

### Официальная документация и спецификации

* [PHP.net: Конфигурация PHP-FPM (`php-fpm.conf`)](https://www.php.net/manual/en/install.fpm.configuration.php)
* [PHP.net: Директивы конфигурации OPcache](https://www.php.net/manual/en/opcache.configuration.php)
* [PHP.net: Механизм предварительной загрузки (Preloading)](https://www.php.net/manual/en/opcache.preloading.php)
* [Спецификация протокола FastCGI (FastCGI Specification)](https://fastcgi-archives.github.io/FastCGI_Specification.html)
