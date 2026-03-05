# StatefulSet

## Определения

**StatefulSet** — это контроллер Kubernetes для управления stateful-приложениями с сохранением состояния. В отличие от [Deployment](./deployment.md), StatefulSet обеспечивает стабильные сетевые идентификаторы и постоянное хранилище для каждого пода.

## Краткое описание

StatefulSet обеспечивает:

- **Стабильные, уникальные сетевые идентификаторы** — поды получают предсказуемые имена (`app-0`, `app-1`)
- **Стабильное, постоянное хранилище** — каждый под имеет свой PVC, привязанный к имени пода
- **Упорядоченное развертывание и масштабирование** — поды создаются и удаляются последовательно

## Когда использовать

- Базы данных (PostgreSQL, MySQL, MongoDB, Cassandra)
- Брокеры сообщений (Kafka, RabbitMQ, Pulsar)
- Распределённые системы (ZooKeeper, etcd, Consul)
- Приложения с RWO-томами, требующие упорядоченных обновлений

## Детальная информация

Полное руководство по StatefulSet:

- **[StatefulSet/statefulset_overview.md](./StatefulSet/statefulset_overview.md)** — общее описание и ключевые концепции
- **[StatefulSet/statefulset_core_concepts.md](./StatefulSet/statefulset_core_concepts.md)** — стабильные идентификаторы, хранилища, порядок развертывания
- **[StatefulSet/statefulset_vs_deployment.md](./StatefulSet/statefulset_vs_deployment.md)** — сравнение с Deployment
- **[StatefulSet/statefulset_practical_guide.md](./StatefulSet/statefulset_practical_guide.md)** — практические примеры развертывания
- **[StatefulSet/statefulset_best_practices.md](./StatefulSet/statefulset_best_practices.md)** — рекомендации по эксплуатации

## Связанные темы

- [Deployment](./deployment.md) — stateless-приложения
- [Pod](./Pod/pod_overview.md) — базовый объект
- [PersistentVolumeClaim](../Storage/pv_and_pvc.md) — хранилище
- [Headless Service](../Networking/Service/service_type_headless.md) — DNS для StatefulSet
- [PodDisruptionBudget](./high_availability.md) — защита от выселений
- [Affinity и Anti-Affinity](../Scheduling/affinity.md) — управление размещением подов
