# Автоматизация и соответствие стандартам (Compliance) в Kyverno

## Определения

**Автоматизация (Automation)** — процесс принудительного исполнения эксплуатационных стандартов и политик безопасности без ручного вмешательства. В Kyverno реализуется через мутацию данных (`mutate`), динамическую генерацию новых объектов (`generate`) и сверхбыструю CEL-валидацию.

**Соответствие (Compliance)** — непрерывное подтверждение соблюдения нормативных требований (PCI DSS 4.0, NIS2, CIS Benchmarks, SOC 2). В современной инфраструктуре комплаенс реализуется через модель **Continuous Compliance** (непрерывный аудит), где политика выступает в роли «живого» контроля качества. Каждый Admission-запрос — это точка проверки, а не разовые ручные аудиты раз в квартал.

**Мультиарендность (Multi-tenancy)** — модель использования кластера, где Kyverno обеспечивает жесткую изоляцию ресурсов команд, автоматизируя создание границ безопасности (NetworkPolicies, RBAC, ResourceQuotas, LimitRange).

---

## Основные концепции

### Стратегии автоматизированного контроля

Kyverno использует специализированные контроллеры для реализации четырех основных стратегий ([подробнее о правах контроллеров](../additional.md)):

| Стратегия | Описание | Применение в 2026 году |
| :--- | :--- | :--- |
| **Mutate** | Изменение манифеста «на лету» перед сохранением. | Инъекция sidecar-контейнеров, логов и меток. |
| **Generate** | Создание ресурсов на основе событий API. | Инициализация Namespace (создание Quotas, NetPol). |
| **Clone** | Копирование эталонных ресурсов. | Синхронизация корпоративных CA и Secrets. |
| **CEL Validate** | Сверхбыстрая проверка условий. | Блокировка некомплаентных конфигураций в CI и Admission. |

### Паттерны мутации

Kyverno поддерживает три подхода к мутации ([подробный синтаксис в rules.md](../rules.md)):

| Паттерн | Механизм | Когда использовать |
| :--- | :--- | :--- |
| **Strategic Merge Patch** | `patchStrategicMerge` — нативный механизм Kubernetes для слияния манифестов. | Инъекция/env, добавление меток, sidecar-контейнеры. |
| **JSON Patch (RFC 6902)** | `patchJSON6902` — набор операций (add, remove, replace) по JSON-путям. | Сложные структуры, где strategic merge неприменим (например, массивы с condition). |
| **Foreach** | `foreach` — итерация по списку контейнеров/ volumes. | Массовая инъекция в каждый контейнер Pod'а. |

**Важно**: `patchStrategicMerge` работает с нативными типами Kubernetes (Pod, Deployment). Для CRD и сложных JSON-структур используйте `patchJSON6902`.

### Паттерны генерации

| Паттерн | Описание | Пример |
| :--- | :--- | :--- |
| **Data** | Создание ресурса «с нуля» с указанием `data`-блока. | ResourceQuota, NetworkPolicy, LimitRange. |
| **Clone** | Копирование эталонного ресурса из конкретного Namespace. | Клонирование CA-сертификата или Registry-Secret. |
| **Synchronize** | Автоматическое обновление сгенерированного ресурса при изменении шаблона. | `synchronize: true` — мгновенное распространение изменений CA. |

**Рекомендация**: Всегда устанавливайте `synchronize: true` для правил `generate`. Без него изменения в шаблоне политики не отразятся на уже созданных ресурсах ([подробнее](../rules.md)).

### Непрерывный аудит и Compliance-as-Code

Модель Continuous Compliance в Kyverno работает на трех уровнях:

| Уровень | Механизм | Описание |
| :--- | :--- | :--- |
| **Pre-admission** | `ValidatingPolicy` / `validate` | Блокировка некомплаентных ресурсов до создания в кластере. |
| **Post-admission** | `mutateExisting` / `generate` | Корректировка уже созданных ресурсов (добавление меток, аудит-информации). |
| **Background** | `CleanupPolicy` / `Report` | Непрерывный мониторинг и очистка устаревших ресурсов. |

### Стандарты compliance и их применимость к Kubernetes

| Стандарт | Ключевые требования к K8s | Механизм Kyverno |
| :--- | :--- | :--- |
| **CIS Benchmark** | Запрет привилегированных контейнеров, read-only rootfs, запрет hostNetwork/hostPID. | `ValidatingPolicy` (CEL) — проверка `securityContext`. |
| **NIS2** | Логирование действий администраторов, контроль доступа, управление инцидентами. | `generate` — автоматическое создание аудит-логов; `mutate` — инъекция меток. |
| **PCI DSS 4.0** | Шифрование TLS 1.3, сегментация сети, контроль доступа к данным. | `ValidatingPolicy` (CEL) — проверка аннотаций Ingress, `generate` — NetworkPolicy. |
| **SOC 2** | Мониторинг доступа, контроль изменений, аудит безопасности. | `PolicyReport` — сводные отчеты; `mutate` — инъекция меток аудита. |
| **GDPR** | Минимизация данных, право на удаление, контроль доступа к PII. | `CleanupPolicy` — автоудаление данных; `generate` — RBAC для доступа к PII. |

### Принцип Shift-Left и тестирование

Для предотвращения деградации кластера и сокращения цикла обратной связи используется **Kyverno CLI**. Он позволяет выполнять юнит-тестирование политик до их деплоя.

**Рекомендуемая структура тестов:**
```text
tests/
├── policy.yaml        # Тестируемая политика
├── resource.yaml      # Пример ресурса (Pod, Deployment)
└── kyverno-test.yaml  # Ожидаемый результат (pass/fail)
```

```bash
# Выполнение тестов в CI
kyverno test tests/
```

**Полная валидация пайплайна:**
```bash
# 1. Проверка синтаксиса политик
kyverno apply policies/ --resource=manifests/

# 2. Юнит-тесты
kyverno test tests/

# 3. Валидация конкретного манифеста
kyverno apply policies/ --resource=deployment.yaml --output-format yaml
```

---

## Практические сценарии

### 1. Интеграция в CI/CD пайплайн (Shift-Left)

Предотвращение попадания небезопасных манифестов в GitOps-репозиторий.

```yaml
# Пример GitHub Actions (v1.18+)
jobs:
  policy-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Kyverno CLI
        run: brew install kyverno
      - name: Validate Manifests
        run: kyverno apply policies/ --resource=manifests/
      - name: Unit Tests
        run: kyverno test tests/
```

**Пример kyverno-test.yaml для compliance-политики:**
```yaml
apiVersion: cli.kyverno.io/v1alpha1
kind: Test
metadata:
  name: test-cis-benchmark
policies:
  - ../cis-restrict-privileged.yaml
resources:
  - resource-privileged.yaml
  - resource-non-privileged.yaml
results:
  - policy: cis-restrict-privileged
    rules:
      - restrict-privileged
    resource: resource-privileged
    result: fail
  - policy: cis-restrict-privileged
    rules:
      - restrict-privileged
    resource: resource-non-privileged
    result: pass
```

### 2. Соответствие PCI DSS 4.0: Контроль шифрования

Требование по обеспечению защищенной передачи данных. Блокировка Ingress с устаревшими версиями TLS.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: pci-enforce-tls-1-3
spec:
  validations:
    - expression: |
        !has(object.metadata.annotations['ingress.kubernetes.io/ssl-min-ver']) ||
        object.metadata.annotations['ingress.kubernetes.io/ssl-min-ver'] == 'TLSv1.3'
      message: "Стандарт PCI DSS 4.0 требует использования TLS 1.3 для всех входящих соединений."
```

### 3. Инициализация Namespace (Multi-tenancy)

Автоматическое создание границ ресурсов для каждой новой команды. Полный набор: ResourceQuota + NetworkPolicy + LimitRange + Labels.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: team-resource-guard
spec:
  rules:
    # 1. ResourceQuota — ограничение ресурсов
    - name: create-default-quota
      match:
        any:
          - resources:
              kinds: [Namespace]
      generate:
        kind: ResourceQuota
        name: default-team-quota
        namespace: "{{request.object.metadata.name}}"
        synchronize: true
        data:
          spec:
            hard:
              cpu: "10"
              memory: 20Gi
              pods: "50"
              services: "10"
              persistentvolumeclaims: "5"
    # 2. NetworkPolicy — изоляция от других Namespace
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
        synchronize: true
        data:
          spec:
            podSelector: {}
            policyTypes: [Ingress]
    # 3. LimitRange — дефолтные лимиты на контейнеры
    - name: create-default-limit-range
      match:
        any:
          - resources:
              kinds: [Namespace]
      generate:
        apiVersion: v1
        kind: LimitRange
        name: default-limit-range
        namespace: "{{request.object.metadata.name}}"
        synchronize: true
        data:
          spec:
            limits:
              - type: Container
                default:
                  cpu: 500m
                  memory: 512Mi
                defaultRequest:
                  cpu: 100m
                  memory: 128Mi
              - type: Pod
                max:
                  cpu: "2"
                  memory: 4Gi
```

**Валидация:**
```bash
# Создание тестового Namespace
kubectl create namespace team-backend

# Проверка созданных ресурсов
kubectl get quota,netpol,limitrange -n team-backend
# → NAME                         CREATED AT
# → default-team-quota           2026-08-30T10:00:00Z
# → NAME                         POD-SELECTOR   POLICY-TYPES
# → default-deny-ingress         {}             [Ingress]
# → NAME                        CREATED AT
# → default-limit-range          2026-08-30T10:00:00Z

# Проверка что synchronize работает (обновление шаблона)
kubectl annotate clusterpolicy team-resource-guard \
  kyverno.io/force-sync=true --overwrite
```

### 4. Глобальная инъекция Proxy-настроек (Mutation)

Автоматическое добавление переменных окружения HTTP_PROXY во все поды, если они не указаны.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: inject-corporate-proxy
spec:
  rules:
    - name: add-proxy-env
      match:
        any:
          - resources:
              kinds: [Pod]
      mutate:
        foreach:
          - list: "request.object.spec.containers"
            patchStrategicMerge:
              env:
                - name: HTTP_PROXY
                  value: "http://proxy.corp.internal:8080"
```

### 5. CIS Benchmark: Запрет привилегированных контейнеров

Проверка `securityContext` на соответствие CIS Kubernetes Benchmark 5.2.5–5.2.13.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: cis-restrict-privileged
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
        !object.spec.containers.exists(c, c.securityContext.privileged == true) &&
        !object.spec.initContainers.exists(c, c.securityContext.privileged == true)
      message: "CIS 5.2.5: Привилегированные контейнеры запрещены."
    - expression: |
        object.spec.containers.all(c,
          has(c.securityContext) &&
          has(c.securityContext.runAsNonRoot) &&
          c.securityContext.runAsNonRoot == true
        )
      message: "CIS 5.2.6: Контейнеры должны работать от непривилегированного пользователя."
    - expression: |
        object.spec.containers.all(c,
          has(c.securityContext) &&
          has(c.securityContext.readOnlyRootFilesystem) &&
          c.securityContext.readOnlyRootFilesystem == true
        )
      message: "CIS 5.2.8: Root filesystem должен быть read-only."
    - expression: |
        !object.spec.containers.exists(c,
          has(c.securityContext) &&
          has(c.securityContext.capabilities) &&
          has(c.securityContext.capabilities.add) &&
          "SYS_ADMIN" in c.securityContext.capabilities.add
        )
      message: "CIS 5.2.10: Capability SYS_ADMIN запрещена."
```

**Валидация:**
```bash
# Тест: привилегированный Pod (должен быть заблокирован)
cat <<EOF | kubectl apply -f - 2>&1
apiVersion: v1
kind: Pod
metadata:
  name: test-privileged
spec:
  containers:
  - name: nginx
    image: nginx
    securityContext:
      privileged: true
EOF
# → Error from server: admission webhook ... denied the request ...
# → CIS 5.2.5: Привилегированные контейнеры запрещены.

# Тест: безопасный Pod (должен пройти)
cat <<EOF | kubectl apply -f - 2>&1
apiVersion: v1
kind: Pod
metadata:
  name: test-safe
spec:
  containers:
  - name: nginx
    image: nginx
    securityContext:
      runAsNonRoot: true
      readOnlyRootFilesystem: true
      allowPrivilegeEscalation: false
EOF
# → pod/test-safe created
```

### 6. NIS2: Аудит действий администраторов

Автоматическое создание записей аудита при изменении критических ресурсов (Secrets, ClusterRoleBinding).

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: nis2-audit-admin-actions
  annotations:
    compliance.kyverno.io/standard: "NIS2"
    compliance.kyverno.io/control: "Article 21"
spec:
  rules:
    # Логирование изменений Secrets
    - name: audit-secret-changes
      match:
        any:
          - resources:
              kinds: [Secret]
              operations: ["CREATE", "UPDATE", "DELETE"]
      generate:
        kind: ConfigMap
        name: "audit-secret-{{request.namespace}}-{{request.userName}}"
        namespace: kyverno-audit
        data:
          event: "{{request.operation}}"
          resource: "{{request.resource.name}}"
          namespace: "{{request.namespace}}"
          user: "{{request.userName}}"
          timestamp: "{{time_now_utc()}}"
          uid: "{{request.uid}}"
    # Логирование изменений ClusterRoleBinding
    - name: audit-clusterrolebinding-changes
      match:
        any:
          - resources:
              kinds: [ClusterRoleBinding]
              operations: ["CREATE", "UPDATE", "DELETE"]
      generate:
        kind: ConfigMap
        name: "audit-clusterrolebinding-{{request.userName}}-{{time_now_utc()}}"
        namespace: kyverno-audit
        data:
          event: "{{request.operation}}"
          resource: "{{request.resource.name}}"
          user: "{{request.userName}}"
          timestamp: "{{time_now_utc()}}"
          uid: "{{request.uid}}"
```

**Валидация:**
```bash
# Проверка что audit namespace существует
kubectl get namespace kyverno-audit

# Создание тестового Secret
kubectl create secret generic test-secret --from-literal=key=value -n default

# Проверка создания записи аудита
kubectl get configmaps -n kyverno-audit -l name=~"audit-secret-default-*"
```

### 7. SOC 2: Аудит через PolicyReport

Использование `PolicyReport` для формирования сводных отчетов по соответствию стандартам безопасности.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: soc2-security-monitoring
  annotations:
    compliance.kyverno.io/standard: "SOC 2"
    compliance.kyverno.io/control: "CC6.1"
spec:
  validationActions: [Audit, Enforce]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
    - expression: |
        object.spec.containers.all(c,
          has(c.resources) &&
          has(c.resources.limits) &&
          has(c.resources.limits.memory)
        )
      message: "SOC 2 CC6.1: Все контейнеры должны иметь лимиты на память."
    - expression: |
        object.spec.containers.all(c,
          has(c.resources) &&
          has(c.resources.limits) &&
          has(c.resources.limits.cpu)
        )
      message: "SOC 2 CC6.1: Все контейнеры должны иметь лимиты на CPU."
```

**Просмотр отчетов:**
```bash
# Просмотр PolicyReport для конкретного Namespace
kubectl get polr -n default -o json | \
  jq '.items[] | {name: .metadata.name, pass: .summary.pass, fail: .summary.fail, warn: .summary.warn}'

# Просмотр всех PolicyReport с ошибками
kubectl get polr -A -o json | \
  jq '.items[] | select(.summary.fail > 0) | {ns: .metadata.namespace, name: .metadata.name, failures: .summary.fail}'

# Детальный просмотр ошибок
kubectl get polr -n default -o json | \
  jq '.items[].results[] | select(.result == "fail") | {policy: .policy, message: .message}'
```

---

## Локальное тестирование (Shift-Left)

### Тестирование compliance-политик через kyverno CLI

```bash
# Структура тестов для compliance
mkdir -p tests/compliance
cat > tests/compliance/kyverno-test.yaml <<EOF
apiVersion: cli.kyverno.io/v1alpha1
kind: Test
metadata:
  name: test-compliance-policies
policies:
  - ../../cis-restrict-privileged.yaml
  - ../../pci-enforce-tls.yaml
resources:
  - privileged-pod.yaml
  - safe-pod.yaml
  - ingress-tls12.yaml
  - ingress-tls13.yaml
results:
  # CIS: привилегированный Pod должен быть заблокирован
  - policy: cis-restrict-privileged
    rules:
      - cis-restrict-privileged
    resource: privileged-pod
    result: fail
  # CIS: безопасный Pod должен пройти
  - policy: cis-restrict-privileged
    rules:
      - cis-restrict-privileged
    resource: safe-pod
    result: pass
  # PCI: TLS 1.2 должен быть заблокирован
  - policy: pci-enforce-tls
    rules:
      - pci-enforce-tls
    resource: ingress-tls12
    result: fail
  # PCI: TLS 1.3 должен пройти
  - policy: pci-enforce-tls
    rules:
      - pci-enforce-tls
    resource: ingress-tls13
    result: pass
EOF

# Запуск тестов
kyverno test tests/compliance/
# → Executing 1 test(s) ...
# → Test Suite Passed
```

### Валидация манифестов перед деплоем

```bash
# Проверка всех политик на конкретном манифесте
kyverno apply policies/ --resource=deployment.yaml --output-format yaml

# Проверка с генерацией отчета
kyverno apply policies/ --resource=manifests/ --output-format json > report.json

# Проверка конкретного Namespace
kyverno apply policies/ --resource=manifests/ --namespace=production
```

---

## Управление исключениями (PolicyException)

Для работы с compliance-политиками могут потребоваться точечные исключения.

### Когда использовать

- Системные Namespace (`kube-system`, `kube-public`) содержат ресурсы, которые не должны проверяться.
- Временные отладочные Pod'ы в dev без полного `securityContext`.
- Критические поды, требующие привилегированного доступа (monitors, agents).

### Пример PolicyException для CIS Benchmark

```yaml
apiVersion: kyverno.io/v2
kind: PolicyException
metadata:
  name: exception-cis-monitoring
  namespace: monitoring
spec:
  exceptions:
    - policyName: cis-restrict-privileged
      ruleNames:
        - cis-restrict-privileged
  match:
    any:
      - resources:
          namespaces:
            - monitoring
          kinds:
            - Pod
```

### Пример PolicyException для NIS2 аудита

```yaml
apiVersion: kyverno.io/v2
kind: PolicyException
metadata:
  name: exception-nis2-system-secrets
  namespace: kube-system
spec:
  exceptions:
    - policyName: nis2-audit-admin-actions
      ruleNames:
        - audit-secret-changes
  match:
    any:
      - resources:
          namespaces:
            - kube-system
          kinds:
            - Secret
```

---

## Типичные ошибки и диагностика

### Ошибки мутации

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `patchStrategicMerge` не применяется | Используется для CRD (нет нативного стратегического мержа). | Перейдите на `patchJSON6902` или `rawPatch`. |
| Мутация не применяется к существующим ресурсам | Используется `mutate` без блока `targets`. | Для `mutateExisting` добавьте блок `targets` с указанием целевого ресурса. |
| Foreach не итерирует контейнеры | Неверный путь в `list`. | Используйте `request.object.spec.containers` (без кавычек). |
| Infinite loop мутации | Политика мутирует сама себя. | Добавьте `exclude` для namespace `kyverno`. |

### Ошибки генерации

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Ресурс не создается | Namespace не существует. | Убедитесь, что Namespace создан до применения политики. |
| UpdateRequest в ошибке | Недостаточно прав RBAC у `background-controller`. | Проверьте ClusterRole `kyverno-bg-controller`. |
| Synchronize не работает | `synchronize: false` или не установлен. | Установите `synchronize: true` в блоке `generate`. |
| Клон не работает | Этальный ресурс не найден. | Проверьте `namespace` и `name` в блоке `clone`. |

### Ошибки CEL-валидации

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `expression` парсится с ошибкой | Невалидный синтаксис CEL. | Проверьте выражение на [cel-playground.appspot.com](https://cel-playground.appspot.com). |
| Все Pod'ы блокируются | Условие слишком широкое. | Сузьте `matchConstraints` (добавьте `namespaceSelector`). |
| `has()` не работает | Используется для отсутствующего поля. | Проверьте структуру объекта: `has(object.spec.containers)`. |

### Диагностика

```bash
# Просмотр состояния всех политик
kubectl get clusterpolicy,validatingpolicy,mutatingpolicy -o wide

# Просмотр PolicyReport для анализа ошибок
kubectl get polr -A -o json | \
  jq '.items[] | select(.summary.fail > 0) | {name: .metadata.name, failures: .summary.fail}'

# Просмотр логов admission-controller
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno -c admission-controller --tail=100

# Просмотр UpdateRequests (для generate/mutateExisting)
kubectl get updaterequests -n kyverno -o wide

# Просмотр логов background-controller (для generate)
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno-background-controller --tail=100
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Обслуживание UpdateRequests**: Регулярно мониторьте ресурсы UR в пространстве имен `kyverno`. Большое количество ошибок в UR может указывать на недостаток прав RBAC у `background-controller` ([подробнее в additional.md](../additional.md)).
2.  **Синхронизация (Synchronize)**: Всегда устанавливайте `synchronize: true` для правил `generate`, чтобы изменения в шаблоне политики (например, обновление CA-сертификата в клонируемом секрете) моментально отразились во всех Namespace.
3.  **Тэгирование политик**: Используйте аннотации для связи политик с пунктами стандартов. Это упрощает формирование отчетов для аудиторов.
    ```yaml
    annotations:
      compliance.kyverno.io/standard: "NIS2"
      compliance.kyverno.io/control: "Article 21"
    ```
4.  **Оптимизация CEL**: Для массовых проверок в CI/CD используйте `ValidatingPolicy` (CEL), так как они потребляют на 30% меньше ресурсов при выполнении тестов.
5.  **Раздельные политики для окружений**: Используйте `Enforce` для production и `Audit` для staging/develop. Это позволяет обнаруживать ошибки без остановки деплоя.
6.  **Audit logging**: Настройте `validationActions: [Audit, Enforce]` для критических политик. Это позволяет видеть все нарушения в `PolicyReport` даже если они заблокированы.

### Типичные ошибки при внедрении

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Compliance-политика блокирует системные Pod'ы | Namespace не исключен из `match`. | Добавьте `kube-system`, `kube-public`, `kyverno` в исключения. |
| Generate не создает ресурсы в новых Namespace | Namespace еще не создан к моменту применения политики. | Используйте `match` на `Namespace` с `generate`. |
| PolicyReport пустой | Политики не привязаны к `validationActions`. | Добавьте `Audit` в `validationActions`. |
| Synchronize не обновляет ресурсы | `background-controller` не имеет прав на изменение. | Проверьте ClusterRole `kyverno-bg-controller`. |

### См. также

- **[Типы правил (SSoT)](../rules.md)** — глубокий разбор match, validate, generate, clone.
- **[Библиотека практических примеров](../policies/practical_scenarios.md)** — готовые YAML для копирования.
- **[Агрегированные роли](../additional.md)** — права контроллеров на генерацию.
- **[Отчеты и AdmissionReports](../reports.md)** — визуализация результатов комплаенса.
