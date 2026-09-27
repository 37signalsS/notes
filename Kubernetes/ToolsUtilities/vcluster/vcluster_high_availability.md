# vCluster — высокая доступность и Production-ready

> Документ описывает настройку HA для vCluster: отказоустойчивый Control Plane, production-ready чек-лист, планирование ёмкости и стратегии развёртывания. Архитектура — в [обзоре](./vcluster_overview.md), бэкап — в [vcluster_backup_restore.md](./vcluster_backup_restore.md), безопасность — в [vcluster_security_and_sync.md](./vcluster_security_and_sync.md).

## Определения

**High Availability (HA)** — способность системы продолжать работу при выходе из строя отдельных компонентов. Для vCluster HA означает, что падение одного пода Control Plane не приводит к недоступности API для тенанта.

**StatefulSet** — объект Kubernetes для управления stateful-приложениями с уникальными сетевыми именами, стабильными хостнеймами и PersistentVolume. Используется для развёртывания Control Plane vCluster.

**PodDisruptionBudget (PDB)** — политика, ограничивающая количество одновременно недоступных подов при volontных операциях (drain, upgrade). Гарантирует, что хотя бы N подов остаются Ready.

**Anti-Affinity** — правило размещения подов, запрещающее colocating подов на одном узле. Для HA Control PlaneSpread across nodes. For HA, use `podAntiAffinity` with `requiredDuringSchedulingIgnoredDuringExecution`.

**Leader Election** — механизм выборов лидера среди реплик. Только лидер обрабатывает запросы, остальные standby. При падении лидера электрируется новый.

** readiness gates** — дополнительные условия готовности пода, определяемые внешним контроллером. Используется для гарантии, что под полностью готов к трафику перед включением в Endpoints.

## Основные концепции

### Архитектура HA vCluster

```text
┌─────────────────────────────────────────────────────────────────┐
│                    Host Cluster                                  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Namespace: team-alpha                                       │ │
│  │                                                              │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │ │
│  │  │ StatefulSet   │  │ StatefulSet   │  │ StatefulSet   │     │ │
│  │  │ vc-<name>-0   │  │ vc-<name>-1   │  │ vc-<name>-2   │     │ │
│  │  │ (apiserver+   │  │ (apiserver+   │  │ (apiserver+   │     │ │
│  │  │  etcd leader) │  │  etcd follower)│  │  etcd follower)│    │ │
│  │  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘     │ │
│  │          │                   │                   │             │ │
│  │  ┌───────▼───────────────────▼───────────────────▼───────┐   │ │
│  │  │              Service (Headless)                        │   │ │
│  │  │   vc-<name>.team-alpha.svc.cluster.local              │   │ │
│  │  └───────────────────────────────────────────────────────┘   │ │
│  │                                                              │ │
│  │  ┌───────────────────────────────────────────────────────┐   │ │
│  │  │ Syncer (Deployment, replicas=1)                       │   │ │
│  │  │   └── синхронизация с хост-кластером                  │   │ │
│  │  └───────────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Компоненты Control Plane для HA

| Компонент | Без HA | С HA | Рекомендация |
| :--- | :--- | :--- | :--- |
| **API Server** | 1 под | 3+ подов (StatefulSet) | Minimum 3 для production |
| **etcd** | Embedded (single-node) | Embedded (3 реплики) или external cluster | External для критичных нагрузок |
| **Syncer** | 1 под (Deployment) | 1 под + leader election | Deployment с `replicas=1` |
| **Scheduler** | Встроен в K8s | Встроен в K8s (не требует настройки) | Не требует внимания |
| **Controller Manager** | Встроен | Встроен | Не требует внимания |

### Конфигурация HA vCluster

```yaml
# vcluster-ha.yaml
controlPlane:
  distro:
    k8s:
      enabled: true
      image: "registry.k8s.io/kube-apiserver:v1.36.0"

  backingStore:
    etcd:
      embedded:
        enabled: true
        size: "10Gi"
        storageClassName: "fast-ssd"

  statefulSet:
    replicas: 3  # Ключевой параметр для HA
    podManagementPolicy: Parallel  # Параллельный старт подов
    updateStrategy:
      type: RollingUpdate
      rollingUpdate:
        partition: 0
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
                - key: app
                  operator: In
                  values:
                    - vcluster
            topologyKey: kubernetes.io/hostname
    resources:
      requests:
        cpu: 300m
        memory: 512Mi
      limits:
        cpu: 1
        memory: 1Gi

  apiserver:
    extraArgs:
      - --audit-log-path=/var/log/vcluster/audit.log
      - --audit-log-maxage=30
      - --audit-log-maxbackup=10
      - --audit-log-maxsize=100

sync:
  toHost:
    pods:
      enabled: true
    services:
      enabled: true
  fromHost:
    storageClasses:
      enabled: true
    nodes:
      enabled: true

policies:
  podSecurityStandard: restricted
  networkPolicy:
    enabled: true
  resourceQuota:
    enabled: true
    quota:
      requests.cpu: "8"
      requests.memory: 16Gi
      pods: "100"

sleepMode:
  enabled: false  # Для production HA отключить sleep
```

### Ресурсы для HA конфигурации

| Конфигурация | CPU requests | RAM requests | CPU limits | RAM limits | Disk (etcd) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1 реплика (dev)** | 300m | 430Mi | 750m | 1Gi | 2Gi |
| **3 реплики (production)** | 900m | 1.5Gi | 3Gi | 3Gi | 10Gi |
| **3 реплики + external etcd** | 900m | 1.2Gi | 3Gi | 2.5Gi | Нет (external) |

Формула планирования ёмкости:

```text
Host CPU headroom >= N * 900m + 30% (workload buffer)
Host RAM headroom >= N * 1.5Gi + 30%
Host Disk >= N * 10Gi + 20%
```

### PodDisruptionBudget для HA

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: vcluster-pdb
  namespace: team-alpha
spec:
  minAvailable: 2  # Минимум 2 из 3 подов должны быть Ready
  selector:
    matchLabels:
      app: vcluster
```

### Production-ready чек-лист

| Уровень | Проверка | Реализация | Приоритет |
| :--- | :--- | :--- | :--- |
| **Control Plane** | 3+ реплики API Server | `controlPlane.statefulSet.replicas: 3` | Критический |
| **Control Plane** | Anti-affinity правила | `affinity.podAntiAffinity` в StatefulSet | Критический |
| **Control Plane** | PDB настроен | `minAvailable: 2` | Критический |
| **Backing Store** | etcd кластер (3 узла) или external DB | `backingStore.etcd.embedded` или внешний PostgreSQL | Критический |
| **Security** | PSA restricted | `policies.podSecurityStandard: restricted` | Критический |
| **Security** | NetworkPolicy включён | `policies.networkPolicy.enabled: true` | Критический |
| **Security** | RBAC Syncer минимизирован | `controlPlane.serviceAccount.create: false` + custom Role | Критический |
| **Security** | Audit log включён | `controlPlane.apiserver.auditLog.enabled: true` | Высокий |
| **Security** | Rootless mode | `securityContext.runAsNonRoot: true` | Высокий |
| **Network** | Ingress/Gateway API настроен | `networking.gatewayAPI.enabled: true` | Высокий |
| **Network** | extraSANs для внешнего доступа | `networking.proxy.extraSANs` | Высокий |
| **Storage** | Fast SSD для etcd | `storageClassName: fast-ssd` | Высокий |
| **Storage** | PVC с резервом | `backingStore.etcd.embedded.size: 10Gi` | Средний |
| **Monitoring** | Prometheus scrape настроен | ServiceMonitor | Высокий |
| **Monitoring** | Алерты на Syncer | `vcluster_syncer_sync_errors_total > 0` | Высокий |
| **Monitoring** | Алерты на etcd | `etcd_server_has_leader == 0` | Критический |
| **Backup** | Автоматический бэкап | CronJob с `etcdctl snapshot save` | Критический |
| **Backup** | Хранение вне кластера | S3/NFS | Критический |
| **Backup** | Тест восстановления | 1 раз в неделю | Высокий |
| **Logging** | Логи Syncer в Loki | Promtail конфигурация | Средний |
| **Compliance** | CIS Benchmark пройден | `kube-bench` | Средний |

### Rolling Update без даунтайма

```yaml
# vcluster.yaml — обновление версии Control Plane
controlPlane:
  distro:
    k8s:
      enabled: true
      image: "registry.k8s.io/kube-apiserver:v1.36.1"  # Новая версия

  statefulSet:
    replicas: 3
    updateStrategy:
      type: RollingUpdate
      rollingUpdate:
        partition: 0  # Обновить все поды
```

Процедура обновления:

```bash
# 1. Проверить текущую версию
vcluster describe <name> -n <ns>

# 2. Обновить vcluster.yaml (изменить image version)

# 3. Применить через Helm
helm upgrade <name> loft/vcluster -n <ns> -f vcluster.yaml

# 4. Мониторить поды
kubectl -n <ns> get pods -l app=vcluster -w

# 5. Проверить, что API доступен
vcluster connect <name> -n <ns> -- kubectl get nodes

# 6. Проверить синхронизацию
kubectl -n <ns> get pods -l vcluster.loft.sh/managed-by
```

### Проверка здоровья HA кластера

```bash
# 1. Состояние подов Control Plane
kubectl -n team-alpha get pods -l app=vcluster -o wide
# → NAME    READY   STATUS    RESTARTS   AGE   NODE
# → vc-0    2/2     Running   0          5d    node-1
# → vc-1    2/2     Running   0          5d    node-2
# → vc-2    2/2     Running   0          5d    node-3

# 2. Лидер etcd
kubectl -n team-alpha exec vc-0 -c etcd -- \
  ETCDCTL_API=3 etcdctl endpoint status --write-out=table
# → https://127.0.0.1:2379, 5d, leader, 10GB, 10MB

# 3. PDB
kubectl -n team-alpha get pdb
# → NAME         MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS
# → vcluster-pdb 2               N/A               1

# 4. Anti-affinity
kubectl -n team-alpha get pod -l app=vcluster -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}'
# → node-1
# → node-2
# → node-3

# 5. API доступен
vcluster connect <name> -n <ns> -- kubectl get --raw=/healthz
# → ok
```

### Диагностика проблем HA

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| 2 из 3 подов Running, 1 Pending | Anti-affinity не может разместить под | Добавить узел или ослабить anti-affinity |
| etcd lost quorum | 2+ узла etcd недоступны | Восстановить из снапшота (см. backup_restore) |
| API Server медленный | Лидер etcd перегружен | Проверить disk latency, увеличить ресурсы |
| PDB блокирует drain | `minAvailable` слишком высокий | Временно снизить `minAvailable` для maintenance |
| Rolling Update завис | Один под не проходит readiness | Проверить логи, откатить обновление |
| Syncer не синхронизирует | Syncer потерял связь с API | Проверить NetworkPolicy, перезапустить Syncer |

### Лучшие практики

- **3 реплики — минимум для production:** 1 реплика = нет HA, 2 реплики = нет кворума при потере 1 узла.
- **Разные узлы:** Anti-affinity с `requiredDuringScheduling` гарантирует, что поды на разных физических узлах.
- **PDB обязателен:** Без PDB Kubernetes может убить все поды одновременно при drain.
- **etcd на SSD:** Задержки диска — главная причина проблем etcd. Используйте NVMe или быстрые SSD.
- **Мониторинг кворума:** Алерт на `etcd_server_has_leader == 0` — это критично.
- **Тестирование failover:** Регулярно убивайте поды (`kubectl delete pod`) и проверяйте, что API остаётся доступным.
- **Разные updateStrategy:** Используйте `RollingUpdate` с `maxUnavailable: 1` для безопасных обновлений.
- **Отключение Sleep Mode:** В production HA sleep mode отключается — он масштабирует до 0, что противоречит HA.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — бэкап и восстановление](./vcluster_backup_restore.md)
- [vCluster — безопасность и синхронизация](./vcluster_security_and_sync.md)

### См. также

- [Kubernetes — High Availability](../../Kubernetes/Installation/)
- [etcd — кластеризация](../../etcd/)

### Внешние ссылки

- [vCluster HA Documentation](https://www.vcluster.com/docs/architecture/ha)
- [Kubernetes StatefulSet Best Practices](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [etcd Clustering Guide](https://etcd.io/docs/v3.5/op-guide/clustering/)
