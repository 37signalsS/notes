# Очистка ресурсов и верификация образов в Kyverno

## Определения

**Очистка ресурсов (Pruning)** — автоматическое удаление устаревших или завершенных ресурсов Kubernetes.

**Верификация образов** — проверка подписей контейнерных образов перед деплоем.

> **Навигация:** [Главная сценариев](./index.md) | [Безопасность](./security_policies.md) | [Автоматизация](./automation_compliance.md)

---

## Basic Concepts

### Механизмы очистки и верификации

| Механизм | API | Описание | Пример |
|----------|-----|----------|--------|
| **CleanupPolicy** | kyverno.io/v2 | Удаление ресурсов по расписанию | Удаление завершенных Pod |
| **verifyImages** | kyverno.io/v1 | Проверка подписей образов | Sigstore/Cosign |

---

## Practical Scenarios

### Сценарий 7: Очистка ресурсов (Pruning)

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

---

### Сценарий 8: Проверка подписей образов

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

**Связанные темы**: [Sigstore](../../../../Security/Tools/sigstore.md), [Supply Chain Security](../../../../Security/Supply_Chain_Security/artifact_signing.md)

---

## Additional Information

### Рекомендации по очистке ресурсов

1. **Настроить расписание** в зависимости от нагрузки кластера
2. **Использовать условия** для точного определения ресурсов на удаление
3. **Мониторить** количество удаляемых ресурсов через [Policy Reporter](../reporter.md)

### Рекомендации по верификации образов

1. **Использовать Sigstore/Cosign** для подписи образов
2. **Хранить публичные ключи** в безопасном месте
3. **Тестировать политики** на staging перед продакшеном

### Связанные темы

- [Написание политик](../policies/practical_scenarios.md) — структура и примеры политик
- [Типы правил](../rules.md) — правило verifyImages
- [Установка](../install.md) — установка и настройка Kyverno
- [Отчеты](../reports.md) — мониторинг применения политик
