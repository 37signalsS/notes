# Распределение подов: Дополнительная информация

## Интеграции

* **[HPA](hpa_detailed.md)** — созданные HPA поды распределяются согласно настроенным правилам.
* **[Pod Disruption Budget](pod_disruption_budget.md)** — совместное использование обеспечивает доступность при потере узла.
* **[Scaling Patterns](scaling_patterns.md)** — при шардировании настраивайте распределение для изоляции сбоев.
* **[Cluster Autoscaler](cluster_autoscaler_detailed.md)** — CA может создавать узлы для соблюдения правил распределения.

## Ограничения

| Ограничение | Описание |
|-------------|----------|
| Требуется достаточное количество узлов | При малом кластере правила могут блокировать планирование |
| Может блокировать масштабирование | При нехватке ресурсов HPA не сможет создать поды |
| Не защищает от недобровольных прерываний | Без PDB сбой узла нарушит доступность |
| Сложность отладки | Комбинация правил может давать неожиданные результаты |

## Топология и домены отказа

| Уровень | Topology Key | Пример использования |
|---------|--------------|---------------------|
| Узел | `kubernetes.io/hostname` | Распределение по физическим серверам |
| Стойка | `topology.kubernetes.io/rack` | Распределение по стойкам ЦОД |
| Зона | `topology.kubernetes.io/zone` | Распределение по зонам доступности |
| Регион | `topology.kubernetes.io/region` | Распределение по регионам |

## Ресурсы

* **[Affinity и Anti-Affinity](../Scheduling/affinity.md)** — основное руководство по механизмам размещения подов.
* **[Taints and Tolerations](../Scheduling/taints_and_tolerations.md)** — механизм отталкивания на уровне узлов.
* **[Pod Disruption Budget](pod_disruption_budget.md)** — защита от массового вытеснения подов.
* [Официальная документация Kubernetes: Pod Affinity](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/#affinity-and-anti-affinity)
* [Официальная документация Kubernetes: Topology Spread](https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/)

---

## Связанные документы

* **[Определения](./definitions.md)** — базовые термины
* **[Основные концепции](./basic_concepts.md)** — сравнение механизмов, уровни строгости
* **[Практические сценарии](./practical_scenarios.md)** — примеры конфигурации, диагностика

---

*Этот файл является частью декомпозированной документации. Исходный файл: [pod_distribution.md](../pod_distribution.md)*
