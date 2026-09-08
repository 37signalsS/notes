# Сценарии безопасности Kyverno

## Определения

**Сценарии безопасности** — практические руководства по реализации защитных механизмов кластера Kubernetes с использованием декларативных политик Kyverno. Сценарии охватывают превентивную блокировку угроз, автоматическое исправление конфигураций и непрерывный аудит на соответствие стандартам (PSS, CIS Benchmark).

В современной инфраструктуре (2025–2026) сценарии безопасности базируются на **CEL (Common Expression Language)** и интеграции с **Sigstore**, что обеспечивает нативную производительность и защиту на всех этапах жизненного цикла артефактов.

---

## Основные концепции

### Эшелонированная защита (Defense in Depth)

Применение Kyverno в контуре безопасности строится по принципу многоуровневого контроля:

| Уровень | Техническая реализация | Цель |
| :--- | :--- | :--- |
| **Admission Control** | `ValidatingPolicy` (CEL) | Блокировка небезопасных ресурсов до их попадания в API-сервер. |
| **Supply Chain** | `ImageValidatingPolicy` | Проверка подлинности образов, аттестаций SLSA и SBOM. |
| **Hardening** | `MutatingPolicy` | Автоматическая инъекция `securityContext` и меток безопасности. |
| **Post-deployment** | `Background Scan` | Выявление дрейфа конфигураций и нарушений в уже запущенных объектах. |

### Соответствие профилей PSS и меткам PSA

Pod Security Standards (PSS) определяют три уровня строгости. Kyverno позволяет реализовать каждый из них через CEL-политики:

| Уровень PSS | Ограничения | Метка PSA | Рекомендуемый подход Kyverno |
| :--- | :--- | :--- | :--- |
| **Privileged** | Без ограничений (только по умолчанию). | `enforce: privileged` | `audit` — мониторинг без блокировки. |
| **Baseline** | Запрет привилегированных контейнеров, hostPath, hostNetwork/hostPID/hostIPC, небезопасных портов. | `enforce: baseline` | `ValidatingPolicy` (CEL) для точечных проверок. |
| **Restricted** | Дополнительно: запрет root, требование seccomp/RuntimeDefault, drop ALL capabilities. | `enforce: restricted` | `ValidatingPolicy` (CEL) + `MutatingPolicy` для инъекции securityContext. |

**Примечание**: PSA работает через labels на Namespace (`pod-security.kubernetes.io/enforce: restricted`). Kyverno дополняет PSA возможностью:
- Исключений на уровне отдельных подов через `PolicyException` (PSA не поддерживает это).
- Автоматического исправления (mutation) ресурсов (PSA умеет только блокировать).
- Детализированных отчетов `PolicyReport` для аудита.

### Рекомендации по выбору версии API

Для каждого типа сценария рекомендуется определенная версия API:

| Сценарий | Рекомендуемый API | Причина |
| :--- | :--- | :--- |
| Валидация (все уровни PSS) | `ValidatingPolicy` (v2) | Нативная интеграция с VAP, задержка <1 мс. |
| Мутация securityContext | `MutatingPolicy` (v2) через `ApplyConfiguration` | Типизированные конфигурации, без JMESPath-шаблонов. |
| Мутация через patchStrategicMerge | `ClusterPolicy` (v1) | CEL не поддерживает `patchStrategicMerge` нативно. |
| Верификация образов | `ImageValidatingPolicy` (v2) | Keyless-поддержка, кэширование, интеграция с Sigstore. |
| Генерация политик (NetworkPolicy) | `ClusterPolicy` (v1) с `generate` | `GeneratingPolicy` (v2) ещё не GA. |

---

## Практические сценарии

### 1. Реализация профиля PSS Restricted (CEL)

**Проблема**: Стандартный PSA Restricted может быть слишком жестким или недостаточно гибким для специфических приложений.

**Решение**: Использование `ValidatingPolicy` для точечной проверки параметров Restricted-профиля с высокой производительностью.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: pss-restricted-hardening
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
          has(c.securityContext) && 
          c.securityContext.allowPrivilegeEscalation == false &&
          c.securityContext.runAsNonRoot == true &&
          c.securityContext.capabilities.drop.contains("ALL")
        )
      message: "Нарушение стандартов PSS Restricted: проверьте привилегии и capabilities."
```

**Валидация:**
```bash
# Проверка наличия подов с привилегиями
kubectl get pods -A -o json | \
  jq -r '.items[] | select(.spec.containers[]?.securityContext.runAsNonRoot != true) | .metadata.name'

# Проверка через kyverno CLI
kyverno test ./test-policies/ --policy pss-restricted-hardening
```

### 2. Верификация аттестаций SBOM и SLSA

**Проблема**: Факт подписи образа не гарантирует отсутствие уязвимостей или соответствие процесса сборки стандартам безопасности.

**Решение**: Проверка аттестаций (доказательств), прикрепленных к образу в реестре.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-supply-chain-attestations
spec:
  rules:
    - name: check-sbom-presence
      imageReferences: ["ghcr.io/my-company/*"]
      attestations:
        - name: verify-cyclonedx
          type: "https://cyclonedx.org/bom"
          attestors:
            - entries:
                - keys:
                    publicKeys: "MFkwEwYHKo..."
# Политика заблокирует образ, если к нему не приложен подписанный SBOM.
```

**Валидация:**
```bash
# Просмотр аттестаций образа через cosign
cosign verify-attestation --type cyclonedx \
  --key cosign.pub ghcr.io/my-company/app:latest

# Проверка наличия SBOM через kyverno CLI
kyverno image verify ghcr.io/my-company/app:latest \
  --policy verify-supply-chain-attestations
```

### 3. Сетевое закаливание (Network Hardening)

**Проблема**: Использование небезопасных портов (например, 22/SSH, 23/Telnet, 3389/RDP) внутри контейнеров увеличивает риск горизонтального перемещения злоумышленника.

**Решение**: Валидация портов контейнеров через CEL-фильтры.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: disallow-unsafe-ports
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
          !has(c.ports) || c.ports.all(p, 
            p.containerPort != 22 && 
            p.containerPort != 23 && 
            p.containerPort != 3389
          )
        )
      message: "Использование портов SSH (22), Telnet (23) и RDP (3389) внутри подов запрещено."
```

#### Дополнительные ограничения для сетевой безопасности

Помимо портов,络加固ома включает:

| Ограничение | Цель | CEL-выражение |
| :--- | :--- | :--- |
| Запрет hostNetwork | Предотвращение доступа к сетевому пространству хоста. | `!has(object.spec.hostNetwork) \|\| object.spec.hostNetwork == false` |
| Запрет hostPID | Предотвращение доступа к процессам хоста. | `!has(object.spec.hostPID) \|\| object.spec.hostPID == false` |
| Запрет hostIPC | Предотвращение доступа к IPC-сегментам хоста. | `!has(object.spec.hostIPC) \|\| object.spec.hostIPC == false` |
| Запрет capabilities (NET_RAW) | Предотвращение спуфинга и ARP-атак. | `!has(c.securityContext.capabilities.add) \|\| !c.securityContext.capabilities.add.exists(e, e == "NET_RAW")` |

### 4. Автоматическая инъекция Security Context (Mutation)

**Проблема**: Ошибки конфигурации в манифестах разработчиков приводят к отказам в Admission Control.

**Решение**: Автоматическое приведение подов к безопасному виду без участия человека.

#### Вариант A: v1 (ClusterPolicy с patchStrategicMerge)

Используйте, когда мутация требует `patchStrategicMerge` или `patchJSON6902` (CEL не поддерживает их нативно):

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: auto-inject-hardening
spec:
  rules:
    - name: inject-root-prevention
      match:
        any:
          - resources:
              kinds: [Pod]
              exclude:
                resources:
                  namespaces:
                    - kube-system
                    - kube-public
                    - kyverno
      mutate:
        patchStrategicMerge:
          spec:
            securityContext:
              runAsNonRoot: true
              seccompProfile:
                type: RuntimeDefault
```

#### Вариант B: v2 (MutatingPolicy с ApplyConfiguration)

Используйте для типизированных мутаций через CEL. Преимущество: нет依赖性 от JMESPath, задержка ниже:

```yaml
apiVersion: policies.kyverno.io/v1
kind: MutatingPolicy
metadata:
  name: auto-inject-hardening-v2
spec:
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  applyConfiguration:
    expression: |
      Object{
        spec: Object{
          securityContext: Object{
            runAsNonRoot: true,
            seccompProfile: Object{
              type: "RuntimeDefault"
            }
          }
        }
      }
```

**Валидация:**
```bash
# Проверка наличия securityContext у подов
kubectl get pods -A -o json | \
  jq -r '.items[] | select(.spec.containers[]?.securityContext.runAsNonRoot != true) | .metadata.name'
```

### 5. Верификация подписей образов (Image Verification)

**Проблема**: Неавторизованные образы могут содержать вредоносный код, уязвимости или не соответствовать политикам сборки.

**Решение**: Блокировка запуска образов, которые не прошли верификацию через Sigstore/Cosign.

#### Вариант A: Статический публичный ключ

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-image-signature
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  imageRules:
    - globPatterns: ["ghcr.io/my-org/*"]
  attestors:
    - name: trusted-registry
      entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
              -----END PUBLIC KEY-----
```

#### Вариант B: Keyless-верификация через OIDC (GitHub Actions)

Для CI/CD-пайплайнов, где ключи не хранятся статически:

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-keyless-ghactions
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  imageRules:
    - globPatterns: ["ghcr.io/my-org/*"]
  attestors:
    - name: github-actions
      entries:
        - keyless:
            url: https://fulcio.sigstore.dev
            identities:
              - issuer: https://token.actions.githubusercontent.com
                subject: https://github.com/my-org/my-repo/.github/workflows/build.yml@refs/heads/main
```

**Валидация:**
```bash
# Проверка подписи через cosign
cosign verify --key cosign.pub ghcr.io/my-org/app:latest

# Просмотр ошибок верификации в PolicyReport
kubectl get polr -A -o json | \
  jq '.items[] | select(.results[]?.result == "fail") | .metadata.name'
```

### 6. Запрет привилегированных контейнеров (PSS Baseline)

**Проблема**: Привилегированные контейнеры имеют полный доступ к ресурсам хоста, что делает их критическим вектором атаки.

**Решение**: Валидация через CEL для блокировки привилегированных контейнеров на уровне Pod.

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
      message: "Привилегированные контейнеры запрещены стандартами безопасности (PSS Baseline)."
```

**Валидация:**
```bash
# Проверка отсутствия привилегированных подов
kubectl get pods -A -o json | \
  jq -r '.items[] | select(.spec.containers[]?.securityContext.privileged == true) | .metadata.name'
```

---

## Локальное тестирование (Shift-Left)

Перед применением политик в кластере рекомендуется локальное тестирование через `kyverno CLI`.

### Структура теста

```
test-policies/
  kyverno-test.yaml      # Конфигурация теста
  resource-pod.yaml      # Тестовый под
  policy.yaml            # Политика для тестирования
```

### Пример теста (kyverno-test.yaml)

```yaml
apiVersion: cli.kyverno.io/v1alpha1
kind: Test
metadata:
  name: test-pss-restricted
policies:
  - ../policies/pss-restricted-hardening.yaml
resources:
  - resource-pod-bad.yaml   # Должен быть отклонен
  - resource-pod-good.yaml  # Должен пройти
results:
  - policy: pss-restricted-hardening
    rules:
      - pss-restricted-hardening
    resource: pod-bad
    result: fail
  - policy: pss-restricted-hardening
    rules:
      - pss-restricted-hardening
    resource: pod-good
    result: pass
```

### Запуск теста

```bash
# Тестирование конкретной политики
kyverno test ./test-policies/

# Тестирование с выводом详细ной информации
kyverno test ./test-policies/ -v 4

# Тестирование в dry-run режиме (без подключения к кластеру)
kyverno apply ./policies/ --resource ./resources/ --dry-run
```

---

## Управление исключениями (PolicyException)

В реальной инфраструктуре невозможно обойтись без исключений. Kyverno предоставляет ресурс `PolicyException` для точечного разрешения нарушений политик.

### Когда использовать PolicyException

- Унаследованные приложения, которые невозможно изменить в短时间内.
- Системные компоненты (monitoring agents, logging sidecars), требующие привилегий.
- Временные разрешения для отладки или миграции.

### Пример PolicyException

```yaml
apiVersion: kyverno.io/v2
kind: PolicyException
metadata:
  name: legacy-app-exception
  namespace: legacy-apps
spec:
  exceptions:
    - policyName: disallow-privileged-containers
      ruleNames:
        - disallow-privileged-containers
  match:
    any:
      - resources:
          namespaces:
            - legacy-apps
          kinds:
            - Pod
```

**Важно**: `PolicyException` должен быть создан в том же Namespace, что и целевые ресурсы. Исключения требуют одобрения администратора платформы (через RBAC или GitOps-процесс).

---

## Типичные ошибки и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Политика не блокирует привилегированные контейнеры | `operations` не включает `UPDATE`. | Добавьте `operations: ["CREATE", "UPDATE"]` в `resourceRules`. |
| Валидация падает с ошибкой компиляции | Неверный синтаксис CEL (например, отсутствие `orValue`). | Проверьте Optional-поля через `.?fieldName.orValue([])`. |
| Security Context не инжектируется | Используется v1 `ClusterPolicy` с `mutate`, но нет `patchStrategicMerge`. | Проверьте наличие блока `mutate.patchStrategicMerge` или перейдите на v2 `MutatingPolicy`. |
| `PolicyException` не действует | Имя политики или правила не совпадает с манифестом. | Проверьте `policyName` и `ruleNames` в `PolicyException`. |
| Верификация образов блокирует все поды | `imageRules.globPatterns` слишком широкий. | Сузьте паттерн до конкретного реестра (`ghcr.io/my-org/*`). |
| Высокая задержка Admission Control | Используется v1 `ClusterPolicy` вместо v2 `ValidatingPolicy`. | Мигрируйте на `ValidatingPolicy` для снижения задержки. |
| Киберлокировка (Deadlock) при запуске | Политика блокирует поды в `kube-system` или `kyverno`. | Добавьте `exclude.resources.namespaces: [kube-system, kube-public, kyverno]`. |

### Диагностика

```bash
# Просмотр PolicyReport для конкретного Namespace
kubectl get polr -n <namespace> -o yaml

# Просмотр ошибок Admission-контроллера
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno -c admission-controller --tail=100

# Проверка состояния политик
kubectl get clusterpolicy,validatingpolicy,mutatingpolicy -o wide

# Просмотр UpdateRequests (для generate/mutate)
kubectl get updaterequests -n kyverno
```

---

## Типичные ошибки при внедрении сценариев

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Разработчики обходят политики через `kubectl apply --server-side` | Клиентская валидация отключена. | Используйте `validationActions: [Deny]` вместо `Audit` для критичных политик. |
| Политика применяется к системным подам | Namespace не исключен. | Добавьте `kube-system`, `kube-public`, `kyverno` в `exclude`. |
| Генерация NetworkPolicy не работает | `synchronize: false` или нет триггера. | Установите `synchronize: true` и проверьте `updaterequests`. |
| Верификация SBOM блокирует все образы | Аттестация не прикреплена к образу. | Убедитесь, что CI/CD пайплайн подписывает SBOM перед деплоем. |
| Высокая задержка API | Используется v1 вместо v2. | Мигрируйте на `ValidatingPolicy` (v2). |

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Стратегия Audit-First**: Любой новый сценарий должен внедряться в режиме `validationFailureAction: Audit`. Это позволяет оценить влияние на существующую нагрузку без риска остановки сервисов.
2.  **Shift-Left**: Интегрируйте `kyverno CLI` в CI-пайплайны для раннего обнаружения нарушений. Это снижает «шум» в Admission-контроллере.
3.  **Управление исключениями**: Для временных допусков используйте ресурс `PolicyException`. Никогда не редактируйте основную политику для решения локальных проблем одной команды.
4.  **Безопасность системных Namespace**: Всегда добавляйте `kube-system`, `kube-public` и `kyverno` в `exclude` правил мутации и валидации, чтобы предотвратить циклические блокировки (Deadlocks).
5.  **Мониторинг дрейфа**: Используйте [Policy Reporter](../reporter.md) для анализа результатов фонового сканирования. Обычные ошибки в существующих ресурсах не должны игнорироваться.
6.  **Версионирование**: Планируйте миграцию с v1 (`ClusterPolicy`) на v2 (`ValidatingPolicy`, `MutatingPolicy`) — `ClusterPolicy` deprecated (удаление в v1.20).

### См. также

- **[Типы правил: глубокое погружение](../rules.md)** — синтаксис validate, mutate, verifyImages.
- **[Библиотека практических примеров](../policies/practical_scenarios.md)** — расширенный набор YAML для копирования.
- **[Система отчетов Policy Reports](../reports.md)** — как работать с результатами проверок.
- **[Security Context в Kubernetes](../../pod_security_context.md)** — описание параметров безопасности.
- **[Стратегия внедрения сценариев](./index.md)** — поэтапный процесс (Audit → Analyze → Enforce).
- **[Определения и концепции Kyverno](../policies/definitions_and_concepts.md)** — глубокое погружение в архитектуру политик.
