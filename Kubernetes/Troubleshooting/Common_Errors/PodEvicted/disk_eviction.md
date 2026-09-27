# Pod Evicted: Выселение по диску (Disk Eviction)

## Определения

**DiskPressure Eviction** — защитный механизм `kubelet`, который принудительно завершает поды при критической нехватке дискового пространства или индексных дескрипторов (inodes). Процесс инициируется, когда узел переходит в состояние `DiskPressure=True`.

**Эфемерное хранилище (Ephemeral storage)** — временное дисковое пространство узла, используемое подами. Оно включает:
*   **Слой записи контейнера (Writable layer):** Изменения в файловой системе контейнера во время работы (overlayfs).
*   **Логи контейнеров:** Файлы в `/var/log/pods/<pod>/<container>/` (или `/var/log/containers/` — симлинки).
*   **Тома типа `emptyDir`:** Локальные данные, время жизни которых ограничено временем жизни пода.
*   **Временные файлы (`/tmp`):** Если не смонтирован отдельный `emptyDir`.

**Порог выселения (Eviction Threshold)** — лимит ресурсов, при пересечении которого `kubelet` начинает освобождение места.
*   **Hard Threshold:** Немедленное выселение (по умолчанию `nodefs.available < 10%`, `nodefs.inodesFree < 5%`).
*   **Soft Threshold:** Выселение после льготного периода (grace period).

**Inodes** — структуры данных в файловой системе, описывающие файлы и директории. Каждый файл, директория или симлинк занимает один inode. Исчерпание inodes делает невозможным создание новых файлов, даже если на диске есть свободные гигабайты.

**Container Log Rotation** — механизм ротации логов контейнеров, управляемый `kubelet`. По умолчанию `kubelet` ротирует логи при достижении 10 МБ на файл и хранит 5 старых копий. Параметры настраиваются через `containerLogMaxSize` и `containerLogMaxFiles` в `KubeletConfiguration`.

**cAdvisor** — встроенный агент в `kubelet`, который собирает метрики потребления ресурсов (CPU, память, файловая система) для всех контейнеров на узле. Именно `cAdvisor` сообщает `kubelet` об использовании дискового пространства каждые 10 секунд.

Общие определения и типы выселения: **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Разделение файловых систем (nodefs vs imagefs)

Kubernetes отслеживает два типа разделов через `Eviction Manager`:

1.  **`nodefs` (Основная ФС):** Корневой раздел узла. Содержит логи, локальное хранилище `kubelet` (`/var/lib/kubelet`), тома `emptyDir` и рабочие директории рантайма (если не выделен `imagefs`).
2.  **`imagefs` (ФС образов):** Опциональный выделенный раздел для рантайма (containerd/CRI-O). Используется для хранения кэша образов и слоев записи контейнеров.

| Раздел | Метрики Kubelet | Что занимает место | Типичные проблемы |
|:---|:---|:---|:---|
| **`nodefs`** | `nodefs.available`, `nodefs.inodesFree` | `/var/log`, `/var/lib/kubelet` (`emptyDir`), `/var/lib/containerd` (если нет `imagefs`) | Переполнение логов, `emptyDir` без `sizeLimit` |
| **`imagefs`** | `imagefs.available`, `imagefs.inodesFree` | Кэш образов, Snapshot-ы рантайма, слои записи (writable layers) | Нехватка места для `docker pull`, переполнение overlay |

**Архитектурная рекомендация:** Вынесение `/var/lib/containerd` на отдельный диск (логический раздел) изолирует рост логов приложения от кэша образов. Это предотвращает ситуацию, когда из-за переполнения логов удаляются образы, что приводит к циклической ошибке `ImagePullBackOff`.

**Как определить, какая ФС переполнена:**
```bash
# Проверка использования nodefs
df -h /var/lib/kubelet
# → /dev/sda1  50G   48G  1.5G   97% /var/lib/kubelet

# Проверка использования imagefs (если выделена отдельно)
df -h /var/lib/containerd
# → /dev/sdb1 100G   85G  10G   90% /var/lib/containerd
```

### Как kubelet рассчитывает использование диска

`kubelet` получает данные от `cAdvisor` и применяет следующую логику:

**Для `nodefs`:**
```
Использование nodefs = (Размер корневой ФС) - (Свободное место на корневой ФС)
```

**Для `imagefs`:**
```
Использование imagefs = (Размер раздела образов) - (Свободное место на разделе образов)
```

**Важный нюанс:** `kubelet` не учитывает `reserved` блоки файловой системы (5% по умолчанию для ext4). Если диск заполнен на 95%, `kubelet` будет считать, что свободного места 0%, даже если `df` показывает 5% (зарезервированных для root).

**Проверка текущих порогов:**
```bash
# Через API kubelet
curl -sk https://<node-ip>:10250/configz | jq '.kubeletconfig.evictionHard'
# → {"imagefs.available":"15%","imagefs.inodesFree":"5%","nodefs.available":"10%","nodefs.inodesFree":"5%"}

# Через манифест
cat /var/lib/kubelet/config.yaml | grep -A 10 "evictionHard"
```

### Алгоритм Garbage Collection (GC) диска

Перед выселением подов `kubelet` выполняет следующие шаги для очистки места:

1.  **Контейнерный GC:** Удаление всех завершенных (exited) контейнеров и их слоев записи.
    *   Настройка: `containerGCHighThresholdPercent` (по умолчанию 85%), `containerGCLowThresholdPercent` (по умолчанию 80%).
    *   Параметр `--container-runtime-max-container-backoff` (по умолчанию 10s) влияет на скорость очистки.
2.  **Образный GC:** Если использование `imagefs` (или `nodefs`, если `imagefs` нет) превысило `HighThresholdPercent` (по умолчанию 85%), удаляются неиспользуемые образы, пока использование не упадет до `LowThresholdPercent` (по умолчанию 80%).
    *   Настройка: `imageGCHighThresholdPercent`, `imageGCLowThresholdPercent`.
    *   Неиспользуемые образы — это образы, которые не используются ни одним запущенным или остановленным контейнером.
3.  **Выселение (Eviction):** Если GC не помог и свободное место все еще ниже Hard Threshold, начинается выбор кандидатов на выселение.

**Логи GC в kubelet:**
```bash
# Проверка запуска контейнерного GC
journalctl -u kubelet | grep -E "container GC|attempting to garbage collect"

# Проверка запуска образного GC
journalctl -u kubelet | grep -E "image GC|removing image|eviction manager: attempting to reclaim"

# Мониторинг циклов GC
journalctl -u kubelet | grep -E "eviction manager: (reclaim|attempting|evicting)"
```

### Порядок (Priority) выселения при DiskPressure

Кандидаты выбираются по следующей логике:
1.  **Нарушители лимитов:** Поды, потребление `ephemeral-storage` которых превышает `limits.ephemeral-storage`.
2.  **BestEffort / Burstable без запросов:** Поды, у которых не указаны `requests.ephemeral-storage`.
3.  **Относительное превышение:** Поды, у которых разница `Usage - Requests` максимально велика.

**Важно:** Если ни один под не превышает `limits`, `kubelet` все равно выберет кандидатов на основе абсолютного потребления. Поды `BestEffort` выселяются первыми, затем `Burstable`, затем `Guaranteed`.

> Подробнее о влиянии QoS на порядок выселения: **[QoS и выселение](./qos_and_eviction.md)**.

### Влияние Container Log Rotation на DiskPressure

`kubelet` выполняет ротацию логов контейнеров автоматически. Если агент сбора логов (Fluentd, Promtail, Vector) не успевает прочитать лог до ротации или удаления пода, данные будут потеряны.

**Параметры ротации (KubeletConfiguration):**

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `containerLogMaxSize` | Максимальный размер лог-файла перед ротацией | `10Mi` |
| `containerLogMaxFiles` | Количество ротированных файлов для хранения | `5` |

**Общий объем логов на под:**
```
Max Logs = containerLogMaxSize * containerLogMaxFiles
```
По умолчанию: `10Mi * 5 = 50Mi` на контейнер. Для пода с 3 контейнерами: `150Mi`.

**Пример настройки для продакшн-узлов:**
```yaml
# /var/lib/kubelet/config.yaml
containerLogMaxSize: "50Mi"    # Увеличиваем для приложений с высоким throughput логов
containerLogMaxFiles: 10       # Сохраняем больше копий для диагностики
```

**Как проверить текущие настройки:**
```bash
curl -sk https://<node-ip>:10250/configz | jq '.kubeletconfig.containerLogMaxSize'
# → "10Mi"
```

### Кросс-доменная корреляция

DiskPressure может быть симптомом проблем в других доменах:

| Домен | Проблема | Симптом DiskPressure |
|:---|:---|:---|
| **Storage** | NFS/Ceph сбой, I/O stall | Поды не могут записать данные, логи копятся в буфере |
| **Networking** | Сбой агента сбора логов | Логи не удаляются, ротация не работает |
| **Container Runtime** | Сбой containerd/CRI-O | Контейнеры не завершаются, слои записи не освобождаются |
| **Application** | Утечка файловых дескрипторов | Процесс держит удаленные файлы открытыми |

## Практические сценарии

### 1. Диагностика состояния узла и пода

При выселении под получает статус `Failed` с причиной `Evicted` и сообщением `The node was low on resource: ephemeral-storage`.

```bash
# 1. Проверка условий узла (Conditions)
kubectl describe node <node-name> | grep -A 5 Conditions
# Результат: DiskPressure: True

# 2. Проверка Taints (узел помечается автоматически)
kubectl describe node <node-name> | grep Taints
# Результат: node.kubernetes.io/disk-pressure:NoSchedule

# 3. Проверка сообщения в поде
kubectl get pod <pod-name> -o jsonpath='{.status.message}'
# → The node was low on resource: ephemeral-storage. \
#   Container nginx was using 2147483648, which exceeds its request of 1073741824
```

**Разбор сообщения:**
*   `Container nginx was using 2147483648` — фактическое потребление (2Gi).
*   `exceeds its request of 1073741824` — превышение запроса (1Gi).
*   Это критически важно: под был выселен, потому что превысил `requests`, а не `limits`.

**Логи Kubelet (`journalctl -u kubelet`):**
Ищите записи о нехватке места:
```bash
eviction manager: attempting to reclaim nodefs
eviction manager: pod <pod> is evicted because it exceeds its ephemeral-storage limit
```

### 2. Поиск причин переполнения на узле

#### Анализ nodefs

```bash
# 1. Анализ emptyDir (тома подов) — топ-5 самых больших
du -sh /var/lib/kubelet/pods/*/volumes/kubernetes.io~empty-dir/* | sort -rh | head -n 5

# 2. Анализ логов (если ротация контейнеров не справляется)
du -sh /var/log/pods/* | sort -rh | head -n 5

# 3. Детальный анализ логов конкретного пода
ls -lh /var/log/pods/<namespace>_<pod>/
# → 300M  container-name_0.log
# → 300M  container-name_0.log.1
# → 300M  container-name_0.log.2

# 4. Проверка удаленных, но удерживаемых файлов
# Если df показывает 100%, а du - 50%, проверьте этот пункт
lsof +L1 | grep deleted | sort -k 7 -rn | head -n 10
# → java  12345 root 1w  REG 253,1 10737418240 0 /var/log/app.log (deleted)
```

**Проверка удаленных файлов через /proc:**
```bash
# Найти PID процесса с открытым удаленным файлом
ls -la /proc/*/fd 2>/dev/null | grep deleted | head -n 5

# Проверить размер удерживаемых файлов
lsof +L1 2>/dev/null | awk '{sum += $7} END {printf "Total held: %.2f GB\n", sum/1024/1024/1024}'
```

#### Анализ imagefs

```bash
# 1. Просмотр использования диска через crictl
crictl stats
# → CONTAINER     CPU %   MEM   DISK

# 2. Список самых тяжелых образов
crictl images --sort-by size
# → IMAGE                                      SIZE
# → docker.io/library/postgres:15              378MB

# 3. Суммарный размер всех образов
crictl images | awk 'NR>1 {sum += $4} END {printf "Total: %.2f GB\n", sum/1024/1024}'

# 4. Проверка использования overlay (если containerd)
df -h /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs
```

### 3. Проблема Inode Exhaustion

Иногда `DiskPressure` возникает при наличии свободного места в гигабайтах, но при исчерпании лимита на количество файлов (Inodes). Это характерно для приложений, создающих миллионы мелких файлов (кэши, сессии, временные данные).

```bash
# 1. Проверка количества свободных Inodes
df -i /var/lib/kubelet
# → Filesystem      Inodes  IUsed   IFree IUse% Mounted on
# → /dev/sda1      6553600 6540000   13600   99% /

# 2. Поиск директории с наибольшим количеством файлов
du --inodes -xS /var/lib/kubelet/pods | sort -rn | head -n 10
# → 1245832  /var/lib/kubelet/pods/abc123/volumes/kubernetes.io~empty-dir/cache
# →  892341  /var/lib/kubelet/pods/def456/volumes/kubernetes.io~empty-dir/sessions

# 3. Быстрый поиск archivos с наибольшим количеством inode
find /var/lib/kubelet/pods -xdev -type f -printf '%h\n' | sort | uniq -c | sort -rn | head -n 10
```

**Решение:**
1.  Очистка лишних файлов: `find /var/lib/kubelet/pods/<pod>/volumes/... -type f -mtime +7 -delete`
2.  Настройка `sizeLimit` для `emptyDir` (см. сценарий 4).
3.  Увеличение `nodefs.inodesFree` в `evictionHard` (например, до `3%`).

### 4. Настройка лимитов (Resource Management)

Всегда ограничивайте эфемерное хранилище, чтобы один под не "уронил" весь узел.

```yaml
spec:
  containers:
  - name: app
    resources:
      requests:
        ephemeral-storage: "1Gi"  # Гарантированный минимум
      limits:
        ephemeral-storage: "2Gi"  # Kubelet выселит под при превышении 2Gi
  volumeMounts:
  - name: temp-data
    mountPath: /tmp
spec:
  volumes:
  - name: temp-data
    emptyDir:
      sizeLimit: "500Mi"  # Лимит конкретно для этого тома
```

**Валидация:**
```bash
# Проверка лимитов пода
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].resources}'
# → {"limits":{"ephemeral-storage":"2Gi","memory":"512Mi"},"requests":{"ephemeral-storage":"1Gi","memory":"256Mi"}}

# Проверка использования через cAdvisor
kubectl get pod <pod-name> -o json | jq '.status.containerStatuses[] | {name: .name, restartCount: .restartCount}'
```

**Пустой `emptyDir` без `sizeLimit`** — типичная причина DiskPressure. Под может записать неограниченное количество данных в том, заполнив весь диск узла.

### 5. Анализ логов Kubelet при DiskPressure

```bash
# Поиск записей о начале выселения
journalctl -u kubelet -g "eviction manager: attempting to reclaim"

# Пример лога:
# eviction manager: attempting to reclaim nodefs
# eviction manager: node stats: available 524288000, capacity 10737418240

# Поиск конкретного пода в логах выселения
journalctl -u kubelet | grep -A 5 "pod <pod-name>"

# Проверка запуска Garbage Collection перед выселением
journalctl -u kubelet | grep -E "container GC|image GC"

# Мониторинг циклов вычисления давления ресурсов
journalctl -u kubelet | grep -E "eviction manager: (reclaim|attempting)"
```

### 6. Проверка настроек kubelet

```bash
# Через API kubelet (требуется аутентификация)
curl -sk https://<node-ip>:10250/configz | jq '.kubeletconfig.evictionHard'
curl -sk https://<node-ip>:10250/configz | jq '.kubeletconfig.evictionSoft'
curl -sk https://<node-ip>:10250/configz | jq '.kubeletconfig.evictionSoftGracePeriod'

# Через манифест (если доступен)
cat /var/lib/kubelet/config.yaml | grep -A 20 "evictionHard"

# Проверка Allocatable ресурсов
kubectl describe node <node-name> | grep -A 10 "Allocated resources"
# → cpu: 8000m (reserved: 1000m, allocatable: 7000m)
# → ephemeral-storage: 90Gi (reserved: 10Gi, allocatable: 80Gi)
```

**Типичные проблемы конфигурации:**
*   `evictionHard` слишком агрессивный (например, `nodefs.available<10%` на 1ТБ диске = 100Gi запаса).
*   Отсутствие `kubeReserved` / `systemReserved` — нет резерва для системных процессов.
*   `evictionSoft` и `evictionSoftGracePeriod` слишком короткие — не дают времени на восстановление.
*   `imageGCHighThresholdPercent` слишком низкий — GC удаляет образы слишком агрессивно.

### 7. Диагностика через DisruptionTarget (K8s 1.31+)

Условие `DisruptionTarget` позволяет точно определить причину выселения:

```bash
# Проверка условия DisruptionTarget
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
# → reason: EvictionByKubelet
# → message: Pod was evicted due to node pressure: DiskPressure

# Проверка всех подов с DisruptionTarget по DiskPressure
kubectl get pods -A -o json | jq -r '.items[] | select(.status.conditions[]? | select(.type=="DisruptionTarget" and .reason=="EvictionByKubelet")) | "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="DisruptionTarget") | .message)"'
```

### 8. Использование эфемерных контейнеров для отладки диска

Если узел в критическом состоянии и SSH недоступен:

```bash
# Запуск отладочного контейнера с доступом к хостовой ФС
kubectl debug node/<node-name> -it --image=busybox

# Внутри контейнера:
chroot /host

# Проверка дисков узла
df -h
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1        50G   48G  1.5G  97% /

# Проверка inodes
df -i

# Поиск крупных директорий
du -sh /var/log/* | sort -rh | head
du -sh /var/lib/kubelet/pods/*/volumes/* | sort -rh | head

# Проверка удаленных открытых файлов
lsof +L1 | head -n 20

# Проверка размера логов контейнеров
ls -lh /var/log/containers/ | sort -k 5 -rh | head -n 10
```

**Проверка cAdvisor метрик напрямую на узле:**
```bash
# После chroot /host
curl -sk https://localhost:10250/stats/summary | jq '.node.fs.availableBytes'
curl -sk https://localhost:10250/stats/summary | jq '.node.fs.usedBytes'
curl -sk https://localhost:10250/stats/summary | jq '.pods[].containers[].rootfs.usedBytes' | sort -rn | head
```

### 9. Диагностика через скрипт

Быстрый скрипт для сбора всех данных об инциденте с DiskPressure:

```bash
#!/bin/bash
# save_disk_incident.sh — Сбор данных об инциденте с DiskPressure
# Использование: ./save_disk_incident.sh <node-name>

NODE=$1
OUTPUT="disk_incident_$(date +%Y%m%d_%H%M%S).txt"

echo "=== Disk Pressure Incident Report ===" > $OUTPUT
echo "Node: $NODE" >> $OUTPUT
echo "Date: $(date)" >> $OUTPUT

echo -e "\n=== Node Conditions ===" >> $OUTPUT
kubectl describe node $NODE | grep -A 20 "Conditions:" >> $OUTPUT

echo -e "\n=== Node Taints ===" >> $OUTPUT
kubectl describe node $NODE | grep -A 5 "Taints:" >> $OUTPUT

echo -e "\n=== Disk Usage ===" >> $OUTPUT
kubectl describe node $NODE | grep -A 10 "Allocated resources" >> $OUTPUT

echo -e "\n=== Evicted Pods ===" >> $OUTPUT
kubectl get pods -A --field-selector spec.nodeName=$NODE,status.reason=Evicted -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,MESSAGE:.status.message" >> $OUTPUT

echo -e "\n=== Events (DiskPressure) ===" >> $OUTPUT
kubectl get events --field-selector reason=Evicted --sort-by='.lastTimestamp' >> $OUTPUT 2>/dev/null

echo -e "\n=== Top Pods by Ephemeral Storage ===" >> $OUTPUT
kubectl top pods -A --sort-by=ephemeral-storage 2>/dev/null >> $OUTPUT

echo -e "\n=== kubelet Eviction Config ===" >> $OUTPUT
curl -sk https://localhost:10250/configz 2>/dev/null | jq '.kubeletconfig.evictionHard' >> $OUTPUT

echo "Report saved to $OUTPUT"
```

### 10. Анализ Disk I/O (не только места)

DiskPressure может возникать из-за проблем с I/O, а не с местом. Медленный диск приводит к накоплению невыброшенных данных.

```bash
# Проверка I/O等待 (await)
iostat -x 1 5
# → Device  r/s    w/s   await  %util
# → sda    150.0  200.0  45.2   95.0   ← Высокий await и %util

# Проверка I/O через atop
atop -d 1

# Проверка скорости записи в overlay
iotop -oP

# Проверка through containerd
crictl stats | grep -i "disk"
```

**Связь I/O и DiskPressure:** Если диск перегружен I/O, процесс сбора логов не успевает записывать данные. Это приводит к росту буферов в памяти, что может спровоцировать `MemoryPressure` параллельно с `DiskPressure`.

### 11. Перекрестная корреляция с другими壓力

DiskPressure редко бывает изолированным. Проверяйте параллельные состояния:

```bash
# Проверка всех Pressure conditions на узле
kubectl describe node $NODE | grep -A 5 "Conditions:"
# → DiskPressure True
# → MemoryPressure False
# → PIDPressure False

# Если DiskPressure и MemoryPressure одновременно — проблема с логами
# Если DiskPressure и PIDPressure — возможно fork-бомба
# Если только DiskPressure — изолированная проблема с диском
```

**Кросс-доменная проверка:**
```bash
# Проверка NFS mount (если используется)
mount | grep nfs
# → 10.0.0.5:/exports on /mnt/nfs type nfs4 (rw,relatime...)

# Проверка состояния NFS
nfsstat -c
# → calls  badcalls  bclntmtm  badxid
# → 123456  0       0         0

# Проверка Ceph (если используется)
ceph health
# → HEALTH_OK
```

## Дополнительная информация

### Настройка порогов (KubeletConfiguration)

Для современных узлов с большими дисками (1ТБ+) использование процентов неэффективно. Рекомендуется использовать абсолютные значения.

```yaml
# /var/lib/kubelet/config.yaml
evictionHard:
  nodefs.available: "5Gi"      # Жесткий порог
  nodefs.inodesFree: "1%"
  imagefs.available: "10Gi"
evictionSoft:
  nodefs.available: "10Gi"     # Мягкий порог
  imagefs.available: "15Gi"
evictionSoftGracePeriod:
  nodefs.available: "2m"       # Время на "самоочистку" перед выселением
  imagefs.available: "1m"
evictionMinimumReclaim:
  nodefs.available: "2Gi"      # Минимальное количество для освобождения
  imagefs.available: "3Gi"

# GC пороги
containerGCHighThresholdPercent: 85
containerGCLowThresholdPercent: 80
imageGCHighThresholdPercent: 85
imageGCLowThresholdPercent: 80
```

**Рекомендации по настройке порогов:**

| Тип узла | `nodefs.available` (Hard) | `imagefs.available` (Hard) | Комментарий |
|:---|:---|:---|:---|
| Worker (500ГБ диск) | `5Gi` | `10Gi` | Стандартная конфигурация |
| Worker (1ТБ+ диск) | `10Gi` | `15Gi` | Абсолютные значения предпочтительнее |
| Control Plane | `10Gi` | `15Gi` | Приоритет стабильности компонентов управления |
| Storage Worker | `20Gi` | `20Gi` | Увеличенный запас для I/O-интенсивных нагрузок |

### Мониторинг (PromQL)

```promql
# Узлы в состоянии DiskPressure
kube_node_status_condition{condition="DiskPressure", status="true"} == 1

# Потребление эфемерного хранилища конкретным подом
sum(container_fs_usage_bytes{container!=""}) by (pod, namespace)

# Прогноз исчерпания Inodes на узле (на основе тренда за 6 часов)
predict_linear(node_filesystem_files_free{mountpoint="/"}[6h], 3600 * 24) < 0

# Прогноз исчерпания дискового пространства на узле
predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 3600 * 24) < 0

# Процент использования диска на узле
(1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100

# Количество выселенных подов по DiskPressure за 24 часа
increase(kube_pod_status_reason{reason="Evicted"}[24h])

# Топ подов по использованию диска (требует node-exporter)
topk(10, container_fs_usage_bytes{container!=""})
```

**Алерты Prometheus:**
```yaml
# Предупреждение о росте использования диска
- alert: NodeDiskSpaceRunningLow
  expr: (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 > 85
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.instance }}: используется >85% диска"

# Критическое предупреждение
- alert: NodeDiskSpaceCritical
  expr: (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 > 95
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Узел {{ $labels.instance }}: критическое использование диска (>95%)"

# Мониторинг Inode exhaustion
- alert: NodeInodeExhaustion
  expr: (1 - node_filesystem_files_free{mountpoint="/"} / node_filesystem_files{mountpoint="/"}) * 100 > 90
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.instance }}: используется >90% inodes"
```

### Типичные ошибки при диагностике DiskPressure

| Ошибка | Последствия | Решение |
|:---|:---|:---|
| Путаница nodefs и imagefs | Неправильный выбор стратегии очистки | Проверяйте `df -h /var/lib/kubelet` и `df -h /var/lib/containerd` отдельно |
| Игнорирование удаленных файлов | `df` показывает 100%, `du` — 50% | Используйте `lsof +L1 | grep deleted` |
| Нет `sizeLimit` для emptyDir | Под может заполнить весь диск узла | Всегда указывайте `sizeLimit` в `emptyDir` |
| Игнорирование Inodes | Свободные ГБ, но нельзя создать файл | Проверяйте `df -i` параллельно с `df -h` |
| Слишком частая ротация логов | Слишком много мелких файлов | Настройте `containerLogMaxSize` и `containerLogMaxFiles` |
| Отсутствие мониторинга | Проблемы обнаруживаются только после вылета сервисов | Настройте алерты в Prometheus |
| Игнорирование disk I/O | DiskPressure из-за медленного диска | Проверяйте `iostat -x` для анализа `await` и `%util` |

### 12. Централизованный сбор логов и DiskPressure

Неправильная настройка сбора логов — одна из частых причин DiskPressure в продакшне. Агент сбора логов (Fluent Bit, Promtail, Vector, Grafana Alloy) должен успевать прочитать лог-файл **до** того, как kubelet выполнит ротацию или удалит под.

**Типичные проблемы:**

| Проблема | Симптом | Решение |
|:---|:---|:---|
| Агент не успевает читать логи | `nodefs.available` падает, хотя приложение не пишет много | Увеличьте `containerLogMaxSize` и `containerLogMaxFiles` |
| Агент упал или завис | Логи копятся в `/var/log/pods/` без отправки | Мониторьте агент через healthcheck, настройте auto-restart |
| Нет Dual Logging | При использовании network log driver логи не дублируются локально | Включите Dual Logging (Docker 20.10+) |
| Лог-агент на DaemonSet без requests | Агент потребляет все ресурсы узла | Установите `resources.requests` для агента |

**Рекомендуемая конфигурация для продакшна:**

```yaml
# Лимиты для контейнера с лог-агентом (DaemonSet)
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
    ephemeral-storage: "100Mi"
  limits:
    cpu: "500m"
    memory: "256Mi"
    ephemeral-storage: "500Mi"
```

**Проверка размера логов на узле:**
```bash
# Топ-5 самых больших лог-директорий
du -sh /var/log/pods/* | sort -rh | head -5

# Общий размер логов
du -sh /var/log/pods/
```

> Подробнее: **[Ротация логов Docker](../../../../Docker/Docker_logs/docker_log_rotation.md)**, **[Агентный сбор логов](../../../../Docker/Docker_logs/docker_agent_based_logging.md)**, **[Kubernetes: Архитектура мониторинга и логирования](../../../../Kubernetes/MonitoringLogging/kubernetes-monitoring-logging-architecture.md)**.

### 13. Kernel-level тюнинг для предотвращения DiskPressure

Некоторые параметры ядра косвенно влияют на потребление диска:

| Параметр | Влияние | Рекомендуемое значение |
|:---|:---|:---|
| `fs.file-max` | Общий лимит файловых дескрипторов. При исчерпании — процессы не могут создавать файлы. | `2097152` |
| `fs.inotify.max_user_watches` | Лимит отслеживания файлов (ConfigMap/Secret монтируются через inotify). | `524288` |
| `fs.inotify.max_user_instances` | Лимит inotify-очередей. При нехватке — поды в Pending. | `512` |
| `vm.max_map_count` | Лимит memory map areas. Для Elasticsearch/Java приложений. | `262144` |

```bash
# Проверка текущих значений
sysctl fs.file-max fs.inotify.max_user_watches fs.inotify.max_user_instances vm.max_map_count

# Применение (временно)
sudo sysctl -w fs.file-max=2097152
sudo sysctl -w fs.inotify.max_user_watches=524288

# Персистентно: /etc/sysctl.d/99-k8s-worker.conf
```

> Подробнее: **[sysctl: Параметры ядра](../../../../Linux/Core/kernel/sysctl.md)**, **[Лимиты ресурсов: Концепции](../../../../Linux/Core/processes/resource_limits_concepts.md)**, **[Подготовка узлов kubeadm](../../../../Kubernetes/Installation/kubeadm/kubeadm_installation_guide.md)**.

### Смотрите также

- **[Pod Evicted: Определения](./definitions.md)** — база по типам выселений.
- **[Диагностика выселения](./diagnostics.md)** — общий алгоритм поиска первопричин.
- **[Профилактика выселения](./prevention.md)** — как настроить кластер, чтобы избежать выселений.
- **[QoS и выселение](./qos_and_eviction.md)** — влияние классов ресурсов на выбор жертвы.
- **[Diagnosing Node Unavailability](../NodeUnavailability/diagnostics.md)** — диагностика проблем с узлами.
