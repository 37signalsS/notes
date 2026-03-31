# StatefulSet: Ключевые концепции

## Определения

**StatefulSet** — контроллер Kubernetes для управления stateful-приложениями, требующими сохранения состояния, стабильных сетевых идентификаторов и упорядоченного развертывания. В отличие от [Deployment](../Deployment/deployment_concepts.md), который рассматривает поды как взаимозаменяемые экземпляры, StatefulSet обеспечивает уникальность и предсказуемость для каждого пода.

Базовые концепции stateful/stateless см. в **[Stateful vs Stateless](../../../Concepts/stateful_vs_stateless.md)**.

### Проблема Deployment для stateful-приложений

Стандартный [Deployment](../Deployment/deployment_concepts.md) при перезапуске или переносе пода может присвоить новый IP-адрес и имя, а также **потерять связь со своим хранилищем**. Для баз данных и других stateful-приложений это равносильно потере данных.

### Когда использовать StatefulSet

- **Базы данных:** PostgreSQL, MySQL, MongoDB, Cassandra
- **Брокеры сообщений:** Kafka, RabbitMQ, Pulsar
- **Распределённые системы:** ZooKeeper, etcd, Consul
- **Приложения с RWO-томами,** требующие упорядоченных обновлений

Для правильного развертывания приложений с состоянием используется комбинация из четырех ключевых компонентов:

| Компонент | Назначение |
|-----------|------------|
| **StatefulSet** | Главный оркестратор: предоставляет подам стабильные имена и привязывает к дискам |
| **PersistentVolumeClaim (PVC)** | Запрос пода на выделение диска; StatefulSet создает уникальный PVC для каждого пода |
| **PersistentVolume (PV)** | Физическое хранилище (NFS, Ceph, диск облачного провайдера), удовлетворяющее запрос PVC |
| **Headless Service** | Сервис с `clusterIP: None`, обеспечивающий стабильные DNS-имена для каждого пода |

Подробнее: [Headless Service](../../Networking/Service/service_type_headless.md), [PV и PVC](../../Storage/pv_and_pvc.md).

## Основные концепции

### Стабильные, уникальные сетевые идентификаторы

Каждый под в StatefulSet получает предсказуемое имя в формате `<имя-StatefulSet>-<порядковый-номер>` (например, `web-0`, `web-1`).

**Ключевые характеристики:**

- Имена сохраняются при перезапуске и переносе подов — критически важно для кластерных приложений
- Требуется **Headless Service** (сервис с `clusterIP: None`) для обеспечения уникальных DNS-имен
- Формат DNS-записи: `pod-ordinal.service.namespace.svc.cluster.local` (например, `web-0.my-svc.default.svc.cluster.local`)
- **Автоматическая метка:** Kubernetes добавляет метку `statefulset.kubernetes.io/pod-name` со значением имени пода (например, `my-app-0`). Позволяет создавать сервисы, нацеленные на конкретный под

Пример DNS-разрешения:

```bash
# Запрос к Headless Service вернет IP всех подов
nslookup web-headless.default.svc.cluster.local

# Запрос к конкретному поду
nslookup web-0.web-headless.default.svc.cluster.local
# Ответ: 10.244.1.5
```

### Стабильные, постоянные хранилища

StatefulSet автоматически создает PVC для каждого пода на основе шаблона `volumeClaimTemplates`.

**Принципы работы:**

- Имя PVC: `<имя-claim>-<имя-pod>` (например, `data-web-0`)
- PVC привязан к конкретному поду и сохраняется после его удаления
- При пересоздании пода StatefulSet гарантирует подключение того же тома
- **Важно:** При удалении StatefulSet PVC **не удаляются автоматически** — защита от потери данных

Пример конфигурации:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web
spec:
  serviceName: "web-headless"
  replicas: 3
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.25.5
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "fast-ssd"
      resources:
        requests:
          storage: 10Gi
```

Проверка PVC:

```bash
# PVC создаются автоматически с именами data-web-0, data-web-1, data-web-2
kubectl get pvc -l app=nginx

# NAME          STATUS   VOLUME   CAPACITY   ACCESS MODES
# data-web-0    Bound    pv-1     10Gi       RWO
# data-web-1    Bound    pv-2     10Gi       RWO
# data-web-2    Bound    pv-3     10Gi       RWO
```

### Упорядоченное развертывание и масштабирование

StatefulSet гарантирует строгий порядок операций создания и удаления подов.

**Создание:** Поды создаются последовательно (сначала `web-0`, потом `web-1`). Следующий под не начнет создаваться, пока предыдущий не станет `Ready`.

**Удаление:** Поды удаляются в обратном порядке (сначала `web-n`, потом `web-n-1`).

**Параметр `podManagementPolicy`:**

| Значение | Описание | Когда использовать |
|----------|----------|-------------------|
| `OrderedReady` (по умолчанию) | Строгий порядок с ожиданием готовности | Базы данных, распределённые системы |
| `Parallel` | Параллельное создание/удаление | Stateless-подобные нагрузки без зависимостей |

Пример:

```yaml
spec:
  podManagementPolicy: Parallel  # Для ускорения развертывания
```

**Стратегия обновлений `updateStrategy`:**

| Тип | Описание |
|-----|----------|
| `RollingUpdate` | Поочередное обновление подов с поддержкой `partition` |
| `OnDelete` | Новая спецификация применяется только к вручную удаленным подам |

Пример канареечного обновления с `partition`:

```yaml
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 2  # Обновятся только поды с индексом >= 2
```

При `replicas: 5`:
- Поды `web-0`, `web-1` остаются на старой версии
- Поды `web-2`, `web-3`, `web-4` обновляются

**Политика `whenScaled` (Kubernetes 1.27+):** Определяет поведение PVC при уменьшении масштаба:

| Значение | Поведение |
|----------|-----------|
| `Retain` (по умолчанию) | PVC остается после удаления пода |
| `Delete` | PVC удаляется вместе с подом |

```yaml
spec:
  persistentVolumeClaimRetentionPolicy:
    whenScaled: Retain
    whenDeleted: Retain
```

### Особое поведение при сбоях

**Недоступность узла:** Если нода становится `NotReady`, Kubernetes **не переносит автоматически** под StatefulSet на другую ноду. Это защита от split-brain для баз данных с `ReadWriteOnce` томами. Требуется ручное вмешательство или оператор.

**Обработка `SIGTERM`:** StatefulSet ожидает корректного завершения работы приложения, что позволяет сохранить данные и отсоединиться от кластера.

## Практические сценарии

### Проверка порядка создания подов

```bash
# Создание StatefulSet
kubectl apply -f statefulset.yaml

# Мониторинг в реальном времени
kubectl get pods -w

# Вывод показывает последовательное создание:
# web-0   0/1   ContainerCreating   0s
# web-0   1/1   Running             5s
# web-1   0/1   ContainerCreating   0s  # Создан только после Ready web-0
# web-1   1/1   Running             4s
# web-2   0/1   ContainerCreating   0s
```

### Тестирование сохранения данных

```bash
# Запись данных в pod-0
kubectl exec web-0 -- /bin/sh -c 'echo "persistent-data" > /usr/share/nginx/html/index.html'

# Удаление пода
kubectl delete pod web-0

# Проверка после пересоздания
kubectl exec web-0 -- cat /usr/share/nginx/html/index.html
# Вывод: persistent-data (данные сохранены в PVC)
```

### Масштабирование с проверкой порядка

```bash
# Увеличение масштаба
kubectl scale statefulset web --replicas=5

# Поды создаются последовательно: web-3, затем web-4
kubectl get pods -w

# Уменьшение масштаба
kubectl scale statefulset web --replicas=2

# Поды удаляются в обратном порядке: web-4, затем web-3
```

### Доступ к конкретному поду через Service

Используйте автоматическую метку `statefulset.kubernetes.io/pod-name` для таргетирования конкретного пода:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-0-service
spec:
  selector:
    statefulset.kubernetes.io/pod-name: web-0  # Таргет на конкретный под
  ports:
  - port: 80
    targetPort: 80
```

### Диагностика проблем

```bash
# Проверка событий StatefulSet
kubectl describe statefulset web

# Проверка порядка создания через события
kubectl get events --field-selector involvedObject.kind=StatefulSet

# Проверка PVC
kubectl get pvc -l app=nginx

# Проверка меток подов
kubectl get pods --show-labels -l app=nginx
```

## Дополнительная информация

### Ограничения StatefulSet

- Не поддерживает автоматическое восстановление при сбое ноды (требуется ручное вмешательство или оператор)
- `ReadWriteOnce` тома ограничивают размещение пода одной зоной
- Удаление StatefulSet не удаляет PVC автоматически
- Масштабирование медленнее Deployment из-за упорядоченного создания
