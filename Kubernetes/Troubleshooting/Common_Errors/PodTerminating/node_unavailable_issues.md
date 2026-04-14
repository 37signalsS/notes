# Pod Terminating: Узел недоступен

## Определения

**Node Unreachable** — состояние, при котором `kube-apiserver` не может связаться с `kubelet` на узле. Контроллер узла не получает heartbeat, статус узла переходит в `Unknown`.

**Node NotReady** — `kubelet` работает, но сообщает, что узел не готов принимать поды (проблемы ресурсов, CNI, runtime).

**Pod на недоступном узле в Terminating** — под получил `deletionTimestamp`, но kubelet на проблемном узле не может выполнить graceful shutdown (SIGTERM, unmount volumes, cleanup), так как узел недоступен.

---

## Базовые концепции

### Таймауты контроллера узлов

| Параметр | По умолчанию | Что происходит |
|----------|--------------|----------------|
| `--node-monitor-grace-period` | 40s | Время без heartbeat → статус `Unknown` |
| `--pod-eviction-timeout` | 5m | Время до начала eviction подов с узла |

### Sequence событий при недоступности узла

```
Узел перестаёт отвечать
    ↓
40s без heartbeat → Node status = Unknown
    ↓
Node controller добавляет taint:
  node.kubernetes.io/unreachable:NoExecute
    ↓
Pod без toleration → eviction (через pod-eviction-timeout)
    ↓
Pod уже в Terminating, но kubelet недоступен
    ↓
SIGTERM не доходит, volumes не размонтируются
    ↓
Pod застревает в Terminating
```

### Почему pod застревает в Terminating

При недоступном узле kubelet не может:

1. Получить SIGTERM → приложение не завершается
2. Размонтировать volumes → CSI driver ждёт
3. Удалить finalizers → объект остаётся в etcd

**Общая диагностика узлов:** [Node Unavailability Diagnostics](../NodeUnavailability/diagnostics.md). Определения: [Node Unavailability Definitions](../NodeUnavailability/definitions.md).

---

## Практические сценарии

### Сценарий 1: Диагностика недоступности узла

**Симптом:**

```bash
kubectl get nodes
NAME       STATUS     AGE
node-1     Ready      10d
node-2     Unknown    5d   ← Проблема
node-3     Ready      10d

kubectl get pods -o wide
NAME      STATUS       NODE     AGE
my-pod    Terminating  node-2   2h   ← Застрял
```

**Диагностика:**

```bash
# 1. Детали узла
kubectl describe node <node-name>
# Conditions: Ready=Unknown, Reason=NodeStatusUnknown

# 2. Events узла
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name>

# 3. SSH на узел (если возможно)
ssh <node-name>
systemctl status kubelet
journalctl -u kubelet --since "10 min ago"
```

Если SSH не работает — узел полностью недоступен (сеть, hardware, cloud instance terminated).

### Сценарий 2: Узел временно недоступен (ожидание восстановления)

**Когда:** Плановый reboot, кратковременный network partition, kubelet restart.

```bash
# Мониторинг статуса узла
kubectl get nodes -w

# Проверка, вернулся ли kubelet
ssh <node-name>
systemctl status kubelet
```

После восстановления kubelet:

- Pod получит SIGTERM и завершится
- Volumes размонтируются
- Запись удалится из etcd

### Сценарий 3: Узел не восстановится (принудительное удаление)

**Когда:** Cloud instance terminated, hardware failure, узел не вернётся.

```bash
# Принудительное удаление pod
kubectl delete pod <pod-name> --force --grace-period=0

# Если есть finalizers — удалить их
kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":[]}}'
```

> **Warning:** Force delete не отсоединяет volumes от узла. Для StatefulSet проверьте PVC перед удалением.

**Для StatefulSet:**

```bash
# Проверить PVC
kubectl get pvc -l app=<statefulset-name>

# Удалить pod (force)
kubectl delete pod <statefulset-pod> --force --grace-period=0

# Если PVC нужно переместить — удалить и пересоздать
kubectl delete pvc <pvc-name>  # Только если данные не важны!
```

### Сценарий 4: Исключение pod из Service перед удалением

Чтобы traffic не шёл на pod на недоступном узле:

```bash
# Удалить Endpoint вручную
kubectl delete endpoints <service-name> -p '{"subsets":[]}'

# Или удалить pod endpoint из списка
kubectl get endpoints <service-name>
# Проверить, что IP проблемного pod удалён
```

### Сценарий 5: Автоматическая очистка через node.kubernetes.io/unreachable taint

Добавить toleration для graceful cleanup при недоступности узла:

```yaml
tolerations:
- key: "node.kubernetes.io/unreachable"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 60  # Удалить pod через 60s после unreachable
```

Подробнее: [Taints и Eviction](../NodeUnavailability/taints_and_eviction.md).

---

## Дополнительная информация

**Связанные разделы:**

- [Определения Pod Terminating](./definitions.md) — причины зависания в Terminating
- [Diagnostics](./diagnostics.md) — чек-лист диагностики terminating pods
- [Graceful Shutdown](./graceful_shutdown.md) — процесс завершения pod
- [Node Unavailability: Definitions](../NodeUnavailability/definitions.md) — NodeNotReady, Unknown
- [Node Unavailability: Diagnostics](../NodeUnavailability/diagnostics.md) — общая диагностика узлов
- [Node Unavailability: Taints & Eviction](../NodeUnavailability/taints_and_eviction.md) — автоматические taints
- [Node Unavailability: Network Issues](../NodeUnavailability/network_issues.md) — сетевые проблемы
- [Обслуживание узлов](../../../Operations/node_maintenance.md) — cordon, drain, uncordon
- [Обзор Troubleshooting](../overview.md) — классификация ошибок Kubernetes
