# Reloader — Мониторинг и отладка

## Definitions

**Мониторинг Reloader** — набор практик и инструментов для отслеживания состояния контроллера Reloader, диагностики проблем и верификации корректности обработки изменений ConfigMap/Secret.

**SSoT:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Basic Concepts

### Эндпоинты Reloader

| Эндпоинт | Назначение | Порт |
| :--- | :--- | :--- |
| `/healthz` | Liveness probe | 9090 |
| `/readyz` | Readiness probe | 9090 |

### Уровни логирования

| Уровень | Когда использовать |
| :--- | :--- |
| `info` | Production (по умолчанию) |
| `debug` | Отладка проблем |

---

## Practical Scenarios

### Сценарий 1: Проверка состояния контроллера

```bash
# Статус deployment
kubectl get deployment reloader -n monitoring

# Статус подов
kubectl get pods -n monitoring -l app=reloader

# Детали
kubectl describe deployment reloader -n monitoring
```

### Сценарий 2: Просмотр логов

```bash
kubectl logs -f deployment/reloader -n monitoring
```

**Типичный вывод при срабатывании:**

```
time="2025-01-15T10:30:45Z" level=info msg="Reloader started"
time="2025-01-15T10:30:46Z" level=info msg="Watching for changes in namespace: default"
time="2025-01-15T10:31:00Z" level=info msg="ConfigMap 'openresty-index-html' updated in namespace 'default'"
time="2025-01-15T10:31:01Z" level=info msg="Triggering rolling upgrade for Deployment 'openresty-deployment'"
```

### Сценарий 3: Отладка проблем

**Проверка, что Reloader видит изменения:**

```bash
# Логи с отладочным уровнем (если включён --log-level=debug)
kubectl logs -f deployment/reloader -n monitoring --tail=100
```

**Проверка, что rollout произошёл:**

```bash
# История rollout для deployment
kubectl rollout history deployment/<имя-deployment> -n <namespace>

# Статус последнего rollout
kubectl rollout status deployment/<имя-deployment> -n <namespace>
```

**Проверка, что поды перезапустились:**

```bash
# AGE подов должен быть небольшим
kubectl get pods -n <namespace> -l app=<имя-приложения>
```

### Сценарий 4: Диагностика отсутствия реакции

Если ConfigMap/Secret изменён, а Reloader не реагирует:

1. **Проверить аннотации** на workload'е:
   ```bash
   kubectl get deployment <имя> -n <namespace> -o yaml | grep -A2 reloader
   ```
2. **Проверить логи Reloader** — нет ли ошибок:
   ```bash
   kubectl logs deployment/reloader -n monitoring | grep -i error
   ```
3. **Проверить RBAC** — есть ли доступ к secrets/configmaps:
   ```bash
   kubectl auth can-i get configmaps --as=system:serviceaccount:monitoring:reloader
   ```

---

## Additional Information

### Интеграция с Prometheus

Service Reloader экспортирует метрики на порту 9090. Можно настроить ServiceMonitor для Prometheus.

### Полезные ссылки

- [GitHub: stakater/Reloader](https://github.com/stakater/Reloader)
