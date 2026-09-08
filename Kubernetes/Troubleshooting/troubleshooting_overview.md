# Поиск и устранение неисправностей в Kubernetes

## Определения

**Траблшутинг (Troubleshooting) Kubernetes** — систематический процесс диагностики и устранения неисправностей в работе подов (Pods), сервисов (Services), узлов (Nodes) и компонентов управления (Control Plane). Включает идентификацию корневой причины сбоев, анализ их воздействия на систему и применение корректирующих мер для восстановления работоспособности.

**Root Cause Analysis (RCA)** — методология глубокого анализа инцидентов, направленная на выявление не симптомов, а фундаментальных причин сбоя. В контексте Kubernetes RCA предполагает последовательное исключение проблем на всех уровнях абстракции: от прикладного кода до инфраструктуры хостов.

** Observability (Наблюдаемость)** — способность системы раскрывать своё внутреннее состояние через внешние проявления: логи (logs), метрики (metrics) и трассировки (traces). Для эффективного траблшутинга необходима все три составляющая Observability, так как каждая из них отвечает на свой класс вопросов.

**SLO-based Troubleshooting** — подход к диагностике, при котором приоритет определяется влиянием на Service Level Objectives. Инциденты, угрожающие SLO (availability, latency, error rate), получают наивысший приоритет.

---

## Основные концепции

### Ключевые области диагностики

Траблшутинг в Kubernetes традиционно разделяется на пять критических направлений:

*   **Сбои приложений:** Ошибки запуска, циклическая перезагрузка, неверная конфигурация или утечки ресурсов внутри контейнеров. Часто проявляются как `CrashLoopBackOff`, `OOMKilled`, `ImagePullBackOff`.
*   **Состояние узлов (Nodes):** Недоступность рабочих узлов, нехватка ресурсов (Pressure), проблемы рантайма (CRI) или системные ошибки ОС. Проявляется как `NodeNotReady`, `Evicted`, `ContainerRuntimeUnhealthy`.
*   **Сетевое взаимодействие:** Ошибки маршрутизации трафика, проблемы DNS, блокировки NetworkPolicy или сбои в Service Mesh. Проявляется как `ConnectionTimeout`, `DNSResolutionFailed`, `502 Bad Gateway`.
*   **Управление ресурсами (RBAC, Quotas):** Нарушения контроля доступа, нехватка квот, конфликты LimitRange. Проявляется как `Forbidden`, `ExceededQuota`, `Insufficient cpu`.
*   **Хранение данных (Storage):** Проблемы с Provisioning PVC, монтированием Volume, деградацией storage-провайдеров. Проявляется как `VolumeBindingPending`, `FailedMount`, `Unable to attach`.

### Классификация ошибок по уровням

| Уровень | Ошибки | Ссылки на руководства |
|:---|:---|:---|
| **Планирование** | `Pending` | [Ошибки планирования](./Common_Errors/pod_pending/definitions_and_concepts.md) |
| **Конфигурация** | `ImagePullBackOff`, `CreateContainerConfigError` | [Ошибки образов](./Common_Errors/PodImagePullErrors/definitions.md), [Ошибки конфигурации](./Common_Errors/CreateContainerConfigError/definitions.md) |
| **Запуск приложения** | `CrashLoopBackOff`, `OOMKilled` | [Циклические перезапуски](./Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md), [Нехватка памяти (OOMKilled)](./Common_Errors/oomkilled_pods.md) |
| **Работоспособность** | `Liveness/Readiness Probe Failed` | [Диагностика проб](../Base/probes.md#диагностика-и-устранение-неисправностей) |
| **Ресурсы узла** | `Evicted`, `NodeNotReady` | [Выселение подов](./Common_Errors/PodEvicted/definitions.md), [Недоступность узла](./Common_Errors/NodeUnavailability/definitions.md) |
| **Безопасность** | `Forbidden`, `Unauthorized` | [Ошибки доступа (RBAC)](./Common_Errors/ApiAccessForbidden/definitions.md) |
| **Завершение** | `Terminating` | [Проблемы удаления подов](./Common_Errors/PodTerminating/definitions.md) |
| **Ресурсы** | `CPUThrottling`, `MemoryPressure` | [Троттлинг CPU](./Common_Errors/cpu_throttling.md) |

### Рабочий процесс диагностики

Для эффективного поиска причины рекомендуется последовательно проверять уровни абстракции:

**Уровень 1: Быстрый обзор кластера**
```bash
# Состояние всех узлов
kubectl get nodes -o wide
# → NAME     STATUS   ROLES    AGE   VERSION   INTERNAL-IP     OS-IMAGE
# → node-1   Ready    master   45d   v1.29.3   192.168.1.10    Ubuntu 22.04.3 LTS

# Состояние всех подов в системном namespace
kubectl get pods -n kube-system
# → NAME                                       READY   STATUS    RESTARTS   AGE
# → coredns-76f75df554-x2j9k                   1/1     Running   0          45d

# Быстрая статистика по namespace
kubectl get pods --all-namespaces | grep -v Running | grep -v Completed
```

**Уровень 2: Детализация по конкретному ресурсу**
```bash
# Проверка статуса, меток, IP-адреса и узла (Node)
kubectl get pods -o wide
# → NAME  READY  STATUS   RESTARTS  AGE  IP           NODE
# → app   1/1    Running  0         5m   10.244.1.5   worker-1

# Хронологический список событий. Часто информативнее, чем `describe`
kubectl get events --sort-by='.lastTimestamp' --field-selector type=Warning
# → 45s  Warning  FailedScheduling  pod/app  0/3 nodes are available: 3 Insufficient cpu.
```

**Уровень 3: Глубокий анализ**
```bash
# Детальный анализ жизненного цикла пода и раздел Events
kubectl describe pod <pod-name>
# → Events:
#   Type    Reason     Age   From               Message
#   ----    ------     ----  ----               -------
#   Normal  Scheduled  1m    default-scheduler  Successfully assigned default/app to worker-1
#   Normal  Pulling    1m    kubelet            Pulling image "nginx:1.25"

# Просмотр логов в реальном времени
kubectl logs <pod-name> --tail=100 -f
# Флаг --previous (-p) нужен, если контейнер перезапустился
kubectl logs my-app -p
# → panic: runtime error: invalid memory address or nil pointer dereference
```

**Уровень 4: Интерактивная отладка**
```bash
# Использование специализированных отладочных образов (например, netshoot)
kubectl debug -it <pod-name> --image=nicolaka/netshoot
# → root@debug-container:/# tcpdump -i eth0 -nn port 53
```

### Алгоритм поиска: общая методология

```
1. Определить симптом (что не работает?)
   ↓
2. Проверить Namespace и Object (где проблема?)
   ↓
3. Проверить события (kubectl describe, events)
   ↓
4. Проверить логи (kubectl logs, --previous)
   ↓
5. Проверить конфигурацию (манифест, env, secrets)
   ↓
6. Проверить ресурсы (limits, requests, node capacity)
   ↓
7. Проверить сеть (DNS, endpoints, network policies)
   ↓
8. Проверить storage (PVC, PV, mount issues)
   ↓
9. Проверить control plane (API server, etcd, scheduler)
   ↓
10. Проверить инфраструктуру (узел, ОС, runtime)
```

### Быстрая диагностика по статусу

| Статус пода | Рекомендуемая команда | Вероятная причина |
|:---|:---|:---|
| `Pending` | `kubectl describe pod` | Нехватка ресурсов, Taints, Affinity, ошибки PVC |
| `ContainerCreating` | `kubectl describe pod` | Проблемы монтирования Volume, загрузки образа, CNI |
| `ImagePullBackOff` | `kubectl logs` (если возможно) | Неверные `imagePullSecrets`, ошибка в имени образа |
| `ErrImagePull` | `kubectl describe pod`, логи рантайма | Ошибка сети, DNS, аутентификации или отсутствие образа |
| `CrashLoopBackOff` | `kubectl logs --previous` | Ошибка приложения (exit code > 0), отсутствие конфигов |
| `OOMKilled` | `kubectl top pod` | Превышение лимитов (Limits). Exit Code: 137 |
| `Evicted` | `kubectl describe node` | DiskPressure (нехватка места) или MemoryPressure на узле |
| `Terminating` | `kubectl get pod -o yaml` | Finalizers в метаданных, зависшие процессы в контейнере |
| `CreateContainerConfigError` | `kubectl describe pod` | Ошибка в ConfigMap/Secret, отсутствие Volume |
| `SandboxCreateError` | `kubectl describe pod`, логи CNI | Проблемы с CNI-плагином, конфликт network namespace |

### Алгоритм диагностики: поды не могут загрузить образ

Когда поды находятся в статусе `ErrImagePull` или `ImagePullBackOff` с ошибкой, связанной с сетью или DNS:

**Шаг 1: Первичная диагностика**
```bash
kubectl describe pod <pod-name> -n <namespace>
```
Обратить внимание на секцию `Events`:
- `Failed to pull image "..."`: rpc error: code = Unknown desc = ...
- `dial tcp: lookup registry.example.com: no such host` — проблема DNS
- `deadline exceeded` — проблема сети/доступности

**Шаг 2: Проверка DNS внутри кластера**
```bash
# Запуск тестового пода для проверки DNS
kubectl run dns-test --image=busybox --rm -it --restart=Never -- nslookup registry.example.com

# Если nslookup не работает — проблема с CoreDNS или NodeLocal DNSCache
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns
```

**Шаг 3: Проверка NodeLocal DNSCache**
```bash
# Статус DaemonSet
kubectl get daemonset -n kube-system node-local-dns

# Логи подов NodeLocal DNSCache
kubectl logs -n kube-system -l k8s-app=node-local-dns --tail=50

# Если поды на конкретных нодах в ошибке:
kubectl get pods -n kube-system -l k8s-app=node-local-dns -o wide
```

**Шаг 4: Проверка сетевой связности**
```bash
# Запуск отладочного контейнера в сетевом пространстве имен ноды
kubectl debug node/<node-name> -it --image=nicolaka/netshoot
# Внутри:
nslookup registry.example.com
curl -v https://registry.example.com/v2/
```

**Шаг 5: Проверка NetworkPolicy**
```bash
# Убедиться, что трафик к DNS (порт 53) разрешен
kubectl get networkpolicy -A
```

**Типичные проблемы и решения:**

| Проблема | Причина | Решение |
|:---|:---|:---|
| `no such host` | DNS не резолвит имя реестра | Проверить CoreDNS, NodeLocal DNSCache |
| `connection timed out` | Реестр недоступен | Проверить Firewall, Security Groups |
| `i/o timeout` | Медленная сеть или большие слои | Настроить таймауты или зеркало реестра |
| TLS ошибки | Проблемы с сертификатами | Добавить CA в доверенные на узлах |
| `unauthorized` | Неверные credentials | Проверить imagePullSecrets и RBAC |

### Диагностика сетевого взаимодействия

Проблемы с сетью часто проявляются как ошибки **502 Bad Gateway** или **Connection Timeout**.

**Цепочка проверок:**

1. **Состояние Service и Endpoints:** Убедитесь, что селекторы Service совпадают с метками подов. Подробные сценарии см. в разделе **[Устранение неполадок Service](../Networking/Service/service_practical_scenarios.md#устранение-неполадок-troubleshooting)**.
   ```bash
   kubectl get endpoints <service-name>
   # → NAME      ENDPOINTS            AGE
   # → my-svc    10.244.1.5:8080      1h
   
   # Проверка совпадения селекторов
   kubectl get svc <service-name> -o yaml | grep -A5 selector
   kubectl get pods -l <selector-key>=<selector-value>
   ```

2. **DNS внутри кластера:** Проверьте разрешение имен через `CoreDNS`. Подробный алгоритм диагностики см. в разделе **[Диагностика DNS](../Networking/dns_deep_dive.md#диагностика-и-устранение-неполадок)**.
   ```bash
   kubectl exec -it <pod-name> -- nslookup kubernetes.default
   # → Server: 10.96.0.10
   # → Address: 10.96.0.10#53
   # → Name: kubernetes.default.svc.cluster.local
   # → Address: 10.96.0.1
   ```

3. **NetworkPolicy:** Проверьте, не блокирует ли трафик объект `NetworkPolicy`.
   ```bash
   kubectl get networkpolicy -A
   # Детальный анализ политик
   kubectl describe networkpolicy <policy-name> -n <namespace>
   ```

4. **Пробы готовности (Readiness Probes):** Если под не прошел пробу, он удаляется из Endpoints, и трафик на него не идет. Подробнее в разделе **[Диагностика и устранение неисправностей проб](../Base/probes.md#диагностика-и-устранение-неисправностей)**.

5. **Проверка kube-proxy и iptables/nftables:**
   ```bash
   # Проверка режима kube-proxy
   kubectl -n kube-system get configmap kube-proxy -o yaml | grep -A5 mode
   
   # Проверка правил (на узле)
   sudo iptables -t nat -L KUBE-SERVICES | grep <service-ip>
   sudo nft list ruleset | grep <service-ip>
   ```

6. **Проверка EndpointSlices:**
   ```bash
   kubectl get endpointslices -l kubernetes.io/service-name=<service-name>
   # → NAME              ENDPOINTS            AGE
   # → my-svc-abc123     10.244.1.5:8080      1h
   ```

### Диагностика уровня узла (Node)

Если проблема не в подах, необходимо проверить состояние `Kubelet` и системные ресурсы узла.

**Быстрый обзор:**
```bash
# Статус узла с условиями
kubectl describe node <node-name> | grep -A10 Conditions
# → Conditions:
#   Type             Status  LastHeartbeatTime                 Reason                       Message
#   ----             ------  -----------------                 ------                       -------
#   MemoryPressure   False   Wed, 05 Sep 2026 10:00:00 UTC   KubeletHasMemory             kubelet has memory available
#   DiskPressure     False   Wed, 05 Sep 2026 10:00:00 UTC   KubeletHasDisk               kubelet has no disk pressure
#   PIDPressure      False   Wed, 05 Sep 2026 10:00:00 UTC   KubeletHasPodPIDs            kubelet has sufficient PID available
#   Ready            True    Wed, 05 Sep 2026 10:00:00 UTC   KubeletReady                 kubelet is posting ready status
```

**Проверка ресурсов узла:**
```bash
# Использование ресурсов (требует Metrics Server)
kubectl top node
# → NAME    CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → node-1  150m         4%     1200Mi          15%

# Детальное описание с_allocatable资源
kubectl describe node <node-name> | grep -A20 Allocatable
# → Allocatable:
#   cpu:                4
#   ephemeral-storage:  101823660Ki
#   hugepages-1Gi:      0
#   hugepages-2Mi:      0
#   memory:             16385408Ki
#   pods:               110
```

**Логи Kubelet:**
```bash
# Выполняется на узле
journalctl -u kubelet -f --no-pager | tail -100
# Или для конкретного времени
journalctl -u kubelet --since "1 hour ago" | grep -i error
```

**Проверка контейнерного рантайма (CRI):**
```bash
# Использование crictl (универсальный инструмент)
crictl ps
# → CONTAINER ID   IMAGE          CREATED         STATE    NAME             ATTEMPT   POD ID
# → abc123def456   nginx:1.25     5 minutes ago  Running  nginx            0         xyz789

crictl pods
# → POD ID         BANDWIDTH   NAMESPACE   NAME                      READY   STATUS    CREATED
# → xyz789         default     my-app      my-app-6d4f5b7c8-x2j9k   true    Running   5 minutes ago

crictl logs <container-id>
# → 2026/09/05 10:00:00 [notice] 1#1: signal process started
```

**Проверка системных ресурсов (на узле):**
```bash
# Дисковое пространство
df -h
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1        50G   35G   13G  73% /

# Свободная память
free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:          15Gi       5.2Gi       8.1Gi       256Mi       2.1Gi       9.5Gi
# → Swap:            0B          0B          0B

# Процессы по потреблению CPU
ps aux --sort=-%cpu | head -10

# Процессы по потреблению памяти
ps aux --sort=-%mem | head -10
```

### Диагностика компонентов управления (Control Plane)

Проблемы с API-сервером, планировщиком (Scheduler) или контроллерами обычно влияют на весь кластер.

**Проверка подов системы:**
```bash
kubectl get pods -n kube-system
# → NAME                                       READY   STATUS    RESTARTS   AGE
# → coredns-76f75df554-x2j9k                   1/1     Running   0          45d
# → etcd-master-1                               1/1     Running   0          45d
# → kube-apiserver-master-1                     1/1     Running   0          45d
# → kube-controller-manager-master-1            1/1     Running   0          45d
# → kube-proxy-7x2k4                            1/1     Running   0          45d
# → kube-scheduler-master-1                     1/1     Running   0          45d
```

**Логи статических подов:**
```bash
# Если кластер развернут через kubeadm
kubectl logs -n kube-system kube-apiserver-master-1 --tail=100
kubectl logs -n kube-system kube-controller-manager-master-1 --tail=100
kubectl logs -n kube-system kube-scheduler-master-1 --tail=100

# Или через journalctl на master-узле
sudo journalctl -u kubelet -f
```

**Состояние etcd:**
```bash
# Проверка доступности etcd (на master-узле)
sudo ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# Проверка кворума
sudo ETCDCTL_API=3 etcdctl endpoint status \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
  --write-out=table
# → ENDPOINT                    DB SIZE   IN USE   DB SIZE IN USE   QUOTA   DB SIZE IN USE   DB VERSION   IS LEADER   IS LEARNER   RAFT TERM   RAFT INDEX   RAFT APPLIED INDEX   ERRORS
# → https://127.0.0.1:2379     15 MB     4.0 MB   26%              8.6 GB  26%              3.5.5        true        false        8           12345        12345               

# Проверка свободного места для etcd
sudo du -sh /var/lib/etcd
# → 15M    /var/lib/etcd
```

**Проверка healthz/livez/readyz эндпоинтов API-сервера:**
```bash
# Базовая проверка
curl -k https://<master-ip>:6443/livez?verbose
# → [+]ping ok
# → [+]etcd ok
# → [+]poststarthook/start-kube-apiserver-admission-initializer ok
# → ...

# Детальная проверка
curl -k https://<master-ip>:6443/readyz?verbose
```

### Диагностика квот и лимитов ресурсов

Проблемы с квотами и лимитами часто приводят к блокировке создания подов или их выселению.

**Проверка ResourceQuota:**
```bash
# Все квоты в namespace
kubectl get resourcequota -n <namespace>
# → NAME       AGE   REQUEST                 LIMIT
# → compute    45d   requests.cpu: 4/8       limits.cpu: 8/16
# →                    requests.memory: 8Gi/16Gi  limits.memory: 16Gi/32Gi

# Детали конкретной квоты
kubectl describe resourcequota compute -n <namespace>
# → Name:                   compute
# → Resource                Used    Hard
# ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
# → requests.cpu            4       8
# → requests.memory         8Gi     16Gi
# → limits.cpu              8       16
# → limits.memory           16Gi    32Gi
# → pods                    12      20
```

**Проверка LimitRange:**
```bash
kubectl get limitrange -n <namespace>
kubectl describe limitrange <limitrange-name> -n <namespace>
# → Type        Resource  Min   Max   Default Request  Default Limit  Max Limit/Request Ratio
# ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
# → Container   cpu       -     2     100m             500m           -
# → Container   memory    -     1Gi   128Mi            512Mi          -
```

**Типичные ошибки квот:**
```bash
# При попытке создать под превышающий квоту
# Error from server (Forbidden): pods "my-pod" is forbidden: exceeded quota: compute, 
# requested: requests.cpu=2, used: requests.cpu=4, limited: requests.cpu=8

# Решение: уменьшить requests или увеличить квоту
kubectl patch resourcequota compute -n <namespace> \
  --type='json' \
  -p='[{"op": "replace", "path": "/spec/hard/requests.cpu", "value": "16"}]'
```

### Диагностика RBAC

Проблемы с разрешениями — одна из самых частых причин ошибок `Forbidden`.

**Проверка разрешений:**
```bash
# Проверка, может ли конкретный пользователь/ServiceAccount выполнять операцию
kubectl auth can-i create deployments --as system:serviceaccount:default:my-sa
# → yes

kubectl auth can-i create deployments --as system:serviceaccount:default:my-sa -n production
# → no

# Список всех доступных операций для ServiceAccount
kubectl auth can-i --list --as system:serviceaccount:default:my-sa
# → Resources   Non-Resource URLs   Resource Names   Verbs
# → pods.*                                    [get list watch create delete]
# → deployments.apps                         [get list watch]
```

**Проверка RoleBinding и ClusterRoleBinding:**
```bash
# RoleBinding в namespace
kubectl get rolebindings -n <namespace>
kubectl describe rolebinding <binding-name> -n <namespace>

# ClusterRoleBinding (глобальные)
kubectl get clusterrolebindings | grep <service-account-name>
```

### Диагностика Storage

Проблемы с хранилищем данных часто проявляются как `Pending` поды или `FailedMount` ошибки.

**Проверка PVC и PV:**
```bash
# Статус PVC
kubectl get pvc -n <namespace>
# → NAME      STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS      AGE
# → data-pvc  Bound    pvc-abc123def456                           10Gi       RWO            local-path        45d

# Статус PV
kubectl get pv
# → NAME                                       CAPACITY   RECLAIM POLICY   STATUS   CLAIM                  STORAGECLASS      REASON   AGE
# → pvc-abc123def456                           10Gi       Delete           Bound    default/data-pvc       local-path                  45d

# Детали проблемного PVC
kubectl describe pvc <pvc-name> -n <namespace>
# → Events:
# → Type    Reason                 Age   From                         Message
# → ----    ------                 ----  ----                         -------
# → Normal  ExternalProvisioning   1m    persistentvolume-controller  waiting for a volume to be created...
```

**Проверка StorageClass:**
```bash
kubectl get storageclass
# → NAME                   PROVISIONER                    RECLAIMPOLICY   VOLUMEBINDINGMODE   ALLOWVOLUMEEXPANSION   AGE
# → local-path (default)   rancher.io/local-path          Delete          WaitForFirstConsumer   false                45d
```

**Диагностика на узле:**
```bash
# Проверкамонтирования volumes
mount | grep -E "kubelet|kubernetes"

# Проверка логов kubelet по storage
sudo journalctl -u kubelet | grep -i "volume\|mount\|storage" | tail -20
```

### Диагностика NetworkPolicy

NetworkPolicy могут блокировать легитимный трафик, если настроены некорректно.

**Проверка политик:**
```bash
# Список всех политик
kubectl get networkpolicy -A
# → NAMESPACE    NAME                      POD-SELECTOR   AGE
# → default      default-deny-all          <none>         45d
# → production   allow-web-to-api          app=web        10d

# Детали конкретной политики
kubectl describe networkpolicy <policy-name> -n <namespace>
# → Spec:
# →   PodSelector:     app=web
# →   PolicyTypes:
# →     Ingress
# →     Egress
# →   Ingress:
# →     From:
# →       - PodSelector:
# →           MatchLabels:
# →             app: api
# →     To:
# →       - Port:
# →           Protocol: TCP
# →           Port: 8080
```

**Тестирование連通性 через эфемерные контейнеры:**
```bash
# Запуск отладочного контейнера для проверки сети
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>
# Внутри контейнера:
curl -v http://<service-name>.<namespace>.svc.cluster.local:8080
nc -zv <service-name> 80
dig <service-name>.<namespace>.svc.cluster.local
```

---

## Основные инструменты командной строки

#### kubectl describe: Детальный статус ресурсов

Предоставляет текущее состояние, лимиты, назначенные ресурсы и хронологический список событий.
- **Exit Code 137:** процесс убит по OOM (Out Of Memory).
- **Exit Code 143:** корректное завершение по сигналу SIGTERM.
- **Exit Code 1:** общая ошибка приложения (часто конфигурационная).
- **Exit Code 2:** ошибка использования командной строки.

#### kubectl logs: Анализ вывода приложения

Позволяет просматривать `stdout` и `stderr`.
- `-l app=nginx`: логи всех подов с определенной меткой.
- `--all-containers`: для подов с sidecar-контейнерами.
- `--previous` или `-p`: логи предыдущего экземпляра контейнера (при перезапуске).
- `--since=1h`: логи за последний час.
- `--timestamps`: добавление временных меток.

```bash
# Просмотр логов конкретного контейнера в multi-container поде
kubectl logs <pod-name> -c <container-name>

# Просмотр логов всех контейнеров в поде
kubectl logs <pod-name> --all-containers

# Просмотр логов с фильтрацией по времени
kubectl logs <pod-name> --since=2h | grep -i error
```

#### kubectl exec и kubectl debug: Интерактивная отладка

**kubectl exec** — выполнение команд в работающем контейнере:
```bash
kubectl exec -it <pod-name> -- /bin/sh
kubectl exec -it <pod-name> -c <container-name> -- /bin/sh
```

**kubectl debug** — подключение эфемерных контейнеров для отладки:
```bash
# Базовая отладка с netshoot
kubectl debug -it <pod-name> --image=nicolaka/netshoot

# Отладка с целевым контейнером
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>

# Отладка с копированием пода (сохранение оригинала)
kubectl debug <pod-name> -it --copy-to=debug-pod --container=<container-name>

# Отладка узла
kubectl debug node/<node-name> -it --image=ubuntu:24.04 --profile=sysadmin
```

**Профили отладки (v1.30+):**
- `baseline` — минимальные разрешения (по умолчанию)
- `restricted` — безопасный профиль для production
- `sysadmin` — полный доступ (только для отладки узлов)

#### kubectl auth can-i: Проверка разрешений

Незаменимо для отладки проблем с RBAC (Role-Based Access Control).
```bash
kubectl auth can-i create deployments --as system:serviceaccount:default:my-sa
# → yes

kubectl auth can-i list pods --as system:serviceaccount:default:my-sa -n production
# → no

kubectl auth can-i --list --as system:serviceaccount:default:my-sa
# → Resources   Verbs
# → pods        [get list watch create delete]
```

#### kubectl top: Мониторинг ресурсов

Требует установленного `Metrics Server`.
```bash
kubectl top node
# → NAME    CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → node-1  150m         4%     1200Mi          15%

kubectl top pod -n <namespace> --sort-by=memory
# → NAME                    CPU(cores)   MEMORY(bytes)
# → my-app-6d4f5b7c8-x2j9k 50m          256Mi
# → sidecar-logger          10m          64Mi
```

#### cAdvisor: Низкоуровневая диагностика

Встроенный в `kubelet` агент (**Container Advisor**), собирающий детальную статистику ресурсов по каждому контейнеру.
- **Применение:** Диагностика аварий контейнеров (Crash Diagnostics), анализ троттлинга CPU и использования памяти на микро-уровне.
- **Доступ:** Через API kubelet (`/metrics/cadvisor`) или системы мониторинга (Prometheus).

```bash
# Прос метрик cAdvisor через API kubelet (на узле)
curl -s http://localhost:10255/metrics/cadvisor | head -20
```

#### crictl: Диагностика контейнерного рантайма

Универсальный инструмент для работы с CRI (Container Runtime Interface) напрямую.
```bash
# Список контейнеров
crictl ps

# Список подов
crictl pods

# Логи контейнера
crictl logs <container-id>

# Информация о контейнере
crictl inspect <container-id>

# Остановка и удаление контейнера
crictl stop <container-id>
crictl rm <container-id>
```

#### kubectx и kubens: Управление контекстами

Удобные утилиты для быстрого переключения между контекстами и namespace.
```bash
# Установка
brew install kubectx kubens

# Переключение контекста
kubectx <context-name>

# Переключение namespace
kubens <namespace-name>

# Список доступных контекстов
kubectx
```

---

## Практические сценарии

### Изоляция пода для отладки

Удаление меток (labels) позволяет временно "спрятать" под от трафика Service для детального изучения.
```bash
kubectl label pod <pod-name> app-
# → pod/my-app labeled (метка 'app' удалена)

# Проверка, что под исключен из Endpoints
kubectl get endpoints <service-name>
```

### Предотвращение перезагрузки падающего пода

Если под постоянно падает, можно изменить `entrypoint` на `sleep`, чтобы войти внутрь и проверить конфигурацию.
```bash
kubectl patch deployment <deploy-name> \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","command":["sleep","3600"]}]}}}}'

# Проверка результата
kubectl get pods -l app=<app-label>
# → NAME                        READY   STATUS    RESTARTS   AGE
# → <deploy-name>-xxxxx         1/1     Running   0          30s
```

### Отладка приложения без логов (distroless-образы)

Для образов без shell и утилит (distroless, scratch) используется `kubectl debug` с эфемерными контейнерами:
```bash
# Запуск отладочного контейнера в том же пространстве имен (Network, PID)
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>

# Просмотр процессов целевого контейнера
# → root@debug-container:/# ps aux
# → USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
# → root         1  0.0  0.0  12345 6789 ?        Ss   10:00   0:00 /app/server

# Проверка сетевой связности
# → root@debug-container:/# curl -v http://localhost:8080/health
```

### Сбор дампов при ошибках

Для анализа состояния приложения в момент сбоя:
```bash
# Запуск отладочного контейнера с копированием пода
kubectl debug <pod-name> -it --copy-to=debug-pod \
  --container=<container-name> --profile=sysadmin

# Внутри контейнера можно собрать:
# - Дампы процессов (ps aux)
# - Сетевую информацию (ss -tlnp, ip route)
# - Файловую систему (ls -la /app/, cat /app/config.yaml)
# - Логи приложения (если есть доступ к файлам)
```

### Диагностика зависшего Rollout

Когда обновление Deployment зависло и не завершается:
```bash
# Проверка статуса rollout
kubectl rollout status deployment/<deploy-name>
# → error: deployment "my-app" exceeded its progress deadline

# История версий
kubectl rollout history deployment/<deploy-name>
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         kubectl apply --filename=deployment.yaml --record=true

# Откат к предыдущей версии
kubectl rollout undo deployment/<deploy-name>
# → deployment.apps/my-app rolled back

# Или к конкретной ревизии
kubectl rollout undo deployment/<deploy-name> --to-revision=1
```

### Экстренное масштабирование

При критических проблемах с производительностью:
```bash
# Быстрое масштабирование вверх
kubectl scale deployment <deploy-name> --replicas=10

# Или через patch
kubectl patch deployment <deploy-name> \
  -p '{"spec":{"replicas":10}}'

# Масштабирование вниз (при проблемах)
kubectl scale deployment <deploy-name> --replicas=0
kubectl scale deployment <deploy-name> --replicas=2
```

### Проверка и восстановление после инцидента

```bash
# 1. Проверка состояния всех компонентов
kubectl get pods -A | grep -v Running | grep -v Completed
kubectl get nodes
kubectl get events --sort-by='.lastTimestamp' --field-selector type=Warning | head -20

# 2. Проверка ресурсов
kubectl top nodes
kubectl top pods -A --sort-by=memory | head -20

# 3. Проверка квот
kubectl get resourcequota -A

# 4. Проверка storage
kubectl get pvc -A | grep -v Bound
kubectl get pv | grep -v Bound
```

### Мониторинг в реальном времени

```bash
# Следить за событиями в реальном времени
kubectl get events --watch

# Мониторинг подов
watch -n 2 kubectl get pods -o wide

# Мониторинг узлов
watch -n 5 kubectl get nodes

# Мониторинг ресурсов
watch -n 10 kubectl top pods -A
```

---

## Дополнительная информация

### Продвинутые методы отладки

- **Трассировка системных вызовов:** использование `strace` или `tcpdump` через привилегированные контейнеры или `kubectl debug`.
  ```bash
  # Трассировка сетевых пакетов
  kubectl debug node/<node-name> -it --image=nicolaka/netshoot
  # → tcpdump -i any -nn port 80
  
  # Трассировка системных вызовов
  kubectl debug node/<node-name> -it --image=ubuntu:24.04 --profile=sysadmin
  # → strace -p <pid> -e trace=network
  ```

- **Remote Debugging:** проброс портов для подключения IDE к процессу внутри контейнера.
  ```bash
  kubectl port-forward pod/<pod-name> 5005:5005
  # Теперь можно подключить отладчик IDE к localhost:5005
  ```

- **Анализ профилей производительности:** сбор CPU и memory профилей через pprof.
  ```bash
  # Запуск отладочного контейнера с инструментами профилирования
  kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>
  # → curl -o cpu.prof http://localhost:6060/debug/pprof/profile?seconds=30
  # → curl -o mem.prof http://localhost:6060/debug/pprof/heap
  ```

### Типичные ошибки и их решения

| Ошибка | Вероятная причина | Решение |
|:---|:---|:---|
| `0/3 nodes are available: 3 Insufficient cpu` | Нехватка CPU на узлах | Уменьшить requests или добавить узлы |
| `0/3 nodes are available: 3 node(s) had taint` | Taints на узлах без Tolerations | Добавить Tolerations или убрать Taints |
| `FailedMount` | Volume не может быть смонтирован | Проверить доступность Volume, права доступа |
| `Unhealthy` | Liveness/Readiness Probe не проходит | Проверить доступность эндпоинта пробы |
| `Back-off restarting failed container` | Приложение падает при запуске | Проверить логи `kubectl logs --previous` |
| `net/http: TLS handshake timeout` | Проблемы с TLS-сертификатами | Проверить CA, сертификаты, clock skew |

### Инструменты мониторинга и алертинга

Для эффективного траблшутинга необходима настроенная Observability:

- **Prometheus** — сбор и хранение метрик
- **Grafana** — визуализация и дашборды
- **Alertmanager** — алертинг и уведомления
- **Loki** — агрегация логов
- **Jaeger/Tempo** — трассировка запросов

**Примеры полезных алертов:**
```yaml
# Алерт на CrashLoopBackOff
- alert: PodCrashLooping
  expr: rate(kube_pod_container_status_restarts_total[15m]) > 0
  for: 5m
  labels:
    severity: warning

# Алерт на MemoryPressure
- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: critical

# Алерт на DiskPressure
- alert: NodeDiskPressure
  expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
  for: 5m
  labels:
    severity: critical
```

---

### Диагностика тормозящего приложения с HPA (комплексный кейс)

**Симптомы:** Приложение в Kubernetes с настроенным HPA постоянно тормозит, потребляет все доступные ресурсы (CPU/Memory), горизонтальное масштабирование не помогает или усугубляет ситуацию.

#### Пошаговый алгоритм диагностики

**1. Быстрая триада: HPA → Метрики → Поды**
```bash
# 1. Статус HPA
kubectl describe hpa <hpa-name>
# → Conditions: AbleToScale, ScalingActive, ScalingLimited
# → TARGETS: <unknown> или реальные значения

# 2. Реальное потребление подов
kubectl top pods -l app=<name> --containers --sort-by=memory
kubectl top pods -l app=<name> --containers --sort-by=cpu

# 3. События HPA
kubectl get events --field-source horizontal-pod-autoscaler -A --sort-by='.lastTimestamp' | tail -20
```

**2. Проверка конфигураций (что проверять в манифестах)**

| Проверка | Команда | Что искать |
|----------|---------|------------|
| `resources.requests` у **всех** контейнеров | `kubectl get deploy <name> -o jsonpath='{.spec.template.spec.containers[*].resources.requests}'` | Отсутствие requests у sidecar (istio-proxy, vault-agent) → `<unknown>` в HPA |
| `limits` vs `requests` ratio | `kubectl get deploy <name> -o jsonpath='{.spec.template.spec.containers[*].resources.limits}'` | Limits без requests (Burstable QoS) → непредсказуемое троттлинг |
| HPA `behavior` секция | `kubectl get hpa <name> -o yaml \| yq '.spec.behavior'` | Отсутствие `stabilizationWindowSeconds` → дребезг |
| HPA метрика | `kubectl get hpa <name> -o yaml \| yq '.spec.metrics'` | CPU для latency-bound приложения → HPA «спит» при высокой latency |
| `minReplicas` / `maxReplicas` | `kubectl get hpa <name> -o yaml \| yq '.spec.minReplicas,.spec.maxReplicas'` | `minReplicas: 1` в prod → холодный старт; `maxReplicas` > емкости кластера → Pending |
| PDB конфликт | `kubectl get pdb -A \| grep <app>` | `minAvailable` > HPA `minReplicas` → нарушение доступности |

**3. Диагностика на ноде (что проверять на узле)**

```bash
# На проблемном узле (где запущены поды приложения):

# 1. Условия узла
kubectl describe node <node-name> | grep -A10 Conditions
# → MemoryPressure, DiskPressure, PIDPressure — должны быть False

# 2. Ресурсы узла (allocatable vs capacity)
kubectl describe node <node-name> | grep -A15 Allocatable
kubectl top node <node-name>

# 3. Топ процессы по CPU/MEM на узле
ps aux --sort=-%cpu | head -15
ps aux --sort=-%mem | head -15

# 4. cgroup статистика подов (на узле)
crictl stats $(crictl pods --name <pod-name> -q)
# → CPU%, MEM%, CPU Throttled time

# 5. dmesg / journalctl — системные события
dmesg -T | grep -i -e oom -e kill -e throttle -e cgroup
journalctl -u kubelet --since "30 minutes ago" | grep -i -e oom -e evict -e throttle -e "memory pressure"

# 6. PSI (Pressure Stall Information) — давление ресурсов
cat /proc/pressure/cpu
cat /proc/pressure/memory
cat /proc/pressure/io
# avg10 > 10% (cpu), > 5% (mem/io) = проблема

# 7. CFS Throttling (CPU квоты)
cat /sys/fs/cgroup/cpu/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod<pod_uid>.slice/cpu.stat
# nr_throttled, throttled_time — если растут = троттлинг
```

**4. Сценарии и решения по попутным вопросам**

---

**🔵 Вопрос: «Я увеличил ресурсы и лимиты по CPU и памяти. 15 минут всё работало нормально, а потом опять всё упало. Что делать?»**

**Диагностика:**
```bash
# 1. Проверка утечки памяти (Memory Leak)
kubectl top pod <pod-name> --containers --sort-by=memory
# → MEMORY растёт монотонно во времени без плато

# 2. Проверка GC поведения (Java/Go/.NET)
# Java: -XX:+PrintGCDetails -Xlog:gc*
# Go: GODEBUG=gctrace=1
# .NET: COMPlus_GCVerbose=1

# 3. Page Cache давление (I/O bound)
cat /proc/pressure/memory
# some/avg10 > 50% = page cache eviction = latency spikes

# 4. HPA behavior — агрессивный scaleUp
kubectl get hpa <name> -o yaml | yq '.spec.behavior.scaleUp'
# percent: 100 за 15s = удвоение подов каждый цикл → CA не успевает
```

**Решения:**
1. **Профилирование приложения** (Pyroscope/Parca/pprof) — найти горячие пути и утечки
2. **Настроить `behavior.scaleUp`**: максимум +4 пода за 30 сек (`Pods: 4`, `periodSeconds: 30`)
3. **Добавить `cpu-initialization-period=10m`** в kube-controller-manager для медленного warmup
4. **Memory limits = requests (Guaranteed QoS)** — исключает OOMKilled от Burstable соседей
5. **JVM/Go tuning**: `-XX:MaxRAMPercentage=75`, `GOMEMLIMIT=0.8*limit`

---

**🔵 Вопрос: «Приложение последние 2 недели работало нормально, а потом стало так тормозить. Что делать?»**

**Диагностика изменений (Change Analysis):**
```bash
# 1. История деплоев
kubectl rollout history deployment/<name>
kubectl rollout history deployment/<name> --revision=<N>

# 2. События за последние дни
kubectl get events -A --sort-by='.lastTimestamp' | grep -E "<namespace>|<app-name>" | tail -50

# 3. Изменения ConfigMap/Secret
kubectl get cm,secret -n <namespace> -o yaml | grep -A5 -B5 "app-config\|feature-flag"

# 4. Метрики трендов (PromQL в Grafana)
# CPU usage trend 14d
rate(container_cpu_usage_seconds_total{namespace="ns",pod=~"app.*"}[1h])
# Memory working_set trend 14d
container_memory_working_set_bytes{namespace="ns",pod=~"app.*"}
# Request latency trend 14d
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{service="app"}[5m]))
# RPS trend 14d
sum(rate(http_requests_total{service="app"}[5m])) by (pod)

# 5. Внешние зависимости
# БД: долгие запросы, lock wait, vacuum
# Kafka: consumer lag
# Redis: memory fragmentation, evictions
```

**Типичные причины «вдруг сломалось»:**
| Причина | Признак | Решение |
|---------|---------|---------|
| **Новый деплой** (code/config) | Резкий скачок метрик в момент rollout | Rollback, бинарный поиск по ревизиям |
| **Feature flag** | Изменение поведения без деплоя | Отключить флаг, проверить логику |
| **Рост данных в БД** | Монотонный рост latency p99 | Индексы, партиционирование, архивирование |
| **Consumer lag (Kafka/Rabbit)** | RPS падает, lag растёт | Увеличить partitions/consumers, оптимизировать обработку |
| **Memory fragmentation** | RSS растёт, GOMEMLIMIT не помогает | Рестарт подов по расписанию, jemalloc/mimalloc |
| **Certificate rotation** | TLS handshake errors, latency | Проверить cert-manager, renewal timing |
| **Noisy neighbor** | Node CPU steal time ↑ | Топология spread, dedicated nodes |

---

**🔵 Вопрос: «Что проверять в конфигурациях?»**

```bash
# Чек-лист конфигураций (выполнять в CI/CD или вручную)

# 1. Deployment spec
kubectl get deploy <name> -o yaml > deploy.yaml
# Проверить:
# - resources.requests/limits (CPU, memory) — реалистичные, не завышенные
# - livenessProbe/readinessProbe/startupProbe — адекватные таймауты
# - terminationGracePeriodSeconds — >= 30s для graceful shutdown
# - podAntiAffinity / topologySpreadConstraints — не слишком строгие
# - priorityClassName — для критических сервисов

# 2. HPA spec
kubectl get hpa <name> -o yaml > hpa.yaml
# Проверить:
# - metrics.type: Resource (CPU) vs Pods (RPS/latency) vs External (KEDA)
# - behavior.scaleDown.stabilizationWindowSeconds >= 300
# - behavior.scaleUp.policies: Pods (не Percent) для предсказуемости
# - minReplicas >= 2 для HA

# 3. Service / Ingress
kubectl get svc,ingress -n <ns> -o yaml
# - sessionAffinity: None (если не нужно sticky)
# - timeout: 30s+ для тяжелых запросов

# 4. ResourceQuota / LimitRange
kubectl get resourcequota,limitrange -n <ns> -o yaml
# - quotas не блокируют масштабирование
# - default requests/limits не завышены

# 5. Node affinity / taints
kubectl get nodes -o yaml | grep -A10 -B5 "taint\|affinity"
```

---

**🔵 Вопрос: «Что проверять на ноде?»**

```bash
# Комплексная диагностика узла (выполнять на проблемном узле)

# 1. Kubelet условия
kubectl describe node <node> | grep -A10 Conditions
# MemoryPressure/DiskPressure/PIDPressure = True = проблема на узле

# 2. Ресурсы
kubectl top node <node>
kubectl describe node <node> | grep -A20 Allocatable

# 3. CRI (containerd/cri-o)
crictl ps -a | grep <app>
crictl stats $(crictl ps --name <app> -q)
crictl inspect <container-id> | jq '.info.runtimeSpec.linux.resources'

# 4. Сетевой стек
ss -tlnp | grep :<port>
tc qdisc show dev eth0
# fq_codel / cake = правильный qdisc для BBR

# 5. Файловая система
df -h /var/lib/kubelet /var/lib/containerd
# > 85% = DiskPressure

# 6. NUMA topology (для высокопроизводительных нагрузок)
lscpu | grep -i numa
numactl --hardware
# Поды должны быть привязаны к одной NUMA-ноте

# 7. IRQ баланс
cat /proc/interrupts | grep -E "eth|rx|tx|mlx"
# Прерывания NIC должны быть на тех же ядрах, где worker-процессы приложения
```

---

**🔵 Вопрос: «Диагностика тормозящего приложения»**

```bash
# Уровень 1: Внешние метрики (Prometheus/Grafana)
# - Latency p50/p95/p99 trend
# - RPS per pod
# - Error rate (5xx, timeout)
# - Queue length (Kafka lag, RabbitMQ depth)

# Уровень 2: Внутренние метрики приложения
# - JVM: JMX Exporter → heap usage, GC pause, thread count
# - Go: pprof /runtime/metrics → goroutines, GC, heap
# - Python: py-spy / pyroscope
# - Node.js: clinic.js / 0x

# Уровень 3: Профилирование под нагрузкой (Continuous Profiling)
kubectl debug -it <pod> --image=ghcr.io/profiling/pprof --target=app
# → curl http://localhost:6060/debug/pprof/profile?seconds=30 > cpu.prof
# → curl http://localhost:6060/debug/pprof/heap > mem.prof

# Уровень 4: Системные вызовы (strace/bpftrace)
kubectl debug node/<node> -it --image=ubuntu:24.04 --profile=sysadmin
# → bpftrace -e 'tracepoint:syscalls:sys_enter_* { @[probe] = count(); }'
# → strace -p <pid> -e trace=network,file -c

# Уровень 5: eBPF инструменты (BCC/bpftrace)
# - offcputime — где процесс спит (I/O, locks, scheduler)
# - runqlat — latency планировщика
# - biosnoop / biolatency — дисковые задержки
# - tcplife / tcpretrans — сетевые проблемы
```

**Матрица типичных паттернов тормозов:**

| Паттерн | CPU | Memory | Latency | RPS | Диагностика |
|---------|-----|--------|---------|-----|-------------|
| **CPU Bound** | 100% us | Стабильно | Растёт линейно | Падает | perf top, pprof → оптимизация алгоритмов |
| **Memory Leak** | Нормально | Растёт монотонно | Резкие скачки при GC | Падает при OOM | heap dump, pprof/inuse_space |
| **GC Thrashing** | Пики sy | Пики | Пульсирующие spikes | Нестабилен | GC logs, GODEBUG/GC logs |
| **Lock Contention** | Низкий (wait) | Нормально | Высокий, переменный | Низкий | bpftrace lock contention, pprof mutex |
| **I/O Bound** | Низкий, высокий wa | Page cache | Высокий, переменный | Ограничен IOPS | iostat -x, biolatency, blktrace |
| **Network Bound** | Низкий | Нормально | Высокий RTT | Ограничен bandwidth | tcpretrans, ss -ti, traceroute |
| **Thundering Herd** | Пики | Пики | Каскадный рост | Коллапс | Cache stampede detection, request coalescing |

---

**🔵 Вопрос: «Проверка ноды, dmesg и системных журналов»**

```bash
# Полный чек-лист системных логов узла

# 1. dmesg — ядро
dmesg -T -l err,crit,alert,emerg | tail -50
dmesg -T | grep -i -e oom -e kill -e throttle -e cgroup -e task.*block -e nmi_watchdog

# 2. journalctl — systemd сервисы
# Kubelet
journalctl -u kubelet --since "1 hour ago" -p err..emerg
journalctl -u kubelet --since "30 minutes ago" | grep -i -e evict -e oom -e throttle -e "memory pressure" -e "disk pressure" -e "pid pressure"

# Containerd / CRI-O
journalctl -u containerd --since "1 hour ago" -p err..emerg
journalctl -u containerd --since "30 minutes ago" | grep -i -e oom -e kill -e "out of memory"

# 3. Auditd (если настроен) — системные вызовы
ausearch -m ANOM_ABEND -ts recent
ausearch -m SYSCALL -k cgroup --ts recent

# 4. Kernel messages через kmsg
cat /dev/kmsg | grep -i -e oom -e kill -e throttle

# 5. NMI / MCE (аппаратные ошибки)
dmesg -T | grep -i -e mce -e nmi -e "hardware error" -e "machine check"

# 6. Soft lockups / hung tasks
dmesg -T | grep -i -e "soft lockup" -e "hung task" -e "rcu.*stall"

# 7. OOM Killer детали (если был)
dmesg -T | grep -A20 "Out of memory"
# → Kill process <pid> (<name>) score <score> or sacrifice child
# → oom_score_adj: 1000 (Guaranteed), 999 (Burstable), 0 (BestEffort)

# 8. CPU frequency / throttling (троттлинг по теплу/энергии)
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq
# Если << max freq = thermal throttling / power capping
```

**Prometheus алерты для раннего обнаружения:**
```yaml
groups:
- name: node-system-health
  rules:
  - alert: NodeMemoryPressure
    expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
    for: 5m
    labels: {severity: critical}
    annotations:
      summary: "Node {{ $labels.node }} under MemoryPressure"
      
  - alert: NodeDiskPressure
    expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
    for: 5m
    labels: {severity: critical}
    
  - alert: NodeCPUThrottlingHigh
    expr: sum(rate(container_cpu_cfs_throttled_seconds_total{namespace!="kube-system"}[5m])) by (pod) > 0.25
    for: 10m
    labels: {severity: warning}
    annotations:
      summary: "Pod {{ $labels.pod }} CPU throttled > 25%"
      
  - alert: ContainerMemoryGrowth
    expr: (container_memory_working_set_bytes / container_spec_memory_limit_bytes) > 0.9
    for: 15m
    labels: {severity: warning}
    annotations:
      summary: "Container {{ $labels.container }} memory > 90% limit"
      
  - alert: HPAFlapping
    expr: changes(kube_horizontalpodautoscaler_status_current_replicas[10m]) > 6
    for: 5m
    labels: {severity: warning}
    annotations:
      summary: "HPA {{ $labels.horizontalpodautoscaler }} flapping"
```

---

### Best Practices для траблшутинга

1. **Всегда начинайте с `kubectl get events`** — это даёт общий обзор происходящего
2. **Используйте `--previous` для логов** — если контейнер перезапустился
3. **Создавайте отладочные поды заранее** — для быстрого доступа к инструментам
4. **Документируйте инциденты** — для построения базы знаний
5. **Настраивайте алертинг** — чтобы ловить проблемы до их воздействия на пользователей
6. **Используйте `kubectl debug`** — вместо установки инструментов в production-образы
7. **Проверяйте квоты** — перед масштабированием
8. **Ведите историю изменений** — через аннотации `kubernetes.io/change-cause`

### См. также

- [Устранение неполадок HPA](./Common_Errors/hpa_troubleshooting.md) — детальная диагностика автомасштабировщика
- [Троттлинг CPU](./Common_Errors/cpu_throttling.md) — механизм CFS, диагностика, решения
- [OOMKilled поды](./Common_Errors/oomkilled_pods.md) — нехватка памяти, exit code 137
- [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md) — классы QoS и их влияние
- [Методология тестирования производительности](../../Testing/performance_testing_methodology.md) — поиск узких мест
- [Законы масштабируемости](../../Concepts/High_Availability/scalability_laws.md) — Little's Law, Kingman, USL
- [Диагностика Tail Latency](../../Linux/Diagnostics/Performance/diagnosing_tail_latency.md) — глубокая диагностика задержек
