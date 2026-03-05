# Сценарии безопасности Kyverno

## Определения

**Сценарии безопасности** — использование Kyverno для применения политик безопасности, обеспечения соответствия стандартам и внедрения лучших практик.

> **Навигация:** [Главная сценариев](./index.md) | [Автоматизация](./automation_compliance.md) | [Очистка](./cleanup_verification.md)

---

## Basic Concepts

### Категории сценариев безопасности

| Тип | Описание | Пример |
|-----|----------|--------|
| **Валидация** | Проверка ресурсов на соответствие требованиям | Требование non-root |
| **Мутация** | Автоматическое добавление настроек безопасности | Добавление securityContext |
| **Генерация** | Создание ресурсов безопасности | NetworkPolicy |

---

## Practical Scenarios

### Сценарий 1: Применение политик безопасности в реальном времени

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

---

### Сценарий 2: Автоматизация соответствия стандартам

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

---

### Сценарий 3: Внедрение лучших практик

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

---

## Additional Information

### Рекомендации по применению политик безопасности

1. **Начать с аудита**: Включить `validationFailureAction: Audit` для сбора данных
2. **Отладка политик**: Использовать [Background Scan](../background.md) для тестирования
3. **Постепенное внедрение**: Переход на `Enforce` после проверки
4. **Мониторинг**: Настроить [Policy Reporter](../reporter.md) для отслеживания нарушений

### Связанные темы

- [Написание политик](../policies.md) — структура и примеры политик
- [Типы правил](../rules.md) — правила validate и mutate
- [Установка](../install.md) — установка и настройка Kyverno
