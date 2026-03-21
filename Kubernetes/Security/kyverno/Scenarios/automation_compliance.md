# Автоматизация и compliance в Kyverno

## Определения

**Автоматизация** — автоматическая настройка ресурсов Kubernetes через политики Kyverno.

**Compliance** — обеспечение соответствия внутренним и внешним стандартам (PCI DSS, GDPR, CIS Benchmark).

> **Навигация:** [Главная сценариев](./index.md) | [Безопасность](./security_policies.md) | [Очистка](./cleanup_verification.md)

---

## Basic Concepts

### Механизмы автоматизации

| Механизм | Описание | Пример |
|----------|----------|--------|
| **Mutate** | Изменение ресурсов перед применением | Добавление imagePullSecrets |
| **Generate** | Создание новых ресурсов | NetworkPolicy, Secret |
| **Clone** | Копирование ресурсов между namespace | Копирование Docker Registry Secret |

---

## Practical Scenarios

### Сценарий 4: Инфраструктура как код и политики как код

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

---

### Сценарий 5: Управление сетевыми политиками

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

**Связанные темы**: [NetworkPolicy](../../network_policies.md)

---

### Сценарий 6: Управление секретами Docker Registry

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

---

## Additional Information

### Рекомендации по автоматизации

1. **Использовать synchronize: true** для поддержания актуальности сгенерированных ресурсов
2. **Тестировать политики** в CI/CD перед применением в продакшене
3. **Версионировать политики** в Git вместе с инфраструктурой
4. **Документировать** каждую политику через annotations

### Связанные темы

- [Написание политик](../policies/practical_scenarios.md) — структура и примеры политик
- [Типы правил](../rules.md) — правила generate и mutate
- [Установка](../install.md) — установка и настройка Kyverno
