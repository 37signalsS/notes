# Недоступность узла: Проблемы Kubelet

Агент `kubelet` является критическим компонентом, обеспечивающим связь между API-сервером и рантаймом контейнеров. Его сбой или некорректная настройка — самая частая причина перехода узла в состояния `NotReady` или `Unknown`. Данный файл является **SSoT для диагностики проблем, специфичных для Kubelet** — общая диагностика узла описана в [Диагностика недоступности узла](./diagnostics.md), проблемы рантайма — в [Проблемы рантайма](./runtime_issues.md), давление ресурсов — в [Давление ресурсов](./resource_pressure.md).

## Основные определения

**Сбой Kubelet (Kubelet Issue)** — состояние, при котором агент не может выполнять жизненно важные функции: управление контейнерами (CRI), отчетность о состоянии (Heartbeats), выполнение проб (Probes) и управление ресурсами (Cgroups/Volumes).

**Статусы при сбоях:**
- **`NotReady`**: Kubelet запущен, но сообщает о внутренней ошибке (например, `NetworkUnavailable`, `DiskPressure` или сбой CNI). Kubelet продолжает отправлять heartbeats, но помечает узел Conditions как `False`.
- **`Unknown`**: Kubelet не отправляет данные в API-сервер (процесс упал, завис или изолирован сетевым экраном). API-сервер ожидает `nodeLeaseDurationSeconds` (по умолчанию 40 сек), затем помечает узел как `Unknown`.

**Типичные причины сбоев Kubelet ( Taxonomy):**

| Категория | Примеры | Последствие |
| :--- | :--- | :--- |
| **Конфигурация** | Несовпадение `cgroupDriver`, неверный kubeconfig, отсутствие `config.yaml` | Kubelet не запускается (Panic или CrashLoopBackOff) |
| **Сертификаты** | Истекший клиентский/серверный сертификат, отсутствие CSR approval | `Unauthorized` ошибки, `NotReady` |
| **Ресурсы ОС** | OOM-kill процесса kubelet, исчерпание PID, переполнение inode | Процесс убит ядром, `Unknown` |
| **CRI-связность** | Сокет containerd недоступен, gRPC timeout, PLEG unhealthy | `NotReady`, поды не запускаются |
| **Состояние (State)** | Повреждение `cpu_manager_state`, `memory_manager_state` | Kubelet не может выделить ресурсы, CrashLoopBackOff |
| **Версия/Баги** | Известные проблемы в конкретных версиях Kubernetes | Непредсказуемое поведение |

Подробная архитектура агента: [Обзор Kubelet](../../../Concepts/kubelet.md).

## Основные концепции

### Критические зависимости и точки отказа

| Компонент | Требование / Зависимость | Последствие сбоя | Способ проверки |
| :--- | :--- | :--- | :--- |
| **Связность с API** | Порт `6443` (Outbound), валидный `kubelet.conf` | Статус `Unknown`, невозможность запустить поды | `curl -sk https://<api>:6443/healthz` |
| **CRI Runtime** | Доступ к Unix-сокету (containerd/CRI-O) | Статус `NotReady`, ошибка PLEG | `sudo crictl info` |
| **Cgroup Driver** | Совпадение (`systemd` vs `cgroupfs`) | Kubelet не запускается (Panic) | `grep cgroupDriver /var/lib/kubelet/config.yaml` |
| **Ресурсы ОС** | Свободная память, CPU и лимиты PID (`pid_max`) | Зависание агента, OOM-kill процесса `kubelet` | `dmesg | grep -i "oom\|kubelet"` |
| **Systemd-logind** | Запущен для Graceful Shutdown | Поды убиваются по SIGKILL при выключении | `systemctl status systemd-logind` |
| **DNS-резолвер** | Доступность `/etc/resolv.conf` | Kubelet не может разрешить имена репозиториев | `cat /etc/resolv.conf` |
| **Дисковое пространство** | Свободное место в `/var/lib/kubelet` | DiskPressure, невозможность записи логов | `df -h /var/lib/kubelet` |

### Файловая структура и файлы состояния

| Путь | Назначение | Риск при повреждении |
| :--- | :--- | :--- |
| `/var/lib/kubelet/config.yaml` | Основная конфигурация (`KubeletConfiguration`). | Kubelet не запускается или работает с неверными параметрами. |
| `/etc/kubernetes/kubelet.conf` | Kubeconfig для авторизации узла в API-сервере. | `Unauthorized` ошибки, `NotReady`. |
| `/var/lib/kubelet/pki/` | Сертификаты узла (клиентские и серверные). | Истечение сертификатов → `Unauthorized`, `NotReady`. |
| `/var/lib/kubelet/cpu_manager_state` | Данные о выделении ядер (могут повреждаться). | Kubelet не может выделить CPU для Guaranteed подов. |
| `/var/lib/kubelet/memory_manager_state` | Данные о выделении памяти (NUMA). | Kubelet не может выделить память для NUMA-оптимизированных подов. |
| `/var/lib/kubelet/pods/` | Локальные данные подов (`emptyDir`, логи контейнеров). | Потеря данных, DiskPressure. |
| `/etc/containerd/config.toml` | Конфигурация containerd (CRI-сокет, sandbox image). | Kubelet не может подключиться к CRI. |

### Конфигурация Kubelet: Иерархия приоритетов

Kubelet получает параметры конфигурации по следующей иерархии (от высшего к низшему):

1. **Командные флаги** (в `ExecStart` unit-файла systemd) — наивысший приоритет.
2. **Drop-in файлы** из `--config-dir` (например, `/etc/kubernetes/kubelet.conf.d/*.conf`) — переопределяют основной конфиг.
3. **Конфигурационный файл** `--config` (обычно `/var/lib/kubelet/config.yaml`).
4. **Значения по умолчанию** для версии `KubeletConfiguration`.

Типичный unit-файл kubeadm (`/etc/systemd/system/kubelet.service.d/10-kubeadm.conf`):

```ini
[Service]
Environment="KUBELET_KUBECONFIG_ARGS=--bootstrap-kubeconfig=/etc/kubernetes/bootstrap-kubelet.conf \
--kubeconfig=/etc/kubernetes/kubelet.conf"
Environment="KUBELET_CONFIG_ARGS=--config=/var/lib/kubelet/config.yaml"
ExecStart=/usr/bin/kubelet $KUBELET_KUBECONFIG_ARGS $KUBELET_CONFIG_ARGS $KUBELET_EXTRA_ARGS
```

**Важно:** После правки конфигурации или unit-файла обязательно перезагрузите systemd daemon и перезапустите kubelet:
```bash
sudo systemctl daemon-reload && sudo systemctl restart kubelet
```

## Практические сценарии

### Сценарий 1: Kubelet не запускается (Cgroup Driver / YAML)

**Симптом**: Сервис `failed`, в логах: `misconfiguration: kubelet cgroup driver: "systemd" is different from docker cgroup driver: "cgroupfs"`.

**Диагностика**:
```bash
# 1. Проверка статуса сервиса
systemctl status kubelet
# → kubelet.service - kubelet: The Kubernetes Node Agent
#    Active: failed (Result: exit-code) since Thu 2026-09-04 17:30:00 UTC; 5min ago

# 2. Просмотр последних логов
journalctl -u kubelet -n 20 --no-pager
# → Sep 04 17:30:00 node-1 kubelet[12345]: F0904 17:30:00.123456 123456 kubelet.go:1405] Failed to run kubelet
# → Sep 04 17:30:00 node-1 kubelet[12345]: error: failed to run Kubelet: misconfiguration: kubelet cgroup driver: "systemd" is different from container runtime cgroup driver: "cgroupfs"

# 3. Проверка драйвера в конфиге Kubelet
grep cgroupDriver /var/lib/kubelet/config.yaml
# → cgroupDriver: systemd

# 4. Проверка драйвера в containerd
grep -i "SystemdCgroup" /etc/containerd/config.toml
# → SystemdCgroup = true

# 5. Проверка, какой драйвер cgroup используется системой
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs    ← cgroup v2 (всегда systemd)
# → tmpfs        ← cgroup v1 (может быть systemd или cgroupfs)
```

**Решение**:
1. Убедитесь, что в обоих конфигах используется одинаковый драйвер. В современных системах (cgroup v2) **всегда** используйте `systemd`.
2. Если containerd использует `cgroupfs`, а kubelet — `systemd`, исправьте containerd:
   ```toml
   # /etc/containerd/config.toml
   [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
     SystemdCgroup = true
   ```
3. После правки:
   ```bash
   systemctl restart containerd kubelet
   systemctl status kubelet
   # → Active: active (running) since Thu 2026-09-04 17:35:00 UTC; 10s ago
   ```

**Важно:** Начиная с Kubernetes 1.28, `cgroupDriver: systemd` является рекомендуемым значением по умолчанию. Для cgroup v2 использование `cgroupfs` в containerd приводит к ошибкам при создании подов.

### Сценарий 2: Повреждение файлов состояния (State Corruption)

**Симптом**: Kubelet падает с ошибкой в `cpu_manager` или не может запустить поды с гарантированным QoS. В логах: `Failed to initialize cpu manager` или `could not restore state`.

**Причина**: Файлы состояния менеджеров ресурсов (`cpu_manager_state`, `memory_manager_state`) содержат данные о распределении ресурсов между подами. Если ядра CPU были отключены/перенумерованы (например, после обновления BIOS или изменения NUMA-topology), или если kubelet был убит во время записи, состояние becomes inconsistent.

**Диагностика**:
```bash
# 1. Проверка логов kubelet на наличие ошибок состояния
journalctl -u kubelet -n 50 --no-pager | grep -E "manager|state"
# → E0904 17:35:00.123456 123456 cpu_manager.go:231] Failed to initialize cpu manager: 
# →   could not restore state from "/var/lib/kubelet/cpu_manager_state": 
# →   failed to validate cpus 3,4,5 from state file against available cpus 0,1,2,4,5

# 2. Проверка содержимого файла состояния
cat /var/lib/kubelet/cpu_manager_state | python3 -m json.tool
# → {
# →     "policyName": "static",
# →     "defaultCpuSet": "0-2",
# →     "entries": {
# →         "pod-uid/container-name": "3-4"
# →     },
# →     "checksum": 1234567890
# → }

# 3. Проверка доступных ядер
lscpu | grep "CPU(s):"
# → CPU(s):                6

# 4. Проверка memory_manager_state (если есть)
cat /var/lib/kubelet/memory_manager_state | python3 -m json.tool 2>/dev/null
```

**Решение**:
```bash
# Безопасное удаление поврежденных файлов состояния
# (Kubelet пересоздаст их при следующем запуске)
systemctl stop kubelet
rm -f /var/lib/kubelet/cpu_manager_state
rm -f /var/lib/kubelet/memory_manager_state
systemctl start kubelet

# Проверка, что kubelet запустился
systemctl status kubelet
# → Active: active (running)

# Проверка, что файл состояния пересоздан
ls -la /var/lib/kubelet/cpu_manager_state
# → -rw-r--r-- 1 root root 256 Sep  4 17:40:00 /var/lib/kubelet/cpu_manager_state
```

**Важно:** Удаление файлов состояния безопасно дляUBELET, но приводит к кратковременному освобождению всех выделенных CPU-наборов. Поды с `Guaranteed` QoS и целочисленными CPU-лимитами могут временно потерять выделенные ядра до следующей синхронизации (обычно несколько секунд).

### Сценарий 3: Истечение сертификатов узла

**Симптом**: Ошибки `x509: certificate has expired` или `Unauthorized` в `journalctl`. Kubelet не может авторизоваться в API-сервере, узел переходит в `Unknown`.

**Причины**:
- Сертификаты Kubelet по умолчанию действительны 1 год (сгенерированы kubeadm).
- Автоматическая ротация клиентских сертификатов (`rotateCertificates: true`) работает через CSR-процесс, но требует одобрения CSR в кластере.
- Серверные сертификаты (порт 10250) требуют дополнительной настройки `serverTLSBootstrap: true`.

**Диагностика**:
```bash
# 1. Проверка срока действия клиентского сертификата
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -text -noout | grep -A 2 "Validity"
# → Validity
# →     Not Before: Sep  4 2025 17:30:00 GMT
# →     Not After : Sep  4 2026 17:30:00 GMT    ← если дата в прошлом — просрочен

# 2. Проверка серверного сертификата
openssl x509 -in /var/lib/kubelet/pki/kubelet-server-current.pem -text -noout | grep -A 2 "Validity" 2>/dev/null
# → Validity
# →     Not Before: Sep  4 2025 17:30:00 GMT
# →     Not After : Sep  4 2026 17:30:00 GMT

# 3. Проверка CSR в кластере (с control plane узла)
kubectl get csr | grep <node-name>
# → NAME        AGE     SIGNERNAME                     REQUESTOR              STATUS
# → csr-abc12   5m      kubernetes.io/kube-apiserver-kubelet-client   system:node:<node-name>   Pending

# 4. Проверка логов kubelet на ошибки авторизации
journalctl -u kubelet -n 20 --no-pager | grep -E "Unauthorized|x509|certificate"
# → E0904 17:35:00.123456 123456 reflector.go:150] Failed to list *v1.Node: 
# →   Unauthorized
```

**Решение**:
```bash
# 1. Если используется kubeadm — обновите сертификаты
sudo kubeadm certs renew all

# 2. Одобрение Pending CSR (на control plane)
kubectl certificate approve csr-abc12

# 3. Включение автоматической ротации (если не включена)
# В /var/lib/kubelet/config.yaml:
# rotateCertificates: true
# serverTLSBootstrap: true

# 4. Если сертификаты полностью удалены или повреждены —
# удалите остатки и перезапустите kubelet для генерации нового CSR:
rm -f /var/lib/kubelet/pki/*
systemctl restart kubelet

# 5. Проверка нового CSR
kubectl get csr | grep <node-name>
# → csr-xyz78   30s     kubernetes.io/kube-apiserver-kubelet-client   system:node:<node-name>   Pending
kubectl certificate approve csr-xyz78
```

**Профилактика**: Включите `serverTLSBootstrap: true` и `rotateCertificates: true` для автоматической ротации. Настройте алерт на приближение истечения сертификатов (см. раздел "Мониторинг" ниже).

Подробнее: [Управление сертификатами](../../../Operations/certificate_management.md).

### Сценарий 4: Ошибки PLEG (PLEG is unhealthy)

**Симптом**: Узел `NotReady`, логи забиты сообщениями `PLEG is unhealthy: relist period was too long`.

**Механизм**: PLEG (Pod Lifecycle Event Generator) опрашивает CRI каждую секунду. Если рантайм не отвечает за `podSyncLoopTimeout` (по умолчанию 1 минуту), PLEG помечается как unhealthy. Подробный разбор механизма PLEG: [Диагностика недоступности узла](./diagnostics.md#механизм-pleg-pod-lifecycle-event-generator).

**Причины и отладка**:
```bash
# 1. Проверка перегрузки CRI — если crictl виснет, рантайм не отвечает
time sudo crictl pods
# → real    0m0.123s   ← норма (< 1 сек)
# → real    0m45.678s  ← рантайм зависает

# 2. Проверка I/O Wait — если диск системного раздела занят
iostat -x 1 3
# → Device   r/s   w/s   await   svctm   %util
# → sda      5.00  350.00  250.00  2.80    100.00  ← 100% utilization = проблема

# 3. Количество контейнеров на узле (массовый PLEG)
sudo crictl ps | wc -l
# → 250   ← много, но нормально для больших узлов
# → 1500  ← вероятно, есть "зомби" контейнеры

# 4. Проверка "зомби" контейнеров
sudo crictl ps -a | grep Exited | wc -l
# → 150  ← много завершенных контейнеров

# 5. Логи kubelet по PLEG
journalctl -u kubelet --since "10 min ago" --no-pager | grep -c "PLEG is unhealthy"
# → 45  ← количество сбоев PLEG за 10 минут
```

**Решение**:
```bash
# 1. Перезапуск рантайма (быстрое восстановление)
sudo systemctl restart containerd

# 2. Очистка "зомби" контейнеров (если их много)
sudo crictl rm $(sudo crictl ps -a -q --state exited)
# → Результат: список удаленных контейнеров

# 3. Проверка восстановления PLEG
journalctl -u kubelet -f --no-pager | grep -E "PLEG|ready"
# → I0904 17:40:00.123456 123456 kubelet.go:2209] "Volume operations successful"
# → I0904 17:40:01.654321 123456 kubelet.go:2234] "PLEG is healthy"

# 4. Если проблема повторяется — проверьте I/O и освободите диск
df -h /var/lib/containerd
# → Filesystem   Size  Used Avail Use% Mounted on
# → /dev/sda1    100G   95G    5G  95% /     ← критически мало места
```

**Важно:** Если PLEG unhealthy持續超過 5 минут, узел автоматически помечается как `NotReady` контроллером узла. Перезапуск containerd решает проблему как временная мера, но требует расследования причин (I/O, количество контейнеров, memory pressure).

### Сценарий 5: Поддержка Swap (Kubernetes 1.31+)

**Симптом**: Kubelet падает на узле с включенным Swap, хотя в 1.31 заявлена поддержка. В логах: `failed to run kubelet: Running with swap on is not supported`.

**Механизм**: По умолчанию Kubernetes требует отключения swap (`swapoff -a`). Поддержка swap для подов появилась постепенно:
- Alpha с 1.22, Beta с 1.28, GA с 1.34.
- Работает **только на cgroup v2**.
- Доступна только подам QoS-класса `Burstable` (не `Guaranteed` и не `BestEffort`).
- Опция `UnlimitedSwap` удалена в 1.30.

**Диагностика**:
```bash
# 1. Проверка включен ли swap
swapon --show
# → NAME      TYPE      SIZE  USED  PRIO
# → /dev/sda2 partition 4G    1.2G  -2
# Если пусто — swap отключен

# 2. Проверка версии cgroup
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs   ← cgroup v2 (swap поддерживается)
# → tmpfs       ← cgroup v1 (swap не поддерживается)

# 3. Проверка конфигурации swap в kubelet
grep -E "failSwap|swapBehavior|NodeSwap" /var/lib/kubelet/config.yaml
# → failSwapOn: false
# → memorySwap:
# →   swapBehavior: LimitedSwap

# 4. Проверка feature gate (для версий < 1.34)
# В логах kubelet:
journalctl -u kubelet -n 50 --no-pager | grep -i "swap\|NodeSwap"
# → I0904 17:35:00.123456 123456 feature_gate.go:220] Feature gate: NodeSwap=true
```

**Решение**:
```yaml
# /var/lib/kubelet/config.yaml
apiVersion: kubelet.config.k8s.io/v1
kind: KubeletConfiguration
failSwapOn: false
memorySwap:
  swapBehavior: LimitedSwap
```

```bash
# После правки конфигурации
sudo systemctl daemon-reload && sudo systemctl restart kubelet

# Проверка, что kubelet запустился с swap
journalctl -u kubelet -n 10 --no-pager | grep -i swap
# → I0904 17:40:00.123456 123456 kubelet.go:1853] Using LimitedSwap memory swap behavior
```

**Ограничения**: Swap для подов работает только на cgroup v2 и доступен лишь подам `Burstable`. Поды `Guaranteed` (с `requests == limits`) и `BestEffort` swap не используют.

---

### Сценарий 6: OOM-kill процесса Kubelet

**Симптом**: Kubelet периодически перезапускается (CrashLoopBackOff), в `dmesg` сообщения об OOM-kill. Узел "миграция" между `Ready` и `NotReady`.

**Причина**: Процесс kubelet потребляет больше памяти, чем выделено для системных резервов (`kube-reserved`). Типичные виновники: большое количество подов на узле (>500), Memory Manager в режиме NUMA, утечки памяти в старых версиях kubelet.

**Диагностика**:
```bash
# 1. Проверка OOM-kill в dmesg
dmesg | grep -i "oom\|kubelet"
# → [Sep 4 17:30:00] Out of memory: Killed process 12345 (kubelet) total-vm:4567892kB, anon-rss:2345678kB

# 2. Текущее потребление памяти kubelet
ps aux | grep kubelet | awk '{print $6/1024 " MB"}'
# → 1024.5 MB

# 3. Лимит памяти для системных сервисов (включая kubelet)
# Проверить через cgroups:
cat /sys/fs/cgroup/memory/kubelet/memory.limit_in_bytes 2>/dev/null || echo "Нет лимита cgroup"
# → 2147483648   ← 2GB лимит

# 4. Проверка логов после перезапуска
journalctl -u kubelet --since "5 min ago" --no-pager | head -20
# → Sep 04 17:35:00 node-1 systemd[1]: kubelet.service: Main process exited, code=killed, status=9/KILL
# → Sep 04 17:35:01 node-1 systemd[1]: kubelet.service: Scheduled restart job, restart counter is at 3.
```

**Решение**:
```bash
# 1. Увеличение резерва памяти для kubelet (в /var/lib/kubelet/config.yaml)
# kubeReserved:
#   memory: "1Gi"   ← увеличить значение

# 2. Проверка потребления kubelet через pprof (если включен)
curl -sk https://127.0.0.1:10250/debug/pprof/heap > /tmp/kubelet-heap.out
go tool pprof /tmp/kubelet-heap.out
# → (pprof) top
# →Showing nodes accounting for 512.32MB, 97.45% of 525.71MB total

# 3. Уменьшение количества подов на узле (maxPods)
# В /var/lib/kubelet/config.yaml:
# maxPods: 110   ← уменьшить, если было увеличено
```

**Профилактика**: Настройте `kube-reserved` с запасом 20-30% от типичного потребления kubelet. Мониторьте потребление памяти kubelet через `process_resident_memory_bytes` в метриках.

---

### Сценарий 7: Image Garbage Collection и DiskPressure

**Симптом**: Узел в `DiskPressure`, поды выселяются из-за нехватки места на диске, хотя `kubeReserved` настроен. Kubelet не успевает очищать неиспользуемые образы.

**Механизм**: Image GC работает в два этапа:
1. Если использование `imagefs` превышает `imageGCHighThresholdPercent` (по умолчанию 85%), Kubelet начинает удаление неиспользуемых образов.
2. Очистка продолжается, пока использование не опустится ниже `imageGCLowThresholdPercent` (по умолчанию 80%).

**Диагностика**:
```bash
# 1. Проверка использования диска для образов
df -h /var/lib/containerd
# → Filesystem   Size  Used Avail Use% Mounted on
# → /dev/sdb1    100G   92G    8G  92% /var/lib/containerd   ← выше 85% = Image GC запущен

# 2. Проверка порогов GC в конфиге kubelet
grep -E "imageGC" /var/lib/kubelet/config.yaml
# → imageGCHighThresholdPercent: 85
# → imageGCLowThresholdPercent: 80

# 3. Просмотр неиспользуемых образов
sudo crictl images -v | grep -E "IMAGE|SIZE" | head -10
# → IMAGE                                     TAG                 IMAGE ID            SIZE
# → docker.io/library/nginx                   1.27                abc123def456...     187.4MB
# → docker.io/library/nginx                   1.25                def789abc012...     175.2MB

# 4. Проверка логов GC
journalctl -u kubelet --since "1 hour ago" --no-pager | grep -i "image gc"
# → I0904 17:30:00.123456 123456 image_gc_manager.go:324] 
# →   Image garbage collection removed 15 images, reclaimed 2345MB space
```

**Решение**:
```bash
# 1. Ручная очистка неиспользуемых образов
sudo crictl rmi --prune

# 2. Настройка более низких порогов GC (в /var/lib/kubelet/config.yaml)
# imageGCHighThresholdPercent: 75
# imageGCLowThresholdPercent: 65

# 3. Проверка Container GC (очистка завершенных контейнеров)
# containerGCHighThresholdPercent: 85
# containerGCLowThresholdPercent: 80

# 4. Проверка DiskPressure после очистки
kubectl describe node <node-name> | grep -A 3 Conditions
# → Conditions:
# →   Type             Status  Reason
# →   DiskPressure     False   KubeletHasNoDiskPressure
```

---

### Сценарий 8: Проблемы с ротацией логов контейнеров

**Симптом**: Диск заполняется логами контейнеров, `DiskPressure` возникает из-за файлов в `/var/log/containers/`. Kubelet не ротирует логи корректно.

**Механизм**: Kubelet ротирует логи контейнеров, когда размер单一日志файла превышает `containerLogMaxSize` (по умолчанию 10Mi), оставляя не более `containerLogMaxFiles` (по умолчанию 5) файлов. Однако если приложение пишет очень быстро или файловая система не поддерживает ротацию (например, `journald` logging driver), логи могут накапливаться.

**Диагностика**:
```bash
# 1. Проверка размера логов контейнеров
du -sh /var/log/containers/
# → 15G     /var/log/containers/   ← критически много

# 2. Проверка largest log files
find /var/log/containers/ -name "*.log" -exec ls -lh {} \; | sort -k5 -h | tail -5
# → -rw-r----- 1 root root 2.5G Sep  4 17:30 my-app-abc123.log
# → -rw-r----- 1 root root 1.8G Sep  4 17:30 my-db-def456.log

# 3. Проверка настроек ротации в kubelet
grep -E "containerLog" /var/lib/kubelet/config.yaml
# → containerLogMaxSize: 10Mi
# → containerLogMaxFiles: 5

# 4. Проверка, есть ли поды с非常に быстрым логированием
kubectl top pods --sort-by=memory -A | head -10
```

**Решение**:
```bash
# 1. Увеличение лимита ротации (в /var/lib/kubelet/config.yaml)
# containerLogMaxSize: 50Mi    ← увеличить
# containerLogMaxFiles: 10     ← увеличить количество файлов

# 2. Ручная очистка старых логов
find /var/log/containers/ -name "*.log" -mtime +7 -delete

# 3. Настройка логирования на уровне приложения (рекомендуется)
# Используйте structured logging и JSON формат для эффективной ротации

# 4. Проверка DiskPressure после очистки
df -h /var/log
# → Filesystem   Size  Used Avail Use% Mounted on
# → /dev/sda1    100G   45G   55G  45% /     ← приемлемо
```

---

### Сценарий 9: Неправильная настройка резервирования ресурсов

**Симптом**: Поды `BestEffort` и `Burstable` выселяются неожиданно, хотя `MemoryPressure` не установлен. Kubelet вычисляет доступные ресурсы (`Allocatable`) с ошибкой из-за неверных `kubeReserved` или `systemReserved`.

**Формула**:
```
Allocatable = Capacity - kubeReserved - systemReserved - evictionHard
```

Если `kubeReserved` или `systemReserved` заданы слишком большими, `Allocatable` уменьшается, и поды могут быть выселены раньше ожидаемого.

**Диагностика**:
```bash
# 1. Проверка Allocatable vs Capacity
kubectl describe node <node-name> | grep -A 5 "Allocatable"
# → Allocatable:
# →   cpu:                3800m      ← Capacity: 4000m, minus kubeReserved (200m)
# →   memory:             7400Mi     ← Capacity: 8192Mi, minus kubeReserved (512Mi) + systemReserved (256Mi)
# →   pods:               110

# 2. Проверка текущего потребления vs Allocatable
kubectl top node <node-name>
# → NAME      CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → node-1    3500m        92%    6800Mi          91%     ← критически близко к Allocatable

# 3. Проверка фактического потребления системных сервисов
ps aux --sort=-%mem | head -10
# → USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
# → root     12345  5.0 15.0 1234567 987656 ?      Sl   17:30   0:30 kubelet
# → root      6789  2.0  8.0  567890 456789 ?      Sl   17:30   0:10 containerd

# 4. Проверка reservations в конфиге
grep -A 5 "kubeReserved\|systemReserved" /var/lib/kubelet/config.yaml
# → kubeReserved:
# →   cpu: "200m"
# →   memory: "512Mi"
# → systemReserved:
# →   cpu: "100m"
# →   memory: "256Mi"
```

**Решение**:
```bash
# 1. Уточните фактическое потребление системных сервисов
# и настройте резервирование с запасом 20-30%:

# /var/lib/kubelet/config.yaml
# kubeReserved:
#   cpu: "500m"        ← если kubelet + containerd потребляют ~400m
#   memory: "1Gi"      ← если потребляют ~800Mi
# systemReserved:
#   cpu: "300m"
#   memory: "512Mi"

# 2. Проверка нового Allocatable
sudo systemctl daemon-reload && sudo systemctl restart kubelet
kubectl describe node <node-name> | grep -A 5 "Allocatable"

# 3. Проверка, что поды не выселяются
kubectl get events --field-selector reason=Eviction --sort-by='.lastTimestamp' | tail -5
```

**Важно:** Недооценка `kubeReserved` приводит к тому, что системные процессы (kubelet, containerd) конкурируют с подами за ресурсы. Переоценка уменьшает `Allocatable` и снижает емкость узла.

## Мониторинг и алертинг

### Метрики Kubelet (Prometheus)

| Метрика | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `process_resident_memory_bytes` | Потребление памяти процессом kubelet | > 1.5 GiB (требует расследования) |
| `process_cpu_seconds_total` | Использование CPU kubelet | > 0.5 cores持续 |
| `rest_client_requests_total{code=~"5.."}` | Ошибки API-сервера (5xx) | > 0持续 5 минут |
| `kubelet_runtime_operations_errors_total` | Ошибки CRI-операций (PLEG) | > 0持续 2 минуты |
| `kubelet_pleg_relist_duration_seconds` | Время relist PLEG | > 1 сек持续 |
| `storage_operation_errors_total` | Ошибки_VOLUME операций (CSI) | > 0持续 5 минут |
| `kubelet_certificate_manager_client_cert_expiration_seconds` | Оставшийся срок сертификата | < 7 дней |

### Примеры алертов (PrometheusRule)

```yaml
groups:
  - name: kubelet-health
    rules:
      # Kubelet не отправляет heartbeats
      - alert: KubeletDown
        expr: absent(up{job="kubelet"} == 1)
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Kubelet на {{ $labels.instance }} не отвечает"
          description: "Kubelet не отправляет метрики более 5 минут"

      # Высокое потребление памяти kubelet
      - alert: KubeletHighMemory
        expr: process_resident_memory_bytes{job="kubelet"} > 1.5e9
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Kubelet на {{ $labels.instance }} потребляет > 1.5Gi памяти"
          description: "Текущее потребление: {{ $value | humanize1024 }}B"

      # Ошибки PLEG
      - alert: KubeletPLEGErrors
        expr: rate(kubelet_runtime_operations_errors_total{operation_type="PLEG"}[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Kubelet на {{ $labels.instance }}รายงาน PLEG ошибки"
          description: "Частота ошибок PLEG: {{ $value }}/сек"

      # Приближение истечения сертификата
      - alert: KubeletCertExpiringSoon
        expr: kubelet_certificate_manager_client_cert_expiration_seconds < 604800
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Сертификат Kubelet на {{ $labels.instance }} истекает через < 7 дней"
          description: "Оставшееся время: {{ $value | humanizeDuration }}"
```

## Рекомендации по мониторингу

1. **Настройте алерт `KubeletDown`** — это критический алерт, требующий немедленного реагирования.
2. **Мониторьте потребление памяти kubelet** — рост выше 1.5 GiB указывает на утечку или необходимость увеличения `kube-reserved`.
3. **Отслеживание PLEG** — частые ошибки PLEG указывают на проблемы с CRI или I/O.
4. **Сертификаты** — настройте алерт за 7 дней до истечения сертификата.
5. **Используйте `kubectl top node`** для быстрой оценки потребления ресурсов узла.

---

## Дополнительная информация

### Полезные команды диагностики

```bash
# Логи kubelet в реальном времени
journalctl -u kubelet -f

# Просмотр conditions узла
kubectl get node <name> -o yaml | grep -A 10 "conditions:"

# Проверка связности Kubelet <-> Runtime
sudo crictl info

# Проверка версии kubelet
kubelet --version

# Проверка конфигурации
cat /var/lib/kubelet/config.yaml

# Проверка healthz endpoint
curl -s http://127.0.0.1:10248/healthz
# → ok

# Проверка подов на узле через Kubelet API
curl -sk https://127.0.0.1:10250/pods | jq '.items | length'

# Проверка метрик Kubelet
curl -sk https://127.0.0.1:10250/metrics | grep -E "^process_|^kubelet_"
```

### Смежные разделы

- [Диагностика узла](./diagnostics.md) — системный алгоритм поиска проблем.
- [Проблемы рантайма](./runtime_issues.md) — если причина в `containerd`/`CRI-O`.
- [Давление ресурсов](./resource_pressure.md) — влияние Memory/Disk Pressure.
- [Управление сертификатами](../../../Operations/certificate_management.md) — детали ротации.
