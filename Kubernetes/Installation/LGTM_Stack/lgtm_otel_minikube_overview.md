# Развертывание стека LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

- **Стек LGTM (Loki, Grafana, Tempo, Mimir/Prometheus)**: Современный, полностью интегрированный стек наблюдаемости с открытым исходным кодом от Grafana Labs. Подробнее в [обзоре наблюдаемости](../../../Concepts/Observability_and_Monitoring/observability_overview.md).
  - **[Loki](../../../Loki/loki_overview.md)**: Система для сбора и агрегации логов, оптимизированная для экономичного хранения.
  - **[Grafana](../../../Grafana/grafana_overview.md)**: Платформа для визуализации и анализа данных, позволяющая объединять метрики, логи и трейсы в едином интерфейсе.
  - **[Tempo](../../../Tempo/tempo_overview.md)**: Высокомасштабируемое хранилище для распределенных трассировок.
  - **[Mimir](../../../Mimir/mimir_overview.md)**: Горизонтально масштабируемое хранилище временных рядов для метрик Prometheus. В данном руководстве используется **Prometheus** из состава `kube-prometheus-stack` как упрощенная альтернатива Mimir для локальных окружений.
- **[OpenTelemetry (OTel)](../../../OpenTelemetry/opentelemetry_overview.md)**: Открытый стандарт и набор инструментов для сбора, обработки и экспорта телеметрических данных (CNCF).
- **[Minikube](https://minikube.sigs.k8s.io/docs/)**: Инструмент для запуска локального однонодового кластера [Kubernetes](../../kubernetes_overview.md). Идеально подходит для разработки, обучения и тестирования.
- **[Docker Registry](../../../Docker/docker_registries.md)**: Сервис для хранения и распространения Docker-образов.
- **[Cert-Manager](../../ToolsUtilities/cert_manager.md)**: Нативный для Kubernetes инструмент для управления TLS-сертификатами. Полная документация: [Cert-Manager](../../ToolsUtilities/cert_manager.md).

> **Важно:** Для production-развертываний рекомендуется использовать **[Grafana Alloy](../../../Grafana/grafana_alloy_overview.md)** — унифицированный агент от Grafana Labs (замена Promtail и Grafana Agent, EOL 2025-2026).

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

1. **Приложение**: Тестовое Java-приложение, инструментированное с помощью [OpenTelemetry SDK](../../../OpenTelemetry/instrumentation_sdk.md) для генерации логов, метрик и трассировок.
2. **OpenTelemetry Collector**: Центральный компонент [OpenTelemetry](../../../OpenTelemetry/opentelemetry_overview.md), который получает телеметрию по протоколу [OTLP](../../../OpenTelemetry/otlp_protocol.md) и экспортирует в бэкенды:
    - Логи → **[Loki](../../../Loki/loki_overview.md)** (через HTTP/Push)
    - Трассировки → **[Tempo](../../../Tempo/tempo_overview.md)** (через OTLP/gRPC)
    - Метрики → **Prometheus** (через Remote Write) или **[Mimir](../../../Mimir/mimir_overview.md)**
3. **Grafana**: Единый интерфейс для анализа всех сигналов (метрики, логи, трейсы) с поддержкой кросс-сигнальной корреляции.
4. **Вспомогательные компоненты**:
    - **[Cert-Manager](../../ToolsUtilities/cert_manager/cluster_ca.md)**: Выпуск самоподписанных сертификатов для Ingress.
    - **[Local Docker Registry](../../../Docker/docker_registries.md)**: Хранение кастомных образов внутри кластера.
    - **Ingress Controller** (nginx): Маршрутизация внешнего трафика к веб-интерфейсам.

### Сигналы наблюдаемости

| Сигнал | Описание | Сбор | Хранение | Визуализация |
| :--- | :--- | :--- | :--- | :--- |
| **Метрики** | Числовые данные о состоянии системы (CPU, memory, RPS) | OTel SDK → Collector | Prometheus/Mimir | Grafana |
| **Логи** | Записи о событиях с временными метками | OTel SDK → Collector | Loki | Grafana + Loki |
| **Трассировки** | Путь запроса через распределенную систему | OTel SDK → Collector | Tempo | Grafana + Tempo |

### Кросс-сигнальная корреляция

Ключевое преимущество стека — возможность перехода между сигналами:

1. **Метрики → Трассировки**: Через **Exemplars** (Prometheus + Tempo) — клик по точке на графике открывает трассировку.
2. **Логи → Трассировки**: Через **Derived Fields** (Loki + Tempo) — извлечение `trace_id` из лога и переход к трассировке.
3. **Трассировки → Логи**: Через **Traces to Logs** (Tempo + Loki) — поиск логов по времени и меткам спана.

## Дополнительная информация

### Таблица компонентов и версий

| Компонент | Версия Helm | Версия приложения |
| :--- | :--- | :--- | :--- |
| **kube-prometheus-stack** | `>=60.x` | Prometheus 2.x, Grafana 11.x | [Prometheus K8s](../../Prometheus/kubernetes/overview.md) |
| **Loki** | `>=6.x` | Loki 3.x | [Loki overview](../../../Loki/loki_overview.md) |
| **Tempo** | `>=1.x` | Tempo 2.x | [Tempo overview](../../../Tempo/tempo_overview.md) |
| **OpenTelemetry Operator** | `>=0.x` | Operator 0.x | [OTel overview](../../../OpenTelemetry/opentelemetry_overview.md) |
| **Cert-Manager** | `>=0.16.x` | 1.x | [Cert-Manager](../../ToolsUtilities/cert_manager.md) |
| **Docker Registry** | `>=2.x` | Registry 2.x | [Docker Registries](../../../Docker/docker_registries.md) |

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

### Связанные документы

- **[Observability Overview](../../../Concepts/Observability_and_Monitoring/observability_overview.md)** — концепция наблюдаемости
- **[OpenTelemetry Architecture](../../../OpenTelemetry/architecture_signals.md)** — сигналы и архитектура OTel
- **[Grafana Alloy](../../../Grafana/grafana_alloy_overview.md)** — рекомендуемый агент для production
- **[Cert-Manager Cluster CA](../../ToolsUtilities/cert_manager/cluster_ca.md)** — настройка CA для кластера
