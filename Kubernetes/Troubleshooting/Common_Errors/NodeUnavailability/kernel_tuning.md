# Недоступность узла: Тюнинг ядра Linux

Некорректная конфигурация параметров ядра Linux — одна из скрытых причин деградации и недоступности узлов Kubernetes. Стандартные дистрибутивы поставляются с консервативными настройками, которые не рассчитаны на высоконагруженные контейнерные среды. Проблемы проявляются как переполнение conntrack, исчерпание PID, OOM-kill, зависания kubelet и невозможность запуска контейнеров.

## Основные определения

**Kernel Tuning** — настройка параметров ядра Linux через `sysctl`, `ulimit` и модули для оптимизации производительности и предотвращения сбоев в контейнерных средах.

**sysctl** — интерфейс для чтения и записи параметров ядра в реальном времени через `/proc/sys/`. Параметры делятся на: сеть (`net.*`), память (`vm.*`), файловые системы (`fs.*`), безопасность (`kernel.*`).

**ulimit / limits.conf** — управление ресурсными лимитами процессов: максимальное количество файловых дескрипторов (`nofile`), процессов (`nproc`), размер стека (`stack`). Влияет на kubelet, containerd и контейнеры.

**cgroup limits** — аппаратные лимиты ресурсов, управляемые ядром через cgroups v1/v2. kubelet настраивает их через `kube-reserved`, `system-reserved` и `evictionHard`.

## Основные концепции

### Критические параметры ядра для Kubernetes

| Параметр | По умолчанию | Рекомендуемое | Последствие не настройки |
| :--- | :--- | :--- | :--- |
| `net.bridge.bridge-nf-call-iptables` | 0 | 1 | CNI не видит трафик через bridge, Service IP не работает |
| `net.bridge.bridge-nf-call-ip6tables` | 0 | 1 | То же для IPv6 |
| `net.ipv4.ip_forward` | 0 | 1 | Поды не могут маршрутизировать трафик между узлами |
| `net.ipv4.conf.all.forwarding` | 0 | 1 | forwarding для всех интерфейсов |
| `net.ipv6.conf.all.forwarding` | 0 | 1 | IPv6 forwarding |
| `net.netfilter.nf_conntrack_max` | 65536 | 1048576+ | Переполнение conntrack, DROP пакетов, таймауты DNS |
| `net.netfilter.nf_conntrack_tcp_timeout_established` | 432000 (5д) | 3600 (1ч) | Медленная очистка conntrack, переполнение |
| `net.core.somaxconn` | 128 | 4096 | Очередь входящих соединений переполняется |
| `net.ipv4.tcp_max_syn_backlog` | 1024 | 4096 | SYN flood чувствителен |
| `vm.max_map_count` | 65530 | 262144 | Elasticsearch/Java-приложения падают с OOM |
| `vm.overcommit_memory` | 0 | 1 | OOM-killer убивает процессы при нехватке памяти |
| `vm.panic_on_oom` | 0 | 0 | Ядро паникует при OOM (оставить 0) |
| `fs.file-max` | 65536 | 2097152 | Исчерпание файловых дескрипторов |
| `fs.inotify.max_user_watches` | 8192 | 524288 | inotify watch переполняется, поды не запускаются |
| `fs.inotify.max_user_instances` | 128 | 8192 | Слишком много namespace/inotify |
| `kernel.pid_max` | 32768 | 65536 | PIDPressure, fork-бомба |
| `kernel.threads-max` |imiter | sysctl | Ограничение потоков в системе |
| `kernel.keys.root_maxbytes` | 25000 | 32000 | Kubelet не может создавать ключи |
| `kernel.keys.root_maxkeys` | 100 | 200 | Лимит ключей исчерпан |

### Файлы конфигурации

| Файл | Назначение | Формат |
| :--- | :--- | :--- |
| `/etc/sysctl.conf` | Основной файл sysctl | `key = value` |
| `/etc/sysctl.d/*.conf` | Дополнительные файлы (рекомендуется) | `key = value` |
| `/etc/security/limits.conf` | Лимиты пользователей (ulimit) | `<domain> <type> <item> <value>` |
| `/etc/security/limits.d/*.conf` | Дополнительные файлы limits | `<domain> <type> <item> <value>` |
| `/etc/systemd/system.conf` | Лимиты для systemd service | `DefaultLimitNOFILE=`, `DefaultLimitNPROC=` |

### Взаимосвязь параметров и компонентов K8s

| Параметр ядра | Компонент K8s | Что ломается |
| :--- | :--- | :--- |
| `bridge-nf-call-iptables=0` | kube-proxy, CNI | Service ClusterIP не работает |
| `nf_conntrack_max` мало | kubelet, CoreDNS | DNS таймауты, Lease не обновляется |
| `somaxconn` мало | kubelet API | `kubectl exec/logs` зависает |
| `max_map_count` мало | Elasticsearch, Java поды | Приложение падает с OOM |
| `pid_max` мало | containerd | Новые контейнеры не создаются |
| `file-max` мало | containerd, kubelet | Ошибки записи логов |
| `inotify.max_user_watches` мало | kubelet | Поды не запускаются |
| `ip_forward=0` | kube-proxy | Маршрутизация между подами не работает |

## Практические сценарии

### Сценарий 1: Переполнение conntrack (DNS таймауты)

**Симптом**: Поды не могут разрешать имена DNS. `nslookup kubernetes.default` возвращает `SERVFAIL` или таймаут. HTTP-соединения к Service обрываются.

**Диагностика:**
```bash
# 1. Проверка текущего лимита и использования
sysctl net.netfilter.nf_conntrack_max net.netfilter.nf_conntrack_count
# → net.netfilter.nf_conntrack_max = 65536
# → net.netfilter.nf_conntrack_count = 65530   ← практически заполнен

# 2. Проверка в dmesg
dmesg -T | grep -i "conntrack table full" | tail -5
# → [Thu Sep  4 17:30:00 2026] nf_conntrack: table full, dropping packet

# 3. Проверка usage через /proc
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max

# 4. Проверка hashsize
cat /sys/module/nf_conntrack/parameters/hashsize
# → 32768   ← может быть мало для 1M+ записей
```

**Решение:**
```bash
# 1. Увеличение лимита
sudo sysctl -w net.netfilter.nf_conntrack_max=1048576

# 2. Увеличение hashsize для предотвращения коллизий
sudo sysctl -w net.netfilter.nf_conntrack_buckets=262144

# 3. Уменьшение timeout для быстрой очистки
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=3600

# 4. Постоянная запись
cat <<EOF | sudo tee /etc/sysctl.d/99-conntrack.conf
net.netfilter.nf_conntrack_max=1048576
net.netfilter.nf_conntrack_buckets=262144
net.netfilter.nf_conntrack_tcp_timeout_established=3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
net.netfilter.nf_conntrack_tcp_timeout_close_wait=15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait=30
EOF
sudo sysctl --system
```

---

### Сценарий 2: Исчерпание PID (PIDPressure)

**Симптом**: Узел в `PIDPressure=True`. Ошибки `fork: Cannot allocate memory`. Новые контейнеры не создаются, kubelet не может запустить поды.

**Диагностика:**
```bash
# 1. Проверка лимита PID
sysctl kernel.pid_max
# → 32768

# 2. Текущее количество процессов
ps -eLf | wc -l
# → 31500   ← критически близко к лимиту

# 3. Поиск процессов с наибольшим количеством потоков
ps -eo pid,nlwp,comm --sort=-nlwp | head -10
# → PID  NLWP COMMAND
# → 1234 5000 java -jar app.jar

# 4. Проверка zombie-процессов
ps -eo stat | grep -c Z
# → 31000   ← zombie-процессы занимают PID

# 5. Проверка через /proc
cat /proc/sys/kernel/pid_max
cat /proc/sys/kernel/threads-max
```

**Решение:**
```bash
# 1. Увеличение лимита PID
sudo sysctl -w kernel.pid_max=65536

# 2. Постоянное изменение
echo "kernel.pid_max=65536" | sudo tee /etc/sysctl.d/99-pid-max.conf
sudo sysctl --system

# 3. Убить fork-бомбу
FG_PID=$(ps -eo pid,ppid,comm | grep "bash.*while" | awk '{print $1}' | head -1)
sudo kill -- -$FG_PID

# 4. Перезапустить systemd для подбора zombies
sudo systemctl daemon-reexec
```

---

### Сценарий 3: vm.max_map_count (Elasticsearch/Java поды)

**Симптом**: Java-приложения (Elasticsearch, Kafka, Cassandra) падают с ошибкой `Failed to map memory` или OOM. Поды в `CrashLoopBackOff` с exit code 137.

**Диагностика:**
```bash
# 1. Проверка текущего лимита
sysctl vm.max_map_count
# → 65530   ← стандартное значение

# 2. Проверка потребления mmap в поде
kubectl exec <pod> -- cat /proc/1/maps | wc -l
# → 65500   ← приближается к лимиту

# 3. Проверка логов приложения
kubectl logs <pod> | grep -i "max_map_count\|mmap\|oom"
# → ERROR: max virtual memory areas vm.max_map_count [65530] is too low
# → increase to at least [262144]
```

**Решение:**
```bash
# 1. Установка через sysctl
sudo sysctl -w vm.max_map_count=262144

# 2. Постоянное изменение
echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-max-map-count.conf
sudo sysctl --system

# 3. Проверка, что приложение запустилось
kubectl get pod <pod>
# → NAME    READY   STATUS    RESTARTS   AGE
# → es-0    1/1     Running   0          30s
```

---

### Сценарий 4: conntrack + kube-proxy (Service ClusterIP не работает)

**Симптом**: Pod не может достучаться до Service по ClusterIP. `curl http://my-service:80` зависает. Но прямой доступ к Pod по IP работает.

**Диагностика:**
```bash
# 1. Проверка, что kube-proxy создал правила
iptables -t nat -L KUBE-SVC-ABCDEF1234 -n 2>/dev/null | head -5
# → Chain KUBE-SVC-ABCDEF1234 (3 references)
# → tcp dpt:80 ...

# 2. Проверка conntrack для конкретного соединения
conntrack -L -p tcp --dport 80 2>/dev/null | head -5
# → tcp  6 300 ESTABLISHED src=10.244.1.5 dst=10.233.0.1 sport=40123 dport=80

# 3. Проверка, не отброшен ли пакет из-за conntrack
dmesg | grep "conntrack" | tail -5
# → [Sep  4 17:30:00] nf_conntrack: table full, dropping packet

# 4. Проверка throughput
conntrack -S
# → cpu=0 found=1234567 inserted=1234567 dropped=50000
# → cpu=1 found=2345678 inserted=2345678 dropped=100000   ← много dropped
```

**Решение:**
```bash
# 1. Увеличить conntrack_max
sudo sysctl -w net.netfilter.nf_conntrack_max=2097152

# 2. Уменьшить timeout для UDP (DNS)
sudo sysctl -w net.netfilter.nf_conntrack_udp_timeout=30
sudo sysctl -w net.netfilter.nf_conntrack_udp_timeout_stream=60

# 3. Если conntrack не нужен (Calico eBPF, Cilium) — отключить:
# sysctl -w net.bridge.bridge-nf-call-iptables=0
# sysctl -w net.bridge.bridge-nf-call-ip6tables=0
```

---

### Сценарий 5: inotify watch переполнение

**Симптом**: kubelet не может запускать поды. Логи: `too many open files` или `failed to add watch`. Service discovery не работает.

**Диагностика:**
```bash
# 1. Проверка текущего лимита inotify
sysctl fs.inotify.max_user_watches fs.inotify.max_user_instances
# → fs.inotify.max_user_watches = 8192
# → fs.inotify.max_user_instances = 128

# 2. Проверка текущего использования
cat /proc/sys/fs/inotify/max_user_watches
find /proc/*/fdinfo -type f -exec grep -l inotify {} \; 2>/dev/null | wc -l

# 3. Проверка через lsof
sudo lsof 2>/dev/null | grep inotify | wc -l
# → 8190   ← почти заполнен
```

**Решение:**
```bash
# 1. Увеличение лимитов
sudo sysctl -w fs.inotify.max_user_watches=524288
sudo sysctl -w fs.inotify.max_user_instances=8192

# 2. Постоянное изменение
cat <<EOF | sudo tee /etc/sysctl.d/99-inotify.conf
fs.inotify.max_user_watches=524288
fs.inotify.max_user_instances=8192
EOF
sudo sysctl --system
```

---

### Сценарий 6: net.bridge.bridge-nf-call-iptables (Service не работает)

**Симптом**: Service ClusterIP недоступен, хотя Service существует и Endpoints есть. kube-proxy не обновляет правила.

**Диагностика:**
```bash
# 1. Проверка bridge-nf-call
sysctl net.bridge.bridge-nf-call-iptables
# → net.bridge.bridge-nf-call-iptables = 0   ← НЕПРАВИЛЬНО

# 2. Проверка, загружен ли модуль bridge
lsmod | grep bridge
# → bridge                163840  0
# → br_netfilter          28672   0
# Если br_netfilter не загружен — bridge-nf-call не работает

# 3. Проверка iptables (трафик не проходит через NAT)
iptables -t nat -L -n | head -10
# → Chain KUBE-SERVICES (2 references)
# → если пусто — bridge-nf-call не работает
```

**Решение:**
```bash
# 1. Загрузить модули ядра
sudo modprobe br_netfilter
sudo modprobe overlay

# 2. Установить sysctl
sudo sysctl -w net.bridge.bridge-nf-call-iptables=1
sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=1
sudo sysctl -w net.ipv4.ip_forward=1

# 3. Постоянное изменение
cat <<EOF | sudo tee /etc/sysctl.d/99-kubernetes-bridge.conf
net.bridge.bridge-nf-call-iptables=1
net.bridge.bridge-nf-call-ip6tables=1
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF
sudo sysctl --system

# 4. Добавить модули в /etc/modules-load.d/
echo -e "br_netfilter\noverlay" | sudo tee /etc/modules-load.d/k8s.conf
```

---

### Сценарий 7: ulimit файловых дескрипторов (kubelet/containerd)

**Симптом**: kubelet или containerd падают с ошибкой `too many open files`. Логи containerd содержат `socket: too many open files`.

**Диагностика:**
```bash
# 1. Проверка ulimit для kubelet
cat /proc/$(pgrep kubelet)/limits | grep "Max open files"
# → Max open files            1024                 1048576              files

# 2. Проверка ulimit для containerd
cat /proc/$(pgrep containerd)/limits | grep "Max open files"
# → Max open files            1024                 1048576              files

# 3. Проверка текущего количества открытых файлов
ls /proc/$(pgrep kubelet)/fd | wc -l
# → 1020   ← почти заполнен лимит 1024

# 4. Проверка limits.conf
grep -v "^#" /etc/security/limits.conf | grep -v "^$"
# → root    soft    nofile    1024    ← слишком мало
```

**Решение:**
```bash
# 1. Настройка limits.conf
cat <<EOF | sudo tee /etc/security/limits.d/99-kubernetes.conf
*       soft    nofile    65536
*       hard    nofile    131072
*       soft    nproc     65536
*       hard    nproc     131072
root    soft    nofile    65536
root    hard    nofile    131072
root    soft    nproc     65536
root    hard    nproc     131072
EOF

# 2. Настройка для systemd service (kubelet, containerd)
sudo mkdir -p /etc/systemd/system/kubelet.service.d/
cat <<EOF | sudo tee /etc/systemd/system/kubelet.service.d/99-limits.conf
[Service]
LimitNOFILE=65536
LimitNPROC=65536
EOF

sudo mkdir -p /etc/systemd/system/containerd.service.d/
cat <<EOF | sudo tee /etc/systemd/system/containerd.service.d/99-limits.conf
[Service]
LimitNOFILE=65536
LimitNPROC=65536
EOF

# 3. Перезагрузка systemd
sudo systemctl daemon-reload
sudo systemctl restart kubelet containerd
```

---

### Сценарий 8: vm.overcommit_memory и OOM-killer

**Симптом**: Kubelet или containerd убиты OOM-killer. `dmesg | grep "Out of memory"` показывает системные процессы.

**Диагностика:**
```bash
# 1. Проверка overcommit
sysctl vm.overcommit_memory vm.overcommit_ratio
# → vm.overcommit_memory = 0
# → vm.overcommit_ratio = 50

# 2. Проверка OOM-killer
dmesg -T | grep -i "oom\|killed" | tail -5
# → [Thu Sep  4 17:30:00 2026] Out of memory: Killed process 12345 (kubelet)
# →   total-vm:4567892kB, anon-rss:2345678kB

# 3. Проверка oom_score для kubelet
cat /proc/$(pgrep kubelet)/oom_score
# → -1000   ← kubelet защищен от OOM (oom_score_adj = -1000)
```

**Решение:**
```bash
# 1. Установить overcommit_memory=1 (всегда выделять)
sudo sysctl -w vm.overcommit_memory=1

# 2. Установить overcommit_ratio
sudo sysctl -w vm.overcommit_ratio=80

# 3. Постоянное изменение
cat <<EOF | sudo tee /etc/sysctl.d/99-overcommit.conf
vm.overcommit_memory=1
vm.overcommit_ratio=80
EOF
sudo sysctl --system

# 4. Убедиться, что kube-reserved достаточный
# В /var/lib/kubelet/config.yaml:
# kubeReserved:
#   memory: "1Gi"   # выделить足够的 памяти для kubelet + containerd
```

## Готовый набор sysctl для Kubernetes

```bash
# Сохранить как /etc/sysctl.d/99-kubernetes.conf

# Сеть
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 5

# Память
vm.max_map_count = 262144
vm.overcommit_memory = 1
vm.overcommit_ratio = 80
vm.panic_on_oom = 0

# Файловые системы
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 8192

# Ядро
kernel.pid_max = 65536
kernel.threads-max = 65536
```

## Мониторинг и алертинг

### Метрики sysctl (node_exporter)

| Метрика | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `node_netstat_Nf_conntrack_inuse` | Использование conntrack | > 80% от max |
| `node_netstat_Icmp_Messages_in_errors` | ICMP ошибки | > 0持续 |
| `node_procs_running` | Количество runnable процессов | > 3000持续 |
| `node_procs_blocked` | Количество заблокированных процессов | > 100持续 |
| `node_filesystem_files` | Количество inodes | IUse% > 90% |
| `node_filesystem_files_free` | Свободные inodes | < 5% |

## Дополнительная информация

### Связанные разделы

- **[Давление ресурсов](./resource_pressure.md)** — sysctl является причиной PIDPressure, MemoryPressure
- **[Сетевые проблемы](./network_issues.md)** — conntrack, bridge-nf-call, MTU
- **[Проблемы Kubelet](./kubelet_issues.md)** — ulimit, OOM-kill, PID
- **[Обслуживание узлов](./maintenance.md)** — настройка sysctl перед вводом узла в эксплуатацию
- **[Ядро Linux: PSI](../../../Linux/Core/kernel/psi.md)** — мониторинг давления на ресурсы
- **[etcd: kernel tuning](../../../etcd/kernel_tuning.md)** — параметры для etcd узлов
- **[Node Preparation](../../../Kubernetes/Installation/HA_Cluster_Bare_Metal/k8s_ha_node_preparation.md)** — подготовка узла
