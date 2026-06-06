# Автоматизация и соответствие стандартам (Compliance) в Kyverno

## Определения

**Автоматизация** в Kyverno — процесс автоматической настройки ресурсов Kubernetes через механизмы мутации (`mutate`) и генерации (`generate`). Позволяет изменять параметры ресурсов или создавать зависимые объекты без ручного вмешательства.

**Соответствие стандартам (Compliance)** — обеспечение соблюдения внутренних и внешних требований безопасности, таких как **PCI DSS (Payment Card Industry Data Security Standard)**, **GDPR (General Data Protection Regulation)** и **CIS Benchmarks (Center for Internet Security Benchmarks)**, путем описания политик в виде декларативного кода — Policy as Code (политики как код).

---

## Основные концепции

### Механизмы автоматизации

Для реализации сценариев автоматизации Kyverno использует следующие типы правил ([подробнее о типах правил](../rules.md)):

| Механизм | Описание | Основная цель |
|----------|----------|---------------|
| **Mutate (Мутация)** | Изменение манифеста перед сохранением в etcd (распределенное хранилище ключей и значений). | Исправление конфигурационных ошибок, добавление параметров по умолчанию. |
| **Generate (Генерация)** | Создание нового ресурса на основе триггерного события. | Автоматическое развертывание сопутствующей инфраструктуры. |
| **Clone (Клонирование)** | Копирование существующего ресурса в новый Namespace (пространство имен). | Синхронизация общих ресурсов, таких как секреты или конфигурации. |

### Политики как код (Policy as Code)

Принцип хранения политик Kyverno в Git-репозитории позволяет реализовать полный цикл контроля качества: версионирование, проверку через **CI/CD (Continuous Integration / Continuous Deployment — непрерывная интеграция и доставка)** и автоматическое тестирование.

Типовая структура репозитория:
```
git-repo/
├── policies/      # Манифесты политик в формате YAML (Yet Another Markup Language)
├── tests/         # Тестовые ресурсы и ожидаемые результаты
└── .github/       # Пайплайны автоматизации (например, GitHub Actions)
```

**Валидация политик**: Перед применением в кластере рекомендуется использовать **Kyverno CLI (Command Line Interface — интерфейс командной строки)** для проверки синтаксиса и тестирования на наборах данных.

Команда для проверки:
```bash
kyverno apply policies/ --resource=tests/
# → Результат выполнения теста
```

---

## Практические сценарии

### 1. Инфраструктура как код (IaC) и CI/CD валидация

**Проблема**: Изменения в политиках безопасности могут случайно заблокировать критические приложения или нарушить работу кластера.

**Решение**: Внедрение автоматической проверки политик в пайплайн доставки перед их применением.

```yaml
# Пример GitHub Actions пайплайна
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

### 2. Обеспечение соответствия стандартам (Compliance)

**Проблема**: Необходимо гарантировать, что все ресурсы соответствуют требованиям безопасности (например, шифрование данных) и автоматически классифицировать нарушения.

**Решение**: Использование аннотаций в политиках для связи с конкретными стандартами и блокировка несоответствующих ресурсов.

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
        message: "PVC (PersistentVolumeClaim) должен использовать зашифрованный StorageClass"
        pattern:
          spec:
            storageClassName: "*-encrypted"
```

### 3. Автоматическое управление сетевой изоляцией

**Проблема**: По умолчанию в Kubernetes разрешены все сетевые взаимодействия. Требуется автоматически изолировать каждое новое пространство имен.

**Решение**: Генерация базовой политики `NetworkPolicy` при создании каждого `Namespace`.

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

> **Важно**: Для генерации ресурсов требуется агрегированная роль с соответствующими правами ([подробнее](../additional.md#контроллеры-kyverno)).

### 4. Управление секретами Docker Registry

**Проблема**: При создании нового пространства имен администраторам приходится вручную копировать секреты с учетными данными (**credentials**) для доступа к приватному реестру образов (**Docker Registry**).

**Решение**: Комбинация правил генерации (для клонирования секрета) и мутации (для автоматического добавления `imagePullSecrets` в Поды).

**Клонирование секрета**:
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
          namespace: template-namespace
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

## Дополнительная информация

### Рекомендации по автоматизации

1. **Синхронизация (`synchronize: true`)**: Используйте этот параметр, чтобы изменения в базовой политике автоматически распространялись на все ранее сгенерированные ресурсы.
2. **Агрегированные роли**: Убедитесь, что контроллер `background-controller` имеет права на создание и изменение генерируемых ресурсов ([подробнее](../additional.md)).
3. **Аннотации для отчетности**: Для автоматизации комплаенс-отчетов используйте аннотации `policies.kyverno.io/category` и `policies.kyverno.io/severity`. Результаты можно визуализировать через [Policy Reporter](../reporter.md).

### Связанные темы

- [Написание политик](../policies/practical_scenarios.md) — библиотека готовых манифестов.
- [Типы правил](../rules.md) — детальное описание механизмов mutate и generate.
- [Отчеты](../reports.md) — мониторинг результатов проверок на соответствие стандартам.
