# StatefulSet: Лучшие практики

## Определения

**StatefulSet Best Practices** — набор рекомендаций по эксплуатации StatefulSet-контроллеров для обеспечения отказоустойчивости, сохранности данных и предсказуемого поведения stateful-приложений в Kubernetes.

## Основные концепции

### Высокая доступность

**PodDisruptionBudget (PDB)** защищает от плановых выселений при обслуживании нод. Критически важно для баз данных и брокеров сообщений.

Пример PDB для StatefulSet:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: kafka-pdb
spec:
  maxUnavailable: 1  # Одновременно недоступен только 1 под
  selector:
    matchLabels:
      app: kafka-broker
```

Подробнее: [Pod Disruption Budget](../../Autoscaling/pod_disruption_budget.md).

**Pod Anti-Affinity** распределяет поды по разным зонам доступности для отказоустойчивости:

```yaml
spec:
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
          - key: app
            operator: In
            values:
            - kafka
        topologyKey: topology.kubernetes.io/zone
```

Подробнее: [Affinity и Anti-Affinity](../../Scheduling/affinity.md).

### Управление хранилищем

**`volumeBindingMode: WaitForFirstConsumer`** в StorageClass предотвращает создание томов до планирования пода, гарантируя совместимость по zone constraints:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: kubernetes.io/aws-ebs
volumeBindingMode: WaitForFirstConsumer  # Критично для многозонных кластеров
```

Подробнее: [PV и PVC](../../Storage/pv_and_pvc.md).

**Выбор StorageClass для production:**
- Поддержка snapshots для быстрого бэкапа
- Multi-AZ replication для отказоустойчивости
- Adequate IOPS для рабочих нагрузок

**Бэкапы PVC:**
- Политика `reclaimPolicy: Retain` защищает данные, но не заменяет бэкапы
- Регулярно создавайте snapshots через CSI-драйвер
- Тестируйте восстановление из бэкапов

### Проверка состояния

**`readinessProbe`** определяет готовность пода к приему трафика. Без этого StatefulSet может начать создавать следующий под до готовности текущего:

```yaml
readinessProbe:
  exec:
    command:
    - pg_isready
    - -U
    - postgres
  initialDelaySeconds: 5
  periodSeconds: 10
```

**`livenessProbe`** перезапускает зависшие контейнеры:

```yaml
livenessProbe:
  tcpSocket:
    port: 5432
  initialDelaySeconds: 30
  periodSeconds: 20
```

Подробнее: [Пробы (Probes)](../probes.md).

### Управление жизненным циклом

**Политика `whenScaled`** (Kubernetes 1.27+) управляет поведением PVC при уменьшении масштаба:

| Значение | Поведение |
|----------|-----------|
| `Retain` (по умолчанию) | PVC остается после удаления пода |
| `Delete` | PVC удаляется вместе с подом |

Пример:

```yaml
spec:
  persistentVolumeClaimRetentionPolicy:
    whenScaled: Retain
    whenDeleted: Retain
```

**Удаление StatefulSet:**
- Поды удаляются в обратном порядке (от высшего индекса к 0)
- PVC **не удаляются автоматически** — защита от потери данных
- Для полного удаления: сначала StatefulSet, затем PVC вручную

**Масштабирование:**
- StatefulSet масштабируется медленнее Deployment из-за упорядоченного создания
- Тестируйте операции масштабирования в staging перед production

## Практические сценарии

### Канареечное развертывание с partition

Используйте `partition` в `updateStrategy` для постепенного обновления:

```yaml
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 2  # Обновятся только поды с индексом >= 2
```

При `replicas: 5` и `partition: 2`:
- Поды `web-0`, `web-1` остаются на старой версии
- Поды `web-2`, `web-3`, `web-4` обновляются

После проверки — уменьшите `partition` до 0 для полного обновления.

### Безопасное уменьшение масштаба

Перед уменьшением `replicas` убедитесь, что данные распределены:

```bash
# Проверка состояния подов
kubectl get pods -l app=kafka

# Проверка PDB
kubectl get pdb kafka-pdb

# Уменьшение масштаба
kubectl scale statefulset kafka --replicas=2

# Мониторинг процесса
kubectl get pods -w
```

### Тестирование восстановления

Проверьте восстановление пода с сохранением данных:

```bash
# Запись данных в pod-0
kubectl exec my-app-0 -- /bin/sh -c 'echo "test-data" > /data/file.txt'

# Удаление пода
kubectl delete pod my-app-0

# Проверка после восстановления
kubectl exec my-app-0 -- cat /data/file.txt
# Вывод: test-data (данные сохранены)
```

### Диагностика проблем

```bash
# Проверка событий StatefulSet
kubectl describe statefulset my-app

# Проверка PVC
kubectl get pvc -l app=my-app

# Проверка PDB
kubectl get pdb -l app=my-app

# События выселения
kubectl get events --field-selector reason=Eviction
```

## Дополнительная информация

### Ограничения StatefulSet

- Не поддерживает автоматическое перераспределение при сбое ноды (требуется ручное вмешательство или оператор)
- `ReadWriteOnce` тома ограничивают размещение пода одной зоной
- Удаление StatefulSet не удаляет PVC автоматически
