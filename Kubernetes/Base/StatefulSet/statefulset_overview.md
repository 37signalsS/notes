# StatefulSet: Обзор

**StatefulSet** — контроллер Kubernetes для управления stateful-приложениями, требующими сохранения состояния, стабильных сетевых идентификаторов и упорядоченного развертывания. В отличие от **[Deployment](../Deployment/index.md)**, который рассматривает поды как взаимозаменяемые экземпляры, StatefulSet обеспечивает уникальность и предсказуемость для каждого пода.

## Определения

StatefulSet используется для приложений, которым необходимы:
* **Стабильные сетевые идентификаторы:** имена подов сохраняются при перезапуске.
* **Стабильное хранилище:** каждый под имеет собственный **[PersistentVolumeClaim (PVC)](../../Storage/pv_and_pvc.md)**, привязанный к его индексу.
* **Упорядоченное развертывание и масштабирование:** поды создаются и удаляются последовательно.

### Когда использовать StatefulSet

* **Базы данных:** PostgreSQL, MySQL, MongoDB, Cassandra.
* **Брокеры сообщений:** Kafka, RabbitMQ, Pulsar.
* **Распределённые системы:** ZooKeeper, etcd, Consul.
* **Приложения с RWO-томами,** требующие упорядоченных обновлений.

Базовые концепции stateful/stateless см. в **[Stateful vs Stateless](../../../Concepts/stateful_vs_stateless.md)**.

## Основные концепции

Для работы StatefulSet требует комбинации компонентов:

1. **StatefulSet** — главный оркестратор, управляет жизненным циклом подов.
2. **[PersistentVolumeClaim (PVC)](../../Storage/pv_and_pvc.md)** — запрос на выделение диска; StatefulSet создает уникальный PVC для каждого пода.
3. **[PersistentVolume (PV)](../../Storage/pv_and_pvc.md)** — физическое хранилище.
4. **[Headless Service](../../Networking/Service/service_type_headless.md)** — сервис с `clusterIP: None` для обеспечения стабильных DNS-имен.

### Ключевые гарантии

| Гарантия | Описание |
| :--- | :--- |
| **Стабильные имена** | Поды получают имена `<имя-StatefulSet>-<порядковый-номер>` (например, `web-0`, `web-1`). |
| **Стабильный DNS** | Формат DNS-записи: `pod-ordinal.service.namespace.svc.cluster.local`. |
| **Постоянство данных** | PVC сохраняются после удаления подов и даже после удаления самого StatefulSet (по умолчанию). |
| **Строгий порядок** | Поды создаются от 0 до N-1 и удаляются от N-1 до 0. |

Подробнее о механизмах работы: **[Ключевые концепции StatefulSet](./statefulset_core_concepts.md)**.

## Практические сценарии

### Пример манифеста

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

### Основные команды управления

```bash
# Создать StatefulSet
kubectl apply -f statefulset.yaml

# Проверить статус подов (создаются последовательно)
kubectl get pods -l app=nginx -w

# Масштабировать
kubectl scale statefulset web --replicas=5

# Удалить (PVC останутся в кластере)
kubectl delete statefulset web
```

Подробнее: **[Практическое руководство](./statefulset_practical_guide.md)**.

## Дополнительная информация

### Ограничения

* **Не поддерживает автоматическое восстановление** при сбое ноды — требуется ручное вмешательство или внешние операторы.
* **`ReadWriteOnce` тома** ограничивают размещение пода одной зоной доступности.
* **Удаление StatefulSet не удаляет PVC** автоматически — данные сохраняются для защиты от случайной потери.
* **Масштабирование медленнее Deployment** из-за упорядоченного создания подов.

### См. также

- **[StatefulSet vs Deployment](./statefulset_vs_deployment.md)** — подробное сравнение контроллеров.
- **[Лучшие практики](./statefulset_best_practices.md)** — рекомендации по эксплуатации и отказоустойчивости.
- **[Headless Service](../../Networking/Service/service_type_headless.md)** — работа DNS в StatefulSet.
- **[PV и PVC](../../Storage/pv_and_pvc.md)** — управление хранилищем в Kubernetes.
