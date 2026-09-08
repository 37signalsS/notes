# Pod Terminating — основные определения и механизмы

## Определения

**`Terminating` (Состояние завершения)** — статус Pod, отображаемый в CLI (`kubectl get pods`), который указывает на то, что объект получил `deletionTimestamp`, но ещё не был полностью удалён из API-сервера. Технически Pod может оставаться в фазе `Running` или `Unknown`, пока процесс завершения не будет подтверждён `kubelet`. Статус `Terminating` — это не отдельная фаза жизненного цикла (поды переходят только через `Pending`, `Running`, `Succeeded`, `Failed`, `Unknown`), а метка, добавляемая API-сервером при наличии `deletionTimestamp`.

**`deletionTimestamp`** — временная метка (RFC 3339), устанавливаемая API-сервером в метаданных объекта при получении запроса на удаление (через `DELETE`, `kubectl delete` или Eviction API). Её наличие переводит Pod в режим «корректного завершения» (graceful shutdown) и блокирует его выборку сервисами (Service) и контроллерами (EndpointSlice). До тех пор, пока `deletionTimestamp` установлен, повторные запросы `DELETE` на тот же объект возвращают код `200 OK` (идемпотентность), а не `404`.

**`deletionGracePeriodSeconds`** — время (в секундах), отведённое на завершение Pod после установки `deletionTimestamp`. По умолчанию значение等于 `terminationGracePeriodSeconds` из спецификации Pod. Если Pod был создан через `kubectl delete --grace-period=<N>`, именно это значение будет записано в `deletionGracePeriodSeconds`. Отсчёт начинается с момента установки `deletionTimestamp`, и по его истечении API-сервер помечает объект для удаления из `etcd`.

**`terminationGracePeriodSeconds`** — общее время (по умолчанию 30 секунд), выделяемое поду на самозавершение. **Важно:** этот интервал включает в себя как выполнение `PreStop Hook`, так и время на обработку сигнала `SIGTERM`. Если хук выполняется дольше этого времени, `SIGTERM` может не быть отправлен до `SIGKILL`. Минимальное значение — 0 (немедленный `SIGKILL`), максимальное — 3600 (1 час). Значение 0 допустимо только для Pod, создающихся через Eviction API.

**PreStop Hook** — команда (exec) или HTTP-запрос (httpGet), выполняемый `kubelet` непосредственно перед отправкой сигнала `SIGTERM`. Используется для завершения транзакций, выхода из кворума или искусственной задержки для обновления сетевых таблиц. Типы:
- `exec` — выполняет команду внутри контейнера. Если команда завершается с кодом >0, хук считается неудачным (`FailedPreStopHook`), но `SIGTERM` всё равно отправляется.
- `httpGet` — отправляет HTTP GET-запрос на указанный URL и порт. Хук считается успешным при HTTP-коде 200–399.

Время выполнения PreStop засчитывается в общее `terminationGracePeriodSeconds`. Если хук выполняется дольше лимита, контейнер будет убит по `SIGKILL` до завершения хука.

**`SIGTERM` (Signal Termination)** — стандартный сигнал POSIX (номер 15), отправляемый основному процессу (PID 1) в каждом контейнере для инициации корректной остановки. Сигнал перехватывается процессом, если тот зарегистрировал обработчик через `signal()` или `sigaction()`. Если обработчик не зарегистрирован, поведение зависит от типа процесса: обычный процесс завершается, но процесс PID 1 (в контейнере) **не получает** стандартного обработчика и может проигнорировать сигнал. Время между отправкой `SIGTERM` и `SIGKILL` составляет `terminationGracePeriodSeconds` минус время выполнения PreStop.

**`SIGKILL` (Signal Kill)** — принудительный сигнал завершения (номер 9), отправляемый ядром Linux процессам, если они не завершились по истечении `terminationGracePeriodSeconds`. Не может быть перехвачен или обработан процессом. Ядро немедленно освобождает все ресурсы процесса (память, файловые дескрипторы, TCP-сокеты). При `SIGKILL` открытые файлы могут остаться в несогласованном состоянии, если процесс находился в середине операции записи.

**Native Sidecar (K8s 1.29+, стабильно с v1.33)** — Sidecar-контейнеры, определенные в `initContainers` с полем `restartPolicy: Always`. Имеют специфический порядок завершения: сначала завершаются основные контейнеры (`containers[]`), и только после этого `kubelet` отправляет `SIGTERM` в Native Sidecar-контейнеры. Это гарантирует, что сайдкар (прокси, агент логирования) работает до тех пор, пока основное приложение не завершится. Отличие от обычного sidecar (контейнер в `containers[]`) — гарантированный порядок запуска и завершения.

**Финализатор (Finalizer)** — строка в `metadata.finalizers`, которая сообщает Kubernetes, что объект нельзя удалять из базы данных `etcd` до тех пор, пока не будут выполнены специфические условия. При удалении объекта API-сервер не удаляет его немедленно, а устанавливает `deletionTimestamp` и ждёт, пока контроллеры снимут свои финализаторы. Если финализатор не снят в течение `--leader-elect-lease-duration` (по умолчанию 15 секунд для большинства контроллеров), запрос на удаление блокируется. Снятие финализатора — это отдельная операция `PATCH`, выполняемая контроллером после завершения очистки.

**Терминальная фаза (Terminal Phase)** — состояние, при котором Pod достиг конечного статуса (`Succeeded` или `Failed`). Начиная с K8s 1.29, `kubelet` гарантированно переводит поды в терминальную фазу перед удалением, что важно для корректной работы Job и Sidecar-контейнеров. До этого изменения Pod мог быть удалён из API до подтверждения терминальной фазы, что приводило к гонке состояний (race condition).

**`Graceful Node Shutdown` (K8s 1.21+, стабильно с v1.24)** — механизм, позволяющий `kubelet` корректно завершать поды при выключении самого узла через взаимодействие с `systemd-logind`. `kubelet` регистрирует Shutdown Hook в `systemd-logind`, и при начале выключения ОС (через `systemctl poweroff`, IPMI и т.д.) получает уведомление с выделенным временем на завершение. По умолчанию `kubelet` завершает поды за 30 секунд до завершения ОС (настраивается через `--shutdown-grace-period` и `--shutdown-grace-period-critical-pods`).

**Принудительное удаление (Force Deletion)** — удаление объекта из API без ожидания подтверждения от `kubelet`. Выполняется командой `kubectl delete pod <name> --force --grace-period=0`. Рискованно при использовании StatefulSet, так как нарушает уникальность индекса (Split-brain) и может привести к одновременному доступу к томам с двух узлов. Используется только когда узел физически уничтожен или.Processes на нём гарантированно не работают.

**Поведение проб (Probes) в Terminating** — при получении `deletionTimestamp` поведение проб меняется:
- `readinessProbe`: Kubelet продолжает выполнять проверки, и если проба возвращает неуспех, под помечается как неготовый (`Ready=False`), что убирает его из Endpoints.
- `livenessProbe`: Kubelet продолжает выполнять проверки. Если проба неуспешна, контейнер будет перезапущен (если `restartPolicy: Always`), что может привести к бесконечному циклу перезапусков в состоянии `Terminating`. Рекомендация: отключить или упростить `livenessProbe` для критичных приложений или увеличить `failureThreshold`.

---

## Базовые концепции

### Процесс удаления Pod

Последовательность действий при штатном удалении:

```
Пользователь/Контроллер → kubectl delete pod
    ↓
API устанавливает metadata.deletionTimestamp
    ↓
API вычисляет deletionGracePeriodSeconds = terminationGracePeriodSeconds (или --grace-period)
    ↓
------------------------------------------------------------------------
| Параллельное выполнение (гонка состояний — Race Condition):          |
|                                                                      |
| Цепочка 1 (локальная, быстрая — миллисекунды):                      |
|   Kubelet видит deletionTimestamp                                     |
|     → Выполнение PreStop hook (если настроен)                        |
|     → Отправка SIGTERM PID 1 в каждом контейнере                     |
|                                                                      |
| Цепочка 2 (глобальная, медленная — от 100мс до 10с):                |
|   Контроллер эндпоинтов удаляет Pod из EndpointSlice                 |
|     → kube-proxy обновляет правила iptables/IPVS на КАЖДОЙ ноде      |
|     → Ingress-контроллер обновляет правила маршрутизации             |
|     → Service Mesh обновляет таблицы маршрутизации                   |
------------------------------------------------------------------------
    ↓
[Ожидание завершения основных контейнеров]
    ↓
Отправка SIGTERM в Native Sidecar контейнеры (K8s 1.29+)
    ↓
[Ожидание завершения или истечение deletionGracePeriodSeconds]
    ↓
Отправка SIGKILL (если процессы всё ещё активны)
    ↓
Размонтирование томов (Volumes) и очистка сетевых ресурсов
    ↓
Kubelet сообщает API о переводе в фазу Succeeded/Failed
    ↓
Снятие системных финализаторов (pod-protection)
    ↓
Удаление объекта из etcd
```

**Проблема задержки обновления (Propagation Delay):** Никакой синхронизации между цепочками нет. Если приложение при получении `SIGTERM` сразу закрывает слушающий сокет, трафик продолжает идти на него, пока сеть не обновится — приводит к ошибкам 502 Bad Gateway или Connection Refused.

> **Парадокс:** Приложение, которое «тупит» несколько секунд после `SIGTERM`, случайно оказывается в выигрыше — оно дорабатывает запросы, пока сеть обновляется. Аккуратное приложение, закрывающее сокет мгновенно, получает больше ошибок.

### Стандартные финализаторы (Finalizers)

| Финализатор | Назначение | Когда снимается |
| :--- | :--- | :--- |
| `kubernetes.io/pod-protection` | Гарантирует, что Pod не будет удалён из API до подтверждения от Kubelet о завершении контейнеров и размонтирования томов. | После подтверждения от Kubelet |
| `node.kubernetes.io/out-of-service` | (K8s 1.24+) Позволяет контроллерам принудительно снять финализаторы на выключенном узле после наложения taints. | После наложения taint и подтверждения CSI |
| `external-attacher/<csi-driver>` | Ожидает, пока CSI-контроллер подтвердит физическое отсоединение (detach) тома от узла (VolumeAttachment). | После `ControllerUnpublishVolume` |
| `kubernetes.io/pvc-protection` | Предотвращает удаление PVC, если он используется активным подом. | После удаления всех подов, ссылающихся на PVC |
| `kubernetes.io/pv-protection` | Предотвращает удаление PV, если он привязан к активному PVC. | После удаления связанного PVC |

Проверка финализаторов:

```bash
# Все финализаторы Pod
kubectl get pod <name> -o jsonpath='{.metadata.finalizers}'

# Финализаторы PVC
kubectl get pvc <name> -o jsonpath='{.metadata.finalizers}'

# Финализаторы PV
kubectl get pv <name> -o jsonpath='{.metadata.finalizers}'
```

### Основные причины зависания в состоянии Terminating

| Категория | Причина | Описание | Ключевые признаки |
| :--- | :--- | :--- | :--- |
| **Хранилище** | **Проблемы CSI/Томов** | Том не может быть отмонтирован из-за блокировки на уровне ОС или ошибки API. | `FailedUnmount` в Events, финализатор `external-attacher` |
| **Узел** | **Node NotReady/Lost** | Kubelet не выходит на связь. API-сервер ждет подтверждения, которое не может прийти. | `node.kubernetes.io/unreachable` taint, `Ready=Unknown` |
| **Приложение** | **Игнорирование SIGTERM** | Приложение (или PID 1) не обрабатывает сигнал. Часто из-за "shell form" в Dockerfile или отсутствия обработчика. | Exit code 137 (128+9), контейнер жив > `terminationGracePeriodSeconds` |
| **Процессы** | **Zombies / D-state** | Процессы в `Uninterruptible Sleep (D)` или зомби-процессы блокируют завершение контейнера/shim. | `ps aux | awk '$8=="D"'`, `lsof` показывает активные дескрипторы |
| **Политики** | **Блокировка через PDB** | PodDisruptionBudget запрещает удаление, если оно нарушает минимальный порог доступности (только для Eviction API). | `ALLOWED DISRUPTIONS: 0`, `kubectl drain` выдаёт `429` |
| **Финализаторы** | **Зависший финализатор** | Контроллер не может снять финализатор (баг, ошибка API, отсутствие компонента). | Финализатор не исчезает > 5 минут после `deletionTimestamp` |
| **PreStop** | **Хук выполняется дольше лимита** | PreStop hook не завершается в пределах `terminationGracePeriodSeconds`. | Событие `FailedPreStopHook`, `SIGKILL` до отправки `SIGTERM` |

### Взаимодействие с EndpointSlice и сетевая задержка

Когда Pod получает `deletionTimestamp`, контроллер эндпоинтов удаляет его из `EndpointSlice`. Это изменение должно распространиться на все узлы кластера:

1. **Kube-proxy** (на каждой ноде) обновляет правила `iptables` или `ipvs` — задержка от 100мс до 5с в зависимости от размера кластера.
2. **Ingress-контроллер** обновляет кэш эндпоинтов — задержка зависит от реализации (NGINX Ingress: ~1с, Envoy: ~500мс).
3. **Service Mesh** (Istio, Linkerd) — обновляет таблицы маршрутизации через xDS API.
4. **DNS-кэш** в клиентах — TTL может составлять от секунд до минут.

**Рекомендация:** Всегда используйте `preStop sleep` для компенсации задержки распространения эндпоинтов. См. [Graceful Shutdown](./graceful_shutdown.md).

### Поведение Readiness Probe в Terminating

При завершении Pod:

1. Kubelet продолжает выполнять `readinessProbe`.
2. Если приложение корректно обрабатывает `SIGTERM` и начинает отдавать ошибки в `readinessProbe`, Pod быстро помечается как неготовый и удаляется из Endpoints.
3. Если `readinessProbe` продолжает возвращать `200 OK` после `SIGTERM`, Pod остаётся в Endpoints до истечения `terminationGracePeriodSeconds` — трафик идёт на умирающий под.

**Важно:** `readinessProbe` во время `Terminating` не влияет на завершение контейнера — она влияет только на попадание в Endpoints.

### Взаимодействие с Liveness Probe в Terminating

1. Kubelet продолжает выполнять `livenessProbe` до полного завершения Pod.
2. Если проба возвращает неуспех и `restartPolicy: Always`, контейнер будет перезапущен.
3. Перезапуск в Terminating создаёт гонку: контейнер перезапускается, снова получает `SIGTERM`, и так далее, пока `terminationGracePeriodSeconds` не истечёт.

**Рекомендация:** Для критичных приложений рассмотрите увеличение `failureThreshold` для `livenessProbe` или отключение проб во время завершения через обработчик в приложении.

---

## Практические сценарии

### Быстрая диагностика зависшего пода

```bash
# 1. Проверка наличия deletionTimestamp и фазы
kubectl get pod <pod-name> -o jsonpath='{.metadata.deletionTimestamp} {.status.phase}'
# → Пример вывода:
#   2026-09-03T10:15:30Z Running

# 2. Поиск зависших финализаторов (CSI или защита пода)
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'
# → Пример вывода:
#   [kubernetes.io/pod-protection]

# 3. Анализ событий (Events) для выявления ошибок CSI (Attach/Detach)
kubectl describe pod <pod-name> | grep -A 15 Events:
# → Ищите строки:
#   FailedScheduling, FailedAttachVolume, FailedMount,
#   Unhealthy (для проб), FailedPreStopHook

# 4. Проверка состояния узла, на котором запущен Pod
kubectl get node $(kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}') \
  -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,HEALTH:.status.conditions[-1].status
# → Пример вывода:
#   node-1   Ready   True

# 5. Проверка наличия процессов в D-state на узле
# (выполнять через SSH на узел)
ssh <node> 'ps -aux | awk '"'"'$8=="D" {print $0}'"'"'

# 6. Проверка продолжительности зависания
kubectl get pod <pod-name> -o jsonpath='{.metadata.creationTimestamp} → {.metadata.deletionTimestamp}'
# → Пример вывода:
#   2026-09-03T10:00:00Z → 2026-09-03T10:15:00Z
#   Прошло: 15 минут с момента запроса на удаление
```

### Ожидание завершения удаления Pod

```bash
# Ожидание удаления конкретного Pod (таймаут 120 секунд)
kubectl wait --for=delete pod/<pod-name> --timeout=120s

# Ожидание перехода Pod в терминальную фазу
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/<job-pod-name> --timeout=300s
```

### Просмотр событий завершения Pod

```bash
# События конкретного Pod с фильтрацией по типу
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'

# Пример вывода:
#   TYPE    REASON      AGE   MESSAGE
#   Normal  Killing     30s   Stopping container app
#   Normal  PreStopHook 29s   Executing pre-stop hook
#   Normal  Pulled      10s   Container image already present on machine
#   Warning Unhealthy   5s    Readiness probe failed: HTTP probe failed
```

### Принудительное завершение на выключенном узле (Non-graceful Shutdown)

Если узел окончательно вышел из строя (K8s 1.24+), используйте механизм `out-of-service`:

1.  **Пометить узел как окончательно недоступный:**
    ```bash
    kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=NoExecute:NoExecute
    ```
2.  **Результат:** Системные контроллеры автоматически снимут финализаторы, позволяя подам (в т.ч. StatefulSet) переехать на другие узлы.
3.  **Дождитесь пересоздания подов:**
    ```bash
    kubectl get pods -o wide | grep <node-name>
    # → Все поды должны исчезнуть или перейти на другие ноды
    ```
4.  **Удалите taint перед возвращением узла в строй:**
    ```bash
    kubectl taint nodes <node-name> node.kubernetes.io/out-of-service-
    ```

### Ручное снятие финализаторов (крайняя мера)

```bash
# Снятие финализаторов с Pod (опасно — может привести к Split-brain для StatefulSet)
kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":null}}' --type=merge

# Снятие финализатора с конкретного PVC
kubectl patch pvc <pvc-name> -p '{"metadata":{"finalizers":["kubernetes.io/pvc-protection"]}}' --type=merge

# Проверка结果 (ожидание исчезновения финализатора)
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}' | grep -c "finalizer"
# → 0 (финализатор снят)
```

**ВНИМАНИЕ:** Перед снятием финализаторов убедитесь:
1. Процессы на исходном узле гарантированно не работают.
2. Тома физически отмонтированы (проверьте `VolumeAttachment`).
3. Нет риска одновременного доступа к томам с двух узлов (Split-brain).

### Шаблоны конфигурации завершения для различных типов приложений

#### Stateless HTTP-сервис (стандартный паттерн)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 3
  strategy:
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0  # Zero-downtime
  template:
    spec:
      terminationGracePeriodSeconds: 45  # preStop(10) + дренаж(25) + запас(10)
      containers:
      - name: app
        image: nginx:1.25
        lifecycle:
          preStop:
            sleep:
              seconds: 10  # Компенсация задержки обновления Endpoints
        readinessProbe:
          httpGet:
            path: /readyz
            port: 8080
          periodSeconds: 5
          failureThreshold: 3
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          periodSeconds: 10
          failureThreshold: 3
```

#### Тяжёлое приложение (Java/БД-клиент)

```yaml
terminationGracePeriodSeconds: 120  # Длинный дренаж для Java GC и закрытия пулов
containers:
- name: app
  lifecycle:
    preStop:
      httpGet:
        path: /shutdown  # Эндпоинт для инициации дренажа
        port: 8080
```

#### Приложение с длинными TCP-соединениями (gRPC, WebSocket)

```yaml
terminationGracePeriodSeconds: 90
containers:
- name: app
  lifecycle:
    preStop:
      sleep:
        seconds: 15  # Дать прокси время обновить маршрутизацию
  readinessProbe:
    exec:
      command: ["/bin/sh", "-c", "curl -sf http://localhost:8080/ready || exit 1"]
    periodSeconds: 5
```

#### Native Sidecar с прокси (Istio/Envoy)

```yaml
initContainers:
- name: istio-proxy
  image: istio/proxyv2:1.20
  restartPolicy: Always  # Native Sidecar (K8s 1.29+)
  lifecycle:
    preStop:
      exec:
        command: ["/bin/sh", "-c", "sleep 5"]  # Дождаться дренажа основного контейнера
containers:
- name: app
  lifecycle:
    preStop:
      sleep:
        seconds: 10
```

---

## Дополнительная информация

### Сборщик мусора подов (Pod Garbage Collector)

**Pod Garbage Collector (Pod GC)** — контроллер в `kube-controller-manager`, который очищает завершённые объекты.

**Типы очистки:**
1.  **По количеству:** Удаляет старые завершённые поды (фазы `Succeeded`/`Failed`), если их число превышает `--terminated-pod-gc-threshold` (по умолчанию 12500).
2.  **Бесхозные поды:** Удаляет поды, привязанные к удалённым узлам.
3.  **Зависшие поды:** Пытается очистить поды в состоянии `Terminating`, если узел был удалён из API.

**Важно:** Если Pod завис в `Terminating` из-за финализатора (например, CSI), Pod GC **не удалит** его принудительно, так как это нарушило бы гарантии безопасности (риск коррупции данных).

### Проблема PID 1 и проброса сигналов

Если приложение запускается через shell-оболочку (`CMD my-app.sh` или `ENTRYPOINT /start.sh` без `exec`), оболочка становится PID 1 и получает `SIGTERM`. Большинство оболочек **не пробрасывают** сигналы к дочерним процессам. Результат: приложение не завершается и убивается по `SIGKILL` через `terminationGracePeriodSeconds`.

**Решения:**
1. Используйте "exec form" в Dockerfile: `ENTRYPOINT ["/app/binary"]` или `CMD ["/app/start.py"]`.
2. Используйте `exec` в shell-скриптах: `exec python app.py` (вместо `python app.py`).
3. Используйте легковесные init-системы: `tini` (~20KB) или `dumb-init`.

```dockerfile
# tini: автоматически пробрасывает сигналы и собирает зомби
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/app/start.sh"]

# Python: exec заменяет shell на процесс приложения
CMD ["python", "-c", "exec(open('app.py').read())"]
```

### Edge Case: DaemonSet при обслуживании узла

Pod'ы DaemonSet **не могут** использовать Pod Disruption Budget (PDB не действует на DaemonSet). При `kubectl drain` с `--ignore-daemonsets=false` поды DaemonSet удаляются принудительно, если узел помечен для обслуживания. Если DaemonSet настроен с `terminationGracePeriodSeconds: 0`, контейнеры будут убиты мгновенно без возможности завершения текущих операций.

### Edge Case: Pod в Namespace с активным ResourceQuota

Если Namespace имеет `ResourceQuota`, ограничивающий количество подов, Pod в `Terminating` **всё ещё считается** в квоте. Это может блокировать создание новых подов в этом Namespace. Проверка:

```bash
kubectl get resourcequota -n <namespace> -o jsonpath='{.items[*].status}'
# → Ищите поле "hard" vs "used" для pods
```

### Связанные команды kubectl

| Команда | Назначение |
| :--- | :--- |
| `kubectl delete pod <name> --grace-period=<N>` | Удаление с указанием периода ожидания (0 = немедленный SIGKILL) |
| `kubectl delete pod <name> --force --grace-period=0` | Принудительное удаление без ожидания |
| `kubectl patch pod <name> -p '{"metadata":{"finalizers":null}}'` | Ручное снятие финализаторов |
| `kubectl wait --for=delete pod/<name> --timeout=<N>s` | Ожидание удаления Pod |
| `kubectl get events --field-selector involvedObject.name=<name>` | События завершения |

**См. также:**
- [Жизненный цикл Pod](../../../Base/Pod/pod_lifecycle_and_state.md) — фазы и условия.
- [Graceful Shutdown](./graceful_shutdown.md) — детали настройки прерываний и хуков.
- [Финализаторы и CSI](./finalizer_issues.md) — глубокий разбор проблем с дисками.
- [Диагностика зависиманий](./diagnostics.md) — пошаговый алгоритм решения.
