# CreateContainerConfigError: Проблемы с томами

## Определения

**Volume-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки среды выполнения контейнера, когда `kubelet` не может успешно разрешить и подготовить тома из секции `volumes` PodSpec. Это блокирует создание контейнера в рантайме (CRI), так как конфигурация монтирования (bind mounts) не может быть сформирована.

В отличие от проблем с PersistentVolumeClaim (PVC), которые обычно приводят к `ContainerCreating` или `Pending`, этот тип ошибки связан с **локальными** ресурсами узла: emptyDir, hostPath, ConfigMap/Secret как тома, Projected Volumes, а также CSI inline-томами. Ошибка возникает до вызова Container Runtime, поэтому логи приложения отсутствуют — диагностика полностью полагается на Events API-сервера.

### Связь с другими файлами серии

| Файл | Фокус |
| :--- | :--- |
| [definitions.md](./definitions.md) | Общие определения CreateContainerConfigError, жизненный цикл, таймауты |
| [diagnostics.md](./diagnostics.md) | Общий алгоритм диагностики всех причин CreateContainerConfigError |
| [configmap_issues.md](./configmap_issues.md) | Проблемы с ConfigMap (env/envFrom и как тома) |
| [secret_issues.md](./secret_issues.md) | Проблемы с Secret (env/envFrom и как тома) |
| [rbac_issues.md](./rbac_issues.md) | Проблемы с RBAC и ServiceAccount |
| [pvc_issues.md](./pvc_issues.md) | Проблемы с PersistentVolumeClaim |
| [prevention.md](./prevention.md) | Профилактика, CI/CD валидация, Admission-политики |
| **Данный файл** | Volume-специфичные причины (emptyDir, hostPath, projected, subPath), диагностика, исправление |

## Основные концепции

### Архитектура подсистемы томов в kubelet

```
API-сервер → kubelet (Pod Worker)
    ├── Volume Manager (Reconciliation Loop)
    │   ├── Desired State: PodSpec.volumes[]
    │   └── Actual State: /var/lib/kubelet/pods/<uid>/volumes/
    ├── Volume Plugin Manager
    │   ├── In-tree: emptyDir, hostPath, secret, configMap, projected
    │   └── CSI: csi (inline), ephemeral
    └── SyncPod Loop
        ├── 1. Resolve volumes (API fetch для configMap/secret)
        ├── 2. Validate volumes (hostPath type check, subPath)
        ├── 3. Setup volumes (create dirs, mount bind)
        └── 4. Generate CRI config (mount paths → container runtime)
```

**Ключевой момент:** `kubelet` разрешает тома **до** вызова CRI `CreateContainer`. Если любой из томов не может быть разрешен — под получает `CreateContainerConfigError` (не `ContainerCreating`).

### Механизм возникновения ошибки (Volume Mount Workflow)

1.  **SyncPod Loop:** `kubelet` получает команду на запуск пода и начинает итерацию жизненного цикла.
2.  **Volume Resolution:** `kubelet` считывает секцию `volumes` в PodSpec. Для каждого тома вызывается операция `SetUp`.
3.  **Data Fetching & Verification:**
    *   Для **ConfigMap/Secret/Projected**: Агент запрашивает данные из API-сервера и записывает их во временную директорию на узле (`/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~<type>/`).
    *   Для **hostPath**: Проверяется существование пути и соответствие заявленному типу (Directory, File, Socket и т.д.).
    *   Для **emptyDir**: Создается директория на локальном диске (или tmpfs для `medium: Memory`).
    *   Для **CSI inline**: Вызывается метод `NodePublishVolume` CSI-драйвера.
4.  **Validation:** Проверяются права доступа, размеры, наличие ключей в ConfigMap/Secret.
5.  **CRI Config Generation:** `kubelet` формирует конфигурацию для Container Runtime, в которой прописаны пути монтирования (bind mounts).
6.  **Блокировка:** Если на любом из этапов 2-4 произошел сбой — процесс формирования конфига прерывается, выставляется статус `CreateContainerConfigError`.

### Директории томов на узле

| Путь | Назначение |
| :--- | :--- |
| `/var/lib/kubelet/pods/<uid>/volumes/` | Точки монтирования томов для Pod |
| `/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~secret/` | Secret-тома |
| `/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~configmap/` | ConfigMap-тома |
| `/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~projected/` | Projected-тома |
| `/var/lib/kubelet/pods/<uid>/volume-subpaths/` | SubPath-монтирования (bind mounts) |
| `/var/lib/kubelet/pods/<uid>/containers/` | Конфигурация контейнеров для CRI |

### Каталог типичных ошибок

| Сообщение в Events | Тип тома | Причина | Статус |
| :--- | :--- | :--- | :--- |
| `configmap "x" not found` | configMap | ConfigMap не существует в Namespace | **Missing** |
| `secret "x" not found` | secret | Secret не существует в Namespace | **Missing** |
| `projected volume error: configmap "x" not found` | projected | Один из источников отсутствует | **Missing** |
| `hostPath type check failed: /path is not a directory` | hostPath | Тип Directory, но путь не существует | **Invalid Path** |
| `hostPath type check failed: /path is not a file` | hostPath | Тип File, но путь не существует | **Invalid Path** |
| `failed to create emptyDir: quota exceeded` | emptyDir | Превышена квота ephemeral-storage | **Quota Exceeded** |
| `subPath "x" not found in volume "y"` | subPath | Ключ/путь не существует в ConfigMap/Secret | **Key Missing** |
| `failed to provision ephemeral volume` | ephemeral | Ошибка CSI-провижинера | **Provision Error** |
| `error: secret "x" is not valid base64` | secret | Невалидные данные в Secret | **Corrupt Data** |
| `volume "x" already mounted` | any | Дублирование монтирования | **Conflict** |
| `unable to mount: permission denied` | hostPath, NFS | Нет прав на монтирование | **Permission Denied** |
| `Recursive read-only mount not supported` | any | Ядро не поддерживает rO-mount | **Unsupported** |

## Алгоритм диагностики

```
CreateContainerConfigError + volume-related
│
├── 1. Проверить Events пода
│   ├── "configmap/secret 'x' not found" → Проверить existence ресурса в namespace (шаг 2)
│   ├── "hostPath type check failed" → Проверить hostPath (шаг 3)
│   ├── "quota exceeded" → Проверить ResourceQuota (шаг 4)
│   ├── "subPath 'x' not found" → Проверить ключи в ConfigMap/Secret (шаг 5)
│   ├── "failed to provision" → Проверить CSI-драйвер (шаг 6)
│   └── "permission denied" → Проверить securityContext, fsGroup (шаг 7)
│
├── 2. Проверить Existence ConfigMap/Secret
│   ├── kubectl get configmap/secret <name> -n <namespace> → существует?
│   ├── Если нет → проверить во всех namespace: kubectl get configmap/secret <name> -A
│   └── Если есть, но в другом namespace → исправить манифест пода
│
├── 3. Проверить hostPath
│   ├── Определить узел пода: kubectl get pod <name> -o jsonpath='{.spec.nodeName}'
│   ├── SSH на узел и проверить путь: ls -la <hostPath>
│   └── Если путь не существует → использовать DirectoryOrCreate или создать вручную
│
├── 4. Проверить ResourceQuota
│   ├── kubectl describe resourcequota -n <namespace>
│   ├── Проверить ephemeral-storageUsed vs Hard
│   └── Если превышено → освободить место или увеличить квоту
│
├── 5. Проверить ключи в ConfigMap/Secret (для subPath)
│   ├── kubectl get configmap/secret <name> -o jsonpath='{.data}' | jq 'keys'
│   ├── Сравнить с ключами в манифесте пода (subPath.path)
│   └── Если ключ отсутствует → добавить ключ или исправить манифест
│
├── 6. Проверить CSI-драйвер
│   ├── kubectl get pods -n kube-system -l app=csi-*
│   ├── kubectl logs -n kube-system -l app=csi-* --tail=50
│   └── Если драйвер не запущен или имеет ошибки → исправить установку CSI
│
└── 7. Проверить SecurityContext
    ├── kubectl get pod <name> -o jsonpath='{.spec.securityContext}'
    ├── Проверить fsGroup, runAsUser, capabilities
    └── Если есть ограничения → исправить securityContext или Pod Security Policy
```

## Практические сценарии

### Сценарий 1: ConfigMap/Secret не найден (volume mount)

Если ConfigMap или Secret монтируется как том (не через env/envFrom), но ресурс не существует — `kubelet` не может создать директорию с данными.

**Диагностика:**
```bash
# Проверка наличия ConfigMap/Secret
kubectl get configmap,secret -n <namespace> | grep <name>
# → NAME               DATA   AGE
# → configmap/app-cfg   3      2d

# Если ресурса нет — проверить все namespace
kubectl get configmap,secret <name> -A
```

**Типичная ошибка:**
```text
Events:
  Warning  Failed  kubelet  Error: configmap "app-config" not found
```

**Решение:** Создайте ConfigMap/Secret в том же namespace, что и Pod.

### Сценарий 2: Projected Volume — отсутствие одного из источников

`Projected Volume` объединяет несколько источников (Secret, ConfigMap, Downward API, ServiceAccountToken) в одну директорию. Если хоть один из них отсутствует — под не запустится.

**Диагностика:**
```bash
# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 2 "Events:"
# → Warning  Failed  ...  Error: projected volume error: secret "db-pass" not found

# Проверка наличия всех источников, указанных в манифесте
kubectl get cm,secret -n <namespace>
```

**Пример манифеста с ошибкой:**
```yaml
volumes:
- name: combined-config
  projected:
    sources:
    - secret:
        name: app-secrets
    - configMap:
        name: app-config  # Этот ConfigMap не существует!
    - downwardAPI:
        items:
        - path: "labels"
          fieldRef:
            fieldPath: metadata.labels
```

**Решение:** Убедитесь, что **все** источники в projected volume существуют. Для необязательных источников используйте `optional: true`.

### Сценарий 3: emptyDir и лимиты Ephemeral Storage

Если в кластере включены лимиты на эфемерное хранилище (`ephemeral-storage`), `emptyDir` может вызвать ошибку еще на этапе создания, если запрашиваемый объем превышает квоту Namespace.

**Диагностика:**
```bash
# Проверка квот в Namespace
kubectl describe resourcequota -n <namespace>
# → Resource           Used  Hard
# → ephemeral-storage  8Gi   10Gi

# Проверка использования ephemeral-storage на узле
kubectl describe node <node-name> | grep -A 5 "Allocated resources"
```

**Решение:** Ограничьте размер `emptyDir` через `sizeLimit`. Это поможет планировщику корректно выбирать узлы и предотвратит `DiskPressure`.
```yaml
volumes:
- name: scratch-pad
  emptyDir:
    sizeLimit: 500Mi
```

### Сценарий 4: hostPath — ограничения безопасности и типы

Часто ошибка возникает, когда в манифесте указан тип `Directory` (обязательное существование), но директория на узле отсутствует. Также на работу `hostPath` влияет Admission-контроллер `NodeRestriction`.

**Диагностика:**
```bash
# Проверка событий пода
kubectl describe pod <pod-name>
# → message: hostPath type check failed: /var/logs/app is not a directory

# Определение узла, где запущен под
kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}'

# SSH на узел и проверка пути
ssh <node-name> "ls -la /var/logs/app"
```

**Типы hostPath и их поведение:**

| Тип | Поведение при отсутствии пути | Рекомендация |
| :--- | :--- | :--- |
| `Directory` | **Ошибка** если путь не существует | Используйте для заранее подготовленных путей |
| `DirectoryOrCreate` | Создает директорию с правами `0755` | Безопасный вариант для автоматического создания |
| `File` | **Ошибка** если файл не существует | Используйте для заранее подготовленных файлов |
| `FileOrCreate` | Создает пустой файл с правами `0644` | Безопасный вариант для автоматического создания |

**Решение:** Используйте `DirectoryOrCreate` или `FileOrCreate`, если допустимо автоматическое создание.

### Сценарий 5: Ошибки разрешения subPath

Использование `subPath` часто приводит к `CreateContainerConfigError`, если путь внутри тома изменился, является битой символической ссылкой или не совпадает с ключом в ConfigMap/Secret.

**Диагностика:**
```bash
# Проверка ключей в ConfigMap/Secret
kubectl get configmap <name> -o jsonpath='{.data}' | jq 'keys'
# → ["config.yaml", "logging.yaml"]  # ключа "settings.json" нет

# Проверка манифеста пода
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes[*].projected.sources}'
```

**Типичная ошибка:**
```yaml
# Манифест пода
volumeMounts:
- name: app-config
  mountPath: /etc/app/settings.json
  subPath: settings.json  # Этого ключа нет в ConfigMap!
```

**Решение:** Убедитесь, что ключи в ресурсе соответствуют именам файлов, указанных в `subPath`.

### Сценарий 6: Права доступа на тома (fsGroup, SELinux)

Иногда под переходит в `CreateContainerConfigError`, если `kubelet` не может применить `fsGroup` (изменение владельца файлов) из-за ограничений файловой системы узла или специфики драйвера.

**Диагностика:**
```bash
# Проверка securityContext пода
kubectl get pod <pod-name> -o jsonpath='{.spec.securityContext}'
# → {"fsGroup": 1000, "runAsUser": 1000}

# Проверка логов kubelet на ошибки fsGroup/SELinux
ssh <node-name> "journalctl -u kubelet --since '10 min ago' | grep -i 'fsGroup\|selinux\|chown\|permission'"

# Проверка SELinux на узле
ssh <node-name> "getenforce"
# → Enforcing
```

**Типичные ошибки:**
```text
Error: failed to set fsGroup for volume "xxx": unable to change group ownership of the volume
Error: SELinux relabeling failed for volume "xxx": permission denied
```

**Решение:**
- Для fsGroup: убедитесь, что ФС поддерживает смену владельца (ext4, xfs)
- Для SELinux: добавьте appropriate `seLinuxOptions` в securityContext или отключите SELinux для конкретных томов

### Сценарий 7: Generic Ephemeral Volumes (K8s 1.23+)

Это "инлайн" PVC, жизненный цикл которых привязан к поду. Ошибки здесь часто связаны с некорректным `storageClassName` или отсутствием прав у провижинера.

**Диагностика:**
```bash
# Проверка ephemeral PVC (имя формата <pod-name>-<volume-name>)
kubectl get pvc -n <namespace> | grep <pod-name>
# → NAME                    STATUS   VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS
# → my-pod-ephemeral-vol   Pending                             my-storage-class

# Проверка статуса PVC
kubectl describe pvc <ephemeral-pvc-name> -n <namespace>
# → Events:
# → Warning  ProvisioningFailed  ...  failed to provision volume with StorageClass "my-storage-class": ...
```

**Типичные ошибки:**
- `storageClass "x" not found` — StorageClass не существует
- `failed to provision volume` — CSI-драйвер не может создать том
- `pending` — PVC не привязан (WaitForFirstConsumer deadlock)

Подробнее о проблемах с PVC: [pvc_issues.md](./pvc_issues.md).

### Сценарий 8: CSI Inline Volume (Secret Store, и др.)

CSI inline volume монтируются как временные тома, но требуют работающего CSI-драйвера. Если драйвер не запущен или конфигурация некорректна — `kubelet` не может вызвать `NodePublishVolume`.

**Диагностика:**
```bash
# Проверка CSI-драйверов
kubectl get csidrivers
# → NAME                  ATTACHREQUIRED   PODINFOONDEMAND   STORAGECAPACITY
# → secrets-store.csi.k8s.io   false            true              false

# Проверка подов CSI-драйвера
kubectl get pods -n kube-system -l app=csi-secrets-store
# → NAME                       READY   STATUS    RESTARTS   AGE
# → csi-secrets-store-xxxxx    3/3     Running   0          2d

# Проверка логов CSI-драйвера
kubectl logs -n kube-system -l app=csi-secrets-store --tail=50
```

**Типичная ошибка:**
```text
Events:
  Warning  Failed  kubelet  Error: failed to mount volume "xxx": rpc error: code = Unknown desc = ...
```

**Решение:** Убедитесь, что CSI-драйвер установлен и запущен, а `SecretProviderClass` (для Secret Store) корректен.

### Сценарий 9: Recursive Read-Only Mounts (K8s 1.30+)

Новая функциональность K8s позволяет делать монтирования рекурсивно "только для чтения". Если нижележащая файловая система узла не поддерживает этот флаг ядра, под может застрять в ошибке конфигурации на этапе `SetUp`.

**Диагностика:**
```bash
# Проверка поддержки рекурсивных монтирований на узле
ssh <node-name> "cat /proc/self/mountinfo | grep -i recursive"
# Если пусто — ядро не поддерживает

# Проверка версии ядра
ssh <node-name> "uname -r"
# Требуется 5.12+ для поддержки MS_REC | MS_RDONLY
```

**Решение:** Обновите ядро узла до версии 5.12+ или не используйте `readOnly: true` с рекурсивными томами.

### Сценарий 10: Ошибки в Helm-шаблонах

Helm может создавать тома с некорректными данными, особенно если используются шаблонные переменные.

**Типичные ошибки:**

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| Пустой Secret/ConfigMap | Tom создан, но с пустыми данными | Проверить `{{ .Values.password }}` в шаблоне |
| Невалидный YAML | Ошибка парсинга манифеста | Проверить отступы в Helm-шаблоне |
| Опечатка в имени | Tom создан, но Pod ссылается на другой | Проверить `{{ include "chart.fullname" . }}` |
| Tom в другом namespace | 403 Forbidden | Убедиться, что том в том же namespace, что и Pod |

**Диагностика:**
```bash
# Рендер манифеста Helm
helm template my-release /path/to/chart -f values.yaml | grep -A 20 "volumes:"

# Проверка созданного манифеста
kubectl get pod <pod-name> -o yaml | grep -A 30 "volumes:"
```

## Список проверок (Checklist)

### Источники данных
- [ ] Все ConfigMap и Secret, указанные в томах, созданы в том же Namespace: `kubectl get cm,secret -n <namespace>`
- [ ] Все источники в Projected Volume существуют (или используются `optional: true`)
- [ ] Ключи в ConfigMap/Secret соответствуют `subPath.path` в манифесте пода

### hostPath
- [ ] Путь на узле существует (для типа `Directory`) или используется `DirectoryOrCreate`
- [ ] Тип пути соответствует реальному (Directory, File, Socket, и т.д.)
- [ ] Права доступа позволяют `kubelet` читать/записывать в путь

### emptyDir
- [ ] Размер `sizeLimit` не превышает квоту `ephemeral-storage` в Namespace
- [ ] Для `medium: Memory` размер не превышает лимит памяти контейнера

### subPath
- [ ] Ключи в ConfigMap/Secret существуют и соответствуют указанным путям
- [ ] Символические ссылки валидны (не битые)

### CSI и драйверы
- [ ] CSI-драйвер установлен и запущен в `kube-system`
- [ ] `StorageClass` для ephemeral volume существует
- [ ] `SecretProviderClass` (для Secret Store) корректен

### Безопасность
- [ ] `fsGroup` совместим с ФС узла (ext4, xfs)
- [ ] SELinux не блокирует монтирование (проверить `seLinuxOptions`)
- [ ] Pod Security Standards не запрещают `hostPath` (если используется)

### Ядро и ОС
- [ ] Версия ядра узла 5.12+ (для рекурсивных Read-Only монтирований)
- [ ] ФС узла поддерживает необходимые опции (mount propagation, SELinux labels)

## Быстрая диагностика

```bash
# 1. Определить причину из Events
kubectl describe pod <pod-name> | grep -A 5 "Events:"
# Ищите: "not found", "type check failed", "quota exceeded", "permission denied"

# 2. Проверить все тома в манифесте пода
kubectl get pod <pod-name> -o json | jq -r '
  .spec.volumes[] | 
  if .configMap then "configMap: \(.configMap.name)"
  elif .secret then "secret: \(.secret.secretName)"
  elif .hostPath then "hostPath: \(.hostPath.path) [\(.hostPath.type // "auto")]"
  elif .emptyDir then "emptyDir: \(.emptyDir.sizeLimit // "no limit")"
  elif .projected then "projected: \(.projected.sources | length) sources"
  elif .persistentVolumeClaim then "pvc: \(.persistentVolumeClaim.claimName)"
  else "other: \(. | keys[0])"
  end
'

# 3. Проверить, все ли источники существуют
kubectl get pod <pod-name> -o json | jq -r '
  .spec.volumes[] |
  if .configMap then .configMap.name
  elif .secret then .secret.secretName
  elif .persistentVolumeClaim then .persistentVolumeClaim.claimName
  else empty
  end
' | sort -u | while read -r name; do
  kubectl get configmap,secret,pvc "$name" -n <namespace> &>/dev/null && echo "OK: $name" || echo "MISSING: $name"
done

# 4. Проверить CSI-драйверы
kubectl get pods -n kube-system -l app=csi-* -o custom-columns='NAME:.metadata.name,STATUS:.status.phase'

# 5. Проверитьphemeral-storage квоты
kubectl describe resourcequota -n <namespace> | grep ephemeral
```

## Типичные ошибки в Helm-чартах

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| ConfigMap/Secret не создан | `configmap/secret "x" not found` | Установить `configmap.create: true` в values.yaml |
| Пустой subPath | `subPath "x" not found` | Проверить ключи в ConfigMap и `items` в шаблоне |
| hostPath не существует | `hostPath type check failed` | Использовать `DirectoryOrCreate` или создать путь заранее |
| sizeLimit превышает квоту | `quota exceeded` | Уменьшить `emptyDir.sizeLimit` или увеличить ResourceQuota |
| Secret в другом namespace | 403 Forbidden | Убедиться, что Secret в том же namespace, что и Pod |
| Recursive mount не поддерживается | `CreateContainerConfigError` | Обновить ядро узла до 5.12+ или убрать `readOnly: true` |

## Сравнение типов томов и типичных ошибок

| Тип тома | Типичная ошибка | Статус пода | Ключевая диагностика |
| :--- | :--- | :--- | :--- |
| **ConfigMap** | "configmap not found" | CreateContainerConfigError | `kubectl get cm -n <ns>` |
| **Secret** | "secret not found" | CreateContainerConfigError | `kubectl get secret -n <ns>` |
| **Projected** | "configmap/secret not found" | CreateContainerConfigError | Проверить все источники |
| **hostPath** | "type check failed" | CreateContainerConfigError | SSH на узел, `ls -la <path>` |
| **emptyDir** | "quota exceeded" | CreateContainerConfigError | `kubectl describe resourcequota` |
| **subPath** | "subPath not found" | CreateContainerConfigError | `kubectl get cm <name> -o jsonpath='{.data}' \| jq 'keys'` |
| **CSI inline** | "failed to mount" | CreateContainerConfigError | `kubectl logs -n kube-system -l app=csi-*` |
| **Generic ephemeral** | "failed to provision" | Pending / CreateContainerConfigError | `kubectl describe pvc <name>` |

## Дополнительная информация

### Сравнение с PVC-проблемами

| Аспект | Эфемерные / Локальные тома | Persistent Volume Claims (PVC) |
|:---|:---|:---|
| **Уровень ресурса** | Описываются внутри PodSpec | Отдельный объект API |
| **Жизненный цикл** | Удаляются вместе с подом | Независимы от пода |
| **Хранилище** | Диск узла (обычно) | Сетевое хранилище |
| **Типичный статус** | `CreateContainerConfigError` | `ContainerCreating` / `Pending` |
| **Типичные ошибки** | NotFound, TypeCheck, Quota | Pending, Multi-Attach, NodeAffinity |
| **Диагностика** | Events + проверка на узле | Events + `kubectl describe pvc/pv` |

### Lifecycle томов в kubelet

```
Pod Scheduled → Node Assigned
    │
    ├── kubelet: SyncPod Loop
    │   ├── 1. Resolve volumes (API fetch для configMap/secret)
    │   ├── 2. Validate hostPath (type check)
    │   ├── 3. Create emptyDir directory
    │   ├── 4. Call CSI NodePublishVolume (для inline)
    │   ├── 5. Generate CRI config (mount paths)
    │   └── 6. Call CRI CreateContainer
    │
    ├── Если步骤 1-4 failed → CreateContainerConfigError
    └── Если步骤 5-6 failed → ContainerCreating / ContainerConfigError
```

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Проблемы с ConfigMap](./configmap_issues.md)
- [Проблемы с Secret](./secret_issues.md)
- [Проблемы с PVC](./pvc_issues.md)
- [Проблемы с RBAC](./rbac_issues.md)
- [CRI и containerd](./cri_and_runtime.md) — Container Runtime Interface, взаимодействие kubelet с рантаймом
- [Projected Volumes — детальный обзор](../../../Base/Pod/volume_types/projected_volumes.md)
- [Типы томов в Kubernetes](../../../Base/Pod/volume_types/volume_types.md)
- [Диагностика эвикции (DiskPressure)](../../PodEvicted/disk_eviction.md)
- [Размонтирование томов (Pod Terminating)](../../PodTerminating/volume_unmount_issues.md)
