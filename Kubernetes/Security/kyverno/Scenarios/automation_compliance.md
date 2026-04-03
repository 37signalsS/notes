# Автоматизация и compliance в Kyverno

## Определения

**Автоматизация** — автоматическая настройка ресурсов Kubernetes через политики Kyverno с использованием механизмов mutate, generate и clone.

**Compliance** — обеспечение соответствия внутренним и внешним стандартам (PCI DSS, GDPR, CIS Benchmark) через политики как код.

---

## Basic Concepts

### Механизмы автоматизации

| Механизм | Описание | SSoT |
|----------|----------|------|
| **Mutate** | Изменение ресурсов перед применением | [Типы правил — mutate](../rules.md#мутация-ресурсов) |
| **Generate** | Создание новых ресурсов при событиях | [Типы правил — генерация](../rules.md#генерация-ресурсов) |
| **Clone** | Копирование ресурсов между namespace | [Типы правил — generate](../rules.md#типы-правил-kyverno) |

### Политики как код (Policy as Code)

Принцип хранения политик Kyverno в Git-репозитории с версионированием и CI/CD-валидацией:

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

**CI/CD пайплайн** использует Kyverno CLI для валидации: `kyverno apply policies/ --resource=tests/` ([подробнее о CLI](https://kyverno.io/docs/kyverno-cli/)).

---

## Practical Scenarios

### Сценарий 4: Инфраструктура как код и политики как код

**Проблема**: Политики безопасности должны версионироваться и тестироваться перед применением в продакшене.

**Решение**: Хранение политик в Git с CI/CD-валидацией через Kyverno CLI.

```yaml
# .github/workflows/validate-policies.yaml
name: Validate Kyverno Policies
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Kyverno CLI
        run: |
          curl -LO https://github.com/kyverno/kyverno/releases/download/v1.12.0/kyverno-cli_v1.12.0_linux_x86_64.tar.gz
          tar -xzf kyverno-cli_v1.12.0_linux_x86_64.tar.gz
          chmod +x kyverno
          sudo mv kyverno /usr/local/bin/
      - name: Validate policies
        run: kyverno apply policies/ --resource=tests/
```

---

### Сценарий 5: Управление сетевыми политиками

**Проблема**: Необходимо автоматически изолировать приложения в разных namespace.

**Решение**: Генерация NetworkPolicy при создании namespace через правило `generate` ([подробнее о синтаксисе](../rules.md#генерация-ресурсов)).

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

> **Примечание**: Для генерации NetworkPolicy требуется агрегированная роль с правами на создание `networkpolicies` ([пример ClusterRole](../additional.md#пример-права-для-генерации-networkpolicy)).

**Связанные темы**: [NetworkPolicy](../../Security/network_policies.md) — концепция и примеры сетевых политик

---

### Сценарий 6: Управление секретами Docker Registry

**Проблема**: При создании namespace необходимо копировать Secret с credentials для доступа к приватному Docker Registry.

**Решение**: Политика `generate` с параметром `clone` ([подробнее о клонировании](../rules.md#типы-правил-kyverno)).

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

> **Примечание**: Для клонирования Secret требуется агрегированная роль с правами на `secrets` ([пример ClusterRole](../additional.md#пример-права-для-генерации-secret)).

**Автоматическое добавление imagePullSecrets** к Pod через правило `mutate`:

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

1. **Использовать `synchronize: true`** для поддержания сгенерированных ресурсов в актуальном состоянии
2. **Тестировать политики в CI/CD** перед применением в продакшене через Kyverno CLI
3. **Версионировать политики** в Git вместе с инфраструктурой
4. **Документировать политики** через annotations (`policies.kyverno.io/description`, `policies.kyverno.io/category`)
5. **Настраивать агрегированные роли** для прав на генерацию ресурсов ([подробнее](../additional.md#aggregated-cluster-roles-в-kyverno))

### Связанные темы

- [Написание политик](../policies/practical_scenarios.md) — структура и примеры политик
- [Типы правил](../rules.md) — правила generate и mutate
- [Aggregated Cluster Roles](../additional.md) — права для генерации ресурсов
- [Установка](../install.md) — установка и настройка Kyverno
