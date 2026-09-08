# Local Path Provisioner

## Определения

**Local Path Provisioner** — Kubernetes-провижинер от Rancher, позволяющий использовать локальное хранилище на узлах кластера через стандартный механизм PVC/PV. Он динамически создаёт `PersistentVolume` из пути на файловой системе хоста, являясь легковесной альтернативой сложным СХД и прямому использованию `HostPath`.

Является стандартным (default) решением для хранения данных в дистрибутиве **K3s**.

## Базовые концепции

### Принцип работы

Provisioner работает как `Deployment`, отслеживающий создание PVC с указанным `StorageClass`.

**Алгоритм при создании PVC:**

1. Под с PVC планируется планировщиком на конкретный узел.
2. Provisioner запускает временный "helper" под на этом же узле.
3. Helper под выполняет `mkdir -p` для создания директории в сконфигурированном пути (например, `/opt/local-path-provisioner/<pvc-name>`).
4. Создаётся `PersistentVolume`, указывающий на эту директорию.
5. PVC связывается с PV (статус `Bound`).

**При удалении PVC:**

- Helper под выполняет `rm -rf` для очистки директории (если Reclaim Policy — `Delete`).
- PV удаляется.

**Преимущество:** Абстракция от прямого использования `HostPath`, повышенная безопасность и упрощённое управление жизненным циклом томов.

### Сравнение с альтернативами

| Решение | Плюсы | Минусы | Когда использовать |
|---------|-------|--------|------------------|
| **Local Path Provisioner** | Простота, высокая производительность, стандартные PVC/PV | Данные привязаны к узлу, нет репликации, нет контроля ёмкости по умолчанию | Dev/Test, кэширование, временные данные, Edge/IoT |
| **HostPath** | Максимальная производительность | Небезопасно, требует ручного создания PV, сложно управлять в динамическом кластере | **Не рекомендуется** для общего использования |
| **NFS/Сетевые ФС** | Доступ со всех узлов, `ReadWriteMany` | Производительность ограничена сетью, требуется отдельный сервер | Общие данные, RWX-требования |
| **Longhorn/Ceph** | Репликация, миграция, снимки, отказоустойчивость | Высокая сложность, накладные расходы на CPU/Сеть | Production, важные данные ([Longhorn](./longhorn.md)) |

### Ограничения

| Ограничение | Описание | Обход / Решение |
|-------------|----------|-------|
| **Привязка к узлу** | Том физически на одном узле. При перемещении пода на другой узел доступ к данным теряется | Использовать `affinity` для жёсткой привязки подов к узлам |
| **Нет контроля ёмкости** | Размер PVC игнорируется. Приложение может занять всё пространство диска хоста | Отдельные диски/разделы, квоты на уровне LVM, мониторинг диска |
| **Только RWO** | Режим `ReadWriteMany` не поддерживается | Использовать NFS/CephFS для сценариев RWX |
| **Node failure** | При выходе узла из строя данные становятся недоступны до восстановления узла | Регулярные бэкапы или использование реплицируемых систем (Longhorn) |

### Безопасность

#### Критические уязвимости

**CVE-2025-62878 (Path Traversal, CVSS 10.0):** В версиях до **v0.0.34** существовала критическая уязвимость, позволявшая выполнять атаку "path traversal" через шаблоны путей в StorageClass, давая доступ к произвольным файлам хоста. **Обязательно обновитесь до v0.0.34+.**

**HelperPod Template Injection (v0.0.36):** Пользователь с правами редактирования ConfigMap `local-path-config` мог манипулировать шаблоном `helperPod.yaml` и создавать небезопасные helper-поды при provision или cleanup операциях. Версия **v0.0.36+** валидирует шаблон и отвергает потенциально опасные поля.

#### Валидация helperPod template (v0.0.36+)

Начиная с v0.0.36, шаблон `helperPod.yaml` валидируется перед принятием. Запрещено определять в шаблоне:

- `securityContext`
- `volumes` / `volumeMounts`
- `initContainers` / `ephemeralContainers`
- `envFrom` / `env.valueFrom`
- `lifecycle`, `livenessProbe`, `readinessProbe`, `startupProbe`
- Host-сетевые пространства (`hostNetwork`, `hostPID`, `hostIPC`)
- `spec.nodeName`, `spec.serviceAccountName`

Допустимо кастомизировать: `image` контейнера, `priorityClassName`, `tolerations`.

Если требуется привилегированный helper pod (например, для distroless-окружений), необходимо явно включить `--allow-unsafe-helper-pod-template` или переменную `ALLOW_UNSAFE_HELPER_POD_TEMPLATE=true` в деплойменте провижинера.

#### Hardening

- **RBAC:** Ограничьте доступ к редактированию ConfigMap `local-path-config` — содержащиеся скрипты (`setup`, `teardown`) выполняются от имени root на хостах.
- **Network Policy:** Рассмотрите ограничение сетевого доступа namespace `local-path-storage`, так как провижинер не требует внешних сетевых подключений.
- **Pod Security Admission:** Для кластеров с PSA в режиме `restricted` потребуется исключение (см. раздел "Устранение неисправностей").

### volumeBindingMode: WaitForFirstConsumer

**Критически важный параметр** для локальных хранилищ.

| Режим | Описание |
|-------|----------|
| `Immediate` | PV создаётся сразу при создании PVC. Риск: PV может быть создан на узле A, а планировщик позже решит запустить под на узле B |
| `WaitForFirstConsumer` | PV создаётся только ПОСЛЕ того, как под будет назначен на узел. Гарантирует совпадение места хранения и места запуска |

**Рекомендация:** Для Local Path Provisioner всегда используйте `WaitForFirstConsumer`.

## Практические сценарии

### Предварительные требования

| Компонент | Минимальная версия |
|-----------|-------------------|
| Kubernetes | v1.12+ |
| kubectl | Соответствующая версия кластера |
| Helm (опционально) | v3.x |

**Дополнительные зависимости:**
- На каждом узле должен быть доступен достаточный объём дискового пространства в конфигурированном пути (по умолчанию `/opt/local-path-provisioner`).
- Узлы не должны иметь taints, которые запрещают планирование helper-подов (кроме `node.kubernetes.io/disk-pressure`, который уже учтён в шаблоне по умолчанию).
- Для кластеров с включённым Pod Security Admission (PSA) в режиме `restricted` потребуется настроить исключение для namespace `local-path-storage`.

### Установка

Актуальная версия (август 2026): **v0.0.37**.

#### Способ 1: Манифест (YAML)

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.37/deploy/local-path-storage.yaml
```

#### Способ 2: Kustomize

```bash
kustomize build "github.com/rancher/local-path-provisioner/deploy?ref=v0.0.37" | kubectl apply -f -
```

#### Способ 3: Helm

```bash
helm repo add rancher https://charts.rancher.io
helm repo update
helm install local-path rancher/local-path-provisioner \
  --namespace local-path-storage \
  --create-namespace
```

#### Проверка установки

```bash
kubectl -n local-path-storage get pod -l app=local-path-provisioner
# → NAME                                     READY   STATUS    RESTARTS   AGE
# → local-path-provisioner-xxx              1/1     Running   0          7m

kubectl -n local-path-storage get sc local-path
# → NAME                 PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION   AGE
# → local-path           rancher.io/local-path   Delete          WaitForFirstConsumer   false                  7m
```

### Конфигурация

Настройка выполняется через `ConfigMap` `local-path-config` в пространстве имен установки. Конфигурация поддерживает горячую перезагрузку — при изменении ConfigMap провижинер автоматически подхватывает новые настройки (с задержкой в несколько секунд).

**Важно:** Поля `config.json`, `sharedFileSystemPath` и `storageClassConfigs` взаимоисключающие. При использовании одного из последних двух `nodePathMap` должен быть установлен в `[]`.

#### Структура ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: local-path-config
  namespace: local-path-storage
data:
  config.json: |
    {
      "nodePathMap": [...]
    }
  setup: |
    #!/bin/sh
    set -eu
    mkdir -m 0777 -p "$VOL_DIR"
  teardown: |
    #!/bin/sh
    set -eu
    rm -rf "$VOL_DIR"
  helperPod.yaml: |
    apiVersion: v1
    kind: Pod
    metadata:
      name: helper-pod
    spec:
      priorityClassName: system-node-critical
      containers:
      - name: helper-pod
        image: busybox
```

#### Параметры config.json

| Поле | Тип | Описание |
|------|-----|----------|
| `nodePathMap` | array | Маппинг узлов на директории для хранения данных |
| `nodePathMap[].node` | string | Имя узла или `DEFAULT_PATH_FOR_NON_LISTED_NODES` для значений по умолчанию |
| `nodePathMap[].paths` | array | Абсолютные пути на файловой системе узла. Если указано несколько — путь выбирается случайно |
| `sharedFileSystemPath` | string | Путь на общей файловой системе (NFS, CephFS), смонтированной на всех узлах. Поддерживает `ReadWriteMany` |
| `storageClassConfigs` | map | Маппинг имён StorageClass на объекты с `nodePathMap` или `sharedFilesystemPath` |

**Правила валидации config.json:**
- Путь должен начинаться с `/` (абсолютный путь).
- Корневая директория (`/`) запрещена.
- Дублирование путей для одного узла запрещено.
- Дублирование имён узлов запрещено.

#### Базовая конфигурация (один путь)

```json
{
  "nodePathMap": [
    {
      "node": "DEFAULT_PATH_FOR_NON_LISTED_NODES",
      "paths": ["/opt/local-path-provisioner"]
    }
  ]
}
```

#### Конфигурация для разных узлов

```json
{
  "nodePathMap": [
    {
      "node": "DEFAULT_PATH_FOR_NON_LISTED_NODES",
      "paths": ["/opt/local-path-provisioner"]
    },
    {
      "node": "worker-fast-ssd",
      "paths": ["/mnt/nvme-fast"]
    },
    {
      "node": "worker-disabled",
      "paths": []
    }
  ]
}
```

Узел с пустым массивом `paths: []` будет исключён из provisioning — провижинер откажется создавать тома на нём.

#### Общая файловая система (RWX)

Для сценариев, когда данные хранятся на общей файловой системе (NFS, GlusterFS, CephFS), смонтированной на всех узлах:

```json
{
  "nodePathMap": [],
  "sharedFileSystemPath": "/mnt/shared-storage"
}
```

При такой конфигурации поддерживаются все режимы доступа: `ReadWriteOnce`, `ReadOnlyMany`, `ReadWriteMany`.

#### Скрипты setup и teardown

Скрипты `setup` и `teardown` выполняются для подготовки и очистки директории тома. Доступные переменные окружения:

| Переменная | Описание |
|------------|----------|
| `VOL_DIR` | Директория тома для создания/удаления |
| `VOL_MODE` | Режим PV: `Block` или `Filesystem` |
| `VOL_SIZE_BYTES` | Запрошенный размер тома в байтах |
| `VOL_USER` | Пользователь, сформированный из `userPattern` |
| `VOL_GROUP` | Группа, сформированная из `groupPattern` |
| `VOL_PERM` | Права, сформированные из `permPattern` |

#### Параметры StorageClass

| Параметр | Описание |
|----------|----------|
| `nodePath` | Конкретный путь из `nodePathMap` для использования данной StorageClass |
| `pathPattern` | Go-шаблон для имени поддиректории. Доступны переменные `{{ .PVName }}`, `{{ .PVC.Namespace }}`, `{{ .PVC.Name }}`, а также лейблы и аннотации PVC |
| `hostDir` | Прямое указание директории хоста (перезаписывает `nodePathMap`) |
| `nodeAffinityKey` | Ключ метки узла для node affinity PV (по умолчанию `kubernetes.io/hostname`). Полезно при нестабильных именах узлов (v0.0.35+) |
| `userPattern` | Шаблон для установки UID владельца директории (v0.0.37+) |
| `groupPattern` | Шаблон для установки GID группы директории (v0.0.37+) |
| `permPattern` | Шаблон для установки прав доступа к директории (v0.0.37+) |
| `allowUnsafePathPattern` | `true` для отключения валидации `pathPattern` (опасно, только для доверенных конфигураций) |

**Пример StorageClass с кастомным путём и шаблоном:**

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path-custom
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
parameters:
  nodePath: /mnt/fast-ssd
  pathPattern: "{{ .PVC.Namespace }}/{{ .PVC.Name }}/"
  nodeAffinityKey: topology.kubernetes.io/zone
```

#### Аннотации для типа тома

Тип создаваемого тома (`hostPath` или `local`) задаётся через аннотации:

| Объект | Аннотация | Описание |
|--------|-----------|----------|
| PVC | `volumeType: local` или `volumeType: hostPath` | Тип для конкретного PVC |
| StorageClass | `defaultVolumeType: local` или `defaultVolumeType: hostPath` | Тип по умолчанию для всех PVC в данной StorageClass |

Аннотация PVC перезаписывает аннотацию StorageClass. По умолчанию используется `hostPath`.

**Примечание:** Тип `local` использует Kubernetes Local Persistent Volume (PV с `local` volume source), что обеспечивает строгую привязку к узлу. Тип `hostPath` использует обычный `hostPath` volume.

### Использование со StatefulSet

StatefulSet требует стабильных идентификаторов и привязки данных.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-sts-headless
spec:
  clusterIP: None
  selector:
    app: my-sts-app
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: my-sts
spec:
  serviceName: "my-sts-headless"
  replicas: 2
  selector:
    matchLabels:
      app: my-sts-app
  template:
    metadata:
      labels:
        app: my-sts-app
    spec:
      affinity:
        # Привязка к узлам с меткой worker=true
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - key: "node-role.kubernetes.io/worker"
                operator: In
                values: ["true"]
        # Распределение подов по разным узлам
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values: ["my-sts-app"]
            topologyKey: "kubernetes.io/hostname"
      containers:
      - name: nginx
        image: nginx:latest
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "local-path-ssd"
      resources:
        requests:
          storage: 1Gi
```

**Объяснение параметров affinity:**

| Параметр | Назначение |
|----------|------------|
| `nodeAffinity` | Гарантирует, что поды будут запускаться только на специализированных рабочих узлах |
| `podAntiAffinity` | Запрещает планировщику размещать два пода одного StatefulSet на одном физическом узле, предотвращая потерю всех реплик при сбое узла |

### Мониторинг и диагностика

#### Health Probes

Начиная с v0.0.33, провижинер поддерживает HTTP-пробы на порту `8080`:

| Проба | Путь | Назначение |
|-------|------|------------|
| Startup | `/health` | Проверка запуска контейнера (5 попыток, интервал 5с) |
| Liveness | `/health` | Проверка работоспособности (интервал 10с) |
| Readiness | `/ready` | Проверка готовности принимать трафик (интервал 5с) |

**Использование в Prometheus/Grafana:**

Для настройки мониторинга через ServiceMonitor (если установлен Prometheus Operator):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: local-path-provisioner
  namespace: monitoring
  labels:
    release: prometheus
spec:
  namespaceSelector:
    matchNames:
    - local-path-storage
  selector:
    matchLabels:
      app: local-path-provisioner
  endpoints:
  - port: health
    path: /health
    interval: 30s
```

**Кастомизация через Helm:**

При установке через Helm доступны параметры для настройки проб и логирования:

```bash
helm install local-path rancher/local-path-provisioner \
  --namespace local-path-storage \
  --create-namespace \
  --set image.debug=true \
  --set replicaCount=2
```

#### Логирование

```bash
# Логи провижинера (процесс создания/удаления томов)
kubectl logs -n local-path-storage -l app=local-path-provisioner -f

# Логи с меткой времени
kubectl logs -n local-path-storage -l app=local-path-provisioner --timestamps=true

# Последние 100 строк
kubectl logs -n local-path-storage -l app=local-path-provisioner --tail=100
```

#### Диагностика PVC

```bash
# Статус конкретного PVC
kubectl describe pvc <pvc-name>

# Все PVC в статусе Pending
kubectl get pvc --all-namespaces --field-selector=status.phase=Pending

# События, связанные с provisioner
kubectl get events -n local-path-storage --sort-by='.lastTimestamp'

# Статус PV
kubectl get pv <pv-name> -o yaml
```

### Устранение неисправностей (Troubleshooting)

#### PVC завис в Pending

| Симптом | Вероятная причина | Решение |
|---------|-------------------|---------|
| PVC в `Pending`, под не создаётся | `WaitForFirstConsumer` — провижинер ждёт назначения пода на узел | Проверьте `kubectl describe pod <pod-name>` на предмет нехватки ресурсов, несовпадения `nodeSelector` или taints |
| PVC в `Pending`, ошибка `ProvisioningFailed` | Узел не указан в `nodePathMap` и нет `DEFAULT_PATH_FOR_NON_LISTED_NODES` | Добавьте узел в ConfigMap или убедитесь, что `DEFAULT_PATH_FOR_NON_LISTED_NODES` настроен |
| PVC в `Pending`, `nodeAffinity` mismatch | PV создан на узле A, но под запланирован на узел B | Используйте `WaitForFirstConsumer` вместо `Immediate` |

#### Ошибки запуска Helper Pod

**Pod Security Admission (restricted mode):**
```bash
kubectl label ns local-path-storage pod-security.kubernetes.io/enforce=privileged
```

**Helper pod не может запуститься (ImagePullBackOff):**
- По умолчанию используется образ `busybox` из Docker Hub.
- В изолированных средах (air-gapped) настройте mirror registry или подключите образ вручную.

**Helper pod завершается с OOMKilled:**
- Увеличьте `resources.limits.memory` в `helperPod.yaml` шаблоне, если скрипты `setup`/`teardown` потребляют много памяти.

#### Проблемы с правами (Permission Denied)

| Сценарий | Решение |
|----------|---------|
| Контейнер запускается от non-root и не может писать в `volumeMount` | Настройте `fsGroup` в `securityContext` пода (например, `fsGroup: 1000`) |
| Директория создаётся с правами 0777, но приложение требует другие | Используйте `userPattern`/`groupPattern`/`permPattern` в StorageClass (v0.0.37+) или скрипт `setup` |
| SELinux блокирует доступ к файлам на хосте | Добавьте `chcon` в скрипт `setup` или отключите SELinux для директории хранения |

#### ConfigMap не применяется

**Симптом:** Изменения в ConfigMap не вступают в силу.

**Причины:**
1. Отсутствует переменная окружения `CONFIG_MOUNT_PATH=/etc/config/` в деплойменте провижинера.
2. В шаблоне `helperPod.yaml` добавлены запрещённые поля (v0.0.36+).
3. В `config.json` ошибка синтаксиса JSON.

**Диагностика:**
```bash
kubectl logs -n local-path-storage -l app=local-path-provisioner | grep -i "config"
# → Ищите строки с "Applied config" или "failed to load the new config"
```

#### Данные недоступны после перемещения пода

**Причина:** Local Path Provisioner хранит данные на конкретном узле. При перемещении пода на другой узел данные остаются на старом узле и недоступны.

**Решение:**
- Используйте `nodeAffinity` для жёсткой привязки пода к узлу (в StatefulSet или Deployment).
- Для Stateless-приложений используйте внешние системы хранения (NFS, Ceph, Longhorn).

#### Удаление PV в stuck-состоянии

```bash
# Принудительное удаление PV
kubectl patch pv <pv-name> -p '{"metadata":{"finalizers":null}}'
kubectl delete pv <pv-name>

# Удаление оставшейся директории на хосте (если ReclaimPolicy: Delete)
# Выполните на узле, где были данные:
rm -rf /opt/local-path-provisioner/pvc-*
```

## Дополнительная информация

### Резервное копирование и восстановление

Local Path Provisioner не предоставляет встроенных механизмов бэкапа. Данные хранятся как обычные директории на файловой системе хоста.

#### Ручной бэкап

```bash
# На узле, где расположен том (узнайте из PV: kubectl get pv <pv-name> -o yaml)
# Директория по умолчанию: /opt/local-path-provisioner/pvc-*

# Архивирование данных
tar -czf /backup/local-path-pvc-<name>.tar.gz -C /opt/local-path-provisioner pvc-*

# Восстановление
tar -xzf /backup/local-path-pvc-<name>.tar.gz -C /opt/local-path-provisioner/
```

#### Автоматический бэкап через CronJob

Для регулярного копирования данных на NFS или другой внешний накопитель:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: local-path-backup
  namespace: local-path-storage
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: alpine:latest
            command:
            - /bin/sh
            - -c
            - |
              apk add --no-cache rsync
              rsync -av --delete /source/ /backup/$(hostname)/
            volumeMounts:
            - name: source
              mountPath: /source
              readOnly: true
            - name: backup-nfs
              mountPath: /backup
          volumes:
          - name: source
            hostPath:
              path: /opt/local-path-provisioner
              type: Directory
          - name: backup-nfs
            nfs:
              server: nfs.example.com
              path: /exports/local-path-backup
          restartPolicy: OnFailure
```

#### Восстановление из бэкапа

1. Остановите поды, использующие PVC.
2. Восстановите данные на узле из архива.
3. Пересоздайте PVC и PV (если были удалены).
4. Запустите поды заново.

### Удаление (Uninstall)

#### Шаг 1: Удалите все PVC и PV

```bash
# Проверьте наличие PV, созданных провижинером
kubectl get pv -o wide | grep local-path

# Удалите все PVC, использующие StorageClass local-path
kubectl delete pvc --all -n default --field-selector=spec.storageClassName=local-path

# Убедитесь, что PV удалены (или удалите вручную)
kubectl get pv | grep local-path
kubectl delete pv <pv-name>
```

#### Шаг 2: Удалите provisioner

```bash
kubectl delete -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.37/deploy/local-path-storage.yaml
```

Или через Helm:

```bash
helm uninstall local-path -n local-path-storage
kubectl delete namespace local-path-storage
```

#### Шаг 3: Очистите данные на узлах (опционально)

```bash
# На каждом узле, где хранились данные:
rm -rf /opt/local-path-provisioner/
```

### Граничные случаи (Edge Cases)

#### Кластер с одним узлом

Local Path Provisioner работает в single-node кластере, но теряет benefit of node affinity. Все тома создаются на единственном узле, и при его отказе данные недоступны. Для single-node рассмотрите Longhorn с `replicaCount: 1`.

#### Нестабильные имена узлов (VM pools)

Если узлы пересоздаются с новыми именами (например, в облаке или при autoscaling), существующие PV становятся unschedulable из-за `nodeAffinity` с устаревшим hostname. Решение: используйте параметр `nodeAffinityKey` в StorageClass (v0.0.35+) для указания стабильной метки узла.

#### Быстрое заполнение диска

Провижинер не контролирует ёмкость. Если диск узла заполнен:
- Helper pod не сможет создать директорию → ошибки provisioning.
- Решение: настройте мониторинг диска (node_exporter + Prometheus алертинг) и установите квоты на уровне LVM/ZFS.

#### Одновременное удаление многих PVC

При массовом удалении PVC helper-поды выполняют `rm -rf` параллельно. На больших томах это может вызвать нагрузку на I/O. Рассмотрите кастомизацию скрипта `teardown` с добавлением задержек или последовательного удаления.

#### Ошибка в helperPod template (v0.0.36+)

Если в `helperPod.yaml` добавлены запрещённые поля (securityContext, volumes и т.д.), провижинер отвергнет шаблон и залогирует ошибку. Тома не будут создаваться до исправления шаблона. Проверьте логи:

```bash
kubectl logs -n local-path-storage -l app=local-path-provisioner | grep -i "validation"
```

- Базовые концепции хранения: [PersistentVolume и PVC](./pv_and_pvc.md).
- Альтернатива для RWX: [NFS Provisioner](./nfs-subdir-external-provisioner.md).
- Официальный репозиторий: [github.com/rancher/local-path-provisioner](https://github.com/rancher/local-path-provisioner).
