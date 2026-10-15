# Мониторинг HAProxy

**Актуально для:** HAProxy 3.0+ / 2.8 LTS (PROMEX, Runtime API, Stats, Logs)

## Определения

**Prometheus Native Exporter (PROMEX)** — встроенный в HAProxy сервис экспорта метрик в формате Prometheus, компилируемый с флагом `USE_PROMEX=1` (включен по умолчанию в официальных пакетах) и вызываемый директивой `http-request use-service prometheus-exporter`.

**Runtime API (Stats Socket)** — двунаправленный интерфейс управления и телеметрии через UNIX-сокет (или TCP), позволяющий инспектировать внутренние структуры данных, считывать счетчики и изменять параметры балансировщика в реальном времени без перезагрузки процесса.

**HAProxy Stats UI** — встроенный веб-интерфейс HTML/CSV, предоставляющий визуальную цветовую панель текущего состояния всех фронтендов, бэкендов, серверов и слушателей.

**Stick Table** — высокопроизводительное key-value хранилище в оперативной памяти процесса HAProxy для отслеживания состояния клиентов (rate limiting, счетчики ошибок, параллельные сессии) и агрегации телеметрии без внешних СУБД.

**Golden Signals** — ключевые метрики мониторинга распределенных систем по классификации Google SRE: задержка (Latency), трафик (Traffic), ошибки (Errors) и насыщенность (Saturation).

**RED Method** — модель мониторинга сервисов, ориентированная на пользовательский опыт: частота запросов (Rate), число ошибок (Errors) и длительность обработки (Duration).

**USE Method** — модель мониторинга инфраструктурных ресурсов: утилизация (Utilization), насыщенность/очередь (Saturation) и системные ошибки (Errors).

**Termination Flags (`%ts`)** — двухсимвольное поле в логах HAProxy, кодирующее причину закрытия сессии и фазу жизненного цикла соединения, на которой произошел разрыв.

**Тайминги сессий (`%TR/%Tw/%Tc/%Tr/%Ta`)** — детальная раскладка времени обработки запроса в миллисекундах: время чтения запроса клиента, нахождение в очереди, установка TCP-соединения с бэкендом, ожидание ответа приложения и суммарная длительность.

**W3C TraceContext** — открытый стандарт распределенной трассировки (`traceparent`, `tracestate`), позволяющий связать запись в логе балансировщика с единым идентификатором сквозного трейса микросервисной архитектуры.

---

## Основные концепции

### Архитектура наблюдаемости HAProxy

HAProxy предоставляет четыре основных канала для получения данных мониторинга и телеметрии в bare-metal и виртуальных средах:

```
┌────────────────────────────────────────────────────────────────────────┐
│                             HAProxy Process                            │
│                                                                        │
│  ┌────────────────┐   ┌────────────────┐   ┌────────────────────────┐  │
│  │   Frontend /   │   │  Stick Tables  │   │      Connection /      │  │
│  │   Backend      │   │  (In-Memory)   │   │      Server Pools      │  │
│  └───────┬────────┘   └───────┬────────┘   └───────────┬────────────┘  │
│          │                    │                        │               │
│  ┌───────▼────────────────────▼────────────────────────▼────────────┐  │
│  │                     Internal Shared Counters                     │  │
│  └───────┬────────────────────┬────────────────────────┬────────────┘  │
└──────────┼────────────────────┼────────────────────────┼───────────────┘
           │                    │                        │
           ▼                    ▼                        ▼
 ┌──────────────────┐ ┌──────────────────┐    ┌─────────────────────┐
 │  PROMEX Service  │ │   Runtime API    │    │ Syslog Log-Format   │
 │   (/metrics)     │ │  (UNIX Socket)   │    │ (Timings, Flags)    │
 └─────────┬────────┘ └─────────┬────────┘    └──────────┬──────────┘
           │                    │                        │
           ▼                    ▼                        ▼
   Prometheus Scrape     socat CLI / Scripts      Vector / Promtail / Loki
```

| Канал | Механизм передачи | Протокол / Формат | Основное назначение |
| :--- | :--- | :--- | :--- |
| **PROMEX** | HTTP endpoint (`/metrics`) | Prometheus text exposition | Системные и прикладные метрики (time-series) для Prometheus / VictoriaMetrics |
| **Runtime API** | UNIX domain socket | Текстовый CLI / CSV | Интерактивная диагностика дежурным инженером, инспекция таблиц, динамическое управление |
| **Stats UI** | HTTP endpoint (`/stats`) | HTML / CSV | Оперативная визуальная панель для дежурной смены без внешних зависимостей |
| **Syslog Events** | UNIX DGRAM / UDP / TCP | Структурированный JSON / RFC 5424 | Позапросный аудит, расследование инцидентов, расчет SLA/SLI по логам |

---

### Встроенные метрики Prometheus (PROMEX)

PROMEX считывает накопленные счетчики напрямую из адресного пространства процессов HAProxy, не создавая процессов-посредников и не производя промежуточной сериализации в CSV.

#### Ключевые группы метрик

1. **Процесс и ресурсы (USE Method):**
   - `haproxy_process_nbthread` — число активных рабочих потоков.
   - `haproxy_process_uptime_seconds` — время непрерывной работы процесса.
   - `haproxy_process_current_tasks` — число задач в очереди планировщика HAProxy.
   - `haproxy_process_idle_time_percent` — процент времени простоя циклов событий (показатель запаса производительности CPU).
   - `haproxy_process_max_connections` / `haproxy_process_current_connections` — лимит и текущее число открытых клиентских соединений.
   - `haproxy_process_max_sockets` / `haproxy_process_current_sockets` — утилизация файловых дескрипторов (FD).

2. **Фронтенды (Входящий трафик и ошибки):**
   - `haproxy_frontend_connections_total` — общее число принятых TCP-соединений.
   - `haproxy_frontend_http_requests_total` — общее число поступивших HTTP-запросов.
   - `haproxy_frontend_http_responses_total{code="5xx"}` — счетчик кодов ответов, сгенерированных на уровне прокси.
   - `haproxy_frontend_bytes_in_total` / `haproxy_frontend_bytes_out_total` — объем переданного сетевого трафика.
   - `haproxy_frontend_request_errors_total` — ошибки чтения запросов от клиентов (обрывы, таймауты).
   - `haproxy_frontend_denied_connections_total` — соединения, заблокированные правилами фильтрации ACL.

3. **Бэкенды и пулы балансировки (RED Method):**
   - `haproxy_backend_status{status="up|down"}` — интегральный статус доступности пула (1 — доступен, 0 — недоступен).
   - `haproxy_backend_active_servers` — число работоспособных серверов, готовых принимать трафик.
   - `haproxy_backend_backup_servers` — число серверов в резерве.
   - `haproxy_backend_current_queue` — число запросов, ожидающих освобождения слота подключения к бэкенду.
   - `haproxy_backend_http_responses_total{code=~"5.."}` — ответы с ошибками от серверов приложений.
   - `haproxy_backend_connection_errors_total` — неудачные попытки подключения к серверам бэкенда.
   - `haproxy_backend_redispatch_warnings_total` — количество перенаправлений запроса на другой сервер из-за сбоя выбранного.

4. **Серверы (Индивидуальное состояние узлов):**
   - `haproxy_server_status{status="up|down|maint|drain"}` — текущее оперативное состояние каждого сервера.
   - `haproxy_server_check_status` — результат последнего health check (1 — успешен, 0 — провален).
   - `haproxy_server_check_duration_seconds` — время отклика проверки состояния.
   - `haproxy_server_current_sessions` — число параллельно обрабатываемых сессий конкретным сервером.
   - `haproxy_server_weight` — текущий эффективный вес сервера в алгоритме распределения.

---

### Runtime API: Архитектура сокета и уровни доступа

Runtime API организуется через UNIX domain socket с механизмом `expose-fd listeners`, позволяющим сохранять сокет открытым при перезагрузках master-worker процесса.

- **Уровни доступа (`level`):**
  - `user` — только чтение базовой статистики (`show info`, `show stat`).
  - `operator` — просмотр таблиц, включение/выключение проверок состояния.
  - `admin` — изменение весов серверов, перевод в maintenance/drain, сброс счетчиков, управление SSL-сертификатами и ACL.
- **Многопоточность:** начиная с HAProxy 2.4+ сокет автоматически распределяет входящие управляющие команды по рабочим потокам без блокировки основного цикла обработки сетевых пакетов.

---

### Анатомия логов HAProxy: Тайминги и флаги завершения

При возникновении задержек или 5xx ошибок детальный анализ логов HAProxy позволяет локализовать сбой за минуты без снятия дампов трафика.

#### Формула таймингов (`%TR/%Tw/%Tc/%Tr/%Ta`)

Каждое HTTP-событие протоколируется с метрикой в формате `TR/Tw/Tc/Tr/Ta` (в миллисекундах):

```
Клиент                      HAProxy                       Сервер бэкенда
  │                            │                                 │
  ├────── Запрос (заголовки) ─►│                                 │   ──► %TR (чтение запроса)
  │                            ├── Очередь бэкенда ──┐           │   ──► %Tw (ожидание слота)
  │                            │◄────────────────────┘           │
  │                            ├────── TCP SYN ─────────────────►│
  │                            │◄───── TCP SYN-ACK ──────────────┤   ──► %Tc (установка TCP)
  │                            ├────── Передача запроса ────────►│
  │                            │◄───── Заголовки ответа ─────────┤   ──► %Tr (время ответа приложения)
  │                            │                                 │
  │◄───── Потоковая отдача ────┤                                 │   ──► %Ta (полная длительность)
```

| Тайминг | Параметр | Что измеряет | Что означает аномальный рост |
| :--- | :--- | :--- | :--- |
| **`%TR`** | Request read time | Время от первого байта запроса до окончания заголовков HTTP | Проблемы в сети клиента, мобильные клиенты с плохим каналом, атаки Slowloris |
| **`%Tw`** | Queue wait time | Время нахождения запроса во внутренней очереди ожидания свободного `maxconn` | Перегрузка серверов бэкенда, нехватка мощностей, слишком низкий `maxconn` |
| **`%Tc`** | Connect time | Длительность трехстороннего рукопожатия TCP с сервером бэкенда | Переполнение очереди SYN (`listen backlog`), сетевые потери, перегрузка ядра бэкенда |
| **`%Tr`** | Response time | Время от отправки запроса до получения первого байта заголовка ответа | Медленный код приложения, тяжелые SQL-запросы, зависание воркеров приложения |
| **`%Ta`** | Total active time | Время от приема соединения до передачи последнего байта клиенту | Скачивание тяжелых файлов клиентом, длительные соединения SSE / WebSocket |

#### Расшифровка кодов завершения (`%ts` — Termination Flags)

Флаг завершения состоит из двух символов (например, `sH`, `cD`, `PR`):
- **Первый символ:** компонент или событие, инициировавшее закрытие:
  - `s` — Сервер бэкенда закрыл соединение или вернул ошибку.
  - `c` — Клиент прервал соединение до завершения передачи.
  - `p` — Прокси (HAProxy) принудительно разорвал соединение (сработал таймаут, правило безопасности или лимит).
  - `R` — Исчерпание системных ресурсов на хосте балансировщика.
  - `I` — Внутренняя ошибка процесса HAProxy.
  - `d` — Передача данных завершена штатно со стороны бэкенда.
  - `K` — Соединение сброшено оператором (через Runtime API).
- **Второй символ:** фаза обработки, на которой произошел разрыв:
  - `H` — Ожидание заголовков ответа сервера приложения (Server Response Headers).
  - `C` — Установка TCP-соединения с сервером (Connection establishment).
  - `Q` — Нахождение в очереди бэкенда (Queue).
  - `R` — Чтение заголовков запроса от клиента (Request).
  - `D` — Фаза передачи тела ответа (Data transfer).
  - `L` — Передача последнего пакета данных (Last data).

| Флаг `%ts` | Типичный HTTP-код | Интерпретация для инженера |
| :--- | :--- | :--- |
| **`sH`** | 504 Gateway Timeout | Бэкенд принял запрос, но не ответил за время `timeout server`. Зависание приложения/БД. |
| **`sC`** | 503 Service Unavailable | Сбой установки TCP-соединения с сервером за время `timeout connect` (Connection Refused / RST). |
| **`sQ`** | 503 Service Unavailable | Запрос простоял во внутренней очереди дольше, чем `timeout queue`. Все слоты бэкенда заняты. |
| **`cD`** | 200 / 206 (прерван) | Пользователь закрыл вкладку в браузере или нажал отмену во время отдачи данных. |
| **`cR`** | 408 Request Timeout | Клиент открыл TCP-сокет, но не передал полные HTTP-заголовки за время `timeout http-request`. |
| **`PR`** | 403 Forbidden | Запрос заблокирован правилами безопасности HAProxy (`http-request deny`, ACL, rate-limit). |
| **`CC`** | 200 OK | Штатное завершение сессии по инициативе клиента (Connection: close). |

---

### Сквозная трассировка (W3C TraceContext)

HAProxy функционирует как сквозной шлюз L7-трафика. Чтобы события в логах балансировщика коррелировали со спанами в Jaeger или Tempo:
1. Балансировщик принимает стандартный заголовок `traceparent` (формат: `00-<trace_id>-<span_id>-<flags>`).
2. Если клиент не передал заголовок, HAProxy генерирует уникальный идентификатор сессии с помощью `unique-id-format`.
3. Значение заголовка `traceparent` выводится в структурированный лог через `%[req.hdr(traceparent)]`, связывая лог балансировщика с трейсом прикладного кода.

---

## Практические сценарии

### Сценарий 1: Настройка встроенного экспортера PROMEX и Web Stats UI

Разделение трафика клиентов и мониторинга: метрики и интерфейс статистики выносятся на отдельный локальный порт с защитой по ACL и базовой аутентификацией.

```haproxy
global
    log /dev/log local0 info
    stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners
    stats timeout 30s
    user haproxy
    group haproxy
    daemon
    master-worker

defaults
    log     global
    mode    http
    option  httplog
    option  dontlognull
    timeout connect 5s
    timeout client  50s
    timeout server  50s

# Выделенный интерфейс для мониторинга и метрик
frontend prometheus_and_stats
    bind 127.0.0.1:8404
    bind 192.168.10.15:8404
    mode http
    no log

    # Ограничение доступа по подсетям доверенного мониторинга
    acl is_monitoring_network src 127.0.0.1 192.168.10.0/24
    http-request deny if !is_monitoring_network

    # Нативный эндпоинт метрик Prometheus
    http-request use-service prometheus-exporter if { path /metrics }

    # Интерактивная HTML-панель статистики HAProxy
    stats enable
    stats uri /stats
    stats refresh 10s
    stats auth admin:SuperSecretSysAdminPass2026
    stats show-node
    stats show-legends

# Основной рабочий фронтенд
frontend web_front
    bind *:80
    bind *:443 ssl crt /etc/haproxy/certs/site.pem
    default_backend app_servers

backend app_servers
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200
    server app01 10.0.0.11:8080 check inter 2s fall 3 rise 2
    server app02 10.0.0.12:8080 check inter 2s fall 3 rise 2
```

**Проверка работы экспортера:**

```bash
# Проверка синтаксиса перед применением
haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Запрос метрик с хоста мониторинга
curl -s http://127.0.0.1:8404/metrics | grep -E "^haproxy_backend_status"
# → haproxy_backend_status{backend="app_servers",status="up"} 1

# Запрос метрик с фильтрацией по scope для экономии ресурсов
curl -s "http://127.0.0.1:8404/metrics?scope=backend,frontend" | head -n 5
# → # HELP haproxy_frontend_current_sessions Current number of active sessions
# → # TYPE haproxy_frontend_current_sessions gauge
```

---

### Сценарий 2: Настройка и эксплуатация Runtime API через UNIX-сокет

Управление балансировщиком и снятие мгновенных отчетов через утилиту `socat`.

```bash
# 1. Проверка прав и доступности сокета
ls -la /run/haproxy/admin.sock
# → srw-rw---- 1 haproxy haproxy 0 Oct 14 20:00 /run/haproxy/admin.sock

# 2. Вывод сводной информации о процессе и нагрузке
echo "show info" | socat stdio /run/haproxy/admin.sock
# → Name: HAProxy
# → Version: 3.0.4
# → Release_date: 2024/09/10
# → Uptime_sec: 86420
# → Process_num: 1
# → Pid: 1420
# → Nbthread: 4
# → Tasks: 12
# → CurrConns: 340
# → Maxpipes: 0

# 3. Получение расширенной статистики бэкендов в CSV
echo "show stat" | socat stdio /run/haproxy/admin.sock | head -n 2
# → # pxname,svname,qcur,qmax,scur,smax,slim,stot,bin,bout,dreq,dresp,ereq,econ,eresp,wretr,wredis,status...
# → app_servers,FRONTEND,,,0,12,2000,1540,120530,948210,0,0,0,,,,OPEN...

# 4. Просмотр ошибок TCP/HTTP за последнее время
echo "show errors" | socat stdio /run/haproxy/admin.sock
# → Total events captured: 0

# 5. Плавный вывод сервера в регламентные работы (drain)
echo "set server app_servers/app01 state drain" | socat stdio /run/haproxy/admin.sock
# → (пустой вывод свидетельствует об успешном применении)

# 6. Проверка обновленного статуса сервера
echo "show servers state app_servers" | socat stdio /run/haproxy/admin.sock | grep "app01"
# → 1 app_servers 1 app01 10.0.0.11 2 2 1 1 50 1 0 0 ... DRAIN

# 7. Возврат сервера в рабочий пул
echo "set server app_servers/app01 state ready" | socat stdio /run/haproxy/admin.sock
```

---

### Сценарий 3: Настройка структурированного JSON-логирования с таймингами

Логирование запросов в формате JSON на локальный демон Syslog (`rsyslog`) с фиксацией таймингов, кодов завершения и идентификаторов трассировки.

```haproxy
global
    # Отправка логов на локальный сокет rsyslog
    log /dev/log local0 info

frontend web_front
    bind *:80
    mode http
    
    # Генерация Correlation ID при отсутствии внешнего
    unique-id-format %[uuid()]
    http-request set-header X-Request-ID %[unique-id] if !{ req.hdr(X-Request-ID) -m found }

    # Структурированный JSON-формат лога
    log-format '{"timestamp":"%t","client_ip":"%ci","client_port":%cp,"frontend":"%f","backend":"%b","server":"%s","status":%ST,"bytes_read":%B,"termination_flags":"%ts","time_request_ms":%TR,"time_queue_ms":%Tw,"time_connect_ms":%Tc,"time_response_ms":%Tr,"time_total_ms":%Ta,"retries":%rq,"http_method":"%HM","http_path":"%HP","http_version":"%HV","request_id":"%[req.hdr(X-Request-ID)]","traceparent":"%[req.hdr(traceparent)]"}'
    
    default_backend app_servers
```

**Конфигурация `/etc/rsyslog.d/49-haproxy.conf` на хосте Linux:**

```config
# Запись логов HAProxy в отдельный файл без буферизации
$AddUnixListenSocket /var/lib/haproxy/dev/log

if ($programname == 'haproxy') then {
    action(type="omfile" file="/var/log/haproxy/access.json.log" flushOnTXEnd="on")
    stop
}
```

**Конфигурация ротации логов `/etc/logrotate.d/haproxy`:**

```config
/var/log/haproxy/*.log {
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    sharedscripts
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate
    endscript
}
```

---

### Сценарий 4: Развертывание внешнего haproxy_exporter (systemd)

Служебный сценарий: если экземпляр HAProxy запущен без поддержки PROMEX (например, устаревшая сборка или специфические требования изоляции сокета), сбор метрик организуется через официальный бинарный экспортер [haproxy_exporter](https://github.com/prometheus/haproxy_exporter).

```ini
# /etc/systemd/system/haproxy_exporter.service
[Unit]
Description=Prometheus HAProxy Exporter
After=network.target haproxy.service
Requires=haproxy.service

[Service]
Type=simple
User=haproxy
Group=haproxy
ExecStart=/usr/local/bin/haproxy_exporter \
    --haproxy.scrape-uri="unix:/run/haproxy/admin.sock" \
    --web.listen-address="127.0.0.1:9101" \
    --web.telemetry-path="/metrics"
Restart=always
RestartSec=5s

# Ограничения безопасности процесса
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/run/haproxy

[Install]
WantedBy=multi-user.target
```

**Управление сервисом экспортера:**

```bash
systemctl daemon-reload
systemctl enable --now haproxy_exporter
# → Created symlink /etc/systemd/system/multi-user.target.wants/haproxy_exporter.service

systemctl status haproxy_exporter --no-pager
# → Active: active (running) since ...

curl -s http://127.0.0.1:9101/metrics | grep "haproxy_up"
# → haproxy_up 1
```

---

### Сценарий 5: Production-правила алертинга Prometheus

Готовый набор алертов для Prometheus / Alertmanager на основе Golden Signals и RED-методологии:

```yaml
# /etc/prometheus/rules/haproxy_alerts.yml
groups:
  - name: haproxy_production_alerts
    rules:
      - alert: HAProxyBackendDown
        expr: haproxy_backend_status{status="up"} == 0
        for: 1m
        labels:
          severity: critical
          tier: networking
        annotations:
          summary: "Пул серверов {{ $labels.backend }} полностью недоступен"
          description: "Все серверы в бэкенде {{ $labels.backend }} признаны неработоспособными проверками состояния healthcheck."

      - alert: HAProxyBackendFewServersActive
        expr: haproxy_backend_active_servers < 2 and haproxy_backend_active_servers > 0
        for: 2m
        labels:
          severity: warning
          tier: networking
        annotations:
          summary: "Остался только один активный сервер в бэкенде {{ $labels.backend }}"
          description: "Резервирование пула снижено. Любой последующий сбой приведет к деградации сервиса."

      - alert: HAProxyHigh5xxErrorRate
        expr: |
          (
            sum by (backend) (rate(haproxy_backend_http_responses_total{code=~"5.."}[5m]))
            /
            sum by (backend) (rate(haproxy_backend_http_responses_total[5m]))
          ) > 0.05
        for: 3m
        labels:
          severity: critical
          tier: application
        annotations:
          summary: "Доля 5xx ошибок бэкенда {{ $labels.backend }} превышает 5%"
          description: "Текущий уровень ошибок бэкенда составляет {{ $value | humanizePercentage }}."

      - alert: HAProxyHighBackendLatencyP95
        expr: |
          histogram_quantile(0.95, sum by (le, backend) (rate(haproxy_backend_http_request_duration_seconds_bucket[5m]))) > 1.5
        for: 5m
        labels:
          severity: warning
          tier: performance
        annotations:
          summary: "Задержка P95 бэкенда {{ $labels.backend }} превысила 1.5 секунды"
          description: "P95 времени обработки составляет {{ $value | humanizeDuration }}. Проверьте время отклика баз данных и приложений."

      - alert: HAProxyQueueSaturating
        expr: haproxy_backend_current_queue > 50
        for: 2m
        labels:
          severity: warning
          tier: performance
        annotations:
          summary: "Очередь запросов в бэкенд {{ $labels.backend }} переполнена"
          description: "В очереди ожидает {{ $value }} запросов. Серверы не успевают обрабатывать входящий поток."

      - alert: HAProxyServerFlapping
        expr: changes(haproxy_server_status{status="up"}[15m]) > 4
        for: 1m
        labels:
          severity: warning
          tier: infrastructure
        annotations:
          summary: "Нестабильный сервер {{ $labels.server }} в пуле {{ $labels.backend }}"
          description: "Сервер изменил статус работоспособности более 4 раз за 15 минут. Проверьте таймауты healthcheck."

      - alert: HAProxyProcessMaxConnectionsNearLimit
        expr: (haproxy_process_current_connections / haproxy_process_max_connections) > 0.85
        for: 5m
        labels:
          severity: warning
          tier: system
        annotations:
          summary: "Лимит клиентских соединений HAProxy исчерпан на 85%"
          description: "Текущие соединения: {{ $value | humanizePercentage }} от максимума. Требуется тюнинг maxconn и sysctl."
```

---

### Сценарий 6: Сбор и парсинг логов в стек Promtail + Loki

Конфигурация агента Promtail для чтения локальных JSON-логов HAProxy, динамического извлечения labels и отправки в хранилище Loki:

```yaml
# /etc/promtail/promtail-config.yml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /var/lib/promtail/positions.yaml

clients:
  - url: http://192.168.10.20:3100/loki/api/v1/push

scrape_configs:
  - job_name: haproxy_json_logs
    static_configs:
      - targets:
          - localhost
        labels:
          job: haproxy
          environment: production
          __path__: /var/log/haproxy/access.json.log

    pipeline_stages:
      # Парсинг JSON структуры
      - json:
          expressions:
            client_ip: client_ip
            frontend: frontend
            backend: backend
            server: server
            status: status
            termination_flags: termination_flags
            time_queue_ms: time_queue_ms
            time_connect_ms: time_connect_ms
            time_response_ms: time_response_ms
            time_total_ms: time_total_ms
            traceparent: traceparent

      # Вынесение ключевых атрибутов в метки Loki
      - labels:
          frontend:
          backend:
          server:
          status:
          termination_flags:

      # Экспорт метрик из логов в Prometheus endpoint Promtail
      - metrics:
          haproxy_log_5xx_total:
            type: Counter
            description: "Total 5xx logged by HAProxy"
            source: status
            config:
              value: "5.."
              action: inc
```

---

### Сценарий 7: Защита бэкендов и мониторинг аномалий через Stick Table

Использование оперативной памяти балансировщика для подсчета RPS и ошибок клиентов, изоляции агрессивных сканеров и экспорта статистики:

```haproxy
backend app_servers
    balance roundrobin

    # Таблица на 200k IP адресов, хранение 5 минут
    # Отслеживание скорости запросов за 10с и скорости 4xx ошибок за 10с
    stick-table type ip size 200k expire 5m store http_req_rate(10s),http_err_rate(10s),conn_cur

    # Привязка текущего сессионного счетчика к IP клиента
    http-request track-sc0 src table app_servers

    # Мониторинг и блокировка при превышении 100 запросов в 10 секунд
    acl is_flooding sc0_http_req_rate(app_servers) gt 100
    http-request deny deny_status 429 if is_flooding

    # Мониторинг перебора (brute-force): блокировка при более 20 ошибок 4xx за 10 сек
    acl is_scanner sc0_http_err_rate(app_servers) gt 20
    http-request deny deny_status 403 if is_scanner

    server app01 10.0.0.11:8080 check
    server app02 10.0.0.12:8080 check
```

**Инспекция содержимого Stick Table через Runtime API:**

```bash
# Просмотр первых записей таблицы и счетчиков
echo "show table app_servers" | socat stdio /run/haproxy/admin.sock
# → # table: app_servers, type: ip, size:204800, used:3
# → 0x7f83b4001c30: key=192.168.1.100 use=0 exp=284000 conn_cur=1 http_req_rate(10000)=12 http_err_rate(10000)=0
# → 0x7f83b4002e10: key=198.51.100.44 use=0 exp=298000 conn_cur=8 http_req_rate(10000)=140 http_err_rate(10000)=25

# Фильтрация только нарушителей лимитов
echo "show table app_servers data.http_req_rate gt 50" | socat stdio /run/haproxy/admin.sock
# → 0x7f83b4002e10: key=198.51.100.44 use=0 exp=298000 conn_cur=8 http_req_rate(10000)=140 http_err_rate(10000)=25
```

---

## Операции и команды

Таблица оперативных команд дежурного инженера и SRE через Runtime API (`/run/haproxy/admin.sock`):

| Команда | Назначение | Пример использования |
| :--- | :--- | :--- |
| **`show info`** | Общее состояние процесса, аптайм, утилизация потоков и задач | `echo "show info" \| socat stdio /run/haproxy/admin.sock` |
| **`show stat`** | Полная статистика по всем узлам в формате CSV | `echo "show stat" \| socat stdio /run/haproxy/admin.sock` |
| **`show errors`** | Детальный вывод последних пойманных протокольных аномалий и сбоев | `echo "show errors" \| socat stdio /run/haproxy/admin.sock` |
| **`show pools`** | Диагностика пулов динамической памяти и возможных утечек | `echo "show pools" \| socat stdio /run/haproxy/admin.sock` |
| **`show activity`** | Профилирование активности потоков, фиксация скачков задержек CPU | `echo "show activity" \| socat stdio /run/haproxy/admin.sock` |
| **`show servers state <bk>`** | Дамп текущих статусов, адресов и весов серверов бэкенда | `echo "show servers state app_servers" \| socat stdio ...` |
| **`set server <bk>/<srv> state maint`** | Немедленный перевод сервера в регламентный режим (отключение) | `echo "set server app_servers/app01 state maint" \| socat stdio ...` |
| **`set server <bk>/<srv> state drain`** | Режим постепенного завершения: новые сессии не принимаются | `echo "set server app_servers/app01 state drain" \| socat stdio ...` |
| **`set server <bk>/<srv> state ready`** | Возврат сервера в рабочий режим балансировки | `echo "set server app_servers/app01 state ready" \| socat stdio ...` |
| **`set server <bk>/<srv> weight <N>`** | Динамическое изменение веса сервера (0–256) | `echo "set server app_servers/app01 weight 50" \| socat stdio ...` |
| **`clear table <table>`** | Очистка всех записей указанной Stick Table | `echo "clear table app_servers" \| socat stdio ...` |
| **`clear counters all`** | Сброс накопительных счетчиков статистики без перезапуска | `echo "clear counters all" \| socat stdio ...` |

---

## Устранение неполадок (Troubleshooting)

| Проблема / Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`connect(/run/haproxy/admin.sock): Permission denied`** | Недостаточно прав пользователя, вызвавшего `socat`. | Проверить права: `ls -la /run/haproxy/admin.sock`. | Добавить сервисного пользователя в группу `haproxy` (`usermod -aG haproxy $USER`) либо настроить `mode 660` и `group haproxy` в секции `global`. |
| **Scrape timeout Prometheus на `/metrics`** | Слишком большой размер экспортируемых метрик из-за динамических серверов или stick tables с высокой кардинальностью. | Замерить время ответа: `curl -w "%{time_total}\n" -o /dev/null -s http://127.0.0.1:8404/metrics`. | Использовать параметр выборки `?scope=frontend,backend` для скрапинга метрик без индивидуальных серверов, либо увеличить `scrape_timeout` в Prometheus. |
| **Преобладание флагов `sH` и кодов 504 Gateway Timeout в логах** | Серверы приложений зависают и не отдают заголовки за интервал `timeout server`. | Проверить тайминг `%Tr` в JSON-логах: если `%Tr >= timeout server`, виновато приложение. | Оптимизировать запросы к БД, увеличить пул воркеров приложения; временно скорректировать `timeout server`. |
| **Флаги `sC` и коды 503 Service Unavailable** | HAProxy не может установить TCP-соединение с бэкендом за время `timeout connect`. | Проверить доступность порта бэкенда: `nc -zv 10.0.0.11 8080` и метрику `%Tc`. | Проверить запущен ли процесс на бэкенде, проверить сетевой экран (iptables/nftables) и размер `net.core.somaxconn`. |
| **Рост значения `%Tw` (запросы долго ждут в очереди)** | Достигнут лимит `maxconn` на бэкенде, входящий поток превышает пропускную способность серверов. | Проверить `haproxy_backend_current_queue` и `show stat` (колонка `qcur`). | Увеличить лимит `maxconn` на директиве `server`, если приложение выдерживает нагрузку, либо добавить узлы в бэкенд. |
| **Логи HAProxy не появляются в `/var/log/haproxy/`** | Демон `rsyslog` не слушает сокет `/dev/log` внутри chroot окружения HAProxy или заблокирован AppArmor/SELinux. | `systemctl status rsyslog`, проверить наличие сокета `/var/lib/haproxy/dev/log`. | Сконфигурировать `$AddUnixListenSocket /var/lib/haproxy/dev/log` в `rsyslog.conf` или перевести логирование на UDP (`log 127.0.0.1:514 local0`). |
| **Серверы постоянно переходят UP/DOWN (Flapping)** | Слишком агрессивные параметры health check либо перегрузка сервера проверками. | Проверить логи: `Health check for server app01 failed`. | Увеличить интервал `inter` (например, с `1s` до `3s`), увеличить порог `fall` до `3`–`5`, проверить легковесность эндпоинта `/healthz`. |

---

## Лучшие практики

1. **Изоляция интерфейса метрик и управления:**
   - Никогда не публиковать эндпоинты `/metrics`, `/stats` и Runtime API на публичных IP-адресах (`0.0.0.0`).
   - Использовать `bind 127.0.0.1:8404` или выделенный management-интерфейс (VLAN/VPN) с обязательной проверкой подсети через ACL.

2. **Контроль кардинальности метрик PROMEX:**
   - При наличии тысяч бэкендов в больших инсталляциях сбор метрик по каждому серверу каждые 15 секунд может создавать ощутимую нагрузку на Prometheus. Используйте эндпоинт `/metrics?scope=frontend,backend` для глобальных дашбордов и отдельный scrape job с интервалом 60 секунд для детальных метрик серверов.

3. **Отказоустойчивость Runtime API:**
   - Всегда указывайте директиву `expose-fd listeners` в строке сокета `stats socket`. Это позволяет рабочим процессам передавать дескриптор сокета новому мастер-процессу при reload без сброса активных соединений утилит автоматизации.

4. **Тонкая настройка проверок состояния (Health Checks):**
   - Используйте специализированный эндпоинт (например, `/healthz` или `/ready`), который проверяет доступность критичных зависимостей сервиса, но не нагружает базу данных тяжелыми операциями.
   - Задавайте адекватные интервалы: `check inter 3s fall 3 rise 2`. Быстрый возврат в строй (`rise 2`) и запас прочности при кратковременном сетевом дропе (`fall 3`).

5. **Оптимизация системных ресурсов ОС хоста Linux:**
   - Настройка дескрипторов файлов в `/etc/security/limits.d/haproxy.conf`:
     ```ini
     haproxy soft nofile 1048576
     haproxy hard nofile 1048576
     ```
   - Настройка сетевого стека в `/etc/sysctl.d/99-haproxy.conf`:
     ```ini
     net.core.somaxconn = 65535
     net.ipv4.tcp_max_syn_backlog = 65535
     net.ipv4.ip_local_port_range = 1024 65535
     net.ipv4.tcp_tw_reuse = 1
     net.ipv4.tcp_fin_timeout = 15
     ```

6. **Структурированное логирование вместо неструктурированного:**
   - Перевод логирования в формат JSON с фиксацией таймингов (`%TR`, `%Tw`, `%Tc`, `%Tr`, `%Ta`) и `traceparent` избавляет от необходимости писать тяжелые регулярные выражения на стороне коллекторов логов.

---

## Дополнительная информация

### Чек-лист готовности мониторинга к эксплуатации (Production Readiness)

- [ ] **PROMEX:** Активирован на выделенном порту (например, `8404`), доступ защищен ACL и закрыт от внешней сети.
- [ ] **Runtime API:** Настроен сокет `/run/haproxy/admin.sock` с правами `mode 660`, владельцем `haproxy:haproxy` и опцией `expose-fd listeners`.
- [ ] **Логирование:** Включен формат JSON с записью таймингов сессий (`%TR/%Tw/%Tc/%Tr/%Ta`), флагов завершения (`%ts`) и заголовка трассировки.
- [ ] **Ротация логов:** Настроен `logrotate` со сжатием и сохранением истории глубиной не менее 14 дней.
- [ ] **Prometheus Scraping:** В конфигурацию Prometheus добавлен job с интервалом сбора 10–15с и правильным `scrape_timeout`.
- [ ] **Алертинг:** Настроены правила на отказ бэкендов, деградацию резервирования, всплеск 5xx ошибок, рост P95-задержки и переполнение очередей.
- [ ] **Health Checks:** Проверки состояния настроены на выделенный эндпоинт приложения с порогами `inter 3s fall 3 rise 2`.
- [ ] **Таймауты:** Скорректированы таймауты `connect`, `client`, `server`, `queue` под реальный профиль нагрузки приложения.

### См. также

- **[HAProxy — базовый обзор](../haproxy_overview.md)** — общая архитектура, алгоритмы балансировки, ACL, SSL-терминация.
- **[Балансировка между локациями и защита от перегруза](./haproxy_multi_location_load_balancing.md)** — синхронизация stick tables через peers, вероятностное сбрасывание запросов.
- **[Логирование веб-серверов](./webserver_logging.md)** — форматы access/error логов, ротация, централизованный сбор логов в Linux.
- **[Устранение неполадок веб-серверов](./webserver_troubleshooting.md)** — методология расследования сетевых и HTTP-инцидентов.
- **[Матрица мониторинга Prometheus](../../Prometheus/Exporters/monitoring_matrix.md)** — стандарты метрик RED/USE и пороговые значения алертов.
- **[Экспортёры Prometheus](../../Prometheus/Exporters/other_exporters.md)** — справочник по портам и режимам работы экспортёров.

