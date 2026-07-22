# Развертывание стека LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - [Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)
> - [Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)
> - [Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)
> - [Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)
> - [Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)

## Определения

**Стек LGTM** — интегрированный набор компонентов для обеспечения [наблюдаемости](../../../Concepts/Observability_and_Monitoring/observability_definitions.md) от Grafana Labs: **L**oki (логи), **G**rafana (визуализация), **T**empo (трассировки), **M**imir/Prometheus (метрики). В данном руководстве используется Prometheus из состава `kube-prometheus-stack`. Подробнее: [Обзор Loki](../../../Loki/loki_overview.md), [Обзор Grafana](../../../Grafana/grafana_overview.md), [Обзор Tempo](../../../Tempo/index.md), [Обзор Mimir](../../../Mimir/mimir_overview.md).

**OpenTelemetry (OTel)** — открытый стандарт CNCF для сбора и экспорта телеметрии. Подробнее: [Обзор OpenTelemetry](../../../OpenTelemetry/opentelemetry_overview.md).

**Minikube** — инструмент для запуска локального кластера Kubernetes. Подробнее: [Концепции Minikube](../../Installation/minikube/minikube_concepts.md).

**Docker Registry** — сервис хранения образов. Подробнее: [Docker Registries](../../../Docker/docker_registries.md).

**Cert-manager** — контроллер для управления TLS-сертификатами. Подробнее: [Cert-manager](../../ToolsUtilities/cert_manager/definitions.md).

> **Важно:** Для продуктивных сред рекомендуется использовать [Grafana Alloy](../../../Grafana/grafana_alloy_overview.md). Grafana Alloy — это унифицированный агент для сбора метрик, логов и трассировок, который заменяет устаревшие Promtail и Grafana Agent (окончание поддержки последних запланировано на 2025–2026 годы).

---

## Основные концепции

### Архитектура решения

```
┌─────────────────┐     ┌──────────────────────────────────────────────────┐
│   Приложение    │────>│          OpenTelemetry Collector                 │
│  (Java/OTel)    │OTLP │  (прием, обработка, экспорт телеметрии)          │
└─────────────────┘     └─────────────┬────────────────┬──────────────────┘
                                      │                │
                    ┌─────────────────┼────────────────┼─────────────┐
                    │                 │                │             │
                    ▼                 ▼                ▼             ▼
              ┌──────────┐     ┌──────────┐    ┌──────────┐  ┌────────────┐
              │   Loki   │     │  Tempo   │    │Prometheus│  │  Grafana   │
              │  (логи)  │     │(трейсы)  │    │(метрики) │  │(визуализ.) │
              └──────────┘     └──────────┘    └──────────┘  └────────────┘
```

**Компоненты архитектуры:**

1. **Приложение** — инструментировано с помощью [OpenTelemetry SDK](../../../OpenTelemetry/instrumentation_sdk.md).
2. **OpenTelemetry Collector** — центральный компонент для обработки и экспорта данных по протоколу [OTLP](../../../OpenTelemetry/otlp_protocol.md).
3. **Grafana** — интерфейс для анализа сигналов с поддержкой корреляции.
4. **Вспомогательные компоненты:** [Cert-manager](../../ToolsUtilities/cert_manager/cluster_ca.md), [Локальный Docker Registry](../../../Docker/docker_registries.md), Ingress Controller.

### Сигналы наблюдаемости

| Сигнал | Описание | Сбор | Хранение | Визуализация |
| :--- | :--- | :--- | :--- | :--- |
| **Метрики** | Состояние системы (CPU, RAM) | OTel SDK -> Collector | Prometheus | Grafana |
| **Логи** | События с метками времени | OTel SDK -> Collector | Loki | Grafana |
| **Трассировки** | Путь запроса в системе | OTel SDK -> Collector | Tempo | Grafana |

### Кросс-сигнальная корреляция

Ключевое преимущество стека — связывание сигналов:

1. **Метрики -> Трассировки** — через **Exemplars** (Prometheus + Tempo).
2. **Логи -> Трассировки** — через **Derived Fields** (Loki + Tempo).
3. **Трассировки -> Логи** — через **Traces to Logs** (Tempo + Loki).

Подробнее: [Обзор наблюдаемости](../../../Concepts/Observability_and_Monitoring/observability_definitions.md).

---

## Практические сценарии

### Сценарий: Развертывание полного стека наблюдаемости на Minikube

**Цель:** Развернуть LGTM + OTel на локальном кластере для разработки.

**Предварительные требования:**

- Docker, Helm 3+, kubectl.
- Minikube: `--cpus 4 --memory 8192mb` (минимум).

**Пример запуска Minikube:**

```bash
minikube start --cpus 4 --memory 12288 --disk-size 50g --addons ingress,metrics-server
```

**Этапы развертывания:**

1. [Подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md) — Minikube и Helm.
2. [Вспомогательные компоненты](./lgtm_otel_minikube_auxiliary_components.md) — cert-manager, Registry.
3. [Стек LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md) — Prometheus, Grafana, Loki, Tempo.
4. [OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md) — Operator, Collector, инструментация.
5. [Тестирование](./lgtm_otel_minikube_test_app_verification.md) — верификация сбора.

---

## Дополнительная информация

### Таблица компонентов и версий

| Компонент | Версия Helm | Документация |
| :--- | :--- | :--- |
| **kube-prometheus-stack** | `>=87.18.x` | [Prometheus K8s](../../../Prometheus/kubernetes/overview.md) |
| **Loki** | `>=7.0.x` | [Обзор Loki](../../../Loki/loki_overview.md) |
| **Tempo** | `>=2.2.x` | [Обзор Tempo](../../../Tempo/index.md) |
| **OpenTelemetry Operator** | `>=0.120.x` | [Обзор OTel](../../../OpenTelemetry/opentelemetry_overview.md) |
| **Cert-Manager** | `>=1.21.x` | [Cert-manager](../../ToolsUtilities/cert_manager/definitions.md) |
| **Docker Registry** | `>=2.x` | [Docker Registries](../../../Docker/docker_registries.md) |

### Требования к ресурсам (Minikube)

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Prometheus** | 500m / 1000m | 512Mi / 2Gi |
| **Grafana** | 100m / 500m | 128Mi / 512Mi |
| **Loki** | 100m / 500m | 128Mi / 512Mi |
| **Tempo** | 100m / 500m | 128Mi / 512Mi |
| **OTel Collector** | 100m / 500m | 128Mi / 512Mi |

**Минимальные требования Minikube:** `--cpus 4 --memory 8192mb`. Для стабильной работы при развертывании нескольких микросервисов рекомендуется увеличить память до `12288mb` (12Gi). При использовании Mimir вместо Prometheus требования к памяти возрастают до 16Gi.

### Поиск и устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Grafana не открывается** | Ingress не настроен | Проверить Ingress, добавить запись в `/etc/hosts` |
| **Нет данных в Loki** | Ошибка экспорта | Проверить логи Collector |
| **Tempo не принимает трейсы** | Ошибка эндпоинта | Проверить конфигурацию `tempo.tempo:4317` |

### Безопасность

> **Внимание:** Конфигурация только для тестовых окружений.

| Аспект | Текущая конфигурация | Рекомендация для Production |
| :--- | :--- | :--- |
| **TLS** | Самоподписанные (Cert-Manager) | Публичные (Let's Encrypt) / Корпоративный CA |
| **Аутентификация** | Отсутствует | OIDC/OAuth2 в Grafana |
| **Изоляция** | Отсутствует | NetworkPolicies, namespace |

### Альтернативы для продуктивной среды

| Компонент | Minikube | Production |
| :--- | :--- | :--- |
| **Kubernetes** | Minikube | Managed (EKS/GKE/AKS), Kubespray |
| **Метрики** | Prometheus | Grafana Mimir, VictoriaMetrics |
| **Логи** | Loki | Loki (микросервисы), Grafana Alloy |
| **Агент** | OTel Collector | Grafana Alloy |

---

**Навигация по руководству:**

- [Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)
- [Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)
