# Интеграция Grafana с Prometheus Operator

## Определения

**Интеграция Grafana в Prometheus Operator** — процесс обеспечения визуализации метрик, собранных Оператором, с использованием механизмов автоматического обнаружения (discovery) и провижининга. В рамках стандартного стека (`kube-prometheus-stack`) Grafana развёртывается как стандартный Deployment с вспомогательными sidecar-контейнерами для динамической загрузки конфигурации.

**Grafana Sidecar (k8s-sidecar)** — специализированный контейнер (`kiwigrid/k8s-sidecar`), работающий в том же поде, что и Grafana. Он отслеживает объекты ConfigMap и Secret в Kubernetes API по специфическим меткам и автоматически монтирует их содержимое в файловую систему Grafana, инициируя обновление дашбордов и источников данных без перезагрузки сервиса.

**Grafana Alloy** — универсальный агент сбора телеметрии (метрики, логи, трассировки), пришедший на смену Grafana Agent в конце 2025 года. Он нативно поддерживает CRD Prometheus Operator (`ServiceMonitor`, `PodMonitor`) и является рекомендуемым компонентом для интеграции в современные (2026+) observability-стеки.

> **Смотрите также:** [Обзор Grafana](../../../Grafana/grafana_overview.md), [Концепции Prometheus Operator](./concepts.md), [Конфигурация Grafana в Helm](../Kube_Prometheus_Stack_Helm/grafana_config.md).

## Основные концепции

### Почему для Grafana нет CRD в базовом Операторе

Prometheus Operator изначально спроектирован для управления жизненным циклом Prometheus и Alertmanager. Grafana является независимым инструментом визуализации. Разработчики стека выбрали путь интеграции через нативные ресурсы Kubernetes (ConfigMap, Secret) вместо создания проприетарных CRD. Это обеспечивает:
- **Переносимость:** Дашборды остаются стандартными JSON-файлами.
- **GitOps-совместимость:** Любой инструмент (ArgoCD, Flux) может управлять дашбордами через стандартные манифесты ConfigMap.
- **Гибкость:** Возможность использования различных версий Grafana и внешних инстансов без ожидания обновлений Оператора.

### Механизмы интеграции: Sidecar vs Alloy

Начиная с 2025–2026 годов, в экосистеме Kubernetes установились два основных подхода:

| Характеристика | Grafana Sidecar (стандарт KPS) | Grafana Alloy (Flow mode) |
| :--- | :--- | :--- |
| **Основная роль** | Загрузка дашбордов и Data Sources. | Сбор телеметрии и интеграция OTLP. |
| **Механизм работы** | Сканирование ConfigMap по лейблам. | Компонентная модель (River), поддержка CRD. |
| **Безопасность** | Стандартный RBAC для чтения ConfigMap. | Встроенная поддержка mTLS и шифрования. |
| **Lifecycle** | Обычный контейнер в поде. | **Native Sidecar** (K8s 1.29+) с гарантией запуска. |

### Архитектура обнаружения ресурсов

Sidecar-контейнер реализует декларативный подход "наблюдай и обновляй":

1.  **Watch (Наблюдение):** Sidecar следит за событиями в Kubernetes API.
2.  **Фильтрация:** Выбираются только ресурсы с метками:
    - `grafana_dashboard: "1"` — для дашбордов.
    - `grafana_datasource: "1"` — для источников данных.
3.  **Синхронизация:** JSON-содержимое записывается в `/tmp/dashboards` или `/etc/grafana/provisioning/datasources`.
4.  **Hot Reload:** Grafana сканирует эти директории и мгновенно отображает изменения в UI.

## Практические сценарии

### Сценарий 1: Интеграция с внешней Grafana через mTLS

Если Grafana развернута в отдельном кластере или как Managed Service:

1.  **Настройка Prometheus:** В ресурсе `Prometheus` настраивается Remote Write или открывается доступ к API через Ingress/Gateway API.
2.  **Безопасность (2026):** Использование `cert-manager` для генерации сертификатов. В Grafana создается Data Source с включенным TLS и указанием CA, клиентского сертификата и ключа.
3.  **URL источника:** Используется внешний адрес, например `https://prometheus.monitoring.example.com`.

### Сценарий 2: Управление дашбордами как код (GitOps)

Для автоматизации добавления дашбордов через ArgoCD/Flux:

1.  Создайте манифест ConfigMap.
2.  Добавьте JSON дашборда в секцию `data`.
3.  Установите необходимые аннотации для sidecar:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-health-dashboard
  labels:
    grafana_dashboard: "1" # Обязательно для обнаружения
  annotations:
    k8s-sidecar-target-directory: "/tmp/dashboards/application" # Категория в UI
spec:
  data:
    app-metrics.json: |-
      { ... JSON содержимое ... }
```

### Сценарий 3: Использование Grafana Alloy как Native Sidecar

В Kubernetes 1.29+ Alloy может работать как `initContainer` с `restartPolicy: Always`, обеспечивая сбор метрик с первых секунд жизни пода.

```yaml
spec:
  initContainers:
    - name: alloy
      image: grafana/alloy:v1.3.0
      restartPolicy: Always
      args: ["run", "--server.http.listen-addr=0.0.0.0:12345", "/etc/alloy/config.alloy"]
      # Alloy автоматически обнаружит ServiceMonitor этого приложения
```

## Дополнительная информация

### Диагностика проблем интеграции

Если дашборд или источник данных не появляется в Grafana:

1.  **Проверка меток:** `kubectl get cm -n <namespace> -l grafana_dashboard=1` — убедитесь, что ресурс виден.
2.  **Логи sidecar-контейнера:**
    `kubectl logs -f <grafana-pod> -c grafana-sc-dashboards`
    Ищите ошибки `Forbidden` (проблемы RBAC) или `Invalid JSON`.
3.  **Объем ConfigMap:** Помните о лимите в 1MB на один ConfigMap. Большие дашборды следует разбивать или использовать Gzip-сжатие (поддерживается `k8s-sidecar`).

### Тренды и перспективы (2026+)

*   **OpenTelemetry First:** Переход от проприетарных форматов к OTLP. Grafana 13+ нативно поддерживает OTLP-источники данных.
*   **eBPF-визуализация:** Интеграция с Grafana Beyla для автоматического построения дашбордов на основе RED-метрик (Rate, Errors, Duration) без модификации кода приложения.

### Связанные темы

*   **[Провиженинг Grafana](../../../Grafana/grafana_provisioning.md)** — глубокая настройка через файлы.
*   **[Источники данных Grafana](../../../Grafana/grafana_datasources.md)** — параметры подключения к Prometheus/Mimir.
*   **[Grafana Alloy — Обзор](../../../Grafana/grafana_alloy_overview.md)** — возможности нового агента.
