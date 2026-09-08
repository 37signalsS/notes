# Диагностика и устранение проблем Kyverno

## Определения

**Troubleshooting (Устранение неполадок)** — систематический процесс диагностики и решения проблем, возникающих при эксплуатации Kyverno в продакшен-среде. Включает методологию поиска причин, набор диагностических команд и типовые сценарии восстановления.

**Admission Control Failure** — ситуация, когда компонент Admission Control (Kyverno webhook) не может обработать запрос к API-серверу, что приводит к блокировке создания ресурсов в кластере. Наиболее критичный тип инцидента для доступности сервисов.

---

## Основные концепции

### Методология диагностики (5 шагов)

Любая проблема с Kyverno диагностируется по единому алгоритму:

```
1. Проверить состояние контроллеров → 2. Проверить webhook-конфигурацию →
3. Проверить политики → 4. Проверить логи → 5. Проверить RBAC
```

### Классификация проблем по критичности

| Критичность | Описание | Время реакции |
| :--- | :--- | :--- |
| **P0 - Critical** | Kyverno webhook блокирует ВСЕ операции в кластере (deadlock) | Немедленно |
| **P1 - High** | Политика блокирует создание критичных сервисов (production) | < 15 минут |
| **P2 - Medium** | PolicyReport показывает нарушения, но блокировки нет | < 1 часа |
| **P3 - Low** | Мутация не применяется к существующим ресурсам | < 24 часов |

---

## Практические сценарии

### Сценарий 1: Полный deadlock кластера (P0)

**Симптомы:**
- `kubectl apply` возвращает ошибку `admission webhook denied the request`
- Создание Pod, Deployment, ConfigMap невозможно
- Поды Kyverno в статусе `CrashLoopBackOff` или `ImagePullBackOff`

**Алгоритм восстановления:**

```bash
# Шаг 1: Проверить статус подов Kyverno
kubectl get pods -n kyverno -o wide
# → Ожидаемый результат: все поды в Running

# Шаг 2: Если поды падают - проверить логи
kubectl logs -n kyverno -l app.kubernetes.io/component=admission-controller --tail=100

# Шаг 3: Временно отключить webhook (экстренное восстановление)
kubectl delete validatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno
kubectl delete mutatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno

# Шаг 4: После восстановления доступа - найти проблемную политику
kubectl get clusterpolicy,validatingpolicy -o wide

# Шаг 5: Перевести проблемную политику в Audit
kubectl patch clusterpolicy <policy-name> --type merge -p '{"spec":{"validationFailureAction":"Audit"}}'

# Шаг 6: Вернуть webhook-конфигурации
helm upgrade kyverno kyverno/kyverno -n kyverno --reuse-values
```

**Профилактика:**
- Всегда используйте `failurePolicy: Ignore` для некритичных политик
- Начинайте с `Audit` перед `Enforce`
- Используйте `PodDisruptionBudget` для контроллеров Kyverno

### Сценарий 2: Политика не применяется к ресурсам (P1)

**Симптомы:**
- Ресурс создан без проверки политикой
- PolicyReport не показывает нарушений
- Мутация не применяется

**Диагностика:**

```bash
# Шаг 1: Проверить, что политика существует и активна
kubectl get clusterpolicy <policy-name> -o jsonpath='{.spec.validationFailureAction}'
# → Должно быть: Enforce или Audit

# Шаг 2: Проверить match/exclude - возможно ресурс исключен
kubectl get clusterpolicy <policy-name> -o yaml | grep -A20 "match:"

# Шаг 3: Проверить, что ресурс попадает под kinds/namespaces
kubectl get clusterpolicy <policy-name> -o jsonpath='{.spec.rules[0].match}'

# Шаг 4: Проверить background scan
kubectl get clusterpolicy <policy-name> -o jsonpath='{.spec.background}'
# → Должно быть: true (для фонового сканирования)

# Шаг 5: Принудительно запустить сканирование
kubectl annotate clusterpolicy <policy-name> kyverno.io/force-scan=$(date +%s) --overwrite
kubectl annotate clusterpolicy <policy-name> kyverno.io/force-scan- # Удалить аннотацию
```

**Типичные причины:**
- `exclude` содержит namespace целевого ресурса
- `match.kinds` не соответствует типу ресурса
- `background: false` для валидации существующих ресурсов
- Политика создана после ресурсов (нет фонового сканирования)

### Сценарий 3: Generate не создает ресурсы (P2)

**Симптомы:**
- При создании Namespace не появляются ResourceQuota/NetworkPolicy
- `kubectl get updaterequests -n kyverno` показывает ошибки

**Диагностика:**

```bash
# Шаг 1: Проверить UpdateRequests
kubectl get updaterequests -n kyverno -o wide
# → Фильтрация по политике
kubectl get updaterequests -n kyverno -l policy=<policy-name>

# Шаг 2: Проверить детали конкретного UR
kubectl describe updaterequest <ur-name> -n kyverno

# Шаг 3: Проверить RBAC background-controller
kubectl auth can-i create resourcequotas \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
# → Должно быть: yes

# Шаг 4: Проверить логи background-controller
kubectl logs -n kyverno -l app.kubernetes.io/component=background-controller --tail=100

# Шаг 5: Проверить, что generate правило корректно
kubectl get clusterpolicy <policy-name> -o jsonpath='{.spec.rules[0].generate}'
```

**Типичные причины:**
- `synchronize: false` (ресурсы не обновляются)
- Namespace не существует на момент создания политики
- Нет прав RBAC у background-controller
- Триггер не срабатывает (неправильный match)

### Сценарий 4: CEL-политика возвращает ошибку компиляции (P2)

**Симптомы:**
- `kubectl apply` возвращает `validation failed`
- PolicyReport показывает `error` вместо `pass/fail`

**Диагностика:**

```bash
# Шаг 1: Проверить логи admission-controller
kubectl logs -n kyverno -l app.kubernetes.io/component=admission-controller --tail=100 | grep -i "error\|CEL"

# Шаг 2: Проверить синтаксис CEL через dry-run
kubectl create -f policy.yaml --dry-run=server 2>&1 | grep -i "error"

# Шаг 3: Использовать cel-playground для отладки
# https://cel-playground.appspot.com

# Шаг 4: Проверить обязательные поля в matchConstraints
kubectl get validatingpolicy <policy-name> -o yaml | grep -A10 "matchConstraints"
```

**Типичные ошибки CEL:**
- Отсутствие `has()` перед обращением к необязательным полям
- Использование неявного преобразования типов (CEL строгий)
- Неправильный синтаксис `.?fieldName.orValue([])` для optional полей
- Отсутствие `validationActions: [Deny]` для блокировки

### Сценарий 5: Мутация конфликтует с Argo CD (P2)

**Симптомы:**
- Argo CD показывает вечный `OutOfSync`
- Ресурс постоянно перезаписывается
- `managedFields` показывает два менеджера

**Диагностика:**

```bash
# Шаг 1: Проверить managedFields
kubectl get deployment <name> -o jsonpath='{.metadata.managedFields}' | jq .
# → Ищем записи с manager: "kyverno" и "argocd-application-controller"

# Шаг 2: Проверить diff в Argo CD
argocd app diff <app-name> --server-side

# Шаг 3: Проверить аннотации Application
kubectl get application <app-name> -o yaml | grep -A5 "ignoreDifferences"

# Шаг 4: Решение - добавить managedFieldsManagers в ignoreDifferences
# В Application:
# spec:
#   ignoreDifferences:
#     - group: "*"
#       kind: "*"
#       managedFieldsManagers:
#         - kyverno
```

**Решение:**
- Включить `ServerSideApply=true` в Argo CD
- Добавить `managedFieldsManagers: [kyverno]` в `ignoreDifferences`
- Использовать `ServerSideDiff=true` в аннотациях Application

### Сценарий 6: Высокая задержка API (P2)

**Симптомы:**
- `kubectl apply` выполняется медленно (>500ms)
- Логи показывают таймауты вебхуков
- Сервисы деградируют из-за задержек

**Диагностика:**

```bash
# Шаг 1: Измерить задержку webhook
kubectl get validatingwebhookconfigurations -o json | \
  jq '.items[].webhooks[] | {name: .name, timeoutSeconds: .timeoutSeconds}'

# Шаг 2: Проверить количество политик
kubectl get clusterpolicy,validatingpolicy --no-headers | wc -l

# Шаг 3: Проверить метрики Kyverno
kubectl port-forward -n kyverno svc/kyverno-svc-metrics 8080:8080
curl http://localhost:8080/metrics | grep kyverno_admission_review_duration

# Шаг 4: Проверить использование ресурсов контроллерами
kubectl top pods -n kyverno
```

**Решения:**
- Мигрировать на `ValidatingPolicy` (v2) вместо `ClusterPolicy` (v1)
- Увеличить `webhookTimeoutSeconds` до 30
- Использовать `GlobalContext` для кэширования внешних данных
- Уменьшить количество правил в одной политике

### Сценарий 7: UpdateRequests в состоянии Failed (P3)

**Симптомы:**
- `kubectl get updaterequests -n kyverno` показывает статус `Failed`
- Мутация/генерация не выполняется

**Диагностика:**

```bash
# Шаг 1: Найти все Failed UR
kubectl get updaterequests -n kyverno -o json | \
  jq -r '.items[] | select(.status.state == "Failed") | "\(.metadata.name): \(.status.message)"'

# Шаг 2: Проверить детали конкретного UR
kubectl describe updaterequest <ur-name> -n kyverno

# Шаг 3: Проверить RBAC на целевой ресурс
kubectl auth can-i patch deployments \
  --as=system:serviceaccount:kyverno:kyverno-background-controller

# Шаг 4: Проверить, не удален ли целевой ресурс
kubectl get deployment <target-name> -n <namespace>
```

**Типичные причины:**
- Нет прав на `patch` целевого ресурса
- Целевой ресурс удален до обработки UR
- Конфликт оптимистичной блокировки (optimistic concurrency)
- OOM контроллера при обработке большого объема данных

---

## Дополнительная информация

### Экстренные команды

```bash
# Полная остановка Kyverno (экстренный случай)
helm uninstall kyverno -n kyverno

# Очистка webhook-конфигураций
kubectl delete validatingwebhookconfigurations,mutatingwebhookconfigurations \
  -l app.kubernetes.io/instance=kyverno

# Просмотр всех нарушений в кластере
kubectl get polr -A -o custom-columns=\
  NAMESPACE:.metadata.namespace,\
  NAME:.metadata.name,\
  PASS:.summary.pass,\
  FAIL:.summary.fail

# Просмотр всех UpdateRequests
kubectl get updaterequests -n kyverno -o wide

# Проверка версии Kyverno
kubectl get deployment -n kyverno kyverno-admission-controller \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

### Мониторинг здоровья Kyverno

```bash
# Prometheus метрики
kyverno_admission_requests_total{resource_state="changed"}
kyverno_policy_results_total{result="fail"}
kyverno_update_requests_total{status_type="error"}
kyverno_admission_review_duration_seconds_bucket

# Алерты для Grafana
# Количество ошибок webhook > 1% за 5 минут
rate(kyverno_admission_requests_total{resource_state="error"}[5m])
/ rate(kyverno_admission_requests_total[5m]) > 0.01

# Количество Failed UpdateRequests > 10 за 5 минут
sum(increase(kyverno_update_requests_total{status_type="error"}[5m])) > 10
```

### См. также
- [Установка и настройка](./install.md) — проверка контроллеров после установки
- [Фоновое сканирование](./background.md) — диагностика UpdateRequests
- [Агрегированные роли](./additional.md) — проверка RBAC контроллеров
- [Отчеты](./reports.md) — анализ PolicyReport
- [Интеграция с Argo CD](./argo-cd.md) — решение конфликтов мутаций
