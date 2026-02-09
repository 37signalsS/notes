# Развертывание стека LGTM и OpenTelemetry на Minikube

## Определения

- **Стек LGTM (Loki, Grafana, Tempo, Mimir)**: Современный, полностью интегрированный стек наблюдаемости с открытым исходным кодом от Grafana Labs. Он включает в себя:
  - **[Loki](../Loki/loki_overview.md)**: Система для сбора и агрегации логов, оптимизированная для экономичного хранения.
  - **[Grafana](../Grafana/grafana_overview.md)**: Платформа для визуализации и анализа данных, позволяющая объединять метрики, логи и трейсы в едином интерфейсе.
  - **[Tempo](../Tempo/tempo_overview.md)**: Высокомасштабируемое хранилище для распределенных трассировок.
  - **[Mimir](../Mimir/mimir_overview.md)**: Горизонтально масштабируемое хранилище временных рядов для метрик Prometheus.
    Более подробно концепция описана в [обзоре наблюдаемости](../Concepts/Observability_and_Monitoring/observability_overview.md).
- **[OpenTelemetry (OTel)](../OpenTelemetry/opentelemetry_overview.md)**: Открытый стандарт и набор инструментов для сбора, обработки и экспорта телеметрических данных. Подробнее см. в [обзоре OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md).
- **[Minikube](https://minikube.sigs.k8s.io/docs/)**: Инструмент для запуска локального однонодового кластера [Kubernetes](../../Kubernetes/kubernetes_overview.md). Идеально подходит для разработки, обучения и тестирования.
- **[Docker Registry](../../Docker/docker_registries.md)**: Сервис для хранения и распространения Docker-образов.
- **[Cert-Manager](../../Kubernetes/ToolsUtilities/cert_manager.md)**: Нативный для Kubernetes инструмент для управления TLS-сертификатами.

## Основные концепции

### Архитектура решения

1. **Приложение**: Тестовое Java-приложение, инструментированное с помощью [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md) для генерации логов, метрик и трассировок.
2. **OpenTelemetry Collector**: Центральный компонент [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md), который получает телеметрию от приложения по протоколу OTLP. Он обрабатывает данные и экспортирует их в соответствующие бэкенды:
    - Логи → **Loki**
    - Трассировки → **Tempo**
    - Метрики → **Mimir** (через Prometheus)
3. **Стек LGTM**: Набор инструментов для хранения и визуализации телеметрии. **Grafana** выступает в роли единого интерфейса для анализа всех собранных данных.
4. **Вспомогательные компоненты**:
    - **[Cert-Manager](../../Kubernetes/ToolsUtilities/cert_manager.md)**: Управляет TLS-сертификатами для защищенного доступа к веб-интерфейсам через [Ingress](../../Kubernetes/Networking/ingress.md).
    - **[Local Docker Registry](../../Docker/docker_registries.md)**: Позволяет хранить и распространять кастомные Docker-образы внутри кластера без необходимости публиковать их в Docker Hub.