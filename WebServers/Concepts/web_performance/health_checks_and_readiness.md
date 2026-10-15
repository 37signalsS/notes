# Health Checks и Readiness для веб-производительности

**Актуально для:** Nginx 1.26+, Angie 1.8+, HAProxy 2.8+ / 3.0+

## Определения

- **Health Check (Проверка состояния / жизнеспособности)** — автоматизированный периодический или транзакционный контроль доступности, целостности и корректности функционирования узла инфраструктуры, сервиса или приложения.
- **Readiness Probe (Проверка готовности к обслуживанию)** — специализированный механизм проверки, определяющий, способен ли экземпляр сервиса принимать входящий пользовательский трафик прямо сейчас (инициализированы ли внутренние структуры данных, прогреты ли локальные кэши, установлены ли пулы соединений к зависимостям). При непрохождении проверки балансировщик временно исключает узел из ротации без перезапуска процесса.
- **Liveness Probe (Проверка жизнеспособности процесса)** — контроль физического функционирования процесса приложения (отсутствие взаимоблокировок / deadlock, критических утечек памяти, зацикливания event loop). При отрицательном результате супервизор процессов (systemd, runit, container runtime) выполняет принудительный перезапуск экземпляра.
- **Startup Probe (Проверка фазы инициализации)** — проверка для сервисов с длительным временем холодного старта (прогрев JIT, загрузка индексов в оперативную память). Блокирует выполнение liveness и readiness проверок до завершения начальной инициализации, предотвращая преждевременный перезапуск медленно стартующего процесса.
- **Passive Health Check (Пассивная проверка / In-band)** — контроль доступности бэкендов в процессе обработки реального клиентского трафика. Балансировщик фиксирует сбои (таймауты TCP-подключения, ошибки чтения/записи, HTTP-коды 5xx) и временно выводит узел из балансировки после заданного количества неудач подряд. Не создает дополнительного трафика, но пропускает порцию сбойных запросов к клиентам.
- **Active Health Check (Активная проверка / Out-of-band)** — проактивная периодическая отправка балансировщиком синтетических контрольных запросов (проб) к бэкендам независимо от наличия пользовательского трафика. Позволяет обнаружить деградацию до того, как с ней столкнутся клиенты, и вернуть узел в строй только после серии успешных ответов.
- **Graceful Drain (Слив трафика / Connection Draining)** — контролируемый перевод узла в режим подготовки к выводу из эксплуатации, при котором балансировщик прекращает направлять на него новые клиентские сессии, но дает возможность уже установленным TCP-соединениям и долгоживущим запросам корректно завершить работу в пределах заданного таймаута.
- **Flapping (Дребезг состояния)** — циклическое высокочастотное переключение статуса узла между доступным (`UP`) и недоступным (`DOWN`), вызванное пограничными задержками сети, чрезмерно жесткими таймаутами или лавинной перегрузкой бэкенда сразу после возвращения в ротацию.
- **Hysteresis (Гистерезис проверок)** — разделение порогов признания узла неисправным (`fall` / `max_fails`) и восстановления его работоспособности (`rise` / `check_success`), предотвращающее явление дребезга.
- **Slow Start (Плавный пуск)** — механизм постепенного линейного или экспоненциального наращивания доли трафика (веса), направляемого на восстановленный узел, защищающий непрогретое приложение от мгновенного насыщения очередями и падения производительности.
- **Core Web Vitals в контексте проверок состояния:**
  - **TTFB (Time to First Byte):** время ожидания первого байта ответа. Задержки детекции сбоя бэкенда при пассивных проверках напрямую суммируются с TTFB клиентского запроса.
  - **LCP (Largest Contentful Paint):** время отрисовки основного контента. Зависание запросов за HTML или ключевыми данными из-за неисправного бэкенда приводит к критической деградации LCP.
  - **INP (Interaction to Next Paint):** задержка реакции интерфейса на действия пользователя. Медленные или аварийно завершающиеся AJAX/API-запросы парализуют клиентские сценарии.

## Основные концепции и архитектура

### Пассивные и активные проверки состояния

Отказоустойчивость и стабильность задержек веб-сервера зависят от комбинации пассивного контроля входящих транзакций и активного периодического зондирования.

```
                              [ Клиентский трафик ]
                                        │
                                        ▼
                           ┌─────────────────────────┐
                           │   L7 Reverse Proxy /    │
                           │   Load Balancer         │
                           │ (Nginx / Angie / HAProxy│
                           └──────┬───────────┬──────┘
             Пассивный контроль   │           │   Активные фоновые
             ответов (In-band)    │           │   зонды (Out-of-band)
                                  ▼           ▼
                           ┌─────────────────────────┐
                           │   Upstream Backend 1    │
                           │  - /ready  (Readiness)  │
                           │  - /live   (Liveness)   │
                           └─────────────────────────┘
```

| Характеристика | Пассивные проверки (In-band) | Активные проверки (Out-of-band) |
| :--- | :--- | :--- |
| **Принцип работы** | Анализ кодов возврата и таймаутов на реальных запросах клиентов | Периодическая отправка синтетических HTTP/TCP-запросов прокси-сервером |
| **Накладные расходы на сеть** | Нулевые (нет дополнительного трафика) | Минимальные (1–2 запроса в несколько секунд на узел) |
| **Скорость обнаружения сбоя** | Зависит от интенсивности трафика; требует пропуска ошибок клиентам | Мгновенно по расписанию (1–3 секунды), до появления клиентских жалоб |
| **Влияние на TTFB / Web Vitals** | Добавляет задержку `proxy_connect_timeout` к запросам первых сбойных клиентов | Полностью изолирует пользователей от деградировавших серверов |
| **Поддержка в Nginx OSS** | Встроена нативно (`max_fails`, `fail_timeout`) | Требует сторонних модулей или форков (Angie, OpenResty) |
| **Поддержка в Angie / HAProxy** | Встроена нативно | Встроена нативно (директива `check` в Angie; `check` в HAProxy) |

### Разделяемая память (Shared Memory Zone) и воркеры Nginx/Angie

Критическая архитектурная деталь Nginx и Angie: рабочие процессы (`worker_processes`) по умолчанию функционируют изолированно. 

- **Без директивы `zone` в `upstream` (только Nginx OSS):** каждый worker-процесс ведет собственный независимый учет счетчиков `max_fails`. Если на хосте запущено 16 воркеров, а `max_fails=3`, то до полного исключения неисправного бэкенда клиенты могут получить до $16 \times 3 = 48$ ошибок 5xx.
- **С директивой `zone` (Nginx Plus, Angie OSS, Angie PRO):** все воркеры синхронизируют счетчики неудач, текущее состояние пиров (`UP`, `DOWN`, `DRAIN`) и статистику активных проверок через сегмент разделяемой памяти. Сервер гарантированно выводится из ротации ровно после 3 ошибок суммарно по всему экземпляру балансировщика.

```
       Worker #1 (сбой 1) ──┐
       Worker #2 (сбой 2) ──┼──► [ shared memory: zone backend 128k ] ──► Статус: DOWN (ровно 3 сбоя)
       Worker #3 (сбой 3) ──┘
```

### Архитектура и проектирование эндпоинтов здоровья

Ошибочное проектирование контрольных эндпоинтов — частая причина каскадных аварий в production (Cascading Failures).

1. **Разделение `/live` и `/ready`:**
   - Эндпоинт `/live` должен быть максимально легковесным: проверять, что процесс жив, event loop не заблокирован и память не исчерпана. Он **никогда** не должен выполнять сетевые запросы к базам данных или внешним сервисам. Сбой `/live` приводит к аварийному перезапуску процесса супервизором.
   - Эндпоинт `/ready` проверяет способность выполнять полезную работу: валидность локального кэша, доступность обязательного пула подключений к БД.
2. **Опасность глубоких проверок (Deep Health Checks):**
   - Если эндпоинт `/ready` каждого бэкенда выполняет тяжелый запрос в общую базу данных (`SELECT * FROM table`), при кратковременном скачке нагрузки на БД все бэкенды одновременно ответят кодом 503. Балансировщик выведет из строя сразу всю ферму серверов, превратив частичную задержку в 100% отказ всей системы.
   - Правило: проверка зависимостей должна контролировать лишь статус соединения из локального пула, либо выполняться с мягким тайм-аутом и кэшированием статуса внутри приложения.
3. **Холодный старт и Slow Start:**
   - После перезапуска процесс приложения (особенно на Java, Node.js, Python) требует времени на JIT-компиляцию и наполнение локальных кэшей. Если на только что поднявшийся сервер сразу направить полный поток запросов, очередь запросов переполнится, и сервер снова упадет по таймауту.
   - Директива `slow_start` плавно повышает эффективный вес сервера от нуля до номинала в течение заданного окна (например, 20–30 секунд).

### Влияние на Core Web Vitals и бюджет времени отклика

Для удержания показателя Good TTFB ($\le 800$ мс по критериям Google CrUX) балансировщик должен жестко лимитировать время реакции на сбой отдельного узла:

$$\text{Время переключения} = \text{proxy\_connect\_timeout} + \text{proxy\_next\_upstream\_timeout}$$

Если стандартный `proxy_connect_timeout` в Nginx равен 60 секундам, при недоступности порта бэкенда клиент будет ждать минуту до получения ответа, что гарантированно разрушает показатели TTFB, LCP и приводит к закрытию вкладки пользователем. 

Оптимальный бюджет времени переключения при сбое:
- `proxy_connect_timeout`: не более `1s` – `2s`;
- `proxy_next_upstream_tries`: не более `2` – `3`;
- `proxy_next_upstream_timeout`: не более `3s` – `5s`.

## Практические сценарии и конфигурация

### Сценарий 1: Высокоточный пассивный мониторинг и failover в Nginx / Angie

Настройка пула бэкендов с синхронизацией состояния через разделяемую память, быстрым переключением при сбоях и отдачей устаревшего кэша при отказе всех серверов.

**Требования:** Nginx 1.26+ или Angie 1.8+, настроенный кэш `api_cache`.

```nginx
# Определение пула upstream с разделяемой памятью
upstream api_cluster {
    zone api_cluster 128k;

    # Бэкенд выбывает после 3 ошибок за 10 секунд; возвращается на пробу через 10 секунд
    server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;

    # Резервный узел, принимает трафик только если оба основных бэкенда недоступны
    server 10.0.1.12:8080 backup;

    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}

server {
    listen 80;
    server_name api.example.internal;

    location /api/ {
        proxy_pass http://api_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Бюджет сетевых таймаутов для защиты TTFB
        proxy_connect_timeout 2s;
        proxy_read_timeout 10s;
        proxy_send_timeout 5s;

        # Условия переключения на следующий сервер в пуле
        proxy_next_upstream error timeout invalid_header http_502 http_503 http_504 non_idempotent;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 4s;

        # Graceful Fallback: отдача stale-кэша при деградации бэкендов
        proxy_cache api_cache;
        proxy_cache_valid 200 302 5m;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;
    }
}
```

**Пояснение параметров:**
- `zone api_cluster 128k;` — единая память счетчиков сбоев для всех воркеров.
- `non_idempotent` — разрешает повторить запрос к следующему бэкенду, даже если это мутирующий метод (POST/PUT), при условии, что заголовки ответа еще не были получены.
- `proxy_cache_use_stale` — защищает клиентов от 5xx ошибок, отдавая кэшированный ответ при аварии бэкенда.

**Валидация конфигурации:**
```bash
# 1. Проверка синтаксиса
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf test is successful

# 2. Применение конфигурации
sudo systemctl reload nginx

# 3. Имитация аварии первого узла
sudo iptables -A INPUT -p tcp --dport 8080 -s 10.0.1.10 -j DROP

# 4. Проверка прозрачного переключения клиента без роста задержек
curl -w "HTTP: %{http_code} | Time: %{time_total}s\n" -s http://api.example.internal/api/ping
# → HTTP: 200 | Time: 0.045s

# 5. Очистка правил iptables
sudo iptables -D INPUT -p tcp --dport 8080 -s 10.0.1.10 -j DROP
```

---

### Сценарий 2: Активные проверки доступности и Slow Start в Angie OSS

В Angie модуль активных проверок включен по умолчанию на уровне открытой версии (`check`), а текущее состояние пулов инспектируется через REST API телеметрии (`/status/`).

**Требования:** Angie 1.8+ (OSS).

```nginx
http {
    upstream dynamic_backend {
        zone dynamic_backend 256k;

        # Серверы с плавным пуском в течение 20 секунд после восстановления
        server 10.0.2.10:8080 max_fails=2 fail_timeout=5s slow_start=20s;
        server 10.0.2.11:8080 max_fails=2 fail_timeout=5s slow_start=20s;

        # Модуль активных проверок Angie OSS
        # Интервал 3000 мс, 2 успеха для UP, 3 сбоя для DOWN, таймаут 1200 мс
        check interval=3000 rise=2 fall=3 timeout=1200 type=http;
        check_http_send "GET /ready HTTP/1.1\r\nHost: api.internal\r\nConnection: close\r\n\r\n";
        check_http_expect_alive http_2xx;
    }

    server {
        listen 80;
        server_name service.internal;

        location / {
            proxy_pass http://dynamic_backend;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_connect_timeout 1s;
            proxy_read_timeout 5s;
        }
    }

    # Внутренний сервисный сервер мониторинга и телеметрии Angie
    server {
        listen 127.0.0.1:8888;
        server_name localhost;

        location /status/ {
            api /status/;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Валидация и проверка состояния в runtime:**
```bash
# 1. Проверка синтаксиса и перезапуск
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf test is successful
sudo systemctl reload angie

# 2. Проверка состояния пиров через официальный JSON API Angie
curl -s http://127.0.0.1:8888/status/http/upstreams/dynamic_backend/ | jq '.peers[] | {server, state, selected, fails}'
# → { "server": "10.0.2.10:8080", "state": "up", "selected": 1420, "fails": 0 }
# → { "server": "10.0.2.11:8080", "state": "up", "selected": 1395, "fails": 0 }

# 3. Имитация деградации сервиса (перевод /ready в 503 на стороне бэкенда 10.0.2.10)
# Через 9 секунд (3 интервала по 3 секунды) узел автоматически изолируется
curl -s http://127.0.0.1:8888/status/http/upstreams/dynamic_backend/ | jq '.peers[] | {server, state}'
# → { "server": "10.0.2.10:8080", "state": "unhealthy" }
# → { "server": "10.0.2.11:8080", "state": "up" }
```

---

### Сценарий 3: Балансировка и Graceful Drain в HAProxy

HAProxy — эталонный балансировщик для bare-metal и виртуальных инфраструктур, поддерживающий гибкие L7-проверки и бесшовный вывод серверов через runtime сокет без перезагрузки процессов.

**Требования:** HAProxy 2.8+ или 3.0+.

```haproxy
global
    log /dev/log local0
    stats socket /var/run/haproxy/admin.sock mode 660 level admin expose-fd listeners
    stats timeout 30s
    maxconn 50000

defaults
    log     global
    mode    http
    option  httplog
    option  dontlognull
    timeout connect 2s
    timeout client  30s
    timeout server  30s
    retries 3

backend app_cluster
    mode http
    balance roundrobin

    # Расширенная проверка готовности L7
    option httpchk
    http-check send meth GET uri /ready ver HTTP/1.1 hdr Host api.internal
    http-check expect status 200

    # inter: 2s (интервал), fall: 3 (порог отключения), rise: 2 (порог включения), slowstart: 30s
    default-server inter 2s fall 3 rise 2 slowstart 30s

    server node1 10.0.3.10:8080 check maxconn 500
    server node2 10.0.3.11:8080 check maxconn 500
```

**Процедура оперативного Connection Draining при деплое:**
```bash
# 1. Проверка текущего статуса бэкендов в сокете
echo "show stat" | sudo socat stdio /var/run/haproxy/admin.sock | cut -d',' -f1,2,18,19 | grep app_cluster
# → app_cluster,node1,UP,
# → app_cluster,node2,UP,

# 2. Перевод node1 в режим DRAIN (новые клиенты не идут, активные сессии завершаются)
echo "set server app_cluster/node1 state drain" | sudo socat stdio /var/run/haproxy/admin.sock
# → (пустой ответ при успехе)

# 3. Верификация перехода в drain
echo "show servers state app_cluster" | sudo socat stdio /var/run/haproxy/admin.sock
# → 1 app_cluster 1 node1 10.0.3.10 2 2 ... (srv_op_state = 2: DRAIN)

# 4. Пауза на завершение активных транзакций приложения
sleep 10

# 5. Перевод сервера в режим техобслуживания (MAINT) и обновление ПО
echo "set server app_cluster/node1 state maint" | sudo socat stdio /var/run/haproxy/admin.sock
sudo systemctl stop api@node1
sudo systemctl start api@node1

# 6. Возврат сервера в рабочее состояние (READY)
echo "set server app_cluster/node1 state ready" | sudo socat stdio /var/run/haproxy/admin.sock
# Сервер переходит в UP с активацией 30-секундного slowstart
```

---

### Сценарий 4: Самостоятельный Readiness Drain приложения под управлением Systemd

В архитектуре высокой доступности приложение при остановке или перезапуске самостоятельно подает сигнал балансировщику об исключении из ротации, гарантируя нулевой процент ошибок клиентов (Zero Downtime).

**Принцип работы:**
1. При получении сигнала `SIGTERM` или команды остановки приложение переводит внутренний флаг готовности в `false` (эндпоинт `/ready` начинает отдавать `503 Service Unavailable`).
2. Балансировщик фиксирует сбой проверки и снимает узел с обслуживания.
3. Приложение выдерживает таймаут слива соединений (`grace_period`), обрабатывает оставшиеся запросы и корректно завершает работу.

**Конфигурация Systemd Unit (`/etc/systemd/system/web-service.service`):**
```ini
[Unit]
Description=High Performance Web Service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/web-service
ExecStart=/opt/web-service/bin/server --port=8080
Restart=always
RestartSec=5s

# Graceful остановка: таймаут на завершение всех активных соединений
TimeoutStopSec=30s
KillSignal=SIGTERM
KillMode=mixed

# Поддержка системных лимитов для веб-нагрузки
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

**Пример реализации логики в приложении (Go / HTTP-обработчик):**
```go
package main

import (
	"context"
	"net/http"
	"os"
	"os/signal"
	"sync/atomic"
	"syscall"
	"time"
)

var isReady int32 = 1

func main() {
	mux := http.NewServeMux()

	// Liveness: проверяет только то, что процесс откликается
	mux.HandleFunc("/live", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ALIVE"))
	})

	// Readiness: зависит от атомарного флага готовности
	mux.HandleFunc("/ready", func(w http.ResponseWriter, r *http.Request) {
		if atomic.LoadInt32(&isReady) == 1 {
			w.WriteHeader(http.StatusOK)
			w.Write([]byte("READY"))
		} else {
			w.WriteHeader(http.StatusServiceUnavailable)
			w.Write([]byte("DRAINING"))
		}
	})

	server := &http.Server{Addr: ":8080", Handler: mux}

	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			os.Exit(1)
		}
	}()

	// Перехват сигналов завершения от systemd
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	<-stop

	// ШАГ 1: Переводим /ready в 503 (балансировщик уберет узел из пула)
	atomic.StoreInt32(&isReady, 0)

	// ШАГ 2: Пауза на фиксацию балансировщиком (интервал проверки * fall + запас)
	time.Sleep(5 * time.Second)

	// ШАГ 3: Graceful shutdown для обработки завершающихся запросов
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	_ = server.Shutdown(ctx)
}
```

## Операции и команды

### Инспекция состояния бэкендов в Angie через REST API

```bash
# Получение общего списка всех upstreams и их пиров в формате JSON
curl -s http://127.0.0.1:8888/status/http/upstreams/ | jq .

# Фильтрация конкретного пула: статус, количество ошибок и активных соединений
curl -s http://127.0.0.1:8888/status/http/upstreams/api_cluster/ | jq '.peers[] | {server, state, active, fails, requests}'
# → { "server": "10.0.1.10:8080", "state": "up", "active": 12, "fails": 0, "requests": 84201 }
# → { "server": "10.0.1.11:8080", "state": "unhealthy", "active": 0, "fails": 3, "requests": 41200 }
```

### Управление состоянием в HAProxy через UNIX-сокет

```bash
# Просмотр статистики всех серверов бэкенда
echo "show stat" | sudo socat stdio /var/run/haproxy/admin.sock | cut -d',' -f1,2,18,19,34,57

# Принудительный вывод узла в техобслуживание (отключение трафика и проверок)
echo "set server app_cluster/node1 state maint" | sudo socat stdio /var/run/haproxy/admin.sock

# Возврат узла в штатную ротацию
echo "set server app_cluster/node1 state ready" | sudo socat stdio /var/run/haproxy/admin.sock

# Изменение веса сервера на лету (снижение доли трафика)
echo "set server app_cluster/node1 weight 50%" | sudo socat stdio /var/run/haproxy/admin.sock
```

### Инъекция сбоев и Chaos-тестирование задержек

```bash
# Проверка времени отклика эндпоинта готовности с замером фаз сетевого соединения
curl -w "\nDNS: %{time_namelookup}s | Connect: %{time_connect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s\n" \
     -s -o /dev/null http://10.0.1.10:8080/ready
# → DNS: 0.001s | Connect: 0.002s | TTFB: 0.015s | Total: 0.016s

# Эмуляция потери пакетов (Packet Loss 20%) на интерфейсе бэкенда для проверки реакции на таймауты
sudo tc qdisc add dev eth0 root netem loss 20%

# Эмуляция задержки сети 500 мс (High Latency)
sudo tc qdisc change dev eth0 root netem delay 500ms

# Удаление правил эмуляции задержек
sudo tc qdisc del dev eth0 root
```

## Диагностика и устранение неисправностей

| Симптом / Проблема | Вероятная причина | Метод диагностики | Пошаговое решение |
| :--- | :--- | :--- | :--- |
| **Клиенты получают 502/504 при падении одного из серверов** | Завышен `proxy_connect_timeout` (по умолчанию 60с); отсутствует `proxy_next_upstream` | Проверить `$upstream_response_time` и `$upstream_status` в access-логах | Установить `proxy_connect_timeout 2s;`, настроить `proxy_next_upstream error timeout http_502 http_503;` |
| **Nginx OSS медленно исключает упавший сервер** | Отсутствует директива `zone` в блоке `upstream`. Каждый worker считает ошибки автономно | Сравнить суммарное число 5xx ошибок в логе с формулой `max_fails * worker_processes` | Добавить `zone <name> 128k;` в блок `upstream` (требует Nginx Plus или переход на Angie) |
| **Дребезг статуса (Flapping: UP <-> DOWN)** | Чрезмерно жесткий таймаут проверки при плавающей нагрузке; равенство порогов (`rise=1`, `fall=1`) | Анализ системного журнала балансировщика на предмет частых событий `is unhealthy / is healthy` | Ввести гистерезис: `rise=3`, `fall=3`, увеличить `check timeout` с 500ms до 1500ms |
| **Лавинный отказ фермы (Cascading Failure)** | Эндпоинт `/ready` выполняет тяжелый запрос в БД, упавшую под нагрузкой | Массовый синхронный переход всех узлов в статус `DOWN` в течение нескольких секунд | Изолировать логику проверок: убрать тяжелые SQL-запросы из `/ready`, проверять только статус локального сокета |
| **Сервер падает сразу после возврата в ротацию** | «Ударная» нагрузка на холодный сервер без прогретого кэша и JIT (Thundering Herd) | Скачок CPU до 100% и рост очередей соединений в первые секунды после перехода в `UP` | Включить `slow_start 30s;` в настройках бэкенда (Angie / HAProxy) |
| **Graceful Drain зависает и не завершается** | Незакрытые HTTP Keepalive соединения клиентов или постоянные WebSocket сессии | Инспекция активных соединений через `ss -tnp '( dport = :8080 )'` | Установить жесткий лимит времени вывода: `TimeoutStopSec` в systemd или отключить keepalive перед остановкой |

## Рекомендации и лучшие практики

### Архитектурные правила SRE

1. **Разделяйте контуры проверок жизнеспособности:**
   - `/live` — ответственность супервизора операционной системы (systemd, docker, podman).
   - `/ready` — ответственность L7-балансировщика нагрузки (Nginx, Angie, HAProxy).
2. **Всегда используйте разделяемую память (`zone`):**
   - В Angie и Nginx всегда определяйте зону памяти в блоке `upstream` (`zone name 128k;`). Это исключает умножение количества клиентских ошибок на число воркер-процессов.
3. **Настраивайте гистерезис проверок:**
   - Для вывода узла из строя достаточно 2–3 последовательных ошибок (`fall=3`).
   - Для возврата узла в строй требуйте не менее 2–3 успешных проверок подряд (`rise=2` – `3`), чтобы исключить колебания при нестабильном сетевом линке.
4. **Используйте Slow Start для высоконагруженных сервисов:**
   - Время плавного пуска (`slow_start=20s`-`30s`) позволяет приложению безопасно заполнить структуры данных без риска захлебнуться во входящих очередях.
5. **Безопасность и разгрузка эндпоинтов здоровья:**
   - Ограничивайте доступ к эндпоинтам `/status/` и `/ready`: разрешайте запросы только с локальной петли (`allow 127.0.0.1; deny all;`) или доверенной подсети балансировщиков.
   - Отключайте логирование регулярных проверок (`access_log off;`), чтобы предотвратить бессмысленную деградацию дискового ввода-вывода (I/O).
6. **Очистка окружения после регламентных работ:**
   - Любые манипуляции с симуляцией сбоев (`iptables`, `tc netem`) должны сопровождаться обязательным скриптовым откатом правил.

## Дополнительная информация

### См. также

- [Circuit Breaker и Degradation Patterns](./circuit_breaker_and_degradation.md) — паттерны защиты от каскадных сбоев и изоляции сбойных узлов.
- [Zero-Downtime Deployment и Graceful Reload](./zero_downtime_deployment.md) — механизмы бесшовного обновления конфигурации и бинарных файлов без простоя.
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — оптимизация сетевых соединений и взаимодействие пулов с проверками состояния.
- [Проверки состояния и мониторинг балансировщика Nginx](../../Nginx/Proxy/Load_Balancing/health_checks_and_monitoring.md) — детальная настройка пассивных и активных проверок в Nginx и Angie.
- [Балансировка нагрузки HTTP в Angie](../../Angie/angie_http_load_balancing.md) — продвинутые алгоритмы распределения трафика и модуль `check`.
- [Health Checks и Readiness Probes в HTTP](../../../Networking/Protocols/HTTP/http_health_checks_readiness.md) — базовые сетевые стандарты проектирования HTTP-проб.

### Стандарты и спецификации

- **RFC 9110** — HTTP Semantics: раздел 15 (Status Codes — `502 Bad Gateway`, `503 Service Unavailable`, `504 Gateway Timeout`) и заголовок `Retry-After`.
- **RFC 9111** — HTTP Caching: поведение кэширующих прокси-серверов при временной недоступности источников данных.
- **RFC 5861** — HTTP Cache-Control Extensions for Stale Content (`stale-if-error` и `stale-while-revalidate`).
