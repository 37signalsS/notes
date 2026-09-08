# Обзор Velero: Резервное копирование Kubernetes

## Определения

**Velero** (ранее Heptio Ark) — это Open Source инструмент (проект CNCF Sandbox, ныне Graduated) для безопасного резервного копирования и восстановления ресурсов кластера Kubernetes, а также для миграции данных между кластерами. Инструмент является стандартом де-факто в экосистеме Kubernetes для обеспечения катастрофоустойчивости (Disaster Recovery).

Ключевые возможности:
- **Резервное копирование объектов API:** сохранение YAML-манифестов (Deployments, ConfigMaps, Secrets, CRD, RBAC, NetworkPolicy и т.д.).
- **Снимки (Snapshots) постоянных томов:** использование CSI или нативных API облачных провайдеров.
- **Перемещение данных (Data Movement):** копирование снимков томов в удаленное объектное хранилище (S3-совместимое) для обеспечения переносимости и долгосрочного хранения.
- **Миграция:** упрощение переноса приложений между разными окружениями (on-prem, разные провайдеры).
- **Планирование (Scheduled Backups):** автоматизация создания копий с гибким сроком хранения (TTL).
- **Application Consistency:** выполнение pre/post-хуков на Pod для получения консистентных снимков баз данных.

## Основные концепции

### Архитектура

Velero работает по модели клиент-сервер, обеспечивая высокую степень изоляции и масштабируемости:

1. **Velero Server:** Deployment внутри кластера (по умолчанию в namespace `velero`). Слушает события создания Custom Resources (`Backup`, `Restore`, `Schedule`, `DownloadRequest`, `PodVolumeRestore`, `PodVolumeBackup`) и координирует работу плагинов. Также экспонирует метрики Prometheus на порту 8085.
2. **Velero CLI:** утилита для управления "извне", просмотра логов и инициации восстановления. Имеет собственный kubeconfig-контекст (параметр `--kubeconfig`).
3. **Node Agent (ранее Restic/Kopia DaemonSet):** DaemonSet, запускаемый на каждом узле. Необходим для резервного копирования файловой системы (FSB) и работы механизма Data Mover. Хранит локальный кэш репозитория Kopia/Restic.

**Поток данных при backup:**
1. CLI/API → создается CR `Backup` в namespace `velero`.
2. Velero Server инвокает контроллер, который через informer API собирает ресурсы согласно `selector`/`includeNamespaces`.
3. Метаданные ресурсов сериализуются в gzip tar и загружаются в `Backup Storage Location` (BSL).
4. Для каждого PVC вызывается либо CSI snapshot, либо node-agent запускает pod `velero-node-agent-<id>` для FSB/Kopia-upload.
5. Финальный статус `Completed` или `PartiallyFailed` записывается в `.status` CR.

### CRD Velero (основные)

| CRD | Назначение | Ключевые поля |
| :--- | :--- | :--- |
| `Backup` | Одноразовый бэкап | `spec.includedNamespaces`, `spec.snapshotVolumes`, `spec.ttl`, `spec.hooks` |
| `Restore` | Восстановление | `spec.backupName`, `spec.namespaceMappings`, `spec.resourceModifierConfigMap` |
| `Schedule` | Расписание | `spec.schedule` (cron), `spec.template` (поля Backup) |
| `BackupStorageLocation` | Куда класть метаданные/данные | `spec.provider`, `spec.objectStorage.bucket`, `spec.config` |
| `VolumeSnapshotLocation` | Где делать cloud-snapshot | `spec.provider`, `spec.config` |

### Механизмы резервного копирования данных

1. **CSI Snapshots:** предпочтительный метод. Velero взаимодействует с нативными объектами Kubernetes — `VolumeSnapshot` и `VolumeSnapshotContent` через CSI-драйвер.
   - **VolumeGroupSnapshots (v1.17+, GA в v1.18):** поддержка создания консистентных снимков для групп томов, что критично для распределенных баз данных (Ceph RBD, Portworx, AWS EBS).
   - Требует `VolumeSnapshotClass`, помеченный `csi.storage.k8s.io/snapshotter-secret` или работающий с дефолтным секретом.
2. **CSI Snapshot Data Movement (Data Mover):** механизм (введен в v1.14, стабилен с v1.16), позволяющий перемещать снимки томов в S3-совместимое хранилище (через node-agent + Kopia).
   - **В v1.18:** реализована поддержка **Cache Volumes** (выделенных кэширующих томов) для подов-загрузчиков, что решает проблемы с лимитами эфемерных дисков и ускоряет восстановление.
3. **File-system Backup (FSB):** используется для томов, не поддерживающих снимки, или для переносимости между типами СХД.
   - **Kopia:** основной и наиболее эффективный загрузчик с v1.14+. Поддерживает дедупликацию на стороне клиента, сжатие (zstd), инкрементальную передачу, шифрование AES-256, а также быструю верификацию.
   - **Restic:** legacy-механизм. В версиях v1.18+ поддержка путей Restic отключена для новых инсталляций (флаг `--use-restic` помечен deprecated). Рекомендуется мигрировать на Kopia.

### Локации хранения

- **Backup Storage Location (BSL):** определяет целевое объектное хранилище для метаданных (YAML) и данных томов (при использовании Data Mover/FSB). Поддерживает **Multiple Storage Locations**, что позволяет сегментировать бэкапы по критичности или командам (через `--storage-location` или `.spec.storageLocation` в `Backup`).
- **Volume Snapshot Location (VSL):** определяет параметры для облачных снимков (регион, Resource Group, параметры шифрования). С v1.10+ deprecated для CSI-провайдеров (используется `VolumeSnapshotClass`), но сохраняется для совместимости.

### Управление ресурсами и фильтрация

Velero предоставляет гранулярный контроль над составом копии:

- **Namespaces:** `--include-namespaces` / `--exclude-namespaces` (можно использовать glob `prod-*`).
- **Resources:** `--include-resources` / `--exclude-resources` (например, `events` и `backups.velero.io` часто исключаются, чтобы избежать рекурсии).
- **Selectors:** `--selector` (фильтрация по стандартным меткам K8s, можно несколько).
- **Orphaned Resources:** автоматическая очистка ресурсов без владельца (`OwnerReference`) при restore — параметр `--include-cluster-resources`.
- **Resource Modifiers:** использование ConfigMap с JSONPath-патчами для изменения атрибутов (StorageClass, образы, аннотации, namespace, nodeName) "на лету" при восстановлении в другой кластер.

### Жизненный цикл бэкапа

1. **Created** — CR создан, ожидает контроллера.
2. **InProgress** — идет сбор ресурсов и/или снимков.
3. **Completed** — успех. `.status.expiration` выставлен по `ttl`.
4. **PartiallyFailed** — есть ошибки в `.status.errors`, но часть ресурсов сохранена. Критично для алертинга.
5. **Failed** — критический сбой (например, BSL недоступен).
6. **Deleting** — выполняется удаление связанных объектов из BSL.

## Практические сценарии

### Установка через Helm с values.yaml (онлайн, MinIO)

Для сложных конфигураций удобнее использовать файл `values.yaml` вместо флага `--set`. Ниже — пример для S3-совместимого хранилища MinIO.

**Файл `velero-values.yaml`:**
```yaml
credentials:
  useSecret: true
  secretContents:
    cloud: |
      [default]
      aws_access_key_id=Keyid_ot_Minio
      aws_secret_access_key=Access_ot_Minio
configuration:
  backupStorageLocation:
    - name: default
      provider: aws
      bucket: velero
      default: true
      accessMode: ReadWrite
      config:
        region: minio
        s3ForcePathStyle: "true"
        s3Url: https://s3.minio.domain.local
        # insecureSkipTLSVerify: "true"  # если MinIO с самоподписанным TLS
        # caCert: LS0tLS1CRUdJTiBDRVJ...  # если есть ЦА
  volumeSnapshotLocation: []
deployNodeAgent: true
nodeAgent:
  disableHostPath: false
  podVolumePath: /var/lib/kubelet/pods
  pluginVolumePath: /var/lib/kubelet/plugins
```

**Установка:**
```bash
helm install velero vmware-tanzu/velero \
    -n velero --create-namespace \
    -f velero-values.yaml
```

### Оффлайн установка в закрытом контуре (Harbor + MinIO)

Если кластер не имеет доступа в Интернет, выполните установку через приватный реестр Harbor.

**Шаг 1. Подготовка пакетов на машине с доступом в Интернет:**

```bash
helm repo add vmware-tanzu https://vmware-tanzu.github.io/helm-charts
helm repo update
helm pull vmware-tanzu/velero --untar
cd velero

# Рендеринг манифестов для получения списка образов
helm template velero . -f values.yaml > rendered.yaml

# Выгрузка списка образов
grep -oE 'image:\s*"?[^"]+' rendered.yaml | sed -E 's/^image:\s*"?//; s/"$//' | sort -u > velero-images.txt

# Добавьте плагин для MinIO/S3 вручную (версию актуализируйте из values.yaml):
echo "docker.io/velero/velero-plugin-for-aws:v1.13.1" >> velero-images.txt

# Скачивание образов
for img in $(cat velero-images.txt); do
  docker pull "$img"
done

# Упаковка
docker save -o velero-images.tar $(cat velero-images.txt)
tar -cvf velero.tgz velero
```

**Шаг 2. Загрузка в Harbor:**

```bash
# Распаковка в закрытом контуре
tar -xvf velero.tgz
cd velero
helm package . -d .
helm push velero-*.tgz oci://harbor.domain.local/helm

# Загрузка образов
docker load -i velero-images.tar

# Тегирование и push
export HARBOR="harbor.domain.local"
export PROJECT="platform"
docker login ${HARBOR}
while read -r img; do
  new="${HARBOR}/${PROJECT}/${img}"
  docker tag "${img}" "${new}"
  docker push "${new}"
done < velero-images.txt
```

**Шаг 3. Настройка MinIO:**

В MinIO создайте пользователя `velero-s3` и бакет `velero-backup`. Если используется HTTPS с самоподписанным сертификатом, получите его содержимое в Base64:

```bash
cat ca.crt | base64 -w0
```

**Шаг 4. Файл переменных для оффлайн установки:**

```yaml
image:
  repository: harbor.domain.local/platform/docker.io/velero/velero
  imagePullSecrets:
    - harbor-pull
kubectl:
  image:
    repository: harbor.domain.local/platform/docker.io/bitnamilegacy/kubectl
    tag: "1.33"
initContainers:
  - name: velero-plugin-for-aws
    image: harbor.domain.local/platform/docker.io/velero/velero-plugin-for-aws:v1.13.1
    volumeMounts:
      - mountPath: /target
        name: plugins
credentials:
  useSecret: true
  secretContents:
    cloud: |
      [default]
      aws_access_key_id=Keyidddddddddd_ot_Minio
      aws_secret_access_key=Accesskeyyyy_ot_Minio
configuration:
  backupStorageLocation:
    - name: default
      provider: aws
      bucket: velero
      default: true
      accessMode: ReadWrite
      config:
        region: minio
        s3ForcePathStyle: "true"
        s3Url: https://s3.minio.domain.local
        # insecureSkipTLSVerify: "true"
        caCert: LS0tLS1CRUdJTiBDRVJ...
  volumeSnapshotLocation: []
deployNodeAgent: true
nodeAgent:
  disableHostPath: false
  podVolumePath: /var/lib/kubelet/pods
  pluginVolumePath: /var/lib/kubelet/plugins
```

**Шаг 5. Секрет для доступа к Harbor (если требуется авторизация):**

```bash
kubectl create ns velero
kubectl -n velero create secret docker-registry harbor-pull \
  --docker-server=harbor.k8s.domain.local \
  --docker-username='<USER>' \
  --docker-password='<PASS>' \
  --docker-email='devnull@example.com'
```

**Шаг 6. Установка:**

```bash
helm install velero oci://harbor.domain.local/helm/velero \
    -n velero --create-namespace \
    -f velero-values.yaml
```

**Проверка:**

```bash
kubectl -n velero get backupstoragelocation
# → NAME      PHASE       LAST VALIDATED   AGE   DEFAULT
# → default   Available   19s              26m   true

# Если недоступен — детали:
kubectl -n velero describe backupstoragelocation default
kubectl logs deployment/velero -n velero
```

### Тестовый бэкап и восстановление

**Шаг 1. Создание тестового namespace и данных:**

```yaml
# test-ns.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: velero-test
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: velero-test-config
  namespace: velero-test
data:
  test: "ok"
  owner: "velero"
  note: "restore-me"
```

```bash
kubectl apply -f test-ns.yaml
kubectl -n velero-test get configmap
```

**Шаг 2. Создание бэкапа:**

```yaml
# backup-test.yaml
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: velero-test-backup
  namespace: velero
spec:
  includedNamespaces:
    - velero-test
  ttl: 24h0m0s
```

```bash
kubectl apply -f backup-test.yaml

# Проверка статуса
kubectl -n velero get backups.velero.io velero-test-backup \
  -o jsonpath='{.status.phase}{"\n"}'
# → Completed
```

**Шаг 3. Удаление namespace и восстановление:**

```bash
kubectl delete ns velero-test
kubectl get ns velero-test
# → Terminating (ожидаем завершения)

# Восстановление
cat <<EOF | kubectl apply -f -
apiVersion: velero.io/v1
kind: Restore
metadata:
  name: velero-test-restore
  namespace: velero
spec:
  backupName: velero-test-backup
EOF

kubectl get ns velero-test
kubectl -n velero-test get configmap
# → velero-test-config восстановлен
```

Тест считается **успешным**, если:
- бэкап `velero-test-backup` перешел в `Completed`;
- namespace `velero-test` удалился;
- после restore namespace `velero-test` появился снова;
- ConfigMap `velero-test-config` вернулся.

### Автоматическое резервное копирование (Schedules)

Для автоматизации используется ресурс `Schedule`. Ниже — пример ежедневного бэкапа namespace `monitoring` с хранением 7 дней.

```yaml
# prom-graf-backup.yaml
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: prom-graf-daily
  namespace: velero
spec:
  schedule: "0 2 * * *"
  template:
    includedNamespaces:
      - monitoring
    defaultVolumesToFsBackup: true
    ttl: 168h
```

```bash
kubectl apply -f prom-graf-backup.yaml
kubectl -n velero get schedules
```

**Важно:** для бэкапа содержимого PVC должен быть включен `node-agent` (устанавливается при инициализации Velero через `deployNodeAgent: true`).

**Просмотр состоявшихся бэкапов по расписанию:**

```bash
velero schedule get
# → NAME             STATUS    SCHEDULE      LAST BACKUP   AGE
# → prom-graf-daily  Enabled   0 2 * * *     17m           15d

velero backup get --selector velero.io/schedule-name=prom-graf-daily
```

### Настройка Multiple Storage Locations

Для разделения бэкапов критических данных (long-term) и временных окружений:

```bash
velero backup-location create secure-bsl \
    --provider aws \
    --bucket secure-backups \
    --config region=us-west-2 \
    --access-mode ReadWrite

# [Результат] Использование при создании бэкапа:
velero backup create ... --storage-location secure-bsl
```

Для резервного хранилища только для чтения (например, для восстановления из DR-снимков):

```bash
velero backup-location create dr-readonly \
    --provider aws \
    --bucket dr-archive \
    --config region=us-east-1 \
    --access-mode ReadOnly
```

### Применение хуков для баз данных (Application Consistency)

Velero поддерживает три типа хуков: `pre` (перед бэкапом), `post` (после), `exec` (внутри backup/restore). Аннотации для Pod с PostgreSQL для сброса буферов на диск перед созданием снимка:

```yaml
metadata:
  annotations:
    # Команда выполняется ВНУТРИ контейнера перед созданием снимка
    pre.backup.velero.io/command: '["/usr/bin/psql", "-c", "SELECT pg_start_backup(\u0027backup\u0027);"]'
    pre.backup.velero.io/container: "postgres"
    pre.backup.velero.io/timeout: "30s"
    # Команда выполняется после завершения снимка
    post.backup.velero.io/command: '["/usr/bin/psql", "-c", "SELECT pg_stop_backup();"]'
    post.backup.velero.io/container: "postgres"
```

**Альтернативный способ через `spec.hooks` (для случаев, когда аннотации невозможны):**

```yaml
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: postgres-with-hook
  namespace: velero
spec:
  includedNamespaces:
    - db
  hooks:
    - namespaces:
        - db
      resources:
        - pods
      pre:
        - name: freeze-pg
          exec:
            container: postgres
            command:
              - /bin/sh
              - -c
              - psql -c "SELECT pg_start_backup('velero-snap');"
            timeout: 60s
      post:
        - name: thaw-pg
          exec:
            container: postgres
            command:
              - /bin/sh
              - -c
              - psql -c "SELECT pg_stop_backup();"
```

### Восстановление с изменением параметров (Resource Modifiers)

Сценарий миграции, где целевой кластер имеет другой `StorageClass` и имена namespace:

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
    - conditions:
        groupResource: deployments.apps
      patches:
        - operation: replace
          path: /spec/template/spec/containers/0/image
          value: registry.internal/myapp:1.2.3
    - conditions:
        groupResource: namespaces
      patches:
        - operation: replace
          path: /metadata/name
          value: prod-restored
```

```bash
velero restore create --from-backup my-backup \
  --resource-modifier-configmap restore-modifiers \
  --namespace-mappings production:prod-restored
```

### Восстановление отдельных ресурсов

Восстановление только одного PVC/Deployment из большого бэкапа (быстрее, не требует полного разворачивания):

```bash
# Список ресурсов в бэкапе
velero backup describe my-backup --details

# Восстановление одного PVC
velero restore create selective-restore \
  --from-backup my-backup \
  --include-resources persistentvolumeclaims \
  --selector app=critical-db \
  --namespace-mappings prod:db-restore

# Или восстановление всего, кроме ненужного
velero restore create filtered-restore \
  --from-backup my-backup \
  --exclude-resources deployments,services \
  --include-namespaces monitoring
```

### Удаление бэкапов и ротация

```bash
# Удалить конкретный бэкап (метаданные + объекты в BSL)
velero backup delete my-backup --confirm

# Удалить все завершившиеся с ошибкой
velero backup delete --selector velero.io/status=PartiallyFailed --confirm

# Получить список истекших (по TTL) и удалить
velero backup get -o json | jq -r '.items[] | select(.status.expiration != null and .status.expiration < now) | .metadata.name' | xargs -I {} velero backup delete {} --confirm
```

### Обновление Velero (Helm)

```bash
# Проверка доступной версии
helm search repo vmware-tanzu/velero --versions

# Обновление с сохранением CRD и BSL
helm upgrade velero vmware-tanzu/velero \
    -n velero \
    -f velero-values.yaml \
    --version <NEW_VERSION>

# ВАЖНО: между мажными версиями проверяйте CHANGELOG.
# При переходе с v1.10 → v1.14+ выполните миграцию Restic → Kopia (см. ниже).
```

### Миграция с Restic на Kopia

В v1.14+ Kopia стал рекомендуемым uploader. Миграция требуется, если ранее использовался Restic (старые бэкапы остаются валидными, но новые создаются на Kopia):

```bash
# 1. Проверить текущий uploader
kubectl -n velero get deployment velero -o jsonpath='{.spec.template.spec.containers[0].args}' | grep uploader-type
# → Если пусто или "restic" — нужна миграция

# 2. Обновить Velero с новым values (uploader-type: kopia)
helm upgrade velero vmware-tanzu/velero \
    -n velero \
    --set deployNodeAgent=true \
    --set uploaderType=kopia \
    -f velero-values.yaml

# 3. Дождаться перезапуска подов
kubectl -n velero rollout status deployment/velero
kubectl -n velero rollout status daemonset/node-agent

# 4. Новые бэкапы будут на Kopia. Старые Restic-бэкапы читаемы.
```

## Диагностика и устранение неисправностей

### Анализ статуса PartialSuccess

Указывает на то, что бэкап создан, но часть ресурсов или томов не была сохранена.

1. **Проверка деталей:**
   ```bash
   velero backup describe <backup-name> --details
   ```
2. **Просмотр логов плагинов:**
   ```bash
   velero backup logs <backup-name> | grep -i error
   ```
3. **Ошибки CSI:** проверьте состояние `VolumeSnapshot` и `VolumeSnapshotContent` объектов в Namespace приложения. Часто причина в отсутствии `VolumeSnapshotClass` с подходящим драйвером.

### Диагностика подов Node Agent (FSB/Kopia)

```bash
# Статус DaemonSet
kubectl -n velero get ds node-agent

# Логи на конкретном узле
kubectl -n velero logs -l name=node-agent --prefix=true --tail=200

# Проверка подключенных PodVolumeBackup/PodVolumeRestore (CR node-agent)
kubectl -n velero get podvolumebackup -o wide
kubectl -n velero get podvolumerestore -o wide
```

### Типовые проблемы

- **Timed out waiting for hooks:** увеличьте `pre.backup.velero.io/timeout` (или `spec.hooks.pre.exec.timeout`). Команда в хуке должна завершаться за указанное время.
- **Invalid volume ID:** возникает при миграции между регионами/кластерами без корректной настройки VSL/VolumeSnapshotClass (проверьте соответствие региона и драйвера в конфиге).
- **Concurrent Backup Limit:** если в кластере много бэкапов одновременно, Velero ставит их в очередь. В v1.16+ настраивается через `--default-backup-ttl`, `--backup-ttl-uptime-percentage` и флаги `--concurrent-backup-syncs`/`--concurrent-restore-syncs` (CLI-параметры при install).
- **BSL Unavailable (`phase: Unavailable`):** чаще всего — сетевая недоступность S3, неверные credentials или истекший сертификат. Проверьте `kubectl -n velero describe bsl`.
- **Backup stuck in `WaitingForPluginOperation`:** плагин не отвечает. Проверьте, запущены ли поды с initContainer плагина (`kubectl -n velero get pod -o jsonpath='{.items[*].spec.initContainers[*].image}'`).
- **`kubectl plugin for velero` отсутствует:** установите Krew (`kubectl krew install velero`) — предоставляет `kubectl velero` shortcuts.
- **MemoryPressure у node-agent при больших PV:** настройте `nodeAgent.podResources` (limits.memory), увеличьте `--fs-backup-timeout` или используйте Data Mover (CSI snapshot → BSL) вместо FSB.
- **`backup attempt failed because secret ... was not found`:** Velero не может получить credentials для snapshot. Проверьте, что `VolumeSnapshotClass` ссылается на существующий Secret в namespace snapshot-класса (параметр `csi.storage.k8s.io/snapshotter-secret-name`).

### Восстановление после полной потери кластера

```bash
# 1. Установить свежий кластер K8s той же версии (или близкой)
# 2. Установить Velero с тем же BSL
velero install --provider aws --bucket velero-backups --secret-file ./creds --use-node-agent

# 3. Дождаться синхронизации (Velero обнаружит существующие бэкапы)
velero backup get
# → Все бэкапы из BSL будут видны

# 4. Восстановить базовую инфраструктуру (CRD, StorageClass)
velero restore create infra-restore --from-backup infra-pre

# 5. Восстановить приложения
velero restore create apps-restore --from-backup apps-latest
```

## Мониторинг и метрики

Velero Server и Node Agent экспонируют метрики Prometheus.

**ServiceMonitor (operator-based Prometheus):**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: velero
  namespace: velero
  labels:
    release: prometheus  # имя Helm-релиза Prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: velero
  endpoints:
    - port: monitoring
      path: /metrics
      interval: 30s
```

**Ключевые метрики:**

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `velero_backup_total` | Counter | Всего бэкапов по статусу (`success`/`failed`/`partial`) |
| `velero_backup_last_success_timestamp_seconds` | Gauge | Unix-время последнего успешного бэкапа |
| `velero_backup_attempt_total` | Counter | Всего попыток бэкапа (включая неуспешные) |
| `velero_restore_total` | Counter | Всего restore-операций |
| `velero_volume_snapshot_attempt_total` | Counter | Попытки создания CSI-снапшотов |
| `velero_backup_duration_seconds_bucket` | Histogram | Длительность бэкапа |
| `node_agent_pod_volume_backup_total` | Counter | Успешные FSB-бэкапы подов |
| `node_agent_pod_volume_backup_errors_total` | Counter | Ошибки FSB |

**Пример алерта на отсутствие свежих бэкапов (≥24h):**

```yaml
- alert: VeleroBackupStale
  expr: time() - velero_backup_last_success_timestamp_seconds > 86400
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "Velero backup отсутствует более 24ч"
    description: "Последний успешный бэкап Velero был {{ $value | humanizeDuration }} назад."
```

## Безопасность и RBAC

### Минимальный RBAC для разработчиков (namespace-scoped)

Разработчикам часто нужна возможность восстанавливать бэкапы только в свои namespace. Создайте `Role` + `RoleBinding`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: velero-restore-dev
  namespace: dev-team-a
rules:
  - apiGroups: ["velero.io"]
    resources: ["restores"]
    verbs: ["create", "get", "list", "watch"]
  - apiGroups: ["velero.io"]
    resources: ["backups"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: velero-restore-dev
  namespace: dev-team-a
subjects:
  - kind: Group
    name: dev-team-a
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: velero-restore-dev
  apiGroup: rbac.authorization.k8s.io
```

Доступ к созданию бэкапов (`backups.create`) и изменению BSL — только cluster-admin.

### Безопасность и иммутабельность бэкапов

- **Object Lock:** использование режима *Compliance* в S3 предотвращает удаление бэкапов даже при компрометации API-ключей (WORM — Write Once Read Many).
- **Шифрование:** всегда используйте KMS-шифрование (SSE-KMS) для бакетов BSL. Kopia дополнительно шифрует данные на стороне клиента паролем из `--default-volumes-to-restic-secret-file` или переменной `KOPIA_PASSWORD`.
- **Network Policies:** ограничьте egress от namespace `velero` только к адресам S3/MinIO. Inress не требуется.
- **ServiceAccount:** Velero Server работает под SA `velero` в namespace `velero`. Не давайте этой SA больше прав, чем требуется (см. Helm chart → `rbac`).

### Шифрование данных Kopia

```bash
# Генерация пароля и сохранение в Secret
KOPIA_PWD=$(openssl rand -base64 32)
kubectl -n velero create secret generic kopia-password \
  --from-literal=password="$KOPIA_PWD"

# Указать в values.yaml
# credentials:
#   existingSecret: kopia-password
# или (если используется Velero install CLI):
velero install ... --kopia-password-file ./kopia.pwd
```

## Производительность и тюнинг

### Параллелизм и ресурсы

```yaml
# values.yaml
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 2000m
    memory: 2Gi
# Параллелизм настраивается через CLI install:
# --concurrency 4 (параллельных backup-операций на кластер)
# или параметр конфигурации сервера (см. configmap)
```

### Уменьшение размера бэкапа

- Исключайте нерелевантные ресурсы: `velero backup create ... --exclude-resources events,endpointslices --exclude-namespaces kube-system,velero`.
- Используйте `selector` для бэкапа только критичных приложений.
- Включайте TTL для автоудаления: `spec.ttl: 168h`.
- Не бэкапите Local PV большого размера через FSB (используйте Data Mover + CSI snapshot).

### Сравнение uploader-типов: Kopia vs Restic

| Параметр | Kopia | Restic |
| :--- | :--- | :--- |
| Дедупликация | Глобальная (по содержимому) | По блокам фиксированного размера |
| Сжатие | zstd/lz4 (быстрое) | Без сжатия по умолчанию |
| Шифрование | AES-256 (встроенное) | AES-256 (встроенное) |
| Инкремент | Эффективный, малый overhead | Средний |
| Скорость восстановления | Высокая (параллельное чтение) | Средняя |
| Maintenance | Активно развивается | Legacy, deprecated в v1.18 |
| Repository | Несовместим с Restic | Несовместим с Kopia |
| Рекомендация | Для всех новых установок | Только для совместимости со старыми бэкапами |

## Провайдеры и плагины

Velero поддерживает множество провайдеров через плагины (Docker images):

| Плагин | Провайдер | Назначение |
| :--- | :--- | :--- |
| `velero-plugin-for-aws` | AWS S3, MinIO, любой S3-совместимый | BSL для S3 |
| `velero-plugin-for-microsoft-azure` | Azure Blob Storage | BSL для Azure |
| `velero-plugin-for-gcp` | Google Cloud Storage | BSL для GCS |
| `velero-plugin-for-csi` | Любой CSI-драйвер | VolumeSnapshot через CSI API |
| `velero-plugin-for-oss` | Alibaba OSS | BSL для Alibaba |
| `velero-plugin-for-eks` | AWS EKS | Интеграция с EKS |

**Установка нескольких плагинов одновременно:**

```bash
velero install \
    --provider aws \
    --bucket velero-bucket \
    --secret-file ./creds \
    --plugins velero/velero-plugin-for-aws:v1.13.1,velero/velero-plugin-for-csi:v0.8.0 \
    --use-node-agent
```

## Совместимость версий и ограничения

- **Версия K8s:** Velero v1.14+ требует K8s ≥ 1.22. Velero v1.16+ рекомендует K8s ≥ 1.25.
- **CSI:** Требуется CSI-драйвер с поддержкой snapshot (не все драйверы поддерживают `VolumeSnapshotClass`).
- **CRD-конфликты:** при restore Velero пытается восстановить CRD сначала. Если версия CRD в целевом кластере устарела, ресурсы не восстановятся.
- **`pvs/pvcs` и `StorageClass`:** Velero не бэкапит `StorageClass`. Если класс отсутствует в целевом кластере, PVC зависнет в `Pending`.
- **Helm releases:** Velero по умолчанию НЕ восстанавливает Helm-managed ресурсы корректно (из-за аннотаций `meta.helm.sh/release-name`). Используйте `--include-cluster-resources=true` с осторожностью или восстанавливайте через `helm template | kubectl apply`.
- **NodeAgent на Windows-узлах:** FSB на Windows ограничен (только NTFS, без дедупликации). Рекомендуется Linux-ноды для критичных workload.

## Дополнительная информация

### Полезные команды

```bash
# Список всех бэкапов с деталями
velero backup get -A

# Экспорт описания в JSON для автоматизации
velero backup describe my-backup --details --output json > backup-desc.json

# Скачивание архива ресурсов из бэкапа
velero backup download my-backup -o ./restore-test/

# Удаление всех бэкапов старше 30 дней (одной строкой)
velero backup get -o json | \
  jq -r '.items[] | select((.status.expiration // .metadata.creationTimestamp | fromdateiso8601) < (now - 2592000)) | .metadata.name' | \
  xargs -I {} velero backup delete {} --confirm

# Проверка версии Velero и плагинов
velero version
velero plugin get
```

### Метрики SLO

| Метрика | Целевое значение |
| :--- | :--- |
| Успешность бэкапов | ≥ 99% за 30 дней |
| Время восстановления (RTO) | ≤ 30 минут для namespace ≤ 100GB |
| Возраст последнего успешного бэкапа | ≤ 24 часа для production |
| Покрытие namespace'ов | 100% production namespace'ов |

### Чеклист внедрения

- [ ] Выбрать uploader (Kopia рекомендуется)
- [ ] Настроить BSL с KMS-шифрованием и Object Lock
- [ ] Создать namespace `velero`, установить Helm chart
- [ ] Включить `node-agent` если есть stateful-нагрузки
- [ ] Настроить `Schedule` для каждого критичного namespace
- [ ] Настроить TTL по политике хранения
- [ ] Интегрировать ServiceMonitor + алерты в Prometheus
- [ ] Написать RBAC для разработчиков (только restore в свой namespace)
- [ ] Провести тестовое восстановление в изолированный namespace
- [ ] Задокументировать Disaster Recovery Plan

### Интеграция с Storage: практические сценарии

#### Velero + Longhorn

Longhorn нативно поддерживает CSI Snapshots. Для интеграции:

```yaml
# VolumeSnapshotClass для Longhorn
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: longhorn-snapclass
  labels:
    velero.io/csi-volumesnapshot-class: "true"
driver: driver.longhorn.io
deletionPolicy: Retain
```

**Особенности:**
- Longhorn создаёт инкрементальные снимки через COW (Copy-on-Write).
- Velero использует `VolumeSnapshotClass` с лейблом `velero.io/csi-volumesnapshot-class: "true"` для автоматического выбора.
- Для данных за пределами Longhorn (NFS-шары) используйте FSB/Kopia через node-agent.

#### Velero + Ceph RBD

```yaml
# VolumeSnapshotClass для Ceph RBD
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ceph-rbd-snapclass
  labels:
    velero.io/csi-volumesnapshot-class: "true"
driver: rbd.csi.ceph.com
deletionPolicy: Retain
parameters:
  csi.storage.k8s.io/snapshot-secret-name: ceph-secret
  csi.storage.k8s.io/snapshot-secret-namespace: default
```

**Особенности:**
- Ceph RBD поддерживает `VolumeGroupSnapshots` — согласованные снимки нескольких томов (GA в v1.36).
- Для межкластерной миграции: Velero бэкап + Ceph RBD Mirroring.
- `deletionPolicy: Retain` гарантирует, что снимок останется в Ceph даже при удалении объекта `VolumeSnapshot` в K8s.

#### Velero + NFS

```yaml
# VolumeSnapshotClass для NFS CSI
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: nfs-snapclass
  labels:
    velero.io/csi-volumesnapshot-class: "true"
driver: nfs.csi.k8s.io
deletionPolicy: Delete
```

**Особенности:**
- NFS CSI-драйвер создаёт «снимки» как архивы `.tar.gz` на NFS-сервере (не нативные снимки ФС).
- Для больших томов предпочтительнее FSB/Kopia вместо CSI snapshots.
- Восстановление создаёт новый подкаталог на NFS-шаре.

#### Application-Consistency: хуки для PostgreSQL

```yaml
apiVersion: v1
kind: Pod
metadata:
  annotations:
    pre.hook.backup.velero.io/command: '["/bin/sh", "-c", "pg_dump -U postgres -Fc -f /backup/dump.db mydb"]'
    pre.hook.backup.velero.io/container: "postgres"
    pre.hook.backup.velero.io/timeout: "300s"
    post.hook.backup.velero.io/command: '["/bin/sh", "-c", "rm -f /backup/dump.db"]'
    post.hook.backup.velero.io/container: "postgres"
spec:
  containers:
  - name: postgres
    image: postgres:16
    volumeMounts:
    - name: backup
      mountPath: /backup
```

#### Application-Consistency: хуки для MySQL

```yaml
metadata:
  annotations:
    pre.hook.backup.velero.io/command: '["/bin/sh", "-c", "mysqldump -u root -p\"$MYSQL_ROOT_PASSWORD\" --all-databases > /backup/dump.sql"]'
    pre.hook.backup.velero.io/container: "mysql"
    post.hook.backup.velero.io/command: '["/bin/sh", "-c", "rm -f /backup/dump.sql"]'
    post.hook.backup.velero.io/container: "mysql"
```

#### StorageClass Mapping при межкластерной миграции

При восстановлении в другой кластер имена StorageClass могут различаться. Используйте Resource Modifiers:

```yaml
# resource-modifiers.yaml
- group: ""
  resourceNames: ["pvc-old-storage"]
  patchPath: {"spec":{"storageClassName":"new-fast-ssd"}}
---
# Применение:
velero restore create my-restore \
  --from-backup my-backup \
  --resource-modifier-configmap resource-modifiers
```

### См. также

- **[Стратегии бэкапа в Kubernetes](../Operations/backup-strategies.md)** — общая методология и правило 3-2-1.
- **[Продвинутые возможности CSI](../Storage/CSI/csi_advanced.md)** — снапшоты и клонирование томов.
- **[Валидация бэкапов](../../Databases/Concepts/backup_validation.md)** — сценарии автоматического тестирования восстановления.
- **[Storage — выбор хранилища](../Storage/storage-decision-matrix.md)** — матрица решений для разных workload-ов.
- **[Storage — репликация и DR](../Storage/storage-replication-dr.md)** — стратегии репликации между кластерами.
