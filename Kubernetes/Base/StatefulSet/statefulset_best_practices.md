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

### Принудительное удаление подов

Иногда поды могут зависать в состоянии `Terminating` (например, из-за бесконечных циклов в приложении или проблем с сетевыми хранилищами).

**Команда для принудительного удаления:**

```bash
# --force и --grace-period=0 для немедленного удаления без ожидания
kubectl delete pod <pod-name> --force --grace-period=0
```

**Особенности:**

- По умолчанию Kubernetes дает поду 30 секунд (`grace period`) на корректное завершение работы (`SIGTERM`).
- Для stateful-приложений принудительное удаление следует использовать с осторожностью, чтобы избежать повреждения данных.

**Удаление StatefulSet:**

- Поды удаляются в обратном порядке (от высшего индекса к 0).
- **Важно:** PVC **не удаляются автоматически**. Это "защитная фича" — данные сохраняются даже при полном удалении StatefulSet, чтобы при повторном развертывании под мог подключиться к своим данным.
- Для полной очистки ресурсов сначала удалите StatefulSet, а затем PVC вручную: `kubectl delete pvc -l app=<app-name>`.

**Масштабирование:**

- StatefulSet масштабируется медленнее Deployment из-за упорядоченного создания
- Тестируйте операции масштабирования в staging перед production

## Практические сценарии

### Обновление StatefulSet через Helm

**Проблема:** При обновлении StatefulSet через `helm upgrade` новая версия образа не применяется корректно, Pod остаётся в `CrashLoopBackOff`.

**Типичные причины:**

- PVC содержит данные от старой версии, которые несовместимы с новой версией приложения
- StatefulSet обновляет Pod по одному (RollingUpdate), и первый Pod с новым образом не может запуститься из-за старых данных на PVC
- Helm не управляет содержимым PVC — только манифестами

**Решение:**

1. **Проверить совместимость данных:** Убедиться, что новая версия приложения может работать с существующими данными на PVC.
2. **Очистка PVC перед обновлением:** Если данные несовместимы и не требуется их сохранять (тестовые окружения):

   ```bash
   # Удалить StatefulSet (PVC сохраняются)
   kubectl delete statefulset <name>
   # Удалить PVC вручную
   kubectl delete pvc -l app=<app-name>
   # Задеплоить новую версию
   helm upgrade <release> <chart> --version 2.0
   ```

3. **Миграция данных:** Для production — использовать init-контейнер или Job для миграции данных перед обновлением.
4. **Partitioned rollout:** Использовать `spec.updateStrategy.rollingUpdate.partition` для поэтапного обновления:

   ```yaml
   spec:
     updateStrategy:
       type: RollingUpdate
       rollingUpdate:
         partition: 2  # Обновит только pod с ordinal >= 2
   ```

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
