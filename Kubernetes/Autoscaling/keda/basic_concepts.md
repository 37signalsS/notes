# KEDA: Основные концепции

## Ключевые возможности

* **Масштабирование до нуля** — KEDA может уменьшить количество реплик до 0 при отсутствии событий.
* **Событийное масштабирование** — реакция на события из 60+ источников (Kafka, RabbitMQ, Prometheus, Cron и др.).
* **Управление HPA** — KEDA создаёт и управляет нативным объектом HPA на основе конфигурации ScaledObject.
* **Внешние метрики** — использование метрик, недоступных в стандартном Metrics Server.

## Архитектура KEDA

1. **KEDA Operator** — оператор, работающий как Deployment в namespace `keda`.
2. **Metrics Server** — компонент KEDA, предоставляющий внешние метрики через Kubernetes Metrics API.
3. **Admission Webhook** — валидация ресурсов KEDA при создании.
4. **Scalers** — плагины для подключения к источникам событий.

## Принцип работы

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────┐
│   Источник  │───▶│ KEDA Scaler  │───▶│   KEDA     │───▶│   HPA    │
│   событий   │    │ (сбор метрик)│    │  Operator  │    │          │
└─────────────┘    └──────────────┘    └─────────────┘    └────┬─────┘
                                                               │
                                                               ▼
                                                        ┌─────────────┐
                                                        │ Deployment  │
                                                        │   (scale)   │
                                                        └─────────────┘
```

## Типы scaler'ов

| Категория | Примеры scaler'ов |
|-----------|-------------------|
| **Очереди сообщений** | Kafka, RabbitMQ, AWS SQS, Azure Service Bus, Google Pub/Sub |
| **Метрики и мониторинг** | Prometheus, Datadog, New Relic, Grafana Loki |
| **Хранилища и базы данных** | MySQL, PostgreSQL, MongoDB, Redis, Elasticsearch |
| **Облачные события** | AWS CloudWatch, Azure Monitor, Google Cloud Monitoring |
| **Расписание и время** | Cron, Azure Event Hubs |
| **Другие** | HTTP requests, GitHub Actions, GitLab, Jenkins |

---

## Связанные документы

* **[Определения](./definitions.md)** — базовые термины KEDA
* **[Практические сценарии](./practical_scenarios.md)** — установка, конфигурация, мониторинг
* **[Дополнительная информация](./additional_info.md)** — интеграции, ограничения, сравнение с HPA

---

*Этот файл является частью декомпозированной документации KEDA. Исходный файл: [keda_detailed.md](../Autoscaling/keda_detailed.md)*
