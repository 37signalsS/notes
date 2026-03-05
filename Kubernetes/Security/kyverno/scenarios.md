# Практические сценарии Kyverno

## Определения

**Практические сценарии** — реальные случаи использования Kyverno для обеспечения безопасности, автоматизации и соответствия стандартам в Kubernetes.

> **Основное руководство:** Этот файл описывает сценарии использования. Примеры политик — в [Написание политик](./policies.md).

---

## Basic Concepts

### Категории сценариев

| Категория | Описание | Примеры |
|-----------|----------|---------|
| **Безопасность** | Применение политик безопасности | Требование non-root, запрет hostPath |
| **Автоматизация** | Автоматическая настройка ресурсов | Добавление securityContext, imagePullSecrets |
| **Соответствие** | Compliance с внутренними/внешними стандартами | PCI DSS, GDPR, CIS Benchmark |
| **Генерация** | Создание ресурсов по шаблону | NetworkPolicy, Secret, ResourceQuota |
| **Очистка** | Удаление устаревших ресурсов | Старые Pod, незавершенные Jobs |

---

## Practical Scenarios

### 1. Применение политик безопасности в реальном времени

**Проблема**: Необходимо обеспечить применение политик безопасности ко всем ресурсам в кластере.

**Решение**: Kyverno применяет политики через Admission Controller во время деплоя.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-security-context
spec:
  validationFailureAction: Enforce
  rules:
    - name: require-run-as-non-root
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Container must run as non-root"
        pattern:
          spec:
            securityContext:
              runAsNonRoot: true
```

**Сравнение с другими инструментами**:
- **[kubesec](../kubesec.md)** — статический анализ YAML до деплоя
- **Kyverno** — валидация и мутация во время деплоя
- **[Falco](../../../Security/Tools/falco.md)** — runtime-мониторинг после деплоя

### 2. Автоматизация соответствия стандартам

**Проблема**: Требуется непрерывное соблюдение стандартов (PCI DSS, GDPR, CIS).

**Решение**: Политики Kyverno с категориями и severity.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: pci-dss-compliance
  annotations:
    policies.kyverno.io/category: PCI-DSS
    policies.kyverno.io/severity: high
spec:
  validationFailureAction: Enforce
  rules:
    - name: encrypt-data-at-rest
      match:
        resources:
          kinds:
            - PersistentVolumeClaim
      validate:
        message: "PVC must use encrypted storage class"
        pattern:
          spec:
            storageClassName: "*-encrypted"
```

### 3. Внедрение лучших практик

**Проблема**: Разработчики забывают добавлять securityContext к подам.

**Решение**: Мутация ресурсов для автоматического добавления настроек.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-security-context
spec:
  rules:
    - name: add-default-securitycontext
      match:
        resources:
          kinds:
            - Pod
      mutate:
        patchStrategicMerge:
          spec:
            securityContext:
              runAsNonRoot: true
              runAsUser: 1000
              fsGroup: 1000
```

### 4. Инфраструктура как код и политики как код

**Проблема**: Политики безопасности должны версионироваться и тестироваться.

**Решение**: Политики Kyverno в Git-репозитории с CI/CD.

```
git-repo/
├── policies/
│   ├── require-run-as-non-root.yaml
│   ├── deny-host-path.yaml
│   └── require-resource-limits.yaml
├── tests/
│   └── policy-tests.yaml
└── .github/workflows/
    └── validate-policies.yaml
```

**CI/CD пайплайн**:
```yaml
# .github/workflows/validate-policies.yaml
name: Validate Kyverno Policies
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install Kyverno CLI
        run: |
          curl -LO https://github.com/kyverno/kyverno/releases/download/v1.11.0/kyverno-cli_v1.11.0_linux_x86_64.tar.gz
          tar -xzf kyverno-cli_v1.11.0_linux_x86_64.tar.gz
          chmod +x kyverno
          sudo mv kyverno /usr/local/bin/
      - name: Validate policies
        run: kyverno apply policies/ --resource=tests/
```

### 5. Управление сетевыми политиками

**Проблема**: Необходимо автоматически изолировать приложения в разных namespace.

**Решение**: Генерация NetworkPolicy при создании namespace.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: generate-network-policy
spec:
  rules:
    - name: generate-default-deny-ingress
      match:
        resources:
          kinds:
            - Namespace
      generate:
        kind: NetworkPolicy
        name: default-deny-ingress
        namespace: "{{request.object.metadata.name}}"
        synchronize: true
        data:
          spec:
            podSelector: {}
            policyTypes:
              - Ingress
```

**Связанные темы**: [NetworkPolicy](../network_policies.md)

### 6. Управление секретами Docker Registry

**Проблема**: При создании namespace необходимо копировать Secret с credentials для доступа к приватному Docker Registry.

**Решение**: Политика `generate` с параметром `clone`.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: copy-docker-registry-secret
spec:
  rules:
    - name: copy-secret
      match:
        resources:
          kinds:
            - Namespace
      generate:
        kind: Secret
        name: docker-registry-credentials
        namespace: "{{request.object.metadata.name}}"
        clone:
          namespace: template
          name: docker-registry-credentials
        synchronize: true
```

**Автоматическое добавление imagePullSecrets**:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-imagepullsecrets
spec:
  rules:
    - name: add-imagepullsecrets
      match:
        resources:
          kinds:
            - Pod
      mutate:
        patchStrategicMerge:
          spec:
            imagePullSecrets:
              - name: docker-registry-credentials
```

### 7. Очистка ресурсов (Pruning)

**Проблема**: Необходимо удалять старые завершенные Pod для экономии ресурсов.

**Решение**: Политика очистки по расписанию.

```yaml
apiVersion: kyverno.io/v2
kind: CleanupPolicy
metadata:
  name: cleanup-completed-pods
spec:
  match:
    any:
      - resources:
          kinds:
            - Pod
  conditions:
    any:
      - key: "{{ status.phase }}"
        operator: Equals
        value: Succeeded
  schedule: "0 */6 * * *"  # Каждые 6 часов
```

### 8. Проверка подписей образов

**Проблема**: Необходимо разрешать деплой только подписанных образов.

**Решение**: Политика `verifyImages` с Sigstore/Cosign.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  rules:
    - name: verify-cosign-signature
      match:
        resources:
          kinds:
            - Pod
      verifyImages:
        - imageReferences:
            - "registry.example.com/*"
          attestors:
            - count: 1
              entries:
                - keys:
                    - publicKeys: |
                        -----BEGIN PUBLIC KEY-----
                        MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
                        -----END PUBLIC KEY-----
```

**Связанные темы**: [Sigstore](../../../Security/Tools/sigstore.md), [Supply Chain Security](../../../Security/Supply_Chain_Security/artifact_signing.md)

---

## Additional Information

### Сравнение инструментов безопасности

| Инструмент | Когда работает | Назначение |
|------------|----------------|------------|
| **Kyverno** | Во время деплоя (Admission) | Применение политик к ресурсам | Этот файл |
| **[kubesec](../kubesec.md)** | До деплоя (статический анализ) | Проверка манифестов на уязвимости | kubesec.md |
| **[kube-bench](../kube-bench.md)** | Периодический аудит | Проверка конфигурации кластера на CIS Benchmark | kube-bench.md |
| **[Falco](../../../Security/Tools/falco.md)** | Runtime (после деплоя) | Мониторинг поведения приложений | falco.md |

### Рекомендации по внедрению

1. **Начать с аудита**: Включить `validationFailureAction: Audit` для сбора данных
2. **Отладка политик**: Использовать [Background Scan](./background.md) для тестирования
3. **Постепенное внедрение**: Переход на `Enforce` после проверки
4. **Мониторинг**: Настроить [Policy Reporter](./reporter.md) для отслеживания нарушений

### Связанные темы

- [Написание политик](./policies.md) — структура и примеры политик
- [Типы правил](./rules.md) — generate, mutate, validate, verifyImages
- [Установка](./install.md) — установка и настройка Kyverno
- [Отчеты](./reports.md) — мониторинг применения политик
