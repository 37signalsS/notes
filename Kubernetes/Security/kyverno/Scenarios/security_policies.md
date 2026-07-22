# Сценарии безопасности Kyverno

## Определения

**Сценарии безопасности** — практические примеры реализации защитных механизмов кластера Kubernetes с использованием Kyverno. Сценарии охватывают превентивную блокировку угроз, автоматическое исправление конфигураций и непрерывный аудит на соответствие стандартам (PSS, CIS).

В современных версиях (2024–2025) сценарии безопасности опираются на **CEL (Common Expression Language)** для обеспечения максимальной производительности и нативной совместимости с Kubernetes.

---

## Основные концепции

### Эшелонированная защита с Kyverno

Использование Kyverno в сценариях безопасности строится по четырем ключевым направлениям:

| Направление | Описание | Инструментарий |
| :--- | :--- | :--- |
| **Prevention** | Блокировка небезопасных ресурсов до их попадания в кластер. | `ValidatingPolicy` (CEL) или `ClusterPolicy` (Enforce). |
| **Mutation** | Автоматическое добавление настроек безопасности (например, `runAsNonRoot`). | `MutatingPolicy` или `ClusterPolicy` (Mutate). |
| **Audit** | Выявление дрифта конфигураций и нарушений в существующих ресурсах. | [Background Scans](../background.md) + `PolicyReports`. |
| **Supply Chain** | Верификация подписей образов и аттестаций безопасности (SBOM). | `ImageValidatingPolicy` (Sigstore/Cosign). |

### Сосуществование с Pod Security Admission (PSA)

Kyverno не заменяет встроенный в Kubernetes механизм PSA, а расширяет его возможности:
*   **Генерация отчетов**: В отличие от PSA, Kyverno создает визуализируемые отчеты `PolicyReport`.
*   **Мутация**: PSA умеет только блокировать; Kyverno может автоматически исправлять ресурсы.
*   **Гранулярность**: Kyverno позволяет создавать точечные исключения через `PolicyException`.

---

## Практические сценарии

### 1. Внедрение Pod Security Standards (CEL-валидация)

**Проблема**: Необходимо обеспечить соответствие кластера стандарту **PSS Restricted** без использования устаревших JMESPath-фильтров.

**Решение**: Использование `ValidatingPolicy` на базе CEL для эффективной проверки параметров безопасности.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: pss-restricted-no-privileged
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        resources: ["pods"]
  validations:
    - expression: |
        object.spec.containers.all(c, 
          !has(c.securityContext) || !has(c.securityContext.privileged) || c.securityContext.privileged == false
        )
      message: "Запуск привилегированных контейнеров запрещен (PSS Restricted)."
```

### 2. Защита цепочки поставок (Image Verification)

**Проблема**: Риск использования скомпрометированных образов из публичных реестров.

**Решение**: Блокировка образов, не подписанных корпоративным ключом Cosign.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-image-signatures
spec:
  rules:
    - name: verify-sigstore
      imageReferences:
        - "index.docker.io/my-company/*"
      attestations:
        - name: check-signature
          verifier:
            sigstore:
              publicKey: |
                -----BEGIN PUBLIC KEY-----
                ...
                -----END PUBLIC KEY-----
```

### 3. Автоматическое исправление конфигураций (Mutation)

**Проблема**: Разработчики не всегда указывают `securityContext`, что приводит к блокировке деплоев.

**Решение**: Автоматическая инъекция параметров безопасности при создании ресурса.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: auto-inject-security-context
spec:
  rules:
    - name: inject-non-root
      match:
        any:
          - resources:
              kinds: [Pod]
      mutate:
        patchStrategicMerge:
          spec:
            securityContext:
              runAsNonRoot: true
              runAsUser: 1000
```

---

## Дополнительная информация

### Рекомендации по стратегии безопасности

1.  **Shift-Left**: Используйте `kyverno CLI` в пайплайнах для проверки манифестов до деплоя. Это позволяет выявить ошибки до того, как они попадут в Admission-контроллер.
2.  **Использование PolicyException**: Для временных разрешений (например, для инструментов миграции) создавайте отдельные ресурсы `PolicyException` вместо изменения основных политик.
3.  **Исключение системных ресурсов**: Всегда добавляйте `kube-system` и `kyverno` в исключения политик мутации, чтобы не нарушить работу самого кластера.
4.  **Мониторинг**: Связывайте сценарии с [Policy Reporter](../reporter.md) для отслеживания динамики нарушений в реальном времени.

### См. также

- **[Типы правил (validate, mutate, generate)](../rules.md)** — основы синтаксиса.
- **[Автоматизация и комплаенс](./automation_compliance.md)** — сетевые политики и соответствие NIS2.
- **[Библиотека политик](../policies/practical_scenarios.md)** — готовые примеры для копирования.
- **[Отчеты (Policy Reports)](../reports.md)** — как анализировать нарушения.
- **[Сравнение с другими инструментами](../concepts.md#сравнение-с-другими-инструментами)** — Kyverno vs Gatekeeper vs Falco.
