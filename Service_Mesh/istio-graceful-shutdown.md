# Корректное завершение (Graceful Shutdown) и длинные соединения в Istio

## Определения

**Graceful Shutdown в mesh** — процесс остановки пода/прокси без обрыва активных запросов: сначала прекращается приём нового трафика (эндпоинт удаляется из реестра), затем обрабатываются in-flight-запросы, и только потом процесс завершается.

**Drain (дренаж)** — период, в течение которого Envoy перестаёт принимать *новые* соединения (listener-ы переводятся в draining), но продолжает обслуживать уже установленные.

**`terminationDrainDuration`** — длительность, на которую прокси продолжает обрабатывать активные запросы после получения SIGTERM, прежде чем завершиться. Задаётся глобально (`ProxyConfig`), через `proxy.istio.io/config` или env `TERMINATION_DRAIN_DURATION`.

**`drainDuration`** — параметр bootstrap Envoy (ProxyConfig), управляющий фазой draining listener'ов при завершении (поведение модуля draining, выключение приёма новых соединений).

**`EXIT_ON_ZERO_ACTIVE_CONNECTIONS`** — env istio-agent: прокси досрочно завершится, как только не останется активных соединений (после дренажа). Ускоряет завершение пода без потери in-flight-трафика.

**preStop hook** — команда/сна в lifecycle контейнера, выполняемая kubelet до отправки SIGTERM; компенсирует запаздывание удаления эндпоинтов из сети (propagation delay).

**Длинноживущие соединения (long-lived)** — gRPC-стримы, WebSocket, SSE: устанавливаются один раз и держатся долго; при rolling-рестарте они обязаны быть аккуратно переподключены, иначе клиенты получают обрыв.

---

## Основные концепции

### Последовательность событий при остановке пода в Sidecar-модели

1. **Удаление эндпоинта**: контроллер убирает под из `EndpointSlice` (глобальная цепочка, занимает от сотен мс до секунд).
2. **preStop-хук** приложения: `sleep` на 5–15 секунд даёт фору цепочке распространения.
3. **SIGTERM** контейнерам: приложение начинает собственный drain; istio-proxy переходит в draining-режим.
4. **Drain прокси**: Envoy закрывает приём новых соединений (`drainDuration`), завершает in-flight-запросы в течение `terminationDrainDuration`.
5. **Выход**: прокси завершается (в случае `EXIT_ON_ZERO_ACTIVE_CONNECTIONS=true` — сразу после обнуления активных соединений).
6. **SIGKILL** по истечении `terminationGracePeriodSeconds`, если кто-то завис.

Эти принципы на уровне Kubernetes (гонка двух цепочек, формула расчёта) подробно описаны в [Pod Terminating: graceful shutdown](../Kubernetes/Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md) — для mesh важно применить их к прокси.

### Ключевые параметры Istio для завершения прокси

| Параметр | Где задаётся | Назначение |
| :--- | :--- | :--- |
| `terminationDrainDuration` | `meshConfig.defaultConfig.terminationDrainDuration` или `proxy.istio.io/config` | Секунды на доводку in-flight запросов после SIGTERM |
| `drainDuration` | `proxy.istio.io/config` (bootstrap) | Продолжительность draining-фазы listener'ов |
| `EXIT_ON_ZERO_ACTIVE_CONNECTIONS` | env `istio-agent` (`kubectl set env` / `proxyMetadata`) | Выход сразу после обнуления активных соединений |
| `terminationGracePeriodSeconds` | Pod spec | Общее время на завершение пода (должно покрыть preStop + drain приложения + drain прокси) |

### Порядок завершения контейнеров (Native Sidecar)

С Kubernetes 1.28+ Istio внедряет sidecar как «native sidecar» (`restartPolicy: Always` в initContainers). Особенности terminateрования:
- kubelet останавливает контейнеры в конвейере: сначала основные приложения, затем sidecar-контейнеры; sidecar-прокси держит drain до последнего.
- Сумарное время на завершение ограничено `terminationGracePeriodSeconds` пода — его нужно увеличивать на время drain прокси, иначе прокси будет убит SIGKILL при незавершённых запросах.
- Проверка типа sidecar: `istioctl proxy-status | ...` и `kubectl get pod -o jsonpath='{.spec.initContainers[*].name}'` (должен быть `istio-init`/`istio-proxy` в initContainers) — см. [Прокси Sidecar](./proxy_sidecar.md).

### Длинноживущие соединения (gRPC, WebSocket, SSE)

Проблема: при rolling-restart старые поды умирают, и все потоковые соединения на них рвутся с `RST`/`GOAWAY`.

Правила для производства:
- **Клиентская сторона**: ретраи на идемпотентных вызовах, переустановка gRPC-стримов, WebSocket-reconnect.
- **Прокси**: `terminationDrainDuration` позволяет довести уже открытые стримы до конца описания (для стрима это «не прерывать пока не завершится»).
- **Keepalive**: настраивают `tcp.keepalive` / ping, чтобы idle-стримы не текли (см. [istio-protocol-detection.md](./istio-protocol-detection.md)).
- **Планирование**: используйте `PodDisruptionBudget` для контроля количества потерянных реплик при voluntary eviction (см. [istio_architecture.md](./istio_architecture.md)).

### Ambient: завершение без sidecar

В Ambient-модели у пода нет sidecar-контейнера: L4-трафик обрабатывает node/Ztunnel, L7 — waypoint (отдельный Deployment).
- Завершение пода ничем не отличается от обычного Kubernetes: важно правильно выставить app-readiness и `terminationGracePeriodSeconds`.
- Waypoint при обновлении получает drain независимо от приложений (это «общий» прокси, а не per-pod).
- Риск 502 при закрытии waypoint во время стримминга — снижается ретраями клиента (как в Sidecar-модели).

---

## Практические сценарии

### Сценарий 1: Базовая конфигурация корректного завершения (Sidecar)

Задаём глобальный drain прокси и per-pod настройки:

```yaml
# meshConfig: глобальный terminationDrainDuration
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
metadata:
  name: graceful-shutdown
spec:
  meshConfig:
    defaultConfig:
      terminationDrainDuration: 15s
```

```yaml
# per-pod: аннотация на Deployment приложения
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        proxy.istio.io/config: |
          terminationDrainDuration: 15s
          concurrency: 2
    spec:
      terminationGracePeriodSeconds: 45   # preStop(10) + drain app(15) + drain proxy(15) + запас(5)
      containers:
      - name: my-app
        image: my-app:1.0
        lifecycle:
          preStop:
            exec:
              command: ["sh", "-c", "sleep 10"]
```

### Сценарий 2: Быстрое завершение вспомогательных подов (Job/дочерних)

Для подов, которые не должны висеть в draining (prometheus-скрейперы, однократные задачи):

```yaml
spec:
  terminationGracePeriodSeconds: 10
  containers:
  - name: istio-proxy
    env:
    - name: EXIT_ON_ZERO_ACTIVE_CONNECTIONS
      value: "true"
```

Поведение: прокси завершится сразу, как только `upstream_cx_active == 0`, не дожидаясь таймаута.

Проверка активных соединений:

```bash
kubectl exec -n production deploy/my-app -c istio-proxy -- curl -s localhost:15000/stats | grep upstream_cx_active
# → cluster.outbound|8080||my-service.production.svc.cluster.local.upstream_cx_active: 0
```

### Сценарий 3: Rolling-рестарт без пропуска трафика (проверка)

```bash
# 1. Rolling restart приложения
kubectl rollout restart deployment/my-app -n production

# 2. Нагрузка во время рестарта (например, vegeta)
vegeta attack -duration=20s -rate=500 -targets=targets.txt | vegeta report
# → Requests  : 10000
# → Success   : 100.00%   ← с корректным drain нет 5xx
# → Error Set : (none)

# 3. Убедиться, что не было 502 в логах прокси старого пода
kubectl logs -n production deploy/my-app --previous -c istio-proxy | grep -c " 502 "
# → 0
```

### Сценарий 4: Принудительный drain Envoy для диагностики

```bash
# Перевести listener'ы в draining (заглушка приёма новых соединений)
kubectl exec -n production deploy/my-app -c istio-proxy -- \
  curl -s -X POST 'localhost:15000/drain_listeners?inboundonly&graceful'

# Просмотр состояния активных соединений (меньше 1 → можно ждать выхода)
kubectl exec -n production deploy/my-app -c istio-proxy -- curl -s localhost:15000/stats | grep "upstream_cx_active"

# Вернуть listener'ы (для тестов)
kubectl exec -n production deploy/my-app -c istio-proxy -- curl -s -X POST 'localhost:15000/drain_listeners?inboundonly&inhibit'
```

### Сценарий 5: Переподключение длинных gRPC-стримов

```bash
# Пример клиентской логики на стороне приложения (Go):
#   - retry c exponential backoff на DeadlineExceeded/Unavailable;
#   - при GOAWAY/RST: повторный NewStream заново.

# Проверка, что стримы переживают рестарт бэкенда
kubectl rollout restart deployment/backend -n production
kubectl exec deploy/client -n production -- grpcurl -plaintext \
  backend:50051 myservice/Method -d '{}'
# → {"ok":true}  ← стрим переподключён после рестарта
```

### Диагностика проблем завершения

```bash
# 1. Пoд висит в Terminating
kubectl get pods -n production | grep Terminating

# 2. События пода (почему долго завершается)
kubectl describe pod my-app-xxx -n production | tail -30
# → застрял preStop, или ожидание drain, или SIGKILL по таймауту

# 3. Верификация типа sidecar и его drain-настроек
istioctl proxy-config bootstrap deploy/my-app -n production | grep -A2 terminating
# → termination: {...: terminationDrainDuration: 15s}

# 4. Логи завершения прокси
kubectl logs -n production deploy/my-app -c istio-proxy | grep -iE "drain|shutdown|termination" | tail
```

---

## Типичные ошибки и устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| 502/504 при rolling-рестарте | Эндпоинт удалён быстро, но прокси не успел drain; или preStop мал | Увеличить `preStop`, `terminationDrainDuration`, `terminationGracePeriodSeconds` |
| Поды висят в `Terminating` долго | Прокси ждёт истечения `terminationDrainDuration` или preStop долгий; либо grace period слишком большой и SIGKILL не приходит вовремя | Уменьшить `terminationDrainDuration`, включить `EXIT_ON_ZERO_ACTIVE_CONNECTIONS` для не-load-workload; скорректировать `terminationGracePeriodSeconds` |
| gRPC-стрим обрывается на каждом deploy | Стрим на старом поде без переподключения | Клиентский retry/reconnect; keepalive на стрим; drain прокси; порядок реплик |
| `istio-proxy` убит по SIGKILL до конца in-flight | `terminationGracePeriodSeconds` < preStop+drain | Формула: grace ≥ preStop + drain app + drain proxy + запас 5–10s |
| После `kubectl rollout restart` первые ответы 503 | Новый под принял трафик до готовности прокси | Использовать readiness от прокси (порт 15021/healthz/ready); `startupProbe` на sidecar |
| Длинный idle считает conn активными (не выходит) | Активных соединений много, `EXIT_ON_ZERO_ACTIVE_CONNECTIONS` не задан | Включить env; настроить keepalive; сократить потоковые в scale-down |

---

## Лучшие практики эксплуатации

1. **Формула времени**: `terminationGracePeriodSeconds = preStop (5–15s) + drain приложения (5–30s) + terminationDrainDuration (10–20s) + 5–10s запас`.
2. **Разделяйте drain приложения и прокси**: приложение закрывает сокеты по-своему, прокси — своим; не доверяйте одному параметру для обоих.
3. **Включайте `EXIT_ON_ZERO_ACTIVE_CONNECTIONS` для**: Job, CronJob, скрейперов, подов без длинных стримов — ускоряет/упорядочивает завершение.
4. **Глобальные значения в `proxy.istio.io/config`**: задавайте `terminationDrainDuration` и `concurrency` через аннотацию на подах, а не мутация во время эксплуатации.
5. **Readiness !== для drain**: readiness-пробa прокси (15021) управляет попаданием трафика в под; drain управляет завершением. Настраивайте и то, и другое.
6. **Мониторинг 5xx на деплоях**: алерт на `502`/`504` с флагом `UC` в access-логах (Upstream Connection failure) → признак неправильной остановки прокси.
7. **Ambient**: не ждите per-pod drain — тестируйте перезапуски waypoint и следите за ретраями клиентов.
8. **PDB для критичных workload**: ограничьте одновременное voluntary-terminating подов, чтобы не терять все копии стрим-сервиса разом.

---

## Дополнительная информация

### Связь с другими темами

- Базовые механизмы Kubernetes (гонка EndpointSlice vs SIGTERM) — [Pod Terminating: graceful shutdown](../Kubernetes/Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md).
- Типы sidecar (native) и их диагностика — [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md).
- Управление долгоживущими TCP (keepalive) — [Определение протокола трафика](./istio-protocol-detection.md).
- HA и PDB для istiod/шлюзов — [Архитектура и компоненты Istio](./istio_architecture.md).

### См. также

- [Исходящий шлюз (Egress Gateway)](./istio-egress-gateway.md)
- [Управление трафиком в Service Mesh](./traffic_management.md)
- [Тюнинг производительности Istio](./istio-performance-tuning.md)

Документация: [Istio: Lifecycle of the Envoy Proxy](https://istio.io/latest/docs/ops/deployment/lifecycle/).