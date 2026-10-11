# Интеграция Kyverno с Argo CD

## Определения

**Интеграция Kyverno с Argo CD** — комплекс мер по настройке совместной работы GitOps-платформы и движка политик, исключающий конфликты при мутации ресурсов и обеспечивающий прозрачность нарушений безопасности (Policy Violations) непосредственно в интерфейсе управления.

---

## Основные концепции

### Проблематика совместного использования

При стандартной настройке Argo CD и Kyverno возникают три критические проблемы:

1.  **Бесконечный цикл синхронизации (Sync Drift)**: Kyverno мутирует ресурс при создании (например, добавляет Sidecar или лейблы). Argo CD видит разницу между Git и кластером и пытается "откатить" изменения.
2.  **Конфликты Resource Tracking**: Если оба инструмента используют одинаковые механизмы отслеживания (метки `app.kubernetes.io/instance`), это приводит к потере контроля над ресурсами.
3.  **Невидимость нарушений**: Без специальной настройки Argo CD считает приложение "Healthy", даже если Kyverno заблокировал создание части его ресурсов или зафиксировал критические ошибки безопасности в отчетах.

### Современный стек (2026)

Стандартом 2026 года для Argo CD v3.x является **полный переход на Server-Side Apply (SSA)** и **Server-Side Diff**. Это переносит логику объединения (merge) и сравнения манифестов на сторону Kubernetes API. При такой архитектуре мутации, внесенные Kyverno, сохраняются в `managedFields` ресурса, что позволяет Argo CD игнорировать их автоматически, если настроены соответствующие менеджеры полей.

### Архитектура взаимодействия: Webhook + GitOps Agent

Понимание порядка вызовов компонентов критично для диагностики проблем интеграции.

**Цикл создания ресурса при наличии Kyverno и Argo CD:**

1. **Git Push**: Оператор пушит манифест в Git-репозиторий.
2. **Argo CD Detects Drift**: Контроллер Argo CD обнаруживает расхождение между Git и кластером (статус `OutOfSync`).
3. **Argo CD Initiates Sync**: При автоматической или ручной синхронизации Argo CD отправляет `kubectl apply` (Client-Side) или `kubectl apply --server-side` (Server-Side) на API-сервер.
4. **API Server Processing**: Kubernetes API-сервер обрабатывает запрос и направляет его в цепочку Admission Controllers.
5. **Kyverno Webhook Intercept**: MutatingWebhookConfiguration перехватывает запрос и применяет мутации (добавление labels, sidecar, resource limits). Если политика содержит `validate` — Kyverно проверяет манифест и может вернуть `deny`.
6. **Final State Applied**: После прохождения всех Admission Controllers ресурс записывается в etcd с мутациями Kyverno.
7. **Argo CD Reconcile**: На следующей итерации реконсиляции Argo CD сравнивает желаемое состояние (Git) с фактическим (кластер). Если включен Server-Side Diff — разница вычисляется с учетом мутаций webhook-а.

**Критические моменты:**
- **Конфликт managedFields**: При Client-Side Apply Argo CD выступает `manager` для всех полей. Kyverno также пытается стать `manager` для мутированных полей. Возникает конфликт владения — ресурс не применяется или мутация откатывается. Решение — переход на Server-Side Apply.
- **Порядок apply**: Argo CD применяет ресурсы параллельно. Если Kyverno генерирует зависимые ресурсы (generate), они появляются после Apply исходного ресурса. Argo CD не знает о них до следующей итерации reconciliation loop.
- **Таймауты**: По умолчанию Argo CD ожидает 2 минуты для-sync каждого ресурса. Если Kyverno выполняет длительную верификацию (verifyImages с обращением к OIDC-реестру), синхронизация может завершиться таймаутом.

### Server-Side Apply: глубокое погружение

**Механизм работы SSA в контексте Kyverno + Argo CD:**

При использовании SSA каждый компонент становится `field manager` — уникальной сущностью, контролирующей определенные поля ресурса. API-сервер отслеживает владельцев каждого поля в `metadata.managedFields`.

| Компонент | Роль в SSA | Какие поля управляет |
| :--- | :--- | :--- |
| **Argo CD** | `argocd-application-controller` | Все поля из Git-манифеста (spec, metadata из репозитория). |
| **Kyverno** | `kyverno` | Поля, добавленные/измененные мутацией (labels, annotations, containers, env). |
| **kubectl** | `kubectl-client-side-apply` | Устаревший режим — конфликтует со всеми. |

**Порядок разрешения конфликтов (force resolution):**
1. Если оба менеджера претендуют на одно поле с разными значениями — API-сервер возвращает ошибку конфликта.
2. При `--force-conflicts` один из менеджеров теряет владение полем (побеждает последний apply).
3. Argo CD v3.x с SSA использует `--server-side --force-conflict` по умолчанию, что предотвращает ошибки конфликтов.

**Практическое значение**: При Client-Side Apply Kyverno не может надежно мутировать поля, которыми управляет Argo CD (например, `spec.replicas`). Мутация или откатывается, или Argo CD видит вечный `OutOfSync`. SSA решает эту проблему, передавая владение мутациями Kyverno в `managedFields`.

---

## Практические сценарии

### 1. Глобальная настройка Server-Side Diff

Чтобы Argo CD корректно учитывал изменения, внесенные мутирующими вебхуками Kyverno, необходимо включить сравнение на стороне сервера. Это критично для ресурсов, где Kyverno добавляет sidecar-контейнеры или инжектирует переменные окружения.

**В аннотациях Application**:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  annotations:
    # Включает server-side diff (учет мутаций admission-вебхуков)
    argocd.argoproj.io/compare-options: ServerSideDiff=true
spec:
  syncPolicy:
    syncOptions:
      - ServerSideApply=true # Использование SSA при синхронизации (стандарт v3.x)
```

### 2. Игнорирование системных различий (ignoreDifferences)

В Argo CD v3.x существует два способа исключения дрифта: классический (через пути) и современный (через менеджеров полей).

#### Способ А: Managed Fields (Рекомендуемый в 2026)
Этот метод позволяет Argo CD полностью доверять Kyverno в управлении определенными полями, не описывая каждое поле вручную.

**В Application или argocd-cm**:
```yaml
spec:
  ignoreDifferences:
    - group: "*"
      kind: "*"
      managedFieldsManagers:
        - kyverno # Игнорировать все изменения, внесенные менеджером kyverno
```

#### Способ Б: JQ и JSON Pointers
Используется для специфических полей Kyverno, которые не всегда попадают под управление менеджера (например, автогенерируемые правила).

**Настройка в Application**:
```yaml
spec:
  ignoreDifferences:
    - group: kyverno.io
      kind: ClusterPolicy
      jqPathExpressions:
        - .spec.rules[] | select(.name|test("autogen-.")) # Игнорировать автогенерируемые правила
        - .spec.rules[].skipBackgroundRequests            # Техническое поле Kyverno
    - group: kyverno.io
      kind: Policy
      jsonPointers:
        - /status # Игнорировать блок статуса
```

### 3. Конфликты при генерации ресурсов (Generate Rules)

Kyverno может генерировать новые ресурсы (например, `NetworkPolicy` или `ConfigMap`) при создании Namespace. Если этот Namespace управляется Argo CD, он увидит «лишние» ресурсы и попытается их удалить (Prune).

**Решение**:
Для ресурсов, генерируемых Kyverno, необходимо добавить аннотацию, запрещающую Argo CD их удалять, или исключить их из процесса прунинга.

**В шаблоне политики Kyverno (generate)**:
```yaml
generate:
  apiVersion: v1
  kind: ConfigMap
  name: global-config
  data:
    metadata:
      annotations:
        # Указывает Argo CD игнорировать этот ресурс при очистке
        argocd.argoproj.io/sync-options: Prune=false
```

### 4. Визуализация отчетов (PolicyReport) в UI Argo CD

Чтобы видеть нарушения политик безопасности непосредственно в дашборде Argo CD, необходимо настроить **Health Checks** для ресурсов отчетов Kyverno. Это позволяет приложению переходить в статус `Degraded`, если обнаружены критические нарушения.

**В конфигурации Argo CD (argocd-cm)**:
```yaml
data:
  # Настройка для обычных отчетов (в Namespace)
  resource.customizations.health.wgpolicyk8s.io_PolicyReport: |
    hs = {}
    if obj.summary.fail > 0 then
      hs.status = "Degraded"
      hs.message = "Нарушения политик: " .. obj.summary.fail
    else
      hs.status = "Healthy"
      hs.message = "Проверки безопасности пройдены"
    end
    return hs

  # Настройка для кластерных отчетов
  resource.customizations.health.wgpolicyk8s.io_ClusterPolicyReport: |
    hs = {}
    if obj.summary.fail > 0 then
      hs.status = "Degraded"
      hs.message = "Кластерные нарушения: " .. obj.summary.fail
    else
      hs.status = "Healthy"
    end
    return hs
```

### 5. Порядок установки (Sync Waves)

Для корректной работы системы при первичной установке необходимо соблюдать очередность:

| Волна (Wave) | Компоненты | Зачем |
| :--- | :--- | :--- |
| **0** | Namespace, Secrets, ConfigMaps. | Базовая инфраструктура. |
| **1** | Контроллер Kyverno (Helm). | Контроллер должен быть готов до появления политик. |
| **2** | ClusterPolicies / Policies. | Политики должны быть загружены до появления нагрузки. |
| **3+** | Application Workloads. | Поды будут проверены или мутированы сразу при создании. |

### 6. RBAC для mutateExisting: права контроллера Kyverno

При использовании `mutateExisting` в политиках Kyverno контроллер должен иметь RBAC-права на целевые ресурсов. ВGitOps-моделе эти права описываются в том же репозитории, что и политики.

**ClusterRole для Kyverno controller (базовый набор):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno:mutate-existing
rules:
  - apiGroups: [""]
    resources: [configmaps, secrets, services]
    verbs: [get, list, watch, update, patch]
  - apiGroups: [apps]
    resources: [deployments, statefulsets, daemonsets]
    verbs: [get, list, watch, update, patch]
  - apiGroups: [networking.k8s.io]
    resources: [networkpolicies]
    verbs: [get, list, watch, create, update, patch]
```

**Привязка к ServiceAccount:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: kyverno:mutate-existing
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: kyverno:mutate-existing
subjects:
  - kind: ServiceAccount
    name: kyverno
    namespace: kyverno
```

**Важно:** Если Kyverno устанавливается через Helm-чарт в namespace `kyverno`, ServiceAccount по умолчанию — `kyverno`. При установке через Argo CD убедитесь, что namespace `kyverno` создан до деплоя чарта (Sync Wave 0 или 1).

### 7. Конфликт SelfHeal и Kyverno мутаций

Argo CD в режиме `selfHeal: true` пытается вернуть ресурс в состояние из Git, перезаписывая ручные изменения и мутации Kyverno. Это создает бесконечный цикл: Kyverno мутирует -> Argo CD откатывает -> Kyverno мутирует снова.

**Симптомы:**
- Бесконечный `OutOfSync` с частыми операциями sync в журнале Argo CD.
- В `managedFields` чередуются записи `argocd-application-controller` и `kyverno`.
- События `NormalizedState` перезаписываются каждые несколько секунд.

**Решение 1: Исключение через managedFieldsManagers (рекомендуется)**
```yaml
spec:
  ignoreDifferences:
    - group: "*"
      kind: "*"
      managedFieldsManagers:
        - kyverno
```

**Решение 2: Исключение конкретных полей через jqPathExpressions**
```yaml
spec:
  ignoreDifferences:
    - group: "*"
      kind: Deployment
      jqPathExpressions:
        - .spec.template.spec.containers[] | select(.name == "injected-sidecar")
        - .metadata.labels | to_entries | map(select(.key | startswith("kyverno.io/")))
```

**Решение 3: Отключение SelfHeal для конкретных приложений**
```yaml
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: false  # Отключить для приложений с активными мутациями Kyverno
```

**Диагностика:** Проверьте, кто управляет конфликтующими полями:
```bash
kubectl get deployment <name> -o jsonpath='{.metadata.managedFields}' | jq .
# → result: [{manager: "argocd-application-controller", ...}, {manager: "kyverno", ...}]
```

### 8. ApplicationSet с исключениями для Kyverno

При управлении множеством приложений через ApplicationSet необходимо настроить `ignoreDifferences` на уровне шаблона, чтобы правила применялись ко всем приложениям единообразно.

**Пример ApplicationSet с Managed Fields исключениями:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: microservices
spec:
  generators:
    - git:
        repoURL: https://git.company.com/apps
        revision: main
        directories:
          - path: services/*
  template:
    metadata:
      name: '{{path.basename}}'
    spec:
      project: default
      source:
        repoURL: https://git.company.com/apps
        targetRevision: main
        path: '{{path}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - ServerSideApply=true
      ignoreDifferences:
        - group: "*"
          kind: "*"
          managedFieldsManagers:
            - kyverno
        - group: kyverno.io
          kind: ClusterPolicy
          jqPathExpressions:
            - .spec.rules[] | select(.name | test("autogen-.")) | .skipBackgroundRequests
```

**Для кастомных CRD с мутациями Kyverno:**
```yaml
    ignoreDifferences:
      - group: "vault.hashicorp.com"
        kind: VaultStaticSecret
        jqPathExpressions:
          - .spec.token  # Kyverno может инжектить токен через mutateExisting
```

### 9. Тестирование интеграции перед деплоем

Перед отправкой политик в production рекомендуется проверить взаимодействие Kyverno и Argo CD локально или в staging-кластере.

**Шаг 1: Тестирование политики Kyverno (CLI)**
```bash
# Подготовка тестовых фикстур
cat > test-pod.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
  labels:
    app: test
spec:
  containers:
  - name: nginx
    image: nginx:latest  # Должен мутировать pullPolicy -> Always
EOF

# Запуск теста
kyverno test ./policies/ -f test-pod.yaml --detailed-results
# → result:
# Applying 2 policies to 1 resource...
# │───│──────────────────────│─────────────────│────────│
# │ # │ POLICY               │ RULE            │ RESULT │
# │───│──────────────────────│─────────────────│────────│
# │ 1 │ add-pull-policy      │ mutate-policy   │ Pass   │
# │ 2 │ require-labels       │ validate-policy │ Pass   │
```

**Шаг 2: Проверка мутации через kubectl dry-run**
```bash
kubectl apply -f test-pod.yaml --dry-run=server -o yaml | grep -A5 "imagePullPolicy"
# → result:
#   imagePullPolicy: Always  # Мутация применена webhook-ом
```

**Шаг 3: Проверка diff в Argo CD (staging)**
```bash
argocd app diff myapp --server-side --local=.
# → result:
# ========  ========
#   apiVersion: v1
#   kind: Pod
#   spec:
#     containers:
#     - image: nginx:latest
# +     imagePullPolicy: Always  # Добавлено Kyverno
#     name: nginx
```

**Шаг 4: Проверка, что Argo CD не показывает ложный OutOfSync**
```bash
argocd app get myapp | grep "STATUS"
# → result:
# STATUS:  Synced  # Если настроены ignoreDifferences + ServerSideDiff
```

### 10. Порядок удаления политик (Uninstall Waves)

При удалении Kyverno через Argo CD важно соблюдать обратный порядок для избежания блокировки ресурсов.

| Волна | Компоненты | Действие |
| :--- | :--- | :--- |
| **3-** | Application Workloads | Сначала удалить нагрузку (если политики в режиме Enforce). |
| **2** | ClusterPolicies / Policies | Удалить политики до остановки контроллера. |
| **1** | Kyverno Controller (Helm) | Остановить контроллер. |
| **0** | Namespace, Secrets | Удалить конфигурацию последней. |

**Важно:** Если политики в режиме `Enforce` и контроллер остановлен до удаления политик, новые поды могут быть заблокированы (webhook недоступен). Используйте `validationFailureAction: Audit` перед удалением.

---

## Дополнительная информация

### Сводная таблица параметров Argo CD для Kyverno (v3.x)

| Параметр | Уровень | Значение | Назначение |
| :--- | :--- | :--- | :--- |
| `ServerSideApply=true` | Sync Option | Да | Рекомендуемый метод для всех ресурсов в 2026 году. |
| `ServerSideDiff=true` | Annotation | Да | Точное сравнение с учетом мутаций на стороне API (v3.5+). Модификации мутирующих вебхуков удаляются из diff по умолчанию. |
| `managedFieldsManagers` | ignoreDiff | [`<имя-менеджера-kyverno>`] | Игнорирование мутаций от Kyverno. Имя менеджера зависит от версии — проверьте его в `metadata.managedFields` целевого ресурса. |

### Особенности Kyverno 1.13+: AdmissionReport

В новых версиях Kyverno отчеты о проверках в момент допуска (Admission) могут сохраняться в ресурсах `AdmissionReport`. В отличие от `PolicyReport`, они эфемерны и могут не требовать постоянного мониторинга в Argo CD, однако для критических приложений рекомендуется также настраивать для них Health Checks по аналогии с `PolicyReport`.

### Особенности работы с Helm

Если Kyverno устанавливается как Helm-чарт через Argo CD, важно обратить внимание на параметр `config.preserve`. 
- **Рекомендация**: Установите `config.preserve=false`. В противном случае Helm создаст `post-delete` хуки для сохранения конфигурации, которые могут блокировать автоматическое удаление ресурсов контроллером Argo CD.

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| Бесконечный `OutOfSync` | `argocd app diff <name> --server-side` | Убедитесь, что `managedFieldsManagers` содержит `kyverno`. |
| Ресурс не мутируется | Проверьте аннотации в объекте | Если используется SSA, проверьте `managedFields` — там должен быть указан менеджер `kyverno`. |
| Приложение `Healthy`, но поды не создаются | `kubectl get events -n <ns>` | Kyverno заблокировал создание (Admission Control). Проверьте `PolicyReport` в UI. |
| Ошибка `Too large resource` | Логи `argocd-application-controller` | Включите `ServerSideApply=true` для этого приложения. |
| `generate` правило не создает ресурсы | `kubectl get updaterequests -n kyverno` | Проверьте права RBAC контроллера Kyverno на целевые Namespace. |
| Kyverno откатывает мутацию Argo CD | `kubectl get <resource> -o jsonpath='{.metadata.managedFields}'` | Два менеджера борются за одно поле. Используйте `ignoreDifferences` или перенесите мутацию в Git. |
| AdmissionReport не отображается в Argo CD | `kubectl get admissionreports -A` | `AdmissionReport` — эфемерный ресурс. Настройте Health Check аналогично PolicyReport. |
| Конфликт с HPA (replicas мигает) | `kubectl get hpa` + `kubectl get deploy -o yaml \| grep replicas` | HPA управляет `replicas`, Kyverno мутирует, Argo CD возвращает из Git. Используйте `managedFieldsManagers: [kube-controller-manager, kyverno]`. |
| Синхронизация зависает на Timeout | `kubectl logs -n argocd -l app=argocd-application-controller \| grep timeout` | Увеличьте таймаут: `argocd app sync <name> --timeout 300` или сократите время верификации образов в Kyverno. |
| Политика Apply вызывает ошибку `field is immutable` | `kubectl get clusterpolicy <name> -o yaml` | Некоторые поля ClusterPolicy immutable после создания. Удалите и пересоздайте политику. |
| `prune` удаляет ресурсы, сгенерированные Kyverno | Проверьте аннотации на сгенерированных ресурсах | Добавьте `argocd.argoproj.io/sync-options: Prune=false` в generate-шаблон политики. |
| Helm Release конфликтует с Kyverno | `helm list -n <ns>` + проверка `managedFields` | Helm использует свои labels/annotations. Добавьте `managedFieldsManagers: [helm]` в `ignoreDifferences`. |

### Best Practices

1. **SSA обязателен для production**: Всегда используйте `ServerSideApply=true` и `ServerSideDiff=true` для приложений с мутирующими политиками Kyverno.
2. **Единый источник для ignoreDifferences**: Определяйте правила исключения в ApplicationSet шаблоне, а не в каждом Application — это упрощает поддержку.
3. **Валидация перед Apply**: Используйте `kyverno test` в CI-пайплайне перед мержем политик в основную ветку.
4. **Монитинг через PolicyReport**: Настройте Health Checks для `PolicyReport` и `ClusterPolicyReport` в `argocd-cm` — это обеспечит видимость нарушений в UI Argo CD.
5. **Audit перед Enforce**: Начинайте с `validationFailureAction: Audit`, анализируйте PolicyReports, и только после этого переходите в `Enforce`.
6. **Исключения для CI/CD**: Временно отключайте политики для пайплайнов, используя `preconditions` с проверкой `request.userInfo.username` ( service account CI/CD).
7. **Версионирование политик**: Храните политики в отдельном Git-репозитории от приложений. Это позволяет применять политики раньше workload'ов через Sync Waves.
8. **Логирование мутаций**: Включите `--v=3` в контроллере Kyverno для отладки сложных конфликтов с Argo CD.

### См. также
- [Установка Kyverno с помощью Argo CD](./install.md)
- [Типы правил и механизмы мутации](./rules.md)
- [Официальный Policy Reporter UI (визуализация)](./reporter.md)
