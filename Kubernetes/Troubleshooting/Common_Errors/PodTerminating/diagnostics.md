# Pod Terminating — диагностика и алгоритмы поиска неисправностей

## Определения

**Диагностический алгоритм Pod Terminating** — структурированная последовательность проверок для выявления причины, по которой объект Pod не удаляется из API-сервера. Основные направления поиска: подсистема хранения (CSI/Volumes), механизмы защиты (Finalizers), состояние инфраструктуры (Nodes), политики доступности (PDB) и жизненный цикл контейнеров (Runtime).

**UID (Unique Identifier)** — уникальный идентификатор Pod в кластере. Используется для сопоставления объекта API с физическими директориями на узле (`/var/lib/kubelet/pods/<UID>`), поиском контейнеров в CRI (`crictl ps --pod <UID>`) и анализом зависших точек монтирования.

**Зависший финализатор (Stuck Finalizer)** — состояние, при котором контроллер, ответственный за снятие финализатора, не может выполнить задачу (из-за ошибки API, отсутствия связи или бага в логике), что блокирует удаление записи из `etcd`.

**Grace Period (Период ожидания)** — время, прошедшее с момента установки `deletionTimestamp`. Если этот интервал значительно превышает `terminationGracePeriodSeconds`, диагностика переходит от анализа жизненного цикла приложения к анализу системных компонентов кластера и CRI.

**Uninterruptible Sleep (D-state)** — состояние процесса, ожидающего завершения ввода-вывода (I/O). Такие процессы игнорируют сигналы `SIGTERM` и `SIGKILL`, блокируя завершение контейнера и размонтирование томов.

**OOMKilled (Out of Memory Killed)** — причина завершения контейнера (`lastState.terminated.reason`), указывающая, что процесс превысил лимит памяти (`resources.limits.memory`) и был убит OOM Killer ядра Linux. Отличается от `SIGKILL`-а по `terminationGracePeriodSeconds` тем, что происходит мгновенно, без предварительного сигнала.

**Провал пробы (Probe Failure)** — состояние, когда `readinessProbe` или `livenessProbe` возвращает неуспех более `failureThreshold` раз подряд. Провал `readinessProbe` убирает Pod из Endpoints. Провал `livenessProbe` вызывает перезапуск контейнера (при `restartPolicy: Always`), что в состоянии `Terminating` приводит к бесконечному циклу.

**Taint Effect `NoExecute`** — эффект taint, автоматически вытесняющий поды, не имеющие соответствующего `toleration`. Применяется контроллером узла при обнаружении проблем (NotReady, Unreachable, OutOfService). Длительность вытеснения зависит от `tolerationSeconds` (по умолчанию 300 секунд).

**Socket Exhaustion (Исход сокетов)** — исчерпание файловых дескрипторов или системных лимитов на сокеты (net.ipv4.ip_local_port_range, ulimit -n). Приводит к отказу в обработке новых соединений и зависанию процессов в `D-state` при попытке I/O.

**Node Condition** — поле `status.conditions[]` в объекте Node, описывающее текущее состояние узла. Ключевые условия для диагностики: `Ready`, `MemoryPressure`, `DiskPressure`, `PIDPressure`, `NetworkUnavailable`.

---

## Базовые концепции

### Дерево решений для быстрой диагностики

```
Pod в Terminating
│
├─ deletionTimestamp > terminationGracePeriodSeconds + запас?
│  └─ Да → Kubelet не может подтвердить. Проверьте:
│     ├─ Узел доступен? → Этап 5 (Node level)
│     ├─ Финализаторы? → Этап 1 (API/Финализаторы)
│     └─ CSI/Volumes? → Этап 3 (Storage)
│
├─ deletionTimestamp < terminationGracePeriodSeconds?
│  └─ Под ещё в процессе нормального завершения.
│     Проверьте preStop и логи контейнеров → Этап 2 (Runtime)
│
├─ Events содержат FailedMount/FailedUnmount?
│  └─ Проблема хранения → Этап 3 (Storage) или
│     [Volume Unmount Issues](./volume_unmount_issues.md)
│
├─ Events содержат FailedPreStopHook?
│  └─ preStop не завершается. Увеличьте terminationGracePeriodSeconds
│
├─ Events содержат Unhealthy + контейнер перезапускается?
│  └─ livenessProbe неуспех в Terminating → Этап 2 (Runtime)
│
└─ Events содержат BackOff / Evicted?
   └─ Проверьте PDB и Eviction → Этап 4 (PDB/Eviction)
```

### Логическая схема диагностики

Анализ строится по принципу «от внешнего к внутреннему»:

1.  **API-уровень**: Анализ метаданных (`finalizers`, `deletionTimestamp`) и системных событий (`Events`).
2.  **Уровень политик (PDB)**: Проверка, не блокирует ли `PodDisruptionBudget` удаление (только для Eviction API / `kubectl drain`).
3.  **Уровень управления (Control Plane)**: Проверка внешних контроллеров (CSI, Job), удерживающих объект.
4.  **Уровень узла (Node Level)**: Проверка связи `kubelet` с API, состояния CRI и физических томов.
5.  **Уровень среды выполнения (Runtime)**: Анализ процессов (PID 1, зомби, D-state, порядок завершения Sidecars).

### Диагностическая матрица инструментов

| Инструмент | Сфера применения | Искомые данные | Когда использовать |
| :--- | :--- | :--- | :--- |
| `kubectl describe pod` | Общий аудит | Ошибки монтирования, таймауты узла, события жизненного цикла. | **Первым делом** всегда. |
| `kubectl get pod -o json` | Полная спецификация | Точные значения `finalizers`, `deletionTimestamp`, `terminationGracePeriodSeconds`. | После описания — для уточнения. |
| `kubectl get events` | Хронология ошибок | Последние события по Pod/Namespace/узлу. | Для поиска паттернов и частоты ошибок. |
| `kubectl get pdb` | Анализ доступности | Проверка `ALLOWED DISRUPTIONS`. Если 0 — удаление может быть заблокировано. | При `kubectl drain` или Eviction. |
| `kubectl top pod` | Потребление ресурсов | Текущее CPU/Memory. Помогает выявить OOMKilled до завершения. | Для проверки исчерпания ресурсов. |
| `crictl ps -a --pod <UID>` | CRI (на узле) | Статус контейнеров внутри пода на уровне runtime. | Если `kubectl logs` недоступен. |
| `crictl inspect <container>` | CRI (на узле) | Exit code, PID, состояние контейнера на уровне рантайма. | Для точного определения причины завершения. |
| `journalctl -u kubelet` | Анализ Kubelet | Ошибки `UnmountVolume`, тайм-ауты обращения к CRI, `Orphaned pod found`. | При проблемах с томами. |
| `lsof +D <path>` | Файловая система | Процессы, блокирующие освобождение дескрипторов томов. | При `target is busy` при unmount. |
| `findmnt` | Точки монтирования | Активные bind-mounts, subpaths, застрявшие монтирования. | При скрытых блокировках томов. |
| `nsenter -t <PID> -m` | Mount Namespace | Глубокая проверка точек монтирования внутри namespace процесса. | При блокировке в namespace Kubelet. |
| `strace -p <PID> -e signal` | Системные вызовы | Получает ли процесс сигналы `SIGTERM`. | Для диагностики PID 1 и обработчиков сигналов. |

### Фильтрация и анализ событий (Events)

События — основной источник информации. Правильная фильтрация экономит время:

```bash
# События конкретного Pod (хронология)
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'

# Только ошибки (Warning) по всему Namespace
kubectl get events -n <namespace> --field-selector type=Warning --sort-by='.lastTimestamp'

# Ошибки планировщика (Pod не может быть запущен)
kubectl get events -n <namespace> --field-selector reason=FailedScheduling

# Ошибки CSI (Volume)
kubectl get events -n <namespace> --field-selector reason=FailedMount

# Ошибки PDB (Eviction)
kubectl get events -n <namespace> --field-selector reason=Eviction

# Ошибки OOM (Kill из-за памяти)
kubectl get events -n <namespace> --field-selector reason=OOMKilling

# Форматированный вывод для отчёта
kubectl get events -n <namespace> --sort-by='.lastTimestamp' \
  -o custom-columns="TIME:.lastTimestamp,TYPE:.type,REASON:.reason,OBJ:.involvedObject.name,MSG:.message"

# Мониторинг в реальном времени (watch)
kubectl get events -n <namespace> -w --sort-by='.lastTimestamp'
```

### Анализ Conditions узла

Если Pod "завис" из-за проблем с узлом, проверьте его состояние:

```bash
# Краткий статус всех узлов
kubectl get nodes -o custom-columns=NAME:.metadata.name,READY:.status.conditions[-1].type,STATUS:.status.conditions[-1].status,HEALTH:.status.conditions[-2].type

# Детальный аудит конкретного узла
kubectl describe node <node-name> | grep -A 20 "Conditions:"

# Проверка taints
kubectl get node <node-name> -o jsonpath='{.spec.taints[*].key} {.spec.taints[*].effect}'
```

**Ключевые условия для диагностики Terminating:**

| Condition | Значение True | Влияние на Pod |
| :--- | :--- | :--- |
| `Ready` | False / Unknown | Kubelet не отвечает. Pod'ы на узле зависают в Terminating. |
| `MemoryPressure` | True | Kubelet запрещает создание новых подов. Существующие могут быть вытеснены (Eviction). |
| `DiskPressure` | True | Аналогично MemoryPressure. Kubelet начинает удаление завершённых подов и образов. |
| `PIDPressure` | True | Исчерпание PID на узле. Новые контейнеры не запускаются. |
| `NetworkUnavailable` | True | CNI-плагин не работает. Pod'ы не получают IP-адреса. |

---

## Практические сценарии

### Быстрый чек-лист диагностики (start here)

```bash
# 1. Время зависания и финализаторы
kubectl get pod <pod-name> -o jsonpath='DeletionTimestamp: {.metadata.deletionTimestamp}{"\n"}Finalizers: {.metadata.finalizers}{"\n"}GracePeriod: {.metadata.deletionGracePeriodSeconds}s'

# 2. Events (быстрый поиск причин)
kubectl describe pod <pod-name> | grep -A 20 Events

# 3. Состояние контейнеров (кто жив, кто умер)
kubectl get pod <pod-name> -o jsonpath='{range .status.containerStatuses[*]}{.name}: {.state}{"\n"}{end}'

# 4. PDB (если drain зависает)
kubectl get pdb -A | grep -v "ALLOWED DISRUPTIONS: 0"

# 5. Состояние узла
kubectl get node $(kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}') -o wide
```

### Этап 1: Первичный сбор и анализ метаданных

```bash
# 1. Проверка времени зависания и финализаторов
kubectl get pod <pod-name> -o jsonpath='{.metadata.deletionTimestamp} {"\n"} {.metadata.finalizers}'
# Пример вывода:
#   2026-09-03T10:15:30Z
#   [kubernetes.io/pod-protection]

# 2. Проверка deletionGracePeriodSeconds vs факт зависания
kubectl get pod <pod-name> -o jsonpath='deletionGracePeriodSeconds: {.metadata.deletionGracePeriodSeconds}s'
# Пример вывода:
#   deletionGracePeriodSeconds: 30s
# Если прошло >30с — Kubelet не может подтвердить завершение.

# 3. Проверка PDB (если удаление инициировано через Drain или Eviction)
kubectl get pdb -A
# Пример вывода:
#   NAME      MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
#   web-pdb   2               <none>            0                     5d
# ALLOWED DISRUPTIONS: 0 → выселение заблокировано. См. [PDB Blocking](./pdb_blocking.md).

# 4. Анализ событий (включая ошибки планировщика и CSI)
kubectl describe pod <pod-name> | grep -A 20 Events
# Пример вывода:
#   Events:
#     Type    Reason     Age   From               Message
#     ----    ------     ----  ----               -------
#     Normal  Killing    30s   kubelet            Stopping container app
#     Normal  PreStop    29s   kubelet            Executing pre stop hook
#     Warning Unhealthy  5s    kubelet            Readiness probe failed: HTTP probe failed
```

**Интерпретация:**
- `finalizers: [kubernetes.io/pvc-protection]` → Проверьте, не используется ли связанный PVC другими подами.
- `Events: FailedUnmount` → **Перейти к Этапу 3 (Storage)** или см. [Volume Unmount Issues](./volume_unmount_issues.md).
- `Events: Denied by PDB` или `Eviction blocked` → См. [PDB Blocking](./pdb_blocking.md).
- `Events: FailedPreStopHook` → preStop не завершается. Увеличьте `terminationGracePeriodSeconds`.

### Этап 2: Диагностика Runtime (контейнеры и процессы)

#### 2.1 Статус контейнеров

```bash
# Проверка статуса каждого контейнера
kubectl get pod <pod-name> -o jsonpath='{range .status.containerStatuses[*]}{
  Имя: {.name}{"\n"}
  Состояние: {.state}{"\n"}
  Последнее: {.lastState}{"\n"}
  Restart Count: {.restartCount}{"\n"}
  Ready: {.ready}{"\n"}
}---{"\n"}{end}'
```

**Интерпретация:**
- `state.terminated.reason: OOMKilled` → Контейнер исчерпал память. Увеличьте `resources.limits.memory`.
- `state.terminated.reason: Error` → Контейнер завершился с кодом != 0. Проверьте логи: `kubectl logs <pod-name> --previous`.
- `state.terminated.reason: Terminated` без OOM → Приложение не успело завершиться за `terminationGracePeriodSeconds`.
- Основные контейнеры `Terminated`, но сайдкар `Running` → Проблема завершения Native Sidecar (K8s 1.29+).

#### 2.2 Native Sidecars (K8s 1.29+)

Если под завис, проверьте статус контейнеров. В модели Native Sidecar основные контейнеры должны завершиться **до** сайдкаров:

```bash
# Проверка, завершились ли основные контейнеры до сайдкаров
kubectl get pod <pod-name> -o jsonpath='{
  Основные: {.status.containerStatuses[?(@.name!="istio-proxy")].state.terminated.reason}
  Сайдкар:  {.status.initContainerStatuses[?(@.name=="istio-proxy")].state}
}'

# Проверка, получил ли сайдкар SIGTERM
kubectl get pod <pod-name> -o jsonpath='{
  Сайдкар terminated: {.status.initContainerStatuses[?(@.name=="istio-proxy")].state.terminated}
}'
```

Если основное приложение завершилось (состояние `Terminated`), но сайдкар (например, `istio-proxy`) всё ещё в `Running`, это может указывать на:
- Баг в логике завершения сайдкара.
- Сайдкар не получил `SIGTERM` (проблема с PID 1).
- Сайдкар выполняет длительную операцию (drain соединений).

#### 2.3 Анализ процессов на узле (PBS и D-state)

```bash
# Поиск процессов Pod на хосте (выполнять через SSH на узел)
POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')
ssh <node> "ls /proc/*/ns/pid 2>/dev/null | while read ns; do
  pid=\$(echo \$ns | cut -d/ -f3)
  if readlink /proc/\$pid/ns/pid 2>/dev/null | grep -q \$POD_UID; then
    echo \"PID: \$pid CMD: \$(cat /proc/\$pid/cmdline | tr '\0' ' ')\"
  fi
done"

# Поиск процессов в D-state (Uninterruptible Sleep)
ssh <node> 'ps -eo pid,stat,wchan,args | awk '"'"'$2 ~ /D/ {print $0}'"'"''
# Пример вывода:
#   PID  STAT WCHAN          COMMAND
#   1234 D    nfs_file_read  [nfs]

# Поиск зомби-процессов
ssh <node> 'ps -eo pid,stat,args | awk '"'"'$2 ~ /Z/ {print $0}'"'"''
# Пример вывода:
#   PID  STAT COMMAND
#   5678 Z    [defunct]
```

**Важно:** Процессы в `D-state` невозможно убить `SIGKILL`. Если такой процесс удерживает том, `umount` будет зависать до завершения I/O (или до перезагрузки узла).

#### 2.4 Анализ PID 1 и сигналов

Если подозреваете, что приложение не получает `SIGTERM`:

```bash
# Найти PID контейнера (выполнять на узле через CRI)
CONTAINER_ID=$(ssh <node> "crictl ps --name <container-name> -q")
PID=$(ssh <node> "crictl inspect $CONTAINER_ID | jq -r '.info.pid'")

# Проверить дерево процессов
ssh <node> "ps -fH -p $PID"
# Пример вывода:
#   UID  PID PPID C STIME TTY TIME CMD
#   root 123  100 0 10:00 ?   00:00:00 /bin/sh -c /app/start.sh
#   root 456  123 0 10:00 ?   00:00:05 python app.py
# Проблема: shell (PID 123) является PID 1, а не приложение (PID 456).

# Проверить, получает ли процесс сигналы
ssh <node> "strace -p $PID -e signal -f 2>&1 | head -5"
# Если нет вывода при отправке kubectl delete — сигнал не доставляется.
```

### Этап 3: Диагностика подсистемы хранения (CSI/Volumes)

Если Pod не удаляется из-за ошибок размонтирования:

```bash
# 1. Получение UID и NodeName
kubectl get pod <pod-name> -o jsonpath='UID: {.metadata.uid}{"\n"}Node: {.spec.nodeName}'

# 2. На узле: Поиск процессов, удерживающих тома (включая скрытые монтирования)
POD_UID="<UID>"
ssh <node> "lsof +D /var/lib/kubelet/pods/$POD_UID/volumes 2>/dev/null"
# Пример вывода:
#   COMMAND   PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
#   python  1234 root  5r REG  253,1  1048576  123 /var/lib/kubelet/pods/.../volumes/kubernetes.io~csi/pvc-xxx/mount/data.db

# 3. Проверка mountinfo для поиска "застрявших" bind-mounts
ssh <node> "grep $POD_UID /proc/self/mountinfo | head -20"
# Пример вывода:
#   123 89 253:1 /var/lib/kubelet/pods/.../volumes/kubernetes.io~csi/pvc-xxx/mount /mount rw,relatime shared:45 - ext4 /dev/vda1 rw

# 4. Поиск подпутей (volume-subpaths)
ssh <node> "findmnt | grep $POD_UID | grep volume-subpaths"

# 5. Проверка VolumeAttachment
kubectl get volumeattachment | grep $(kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}')
# Если объект есть с финализатором external-attacher — том не отсоединен в CSI.
```

**Детальный разбор проблем с томами:** См. [Volume Unmount Issues](./volume_unmount_issues.md).

### Этап 4: Диагностика PDB и Eviction

Если `kubectl drain` зависает или выдаёт ошибку `Cannot evict pod`:

```bash
# Проверка всех PDB и ALLOWED DISRUPTIONS
kubectl get pdb -A -o wide
# Пример вывода:
#   NAME      MIN AVAILABLE   MAX UNALLOWED   ALLOWED DISRUPTIONS   SELECTOR
#   web-pdb   2               <none>          0                     app=web
# ALLOWED DISRUPTIONS: 0 → выселение заблокировано.

# Детальный аудит конкретного PDB
kubectl describe pdb <pdb-name>
# Пример вывода:
#   Spec:
#     Min Available:  2
#     Selector:       app=web
#   Status:
#     Current Healthy:  2
#     Desired Healthy:  2
#     Disruptions Allowed: 0
#     Disruption Target:  [pod/web-abc12]  ← Этот под уже "забронирован" для выселения

# Поиск "зависших" выселений (K8s 1.29+)
kubectl get pdb <pdb-name> -o jsonpath='{.status.disruptionTarget}'
# Если есть имена подов — они блокируют очередь.

# Проверка, есть ли Eviction API ошибки в событиях
kubectl get events -A --field-selector reason=Eviction
```

**Детальный разбор PDB:** См. [PDB Blocking](./pdb_blocking.md).

**Разрешение:**
1. **Увеличьте количество реплик** (`kubectl scale deployment <name> --replicas=N+1`) — самый безопасный путь.
2. **Скорректируйте PDB** (`kubectl patch pdb <name> -p '{"spec":{"maxUnavailable":1}}'`) — если реплик достаточно.
3. **Временно обходите** (`kubectl delete pod <name> --grace-period=30`) — если обслуживание критично и готовность не критична.

### Этап 5: Диагностика Graceful Node Shutdown

Если поды зависают при выключении узла:

```bash
# Проверка событий выключения через kubelet
ssh <node> 'journalctl -u kubelet --grep "Shutdown manager" --no-pager -n 30'
# Пример вывода:
#   Sep 03 10:15:01 node-1 kubelet[1234]: I1003 10:15:01.123456 123456 shutdown_manager.go:150]
#   Pod "default/web-0" (abc123) у uid "abc123", timeout 30s
#   Started graceful shutdown for pod "default/web-0"

# Проверка, получил ли kubelet сигнал от logind
ssh <node> 'journalctl -t systemd-logind --no-pager -n 10'
# Ищите: "System is powering down" или "Creating shutdown job"

# Проверка времени завершения (.shutdownGracePeriod)
ssh <node> 'cat /var/lib/kubelet/config.yaml | grep -A 2 shutdownGracePeriod'
# shutdownGracePeriod: 30s
# shutdownGracePeriodCriticalPods: 10s

# Проверка тайм-аута выселения в контроллере (по умолчанию 5 минут)
# Если узел NotReady > 5 минут, поды начнут вытесняться через taint-based eviction.
```

**Сценарий: узел выключается, поды зависают в Terminating**

Причины:
1. Kubelet не получил сигнал от `systemd-logind` (нет записи в `journalctl`).
2. Приложение игнорирует `SIGTERM` (проверьте PID 1 через Этап 2.4).
3. PreStop hook выполняется дольше `terminationGracePeriodSeconds`.
4. Kubelet не может завершить I/O на томах (NFS, iSCSI — см. Этап 3).

**Действие:** Дождаться `pod-eviction-timeout` (5 минут), затем поды будут вытеснены через taint-based eviction.

### Этап 6: Диагностика Liveness Probe → Restart Loop в Terminating

Если контейнер перезапускается в состоянии Terminating:

```bash
# Проверка количества перезапусков
kubectl get pod <pod-name> -o jsonpath='{
  restartCount: {.status.containerStatuses[0].restartCount}
}'
# restartCount: 15 → контейнер постоянно перезапускается.

# Проверка причины последнего завершения
kubectl get pod <pod-name> -o jsonpath='{
  lastReason: {.status.containerStatuses[0].lastState.terminated.reason}
  lastCode:   {.status.containerStatuses[0].lastState.terminated.exitCode}
  lastMessage:{.status.containerStatuses[0].lastState.terminated.message}
}'
# Пример вывода:
#   lastReason: Error
#   lastCode:   1
#   lastMessage: healthcheck probe failed

# Проверка livenessProbe конфигурации
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[0].livenessProbe}'
# Пример вывода:
#   {"exec":{"command":["curl","-f","http://localhost:8080/healthz"]},
#    "initialDelaySeconds":10,"periodSeconds":5,"failureThreshold":3}
# failureThreshold: 3, periodSeconds: 5 → после 15с неуспеха контейнер убивается.
```

**Решение:**
1. Увеличьте `failureThreshold` для `livenessProbe` (например, до 10).
2. Увеличьте `terminationGracePeriodSeconds`, чтобы дать приложению время на дренаж.
3. Или реализуйте в приложении возврат ошибки в `livenessProbe` после получения `SIGTERM`, чтобы Pod быстро удалился из Endpoints.

### Этап 7: Диагностика Resource Pressure на узле

Если Pod не может быть запущен или вытесняется:

```bash
# Проверка Resource Pressure на узле
kubectl describe node <node-name> | grep -A 5 "Conditions:"
# Пример вывода:
#   Conditions:
#     Type             Status  LastHeartbeatTime                 LastTransitionTime
#     MemoryPressure   False   Tue, 03 Sep 2026 10:00:00 +0000   Tue, 03 Sep 2026 08:00:00 +0000
#     DiskPressure     True    Tue, 03 Sep 2026 10:00:00 +0000   Tue, 03 Sep 2026 09:30:00 +0000
# DiskPressure: True → узел исчерпал место на диске.

# Проверка потребления ресурсов Pod'ом
kubectl top pod <pod-name> --containers
# Пример вывода:
#   NAME   CPU(cores)   MEMORY(bytes)
#   app    250m         489Mi
#   app    (limits: 500m / 512Mi)
# Если потребление приближается к limits → возможен OOMKilled.

# Проверка исчерпания PID на узле
ssh <node> 'cat /proc/sys/kernel/pid_max'
ssh <node> 'ps -e --no-headers | wc -l'
# Если количество процессов приближается к pid_max → PIDPressure.
```

---

## Дополнительная информация

### Коды завершения (Exit Codes) при остановке

Анализ `status.containerStatuses[*].lastState.terminated.exitCode` помогает понять, как завершился процесс:

| Exit Code | Значение | Типичная причина |
| :--- | :--- | :--- |
| **0** | Успешное завершение | Приложение завершилось штатно. |
| **1** | Общая ошибка | Ошибка в приложении. Проверьте логи. |
| **130** | SIGINT (128+2) | Получен `Ctrl+C` или `kill -INT`. |
| **137** | SIGKILL (128+9) | Убит по `SIGKILL`. Причины: (1) `OOMKilled` — нехватка памяти; (2) не завершился за `terminationGracePeriodSeconds`. |
| **143** | SIGTERM (128+15) | Корректное завершение по `SIGTERM`. Это **нормальное** поведение. |
| **1** + `reason: Error` | Ошибка приложения | Приложение завершилось с ошибкой до обработки SIGTERM. |

### Соответствие Events → Корневая причина

| Событие (Reason) | Вероятная причина | Следующий шаг |
| :--- | :--- | :--- |
| `FailedMount` | Ошибка монтирования тома (NFS недоступен, PVC не найден). | Этап 3 (Storage) или [Volume Unmount Issues](./volume_unmount_issues.md). |
| `FailedUnmount` | Том не размонтируется (процесс удерживает fd, D-state). | Этап 3 (Storage) или [Volume Unmount Issues](./volume_unmount_issues.md). |
| `FailedAttachVolume` | CSI не может примонтировать том к узлу. | Проверьте `kubectl get volumeattachment`. |
| `Unhealthy` | Liveness/Readiness probe вернул неуспех. | Этап 2.1 (контейнеры) или Этап 6 (liveness loop). |
| `FailedPreStopHook` | PreStop hook не завершился. | Увеличьте `terminationGracePeriodSeconds`. |
| `Eviction` | Выселение через Eviction API (drain, autoscaler). | Этап 4 (PDB). |
| `OOMKilling` | Процесс убит OOM Killer. | Увеличьте `resources.limits.memory`. |
| `BackOff` | Контейнер перезапускается после ошибки. | Проверьте логи: `kubectl logs <pod> --previous`. |
| `NodeNotReady` | Kubelet не отвечает. | Этап 5 (Node). |
| `Killing` | Kubelet завершает контейнер (нормальное завершение). | Нормальное поведение. |

### Типовые паттерны завершения и их значение

| Паттерн | Значение | Действие |
| :--- | :--- | :--- |
| Контейнер завершается с `exitCode: 143` через 30с после `SIGTERM` | Нормальное поведение. Приложение обработало SIGTERM. | Действий не требуется. |
| Контейнер завершается с `exitCode: 137` через `terminationGracePeriodSeconds` | Приложение не обработало SIGTERM. | Проверьте PID 1 (Этап 2.4). |
| Контейнер перезапускается с `restartCount` > 0 в Terminating | `livenessProbe` срабатывает до завершения. | Увеличьте `failureThreshold` (Этап 6). |
| Pod висит с `finalizers` > 5 минут | Финализатор не снят контроллером. | Проверьте CSI-контроллер или снимите вручную. |
| Pod в Terminating с `deletionGracePeriodSeconds: 0` | Принудительное удаление (`--force --grace-period=0`). | Нормально для выключенных узлов. |
| Pod с `deletionTimestamp`, но `kubectl get pods` показывает `Running` | Kubelet ещё не обработал удаление. | Подождите `terminationGracePeriodSeconds`. |

### Edge Cases

**Связь с ResourceQuota:**
Pod в `Terminating` **всё ещё считается** в квоте (`ResourceQuota`). Это может блокировать создание новых подов в этом Namespace. Проверка:

```bash
kubectl get resourcequota -n <namespace> -o jsonpath='{.items[*].status}'
# Ищите: "pods" в "used" vs "hard"
```

**Связь с OOMKilled и Memory Limits:**
Если контейнер убит `OOMKilled`, проверьте, не является ли он Java-приложением с неправильно настроенной кучей. JVM может потреблять больше `limits.memory` из-за отсутствия `-XX:MaxRAMPercentage`.

**Связь с DaemonSet:**
Pod'ы DaemonSet **не могут** использовать Pod Disruption Budget (PDB не действует на DaemonSet). При `kubectl drain` с `--ignore-daemonsets=false` поды DaemonSet удаляются принудительно.

**Связь с Job и Active Deadline Seconds:**
Если Job имеет `activeDeadlineSeconds`, Pod может быть завершён контроллером Job до истечения `terminationGracePeriodSeconds`. Проверьте `kubectl get job <name> -o jsonpath='{.spec.activeDeadlineSeconds}'`.

### Связанные команды kubectl

| Команда | Назначение |
| :--- | :--- |
| `kubectl delete pod <name> --grace-period=<N>` | Удаление с указанием периода ожидания (0 = немедленный SIGKILL) |
| `kubectl delete pod <name> --force --grace-period=0` | Принудительное удаление без ожидания |
| `kubectl patch pod <name> -p '{"metadata":{"finalizers":null}}'` | Ручное снятие финализаторов |
| `kubectl wait --for=delete pod/<name> --timeout=<N>s` | Ожидание удаления Pod |
| `kubectl get events --field-selector involvedObject.name=<name>` | События завершения |
| `kubectl top pod <name>` | Текущее потребление CPU/Memory |
| `kubectl logs <name> --previous` | Логи предыдущего (убитого) контейнера |
| `kubectl get volumeattachment` | Проверка привязки томов к узлам |
| `kubectl taint nodes <name> node.kubernetes.io/out-of-service=NoExecute:NoExecute` | Пометка узла для out-of-service |
| `kubectl drain <node> --ignore-daemonsets --timeout=900s` | Безопасное обслуживание узла |

**См. также:**
- [Определения Pod Terminating](./definitions.md) — базовые термины и механизмы.
- [Graceful Shutdown](./graceful_shutdown.md) — настройка периодов завершения и preStop.
- [Ошибки размонтирования томов](./volume_unmount_issues.md) — глубокий анализ проблем ФС.
- [Проблемы финализаторов](./finalizer_issues.md) — ручная очистка и CSI-специфика.
- [Недоступность узла](./node_unavailable_issues.md) — действия при отказе инфраструктуры.
- [Блокировка через PDB](./pdb_blocking.md) — разрешение блокировок при drain.
