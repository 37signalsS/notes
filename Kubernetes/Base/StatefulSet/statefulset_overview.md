# StatefulSet

## Определения

**StatefulSet** — это объект Kubernetes, предназначенный для управления приложениями, которые требуют сохранения состояния и/или стабильных сетевых идентификаторов. В отличие от [Deployment](../deployment.md), который обращается с подами как со взаимозаменяемыми "копиями", StatefulSet обеспечивает гарантии порядка и уникальности для своих подов.

Ключевая задача `StatefulSet` — обеспечить каждому поду:

1. **Стабильное, уникальное сетевое имя** в формате `<имя-StatefulSet>-<порядковый-номер>` (например, `web-0`, `web-1`).
2. **Стабильное, постоянное хранилище** через [PersistentVolumeClaim](../../Storage/pv_and_pvc.md), привязанное к конкретному поду.

> **Проблема:** Стандартный [Deployment](../deployment.md) при перезапуске или переносе пода может присвоить новый IP-адрес и имя, а также **потерять связь со своим хранилищем**. Для баз данных и других stateful-приложений это равносильно потере данных.

## Глубокое погружение

* [Ключевые концепции StatefulSet](./statefulset_core_concepts.md) — детальное рассмотрение стабильных идентификаторов, хранилищ, порядка развертывания и поведения при сбоях.
* [StatefulSet vs. Deployment](./statefulset_vs_deployment.md) — сравнение двух контроллеров и сценарии выбора.
* [Практическое руководство](./statefulset_practical_guide.md) — примеры использования и развертывания.
* [Лучшие практики](./statefulset_best_practices.md) — рекомендации по эксплуатации.

## Связанные темы

* [Deployment](../deployment.md) — управление stateless-приложениями
* [Pod](../Pod/pod_overview.md) — базовый объект развертывания
* [PersistentVolumeClaim](../../Storage/pv_and_pvc.md) — запросы на хранилище
* [Headless Service](../../Networking/Service/service_type_headless.md) — стабильные DNS-имена для подов
* [Service](../../Networking/Service/service_overview.md) — сетевой доступ к подам
* [Высокая доступность](../high_availability.md) — PodDisruptionBudget, отказоустойчивость
* [Affinity и Anti-Affinity](../../Scheduling/affinity.md) — управление размещением подов
