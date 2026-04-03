# Очистка ресурсов и верификация образов в Kyverno

## Определения

**Очистка ресурсов (Pruning)** — автоматическое удаление устаревших или завершённых ресурсов Kubernetes через ресурс `CleanupPolicy` (API `kyverno.io/v2`).

**Верификация образов** — проверка подписей контейнерных образов перед деплое через правило `verifyImages` ([подробнее о синтаксисе](../rules.md#проверка-подписей-образов)).

---

## Basic Concepts

### Механизмы очистки и верификации

| Механизм | API | Описание | SSoT |
|----------|-----|----------|------|
| **CleanupPolicy** | kyverno.io/v2 | Удаление ресурсов по расписанию | — |
| **verifyImages** | kyverno.io/v1 | Проверка подписей образов | [Типы правил — verifyImages](../rules.md#типы-правил-kyverno) |

---

## Practical Scenarios

### Сценарий 7: Очистка ресурсов (Pruning)

**Проблема**: Необходимо удалять старые завершённые Pod для экономии ресурсов кластера.

**Решение**: Политика очистки по расписанию через `CleanupPolicy`.

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

> **Примечание**: Для работы `CleanupPolicy` требуется установленный `cleanup-controller` ([подробнее об установке](../install.md)).

---

### Сценарий 8: Проверка подписей образов

**Проблема**: Необходимо разрешать деплой только подписанных образов из доверенного реестра.

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

**Связанные темы**: [Sigstore](../../../../Security/Tools/sigstore.md) — инструментарий подписи, [Artifact Signing](../../../../Security/Supply_Chain_Security/artifact_signing.md) — supply chain security

---

## Additional Information

### Рекомендации по очистке ресурсов

1. **Настроить расписание** в зависимости от нагрузки кластера
2. **Использовать условия** для точного определения ресурсов на удаление
3. **Мониторить** количество удаляемых ресурсов через [Policy Reporter](../reporter.md)

### Рекомендации по верификации образов

1. **Использовать Sigstore/Cosign** для подписи образов
2. **Хранить публичные ключи** в защищённом месте (KMS, Vault)
3. **Тестировать политики** на staging перед продакшеном

### Связанные темы

- [Написание политик](../policies/practical_scenarios.md) — структура и примеры политик
- [Типы правил](../rules.md) — правило verifyImages
- [Установка](../install.md) — установка и настройка Kyverno
- [Policy Reports](../reports.md) — мониторинг применения политик
