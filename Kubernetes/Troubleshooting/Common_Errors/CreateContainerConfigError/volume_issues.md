# CreateContainerConfigError: Проблемы с томами

## Определения

**Volume-related CreateContainerConfigError** — состояние пода, при котором запуск контейнера блокируется на этапе подготовки конфигурации из-за проблем с эфемерными или статическими томами (Projected Volume, emptyDir, hostPath, ConfigMap/Secret), не связанными с механизмом PVC.

Подробные определения ошибки: [definitions.md](./definitions.md).
Общие концепции томов в Kubernetes: [Типы томов](../../../Base/Pod/volume_types/volume_types.md).

## Основные концепции

### Типы томов и причины блокировки

| Тип тома | Характер ошибки | Типичное сообщение в Events |
|:---|:---|:---|
| **Projected Volume** | Отсутствует один из источников данных | `projected volume error: configmap "x" not found` |
| **emptyDir** | Превышение лимитов или квот узла | `failed to create emptyDir: quota exceeded` |
| **hostPath** | Несоответствие типа или отсутствие пути | `hostPath path not accessible` |
| **ConfigMap/Secret** | Ресурс не найден (при монтировании томом) | `configmap/secret "x" not found` |
| **Generic Ephemeral** | Ошибки провижининга инлайн-тома | `failed to provision ephemeral volume` |

### Механизм возникновения ошибки

1.  **Обнаружение спецификации:** `kubelet` считывает секцию `volumes` в PodSpec.
2.  **Проверка источников:** Перед созданием контейнера `kubelet` обязан убедиться, что все источники данных для томов доступны.
3.  **Остановка процесса:** Если хотя бы один ConfigMap, Secret или путь `hostPath` недоступен, формирование спецификации контейнера прерывается.
4.  **Статус:** Поду присваивается статус `CreateContainerConfigError`.

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
# → Error from server (NotFound): secrets "db-pass" not found
```

**Решение:** Создайте отсутствующий ресурс или исправьте опечатку в имени источника.

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

Часто ошибка возникает, когда в манифесте указан тип `Directory` (обязательное существование), но директория на узле отсутствует.

**Диагностика:**
```bash
kubectl describe pod <pod-name>
# → message: hostPath type check failed: /var/logs/app is not a directory
```

**Решение:** Используйте `DirectoryOrCreate`, если допустимо автоматическое создание директории kubelet-ом. 
**Внимание:** Использование `hostPath` в Production не рекомендуется по соображениям безопасности.

### Сценарий 4: Generic Ephemeral Volumes (K8s 1.23+)

Это "инлайн" PVC, жизненный цикл которых привязан к поду. Ошибки здесь часто связаны с некорректным `storageClassName`.

**Диагностика:**
```bash
kubectl get pvc
# Ищите PVC с именем <pod-name>-<volume-name>
kubectl describe pvc <ephemeral-pvc-name>
```

Подробнее о проблемах с PVC: [pvc_issues.md](./pvc_issues.md).

### Сценарий 5: Права доступа на тома (fsGroup)

Иногда под переходит в `CreateContainerConfigError`, если `kubelet` не может применить `fsGroup` (изменение владельца файлов) из-за ограничений файловой системы узла.

**Решение:** Проверьте `securityContext` пода и параметры монтирования.

## Список проверок (Checklist)

1.  **Existence:** Все ConfigMap и Secret, указанные в томах, созданы в том же Namespace.
2.  **Typo:** Проверьте имена томов в `volumes` и их соответствие в `volumeMounts`.
3.  **hostPath Type:** Если используете `hostPath`, убедитесь, что путь существует на узле или используйте `*OrCreate` типы.
4.  **Storage Quota:** Проверьте `ResourceQuota` на предмет ограничений `ephemeral-storage`.
5.  **CSI Status:** Если используются CSI-драйверы для эфемерных томов, убедитесь, что соответствующие поды драйверов запущены.

## Дополнительная информация

### Сравнение с PVC-проблемами

| Аспект | Эфемерные тома | Persistent Volume Claims (PVC) |
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
