# Диагностика недоступности узла: Алгоритм

Системный процесс выявления причин перехода узла в состояния `NotReady` или `Unknown`. Диагностика охватывает все уровни: от Kubernetes API до низкоуровневых проверок ядра ОС и аппаратного обеспечения.

## Основные определения

**Диагностика узла** — это методология последовательной проверки компонентов кластера и хоста для локализации точки сбоя (сеть, Kubelet, ресурсы, CRI-рантайм или ядро).

**Целевое состояние** — восстановление стабильного статуса `Ready` и минимизация влияния на запущенные поды (предотвращение нежелательных эвикций).

Основные статусы и условия описаны в разделе: [Недоступность узла: Определения](./definitions.md).

## Основные концепции

### Инструменты диагностики

| Инструмент | Уровень | Назначение |
| :--- | :--- | :--- |
| **`kubectl`** | Кластер | Внешний осмотр через API (Conditions, Events, Leases). |
| **`kubectl debug node/`** | Узел | Отладка через эфемерные контейнеры (рекомендуется профиль `--profile=sysadmin`). |
| **`crictl`** | CRI | CLI для прямой работы с рантаймом (containerd/CRI-O) на узле. |
| **`ssh`** | ОС | Прямой доступ к узлу для глубокого системного анализа. |
| **`journalctl`** | Сервисы | Просмотр логов системных служб (`kubelet`, `containerd`). |
| **`dmesg` / `vmstat`** | Ядро | Анализ аппаратных ошибок, I/O wait и срабатываний OOM-killer. |

### Ключевые индикаторы (Node Conditions)

При выполнении `kubectl describe node <node-name>` критически важными являются поля `Reason` и `Message`:

| Reason | Состояние | Интерпретация | Типичные причины |
| :--- | :--- | :--- | :--- |
| **`KubeletReady`** | `True` | `kubelet` работает штатно. | Нормальная работа |
| **`KubeletNotReady`** | `False` | Агент активен, но есть блокирующие проблемы (например, сбой CNI или CSI). | Проблемы с сетью, CRI, ресурсами |
| **`KubeletStopped`** | `False` | Служба `kubelet` на узле остановлена или упала. | Остановка службы, crash |
| **`NodeStatusNeverUpdated`** | `Unknown` | API-сервер не получал heartbeats с момента создания объекта. | Неправильная конфигурация, проблемы с сетью |
| **`NodeStatusUnknown`** | `Unknown` | Потеря связи с работающим узлом (тайм-аут Lease). | Сетевая изоляция, crash kubelet |

### Механизм PLEG (Pod Lifecycle Event Generator)

**PLEG (Pod Lifecycle Event Generator)** — компонент Kubelet, отвечающий за мониторинг состояния контейнеров и генерацию событий жизненного цикла подов. PLEG работает в фоновом режиме и периодически опрашивает CRI-рантайм для получения актуального состояния контейнеров.

**Как работает PLEG:**
1. Каждые **1 секунду** PLEG опрашивает CRI через gRPC API
2. Сравнивает текущее состояние с предыдущим
3. Генерирует события: `ContainerStarted`, `ContainerStopped`, `ContainerHealth`
4. Передает события в sync loop Kubelet

**Причины сбоев PLEG:**
- **Перегрузка CRI**: рантайм не успевает обрабатывать запросы
- **I/O Wait**: проблемы с диском блокируют операции
- **Сетевые проблемы**: задержки в gRPC вызовах
- **Много контейнеров**: превышение лимита на количество подов

**Диагностика PLEG:**
```bash
# Проверка логов PLEG
journalctl -u kubelet | grep -i "pleg"
# → I0904 17:35:00.123456 123456 generic.go:340] PLEG is healthy
# → W0904 17:35:01.654321 123456 generic.go:345] PLEG is not healthy: relist period was too long

# Проверка времени relist
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastTransitionTime}'
```

### Механизм Heartbeats и Lease API

Kubernetes использует два механизма для отслеживания живости узлов:

1. **Node Lease (основной)**: обновляется каждые 10 секунд
2. **Node Status (редкий)**: обновляется каждые 5 минут или при изменениях

**Тайм-ауты:**
- `node-monitor-grace-period`: 40 секунд (по умолчанию) - время до присвоения статуса `Unknown`
- `node-monitor-period`: 5 секунд (по умолчанию) - частота проверки

**Формула расчета тайм-аута:**
```
node-monitor-grace-period = node-monitor-period × 2 + запас
```

### Сетевые зависимости и порты

Для корректной работы и диагностики должны быть открыты порты:
- **`10250`** (TCP): Входящий для Kubelet API (логи, метрики, `exec`). Если закрыт — `kubectl logs` не будут работать.
- **`6443`** (TCP): Исходящий от Kubelet к API-серверу. Если закрыт — узел уйдет в `Unknown`.
- **Порты CNI**: Например, 4789/UDP (VXLAN) или 179 (BGP) для связи между подами на разных узлах.

## Практические сценарии

### Пошаговый алгоритм диагностики (Step-by-Step)

#### Шаг 1: Анализ через Control Plane (Внешний осмотр)

Начните с проверки состояния объекта Node и пульса (Lease):

```bash
# 1. Проверка статуса и времени последнего обновления
kubectl get nodes -o wide
# → NAME    STATUS     ROLES    AGE   VERSION   INTERNAL-IP     OS-IMAGE
# → node1   Ready      <none>   30d   v1.31.0   10.0.1.10       Ubuntu 22.04.3 LTS
# → node2   NotReady   <none>   30d   v1.31.0   10.0.1.11       Ubuntu 22.04.3 LTS

# 2. Проверка Heartbeats (Lease API) — современный способ в 1.31
kubectl get lease -n kube-node-lease <node-name> -o yaml
# Смотрите на поле renewTime: оно должно обновляться каждые 10 секунд.
# Пример вывода:
# apiVersion: coordination.k8s.io/v1
# kind: Lease
# metadata:
#   name: node1
#   namespace: kube-node-lease
# spec:
#   holderIdentity: node1
#   leaseDurationSeconds: 40
#   renewTime: "2026-09-04T17:30:00Z"

# 3. Поиск событий (Events), связанных с узлом
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name> --sort-by='.lastTimestamp'
# Пример вывода при проблемах:
# LAST SEEN   TYPE      REASON        OBJECT   MESSAGE
# 5m          Warning   NodeNotReady  Node     Node node2 status is now: NodeNotReady
# 10m         Normal    NodeReady     Node     Node node2 status is now: NodeReady

# 4. Проверка всех Conditions узла
kubectl describe node <node-name> | grep -A 20 "Conditions:"
# → Ready               True    Mon, 04 Sep 2026 17:30:00 +0000   KubeletReady    kubelet is posting ready status
# → MemoryPressure      False   Mon, 04 Sep 2026 17:30:00 +0000   KubeletHasMemory  kubelet has memory available
# → DiskPressure        False   Mon, 04 Sep 2026 17:30:00 +0000   KubeletHasDisk    kubelet has disk pressure
# → PIDPressure         False   Mon, 04 Sep 2026 17:30:00 +0000   KubeletHasPID     kubelet has PID pressure
# → NetworkUnavailable  False   Mon, 04 Sep 2026 17:30:00 +0000   RouteCreated      RouteController created a route

# 5. Проверка Taints на узле
kubectl get node <node-name> -o jsonpath='{.spec.taints}'
# → [{"key":"node.kubernetes.io/unreachable","effect":"NoExecute","timeAdded":"2026-09-04T17:25:00Z"}]

# 6. Проверка доступности API-сервера
kubectl cluster-info
# → Kubernetes control plane is running at https://10.0.1.1:6443
# → CoreDNS is running at https://10.0.1.1:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
```

#### Шаг 2: Удалённая отладка через kubectl debug

Используйте эфемерный контейнер для инспекции хоста без SSH:

```bash
kubectl debug node/<node-name> -it --image=ubuntu:24.04 --profile=sysadmin
# Профиль sysadmin дает доступ к ФС хоста в /host, процессам и сети.
# Внутри контейнера: chroot /host
```

#### Шаг 3: Локальная диагностика на узле (SSH)

Если API-сервер доступен, но узел не в сети:

```bash
# 1. Проверка системных служб
systemctl status kubelet containerd
# → kubelet.service - kubelet: The Kubernetes Node Agent
#    Loaded: loaded (/lib/systemd/system/kubelet.service; enabled; vendor preset: enabled)
#    Active: active (running) since Thu 2026-09-04 17:30:00 UTC; 5min ago
# containerd.service - containerd container runtime
#    Loaded: loaded (/lib/systemd/system/containerd.service; enabled; vendor preset: enabled)
#    Active: active (running) since Thu 2026-09-04 17:30:00 UTC; 5min ago

# 2. Анализ логов kubelet (поиск ошибок API или CRI)
journalctl -u kubelet -n 100 --no-pager
# Примеры ошибок:
# → E0904 17:35:00.123456 123456 reflector.go:150] Failed to list *v1.Node: Get "https://10.0.1.1:6443/api/v1/nodes": dial tcp 10.0.1.1:6443: connect: connection refused
# → E0904 17:35:00.654321 123456 runtime.go:78] Abort: PLEG is not healthy

# 3. Проверка сообщений ядра (OOM-killer, проблемы с диском)
dmesg -T | grep -iE "oom|killed|error|fail|readonly"
# Пример вывода при OOM:
# → [Thu Sep  4 17:35:00 2026] Out of memory: Killed process 12345 (kubelet) total-vm:1234568kB, anon-rss:876543kB

# 4. Проверка времени работы узла (uptime)
uptime
# → 17:35:00 up 30 days,  2:30,  1 user,  load average: 2.50, 1.80, 1.20

# 5. Проверка использования ресурсов
top -bn1 | head -20
# → Tasks: 250 total,   2 running, 248 sleeping,   0 stopped,   0 zombie
# → %Cpu(s): 25.0 us,  5.0 sy,  0.0 ni, 65.0 id,  5.0 wa,  0.0 hi,  0.0 si,  0.0 st
# → MiB Mem:  16384.0 total,   8192.0 free,   4096.0 used,   4096.0 buff/cache
# → MiB Swap:  4096.0 total,   4096.0 free,      0.0 used.  11264.0 avail Mem
```

#### Шаг 4: Проверка ресурсов и рантайма (CRI)

```bash
# 1. Проверка диска и лимитов PID
df -h
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1        50G   30G   18G  63% /
# → /dev/sdb1       100G   50G   45G  53% /var/lib/containerd

cat /proc/sys/kernel/pid_max
# → 32768

ps -eLf | wc -l
# → 1250

# 2. Прямая проверка рантайма через crictl
sudo crictl info
# → {
# →   "containerd": {
# →     "version": "1.7.0",
# →     "commit": "unknown"
# →   },
# →   "runtime": {
# →     "name": "containerd",
# →     "version": "1.7.0"
# →   }
# → }

sudo crictl ps
# → CONTAINER ID   IMAGE          CREATED        STATE    NAME     ATTEMPT    POD ID    POD NAME
# → abc123def456   nginx:latest   2 hours ago    Running  nginx    0          xyz789    nginx-pod

sudo crictl stats
# → CONTAINER ID   NAME     CPU %   MEM USAGE / LIMIT     MEM %   NET I/O          BLOCK I/O
# → abc123def456   nginx    0.50%   50MiB / 128MiB        39.06%  1.5MB / 2.3MB    0B / 0B

# 3. ПроверкаPods через crictl
sudo crictl pods
# → POD ID              CREATED             STATE               NAME                NAMESPACE           ATTEMPT
# → xyz789              2 hours ago         Running             nginx-pod           default             0

# 4. Проверка образов
sudo crictl images
# → IMAGE               TAG                 IMAGE ID            SIZE
# → docker.io/library/nginx   latest          abc123def456        187MB

# 5. Проверка логов контейнера через crictl
sudo crictl logs <container-id>
# → 2026/09/04 17:30:00 [notice] 1#1: start worker process 1
# → 2026/09/04 17:30:00 [notice] 1#1: start worker process 2
```

---

## Сценарий: "Мигающий" узел (Ready/NotReady Flapping)

Ситуация, при которой узел постоянно переключается между состояниями, является критической: она вызывает каскадные выселения подов и нестабильность Control Plane.

### 1. Проверка журналов Kubelet
Ищите записи о невозможности отправить heartbeat или тайм-ауты обращения к API:
```bash
journalctl -u kubelet -f | grep -iE "heartbeat|lease|error"
```

### 2. Проверка работоспособности PLEG
**PLEG (Pod Lifecycle Event Generator)** — механизм в Kubelet, синхронизирующий состояние подов с CRI.
- **Признак сбоя:** Ошибки в логах `PLEG is unhealthy` или `skipping pod lifecycle event`.
- **Причина:** Если PLEG неисправен, Kubelet не успевает обрабатывать события контейнеров и «замирает», пропуская отправку heartbeats. Обычно это указывает на перегрузку рантайма (`containerd`) или зависание I/O.

### 3. Углубленная проверка системных ресурсов
- **Память:** Активен ли OOM-killer? В K8s 1.31 при наличии **Swap** узел может не уходить в `NotReady` сразу, но производительность резко упадет из-за трэшинга диска.
- **CPU:** Проверьте `top`. Если Kubelet (процесс) ограничен в CPU (Throttling), он может не успевать обновлять Lease.
- **Диск:** Заполнение `/var/lib/kubelet` или проблемы с Latency на системном диске.
- **PID:** Исчерпание идентификаторов процессов блокирует создание новых контейнеров.
  ```bash
  sysctl kernel.pid_max
  ```

### 4. Сетевое подключение к API Server
Периодическая потеря пакетов или проблемы с брандмауэром.
```bash
# Проверка доступности API изнутри узла
curl -k https://<api-server-ip>:6443/healthz
```

**Реальный пример (Кейс из практики):**
Узел переходил в `NotReady` каждые несколько часов. Логи показали `PLEG is unhealthy`. Расследование выявило ошибку в рантайме при обработке огромного количества Liveness-проб (500+ на узел). Рантайм переставал отвечать на запросы PLEG, Kubelet считал узел неисправным.
**Решение:** Оптимизация частоты проб и обновление `containerd` до версии с исправленным механизмом блокировок.

### 5. Архитектурное влияние флапинга

1.  **Нагрузка на Control Plane:** Массовые записи в `etcd` при каждом изменении статуса.
2.  **Каскадное выселение (Churn):** Постоянное пересоздание подов из-за срабатывания `pod-eviction-timeout` (обычно 5 мин).
3.  **Неэффективность планирования:** `kube-scheduler` планирует поды на узел в момент `Ready`, но они падают при переходе в `NotReady`.
4.  **Фрагментация ресурсов:** Препятствует работе автоскейлеров (Karpenter/CAS), так как они не могут консолидировать нагрузку на нестабильных узлах.

---

## Сценарий: Проблемы с сетью (Network Partition)

Сетевая изоляция узла от API-сервера приводит к состоянию `Unknown`. Это одна из самых частых причин недоступности в дата-центрах.

### Причины
- Блокировка файрволом порта 6443 (API-сервер)
- Проблемы с сетевым оборудованием (коммутатор, маршрутизатор)
- Неправильная маршрутизация
- Переполнение conntrack table

### Диагностика

```bash
# 1. Проверка доступности API-сервера из узла
curl -sk https://<api-server-ip>:6443/healthz
# → ok

# 2. Проверка портов
nc -zv <api-server-ip> 6443
# → Connection to 10.0.1.1 6443 port [tcp/*] succeeded!

# 3. Проверка маршрутизации
ip route show
# → default via 10.0.1.1 dev eth0
# → 10.0.1.0/24 dev eth0 proto kernel scope link src 10.0.1.10

# 4. Проверка conntrack table
dmesg | grep conntrack
# → [Thu Sep  4 17:35:00 2026] nf_conntrack: table full, dropping packet

# 5. Проверка файрвола
sudo iptables -L -n | grep -E "6443|DROP|REJECT"
# → DROP tcp  -- 0.0.0.0/0  0.0.0.0/0  tcp dpt:6443
```

### Решение
1. Откройте порт 6443 в файрволе
2. Увеличьте лимит conntrack table: `sysctl net.nf_conntrack_max=1048576`
3. Проверьте сетевое оборудование

---

## Сценарий: Проблемы с диском (DiskPressure)

Заполнение системного диска или диска с образами приводит к `NotReady` и эвикции подов.

### Причины
- Логи контейнеров заполнили диск
- Образы контейнеров занимают много места
- Временные файлы не очищаются
- Монтирование дисков в режиме read-only

### Диагностика

```bash
# 1. Проверка использования диска
df -h
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1        50G   48G    0G 100% /
# → /dev/sdb1       100G   50G   45G  53% /var/lib/containerd

# 2. Проверка inode
df -i
# → Filesystem      Inodes  IUsed   IFree IUse% Mounted on
# → /dev/sda1      3276800 3276800      0  100% /

# 3. Поиск больших файлов
du -sh /* 2>/dev/null | sort -rh | head -10
# → 25G    /var
# → 10G    /var/lib
# → 8G     /var/lib/containerd

# 4. Проверка логов контейнеров
journalctl -u containerd | grep -i "disk\|space\|full"
# → W0904 17:35:00.123456 123456 sandbox.go:255] Failed to update sandbox status: disk space issue

# 5. Проверка монтирования
mount | grep -E "ro,|rw,"
# → /dev/sda1 on / type ext4 (ro,relatime,errors=remount-ro)
```

### Решение
1. Очистите неиспользуемые образы: `crictl rmi --prune`
2. Настройте ротацию логов
3. Добавьте мониторинг использования диска

---

## Сценарий: Проблемы с CRI-рантаймом

Сбой containerd или CRI-O приводит к `NotReady` и невозможности запуска новых подов.

### Причины
- Зависание процесса containerd
- Проблемы с overlayfs
- Конфликт версий
- Повреждение базы данных рантайма

### Диагностика

```bash
# 1. Проверка статуса containerd
systemctl status containerd
# → containerd.service - containerd container runtime
#    Active: active (running) since Thu 2026-09-04 17:30:00 UTC; 5min ago

# 2. Проверка логов containerd
journalctl -u containerd -n 100 --no-pager
# → time="2026-09-04T17:35:00.123456Z" level=error msg="Failed to GC image service" error="context deadline exceeded"

# 3. Проверка sock файла
ls -la /run/containerd/containerd.sock
# → srwxrwxrwx 1 root root 0 Sep  4 17:30 /run/containerd/containerd.sock

# 4. Проверка через ctr
sudo ctr version
# → Client:
# →   Version:  1.7.0
# →   Revision: unknown
# → Server:
# →   Version:  1.7.0
# →   Revision: unknown

# 5. Проверка подов через crictl
sudo crictl pods
# → POD ID              CREATED             STATE               NAME                NAMESPACE           ATTEMPT
# → xyz789              2 hours ago         Running             nginx-pod           default             0
```

### Решение
1. Перезапустите containerd: `systemctl restart containerd`
2. Очистите неиспользуемые ресурсы: `crictl rmi --prune`
3. Проверьте конфигурацию: `/etc/containerd/config.toml`

---

## Мониторинг и алертинг

### Prometheus метрики

Для обнаружения проблем с узлами настройте сбор метрик:

```yaml
# prometheus-rules.yaml
groups:
  - name: node-health
    rules:
      - alert: NodeNotReady
        expr: kube_node_status_condition{condition="Ready",status="true"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Узел {{ $labels.node }} не готов"
          description: "Узел находится в статусе NotReady более 5 минут"

      - alert: NodeLeaseExpired
        expr: time() - kube_node_lease_renew_time > 300
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Lease узла {{ $labels.node }} не обновляется"
          description: "Lease не обновлялся более 5 минут"

      - alert: NodeHighMemoryUsage
        expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100 > 90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое использование памяти на {{ $labels.node }}"
          description: "Использование памяти превышает 90%"

      - alert: NodeHighDiskUsage
        expr: (node_filesystem_size_bytes - node_filesystem_avail_bytes) / node_filesystem_size_bytes * 100 > 90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое использование диска на {{ $labels.node }}"
          description: "Использование диска превышает 90%"
```

### Grafana дашборды

Рекомендуемые дашборды для мониторинга узлов:
1. **Node Exporter Full** - полная информация об узле
2. **Kubernetes Cluster Monitoring** - состояние кластера
3. **Container Monitoring** - метрики контейнеров

### Логирование

Настройте централизованное логирование:
```bash
# Сбор логов kubelet
journalctl -u kubelet -f --output=json | jq .

# Сбор логов containerd
journalctl -u containerd -f --output=json | jq .
```

---

## Дополнительная информация

### Node Problem Detector (NPD)
Рекомендуется использовать NPD для обнаружения скрытых проблем:
- `KernelDeadlock` (зависание потоков ядра).
- `ReadonlyFilesystem` (переход диска в RO из-за ошибок).
- `HungTask` (зависшие системные процессы).

### Новое в Kubernetes 1.31
- **Swap Support (Stable)**: Учитывайте наличие свопа при анализе MemoryPressure.
- **PDB Unhealthy Pod Eviction Policy**: Используйте `AlwaysAllow`, чтобы `kubectl drain` не блокировался "мертвыми" подами при диагностике.
- **NodeMaintenance API (Alpha)**: Позволяет декларативно помечать узлы на обслуживание, что упрощает отслеживание статуса вывода узла.

**Связанные разделы:**
- [Taints и выселение](./taints_and_eviction.md) — последствия недоступности.
- [Проблемы Kubelet](./kubelet_issues.md) — глубокий разбор агента.
- [Обслуживание узлов](../../../Operations/node_maintenance.md) — плановые работы.
