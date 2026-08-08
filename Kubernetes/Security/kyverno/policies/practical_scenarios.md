# Библиотека политик Kyverno: Практические примеры

## Определения

**Библиотека политик** — структурированная коллекция проверенных манифестов Kyverno, предназначенная для быстрого внедрения стандартов безопасности и автоматизации в кластер Kubernetes.

**ValidatingPolicy / MutatingPolicy** — специализированные ресурсы (v1.14+), оптимизированные для выполнения CEL-выражений (Common Expression Language). Они обеспечивают нативную интеграцию с Kubernetes API и работают значительно быстрее классических `ClusterPolicy`.

---

## Основные концепции

Библиотека построена на принципах **Pod Security Standards (PSS)** и **Supply Chain Security**. Все примеры соответствуют стандартам 2026 года и ориентированы на использование CEL-first подхода.

| Категория | Цель | Основные инструменты |
| :--- | :--- | :--- |
| **Prevention** | Блокировка небезопасных ресурсов. | `ValidatingPolicy` (CEL). |
| **Correction** | Автоматическое исправление манифестов. | `MutatingPolicy`, `patchStrategicMerge`. |
| **Automation** | Генерация зависимых объектов. | `generate`, `clone`. |
| **Verification** | Проверка целостности артефактов. | `verifyImages`, Sigstore. |

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

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Shift-Left Security**: Используйте `kyverno CLI` для проверки манифестов в CI пайплайнах. Это позволяет исправить нарушения до того, как они попадут в Admission-контроллер.
2.  **Режим Audit для новых правил**: Всегда внедряйте политики сначала в режиме `Audit`. Проверьте результаты через **[Policy Reports](../reports.md)**, чтобы убедиться в отсутствии ложноположительных срабатываний.
3.  **Исключения (PolicyException)**: Используйте ресурс `PolicyException` для временных разрешений (например, для специфического legacy-приложения), не ослабляя общую политику кластера.
4.  **Безопасность системных Namespace**: Всегда добавляйте исключения (`exclude`) для `kube-system` и `kyverno`, чтобы предотвратить «мертвую петлю», когда контроллер блокирует сам себя.

### См. также

- **[Типы правил (подробный синтаксис)](../rules.md)** — глубокое погружение в validate, mutate, generate.
- **[Определения и структура](./definitions_and_concepts.md)** — база для написания манифестов.
- **[Интеграция с Argo CD](../argo-cd.md)** — GitOps и визуализация отчетов.
- **[Supply Chain Security: Обзор](../../../Security/Supply_Chain_Security/overview.md)** — теория защиты цепочки поставок.
