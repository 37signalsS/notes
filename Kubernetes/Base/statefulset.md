# StatefulSet

## Определения

**StatefulSet** — контроллер Kubernetes для управления stateful-приложениями, требующими сохранения состояния, стабильных сетевых идентификаторов и упорядоченного развертывания. В отличие от [Deployment](./Deployment/index.md), который рассматривает поды как взаимозаменяемые экземпляры, StatefulSet обеспечивает уникальность и предсказуемость для каждого пода.

Базовые концепции stateful/stateless см. в **[Stateful vs Stateless](../../Concepts/stateful_vs_stateless.md)**.

### Когда использовать StatefulSet

* **Базы данных:** PostgreSQL, MySQL, MongoDB, Cassandra.
* **Брокеры сообщений:** Kafka, RabbitMQ, Pulsar.
* **Распределённые системы:** ZooKeeper, etcd, Consul.
* **Приложения с RWO-томами,** требующие упорядоченных обновлений.

### Ключевые гарантии

| Гарантия | Описание |
| :--- | :--- |
| **Стабильные сетевые идентификаторы** | Поды получают имена `<имя-StatefulSet>-<порядковый-номер>` (например, `web-0`, `web-1`) |
| **Стабильное хранилище** | Каждый под имеет свой PVC, привязанный к имени пода |
| **Упорядоченное развертывание** | Поды создаются и удаляются последовательно |

## Основные концепции

### Архитектурные компоненты

Для работы StatefulSet требует комбинации компонентов:

1. **StatefulSet** — главный оркестратор, предоставляет подам стабильные имена и привязывает к дискам.
2. **[PersistentVolumeClaim (PVC)](../Storage/pv_and_pvc.md)** — запрос пода на выделение диска; StatefulSet создает уникальный PVC для каждого пода.
3. **[PersistentVolume (PV)](../Storage/pv_and_pvc.md)** — физическое хранилище (NFS, Ceph, диск облачного провайдера).
4. **[Headless Service](../Networking/Service/service_type_headless.md)** — сервис с `clusterIP: None`, обеспечивающий стабильные DNS-имена.

### Стабильные имена и DNS

Каждый под получает предсказуемое имя в формате `<имя-StatefulSet>-<порядковый-номер>`:

* Имена сохраняются при перезапуске и переносе подов.
* Требуется **Headless Service** для обеспечения уникальных DNS-имен.
* Формат DNS-записи: `pod-ordinal.service.namespace.svc.cluster.local` (например, `web-0.my-svc.default.svc.cluster.local`).

### Стратегии обновлений

* **RollingUpdate** — поочередное обновление подов с поддержкой `partition` для поэтапного развертывания.
* **OnDelete** — новая спецификация применяется только к вручную удаленным подам.

## Практические сценарии

### Пример манифеста StatefulSet

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
        image: nginx:1.28.0
        ports:
        - containerPort: 80
        volumeMounts:
        - name: www
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:
  - metadata:
      name: www
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
```

### Управление через kubectl

```bash
# Создать StatefulSet
kubectl apply -f statefulset.yaml

# Проверить статус
kubectl get statefulset web
kubectl get pods -l app=nginx

# Масштабировать
kubectl scale statefulset web --replicas=5

# Удалить (PVC сохраняются)
kubectl delete statefulset web
```

Подробнее: **[Практическое руководство](./StatefulSet/statefulset_practical_guide.md)**.

## Дополнительная информация

### Ограничения

* **Не поддерживает автоматическое восстановление** при сбое ноды — требуется ручное вмешательство или внешние операторы.
* **`ReadWriteOnce` тома** ограничивают размещение пода одной зоной доступности.
* **Удаление StatefulSet не удаляет PVC** автоматически — данные сохраняются для защиты от случайной потери.
* **Масштабирование медленнее Deployment** из-за упорядоченного создания подов.

### Лучшие практики

* Используйте **PodDisruptionBudget** для защиты от массовых выселений.
* Настройте **Affinity/Anti-Affinity** для распределения подов по узлам.
* Для баз данных используйте **операторы** (Postgres Operator, MongoDB Operator).

Подробнее:

* **[Ключевые концепции](./StatefulSet/statefulset_core_concepts.md)** (SSoT) — детальное описание принципов работы.
* **[StatefulSet vs Deployment](./StatefulSet/statefulset_vs_deployment.md)** — сравнение контроллеров.
* **[Лучшие практики](./StatefulSet/statefulset_best_practices.md)** — рекомендации по эксплуатации.

### Связанные темы

* [Deployment](./Deployment/index.md) — stateless-приложения.
* [Pod](./Pod/pod_overview.md) — базовый объект.
* [PersistentVolumeClaim](../Storage/pv_and_pvc.md) — хранилище.
* [Headless Service](../Networking/Service/service_type_headless.md) — DNS для StatefulSet.
* [PodDisruptionBudget](./high_availability.md) — защита от выселений.
* [Affinity и Anti-Affinity](../Scheduling/affinity.md) — управление размещением подов.
