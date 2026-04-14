# StatefulSet vs. Deployment: Сравнение контроллеров

## Определения

**Deployment** — контроллер Kubernetes для управления stateless-приложениями (веб-серверы, API), где поды взаимозаменяемы и не требуют сохранения состояния.

**StatefulSet** — контроллер Kubernetes для управления stateful-приложениями (базы данных, брокеры сообщений), требующими стабильных сетевых идентификаторов и персистентного хранилища.

> **SSoT:** Детальное описание концепций см. в **[Ключевые концепции StatefulSet](./statefulset_core_concepts.md)** и **[Kubernetes Deployment: Концепции](../Deployment/deployment_concepts.md)**.

## Основные концепции

### Сравнительная таблица

| Характеристика | Deployment | StatefulSet |
|----------------|------------|-------------|
| **Предназначение** | Stateless-приложения (веб-серверы, API) | Stateful-приложения (базы данных, брокеры сообщений) |
| **Сетевая идентификация** | Поды взаимозаменяемы, получают случайные имена и IP-адреса | Поды получают стабильные, уникальные имена (`<имя>-0`, `<имя>-1`) и DNS-записи |
| **Хранилище** | Общее хранилище (`ReadOnlyMany`) или временное | Каждый под получает постоянное хранилище ([PersistentVolumeClaim](../../Storage/pv_and_pvc.md)) |
| **Стратегия обновления** | `RollingUpdate`: гибкое, параллельное обновление | `RollingUpdate` (упорядоченный): последовательное обновление |
| **Масштабирование/Удаление** | Поды создаются и удаляются в случайном порядке | Поды создаются по порядку (0, 1, 2) и удаляются в обратном порядке (n, n-1, n-2) |

### Ключевое отличие: стратегия обновления

**Deployment** стремится как можно быстрее обновить поды, часто запуская новые параллельно со старыми.

**StatefulSet** обновляет поды **строго по одному**, дожидаясь, пока обновленный под станет `Ready`, прежде чем переходить к следующему. Это гарантирует целостность кластерных систем, где важен порядок.

### Сравнение поведения подов

| Аспект | StatefulSet Pod | Deployment Pod |
|--------|-----------------|----------------|
| **Имя и индекс** | Стабильные, с порядком (0..N-1) | Эфемерные имена без порядка |
| **DNS** | Предсказуемые записи per-Pod | Сервисный адрес без гарантии на Pod-идентичность |
| **Хранилище** | Отдельный PVC на Pod, сохраняется | Общие шаблоны Volumes, без индивидуального PVC |
| **Порядок** | Управляемый (Ordered/Parallel) | Нет гарантий порядка |

## Практические сценарии

### Сценарий 1: Выбор контроллера для приложения с общим хранилищем

Некоторые приложения (CMS, Git-серверы) могут работать в кластерном режиме, но требуют доступа к одному общему хранилищу. Выбор контроллера зависит от режима доступа (`accessMode`).

#### Паттерн 1: `Deployment` + Хранилище `ReadWriteMany` (RWX)

**Когда использовать:** Доступно хранилище с поддержкой RWX (NFS, CephFS, GlusterFS).

**Как работает:**

1. Создается один `PersistentVolumeClaim` с `accessMode: ReadWriteMany`
2. `Deployment` управляет подами приложения
3. Все реплики монтируют **один и тот же** PVC

**Почему это работает:** Блокировки файлов и целостность данных обеспечиваются нижней файловой системой (NFS).

**Пример манифеста:**

```yaml
# pvc-rwx.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shared-storage
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: nfs-storage
  resources:
    requests:
      storage: 10Gi
---
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cms-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: cms
  template:
    metadata:
      labels:
        app: cms
    spec:
      containers:
      - name: cms
        image: drupal:latest
        volumeMounts:
        - name: shared-storage
          mountPath: /var/www/html
      volumes:
      - name: shared-storage
        persistentVolumeClaim:
          claimName: shared-storage
```

**Горизонтальное масштабирование и `RollingUpdate` безопасны.**

#### Паттерн 2: `StatefulSet` + Хранилище `ReadWriteOnce` (RWO)

**Когда использовать:** Доступно только блочное хранилище (диски облачных провайдеров, iSCSI) с режимом RWO.

**Проблема с `Deployment`:** `RollingUpdate` создает новый под до удаления старого. При монтировании уже используемого RWO-тома новый под зависнет в `ContainerCreating`.

**Решение через `StatefulSet`:** Упорядоченная стратегия обновления — сначала удаляет старый под, освобождая том, потом создает новый.

**Пример манифеста:**

```yaml
# statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: git-server
spec:
  serviceName: "git-server-headless"
  replicas: 1  # Даже одна реплика требует StatefulSet для RWO
  selector:
    matchLabels:
      app: git-server
  template:
    metadata:
      labels:
        app: git-server
    spec:
      containers:
      - name: git-server
        image: gogs/gogs:latest
        volumeMounts:
        - name: shared-storage
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: shared-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: fast-ssd
      resources:
        requests:
          storage: 10Gi
```

**Вывод:** Для приложений с общим хранилищем на RWO-томах использование `StatefulSet` (даже с одной репликой) обязательно для безопасных обновлений без простоев.

### Сценарий 2: Миграция с Deployment на StatefulSet

**Контекст:** Приложение изначально развернуто через `Deployment`, но потребовалось сохранение состояния и стабильные идентификаторы.

**Шаги миграции:**

1. **Создать Headless Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: app-headless
spec:
  clusterIP: None
  selector:
    app: my-app
  ports:
  - port: 80
```

1. **Создать StatefulSet с новыми PVC:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: my-app
spec:
  serviceName: "app-headless"
  replicas: 2
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
      - name: app
        image: my-app:latest
        volumeMounts:
        - name: data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 5Gi
```

1. **Скопировать данные со старых томов на новые** (через временные поды)

2. **Удалить старый Deployment:**

```bash
kubectl delete deployment my-app
```

1. **Проверить работу StatefulSet:**

```bash
kubectl get pods -l app=my-app
# my-app-0, my-app-1 — стабильные имена
```

Подробнее о миграции: **[Миграция Kafka с Deployment на StatefulSet](../../../Kafka/deployment_to_statefulset_migration.md)**.

### Сценарий 3: Диагностика и сравнение поведения

**Проверка порядка создания:**

```bash
# Deployment — поды создаются параллельно, случайные имена
kubectl apply -f deployment.yaml
kubectl get pods -w
# app-7d4f8-abc12, app-7d4f8-xyz34 — случайные имена

# StatefulSet — поды создаются последовательно
kubectl apply -f statefulset.yaml
kubectl get pods -w
# app-0, затем app-1, затем app-2 — упорядоченно
```

**Проверка сохранения данных:**

```bash
# Deployment — данные теряются при рестарте
kubectl exec app-7d4f8-abc12 -- echo "test" > /data/file.txt
kubectl delete pod app-7d4f8-abc12
# Новый под не содержит файл

# StatefulSet — данные сохраняются
kubectl exec app-0 -- echo "test" > /data/file.txt
kubectl delete pod app-0
kubectl exec app-0 -- cat /data/file.txt
# Вывод: test (данные сохранены в PVC)
```

**Проверка DNS:**

```bash
# Deployment — только сервисный DNS
nslookup my-service.default.svc.cluster.local

# StatefulSet — DNS каждого пода
nslookup app-0.app-headless.default.svc.cluster.local
nslookup app-1.app-headless.default.svc.cluster.local
```

## Дополнительная информация

### Связанные документы

- **[Ключевые концепции StatefulSet](./statefulset_core_concepts.md)** (SSoT)
- **[Kubernetes Deployment: Концепции](../Deployment/deployment_concepts.md)** (SSoT)
- **[Практическое руководство по StatefulSet](./statefulset_practical_guide.md)**
- **[Лучшие практики StatefulSet](./statefulset_best_practices.md)**
- **[PV и PVC](../../Storage/pv_and_pvc.md)**
- **[Headless Service](../../Networking/Service/service_type_headless.md)**
- **[Миграция Kafka с Deployment на StatefulSet](../../../Kafka/deployment_to_statefulset_migration.md)**

### Критерии выбора контроллера

| Критерий | Deployment | StatefulSet |
|----------|------------|-------------|
| Приложение не требует сохранения состояния | ✅ | ❌ |
| Поды взаимозаменяемы | ✅ | ❌ |
| Требуется стабильное хранилище на под | ❌ | ✅ |
| Нужны стабильные DNS-имена подов | ❌ | ✅ |
| Важен порядок развертывания | ❌ | ✅ |
| Общее хранилище RWX | ✅ | ❌ |
| Общее хранилище RWO | ❌ | ✅ |

### Ограничения

| Контроллер | Ограничения |
|------------|-------------|
| **Deployment** | Не подходит для stateful-приложений; не гарантирует порядок; поды без стабильных идентификаторов |
| **StatefulSet** | Нет авто-восстановления при сбое ноды; RWO тома ограничены одной зоной; PVC не удаляются автоматически; медленное масштабирование |
