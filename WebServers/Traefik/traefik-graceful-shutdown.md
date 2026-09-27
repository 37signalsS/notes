# Graceful Shutdown и Zero-Downtime Deploy в Traefik

## Определения

**Graceful shutdown** — корректное завершение работы Traefik без потерь активных соединений: процесс перестает принимать новый трафик, дожидается завершения in-flight запросов и только тогда выходит.

**SIGTERM** — стандартный сигнал завершения процесса (`kill -15`). Traefik перехватывает его и запускает graceful shutdown.

**SIGKILL** — принудительное завершение (`kill -9`). Traefik не может его перехватить; все активные соединения обрываются, возможна порча `acme.json`.

**Drain** — режим ноды/инстанса, при котором она перестает принимать новый трафик, но продолжает обрабатывать существующие соединения.

**preStop hook** — Kubernetes-хук, выполняемый перед отправкой SIGTERM контейнеру. Используется для компенсации задержки распространения изменений в Endpoints.

**terminationGracePeriodSeconds** — таймаут в Kubernetes, за который под должен завершиться после SIGTERM; по истечении Kubelet отправляет SIGKILL.

**TimeoutStopSec** — таймаут systemd, за который сервис должен остановиться после SIGTERM; по истечении systemd отправляет SIGKILL.

**requestAcceptGraceTimeout** — период в Traefik, в течение которого инстанс продолжает принимать новые соединения после получения SIGTERM (добор in-flight запросов).

**graceTimeout** — максимальное время ожидания завершения активных соединений после остановки приема нового трафика.

## Базовые концепции

### Последовательность graceful shutdown в Traefik

При получении SIGTERM Traefik выполняет:

1. **Остановка приема новых соединений** на всех entrypoints
2. **requestAcceptGraceTimeout** — продолжает принимать новые соединения еще это время (добор in-flight)
3. **Ожидание завершения активных соединений** до `graceTimeout`
4. **Завершение ACME renewal** (если активно)
5. **Сохранение состояния** и выход с кодом `0`

Если шаг 3 не успевает за `graceTimeout` + `terminationGracePeriodSeconds`/`TimeoutStopSec` — процесс получает SIGKILL.

### systemd ↔ Traefik: правильная конфигурация

`TimeoutStopSec` в unit-файле должен быть **больше** чем сумма `requestAcceptGraceTimeout` + `graceTimeout` в Traefik. Иначе systemd убьет процесс раньше, чем Traefik завершит gracefully.

Пример правильной конфигурации:

```ini
# /etc/systemd/system/traefik.service
[Service]
Type=simple
User=traefik
Group=traefik
ExecStart=/usr/local/bin/traefik --configfile=/etc/traefik/traefik.yml
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5

# Graceful shutdown
TimeoutStopSec=90

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/traefik /var/log/traefik
LimitNOFILE=100000
LimitNPROC=10000
```

В `traefik.yml`:

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      lifeCycle:
        requestAcceptGraceTimeout: 5s
        graceTimeout: 30s
```

Итого: Traefik может работать до `5s + 30s = 35s`, systemd ждет `90s` — безопасный запас.

### K8s: preStop + readinessProbe + PDB

Без `preStop` возникает гонка:
1. Kubelet отправляет SIGTERM
2. `readinessProbe` сразу начинает падать
3. LB убирает pod из Endpoints
4. Traefik еще не завершил in-flight запросы
5. Клиенты получают 503

`preStop` hook компенсирует это:

```yaml
spec:
  containers:
  - name: traefik
    lifecycle:
      preStop:
        exec:
          command:
          - /bin/sh
          - -c
          - sleep 5
    readinessProbe:
      httpGet:
        path: /ping
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
    livenessProbe:
      httpGet:
        path: /ping
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 10
```

`sleep 5` дает время LB на распространение изменений Endpoints до того как Traefik остановит прием трафика.

**PodDisruptionBudget** защищает от voluntary eviction (drain ноды), но **не блокирует** Rolling Update Deployment:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: traefik
  namespace: traefik
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
```

Важно: `minAvailable <= replicas - 1`, иначе drain зависнет.

### WebSocket и SSE при shutdown

Traefik **не отправляет** WebSocket close frame при shutdown. Соединение просто обрывается. Клиент должен реализовать reconnect logic.

SSE streaming — то же поведение: соединение рвется, клиент получает ошибку сети.

Практика:
- Устанавливайте `graceTimeout` >= максимальное время idle WebSocket/SSE соединения
- На клиенте: exponential backoff + jitter для reconnect
- Мониторьте длительные соединения через `traefik_entrypoint_requests_duration_seconds`

### Внешний LB: passive health check

LB должен понимать, что Traefik в drain. Это работает через `/ping` endpoint:

- **Active health check**: LB периодически шлет GET /ping
- **Passive health check**: LB отслеживает 503/502 от Traefik и убирает ноду из пула

При shutdown Traefik отвечает `/ping` → `503` (в drain-периоде). LB убирает ноду.

**Keepalived** (bare-metal L4):

```bash
# /etc/keepalived/keepalived.conf
vrrp_instance VI_1 {
  virtual_router_id 51
  priority 100
  advert_int 1
  authentication {
    auth_type PASS
    auth_pass secret
  }
  virtual_ipaddress {
    192.168.1.100
  }
  track_script {
    misc_check
  }
}

vrrp_script misc_check {
  script "/usr/local/bin/check_traefik.sh"
  interval 2
  weight -20
  fall 2
  rise 2
}
```

`check_traefik.sh`:

```bash
#!/bin/bash
if curl -sf http://127.0.0.1:8082/ping > /dev/null; then
  exit 0
else
  exit 1
fi
```

### Graceful reload vs restart

Traefik **не поддерживает** graceful reload по SIGHUP для статической конфигурации. `SIGHUP` в systemd unit обычно вызывает `ExecReload` — в Traefik это просто проверка конфига, а не перезагрузка.

Для обновления статической конфигурации (entrypoints, providers, ACME) без даунтайма:
1. Rolling restart инстансов за LB
2. Или внешний LB с passive health check (автоматически убирает/добавляет ноды)

Динамическая конфигурация (роутеры, middleware) перезагружается без рестарта через providers.file.watch или KV-store watch.

### ACME certificates при shutdown

Traefik завершает активный ACME renewal перед shutdown. Но если Traefik был остановлен > 30 дней — certificates expire, нужен manual intervention.

Практика:
- Мониторьте время shutdown Traefik
- При planned maintenance: проверяйте срок certificates до остановки
- Backup `acme.json` перед rolling restart

## Практические сценарии

### Сценарий 1: Zero-downtime restart в Docker Compose

```bash
# Rolling restart с двумя репликами Traefik
docker compose up -d --scale traefik=2 --no-recreate

# Проверка, что обе реплики работают
docker compose ps traefik

# Уменьшение обратно до 1
docker compose up -d --scale traefik=1 --no-recreate
```

Но это работает только если Traefik stateless и конфиг общий. Для ACME используйте DNS-01 challenge (shared `acme.json` невозможен).

### Сценарий 2: Rolling update в Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: traefik
  namespace: traefik
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
    spec:
      terminationGracePeriodSeconds: 90
      containers:
      - name: traefik
        image: traefik:v3.4
        args:
        - --configfile=/etc/traefik/traefik.yml
        lifecycle:
          preStop:
            exec:
              command:
              - /bin/sh
              - -c
              - sleep 5
        readinessProbe:
          httpGet:
            path: /ping
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /ping
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10
```

`maxUnavailable: 0` гарантирует, что при обновлении всегда есть минимум 2 готовых поды.

### Сценарий 3: graceful shutdown для WebSocket-сервиса

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      respondingTimeouts:
        writeTimeout: 3600s    # 1 час для длительных WebSocket
      lifeCycle:
        requestAcceptGraceTimeout: 10s
        graceTimeout: 60s       # дать время на закрытие WebSocket
```

На клиенте: reconnect с exponential backoff.

### Сценарий 4: Keepalived + Traefik (bare-metal HA)

```bash
# check_traefik.sh
#!/bin/bash
# Health check для keepalived
STATUS=$(curl -sf http://127.0.0.1:8080/ping)
if [ "$STATUS" = "OK" ]; then
  exit 0
else
  exit 1
fi
```

При остановке Traefik:
1. Traefik получает SIGTERM
2. `/ping` отвечает 503 (в drain-периоде)
3. Keepalived отмечает ноду как unhealthy
4. VIP переезжает на другой инстанс
5. Новые запросы идут на живую ноду

### Сценарий 5: MetalLB + Traefik (K8s bare-metal)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: traefik
  namespace: traefik
spec:
  type: LoadBalancer
  loadBalancerIP: 192.168.1.100
  ports:
  - name: web
    port: 80
    targetPort: 80
  - name: websecure
    port: 443
    targetPort: 443
  selector:
    app.kubernetes.io/name: traefik
```

MetalLB шлет health check на `/ping`. При drain pod'a:
1. Pod убирается из Endpoints
2. MetalLB перестает отправлять трафик на эту ноду
3. Traefik завершает in-flight запросы

### Сценарий 6: Graceful shutdown при ACME renewal

```bash
# Проверка активного renewal перед rolling restart
kubectl logs -n traefik -l app.kubernetes.io/name=traefik | grep -i acme

# Если renewal активен — дождаться завершения или отменить
# Traefik завершит renewal сам при SIGTERM, но лучше дождаться
```

## Операции и команды

```bash
# Проверка, что Traefik обрабатывает SIGTERM gracefully
kill -TERM $(pgrep -f traefik)
# → Лог: "Starting TCP Server" ... "Stopping" → exit code 0

# Проверка TimeoutStopSec в systemd
systemctl show traefik | grep TimeoutStopSec
# → TimeoutStopSec=90

# Проверка terminationGracePeriodSeconds в K8s
kubectl get pod -n traefik -o jsonpath='{.spec.terminationGracePeriodSeconds}'
# → 90

# Проверка preStop hook
kubectl get pod -n traefik -o jsonpath='{.spec.containers[0].lifecycle.preStop.exec.command}'
# → [/bin/sh -c sleep 5]

# Проверка readinessProbe
kubectl describe pod -n traefik <pod-name> | grep -A5 readinessProbe

# Проверка PDB
kubectl get pdb -n traefik
# → NAME    MIN AVAILABLE   MAX UNAVAILABLE   AGE
# → traefik 1               N/A               10d

# Проверка, что LB видит drain
curl -s http://<lb-ip>:8080/ping
# → 503 (если Traefik в drain)
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Потеря запросов при restart** | `graceTimeout` слишком мал, `TimeoutStopSec` < `graceTimeout` | Увеличьте `graceTimeout` и `TimeoutStopSec` |
| **Pod зависает в Terminating** | `terminationGracePeriodSeconds` истек, но процесс не завершился | Увеличьте таймаут, проверьте зависшие соединения |
| **LB дергает ноды** | `/ping` отвечает 503 при drain, нет passive health check | Настройте passive health check на LB |
| **WebSocket разрываются при rolling update** | `graceTimeout` меньше времени жизни WebSocket | Увеличьте `graceTimeout`, добавьте reconnect на клиенте |
| **PDB блокирует drain** | `minAvailable: 2`, но реплик только 2 | Установите `minAvailable <= replicas - 1` |
| **preStop не работает** | Неправильный command/args в lifecycle hook | Проверьте `kubectl describe pod` |
| **Traefik не останавливается** | Долгие запросы бэкенда, `graceTimeout` исчерпан | Увеличьте `graceTimeout` или настройте таймауты бэкенда |
| **SIGKILL corruption acme.json** | `TimeoutStopSec` < время graceful shutdown | Увеличьте `TimeoutStopSec`, backup `acme.json` перед restart |
| **Readiness probe падает при shutdown** | Отсутствует `preStop` hook | Добавьте `preStop` с sleep |
| **Keepalived split-brain** | Обе ноды думают, что они master | Настройте unicast, фиксированные приоритеты |

## Рекомендации

- Всегда настраивайте `graceTimeout` и `requestAcceptGraceTimeout` в production
- `TimeoutStopSec`/`terminationGracePeriodSeconds` должны быть **больше** чем `graceTimeout`
- Для WebSocket/SSE: `graceTimeout` >= максимальное время idle соединения + запас
- Всегда используйте `preStop` hook в K8s с `sleep 5` (или больше)
- PDB: `minAvailable <= replicas - 1`
- Внешний LB должен иметь passive health check по `/ping`
- Мониторьте время graceful shutdown: алерт если > N секунд
- Backup `acme.json` перед rolling restart
- Тестируйте graceful shutdown в staging перед production

## Дополнительная информация

- [Traefik на bare-metal](./traefik-bare-metal.md) — systemd unit, SIGTERM handling
- [High Availability Traefik](./traefik-high-availability.md) — rolling update, `/ping` health check
- [Traefik в Kubernetes](./traefik-kubernetes.md) — CRD, RBAC, PDB, probes
- [Протоколы и потоки данных](./traefik-protocols-advanced.md) — WebSocket, SSE, HTTP/2 draining
