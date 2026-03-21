# Типы правил Kyverno

## Определения

**Правило (rule)** — базовый элемент политики Kyverno, определяющий тип действия (валидация, мутация, генерация) и условия его применения.

**Политика (policy)** — набор правил, объединенных общей целью. Бывает двух типов:

- **Policy** — namespace-scoped, применяется к ресурсам в конкретном namespace
- **ClusterPolicy** — cluster-scoped, применяется ко всему кластеру

> **Основное руководство:** Подробное описание структуры политик и примеров — в [Написание политик](./policies/practical_scenarios.md).

---

## Basic Concepts

### Типы правил

| Тип | Назначение | Подтипы/механизмы |
|-----|------------|-------------------|
| **generate** | Создание или клонирование ресурсов | `clone` (копирование Secret/ConfigMap), `synchronize` (синхронизация с источником) |
| **mutate** | Автоматическое добавление или изменение полей | `patchStrategicMerge`, `imagePullPolicy`, `imagePullSecrets` |
| **validate** | Валидация ресурсов на соответствие правилам | `pattern` (шаблон), `deny` (запрет с условиями), `foreach` (итерация по массиву) |
| **verifyImages** | Проверка подписей образов | Cosign, KMS, другие системы подписи |

### Match и Exclude

Каждое правило содержит условия применения:

```yaml
rules:
  - name: example-rule
    match:
      any:
        - resources:
            kinds:
              - Pod
            namespaces:
              - default
              - user1
            operations:
              - CREATE
              - UPDATE
    exclude:
      all:
        - resources:
            namespaces:
              - kube-system
```

| Параметр | Описание |
|----------|----------|
| `any` / `all` | Логическое объединение условий (OR / AND) |
| `kinds` | Типы ресурсов (Pod, Deployment, Service, etc.) |
| `namespaces` | Namespace для применения |
| `operations` | Операции: CREATE, UPDATE, DELETE, CONNECT |

---

## Practical Scenarios

### Валидация с помощью pattern

Правило `validate` с типом `pattern` проверяет манифест на соответствие шаблону:

```yaml
rules:
  - name: require-run-as-non-root
    match:
      resources:
        kinds:
          - Pod
    validate:
      failureAction: Enforce
      message: "Container must run as non-root user"
      pattern:
        spec:
          =(securityContext):
            runAsNonRoot: true
            runAsUser: ">0"
```

**Якоря (anchors)**:

- `(field)` — опциональное поле: если присутствует, проверяется условие
- `=(field)` — обязательное поле
- `>(n)`, `>=(n)`, `=(n)`, `<(n)`, `<=(n)` — числовые сравнения
- `*` — wildcard (любое значение)

### Запрещающие правила (deny)

Правило `deny` использует условия для запрета:

```yaml
rules:
  - name: deny-host-path
    match:
      resources:
        kinds:
          - Pod
    deny:
      conditions:
        - key: "{{ request.object.spec.volumes[*].hostPath }}"
          operator: AnyNotIn
          value:
            - ""
            - null
      message: "HostPath volumes are forbidden"
```

Условия работают с **AdmissionReview** — JSON-объект, содержащим информацию о запросе.

### Генерация ресурсов

```yaml
rules:
  - name: generate-network-policy
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

### Мутация ресурсов

```yaml
rules:
  - name: add-security-context
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
```

### Проверка подписей образов

```yaml
rules:
  - name: verify-image-signature
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
                      ...
                      -----END PUBLIC KEY-----
```

---

## Additional Information

### Важные замечания

1. **Background scan не применяется к существующим ресурсам** — политика срабатывает только при CREATE/UPDATE ([подробнее](./background.md))
2. По умолчанию примеры политик в документации используют `failureAction: audit`
3. Для полной защиты необходимо переключить на `failureAction: Enforce`
4. Политики применяются к **Pod** — Kyverno проверяет итоговый Pod, сгенерированный из Deployment/StatefulSet/DaemonSet

### Операторы условий

| Оператор | Описание |
|----------|----------|
| `AnyIn` / `AnyNotIn` | Проверка элемента массива на вхождение/невхождение |
| `AllIn` / `AllNotIn` | Проверка всех элементов массива |
| `Equal` / `NotEqual` | Равенство / неравенство |
| `GreaterThanOrEquals` / `LessThanOrEquals` | Числовые сравнения |
| `PatternMatch` | Проверка по regex-шаблону |

### Связанные темы

- [Написание политик](./policies/practical_scenarios.md) — подробные примеры политик
- [Policy Reports](./reports.md) — отчеты о применении правил
- [Aggregated Cluster Roles](./additional.md) — права для генерации ресурсов
