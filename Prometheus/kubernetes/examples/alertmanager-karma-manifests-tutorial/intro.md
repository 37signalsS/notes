# Alertmanager + Karma в Kubernetes: Введение

## Определения

**Alertmanager + Karma в Kubernetes** — практическое руководство по развёртыванию стека управления оповещениями (Alertmanager + Karma) в кластере Kubernetes с использованием стандартных манифестов (StatefulSet, Deployment, ConfigMap, Secret, Service, Ingress). В отличие от автоматизированного развёртывания через Helm-чарты или Оператор, данный подход предоставляет полный контроль над каждым ресурсом и наглядно демонстрирует паттерны безопасного управления конфигурациями и секретами.

> **См. также:** [Alertmanager — общий обзор](../../../alertmanager.md), [Дашборд Karma](../../../karma_dashboard.md).

---

## Основные концепции

### Ключевые особенности подхода

| Особенность | Описание |
| :--- | :--- |
| **StatefulSet для Alertmanager** | Обеспечивает стабильный сетевой идентификатор (например, `alertmanager-0`) и поддержку постоянного хранилища через `volumeClaimTemplates` для сохранения состояния silences и базы данных уведомлений. |
| **Управление секретами** | Рассматривается два подхода: классический с `init-container` (шаблонизация конфига) и современный нативный (Alertmanager 0.27+), позволяющий использовать `${ENV_VAR}` непосредственно в `alertmanager.yml`. |
| **Декларативные шаблоны** | Использование ConfigMap для хранения `alertmanager.yml` и Go-templates (`.tmpl`) позволяет версионировать логику уведомлений отдельно от манифестов инфраструктуры. |
| **Интеграция с Telegram** | Использование встроенного `telegram_configs` (v0.24+) для прямой отправки уведомлений, что упрощает архитектуру и исключает необходимость в `alertmanager-bot`. |
| **Karma как агрегатор** | Развёртывание Karma в режиме агрегатора позволяет объединять алерты из нескольких независимых инстансов Alertmanager (например, из разных кластеров) в едином интерфейсе. |

### Архитектура решения

```text
┌─────────────────────────────────────────────────────────────┐
│                        Kubernetes                           │
│                                                             │
│  ┌─────────────────────────┐      ┌──────────────────────┐  │
│  │  Alertmanager           │      │  Karma               │  │
│  │  (StatefulSet)          │      │  (Deployment)        │  │
│  │  • Native Env Var / Init│<─────│  • ConfigMap (YAML)  │  │
│  │  • ConfigMap (Templates)│      │  • Stateless Pod     │  │
│  │  • PVC (Data Storage)   │      │  • Service           │  │
│  │  • Service (Port 9093)  │      └──────────────────────┘  │
│  └─────────────────────────┘                                │
│               ▲                                             │
│               │ (Alerts)                                    │
│  ┌─────────────────────────┐      ┌──────────────────────┐  │
│  │  Prometheus             │      │  Ingress Controller  │  │
│  │  (Внешний или в кластере)──────▶  • alertmanager.local│  │
│  └─────────────────────────┘      │  • karma.local        │  │
│                                   └──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Требования к окружению

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **Kubernetes** | 1.30+ | Рекомендуется для стабильной работы SidecarContainers и актуальных версий API. |
| **Alertmanager** | 0.27+ | Обязательна для использования нативной подстановки переменных окружения. |
| **kubectl** | Актуальная | Доступ к кластеру с правами администратора в namespace `monitoring`. |

---

## Практические сценарии

### Порядок применения манифестов

Для корректной работы зависимостей рекомендуется следующая последовательность:

| Шаг | Ресурс | Файл | Назначение |
| :--- | :--- | :--- | :--- |
| 1 | Secret | [secrets.md](./secrets.md) | Токены SMTP и Telegram — создаются первыми для внедрения в поды. |
| 2 | ConfigMap (config) | [alertmanager-config.md](./alertmanager-config.md) | Конфигурация `alertmanager.yml` с плейсхолдерами или переменными. |
| 3 | ConfigMap (templates) | [alertmanager-templates.md](./alertmanager-templates.md) | Файлы шаблонов уведомлений для кастомизации вывода. |
| 4 | StatefulSet | [alertmanager-statefulset.md](./alertmanager-statefulset.md) | Развёртывание основного инстанса Alertmanager с PVC. |
| 5 | ConfigMap (karma) | [karma-config.md](./karma-config.md) | Настройки подключения Karma к API Alertmanager. |
| 6 | Deployment (karma) | [karma-deployment.md](./karma-deployment.md) | Развёртывание веб-интерфейса Karma. |
| 7 | Service + Ingress | [services.md](./services.md) | Настройка сетевой доступности компонентов. |

### Проверка работоспособности

1.  **Alertmanager UI:** Убедитесь, что интерфейс доступен по адресу `http://alertmanager.local`. Проверьте вкладку "Status" на наличие ошибок загрузки конфига.
2.  **Karma UI:** Откройте `http://karma.local`. В нижней части экрана должен отображаться статус подключения к Alertmanager "Kubernetes Cluster: OK".
3.  **Тестирование оповещений:**
    ```bash
    # Отправка тестового алерта через API
    curl -XPOST http://alertmanager.local/api/v1/alerts -d '[{
      "labels": {"alertname": "TestAlert", "severity": "critical"},
      "annotations": {"summary": "Тестовое оповещение"}
    }]'
    ```

---

## Дополнительная информация

Данное руководство ориентировано на изучение внутреннего устройства ресурсов Kubernetes. Для промышленной эксплуатации в масштабных средах рекомендуется рассматривать:

- **[kube-prometheus-stack](../../Kube_Prometheus_Stack_Helm/overview.md)** — стандарт де-факто для автоматизированного развёртывания стека через Helm.
- **[Prometheus Operator — Alertmanager](../../operator/crd/alertmanager.md)** — управление жизненным циклом через Custom Resources (CRD).
- **[Высокая доступность Alertmanager](../../alertmanager.md#кластеризация-и-ha)** — настройка Mesh-кластера для исключения единой точки отказа.
