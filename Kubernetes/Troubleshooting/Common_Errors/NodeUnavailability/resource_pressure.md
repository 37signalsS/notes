# Недоступность узла: Давление ресурсов

Давление ресурсов (Resource Pressure) — это защитное состояние узла, при котором `kubelet` обнаруживает критическую нехватку аппаратных мощностей и ограничивает планирование или начинает принудительное выселение подов для предотвращения системного сбоя. Данный файл является **SSoT для диагностики давления ресурсов, приводящего к недоступности узла** — детали по каждому типу выселения описаны в сестринских файлах, общие концепции kubelet — в [Настройка Kubelet](../../../Concepts/kubelet.md).

## Основные определения

**Давление ресурсов (Resource Pressure)** — набор флагов в `status.conditions` объекта Node, указывающих на дефицит конкретного ресурса (RAM, Disk, PID). Каждый флаг активирует **taint** на узле, запрещающий планировщику назначать новые поды с соответствующей `toleration`.

**Выселение (Eviction)** — процесс превентивного завершения подов компонентом `kubelet`. В отличие от OOM-killer ядра, выселение в Kubernetes основано на достижении порогов, настраиваемых в `KubeletConfiguration`. kubelet опрашивает метрики каждые **10 секунд** (по умолчанию) и сравнивает с `evictionHard` / `evictionSoft`.

**Eviction Manager** — модуль внутри `kubelet`, который непрерывно отслеживает метрики (через `cAdvisor`) и принимает решение о выселении. При достижении порога `evictionHard` выселение происходит немедленно без `grace period`. При `evictionSoft` выдерживается `evictionSoftGracePeriod`.

**Node Allocatable** — вычисляемое значение ресурсов, доступных для подов на узле. Формула:
`Allocatable = Capacity - kube-reserved - system-reserved - eviction-hard-threshold`
Где `kube-reserved` — ресурсы для компонентов Kubernetes (kubelet, containerd), `system-reserved` — для системных процессов (sshd, systemd, journald). Подробнее: [Настройка Kubelet: Node Allocatable](../../../Concepts/kubelet.md#управление-ресурсами-и-node-allocatable).

**PSI (Pressure Stall Information)** — механизм ядра Linux (4.20+), измеряющий **процент времени**, в течение которого процессы теряли возможность работать из-за нехватки ресурса. В отличие от `memory.available` (мгновенный снимок), PSI учитывает **время простоя**. Доступен в `/proc/pressure/memory`. Подробнее: [PSI: статистика давления на ресурсы](../../../Linux/Core/kernel/psi.md).

**cgroup v2 memory controller** — подсистема управления памятью. Основные контролы, влияющие на поведение контейнеров при давлении:
- `memory.max` — жесткий лимит (аналог `limits.memory`), при превышении — OOM Kill.
- `memory.high` — порог мягкого торможения (throttling), при превышении — процессы замедляются, но не убиваются.
- `memory.min` — гарантированный минимум (аналог `requests.memory`), не может быть отобран другими cgroups.

### Классификация типов давления ресурсов

| Тип | Condition | Тинт | t.Key | Порог по умолчанию | Влияние на поды |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Память** | `MemoryPressure=True` | `NoSchedule` | `node.kubernetes.io/memory-pressure` | `memory.available < 100Mi` | Запрет планирования новых подов, выселение BestEffort → Burstable → Guaranteed |
| **Диск (объем)** | `DiskPressure=True` | `NoSchedule` | `node.kubernetes.io/disk-pressure` | `nodefs.available < 10%` | Запрет планирования, выселение по QoS, очистка образов (Image GC) |
| **Диск (Inodes)** | `DiskPressure=True` | `NoSchedule` | `node.kubernetes.io/disk-pressure` | `nodefs.inodesFree < 5%` | Запрет планирования, выселение, невозможность создания новых файлов |
| **Процессы** | `PIDPressure=True` | `NoSchedule` | `node.kubernetes.io/pid-pressure` | `pid.available < 15%` | Запрет планирования, ошибки запуска контейнеров (`fork: Cannot allocate memory`) |

### Несжимаемые vs сжимаемые ресурсы

| Тип | Ресурсы | Реакция kubelet при дефиците |
| :--- | :--- | :--- |
| **Несжимаемые (Incompressible)** | Память, диск, PID | Выселение подов (Eviction) |
| **Сжимаемые (Compressible)** | CPU | Throttling (замедление контейнеров через CFS bandwidth control), но не выселение |

> **Важно:** CPU-throttling не приводит к `CPUThrottlingHigh` condition у узла — это метрика контейнера, а не узла. Но при severe CPU-throttling приложения могут деградировать, имитируя давление ресурсов.

### Раздельные файловые системы (nodefs vs imagefs)

| Раздел | Место по умолчанию | Метрики Kubelet | Что Occupies | Последствия переполнения |
| :--- | :--- | :--- | :--- | :--- |
| **nodefs** | `/` (корневой раздел) | `nodefs.available`, `nodefs.inodesFree` | `/var/log`, `/var/lib/kubelet/pods/`, `emptyDir`, `/tmp` | Выселение подов, потеря данных в emptyDir |
| **imagefs** | `/var/lib/containerd` (если выделен отдельно) | `imagefs.available`, `imagefs.inodesFree` | Кэш образов, snapshot-ы, writable layers | Image GC, `ImagePullBackOff`, невозможность запуска новых контейнеров |

> **Архитектурная рекомендация:** Вынесение `/var/lib/containerd` на отдельный диск изолирует рост логов приложения от кэша образов. Это предотвращает ситуацию, когда из-за переполнения логов удаляются образы, что приводит к циклической ошибке `ImagePullBackOff`.

### Пороги выселения (Thresholds)

| Тип порога | Поведение | Grace Period | Рекомендуемое использование |
| :--- | :--- | :--- | :--- |
| **Hard (Жесткий)** | Немедленное выселение по `SIGKILL` (без `grace period`) | Нет | Критичные системы, продакшен |
| **Soft (Мягкий)** | Выселение по `SIGTERM` после `evictionSoftGracePeriod` | `evictionSoftGracePeriod` | Dev/test среды, когда важно завершить работу корректно |

**Стандартная конфигурация порогов (рекомендуемая для продакшена):**
```yaml
evictionHard:
  memory.available: "200Mi"
  nodefs.available: "10%"
  nodefs.inodesFree: "5%"
  imagefs.available: "15%"
  imagefs.inodesFree: "5%"
  pid.available: "15%"
evictionSoft:
  memory.available: "500Mi"
  nodefs.available: "15%"
evictionSoftGracePeriod:
  memory.available: "1m30s"
  nodefs.available: "1m30s"
```

## Практические сценарии

### Сценарий 1: MemoryPressure — диагностика и кросс-доменные симптомы

**Симптомы**: Узел в `MemoryPressure=True`. Поды не планируются на узел. Логи kubelet: `Attempt to reclaim kubelet Great!

**Кросс-доменные симптомы** (важно учитывать):
- `DiskPressure` может возникнуть одновременно (если лог-файлы растут из-за swap).
- `PIDPressure` — fork-бомба из-за утечки памяти (много zombie-процессов).
- I/O деградация (PSI I/O `some` > 10%) из-за активного swap.

**Диагностика**:
```bash
# 1. Проверка Conditions узла
kubectl describe node <node-name> | grep -A 5 Conditions
# → MemoryPressure   True    Thu Sep  4 17:30:00 2026   KubeletHasMemoryPressure

# 2. Проверка available памяти через kubelet API
curl -sk https://<node-ip>:10250/pods | jq '.items[] | select(.metadata.name=="kube-proxy")' | head -5
# Или через API:
kubectl get --raw "/api/v1/nodes/<node-name>/proxy/stats/summary" | jq '.node.memory.availableBytes'
# → 52428800   ← 50MB available (критически мало)

# 3. Проверка через системные утилиты
free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:           15Gi       14Gi       256Mi        12Mi       512Mi       512Mi
# → Swap:         4.0Gi       3.8Gi       200Mi

# 4. Проверка использования памяти по процессам (топ-10)
ps aux --sort=-%mem | head -11
# → USER  PID %CPU %MEM  COMMAND
# → root  1234  12.5  45.2  java -jar app.jar    ← доминирующий процесс

# 5. Проверка PSI (если ядро поддерживает)
cat /proc/pressure/memory
# → some avg10=15.30 avg60=8.20 avg300=3.50 total=12345678
# → full avg10=5.20  avg60=2.10 avg300=0.80 total=4567890
# → avg10 > 15% = критическое давление

# 6. Проверка swap-активности
vmstat 1 3
# → free  buff  cache   si   so
# → 256M  128M  384M  1024 2048   ← активный swap-in/swap-out
```

**Решение**:
```bash
# 1. Немедленное освобождение памяти (убить памятоемкие поды с низким QoS)
kubectl get pods --field-selector spec.nodeName=<node-name> -o json | \
  jq -r '.items[] | select(.status.qosClass=="BestEffort") | .metadata.name' | \
  head -5 | xargs -I {} kubectl delete pod {} --grace-period=0 --force

# 2. Очистка кэша страниц (temporary)
sync && echo 3 > /proc/sys/vm/drop_caches
# Проверка:
free -h

# 3. Если Swap агрессивно используется — добавьте pod anti-affinity или ограничьте поды
# 4. Рассмотрите добавление RAM на узел или горизонтальное масштабирование
```

Подробнее: **[Выселение по памяти](../PodEvicted/memory_eviction.md)**.

---

### Сценарий 2: DiskPressure — объем vs Inodes

**Симптомы**: Узел в `DiskPressure=True`. Поды не планируются. `kubectl logs` может не работать (нет места для записи логов).

**Кросс-доменные симптомы**:
- `MemoryPressure` — если активен swap из-за нехватки диска (page-in с диска).
- Container runtime failures — containerd/CRI-O не может распаковать образы.
- Node NotReady — kubelet не может записать heartbeat файлы.

**Диагностика**:
```bash
# 1. Проверка Conditions узла
kubectl describe node <node-name> | grep -A 5 Conditions
# → DiskPressure   True    Thu Sep  4 17:30:00 2026   KubeletHasDiskPressure

# 2. Проверка использования nodefs и imagefs
df -h /var/lib/kubelet
# → /dev/sda1   50G   48G  1.5G   97% /var/lib/kubelet   ← nodefs

df -h /var/lib/containerd
# → /dev/sdb1  100G   85G  10G   90% /var/lib/containerd  ← imagefs

# 3. Проверка Inodes (часто неочевидная причина DiskPressure)
df -i /var/lib/kubelet
# → Filesystem      Inodes   IUsed   IFree IUse% Mounted on
# → /dev/sda1      3200000  3190000   10000   99% /var/lib/kubelet  ← Inodes исчерпаны

# 4. Поиск директорий, потребляющих最多的 Inodes
du --inodes -xS /var/lib/kubelet/pods 2>/dev/null | sort -rh | head -10
# → 1523456  /var/lib/kubelet/pods/abc123/volumes/empty-dir/cache
# →  892345  /var/lib/kubelet/pods/def456/volumes/empty-dir/logs

# 5. Проверка, что именно заполняет disk (top-10 самых больших директорий)
du -hx /var/lib/kubelet 2>/dev/null | sort -rh | head -10
# → 25G   /var/lib/kubelet/pods
# → 15G   /var/lib/containerd

# 6. Проверка дискового I/O (DiskPressure часто сопровождается I/O starvation)
iostat -x 1 3
# → Device   r/s   w/s   await   svctm   %util
# → sda      5.00  350.00  250.00  2.80    100.00  ← 100% utilization
```

**Решение**:
```bash
# 1. Очистка неиспользуемых образов
sudo crictl rmi --prune

# 2. Очистка завершенных контейнеров
sudo crictl rm -f $(sudo crictl ps -q --state exited | head -20)

# 3. Очистка лог-файлов контейнеров (источник DiskPressure)
sudo find /var/log/pods/ -name "*.log" -mtime +3 -delete
# Или точечная очистка:
sudo find /var/log/pods/ -name "*.log" -exec truncate -s 0 {} \;

# 4. Поиск и удаление старых emptyDir без sizeLimit
kubectl get pods --field-selector spec.nodeName=<node-name> -o json | \
  jq -r '.items[] | select(.spec.volumes[]?.emptyDir != null) | .metadata.name' | \
  head -5

# 5. Если нужно немедленное освобождение места (экстренная мера)
sudo journalctl --vacuum-size=100M
sudo apt-get clean 2>/dev/null || sudo yum clean all 2>/dev/null

# 6. Проверка восстановления
kubectl describe node <node-name> | grep -A 3 Conditions
# → DiskPressure   False   KubeletHasNoDiskPressure
```

Подробнее: **[Выселение по диску](../PodEvicted/disk_eviction.md)**.

---

### Сценарий 3: PIDPressure — fork-бомба и исчерпание PID

**Симптомы**: Узел `Ready`, но команды `exec` или запуск новых контейнеров падают с ошибкой `resource temporarily unavailable` или `fork: Cannot allocate memory`.

**Кросс-доменные симптомы**:
- `MemoryPressure` — fork-бомба создает много процессов, каждый потребляет память.
- Container runtime failures — containerd не может создать новый процесс в контейнере.
- High I/O — много процессов создают swap-in/swap-out.

**Диагностика**:
```bash
# 1. Проверка Conditions узла
kubectl describe node <node-name> | grep -A 5 Conditions
# → PIDPressure   True    Thu Sep  4 17:30:00 2026   KubeletHasPIDPressure

# 2. Проверка лимитов ядра
sysctl kernel.pid_max
# → kernel.pid_max = 32768   ← стандартное значение

# 3. Проверка текущего количества процессов
ps -eLf | wc -l
# → 31500   ← критически близко к 32768

# 4. Поиск процессов с наибольшим количеством потомков
ps -eo pid,ppid,nlwp,comm --sort=-nlwp | head -11
# → PID  PPID NLWP COMMAND
# → 1234 1    5000 java -jar leaky-app.jar   ← 5000 потоков

# 5. Проверка PID в cgroups (какой под создал больше процессов)
for cg in /sys/fs/cgroup/kubepods.slice/kubepods-pod*.slice; do
  echo "$(cat $cg/cgroup.procs 2>/dev/null | wc -l) $cg"
done | sort -rn | head -5
# → 2500 /sys/fs/cgroup/kubepods.slice/kubepods-pod<uid1>.slice
# → 1800 /sys/fs/cgroup/kubepods.slice/kubepods-pod<uid2>.slice

# 6. Проверка podPidsLimit в kubelet
cat /var/lib/kubelet/config.yaml | grep podPidsLimit
# → podPidsLimit: 4096   ← лимит на под (по умолчанию)
```

**Решение**:
```bash
# 1. Увеличение системного лимита (временное, до перезагрузки)
sudo sysctl -w kernel.pid_max=65536

# 2. Постоянное изменение
echo "kernel.pid_max=65536" | sudo tee -a /etc/sysctl.d/99-pid-max.conf
sudo sysctl --system

# 3. Убить fork-бомбу (если известен PID-потомок)
sudo kill -9 -- -<pgid>   # убить всю группу процессов

# 4. Настройка podPidsLimit в kubelet (ограничение одного пода)
# В /var/lib/kubelet/config.yaml:
# podPidsLimit: 4096

# 5. Поиск и удаление problematic пода
kubectl get pods --field-selector spec.nodeName=<node-name> -o json | \
  jq -r '.items[] | select(.spec.containers[].resources.limits.cpu == null) | .metadata.name' | \
  head -3 | xargs -I {} kubectl delete pod {} --grace-period=0 --force

# 6. Проверка восстановления
ps -eLf | wc -l
# → 15000   ← норма
```

---

### Сценарий 4: MemoryPressure + DiskPressure (кросс-доменный)

**Симптомы**: Узел одновременно в `MemoryPressure=True` и `DiskPressure=True`. Каскадная деградация.

**Причина**: Часто DiskPressure является первичным (диск заполнен), что приводит к swap-in/swap-out, что приводит к MemoryPressure.

**Диагностика**:
```bash
# 1. Проверка всех Conditions
kubectl describe node <node-name> | grep -A 10 Conditions
# → MemoryPressure   True    ...
# → DiskPressure     True    ...
# → PIDPressure      False   ...
# → Ready            True    ...

# 2. Порядок событий (в логах kubelet)
journalctl -u kubelet --since "1 hour ago" --no-pager | grep -E "eviction|pressure|reclaim"
# → I0904 17:00:01 eviction_manager.go:340] Eviction manager: disk usage above threshold
# → I0904 17:00:15 eviction_manager.go:340] Eviction manager: memory usage above threshold
# → I0904 17:00:30 eviction_manager.go:400] Attempting to reclaim ephemeral-storage

# 3. Проверка PSI по всем ресурсам
cat /proc/pressure/memory
# → some avg10=20.50 avg60=12.30 avg300=5.60 total=23456789
# → full avg10=8.50  avg60=4.20  avg300=1.80 total=9876543

cat /proc/pressure/io
# → some avg10=15.20 avg60=8.10 avg300=3.20 total=15678901
# → full avg10=5.30  avg60=2.80 avg300=1.10 total=5432109

cat /proc/pressure/cpu
# → some avg10=25.80 avg60=15.40 avg300=7.60 total=34567890
```

**Решение** (приоритезированный порядок):
```bash
# 1. Сначала очистите disk (корневая причина)
sudo crictl rmi --prune
sudo find /var/log/pods/ -name "*.log" -mtime +1 -delete

# 2. Затем освободите память
sync && echo 3 > /proc/sys/vm/drop_caches

# 3. Проверка восстановления Conditions
kubectl describe node <node-name> | grep -A 3 Conditions
# → MemoryPressure   False   KubeletHasNoMemoryPressure
# → DiskPressure     False   KubeletHasNoDiskPressure
```

---

### Сценарий 5: Oscillation (осцилляция) между Pressure и нормой

**Симптомы**: Узел периодически переходит в `MemoryPressure=True` → `False` → `True` через каждые несколько минут. Поды постоянно выселяются и пересоздаются.

**Причина**: Порог `evictionHard:memory.available` настроен слишком близко к фактическому использованию памяти. `memory.available` осциллирует вокруг порога.

**Диагностика**:
```bash
# 1. Проверка频率 изменения Conditions
kubectl get node <node-name> -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.lastTransitionTime}{"\n"}{end}'
# → MemoryPressure	True	2026-09-04T17:30:00Z
# → MemoryPressure	False	2026-09-04T17:35:00Z
# → MemoryPressure	True	2026-09-04T17:40:00Z   ← каждые 5 минут

# 2. Проверка evictionHard
cat /var/lib/kubelet/config.yaml | grep -A 5 "evictionHard"
# → evictionHard:
# →   memory.available: "200Mi"   ← слишком мало для 16GB узла

# 3. Проверка текущего usage относительно порога
kubectl get --raw "/api/v1/nodes/<node-name>/proxy/stats/summary" | jq '.node.memory'
# → {"availableBytes":262144000,"capacityBytes":17179869184,...}
# → available: 250MB, threshold: 200MB → осцилляция
```

**Решение**:
```bash
# 1. Увеличьте evictionHard (добавьте запас)
# В /var/lib/kubelet/config.yaml:
# evictionHard:
#   memory.available: "500Mi"   # было 200Mi, стало 500Mi

# 2. Перезапустите kubelet
sudo systemctl restart kubelet

# 3. Проверка, что осцилляция прекратилась
kubectl get node <node-name> -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.lastTransitionTime}{"\n"}{end}'
# → MemoryPressure	False	2026-09-04T17:45:00Z   ← стабильно False
```

---

### Сценарий 6: Image GC и DiskPressure (очистка образов)

**Симптомы**: `DiskPressure=True` из-за переполнения `imagefs`. kubelet не успевает очищать неиспользуемые образы.

**Диагностика**:
```bash
# 1. Проверка usage imagefs
df -h /var/lib/containerd
# → /dev/sdb1  100G   95G    5G  95% /var/lib/containerd

# 2. Проверка порогов Image GC
cat /var/lib/kubelet/config.yaml | grep -E "imageGC"
# → imageGCHighThresholdPercent: 85
# → imageGCLowThresholdPercent: 80

# 3. Проверка текущего использования образов
sudo crictl images | wc -l
# → 450   ← много образов

# 4. Проверка логов Image GC
journalctl -u kubelet --since "1 hour ago" --no-pager | grep -i "image gc"
# → I0904 17:30:00 image_gc_manager.go:324] Image garbage collection removed 15 images

# 5. Проверка containerd content store
sudo du -sh /var/lib/containerd/io.containerd.content.v1.content/
# → 35G     /var/lib/containerd/io.containerd.content.v1.content/
```

**Решение**:
```bash
# 1. Ручная очистка неиспользуемых образов
sudo crictl rmi --prune

# 2. Настройка более агрессивных порогов Image GC
# В /var/lib/kubelet/config.yaml:
# imageGCHighThresholdPercent: 75
# imageGCLowThresholdPercent: 65

# 3. Настройка containerd GC (если нужно)
# В /etc/containerd/config.toml:
# [plugins."io.containerd.grpc.v1.cri".containerd]
#   discard_unpacked_layers = true

# 4. Проверка
df -h /var/lib/containerd
# → /dev/sdb1  100G   60G   40G  60% /var/lib/containerd  ← норма
```

Подробнее: **[Проблемы рантайма: Image GC](./runtime_issues.md#сценарий-8-image-garbage-collection-и-diskpressure)**.

---

### Сценарий 7: PIDPressure + MemoryPressure (fork-бомба с утечкой памяти)

**Симптомы**: Одновременно `PIDPressure=True` и `MemoryPressure=True`. Много процессов, каждый потребляет память.

**Диагностика**:
```bash
# 1. Проверка Conditions
kubectl describe node <node-name> | grep -A 5 Conditions
# → MemoryPressure   True    ...
# → PIDPressure      True    ...

# 2. Подсчет процессов по UID (кто fork-нулся)
ps -eo pid,uid,nlwp,comm --sort=-nlwp | head -11
# → PID  UID  NLWP COMMAND
# → 1234 1000 8000 bash -c "while true; do sleep 1 & done"  ← fork-бомба

# 3. Проверка, какой под создал fork-бомбу
for cg in /sys/fs/cgroup/kubepods.slice/kubepods-pod*.slice; do
  procs=$(cat $cg/cgroup.procs 2>/dev/null | wc -l)
  if [ "$procs" -gt 1000 ]; then
    echo "$procs processes in $cg"
  fi
done
# → 8500 processes in /sys/fs/cgroup/kubepods.slice/kubepods-pod<uid>.slice

# 4. Проверка памяти по подам
kubectl top pods --field-selector spec.nodeName=<node-name> --sort-by=memory | head -5
# → NAME        CPU    MEMORY
# → leaky-app   1200m  12Gi   ← аномально
```

**Решение**:
```bash
# 1. Убить fork-бомбу (найти PID-потомка и убить группу)
FG_PID=$(ps -eo pid,ppid,comm | grep "bash.*while" | awk '{print $1}' | head -1)
sudo kill -- -$FG_PID

# 2. Удалить проблемный под
kubectl delete pod <problematic-pod> --grace-period=0 --force

# 3. Проверка восстановления
ps -eLf | wc -l
# → 15000   ← норма
free -h
# → Mem:   15Gi   6Gi   8Gi   ← норма
```

---

### Сценарий 8: PIDPressure из-за僵尸ных (zombie) процессов

**Симптомы**: `PIDPressure=True`, но `ps -eLf | wc -l` показывает нормальное количество процессов. Ошибка `fork: Cannot allocate memory`.

**Причина**: Zombie-процессы (статус `Z`) не потребляют RAM, но занимают PID. Если PID-пространство исчерпано zombie-процессами, новые процессы не могут быть созданы.

**Диагностика**:
```bash
# 1. Подсчет zombie-процессов
ps -eo stat | grep -c Z
# → 31000   ← 31000 zombies из 32768 лимита

# 2. Поиск родительских процессов zombie
ps -eo pid,ppid,stat,comm | awk '$3=="Z"' | head -10
# → PID  PPID STAT COMMAND
# → 1234 1    Z    containerd-shim
# → 1235 1    Z    containerd-shim

# 3. Проверка, что родитель zombie — системный процесс
ps -p 1 -o comm=
# → systemd   ← если systemd не подбирает zombies — проблема в systemd

# 4. Проверка zombie в контейнерах
for cid in $(crictl ps -q); do
  zombies=$(crictl exec $cid sh -c "ps -eo stat | grep -c Z" 2>/dev/null)
  echo "$zombies zombies in container $cid"
done
```

**Решение**:
```bash
# 1. Убить родительский процесс zombie (если это не systemd)
sudo kill -9 <parent-pid>

# 2. Перезапустить systemd (если zombies не подбираются)
sudo systemctl daemon-reexec

# 3. Перезапустить containerd (если zombies в контейнерах)
sudo systemctl restart containerd

# 4. Если zombies в контейнерах — перезапустить под
kubectl delete pod <pod-name> --grace-period=0 --force

# 5. Проверка
ps -eo stat | grep -c Z
# → 15   ← норма
```

## Мониторинг и алертинг

### Метрики давления ресурсов (Prometheus)

| Метрика | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `node_memory_MemAvailable_bytes` | Доступная память на узле | < 500MB持续 |
| `node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100` | Процент доступной памяти | < 10%持续 |
| `node_filesystem_avail_bytes` | Доступное место на корневом разделе | < 10%持续 |
| `node_filesystem_files_free` | Свободные inodes | < 5%持续 |
| `node_procs_running` | Количество runnable-процессов | > 3000持续 |
| `node_procs_blocked` | Количество заблокированных процессов | > 100持续 |
| `node_pressure_memory_waiting_seconds_total` | PSI: суммарное время ожидания памяти | rate > 10持续 5 минут |
| `node_pressure_io_waiting_seconds_total` | PSI: суммарное время ожидания I/O | rate > 20持续 5 минут |
| `kubelet_evictions` | Количество eviction-событий по kubelet | > 0持续 5 минут |
| `kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes * 100` | Использование эфемерного хранилища | > 85%持续 |
| `kube_node_status_condition{condition="MemoryPressure",status="true"}` | Condition MemoryPressure=True у узла | == 1持续 2 минуты |
| `kube_node_status_condition{condition="DiskPressure",status="true"}` | Condition DiskPressure=True у узла | == 1持续 2 минуты |
| `kube_node_status_condition{condition="PIDPressure",status="true"}` | Condition PIDPressure=True у узла | == 1持续 2 минуты |

### Примеры алертов (PrometheusRule)

```yaml
groups:
  - name: resource-pressure
    rules:
      # MemoryPressure
      - alert: NodeMemoryPressure
        expr: kube_node_status_condition{condition="MemoryPressure", status="true"} == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.node }} в состоянии MemoryPressure"
          description: "kubelet обнаружил критическую нехватку RAM"

      # DiskPressure
      - alert: NodeDiskPressure
        expr: kube_node_status_condition{condition="DiskPressure", status="true"} == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.node }} в состоянии DiskPressure"
          description: "kubelet обнаружил критическую нехватку дискового пространства"

      # PIDPressure
      - alert: NodePIDPressure
        expr: kube_node_status_condition{condition="PIDPressure", status="true"} == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.node }} в состоянии PIDPressure"
          description: "kubelet обнаружил исчерпание лимита PID"

      # Low memory (раннее предупреждение)
      - alert: NodeMemoryLow
        expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100 < 15
        for: 10m
        labels:
          severity: info
        annotations:
          summary: "Узел {{ $labels.instance }}: доступно < 15% памяти"
          description: "При текущей динамике возможно наступление MemoryPressure"

      # PSI memory pressure
      - alert: NodePSIMemoryPressure
        expr: rate(node_pressure_memory_waiting_seconds_total{state="full"}[5m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.instance }}: PSI memory pressure"
          description: "Процессы теряют время из-за нехватки памяти (full avg10 > 5%)"

      # High disk usage
      - alert: NodeDiskUsageHigh
        expr: (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes) * 100 > 90
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.instance }}: диск заполнен > 90%"
          description: "Возможно наступление DiskPressure"

      # Eviction events
      - alert: KubeletEvictionsHigh
        expr: increase(kubelet_evictions[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Kubelet на {{ $labels.instance }} выселяет поды"
          description: "Обнаружены eviction-события из-за нехватки ресурсов"

      # Low available inodes
      - alert: NodeInodesLow
        expr: node_filesystem_files_free / node_filesystem_files * 100 < 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.instance }}: мало свободных inodes"
          description: "Свободно < 5% inodes, возможен DiskPressure"
```

## Рекомендации по мониторингу

1. **Мониторьте PSI** — PSI показывает реальную потерю производительности, тогда как `memory.available` — только мгновенный объем. Рекомендуется настраивать алерты на обе метрики.
2. **Отслеживание Oscillation** — если `MemoryPressure` переключается чаще раза в 10 минут, это признак слишком жестких порогов `evictionHard`.
3. **Кросс-доменные симптомы** — `DiskPressure` часто вызывает `MemoryPressure` (через swap) и `PIDPressure` (через zombie-процессы). Ищите корневую причину.
4. **Inodes** — мониторьте `df -i` отдельно от `df -h`. Millions мелких файлов (логи, tmp-файлы) могут исчерпать inodes при наличии свободных гигабайт.
5. **Image GC** — его ошибки приводят к `DiskPressure`, который приводит к `MemoryPressure`. Каскадная деградация требует приоритизированного подхода к очистке.

## Дополнительная информация

### Основные утилиты отладки

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `free -h` | Использование памяти (total/used/free/buff/cache/available) | `free -h \| grep Mem` |
| `vmstat 1 3` | Детальная статистика памяти (si/so — swap-in/out) | `vmstat 1 3` |
| `cat /proc/pressure/memory` | PSI: давление на память | `cat /proc/pressure/memory` |
| `cat /proc/pressure/io` | PSI: давление на I/O | `cat /proc/pressure/io` |
| `cat /proc/pressure/cpu` | PSI: давление на CPU | `cat /proc/pressure/cpu` |
| `ps -eLf \| wc -l` | Общее количество процессов (PID usage) | `ps -eLf \| wc -l` |
| `ps -eo stat \| grep -c Z` | Количество zombie-процессов | `ps -eo stat \| grep -c Z` |
| `du --inodes -xS /var/lib/kubelet` | Поиск потребителей inodes | `du --inodes -xS /var/lib/kubelet \| sort -rh \| head` |
| `df -h /var/lib/kubelet` | Использование nodefs | `df -h /var/lib/kubelet` |
| `df -i /var/lib/kubelet` | Использование inodes | `df -i /var/lib/kubelet` |
| `iostat -x 1 3` | Дисковое I/O (для выявления I/O starvation) | `iostat -x 1 3` |
| `kubectl describe node <name>` | Conditions узла | `kubectl describe node node-1 \| grep -A 5 Conditions` |
| `kubectl get --raw "/api/v1/nodes/<name>/proxy/stats/summary"` | Статистика ресурсов узла (JSON) | jq: `jq '.node.memory.availableBytes'` |
| `crictl stats` | Потребление ресурсов контейнерами | `sudo crictl stats` |
| `sysctl kernel.pid_max` | Лимит PID на узле | `sysctl kernel.pid_max` |

### Формула Node Allocatable (расширенная)

```
Allocatable = Capacity
             - kube-reserved      (kubelet, container runtime, system services)
             - system-reserved    (sshd, journald, systemd, kernel threads)
             - eviction-hard      (запас перед началом выселения)
```

**Пример для узла с 16GB RAM и 8 CPU:**
```yaml
# Типичная конфигурация для продакшена
kubeReserved:
  cpu: "500m"
  memory: "1Gi"
  ephemeral-storage: "1Gi"
systemReserved:
  cpu: "500m"
  memory: "1Gi"
  ephemeral-storage: "1Gi"
evictionHard:
  memory.available: "500Mi"
  nodefs.available: "10%"
  imagefs.available: "15%"

# Результат:
# Allocatable CPU = 8 - 0.5 - 0.5 = 7 cores
# Allocatable Memory = 16Gi - 1Gi - 1Gi - 0.5Gi = 13.5Gi
```

Подробнее: [Настройка Kubelet: Node Allocatable](../../../Concepts/kubelet.md#управление-ресурсами-и-node-allocatable).

### Связанные разделы

- **[Выселение по памяти](../PodEvicted/memory_eviction.md)** — детали MemoryPressure: WSS, PSI, eviction manager, PriorityQueue.
- **[Выселение по диску](../PodEvicted/disk_eviction.md)** — детали DiskPressure: nodefs/imagefs, GC, container log rotation.
- **[QoS и выселение](../PodEvicted/qos_and_eviction.md)** — PriorityQueue, oom_score_adj, порядок выселения по QoS.
- **[Профилактика выселения](../PodEvicted/prevention.md)** — kube-reserved, system-reserved, Best Practices.
- **[Diagnostics узла](./diagnostics.md)** — системные утилиты для анализа ресурсов.
- **[Настройка Kubelet](../../../Concepts/kubelet.md)** — детальный разбор YAML-конфигурации.
- **[Taints и выселение](./taints_and_eviction.md)** — taint-based eviction, автоматическое наложение taints.
- **[PSI: статистика давления](../../../Linux/Core/kernel/psi.md)** — детали PSI, конфигурация, пороги.
- **[Тюнинг ядра](./kernel_tuning.md)** — sysctl параметры, влияющие на ресурсы (vm.max_map_count, pid_max).
- **[SELinux и AppArmor](./security_profiles.md)** — MAC-политики могут блокировать диагностику ресурсов.
