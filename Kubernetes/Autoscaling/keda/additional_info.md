# KEDA: Дополнительная информация

## Интеграции

* **[HPA](../HPA/index.md)** — KEDA создаёт и управляет HPA, не используйте одновременно для одного Deployment.
* **[Cluster Autoscaler](../cluster_autoscaler_detailed.md)** — CA реагирует на поды, созданные KEDA.
* **[Karpenter](../Karpenter/installation.md)** — Karpenter создаёт узлы для подов, масштабированных KEDA.
* **[Prometheus](../../Prometheus/overview.md)** — Prometheus как источник метрик для KEDA.

## Ограничения

* **Один ScaledObject на Deployment** — нельзя применить несколько ScaledObject к одному ресурсу.
* **Только Deployment/StatefulSet** — не работает с DaemonSet, Job, CronJob.
* **Задержка масштабирования** — зависит от `pollingInterval` (минимум 5 секунд).
* **Внешние зависимости** — требует доступности источника метрик (RabbitMQ, Kafka, Prometheus).

## Сравнение с нативным HPA

| Характеристика | HPA | KEDA |
|----------------|-----|------|
| Источники метрик | CPU, Memory, Custom, External | 60+ scaler'ов |
| Масштабирование до 0 | Нет | Да |
| Событийное масштабирование | Нет | Да |
| Расписание (Cron) | Нет | Да |
| Сложность настройки | Низкая | Средняя |
| Управление | Прямое | Через HPA |

## Ресурсы

* [Официальная документация KEDA](https://keda.sh/)
* [GitHub репозиторий](https://github.com/kedacore/keda)
* [Список поддерживаемых scaler'ов](https://keda.sh/docs/latest/scalers/)

---

## Связанные документы

* **[Определения](./definitions.md)** — базовые термины KEDA
* **[Основные концепции](./basic_concepts.md)** — архитектура, принцип работы, типы scaler'ов
* **[Практические сценарии](./practical_scenarios.md)** — установка, конфигурация, мониторинг
