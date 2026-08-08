# Argo CD: Диагностика и мониторинг

> **Актуальность (2026):** В версии Argo CD v3.x произошли фундаментальные изменения в модели данных мониторинга. Метрики были оптимизированы для снижения нагрузки на Prometheus (Cardinality reduction). Основным источником данных о состоянии приложений стала метрика `argocd_app_info`.

## Определения

**Диагностика (Troubleshooting) Argo CD** — систематический процесс выявления и устранения сбоев в работе GitOps-контроллера, механизмов рендеринга манифестов и процессов синхронизации ресурсов с Kubernetes API.

**Мониторинг Argo CD** — непрерывный сбор и анализ телеметрии (метрик, логов, событий) для обеспечения наблюдаемости (Observability) процесса доставки ПО и оценки эффективности инженерных команд (DORA-метрики).

**Reconciliation Loop (Цикл сверки)** — основной процесс контроллера Argo CD, который сравнивает "желаемое" состояние (Git) с "фактическим" (Cluster) и формирует список необходимых изменений (diff).

## Базовые концепции

### Компоненты и их роль в диагностике

| Компонент | Что проверять при сбоях |
| :--- | :--- |
| `argocd-application-controller` | Логика сверки, ошибки `SyncFailed`, проблемы с производительностью (Sharding). |
| `argocd-repo-server` | Ошибки клонирования Git, таймауты Helm/Kustomize, нехватка памяти при рендеринге. |
| `argocd-server` | Ошибки RBAC (403), проблемы с UI/CLI, таймауты API-запросов. |
| `argocd-redis` | Задержки в отдаче кэша, ошибки десериализации, заполнение памяти (OOM). |
| `argocd-dex-server` | Проблемы SSO-аутентификации (OIDC/LDAP), ошибки конфигурации коннекторов. |

### Особенности мониторинга v3.x

В v3.x удалено более 20 устаревших метрик. 
- **SSoT Метрика:** `argocd_app_info` — содержит лейблы `health_status`, `sync_status`, `project`, `name`.
- **Оптимизация:** Параметр `--metrics-cache-expiration` (по умолчанию 24h) автоматически удаляет метрики для удаленных приложений, предотвращая "раздувание" базы Prometheus.

## Практические сценарии диагностики

### Сценарий 1: Отладка ошибок синхронизации (Sync Errors)

Если приложение находится в статусе `OutOfSync` или `Error`, выполните следующие шаги:

**1. Проверка diff через CLI:**
```bash
# Просмотр детальных расхождений (на стороне сервера)
argocd app diff <app-name> --server-side
```

**2. Анализ событий приложения:**
```bash
kubectl get events -n argocd --field-selector involvedObject.name=<app-name> --sort-by='.lastTimestamp'
```

**3. Типичные коды ошибок:**
- **`ComparisonError`**: Ошибка в синтаксисе манифестов или недоступность репозитория.
- **`InvalidSpecError`**: Ошибка в конфигурации объекта `Application` (например, несуществующий кластер).
- **`Namespace Not Found`**: Целевой namespace не существует и `CreateNamespace=true` не включен.

### Сценарий 2: Решение сетевых проблем и таймаутов Git

Проблемы часто возникают из-за больших репозиториев или медленных каналов.

**1. Увеличение таймаутов в `argocd-cm`:**
```yaml
data:
  # Время ожидания выполнения helm template / kustomize build
  controller.repo.server.timeout.seconds: "90" 
  # Частота опроса репозитория (по умолчанию 3m)
  timeout.reconciliation: "180s"
```

**2. Очистка локального кэша repo-server:**
Если данные в Git изменились, но Argo CD видит старую версию:
```bash
kubectl exec -it -n argocd deployment/argocd-repo-server -- rm -rf /tmp/repo-*
```

### Сценарий 3: Тюнинг производительности контроллера (Scaling)

При количестве приложений > 1000 контроллер может не успевать выполнять сверку.

**1. Шардирование (Sharding):**
Увеличьте количество реплик контроллера и настройте алгоритм распределения в `argocd-cmd-params-cm`.
```yaml
data:
  controller.sharding.algorithm: "round-robin"
```

**2. Настройка параллелизма:**
Увеличьте количество воркеров контроллера (по умолчанию 20):
```bash
# В аргументах запуска контроллера
--status-processors 50
--operation-processors 25
```

## Мониторинг и алертинг

### Ключевые метрики Prometheus

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `argocd_app_info` | Состояние здоровья и синхронизации | `health_status="Degraded"` |
| `argocd_app_reconcile_count` | Количество циклов сверки | Резкое падение (зависание) |
| `argocd_cluster_api_resource_objects` | Кол-во объектов под управлением | Рост > 100к (нагрузка на etcd) |
| `argocd_kubectl_exec_pending` | Очередь команд к K8s API | `> 20` (задержки API) |

### Рекомендуемые правила Alertmanager

```yaml
groups:
- name: ArgoCDAlerts
  rules:
  - alert: ArgoAppDegraded
    expr: argocd_app_info{health_status="Degraded"} > 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Приложение {{ $labels.name }} в статусе Degraded"

  - alert: ArgoControllerDown
    expr: absent(up{job="argocd-application-controller-metrics"} == 1)
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Контроллер Argo CD недоступен"
```

### Сбор DORA-метрик

Для построения дашбордов DORA (DevOps Research and Assessment) используйте:

1.  **Deployment Frequency (Частота):**
    `sum(increase(argocd_app_sync_total{phase="Succeeded"}[24h]))`
2.  **Change Failure Rate (% ошибок):**
    `sum(rate(argocd_app_sync_total{phase="Failed"}[1h])) / sum(rate(argocd_app_sync_total[1h]))`
3.  **Mean Time to Recovery (Время восстановления):**
    Рассчитывается как время между алертом `Degraded` и возвратом в `Healthy` (требует экспорта в VictoriaMetrics/InfluxDB).

## Технический справочник

### Тюнинг Redis

Redis является критическим узлом для кэширования манифестов. 
- **Размер кэша:** Убедитесь, что `maxmemory` в Redis позволяет хранить все отрендеренные манифесты.
- **Очистка:** Используйте политику `allkeys-lru` для автоматического удаления старых данных.

### Диагностика mTLS (v3.5+)

Если включено шифрование между компонентами, проверяйте сертификаты:
```bash
# Проверка логов на ошибки Handshake
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server | grep "TLS handshake error"
```

## Дополнительная информация

### См. также
- [Обзор Argo CD: Архитектура](./argocd_overview.md)
- [Синхронизация и политики](./synchronization.md)
- [Установка и настройка Argo CD](./argocd_installation_and_setup.md)
- [Метрики DORA в CI/CD](../../CI-CD/Core_Concepts/dora_metrics.md)

### Ссылки
- [Argo CD Metrics (Official Docs)](https://argo-cd.readthedocs.io/en/stable/operator-manual/metrics/)
- [Troubleshooting Guide](https://argo-cd.readthedocs.io/en/stable/operator-manual/troubleshooting/)
