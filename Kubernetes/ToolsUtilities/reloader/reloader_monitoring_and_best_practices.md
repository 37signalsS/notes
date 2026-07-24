# Reloader — Мониторинг, отладка и лучшие практики

## Определения

**Мониторинг Reloader** — совокупность методов и инструментов для наблюдения за состоянием контроллера, анализа метрик производительности и диагностики процессов автоматической перезагрузки рабочих нагрузок.

**Лучшие практики (Best Practices)** — набор рекомендованных конфигураций и архитектурных подходов, обеспечивающих стабильность, безопасность и предсказуемость работы Reloader в высоконагруженных Kubernetes-кластерах.

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Основные концепции

### Точки доступа контроллера (Endpoints)

Reloader предоставляет стандартные HTTP-эндпоинты для проверки состояния и сбора данных. По умолчанию используется порт `9090`.

| Эндпоинт | Назначение | Описание |
| :--- | :--- | :--- |
| `/healthz` | Liveness Probe | Проверка того, что процесс контроллера запущен и не завис. |
| `/readyz` | Readiness Probe | Проверка готовности контроллера к обработке событий API. |
| `/metrics` | Prometheus Metrics | Экспорт технических метрик в формате OpenMetrics. |

### Метрики производительности

В версии v1.4.x доступны следующие ключевые метрики для построения дашбордов:

- `reloader_success_reload_total` — общее количество успешно инициированных Rolling Update.
- `reloader_failure_reload_total` — количество ошибок при попытке обновить рабочую нагрузку (например, из-за нехватки прав RBAC).
- `controller_runtime_reconcile_errors_total` — ошибки внутреннего цикла согласования (reconciliation loop).
- `workqueue_depth` — текущая очередь событий на обработку (помогает выявить задержки при массовых изменениях).

### Уровни детализации логов

Настройка выполняется через аргумент `--log-level`:
- **`info`** (по умолчанию) — регистрация запусков, обнаружения изменений и фактов перезагрузки.
- **`debug`** — детальный вывод процесса сопоставления аннотаций и сканирования ресурсов. Рекомендуется включать только при поиске причин, по которым Reloader "не видит" изменения.

---

## Практические сценарии

### Сценарий 1: Базовая диагностика состояния

```bash
# Проверка наличия и статуса подов контроллера
kubectl get pods -n reloader-system -l app=reloader
# → result: reloader-xxxx-xxxx 1/1 Running

# Проверка событий в пространстве имён контроллера
kubectl get events -n reloader-system --sort-by='.lastTimestamp'
# → result: Наличие событий "Normal" при успешных операциях
```

### Сценарий 2: Анализ процесса перезагрузки через логи

Для верификации того, что Reloader корректно определил изменение, используйте фильтрацию логов:

```bash
kubectl logs -f deployment/reloader -n reloader-system | grep -i "triggering"
# → result: time="..." level=info msg="Triggering rolling upgrade for Deployment 'my-app' in namespace 'default'"
```

### Сценарий 3: Проверка корректности RBAC

Если в логах видны ошибки `permission denied`, проверьте права ServiceAccount контроллера:

```bash
# Может ли Reloader обновлять Deployments в целевом Namespace?
kubectl auth can-i patch deployments --as=system:serviceaccount:reloader-system:reloader -n production
# → result: yes

# Может ли Reloader смотреть секреты (Secrets)?
kubectl auth can-i watch secrets --as=system:serviceaccount:reloader-system:reloader -n production
# → result: yes
```

### Сценарий 4: Отладка интеграции с Secrets Store CSI Driver

Если включен флаг `--enable-csi-integration=true`, Reloader должен реагировать на объекты `SecretProviderClassPodStatus`.

```bash
# Проверка наличия статусов CSI драйвера
kubectl get secretproviderclasspodstatuses -n production
# → result: Список объектов, подтверждающих монтирование секретов в поды
```

---

## Лучшие практики

### 1. Безопасность и область видимости

- **Ограничение прав:** Не используйте `ClusterRole`, если Reloader нужен только в нескольких пространствах имён. Используйте `Role` и `RoleBinding` для конкретных Namespace.
- **Namespace Selector:** В больших кластерах (>1000 секретов) используйте параметр `--namespace-selector`, чтобы контроллер не тратил ресурсы на мониторинг системных или неиспользуемых зон.

### 2. Оптимизация обновлений

- **Группировка (Debounce):** Используйте аннотацию `pause-period` для предотвращения каскадных перезапусков при массовом обновлении конфигураций (например, при деплое целого стека через Helm).
  ```yaml
  metadata:
    annotations:
      deployment.reloader.stakater.com/pause-period: "1m"
  ```
- **Явные аннотации:** Избегайте `reloader.stakater.com/auto: "true"` для критических приложений. Явно перечисляйте ресурсы через `configmap.reloader.stakater.com/reload`, чтобы избежать случайных перезапусков при изменении метаданных ConfigMap, не влияющих на приложение.

### 3. Интеграция с GitOps (ArgoCD / Flux)

- **Стратегия аннотаций:** Всегда используйте `--reload-strategy=annotations`. Это предотвращает перезапись переменных окружения в `spec.template`, что позволяет GitOps-контроллерам сохранять статус "Synced".
- **Игнорирование хешей:** Настройте GitOps-инструмент на игнорирование аннотации `reloader.stakater.com/last-reloaded-from`.

### 4. Ресурсы контроллера

- **Limits и Requests:** Обязательно задавайте лимиты памяти. При мониторинге огромного количества секретов потребление RAM может расти из-за кеширования объектов в памяти контроллера.

---

## Дополнительная информация

### Мониторинг через Prometheus Operator

Для автоматического обнаружения метрик создайте `ServiceMonitor`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: reloader
  namespace: reloader-system
  labels:
    release: prometheus-stack # Метка для вашего Prometheus-оператора
spec:
  selector:
    matchLabels:
      app: reloader
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

### См. также
- [Установка и настройка Reloader](./reloader_installation.md)
- [Практические сценарии использования](./reloader_usage_scenarios.md)
- [GitHub: Дашборды Grafana для Reloader](https://github.com/stakater/Reloader/tree/master/dashboards)
