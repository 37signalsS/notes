# Оптимизация производительности Angie

## Определения

**Оптимизация производительности (Performance Optimization)** — комплекс конфигурационных и архитектурных мер, направленных на повышение пропускной способности сервера (RPS — Requests Per Second) и минимизацию задержек (Latency, TTFB — Time To First Byte) при наиболее эффективном использовании аппаратных ресурсов (CPU, RAM, Disk I/O, Network).

**Inflight Requests** — запросы, которые уже приняты сервером и находятся в процессе обработки, но ответ по которым еще не отправлен полностью. Учет этого показателя критичен для предотвращения перегрузки медленных бэкендов.

**Kernel TLS (kTLS)** — технология переноса операций симметричного шифрования TLS непосредственно в ядро ОС, что позволяет использовать механизм `sendfile()` для передачи данных по HTTPS без лишних копирований между пространством ядра и пользователя.

---

## Базовые концепции

Angie (форк Nginx) расширяет возможности стандартного веб-сервера, включая в себя инструменты уровня Enterprise, которые позволяют эффективно масштабировать нагрузку в современных высоконагруженных средах (2026 г.).

### Уникальные возможности Angie для оптимизации

1.  **Продвинутая балансировка (`least_time`):** Выбор бэкенда не просто по количеству соединений, а по реальному времени отклика с учетом незавершенных запросов (`inflight`).
2.  **Эффективный QUIC (eBPF):** Использование `quic_bpf` для привязки UDP-пакетов к конкретным воркерам, что обеспечивает стабильность сессий HTTP/3 даже при `reload` конфигурации.
3.  **Нативное сжатие Zstd:** Встроенная поддержка алгоритма Zstandard, обеспечивающего лучший баланс между CPU и степенью сжатия по сравнению с Gzip/Brotli.
4.  **Кластерная осведомленность:** Возможность синхронизации состояний (лимиты, сессии) между узлами кластера для предотвращения "локальных" перегрузок.
5.  **Нативная наблюдаемость:** Поддержка OpenTelemetry (OTel) и встроенный экспорт в Prometheus без накладных расходов на sidecar-контейнеры.

---

## Практические сценарии

### Сценарий 1: Системный тюнинг (sysctl)

Максимальная производительность Angie невозможна без настройки параметров ядра Linux, управляющих сетевым стеком.

**Пример конфигурации `/etc/sysctl.d/90-angie.conf`:**

```bash
# Увеличение очереди прослушиваемых сокетов (согласовать с backlog в Angie)
net.core.somaxconn = 65535

# Расширение диапазона эфемерных портов для исходящих соединений
net.ipv4.ip_local_port_range = 1024 65535

# Быстрое переиспользование сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1

# Запрет сброса TCP Slow Start после простоя (критично для Keep-Alive API)
net.ipv4.tcp_slow_start_after_idle = 0

# Использование алгоритма BBRv3 для управления перегрузкой
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
```

Применение: `sysctl --system`. Подробнее см. в разделе **[Тюнинг параметров ядра (sysctl)](../../../Linux/Core/kernel/sysctl.md)**.

---

### Сценарий 2: Многопоточность и асинхронный I/O

Для раздачи тяжелого контента или работы с медленными дисками необходимо выносить блокирующие операции в отдельные пулы потоков.

```nginx
# В основном контексте (main)
thread_pool dio_pool threads=32 max_queue=65536;

http {
    sendfile on;
    tcp_nopush on;
    
    # Асинхронный ввод-вывод через пулы потоков
    aio threads=dio_pool;
    
    # Ограничение размера чанка при sendfile (предотвращает забивание шины данных одним воркером)
    sendfile_max_chunk 1m;

    server {
        location /static/video/ {
            # Использование Direct I/O для обхода Page Cache при работе с большими файлами
            directio 8m;
            aio threads=dio_pool;
        }
    }
}
```

---

### Сценарий 3: Оптимизация TLS через Kernel TLS (kTLS)

kTLS радикально снижает нагрузку на CPU при передаче данных через HTTPS.

```nginx
http {
    # Требует поддержки в ядре (modprobe tls) и OpenSSL 3.0+
    ssl_conf_command Options +KTLS;

    server {
        listen 443 ssl;
        ssl_certificate /etc/angie/ssl/fullchain.pem;
        ssl_certificate_key /etc/angie/ssl/privkey.pem;

        # kTLS работает максимально эффективно в связке с sendfile
        sendfile on;
    }
}
```

---

### Сценарий 4: Тюнинг HTTP/3 и eBPF

В отличие от Nginx, Angie использует eBPF для сохранения QUIC-сессий при перезагрузке процесса.

```nginx
# В основном контексте (main)
quic_bpf on;

http {
    server {
        listen 443 quic reuseport;
        http3 on;

        # Generic Segmentation Offload для UDP (снижает нагрузку на CPU)
        quic_gso on;
        
        # Информирование клиента о поддержке HTTP/3
        add_header Alt-Svc 'h3=":443"; ma=86400';
    }
}
```
Подробнее: **[Конфигурация HTTP/2 и HTTP/3 в Nginx/Angie](../../Nginx/Performance/nginx_http_versions.md)**.

---

### Сценарий 5: Продвинутая балансировка и плавный старт

Использование `least_time` с учетом незавершенных запросов позволяет обходить бэкенды, которые начинают деградировать.

```nginx
upstream backend_api {
    zone upstream_api 1m;
    
    # inflight: учитывать запросы в обработке (самый точный метод для High Load)
    # last_byte: расчет по времени получения полного ответа
    least_time last_byte inflight;
    
    # slow_start: постепенный ввод сервера в работу (защита от "шока" холодного кэша)
    server 10.0.0.1:8080 slow_start=30s;
    server 10.0.0.2:8080 slow_start=30s;

    # Поддержание постоянных соединений с бэкендами
    keepalive 64;
    keepalive_requests 1000;
}
```

---

### Сценарий 6: Нативная наблюдаемость (Prometheus и OTel)

Angie позволяет собирать метрики без внешних агентов, что снижает Latency на сбор статистики.

```nginx
http {
    # Нативный экспорт в Prometheus
    prometheus api /p8s;

    server {
        listen 127.0.0.1:8080;
        
        location /status {
            # Встроенный API (JSON формат)
            api /status/;
            allow 127.0.0.1;
            deny all;
        }

        location /p8s {
            # Эндпоинт для скрейпинга Prometheus
            prometheus;
        }
    }
}
```

---

## Дополнительная информация

### Рекомендации по тюнингу

1.  **PCRE JIT:** Всегда включайте `pcre_jit on;` для ускорения регулярных выражений.
2.  **Open File Cache:** `open_file_cache max=10000 inactive=60s;` — кэширование дескрипторов открытых файлов значительно снижает количество системных вызовов при раздаче статики.
3.  **Сжатие Zstd:** Используйте `zstd on;` вместо Gzip для API-ответов, это дает выигрыш до 20-30% по трафику при меньшем потреблении CPU.
4.  **Бенчмаркинг:** В 2026 году для High Load тестов рекомендуется использовать `wrk2` или `k6`, так как они корректно учитывают Coordinated Omission.

### Сценарий 7: Оптимизация RPS при исчерпании ресурсов CPU и отсутствии бюджета

Когда вертикальное масштабирование невозможно (нет свободных CPU, нет бюджета на новые инстансы), прирост RPS достигается только за счет **повышения эффективности** текущих ресурсов.

#### 7.1. Диагностика: подтверждение CPU-bound

```bash
# 1. PSI — давление на CPU (среднее за 10с > 10% = перегруз)
cat /proc/pressure/cpu

# 2. top/htop — утилизация пользовательского пространства (us) vs системного (sy)
# sy > 30% — накладные расходы ядра (системные вызовы, прерывания, контекстные переключения)
# us ~ 100% — нагрузка от бизнес-логики приложения

# 3. perf top — горячие функции в user-space
perf top -g --ns --all-cpus

# 4. bpftrace — системные вызовы
bpftrace -e 'tracepoint:syscalls:sys_enter_* { @[probe] = count(); }'
```

#### 7.2. Оптимизация на уровне ОС и сети (бесплатно, высокий ROI)

| Мера | Эффект | Команда / Конфиг |
|------|--------|------------------|
| **RPS/RFS (Receive Packet/ Flow Steering)** | Распределение сетевых прерываний по ядрам, снятие горячего ядра CPU0 | `echo ffffffff > /sys/class/net/eth0/queues/rx-0/rps_cpus` |
| **XPS (Transmit Packet Steering)** | Привязка TX очередей к ядрам, обрабатывающим приложение | `echo ffffffff > /sys/class/net/eth0/queues/tx-0/xps_cpus` |
| **IRQ Affinity** | Жесткая привязка прерываний NIC к выделенным ядрам | `irqbalance --banlist=0-3` (оставить ядра 0-3 под приложение) |
| **TCP BBR v3** | Снижение ретрансляций, лучшее использование полосы | `net.ipv4.tcp_congestion_control=bbr` |
| **SO_REUSEPORT** | Множественные сокеты прослушивания на одном порту, балансировка в ядре | `reuseport` в `listen` директиве Angie |
| **Busy Poll / busy_read** | Опрос сокетов в пользовательском пространстве без системных вызовов | `net.core.busy_poll=50`, `net.core.busy_read=50` |

**Пример sysctl для high-RPS без бюджета:**
```bash
# /etc/sysctl.d/99-rps-optimization.conf
net.core.netdev_max_backlog = 250000
net.core.somaxconn = 65535
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
net.ipv4.tcp_fastopen = 3
net.core.busy_poll = 50
net.core.busy_read = 50
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_slow_start_after_idle = 0
# RPS/RFS настраивается динамически через /sys/class/net/
```

#### 7.3. Оптимизация Angie/Nginx конфигурации

```nginx
# main context
worker_processes auto;
worker_cpu_affinity auto;        # Привязка воркеров к ядрам
worker_rlimit_nofile 1048576;    # Дескрипторы

#_thread_pool для асинхронного I/O (не блокирует event loop)
thread_pool default threads=32 max_queue=65536;

http {
    # Zero-copy + kTLS = минимальный CPU на шифрование/передачу
    sendfile on;
    sendfile_max_chunk 512k;
    tcp_nopush on;
    tcp_nodelay on;
    aio threads=default;

    # kTLS (OpenSSL 3.0+, Linux 4.13+)
    ssl_conf_command Options KTLS;
    ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;

    # HTTP/2 оптимизация
    http2_max_concurrent_streams 128;
    http2_max_requests 1000;

    # Реusoport — балансировка входящих соединений ядром
    server {
        listen 443 ssl http2 reuseport;
        listen 443 quic reuseport;  # HTTP/3
        http3 on;
        quic_gso on;                # GSO для UDP (CPU offload)
    }

    # Сжатие Zstd — лучший ratio/CPU чем gzip/brotli
    zstd on;
    zstd_comp_level 3;              # Баланс скорость/сжатие

    # Кэш дескрипторов файлов
    open_file_cache max=20000 inactive=30s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # Ограничение буферов — предотвращает OOM и забивание CPU memcpy
    client_body_buffer_size 16k;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 4k;
}
```

#### 7.4. Архитектурные паттерны без затрат

| Паттерн | Что делает | Результат |
|---------|------------|-----------|
| **Кэширование на уровне Angie** (`proxy_cache`, `proxy_cache_valid`) | Снижает запросы к бэкенду на 60-90% для читаемых данных | RPS растет пропорционально hit-rate, CPU бэкенда освобождается |
| **Кэширование ответов в `shared_dict` (lua/shared memory)** | Микро-кэш для часто меняющихся данных (конфиг, фичи) | Исключает лишние RPC к config-service |
| **Connection Pooling к бэкендам** (`keepalive`, `keepalive_requests`) | Исключает накладные расходы TCP/TLS handshake на каждый запрос | -30-50% CPU на proxying, -Latency |
| **Request Coalescing** (`proxy_cache_lock`, `proxy_cache_use_stale updating`) | Объединяет одновременные запросы за одним и тем же ключом | Предотвращает thundering herd при cold cache |
| **Rate Limiting на входе** (`limit_req_zone`, `limit_conn_zone`) | Защищает от перегрузки, гарантирует качество обслуживания | Предотвращает Kingman-эффект при U→100% |

#### 7.5. Применение на уровне приложения (если есть доступ к коду)

1. **Профилирование (Continuous Profiling — Pyroscope/Parca):** Найти top-5 функций по CPU-time.
2. **Алгоритмическая оптимизация:** O(N²) → O(N log N), убрать N+1 запросы к БД.
3. **Кэширование в памяти приложения:** LRU-кэш для горячих вычислений.
4. **Batch-обработка:** Объединение мелких операций в батчи (DB bulk insert, pipeline Redis).
5. **Асинхронность:** Перевод блокирующих вызовов в async/await, пулы потоков для CPU-bound задач.

#### 7.6. Чек-лист верификации (валидация без нагрузочного стенда)

```bash
# 1. Сравнить CPU utilization до/после на той же нагрузке
# Цель: us% снизился, sy% не вырос

# 2. Проверить IRQ баланс
cat /proc/interrupts | grep -E "eth|rx|tx"
# Прерывания должны равномерно распределяться по ядрам приложения

# 3. Проверить очередь сокетов
ss -ltni | grep -E "Send-Q|Recv-Q"
# Send-Q/Recv-Q должны быть близки к 0 в steady state

# 4. Метрики Angie (Prometheus)
# angie_http_requests_total / rate(angie_nginx_process_cpu_seconds_total[5m])
# → RPS per CPU core. Цель: > 10k RPS/core на статике, > 2k RPS/core на proxy
```

#### 7.7. Когда оптимизации исчерпаны — стратегия выхода

Если после всех мер RPS всё равно не устраивает и **нет бюджета на железо**:
1. **Деградация функционала:** Отключить некритичные фичи (рекомендации, аналитика, тяжелые отчеты) под флагом.
2. **Приоритизация трафика:** `limit_req` с `burst` и `nodelay` для VIP-клиентов, `dryrun` для остальных.
3. **Клиентская оптимизация:** Внедрить `ETag`/`If-None-Match`, `Cache-Control: immutable` для статики — снижает входящий RPS.
4. **Архитектурный сдвиг:** Перевод части нагрузки в async (очереди, webhook'и) — сглаживает пики, не требует пиковых ресурсов.

---

### См. также

- [Тюнинг производительности Nginx](../../Nginx/Performance/nginx_performance_tuning.md)
- [Серверное кэширование и производительность](../../Nginx/Performance/Caching/proxy_caching.md)
- [Защита от DoS-атак в Angie](./dos_protection.md)
- [Обзор возможностей Angie](../angie_overview.md)
- [Балансировка нагрузки HTTP в Angie](../angie_http_load_balancing.md)
- [Методология тестирования производительности](../../Testing/performance_testing_methodology.md)
- [Законы масштабируемости](../../Concepts/High_Availability/scalability_laws.md)
- [Linux RSS/RPS/RFS](../../Linux/Networking/Concepts/rss_rps_rfs.md)
