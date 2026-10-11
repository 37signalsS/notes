# Argo CD: Диагностика и мониторинг

> **Актуальность (2026):** В версии Argo CD v3.x произошли фундаментальные изменения в модели данных мониторинга. Метрики были оптимизированы для снижения нагрузки на Prometheus (Cardinality reduction). Основным источником данных о состоянии приложений стала метрика `argocd_app_info`. Компоненты системы стали полностью gRPC-ориентированными, что повлияло на методику диагностики сетевых проблем.

## Предварительные требования

Для диагностики и мониторинга Argo CD необходимы:

1. **kubectl:** Доступ к кластеру Kubernetes с правами чтения ресурсов в namespace `argocd`.
2. **argocd CLI:** Установлен и настроен (см. [Установка и настройка](./argocd_installation_and_setup.md)).
3. **Prometheus:** Экспорт метрик Argo CD (встроен или через ServiceMonitor).
4. **Grafana:** Для визуализации дашбордов (опционально, но рекомендуется).
5. **Доступ к логам:** `kubectl logs` или централизованное хранилище логов (Loki, ELK).

## Определения

**Диагностика (Troubleshooting) Argo CD** — систематический процесс выявления и устранения сбоев в работе GitOps-контроллера, механизмов рендеринга манифестов и процессов синхронизации ресурсов с Kubernetes API.

**Мониторинг Argo CD** — непрерывный сбор и анализ телеметрии (метрик, логов, событий) для обеспечения наблюдаемости (Observability) процесса доставки ПО и оценки эффективности инженерных команд (DORA-метрики).

**Reconciliation Loop (Цикл сверки)** — основной процесс контроллера Argo CD, который сравнивает "желаемое" состояние (Git) с "фактическим" (Cluster) и формирует список необходимых изменений (diff).

**Sync Server** — в v3.x архитектуре функциональность синхронизации интегрирована в `argocd-application-controller`. Отдельный процесс `argocd-server` отвечает за REST API и UI, но не за reconciliation.

**Health Check Timeout** — время ожидания готовности ресурса (по умолчанию 5 минут для Deployment). Настраивается через `argocd-cm` параметр `timeout.reconciliation` или аннотацию `argocd.argoproj.io/health-check-timeout`.

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

### Методология диагностики

```text
Application в статусе Error/Degraded?
├── Да → Проверить логи контроллера
│         ├── Ошибка в манифесте → Сценарий 1
│         ├── Нет доступа к репозиторию → Сценарий 2
│         └── Нехватка ресурсов → Сценарий 3
└── Нет → Приложение не синхронизируется?
          ├── Auto Sync отключен → Включить (auto_sync.md)
          ├── Sync Windows активны → sync_windows.md
          └── Diff слишком большой → ignore_differences.md
```

## Практические сценарии диагностики

### Сценарий 1: Отладка ошибок синхронизации (Sync Errors)

Если приложение находится в статусе `OutOfSync` или `Error`:

**1. Просмотр diff:**
```bash
argocd app diff <app-name> --server-side
argocd app diff <app-name> --resource kind:Deployment,name:my-app
```

**2. Анализ событий:**
```bash
kubectl get events -n argocd --field-selector involvedObject.name=<app-name> --sort-by='.lastTimestamp'
```

**3. Типичные коды ошибок:**
- **`ComparisonError`**: Ошибка в синтаксисе манифестов или недоступность репозитория.
- **`InvalidSpecError`**: Ошибка в конфигурации объекта `Application`.
- **`Namespace Not Found`**: Целевой namespace не существует.
- **`PermissionDenied`**: ServiceAccount не имеет прав на создание ресурсов.

**4. Просмотр логов с фильтрацией:**
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100 | grep -A5 "<app-name>"
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=100 | grep -i "error\|fail"
```

### Сценарий 2: Решение сетевых проблем и таймаутов Git

**1. Увеличение таймаутов в `argocd-cm`:**
```yaml
data:
  controller.repo.server.timeout.seconds: "90"
  timeout.reconciliation: "180s"
  timeout.git: "120s"
```

**2. Очистка локального кэша repo-server:**
```bash
kubectl exec -it -n argocd deployment/argocd-repo-server -- rm -rf /tmp/repo-*
kubectl delete pod -n argocd -l app.kubernetes.io/name=argocd-repo-server
```

**3. Диагностика DNS:**
```bash
kubectl exec -it -n argocd deployment/argocd-repo-server -- nslookup github.com
kubectl exec -it -n argocd deployment/argocd-repo-server -- curl -vI https://github.com 2>&1 | grep -A2 "SSL certificate"
```

### Сценарий 3: Тюнинг производительности контроллера (Scaling)

При количестве приложений > 1000 контроллер может не успевать выполнять сверку.

**1. Шардирование (Sharding):**
```yaml
data:
  controller.sharding.algorithm: "round-robin"
```

**2. Настройка параллелизма:**
```bash
--status-processors 50
--operation-processors 25
```

**3. Мониторинг потребления ресурсов:**
```bash
kubectl top pod -n argocd -l app.kubernetes.io/name=argocd-application-controller
kubectl get --raw /metrics | grep argocd_kubectl_exec_pending
```

### Сценарий 4: Восстановление доступа (SSO, RBAC, пароль admin)

**1. Сброс пароля admin:**
```bash
argocd account update-password --account admin
# Или через kubectl
kubectl -n argocd delete secret argocd-secret
kubectl -n argocd rollout restart deployment argocd-server
```

**2. Диагностика SSO:**
```bash
kubectl -n argocd get configmap argocd-cm -o yaml | grep -A20 "url\|oidc\|dex"
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server --tail=50
```

**3. Диагностика RBAC:**
```bash
kubectl -n argocd get configmap argocd-rbac-cm -o yaml
argocd account list
argocd account get --account <username>
```

### Сценарий 5: Диагностика потребления ресурсов (OOM/CrashLoopBackOff)

```bash
kubectl top pods -n argocd
kubectl describe pod -n argocd <pod-name> | grep -A10 "Last State\|Restart Count"
kubectl get pod -n argocd <pod-name> -o jsonpath='{.spec.containers[*].resources}'
```

**Типичные причины OOM:**
- Большое количество приложений (>5000) без шардирования
- Утечки памяти при работе с большими Helm-чартами (>100 файлов)
- Нехватка памяти Redis при большом объеме кэшированных манифестов

### Сценарий 6: Диагностика проблем с репозиторием

**1. Проверка доступа:**
```bash
argocd repo list
argocd repo get <repo-url>
argocd repo rm <repo-url>
argocd repo add <repo-url> <username> --upsert
```

**2. Очистка кэша:**
```bash
kubectl exec -it -n argocd deployment/argocd-repo-server -- ls -la /tmp/repo-*
kubectl exec -it -n argocd deployment/argocd-repo-server -- rm -rf /tmp/repo-<hash>
```

### Сценарий 7: Диагностика ApplicationSet Controller

**1. Проверка логов ApplicationSet:**
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller --tail=100
```

**2. Проверка состояния ApplicationSet:**
```bash
kubectl get applicationset -n argocd
kubectl describe applicationset <name> -n argocd
```

**3. Типичные ошибки:**
- **`Error generating application`**: Ошибка в шаблоне переменных или отсутствие секрета.
- **`Application create error`**: Конфликт имён или дублирование приложений.
- **`SCM Provider error`**: Недоступность API Git-хостинга или истекший токен.

### Сценарий 8: Диагностика Crossplane Managed Resources

Для динамических окружений с Crossplane:

```bash
# Проверка состояния Managed Resources
kubectl get managed -n <namespace>
kubectl describe managed <name> -n <namespace>

# Просмотр логов Crossplane
kubectl logs -n crossplane-system -l app.kubernetes.io/name=crossplane --tail=100

# Проверка обработчиков
kubectl get compositeresourcedefinitions
kubectl get compositions
```

### Сценарий 9: Debug Logging и Tracing

**Включение расширенного логирования:**
```yaml
# argocd-cm ConfigMap
data:
  # Уровень логирования: debug, info, warn, error
  controller.log.level: "debug"
  server.log.level: "debug"
  repoServer.log.level: "debug"
```

**Настройка OpenTelemetry (v3.x):**
```yaml
# Аргументы запуска контроллера
--otelendpoint="otel-collector.observability:4317"
--otelservice="argocd-application-controller"
```

**Просмотр логов с фильтрацией по уровню:**
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=200 | grep -i "debug\|warn\|error"
```

## Мониторинг и алертинг

### Ключевые метрики Prometheus

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `argocd_app_info` | Состояние здоровья и синхронизации (labels `health_status`, `sync_status`) | `health_status="Degraded"` |
| `argocd_app_reconcile` | Гистограмма длительности сверки, секунды | Рост p99 (замедление сверки) |
| `argocd_cluster_api_resource_objects` | Кол-во объектов под управлением | Рост > 100к (нагрузка на etcd) |
| `argocd_kubectl_exec_pending` | Очередь команд к K8s API | `> 20` (задержки API) |
| `argocd_app_sync_total` | Общее количество синхронизаций (label `phase`) | Падение до 0 (контроллер завис) |
| `argocd_app_sync_total{phase="Error"}` | Ошибки синхронизации | Рост > 5/мин |
| `argocd_git_fetch_fail_total` | Ошибки git fetch в repo-server | Рост > 10/час |
| `argocd_redis_request_total` | Redis-запросы при сверке (label `failed`) | Рост `failed="true"` |
| `argocd_app_sync_blocked` | Автоматический синк заблокирован sync windows, gauge `0`/`1` (v3.5+) | `== 1` дольше ожидаемого заморозки |
| `argocd_app_sync_window_error` | Sync windows не вычислены (fail-closed), gauge `0`/`1` (v3.5+) | `== 1` (битая конфигурация окон) |

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

  - alert: ArgoAppOutOfSync
    expr: argocd_app_info{sync_status="OutOfSync"} > 0
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "Приложение {{ $labels.name }} не синхронизировано более 15 минут"

  - alert: ArgoControllerDown
    expr: absent(up{job="argocd-application-controller-metrics"} == 1)
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Контроллер Argo CD недоступен"

  - alert: ArgoRepoServerHighLatency
    expr: histogram_quantile(0.99, rate(argocd_git_request_duration_seconds_bucket[5m])) > 10
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Высокая латентность repo-server (p99 > 10s)"

  - alert: ArgoHighReconcileErrors
    expr: rate(argocd_app_sync_total{phase="Error"}[5m]) > 0.1
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Повышенная частота ошибок синхронизации"
```

### Сбор DORA-метрик

1. **Deployment Frequency:**
   `sum(increase(argocd_app_sync_total{phase="Succeeded"}[24h]))`
2. **Change Failure Rate:**
   `sum(rate(argocd_app_sync_total{phase="Failed"}[1h])) / sum(rate(argocd_app_sync_total[1h]))`
3. **Mean Time to Recovery:**
   Время между алертом `Degraded` и возвратом в `Healthy`.

### Grafana Dashboard

Рекомендуемые панели для дашборда Argo CD:

| Панель | Метрика | Тип |
| :--- | :--- | :--- |
| Всего приложений | `count(argocd_app_info)` | Stat |
| Здоровые / Больные | `argocd_app_info by (health_status)` | Pie Chart |
| Частота синхронизации | `rate(argocd_app_sync_total[5m])` | Time Series |
| Ошибки синхронизации | `rate(argocd_app_sync_total{phase="Error"}[5m])` | Time Series |
| Латентность kubectl-запросов | `histogram_quantile(0.99, rate(argocd_kubectl_request_duration_seconds_bucket[5m]))` | Time Series |
| Потребление памяти | `container_memory_usage_bytes{namespace="argocd"}` | Time Series |

## Технический справочник

### Тюнинг Redis

Redis является критическим узлом для кэширования манифестов.
- **Размер кэша:** Убедитесь, что `maxmemory` позволяет хранить все отрендеренные манифесты.
- **Очистка:** Используйте политику `allkeys-lru` для автоматического удаления старых данных.
- **Мониторинг:** Проверяйте `redis_connected_clients` и `redis_memory_used_bytes`.

### Диагностика mTLS

Если включено шифрование между компонентами:
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server | grep "TLS handshake error"
kubectl get secret argocd-repo-server-tls -n argocd -o yaml
```

### Управление логами в production

```yaml
# Ротация логов через Kubernetes
spec:
  containers:
  - name: argocd-application-controller
    env:
    - name: ARGOCD_CONTROLLER_LOG_LEVEL
      value: "info"
```

**Централизованный сбор логов:**
- **Loki + Grafana:** Легковесное решение для Kubernetes. Метки: `app=argocd`, `namespace=argocd`.
- **ELK Stack:** Полноценный стек с полнотекстовым поиском. Filebeat как sidecar.
- **Fluentd/Fluent Bit:** Агрегаторы логов с маршрутизацией по уровням.

### Оптимизация потребления ресурсов

| Компонент | Рекомендуемые limits | Причина |
| :--- | :--- | :--- |
| `argocd-application-controller` | CPU: 2, Memory: 2Gi | Вычислительно intensive reconciliation |
| `argocd-repo-server` | CPU: 2, Memory: 2Gi | Рендеринг Helm/Kustomize |
| `argocd-server` | CPU: 1, Memory: 512Mi | REST API и UI |
| `argocd-redis` | CPU: 500m, Memory: 512Mi | Кэширование |

## Дополнительная информация

### См. также
- [Обзор Argo CD: Архитектура](./argocd_overview.md)
- [Синхронизация и политики](./synchronization.md)
- [Установка и настройка Argo CD](./argocd_installation_and_setup.md)
- [Уведомления Argo CD](./argocd_notifications.md)
- [Helm интеграция](./helm_integration.md)
- [SSO с GitLab](./argocd_sso_gitlab.md)
- [API автоматизация](./argocd_api_automation.md)
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Изоляция проектов, квоты, restrictions, кастомные роли.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.
- [Disaster Recovery](./argocd_disaster_recovery.md) — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.

### Ссылки
- [Argo CD Metrics (Official Docs)](https://argo-cd.readthedocs.io/en/stable/operator-manual/metrics/)
- [Troubleshooting Guide](https://argo-cd.readthedocs.io/en/stable/operator-manual/troubleshooting/)
- [Grafana Dashboards for Argo CD](https://grafana.com/grafana/dashboards/?search=argocd)
- [OpenTelemetry Integration](https://argo-cd.readthedocs.io/en/stable/operator-manual/open-telemetry/)
