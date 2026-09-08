# Продвинутые сценарии диагностики Deployment

Реальные кейсы из продакшена и собеседований: от простых ошибок до сложных системных сбоев. Каждый сценарий включает симптомы, диагностику и решение.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes (v1.16+).
- Установленный `kubectl` с доступом к кластеру.
- Базовое понимание [Deployment](./index.md), [Troubleshooting](./troubleshooting.md).
- Для продвинутой диагностики: `jq`, `stern`, `k9s`.

## 1. Определения

**Incident** — событие, нарушающее работоспособность сервиса или его компонентов. В контексте Deployment — это ситуация, когда приложение недоступно, работает некорректно или обновление привело к регрессии.

**Root Cause Analysis (RCA)** — процесс определения корневой причины инцидента. В Kubernetes ключевой является способность быстро перейти от симптома (например, 5xx ошибки) к корневой причине (например, баг в новой версии кода).

**Blast Radius** — область поражения: количество пользователей/сервисов, затронутых инцидентом. При деплое blast radius определяется стратегией обновления (RollingUpdate vs Blue-Green vs Canary).

> Детальные руководства по устранению конкретных ошибок см. в [Troubleshooting Common Errors](../../../Kubernetes/Troubleshooting/Common_Errors/). Базовый алгоритм диагностики — в [Troubleshooting Deployment](./troubleshooting.md).

## 2. Базовые концепции

### Модель диагностики: от симптома к причине

```
Симптом: 5xx ошибки
  ↓
Уровень 1: Проверка Deployment conditions
  ↓
Уровень 2: Анализ ReplicaSets и распределения реплик
  ↓
Уровень 3: Диагностика подов (события, логи, статус)
  ↓
Уровень 4: Инфраструктура (узлы, сеть, хранилище)
  ↓
Уровень 5: Приложение (баг, конфигурация, зависимости)
```

### Категории инцидентов

| Категория | Примеры | Критичность |
|:----------|:--------|:------------|
| **Полная недоступность** | Все поды падают, rollout завис | P1 (критичный) |
| **Частичная деградация** | Часть реплик не готова, increased latency | P2 (высокий) |
| **Регрессия после деплоя** | Новые баги, бизнес-логика сломана | P2 (высокий) |
| **Зависший rollout** | Обновление не завершается | P3 (средний) |
| **Проблемы производительности** | OOMKilled, CPU throttling | P3 (средний) |

## 3. Практические сценарии

### Сценарий 1: Каскадный отказ при деплое

**Симптомы:** После обновления образа начались 5xx ошибки. Часть пользователей получает ошибки, часть работает нормально.

**Диагностика:**
```bash
# 1. Проверка текущего состояния
kubectl get deployment my-app -o jsonpath='{.status.conditions[*].type}{"\n"}'
# → Available=True Progressing=True

# 2. Проверка распределения реплик
kubectl get rs -l app=my-app
# → my-app-7f6f8d6f5d   3   3   3   5m
# → my-app-5c6b7c8d9e   2   2   1   1h  ← одна реплика не готова

# 3. Проверка подов нового RS
kubectl get pods -l app=my-app -o wide | grep my-app-7f6f8d6f5d
# → my-app-7f6f8d6f5d-abc12   Running   0/1     ← readiness не проходит

# 4. Проверка readiness
kubectl describe pod my-app-7f6f8d6f5d-abc12 | grep -A5 "Readiness"
# → Readiness probe failed: HTTP probe failed with statuscode: 503

# 5. Проверка логов
kubectl logs my-app-7f6f8d6f5d-abc12
# → ERROR: Cannot connect to database "users_db"
```

**Причина:** Новая версия требует новую таблицу в БД, но миграция не была выполнена.

**Решение:**
```bash
# 1. Выполнить миграцию
kubectl create job --from=cronjob/db-migration manual-migration

# 2. Дождаться завершения миграции
kubectl get jobs -w

# 3. После успешной миграции rollout завершится автоматически
kubectl rollout status deployment/my-app --timeout=5m
```

### Сценарий 2: OOMKilled цикл

> Детальное руководство по OOMKilled см. в [OOMKilled Pods](../../../Kubernetes/Troubleshooting/Common_Errors/oomkilled_pods.md).

**Симптомы:** Поды постоянно перезапускаются, в статусе `CrashLoopBackOff`, exit code 137.

**Диагностика:**
```bash
# 1. Проверка статуса
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].lastState}'
# → {"terminated":{"exitCode":137,"reason":"OOMKilled"}}

# 2. Проверка лимитов
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[0].resources.limits.memory}'
# → 256Mi

# 3. Проверка потребления
kubectl top pod <pod-name>
# → MEM BYTES: 245Mi / 256Mi  ← близко к лимиту

# 4. Проверка历史 OOM
kubectl get events --field-selector involvedObject.name=<pod-name>,reason=OOMKilling
```

**Причина:** Приложение потребляет больше памяти, чем установлен лимит. Java-приложение с настроенным MaxRAMPercentage выше limit.

**Решение:**
```bash
# 1. Увеличить лимит памяти
kubectl patch deployment my-app --type='json' -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"512Mi"}]'

# 2. Или оптимизировать потребление памяти приложения
# (настроить JVM MaxRAMPercentage, уменьшить кеши и т.д.)

# 3. Мониторить потребление
kubectl top pod -l app=my-app --watch
```

### Сценарий 3: Зависший rollout из-за PDB

> Детальное руководство по PDB см. в [PDB Blocking](../../../Kubernetes/Troubleshooting/Common_Errors/PodTerminating/pdb_blocking.md).

**Симптомы:** Rollout не завершается, контроллер не может удалить старые поды.

**Диагностика:**
```bash
# 1. Проверка conditions
kubectl describe deployment my-app | grep -A5 "Conditions"
# → Type=Progressing, Status=False, Reason=ProgressDeadlineExceeded

# 2. Проверка PDB
kubectl get pdb -n production
# → NAME              MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS
# → my-app-pdb        3               N/A               0

# 3. Проверка有多少 подов защищено PDB
kubectl describe pdb my-app-pdb
# → Current: 5/5 pods are ready
# → Allowed disruptions: 0  ← PDB не дает удалить ни одного пода

# 4. Проверка событий
kubectl get events --field-selector reason=PodDisruptionBudget -n production
```

**Причина:** PDB требует `minAvailable: 3`, а Deployment пытается обновить поды, уменьшая количество доступных ниже 3.

**Решение:**
```bash
# Вариант 1: Уменьшить maxUnavailable
kubectl patch deployment my-app -p '{"spec":{"strategy":{"rollingUpdate":{"maxUnavailable":1}}}}'

# Вариант 2: Временно ослабить PDB
kubectl patch pdb my-app-pdb -p '{"spec":{"minAvailable":2}}'

# Вариант 3: Использовать Recreate стратегию (крайний случай)
kubectl patch deployment my-app -p '{"spec":{"strategy":{"type":"Recreate"}}}'
```

### Сценарий 4: NetworkPolicy блокирует трафик

> Детальные сценарии NetworkPolicy см. в [NetworkPolicy practical scenarios](../../../Kubernetes/Networking/Network/NetworkPolicy/practical_scenarios.md).

**Симптомы:** После деплоя новый под не может подключиться к базе данных, хотя DNS резолвится.

**Диагностика:**
```bash
# 1. Проверка DNS изнутри пода
kubectl exec -it <pod-name> -- nslookup postgresql.production.svc.cluster.local
# → Сервер не отвечает

# 2. Проверка NetworkPolicy
kubectl get networkpolicy -n production -o yaml
# → PolicyType: Egress, но нет правила для DNS (port 53)

# 3. Проверка подключения
kubectl exec -it <pod-name> -- curl -v postgresql:5432
# → Connection timed out
```

**Причина:** NetworkPolicy разрешает egress только на порт 5432, но не на DNS (UDP 53).

**Решение:**
```yaml
# Добавить правило для DNS
egress:
- to: []
  ports:
  - protocol: UDP
    port: 53
  - protocol: TCP
    port: 53
```

### Сценарий 5: HPA конфликтует с ручным масштабированием

**Симптомы:** Количество реплик постоянно меняется, HPA перезаписывает вручную заданные replicas.

**Диагностика:**
```bash
# 1. Проверка HPA
kubectl get hpa my-app
# → NAME    REFERENCE          TARGETS   MINPODS   MAXPODS   REPLICAS
# → my-app  Deployment/my-app  45%/80%   2         10        8

# 2. Проверка текущих replicas
kubectl get deployment my-app -o jsonpath='{.spec.replicas}'
# → 5

# 3. Проверка who changed replicas
kubectl get deployment my-app -o json | jq '.metadata.managedFields[] | select(.manager=="horizontal-pod-autoscaler")'
# → HPA управляет replicas
```

**Причина:** Разработчик вручную изменил `replicas`, но HPA постоянно перезаписывает это значение.

**Решение:**
```bash
# НЕ ИСПОЛЬЗОВАТЬ kubectl scale для Deployment, управляемого HPA
# Масштабирование должно происходить через HPA:
kubectl autoscale deployment my-app --min=3 --max=10 --cpu-percent=80
```

### Сценарий 6: ConfigMap изменен, но поды не перезапустились

**Симптомы:** Конфигурация обновлена в ConfigMap, но приложение продолжает работать со старыми настройками.

**Диагностика:**
```bash
# 1. Проверка содержимого ConfigMap
kubectl get configmap app-config -o jsonpath='{.data.LOG_LEVEL}'
# → debug  ← обновлено

# 2. Проверка переменных окружения в поде
kubectl exec -it <pod-name> -- env | grep LOG_LEVEL
# → LOG_LEVEL=info  ← старое значение

# 3. Проверка что rollout не был инициирован
kubectl rollout history deployment/my-app
# → Ревизия не изменилась
```

**Причина:** Изменение содержимого ConfigMap **не** инициирует rollout в Kubernetes.

**Решение:**
```bash
# Вариант 1: Принудительный перезапуск
kubectl rollout restart deployment/my-app

# Вариант 2: Использовать хеш-аннотацию в шаблоне пода (для автоматического rollout)
```

### Сценарий 7: Intermediary версия несовместима с БД

**Симптомы:** При обновлении с v1 на v3 через v2 (rolover), v2 несовместима с текущей схемой БД.

**Диагностика:**
```bash
# 1. Проверка истории ревизий
kubectl rollout history deployment/my-app
# → REVISION  CHANGE-CAUSE
# → 1         v1
# → 2         v2
# → 3         v3

# 2. Проверка текущей ревизии
kubectl get deployment my-app -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}'
# → 3  ← v3, но v2 была пропущена

# 3. Проверка логов пода v3
kubectl logs <pod-v3> --previous
# → ERROR: column "sessions" does not exist
```

**Причина:** Rollover пропустил v2, которая была бы совместима с текущей схемой БД.

**Решение:**
```bash
# 1. Откатить к v1
kubectl rollout undo deployment/my-app --to-revision=1

# 2. Выполнить миграцию для v2
kubectl create job --from=cronjob/migrate-v2 manual-migrate-v2

# 3. Деплоить v2
kubectl set image deployment/my-app app=my-registry.com/app:v2

# 4. После проверки, деплоить v3
kubectl set image deployment/my-app app=my-registry.com/app:v3
```

### Сценарий 8: StartupProbe не успевает

**Симптомы:** Java-приложение с долгим стартом (Spring Boot) убивается livenessProbe до готовности.

**Диагностика:**
```bash
# 1. Проверка статуса пода
kubectl describe pod <pod-name> | grep -A3 "Startup"
# → Startup probe failed: HTTP probe failed with statuscode: 503
# → Liveness probe failed: HTTP probe failed with statuscode: 503

# 2. Проверка времени жизни пода
kubectl get pod <pod-name> -o jsonpath='{.status.startTime}'
# → Время создания: 2 минуты назад

# 3. Расчет окна пробы
# startupProbe: initialDelaySeconds: 10, periodSeconds: 5, failureThreshold: 3
# → Окно: 10 + (3-1)*5 = 20 секунд
# → Приложению нужно 60 секунд на старт!
```

**Причина:** `startupProbe` настроена с слишком малым окном для Java-приложения.

**Решение:**
```bash
# Увеличить failureThreshold для startupProbe
kubectl patch deployment my-app --type='json' -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/startupProbe/failureThreshold","value":"30"},
  {"op":"replace","path":"/spec/template/spec/containers/0/startupProbe/periodSeconds","value":"10"}
]'
# → Новое окно: 10 + (30-1)*10 = 300 секунд (5 минут)
```

## 4. Дополнительная информация

### Полезные инструменты

| Инструмент | Назначение | Установка |
|:-----------|:-----------|:----------|
| **k9s** | TUI для управления кластером | `brew install derailed/k9s/k9s` |
| **stern** | Multi-pod логи | `brew install stern` |
| **ketall** | Все ресурсы в неймспейсе | `kubectl krew install ketall` |
| **trace** | Трассировка запросов в кластере | `kubectl krew install trace` |

### См. также
- [Устранение неполадок Deployment](./troubleshooting.md) — базовый алгоритм диагностики.
- [Управление жизненным циклом](./lifecycle_management.md) — rollout, rollback, пауза.
- [Production Checklist](./production_checklist.md) — чеклист перед деплоем.
