# Очистка ресурсов и верификация образов в Kyverno

## Определения

**Автоматическая очистка (Cleanup)** — асинхронный процесс удаления устаревших, завершенных или неиспользуемых объектов Kubernetes. Выполняется специализированным `cleanup-controller`, который отслеживает расписания (`CleanupPolicy`) и метки времени жизни (TTL).

**Update Request (UR)** — внутренний ресурс Kyverno, создаваемый контроллером для выполнения и отслеживания статуса фоновых задач, включая операции массовой очистки и генерации.

**Верификация образов (Image Verification)** — динамический контроль подлинности контейнерных образов в момент Admission-контроля. Включает проверку криптографических подписей, аттестаций (доказательств сборки) и соответствие содержимого SBOM (Software Bill of Materials) установленным стандартам.

---

## Основные концепции

### Механизмы управления жизненным циклом

На 2026 год Kyverno предлагает три уровня контроля за состоянием кластера:

| Механизм | Техническая реализация | Применение |
| :--- | :--- | :--- |
| **CleanupPolicy** | `ClusterCleanupPolicy` (v2) | Массовое удаление по расписанию (Cron) с использованием CEL-фильтров. |
| **Label-based TTL** | `cleanup.kyverno.io/ttl` | Индивидуальное самоудаление ресурсов (например, временных Namespace). |
| **Image Verification** | `ImageValidatingPolicy` | Проверка цепочки поставок (Supply Chain) через Sigstore/Cosign. |

### Защита цепочки поставок (Supply Chain Security)

Современная архитектура верификации в Kyverno (v1.17+) базируется на стандартах **SLSA** и **OCI 1.1 Referrers API**:
1.  **Keyless Signing**: Проверка подписей на основе OIDC-идентификаторов (например, GitHub Actions Runner), что исключает риск компрометации долгоживущих приватных ключей.
2.  **Attestations & VSA**: Проверка аттестаций сканирования на уязвимости и **Vulnerability Scanning Attestations (VSA)**.
3.  **SBOM Validation**: Анализ состава образа (библиотеки, лицензии) через спецификации CycloneDX или SPDX, прикрепленные к образу как Referrers.

---

## Практические сценарии

### 1. Автоматическая очистка временных сред (TTL)

Используется для управления жизненным циклом ресурсов в песочницах (Sandbox) без создания дополнительных политик.

```yaml
# Пример Namespace для Feature-ветки
apiVersion: v1
kind: Namespace
metadata:
  name: feat-ui-header-452
  labels:
    # Контроллер удалит NS ровно через 12 часов после создания
    cleanup.kyverno.io/ttl: "12h"
```

### 2. Очистка «осиротевших» ресурсов (Orphaned Resources)

**Проблема**: После удаления `PVC` (PersistentVolumeClaim) в кластере могут оставаться неиспользуемые `PV` (PersistentVolume) в статусе `Released`, занимающие дисковое пространство.

**Решение**: Политика очистки неиспользуемых томов.

```yaml
apiVersion: kyverno.io/v2
kind: ClusterCleanupPolicy
metadata:
  name: cleanup-orphaned-pv
spec:
  schedule: "0 2 * * *" # Ежедневно в 02:00
  match:
    any:
      - resources:
          kinds: [PersistentVolume]
  conditions:
    all:
      - key: "{{ target.status.phase }}"
        operator: Equals
        value: "Released"
```

### 3. Keyless-верификация через GitHub Actions

**Проблема**: Необходимо гарантировать, что в `production` попадают только образы, собранные в официальном репозитории организации.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-github-provenance
spec:
  rules:
    - name: check-keyless-signature
      imageReferences: ["ghcr.io/my-company/*"]
      attestors:
        - entries:
            - keyless:
                # Доверяем только GitHub Actions как эмитенту токена
                issuer: "https://token.actions.githubusercontent.com"
                # Проверяем конкретный репозиторий и ветку сборки
                subject: "https://github.com/my-org/core-api/.github/workflows/deploy.yaml@refs/heads/main"
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Обслуживание UpdateRequests**: Регулярно мониторьте ресурсы UR в пространстве имен `kyverno`. Большое количество ошибок в UR может указывать на недостаток прав RBAC у `cleanup-controller` ([подробнее в additional.md](../additional.md)).
2.  **Оптимизация кэша**: Для `ImageValidatingPolicy` всегда используйте `image-verify-cache`. Это снижает количество внешних запросов к OCI-реестру и Rekor-серверу Sigstore на 90%.
3.  **Foreground Deletion**: При настройке `CleanupPolicy` учитывайте, что Kyverno использует стандартные механизмы удаления K8s. Убедитесь, что `Finalizers` на ресурсах не блокируют процесс очистки.
4.  **Shift-Left**: Проверяйте наличие аттестаций SBOM еще на этапе CI через `kyverno CLI`, чтобы предотвратить блокировку деплоя в кластере.

### См. также

- **[Агрегированные роли и права контроллеров](../additional.md)** — настройка прав для удаления ресурсов.
- **[Отчеты и AdmissionReports](../reports.md)** — анализ результатов верификации образов.
- **[Подписание артефактов и Sigstore](../../../Security/Supply_Chain_Security/artifact_signing.md)** — теория Keyless-подписи.
- **[Анализ SBOM в CI/CD](../../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)** — генерация и аудит состава ПО.
