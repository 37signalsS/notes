# Модуль image_filter в Angie: производительность и масштабирование

**Актуально для:** Angie 1.12.x

## Определения

**Производительность image_filter** — комплексная характеристика эффективности динамической обработки медиаконтента, определяемая временем задержки (Latency/TTFB/TTLB) на операцию трансформации и совокупной пропускной способностью (Throughput, RPS) системы при контролируемых ограничениях вычислительных ресурсов (CPU, RAM, Disk I/O).

**Синхронный конвейер трансформации (Synchronous Transformation Pipeline)** — механизм выполнения `ngx_http_image_filter_module`, при котором декодирование исходного сжатого файла, манипуляции с несжатой пиксельной матрицей в библиотеке `libgd` и кодирование в целевой формат выполняются синхронно в контексте рабочего процесса (worker process). В процессе трансформации рабочий процесс полностью блокирует свой цикл событий (`epoll event loop`), не обрабатывая сетевые события других клиентских соединений на данном воркере.

**Буфер чтения оригинала (`image_filter_buffer`)** — максимальный объем оперативной памяти, выделяемый воркером Angie для считывания сырого сжатого файла из хранилища или апстрима перед передачей декодеру `libgd`. Если размер входящего файла превышает этот лимит, обработка прерывается с возвратом HTTP `415 Unsupported Media Type`.

**Рабочий набор памяти (Memory Footprint / RSS)** — совокупный объем оперативной памяти, аллоцируемый процессом при выполнении трансформации. Складывается из памяти `image_filter_buffer`, промежуточной несжатой RGBA-матрицы в `libgd` (`Ширина × Высота × 4 байта`), буфера масштабированного изображения и рабочих буферов кодеков (`libavif`, `libwebp`).

**Tail Latency (P95/P99)** — перцентили времени отклика системы, отражающие worst-case сценарии. В задачах обработки изображений P95/P99 критически чувствительны к типу кодека: ресурсоемкое кодирование AVIF способно вызвать всплеск задержки до сотен миллисекунд и заблокировать воркер.

**Насыщение (Saturation)** — состояние вычислительной подсистемы, при котором дальнейший рост входящей нагрузки не увеличивает фактический RPS, а приводит к лавинообразному росту глубины очередей сокетов (`listen backlog`), задержки планировщика ядра ОС (`CFS runqueue latency`) и возрастанию таймаутов (HTTP 504 Gateway Timeout).

**Head-of-Line Blocking (HOL)** — явление блокировки очереди, при котором медленный запрос (например, кодирование AVIF высокого разрешения длительностью 150 мс) задерживает обработку последующих мультиплексированных запросов в рамках одного воркера или HTTP/2-соединения.

**Двухуровневое проксирование (Double Proxying)** — архитектурный паттерн High Load, разделяющий конвейер на внешний фронтенд (SSL-терминация, неблокирующий `proxy_cache`, согласование формата `Accept`, отдача статики) и изолированный внутренний бэкенд трансформации (выделенный пул воркеров с `image_filter`), связанный через Unix Domain Socket или локальный loopback.

**Защита от эффекта стада (Thundering Herd / Cache Stampede)** — предотвращение параллельного запуска одинаковых тяжелых вычислений при промахе кэша (MISS) с помощью директив синхронизации `proxy_cache_lock` и отдачи устаревшего контента `proxy_cache_use_stale updating`.

**Прогрев кэша (Cache Warmup)** — контролируемый регламентный процесс генерации и сохранения в кэш наиболее востребованных размеров и форматов изображений до поступления пользовательского трафика, исключающий деградацию производительности при холодном старте.

---

## Базовые концепции

### Механика выполнения и блокировка event loop

Модуль `ngx_http_image_filter_module` принципиально отличается от стандартных модулей Angie:
1. Стандартная отдача статических файлов работает в неблокирующем асинхронном режиме через системный вызов `sendfile()` с минимальным расходом CPU и нулевым копированием (Zero-Copy).
2. Модуль `image_filter` является фильтром тела ответа (`body filter`). Он аккумулирует весь файл в `image_filter_buffer`, затем вызывает C-библиотеку `libgd`, которая выполняет распаковку, билинейное или бикубическое масштабирование и последующее сжатие в JPEG, WebP или AVIF.

```
Входящий запрос → epoll → чтение оригинала в image_filter_buffer
                                  │
                                  ▼
                     [БЛОКИРОВКА EVENT LOOP ВОРКЕРА]
                     ├── libgd: декодирование в RGBA (CPU/RAM)
                     ├── libgd: gdImageCopyResampled (CPU)
                     ├── libavif / libwebp: сжатие (CPU)
                                  │
                                  ▼
                     [РАЗБЛОКИРОВКА EVENT LOOP]
                                  │
                                  ▼
                     Отправка готового файла клиенту
```

> [!WARNING]
> Пока воркер занят кодированием изображения, его цикл событий `epoll` полностью остановлен. Воркер не может принимать новые TCP-соединения, обрабатывать TLS-хэндшейки или передавать данные по уже открытым соединениям. Если тяжелый `image_filter` работает на тех же процессах, что и публичный фронтенд, это приводит к резкому росту задержки всех клиентов сайта.

### Вычислительная сложность современных кодеков

Вычислительные затраты на операцию сжатия различаются на порядки в зависимости от целевого формата:

| Формат | Библиотека | Алгоритм | Относительная нагрузка на CPU | Средняя задержка (800×600, 1 ядро 3.2 GHz) | Рекомендации для High Load |
|:-------|:-----------|:---------|:------------------------------|:-------------------------------------------|:---------------------------|
| **JPEG** | `libgd` (libjpeg-turbo) | DCT, Huffman | Базовая (1x) | 10–25 мс | Стандартный baseline-режим; `image_filter_interlace on` добавляет +5–10% CPU |
| **WebP** | `libwebp` | VP8 (lossy), VP8L (lossless) | Средняя (2x–3x) | 25–45 мс | `image_filter_webp_quality 75–80` |
| **AVIF** | `libavif` (libaom / rav1e) | AV1 intra-frame | Экстремальная (10x–40x) | 70–160 мс (при speed 9) / >1500 мс (при speed 4) | Обязательно `image_filter_avif_speed 8–10`; speed < 8 запрещен в online-контуре |
| **HEIC** | `libheif` | HEVC / x265 | Высокая (8x–15x) | 60–120 мс | `image_filter_heic_quality 70–75` |
| **Sharpen** | `libgd` | Свертка матрицы 3×3 | Дополнительная (+15–30%) | +10–25 мс к любому кодеку | Ограничивать `image_filter_sharpen 1–2` только для мелких превью (thumbnails) |

### Детальная модель потребления оперативной памяти

Ошибочно полагать, что память на запрос ограничена только параметром `image_filter_buffer`. Полный объем памяти, выделяемый воркером из системной кучи (glibc heap) при трансформации:

$$\text{RAM}_{\text{req}} = \text{image\_filter\_buffer} + (\text{Width}_{\text{src}} \times \text{Height}_{\text{src}} \times 4) + (\text{Width}_{\text{dst}} \times \text{Height}_{\text{dst}} \times 4) + \text{Heap}_{\text{codec}}$$

Где:
- $\text{image\_filter\_buffer}$ — буфер для входящего файла (например, 20 МБ);
- $\text{Width}_{\text{src}} \times \text{Height}_{\text{src}} \times 4$ — несжатая матрица оригинала TrueColor в `libgd` (4 байта на пиксель: R, G, B, Alpha). Для фото со смартфона 24 Мп (6000×4000) размер матрицы составляет:
  $$6000 \times 4000 \times 4 = 96\,000\,000 \text{ байт } (\approx 91.5 \text{ МБ});$$
- $\text{Width}_{\text{dst}} \times \text{Height}_{\text{dst}} \times 4$ — результирующая матрица после масштабирования;
- $\text{Heap}_{\text{codec}}$ — внутренние рабочие структуры кодека (`libavif` аллоцирует дополнительные 15–30 МБ под контекст энкодера AV1).

**Следствие для сайзинга:**
При обработке 24 Мп фото один воркер кратковременно потребляет $20 + 91.5 + 4 + 20 \approx 135.5 \text{ МБ}$ RAM. Если на 16-ядерном сервере все 16 воркеров одновременно примут запросы на обработку тяжелых оригиналов, мгновенный всплеск составит более 2.1 ГБ оперативной памяти только под нужды трансформации.

### Архитектурная топология High Load (Двухуровневый контур)

Для устранения деградации производительности в bare-metal и on-premise инфраструктурах применяется строгое разделение:

```
[ Публичный сетевой трафик ]
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Фронтенд-уровень (Edge Tier / Angie Frontend)            │
│  - SSL/TLS termination, HTTP/2, HTTP/3 (QUIC)               │
│  - worker_processes auto, worker_cpu_affinity               │
│  - Content Negotiation (map $http_accept -> avif, webp, ...)│
│  - proxy_cache на NVMe (индекс в keys_zone)                │
│  - proxy_cache_lock on; proxy_cache_use_stale updating      │
│  - Rate Limiting (limit_req, limit_conn)                    │
└──────────────────────────────┬──────────────────────────────┘
                               │ (MISS / BYPASS)
                 Unix Domain Socket / Keepalive Loopback
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Бэкенд-уровень (Compute Tier / Angie Image Processor)    │
│  - worker_processes = количеству выделенных CPU ядер         │
│  - Изоляция ядер через worker_cpu_affinity / isolcpus       │
│  - image_filter_buffer 20M–30M; proxy_buffering off;        │
│  - Выделенные лимиты systemd (CPUQuota, MemoryMax)          │
│  - Отдача трансформированного потока в сокет фронтенда      │
└─────────────────────────────────────────────────────────────┘
```

**Преимущества схемы:**
- Фронтенд обслуживает 100 000+ соединений без риска зависания event loop.
- Бэкенд получает ровно столько запросов, сколько способен обработать без деградации планировщика (ограничивается через параметр `max_conns` в апстриме фронтенда).
- 95–99% запросов отдаются из кэша фронтенда со скоростью статики (latency < 1–2 мс).

### Модель очередей и Capacity Planning

Пропускная способность пула трансформации подчиняется модели систем массового обслуживания (M/M/c). При приближении коэффициента утилизации CPU к $U > 0.75$ (75%) среднее время ожидания в очереди начинает расти экспоненциально:

$$\text{Параллельные трансформации } (C_{\text{active}}) = \text{RPS}_{\text{miss}} \times \overline{T}_{\text{latency}}$$

Где $\overline{T}_{\text{latency}}$ — средневзвешенное время обработки запроса с учетом распределения форматов:

$$\overline{T}_{\text{latency}} = (p_{\text{avif}} \times t_{\text{avif}}) + (p_{\text{webp}} \times t_{\text{webp}}) + (p_{\text{jpeg}} \times t_{\text{jpeg}})$$

**Расчет необходимого числа ядер (Headroom 30%):**

$$N_{\text{cores}} = \left\lceil \frac{C_{\text{active}}}{U_{\text{target}}} \right\rceil = \left\lceil \frac{C_{\text{active}}}{0.70} \right\rceil$$

**Пример практического расчета:**
- Входящая нагрузка: 500 RPS в фазе cache miss (или при прогреве).
- Распределение форматов: 60% AVIF ($t = 0.12$ c), 30% WebP ($t = 0.035$ c), 10% JPEG ($t = 0.02$ c).
- Средневзвешенное время: $(0.6 \times 0.12) + (0.3 \times 0.035) + (0.1 \times 0.02) = 0.072 + 0.0105 + 0.002 = 0.0845 \text{ с } (84.5 \text{ мс})$.
- Активных одновременных задач: $500 \times 0.0845 = 42.25$.
- Необходимое число ядер CPU при целевой утилизации 70%: $\lceil 42.25 / 0.70 \rceil = 61 \text{ ядро}$.

---

## Практические сценарии

### Сценарий 1: Двухуровневая высоконагруженная архитектура с Unix Domain Socket

Разделение логики между фронтендом с дисковым кэшем и внутренним воркер-процессором через Unix Domain Socket с контролем соединений.

**Конфигурация бэкенда (`/etc/angie/conf.d/image_backend.conf`):**

```nginx
# Внутренний сервер трансформации
server {
    listen unix:/var/run/angie/image_processor.sock backlog=2048;
    server_name _;

    # Учет метрик внутреннего контура
    status_zone image_filter_backend;

    # Буфер под сжатый входящий оригинал
    image_filter_buffer 25M;

    # Настройки кодеков для минимизации Latency
    image_filter_avif_speed 9;
    image_filter_avif_quality 65;
    image_filter_webp_quality 80;
    image_filter_jpeg_quality 80;

    location ~ ^/transform/(?<fmt>avif|webp|jpeg)/(?<w>\d+)x(?<h>\d+)/(?<path>.+)$ {
        # Защита: доступ только из локального процесса
        allow 127.0.0.1;
        allow unix:;
        deny all;

        alias /var/www/media/originals/$path;

        # Конвертация и пропорциональное масштабирование
        image_filter resize $w $h;
        image_filter convert $fmt;

        # Отключение буферизации для немедленной передачи чанков
        proxy_buffering off;
    }
}
```

**Конфигурация фронтенда (`/etc/angie/conf.d/image_frontend.conf`):**

```nginx
proxy_cache_path /var/cache/angie/images 
    levels=1:2 
    keys_zone=img_cache:64m 
    max_size=50g 
    inactive=30d 
    use_temp_path=off;

map $http_accept $target_format {
    default                  jpeg;
    "~*image/avif"           avif;
    "~*image/webp"           webp;
}

upstream image_backend_cluster {
    zone image_backend_cluster 512k;
    server unix:/var/run/angie/image_processor.sock max_conns=16 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 80;
    listen 443 ssl reuseport;
    server_name media.example.internal;

    status_zone image_frontend;

    location ~ ^/media/(?<w>\d+)x(?<h>\d+)/(?<path>.+)$ {
        proxy_cache img_cache;
        proxy_cache_key "$target_format:$w:$h:$path";
        
        # Защита от Thundering Herd
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_lock_age 10s;
        
        # Отдача устаревшего кэша при обновлении или сбое бэкенда
        proxy_cache_use_stale updating error timeout invalid_header http_500 http_502 http_503 http_504;
        proxy_cache_valid 200 30d;
        proxy_cache_valid 404 415 1m;

        # Заголовки для браузера и CDN
        add_header X-Cache-Status $upstream_cache_status always;
        add_header Vary Accept always;

        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_pass http://image_backend_cluster/transform/$target_format/${w}x${h}/$path;
    }
}
```

**Валидация:**
```bash
# Проверка прав и существования сокета
ls -la /var/run/angie/image_processor.sock
# → srw-rw-rw- 1 angie angie 0 Oct 14 13:20 /var/run/angie/image_processor.sock

# Тестовый запрос с эмуляцией поддержки AVIF
curl -I -H "Accept: image/avif,image/webp,*/*" http://127.0.0.1/media/400x300/catalog/item1.jpg
# → HTTP/1.1 200 OK
# → Content-Type: image/avif
# → X-Cache-Status: MISS
# → Vary: Accept

# Повторный запрос (проверка HIT)
curl -I -H "Accept: image/avif,image/webp,*/*" http://127.0.0.1/media/400x300/catalog/item1.jpg
# → HTTP/1.1 200 OK
# → X-Cache-Status: HIT
```

---

### Сценарий 2: Привязка воркеров к ядрам (CPU Affinity) и оптимизация NUMA

На многопроцессорных bare-metal серверах (2 сокета NUMA) перенос процесса с одного ядра на другое или обращение к чужому банку оперативной памяти вызывает деградацию L1/L2 кэша и пропускной способности шин UPI/QPI.

**Конфигурация `/etc/angie/angie.conf` (для 16-ядерной системы, 2 сокета по 8 ядер):**

```nginx
user angie;
# Запуск 16 воркеров
worker_processes 16;

# Жесткая маска привязки воркеров к конкретным ядрам (ядра 0-15)
worker_cpu_affinity 0000000000000001 
                    0000000000000010 
                    0000000000000100 
                    0000000000001000 
                    0000000000010000 
                    0000000000100000 
                    0000000001000000 
                    0000000010000000 
                    0000000100000000 
                    0000001000000000 
                    0000010000000000 
                    0000100000000000 
                    0001000000000000 
                    0010000000000000 
                    0100000000000000 
                    1000000000000000;

worker_rlimit_nofile 131072;
```

**Оптимизация NUMA на уровне ОС:**
```bash
# Проверка распределения памяти по NUMA-узлам
numastat -c angie
# → Node 0   Node 1   Total
# → 1250 MB  1240 MB  2490 MB

# Запуск Angie с политикой чередования памяти между сокетами
# /etc/systemd/system/angie.service.d/numa.conf
[Service]
ExecStart=
ExecStart=/usr/bin/numactl --interleave=all /usr/sbin/angie -c /etc/angie/angie.conf
```

**Валидация:**
```bash
# Проверка привязки воркеров (PSR - процессор, на котором работает процесс)
ps -o pid,psr,comm -p $(pgrep angie | tr '\n' ' ')
# → PID   PSR COMMAND
# → 4101    0 angie
# → 4102    1 angie
# → 4103    2 angie
# → 4104    3 angie
```

---

### Сценарий 3: Настройка параметров ядра Linux (sysctl) и лимитов systemd

Для обслуживания High Load и предотвращения переполнения сетевых сокетов и исчерпания памяти на физическом сервере настраиваются подсистемы ядра и `systemd`.

**Конфигурация `/etc/sysctl.d/99-angie-image-filter.conf`:**

```ini
# Максимальное число открытых файловых дескрипторов в системе
fs.file-max = 2097152

# Глубина очереди входящих соединений на слушающих сокетах (backlog)
net.core.somaxconn = 65535

# Глубина очереди сетевых пакетов на уровне интерфейса (NIC RX queue)
net.core.netdev_max_backlog = 16384

# Защита от переполнения SYN-очереди при всплесках соединений
net.ipv4.tcp_max_syn_backlog = 32768

# Быстрое переиспользование сокетов в TIME_WAIT для локальных апстримов
net.ipv4.tcp_tw_reuse = 1

# Буферы приема и передачи TCP (автотюнинг)
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Запрет паники OOM и контроль аллокации памяти для libgd
vm.overcommit_memory = 0
vm.swappiness = 10
```

**Применение настроек:**
```bash
sudo sysctl --system
# → * Applying /etc/sysctl.d/99-angie-image-filter.conf ...
# → fs.file-max = 2097152
# → net.core.somaxconn = 65535
```

**Конфигурация `/etc/systemd/system/angie.service.d/override.conf`:**

```ini
[Service]
# Лимит на файловые дескрипторы для мастер-процесса и воркеров
LimitNOFILE = 131072
LimitNPROC = 65536

# Изоляция ресурсов cgroups v2
MemoryHigh = 14G
MemoryMax = 16G
CPUWeight = 1000

# Защита от выбивания процесса OOM Killer при общем дефиците памяти
OOMScoreAdjust = -500

# Перезапуск в случае падения воркера из-за segfault в сторонних библиотеках
Restart = on-failure
RestartSec = 2s
```

**Применение и валидация:**
```bash
sudo systemctl daemon-reload
sudo systemctl restart angie

# Проверка действующих лимитов процесса Angie
systemctl show angie --property=LimitNOFILE,MemoryMax,OOMScoreAdjust
# → LimitNOFILE=131072
# → MemoryMax=17179869184
# → OOMScoreAdjust=-500
```

---

### Сценарий 4: Нагрузочное тестирование с защитой от Coordinated Omission (wrk2)

Стандартные утилиты (`ab`, `wrk`) задерживают отправку новых запросов, если сервер заблокирован обработкой предыдущих, что скрывает реальные катастрофические хвосты задержки (Tail Latency). Для объективного тестирования используется `wrk2` с фиксированной частотой подачи запросов (`-R`).

**Команда нагрузочного теста:**
```bash
# Тест с фиксированной нагрузкой 200 RPS, 4 потока, 50 соединений, длительность 60 секунд
wrk -t4 -c50 -d60s -R200 --latency -H "Accept: image/avif" http://127.0.0.1/media/800x600/catalog/photo.jpg
```

**Ожидаемый результат валидации:**
```text
Running 1m test @ http://127.0.0.1/media/800x600/catalog/photo.jpg
  4 threads and 50 connections
  Thread calibration: mean lat.: 42.12ms, rate: 50.00 rps
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    45.18ms   12.35ms 182.40ms   84.20%
    Req/Sec    50.00      0.00    50.00    100.00%
  Latency Distribution (HdrHistogram - Raw)
     50.000%   42.10ms
     75.000%   49.80ms
     90.000%   58.40ms
     95.000%   72.10ms
     99.000%  112.50ms
     99.900%  164.20ms
  Requests/sec:    199.98
  Transfer/sec:      4.82MB
```

---

### Сценарий 5: Профилирование узких мест CPU и памяти (perf, pidstat)

Анализ времени процессора на физическом сервере для выявления доли, приходящейся на кодеки, и устранения непроизводительных циклов.

**1. Непрерывный мониторинг загрузки воркеров и переключений контекста:**
```bash
pidstat -u -w -r -p $(pgrep -d',' -f "angie: worker") 1 3
```
**Ожидаемый вывод:**
```text
Linux 6.8.0 (node01)    10/14/2026      _x86_64_        (16 CPU)

13:25:01      UID       PID    %usr %system  %guest   %wait    %CPU   CPU  Command
13:25:02      101      4101   88.00    8.00    0.00    0.00   96.00     0  angie
13:25:02      101      4102   89.00    7.00    0.00    0.00   96.00     1  angie
13:25:02      101      4103   91.00    6.00    0.00    0.00   97.00     2  angie
```
> Анализ: `%usr` > 85% при `%system` < 10% указывает на чисто вычислительную работу кодека (норма для AVIF/WebP). Высокий `%wait` или `%system` свидетельствует о блокировках на системных вызовах или дисковом I/O.

**2. Анализ профиля функций в реальном времени через `perf`:**
```bash
# Сбор топ-функций по использованию CPU (требуются отладочные символы библиотек)
sudo perf top --pid=$(pgrep -o -f "angie: worker") --sort comm,dso,symbol
```
**Ожидаемый вывод:**
```text
Samples: 42K of event 'cycles', 4000 Hz, Event count (approx.): 18451200234
Overhead  Shared Object         Symbol
  42.15%  libavif.so.16.0.1     [.] aom_convolve8_vert_ssse3
  21.30%  libavif.so.16.0.1     [.] av1_quantize_fp_sse2
  14.20%  libgd.so.3.0.11       [.] gdImageCopyResampled
   8.40%  libwebp.so.7.1.9      [.] VP8EncLoop
   2.10%  angie                 [.] ngx_http_image_filter_body_filter
```
> Анализ: Топ-функции принадлежат оптимизированным SIMD-инструкциям (`ssse3`, `sse2`) энкодеров. Если в топе появляется `lock` или системные вызовы аллокатора (`malloc`/`free`), требуется настройка `jemalloc` или `tcmalloc`.

---

### Сценарий 6: Graceful Degradation и сброс нагрузки при перегрузке CPU

Когда процессор загружен на 95–100%, прием новых запросов на кодирование AVIF приведет к параличу сервера. Настраивается отсечка с возвратом HTTP 503 или мгновенным fallback на отдачу исходного JPEG без трансформации.

**Конфигурация `/etc/angie/conf.d/shedding.conf`:**

```nginx
# Зона лимита на параллельные тяжелые трансформации
limit_conn_zone $server_name zone=heavy_transforms:10m;
limit_req_zone $binary_remote_addr zone=transform_rate:20m rate=100r/s;

server {
    listen 8081;
    server_name localhost;

    location /resize/ {
        # Жесткое ограничение очереди: если в обработке уже 32 трансформации,
        # новые запросы немедленно сбрасываются с кодом 503
        limit_conn heavy_transforms 32;
        limit_req zone=transform_rate burst=50 nodelay;

        limit_conn_status 503;
        limit_req_status 503;

        # Обработка ошибки 503: мгновенный возврат оригинального файла
        error_page 503 = @fallback_original;

        image_filter resize 800 600;
        image_filter convert avif;
        alias /var/www/media/originals/;
    }

    location @fallback_original {
        # Отдача исходника без вызова image_filter
        root /var/www/media/originals;
        add_header X-Transform-Status "Degraded-Original" always;
    }
}
```

**Валидация:**
```bash
# Стресс-тест генерации 50 параллельных запросов
ab -n 100 -c 50 http://127.0.0.1:8081/resize/photo.jpg | grep "Complete requests"
# → Complete requests: 100

# Проверка наличия заголовка деградации при насыщении
curl -I http://127.0.0.1:8081/resize/photo.jpg
# → HTTP/1.1 200 OK
# → X-Transform-Status: Degraded-Original
```

---

### Сценарий 7: Регламентный прогрев кэша (Cache Warmup)

Для предотвращения дискового и процессорного шторма после перезапуска Angie или выкатки нового каталога выполняется асинхронный прогрев с ограничением параллелизма на локальном хосте.

**Скрипт прогрева `/usr/local/bin/angie-image-warmup.sh`:**

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="http://127.0.0.1"
CONCURRENCY=4
URL_LIST="/var/run/angie/warmup_urls.txt"

# Генерация списка целевых URI
cat << 'EOF' > "${URL_LIST}"
/media/400x300/catalog/item1.jpg
/media/800x600/catalog/item1.jpg
/media/400x300/catalog/item2.jpg
/media/800x600/catalog/item2.jpg
/media/1200x900/promo/banner.jpg
EOF

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Запуск прогрева кэша с параллелизмом ${CONCURRENCY}..."

# Прогрев AVIF и WebP через xargs
cat "${URL_LIST}" | xargs -P "${CONCURRENCY}" -I {} \
    curl -s -o /dev/null -w "URI: {} | Format: AVIF | Status: %{http_code} | Time: %{time_total}s\n" \
    -H "Accept: image/avif" "${TARGET_HOST}{}"

cat "${URL_LIST}" | xargs -P "${CONCURRENCY}" -I {} \
    curl -s -o /dev/null -w "URI: {} | Format: WebP | Status: %{http_code} | Time: %{time_total}s\n" \
    -H "Accept: image/webp" "${TARGET_HOST}{}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Прогрев успешно завершен."
```

**Запуск и валидация:**
```bash
chmod +x /usr/local/bin/angie-image-warmup.sh
/usr/local/bin/angie-image-warmup.sh
# → [2026-10-14 13:30:00] Запуск прогрева кэша с параллелизмом 4...
# → URI: /media/400x300/catalog/item1.jpg | Format: AVIF | Status: 200 | Time: 0.112s
# → URI: /media/800x600/catalog/item1.jpg | Format: AVIF | Status: 200 | Time: 0.145s
# → [2026-10-14 13:30:02] Прогрев успешно завершен.

# Проверка наполнения кэша через API Angie
curl -s http://127.0.0.1:8080/status/http/caches/img_cache | jq '.responses'
# → { "hit": 0, "stale": 0, "updating": 0, "revalidated": 0, "miss": 10, "expired": 0, "bypass": 0 }
```

---

## Операции и команды

| Задача | Команда | Ожидаемый результат |
|:-------|:--------|:--------------------|
| **Проверка сборки и модуля** | `angie -V 2>&1 \| grep -o 'http_image_filter_module'` | `http_image_filter_module` |
| **Тестирование конфигурации** | `angie -t` | `syntax is ok / test is successful` |
| **Проверка библиотек кодеков** | `ldd $(which angie) \| grep -E 'avif\|webp\|gd'` | Вывод динамических путей к `libavif.so`, `libwebp.so`, `libgd.so` |
| **Проверка активности сокета** | `ss -xlp \| grep image_processor` | `u_str LISTEN 0 2048 /var/run/angie/image_processor.sock` |
| **Загрузка ядер воркерами** | `mpstat -P ALL 1 3 \| grep -E 'Average\|CPU'` | Сбалансированное распределение `%usr` по ядрам, `%idle` > 20% |
| **Память и swap воркеров** | `vmstat 1 3` | Столбцы `si` и `so` строго равны `0` |
| **Мониторинг задержки зоны (API)**| `curl -s http://127.0.0.1:8080/status/http/status_zones/image_filter_backend \| jq '.responses.time'` | Время ответа в миллисекундах (P50/P95) |
| **Проверка ошибок 415 (API)** | `curl -s http://127.0.0.1:8080/status/http/status_zones/image_filter_backend \| jq '.responses.codes."415"'` | `0` (или минимальный процент < 0.1%) |
| **Статус дискового кэша (API)** | `curl -s http://127.0.0.1:8080/status/http/caches/img_cache \| jq '{size: .bytes, hit_ratio: (.responses.hit / (.responses.hit + .responses.miss))}'` | `hit_ratio` > 0.90 (90%+ кэш-хитов) |
| **Метрики Prometheus** | `curl -s http://127.0.0.1:8080/metrics \| grep -E 'angie_http_status_zone'` | Текстовый вывод метрик в формате OpenMetrics |
| **Проверка очередей бэкенда** | `curl -s http://127.0.0.1:8080/status/http/upstreams/image_backend_cluster \| jq '.peers[] \| {server, active, conns}'` | `active` не превышает установленный `max_conns` |
| **Валидация правил Prometheus**| `promtool check rules /etc/prometheus/rules/image_filter.yml` | `SUCCESS: 2 rules found` |

---

## Troubleshooting

### Матрица инцидентов производительности

| Симптом | Диагностика | Первопричина | Решение |
|:---|:---|:---|:---|
| **Полка CPU 100%, лавинообразный рост 504 Gateway Timeout** | `top -b -n1 \| grep angie`<br>`pidstat -u 1 5` | Всплеск запросов на кодирование AVIF с низким параметром скорости (`speed < 8`) или лавина cache miss | 1. Установить `image_filter_avif_speed 9;` или `10`.<br>2. Ограничить `max_conns` в апстриме бэкенда.<br>3. Включить `proxy_cache_lock on;` на фронтенде. |
| **Рост ошибок HTTP 415 Unsupported Media Type** | `grep "image buffer is too small" /var/log/angie/error.log`<br>`curl .../status/http/status_zones/...` | Размер входящего оригинала превышает `image_filter_buffer` | Увеличить `image_filter_buffer` в блоке `server` бэкенда (например, с `10M` до `25M–30M`). |
| **Аварийное завершение воркеров (SIGSEGV / OOM Killer)** | `dmesg -T \| grep -E -i "kill\|oom\|segfault"`<br>`journalctl -u angie -e` | Исчерпание лимита оперативной памяти (`MemoryMax`) из-за одновременной обработки гигантских фото (24–48 Мп) | 1. Уменьшить `worker_processes` на узле трансформации.<br>2. Ограничить максимальные размеры через директивы `map`.<br>3. Увеличить `MemoryMax` в systemd override. |
| **Всплеск P99 Latency (>2 сек) при нормальном среднем P50** | `wrk2` гистограмма;<br>`curl .../status/http/status_zones/... \| jq .responses.time` | 1. Head-of-Line blocking в HTTP/2.<br>2. Несколько одновременных тяжелых трансформаций заблокировали воркеры | 1. Использовать HTTP/1.1 с пулом постоянных соединений `keepalive 32` между фронтендом и бэкендом.<br>2. Настроить `least_time` балансировку в upstream. |
| **Высокий I/O Wait (%iowait > 15%), деградация отдачи** | `iostat -xz 1 5`<br>Столбец `%util` близок к 100%, `await > 10ms` | Запись кэша на медленный накопитель или включенный `use_temp_path=on`, вызывающий двойную перезапись файлов | 1. В директиве `proxy_cache_path` обязательно выставить `use_temp_path=off`.<br>2. Перенести директорию кэша на выделенный массив NVMe с опцией монтирования `noatime`. |
| **Зависание соединений на сокете фронтенда** | `ss -xlp \| grep angie`<br>Очередь сокета (`Send-Q`) растет | Бэкенд трансформации перегружен и не успевает считывать данные из сокета | 1. Увеличить `backlog` в директиве `listen unix:... backlog=4096;`.<br>2. Настроить `limit_conn` для сброса избыточных задач. |
| **Деградация скорости при использовании `image_filter_sharpen`** | `perf top` показывает высокую нагрузку на `gdImageCopyResampled` | Директива `sharpen` выполняет свертку O(W×H) по всей матрице пикселей | Отключить `image_filter_sharpen` для крупных изображений (>800x600), использовать значение не более `1` или `2` только для превью. |

---

## Best Practices

1. **Строго изолируйте контуры обслуживания (Double Proxying):** Никогда не запускайте `image_filter` на публичных воркерах, обслуживающих клиентские соединения и SSL. Фронтенд должен только кэшировать и проверять `Accept`, бэкенд — трансформировать.
2. **Используйте Unix Domain Socket для локального IPC:** Связка фронтенда и бэкенда через сокет устраняет накладные расходы сетевого стека TCP/IP, экономя 15–20% процессорного времени и устраняя риск исчерпания локальных портов (ephemeral ports exhaustion).
3. **Фиксируйте параметры скорости AVIF в диапазоне 8–10:** Параметр `image_filter_avif_speed 9` обеспечивает 90% преимуществ сжатия формата AVIF по сравнению с WebP при четырехкратном снижении расхода процессорного времени относительно `speed 4`.
4. **Контролируйте конкурентность через `max_conns`:** В блоке `upstream` фронтенда всегда указывайте `server unix:... max_conns=N;`, где $N$ равно количеству процессорных ядер бэкенда. Это предотвращает накопление блокирующих задач в воркерах.
5. **Защищайте контур от Thundering Herd:** Обязательно настраивайте `proxy_cache_lock on;`, `proxy_cache_lock_timeout 5s;` и `proxy_cache_use_stale updating;`. Это гарантирует, что при промахе кэша только один запрос уйдет на кодирование оригинала, а остальные клиенты дождутся готового результата либо получат предыдущую версию.
6. **Выставляйте `use_temp_path=off` в кэше:** Запись файлов кэша непосредственно в целевую иерархию папок исключает дополнительную операцию копирования между временным каталогом и постоянным хранилищем, кратно снижая нагрузку на диск.
7. **Привязывайте воркеры к ядрам и учитывайте NUMA:** На многопроцессорных серверах используйте `worker_cpu_affinity` и утилиту `numactl --interleave=all`, чтобы избежать деградации памяти и вытеснения кэша CPU L1/L2.
8. **Ограничивайте ресурсы через cgroups v2 / systemd:** Задавайте `MemoryMax` и `LimitNOFILE` в `override.conf` сервиса Angie. Это защитит хост от падения при попытке обработки вредоносных декомпрессионных бомб (Pixel Flood).
9. **Мониторьте Tail Latency (P95/P99), а не среднее:** Среднее время ответа маскирует катастрофические задержки кодеков. Настройте Prometheus-алерты на 95-й перцентиль времени обработки зоны `image_filter_backend`.

---

## Дополнительная информация

### Мониторинг Prometheus и правила Alertmanager

Конфигурация экспорта метрик через модуль `ngx_http_prometheus_module`:

```nginx
# В основном контексте http блока
http {
    include prometheus_all.conf;

    # Сервер мониторинга
    server {
        listen 127.0.0.1:8080;
        server_name localhost;

        location /status/ {
            api /status/;
            allow 127.0.0.1;
            deny all;
        }

        location /metrics {
            prometheus all;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Файл правил Prometheus Alertmanager (`/etc/prometheus/rules/image_filter.yml`):**

```yaml
groups:
  - name: angie.image_filter.performance
    rules:
      - record: job:angie_image_filter_latency:p95
        expr: histogram_quantile(0.95, sum(rate(angie_http_status_zone_responses_time_seconds_bucket{zone="image_filter_backend"}[5m])) by (le))

      - record: job:angie_image_filter_error_rate_415:ratio
        expr: sum(rate(angie_http_status_zone_responses_total{zone="image_filter_backend", code="415"}[5m])) / sum(rate(angie_http_status_zone_responses_total{zone="image_filter_backend"}[5m]))

      - alert: ImageFilterHighTailLatency
        expr: job:angie_image_filter_latency:p95 > 0.40
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency трансформации изображений превышает 400 мс"
          description: "Текущее значение: {{ $value }}s. Возможен всплеск тяжелых AVIF-запросов или нехватка CPU ядер."

      - alert: ImageFilterBufferOverflowSpike
        expr: job:angie_image_filter_error_rate_415:ratio > 0.02
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Более 2% запросов завершаются ошибкой 415 (image_filter_buffer)"
          description: "Входящие оригиналы превышают размер image_filter_buffer. Требуется пересмотр лимита буфера."
```

### См. также

- [Обзор модуля image_filter](./overview.md)
- [Стратегии кэширования изображений](./caching.md)
- [Безопасность и защита от DoS](./security.md)
- [Конфигурация директив фильтрации](./filter_configuration.md)
- [Геометрические трансформации и масштабирование](./resize.md)
- [Комплексная настройка сайта](./site_configuration.md)
- [Установка и сборка модуля](./installation.md)
- [Оптимизация производительности Angie](../performance_optimization.md)
