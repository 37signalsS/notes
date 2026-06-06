# Очистка ресурсов и верификация образов в Kyverno

## Определения

**Очистка ресурсов (Pruning)** — процесс автоматического удаления устаревших, завершенных или неиспользуемых объектов Kubernetes по заданному расписанию или условиям. Реализуется через ресурс `CleanupPolicy` (API `kyverno.io/v2`).

**Верификация образов (Image Verification)** — механизм проверки подлинности и целостности контейнерных образов путем верификации их цифровых подписей (например, через Sigstore/Cosign) перед допуском в кластер.

---

## Основные концепции

### Механизмы контроля жизненного цикла

| Механизм | API (Application Programming Interface) | Назначение | Особенности |
|----------|---------------------------------------|------------|-------------|
| **CleanupPolicy** | `kyverno.io/v2` | Удаление ресурсов по расписанию. | Работает через `cleanup-controller`. |
| **verifyImages** | `kyverno.io/v1` | Проверка подписей образов. | Интеграция с Sigstore/Cosign и KMS. |

---

## Практические сценарии

### 1. Автоматическая очистка завершенных подов (Pruning)

**Проблема**: Завершенные поды (со статусом `Succeeded` или `Failed`) накапливаются в кластере, занимая место в etcd и затрудняя мониторинг.

**Решение**: Использование политики очистки `CleanupPolicy` для удаления подов через 6 часов после завершения.

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
        value: Succeeded # Удалять только успешно завершенные
  schedule: "0 */6 * * *"  # Запуск каждые 6 часов
```

> **Примечание**: Для работы данной функции должен быть установлен и запущен компонент `cleanup-controller` ([подробнее об архитектуре](../concepts.md)).

---

### 2. Верификация подписей образов через Cosign

**Проблема**: Риск подмены образов в реестре или деплоя непроверенного ПО.

**Решение**: Настройка правила `verifyImages` для проверки подписи каждого образа публичным ключом.

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
            - "registry.example.com/*" # Проверять все образы из доверенного реестра
          attestors:
            - count: 1
              entries:
                - keys:
                    - publicKeys: |
                        -----BEGIN PUBLIC KEY-----
                        MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
                        -----END PUBLIC KEY-----
```

**Связанные инструменты**: [Sigstore](../../../../Security/Tools/sigstore.md) — платформа для подписи ПО, [Artifact Signing](../../../../Security/Supply_Chain_Security/artifact_signing.md) — концепция защиты цепочки поставок.

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Тестирование расписания**: При настройке `CleanupPolicy` сначала протестируйте расписание на небольшом интервале, чтобы убедиться в корректности условий.
2.  **Защита ключей**: Храните публичные ключи для верификации образов в виде секретов Kubernetes или используйте интеграцию с **KMS (Key Management Service)**.
3.  **Мониторинг очистки**: Настройте оповещения в [Policy Reporter](../reporter.md), чтобы отслеживать массовое удаление ресурсов.
4.  **Количество аттестаторов**: В правилах `verifyImages` можно требовать подписи от нескольких сторон (например, от безопасности и от QA), используя параметр `count`.

### Связанные темы

- [Библиотека политик](../policies/practical_scenarios.md) — примеры готовых манифестов.
- [Типы правил](../rules.md) — детально о синтаксисе `verifyImages`.
- [Установка](../install.md) — настройка контроллеров очистки.
