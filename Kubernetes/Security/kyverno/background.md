# Фоновое сканирование в Kyverno

## Определения

**Фоновое сканирование (Background Scan)** — процесс периодической или триггерной проверки ресурсов кластера на соответствие политикам безопасности. В отличие от Admission-контроля, работающего в синхронном режиме при создании ресурса, фоновое сканирование анализирует уже существующие объекты асинхронно, не влияя на задержку API-сервера.

**Update Request (UR)** — системный ресурс Kyverno в пространстве имен `kyverno`, выступающий посредником для выполнения асинхронных операций мутации (`mutateExisting`) и генерации (`generate`) существующих ресурсов. UR служит промежуточным буфером между Background Controller и целевыми ресурсами кластера, обеспечивая надежность и возможность повторных попыток при сбоях.

**Background Controller** — отдельный Deployment Kyverno, отвечающий за выполнение правил `generate` и `mutateExisting` для уже существующих ресурсов. В отличие от Reports Controller, он не формирует `PolicyReport` напрямую, а управляет жизненным циклом `UpdateRequest`.

**Reports Controller** — отдельный Deployment Kyverno, отвечающий за формирование `PolicyReport` и `ClusterPolicyReport` на основе результатов Admission Scan и Background Scan.

---

## Основные концепции

### Архитектура и разделение обязанностей

В архитектуре Kyverno (v1.12+) функции фоновой обработки строго разделены между двумя независимыми контроллерами:

| Контроллер | Функциональная роль | Основные задачи |
| :--- | :--- | :--- |
| **Reports Controller** | Аудит и наблюдаемость | Периодическое сканирование существующих ресурсов для формирования `PolicyReports`. Обрабатывает правила `validate` и `verifyImages`. |
| **Background Controller** | Активное управление | Выполнение правил `generate` и `mutateExisting` для уже существующих ресурсов через `UpdateRequest`. |

> **Важно**: Reports Controller выполняет фоновое сканирование для АУДИТА (создание отчетов), а Background Controller — для АКТИВНОГО ИЗМЕНЕНИЯ ресурсов. Оба контроллера работают независимо и могут масштабироваться отдельно.

### Сравнение: Admission Scan vs Background Scan

| Аспект | Admission Scan | Background Scan |
| :--- | :--- | :--- |
| **Триггер** | Запрос к API-серверу (CREATE/UPDATE) | Периодический интервал или обновление политики |
| **Цель** | Блокировка невалидных ресурсов до сохранения в etcd | Формирование `PolicyReport` для уже существующих ресурсов |
| **Синхронность** | Синхронно — блокирует запрос | Асинхронно — не влияет на API-запросы |
| **Результат** | Допуск/блокировка ресурса | Запись в `PolicyReport`/`ClusterPolicyReport` |
| **Режим Enforce** | Блокирует создание ресурса | Только записывает нарушение в отчет, ресурс не трогает |
| **Контроллер** | Admission Controller | Reports Controller |

### Триггеры фонового сканирования

Background Scan запускается в следующих случаях:

1. **Периодический запуск**: По интервалу `BACKGROUND_SCAN_INTERVAL` (по умолчанию 1 час).
2. **Триггер при обновлении политики**: При создании или изменении `ClusterPolicy`/`Policy` Reports Controller добавляет сканирование в очередь.
3. **Триггер при включении фона**: Если политика была создана с `spec.background: true` (v1) или `evaluation.background.enabled: true` (v2), сканирование стартует сразу после применения.

### Жизненный цикл UpdateRequest (UR)

Процесс мутации или генерации существующего ресурса через UR проходит следующие этапы:

1. **Триггер**: Создание/обновление политики с `mutateExisting` (v1) / `evaluation.mutateExisting.enabled: true` (v2) или `generate` + `generateExisting: true`.
2. **Создание UR**: Background Controller создает объект `UpdateRequest` в пространстве имен `kyverno` для каждого целевого ресурса.
3. **Выполнение**: Воркер `updateRequestWorkers` (по умолчанию 10) выбирает UR из очереди, применяет изменения к целевому ресурсу и обновляет статус.
4. **Очистка**: После успешного выполнения (`Completed`) UR автоматически удаляется (начиная с v1.14), чтобы не перегружать `etcd`.

**Состояния UR**:
- **Pending** — UR создан, ожидает обработки воркером Background Controller.
- **Processing** — контроллер считывает UR и применяет изменения к целевому ресурсу.
- **Completed** — операция выполнена успешно, UR помечен для автоматической очистки (v1.14+).
- **Failed** — операция завершилась ошибкой (RBAC, конфликт оптимистичной блокировки). Kyverno повторяет попытку до 3 раз с экспоненциальной задержкой (1s → 2s → 4s, максимум 60s).
- **Skip** — ресурс не соответствует текущему состоянию политики (например, был удален) или политика была удалена.

### Структура UR

```yaml
apiVersion: kyverno.io/v1
kind: UpdateRequest
metadata:
  name: <policy-name>-<resource-namespace>-<resource-name>-<uid>
  namespace: kyverno
spec:
  policy: <policy-name>
  rule: <rule-name>
  resource:
    apiVersion: <target-apiVersion>
    kind: <target-kind>
    namespace: <target-namespace>
    name: <target-name>
    uid: <target-uid>
status:
  state: Completed | Failed | Pending | Skip
  message: "Описание результата"
```

### Ключевые параметры спецификации политики

*   **`spec.background`**: (по умолчанию `true` в v1, `evaluation.background.enabled: true` в v2) — разрешает фоновое сканирование для формирования `PolicyReport` существующих ресурсов.
*   **`spec.mutateExisting`**: (v1) / **`evaluation.mutateExisting.enabled: true`** (v2) — включает асинхронную мутацию уже существующих ресурсов. Требует `targets` в блоке `mutate`.
*   **`spec.generateExisting`**: (v1) / **`evaluation.generateExisting.enabled: true`** (v2) — включает генерацию ресурсов для уже существующих объектов.

> **Важно**: Фоновое сканирование в режиме `Enforce` **не блокирует** существующие ресурсы. Оно лишь фиксирует нарушение в отчете. Реальное изменение объекта происходит только при использовании правил `mutateExisting`.

### Исключение ресурсов из фонового сканирования

Для снижения нагрузки на Reports Controller и уменьшения объема отчетов используйте блок `exclude`:

```yaml
spec:
  background: true
  rules:
    - name: validate-resource-limits
      match:
        resources:
          kinds: [Pod]
      exclude:
        resources:
          namespaces:
            - kube-system
            - kyverno
            - kube-public
          labels:
            environment: "system"
```

**Правила исключения:**
- `exclude` вычисляется с логическим И с `match` — ресурс должен соответствовать `match` И НЕ соответствовать `exclude`.
- Исключение системных Namespace (`kube-system`, `kube-public`, `kyverno`) является обязательной практикой для всех политик.
- При использовании `subjects`, `roles` или `clusterRoles` в `match`/`exclude` политика **не может** работать в режиме Background Scan (только Admission).

### Параметры конфигурации контроллеров

**Background Controller:**
- `--updateRequestWorkers`: количество параллельных воркеров для обработки UR (по умолчанию 10). Увеличьте до 20–30 для кластеров с >5000 объектов.
- `--updateRequestDelayOnFailure`: задержка перед повторной попыткой при ошибке (по умолчанию 1s, экспоненциальный backoff до 60s).
- `--backgroundScanWorkers`: количество воркеров для обработки фоновых задач (по умолчанию 10).

**Reports Controller:**
- `--backgroundScanInterval`: интервал полного сканирования (по умолчанию 1h). Увеличьте до 6–12h для больших кластеров (>5000 объектов).
- `--reportsChunkSize`: количество ресурсов, обрабатываемых за одну итерацию (по умолчанию 1000). Увеличьте для ускорения сканирования при высокой пропускной способности API-сервера.

---

## Практические сценарии

### 1. Оптимизация интервала сканирования

Для больших кластеров (>5000 объектов) рекомендуется увеличивать интервал сканирования для предотвращения пиковых нагрузок на API-сервер.

**Настройка через Helm `values.yaml`**:
```yaml
backgroundController:
  envVars:
    - name: BACKGROUND_SCAN_INTERVAL
      value: "12h" # Полное сканирование раз в 12 часов
    - name: UPDATE_REQUEST_WORKERS
      value: "20" # Увеличить для больших кластеров
reportsController:
  envVars:
    - name: BACKGROUND_SCAN_INTERVAL
      value: "12h"
```

### 2. Мутация существующих ресурсов (mutate.targets)

Пример политики, которая асинхронно добавляет метку безопасности во все существующие Namespace, где она отсутствует. Использует `targets` для точного выбора ресурсов.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: enforce-security-label
spec:
  mutateExistingOnPolicyUpdate: false # Рекомендуется false при использовании targets
  rules:
    - name: add-label-to-namespaces
      match:
        any:
          - resources:
              kinds: [Namespace]
              selector:
                matchLabels:
                  environment: "production"
      mutate:
        targets:
          - apiVersion: v1
            kind: Namespace
            selector:
              matchLabels:
                security-audit: null # Обрабатывать только те, где метки нет
        patchStrategicMerge:
          metadata:
            labels:
              security-audit: "enabled"
              audit-date: "{{ time_now_utc() }}"
```

### 3. Исключение системных областей (Noise Reduction)

Для снижения нагрузки на `reports-controller` и уменьшения объема отчетов следует исключать инфраструктурные Namespace.

```yaml
spec:
  background: true
  rules:
    - name: validate-resource-limits
      match:
        resources:
          kinds: [Pod]
      exclude:
        resources:
          namespaces:
            - kube-system
            - kyverno
            - kube-public
            - istio-system
```

---

## Методология диагностики фоновых операций

Системный подход к диагностике проблем с фоновым сканированием и UpdateRequests. Выполняйте шаги последовательно.

### Шаг 1. Проверка состояния контроллеров

Убедитесь, что все Deployment Kyverno имеют готовые поды:

```bash
# Проверка всех контроллеров
kubectl get pods -n kyverno -o wide

# Ожидаемый результат:
# kyverno-admission-controller-xxx   3/3     Running
# kyverno-background-controller-xxx  1/1     Running
# kyverno-reports-controller-xxx     1/1     Running
# kyverno-cleanup-controller-xxx     1/1     Running
```

Если поды в статусе `CrashLoopBackOff` или `ImagePullBackOff`:
```bash
# Получение логов проблемного контроллера
kubectl logs -n kyverno -l app.kubernetes.io/component=background-controller --tail=100

# Проверка событий Pod
kubectl describe pod -n kyverno -l app.kubernetes.io/component=background-controller
```

### Шаг 2. Проверка конфигурации фонового сканирования

Убедитесь, что политика активировала фоновое сканирование:

```bash
# Для v1 (ClusterPolicy)
kubectl get clusterpolicy <policy-name> -o jsonpath='{.spec.background}'
# → true

# Для v2 (ValidatingPolicy)
kubectl get validatingpolicy <policy-name> -o jsonpath='{.spec.evaluation.background.enabled}'
# → true
```

Если значение `false` или пустое — фоновое сканирование не запущено. Измените политику и примените повторно.

### Шаг 3. Проверка UpdateRequests (для generate/mutateExisting)

Если политика использует `mutateExisting` или `generateExisting`, проверьте создание UR:

```bash
# Список всех UR
kubectl get updaterequests -n kyverno

# Фильтрация по политике
kubectl get updaterequests -n kyverno -l policy=<policy-name>

# Детальная информация о конкретном UR
kubectl describe updaterequest <ur-name> -n kyverno

# Поиск UR в состоянии Failed
kubectl get updaterequests -n kyverno -o json | \
  jq -r '.items[] | select(.status.state == "Failed") | "\(.metadata.name): \(.status.message)"'
```

### Шаг 4. Проверка PolicyReports (для валидации)

Проверьте, что Reports Controller создает отчеты:

```bash
# Namespace-scoped отчеты
kubectl get polr -A

# Cluster-scoped отчеты
kubectl get cpolr

# Проверка последних Admission-отчетов (эфемерных)
kubectl get admissionreport -A --sort-by=.metadata.creationTimestamp | tail -20
```

Если `PolicyReport` отсутствует для Namespace с ресурсами:
- Проверьте, что политика не исключает этот Namespace через `exclude`.
- Проверьте, что политика имеет `validationActions: [Audit]` (v2) или `validationFailureAction: Audit` (v1).
- Дождитесь следующего цикла сканирования (до 1 часа).

### Шаг 5. Проверка RBAC контроллеров

Background Controller должен иметь права на чтение и изменение целевых ресурсов:

```bash
# 1. Background Controller: права на generate/mutateExisting
kubectl auth can-i create resourcequotas \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
kubectl auth can-i patch deployments \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
kubectl auth can-i create networkpolicies \
  --as=system:serviceaccount:kyverno:kyverno-background-controller

# 2. Reports Controller: права на создание отчетов
kubectl auth can-i create policyreports.kyverno.io \
  --as=system:serviceaccount:kyverno:kyverno-reports-controller
kubectl auth can-i get namespaces \
  --as=system:serviceaccount:kyverno:kyverno-reports-controller

# 3. Cleanup Controller: права на удаление
kubectl auth can-i delete jobs \
  --as=system:serviceaccount:kyverno:kyverno-cleanup-controller
kubectl auth can-i delete namespaces \
  --as=system:serviceaccount:kyverno:kyverno-cleanup-controller
```

Если любая команда возвращает `no` — создайте соответствующую `ClusterRole` с меткой агрегации. Подробнее см. в [Агрегированные роли](./additional.md).

### Шаг 6. Анализ логов контроллеров

```bash
# Логи Background Controller (UR, generate, mutateExisting)
kubectl logs -n kyverno -l app.kubernetes.io/component=background-controller --tail=100 | \
  grep -i "forbidden\|unauthorized\|error\|failed"

# Логи Reports Controller (PolicyReport, Background Scan)
kubectl logs -n kyverno -l app.kubernetes.io/component=reports-controller --tail=100 | \
  grep -i "forbidden\|unauthorized\|error\|failed"

# Логи Admission Controller (сопутствующие ошибки)
kubectl logs -n kyverno -l app.kubernetes.io/component=admission-controller --tail=50 | \
  grep -i "background\|updaterequest"
```

### Шаг 7. Принудительное запускание сканирования

Если требуется немедленная проверка ресурсов без ожидания интервала:

```bash
# Перезапуск Deployment Reports Controller (триггерит сканирование)
kubectl rollout restart deployment -n kyverno kyverno-reports-controller

# Или обновление политики (триггерит создание UR и сканирование)
kubectl annotate clusterpolicy <policy-name> kyverno.io/force-scan=$(date +%s) --overwrite
kubectl annotate clusterpolicy <policy-name> kyverno.io/force-scan- # Очистка аннотации
```

### Шаг 8. Проверка производительности

При больших кластерах (>5000 объектов) проверьте нагрузку:

```bash
# Количество PolicyReport в кластере
kubectl get polr -A --no-headers | wc -l

# Количество UpdateRequests
kubectl get updaterequests -n kyverno --no-headers | wc -l

# Использование ресурсов контроллерами
kubectl top pods -n kyverno -l app.kubernetes.io/component=background-controller
kubectl top pods -n kyverno -l app.kubernetes.io/component=reports-controller
```

---

## Типичные ошибки и решения

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| UpdateRequest в состоянии Failed | Нет прав на `patch` целевого ресурса | Создайте ClusterRole с меткой агрегации и verbs: [patch, update, get, list, watch] |
| GlobalContext возвращает stale данные | Слишком большой `periodSeconds` | Уменьшите интервал до 60s для актуальных данных |
| Background Controller не создает UR | `spec.background: false` или `mutateExisting` не включен | Проверьте конфигурацию политики и логи контроллера |
| Reports Controller не создает PolicyReport | Нет прав на создание `policyreports.kyverno.io` | Добавьте правила для `policyreports`, `clusterpolicyreports` в ClusterRole |
| Cleanup не удаляет ресурсы | `schedule` не сработал или нет прав на delete | Проверьте CronJob в namespace kyverno и права cleanup-controller |
| Конфликт с Argo CD | Argo CD перезаписывает мутированные ресурсы | Используйте SSA и `Prune=false` для отчетов |
| Высокая задержка Admission | Большое количество правил или `apiCall` в политике | Используйте CEL-based ValidatingPolicy (v2) и GlobalContext |
| Фоновое сканирование не находит нарушения | Политика создана после ресурсов или `background` выключен | Включите `background: true` и дождитесь полного цикла (до 1 часа) |
| Сканирование загружает API-сервер | Слишком частый интервал на большом кластере | Увеличьте `BACKGROUND_SCAN_INTERVAL` до 6–12 часов, добавьте `exclude` |

---

## Проверка целостности кластера после изменений

```bash
# Проверка что все контроллеры запущены
kubectl get pods -n kyverno

# Проверка состояния вебхуков
kubectl get validatingwebhookconfigurations kyverno-resource-validating-webhook-cfg -o yaml
kubectl get mutatingwebhookconfigurations kyverno-resource-mutating-webhook-cfg -o yaml

# Проверка что политики загружены
kubectl get clusterpolicy,validatingpolicy,mutatingpolicy,generatingpolicy -A

# Проверка последних Admission-отчетов
kubectl get admissionreport -A --sort-by=.metadata.creationTimestamp | tail -20
```

---

## Дополнительная информация

### Мониторинг фоновых операций

```bash
# Просмотр всех UR в пространстве имен kyverno
kubectl get updaterequests -n kyverno -o wide

# Фильтрация по политике
kubectl get updaterequests -n kyverno -l policy=enforce-security-label

# Детальная диагностика конкретного UR
kubectl describe updaterequest <ur-name> -n kyverno

# Просмотр зависших или ошибочных запросов
kubectl get updaterequests -n kyverno -o json | jq '.items[] | select(.status.state != "Completed")'
```

### Оптимизация производительности контроллеров

При использовании внешнего сервера отчетов или больших кластеров (>5000 объектов) настройте параметры в Helm `values.yaml`:

```yaml
# values.yaml для Helm-установки Kyverno
backgroundController:
  replicas: 2
  resources:
    limits:
      cpu: "500m"
      memory: "512Mi"
    requests:
      cpu: "200m"
      memory: "256Mi"
  envVars:
    - name: BACKGROUND_SCAN_INTERVAL
      value: "12h" # Полное сканирование раз в 12 часов
    - name: UPDATE_REQUEST_WORKERS
      value: "20" # Увеличить для больших кластеров

reportsController:
  replicas: 2
  resources:
    limits:
      cpu: "500m"
      memory: "512Mi"
  envVars:
    - name: BACKGROUND_SCAN_INTERVAL
      value: "12h"

admissionController:
  replicas: 3 # HA: минимум 3 реплики
  resources:
    limits:
      cpu: "1000m"
      memory: "1Gi"
  envVars:
    - name: WEBHOOK_TIMEOUT
      value: "15" # Увеличить для сложных CEL-проверок
```

### Диагностика RBAC и агрегации прав

Методология поиска проблем с правами контроллеров:

```bash
# Шаг 1: Проверка что метки агрегации установлены
kubectl get clusterrole -l rbac.kyverno.io/aggregate-to-background-controller=true

# Шаг 2: Проверка итоговых правил (должны быть не пустыми)
kubectl get clusterrole -l rbac.kyverno.io/aggregate-to-background-controller=true -o jsonpath='{.rules}' | jq .

# Шаг 3: Проверка ClusterRoleBinding
kubectl get clusterrolebinding -l rbac.kyverno.io/aggregate-to-background-controller=true

# Шаг 4: Проверка конкретного права
kubectl auth can-i create networkpolicies \
  --as=system:serviceaccount:kyverno:kyverno-background-controller

# Шаг 5: Проверка логов контроллера на ошибки RBAC
kubectl logs -n kyverno -l app.kubernetes.io/component=background-controller --tail=100 | grep -i "forbidden\|unauthorized"
```

### Edge Cases и ограничения

**Оптимистичная блокировка (Optimistic Concurrency):**
При одновременном изменении ресурса Background Controller и другим процессом (например, Argo CD или kubectl apply), операция UR завершается с ошибкой `Conflict`. Kyverno повторяет попытку до 3 раз. Если конфликт persists — UR переходит в состояние `Failed`.

**Удаление ресурса во время обработки UR:**
Если целевой ресурс удален до того, как Background Controller обработал UR, UR переводится в состояние `Skip`. Это нормальное поведение, не требующее вмешательства.

**Удаление политики во время обработки UR:**
Если политика удалена до завершения UR, pending UR отменяются. Уже выполненные UR очищаются автоматически.

**Ограничения производительности:**
- Background Controller обрабатывает UR последовательно в рамках одного воркера. При большом объеме изменений используйте `--updateRequestWorkers` для распараллеливания.
- Reports Controller создает нагрузку на API-сервер пропорционально количеству ресурсов. Для кластеров >10,000 объектов используйте внешнее хранилище (Reports Server).

### См. также

- [Отчеты Kyverno: структура и стандарты](./reports.md)
- [Агрегированные роли и права контроллеров](./additional.md)
- [Основные концепции и движок CEL](./concepts.md)
- [Типы правил (rules)](./rules.md)
- [Практические сценарии внедрения](./Scenarios/index.md)
- [Установка и настройка Kyverno](./install.md)
