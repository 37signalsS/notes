# StatefulSet

**StatefulSet** — это Kubernetes-контроллер для управления stateful-приложениями с сохранением состояния.

## Определения

StatefulSet обеспечивает:
- **Стабильные, уникальные сетевые идентификаторы** — поды получают предсказуемые имена (`app-0`, `app-1`)
- **Стабильное, постоянное хранилище** — каждый под имеет свой PVC, привязанный к имени пода
- **Упорядоченное развертывание и масштабирование** — поды создаются и удаляются последовательно

## Когда использовать

Используйте StatefulSet для:
- Базы данных (PostgreSQL, MySQL, MongoDB)
- Брокеры сообщений (Kafka, RabbitMQ)
- Distributed systems (ZooKeeper, etcd)
- Приложения с RWO-томами, требующие ordered updates

## Основные концепции

- [Ключевые концепции](./StatefulSet/statefulset_core_concepts.md) — технические детали
- [StatefulSet vs. Deployment](./StatefulSet/statefulset_vs_deployment.md) — сравнение
- [Практическое руководство](./StatefulSet/statefulset_practical_guide.md) — примеры
- [Лучшие практики](./StatefulSet/statefulset_best_practices.md) — рекомендации

## Связанные темы

- [Deployment](./deployment.md) — stateless-приложения
- [Pod](./Pod/pod_overview.md) — базовый объект
- [PersistentVolumeClaim](./Storage/pv_and_pvc.md) — хранилище
- [Headless Service](./Networking/Service/service_type_headless.md) — DNS для StatefulSet
- [PodDisruptionBudget](./high_availability.md) — защита от выселений
