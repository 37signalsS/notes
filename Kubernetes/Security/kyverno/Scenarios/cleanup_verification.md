# Очистка ресурсов и верификация образов в Kyverno

## Определения

**Автоматическая очистка (Cleanup)** — асинхронный процесс удаления устаревших, завершенных или неиспользуемых объектов Kubernetes. Выполняется специализированным `cleanup-controller`, который отслеживает расписания (`CleanupPolicy`) и метки времени жизни (TTL).

**Update Request (UR)** — внутренний ресурс Kyverno, создаваемый контроллером для выполнения и отслеживания статуса фоновых задач, включая операции массовой очистки и генерации.

**Верификация образов (Image Verification)** — динамический контроль подлинности контейнерных образов в момент Admission-контроля. Включает проверку криптографических подписей, аттестаций (доказательств сборки) и соответствие содержимого SBOM (Software Bill of Materials) установленным стандартам.

---

## Основные концепции

### Механизмы управления жизненным циклом

На 2026 год Kyverno предлагает три уровня контроля за состоянием кластера:

| Механизм | Техническая реализация | Применение |
| :--- | :--- | :--- |
| **CleanupPolicy** | `ClusterCleanupPolicy` (v2) | Массовое удаление по расписанию (Cron) с использованием CEL-фильтров. |
| **Label-based TTL** | `cleanup.kyverno.io/ttl` | Индивидуальное самоудаление ресурсов (например, временных Namespace). |
| **Image Verification** | `ImageValidatingPolicy` | Проверка цепочки поставок (Supply Chain) через Sigstore/Cosign. |

### CleanupPolicy vs Label TTL: когда что использовать

| Критерий | `CleanupPolicy` (v2) | `cleanup.kyverno.io/ttl` |
| :--- | :--- | :--- |
| **Масштаб** | Массовое удаление по регулярному расписанию (Cron). | Индивидуальное удаление одного ресурса по прошествии времени. |
| **Гибкость фильтров** | CEL-условия (`conditions`) для точного отбора ресурсов. | Простая метка — удаляется всё с установленным TTL. |
| **Удаление Namespace** | Не поддерживается (Namespace требует kubectl). | Поддерживается — Namespace удалится со всем содержимым. |
| **Повторяемость** | Циклическое выполнение (например, ежедневно в 02:00). | Одноразовое — TTL срабатывает один раз. |
| **Диагностика** | `UpdateRequests` в `kyverno` namespace. | Логи cleanup-controller, `kubectl describe ns`. |
| **Зависимости** | Требует `cleanup-controller` (входит в standard-установку). | Нативный Kubernetes (netting控制器). |

### Lifecycle CleanupPolicy

`cleanup-controller` выполняет цикл reconciliation для каждого `ClusterCleanupPolicy`:

1. **Расписание (Schedule)**: Cron-выражение определяет, когда política запускается.
2. **Подбор ресурсов (Match)**: Блок `match.any/match.all` определяет целевые ресурсы по kinds, namespaces, selector.
3. **Фильтрация (Conditions)**: Блок `conditions.all/any` применяет CEL-выражения для进一步 фильтрации.
4. **Удаление (Delete)**: Подобранные ресурси удаляются стандартными механизмами Kubernetes (foreground/background deletion).

**Важно**: `CleanupPolicy` поддерживает только ресурсы, которые могут быть перечислены через API (list verb). Namespace не поддерживаются — используйте TTL или `kubectl delete namespace <name> --force`.

### Защита цепочки поставок (Supply Chain Security)

Современная архитектура верификации в Kyverno (v1.17+) базируется на стандартах **SLSA** и **OCI 1.1 Referrers API**:
1.  **Keyless Signing**: Проверка подписей на основе OIDC-идентификаторов (например, GitHub Actions Runner), что исключает риск компрометации долгоживущих приватных ключей.
2.  **Attestations & VSA**: Проверка аттестаций сканирования на уязвимости и **Vulnerability Scanning Attestations (VSA)**.
3.  **SBOM Validation**: Анализ состава образа (библиотеки, лицензии) через спецификации CycloneDX или SPDX, прикрепленные к образу как Referrers.

### Способы верификации образов: сравнение

| Способ | Механизм | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Static Key** | Файловый публичный ключ (`cosign.pub`). | Простота, не требует OIDC-провайдера. | Долгоживущий ключ — риск компрометации. |
| **Keyless (OIDC)** | Fulcio + Rekor (Short-lived certificate). | Автоматическая ротация, аудит в Rekor Transparency Log. | Зависимость от внешних сервисов (Fulcio, Rekor). |
| **KMS** | HSM/Cloud KMS (HashiCorp Vault, AWS KMS). | Централизованное управление ключами. | Дополнительная инфраструктура, задержка запросов. |

### Типы аттестаций

Kyverno поддерживает проверку следующих типов аттестаций:

| Тип | Стандарт | Назначение | Пример использования |
| :--- | :--- | :--- | :--- |
| **SBOM** | CycloneDX / SPDX | Состав ПО (библиотеки, лицензии, версии). | Блокировка образов с зависимостями, имеющими известные CVE. |
| **SLSA Provenance** | SLSA v1.2 | Доказательства сборки (кто, как, из чего собрал образ). | Аудит цепочки поставок, compliance (SOC 2, PCI DSS). |
| **Vulnerability** | Cosign Vuln Attestation | Результаты сканирования на уязвимости. | Блокировка образов с критическими CVE. |
| **VSA (Vulnerability Scanning Attestation)** | Kyverno-native | Комбинированная аттестация сканирования. | Единый формат для всех сканеров уязвимостей. |

---

## Практические сценарии

### 1. Автоматическая очистка временных сред (TTL)

Используется для управления жизненным циклом ресурсов в песочницах (Sandbox) без создания дополнительных политик.

```yaml
# Пример Namespace для Feature-ветки
apiVersion: v1
kind: Namespace
metadata:
  name: feat-ui-header-452
  labels:
    # Контроллер удалит NS ровно через 12 часов после создания
    cleanup.kyverno.io/ttl: "12h"
```

**Валидация:**
```bash
# Проверка наличия метки TTL
kubectl get ns feat-ui-header-452 -o jsonpath='{.metadata.labels.cleanup\.kyverno\.io/ttl}'
# → 12h

# Проверка оставшегося времени (приблизительно)
kubectl get ns feat-ui-header-452 -o json | \
  jq -r '.metadata.creationTimestamp as $created | .metadata.labels["cleanup.kyverno.io/ttl"] as $ttl | "Created: \($created), TTL: \($ttl)"'
```

### 2. Очистка «осиротевших» ресурсов (Orphaned Resources)

**Проблема**: После удаления `PVC` (PersistentVolumeClaim) в кластере могут оставаться неиспользуемые `PV` (PersistentVolume) в статусе `Released`, занимающие дисковое пространство.

**Решение**: Политика очистки неиспользуемых томов.

```yaml
apiVersion: kyverno.io/v2
kind: ClusterCleanupPolicy
metadata:
  name: cleanup-orphaned-pv
spec:
  schedule: "0 2 * * *" # Ежедневно в 02:00
  match:
    any:
      - resources:
          kinds: [PersistentVolume]
  conditions:
    all:
      - key: "{{ target.status.phase }}"
        operator: Equals
        value: "Released"
```

### 3. Очистка завершенных Job и Pod в CrashLoopBackOff

**Проблема**: Завершенные Job и поды в `Error`/`CrashLoopBackOff` засоряют namespace и затрудняют мониторинг.

**Решение**: Регулярная очистка завершенных/ошибочных ресурсов.

```yaml
apiVersion: kyverno.io/v2
kind: ClusterCleanupPolicy
metadata:
  name: cleanup-completed-jobs
spec:
  schedule: "*/30 * * * *" # Каждые 30 минут
  match:
    any:
      - resources:
          kinds: [Job]
  conditions:
    all:
      - key: "{{ target.status.succeeded }}"
        operator: GreaterThanOrEquals
        value: 1
---
apiVersion: kyverno.io/v2
kind: ClusterCleanupPolicy
metadata:
  name: cleanup-failed-pods
spec:
  schedule: "*/15 * * * *" # Каждые 15 минут
  match:
    any:
      - resources:
          kinds: [Pod]
          namespaces: [dev, staging]
  conditions:
    all:
      - key: "{{ target.status.phase }}"
        operator: Equals
        value: "Failed"
```

**Валидация:**
```bash
# Проверка количества завершенных Job в namespace
kubectl get jobs -n dev -o json | \
  jq '[.items[] | select(.status.succeeded >= 1)] | length'
# → 0 (после очистки)

# Просмотр логов cleanup-controller для отладки
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno-cleanup-controller --tail=50
```

### 4. Keyless-верификация через GitHub Actions

**Проблема**: Необходимо гарантировать, что в `production` попадают только образы, собранные в официальном репозитории организации.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-github-provenance
spec:
  rules:
    - name: check-keyless-signature
      imageReferences: ["ghcr.io/my-company/*"]
      attestors:
        - entries:
            - keyless:
                # Доверяем только GitHub Actions как эмитенту токена
                issuer: "https://token.actions.githubusercontent.com"
                # Проверяем конкретный репозиторий и ветку сборки
                subject: "https://github.com/my-org/core-api/.github/workflows/deploy.yaml@refs/heads/main"
```

**Валидация:**
```bash
# Проверка подписи через cosign
cosign verify \
  --certificate-identity "https://github.com/my-org/core-api/.github/workflows/deploy.yaml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/my-company/core-api:latest

# Просмотр ошибок верификации в PolicyReport
kubectl get polr -A -o json | \
  jq '.items[] | select(.results[]?.result == "fail") | {name: .metadata.name, failures: [.results[] | select(.result == "fail") | .message]}'
```

### 5. Multi-attestor верификация (SBOM + SLSA Provenance)

**Проблема**: Необходимо проверять не только подпись образа, но и состав ПО (SBOM), и процесс сборки (SLSA Provenance) одновременно.

**Решение**: Политика с несколькими блоками `attestations` в одном правиле.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-supply-chain-complete
spec:
  rules:
    - name: check-all-attestations
      imageReferences: ["ghcr.io/my-company/*"]
      attestors:
        - entries:
            - keyless:
                issuer: "https://token.actions.githubusercontent.com"
                subjectRegExp: "https://github.com/my-org/.*"
      attestations:
        # Проверка SBOM (CycloneDX)
        - name: verify-sbom
          type: "https://cyclonedx.org/bom"
          attestors:
            - entries:
                - keyless:
                    issuer: "https://token.actions.githubusercontent.com"
                    subjectRegExp: "https://github.com/my-org/.*"
        # Проверка SLSA Provenance
        - name: verify-provenance
          type: "https://slsa.dev/provenance/v1"
          attestors:
            - entries:
                - keyless:
                    issuer: "https://token.actions.githubusercontent.com"
                    subjectRegExp: "https://github.com/my-org/.*"
        # Проверка Vulnerability Attestation
        - name: verify-vuln
          type: "https://cosign.sigstore.dev/attestation/vuln/v1"
          attestors:
            - entries:
                - keyless:
                    issuer: "https://token.actions.githubusercontent.com"
                    subjectRegExp: "https://github.com/my-org/.*"
```

**Валидация:**
```bash
# Просмотр всех аттестаций образа
cosign verify-attestation --type cyclonedx ghcr.io/my-company/app:latest | jq '.payload' | base64 -d | jq
cosign verify-attestation --type slsaprovenance ghcr.io/my-company/app:latest | jq '.payload' | base64 -d | jq
cosign verify-attestation --type vuln ghcr.io/my-company/app:latest | jq '.payload' | base64 -d | jq

# Проверка через kyverno CLI
kyverno image verify ghcr.io/my-company/app:latest \
  --policy verify-supply-chain-complete
```

### 6. Обработка ошибок верификации (Audit vs Enforce)

**Проблема**: Режим `Enforce` блокирует деплой при ошибках верификации, но в staging/develop нужен `Audit` для анализа без остановки.

**Решение**: Две политики с разными `validationFailureAction` для разных окружений.

```yaml
# Production: блокировка при ошибках
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-images-enforce
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  imageRules:
    - globPatterns: ["ghcr.io/my-company/*"]
  attestors:
    - entries:
        - keyless:
            issuer: "https://token.actions.githubusercontent.com"
            subjectRegExp: "https://github.com/my-org/.*"
---
# Staging: только аудит (логирование без блокировки)
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-images-audit
  annotations:
    policies.kyverno.io/category: Supply Chain Security
    policies.kyverno.io/description: Аудит верификации в staging без блокировки деплоя.
spec:
  validationActions: [Audit]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
        namespaces: [staging, develop]
  imageRules:
    - globPatterns: ["ghcr.io/my-company/*"]
  attestors:
    - entries:
        - keyless:
            issuer: "https://token.actions.githubusercontent.com"
            subjectRegExp: "https://github.com/my-org/.*"
```

**Валидация:**
```bash
# Просмотр PolicyReport для staging (режим Audit)
kubectl get polr -n staging -o json | \
  jq '.items[] | select(.results[]?.result == "fail") | {name: .metadata.name, warnings: [.results[] | select(.result == "fail") | .message]}'

# Просмотр PolicyReport для production (режим Enforce)
kubectl get polr -n production -o json | \
  jq '.items[] | select(.results[]?.result == "fail") | {name: .metadata.name, failures: [.results[] | select(.result == "fail") | .message]}'
```

---

## Локальное тестирование (Shift-Left)

Перед применением политик в кластере рекомендуется локальное тестирование через `kyverno CLI`.

### Тестирование CleanupPolicy

```bash
# Структура теста
mkdir -p test-cleanup
cat > test-cleanup/kyverno-test.yaml <<EOF
apiVersion: cli.kyverno.io/v1alpha1
kind: Test
metadata:
  name: test-cleanup-completed-jobs
policies:
  - ../cleanup-completed-jobs.yaml
resources:
  - job-completed.yaml
  - job-running.yaml
results:
  - policy: cleanup-completed-jobs
    rules:
      - cleanup-completed-jobs
    resource: job-completed
    result: pass
  - policy: cleanup-completed-jobs
    rules:
      - cleanup-completed-jobs
    resource: job-running
    result: pass
EOF

# Запуск теста
kyverno test ./test-cleanup/
```

### Тестирование Image Verification

```bash
# Проверка верификации образа через CLI
kyverno image verify ghcr.io/my-company/app:latest \
  --policy verify-images.yaml \
  --kubeconfig ~/.kube/config

# Проверка конкретной аттестации
cosign verify-attestation --type cyclonedx \
  --key cosign.pub ghcr.io/my-company/app:latest

# Проверка keyless-подписи
cosign verify \
  --certificate-identity "https://github.com/my-org/repo/.github/workflows/build.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/my-company/app:latest
```

---

## Управление исключениями (PolicyException)

Для работы с `CleanupPolicy` и `ImageValidatingPolicy` могут потребоваться точечные исключения.

### Когда использовать

- Системные namespace (например, `kube-system`) содержат завершенные Job, которые не должны удаляться.
- Временные образы в development без аттестаций (но с включенным Audit).
- Критические поды, верификация которых требует extended таймаута.

### Пример PolicyException для CleanupPolicy

```yaml
apiVersion: kyverno.io/v2
kind: PolicyException
metadata:
  name: exception-cleanup-system-jobs
  namespace: kube-system
spec:
  exceptions:
    - policyName: cleanup-completed-jobs
      ruleNames:
        - cleanup-completed-jobs
  match:
    any:
      - resources:
          namespaces:
            - kube-system
          kinds:
            - Job
```

### Пример PolicyException для ImageValidatingPolicy

```yaml
apiVersion: kyverno.io/v2
kind: PolicyException
metadata:
  name: exception-verify-debug-images
  namespace: develop
spec:
  exceptions:
    - policyName: verify-images-enforce
      ruleNames:
        - check-keyless-signature
  match:
    any:
      - resources:
          namespaces:
            - develop
          kinds:
            - Pod
```

---

## Типичные ошибки и диагностика

### Ошибки CleanupPolicy

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| CleanupPolicy не удаляет ресурсы | `schedule` задан некорректно (невалидный Cron). | Проверьте синтаксис Cron через `crontab.guru`. |
| Ресурсы не подбираются `match` | Namespace не входит в `match.any[].resources.namespaces`. | Добавьте нужный namespace или уберите фильтр. |
| `conditions` не срабатывают | Используется неверный оператор (например, `Equals` вместо `Contains`). | Проверьте/operators: `Equals`, `NotEquals`, `Contains`, `GreaterThan`, `LessThan`. |
| Ошибка RBAC у cleanup-controller | Недостаточно прав на удаление ресурсов. | Проверьте ClusterRole `kyverno-cleanup-controller`. |
| Namespace не удаляется | `CleanupPolicy` не поддерживает Namespace. | Используйте TTL или `kubectl delete namespace`. |
| Удаление блокируется Finalizer | Ресурс имеет `finalizers`, блокирующие удаление. | Проверьте и удалите лишние finalizers. |

### Ошибки Image Verification

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Все образы блокируются | `imageReferences` не совпадает с реальным именем образа. | Проверьте glob-паттерн: `ghcr.io/my-org/*` vs `ghcr.io/my-org/app`. |
| Keyless-верификация падает | OIDC-issuer недоступен (Fulcio/Rekor). | Проверьте сетевую доступность `fulcio.sigstore.dev` и `rekor.sigstore.dev`. |
| Аттестация не найдена | Аттестация не прикреплена к образу через `cosign attach`. | Убедитесь, что CI/CD пайплайн выполняет `cosign attest`. |
| Таймаут верификации | Медленное подключение к OCI-реестру. | Увеличьте `timeoutSeconds` или настройте `image-verify-cache`. |
| `subject` не совпадает | OIDC subject изменился (например, изменился путь к workflow). | Обновите `subject`/`subjectRegExp` в политике. |

### Диагностика

```bash
# Просмотр состояния всех политик
kubectl get clusterpolicy,validatingpolicy,mutatingpolicy,clustercleanuppolicy -o wide

# Просмотр PolicyReport для анализа ошибок
kubectl get polr -A -o json | \
  jq '.items[] | select(.summary.fail > 0) | {name: .metadata.name, failures: .summary.fail}'

# Просмотр логов cleanup-controller
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno-cleanup-controller --tail=100

# Просмотр логов admission-controller (для верификации)
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno -c admission-controller --tail=100

# Просмотр UpdateRequests (для cleanup/generate)
kubectl get updaterequests -n kyverno -o wide

# Проверка доступности OCI-реестра
curl -s https://ghcr.io/v2/ | head -5
```

---

## Кэширование верификации

Для снижения нагрузки на OCI-реестры и Sigstore Kyverno поддерживает кэширование результатов верификации.

### Механизм работы

1. При первом запросе на верификацию образа результат сохраняется в кэше (in-memory + опционально Redis).
2. При повторном запросе для того же образа (тот же digest) результат берется из кэша.
3. Кэш инвалидируется при смене digest образа или истечении TTL.

### Конфигурация

```yaml
# В values.yaml при установке Kyverno через Helm
imageVerify:
  cache:
    enabled: true
    ttl: 10m  # Время жизни записи в кэше
    maxEntries: 1000  # Максимальное количество записей
```

**Рекомендация**: Всегда включайте кэширование для `ImageValidatingPolicy`. Это снижает количество внешних запросов к OCI-реестру и Rekor-серверу на ~90%.

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Обслуживание UpdateRequests**: Регулярно мониторьте ресурсы UR в пространстве имен `kyverno`. Большое количество ошибок в UR может указывать на недостаток прав RBAC у `cleanup-controller` ([подробнее в additional.md](../additional.md)).
2.  **Оптимизация кэша**: Для `ImageValidatingPolicy` всегда используйте `image-verify-cache`. Это снижает количество внешних запросов к OCI-реестру и Rekor-серверу Sigstore на 90%.
3.  **Foreground Deletion**: При настройке `CleanupPolicy` учитывайте, что Kyverno использует стандартные механизмы удаления K8s. Убедитесь, что `Finalizers` на ресурсах не блокируют процесс очистки.
4.  **Shift-Left**: Проверяйте наличие аттестаций SBOM еще на этапе CI через `kyverno CLI`, чтобы предотвратить блокировку деплоя в кластере.
5.  **Раздельные политики для окружений**: Используйте `Enforce` для production и `Audit` для staging/develop. Это позволяет обнаруживать ошибки без остановки деплоя.
6.  **Мониторинг PolicyReport**: Регулярно проверяйте `PolicyReport` для анализа ошибок верификации. Ошибки в `Audit`-режиме не блокируют деплой, но требуют внимания.

### Типичные ошибки при внедрении

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| CleanupPolicy удаляет критические ресурсы | Namespace не исключен из `match`. | Добавьте `kube-system`, `kube-public`, `kyverno` в исключения. |
| Верификация блокирует все образы | `imageReferences` слишком широкий. | Сузьте паттерн до конкретного реестра (`ghcr.io/my-org/*`). |
| Cleanup-controller падает в CrashLoopBackOff | Недостаток прав RBAC. | Проверьте ClusterRole `kyverno-cleanup-controller`. |
| Keyless-верификация не работает за NAT | Fulcio/Rekor недоступны. | Настройте прокси или увеличьте таймауты. |

### См. также

- **[Агрегированные роли и права контроллеров](../additional.md)** — настройка прав для удаления ресурсов.
- **[Отчеты и AdmissionReports](../reports.md)** — анализ результатов верификации образов.
- **[Подписание артефактов и Sigstore](../../../../Security/Supply_Chain_Security/artifact_signing.md)** — теория Keyless-подписи.
- **[Анализ SBOM в CI/CD](../../../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)** — генерация и аудит состава ПО.
