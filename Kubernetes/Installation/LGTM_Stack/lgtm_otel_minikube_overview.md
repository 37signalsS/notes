# Развертывание стека LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

**Стек LGTM** — интегрированный набор компонентов наблюдаемости от Grafana Labs: **L**oki (логи), **G**rafana (визуализация), **T**empo (трассировки), **M**imir/Prometheus (метрики). В данном руководстве используется Prometheus из состава `kube-prometheus-stack` как упрощённая альтернатива Mimir для локальных окружений. Полная документация: **[Loki](../../../Loki/loki_overview.md)**, **[Grafana](../../../Grafana/grafana_overview.md)**, **[Tempo](../../../Tempo/index.md)**, **[Mimir](../../../Mimir/mimir_overview.md)**.

**OpenTelemetry (OTel)** — открытый стандарт CNCF для сбора, обработки и экспорта телеметрических данных (трассировки, метрики, логи). Полная документация: **[OpenTelemetry overview](../../../OpenTelemetry/opentelemetry_overview.md)**.

**Minikube** — инструмент для запуска локального однонодового кластера Kubernetes. Идеально подходит для разработки, обучения и тестирования. Подробнее: **[Minikube concepts](../../Installation/minikube/minikube_concepts.md)**.

**Docker Registry** — сервис для хранения и распространения Docker-образов. В данном руководстве разворачивается локальный registry внутри кластера. Полная документация: **[Docker Registries](../../../Docker/docker_registries.md)**.

**Cert-manager** — нативный для Kubernetes контроллер для автоматизации управления TLS-сертификатами. В данном руководстве используется для выпуска самоподписанных сертификатов. Полная документация: **[Cert-manager definitions](../../ToolsUtilities/cert_manager/definitions.md)**, **[Installation](../../ToolsUtilities/cert_manager/installation.md)**, **[Cluster CA](../../ToolsUtilities/cert_manager/cluster_ca.md)**.

> **Важно:** Для production-развертываний рекомендуется использовать **[Grafana Alloy](../../../Grafana/grafana_alloy_overview.md)** — унифицированный агент от Grafana Labs. Promtail и Grafana Agent объявлены устаревшими (EOL: Promtail — весна 2026, Grafana Agent static mode — ноябрь 2025).

---

## Основные концепции

### Архитектура решения

```
┌─────────────────┐     ┌──────────────────────────────────────────────────┐
│   Приложение    │────▶│          OpenTelemetry Collector                 │
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

1. **Приложение** — тестовое Java-приложение, инструментированное с помощью **[OpenTelemetry SDK](../../../OpenTelemetry/instrumentation_sdk.md)** для генерации логов, метрик и трассировок.

2. **OpenTelemetry Collector** — центральный компонент **[OpenTelemetry](../../../OpenTelemetry/opentelemetry_overview.md)**, который получает телеметрию по протоколу **[OTLP](../../../OpenTelemetry/otlp_protocol.md)** и экспортирует в бэкенды:
   - Логи → **[Loki](../../../Loki/loki_overview.md)** (через HTTP/Push)
   - Трассировки → **[Tempo](../../../Tempo/index.md)** (через OTLP/gRPC)
   - Метрики → Prometheus (через remote write) или **[Mimir](../../../Mimir/mimir_overview.md)**

3. **Grafana** — единый интерфейс для анализа всех сигналов (метрики, логи, трейсы) с поддержкой кросс-сигнальной корреляции.

4. **Вспомогательные компоненты:**
   - **[Cert-manager](../../ToolsUtilities/cert_manager/cluster_ca.md)** — выпуск самоподписанных сертификатов для Ingress
   - **[Local Docker Registry](../../../Docker/docker_registries.md)** — хранение кастомных образов внутри кластера
   - **Ingress Controller (nginx)** — маршрутизация внешнего трафика к веб-интерфейсам

### Сигналы наблюдаемости

| Сигнал | Описание | Сбор | Хранение | Визуализация |
| :--- | :--- | :--- | :--- | :--- |
| **Метрики** | Числовые данные о состоянии системы (CPU, memory, RPS) | OTel SDK → Collector | Prometheus/Mimir | Grafana |
| **Логи** | Записи о событиях с временными метками | OTel SDK → Collector | Loki | Grafana + Loki |
| **Трассировки** | Путь запроса через распределенную систему | OTel SDK → Collector | Tempo | Grafana + Tempo |

### Кросс-сигнальная корреляция

Ключевое преимущество стека — возможность перехода между сигналами:

1. **Метрики → Трассировки** — через **Exemplars** (Prometheus + Tempo): клик по точке на графике открывает трассировку.
2. **Логи → Трассировки** — через **Derived Fields** (Loki + Tempo): извлечение `trace_id` из лога и переход к трассировке.
3. **Трассировки → Логи** — через **Traces to Logs** (Tempo + Loki): поиск логов по времени и меткам спана.

Подробнее о концепции наблюдаемости: **[Observability Overview](../../../Concepts/Observability_and_Monitoring/observability_definitions.md)**.

---

## Практические сценарии

### Сценарий: Развертывание полного стека наблюдаемости на Minikube

**Цель:** Развернуть полный стек наблюдаемости (LGTM + OTel) на локальном кластере Minikube для разработки и тестирования.

**Предварительные требования:**

- Docker для запуска Minikube
- Minikube с ресурсами: `--cpus 4 --memory 8192mb`
- Helm 3+ для установки чартов
- kubectl, настроенный на кластер Minikube

**Этапы развёртывания:**

1. **[Подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)** — установка Minikube, добавление Helm-репозиториев
2. **[Вспомогательные компоненты](./lgtm_otel_minikube_auxiliary_components.md)** — cert-manager, Docker Registry
3. **[Стек LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)** — Prometheus, Grafana, Loki, Tempo
4. **[OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** — OTel Operator, Collector, автоматическая инструментация
5. **[Тестирование](./lgtm_otel_minikube_test_app_verification.md)** — верификация сбора телеметрии

---

## Дополнительная информация

### Таблица компонентов и версий

| Компонент | Версия Helm | Версия приложения | Документация |
| :--- | :--- | :--- | :--- |
| **kube-prometheus-stack** | `>=82.x` | Prometheus 3.x, Grafana 11.x | **[Prometheus K8s](../../Prometheus/kubernetes/overview.md)** |
| **Loki** | `>=6.x` | Loki 3.x | **[Loki overview](../../../Loki/loki_overview.md)** |
| **Tempo** | `>=1.x` | Tempo 2.x | **[Tempo overview](../../../Tempo/index.md)** |
| **OpenTelemetry Operator** | `>=0.x` | Operator 0.x | **[OTel overview](../../../OpenTelemetry/opentelemetry_overview.md)** |
| **Cert-Manager** | `>=0.16.x` | 1.x | **[Cert-manager](../../ToolsUtilities/cert_manager/definitions.md)** |
| **Docker Registry** | `>=2.x` | Registry 2.x | **[Docker Registries](../../../Docker/docker_registries.md)** |

> **Примечание:** Проверяйте актуальные версии на **[Artifact Hub](https://artifacthub.io/)** и в официальной документации.

### Требования к ресурсам (Minikube)

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Prometheus** | 500m / 1000m | 512Mi / 2Gi |
| **Grafana** | 100m / 500m | 128Mi / 512Mi |
| **Loki** | 100m / 500m | 128Mi / 512Mi |
| **Tempo** | 100m / 500m | 128Mi / 512Mi |
| **OTel Collector** | 100m / 500m | 128Mi / 512Mi |
| **Cert-Manager** | 10m / 100m | 32Mi / 128Mi |

**Минимальные требования Minikube:** `--cpus 4 --memory 8192mb`

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Grafana не открывается** | Ingress не настроен | Проверить `kubectl get ingress -A`, добавить запись в `/etc/hosts` |
| **Нет данных в Loki** | OTel Collector не экспортирует логи | Проверить логи Collector: `kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector` |
| **Сертификат не доверяется** | Самоподписанный CA | Импортировать CA в браузер или использовать `--insecure` |
| **Pod не запускается** | ImagePullBackOff | Проверить доступ к Docker Registry, наличие секрета `regcred` |
| **Tempo не принимает трейсы** | Неправильный endpoint | Проверить конфигурацию OTel Collector, сервис `tempo.tempo:4317` |

### Безопасность

> **Внимание:** Данная конфигурация предназначена **только для локальных/тестовых окружений**.

| Аспект | Текущая конфигурация | Production-рекомендация |
| :--- | :--- | :--- |
| **TLS** | Самоподписанные сертификаты (Cert-Manager) | Публичные сертификаты (Let's Encrypt) или корпоративный CA |
| **Аутентификация** | Отсутствует (внутренняя сеть) | OAuth2/OIDC через Grafana, mTLS между компонентами |
| **Сетевая изоляция** | Отсутствует | NetworkPolicies, отдельные namespace |
| **Хранение секретов** | Kubernetes Secrets | HashiCorp Vault, External Secrets Operator |

### Альтернативы для production

| Компонент | Minikube (это руководство) | Production |
| :--- | :--- | :--- |
| **Kubernetes** | Minikube | Kubespray, managed (EKS/GKE/AKS) |
| **Метрики** | Prometheus (kube-prometheus-stack) | Grafana Mimir, VictoriaMetrics |
| **Логи** | Loki (single-binary) | Loki (микросервисы), Grafana Alloy |
| **Агент** | OTel Collector | Grafana Alloy, OTel Collector |
| **Сертификаты** | Self-signed CA | Let's Encrypt, корпоративный CA |

---

**Навигация по руководству:**

- **[← Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)**
- **[Развертывание вспомогательных компонентов →](./lgtm_otel_minikube_auxiliary_components.md)**
