# Kyverno: Движок политик для Kubernetes

## Определения

* **Kyverno**: Открытый policy-движок для Kubernetes (<https://kyverno.io/>), позволяющий управлять политиками с помощью YAML-манифестов. Предназначен для автоматизации безопасности, обеспечения соответствия требованиям и внедрения лучших практик непосредственно в кластере Kubernetes.

## Структура документации

- [Основные концепции](./kyverno/concepts.md) — Как работает Kyverno, ключевой функционал
- [Типы правил](./kyverno/rules.md) — generate, mutate, validate, verifyImages
- [Написание политик](./kyverno/policies.md) — Структура политик, Match/Exclude, валидация, запрещающие правила
- [Практические сценарии](./kyverno/scenarios.md) — Применение в реальных условиях
- [Установка](./kyverno/install.md) — Установка через Helm, компоненты
- [Интеграция с Argo CD](./kyverno/argo-cd.md) — Конфликты и решения
- [Отчеты](./kyverno/reports.md) — Policy Reports, типы, структура
- [Background Scans](./kyverno/background.md) — Фоновое сканирование
- [Policy Reporter](./kyverno/reporter.md) — UI и метрики
- [Дополнительная информация](./kyverno/additional.md) — Aggregated Cluster Roles, историческая справка
