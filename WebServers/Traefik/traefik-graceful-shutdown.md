# Graceful Shutdown и Zero-Downtime Deploy в Traefik

**Актуально для:** Traefik v3.x (протестировано на v3.3–v3.6) / Linux systemd / Docker Compose v2.x / Kubernetes 1.30+

## Определения

**Graceful Shutdown (мягкое завершение)** — процедура контролируемой остановки сервиса без обрыва активных клиентских соединений и потери данных: процесс перестает принимать новые запросы, дожидается завершения обработки уже принятых транзакций (in-flight) и только после этого освобождает системные ресурсы и завершает работу.

**SIGTERM (Signal 15)** — стандартный сигнал завершения процесса в POSIX-совместимых операционных системах (`kill -15`). Traefik перехватывает данный сигнал и инициирует конвейер штатного дренажа соединений.

**SIGINT (Signal 2)** — сигнал прерывания процесса с терминала (`Ctrl+C` или `kill -2`). В Traefik обрабатывается аналогично сигналу `SIGTERM`.

**SIGKILL (Signal 9)** — безусловный сигнал немедленного уничтожения процесса ядром операционной системы. Traefik не способен его перехватить или заблокировать; влечет мгновенный сброс всех активных TCP-сокетов (отправка TCP `RST`), обрыв транзакций и высокий риск повреждения дискового файла хранилища сертификатов `acme.json`.

**In-flight запросы** — запросы и сетевые соединения, уже принятые балансировщиком в обработку, но ответ по которым еще не передан клиенту в полном объеме.

**Connection Draining (дренаж соединений)** — процедура плавного вывода сетевого узла или инстанса из обслуживания: прекращение регистрации новых сессий при сохранении работоспособности для завершения текущих задач.

**`requestAcceptGraceTimeout`** — директива статической конфигурации входной точки (`entryPoint`) Traefik. Задает интервал времени после получения `SIGTERM`, в течение которого процесс продолжает принимать новые входящие TCP-соединения, нивелируя задержки сетевой синхронизации внешних балансировщиков.

**`graceTimeout`** — директива статической конфигурации `entryPoint` Traefik. Задает предельное время ожидания завершения активных соединений после прекращения приема нового трафика.

**preStop Hook** — хук жизненного цикла контейнера в Kubernetes, выполняемый Kubelet перед отправкой сигнала `SIGTERM`. Предоставляет временной зазор для обновления сетевых таблиц ядра на всех узлах кластера до начала остановки приложения.

**`terminationGracePeriodSeconds`** — системный таймаут пода в Kubernetes, за который контейнер должен выполнить `preStop` хук и штатно завершиться после получения `SIGTERM`. По истечении времени Kubelet направляет процессу `SIGKILL`.

**`TimeoutStopSec`** — директива сервисного юнита Linux systemd, регламентирующая максимальное время ожидания остановки сервиса после отправки `SIGTERM` до применения принудительного `SIGKILL`.

**PodDisruptionBudget (PDB)** — объект политики Kubernetes, ограничивающий число одновременно недоступных реплик сервиса при операциях планового обслуживания инфраструктуры (например, `kubectl drain`).

**HTTP/2 GOAWAY Frame** — служебный управляющий фрейм протокола HTTP/2 (RFC 7540 / RFC 9113), информирующий клиента о прекращении приема новых потоков на данном соединении с указанием идентификатора последнего принятого потока (`Last-Stream-ID`).

---

## Архитектура и принципы работы

### Внутренний жизненный цикл Graceful Shutdown в Traefik v3

Процедура мягкого завершения работы Traefik при получении сигнала `SIGTERM` или `SIGINT` выполняется по строго детерминированному многофазному алгоритму:

```
[Сигнал SIGTERM / SIGINT]
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. Фаза удержания приема: requestAcceptGraceTimeout (напр. 5s)  │
│    - Слушающие сокеты открыты                                   │
│    - Новые TCP SYN принимаются (добор in-flight из сети)        │
│    - /ping эндпоинт переходит в состояние 503 / unhealthy       │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Остановка сетевых слушателей (net.Listener.Close)            │
│    - Порты 80, 443 и др. закрываются на прием новых подключений │
│    - Новые попытки TCP handshake отклоняются ядром (TCP RST)    │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Фаза дренажа активных соединений: graceTimeout (напр. 30s)   │
│    - HTTP/1.1: добавление заголовка "Connection: close"         │
│    - HTTP/2: отправка управляющего фрейма GOAWAY (NO_ERROR)     │
│    - WebSocket / Streaming: удержание до закрытия или таймаута  │
│    - Upstream: завершение обработки ответов от бэкендов         │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Атомарная фиксация состояния ACME                            │
│    - Ожидание завершения текущих TLS-вызовов                    │
│    - Сброс сертификатов на диск в acme.json                     │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Сброс телеметрии и корректный выход                          │
│    - Flush буферов метрик (Prometheus) и трейсинга              │
│    - Завершение процесса с кодом возврата 0                     │
└─────────────────────────────────────────────────────────────────┘
```

1. **Фаза удержания приема (`requestAcceptGraceTimeout`):**
   Если параметр `requestAcceptGraceTimeout` больше `0s`, Traefik после перехвата сигнала продолжает выполнять системный вызов `accept()` на сетевых сокетах. Это компенсирует сетевой джиттер и задержки распространения информации о выводе узла из строя: запросы клиентов, чьи пакеты `SYN` уже находились в канале связи или в очереди ядра `listen backlog`, успешно принимаются и обрабатываются без ошибок `Connection reset by peer`.
2. **Остановка сетевых слушателей:**
   Traefik вызывает метод `Close()` для всех сетевых слушателей (`net.Listener`). Новые входящие попытки установить TCP-соединение немедленно отклоняются операционной системой (ядро отправляет TCP `RST`).
3. **Дренаж активных соединений (`graceTimeout`):**
   - **HTTP/1.1:** Прокси добавляет заголовок `Connection: close` ко всем исходящим ответам. Это сигнализирует клиенту о необходимости немедленно закрыть соединение после получения ответа и запрещает повторное использование сокета для следующих запросов (отключение HTTP Keep-Alive).
   - **HTTP/2:** Traefik генерирует и отправляет клиенту фрейм `GOAWAY` с кодом ошибки `NO_ERROR` (`0x0`) и указанием последнего обработанного идентификатора потока (`Stream ID`). Клиент завершает открытые потоки данных, а последующие запросы направляет через новые TCP-соединения к другим инстансам балансировщика.
   - **WebSocket / gRPC / SSE:** Долгоживущие двунаправленные TCP-туннели удерживаются в активном состоянии до тех пор, пока клиент или бэкенд самостоятельно не разорвут сессию, либо пока не истечет общий `graceTimeout`. Traefik v3 не генерирует синтетические фреймы закрытия WebSocket (`0x88`) на прикладном уровне. Если соединение не завершилось в рамках `graceTimeout`, Traefik принудительно закрывает underlying TCP-сокет.
   - **Upstream Pool:** Пул свободных keep-alive соединений к бэкендам закрывается, а соединения, находящиеся в процессе передачи данных, удерживаются до получения финального байта ответа.
4. **Фиксация состояния ACME и сертификатов:**
   Traefik блокирует старт новых сессий ACME renewal, дожидается завершения текущих криптографических транзакций и выполняет атомарную запись сертификатов в файл `acme.json`, исключая повреждение структуры JSON-файла.
5. **Сброс телеметрии и выход:**
   Сбрасываются внутренние очереди метрик и трейсинга, после чего процесс завершается со стандартным кодом возврата `0`.

---

### Взаимодействие с Linux systemd на Bare-Metal

На физических серверах и виртуальных машинах жизненным циклом демона Traefik управляет `systemd`. Некорректная настройка параметров завершения в unit-файле приводит к преждевременной отправке сигнала `SIGKILL` ядром системы.

#### Математика таймаутов systemd

Для гарантии чистого дренажа значение `TimeoutStopSec` обязано рассчитываться по формуле:

$$\text{TimeoutStopSec} > \text{requestAcceptGraceTimeout} + \text{graceTimeout} + \Delta_{\text{safety}}$$

Где $\Delta_{\text{safety}}$ — защитный интервал (минимум 15–20 секунд) на дисковый ввод-вывод (`acme.json`), системные вызовы ядра и сброс сетевых буферов.

| Параметр в Traefik | Рекомендуемое значение | Соответствующий `TimeoutStopSec` в systemd |
| :--- | :--- | :--- |
| Стандартный Web/API | `requestAccept: 5s`, `grace: 30s` | `TimeoutStopSec=60` |
| Длительные WebSocket / Uploads | `requestAccept: 10s`, `grace: 60s` | `TimeoutStopSec=90` |
| Streaming / Тяжелые API | `requestAccept: 15s`, `grace: 120s` | `TimeoutStopSec=160` |

#### Анализ SIGHUP и директивы ExecReload

В Traefik v3 **не существует механизма горячего перечитывания статической конфигурации по сигналу `SIGHUP`**.
- Динамическая конфигурация (роутеры, сервисы, middleware) обновляется налету без рестарта процесса через файловый провайдер (`providers.file.watch: true`) или провайдеры поставщиков (Consul, Nomad).
- Статическая конфигурация (точки входа `entryPoints`, сетевые таймауты, сертификационные резолверы) считывается исключительно при инициализации бинарника.
- Размещение директивы `ExecReload=/bin/kill -HUP $MAINPID` в unit-файле Traefik является технической ошибкой: Traefik либо проигнорирует `SIGHUP`, либо завершит процесс с ошибкой. Для обновления статики без даунтайма требуется rolling-перезапуск инстансов за внешним L4-балансировщиком (HAProxy / Keepalived).

---

### Жизненный цикл подов в Kubernetes и устранение гонок (Race Conditions)

Во время выполнения Rolling Update или при удалении пода Traefik в Kubernetes возникает критическая гонка между плоскостью управления (Control Plane) и агентом узла (Kubelet):

```
                       [Команда: Удаление Pod Traefik]
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
┌──────────────────────────────────────┐     ┌──────────────────────────────────────┐
│       Control Plane (Асинхронно)     │     │            Kubelet (Узел)            │
│  - Установка deletionTimestamp       │     │  - Запуск preStop хука: sleep 10     │
│  - EndpointSlice Controller удаляет  │     │    (Traefik работает в 100% штатном  │
│    IP пода из списка Endpoints       │     │     режиме, сокеты открыты)          │
│  - kube-proxy / CNI (Cilium/Calico)  │     │                                      │
│    обновляют iptables / eBPF на всех │     │                                      │
│    рабочих узлах (задержка 1-5 сек)  │     │                                      │
└──────────────────┬───────────────────┘     └──────────────────┬───────────────────┘
                   │                                            │
                   ▼                                            ▼
┌──────────────────────────────────────┐     ┌──────────────────────────────────────┐
│  Новый трафик больше не идет на Pod  │     │  Истек preStop: Kubelet шлет SIGTERM │
│  (все ноды исключили старый IP)      │◀────│  Traefik запускает graceful shutdown: │
│                                      │     │  requestAccept -> graceTimeout -> 0  │
└──────────────────────────────────────┘     └──────────────────────────────────────┘
```

1. **Гонка без `preStop` хука:**
   Если `preStop` не определен, Kubelet отправляет `SIGTERM` сразу после фиксации команды удаления. Traefik мгновенно закрывает сетевые сокеты. В это же время демоны `kube-proxy` или CNI-агенты на соседних нодах кластера еще не успели применить обновления правил маршрутизации (сетевая задержка API-сервера). Клиентские запросы продолжают пересылаться на IP останавливающегося пода, в результате чего пользователи получают ошибки `502 Bad Gateway` или сброс соединений `ECONNREFUSED`.
2. **Компенсация через `preStop: sleep 10`:**
   Хук задерживает отправку сигнала `SIGTERM` на 10 секунд. В течение этой паузы Traefik продолжает полноценно функционировать и принимать сетевые пакеты. За 10 секунд все узлы кластера гарантированно успевают исключить IP пода из локальных таблиц маршрутизации. Сигнал `SIGTERM` приходит только тогда, когда на под больше не поступает новый сетевой трафик.
3. **Расчет `terminationGracePeriodSeconds`:**
   Таймаут пода в Kubernetes рассчитывается по формуле:

   $$\text{terminationGracePeriodSeconds} \ge \text{preStop sleep} + \text{requestAcceptGraceTimeout} + \text{graceTimeout} + 15\text{s}$$

   Пример: `sleep 10s` + `5s` + `30s` + `15s` = `60s` (рекомендуемое значение: `60` или `90`).
4. **Специфика Deployment и DaemonSet:**
   - **Deployment:** Оптимален при работе за внешним аппаратным или программным балансировщиком. Используется стратегия обновления с параметрами `maxSurge: 1` (создание нового пода до удаления старого) и `maxUnavailable: 0` (запрет снижения емкости кластера).
   - **DaemonSet:** Применяется при привязке к портам хоста (`hostPort: 80/443` или `hostNetwork: true`). Стратегия `maxSurge` здесь **не применима**, так как две реплики не могут одновременно занять один и тот же TCP-порт на физическом интерфейсе узла (ошибка `bind: address already in use`). Для DaemonSet применяется стратегия `RollingUpdate` с `maxUnavailable: 1` в сочетании с внешним L4-балансировщиком, отслеживающим статус через эндпоинт `/ping`.

---

### Архитектура внешнего L4-балансировщика (Keepalived / HAProxy)

В отказоустойчивых Bare-Metal инфраструктурах Traefik развертывается минимум на двух независимых серверах за внешним L4-балансировщиком (HAProxy, Keepalived VRRP).

- **Роль эндпоинта `/ping`:**
  Traefik предоставляет нативный эндпоинт `/ping`. В штатном состоянии сервис отдает статус `HTTP 200 OK`. При инициализации остановки или переводе в режим дренажа Traefik переводит эндпоинт в состояние ошибки или прекращает отвечать, сигнализируя внешним балансировщикам о необходимости исключения ноды.
- **VRRP Failover (Keepalived):**
  Демон Keepalived периодически запускает локальный скрипт проверки (`vrrp_script`), отправляющий HTTP-запрос к эндпоинту `/ping`. При фиксации кода, отличного от `200`, приоритет ноды снижается, и виртуальный IP-адрес (VIP) переключается на резервный сервер.

---

## Практические сценарии

### Сценарий 1: Конфигурация Traefik и systemd на Linux Bare-Metal

Конфигурация производственного сервера Traefik v3 с корректными параметрами дренажа, системными лимитами дескрипторов и безопасными директивами systemd.

#### Статическая конфигурация `/etc/traefik/traefik.yml`

```yaml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

# Логирование
log:
  level: INFO
  filePath: /var/log/traefik/traefik.log
  format: json

# Точки входа с настройкой жизненного цикла
entryPoints:
  web:
    address: ":80"
    transport:
      lifeCycle:
        requestAcceptGraceTimeout: 5s
        graceTimeout: 30s
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true

  websecure:
    address: ":443"
    transport:
      lifeCycle:
        requestAcceptGraceTimeout: 5s
        graceTimeout: 30s
      respondingTimeouts:
        readTimeout: 60s
        writeTimeout: 60s
        idleTimeout: 180s

  # Выделенная точка входа для мониторинга и health check
  ping:
    address: "127.0.0.1:8082"

# Включение эндпоинта проверки работоспособности
ping:
  entryPoint: ping

# Динамические провайдеры
providers:
  file:
    directory: /etc/traefik/dynamic
    watch: true
```

#### Сервисный юнит `/etc/systemd/system/traefik.service`

```ini
[Unit]
Description=Traefik v3 Modern Edge Reverse Proxy
Documentation=https://doc.traefik.io/traefik/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=traefik
Group=traefik
ExecStart=/usr/local/bin/traefik --configfile=/etc/traefik/traefik.yml

# Graceful shutdown параметры:
# TimeoutStopSec (60s) > requestAcceptGraceTimeout (5s) + graceTimeout (30s) + запас (25s)
TimeoutStopSec=60
KillMode=control-group
KillSignal=SIGTERM
Restart=on-failure
RestartSec=5s

# Безопасность и песочница процесса
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectControlGroups=true
ReadWritePaths=/var/log/traefik /var/lib/traefik
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE

# Системные лимиты дескрипторов и процессов
LimitNOFILE=1048576
LimitNPROC=524288

[Install]
WantedBy=multi-user.target
```

#### Применение и валидация конфигурации

```bash
# 1. Проверка синтаксиса конфигурации перед перезапуском
/usr/local/bin/traefik version --configfile=/etc/traefik/traefik.yml
# → Version:      v3.3.4
# → Codename:     ...

# 2. Перечитывание конфигурации systemd и старт сервиса
sudo systemctl daemon-reload
sudo systemctl enable --now traefik.service

# 3. Проверка статуса сервиса и таймаута остановки
systemctl show traefik.service -p TimeoutStopUSec,ActiveState
# → TimeoutStopUSec=1min
# → ActiveState=active

# 4. Проверка ответа локального эндпоинта ping
curl -s -i http://127.0.0.1:8082/ping
# → HTTP/1.1 200 OK
# → OK
```

---

### Сценарий 2: Zero-Downtime Rolling Update в Docker Compose v2

Развертывание двух реплик Traefik за локальным балансировщиком HAProxy в окружении Docker Compose с использованием директивы `stop_grace_period`.

#### Файл конфигурации `compose.yaml`

```yaml
services:
  haproxy:
    image: haproxy:2.8-alpine
    container_name: lb-edge
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    depends_on:
      - traefik-1
      - traefik-2
    networks:
      - edge-net

  traefik-1:
    image: traefik:v3.3
    container_name: traefik-node-1
    restart: unless-stopped
    stop_grace_period: 45s
    command:
      - "--global.checknewversion=false"
      - "--global.sendanonymoususage=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.web.transport.lifecycle.requestacceptgracetimeout=5s"
      - "--entrypoints.web.transport.lifecycle.gracetimeout=30s"
      - "--ping=true"
      - "--ping.entrypoint=web"
      - "--providers.file.directory=/etc/traefik/dynamic"
      - "--providers.file.watch=true"
    volumes:
      - ./dynamic:/etc/traefik/dynamic:ro
    networks:
      - edge-net

  traefik-2:
    image: traefik:v3.3
    container_name: traefik-node-2
    restart: unless-stopped
    stop_grace_period: 45s
    command:
      - "--global.checknewversion=false"
      - "--global.sendanonymoususage=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.web.transport.lifecycle.requestacceptgracetimeout=5s"
      - "--entrypoints.web.transport.lifecycle.gracetimeout=30s"
      - "--ping=true"
      - "--ping.entrypoint=web"
      - "--providers.file.directory=/etc/traefik/dynamic"
      - "--providers.file.watch=true"
    volumes:
      - ./dynamic:/etc/traefik/dynamic:ro
    networks:
      - edge-net

networks:
  edge-net:
    driver: bridge
```

#### Конфигурация балансировщика `haproxy.cfg`

```haproxy
global
    log stdout format raw local0

defaults
    log     global
    mode    http
    timeout connect 5s
    timeout client  50s
    timeout server  50s

frontend http_front
    bind *:80
    default_backend traefik_cluster

backend traefik_cluster
    balance roundrobin
    option httpchk GET /ping
    http-check expect status 200
    # Проверка каждые 2 секунды, исключение после 2 ошибок
    server t1 traefik-node-1:80 check inter 2s fall 2 rise 2
    server t2 traefik-node-2:80 check inter 2s fall 2 rise 2
```

#### Процедура поочередного обновления без простоя

```bash
# Шаг 1. Пересборка или обновление образа первой ноды
docker compose stop traefik-1
# → Контейнер получает SIGTERM, дорабатывает in-flight запросы в течение stop_grace_period (45s)
# → HAProxy фиксирует отключение t1 и переводит 100% трафика на traefik-node-2

docker compose up -d --no-deps traefik-1
# → Нода запускается, отдает 200 на /ping, HAProxy возвращает ее в балансировку

# Шаг 2. Пауза на стабилизацию
sleep 5

# Шаг 3. Обновление второй ноды
docker compose stop traefik-2
docker compose up -d --no-deps traefik-2

# Шаг 4. Проверка состояния всех контейнеров
docker compose ps
# → Name             State    Ports
# → lb-edge          Up       0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
# → traefik-node-1   Up       
# → traefik-node-2   Up       
```

---

### Сценарий 3: Zero-Downtime Rolling Update в Kubernetes (Deployment + PDB)

Production-манифест развертывания Traefik Ingress Controller в Kubernetes с гарантией отсутствия потерь пакетов во время ротации подов и дренажа рабочих узлов.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: traefik-ingress
  namespace: traefik
  labels:
    app.kubernetes.io/name: traefik
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
  template:
    metadata:
      labels:
        app.kubernetes.io/name: traefik
    spec:
      # Таймаут: preStop (10s) + requestAccept (5s) + grace (30s) + запас (25s) = 70s
      terminationGracePeriodSeconds: 70
      containers:
      - name: traefik
        image: traefik:v3.3.4
        args:
        - --entrypoints.web.address=:8000
        - --entrypoints.websecure.address=:8443
        - --entrypoints.traefik.address=:9000
        # Параметры жизненного цикла для входных точек
        - --entrypoints.web.transport.lifecycle.requestacceptgracetimeout=5s
        - --entrypoints.web.transport.lifecycle.gracetimeout=30s
        - --entrypoints.websecure.transport.lifecycle.requestacceptgracetimeout=5s
        - --entrypoints.websecure.transport.lifecycle.gracetimeout=30s
        # Включение проверки работоспособности
        - --ping=true
        - --ping.entrypoint=traefik
        - --providers.kubernetesingress=true
        lifecycle:
          preStop:
            exec:
              command:
              - /bin/sh
              - -c
              # Задержка для распространения EndpointSlice на все ноды кластера
              - "sleep 10"
        ports:
        - name: web
          containerPort: 8000
        - name: websecure
          containerPort: 8443
        - name: traefik
          containerPort: 9000
        readinessProbe:
          httpGet:
            path: /ping
            port: 9000
          initialDelaySeconds: 3
          periodSeconds: 3
          timeoutSeconds: 2
          failureThreshold: 2
        livenessProbe:
          httpGet:
            path: /ping
            port: 9000
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 2
          failureThreshold: 3
        resources:
          requests:
            cpu: 500m
            memory: 256Mi
          limits:
            cpu: 2000m
            memory: 1Gi
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: traefik-pdb
  namespace: traefik
spec:
  # Гарантирует наличие минимум 2 доступных реплик при drain ноды
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
```

---

### Сценарий 4: Высокая доступность Bare-Metal с Keepalived VRRP

Организация High Availability кластера из двух независимых узлов Traefik с виртуальным IP-адресом (VIP) и активным мониторингом эндпоинта `/ping`.

#### Конфигурация `/etc/keepalived/keepalived.conf` (Мастер-узел)

```ini
vrrp_script check_traefik_health {
    script "/usr/local/bin/check_traefik_ping.sh"
    interval 2
    timeout 2
    fall 2
    rise 2
    weight -30
}

vrrp_instance VI_TRAEFIK {
    state MASTER
    interface eth0
    virtual_router_id 55
    priority 110
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass Secr3tPass99
    }

    virtual_ipaddress {
        192.168.10.100/24 dev eth0 label eth0:vip
    }

    track_script {
        check_traefik_health
    }
}
```

#### Скрипт проверки работоспособности `/usr/local/bin/check_traefik_ping.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

# Опрос локального эндпоинта ping с жестким таймаутом в 1 секунду
PING_URL="http://127.0.0.1:8082/ping"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 1 "${PING_URL}" || true)

if [[ "${HTTP_CODE}" == "200" ]]; then
    exit 0
else
    # При остановке Traefik или ошибке скрипт возвращает 1
    # Keepalived снижает priority на 30, и VIP мигрирует на BACKUP узел
    exit 1
fi
```

Настройка прав исполнения:
```bash
sudo chmod 0755 /usr/local/bin/check_traefik_ping.sh
sudo systemctl restart keepalived
```

---

### Сценарий 5: Дренаж долгоживущих соединений (WebSocket, SSE, gRPC)

Конфигурация параметров проксирования для сервисов потоковой передачи данных и предотвращение каскадных сетевых аварий (Thundering Herd) при обновлении Traefik.

#### Конфигурация входной точки для WebSocket/SSE в `traefik.yml`

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      lifeCycle:
        requestAcceptGraceTimeout: 10s
        # Увеличенное время ожидания для завершения текущих диалогов
        graceTimeout: 60s
      respondingTimeouts:
        readTimeout: 0s        # 0s отключает таймаут чтения для бесконечных стримов
        writeTimeout: 0s       # 0s для удержания канала клиентом
        idleTimeout: 300s      # 5 минут на обнаружение оборванных TCP-сессий
```

#### Клиентский алгоритм реконнекта: Exponential Backoff с Random Jitter

При принудительном разрыве WebSocket сокета по истечении `graceTimeout` тысячи клиентов не должны одномоментно атаковать новые инстансы Traefik. На стороне клиентского приложения реализуется декоррелированный алгоритм повторных попыток:

```javascript
// Паттерн устойчивого подключения WebSocket
class ResilientWebSocket {
    constructor(url) {
        this.url = url;
        this.baseDelayMs = 1000;  // Начальная задержка 1 секунда
        this.maxDelayMs = 30000;  // Максимальная задержка 30 секунд
        this.attempts = 0;
        this.connect();
    }

    connect() {
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            console.log("Соединение успешно установлено");
            this.attempts = 0; // Сброс счетчика при успешном подключении
        };

        this.ws.onclose = (event) => {
            console.warn(`Соединение закрыто (код: ${event.code}). Подготовка реконнекта...`);
            this.scheduleReconnect();
        };

        this.ws.onerror = (err) => {
            this.ws.close();
        };
    }

    scheduleReconnect() {
        this.attempts++;
        // Экспоненциальный рост: baseDelay * 2^(attempts - 1)
        const exponentialDelay = Math.min(
            this.maxDelayMs,
            this.baseDelayMs * Math.pow(2, this.attempts - 1)
        );
        // Добавление случайного разброса (Full Jitter) от 0 до exponentialDelay
        const jitteredDelay = Math.random() * exponentialDelay;

        setTimeout(() => this.connect(), jitteredDelay);
    }
}
```

---

### Сценарий 6: Защита хранилища сертификатов `acme.json` при остановке

Файл `acme.json` хранит приватные ключи и метаданные Let's Encrypt сертификатов. Если Traefik получает `SIGKILL` в момент вызова `os.WriteFile()` или сериализации JSON, файл повреждается (размер становится 0 байт или нарушается синтаксис JSON), что блокирует повторный старт демона.

#### Скрипт автоматического резервного копирования перед остановкой

В systemd unit добавляется директива `ExecStopPresync`:

```ini
# Дополнение в секцию [Service] файла /etc/systemd/system/traefik.service
ExecStop=/usr/local/bin/backup_acme_state.sh
```

Содержимое скрипта `/usr/local/bin/backup_acme_state.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ACME_FILE="/var/lib/traefik/acme.json"
BACKUP_DIR="/var/backups/traefik"

mkdir -p "${BACKUP_DIR}"

if [[ -f "${ACME_FILE}" && -s "${ACME_FILE}" ]]; then
    # Валидация валидности JSON перед созданием снапшота
    if jq empty "${ACME_FILE}" >/dev/null 2>&1; then
        cp -p "${ACME_FILE}" "${BACKUP_DIR}/acme.json.bak"
        # Ротация до 5 последних валидных копий
        cp -p "${ACME_FILE}" "${BACKUP_DIR}/acme_$(date +%Y%m%d_%H%M%S).json"
        find "${BACKUP_DIR}" -name "acme_*.json" -type f -mtime +7 -delete
    else
        echo "WARNING: Файл ${ACME_FILE} поврежден! Пропуск создания резервной копии." >&2
    fi
fi
```

> [!IMPORTANT]
> При горизонтальном масштабировании Traefik (2 и более реплик) **запрещено монтировать один и тот же файл `acme.json` в несколько инстансов**. Traefik OSS не поддерживает распределенные файловые блокировки. Для HA-кластеров сертификаты необходимо получать через DNS-01 API независимо на каждом узле либо использовать внешнее централизованное управление сертификатами.

---

## Операции и команды

### Ручное тестирование перехвата сигналов и времени дренажа

```bash
# 1. Поиск PID основного процесса Traefik
MAIN_PID=$(pgrep -f "/usr/local/bin/traefik")
echo "PID процесса: ${MAIN_PID}"
# → PID процесса: 41258

# 2. Отправка сигнала SIGTERM для инициализации graceful shutdown
kill -TERM "${MAIN_PID}"

# 3. Мониторинг журнала systemd в реальном времени
journalctl -u traefik.service -n 20 --no-pager
# → {"level":"info","msg":"Stopping server gracefully","time":"2026-10-17T15:52:00Z"}
# → {"level":"info","msg":"Shutting down","time":"2026-10-17T15:52:05Z"}
# → {"level":"info","msg":"Server stopped","time":"2026-10-17T15:52:12Z"}
# → systemd[1]: traefik.service: Deactivated successfully.
# → systemd[1]: traefik.service: Consumed 1.428s CPU time.
```

### Проверка системных таймаутов и лимитов systemd

```bash
# Проверка действующих таймаутов завершения юнита
systemctl show traefik.service -p TimeoutStopUSec,KillMode,KillSignal,LimitNOFILE
# → TimeoutStopUSec=1min
# → KillMode=control-group
# → KillSignal=15
# → LimitNOFILE=1048576

# Точный замер времени остановки службы
time sudo systemctl stop traefik.service
# → real    0m7.241s
# → user    0m0.012s
# → sys     0m0.008s
```

### Нагрузочное тестирование непрерывности обслуживания (Zero-Downtime Verification)

Проверка отсутствия ошибок соединения (`502 Bad Gateway`, `503 Service Unavailable`, `Connection reset`) во время перезапуска Traefik с помощью утилиты генерации нагрузки `hey`:

```bash
# Запуск непрерывной нагрузки: 50 параллельных воркеров в течение 30 секунд
hey -z 30s -c 50 -q 10 https://traefik.example.internal/api/v1/health

# В параллельном терминале инициируется перезапуск службы или rollout пода:
# sudo systemctl restart traefik.service
# или kubectl rollout restart deployment/traefik-ingress -n traefik

# Ожидаемый результат в отчете hey:
# → Summary:
# →   Total:        30.0122 secs
# →   Slowest:      0.1451 secs
# →   Fastest:      0.0018 secs
# →   Average:      0.0112 secs
# →   Requests/sec: 499.79
# → 
# → Status code distribution:
# →   [200] 15000 responses
# → 
# → Error distribution:
# →   (Ошибки отсутствуют: 0 connection errors, 0 non-2xx)
```

### Мониторинг вывода подов и EndpointSlices в Kubernetes

```bash
# Отслеживание ротации подов в процессе rolling update
kubectl get pods -n traefik -l app.kubernetes.io/name=traefik -w
# → traefik-ingress-7b4bf9bc59-xyz1   1/1   Running       0   10m
# → traefik-ingress-865dc6df74-abc2   0/1   Pending       0   0s
# → traefik-ingress-865dc6df74-abc2   1/1   Running       0   3s
# → traefik-ingress-7b4bf9bc59-xyz1   1/1   Terminating   0   10m

# Проверка удаления IP пода из EndpointSlice во время preStop фазы
kubectl get endpointslices -n traefik -l kubernetes.io/service-name=traefik-ingress -o yaml
# → endpoints:
# → - addresses:
# →   - 10.244.2.45
# →   conditions:
# →     ready: true
# →     serving: true
# →     terminating: false
# → - addresses:
# →   - 10.244.1.89
# →   conditions:
# →     ready: false
# →     serving: true
# →     terminating: true
```

---

## Устранение неисправностей

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Ошибки `502 Bad Gateway` во время Rolling Update в K8s** | Отсутствует `preStop` hook; Kubelet посылает `SIGTERM` до того, как сетевые правила `iptables`/`eBPF` успевают обновиться на рабочих узлах. | `kubectl describe pod <pod>` — проверить секцию `Lifecycle`. В логах клиентов всплеск 502 ровно в момент старта удаления пода. | Добавить в контейнер `lifecycle.preStop.exec.command: ["sleep", "10"]` и убедиться, что `terminationGracePeriodSeconds >= 70`. |
| **Разрыв соединений `Connection reset by peer` при рестарте systemd** | `requestAcceptGraceTimeout` не задан (по умолчанию `0s`); ядро сразу шлет TCP RST на новые SYN-пакеты. | Снятие сетевого дампа во время рестарта: `tcpdump -nn -i any "tcp[tcpflags] & tcp-rst != 0" and port 443`. | В секции `transport.lifeCycle` выставить `requestAcceptGraceTimeout: 5s` для всех рабочих `entryPoints`. |
| **Повреждение файла сертификатов `acme.json` (размер 0 байт)** | Процесс принудительно убит по `SIGKILL` во время записи сертификата на диск из-за истечения `TimeoutStopSec`. | `journalctl -u traefik` содержит `systemd: Unit traefik.service stop-sigterm timed out. Killing.`. Проверить `ls -la /var/lib/traefik/acme.json`. | Увеличить `TimeoutStopSec` в unit-файле до 60–90 секунд; восстановить файл из резервной копии; настроить pre-stop backup. |
| **Команда `kubectl drain` блокируется бесконечно** | Некорректно настроенный `PodDisruptionBudget` (`minAvailable` равен общему числу реплик). | `kubectl get pdb -n traefik` показывает `ALLOWED DISRUPTIONS: 0`. Вывод drain: `Cannot evict pod: PodDisruptionBudget is violated`. | Установить `minAvailable: 1` при 2 репликах или переключиться на `maxUnavailable: 1`. |
| **Массовый обрыв WebSocket сессий каждые 30 секунд при деплое** | `graceTimeout` меньше типового времени активности сессии; клиенты одновременно шлют реконнект без джиттера. | Логи Traefik: принудительное закрытие клиентских сокетов по истечении `graceTimeout`. Всплеск нагрузки на CPU из-за лавины повторных подключений. | Увеличить `graceTimeout` до 60–120 секунд; на клиентах внедрить алгоритм Exponential Backoff со случайным разбросом (Full Jitter). |
| **Конфликт `bind: address already in use` при обновлении DaemonSet** | Попытка запуска новой реплики с `hostNetwork: true` или `hostPort` на том же физическом узле, где еще работает старая реплика. | `kubectl describe pod` показывает статус `CrashLoopBackOff` или `FailedToStartContainer` с ошибкой привязки сокета. | Для DaemonSet с host-портами использовать стратегию `RollingUpdate` с `maxUnavailable: 1` (одновременное поднятие на одном хосте невозможно). |
| **Keepalived переходит в Split-Brain или преждевременно ротирует VIP** | Скрипт проверки `/ping` использует слишком малый таймаут или балансировщик перегружен всплеском запросов. | `journalctl -u keepalived` фиксирует частую смену статусов `VRRP_Instance(...) Entering FAULT / BACKUP state`. | В `vrrp_script` установить `fall 3`, `rise 2`, `timeout 2`, а в curl задать `--max-time 1` и таймаут между проверками `interval 2`. |
| **Pod зависает в статусе `Terminating` на 10 минут** | Зависшие горутины из-за неотвечающих upstream-бэкендов при отсутствии `respondingTimeouts`. | `kubectl get pod -n traefik` видит pod в `Terminating`. `netstat -tanp \| grep traefik` показывает сокеты в `CLOSE_WAIT`. | Задать жесткие лимиты `respondingTimeouts.readTimeout: 60s` и `respondingTimeouts.writeTimeout: 60s` на entrypoints Traefik. |

---

## Рекомендации

1. **Строгое соблюдение иерархии таймаутов:**
   Ни при каких обстоятельствах не допускайте ситуации, при которой внешний супервизор (systemd, Kubelet) отправляет `SIGKILL` раньше, чем Traefik завершит внутренние фазы дренажа:
   - **В systemd:** `TimeoutStopSec` $\ge$ `requestAcceptGraceTimeout` + `graceTimeout` + 20s.
   - **В Kubernetes:** `terminationGracePeriodSeconds` $\ge$ `preStop (sleep)` + `requestAcceptGraceTimeout` + `graceTimeout` + 20s.
2. **Всегда используйте `preStop` задержку в Kubernetes:**
   Для продуктивных Ingress-контроллеров задержка `sleep 10` (для крупных кластеров — `sleep 15`) является обязательным условием исключения ошибок `502 Bad Gateway` при перестроении EndpointSlices.
3. **Оптимизация параметров ядра Linux для быстрого дренажа TCP:**
   На bare-metal узлах в файле `/etc/sysctl.d/99-traefik.conf` зафиксируйте параметры сетевого стека:
   ```ini
   # Расширение очереди неполных соединений и входящих сокетов
   net.core.somaxconn = 65535
   net.ipv4.tcp_max_syn_backlog = 65535

   # Повторное использование TIME_WAIT сокетов для исходящих подключений к бэкендам
   net.ipv4.tcp_tw_reuse = 1

   # Расширение диапазона клиентских портов
   net.ipv4.ip_local_port_range = 10240 65535

   # Ускорение очистки оборванных TCP KeepAlive сессий
   net.ipv4.tcp_keepalive_time = 300
   net.ipv4.tcp_keepalive_intvl = 15
   net.ipv4.tcp_keepalive_probes = 5
   ```
4. **Не используйте SIGHUP для перезагрузки:**
   Не пытайтесь слать `SIGHUP` процессу Traefik. Разделяйте статическую и динамическую конфигурации. Динамика применяется мгновенно через файловый вотчер, а изменения статики производите исключительно методом поочередной ротации узлов.
5. **Изоляция и валидация хранилища `acme.json`:**
   Никогда не делите файл сертификатов между разными инстансами Traefik через NFS или сетевые тома. Настройте автоматическое резервное копирование файла сертификатов перед каждым плановым перезапуском.

---

## Дополнительная информация

- [Traefik на bare-metal](./traefik-bare-metal.md) — развертывание systemd, обработка сигналов и тюнинг сетевого стека Linux.
- [High Availability Traefik](./traefik-high-availability.md) — кластеризация без разделяемого состояния, эндпоинт `/ping` и балансировка.
- [Traefik в Kubernetes](./traefik-kubernetes.md) — IngressRoute, CRD, RBAC, Probes и интеграция с Gateway API.
- [Развертывание Traefik: Blue/Green, Canary, Rolling Update](./traefik-deployments.md) — управление трафиком и жизненным циклом приложений.
- [Пул соединений и Keep-Alive в Traefik](./traefik-connection-pooling.md) — управление жизненным циклом входящих и исходящих сокетов.
- [Протоколы и потоки данных](./traefik-protocols-advanced.md) — специфика работы WebSocket, SSE, HTTP/2 и gRPC при остановке прокси.
- [Управление сервисами systemd](../../Linux/Core/systemd/service_management.md) — сигналы завершения, таймауты и управление жизненным циклом юнитов.
