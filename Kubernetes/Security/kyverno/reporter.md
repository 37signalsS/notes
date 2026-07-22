# Policy Reporter

## Определения

**Policy Reporter** — специализированное приложение для визуализации, мониторинга и агрегации отчетов безопасности в Kubernetes. Инструмент преобразует «сырые» данные из PolicyReports (Custom Resources) в наглядные дашборды, генерирует метрики для систем мониторинга и обеспечивает оперативную рассылку уведомлений о нарушениях политик.

В современных версиях (2024–2025) проект поддерживает инициативу **OpenReports**, что позволяет объединять результаты не только от Kyverno, но и от других инструментов (Falco, Trivy, Kube-bench) в едином интерфейсе.

---

## Основные концепции

### Возможности инструмента

| Компонент | Назначение |
|-----------|------------|
| **Web UI** | Графическая панель управления для поиска, фильтрации и глубокого анализа отчетов. |
| **Метрики** | Формирование данных в формате Prometheus для долгосрочного анализа трендов. |
| **Мульти-инструментальность** | Поддержка любых движков политик, совместимых с форматом PolicyReport (Kyverno, CEL, Falco). |
| **Высокая доступность (HA)** | Режим работы с Leader Election для предотвращения дублирования уведомлений в нагруженных кластерах. |
| **Targets (Цели)** | Отправка алертов в Slack, Telegram, Microsoft Teams, Discord, Loki, S3 и Elasticsearch. |
| **Безопасность** | Поддержка NetworkPolicies для изоляции компонентов и BasicAuth для защиты API и метрик. |

### Архитектура взаимодействия

Процесс обработки данных строится по следующей схеме:

1.  **Engine (Kyverno/CEL)**: Генерирует отчеты в виде ресурсов `PolicyReport` или `ClusterPolicyReport`.
2.  **Core компонент**: Считывает данные через Kubernetes API, используя оптимизированные очереди (`workerqueue`) для снижения нагрузки на Control Plane.
3.  **Распределение**:
    *   **UI**: Отображение в реальном времени.
    *   **Prometheus**: Экспорт числовых метрик (результаты pass/fail/warn).
    *   **Notifications**: Отправка в настроенные внешние системы (Targets).

---

## Практические сценарии

### Установка через Helm (v3.x)

Для актуальных версий чарта используется модульная структура, где плагины включаются отдельно.

```bash
# Добавление и обновление репозитория
helm repo add policy-reporter https://kyverno.github.io/policy-reporter
helm repo update

# Установка с включенным UI, метриками и плагином для Kyverno
helm install policy-reporter policy-reporter/policy-reporter \
  --namespace policy-reporter \
  --create-namespace \
  --set ui.enabled=true \
  --set plugin.kyverno.enabled=true \
  --set metrics.enabled=true \
  --set prometheus.enabled=true
# → NAME: policy-reporter, STATUS: deployed
```

### Настройка уведомлений и логирования

Пример конфигурации `values.yaml` для отправки алертов в Telegram и логирования в Grafana Loki:

```yaml
# Уведомления в Telegram
telegram:
  enabled: true
  token: "BOT_TOKEN"
  chatID: "CHAT_ID"
  minimumPriority: "critical"

# Отправка отчетов в Loki для анализа логов
loki:
  enabled: true
  host: "http://loki-gateway.monitoring.svc.cluster.local"
  minimumPriority: "warning"

# Фильтрация по пространствам имен
filter:
  namespaces:
    include: ["production", "security-audit"]
    exclude: ["kube-system", "temp-*"]
```

### Проверка состояния и доступ к UI

```bash
# Проверка подов (Core, UI и Plugins)
kubectl get pods -n policy-reporter
# → NAME                                     READY   STATUS    RESTARTS   AGE
# → policy-reporter-5f8c9d7b9c-abc12         1/1     Running   0          5m
# → policy-reporter-ui-6d9f8e7c8d-def34      1/1     Running   0          5m
# → policy-reporter-kyverno-67f9b8c5-xzy78   1/1     Running   0          5m

# Доступ к интерфейсу через Port-Forward
kubectl port-forward svc/policy-reporter-ui -n policy-reporter 8080:80
# → Forwarding from 127.0.0.1:8080 -> 80
```

### Использование REST API

```bash
# Получение сводной статистики по результатам (Pass/Fail)
curl http://localhost:8080/api/v1/statistics
# → {"pass": 120, "fail": 5, "warn": 2, "error": 0}

# Получение списка отчетов с фильтрацией по результату
curl "http://localhost:8080/api/v1/policy-reports?result=fail"
```

---

## Дополнительная информация

### Производительность и масштабируемость

| Параметр | Рекомендация |
|----------|--------------|
| **Ресурсы (RAM)** | 150–300 MB (зависит от количества PolicyReports в кластере). |
| **Ресурсы (CPU)** | 0.1–0.3 ядра. |
| **Масштабирование** | При использовании более 500 namespaces рекомендуется включить HA-режим (`replicaCount: 2` + `leaderElection.enabled: true`). |

### Решение проблем (Troubleshooting)

*   **UI пустой**: Убедитесь, что Kyverno генерирует отчеты (`kubectl get polr -A`). Проверьте, включен ли соответствующий плагин в Policy Reporter (`plugin.kyverno.enabled`).
*   **Дубликаты уведомлений**: Проверьте, не запущено ли несколько реплик Core-компонента без включенного Leader Election.
*   **Ошибка RBAC**: Policy Reporter требует прав на чтение `policyreports.wgpolicyk8s.io` во всех пространствах имен.

### Полезные ссылки

*   [Отчеты Kyverno](./reports.md) — структура и типы данных.
*   [Установка Kyverno](./install.md) — базовый движок политик.
*   [Официальная документация](https://kyverno.github.io/policy-reporter/) — актуальные параметры конфигурации.
