# Argo CD: Диагностика и мониторинг

## Определения

**Диагностика (Troubleshooting) Argo CD** — процесс выявления и устранения проблем, связанных с синхронизацией манифестов, доступом к репозиториям, конфликтами ресурсов Kubernetes и состоянием компонентов системы.

**Мониторинг Argo CD** — непрерывный сбор метрик производительности (Prometheus), анализ логов и визуализация состояния приложений для обеспечения надежности доставки и оценки эффективности процессов (метрики DORA).

## Основные концепции

### Категории типовых проблем

| Категория | Типичные проявления |
| :--- | :--- |
| **Синхронизация** | Статус `OutOfSync`, ошибки рендеринга (Helm/Kustomize), конфликты `Server-Side Apply`. |
| **Доступ к данным** | Ошибки аутентификации в Git/OCI (SSH/HTTPS), таймауты подключения к API. |
| **Состояние ресурсов** | Статусы приложений `Degraded` (ошибки health-checks), `Missing` (удаленные ресурсы). |
| **Производительность** | Медленная обработка репозиториев (высокий `reconciliation time`), нагрузка на Redis. |
| **RBAC и доступ** | Ошибки `ComparisonError` или `Forbidden` при выполнении операций в UI/CLI. |

### Особенности мониторинга v3.x (2026)

В версии Argo CD v3.0 была проведена значительная очистка метрик. Устаревшие метрики (например, `argocd_app_sync_status`) удалены. 

**Ключевое изменение:** Единственным источником истины для статуса приложений стала метрика **`argocd_app_info`**. Она содержит метки `sync_status` и `health_status`, которые необходимо использовать в запросах Prometheus.

## Практические сценарии диагностики

### Сценарий 1: Анализ системных логов

Логи разделены по функциональным компонентам. В v3.x рекомендуется использовать структурированный вывод логов в формате JSON для анализа через системы типа ELK или Loki.

```bash
# Ошибки синхронизации и логика контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller

# Ошибки рендеринга манифестов (Helm lint, Kustomize build)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server

# Ошибки авторизации и взаимодействия с пользователем
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server
```

### Сценарий 2: Глубокая отладка синхронизации (Hard Refresh)

Если ресурсы в кластере отображаются некорректно или "висят" в статусе `Unknown`, это может быть связано с переходом Argo CD на аннотации вместо лейблов для отслеживания ресурсов (v3.1+).

**Решение через CLI:**
```bash
# Принудительное обновление кэша метаданных приложения
argocd app get <app-name> --refresh --hard

# Просмотр детальных расхождений через Server-Side Diff
argocd app diff <app-name> --server-side
```

### Сценарий 3: Диагностика RBAC (v3.5+)

Версии 3.x ввели гранулярный RBAC для ресурсов и логов. Если пользователь видит пустой экран или ошибку `403`, проверьте конфигурацию `argocd-rbac-cm`.

**Проверка прав через CLI (admin):**
```bash
# Проверить, имеет ли пользователь права на действие
argocd admin rbac can <user> <action> <resource>
```

## Мониторинг и алертинг

### Правила алертинга Prometheus (v3.x)

Рекомендуемые правила для Prometheus Alertmanager (2026):

| Название алерта | Уровень | Запрос PromQL |
| :--- | :--- | :--- |
| **Приложение в Degraded** | Critical | `argocd_app_info{health_status="Degraded"} > 0` |
| **Дрейф конфигурации** | Warning | `argocd_app_info{sync_status="OutOfSync"} > 0` (for: 30m) |
| **Ошибка синхронизации** | Warning | `increase(argocd_app_sync_total{phase="Failed"}[15m]) > 0` |
| **Контроллер недоступен** | Critical | `absent(up{job="argocd-application-controller-metrics"} == 1)` |
| **Перегрузка контроллера** | Warning | `argocd_kubectl_exec_pending > 10` |

### Сбор метрик DORA

Для оценки эффективности процессов (DevOps Research and Assessment) используйте следующие расчеты на основе метрик Argo CD:

1. **Deployment Frequency (Частота деплоев):**
   `sum(increase(argocd_app_sync_total{phase="Succeeded"}[24h]))`
2. **Change Failure Rate (Процент ошибок):**
   `sum(rate(argocd_app_sync_total{phase="Failed"}[1h])) / sum(rate(argocd_app_sync_total[1h]))`

## Дополнительная информация

### Технические лимиты и тюнинг

- **Cardinality (Кардинальность):** В v3.x включите `--metrics-cache-expiration=24h` в параметрах `application-controller`, чтобы очищать метрики удаленных приложений и не перегружать Prometheus.
- **Resource Exclusions:** Используйте `resource.exclusions` в `argocd-cm`, чтобы игнорировать динамические ресурсы (например, EndpointSlice), которые создают лишний шум в метриках и логах.

### Полезные команды отладки

```bash
# Просмотр истории синхронизации
argocd app history <app-name>

# Остановка зависшей операции
argocd app terminate-op <app-name>

# Глобальная пауза синхронизации в кластере (v3.4+)
# Добавьте аннотацию в секрет кластера:
# argocd.argoproj.io/reconciliation-pause: "true"
```

### См. также

- [Обзор Argo CD](./argocd_overview.md)
- [Синхронизация и политики](./synchronization.md)
- [Установка и настройка Argo CD](./argocd_installation_and_setup.md)
- [Метрики DORA](../../CI-CD/Core_Concepts/dora_metrics.md)
