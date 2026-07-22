# Автоматизация и соответствие стандартам (Compliance) в Kyverno

## Определения

**Автоматизация (Automation)** — процесс принудительного исполнения эксплуатационных стандартов и политик безопасности без ручного вмешательства. В Kyverno реализуется через мутацию существующих данных (`mutate`) и динамическую генерацию новых объектов (`generate`).

**Соответствие (Compliance)** — непрерывное обеспечение и подтверждение соблюдения нормативных требований (PCI DSS 4.0, NIS2, CIS Benchmarks, GDPR). В контексте Kubernetes комплаенс переходит от модели «периодических проверок» к модели «непрерывного аудита» (Continuous Compliance) через механизм Policy-as-Code.

---

## Основные концепции

### Механизмы автоматизированного контроля

Kyverno использует специализированные контроллеры для реализации четырех основных стратегий автоматизации ([подробнее о правах контроллеров](../additional.md)):

| Механизм | Описание | Основная цель |
| :--- | :--- | :--- |
| **Mutate (Мутация)** | Изменение манифеста в оперативной памяти перед сохранением в `etcd`. | Исправление ошибок конфигурации, добавление настроек безопасности по умолчанию. |
| **Generate (Генерация)** | Создание нового ресурса (например, `NetworkPolicy`) на основе события (создание `Namespace`). | Автоматизация развертывания сопутствующей инфраструктуры. |
| **Clone (Клонирование)** | Копирование существующего ресурса (например, `Secret`) в новый `Namespace`. | Синхронизация общих ресурсов между командами (Docker Registry Credentials, CA Bundles). |
| **CEL Validate** | Нативная валидация через Common Expression Language (v1.14+). | Высокопроизводительная проверка сложных условий комплаенса без сетевых задержек. |

### Принцип Policy-as-Code и CI/CD

Хранение политик в Git позволяет использовать стандартные инструменты разработки для контроля качества безопасности.

**Структура репозитория политик:**
```
policy-repo/
├── policies/      # Манифесты ClusterPolicy и ValidatingPolicy в YAML
├── tests/         # Тестовые ресурсы (положительные и отрицательные тесты)
│   └── values.yaml # Переменные для тестирования
└── .github/       # Пайплайны автоматизации (GitHub Actions, GitLab CI)
```

**Kyverno CLI**: Основной инструмент для «сдвига влево» (Shift-Left). Он позволяет протестировать влияние новой политики на тысячи ресурсов до её применения в кластере.

```bash
# Проверка синтаксиса и тестирование на ресурсах
kyverno apply policies/ --resource=tests/
# → PASS: policy check-labels on resource pod-1
```

---

## Практические сценарии

### 1. Инфраструктура как код и CI/CD валидация

Интеграция Kyverno в пайплайн предотвращает попадание небезопасных или некомплаентных манифестов в кластер.

```yaml
# Пример GitHub Actions пайплайна (актуально для v1.14+)
name: Validate Security Policies
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Kyverno CLI
        run: |
          # Установка актуальной версии CLI
          curl -LO https://github.com/kyverno/kyverno/releases/download/v1.14.0/kyverno-cli_v1.14.0_linux_x86_64.tar.gz
          tar -xzf kyverno-cli_v1.14.0_linux_x86_64.tar.gz
          sudo mv kyverno /usr/local/bin/
      - name: Test Policies
        run: kyverno apply policies/ --resource=tests/
```

### 2. Соответствие PCI DSS 4.0 и NIS2 (2025)

Для критических инфраструктур (финтех, энергетика) Kyverno обеспечивает выполнение требований по защите цепочки поставок и шифрованию.

**Сценарий: Проверка аттестаций SBOM (Requirement 6.3.3)**:
```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: pci-verify-sbom
spec:
  rules:
    - name: check-cyclonedx-attestation
      imageReferences: ["pci-registry.io/*"]
      attestations:
        - name: check-sbom
          type: "https://cyclonedx.org/schema" # Требуем наличие спецификации компонентов ПО
          verifier:
            sigstore:
              publicKey: |
                -----BEGIN PUBLIC KEY-----
                ...
                -----END PUBLIC KEY-----
```

### 3. Автоматическое управление сетевой изоляцией (Generate)

**Сценарий**: Реализация концепции Zero Trust. При создании каждого нового Namespace Kyverno обязан автоматически создать `NetworkPolicy`, запрещающий весь входящий трафик по умолчанию.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: generate-default-deny
spec:
  rules:
    - name: deny-all-ingress
      match:
        any:
          - resources:
              kinds: [Namespace]
      generate:
        kind: NetworkPolicy
        name: default-deny-ingress
        namespace: "{{request.object.metadata.name}}"
        synchronize: true # Автообновление при изменении политики
        data:
          spec:
            podSelector: {}
            policyTypes: [Ingress]
```

### 4. Синхронизация Docker Registry Credentials (Clone + Mutate)

**Сценарий**: Автоматизация доступа к приватному реестру для всех команд без ручного копирования секретов.

1. **Клонирование секрета** из эталонного пространства имен:
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: sync-reg-secrets
spec:
  rules:
    - name: clone-secret
      match:
        any:
          - resources:
              kinds: [Namespace]
      generate:
        kind: Secret
        name: reg-creds
        namespace: "{{request.object.metadata.name}}"
        clone:
          namespace: cert-manager # Источник
          name: reg-creds
```

2. **Автоматическая инъекция** секрета во все поды (Мутация):
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: inject-reg-secrets
spec:
  rules:
    - name: add-imagepullsecrets
      match:
        any:
          - resources:
              kinds: [Pod]
      mutate:
        patchStrategicMerge:
          spec:
            imagePullSecrets:
              - name: reg-creds
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Синхронизация (`synchronize: true`)**: При использовании `generate` этот параметр гарантирует, что если вы обновите шаблон политики (например, добавите новый разрешенный порт в `NetworkPolicy`), изменения моментально применятся ко всем сгенерированным ресурсам во всех неймспейсах.
2.  **Постепенное внедрение (Audit → Enforce)**: Даже при полной уверенности в комплаенсе, сначала применяйте политики в режиме `Audit`. Используйте [Policy Reporter](../reporter.md) для анализа ложных срабатываний.
3.  **Агрегированные роли**: Контроллеры Kyverno (`background` и `reports`) должны иметь права на создание и изменение генерируемых ресурсов. Проверьте конфигурацию [агрегированных ролей](../additional.md).
4.  **Аннотации комплаенса**: Для упрощения аудита всегда добавляйте в метаданные политики аннотации с кодами стандартов:
    ```yaml
    annotations:
      policies.kyverno.io/category: "Compliance: PCI-DSS 4.0"
      policies.kyverno.io/severity: "High"
    ```

### См. также

- **[Типы правил (validate, mutate, generate)](../rules.md)** — детальный синтаксис.
- **[Библиотека практических примеров](../policies/practical_scenarios.md)** — готовые манифесты.
- **[Отчеты (Policy Reports)](../reports.md)** — база для комплаенс-мониторинга.
- **[Официальный портал комплаенса Kyverno](https://kyverno.io/docs/compliance/)**
