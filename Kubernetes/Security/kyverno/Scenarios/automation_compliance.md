# Автоматизация и соответствие стандартам (Compliance) в Kyverno

## Определения

**Автоматизация (Automation)** — процесс принудительного исполнения эксплуатационных стандартов и политик безопасности без ручного вмешательства. В Kyverno реализуется через мутацию данных (`mutate`) и динамическую генерацию новых объектов (`generate`).

**Соответствие (Compliance)** — непрерывное подтверждение соблюдения нормативных требований (PCI DSS 4.0, NIS2, CIS Benchmarks, HIPAA). В современной инфраструктуре комплаенс реализуется через модель **Continuous Compliance** (непрерывный аудит), где политика выступает в роли «живого» контроля качества.

**Мультиарендность (Multi-tenancy)** — модель использования кластера, где Kyverno обеспечивает жесткую изоляцию ресурсов команд, автоматизируя создание границ безопасности (NetworkPolicies, RBAC, Quotas).

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

Автоматическое создание границ ресурсов для каждой новой команды.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: team-resource-guard
spec:
  rules:
    - name: create-default-quota
      match:
        any:
          - resources:
              kinds: [Namespace]
      generate:
        kind: ResourceQuota
        name: default-team-quota
        namespace: "{{request.object.metadata.name}}"
        data:
          spec:
            hard:
              cpu: "10"
              memory: 20Gi
              pods: "50"
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

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Использование UpdateRequests**: При выполнении фоновых генераций всегда проверяйте статус в `kubectl get updaterequests -n kyverno`. Это единственный способ отследить ошибки асинхронных операций.
2.  **Синхронизация (Synchronize)**: Всегда устанавливайте `synchronize: true` для правил `generate`, чтобы изменения в шаблоне политики (например, обновление CA-сертификата в клонируемом секрете) моментально отразились во всех Namespace.
3.  **Тэгирование политик**: Используйте аннотации для связи политик с пунктами стандартов. Это упрощает формирование отчетов для аудиторов.
    ```yaml
    annotations:
      compliance.kyverno.io/standard: "NIS2"
      compliance.kyverno.io/control: "Article 21"
    ```
4.  **Оптимизация CEL**: Для массовых проверок в CI/CD используйте `ValidatingPolicy` (CEL), так как они потребляют на 30% меньше ресурсов при выполнении тестов.

### См. также

- **[Типы правил (SSoT)](../rules.md)** — глубокий разбор match, validate, generate.
- **[Библиотека практических примеров](../policies/practical_scenarios.md)** — готовые YAML для копирования.
- **[Агрегированные роли](../additional.md)** — права контроллеров на генерацию.
- **[Отчеты и AdmissionReports](../reports.md)** — визуализация результатов комплаенса.
