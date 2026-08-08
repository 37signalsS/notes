# CreateContainerConfigError: Проблемы с томами

## Определения

**Volume-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки к запуску контейнера, когда `kubelet` не может подготовить локальную файловую систему узла для монтирования томов. 

В отличие от проблем с PVC (сетевые диски), этот тип ошибки обычно связан с локальными ресурсами узла (hostPath), эфемерными хранилищами (emptyDir) или агрегированными источниками данных (Projected Volumes), которые должны быть успешно разрешены и подготовлены **до** вызова Container Runtime (CRI).

Подробные определения ошибки: [definitions.md](./definitions.md).
Общие концепции томов в Kubernetes: [Типы томов](../../../Base/Pod/volume_types/volume_types.md).

## Основные концепции

### Механизм возникновения ошибки

1.  **SyncPod Loop:** `kubelet` получает команду на запуск пода и начинает итерацию жизненного цикла.
2.  **Volume Manager Stage:** `kubelet` считывает секцию `volumes` в PodSpec. Для каждого тома вызывается операция `SetUp`.
3.  **Data Fetching & Verification:** 
    *   Для **ConfigMap/Secret/Projected**: Агент запрашивает данные из API-сервера и записывает их во временную директорию на узле (`/var/lib/kubelet/pods/...`).
    *   Для **hostPath**: Проверяется существование пути и соответствие заявленному типу (Directory, File, Socket и т.д.).
4.  **CRI Config Generation:** `kubelet` формирует конфигурацию для Container Runtime, в которой прописаны пути монтирования (bind mounts).
5.  **Блокировка:** Если на этапе 3 данные недоступны, ресурс не найден или путь `hostPath` не прошел валидацию — процесс формирования конфига прерывается, выставляется статус `CreateContainerConfigError`.

### Типы томов и причины блокировки

| Тип тома | Характер ошибки | Типичное сообщение в Events |
|:---|:---|:---|
| **Projected Volume** | Отсутствует один из источников данных | `projected volume error: configmap "x" not found` |
| **emptyDir** | Превышение лимитов или квот узла | `failed to create emptyDir: quota exceeded` |
| **hostPath** | Несоответствие типа или отсутствие пути | `hostPath type check failed: /path is not a directory` |
| **ConfigMap/Secret** | Ресурс не найден (при монтировании томом) | `configmap/secret "x" not found` |
| **Generic Ephemeral** | Ошибки провижининга инлайн-тома | `failed to provision ephemeral volume` |
| **subPath** | Ошибка разрешения пути внутри тома | `subPath "x" not found in volume "y"` |

## Практические сценарии

### Сценарий 1: Ошибки в Projected Volume

`Projected Volume` объединяет несколько источников (Secret, ConfigMap, Downward API, ServiceAccountToken) в одну директорию. Если хоть один из них отсутствует — под не запустится.

**Диагностика:**
```bash
# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 2 "Events:"
# → Warning  Failed  ...  Error: projected volume error: secret "db-pass" not found

# Проверка наличия всех источников, указанных в манифесте
kubectl get cm,secret -n <namespace>
```

### Сценарий 2: emptyDir и лимиты Ephemeral Storage

Если в кластере включены лимиты на эфемерное хранилище (`ephemeral-storage`), `emptyDir` может вызвать ошибку еще на этапе создания, если запрашиваемый объем превышает квоту Namespace.

**Диагностика:**
```bash
# Проверка квот в Namespace
kubectl describe resourcequota -n <namespace>
# → Resource           Used  Hard
# → ephemeral-storage  8Gi   10Gi
```

**Решение:** Ограничьте размер `emptyDir` через `sizeLimit`. Это поможет планировщику корректно выбирать узлы и предотвратит `DiskPressure`.
```yaml
volumes:
- name: scratch-pad
  emptyDir:
    sizeLimit: 500Mi
```

### Сценарий 3: hostPath — ограничения безопасности и типы

Часто ошибка возникает, когда в манифесте указан тип `Directory` (обязательное существование), но директория на узле отсутствует. Также на работу `hostPath` влияет Admission-контроллер `NodeRestriction`.

**Диагностика:**
```bash
kubectl describe pod <pod-name>
# → message: hostPath type check failed: /var/logs/app is not a directory
```

**Решение:** Используйте `DirectoryOrCreate`, если допустимо автоматическое создание директории kubelet-ом.

### Сценарий 4: Generic Ephemeral Volumes (K8s 1.23+)

Это "инлайн" PVC, жизненный цикл которых привязан к поду. Ошибки здесь часто связаны с некорректным `storageClassName` или отсутствием прав у провижинера.

**Диагностика:**
```bash
kubectl get pvc
# Ищите PVC с именем <pod-name>-<volume-name>
kubectl describe pvc <ephemeral-pvc-name>
```

Подробнее о проблемах с PVC: [pvc_issues.md](./pvc_issues.md).

### Сценарий 5: Ошибки разрешения subPath

Использование `subPath` часто приводит к `CreateContainerConfigError`, если путь внутри тома изменился, является битой символической ссылкой или не совпадает с ключом в ConfigMap/Secret.

**Решение:** Убедитесь, что ключи в ресурсе соответствуют именам файлов, указанным в `subPath`.

### Сценарий 6: Права доступа на тома (fsGroup)

Иногда под переходит в `CreateContainerConfigError`, если `kubelet` не может применить `fsGroup` (изменение владельца файлов) из-за ограничений файловой системы узла или специфики драйвера.

### Сценарий 7: Recursive Read-Only Mounts (v1.30+)

Новая функциональность K8s позволяет делать монтирования рекурсивно "только для чтения". Если нижележащая файловая система узла не поддерживает этот флаг ядра, под может застрять в ошибке конфигурации на этапе `SetUp`.

## Список проверок (Checklist)

1.  **Sources Existence:** Все ConfigMap и Secret, указанные в томах, созданы в том же Namespace.
2.  **Typo & Mapping:** Имена томов в `volumes` и их соответствие в `volumeMounts` проверены.
3.  **hostPath Validity:** Путь на узле существует (для типа `Directory`) или используется `*OrCreate`.
4.  **Storage Quota:** Квота `ephemeral-storage` в Namespace не превышена.
5.  **CSI/Driver Health:** Поды CSI-драйверов запущены и не имеют ошибок в `kube-system`.
6.  **subPath Consistency:** Пути внутри томов соответствуют ключам в манифестах ConfigMap/Secret.
7.  **Recursive Mounts Support:** Проверена совместимость ядра узла при использовании рекурсивных Read-Only монтирований.

## Дополнительная информация

### Сравнение с PVC-проблемами

| Аспект | Эфемерные / Локальные тома | Persistent Volume Claims (PVC) |
|:---|:---|:---|
| **Уровень ресурса** | Описываются внутри PodSpec | Отдельный объект API |
| **Жизненный цикл** | Удаляются вместе с подом | Независимы от пода |
| **Хранилище** | Диск узла (обычно) | Сетевое хранилище / Облачные диски |
| **Типичный статус** | `CreateContainerConfigError` | `ContainerCreating` / `Pending` |

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Проблемы с PVC](./pvc_issues.md)
- [Projected Volumes — детальный обзор](../../../Base/Pod/volume_types/projected_volumes.md)
- [Диагностика эвикции (DiskPressure)](../../PodEvicted/disk_eviction.md)
- [Recursive Read-Only Mounts (K8s docs)](https://kubernetes.io/docs/concepts/storage/volumes/#recursive-read-only-mounts)
