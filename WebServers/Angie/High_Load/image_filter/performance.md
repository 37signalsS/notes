# Модуль image_filter в Angie: производительность и масштабирование

## Определения

**Производительность image_filter** — комплексная характеристика эффективности обработки медиаконтента, определяемая временем задержки (Latency) на операцию трансформации и совокупной пропускной способностью (Throughput) системы при заданных лимитах вычислительных ресурсов (CPU, RAM).

**Масштабирование обработки** — процесс увеличения мощности системы для поддержания стабильного времени ответа при росте количества запросов на динамическую генерацию изображений.

**Пропускная способность (Throughput)** — количество успешно обработанных трансформаций в единицу времени (обычно запросов в секунду, rps). Ограничена min(CPU_bound, IO_bound, Memory_bound).

**Saturation (Насыщение)** — состояние, при котором добавление новой единицы нагрузки (запроса) не увеличивает пропускную способность, а только растет задержка или queue depth.

**Tail Latency (P95/P99)** — перцентили времени ответа, отражающие worst-case поведение системы. Для image_filter критичен P95/P99, потому что единичный AVIF-запрос может заблокировать воркер на сотни миллисекунд.

**Head-of-line blocking** — явление, при котором медленный запрос (например, AVIF на 180 мс) блокирует очередь (HTTP/2 stream или worker connection), замедляя отдачу всех последующих запросов на этом соединении/воркере.

**Cache Warmup (Прогрев кэша)** — процесс предварительного заполнения кэша результатами трансформаций до прихода пиковой нагрузки, чтобы минимизировать MISS-запросы к image_filter.

**Cold Start Latency** — задержка первого запроса после перезагрузки Angie или истечения TTL, когда результат отсутствует в кэше и требуется полная трансформация оригинала.

## Базовые концепции

### Факторы влияния на производительность

Время обработки одного изображения (Latency) в Angie зависит от нескольких ключевых факторов:

- **Вычислительная сложность кодека:**
  - **AVIF/HEIC:** Требуют в 10–50 раз больше циклов CPU по сравнению с JPEG. В Angie скорость регулируется через `image_filter_avif_speed` (0 — макс. сжатие, 10 — макс. скорость).
  - **WebP:** Промежуточный вариант, требует в 2–3 раза больше ресурсов, чем JPEG.
- **Размер и глубина цвета оригинала:** Чем выше разрешение исходного файла, тем больше памяти занимает его декомпрессия в буфере `image_filter_buffer` и тем дольше длится этап фильтрации.
- **Дополнительные фильтры:** Директива `image_filter_sharpen` значительно увеличивает нагрузку на CPU, так как требует прохода по всей матрице пикселей для вычисления резкости (свертка с ядром Гаусса).
- **Режим кодирования JPEG:** Директива `image_filter_interlace on` включает двухпроходное кодирование, добавляя +5–10% к времени обработки по сравнению с baseline JPEG.
- **Ориентировочные задержки (на 1 ядро 3GHz):**
  - JPEG → WebP (800x600): ~30–50 мс.
  - JPEG → AVIF (speed 8, 800x600): ~100–180 мс.
  - Применение Sharpen (1–10): добавляет +15–30% к времени обработки.
  - Применение Interlace: добавляет +5–10%.

### Архитектура производительности

Для обеспечения стабильности под высокой нагрузкой обязательным является использование схемы **двухуровневого проксирования** (Double Proxying). Внешний фронтенд отвечает за кэширование и защиту, внутренний сервер — за ресурсоёмкую обработку.

```
Клиент (Accept: image/avif) → [Фронтенд: Проверка кэша + Vary: Accept]
                                 ↓
                                 MISS → [Внутренний прокси: Трансформация]
                                           ↓
                                           [Запрос оригинала у хранилища]
                                           ↓
                                           [Применение image_filter: Resize/Convert]
                                           ↓
                                 HIT ← [Кэширование результата + Vary: Accept]
```

**Ключевые аспекты архитектуры:**
- **Изоляция:** Тяжелые операции обработки (особенно AVIF) выносятся на внутренние воркеры или отдельные инстансы, чтобы не блокировать быструю отдачу статики.
- **Управление кэшем:** Обязательная передача заголовка `Vary: Accept`, чтобы разные браузеры получали подходящие им форматы (AVIF для Chrome, JPEG для старых Safari) по одному URL.
- **Эффективность:** В `proxy_cache` сохраняется готовый результат. Оригинал запрашивается только один раз при промахе кэша (cache miss).

### Модель загрузки и насыщения

Каждый воркер Angie обрабатывает один запрос в один поток (один процесс — один запрос). Для параллельной обработки множества запросов требуется адекватное количество `worker_processes`, соответствующее числу ядер CPU.

**Формула параллелизма:**
```
Параллельные трансформации = (PPS_peak × p_avif × t_avif) + (PPS_peak × p_webp × t_webp) + (PPS_peak × p_jpeg × t_jpeg)
```

Где:
- `PPS_peak` — пиковое количество запросов в секунду
- `p_avif/p_webp/p_jpeg` — доля запросов на соответствующий формат
- `t_avif/t_webp/t_jpeg` — среднее время обработки одного запроса в секундах

**Пример расчета:**
- 1000 rps пик, 60% AVIF (180 мс), 30% WebP (40 мс), 10% JPEG (20 мс)
- Параллельные AVIF: 1000 × 0.6 × 0.18 = 108 воркеров
- Параллельные WebP: 1000 × 0.3 × 0.04 = 12 воркеров
- Параллельные JPEG: 1000 × 0.1 × 0.02 = 2 воркера
- Итого: ~122 параллельных трансформации

При `image_filter_buffer 20M` требуется ~2.44 GB RAM только для модуля. Добавьте 30% запас на ОС и другие процессы.

### Память и вычислительная модель

Каждая трансформация требует объема RAM, равного `image_filter_buffer`, для хранения полностью раскодированного изображения в пиксельной матрице.

**Расчет буфера:**
```
Буфер ≥ (Ширина × Высота × 4 байта RGB) × 1.3 (запас на метаданные)
```

Примеры:
- 12 МП фото (4032×3024): ~46 MB несжато → буфер 20M–30M
- 8 К видео кадр (7680×4320): ~100 MB несжато → буфер 40M–60M

При 100 параллельных запросах и буфере 20M потребуется ~2 GB оперативной памяти только под нужды модуля.

### Влияние HTTP/2 и мультиплексирования

HTTP/2 позволяет передавать несколько запросов по одному TCP-соединению. Это повышает эффективность использования соединений, но создает риск **head-of-line blocking**: медленный AVIF-запрос может заблокировать весь поток (stream), если `worker_connections` исчерпаны или очередь воркера переполнена. Для компенсации:
- Увеличивайте `worker_connections` (например, до 4096).
- Настраивайте `proxy_cache_lock` для предотвращения дублирования тяжелых операций.
- Используйте отдельный балансировщик для image_filter backend.

### CPU Affinity и NUMA

Привязка воркеров к ядрам через `worker_cpu_affinity` критична для image_filter, так как это предотвращает вытеснение кэша L1/L2 при интенсивных математических вычислениях. В системах с NUMA (многосокетные серверы) для предсказуемой производительности:
- Размещайте `worker_processes` на ядрах одного NUMA-узла, где находится оперативная память, используемая модулем.
- Используйте `numactl` или `systemd` CPUAffinity для привязки Angie к конкретному узле.

### Стратегии масштабирования

1.  **Вертикальное (Scale Up):**
    - Увеличение количества `worker_processes` до соответствия числу ядер CPU.
    - **CPU Affinity:** Привязка процессов к ядрам через `worker_cpu_affinity` предотвращает вытеснение кэша L1/L2 при интенсивных вычислениях.
2.  **Горизонтальное (Scale Out):**
    - Вынос фильтрации на выделенные узлы (Backend-фермы).
    - **Метод feedback (Angie Pro):** Позволяет балансировщику выбирать узел на основе реального времени ответа (Latency). Если одна нода занята тяжелым ресайзом AVIF, новые запросы уйдут на менее нагруженные узлы.
3.  **Изоляция ресурсов:** Использование `cgroups` или лимитов в Kubernetes (CPU shares) для предотвращения ситуации, когда процесс ресайза «задушит» отдачу статического контента или обработку TLS.

---

## Практические сценарии

### Сценарий: Базовое тестирование пропускной способности (Baseline Benchmark)

Определение максимальной пропускной способности и Tail Latency на эталонном конфигурации перед внедрением в production.

**Предварительные требования:**
- Установлен `wrk` или `ab` (ApacheBench).
- Включен `status_zone` на внутреннем сервере трансформации.
- Кэш очищен (`find /var/cache/angie/images -type f -delete`), чтобы запросы шли в image_filter.

```bash
# Базовый тест: 1000 запросов, 50 параллельных соединений, 10s ramp-up
wrk -t4 -c50 -d10s -H "Accept: image/avif" https://img.example.com/resize/400x300/photo.jpg

# Ожидаемый вывод (пример):
# Requests/sec: ~350, Latency P95 ~180ms, Timeout 12
```

**Валидация:**
```bash
# Проверка статуса зоны после теста
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_filter_backend | jq '.responses | {time: .time, codes: .codes}'

# Проверка утилизации CPU под нагрузкой
mpstat -P ALL 1 5 | grep -E "Average|CPU"
# → CPU0: 100% (все запросы ушли на одно ядро при worker_processes 1)
```

### Сценарий: Изоляция CPU для задач фильтрации

Выделение конкретных ядер CPU только под задачи обработки изображений для обеспечения предсказуемого времени ответа.

```nginx
# В основном контексте angie.conf
worker_processes 4;
# Привязываем воркеры к первым 4 ядрам
worker_cpu_affinity 0001 0010 0100 1000;

http {
    upstream image_filter_backend {
        server 127.0.0.1:8081;
        keepalive 32;
    }
}
```

**Валидация:**
```bash
# Проверка привязки воркеров к ядрам
ps -o pid,psr,comm -p $(pgrep angie | head -4)
# → PID  PSR COMMAND
# → 1234   0 angie, 1235   1 angie, 1236   2 angie, 1237   3 angie
```

### Сценарий: Тюнинг скорости и качества для High Load

Оптимизация параметров для снижения Latency при сохранении приемлемого визуального качества.

```nginx
location /img/v1/ {
    image_filter convert avif;
    image_filter_avif_quality 60;
    # Значение 9-10 обеспечивает скорость, близкую к WebP
    image_filter_avif_speed 9; 
    
    # Резкость только для превью
    image_filter_sharpen 2;
    
    # Буфер с запасом для мобильных фото
    image_filter_buffer 20M;
}
```

**Валидация:**
```bash
# → 0.142 (при speed 9, AVIF 800x600)
```

### Сценарий: Защита от всплесков нагрузки (Thundering Herd)

Предотвращение одновременной генерации одного и того же изображения несколькими потоками.

```nginx
location / {
    proxy_cache img_cache;
    # Ожидание завершения первой генерации
    proxy_cache_lock on;
    proxy_cache_lock_age 10s;
    proxy_cache_lock_timeout 5s;
    
    # Отдача старой версии при обновлении в фоне
    proxy_cache_use_stale updating error timeout;
    proxy_pass http://image_filter_backend;
}
```

**Валидация:**
```bash
# → MISS (только один запрос до image_filter), последующие HIT
```

### Сценарий: Наблюдаемость и алертинг через API Angie

Включение `status_zone` позволяет анализировать эффективность масштабирования в реальном времени.

```nginx
# Внутренний сервер (трансформация)
server {
    listen unix:/var/run/angie_img_filter.sock;
    server_name localhost;
    status_zone image_filter_backend;
    
    # ... конфигурация фильтрации ...
}

# Фронтенд с API
server {
    listen 127.0.0.1:8080;
    server_name localhost;
    
    location /status {
        api /status/;
        allow 127.0.0.1;
        deny all;
    }
    
    location /p8s {
        prometheus;
    }
}
```

**Метрики для мониторинга:**
- **`responses.time`**: Среднее время ответа внутреннего фильтра. Используется для тюнинга `avif_speed`.
- **`responses.codes.415`**: Частота ошибок из-за нехватки `image_filter_buffer`.
- **`requests.current`**: Количество параллельно обрабатываемых изображений.

**Валидация:**
```bash
# Проверка статуса зоны
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_filter_backend | jq .

# Проверка Prometheus-метрик
curl -s http://127.0.0.1:8080/p8s | grep -E "angie_zone|image_filter"
```

### Сценарий: Тюнинг sysctl и systemd для High Load

Оптимизация параметров ядра и systemd для обработки тысяч параллельных трансформаций.

```bash
# /etc/sysctl.d/99-image-filter.conf
fs.file-max = 200000
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.core.netdev_max_backlog = 65535

# Применение
sudo sysctl --system
```

```ini
# /etc/systemd/system/angie.service.d/override.conf
[Service]
LimitNOFILE = 65536
MemoryMax = 8G
CPUQuota = 800%
TasksMax = 1024
```

```nginx
# В основном контексте angie.conf
worker_processes auto;
worker_rlimit_nofile 65536;

events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
}

http {
    # Включаем sendfile для статики, но для image_filter используем proxy_buffering off
    sendfile on;
    
    server {
        location / {
            proxy_buffering off;
            proxy_pass http://image_filter_backend;
        }
    }
}
```

**Валидация:**
```bash
# → LimitNOFILE=65536, MemoryMax=8G, CPUQuota=800%
```

### Сценарий: Профилирование CPU для image_filter

Диагностика bottlenecks при высокой утилизации CPU.

```bash
# 1. Топ процессов Angie по CPU
top -b -n1 -p $(pgrep angie | tr '\n' ',' | sed 's/,$//') | head -20

# 2. Детальная статистика по потокам
pidstat -t -p $(pgrep angie | head -1) 1 5

# 3. Perf-отчет по hottest функциям (требует debug-символы angie)
perf top -p $(pgrep angie | head -1) --sort cpu

# 4. Flame Graph (требует perf + FlameGraph)
perf record -g -p $(pgrep angie | head -1) -- sleep 30
perf script | ./stackcollapse-perf.pl | ./flamegraph.pl > angie-flamegraph.svg
```

- `libavif`/`libwebp` в топе — нормальная активность кодирования.
- `libgd`/`gdImage*` — штатная работа с пиксельной матрицей.
- Аномально высокий `wait`/`iowait` — проблема с диском или памятью.

### Сценарий: Диагностика утечек памяти и давления

```bash
# → Mem: 16384 total, 8192 used, 8192 free
# → si/so = 0
```

- Увеличить `image_filter_buffer` только при ошибках 415.
- Уменьшить `worker_processes` при бесконечном росте RSS (утечка в libgd).
- Добавить `MemoryMax` в systemd override для автоматического перезапуска при превышении лимита.

### Сценарий: Диагностика задержек I/O

```bash
# → %util близко к 100% означает насыщение диска
# → await < 5ms на NVMe
```

- Переместить кэш Angie на быстрый NVMe.
- Включить `use_temp_path=off` в `proxy_cache_path` для снижения I/O.
- Увеличить `inactive` в `proxy_cache_path`, чтобы объекты дольше оставались в page cache.

### Сценарий: Сравнение Unix-сокет vs TCP loopback

Оценка производительности двух вариантов соединения фронтенда и внутреннего фильтра.

```bash
# TCP loopback:   ~320 rps, P95 ~180ms
# Unix-сокет:     ~380 rps, P95 ~150ms
```

**Вывод:** Unix-сокет дает прирост 15–20% за счет исключения TCP/IP-стека.

### Сценарий: HTTP/2 Multiplexing и Tail Latency

Оценка влияния HTTP/2 на производительность image_filter.

```bash
# HTTP/2:    ~280 rps, P95 210ms (head-of-line blocking)
# HTTP/1.1:  ~350 rps, P95 160ms (изоляция соединений)
```

**Рекомендация:** Для image_filter приоритет имеет HTTP/1.1 или отдельные TCP-соединения к внутреннему фильтру, чтобы исключить блокировку быстрых запросов медленными AVIF-операциями.

### Сценарий: Прогрев кэша (Cache Warmup)

Предварительное заполнение кэша популярными трансформациями для минимизации MISS при развертывании или после перезагрузки.

```bash
# Список популярных трансформаций (widths и форматы)
cat <<EOF > /tmp/warmup.txt
/resize/400x300/photo.jpg
/resize/800x600/photo.jpg
/resize/1200x900/photo.jpg
/resize/400x400/avatar.jpg
/resize/100x100/thumb.jpg
EOF

# → 200 /resize/400x300/photo.jpg, 200 /resize/800x600/photo.jpg

# Проверка заполнения кэша
curl -s http://127.0.0.1:8080/api/6/http/caches/img_cache | jq '.bytes | .total, .free'
```

### Сценарий: Graceful Degradation при насыщении CPU

Настройка поведения системы при превышении порога утилизации CPU.

```nginx
http {
    # Зона для отслеживания очереди
    limit_req_zone $binary_remote_addr zone=image_ops:10m rate=50r/s;
    
    server {
        location /resize/ {
            # При превышении 50 r/s возвращаем статический placeholder
            limit_req zone=image_ops burst=100 nodelay;
            limit_req_status 503;
            error_page 503 = /static/placeholder_avif.png;
            
            proxy_pass http://image_filter_backend;
        }
        
        # Fallback: отдача оригинала без трансформации
        location /static/ {
            internal;
            root /var/www/images/originals;
            expires 7d;
        }
    }
}
```

**Валидация:**
```bash
# → Часть запросов 503, latency не растет бесконечно
```

### Сценарий: Планирование мощности (Capacity Planning) с учетом headroom

Расчет параметров для горизонтального масштабирования с запасом на пики.

**Формула:**
```
Рекомендуемое число воркеров = ceil(Пиковые параллельные трансформации × 1.3)
```

Где 1.3 — запас на 30% на пики и сбои.

**Пример расчета:**
- 1000 rps пик, 60% AVIF (180 мс), 30% WebP (40 мс), 10% кэш HIT
- Параллельные AVIF: 1000 × 0.6 × 0.18 = 108
- Параллельные WebP: 1000 × 0.3 × 0.04 = 12
- Итого без HIT: 120 воркеров
- С запасом 30%: ceil(120 × 1.3) = 156 воркеров

При `image_filter_buffer 20M` требуется ~3.1 GB RAM только для модуля (156 × 20M).

**Валидация:**
```bash
# → time в диапазоне, codes.415 ≈ 0
```

---

## Операции и команды

| Задача | Команда | Ожидаемый результат |
|:-------|:--------|:--------------------|
| Проверка версии Angie | `angie -V 2>&1 | grep -E "1.1[1-9]|image_filter"` | Версия ≥ 1.11.0 и флаг модуля |
| Проверка libgd | `ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so \| grep -E "webp\|avif\|heif"` | Вывод `libwebp`, `libavif`, `libheif` |
| Статус воркеров | `systemctl status angie && ps aux \| grep angie \| wc -l` | active (running), N процессов |
| Утилизация CPU | `mpstat -P ALL 1 5 \| grep -E "Average\|CPU"` | Распределение по ядрам, нет single-thread瓶颈 |
| Использование памяти | `free -m && vmstat 1 5` | Доступная RAM, нулевой swap in/out |
| I/O wait | `iostat -xz 1 5` | %iowait < 5%, %util диска < 80% |
| Открытые FD | `ls /proc/$(pgrep -o angie)/fd \| wc -l` | < worker_rlimit_nofile |
| Статус кэша | `curl -s http://127.0.0.1:8080/api/6/http/caches/img_cache \| jq '.bytes \| .total, .free'` | total > 0, free адекватный |
| Статус зоны | `curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_filter_backend \| jq '.responses \| {time: .time, codes: .codes}'` | time в диапазоне, codes.415 ≈ 0 |
| Prometheus метрики | `curl -s http://127.0.0.1:8080/p8s \| grep -E "angie_zone\|image_filter"` | Метрики по zone image_filter_backend |
| Проверка синтаксиса | `angie -t -c /etc/angie/angie.conf` | syntax is ok |
| Проверка сокета | `ss -xl \| grep angie_img_filter` | LISTEN /var/run/angie_img_filter.sock |

---

## Troubleshooting

### Высокая утилизация CPU (CPU-bound)

| Симптом | Диагностика | Решение |
|:--------|:------------|:--------|
| `mpstat` показывает 100% на одном ядре | `worker_processes` установлен в 1 или привязан к одному ядру | Увеличить `worker_processes` до числа ядер, настроить `worker_cpu_affinity` |
| Рост latency AVIF при росте rps | `image_filter_avif_speed` слишком низкий (0–5) | Установить `image_filter_avif_speed 8–10` |
| Высокий `%iowait` в `mpstat` | Диск не справляется с чтением оригиналов | Переместить хранилище на NVMe, включить `use_temp_path=off` |
| Процессы Angie в `D` состоянии (uninterruptible sleep) | Проблемы с диском или NFS | Проверить `dmesg`, заменить хранилище на локальное |

### Нехватка памяти (Memory-bound)

| Симптом | Диагностика | Решение |
|:--------|:------------|:--------|
| Ошибки `415 Unsupported Media Type` при валидных изображениях | `curl ... \| jq '.responses.codes."415"'` > 0 | Увеличить `image_filter_buffer` до 20M–30M |
| RSS Angie растет бесконечно | `ps aux \| grep angie \| awk '{print $6}'` — мониторинг | Уменьшить `worker_processes`, проверить обновление libgd |
| Активный swap | `vmstat 1 5` — `si/so` > 0 | Увеличить RAM, уменьшить `image_filter_buffer`, добавить `MemoryMax` в systemd |
| OOM Killer убил Angie | `dmesg \| grep -i "out of memory"` | Установить `OOMScoreAdjust=-500` в systemd, увеличить RAM |

### Высокий Tail Latency (P95/P99)

| Симптом | Диагностика | Решение |
|:--------|:------------|:--------|
| P95 > 500 мс при стабильном среднем | `curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_filter_backend \| jq '.responses.time'` | Включить `proxy_cache_lock`, увеличить `image_filter_avif_speed` |
| Резкие скачки latency (spikes) | `proxy_cache_use_stale error timeout updating` отключен | Включить `proxy_cache_use_stale` для отдачи старого кэша |
| Latency растет только на AVIF | `responses.time` разный по форматам | Снизить `image_filter_avif_quality`, увеличить `image_filter_avif_speed`, добавить прегенерацию AVIF |
| Head-of-line blocking в HTTP/2 | Высокий P99 при низком P50 | Использовать HTTP/1.1 для внутреннего проксирования или отдельные TCP-соединения |

### I/O Bottleneck

| Симптом | Диагностика | Решение |
|:--------|:------------|:--------|
| `%util` диска > 90% в `iostat` | `iostat -xz 1 5` | Переместить кэш и originals на отдельный быстрый диск/NVMe |
| Высокий `await` (> 20 мс) | `iostat -xz 1 5` — столбец `await` | Заменить HDD на SSD/NVMe, проверить RAID |
| Высокий `%iowait` в `mpstat` | `mpstat -P ALL 1 5` | Включить `use_temp_path=off`, увеличить `manager_sleep` в `proxy_cache_path` |

---

## Best Practices

1. **Выделяйте отдельный хост/контейнер для image_filter backend** при нагрузке >5000 rps. Это исключает конкуренцию за CPU и I/O с фронтендом.
2. **Используйте Unix-сокет** для соединения фронтенда и внутреннего фильтра. Прирост 15–20% по сравнению с TCP loopback.
3. **Никогда не кэшируйте ответ ДО фильтра.** Используйте двухслойную схему: фронтенд кэширует, внутренний сервер трансформирует.
4. **Устанавливайте `image_filter_buffer` с запасом 30–50%** от размера самого большого оригинала. Для современных мобильных фото — минимум 20M.
5. **Для High Load используйте `image_filter_avif_speed 8–10`**. Значения 0–5 допустимы только для offload-задач, не критичных по времени.
6. **Настройте `proxy_cache_lock`** с `proxy_cache_lock_age 10s` и `proxy_cache_lock_timeout 5s` для защиты от Thundering Herd.
7. **Всегда добавляйте `Vary: Accept`** при адаптивной доставке. Без этого CDN и промежуточные прокси «отравят» кэш.
8. **Мониторьте P95/P99, а не только среднее.** Tail latency напрямую влияет на пользовательский опыт.
9. **Настройте алерты до попадания в production:** `ImageFilterBufferExhaustion`, `ImageFilterLatencyHigh`, `ImageFilterThroughputDrop`.
10. **Проверяйте `libgd` после каждого обновления ОС.** Поддержка AVIF/HEIC зависит от системных библиотек.

---

## Дополнительная информация

### Мониторинг и алертинг (Prometheus + Alertmanager)

```yaml
groups:
  - name: image_filter.rules
    rules:
      - record: angie_image_filter_latency_p95
        expr: histogram_quantile(0.95, sum(rate(angie_zone_responses_time_bucket{zone="image_filter_backend"}[5m])) by (le))
      - record: angie_image_filter_error_rate_415
        expr: sum(rate(angie_zone_responses_codes{code="415", zone="image_filter_backend"}[1m])) / sum(rate(angie_zone_requests_total{zone="image_filter_backend"}[1m]))
```

```yaml
groups:
  - name: image_filter.alerts
    rules:
      - alert: ImageFilterLatencyHigh
        expr: angie_image_filter_latency_p95 > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency image_filter > 500ms"
          description: "Текущий P95: {{ $value }}s. Проверьте image_filter_avif_speed и нагрузку."

      - alert: ImageFilterBufferExhaustion
        expr: angie_image_filter_error_rate_415 > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Более 5% ошибок 415"
          description: "Увеличьте image_filter_buffer или ограничьте размеры оригиналов."

      - alert: ImageFilterThroughputDrop
        expr: sum(rate(angie_zone_requests_total{zone="image_filter_backend"}[5m])) < 100
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Пропускная способность image_filter упала ниже 100 rps"
          description: "Проверьте worker_processes, cgroups и доступность хранилища."
```

# Проверка загрузки алертов
curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.alertname | startswith("ImageFilter"))'

### См. также

- [Обзор модуля image_filter](./overview.md)
- [Безопасность и защита от DoS](./security.md)
- [Стратегии кэширования изображений](./caching.md)
