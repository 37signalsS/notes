# Библиотека политик Kyverno: Практические примеры

## Определения

**Библиотека политик** — структурированная коллекция проверенных манифестов Kyverno, предназначенная для быстрого внедрения стандартов безопасности и автоматизации в кластер Kubernetes.

**ValidatingPolicy / MutatingPolicy** — специализированные ресурсы (v1.14+), оптимизированные для выполнения CEL-выражений (Common Expression Language). Они обеспечивают нативную интеграцию с Kubernetes API и работают значительно быстрее классических `ClusterPolicy`. Подробнее: [definitions_and_concepts.md](./definitions_and_concepts.md).

**ClusterPolicy (v1)** — классический ресурс Kyverno с JMESPath-выражениями. Поддерживает все типы правил: `validate`, `mutate`, `generate`, `verifyImages`, `cleanup`. Работает через Admission Webhook с сетевым вызовом (5-15 мс).

**CleanupPolicy** — асинхронный процесс удаления устаревших ресурсов по расписанию (Cron). Управляется через `cleanup-controller`. Подробнее: [cleanup_verification.md](../Scenarios/cleanup_verification.md).

---

## Основные концепции

### Категории политик

| Категория | Цель | Основные инструменты |
| :--- | :--- | :--- |
| **Prevention** | Блокировка небезопасных ресурсов. | `ValidatingPolicy` (CEL). |
| **Correction** | Автоматическое исправление манифестов. | `MutatingPolicy`, `patchStrategicMerge`. |
| **Automation** | Генерация зависимых объектов. | `generate`, `clone`. |
| **Verification** | Проверка целостности артефактов. | `verifyImages`, Sigstore. |

### Ключевые паттерны для DevOps/SRE

| Паттерн | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Shift-Left** | Проверка манифестов в CI до деплоя. | Предотвращение промахов в Admission. |
| **Audit → Enforce** | Сначала мониторинг, потом блокировка. | Новые политики, где возможны ложные срабатывания. |
| **Exception-based** | Точечные исключения через `PolicyException`. | Legacy-приложения, временные допуски. |
| **Defense-in-Depth** | Многоуровневая защита: Admission + Supply Chain + Background. | Соответствие стандартам (PCI DSS, NIS2). |
| **Mutate-then-Validate** | Сначала исправление, потом проверка. | Единый стандарт для всех команд. |

---

## Практические сценарии

### 1. Запрет привилегированных контейнеров (PSS Baseline)

Предотвращает запуск контейнеров, имеющих неограниченный доступ к ресурсам хоста. Использует современный синтаксис `ValidatingPolicy`.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: disallow-privileged-containers
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
    - expression: |
        (object.spec.containers + object.spec.?initContainers.orValue([]) + object.spec.?ephemeralContainers.orValue([])).all(c, 
          !has(c.securityContext) || !has(c.securityContext.privileged) || c.securityContext.privileged == false
        )
      message: "Привилегированные контейнеры запрещены стандартами безопасности."
```

**Валидация:**
```bash
# Проверка отсутствия привилегированных подов
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.containers[]?.securityContext.privileged == true) | .metadata.name'
```

### 2. Верификация образов через Sigstore (Supply Chain)

Блокировка запуска образов, которые не были подписаны доверенным ключом в реестре. Это критично для предотвращения атак на цепочку поставок.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  background: false
  rules:
    - name: verify-sigstore
      match:
        any:
          - resources:
              kinds: [Pod]
      verifyImages:
        - imageReferences: ["ghcr.io/my-org/*"]
          attestors:
            - entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
                      -----END PUBLIC KEY-----
```

**Примечание**: Для keyless-подписи (OIDC) используйте `attestors[].entries[].keys`.keyless`. Подробнее: [cleanup_verification.md](../Scenarios/cleanup_verification.md).

### 3. Ограничение типов томов hostPath (PSS Restricted)

Запрещает использование `hostPath`, что предотвращает несанкционированный доступ контейнеров к файловой системе узла.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: restrict-host-path
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      resources: ["pods"]
  validations:
    - expression: |
        !has(object.spec.volumes) || object.spec.volumes.all(vol, !has(vol.hostPath))
      message: "Использование hostPath запрещено. Используйте PVC или emptyDir."
```

### 4. Автоматическое внедрение лимитов ресурсов (Мутация)

Если разработчик не указал лимиты, Kyverno автоматически добавит их, предотвращая деградацию кластера из-за «прожорливых» приложений.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: set-default-resources
spec:
  rules:
    - name: set-cpu-memory-limits
      match:
        any:
          - resources:
              kinds: [Pod]
      mutate:
        patchStrategicMerge:
          spec:
            containers:
              - (name): "*" # Применить ко всем контейнерам
                resources:
                  limits:
                    cpu: "500m"
                    memory: "512Mi"
                  requests:
                    cpu: "100m"
                    memory: "128Mi"
```

### 5. Инициализация Namespace (Генерация)

Автоматическое создание стандартных ресурсов (NetworkPolicy, LimitRange) при создании нового пространства имен.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: init-new-namespace
spec:
  rules:
    - name: create-default-network-policy
      match:
        any:
          - resources:
              kinds: [Namespace]
      generate:
        apiVersion: networking.k8s.io/v1
        kind: NetworkPolicy
        name: default-deny-ingress
        namespace: "{{request.object.metadata.name}}"
        data:
          spec:
            podSelector: {}
            policyTypes: [Ingress]
```

### 6. Мутация существующих ресурсов (mutateExisting)

При обновлении политики Kyverno может применить изменения к уже запущенным ресурсам. Критично для безопасного обновления политик без пересоздания подов.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-security-label-existing
spec:
  rules:
    - name: label-existing-deployments
      match:
        any:
          - resources:
              kinds: [Deployment]
      mutate:
        targets:
          - apiVersion: apps/v1
            kind: Deployment
            namespace: "{{ request.namespace }}"
        patchStrategicMerge:
          metadata:
            labels:
              security-scan: "enabled"
              last-audit: "{{ time_now_utc() }}"
```

**Требования к RBAC**: Контроллер `background-controller` должен иметь права на чтение и изменение целевых ресурсов. См. [aggregated ClusterRoles](../additional.md).

### 7. Запрет тега `:latest` ( CEL-валидация)

Запрет использования тегов `:latest` для предсказуемости деплоев и отслеживания версий.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: disallow-latest-tag
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
    - expression: |
        object.spec.containers.all(c, !c.image.endsWith(":latest"))
      message: "Тег ':latest' запрещён. Используйте конкретную версию или дайджест."
```

### 8. Ограничение реестров образов (Белый список)

Разрешение образов только из доверенных реестров. Важно для предотвращения атак через вредоносные образы.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: restrict-registries
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
    - expression: |
        (object.spec.containers + object.spec.?initContainers.orValue([])).all(c,
          c.image.startsWith("ghcr.io/my-org/") || c.image.startsWith("registry.internal/")
        )
      message: "Разрешены только образы из доверенных реестров (ghcr.io/my-org/, registry.internal/)."
```

### 9. Запрет hostAliases (Изоляция DNS)

Запрещает добавление записей в `/etc/hosts` подов — это блокирует атаки через подмену DNS.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: disallow-host-aliases
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
    - expression: |
        !has(object.spec.hostAliases) || size(object.spec.hostAliases) == 0
      message: "Использование hostAliases запрещено. Настройте DNS через CoreDNS."
```

### 10. Валидация ResourceQuota перед деплоем

Проверка перед деплоем: не превышают ли запрошенные ресурсы квоты Namespace. Предотвращает промахи планировщика и оставление подов в статусе `Pending`.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-resource-quota
spec:
  rules:
    - name: validate-cpu-request
      context:
        - name: quota-data
          apiCall:
            urlPath: "/api/v1/namespaces/{{request.namespace}}/resourcequotas"
            jmesPath: "items[0].status.hard.cpu"
      validate:
        message: "Запрошенный CPU ({{ request.object.spec.containers[0].resources.requests.cpu }}) превышает квоту Namespace."
        deny:
          conditions:
            all:
              - key: "{{ request.object.spec.containers[0].resources.requests.cpu }}"
                operator: GreaterThan
                value: "{{ quota-data }}"
```

### 11. Генерация NetworkPolicy для сегментации Namespace (GitOps)

Автоматическая сегментация: при аннотации Namespace создается политика по умолчанию deny-all.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: generate-network-segmentation
spec:
  rules:
    - name: create-default-deny
      match:
        any:
          - resources:
              kinds: [Namespace]
              annotations:
                kyverno.io/generate-networkpolicy: "true"
      generate:
        synchronize: true
        apiVersion: networking.k8s.io/v1
        kind: NetworkPolicy
        name: default-deny-all
        namespace: "{{ request.object.metadata.name }}"
        data:
          spec:
            podSelector: {}
            policyTypes:
              - Ingress
              - Egress
```

### 12. Исключения через PolicyException (DevOps-сценарий)

Точечные исключения для legacy-приложений без ослабления глобальных политик.

```yaml
apiVersion: kyverno.io/v1
kind: PolicyException
metadata:
  name: legacy-app-exception
  namespace: team-backend
spec:
  exceptions:
    - policyName: disallow-privileged-containers
      ruleNames:
        - check-privileged
  match:
    any:
      - resources:
          kinds:
            - Pod
          namespaces:
            - team-backend
          names:
            - legacy-*
```

**Важно**: `PolicyException` требует отдельного RBAC-контроля. Рекомендуется выделить отдельную группу через `ClusterRoleBinding` с правами на создание `policyexceptions`.

### 13. Мутация labels и аннотаций для мониторинга

Автоматическое добавление меток для агрегации в Prometheus и Grafana.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-monitoring-labels
spec:
  rules:
    - name: label-pods
      match:
        any:
          - resources:
              kinds: [Pod]
      mutate:
        patchStrategicMerge:
          metadata:
            labels:
              app.kubernetes.io/managed-by: kyverno
              monitoring.enabled: "true"
            annotations:
              prometheus.io/scrape: "true"
              prometheus.io/port: "9090"
```

### 14. Ограничение размера образа (maxSize)

Блокировка образов, превышающих допустимый размер (в MB), для экономии дискового пространства на узлах.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: limit-image-size
spec:
  rules:
    - name: check-image-size
      context:
        - name: image-size
          apiCall:
            urlPath: "/api/v1/namespaces/{{request.namespace}}/pods/{{request.object.metadata.name}}/log"
            jmesPath: "length(content)"
      validate:
        message: "Размер образа превышает допустимый лимит."
        deny:
          conditions:
            all:
              - key: "{{ image-size }}"
                operator: GreaterThan
                value: 104857600  # 100 MB в байтах
```

**Примечание**: Реализация зависит от реестра. Для Docker Hub используйте API `/v2/<image>/manifests/<tag>` с проверкой `Content-Length`.

### 15. Shift-Left: проверка в CI/CD (kyverno test)

Интеграция Kyverno CLI в пайплайн для проверки манифестов перед деплоем.

```bash
# Структура тестов
tests/
├── policy.yaml        # Тестируемая политика
├── resource-pass.yaml # Манифест, который должен пройти
├── resource-fail.yaml # Манифест, который должен быть заблокирован
└── kyverno-test.yaml  # Ожидаемые результаты
```

```yaml
# kyverno-test.yaml
apiVersion: cli.kyverno.io/v1alpha1
kind: Test
metadata:
  name: test-disallow-privileged
results:
  - policy: disallow-privileged-containers
    rules:
      - check-privileged
    resources:
      - resource-pass
    result: pass
  - policy: disallow-privileged-containers
    rules:
      - check-privileged
    resources:
      - resource-fail
    result: fail
```

```bash
# Выполнение тестов в CI
kyverno test tests/ --detailed-results
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Shift-Left Security**: Используйте `kyverno CLI` для проверки манифестов в CI пайплайнах. Это позволяет исправить нарушения до того, как они попадут в Admission-контроллер.
2.  **Режим Audit для новых правил**: Всегда внедряйте политики сначала в режиме `Audit`. Проверьте результаты через **[Policy Reports](../reports.md)**, чтобы убедиться в отсутствии ложноположительных срабатываний.
3.  **Исключения (PolicyException)**: Используйте ресурс `PolicyException` для временных разрешений (например, для специфического legacy-приложения), не ослабляя общую политику кластера.
4.  **Безопасность системных Namespace**: Всегда добавляйте исключения (`exclude`) для `kube-system` и `kyverno`, чтобы предотвратить «мертвую петлю», когда контроллер блокирует сам себя.

### Чек-лист для продакшена

| Проверка | Команда / Действие |
| :--- | :--- |
| Политики в Audit перед Enforce | `validationFailureAction: Audit` → мониторинг 1-2 недели → `Enforce` |
| Тесты пройдены | `kyverno test tests/ --detailed-results` |
| Исключения для системных NS | `exclude.resources.namespaces: [kube-system, kyverno, istio-system]` |
| RBAC для PolicyException | `ClusterRoleBinding` с правами на `policyexceptions` |
| Мониторинг PolicyReport | Алерт на рост `policy_report_results` в Prometheus |
| CI/CD интеграция | `kyverno apply` перед `kubectl apply` |
| Аудит background scan | `spec.background: true` для всех validate-политик |
| Документация политик | Аннотации `policies.kyverno.io/title`, `policies.kyverno.io/description` |

### Типичные ошибки и диагностика

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Политика не применяется к существующим ресурсам | Отсутствует фоновое сканирование или `mutateExisting` | Убедитесь, что `spec.background: true` и используйте `targets` в mutate. |
| `generate` не создает ресурсы в новом NS | Нет триггера или проблемы с RBAC | Проверьте `updaterequests` и права контроллера. |
| Ошибка `validation failed` при валидации | Несовпадение шаблона с реальным манифестом | Используйте `kubectl get policyreport -A` для диагностики. |
| Мутация не применяется к Pod | Pod создан до применения политики | Используйте `mutateExisting` + `background: true`. |
| CEL-политика не работает в VAP-режиме | Ошибка в выражении CEL или неверный `matchConstraints` | Проверьте логи Admission Controller, используйте `dryRun=Server`. |
| `PolicyException` не действует | Имя политики или правила не совпадает | Проверьте `policyName` и `ruleNames` в `PolicyException`. |
| `verifyImages` не блокирует образ | Образ не в списке `imageReferences` | Расширьте glob-паттерн или добавьте конкретный реестр. |

### См. также

- **[Типы правил (подробный синтаксис)](../rules.md)** — глубокое погружение в validate, mutate, generate.
- **[Определения и структура](./definitions_and_concepts.md)** — база для написания манифестов.
- **[Интеграция с Argo CD](../argo-cd.md)** — GitOps и визуализация отчетов.
- **[Supply Chain Security: Обзор](../../../../Security/Supply_Chain_Security/overview.md)** — теория защиты цепочки поставок.
- **[Очистка и верификация](../Scenarios/cleanup_verification.md)** — TTL, CleanupPolicy, image verification.
- **[Автоматизация и Compliance](../Scenarios/automation_compliance.md)** — CI/CD, continuous compliance, multi-tenancy.
