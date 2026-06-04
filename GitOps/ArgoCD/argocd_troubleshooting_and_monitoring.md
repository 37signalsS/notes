# ArgoCD: Диагностика и мониторинг

## Определения

**Диагностика (Troubleshooting) ArgoCD** — процесс выявления и устранения проблем, связанных с синхронизацией манифестов, доступом к репозиториям и состоянием компонентов системы.

**Мониторинг ArgoCD** — непрерывный сбор метрик производительности и состояния приложений для обеспечения надежности доставки и оценки эффективности процессов (метрики DORA).

## Базовые концепции

### Категории типовых проблем

| Категория | Типичные проявления |
| :--- | :--- |
| **Синхронизация** | Статус `OutOfSync`, ошибки рендеринга манифестов, конфликты ресурсов. |
| **Доступ к данным** | Ошибки аутентификации в Git (SSH/HTTPS), таймауты подключения. |
| **Состояние ресурсов** | Статусы приложений `Degraded`, `Missing`, `Unknown`. |
| **Производительность** | Медленная обработка репозиториев, высокая нагрузка на `application-controller`. |
| **Инфраструктура** | Проблемы с Redis (кеширование), ошибки RBAC. |

### Метрики и мониторинг

ArgoCD предоставляет встроенный экспортер метрик в формате Prometheus. Основные эндпоинты:

- `/metrics`: Общие метрики системы и контроллера.
- `/metrics/applications`: Детальные метрики по каждому приложению.

## Практические сценарии

### Сценарий 1: Диагностика компонентов через логи

При возникновении системных ошибок первым шагом является анализ логов основных компонентов в неймспейсе `argocd`:

```bash
# Логи основного контроллера приложений
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller

# Логи сервера репозиториев (ошибки Helm/Kustomize)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server

# Логи API-сервера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server
```

### Сценарий 2: Проблемы с доступом к репозиторию

Если приложение не может получить манифесты, необходимо проверить статус репозитория:

```bash
# Список всех репозиториев и их статус
argocd repo list

# Детальная проверка конкретного URL
argocd repo get <repo-url>
```

**Распространенные причины:**

- Истечение срока действия SSH-ключа или Personal Access Token (PAT).
- Некорректный формат приватного ключа (требуется OpenSSH формат без passphrase).
- Сетевые ограничения (Firewall/Proxy) между кластером и Git-сервером.

### Сценарий 3: Анализ расхождений (Diff)

Когда приложение находится в статусе `OutOfSync`, используйте CLI для визуализации различий:

```bash
argocd app diff <app-name>
```

Это поможет понять, какие поля в кластере отличаются от описанных в Git (например, из-за внешних контроллеров или ручных правок).

### Сценарий 4: Интеграция с Prometheus

Для автоматического сбора метрик в среде с Prometheus Operator используйте `ServiceMonitor`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: argocd-metrics
  namespace: argocd
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: argocd-metrics
  endpoints:
  - port: metrics
```

### Сценарий 5: Расчет метрик DORA через ArgoCD

ArgoCD является идеальным источником данных для двух из четырех метрик DORA:

| Метрика DORA | Запрос Prometheus (пример) |
| :--- | :--- |
| **Deployment Frequency** | `increase(argocd_app_sync_status{phase="Succeeded"}[24h])` |
| **Change Failure Rate** | `sum(rate(argocd_app_sync_status{phase="Failed"}[24h])) / sum(rate(argocd_app_sync_status[24h]))` |

Подробное описание методологии DORA приведено в разделе **[Метрики DORA](../../CI-CD/Core_Concepts/dora_metrics.md)**.

## Дополнительная информация

### Полезные команды CLI для диагностики

```bash
# История синхронизаций приложения
argocd app history <app-name>

# Журналы подов конкретного приложения
argocd app logs <app-name>

# Перезапуск процесса синхронизации
argocd app sync <app-name> --retry

# Принудительное удаление с очисткой ресурсов
argocd app delete <app-name> --cascade=true
```

### См. также

- [ArgoCD: Обзор системы](./argocd_overview.md)
- [ArgoCD: Установка и настройка](./argocd_installation_and_setup.md)
- [ArgoCD: Синхронизация и её политики](./synchronization.md)
- [Официальная документация: Troubleshooting](https://argo-cd.readthedocs.io/en/stable/operator-manual/troubleshooting/)
