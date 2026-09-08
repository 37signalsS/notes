# Недоступность узла: Проблемы среды выполнения (Runtime)

Среда выполнения контейнеров (Container Runtime) — это фундамент, на котором запускаются рабочие нагрузки. Сбои на этом уровне приводят к потере контроля над контейнерами, невозможности запуска новых подов и переходу узла в статус `NotReady` или `Unknown`. Данный файл является **SSoT для диагностики проблем рантайма, приводящих к недоступности узла** — общая концепция CRI/OCI описана в [Container Runtime: Концепции](../../../Concepts/container_runtime.md), проблемы kubelet — в [Проблемы Kubelet](./kubelet_issues.md), давление ресурсов — в [Давление ресурсов](./resource_pressure.md), диагностика узла — в [Диагностика узла](./diagnostics.md).

## Основные определения

**Среда выполнения контейнеров (Container Runtime)** — низкоуровневое ПО, отвечающее за запуск и управление жизненным циклом контейнеров через взаимодействие с ядром ОС (`namespaces`, `cgroups`). Kubernetes работает с ними через стандарт **CRI (Container Runtime Interface)**.

**Сбой CRI (CRI Failure)** — состояние, при котором агент `kubelet` теряет связь со службой рантайма (через gRPC сокет) или рантайм перестаёт отвечать на запросы в течение установленного времени (тайм-аут PLEG).

**PLEG (Pod Lifecycle Event Generator)** — механизм внутри `kubelet`, который опрашивает рантайм о состоянии контейнеров. Если рантайм «зависает», в логах появляется ошибка `PLEG is unhealthy`, и узел помечается как `NotReady`. Подробный разбор PLEG: [Диагностика узла](./diagnostics.md#механизм-pleg-pod-lifecycle-event-generator).

**Сnapshotter** — подсистема containerd для управления слоями файловой системы образов (overlayfs, btrfs, zfs). Сбои snapshotter приводят к невозможности распаковки образов и запуска контейнеров.

**Container GC (Garbage Collection)** — автоматическая очистка завершенных контейнеров и неиспользуемых образов. Управляется kubelet (`containerGCHighThresholdPercent`, `imageGCHighThresholdPercent`) и самим рантаймом (`discard_unpacked_layers`, `max_total_backups`).

### Классификация сбоев рантайма

| Категория | Симптомы | Типичные причины | Критичность |
| :--- | :--- | :--- | :--- |
| **CRI-сокет** | `NotReady`, `connection refused`, `context deadline exceeded` | containerd/CRI-O упал, сокет поврежден, OOM рантайма | Critical |
| **Cgroups** | `ContainerCreating`, `OCI runtime create failed` | Несоответствие SystemdCgroup, cgroup v1/v2 | Critical |
| **Sandbox/pause** | `ContainerCreating`, `Failed to pull image pause` | Нет образа pause, неверная версия, сеть недоступна | High |
| **PLEG** | `PLEG is unhealthy`, поды в `Unknown` | Рантайм завис, перегрузка I/O, zombie-контейнеры | Critical |
| **Low-Level Runtime** | Процессы runc в D-state, crictl не отвечает | NFS-зависания, блокировка I/O, повреждение rootfs | High |
| **Snapshotter** | `failed to get parent`, `unable to unpack` | Поврежденные слои, нехватка места, overlayfs ошибки | High |
| **Container Logs** | `kubectl logs` пустой, DiskPressure от логов | Ротация не настроена, max size превышен, journald满 | Medium |
| **Image GC** | `DiskPressure`, `ImageGCBackOff` | Пороги GC настроены неверно,慢速 диск, insufficient space | High |
| **Конфигурация** | `Failed to run kubelet`, `misconfiguration` | Неверный config.toml, sandbox_image, registry mirrors | Critical |

## Основные концепции

### Современная архитектура CRI

С версии 1.24 Kubernetes использует прямые реализации CRI без прослойки `dockershim`:

| Компонент | Роль | Основные инструменты |
| :--- | :--- | :--- |
| **High-Level Runtime** | Управление образами, сетью и песочницами (`containerd`, `CRI-O`). | `crictl`, `nerdctl` |
| **Low-Level Runtime** | Непосредственное создание процессов контейнеров (`runc`, `crun`). | `runc list`, `ctr` |
| **OCI Spec** | Стандарт конфигурации и файловой системы контейнера. | — |

### Зависимости рантайма от системных компонентов

| Зависимость | Проверка | Последствие сбоя |
| :--- | :--- | :--- |
| **systemd** | `systemctl status containerd` | Containerd не запущен, сокет недоступен |
| **cgroup driver** | `grep SystemdCgroup /etc/containerd/config.toml` | `OCI runtime create failed`, поды не запускаются |
| **Диск (/var/lib/containerd)** | `df -h /var/lib/containerd` | Snapshotter не работает, образы не распаковываются |
| **Сеть** | `curl -s http://127.0.0.1:38080/healthz` | Образы не скачиваются, sandbox/pause недоступен |
| **Сетевые модули ядра** | `lsmod \| grep -E "br_netfilter\|overlay"` | CNI не функционирует, поды без сети |
| **pid_max** | `cat /proc/sys/kernel/pid_max` | Исчерпание PID, новые контейнеры не создаются |
| **file descriptors** | `cat /proc/sys/fs/file-nr` | Исчерпание FD, рантайм зависает |

### Критические точки отказа рантайма

1.  **Несоответствие драйвера Cgroups**: Если `kubelet` использует `systemd`, а рантайм — `cgroupfs` (или наоборот), запуск контейнеров завершится ошибкой на этапе создания Task. Подробнее: [Проблемы Kubelet: Cgroup Driver](./kubelet_issues.md#сценарий-1-несоответствие-драйвера-cgroup-systemd-vs-cgroupfs).
2.  **Зависание I/O**: Рантайм часто блокируется при попытке записи логов или монтирования томов, если диск системного раздела перегружен (I/O Wait). См. [Давление ресурсов](./resource_pressure.md).
3.  **Лимиты ресурсов ОС**: Исчерпание `pid_max` или файловых дескрипторов на хосте блокирует создание новых процессов внутри рантайма.
4.  **Sandbox Image (pause)**: Образ `pause` является сетевой основой каждого пода. Если он недоступен или имеет неверную версию, поды не перейдут в статус `Running`.
5.  **Snapshotter**: Повреждение overlayfs/бэкенд-файловой системы приводит к невозможности распаковки образов. Контейнеры не могут быть созданы из-за ошибок в слоях.
6.  **Container Logs**: Рантайм записывает stdout/stderr контейнеров на диск. Если диск заполнен логами, kubelet не может записывать новые, что ведет к `DiskPressure`.

## Практические сценарии

### Сценарий 1: containerd/CRI-O не отвечает (Сокет недоступен)

**Симптомы**: Узел `NotReady`, в логах `kubelet`: `failed to connect to cri: connection refused` или `context deadline exceeded`.

**Диагностика**:
```bash
# 1. Проверка статуса сервиса
systemctl status containerd
# → containerd.service - containerd container runtime
# →   Active: inactive (dead) since Thu 2026-09-04 17:30:00 UTC; 5min ago

# 2. Проверка доступности сокета через crictl
# Убедитесь, что в /etc/crictl.yaml прописан верный сокет
cat /etc/crictl.yaml
# → runtime-endpoint: unix:///run/containerd/containerd.sock
# → image-endpoint: unix:///run/containerd/containerd.sock
sudo crictl info
# → FATA[0000] connecting to runtime endpoint "unix:///run/containerd/containerd.sock": 
# →   connect error: connection refused   ← сокет недоступен

# 3. Проверка, что сокет-файл существует
ls -la /run/containerd/containerd.sock
# → srw-rw---- 1 root root 0 Sep  4 17:25:00 /run/containerd/containerd.sock
# Если файла нет → containerd не запущен

# 4. Анализ логов на предмет OOM-kill самого рантайма
journalctl -u containerd -n 100 --no-pager | grep -i "oom\|killed\|signal"
# → Sep 04 17:30:00 node-1 systemd[1]: containerd.service: Main process exited, 
# →   status=137/KILLED
# → Sep 04 17:30:00 node-1 kernel: Out of memory: Killed process 12345 (containerd)

# 5. Проверка памяти, потребляемой containerd
ps aux | grep containerd | awk '{print $6}'
# → 1234567   ← ~1.2 GB — нормально для большого кластера
# → 3456789   ← ~3.3 GB — аномально, вероятна утечка памяти

# 6. Проверка логов containerd на ошибки
journalctl -u containerd -n 50 --no-pager | grep -iE "error|fail|panic"
# → Sep 04 17:29:55 node-1 containerd[12345]: level=error msg="failed to cache image" 
# →   error="no space left on device"
```

**Решение**:
```bash
# 1. Перезапуск сервиса
sudo systemctl restart containerd
sudo systemctl status containerd
# → Active: active (running) since Thu 2026-09-04 17:35:00 UTC; 10s ago

# 2. Если containerd падает из-за OOM — увеличьте лимит памяти
# В systemd unit file (/etc/systemd/system/containerd.service.d/override.conf):
# [Service]
# MemoryLimit=4G
sudo systemctl daemon-reload && sudo systemctl restart containerd

# 3. Если падения повторяются — проверьте дисковое пространство
df -h /var/lib/containerd
# → /dev/sdb1    100G   95G    5G  95% /var/lib/containerd   ← критически мало
# Очистите образы:
sudo crictl rmi --prune

# 4. Проверьте dmesg на аппаратные ошибки
dmesg -T | grep -iE "error|fail|hardware" | tail -10
```

---

### Сценарий 2: Ошибки Cgroups v2 (SystemdCgroup)

**Симптомы**: Поды «виснут» в `ContainerCreating`. В `kubectl describe pod` ошибка: `failed to create containerd task: ... failed to create shim task: OCI runtime create failed`.

**Причина**: На современных ядрах с **cgroup v2** рантайм обязан использовать драйвер `systemd`.

**Диагностика**:
```bash
# 1. Проверка версии cgroup на узле
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs    ← cgroup v2 (systemd обязателен)
# → tmpfs        ← cgroup v1 (может быть cgroupfs)

# 2. Проверка драйвера в конфиге containerd
grep -i "SystemdCgroup" /etc/containerd/config.toml
# → SystemdCgroup = false   ← НЕПРАВИЛЬНО для cgroup v2

# 3. Проверка драйвера в конфиге kubelet
grep cgroupDriver /var/lib/kubelet/config.yaml
# → cgroupDriver: systemd

# 4. Проверка логов kubelet на ошибку несоответствия
journalctl -u kubelet -n 20 --no-pager | grep -i "cgroup\|misconfiguration"
# → F0904 17:30:00.123456 kubelet.go:1405] Failed to run kubelet: 
# →   misconfiguration: kubelet cgroup driver: "systemd" is different from 
# →   container runtime cgroup driver: "cgroupfs"
```

**Решение для containerd**:
Отредактируйте `/etc/containerd/config.toml`:
```toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  SystemdCgroup = true
```
После правки обязателен перезапуск: `sudo systemctl restart containerd`.

---

### Сценарий 3: Проблемы с Sandbox-образом (pause)

**Симптомы**: Поды застряли в `ContainerCreating`. Лог `kubelet` сообщает: `Failed to pull image "registry.k8s.io/pause:3.10"`.

**Диагностика**:
```bash
# 1. Проверка настроенного пути в конфиге containerd
containerd config dump | grep sandbox_image
# → sandbox_image = "registry.k8s.io/pause:3.10"

# 2. Проверка доступности образа pause
sudo crictl images | grep pause
# → IMAGE                 TAG                 IMAGE ID            SIZE
# Если нет → образ не скачан

# 3. Попытка скачать образ вручную
sudo crictl pull registry.k8s.io/pause:3.10
# → FATA[0000] pulling image: rpc error: code = NotFound desc = failed to pull and unpack image
# → Если 404 → образ недоступен в registry

# 4. Проверка сети с узла
curl -s -o /dev/null -w "%{http_code}" https://registry.k8s.io/v2/
# → 200   ← registry доступен
# → 000   ← нет сети

# 5. Проверка DNS с узла
nslookup registry.k8s.io
# → Server:    10.233.0.10
# → Address:   10.233.0.10
# → Name:      registry.k8s.io
# → Address:   146.75.28.170
```

**Решение**:
```bash
# 1. В изолированных сетях (Air-gapped) загрузите образ вручную:
sudo crictl pull my-local-registry/pause:3.10

# 2. Обновите sandbox_image в config.toml:
# [plugins."io.containerd.grpc.v1.cri"]
#   sandbox_image = "my-local-registry/pause:3.10"

# 3. Перезапустите containerd:
sudo systemctl restart containerd

# 4. Проверка, что поды теперь создают sandbox:
sudo crictl pods | grep "my-pod"
# → POD ID              CREATED             STATE               NAME
# → abc123def456         30 seconds ago     Ready               my-pod
```

---

### Сценарий 4: Зависание PLEG из-за "зомби" контейнеров

**Симптомы**: Узел периодически переходит в `NotReady`. В логах `kubelet`: `PLEG is unhealthy`. `crictl ps` показывает огромное количество контейнеров в статусе `Exited`. Подробный разбор PLEG: [Проблемы Kubelet: PLEG](./kubelet_issues.md#сценарий-4-ошибки-pleg-pleg-is-unhealthy).

**Диагностика**:
```bash
# 1. Подсчет контейнеров по статусам
sudo crictl ps -a --output json | jq -r '.containers[].state' | sort | uniq -c | sort -rn
# → 150 Running
# → 250 Exited        ← много завершенных контейнеров

# 2. Проверка самых старых завершенных контейнеров
sudo crictl ps -a --output json | jq -r '.containers[] | select(.state=="Exited") | "\(.id[0:12]) \(.image.image) \(.created)"' | sort -k3 | head -10
# → abc123def456 nginx:1.27 2026-09-01T10:00:00Z   ← 3 дня назад

# 3. Проверка времени ответа crictl
time sudo crictl pods
# → real    0m0.123s   ← норма (< 1 сек)
# → real    0m45.678s  ← рантайм зависает

# 4. Проверка I/O Wait
iostat -x 1 3
# → Device   r/s   w/s   await   svctm   %util
# → sda      5.00  350.00  250.00  2.80    100.00  ← 100% utilization
```

**Решение**:
```bash
# 1. Удалить все "зависшие" поды (песочницы) — безопасно для активных подов
sudo crictl rmp -fa

# 2. Удалить все неиспользуемые образы
sudo crictl rmi --prune

# 3. Удалить конкретные завершенные контейнеры
sudo crictl rm $(sudo crictl ps -a -q --state exited | head -50)

# 4. Перезапуск containerd (если crictl зависает)
sudo systemctl restart containerd

# 5. Проверка восстановления
journalctl -u kubelet --since "5 min ago" --no-pager | grep -E "PLEG|ready"
# → I0904 17:40:01.654321 kubelet.go:2234] "PLEG is healthy"
```

---

### Сценарий 5: Ошибки на уровне Low-Level Runtime (runc)

**Симптомы**: Процессы `runc` висят в состоянии `D` (Uninterruptible sleep). `crictl` команды не возвращают результат.

**Диагностика**:
```bash
# 1. Поиск зависших процессов runc
ps aux | grep runc | grep -v grep
# → root  12345  0.0  0.0  123456  7890 ?    D    17:30   0:05 runc containerinit-12345
# → root  12346  0.0  0.0  123456  7891 ?    D    17:31   0:03 runc exec 12345

# 2. Проверка PID-пространства
ls /proc/*/comm 2>/dev/null | xargs grep -l "runc" 2>/dev/null | wc -l
# → 15   ← количество runc-процессов

# 3. Проверка сообщений ядра о блокировках
dmesg -T | grep -i "blocked for more than 120 seconds" | tail -5
# → [Thu Sep  4 17:30:00 2026] task runc:12345 blocked for more than 120 seconds.
# → [Thu Sep  4 17:30:00 2026] "echo 0 > /proc/sys/kernel/hung_task_timeout_secs" disables this message.

# 4. Проверка, что блокирует runc (Strace)
strace -p <runc-PID> -e trace=network,write -f
# → futex(0x..., FUTEX_WAIT, 0, NULL) = ?   ← блокировка на futex (файл/сеть)

# 5. Проверка файловой системы, где лежат rootfs контейнеров
mount | grep "containerd\|overlay"
# → /dev/sdb1 on /var/lib/containerd type ext4 (rw,relatime)
# Если overlayfs → проверьте:
dmesg | grep -i "overlay\|ext4\|xfs" | tail -5
```

**Решение**:
```bash
# 1. Если runc завис из-за NFS — восстановите NFS-сервер или размонтируйте:
sudo umount -f /mnt/nfs-share 2>/dev/null

# 2. Если runc завис из-за Ext4/xfs — проверьте fsck:
sudo umount /var/lib/containerd
sudo fsck -y /dev/sdb1

# 3. Принудительное завершение runc-процессов (крайний случай):
sudo kill -9 <runc-PID>

# 4. Перезапуск containerd для восстановления:
sudo systemctl restart containerd
```

---

### Сценарий 6: Повреждение Snapshotter (overlayfs)

**Симптомы**: Ошибки при распаковке образов: `failed to get parent`, `unable to unpack image`, `no such file or directory` при запуске контейнера.

**Причина**: Повреждение overlayfs-слоев, нехватка места на диске, конфликт между GC рантайма и GC kubelet.

**Диагностика**:
```bash
# 1. Проверка бэкенда snapshotter
containerd config dump | grep -A 5 "snapshotter"
# → [plugins."io.containerd.grpc.v1.cri".containerd]
# →   snapshotter = "overlayfs"

# 2. Проверка overlayfs-монтирования
mount | grep overlay
# → overlay on /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/123/fs 
# →   type overlay (rw,relatime,lowerdir=...,upperdir=...,workdir=...)

# 3. Проверка дискового пространства
df -h /var/lib/containerd
# → /dev/sdb1    100G   98G    2G  98% /var/lib/containerd   ← мало места

# 4. Проверка количества снапшотов
ls -d /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/*/ | wc -l
# → 1500   ← много снапшотов

# 5. Проверка ошибок в логах containerd
journalctl -u containerd -n 100 --no-pager | grep -iE "snapshot|unpack|layer"
# → level=error msg="failed to unpack image" error="no space left on device"
```

**Решение**:
```bash
# 1. Очистка неиспользуемых образов (освобождает слои):
sudo crictl rmi --prune

# 2. Очистка конкретного образа:
sudo crictl rmi <image-id>

# 3. Если overlayfs поврежден — пересоздайте снапшоттер:
# (осторожно: удалит все контейнеры на узле)
sudo systemctl stop containerd
sudo rm -rf /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/*
sudo systemctl start containerd

# 4. Проверка, что containerd восстановился:
sudo crictl info | grep -i "snapshotter"
# → "snapshotter": "overlayfs"
```

---

### Сценарий 7: Проблемы с контейнерными логами

**Симптомы**: `kubectl logs <pod>` возвращает пустой вывод. DiskPressure из-за роста лог-файлов. kubelet не может записать stdout/stderr контейнера.

**Механизм**: Контейнеры записывают stdout/stderr в лог-файлы на диске (обычно `/var/log/pods/` или `/var/lib/containerd/io.containerd.log.v1.cri/`). kubelet выполняет ротацию по параметрам `containerLogMaxSize` и `containerLogMaxFiles`.

**Диагностика**:
```bash
# 1. Проверка размера лог-файлов пода
find /var/log/pods/ -name "*.log" -exec du -sh {} + 2>/dev/null | sort -rh | head -10
# → 5.2G   /var/log/pods/kube-system_coredns-abc123/coredns/0.log
# → 1.8G   /var/log/pods/my-ns_my-pod/abc123/container.log

# 2. Проверка настроек ротации в kubelet
grep -E "containerLog" /var/lib/kubelet/config.yaml
# → containerLogMaxSize: "10Mi"        ← слишком мало для продакшена
# → containerLogMaxFiles: 3

# 3. Проверка логов containerd о переполнении
journalctl -u containerd -n 50 --no-pager | grep -i "log\|write"
# → level=error msg="failed to write log" error="no space left on device"

# 4. Проверка текущего использования диска логами
du -sh /var/log/pods/ 2>/dev/null
# → 25G     /var/log/pods/   ← много

# 5. Проверка CRI log format
containerd config dump | grep -i "log"
# → [plugins."io.containerd.grpc.v1.cri".containerd.runc.options]
# →   Sysctls = {}
# → [plugins."io.containerd.grpc.v1.cri".cni]
```

**Решение**:
```bash
# 1. Ручная очистка старых лог-файлов:
sudo find /var/log/pods/ -name "*.log" -mtime +7 -delete

# 2. Настройка более агрессивной ротации (в /var/lib/kubelet/config.yaml):
# containerLogMaxSize: "50Mi"
# containerLogMaxFiles: 5

# 3. Применение настроек:
sudo systemctl restart kubelet

# 4. Проверка DiskPressure после очистки:
kubectl describe node <node-name> | grep -A 3 Conditions
# →   DiskPressure     False   KubeletHasNoDiskPressure
```

---

### Сценарий 8: Image Garbage Collection и DiskPressure

**Симптомы**: Узел в `DiskPressure`, поды выселяются из-за нехватки места на диске. kubelet не успевает очищать неиспользуемые образы. Подробнее: [Проблемы Kubelet: Image GC](./kubelet_issues.md#сценарий-7-image-garbage-collection-и-diskpressure).

**Дополнительная диагностика (специфичная для рантайма)**:
```bash
# 1. Проверка usage в containerd
sudo ctr -n k8s.io images ls -q | wc -l
# → 450   ← количество образов в containerd

# 2. Проверка слоёв snapshotter
sudo ctr -n k8s.io snapshots ls | wc -l
# → 1200   ← количество снапшотов

# 3. Проверка дискового использования по компонентам
sudo du -sh /var/lib/containerd/io.containerd.content.v1.content/ 2>/dev/null
# → 35G     /var/lib/containerd/io.containerd.content.v1.content/
sudo du -sh /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/ 2>/dev/null
# → 60G     /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/

# 4. Проверка логов Image GC в kubelet
journalctl -u kubelet --since "1 hour ago" --no-pager | grep -i "image gc"
# → I0904 17:30:00.123456 image_gc_manager.go:324] 
# →   Image garbage collection removed 15 images, reclaimed 2345MB space

# 5. Проверка метрик containerd (если включен MetricsPlugin)
curl -s http://localhost:1338/v1/metrics | jq '.image_pulls'
```

**Решение**:
```bash
# 1. Ручная очистка неиспользуемых образов:
sudo crictl rmi --prune

# 2. Настройка более низких порогов Image GC (в /var/lib/kubelet/config.yaml):
# imageGCHighThresholdPercent: 75
# imageGCLowThresholdPercent: 65

# 3. Настройка containerd GC (если нужно более агрессивное удаление):
# В /etc/containerd/config.toml:
# [plugins."io.containerd.grpc.v1.cri".containerd]
#   discard_unpacked_layers = true
#   max_concurrent_downloads = 10
#   max_total_backups = 3

# 4. Проверка DiskPressure после очистки:
kubectl describe node <node-name> | grep -A 3 Conditions
# →   DiskPressure     False   KubeletHasNoDiskPressure
```

---

### Сценарий 9: Конфигурация registry mirrors и таймауты pull

**Симптомы**: Образы скачиваются очень долго или не скачиваются вообще. `ImagePullBackOff` на нескольких узлах. Таймауты `context deadline exceeded` при pull.

**Причина**: Неверно настроенные mirror registries, таймауты подключения, TLS-сертификаты.

**Диагностика**:
```bash
# 1. Проверка конфигурации registry mirrors
containerd config dump | grep -A 10 "config_path\|mirrors"
# → [plugins."io.containerd.grpc.v1.cri".registry]
# →   config_path = "/etc/containerd/certs.d"
# → [plugins."io.containerd.grpc.v1.cri".registry.mirrors]
# →   [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
# →     endpoint = ["https://mirror.registry.local","https://docker.io"]

# 2. Проверка доступности mirror registry
curl -s -o /dev/null -w "%{http_code}" https://mirror.registry.local/v2/
# → 200   ← mirror доступен
# → 000   ← mirror недоступен

# 3. Проверка TLS-сертификатов registry
openssl s_client -connect mirror.registry.local:443 -showcerts < /dev/null 2>/dev/null | head -5
# → depth=1 CN = mirror.registry.local

# 4. Проверка времени pull (ускорение = mirror работает)
time sudo crictl pull docker.io/library/nginx:1.27
# → real    0m3.456s   ← норма через mirror
# → real    2m15.000s  ← таймаут или медленный mirror

# 5. Проверка сетевых ограничений (firewall)
iptables -L -n | grep -i "443\|80\|registry"
```

**Решение**:
```bash
# 1. Настройка mirrors через config_path (рекомендуется):
# Создайте директорию:
sudo mkdir -p /etc/containerd/certs.d/docker.io

# Создайте файл /etc/containerd/certs.d/docker.io/hosts.toml:
# server = "https://docker.io"
# [host."https://mirror.registry.local"]
#   capabilities = ["pull","resolve"]
#   skip_verify = false

# 2. Перезапустите containerd:
sudo systemctl restart containerd

# 3. Проверка pull:
sudo crictl pull docker.io/library/nginx:1.27
```

---

### Сценарий 10: Невозможность exec в контейнер (OCI runtime exec failed)

**Симптомы**: `kubectl exec -it <pod> -- /bin/sh` завершается ошибкой: `OCI runtime exec failed: exec failed: unable to start container process`.

**Причины**:
- Отсутствует executable в контейнере (`/bin/sh` не найден).
- Нет прав на выполнение (permissions).
- Контейнер завершился (state `Terminated`).
- SELinux/AppArmor блокирует exec.

**Диагностика**:
```bash
# 1. Проверка статуса контейнера
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].state}'
# → {"running":{"startedAt":"2026-09-04T17:30:00Z"}}   ← OK
# → {"terminated":{"exitCode":0}}   ← контейнер завершился

# 2. Проверка доступного shell в контейнере
kubectl exec <pod> -- ls -la /bin/sh
# → lrwxrwxrwx 1 root root 4 Mar  4 17:30 /bin/sh -> busybox
# Если нет → контейнер не содержит shell

# 3. Проверка через crictl (прямой exec через runc)
CONTAINER_ID=$(crictl ps --name <container-name> -q)
sudo crictl exec -it $CONTAINER_ID /bin/sh
# → If the error persists → проблема на уровне runc

# 4. Проверка SELinux (если включен)
getenforce
# → Enforcing
# → sudo ausearch -m avc --raw | grep exec

# 5. Проверка AppArmor
aa-status | grep container
# → containerd (256 profiles)
```

**Решение**:
```bash
# 1. Если shell отсутствует — используйте другой контейнер с shell:
kubectl debug -it <pod> --image=busybox:1.36 --target=<container-name>

# 2. Если контейнер завершился — проверьте логи:
kubectl logs <pod> --previous

# 3. Если SELinux блокирует — добавьте rule (временно):
sudo setenforce 0
# Или永久но: добавьте исключение в policy

# 4. Если AppArmor блокирует — проверьте profile:
sudo aa-status | grep -A 5 containerd
```

---

### Сценарий 11: Обновление Container Runtime на кластере

**Симптомы**: После обновления containerd/CRI-O поды на некоторых узлах не запускаются. Несовместимость версий CRI.

**Механизм**: Обновление рантайма требует последовательного обновления на каждом узле. kubelet на новой версии Kubernetes может требовать новую версию CRI.

**Диагностика**:
```bash
# 1. Проверка текущей версии containerd
containerd --version
# → containerd github.com/containerd/containerd 1.7.20 15667c6f383b6c93d5e3b0d1c...

# 2. Проверка версии Kubernetes
kubectl version --short
# → Server Version: v1.31.0

# 3. Проверка совместимости (Container Runtime Interface version)
sudo crictl info | jq '.version'
# → {"version":"0.1.0","runtime_name":"containerd","runtime_version":"1.7.20"}

# 4. Проверка, что kubelet может подключиться к CRI
sudo crictl info | jq '.config'
# → {"containerd":{"snapshotter":"overlayfs",...}}
```

**Решение**:
```bash
# 1. Обновите containerd на одном узле (drain перед обновлением):
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# 2. Обновите package:
sudo apt-get update && sudo apt-get install -y containerd.io
# или для RHEL/CentOS:
# sudo yum install -y containerd.io

# 3. Сохраните текущую конфигурацию:
sudo cp /etc/containerd/config.toml /etc/containerd/config.toml.bak

# 4. Перегенерируйте конфигурацию (если major version):
sudo containerd config default | sudo tee /etc/containerd/config.toml

# 5. Восстановите кастомные настройки из backup:
# (sandbox_image, SystemdCgroup, registry mirrors)

# 6. Перезапустите containerd:
sudo systemctl restart containerd

# 7. Верните узел в кластер:
kubectl uncordon <node-name>

# 8. Проверка:
kubectl get nodes
# → NAME     STATUS   ROLES           AGE   VERSION
# → node-1   Ready    <none>          5d    v1.31.0
```

---

### Сценарий 12: containerd и systemd: интеграция и проблемы

**Симптомы**: Containerd не перезапускается автоматически после падения. Systemd не определяет его как failed. Логи containerd не попадают в journald.

**Механизм**: Containerd работает как systemd service. Корректная интеграция включает: restart policy, watchdog, journald logging, resource limits через systemd slices.

**Диагностика**:
```bash
# 1. Проверка systemd unit file
systemctl cat containerd
# → [Unit]
# → Description=containerd container runtime
# → After=network.target systemd-networkd.service
# → 
# → [Service]
# → ExecStartPre=/sbin/modprobe overlay
# → ExecStart=/usr/bin/containerd
# → Restart=always
# → RestartSec=5
# → TimeoutSec=0
# → Delegate=yes
# → KillMode=process

# 2. Проверка watchdog (если настроен)
grep -i "watchdog" /etc/systemd/system/containerd.service.d/*.conf 2>/dev/null
# → WatchdogSec=30   ← если есть — containerd должен обновлять watchdog

# 3. Проверка логирования в journald
journalctl -u containerd -n 5 --no-pager
# → Sep 04 17:30:00 node-1 containerd[12345]: level=info msg="starting containerd"
# Если логов нет → containerd не логирует в journald

# 4. Проверка Delegate (cgroups)
systemctl show containerd | grep -i "delegate\|memory"
# → Delegate=yes
# → MemoryLimit=4294967296   ← 4GB лимит

# 5. Проверка restart count
systemctl show containerd | grep -i "nrestart\|result"
# → NRestarts=5   ← количество перезапусков
# → Result=success
```

**Решение**:
```bash
# 1. Настройка автоматического restart (если не настроен):
sudo mkdir -p /etc/systemd/system/containerd.service.d
cat <<EOF | sudo tee /etc/systemd/system/containerd.service.d/override.conf
[Service]
Restart=always
RestartSec=5
KillMode=process
Delegate=yes
MemoryLimit=4G
CPUQuota=200%
EOF

# 2. Перезагрузка systemd:
sudo systemctl daemon-reload

# 3. Настройка логирования в journald:
# В /etc/containerd/config.toml:
# [plugins."io.containerd.grpc.v1.cri"]
#   enable_cdi = false
# [plugins."io.containerd.grpc.v1.cri".containerd]
#   default_runtime_name = "runc"
#   disable_snapshot_annotations = false
#   discard_unpacked_layers = false

# 4. Проверка, что containerd запускается корректно:
sudo systemctl restart containerd
sudo systemctl status containerd
# → Active: active (running) since Thu 2026-09-04 17:35:00 UTC; 10s ago
# → Main PID: 12345 (containerd)
```

## Мониторинг и алертинг

### Метрики рантайма (Prometheus)

| Метрика | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `containerd_containers_total` | Общее количество контейнеров (все статусы) | > 2000持续 |
| `containerd_tasks_total` | Количество активных задач (procceses) | > 1000持续 |
| `containerd_image_pulls_bytes_total` | Объем скачанных образов (rate) | rate > 100MB/s持续 |
| `containerd_image_pulls_failed_total` | Неудачные pull образов | > 0持续 5 минут |
| `containerd_gc_errors_total` | Ошибки GC рантайма | > 0持续 |
| `container_tasks_ovom_total` | OOM-контейнеры (tasks killed by OOM) | > 0持续 |
| `kubelet_runtime_operations_errors_total` | Ошибки CRI-операций kubelet | > 0持续 2 минуты |
| `kubelet_pleg_relist_duration_seconds` | Время relist PLEG | p99 > 10 сек持续 |
| `kubelet_pleg_relist_work_queue_duration_seconds` | Время обработки очереди PLEG | p99 > 5 сек持续 |

### Примеры алертов (PrometheusRule)

```yaml
groups:
  - name: container-runtime-health
    rules:
      # Containerd не отвечает
      - alert: ContainerdSocketUnreachable
        expr: up{job="containerd"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Containerd не отвечает на {{ $labels.instance }}"
          description: "CRI-сокет containerd недоступен"

      # PLEG unhealthy
      - alert: PLEGUnhealthy
        expr: rate(kubelet_pleg_relist_duration_seconds_bucket[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "PLEG unhealthy на {{ $labels.instance }}"
          description: "PLEG relist duration > 10 секунд"

      # OOM-контейнеры
      - alert: ContainerOOMKilled
        expr: rate(container_tasks_ovom_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Контейнер OOM-killed на {{ $labels.instance }}"
          description: "Контейнеры убиты OOM-killer"

      # Ошибки pull образов
      - alert: ImagePullFailures
        expr: rate(containerd_image_pulls_failed_total[10m]) > 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Ошибки pull образов на {{ $labels.instance }}"
          description: "Неудачные pull образов через containerd"
```

## Рекомендации по мониторингу

1. **Мониторьте PLEG** — частые unhealthy-события указывают на проблемы с I/O или перегрузку рантайма.
2. **Отслеживание контейнеров** — рост общего количества контейнеров (Running + Exited) указывает на утечку или zombie-процессы.
3. **Image Pull Failures** — немедленный алерт при ошибках pull, особенно на критических узлах.
4. **Containerd GC** — его ошибки приводят к заполнению диска и `DiskPressure`.
5. **Дисковое пространство** — мониторьте `/var/lib/containerd` и `/var/log/pods/` отдельно.

## Дополнительная информация

### Основные утилиты отладки

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `crictl info` | Общая информация о рантайме и CNI | `sudo crictl info \| jq '.config.containerd'` |
| `crictl stats` | Потребление ресурсов контейнерами | `sudo crictl stats` |
| `crictl inspect <ID>` | Детальный JSON состояния контейнера | `sudo crictl inspect abc123` |
| `crictl ps -a` | Все контейнеры (включая завершенные) | `sudo crictl ps -a \| grep Exited` |
| `crictl pods` | Все поды (sandbox) | `sudo crictl pods` |
| `crictl images` | Образы в рантайме | `sudo crictl images \| grep pause` |
| `crictl pull` | Ручной pull образа | `sudo crictl pull nginx:1.27` |
| `containerd config dump` | Текущая конфигурация | `containerd config dump \| grep sandbox` |
| `ctr -n k8s.io images ls` | Образы в namespace k8s.io | `sudo ctr -n k8s.io images ls -q` |
| `runc list` | Активные контейнеры OCI runtime | `sudo runc list` |
| `runc state <container-id>` | Состояние конкретного контейнера | `sudo runc state abc123` |

### Смежные разделы
- **[Container Runtime: Концепции](../../../Concepts/container_runtime.md)** — общая теория, CRI/OCI, конфигурация containerd.
- **[Проблемы Kubelet](./kubelet_issues.md)** — диагностика ошибок связи `kubelet` <-> CRI, PLEG, cgroup driver, Image GC.
- **[Давление ресурсов](./resource_pressure.md)** — MemoryPressure, DiskPressure, PIDPressure, eviction thresholds.
- **[Диагностика узла](./diagnostics.md)** — общий алгоритм поиска неисправностей, CRI-сокет, ssh.
- **[Taints и выселение](./taints_and_eviction.md)** — автоматическое выселение при `NotReady`.
- **[Сетевые проблемы](./network_issues.md)** — network issues container networking (netns, veth, bridge).
