# CI/CD: Метрики

> **Примечание:** Этот документ перенаправляет на основной SSoT-файл по теме метрик CI/CD.
>
> **Актуальная версия:** [Метрики DORA](./Core_Concepts/dora_metrics.md)

## Определения

**CI/CD Метрики** — количественные показатели для оценки эффективности, скорости, стабильности и качества процессов непрерывной интеграции и доставки. Основным стандартом являются **[метрики DORA](./Core_Concepts/dora_metrics.md)** (DevOps Research and Assessment).

## Основные концепции

Метрики CI/CD делятся на две категории:

1. **Скорость (Throughput):** Как быстро изменения доходят до пользователя — [Lead Time](./Core_Concepts/dora_metrics.md#1-lead-time-for-changes-время-выполнения-изменений), [Deployment Frequency](./Core_Concepts/dora_metrics.md#2-deployment-frequency-частота-развертывания).
2. **Стабильность (Stability):** Насколько надежен процесс доставки — [Change Failure Rate](./Core_Concepts/dora_metrics.md#3-change-failure-rate-cfr-процент-сбоев), [MTTR](./Core_Concepts/dora_metrics.md#4-mean-time-to-recovery-mttr-среднее-время-восстановления).

## Практический сценарий: Оценка зрелости CI/CD

Подробное описание метрик, целевых уровней (Элитный, Высокий, Средний, Низкий) и практические сценарии сбора — в [Метрики DORA](./Core_Concepts/dora_metrics.md).

## Дополнительная информация

- **SSoT:** [Метрики DORA](./Core_Concepts/dora_metrics.md) — полный разбор четырёх ключевых метрик.
- **Паттерны CI/CD:** [Улучшение метрик](./ci_cd_patterns.md) через внедрение эффективных практик.
- **Анти-паттерны CI/CD:** [Избегание проблем](./ci_cd_antipatterns.md), снижающих показатели.
- **Observability:** [Метрики наблюдаемости](../Concepts/Observability_and_Monitoring/observability_definitions.md) — CI/CD-метрики как часть общей наблюдаемости системы.
