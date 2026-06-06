# Reloader — Мониторинг, отладка и лучшие практики

## Определения

**Мониторинг Reloader** — набор практик и инструментов для отслеживания состояния контроллера Reloader, диагностики проблем и верификации корректности обработки изменений объектов `ConfigMap` и `Secret`.

**Лучшие практики (Best Practices)** — проверенные методы настройки и эксплуатации Reloader для обеспечения стабильности Kubernetes-кластера и предсказуемости обновлений.

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Основные концепции

### Эндпоинты контроллера

Reloader предоставляет HTTP-эндпоинты (точки доступа) для проверки состояния и сбора метрик:

| Эндпоинт | Назначение | Порт |
| :--- | :--- | :--- |
| `/healthz` | Liveness probe (проверка живучести) | 9090 |
| `/readyz` | Readiness probe (проверка готовности) | 9090 |
| `/metrics` | Метрики в формате Prometheus | 9090 |

### Уровни логирования

Настройка уровня детализации логов выполняется через флаг `--log-level`:

- **`info`** — основные события: запуск, обнаружение изменений, инициирование перезагрузки.
- **`debug`** — детальная информация о процессе сканирования ресурсов и сопоставления зависимостей. Рекомендуется только для отладки.

### Метрики Prometheus

Reloader экспортирует следующие ключевые метрики:
- `reloader_success_reload_total` — общее количество успешных перезагрузок.
- `reloader_failure_reload_total` — количество неудачных попыток перезагрузки.

---

## Практические сценарии

### Сценарий 1: Проверка состояния контроллера

```bash
# Проверка статуса развёртывания (Deployment)
kubectl get deployment reloader -n monitoring

# Проверка состояния подов (Pods)
kubectl get pods -n monitoring -l app=reloader

# Получение детальной информации
kubectl describe deployment reloader -n monitoring
```

### Сценарий 2: Анализ логов

```bash
kubectl logs -f deployment/reloader -n monitoring
```

**Пример вывода при успешном срабатывании (июнь 2026):**

```text
time="2026-06-06T10:30:45Z" level=info msg="Reloader started"
time="2026-06-06T10:30:46Z" level=info msg="Watching for changes in namespace: default"
time="2026-06-06T10:31:00Z" level=info msg="ConfigMap 'app-config' updated in namespace 'default'"
time="2026-06-06T10:31:01Z" level=info msg="Triggering rolling upgrade for Deployment 'myapp'"
```

### Сценарий 3: Диагностика отсутствия реакции

Если `ConfigMap`/`Secret` изменён, но поды не перезапускаются:

1.  **Проверка аннотаций:** убедитесь, что аннотация добавлена в `metadata` самого `Deployment`/`StatefulSet`, а не во вложенный `template`.
    ```bash
    kubectl get deployment <имя> -o yaml | grep -A2 reloader.stakater.com
    ```
2.  **Проверка RBAC (Role-Based Access Control):** убедитесь, что у ServiceAccount контроллера есть права на `watch` ресурсов в целевом пространстве имён (Namespace).
    ```bash
    kubectl auth can-i watch configmaps --as=system:serviceaccount:monitoring:reloader
    ```
3.  **Фильтры Namespace:** проверьте, не включены ли флаги `--namespaces-to-ignore` или `--namespaces-to-select`, ограничивающие область работы контроллера.

### Сценарий 4: Применение лучших практик

Для надёжной работы Reloader рекомендуется следовать этим правилам:

1.  **Явные аннотации вместо `auto`:** используйте `configmap.reloader.stakater.com/reload`, чтобы избежать случайных перезагрузок при изменении не связанных с приложением ресурсов.
2.  **Изоляция системных ресурсов:** всегда добавляйте системные пространства имён (`kube-system`, `kube-public`) в список исключений через флаг `--namespaces-to-ignore`.
3.  **Ограничение ресурсов (Resource Quotas):** обязательно задавайте `limits` и `requests` для CPU (Central Processing Unit) и памяти контроллера, чтобы он не влиял на работу бизнес-приложений.
4.  **Стратегия для GitOps:** при использовании ArgoCD или FluxCD применяйте стратегию обновления `annotations` вместо `env-vars`, чтобы избежать расхождений (drift) между желаемым и текущим состоянием манифестов.

---

## Дополнительная информация

### Мониторинг в кластере

Для автоматического сбора метрик рекомендуется создать объект `ServiceMonitor` (если используется Prometheus Operator):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: reloader
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: reloader
  endpoints:
    - port: http
      path: /metrics
```

### Ресурсы

- [GitHub: stakater/Reloader](https://github.com/stakater/Reloader)
- [Практические сценарии использования](./reloader_usage_scenarios.md)
