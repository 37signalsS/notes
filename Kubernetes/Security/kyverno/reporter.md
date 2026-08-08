# Визуализация и мониторинг: Policy Reporter

## Определения

**Policy Reporter** — специализированный инструмент для визуализации, агрегации и мониторинга отчетов безопасности в Kubernetes. Он преобразует декларативные данные из ресурсов `PolicyReport` ( Custom Resource) в интерактивные дашборды, формирует метрики для систем наблюдения (Prometheus/Grafana) и обеспечивает маршрутизацию уведомлений о нарушениях.

На 2026 год Policy Reporter является ключевым компонентом для реализации **Compliance-as-Code**, поддерживая стандарт **OpenReports**. Это позволяет объединять результаты проверок от различных движков (Kyverno, Falco, Trivy, Kube-bench) в единой консоли управления.

---

## Основные концепции

### Возможности и компоненты

| Компонент | Функциональное назначение |
| :--- | :--- |
| **Web UI** | Графический интерфейс для анализа текущего состояния безопасности и поиска нарушений. |
| **Metrics Engine** | Генерация Prometheus-метрик для анализа трендов безопасности во времени. |
| **OpenReports Plugin** | Обеспечивает прием и нормализацию данных от сторонних сканеров (Falco, Trivy). |
| **High Availability (HA)** | Поддержка режима Active-Passive с Leader Election для предотвращения дублирования алертов. |
| **Target Routing** | Гибкая настройка получателей уведомлений (Slack, Telegram, Loki, Elasticsearch, S3). |

### Модульная архитектура (OpenReports)

Процесс сбора и визуализации данных строится на принципе нормализации:

1.  **Сбор данных**: Плагины (Kyverno, Falco) отслеживают изменения соответствующих ресурсов в кластере.
2.  **Нормализация**: Данные приводятся к стандарту `openreports.io`, что позволяет корректно отображать специфические метаданные (например, уровни CVE от Trivy или системные вызовы от Falco).
3.  **Обработка**: Core-компонент применяет фильтры и правила маршрутизации.
4.  **Визуализация и алертинг**: Обновление UI и отправка событий в настроенные Targets.

---

## Практические сценарии

### 1. Промышленная установка через Helm

В 2026 году рекомендуется модульная установка с разделением компонентов для повышения безопасности.

```bash
# Добавление репозитория
helm repo add policy-reporter https://kyverno.github.io/policy-reporter
helm repo update

# Установка с HA и интеграцией Kyverno
helm install policy-reporter policy-reporter/policy-reporter \
  --namespace policy-reporter \
  --create-namespace \
  --set ui.enabled=true \
  --set plugin.kyverno.enabled=true \
  --set metrics.enabled=true \
  --set leaderElection.enabled=true \
  --set replicaCount=2
```

### 2. Настройка безопасности UI (Ingress + BasicAuth)

Для защиты доступа к дашборду рекомендуется использовать Ingress-контроллер с аутентификацией.

**Конфигурация Ingress в `values.yaml`**:
```yaml
ui:
  ingress:
    enabled: true
    annotations:
      kubernetes.io/ingress.class: nginx
      nginx.ingress.kubernetes.io/auth-type: basic
      nginx.ingress.kubernetes.io/auth-secret: basic-auth-secret
    hosts:
      - host: policy-reporter.example.org
        paths:
          - path: /
            pathType: ImplementationSpecific
```

### 3. Интеграция Falco и Trivy (OpenReports)

Для объединения runtime-событий Falco и результатов сканирования Trivy в Policy Reporter необходимо включить соответствующие адаптеры.

**Настройка плагинов**:
```yaml
plugin:
  falco:
    enabled: true
  trivy:
    enabled: true
# После включения Policy Reporter начнет отображать CVE и runtime-инциденты в общем списке.
```

### 4. Маршрутизация уведомлений (Slack и Loki)

Пример настройки `values.yaml` для разделения потоков данных: критические алерты в Slack, все события — в Loki.

```yaml
target:
  slack:
    enabled: true
    webhook: "https://hooks.slack.com/services/..."
    minimumPriority: "critical"
  loki:
    enabled: true
    host: "http://loki-gateway.monitoring.svc:3100"
    minimumPriority: "warning"
    # Добавление кастомных лейблов для Loki
    customLabels:
      cluster: "prod-cluster-01"
```

---

## Дополнительная информация

### Производительность и лимиты

| Аспект | Рекомендация | Примечание |
| :--- | :--- | :--- |
| **Память (RAM)** | 256 MB - 1 GB | Зависит от количества `PolicyReport` в памяти. |
| **Процессор (CPU)** | 200m - 500m | Основная нагрузка приходится на парсинг JSON/YAML. |
| **Кэширование** | Включено по умолчанию | Снижает нагрузку на API-сервер K8s. |

### Поиск и устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **UI пустой** | Плагин не активирован или нет прав RBAC. | Проверьте `plugin.<name>.enabled` и наличие ClusterRole. |
| **Дубли алертов** | Отключен Leader Election в HA-режиме. | Убедитесь, что `leaderElection.enabled=true`. |
| **Нет данных в Loki** | Ошибка авторизации или сетевой доступ. | Проверьте логи пода `policy-reporter` на наличие 401/403 ошибок. |

### См. также
- [Отчеты Kyverno и стандарты PolicyReport](./reports.md)
- [Интеграция Kyverno с Argo CD](./argo-cd.md)
- [Официальный репозиторий Policy Reporter](https://github.com/kyverno/policy-reporter)
