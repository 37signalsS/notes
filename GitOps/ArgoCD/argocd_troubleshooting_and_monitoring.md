# ArgoCD: Устранение неполадок и мониторинг

## Определения

**Troubleshooting ArgoCD** — процесс диагностики и устранения проблем с синхронизацией, развёртыванием и мониторингом приложений в ArgoCD.

## Базовые концепции

### Типы проблем в ArgoCD

| Категория | Примеры |
| :--- | :--- |
| **Синхронизация** | Ошибки применения манифестов, конфликты ресурсов |
| **Доступ к репозиторию** | Неверные учётные данные, SSH-ключи |
| **Health статус** | Приложения в статусе `Degraded`, `Missing` |
| **Производительность** | Медленная синхронизация, таймауты API |
| **Безопасность** | Ошибки аутентификации, RBAC |

## Практические сценарии

### Сценарий 1: Диагностика ошибок синхронизации

**Проверка логов компонентов:**
```bash
# Application Controller
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller

# Repo Server
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server

# Server
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server
```

**Просмотр различий между Git и кластером:**
```bash
argocd app diff <app-name>
```

**Проверка статуса приложения:**
```bash
argocd app get <app-name>
argocd app list
```

### Сценарий 2: Проблемы с доступом к репозиторию

**Проверка подключенных репозиториев:**
```bash
argocd repo list
```

**Тестирование подключения:**
```bash
argocd repo get <repo-url>
```

**Частые причины:**
- Истёк SSH-ключ или токен доступа
- Изменился URL репозитория
- Блокировка сетевым экраном
- Неправильный формат ключа (должен быть без passphrase)

**Решение:**
```bash
# Обновление репозитория
argocd repo rm <repo-url>
argocd repo add <repo-url> --ssh-private-key-path ~/.ssh/id_rsa
```

### Сценарий 3: Проблемы с образами контейнеров

**ImagePullBackOff / ErrImagePull:**
```bash
# Проверка событий в namespace
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# Проверка secret для registry
kubectl get secret <registry-secret> -n <namespace> -o yaml
```

**Для локальных кластеров (Minikube/Kind):**
```bash
# Загрузка образа в кластер
minikube image load <image>:<tag>
kind load docker-image <image>:<tag>
```

### Сценарий 4: Self-Healing и Prune

**Параметры политики синхронизации:**

| Параметр | Описание |
| :--- | :--- |
| `selfHeal: true` | Автоматически восстанавливает ресурсы, удалённые вручную из кластера |
| `prune: true` | Удаляет ресурсы из кластера, которые отсутствуют в Git |

**Проверка политики:**
```bash
argocd app get <app-name> -o yaml | grep -A 10 syncPolicy
```

**Удаление приложения и всех его ресурсов:**
```bash
# Через CLI
argocd app delete <app-name> --cascade=true

# Через kubectl
kubectl delete -f my-application.yaml
```

### Сценарий 5: Мониторинг и метрики

ArgoCD предоставляет встроенный экспортер метрик для Prometheus.

**Эндпоинты метрик:**
- `/metrics` — основные метрики
- `/metrics/applications` — метрики приложений

**Ключевые метрики:**

| Метрика | Описание |
| :--- | :--- |
| `argocd_app_info` | Информация о приложениях |
| `argocd_app_sync_status` | Статус синхронизации |
| `argocd_app_health_status` | Статус здоровья |
| `argocd_repo_server_queue_size` | Размер очереди Repo Server |
| `argocd_cluster_api_requests` | Запросы к Kubernetes API |

**Интеграция с Prometheus:**
```yaml
# ServiceMonitor для Prometheus Operator
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

### Сценарий 6: Метрики DORA через ArgoCD

ArgoCD позволяет отслеживать ключевые метрики DORA через Prometheus. Подробное описание: **[Метрики DORA](../../CI-CD/Core_Concepts/dora_metrics.md)**.

| Метрика DORA | Источник в ArgoCD |
| :--- | :--- |
| **Deployment Frequency** | Количество успешных синхронизаций (`argocd_app_sync_status{phase="Succeeded"}`) |
| **Change Fail Rate** | Процент синхронизаций со статусом `Failed` |
| **MTTR** | Время между неудачной и последующей успешной синхронизацией |
| **Lead Time** | Время от коммита до успешной синхронизации (требует интеграции с Git) |

**Пример запроса Prometheus для Deployment Frequency:**
```promql
# Количество успешных развёртываний за 24 часа
increase(argocd_app_sync_status{phase="Succeeded"}[24h])
```

**Пример для Change Fail Rate:**
```promql
# Процент неудачных синхронизаций
sum(increase(argocd_app_sync_status{phase="Failed"}[24h])) 
/ 
sum(increase(argocd_app_sync_status[24h])) * 100
```

### Сценарий 7: Ограничения мониторинга с ArgoCD

- **Неполное покрытие:** Не все части пайплайна отслеживаются
- **Изолированная аналитика:** Данные из разных источников слабо связаны
- **Сложность корреляции:** Трудности с связью метрик, логов и трассировок

**Решение:** Дополнение ArgoCD инструментами наблюдаемости:
- **Keptn:** Quality Gates, пре/пост-деплой проверки
- **Backstage:** Developer Portal для единой точки входа
- **Grafana:** Визуализация метрик из нескольких источников

## Дополнительная информация

### Полезные команды CLI

```bash
# История синхронизаций
argocd app history <app-name>

# Журналы подов приложения
argocd app logs <app-name>

# Перезапуск синхронизации
argocd app sync <app-name> --retry

# Откат к предыдущей ревизии
argocd app rollback <app-name> [revision]

# Ожидание завершения синхронизации
argocd app wait <app-name> --sync --health
```

### Ссылки

- **[Метрики DORA](../../CI-CD/Core_Concepts/dora_metrics.md)** — основное руководство по метрикам
- **[Синхронизация](./synchronization.md)** — политики и опции
- **[Официальная документация](https://argo-cd.readthedocs.io/en/stable/operator-manual/troubleshooting/)**
