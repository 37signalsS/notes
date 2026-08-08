# Обзор Velero: Резервное копирование Kubernetes

## Определения

**Velero** (ранее Heptio Ark) — это Open Source инструмент (проект CNCF Sandbox) для безопасного резервного копирования и восстановления ресурсов кластера Kubernetes, а также для миграции данных между кластерами. Инструмент является стандартом де-факто в экосистеме Kubernetes для обеспечения катастрофоустойчивости (Disaster Recovery).

Ключевые возможности:
- **Резервное копирование объектов API:** сохранение YAML-манифестов (Deployments, ConfigMaps, Secrets, CRD и т.д.).
- **Снимки (Snapshots) постоянных томов:** использование CSI или нативных API облачных провайдеров.
- **Перемещение данных (Data Movement):** копирование снимков томов в удаленное объектное хранилище (S3/Azure Blob/GCS) для обеспечения переносимости и долгосрочного хранения.
- **Миграция:** упрощение переноса приложений между разными облаками или on-premise средами.
- **Планирование (Scheduled Backups):** автоматизация создания копий с гибким сроком хранения (TTL).

## Основные концепции

### Архитектура
Velero работает по модели клиент-сервер, обеспечивая высокую степень изоляции и масштабируемости:
1.  **Velero Server:** Deployment внутри кластера. Слушает события создания Custom Resources (Backup, Restore, Schedule, DownloadRequest) и координирует работу плагинов.
2.  **Velero CLI:** утилита для управления "извне", просмотра логов и инициации восстановления.
3.  **Node Agent (ранее Restic/Kopia):** DaemonSet, запускаемый на каждом узле. Необходим для резервного копирования файловой системы (FSB) и работы механизма Data Mover.

### Механизма резервного копирования данных
1.  **CSI Snapshots:** предпочтительный метод. Velero взаимодействует с нативными объектами Kubernetes — `VolumeSnapshot` и `VolumeSnapshotContent`. 
    *   **VolumeGroupSnapshots (v1.17+):** поддержка создания консистентных снимков для групп томов, что критично для распределенных баз данных.
2.  **CSI Snapshot Data Movement (Data Mover):** механизм (введен в v1.14), позволяющий перемещать облачные снимки в S3.
    *   **В v1.18:** реализована поддержка **Cache Volumes** (выделенных кэширующих томов) для подов-загрузчиков, что решает проблемы с лимитами эфемерных дисков и ускоряет восстановление.
3.  **File-system Backup (FSB):** используется для томов, не поддерживающих снимки, или для переносимости между типами СХД.
    *   **Kopia:** основной и наиболее эффективный загрузчик. Поддерживает дедупликацию на стороне клиента, сжатие и инкрементальную передачу.
    *   **Restic:** устаревший механизм. В версиях v1.18+ поддержка legacy-путей Restic отключена для новых инсталляций.

### Локации хранения (Storage Locations)
- **Backup Storage Location (BSL):** определяет целевое объектное хранилище для метаданных (YAML) и данных томов (при использовании Data Mover). Поддерживает **Multiple Storage Locations**, что позволяет сегментировать бэкапы по критичности или командам.
- **Volume Snapshot Location (VSL):** определяет параметры для облачных снимков (регион, Resource Group, параметры шифрования KMS).

### Управление ресурсами и фильтрация
Velero предоставляет гранулярный контроль над составом копии:
- **Namespaces:** `--include-namespaces` / `--exclude-namespaces`.
- **Resources:** `--include-resources` / `--exclude-resources` (например, `events` и `backups.velero.io` часто исключаются).
- **Selectors:** `--selector` (фильтрация по стандартным меткам K8s).
- **Orphaned Resources:** автоматическая очистка ресурсов без владельца (`OwnerReference`).
- **Resource Modifiers:** использование ConfigMap для изменения атрибутов (StorageClass, образы, аннотации) "на лету" при восстановлении в другой кластер.

## Практические сценарии

### Установка через Helm (v1.18+)

Рекомендуется использовать Helm для интеграции с GitOps и управления версиями плагинов.

```bash
helm repo add vmware-tanzu https://vmware-tanzu.github.io/helm-charts
helm repo update

# Установка с поддержкой CSI и Data Mover (Data Movement)
helm install velero vmware-tanzu/velero \
    --namespace velero \
    --create-namespace \
    --set configuration.features=EnableCSI \
    --set-file credentials.secretContents.cloud=./credentials-velero \
    --set configuration.provider=aws \
    --set configuration.backupStorageLocation[0].name=default \
    --set configuration.backupStorageLocation[0].bucket=my-k8s-backups \
    --set configuration.backupStorageLocation[0].config.region=us-east-1 \
    --set configuration.volumeSnapshotLocation[0].name=default \
    --set configuration.volumeSnapshotLocation[0].config.region=us-east-1 \
    --set initContainers[0].name=velero-plugin-for-aws \
    --set initContainers[0].image=velero/velero-plugin-for-aws:v1.13.0 \
    --set deployNodeAgent=true \
    --set configuration.uploaderType=kopia
```

### Настройка Multiple Storage Locations
Для разделения бэкапов критических данных (long-term) и временных окружений:
```bash
velero backup-location create secure-bsl \
    --provider aws \
    --bucket secure-backups \
    --config region=us-west-2 \
    --access-mode ReadWrite
```
# [Результат] Использование при создании бэкапа: `velero backup create ... --storage-location secure-bsl`

### Применение хуков для баз данных (Application Consistency)
Аннотации для Pod с PostgreSQL для сброса буферов на диск перед созданием снимка:
```yaml
metadata:
  annotations:
    # Команда выполняется ВНУТРИ контейнера перед созданием снимка
    pre.backup.velero.io/command: '["/usr/bin/psql", "-c", "SELECT pg_start_backup(\'backup\');"]'
    pre.backup.velero.io/container: "postgres"
    pre.backup.velero.io/timeout: "30s"
    # Команда выполняется после завершения снимка
    post.backup.velero.io/command: '["/usr/bin/psql", "-c", "SELECT pg_stop_backup();"]'
    post.backup.velero.io/container: "postgres"
```

### Восстановление с изменением параметров (Resource Modifiers)
Сценарий миграции, где целевой кластер имеет другой `StorageClass`:
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

### Анализ статуса PartialSuccess
Указывает на то, что бэкап создан, но часть ресурсов или томов не была сохранена.
1.  **Проверка деталей:**
    ```bash
    velero backup describe <backup-name> --details
    ```
2.  **Просмотр логов плагинов:**
    ```bash
    velero backup logs <backup-name> | grep error
    ```
3.  **Ошибки CSI:** проверьте состояние `VolumeSnapshot` и `VolumeSnapshotContent` объектов в Namespace приложения. Часто причина в отсутствии `VolumeSnapshotClass`.

### Типовые проблемы
- **Timed out waiting for hooks:** увеличьте `pre.backup.velero.io/timeout`. Команда в хуке должна завершаться за указанное время.
- **Invalid volume ID:** возникает при миграции между регионами облака без корректной настройки VSL (проверьте соответствие региона в конфиге).
- **Concurrent Backup Limit:** если в кластере много бэкапов, Velero может встать в очередь. В v1.18+ используйте флаг `--concurrent-backup-syncs` в конфигурации сервера.

## Дополнительная информация

### Безопасность и иммутабельность
- **Object Lock:** использование режима *Compliance* в S3 предотвращает удаление бэкапов даже при компрометации API-ключей.
- **Шифрование:** всегда используйте KMS-шифрование (SSE-KMS) для бакетов BSL.
- **RBAC:** доступ к ресурсам Velero (`backups`, `restores`, `schedules`) должен быть строго ограничен ролью `velero-server`.

### См. также
- **[Стратегии бэкапа в Kubernetes](../Operations/backup-strategies.md)** — общая методология и правило 3-2-1.
- **[Продвинутые возможности CSI](../Storage/CSI/csi_advanced.md)** — снапшоты и клонирование томов.
- **[Валидация бэкапов](../../Databases/Concepts/backup_validation.md)** — сценарии автоматического тестирования восстановления.
