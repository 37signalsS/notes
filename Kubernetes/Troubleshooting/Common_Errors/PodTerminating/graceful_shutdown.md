# Pod Terminating: Graceful Shutdown

## Определения

**Graceful Shutdown** — процесс корректного завершения пода: отправка SIGTERM → ожидание → preStop hook → SIGKILL. Даёт приложению время на завершение активных соединений и сохранение данных.

**preStop hook** — хук, выполняемый *до* отправки SIGTERM. Используется для уведомления приложения о предстоящем завершении (исключение из load balancer, drain соединений).

**SIGTERM** — сигнал корректного завершения (signal 15). Приложение должно перехватывать его для graceful shutdown.

**SIGKILL** — сигнал принудительного завершения (signal 9). Не перехватывается, не обрабатывается — немедленная остановка процесса.

**terminationGracePeriodSeconds** — общий таймаут (по умолчанию 30s) на весь graceful shutdown: preStop + обработка SIGTERM.

---

## Базовые концепции

### Порядок событий при удалении пода

```
kubectl delete pod / scaling down / eviction
    ↓
1. Pod получает deletionTimestamp
    ↓
2. Одновременно:
   a. preStop hook (если определён)
   b. Endpoints удаляются из Service (исключение из load balancer)
    ↓
3. SIGTERM отправляется PID 1 контейнера
    ↓
4. Ожидание: preStop завершается ИЛИ SIGTERM обрабатывается
    ↓
5. [ожидание terminationGracePeriodSeconds]
    ↓
6. timeout → SIGKILL (принудительное завершение)
    ↓
7. Остановка контейнеров → размонтирование volumes → удаление finalizers
```

> **Важно:** preStop и SIGTERM отправляются *одновременно*, не последовательно. Если preStop выполняется дольше grace period → SIGKILL.

### Взаимодействие preStop и grace period

| Конфигурация | Поведение |
|--------------|-----------|
| Без preStop | SIGTERM → ожидание grace period → SIGKILL |
| preStop короткий | preStop → SIGTERM → ожидание → SIGKILL |
| preStop длинный | preStop может быть убит SIGKILL, если > grace period |
| grace period = 0 | SIGKILL немедленно (preStop не выполняется) |
| preStop > grace period | Kubelet запрашивает **+2 секунды** дополнительно (emergency termination), затем SIGKILL |

> **Рекомендация:** preStop hook должен содержать быструю команду (например, уведомление о завершении), не требующую длительного ожидания. Если приложению нужно больше времени — увеличьте `terminationGracePeriodSeconds`, а не полагайтесь на автоматическое расширение.

### Как приложение должно обрабатывать SIGTERM

1. Перестать принимать новые запросы/соединения
2. Завершить обработку текущих запросов
3. Закрыть соединения с БД, очередями, внешними сервисами
4. Сохранить состояние (если необходимо)
5. Выйти с кодом 0

Подробнее в [Жизненный цикл Pod — Graceful Shutdown](../../../Base/Pod/pod_lifecycle_and_state.md).

---

## Практические сценарии

### Сценарий 1: Настройка graceful shutdown

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: graceful-app
spec:
  terminationGracePeriodSeconds: 60  # Увеличенный grace period
  containers:
  - name: app
    image: my-app:1.0
    lifecycle:
      preStop:
        exec:
          # Исключение из Service перед SIGTERM
          command: ["/bin/sh", "-c", "sleep 10"]
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      periodSeconds: 2
      failureThreshold: 1
```

**Порядок завершения:**

1. preStop: `sleep 10` (ожидание удаления из Endpoints)
2. readinessProbe → `/ready` → `503` (исключение из Service)
3. SIGTERM → приложение завершает соединения
4. Ожидание до 60s → SIGKILL если не завершилось

### Сценарий 2: Методы удаления пода

| Метод | Команда | Когда использовать | Риск |
|-------|---------|-------------------|------|
| Стандартное | `kubectl delete pod` | Нормальный случай | Нет |
| Увеличенный grace | `kubectl delete pod --grace-period=60` | Приложение требует больше времени | Нет |
| Принудительное | `kubectl delete pod --force --grace-period=0` | Pod застрял в Terminating | Высокий: потеря данных, volume attached |
| Удаление finalizers | `kubectl patch pod -p '{"metadata":{"finalizers":[]}}'` | Крайняя мера | Высокий: утечка ресурсов |

> **Warning:** `--force --grace-period=0` не решает проблему на узле. API-сервер удаляет объект Pod из etcd **немедленно**, не дожидаясь подтверждения от kubelet о фактической терминации контейнеров на узле. Ресурсы (процессы, volumes) могут продолжать работать. Volume может остаться в состоянии «attached». Данные могут быть потеряны. После force delete необходимо самостоятельно убедиться, что под полностью удалён с узла.

### Сценарий 3: Диагностика проблем graceful shutdown

```bash
# Проверить terminationGracePeriodSeconds
kubectl get pod <pod-name> -o jsonpath='{.spec.terminationGracePeriodSeconds}'

# Проверить preStop hook
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].lifecycle.preStop}'

# Проверить, как pod обрабатывает SIGTERM
kubectl exec <pod-name> -- cat /proc/1/cmdline | tr '\0' ' '
# PID 1 должен быть приложением, а не shell
```

### Сценарий 4: Проблема — PID 1 не обрабатывает SIGTERM

**Симптом:** Контейнер не завершается по SIGTERM, требует SIGKILL.

**Причина:** Entrypoint — shell (`/bin/sh -c`), который не forwards SIGTERM к дочернему процессу.

**Решение:**

```yaml
# Вариант A: exec form entrypoint
containers:
- name: app
  image: my-app
  command: ["my-app-binary", "--flag"]  # exec form, не shell form

# Вариант B: tini как init process
containers:
- name: app
  image: my-app
  args: ["/usr/bin/tini", "--", "my-app-binary"]
```

---

## Дополнительная информация

**Связанные разделы:**

- [Определения Pod Terminating](./definitions.md) — базовые понятия, finalizers, Pod GC
- [Diagnostics](./diagnostics.md) — чек-лист диагностики terminating pods
- [Finalizer и CSI проблемы](./finalizer_issues.md) — удаление finalizers
- [Жизненный цикл Pod](../../../Base/Pod/pod_lifecycle_and_state.md) — SIGTERM обработка, фазы пода, sidecar termination
- [Node Unavailable](./node_unavailable_issues.md) — узел недоступен
- [PDB Blocking](./pdb_blocking.md) — PodDisruptionBudget
- [Обзор Troubleshooting](../../troubleshooting_overview.md) — классификация ошибок Kubernetes
