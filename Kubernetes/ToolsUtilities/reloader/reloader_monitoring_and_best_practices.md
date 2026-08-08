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
| `/healthz` | Liveness Probe | Проверка жизнеспособности процесса. |
| `/readyz` | Readiness Probe | Готовность контроллера к обработке событий API. |
| `/metrics` | Prometheus Metrics | Экспорт технических метрик в формате OpenMetrics. |

### Ключевые метрики производительности

Для версии v1.4.x (2026) рекомендуется отслеживать следующие показатели:

- `reloader_success_reload_total` — общее количество успешно инициированных Rolling Update.
- `reloader_failure_reload_total` — количество отказов (ошибки RBAC, квоты, недоступность API).
- `controller_runtime_reconcile_errors_total` — системные ошибки цикла согласования.
- `workqueue_depth` — глубина очереди задач. Резкий рост указывает на перегрузку контроллера.
- `reloader_resource_watch_total` — количество отслеживаемых объектов (ConfigMap/Secret).

### Уровни логирования

Настройка через аргумент `--log-level`:
- **`info`** — оптимально для Production. Фиксирует изменения и триггеры перезагрузки.
- **`debug`** — детальная трассировка процесса сопоставления аннотаций. Используется при отладке "пропущенных" событий.

---

## Практические сценарии

### Сценарий 1: Базовая диагностика и проверка логов

При обнаружении того, что приложение не перезапустилось после изменения конфига:

```bash
# 1. Проверка состояния контроллера
kubectl get pods -n reloader-system -l app=reloader

# 2. Поиск события срабатывания в логах
kubectl logs -n reloader-system -l app=reloader | grep -i "triggering"
# → result: level=info msg="Triggering rolling upgrade for Deployment 'app' in namespace 'prod'"
```

### Сценарий 2: Тестирование прав RBAC (self-check)

Частая причина отказов (`failure_reload`) — нехватка прав в целевом пространстве имён:

```bash
# Может ли Reloader обновлять ресурсы в namespace 'business'?
kubectl auth can-i patch deployments --as=system:serviceaccount:reloader-system:reloader -n business
# → result: yes
```

### Сценарий 3: Отладка глобального игнорирования (v1.4.19+)

Если приложение помечено `reloader.stakater.com/ignore: "true"`, но всё равно перезапускается:

1.  Проверьте флаги запуска контроллера.
2.  Если установлен `--ignore-annotation=true`, Reloader будет игнорировать аннотацию `ignore` на ресурсах.
3.  В логах это будет отмечено как принудительное обновление по политике платформы.

### Сценарий 4: Диагностика Secrets Store CSI Driver

Если секреты ротируются во внешнем хранилище (Vault), но Reloader не реагирует:

```bash
# Проверка наличия статусов CSI драйвера
kubectl get secretproviderclasspodstatuses -n <namespace>
# → result: Должен присутствовать статус, привязанный к вашему поду
```

---

## Лучшие практики

### 1. Безопасность и изоляция

- **Scoped RBAC:** В мультитенантных кластерах избегайте `ClusterRole`. Используйте `Role` и `RoleBinding` только в разрешённых Namespace.
- **User Namespaces:** Запускайте Reloader с включенным `hostUsers: false` (v1.4+) для предотвращения атак на уровне ядра Linux.
- **NetworkPolicies:** Ограничьте входящий трафик к порту `9090` только из доверенных зон мониторинга.

### 2. Производительность в больших кластерах

- **Namespace Selector:** Всегда используйте `--namespaces-to-select` или `--namespaces-to-ignore`, чтобы уменьшить количество отслеживаемых событий API Server.
- **Debounce (Задержка):** Используйте аннотацию `pause-period: "1m"` для приложений, использующих множество ConfigMap/Secret. Это объединит несколько изменений в один Rolling Update.

### 3. GitOps-совместимость (ArgoCD / Flux)

- **Annotation Strategy:** Используйте `--reload-strategy=annotations`. Это исключает изменение `spec.template.spec.containers[...].env`, что делает `diff` в ArgoCD более чистым.
- **Ignore Differences:** Всегда добавляйте аннотацию `reloader.stakater.com/last-reloaded-from` в список игнорируемых полей в конфигурации `Application`.

### 4. Надёжность и тестирование

- **E2E Ginkgo:** При написании собственных расширений или интеграций ориентируйтесь на стандарт тестирования проекта (Ginkgo).
- **Probes:** Никогда не отключайте Liveness и Readiness пробы. Reloader активно взаимодействует с API, и его зависание может привести к "протуханию" конфигураций в кластере.

---

## Дополнительная информация

### Мониторинг через ServiceMonitor

Рекомендуемый манифест для Prometheus Operator:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: reloader
  namespace: reloader-system
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: reloader
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
      honorLabels: true
```

### См. также
- [Установка и настройка Reloader](./reloader_installation.md)
- [Практические сценарии использования](./reloader_usage_scenarios.md)
- [GitHub: Дашборды Grafana для Reloader](https://github.com/stakater/Reloader/tree/master/dashboards)
