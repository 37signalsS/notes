# Обзор Velero: Резервное копирование Kubernetes

---
**Надёжность:** 10 (SSoT + Проектный контекст 2026)
**Свежесть:** Актуально на 31 июля 2026
---

## Определения

**Velero** (ранее Heptio Ark) — это Open Source инструмент (проект CNCF Sandbox с 2026 года) для безопасного резервного копирования и восстановления ресурсов кластера Kubernetes, а также для миграции данных между кластерами. 

Ключевые возможности:
- **Резервное копирование объектов API:** Сохранение YAML-манифестов (Deployments, ConfigMaps, Secrets, CRD и т.д.).
- **Снимки (Snapshots) постоянных томов:** Использование CSI или нативных API облачных провайдеров.
- **Перемещение данных (Data Movement):** Копирование снимков томов в удаленное объектное хранилище (S3/Azure Blob/GCS) для обеспечения катастрофоустойчивости (Disaster Recovery).
- **Миграция:** Упрощение переноса приложений между разными облаками или on-premise средами.
- **Планирование (Scheduled Backups):** Автоматизация создания копий с гибким сроком хранения (TTL).

## Базовые концепции

### Архитектура
Velero работает по модели клиент-сервер:
1.  **Velero Server:** Deployment внутри кластера. Слушает события создания Custom Resources (Backup, Restore, Schedule) и координирует работу плагинов.
2.  **Velero CLI:** Утилита для управления, просмотра логов и инициации восстановления.
3.  **Node Agent (ранее Restic/Kopia):** DaemonSet, запускаемый на каждом узле для резервного копирования файловой системы (File-System Backup, FSB).

### Механизмы резервного копирования данных
1.  **CSI Snapshots:** Предпочтительный метод. Velero взаимодействует с `VolumeSnapshot` объектами Kubernetes. Поддерживает инкрементальные снимки, если это реализовано в CSI-драйвере.
2.  **File-system Backup (FSB):** Используется для томов, не поддерживающих снимки, или при необходимости переносимости между разными типами СХД.
    *   **Kopia:** Основной и наиболее эффективный загрузчик (uploader). Поддерживает дедупликацию, сжатие и параллельную передачу данных.
    *   **Restic:** Устаревший механизм. В v1.18+ поддержка legacy-путей Restic прекращена для новых установок.

### Локации хранения (Storage Locations)
- **Backup Storage Location (BSL):** Определяет целевое объектное хранилище для метаданных (YAML). Поддерживает **Multiple Storage Locations**, что позволяет хранить бэкапы разных приложений в разных бакетах или даже у разных провайдеров.
- **Volume Snapshot Location (VSL):** Определяет параметры для облачных снимков (регион, Resource Group, параметры шифрования).

### Управление ресурсами и фильтрация
Velero позволяет гибко выбирать объекты для бэкапа:
- **Namespaces:** `--include-namespaces` / `--exclude-namespaces`.
- **Resources:** `--include-resources` / `--exclude-resources` (например, `events` часто исключаются для экономии места).
- **Selectors:** `--selector` (фильтрация по меткам).
- **Orphaned Resources:** Автоматическая очистка ресурсов, не имеющих владельца (OwnerReference).

## Практические сценарии

### Установка через Helm (Рекомендуемый метод)
Использование Helm позволяет легко управлять жизненным циклом Velero и интегрироваться с GitOps (ArgoCD/Flux).

```bash
helm repo add vmware-tanzu https://vmware-tanzu.github.io/helm-charts
helm repo update

helm install velero vmware-tanzu/velero \
    --namespace velero \
    --create-namespace \
    --set-file credentials.secretContents.cloud=./credentials-velero \
    --set configuration.provider=aws \
    --set configuration.backupStorageLocation[0].name=default \
    --set configuration.backupStorageLocation[0].bucket=my-k8s-backups \
    --set configuration.backupStorageLocation[0].config.region=us-east-1 \
    --set configuration.volumeSnapshotLocation[0].name=default \
    --set configuration.volumeSnapshotLocation[0].config.region=us-east-1 \
    --set initContainers[0].name=velero-plugin-for-aws \
    --set initContainers[0].image=velero/velero-plugin-for-aws:v1.13.0 \
    --set initContainers[0].volumeMounts[0].mountPath=/plugins \
    --set initContainers[0].volumeMounts[0].name=plugins \
    --set deployNodeAgent=true \
    --set configuration.uploaderType=kopia
```

### Настройка Multiple Storage Locations
Для разделения бэкапов критических данных и временных окружений:
```bash
velero backup-location create secure-bsl \
    --provider aws \
    --bucket secure-backups \
    --config region=us-west-2 \
    --access-mode ReadWrite
```
# → Использование при создании бэкапа: `velero backup create ... --storage-location secure-bsl`

### Применение хуков для баз данных (Application Consistency)
Аннотации для Pod с PostgreSQL для обеспечения консистентности на уровне приложения:
```yaml
metadata:
  annotations:
    # Команда выполняется ВНУТРИ контейнера перед созданием снимка
    pre.backup.velero.io/command: '["/usr/bin/psql", "-c", "SELECT pg_start_backup('backup');"]'
    pre.backup.velero.io/container: "postgres"
    pre.backup.velero.io/timeout: "30s"
    # Команда выполняется после завершения снимка
    post.backup.velero.io/command: '["/usr/bin/psql", "-c", "SELECT pg_stop_backup();"]'
    post.backup.velero.io/container: "postgres"
```

### Восстановление с изменением параметров (Resource Modifiers)
Используется для смены `StorageClass` или изменения `image` при миграции:
```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: restore-modifiers
  namespace: velero
data:
  rules.yaml: |
    - conditions:
        groupResource: persistentvolumeclaims
      patches:
        - operation: replace
          path: /spec/storageClassName
          value: high-perf-ssd
```
```bash
velero restore create --from-backup my-backup --resource-modifier-configmap restore-modifiers
```

## Диагностика и устранение неисправностей

### Анализ статуса "PartialSuccess"
Часто возникает при ошибках в хуках или недоступности отдельных томов.
1.  **Проверка деталей:**
    ```bash
    velero backup describe <backup-name> --details
    ```
2.  **Просмотр логов плагинов:**
    ```bash
    velero backup logs <backup-name> | grep error
    ```
3.  **Ошибки CSI:** Проверьте состояние `VolumeSnapshot` и `VolumeSnapshotContent` объектов в Namespace приложения.

### Типовые проблемы
- **Timed out waiting for hooks:** Увеличьте `pre.backup.velero.io/timeout`.
- **Invalid volume ID:** Часто возникает при миграции между регионами облака без корректной настройки VSL.
- **Concurrent Backup Limit:** Если в кластере много бэкапов, Velero может встать в очередь. Настройте `--concurrent-backup-syncs` в конфигурации сервера.

## Дополнительная информация

### Безопасность и иммутабельность
- **Object Lock:** Использование режима *Compliance* в S3 предотвращает удаление бэкапов даже при компрометации API-ключей.
- **Шифрование:** Всегда используйте KMS-шифрование для бакетов BSL.
- **RBAC:** Доступ к ресурсам Velero должен быть строго ограничен.

### См. также
- **[Стратегии бэкапа в Kubernetes](../Operations/backup-strategies.md)** — общая методология и правило 3-2-1.
- **[Продвинутые возможности CSI](../Storage/CSI/csi_advanced.md)** — снапшоты и клонирование томов.
- **[Безопасность и шифрование бэкапов](../../Databases/Concepts/backup_security.md)** — защита данных в Object Storage.
- **[Валидация бэкапов](../../Databases/Concepts/backup_validation.md)** — сценарии автоматического тестирования восстановления.
