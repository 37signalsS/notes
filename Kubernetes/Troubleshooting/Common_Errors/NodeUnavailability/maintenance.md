# Недоступность узла: Проблемы при обслуживании

В данном разделе рассматриваются критические ситуации, возникающие в процессе планового вывода узлов из эксплуатации (Cordon/Drain), их перезагрузки или возврата в кластер.

## Основные определения

**Зависание обслуживания (Maintenance Hang)** — состояние, при котором процедура дренажа (`drain`) не завершается из-за блокирующих факторов на уровне API или хоста.

**Забытый узел (Stale SchedulingDisabled)** — исправный узел в статусе `Ready`, который остался в режиме `SchedulingDisabled` из-за отсутствия команды `uncordon`.

**Eviction API** — механизм, используемый `kubectl drain` для безопасного удаления подов. В отличие от `delete`, `evict` учитывает `PodDisruptionBudget` и может быть отклонен API-сервером.

**NodeMaintenance API (Alpha в 1.31)** — новый декларативный способ управления обслуживанием узлов, позволяющий автоматизировать процессы через специальные Custom Resources.

Основные инструкции по проведению работ: [Обслуживание узлов: Cordon и Drain](../../../Operations/node_maintenance.md).

## Основные концепции

### Механизмы блокировки обслуживания

Процесс вывода узла может быть остановлен API-сервером по следующим причинам:

1.  **Нарушение PodDisruptionBudget (PDB)**: Если удаление пода нарушает условие `minAvailable` или `maxUnavailable`.
2.  **Наличие финализаторов (`finalizers`)**: Метаданные в поде (например, от операторов или CSI), которые требуют выполнения внешнего действия перед удалением объекта.
3.  **Локальные данные (`emptyDir`)**: Kubelet защищает поды с локальными данными от случайного удаления (требуется флаг `--delete-emptydir-data`).
4.  **Bare Pods (Голые поды)**: Поды без владельца (OwnerReference). `drain` не удаляет их без флага `--force`, так как они не будут пересозданы.

### Улучшения в 1.31 для стабильного обслуживания

**Политика выселения нездоровых подов (`unhealthyPodEvictionPolicy`)**:
Начиная с Kubernetes 1.31, поле в PDB стало стабильным. Оно позволяет игнорировать "мертвые" поды (например, в `CrashLoopBackOff`) при расчете бюджета:
```yaml
spec:
  unhealthyPodEvictionPolicy: AlwaysAllow # Разрешает выселение нездоровых подов, даже если бюджет нарушен
```
Это критически важно для предотвращения бесконечного ожидания `drain` из-за подов, которые и так не функционируют.

## Практические сценарии

### Сценарий 1: Блокировка kubectl drain из-за PDB

**Симптом**: `kubectl drain` висит часами, в логах сообщения: `Cannot evict pod as it would violate the pod's disruption budget`.

**Диагностика**:
```bash
kubectl get pdb -A
# Найдите PDB с 0 разрешенными разрывами (ALLOWED DISRUPTIONS: 0)
```

**Решение**:
- Временно уменьшите `minAvailable` или увеличьте `maxUnavailable` в манифесте PDB.
- Добавьте реплик в соответствующий Deployment/StatefulSet на других узлах.
- **Экстренно**: Используйте флаг `--disable-eviction`, который переключает команду на прямое удаление (игнорируя PDB).

### Сценарий 2: Поды застряли в Terminating (Finalizers)

**Симптом**: Узел пуст, но `drain` не завершается, так как поды висят в `Terminating`.

**Причина**: Зависший финализатор (часто `kubernetes.io/pvc-protection` или кастомные финализаторы операторов).

**Диагностика**:
```bash
kubectl get pod <name> -o jsonpath='{.metadata.finalizers}'
```

**Решение**:
Если вы уверены, что процессы завершены и данные в безопасности, удалите финализаторы:
```bash
kubectl patch pod <name> -p '{"metadata":{"finalizers":null}}' --type=merge
```

### Сценарий 3: Узел NotReady после перезагрузки

**Симптом**: Хост загрузился, но статус в кластере `NotReady` или `Unknown`.

**Диагностические шаги на узле**:
1.  **Проверка Swap**: Если после перезагрузки Swap включился автоматически, Kubelet может не запуститься.
    ```bash
    swapoff -a && systemctl restart kubelet
    ```
2.  **Модули ядра**: Проверьте наличие `br_netfilter` и `overlay`.
    ```bash
    lsmod | grep -E "overlay|br_netfilter"
    ```
3.  **Конфигурация CNI**: Если CNI-плагин не запустился (например, из-за сетевых проблем или отсутствия бинарников в `/opt/cni/bin`), узел будет `NotReady` с причиной `NetworkUnavailable`.
    ```bash
    journalctl -u kubelet | grep "cni"
    ```

### Сценарий 4: Сбой Graceful Node Shutdown

**Симптом**: При выключении узла поды убиваются по `SIGKILL` мгновенно, не успевая сохранить состояние или завершить транзакции.

**Причина**: Неверная конфигурация `KubeletConfiguration` или отсутствие связи с `systemd-logind`.

**Верификация**:
Убедитесь, что в конфигурации kubelet (обычно `/var/lib/kubelet/config.yaml`) заданы:
```yaml
shutdownGracePeriod: 30s
shutdownGracePeriodCriticalPods: 10s
```
Проверьте логи на наличие сообщений от **Shutdown Manager**:
```bash
journalctl -u kubelet -g "Shutdown manager"
```

### Сценарий 5: Зависшие VolumeAttachments

**Симптом**: `drain` завершен, но узел нельзя удалить из облачной платформы, так как диски (EBS/PD) все еще примонтированы к нему.

**Решение**:
Найдите зависшие объекты `VolumeAttachment` и проверьте их статус. В критических случаях, если узел физически выключен, удалите объект вручную:
```bash
kubectl get volumeattachments | grep <node-name>
kubectl delete volumeattachment <attachment-id>
```

## Дополнительная информация

- [Диагностика недоступности узла](./diagnostics.md) — алгоритм поиска причин `NotReady`.
- [Проблемы рантайма](./runtime_issues.md) — если `containerd` не стартует после обслуживания.
- [Pod Disruption Budget](../../../Autoscaling/pod_disruption_budget.md) — архитектура защитных бюджетов.
- [Node Maintenance API (K8s docs)](https://kubernetes.io/docs/concepts/architecture/nodes/#node-maintenance) — официальная документация по новому API.
