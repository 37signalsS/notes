# Argo CD — игнорирование различий и принудительная синхронизация

> **Актуальность (2026):** В версии Argo CD v3.x механизмы сравнения ресурсов (diffing) стали более интеллектуальными благодаря глубокой интеграции с **Server-Side Apply (SSA)**. Основным методом игнорирования динамических изменений стал `managedFieldsManagers`, который заменяет ручное перечисление полей через JSON Pointers в 90% случаев.

## Предварительные требования

Перед настройкой `ignoreDifferences` необходимо убедиться в следующем:

1. **Версия Argo CD:** v2.6+ (рекомендуется v3.x для полной поддержки `managedFieldsManagers` и Server-Side Diff).
2. **Доступ к кластеру:** У приложения Argo CD есть права на чтение метаданных ресурсов (`get`, `list`, `watch`).
3. **Понимание источника изменений:** Определите, какой контроллер или вебхук мутирует ресурс (HPA, cert-manager, Service Mesh, облачный провайдер). Это критично для выбора метода игнорирования.
4. **Server-Side Apply (рекомендуется):** Для v3.x рекомендуется включить SSA на уровне кластера или приложения — это упрощает управление `managedFields` и делает `managedFieldsManagers` более предсказуемым.

## Определения

**Игнорирование различий (Ignore Differences)** — механизм Argo CD, позволяющий исключать конкретные поля или целые группы полей ресурсов из процесса сравнения (diffing). Это предотвращает ложные срабатывания статуса `OutOfSync` для полей, которые изменяются внешними контроллерами, мутирующими вебхуками или автоматикой облачных провайдеров.

**Принудительная синхронизация (Force Sync)** — режим, при котором Argo CD использует команду `kubectl apply --force`. Это приводит к удалению и повторному созданию ресурса, если обычное обновление (patch/update) невозможно из-за конфликтов или наличия неизменяемых (immutable) полей.

**managedFieldsManagers** — метод игнорирования, основанный на метаданных `managedFields` в Kubernetes. Позволяет Argo CD автоматически игнорировать любые изменения, внесенные указанным контроллером (менеджером), не требуя ручного указания путей к полям. Метод основан на механизме field ownership, который отслеживает, какой актор (controller, operator, пользователь) управляет каждым полем ресурса.

**Server-Side Diffing** — режим, при котором вычисление разницы между Git и кластером делегируется API-серверу Kubernetes. Это позволяет учитывать работу всех мутирующих вебхуков (например, инъекцию sidecar-контейнеров) до проведения сравнения. При включении этого режима Argo CD получает уже «финальное» состояние ресурса после работы всех admission-контроллеров.

## Базовые концепции

### Методы настройки игнорирования

Argo CD предлагает три способа идентификации полей для исключения:

1.  **managedFieldsManagers (Рекомендуемый):** Опирается на то, *кто* изменил поле. Самый надежный метод для систем типа HPA, cert-manager или облачных контроллеров. Преимущество — автоматическое покрытие всех полей, которыми управляет указанный менеджер, без необходимости перечислять каждый путь. Недостаток — не работает, если контроллер не использует SSA или не записывает `managedFields`.

2.  **jqPathExpressions:** Опирается на логику JQ. Позволяет выбирать элементы в списках по условию (например, контейнер с конкретным именем в массиве `containers`). Гибкий метод для сложных структур данных. Преимущество — возможность фильтрации по значениям внутри списков. Недостаток — более сложный синтаксис, выше риск ошибок в выражениях.

3.  **jsonPointers:** Опирается на RFC6901. Классический метод указания жесткого пути к полю (например, `/spec/replicas`). Преимущество — простота и предсказуемость. Недостаток — не поддерживает динамические условия и работу со списками (кроме указания индекса).

**Критерии выбора метода:**

| Сценарий | Рекомендуемый метод | Причина |
| :--- | :--- | :--- |
| Контроллер масштабирования (HPA) | `managedFieldsManagers` | HPA всегда использует `kube-controller-manager` |
| Service Mesh (Istio, Linkerd) | `jqPathExpressions` | Sidecar-контейнеры добавляются динамически в массив |
| Фиксированное поле (replicas, clusterIP) | `jsonPointers` | Простой путь, не изменяется структурой |
| Облачный провайдер (GKE, AWS) | `managedFieldsManagers` | Контроллеры записывают `managedFields` |
| Kyverno / OPA Gatekeeper | `managedFieldsManagers` или `jqPathExpressions` | Зависит от типа мутации |

### Уровни конфигурации

- **Локальный (Application level):** Правила описываются внутри манифеста `Application` в секции `spec.ignoreDifferences`. Применяются только к конкретному приложению. Подходит для специфичных правил, которые не должны распространяться на другие приложения.

- **Глобальный (System level):** Настраивается в ConfigMap `argocd-cm`. Позволяет задать общие правила (Customizations) для всех приложений в кластере на основе Group/Kind ресурсов. Формат ключа: `resource.customizations.ignoreDifferences.<group>_<kind>`. Для всех ресурсов одного типа используется `resource.customizations.ignoreDifferences.all`.

**Приоритет:** Локальные правила переопределяют глобальные. Если правило задано и на уровне Application, и в `argocd-cm`, применяется правило из Application.

### Параметр RespectIgnoreDifferences

По умолчанию `ignoreDifferences` влияет только на визуальный статус (превращает `OutOfSync` в `Synced`). Однако при запуске синхронизации Argo CD по умолчанию попытается привести поле в соответствие с Git.

Чтобы Argo CD **не перезаписывал** игнорируемые поля во время автоматической или ручной синхронизации, необходимо установить параметр `RespectIgnoreDifferences=true` в `syncOptions`.

**Важно:** Если `RespectIgnoreDifferences=true` не установлен, Argo CD будет пытаться применить значение из Git даже для игнорируемых полей при каждой синхронизации. Это может привести к конфликтам с внешними контроллерами.

### Взаимодействие с Server-Side Apply (SSA)

При использовании SSA каждый контроллер, мутирующий ресурс, получает уникальный идентификатор менеджера в `metadata.managedFields`. Argo CD v3.x по умолчанию использует SSA для синхронизации, что делает `managedFieldsManagers` наиболее надежным методом.

**Рекомендация:** Для новых приложений всегда включайте `ServerSideApply=true` в `syncOptions`. Это обеспечит:
- Корректное разделение полей между контроллерами
- Предсказуемое поведение `managedFieldsManagers`
- Отсутствие конфликтов при одновременном управлении полями разными системами

## Практические сценарии

### Сценарий 1: Совместная работа с HPA (v3.x Way)

Вместо перечисления поля `replicas`, мы доверяем контроллеру, управляющему масштабированием. HPA использует `kube-controller-manager` как менеджер полей, поэтому все изменения количества реплик автоматически игнорируются.

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    managedFieldsManagers:
    - kube-controller-manager # HPA управляется этим менеджером
  syncPolicy:
    syncOptions:
    - RespectIgnoreDifferences=true
```

**Проверка:** После применения убедитесь, что поле `replicas` в `metadata.managedFields` содержит менеджера `kube-controller-manager`:

```bash
kubectl get deployment <name> -o jsonpath='{.metadata.managedFields[*].manager}' | tr ' ' '\n' | grep kube-controller
# → result: kube-controller-manager
```

### Сценарий 2: Игнорирование мутаций Service Mesh (Istio/Linkerd)

Системы Service Mesh внедряют sidecar-контейнеры и аннотации, которые отсутствуют в Git. Поскольку sidecar добавляется динамически в массив контейнеров, используется `jqPathExpressions` для точного указания контейнера по имени.

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jqPathExpressions:
    - .spec.template.spec.containers[] | select(.name == "istio-proxy")
    - .spec.template.metadata.annotations["sidecar.istio.io/status"]
```

**Для Linkerd** аналогично:

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jqPathExpressions:
    - .spec.template.spec.containers[] | select(.name == "linkerd-proxy")
    - .spec.template.metadata.annotations["linkerd.io/proxy-version"]
```

### Сценарий 3: Глобальное игнорирование системных аннотаций

Настройка в `argocd-cm` для исключения «шума» от облачных провайдеров (например, GKE/AWS/Yandex Cloud). Эти аннотации и метки добавляются автоматически и не должны влиять на статус синхронизации.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
data:
  resource.customizations.ignoreDifferences.all: |
    jqPathExpressions:
      - .metadata.annotations["cloud.google.com/gke-installed-by"]
      - .metadata.labels["managed-by-external-system"]
```

**Для AWS EKS:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
data:
  resource.customizations.ignoreDifferences.apps_Deployment: |
    jqPathExpressions:
      - .metadata.annotations["eks.amazonaws.com/compute-type"]
      - .metadata.labels["eks.amazonaws.com/pod-identity-association"]
```

### Сценарий 4: Принудительное обновление неизменяемых полей

Если в Git изменилось поле, которое Kubernetes запрещает обновлять (например, `spec.selector` в `Service` или `spec.clusterIP`), синхронизация завершится ошибкой.

**Решение через CLI:**

```bash
argocd app sync <app-name> --force
```

**Решение в коде (использовать с осторожностью):**

```yaml
spec:
  syncPolicy:
    syncOptions:
    - Force=true # Приведет к удалению и пересозданию ресурса
```

> **Внимание:** `Force=true` удаляет и пересоздает ресурс. Это может привести к даунтайму для Stateless-приложений и потере данных для StatefulSet. Используйте только когда `Replace=true` недостаточно.

**Альтернатива — `Replace=true`:**

```yaml
spec:
  syncPolicy:
    syncOptions:
    - Replace=true # Использует kubectl replace вместо apply
```

`Replace=true`.performicts с `kubectl replace`, который перезаписывает весь ресурс. Подходит для ресурсов с неизменяемыми полями, но не приводит к удалению.

### Сценарий 5: Интеграция с cert-manager

cert-manager автоматически добавляет и обновляет аннотации и TLS-секреты. Используйте `managedFieldsManagers` для игнорирования изменений от cert-manager.

```yaml
spec:
  ignoreDifferences:
  - group: cert-manager.io
    kind: Certificate
    managedFieldsManagers:
    - cert-manager-certificates-issuer
  - group: ""
    kind: Secret
    jqPathExpressions:
    - .metadata.annotations["cert-manager.io/certificate-name"]
    - .metadata.annotations["cert-manager.io/issuer-name"]
```

### Сценарий 6: Настройка для Reloader (Stakater)

Reloader автоматически перезапускает поды при изменении ConfigMap/Secret. Он добавляет аннотацию `reloader.stakater.com/last-reloaded-from`, которая создает «шум» в diff.

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jsonPointers:
    - /spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from
```

> **Примечание:** Тильда `~1` используется в JSON Pointer для экранирования слеша `/` в имени аннотации.

### Сценарий 7: Игнорирование status-блока для CRD

Многие Custom Resources имеют динамический блок `status`, который обновляется контроллером. Игнорирование всего блока предотвращает бесконечный `OutOfSync`.

```yaml
spec:
  ignoreDifferences:
  - group: "*"
    kind: "*"
    jsonPointers:
    - /status
```

> **Внимание:** Глобальное игнорирование `/status` для всех ресурсов может скрыть важные изменения. Рекомендуется указывать конкретные Group/Kind.

## Технический справочник

### Типичные менеджеры полей (Managers)

| Система | Имя менеджера (`managedFieldsManagers`) | Примечание |
| :--- | :--- | :--- |
| **Horizontal Pod Autoscaler** | `kube-controller-manager` | Управляет полем `spec.replicas` |
| **cert-manager** | `cert-manager-certificates-issuer` | Управляет Certificate и Secret |
| **Kyverno** | `kyverno` | Мутирует ресусы по политикам |
| **OPA Gatekeeper** | `gatekeeper` | Мутирует ресусы по политикам |
| **Argo CD (SSA)** | `argocd-controller` | При использовании Server-Side Apply |
| **Cloud Controllers** | `cloud-controller-manager` | Управляет LB, PV и облачными аннотациями |
| **Istio** | `istio-sidecar-injector` | Инжектирует sidecar-контейнеры |
| **Prometheus Operator** | `prometheus-operator` | Управляет ServiceMonitor и другими CRD |
| **External Secrets** | `external-secrets` | Управляет секретами из внешних хранилищ |

### Server-Side Diffing (Оптимизация)

Для ресурсов с огромным количеством динамических правок (например, `CustomResourceDefinitions`) рекомендуется включить Server-Side Diffing в `argocd-cm`:

```yaml
data:
  # Включение SSA для всех ресурсов по умолчанию
  server.side.apply.enabled: "true"
```

Это позволит Argo CD видеть «финальное» состояние ресурса после работы всех вебхуков, что радикально сокращает список необходимых `ignoreDifferences`.

**Глобальное включение Server-Side Diff:**

```yaml
data:
  # Включает сравнение на стороне сервера для всех приложений
  controller.diff.mode: "server-side"
```

**Включение для конкретного приложения ( через аннотации):**

```yaml
metadata:
  annotations:
    argocd.argoproj.io/compare-options: ServerSideDiff=true,IncludeMutationWebhook=true
```

### Сравнение методов игнорирования

| Критерий | managedFieldsManagers | jqPathExpressions | jsonPointers |
| :--- | :--- | :--- | :--- |
| **Простота настройки** | Высокая | Средняя | Высокая |
| **Гибкость** | Средняя | Высокая | Низкая |
| **Покрытие полей** | Все поля менеджера | Указанные выражения | Указанные пути |
| **Зависимость от SSA** | Да | Нет | Нет |
| **Работа со списками** | Автоматически | Да (через select) | Только по индексу |
| **Рекомендация (2026)** | Рекомендуется | Для сложных случаев | Для простых полей |

## Диагностика и устранение неисправностей

### Типичные проблемы

| Проблема | Симптомы | Вероятная причина | Решение |
| :--- | :--- | :--- | :--- |
| **Бесконечный `OutOfSync`** | Приложение постоянно в статусе `OutOfSync`, несмотря на `ignoreDifferences` | Неверный путь в `jsonPointers` или `jqPathExpressions` | Проверьте diff через `argocd app diff <name>` |
| **Игнорирование не работает** | Изменения все еще отображаются в diff | Не установлен `RespectIgnoreDifferences=true` | Добавьте `RespectIgnoreDifferences=true` в `syncOptions` |
| **Конфликт с HPA** | Argo CD пытается вернуть количество реплик | Не настроено игнорирование для `kube-controller-manager` | Добавьте `managedFieldsManagers: [kube-controller-manager]` |
| **Ошибка при синхронизации** | `error:unable to find match` | Несуществующий путь в `jqPathExpressions` | Проверьте JQ-выражение через `jq` локально |
| **Лишние ресурсы удаляются** | Kyverno/Reloader создают ресурсы, которые Argo CD пытается удалить | Не настроена политика Prune | Добавьте `Prune=false` в syncOptions или аннотацию `argocd.argoproj.io/sync-options: Prune=false` |

### Диагностические команды

```bash
# Просмотр diff для приложения
argocd app diff <app-name>

# Просмотр diff с учетом Server-Side Apply
argocd app diff <app-name> --server-side

# Просмотр managedFields ресурса
kubectl get <resource> <name> -o jsonpath='{.metadata.managedFields}' | jq

# Просмотр конкретного менеджера
kubectl get deployment <name> -o jsonpath='{.metadata.managedFields[*].manager}'

# Проверка текущего статуса приложения
argocd app get <app-name>

# Просмотр логов контроллера Argo CD
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller
```

### Пошаговая диагностика

1. **Проверьте diff:** `argocd app diff <name>` — покажет, какие именно поля различаются.
2. **Определите источник изменений:** `kubectl get <resource> <name> -o yaml | grep managedFields` — покажет, какой контроллер управляет каждым полем.
3. **Проверьте JQ-выражение локально:** `echo '<json>' | jq '<expression>'` — убедитесь, что выражение возвращает ожидаемый результат.
4. **Проверьте статус приложения:** `argocd app get <name>` — убедитесь, что `ignoreDifferences` применено.
5. **Просмотрите логи:** `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller` — найдите ошибки синхронизации.

## Валидация и проверка работоспособности

### Проверка применения правил

```bash
# 1. Примените манифест Application
kubectl apply -f application.yaml

# 2. Дождитесь обновления статуса (до 3 минут по умолчанию)
argocd app get <name> --refresh

# 3. Проверьте, что статус стал Synced
argocd app get <name> | grep Status
# → result: Status: Synced
```

### Проверка игнорирования конкретного поля

```bash
# 1. Измените поле, которое должно игнорироваться
kubectl patch deployment <name> --type merge -p '{"spec":{"replicas":5}}'

# 2. Дождитесь следующей сверки (или принудительно)
argocd app get <name> --refresh

# 3. Проверьте, что статус остался Synced
argocd app get <name> | grep Status
# → result: Status: Synced

# 4. Убедитесь, что поле НЕ было возвращено в Git-значение
kubectl get deployment <name> -o jsonpath='{.spec.replicas}'
# → result: 5 (не значение из Git)
```

### Проверка для `jqPathExpressions`

```bash
# 1. Проверьте JQ-выражение локально на примере ресурса
kubectl get deployment <name> -o json | jq '.spec.template.spec.containers[] | select(.name == "istio-proxy")'
# → result: Должен вернуть объект контейнера

# 2. Если выражение не работает, проверьте синтаксис
echo '{"containers":[{"name":"app"},{"name":"istio-proxy"}]}' | jq '.containers[] | select(.name == "istio-proxy")'
```

## Лучшие практики

### Приоритет методов

1. **Используйте `managedFieldsManagers`** как метод по умолчанию для v3.x. Он автоматически покрывает все поля менеджера и не требует обновления при изменении структуры ресурса.
2. **Переключайтесь на `jqPathExpressions`** только когда нужна фильтрация по значениям внутри списков (например, конкретный контейнер в массиве).
3. **Используйте `jsonPointers`** только для простых, фиксированных полей (например, `/spec/replicas`, `/status`).

### Безопасность

- **Не игнорируйте поля безопасности:** Не исключайте из diff поля `securityContext`, `runAsNonRoot`, `readOnlyRootFilesystem` и подобные — это может скрыть критические нарушения.
- **Используйте минимальные правила:** Вместо глобального `kind: "*"` указывайте конкретные Group/Kind.
- **Ревью через PR:** Любые изменения в `ignoreDifferences` должны проходить code review, так как это влияет на видимость drift в кластере.

### Масштабирование

- **Для ApplicationSet:** Задавайте `ignoreDifferences` в шаблоне ApplicationSet, чтобы правила применялись ко всем приложениям.
- **Для мультикластерных сред:** Используйте глобальные правила в `argocd-cm` для единообразия.
- **Для кастомных CRD:** Всегда добавляйте `managedFieldsManagers` для контроллера, который управляет вашим CRD.

### Мониторинг

- **Настраивайте алерты** на длительный статус `OutOfSync` — это может указывать на неправильно настроенное игнорирование.
- **Используйте Resource Health Checks** для визуализации состояния ресурсов в UI Argo CD.
- **Регулярно проверяйте** `managedFields` ресурсов — контроллеры могут обновляться и менять имена менеджеров.

## Ограничения и edge cases

### Ограничения

1. **`managedFieldsManagers` не работает без SSA:** Если контроллер не использует Server-Side Apply, его изменения не попадают в `managedFields`. В этом случае используйте `jqPathExpressions` или `jsonPointers`.

2. **Нет поддержки условий:** Argo CD не поддерживает условное игнорирование (например, «игнорировать поле только если значение > 100»). Все правила безусловны.

3. **Игнорирование не влияет на Health Checks:** `ignoreDifferences` влияет только на diff и статус `OutOfSync`. Статус здоровья ресурса (Healthy/Degraded) определяется отдельно.

4. **Конфликт с SelfHeal:** Если включены и `ignoreDifferences`, и `SelfHeal=true`, Argo CD может пытаться «починить» поля, которые не игнорируются. Убедитесь, что игнорируемые поля действительно исключены из diff.

### Edge Cases

1. **Ресурс без managedFields:** Некоторые ресурсы (например, Secret, созданный через `kubectl create secret`) могут не иметь `managedFields`. В этом случае `managedFieldsManagers` не работает.

2. **Множественные менеджеры одного поля:** Если одно поле управляется несколькими контроллерами (редкий случай), Argo CD игнорирует изменения от всех указанных менеджеров.

3. **Удаление managedFields:** Если контроллер удаляет запись из `managedFields` (например, при обновлении), Argo CD может начать отслеживать ранее игнорируемые поля.

4. **Helm и managedFields:** При использовании Helm через Argo CD может возникать конфликт менеджеров. Рекомендуется использовать `--atomic` и `--cleanup-on-fail` в Helm-аргументах.

5. **Cross-namespace ресурсы:** `ignoreDifferences` работает только в рамках одного Application. Для кросс-namespace ресурсов (например, ClusterRoleBinding) настройте глобальные правила.

## Дополнительная информация

### См. также
- [Синхронизация Argo CD: Обзор](../synchronization.md)
- [Автоматическая синхронизация и Self-Heal](./scenarios/auto_sync.md)
- [Диагностика и Troubleshooting](../argocd_troubleshooting_and_monitoring.md)
- [Интеграция Kyverno и Argo CD](../../../Kubernetes/Security/kyverno/argo-cd.md)

### Ссылки
- [Argo CD Documentation: Diff Customization](https://argo-cd.readthedocs.io/en/stable/user-guide/diff-customization/)
- [Kubernetes: Server-Side Apply Managed Fields](https://kubernetes.io/docs/reference/using-api/server-side-apply/#field-management)
- [RFC 6901: JavaScript Object Notation (JSON) Pointer](https://datatracker.ietf.org/doc/html/rfc6901)
