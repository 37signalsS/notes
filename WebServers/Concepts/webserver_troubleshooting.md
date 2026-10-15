# Диагностика веб-серверов (Troubleshooting)

**Актуально для:** Nginx 1.26+, Angie 1.8+, Apache 2.4.60+, HAProxy 3.0+, Linux Kernel 5.15+ / 6.x, systemd 249+

---

## Определения

**Troubleshooting (Поиск и устранение неисправностей)** — систематический процесс выявления, анализа и устранения причин, препятствующих корректной работе веб-сервера (Nginx, Angie, Apache, HAProxy) или связанных с ним системных и прикладных сервисов.

**Post-reboot failure (Сбой после перезагрузки)** — аварийная ситуация, при которой сервис штатно функционировал до перезагрузки операционной системы, но не смог запуститься либо корректно принимать трафик после рестарта из-за проблем с порядком инициализации systemd, монтированием сетевых файловых систем, доступностью DNS или привязкой к сетевым интерфейсам (`IP_FREEBIND`).

**MTTR (Mean Time To Repair)** — среднее время восстановления сервиса после инцидента. В SRE-практиках снижение MTTR достигается заблаговременной подготовкой runbook'ов, автоматизацией сбора диагностических артефактов и применением стандартизированных алгоритмов локализации сбоев.

**Runbook** — пошаговый эксплуатационный регламент для инженера DevOps/SRE/SysAdmin по реагированию на инцидент. Включает критерии идентификации проблемы, верифицированные диагностические команды, шаги локализации, методы безопасного восстановления и критерии эскалации.

**Узел отказа (Failure Domain)** — изолированная граница инфраструктуры или программного стека, сбой внутри которой приводит к деградации либо недоступности сервиса. Для веб-сервера узлами отказа выступают: процессное пространство сервера, сокеты и очереди ядра Linux, сетевая подсистема, дисковый ввод-вывод (I/O), DNS-резолвер, TLS-терминация и upstream-приложения.

**USE-метод (Utilization, Saturation, Errors)** — методология анализа производительности Брендана Грегга для аппаратных и системных ресурсов: утилизация (процент времени занятости ресурса), насыщение (наличие очереди задач к ресурсу) и ошибки (счетчики отказов ресурса).

**RED-метод (Rate, Errors, Duration)** — методология мониторинга сервисов, ориентированная на клиентский опыт: частота входящих запросов (Rate), количество или доля ошибочных ответов (Errors) и задержка обработки запросов (Duration/Latency).

**Listen Backlog** — системная очередь сокета в ядре Linux для входящих TCP-соединений, завершивших трехстороннее рукопожатие (3-way handshake), но еще не извлеченных приложением с помощью системного вызова `accept()`. Размер регулируется параметром `somaxconn` ядра и аргументом вызова `listen()`.

**SYN Backlog** — очередь полуоткрытых соединений (состояние `SYN_RECV`), для которых сервер получил пакет `SYN`, отправил `SYN-ACK`, но ожидает финальный `ACK` от клиента. Регулируется параметром `tcp_max_syn_backlog` ядра.

**Ephemeral Port Exhaustion (Исчерпание динамических портов)** — состояние операционной системы, при котором исчерпан диапазон локальных TCP-портов (`ip_local_port_range`), выделяемых для исходящих соединений к upstream-серверам, чаще всего вызванное скоплением сокетов в состоянии `TIME_WAIT`.

**Graceful Reload** — операция перечитывания конфигурации веб-сервера без разрыва активных клиентских соединений: master-процесс проверяет конфигурацию, запускает новое поколение worker-процессов и отправляет старому поколению сигнал на плавное завершение после обработки текущих запросов.

---

## Базовые концепции и архитектура

### Архитектурные уровни и точки отказа

Для корректной локализации аварии веб-сервер рассматривается как многоуровневая система, объединяющая стек сетевых протоколов ядра, управление процессами ОС и прикладную логику проксирования:

```text
[ Клиентский трафик ]
         │
         ▼
┌────────────────────────────────────────────────────────┐
│ 1. Сетевой уровень ядра Linux                          │
│    - Сетевой интерфейс, драйвер, очереди RX/TX         │
│    - Файрвол: nftables / iptables / conntrack          │
│    - TCP SYN Backlog (tcp_max_syn_backlog)             │
│    - TCP Listen Backlog (somaxconn, accept queue)      │
└────────────────────────┬───────────────────────────────┘
                         │ accept()
                         ▼
┌────────────────────────────────────────────────────────┐
│ 2. Процессное пространство веб-сервера                 │
│    - Master-процесс: root, чтение конфигов, bind портов│
│    - Worker-процессы: неблокирующий epoll event loop   │
│    - Системные лимиты: LimitNOFILE, worker_rlimit      │
│    - Буферы и разделяемая память: shared memory zones  │
└────────────────────────┬───────────────────────────────┘
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
┌────────────────────────┐    ┌──────────────────────────┐
│ 3. Локальные ресурсы   │    │ 4. Upstream-подсистема   │
│  - Файловая система    │    │  - Unix Domain Sockets   │
│  - Inodes, свободное   │    │  - TCP Loopback/LAN сокет│
│    место, lsof +L1     │    │  - FastCGI / PHP-FPM     │
│  - Права DAC (chmod)   │    │  - Пул keepalive-соединений
│  - Политики MAC        │    │  - Таймауты чтения/ответа│
│    (SELinux, AppArmor) │    │  - Прикладные БД/очереди │
└────────────────────────┘    └──────────────────────────┘
```

Каждый компонент архитектуры формирует изолированную область возможных сбоев:
- **Master-процесс:** управляет жизненным циклом воркеров. Падение master останавливает обслуживание новых клиентов; зависание master блокирует `reload` и ротацию логов.
- **Worker-процессы:** исполняют цикл обработки событий (`epoll`/`kqueue`). Зависание воркера в блокирующем системном вызове (дисковый ввод-вывод, обращение к медленной ФС) парализует обработку сотен клиентских соединений, прикрепленных к данному воркеру.
- **Очереди ядра:** при пиковом наплыве трафика или зависании воркеров очереди `listen` переполняются, в результате чего ядро молча сбрасывает новые входящие пакеты `SYN` или отправляет `RST`.
- **Upstream-канал:** задержки в обработке динамических запросов приложением приводят к исчерпанию соединений между веб-сервером и бэкендом, возвращая клиентам ошибки 502/504.

### Универсальный алгоритм диагностики (метод слоев)

Диагностика строится от внешних сетевых границ к внутренним системным зависимостям по цепочке прохождения запроса:

1. **Разрешение доменного имени (DNS):** клиент получает корректный IP-адрес хоста без зависаний резолверов.
2. **Сетевая доступность и маршрутизация:** пакеты достигают целевого сетевого интерфейса, не отбрасываются пакетным фильтром (`nftables`/`iptables`) и таблицей трансляции состояний (`conntrack`).
3. **Установка TCP-соединения (3-Way Handshake):** ядро принимает SYN, отправляет SYN-ACK и помещает сокет в очередь `listen`.
4. **Криптографическое рукопожатие (TLS Handshake):** согласование версии протокола, шифронабора, передача полной цепочки сертификатов и сопоставление SNI (Server Name Indication).
5. **Прием и валидация HTTP-запроса:** разбор строки запроса и заголовков воркером веб-сервера, проверка размера тела (`client_max_body_size` / `LimitRequestBody`).
6. **Маршрутизация и права доступа (Static vs Dynamic):**
   - Для статических файлов: проверка прав доступа на уровне ФС (DAC) и меток безопасности (SELinux/AppArmor).
   - Для динамики: установление соединения с upstream (TCP или Unix-сокет), передача запроса, ожидание ответа в рамках таймаутов.
7. **Формирование и отправка ответа:** отдача статуса и тела ответа клиенту, освобождение ресурсов сокета.

> **Важно:** Попытка немедленного перезапуска сервиса (`systemctl restart`) до фиксации текущего состояния является грубой эксплуатационной ошибкой. Перезапуск стирает дампы памяти, сбрасывает счетчики соединений в сокетах ядра, удаляет сопутствующие временные сокеты и превращает диагностируемый инцидент в трудноуловимый периодический сбой. Первое действие инженера — фиксация метрик, логов и состояния сокетов.

### Локализация стадии сбоя со стороны клиента

Первичная локализация выполняется утилитой `curl` с детальным выводом (`-v`) и жесткими таймаутами. Это позволяет точно определить, на каком этапе прерывается сессия:

```bash
curl -v --connect-timeout 5 --max-time 15 -o /dev/null -s -w "\
DNS Lookup:        %{time_namelookup}s\n\
TCP Connect:       %{time_connect}s\n\
TLS Handshake:     %{time_appconnect}s\n\
Pre-transfer:      %{time_pretransfer}s\n\
Start Transfer:    %{time_starttransfer}s\n\
Total Time:        %{time_total}s\n\
HTTP Code:         %{http_code}\n" https://example.com/
# → DNS Lookup:        0.004123s
# → TCP Connect:       0.021456s
# → TLS Handshake:     0.054321s
# → Pre-transfer:      0.054410s
# → Start Transfer:    0.124512s
# → Total Time:        0.125890s
# → HTTP Code:         200
```

Сводная матрица симптомов в клиентском выводе:

| Симптом в выводе curl | Стадия обрыва | Вероятная причина в инфраструктуре | Инструменты локализации на сервере |
| :--- | :--- | :--- | :--- |
| `Could not resolve host` | DNS-резолвинг | Ошибка в `/etc/resolv.conf`, падение локального `systemd-resolved`, сбой авторитетных DNS. | `resolvectl status`, `dig +trace`, `cat /etc/resolv.conf` |
| `Connection refused` (мгновенно) | TCP Connect | Веб-сервер не запущен, упал worker/master, сокет слушает не тот интерфейс, либо файрвол ответил `TCP RST / REJECT`. | `ss -ltnp`, `systemctl status`, `nft list ruleset` |
| `Connection timed out` (через 5с) | TCP Connect | Пакетный фильтр хоста или шлюза отбрасывает пакеты (`DROP`), заполнена таблица `conntrack`, сетевая черная дыра (MTU/Routing). | `dmesg \| grep conntrack`, `tcpdump -ni any 'tcp port 80 or tcp port 443'` |
| Зависание на `SSL connection using...` или `SSL certificate verify failed` | TLS Handshake | Сертификат просрочен, отсутствует промежуточный сертификат (Intermediate CA) в `fullchain.pem`, несовпадение SNI, блокировка MTU. | `openssl s_client -connect IP:443 -servername HOST`, `curl --resolve` |
| `Empty reply from server` | HTTP Request/Response | Воркер веб-сервера аварийно завершился (segfault / OOM) во время обработки запроса, сброс соединения ядром. | `dmesg -T \| grep -i oom`, `journalctl -k`, `coredumpctl list` |
| Таймаут после отправки запроса (`Start Transfer` превышает `--max-time`) | Upstream Processing | Зависание прикладного сервера (PHP-FPM, uWSGI, Go/Java app), дедлок в базе данных, исчерпание пула воркеров бэкенда. | `ss -lntp 'sport = :8000'`, `strace -p PID`, `journalctl -u app` |

Для исключения влияния Dual-Stack сетевой конфигурации всегда проверяется изолированная работа по протоколам IPv4 и IPv6:

```bash
# Диагностика только через IPv4
curl -4 -v --connect-timeout 5 --max-time 15 -o /dev/null https://example.com/
# → Connected to example.com (203.0.113.10) port 443

# Диагностика только через IPv6
curl -6 -v --connect-timeout 5 --max-time 15 -o /dev/null https://example.com/
# → Connection timed out after 5001 milliseconds
```
*Интерпретация:* Успешное соединение по IPv4 и таймаут по IPv6 указывает на некорректно опубликованную AAAA-запись в DNS, отсутствие маршрутизации IPv6 на шлюзе или отсутствие привязки сокета к `[::]:443` в конфигурации веб-сервера.

---

## Практические сценарии диагностики и локализации

### Сценарий 1: Валидация синтаксиса и инспекция активного дерева конфигурации

При внесении изменений или аварийном падении сервиса первым шагом выполняется синтаксическая валидация конфигурационных файлов без перезапуска рабочего процесса.

**Диагностика синтаксиса:**

```bash
# Nginx / Angie: валидация файлов конфигурации
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Apache: валидация синтаксиса
sudo apachectl configtest
# → Syntax OK

# HAProxy: валидация файла конфигурации
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file /etc/haproxy/haproxy.cfg is valid
```

**Инспекция активного дерева конфигурации:**
Частая ошибка инженера — редактирование файла, который фактически не подключен через директивы `include`, либо переопределение параметров в последующих блоках. Вывод полного объединенного дерева конфигурации:

```bash
# Nginx / Angie: дамп всей рабочей конфигурации со всеми include
sudo nginx -T | grep -E "server_name|listen|proxy_pass"
# → server_name example.com www.example.com;
# → listen 443 ssl http2;
# → proxy_pass http://127.0.0.1:8080;

# Apache: вывод виртуальных хостов, порядка их сопоставления и расположения в файлах
sudo apachectl -S
# → VirtualHost configuration:
# → *:443 is a NameVirtualHost
# →      default server example.com (/etc/apache2/sites-enabled/example.conf:1)
# →      port 443 namevhost example.com (/etc/apache2/sites-enabled/example.conf:1)
# →      port 443 namevhost api.example.com (/etc/apache2/sites-enabled/api.conf:1)
```

### Сценарий 2: Диагностика переполнения сетевых очередей ядра (Listen Backlog drops)

Если веб-сервер запущен, но клиенты периодически сталкиваются с задержками или ошибками соединения при высокой нагрузке, вероятная причина — насыщение очередей сокета в ядре Linux.

**1. Проверка текущей глубины очереди слушающих сокетов:**

```bash
# Просмотр очереди сокетов веб-сервера
ss -lnt '( sport = :80 or sport = :443 )'
# → State  Recv-Q  Send-Q  Local Address:Port  Peer Address:Port
# → LISTEN 129     128     0.0.0.0:80          0.0.0.0:*
# → LISTEN 0       511     0.0.0.0:443         0.0.0.0:*
```
*Интерпретация:* Для сокетов в состоянии `LISTEN` колонка `Send-Q` отображает максимально допустимый размер очереди `listen backlog`, а `Recv-Q` — количество соединений, ожидающих вызова `accept()`. Если `Recv-Q > Send-Q`, очередь переполнена, и ядро отбрасывает новые входящие подключения.

**2. Анализ системных счетчиков сброса пакетов ядра:**

```bash
# Поиск сброшенных соединений из-за переполнения очередей listen
netstat -s | grep -i "listen"
# → 1420 times the listen queue of a socket overflowed
# → 1420 SYNs to LISTEN sockets dropped
```

**3. Устранение насыщения:**
Размер очереди ограничивается минимумом из двух значений: директивы веб-сервера (`listen ... backlog=N`) и системного параметра ядра `net.core.somaxconn`.

```bash
# Проверка текущего системного лимита
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog
# → net.core.somaxconn = 4096
# → net.ipv4.tcp_max_syn_backlog = 4096

# Применение увеличенных лимитов на лету
sudo sysctl -w net.core.somaxconn=65535
# → net.core.somaxconn = 65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=65535
# → net.ipv4.tcp_max_syn_backlog = 65535
```
Для фиксации настроек добавьте параметры в файл `/etc/sysctl.d/99-webserver-backlog.conf` и выполните `sudo sysctl --system`. В конфигурации Nginx укажите: `listen 443 ssl backlog=65535;`.

### Сценарий 3: Исчерпание эфемерных портов и соединений TIME_WAIT к upstream

При интенсивном обращении веб-сервера к локальным или сетевым upstream-серверам (например, PHP-FPM по TCP 127.0.0.1:9000 или кластер Node.js) без постоянных соединений (HTTP Keep-Alive) операционная система генерирует тысячи короткоживущих сокетов, переходящих в состояние `TIME_WAIT` (по умолчанию 60 секунд в Linux).

**Диагностика:**

```bash
# Подсчет количества TCP-сокетов по состояниям
ss -tan | awk '{print $1}' | sort | uniq -c
# →   15 ESTAB
# →    2 LISTEN
# → 28410 TIME-WAIT

# Проверка доступного диапазона эфемерных портов
cat /proc/sys/net/ipv4/ip_local_port_range
# → 32768   60999
```
*Интерпретация:* Диапазон от 32768 до 60999 предоставляет всего 28231 порт. Наличие 28410 сокетов в `TIME-WAIT` означает полное исчерпание пула портов для конкретного кортежа (source IP, source port, dest IP, dest port). Веб-сервер начинает регистрировать ошибки в `error.log`:
`connect() to 127.0.0.1:9000 failed (99: Cannot assign requested address)`.

**Решение:**
1. **Включение повторного использования сокетов TIME_WAIT на уровне ядра:**
   ```bash
   sudo sysctl -w net.ipv4.tcp_tw_reuse=1
   # → net.ipv4.tcp_tw_reuse = 1
   ```
   *Параметр `tcp_tw_reuse=1` безопасен для исходящих клиентских подключений веб-сервера согласно RFC 1323 (при активных TCP timestamps).*

2. **Включение HTTP Keepalive в блоке upstream веб-сервера (Nginx/Angie):**
   ```nginx
   upstream backend_pool {
       server 127.0.0.1:9000;
       keepalive 64; # Пул открытых постоянных соединений к upstream
   }

   server {
       location / {
           proxy_pass http://backend_pool;
           proxy_http_version 1.1;
           proxy_set_header Connection ""; # Очистка заголовка Close
       }
   }
   ```
   Подробнее об архитектуре пулов: [Пул соединений и Keepalive к upstream](./web_performance/upstream_keepalive_and_pooling.md).

### Сценарий 4: Лимиты файловых дескрипторов (Too many open files)

В ОС Linux сетевой сокет, открытый файл на диске, пайп и сокет межпроцессного взаимодействия являются файловыми дескрипторами (FD). При исчерпании лимита воркер не может принять новое TCP-соединение и аварийно фиксирует:
`accept4() failed (24: Too many open files)`.

**Диагностика:**

```bash
# 1. Проверка лимитов работающего процесса воркера Nginx
WORKER_PID=$(pgrep -n -f "nginx: worker process")
cat /proc/${WORKER_PID}/limits | grep "Max open files"
# → Max open files            1024                 1024                 files

# 2. Подсчет фактически открытых дескрипторов воркером
ls -1 /proc/${WORKER_PID}/fd | wc -l
# → 1023
```
*Интерпретация:* Лимит процесса составляет 1024 дескриптора, при этом 1023 дескриптора уже заняты. Процесс исчерпал квоту.

**Решение:**
Для веб-сервера лимит должен быть увеличен как на уровне менеджера служб systemd, так и в конфигурации самого сервера:

1. **В конфигурации systemd (`/etc/systemd/system/nginx.service.d/override.conf`):**
   ```ini
   [Service]
   LimitNOFILE=65535
   ```
   Применение:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart nginx
   ```

2. **В конфигурации Nginx (`/etc/nginx/nginx.conf` в глобальном контексте):**
   ```nginx
   worker_rlimit_nofile 65535;
   events {
       worker_connections 16384; # Должно быть меньше worker_rlimit_nofile
   }
   ```

### Сценарий 5: Анализ оперативной памяти, swap и событий OOM-killer

Внезапное исчезновение процессов воркеров или периодический отказ в обработке запросов часто связаны с принудительным завершением процессов механизмом Out of Memory (OOM) Killer ядра Linux.

**Диагностика:**

```bash
# 1. Проверка доступной оперативной памяти и использования swap
free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:           15Gi        14Gi       210Mi       1.2Gi       1.1Gi       450Mi
# → Swap:         2.0Gi       1.9Gi        98Mi

# 2. Проверка интенсивности свопинга (si - swap in, so - swap out)
vmstat 1 3
# → procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
# →  r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
# →  4  1 201200 215040  45120 114520  420  890  1200  1800 4500 8200 35 25 20 20  0
```
*Интерпретация:* Поле `available` составляет всего 450 МБ, при этом `so` (swap out) показывает непрерывную запись на диск, а процент `wa` (iowait) достигает 20%. Система находится в состоянии тяжелого дефицита памяти (thrashing).

**Поиск следов OOM Killer в системных логах:**

```bash
# Поиск события OOM в dmesg
sudo dmesg -T | grep -i -E "oom[- ]killer|killed process"
# → [Wed Oct 14 15:30:12 2026] Out of memory: Killed process 4125 (php-fpm) total-vm:498212kB, anon-rss:312500kB, file-rss:120kB, shmem-rss:0kB, UID:33 pgtables:1024kB oom_score_adj:0

# Анализ через journalctl (для systemd)
sudo journalctl -k --since "-1 hour" -g "killed process"
# → Oct 14 15:30:12 srv-web kernel: Memory cgroup out of memory: Killed process 4125 (php-fpm)...
```
Подробнее об анализе и настройке весов: [Диагностика OOM Killer в Linux](../../Linux/Core/processes/oom_killer_diagnostics.md).

### Сценарий 6: Проблемы дисковой подсистемы: свободное место, Inodes и дескрипторы удаленных файлов

Веб-сервер не может функционировать без возможности записи во временные каталоги (`client_body_temp`, `proxy_temp`) и файлы журналов.

**1. Проверка объема диска и свободных индексных дескрипторов (inodes):**

```bash
# Проверка свободного места на разделах
df -h /var/log /tmp
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1        40G   39G  200M 100% /

# Проверка свободных inodes
df -i /var/log /tmp
# → Filesystem       Inodes   IUsed   IFree IUse% Mounted on
# → /dev/sda1       2621440 2621400      40  100% /
```
*Интерпретация:* Если `df -h` показывает свободное место, но `df -i` фиксирует 100% `IUse%`, создание любых новых файлов блокируется с ошибкой `No space left on device`. Это характерно при накоплении миллионов мелких файлов сессий PHP или буферов проксирования.

**2. Расхождение между `df` и `du` (удерживаемые удаленные файлы):**
Если администратор удалил лог-файл командой `rm /var/log/nginx/access.log`, но веб-сервер не был оповещен о ротации, место на диске не освобождается, так как процесс удерживает открытый файловый дескриптор.

```bash
# Поиск файлов, удаленных из файловой системы, но удерживаемых процессами
sudo lsof +L1
# → COMMAND   PID   USER   FD   TYPE DEVICE   SIZE/OFF NLINK   NAME
# → nginx   14210   root    7w   REG    8,1 15728640000     0 /var/log/nginx/access.log (deleted)
```
*Решение:*
Освободить место немедленно без остановки сервиса можно обнулением файла через дескриптор в `/proc`:
```bash
# Обнуление удаленного файла через procfs (FD 7 процесса 14210)
sudo truncate -s 0 /proc/14210/fd/7
# Перечитывание логов веб-сервером
sudo nginx -s reopen
```
Подробнее: [Диагностика дискового пространства](../../Linux/FileSystems/disk_space_troubleshooting.md).

### Сценарий 7: Права доступа на ФС и политики безопасности SELinux/AppArmor (403 Forbidden)

Ошибка `403 Forbidden` возникает, когда веб-сервер нашел запрашиваемый ресурс, но операционная система или модуль безопасности запрещают его чтение.

**1. Проверка прав дискреционного доступа (POSIX DAC):**
Для чтения файла веб-сервер должен обладать правом `r` на целевой файл и правом `x` (выполнение/проход) на **все** родительские директории в пути:

```bash
# Проверка прав по всей цепочке директорий до DocumentRoot
namei -l /var/www/myproject/public/index.html
# → f: /var/www/myproject/public/index.html
# → drwxr-xr-x root     root     /
# → drwxr-xr-x root     root     var
# → drwxr-xr-x www-data www-data www
# → drwxr-x--- deploy   deploy   myproject       <-- ОШИБКА: нет 'x' для остальных пользователей!
# → drwxr-xr-x deploy   deploy   public
# → -rw-r--r-- deploy   deploy   index.html
```
*Решение:* Предоставить право прохода группе или другим пользователям: `sudo chmod o+x /var/www/myproject`.

**2. Проверка мандатного контроля доступа SELinux:**
Если права POSIX корректны (`chmod 644`), но отдается 403, проверьте контекст безопасности SELinux:

```bash
# Проверка текущего режима SELinux
getenforce
# → Enforcing

# Проверка контекста безопасности файла
ls -lZ /var/www/myproject/public/index.html
# → -rw-r--r--. 1 www-data www-data unconfined_u:object_r:user_home_t:s0 index.html
```
*Контекст `user_home_t` запрещает чтение веб-серверу (ожидается `httpd_sys_content_t`).*

**Анализ логов аудита и исправление:**
```bash
# Поиск блокировок веб-сервера за последние 10 минут
sudo ausearch -m avc -ts recent | audit2why
# → type=AVC msg=audit(...): avc:  denied  { read } for  pid=2150 comm="nginx" name="index.html" ...
# → Was caused by: Missing or invalid context.
# → Suggestion: restorecon -R -v /var/www/myproject

# Восстановление эталонного контекста
sudo restorecon -Rv /var/www/myproject
# → Relabeled /var/www/myproject/public/index.html from ...:user_home_t:... to ...:httpd_sys_content_t:...
```

**Сетевые подключения в SELinux (для Reverse Proxy):**
Если Nginx в режиме прокси возвращает 502/13: Permission denied при попытке подключиться к бэкенду по TCP:
```bash
# Разрешение веб-серверу устанавливать исходящие сетевые соединения
sudo setsebool -P httpd_can_network_connect 1
```

### Сценарий 8: Диагностика обратного проксирования и upstream-сервисов (502 / 504 / 499)

Ошибки серии 5xx в архитектуре обратного прокси требуют строгого разделения: сбой произошел в самом веб-сервере или в приложении за ним.

```text
[ Клиент ] ──(HTTP)──> [ Nginx/Angie ] ──(Proxy/FastCGI)──> [ Upstream App ]
                             │
       ┌─────────────────────┴─────────────────────┐
       ▼                                           ▼
 502 Bad Gateway                             504 Gateway Timeout
 - Бэкенд не запущен                         - Бэкенд принял запрос, но не
 - Сокет отклонил connect (ECONNREFUSED)       успел ответить за proxy_read_timeout
 - Приложение упало во время ответа (RST)    - Дедлок в БД, блокирующий I/O
 - Неверный протокол / битые заголовки       - Долгий тяжелый расчет без буферизации
```

**1. Проверка доступности upstream-сокета:**

```bash
# Если используется TCP-сокет (например, 127.0.0.1:8000)
ss -ltnp 'sport = :8000'
# → LISTEN 0 128 127.0.0.1:8000 0.0.0.0:* users:(("python3",pid=8120,fd=3))

# Прямой HTTP-запрос к бэкенду в обход Nginx
curl -v --max-time 5 http://127.0.0.1:8000/health -H 'Host: example.com'
# → < HTTP/1.1 200 OK
# → < Content-Type: application/json
# → {"status":"healthy"}
```

**2. Если используется Unix Domain Socket (например, `/run/php/php-fpm.sock`):**
```bash
# Проверка существования сокета и прав доступа
ls -la /run/php/php-fpm.sock
# → srw-rw---- 1 www-data www-data 0 Oct 14 10:00 /run/php/php-fpm.sock

# Проверка очереди подключений Unix-сокета
ss -axl | grep "php-fpm.sock"
# → u_str LISTEN 150 128 /run/php/php-fpm.sock 12345 * 0
```
*Если `Send-Q` (128) превышена значением `Recv-Q` (150), пул PHP-FPM исчерпан (`pm.max_children`), и новые запросы отклоняются с кодом 502.*

**3. Анализ кода 499 (Client Closed Request):**
Код 499 специфичен для Nginx/Angie: клиент закрыл TCP-соединение до того, как веб-сервер успел передать ему ответ от upstream.
- Если в логах одновременно растут 499 и `upstream_response_time`: приложение работает медленно, клиент (браузер или мобильное приложение) обрывает соединение по собственному таймауту.
- Решение: профилировать запросы бэкенда, не увеличивать бездумно `proxy_read_timeout`.

### Сценарий 9: Проверка TLS-цепочки, сертификатов и SNI

Ошибки `SSL_ERROR_RX_RECORD_TOO_LONG`, `certificate verify failed` или периодические сбои мобильных клиентов при корректной работе десктопных браузеров связаны с неполной цепочкой сертификатов (отсутствием Intermediate CA).

**Диагностика через OpenSSL CLI:**

```bash
# Комплексная проверка TLS-соединения с эмуляцией SNI и валидацией цепочки
openssl s_client \
  -connect 203.0.113.10:443 \
  -servername example.com \
  -verify_hostname example.com \
  -verify_return_error \
  -brief </dev/null
# → CONNECTION ESTABLISHED
# → Protocol : TLSv1.3
# → Cipher : TLS_AES_256_GCM_SHA384
# → Verification: OK
```
*Если верификация провалена:*
```text
# → Verification error: unable to get local issuer certificate
```
*Причина:* В директиве `ssl_certificate` указан только сертификат домена (`cert.pem`), а не полная цепочка (`fullchain.pem`). Десктопный браузер может иметь промежуточный сертификат в локальном кэше, но curl, микросервисы и мобильные клиенты завершат сессию ошибкой.

**Проверка срока действия локального сертификата на диске:**

```bash
openssl x509 -in /etc/ssl/certs/example.com.crt -noout -dates -subject -issuer
# → notBefore=Aug 15 00:00:00 2026 GMT
# → notAfter=Nov 13 23:59:59 2026 GMT
# → subject=CN = example.com
# → issuer=C = US, O = Let's Encrypt, CN = R3
```

Подробнее об устранении неполадок шифрования: [Диагностика TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md).

### Сценарий 10: Локализация сетевых аномалий и файрвола (локально работает, снаружи нет)

Случай: curl на `127.0.0.1` внутри сервера отдает `200 OK`, но внешние клиенты получают `Connection timed out` или `Connection refused`.

**1. Проверка привязки адреса сокетом (Bind Interface):**

```bash
ss -ltnp 'sport = :443'
# → LISTEN 0 511 127.0.0.1:443 0.0.0.0:* users:(("nginx",pid=1234,fd=6))
```
*Ошибка:* Сокет привязан исключительно к loopback-интерфейсу `127.0.0.1:443`, вместо `0.0.0.0:443` или внешнего IP. Внешние пакеты отклоняются ядром.

**2. Инспекция пакетного фильтра Linux:**

```bash
# nftables: проверка активного набора правил
sudo nft list ruleset | grep -A 5 -B 2 "443"
# → chain input {
# →     type filter hook input priority filter; policy drop;
# →     tcp dport 443 accept
# → }

# iptables: проверка сброшенных пакетов по счетчикам
sudo iptables -L INPUT -v -n | grep -E "dpt:80|dpt:443|DROP"
# →  1420 85200 ACCEPT  tcp  --  *  *  0.0.0.0/0  0.0.0.0/0  tcp dpt:443
# → 54100 2705K DROP    all  --  *  *  0.0.0.0/0  0.0.0.0/0
```

**3. Инспекция блокировок Fail2ban:**
```bash
sudo fail2ban-client status nginx-http-auth
# → Status for the jail: nginx-http-auth
# → |- Filter
# → |  |- Currently failed: 0
# → |  `- Total failed:     45
# → `- Actions
# →    |- Currently banned: 1
# →    `- Banned IP list:   198.51.100.25
```

**4. Захват пакетов на сетевом интерфейсе (tcpdump):**
Для доказательства поступления трафика на сервер запустите захват параллельно с внешним клиентским запросом:

```bash
sudo tcpdump -ni any 'tcp port 443' -c 10 -nn
# → 15:00:01.120 IP 198.51.100.25.54120 > 203.0.113.10.443: Flags [S], seq 124510
# → 15:00:01.120 IP 203.0.113.10.443 > 198.51.100.25.54120: Flags [S.], seq 854120, ack 124511
# → 15:00:01.145 IP 198.51.100.25.54120 > 203.0.113.10.443: Flags [.], ack 1
```
*Интерпретация:*
- Есть `Flags [S]`, но нет ответа `[S.]`: пакет блокируется локальным файрволом хоста, либо очередь сокета переполнена.
- Нет ни одного входящего пакета `Flags [S]`: проблема во внешней сети, маршрутизации провайдера, сетевом экране дата-центра или некорректном DNS.

### Сценарий 11: Сбои после перезагрузки ОС (Post-reboot failures)

Если после планового или аварийного ребута хоста веб-сервер находится в состоянии `failed` или `inactive`:

**1. Проверка включения сервиса в автозагрузку systemd:**

```bash
systemctl is-enabled nginx
# → disabled

# Включение службы в автозагрузку
sudo systemctl enable nginx
# → Created symlink /etc/systemd/system/multi-user.target.wants/nginx.service → /lib/systemd/system/nginx.service.
```

**2. Анализ сбоя запуска через systemd journal:**

```bash
# Просмотр логов юнита с момента последней загрузки
sudo journalctl -u nginx -b 0 --no-pager
# → Oct 14 06:00:15 srv-web nginx[910]: nginx: [emerg] bind() to 203.0.113.10:443 failed (99: Cannot assign requested address)
# → Oct 14 06:00:15 srv-web systemd[1]: nginx.service: Control process exited, code=exited, status=1/FAILURE
```
*Причина:* Веб-сервер настроен слушать конкретный внешний IP-адрес (`listen 203.0.113.10:443;`), но стартует раньше, чем сетевой интерфейс успевает получить адрес по DHCP или инициализироваться сетевым демоном.

**Решение проблемы привязки IP (два способа):**
- Способ А (системный): разрешить процессам биндиться на несуществующие/неподнятые адреса в ядре Linux:
  ```bash
  sudo sysctl -w net.ipv4.ip_nonlocal_bind=1
  # → net.ipv4.ip_nonlocal_bind = 1
  ```
- Способ Б (systemd): настроить зависимость в unit-файле (`/etc/systemd/system/nginx.service.d/override.conf`):
  ```ini
  [Unit]
  After=network-online.target
  Wants=network-online.target
  ```

---

## Операции и команды

### Управление службами и инспекция systemd

| Команда | Назначение | Пример ожидаемого вывода (`# → result`) |
| :--- | :--- | :--- |
| `sudo nginx -t` | Синтаксическая проверка конфига Nginx/Angie | `# → syntax is ok && test is successful` |
| `sudo apachectl configtest` | Синтаксическая проверка конфига Apache | `# → Syntax OK` |
| `sudo haproxy -c -f /etc/haproxy/haproxy.cfg` | Валидация конфигурации HAProxy | `# → Configuration file is valid` |
| `sudo systemctl status nginx` | Проверка текущего статуса службы, PID и последних событий | `# → Active: active (running) since ...` |
| `sudo systemctl reload nginx` | Graceful reload без обрыва пользовательских сессий (`SIGHUP`) | `# → без вывода (код возврата 0)` |
| `sudo systemctl restart nginx` | Полный перезапуск сервиса (остановка и новый старт) | `# → без вывода (код возврата 0)` |
| `systemctl is-enabled nginx` | Проверка регистрации юнита в автозагрузке | `# → enabled` / `# → disabled` |
| `systemd-analyze critical-chain nginx.service` | Анализ задержек цепочки загрузки сервиса | `# → nginx.service +120ms (network-online.target @3.1s)` |

### Сетевая диагностика и сокеты

| Команда | Назначение | Пример ожидаемого вывода (`# → result`) |
| :--- | :--- | :--- |
| `ss -lntp 'sport = :443'` | Проверка процесса, слушающего TCP-порт 443 | `# → LISTEN 0 511 0.0.0.0:443 users:(("nginx",pid=1234,fd=6))` |
| `ss -s` | Сводная статистика сокетов стека ядра | `# → Total: 1250 TCP: 1450 (estab 85, closed 1200)` |
| `ss -tan state time-wait \| wc -l` | Подсчет количества сокетов в `TIME_WAIT` | `# → 14520` |
| `lsof -i TCP:80` | Список процессов и дескрипторов на 80 порту | `# → nginx 1234 root 6u IPv4 2514 TCP *:http (LISTEN)` |
| `tcpdump -ni any 'tcp port 80 or tcp port 443' -c 5` | Захват первых 5 сетевых пакетов HTTP/HTTPS | `# → IP 198.51.100.1.5120 > 203.0.113.10.443: Flags [S]` |
| `curl -v --resolve example.com:443:127.0.0.1 https://example.com/` | Локальный HTTPS-запрос с сохранением SNI и Host | `# → < HTTP/2 200` |
| `openssl s_client -connect 127.0.0.1:443 -servername example.com -brief </dev/null` | Проверка TLS-рукопожатия и сертификата | `# → Verification: OK, Protocol: TLSv1.3` |

### Анализ логов веб-серверов

| Команда | Назначение | Пример ожидаемого вывода (`# → result`) |
| :--- | :--- | :--- |
| `journalctl -u nginx --since "-30m" --no-pager` | Логи systemd сервиса за последние 30 минут | `# → Хронологический вывод сообщений stdout/stderr` |
| `journalctl -u nginx -p err --no-pager` | Фильтр логов сервиса только по уровню ошибок (`err`/`crit`) | `# → Строки ошибок конфигурации и воркеров` |
| `tail -n 100 /var/log/nginx/error.log` | Последние 100 строк лога ошибок веб-сервера | `# → [error] 1234#0: *502 connect() failed ...` |
| `awk '{print $9}' access.log \| sort \| uniq -c \| sort -rn \| head -5` | Топ-5 HTTP-кодов ответов в access-логе | `# → 15200 200, 840 404, 120 502, 45 504, 10 500` |
| `awk '($9 ~ /50[234]/) {print $7}' access.log \| sort \| uniq -c \| sort -rn \| head -5` | Топ URL, вызывающих ошибки 502/503/504 | `# → 85 /api/v1/checkout, 35 /search` |
| `grep "upstream timed out" /var/log/nginx/error.log \| tail -5` | Поиск таймаутов проксирования к бэкенду | `# → [error] ... upstream timed out (110: Connection timed out)` |

### Мониторинг системных ресурсов и профилирование процессов

| Команда | Назначение | Пример ожидаемого вывода (`# → result`) |
| :--- | :--- | :--- |
| `free -h` | Проверка RAM (ключевой показатель — `available`) | `# → Mem: 15Gi used 4Gi available 10Gi` |
| `vmstat 1 3` | Анализ очередей планировщика, свопинга (`si`/`so`) и CPU | `# → r b swpd free si so us sy id wa` |
| `iostat -xz 1 3` | Расширенная статистика утилизации дисков (`%util`, `await`) | `# → Device r/s w/s rMB/s wMB/s await %util` |
| `df -h && df -i` | Проверка дискового пространства и свободных inodes | `# → Use% 45%, IUse% 12%` |
| `lsof +L1` | Поиск удаленных файлов, занимающих место на диске | `# → nginx 1420 7w REG 8,1 15G 0 /var/log/access.log (deleted)` |
| `cat /proc/$(pgrep -n -f "nginx: worker")/limits \| grep "Max open files"` | Проверка лимитов файловых дескрипторов воркера | `# → Max open files 65535 65535 files` |
| `strace -p PID -e trace=network,file -s 128` | Трассировка сетевых и файловых системных вызовов процесса | `# → connect(8, {sa_family=AF_INET...}, 16) = -1 EINPROGRESS` |

---

## Устранение неисправностей

### Типовые ошибки HTTP 4xx

#### 400 Bad Request
- **Причины:** Заголовок запроса превышает размер буфера сервера (`client_header_buffer_size`, `large_client_header_buffers`); синтаксическая ошибка в HTTP-запросе; недопустимые символы в URI; отправка HTTP-запроса на порт, ожидающий HTTPS.
- **Диагностика:** Поиск в `error.log` строк `client sent invalid request`, `client sent too long header line` или `client sent plain HTTP request to HTTPS port`.
- **Решение:** Для длинных cookie или токенов авторизации увеличьте буферы:
  ```nginx
  client_header_buffer_size 4k;
  large_client_header_buffers 4 16k;
  ```

#### 403 Forbidden
- **Причины:**
  1. Отсутствие прав чтения на файл (`chmod`) или прав исполнения на родительские каталоги для пользователя воркера (`nginx`, `www-data`, `apache`).
  2. Запрет на уровне конфигурации: директивы `deny all`, `Require all denied`.
  3. Отсутствие индексного файла (`index.html`, `index.php`) при отключенном автоиндексе (`autoindex off`).
  4. Блокировка подсистемой SELinux (неверный контекст файла `httpd_sys_content_t`) или профилем AppArmor.
- **Диагностика:**
  ```bash
  # Проверка прав доступа по всему пути
  namei -l /var/www/site/index.html
  # Проверка аудита безопасности
  sudo ausearch -m avc -ts recent
  ```
- **Решение:** Выставить права `chmod o+x` на каталоги; запустить `restorecon -Rv /var/www/site`.

#### 404 Not Found
- **Причины:** Запрашиваемый файл отсутствует на диске; опечатка в директиве `root` или некорректная склейка путей директивой `alias`; запрос попал в дефолтный виртуальный хост из-за отсутствия нужного `server_name`.
- **Диагностика:** Сравнить реальный путь на диске с логом:
  `grep "open() failed (2: No such file or directory)" /var/log/nginx/error.log`
- **Решение:** Проверить правильность слешей в `alias` (в Nginx `location /images/ { alias /data/images/; }` требует замыкающего слеша в обоих параметрах).

#### 413 Payload Too Large
- **Причины:** Размер тела запроса (загружаемого файла) превышает лимит сервера (`client_max_body_size` в Nginx/Angie, `LimitRequestBody` в Apache).
- **Решение:** Задать допустимый лимит в соответствующем блоке `location` или `server`:
  ```nginx
  client_max_body_size 64M;
  ```

#### 499 Client Closed Request
- **Причины:** Клиент оборвал соединение до завершения обработки запроса сервером. В 95% случаев вызвано медленной обработкой запроса на бэкенде, превышающей клиентский таймаут приложения или JS-фреймворка.
- **Диагностика:** Проверить время ответа бэкенда в access-логе: `$upstream_response_time`.
- **Решение:** Оптимизировать запросы к БД и логику бэкенда; проверить очереди upstream.

### Типовые ошибки HTTP 5xx

#### 500 Internal Server Error
- **Причины:** Фатальная ошибка в скрипте приложения (если сервер совмещен, например mod_php); сбой в синтаксисе децентрализованного файла `.htaccess` (в Apache); зацикливание внутренних перенаправлений (`rewrite` loop или некорректный `try_files`).
- **Диагностика:**
  ```bash
  grep -E "rewrite or internal redirection cycle|alert" /var/log/nginx/error.log
  ```
- **Решение:** Исправить зацикленный `try_files $uri $uri/ /index.php?$args;`; в Apache проверить директивы `.htaccess`.

#### 502 Bad Gateway
- **Причины:**
  1. Upstream-сервер выключен, упал или не слушает целевой порт (`ECONNREFUSED`).
  2. Падение процесса приложения во время отправки ответа (Segmentation fault, OOM Killer).
  3. Размер заголовков ответа upstream превышает буфер веб-сервера (`upstream sent too big header`).
  4. SELinux блокирует сетевое соединение с бэкендом.
- **Диагностика:**
  ```bash
  # В error.log веб-сервера:
  # "connect() failed (111: Connection refused) while connecting to upstream"
  # "upstream prematurely closed connection while reading response header"
  ```
- **Решение:**
  - Если приложение живо, но заголовки велики (тяжелые cookie / JWT):
    ```nginx
    proxy_buffer_size 128k;
    proxy_buffers 4 256k;
    proxy_busy_buffers_size 256k;
    ```
  - Включить булеву переменную SELinux: `setsebool -P httpd_can_network_connect 1`.

#### 503 Service Unavailable
- **Причины:** Превышение лимитов частоты запросов или соединений (`limit_req`, `limit_conn`); все бэкенды в группе upstream помечены как неработающие (down/failed); включен регламентный режим обслуживания (Maintenance mode).
- **Диагностика:**
  ```bash
  grep -E "limiting requests|no live upstreams" /var/log/nginx/error.log
  ```
- **Решение:** Скорректировать зоны `limit_req_zone` (параметр `burst` и флаг `nodelay`); восстановить работоспособность upstream-серверов.

#### 504 Gateway Timeout
- **Причины:** Upstream-сервер принял соединение, но не вернул ответ в пределах отведенного окна таймаута (`proxy_read_timeout`, `fastcgi_read_timeout`). Вызывается зависанием долгих SQL-запросов, внешних API или нехваткой воркеров бэкенда.
- **Диагностика:**
  ```bash
  grep "upstream timed out" /var/log/nginx/error.log
  ```
- **Решение:** Проверить список активных запросов на бэкенде и блокировки в БД (`SHOW FULL PROCESSLIST` в MySQL, `pg_stat_activity` в PostgreSQL). Временное увеличение таймаута для тяжелых отчетов:
  ```nginx
  proxy_read_timeout 120s;
  ```

### Сетевые сбои транспортного уровня

#### Connection refused
- **Причина:** На указанном адресе и порту нет слушающего сокета в ядре Linux, либо порт блокируется пакетным фильтром с правилом `REJECT --reject-with tcp-reset`.
- **Диагностика:**
  ```bash
  ss -ltn 'sport = :443'
  ```
  Если сокет отсутствует — проверить статус демона: `systemctl status nginx`.

#### Connection timed out
- **Причина:** Пакетный фильтр хоста (`nftables`/`iptables`) отбрасывает пакеты (`DROP`); переполнена таблица состояний файрвола `conntrack`; проблемы асимметричной маршрутизации.
- **Диагностика:**
  ```bash
  # Проверка заполнения таблицы conntrack
  cat /proc/sys/net/netfilter/nf_conntrack_count
  cat /proc/sys/net/netfilter/nf_conntrack_max
  dmesg | grep "nf_conntrack: table full"
  ```
- **Решение:** Увеличить размер таблицы состояний:
  ```bash
  sudo sysctl -w net.netfilter.nf_conntrack_max=262144
  ```

---

## Лучшие практики

### Организация безопасных изменений и откат конфигурации

- **Атомарная валидация перед перезагрузкой:** Ни при каких обстоятельствах не выполняйте `reload` или `restart` без предварительного вызова валидатора (`nginx -t`, `apachectl configtest`). Автоматизируйте это в CI/CD и Makefile/скриптах деплоя:
  ```bash
  sudo nginx -t && sudo systemctl reload nginx
  ```
- **Версионирование конфигурации:** Директория `/etc/nginx` (или `/etc/apache2`) должна находиться под управлением локального Git-репозитория (`etckeeper` или выделенный `git init`). Это обеспечивает мгновенный аудит изменений и возможность отката:
  ```bash
  sudo git diff
  sudo git checkout -- /etc/nginx/conf.d/site.conf
  ```
- **Приоритет `reload` над `restart`:** Изменение конфигурации, добавление виртуальных хостов и обновление TLS-сертификатов применяются исключительно через `reload` (`SIGHUP`). Это исключает сброс сокетов в `ECONNREFUSED` и гарантирует непрерывность обслуживания активных соединений.

### Эксплуатационные стандарты SRE

- **Внедрение Runbook'ов инцидентов:** Для каждого класса критических алертов (рост кодов 5xx выше 1%, рост задержки p99 выше 500мс, свободное место на диске менее 10%) инженерная команда должна иметь готовый регламент локализации.
  Подробнее: [Runbooks и Incident Response для веб-серверов](./runbooks_incident_response.md).
- **Разделение дисковых пулов для логов:** Каталог журналов `/var/log` должен монтироваться на отдельный логический том (LVM/диск), изолированный от корневой файловой системы `/`. Переполнение диска логами не должно приводить к краху всей операционной системы.
- **Корректная ротация логов:** При использовании `logrotate` файл не должен удаляться без оповещения сервера. Используйте скрипт с отправкой сигнала `USR1`:
  ```text
  /var/log/nginx/*.log {
      daily
      missingok
      rotate 14
      compress
      delaycompress
      notifempty
      create 0640 www-data adm
      sharedscripts
      postrotate
          [ -f /run/nginx.pid ] && kill -USR1 $(cat /run/nginx.pid)
      endscript
  }
  ```

### Стандарты безопасности и изоляции

- **Принцип наименьших привилегий воркеров:** Master-процесс запускается от `root` исключительно для привязки к портам 80/443 и открытия дескрипторов логов. Worker-процессы обязаны работать под непривилегированным пользователем (`nginx`, `www-data`, `apache`).
- **Соблюдение политик SELinux/AppArmor:** Категорически запрещается отключать SELinux (`setenforce 0`) в production-среде для устранения ошибок 403 или 502. Корректный подход — настройка контекстов (`restorecon`) и переключение разрешающих флагов (`setsebool -P httpd_can_network_connect 1`).
- **Изоляция административных страниц:** Служебные эндпоинты (`/nginx_status`, `/server-status`) должны быть жестко ограничены доступом только с доверенных IP-адресов мониторинга или локального сокета:
  ```nginx
  location = /stub_status {
      stub_status;
      allow 127.0.0.1;
      allow 10.0.0.0/8;
      deny all;
  }
  ```

### Чек-лист валидации после устранения аварии (Post-Fix Checklist)

1. **Проверка синтаксиса и перезагрузка:** Выполнен `nginx -t` и `systemctl reload nginx`.
2. **Проверка слушающих сокетов:** Команда `ss -lntp` подтверждает, что порты 80 и 443 слушаются нужным процессом на всех требуемых интерфейсах.
3. **Локальная верификация:** Запрос `curl -v -H "Host: domain" http://127.0.0.1/` возвращает ожидаемый HTTP-код.
4. **Внешняя сквозная верификация:** Внешний запрос `curl -v https://domain/health` подтверждает корректность DNS, TLS-сертификата и доступность upstream-бэкенда.
5. **Проверка логов ошибок:** Команда `tail -n 50 /var/log/nginx/error.log` не регистрирует новых сообщений `[emerg]`, `[alert]` или `[error]`.
6. **Контроль системных очередей:** Вывод `ss -lnt` фиксирует `Recv-Q = 0` на слушающих сокетах.

---

## Дополнительная информация

### См. также

- **[Диагностика и устранение неисправностей Nginx](../Nginx/Operations/nginx_troubleshooting.md)** — Nginx-специфичные директивы, отладка воркеров и детальный разбор error.log.
- **[Apache HTTP Server 2.4+ (Обзор)](../Apache/apache_overview.md)** — архитектура модулей MPM (event, worker, prefork) и диагностика директив virtual hosts.
- **[Runbooks и Incident Response для веб-серверов](./runbooks_incident_response.md)** — готовые SRE-регламенты реагирования на массовые инциденты (502/504, OOM, переполнение диска).
- **[Диагностика TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — матрица совместимости шифронаборов и решение проблем рукопожатия.
- **[Диагностика SSL-сертификатов](../../Security/Tools/ssl_certificate_diagnostics.md)** — углубленный анализ сертификатов с помощью OpenSSL.
- **[Диагностика дискового пространства](../../Linux/FileSystems/disk_space_troubleshooting.md)** — методы обнаружения утечек места, inodes и освобождения удаленных дескрипторов.
- **[Диагностика OOM Killer в Linux](../../Linux/Core/processes/oom_killer_diagnostics.md)** — глубокий анализ логов ядра, cgroups v2 и настройка oom_score_adj.
- **[Общая методология диагностики сервисов](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md)** — общесистемные методы поиска неисправностей в Linux.
- **[Коды состояния HTTP](../../Networking/Protocols/HTTP/http_status_codes.md)** — семантика и стандарты статусных кодов согласно RFC 9110.
- **[Логирование веб-серверов](./webserver_logging.md)** — настройка структурированных логов, сбор метрик задержек и аудит.
