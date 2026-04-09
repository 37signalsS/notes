# Alertmanager + Karma в Kubernetes (руководство по манифестам)

## Definitions

**Alertmanager + Karma в Kubernetes** — практическое руководство по развёртыванию стека оповещений (Alertmanager + Karma) в Kubernetes через стандартные манифесты (StatefulSet, Deployment, ConfigMap, Secret, Service, Ingress). В отличие от Helm-чартов, подход предоставляет полный контроль над каждым ресурсом и демонстрирует паттерны безопасного управления секретами.

> **См. также:** [Alertmanager](../../alertmanager.md) (SSoT), [Karma Dashboard](../../karma_dashboard.md) (SSoT)

## Basic Concepts

### Ключевые особенности подхода

| Особенность | Описание |
|---|---|
| **StatefulSet для Alertmanager** | Стабильный сетевой идентификатор (`alertmanager-0`) и поддержка постоянного хранилища (PVC) для silences |
| **Init Container для секретов** | `busybox` через `sed` подставляет токены/пароли из Kubernetes Secret в шаблон конфига — секреты не хранятся в Git |
| **ConfigMap для конфигурации** | Шаблоны `alertmanager.yml` и Go-templates вынесены в отдельные ConfigMap — версионирование и обновление без пересоздания пода |
| **Интеграция с Telegram** | Использование нативного `telegram_configs` (Alertmanager 0.24+) вместо webhook-костылей |
| **Karma как агрегатор** | Отдельный Deployment Karma — единый UI для мониторинга и управления silences |

### Архитектура решения

```
┌─────────────────────────────────────────────────────┐
│                    Kubernetes                        │
│                                                      │
│  ┌─────────────────────┐    ┌────────────────────┐  │
│  │  Alertmanager        │    │  Karma             │  │
│  │  (StatefulSet)       │◄───│  (Deployment)      │  │
│  │  • init-container    │    │  • configmap       │  │
│  │  • config from emptyDir│  │  • service         │  │
│  │  • PVC (data)        │    └────────────────────┘  │
│  │  • service           │                            │
│  └─────────────────────┘                            │
│         │                                            │
│         ▼                                            │
│  ┌─────────────────────┐                            │
│  │  Ingress             │                            │
│  │  • alertmanager.example.com│                     │
│  │  • karma.example.com │                            │
│  └─────────────────────┘                            │
└─────────────────────────────────────────────────────┘
```

### Требования

| Компонент | Минимальная версия | Примечание |
|---|---|---|
| Kubernetes | 1.24+ | Поддержка StatefulSet, PVC, Secret |
| Alertmanager | 0.24+ | Нативная поддержка `telegram_configs` |
| kubectl | актуальная | Доступ к кластеру с правами создания ресурсов в namespace `monitoring` |

## Practical Scenarios

### Порядок применения манифестов

Рекомендуемая последовательность применения ресурсов:

| Шаг | Ресурс | Файл | Назначение |
|---|---|---|---|
| 1 | Secret | [secrets.md](./secrets.md) | Токены SMTP, Telegram — применяются первыми |
| 2 | ConfigMap (config) | [alertmanager-config.md](./alertmanager-config.md) | Шаблон `alertmanager.yml` с плейсхолдерами |
| 3 | ConfigMap (templates) | [alertmanager-templates.md](./alertmanager-templates.md) | Go-шаблоны для Telegram/Email |
| 4 | StatefulSet | [alertmanager-statefulset.md](./alertmanager-statefulset.md) | Alertmanager с init-container |
| 5 | ConfigMap (karma) | [karma-config.md](./karma-config.md) | Конфигурация Karma (URL Alertmanager) |
| 6 | Deployment (karma) | [karma-deployment.md](./karma-deployment.md) | Развёртывание Karma |
| 7 | Service + Ingress | [services.md](./services.md) | Сетевой доступ извне |

### Быстрый старт

После применения всех манифестов:

1. **Alertmanager UI:** `http://alertmanager.example.com` (порт 9093)
2. **Karma UI:** `http://karma.example.com` — агрегированный view алертов
3. **Проверка:** отправьте тестовый алерт через Prometheus UI → убедитесь, что уведомление пришло в Telegram/Email

## Additional Information

Детальные разделы руководства описаны выше в таблице порядка применения. Cross-ссылки на смежные материалы:

- [Alertmanager Installation](../../installation/alertmanager_installation.md) — установка Alertmanager (бинарники, Docker, кластеризация)
- [Karma Dashboard](../../karma_dashboard.md) — общее описание Karma, Helm-установка
- [kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md) — альтернативный подход через Helm-чарт
