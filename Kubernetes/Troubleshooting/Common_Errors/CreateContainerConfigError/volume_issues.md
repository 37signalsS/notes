# CreateContainerConfigError: Проблемы с томами

## Определения

**Volume-related CreateContainerConfigError** — ошибка, возникающая когда Pod не может создать конфигурацию контейнера из-за проблем с эфемерными томами (Projected Volume, emptyDir, hostPath), не связанными с PVC.

## Базовые концепции

### Типы томов, вызывающие ошибку

| Тип тома | Назначение | Типичная ошибка |
|----------|------------|-----------------|
| **Projected Volume** | Объединение ConfigMap + Secret + DownwardAPI в одну директорию | `projected volume error: configmap "x" not found` |
| **emptyDir** | Временное хранилище, обмен между контейнерами | `quota exceeded`, `sizeLimit exceeded` |
| **hostPath** | Файл/директория с хоста (dev/test) | `hostPath path not accessible` |
| **configMap/Secret (отдельный том)** | Монтирование одного ресурса | `configmap/secret not found` |

> Общие концепции томов: [Тома в Kubernetes](../../../Base/Pod/volume_types/volume_types.md).
> Projected volumes: [projected_volumes.md](../../../Base/Pod/volume_types/projected_volumes.md).

### Механизм ошибки

```
Pod определён с volumes
         ↓
kubelet проверяет каждый источник тома
         ↓
❌ Один из источников недоступен
         ↓
CreateContainerConfigError
```

## Практические сценарии

### Сценарий 1: Projected Volume — источник не найден

**Сообщение:**

```
Error: projected volume error: configmap "cm1" not found
```

**Причина:** Projected volume объединяет несколько источников, один из которых отсутствует.

**Диагностика:** Проверить каждый источник из `sources`:

```bash
# Проверка ConfigMap
kubectl get configmap app-config -n <namespace>

# Проверка Secret
kubectl get secret db-credentials -n <namespace>
```

**Решение:** Создать недостающий ресурс или исправить имя в манифесте.

```yaml
volumes:
- name: all-in-one
  projected:
    sources:
    - configMap:
        name: app-config      # ✅ Должен существовать
    - secret:
        name: db-credentials  # ✅ Должен существовать
    - downwardAPI:
        items:
        - path: "labels"
          fieldRef:
            fieldPath: metadata.labels
```

### Сценарий 2: emptyDir — превышение квоты

**Сообщение:**

```
Error: failed to create emptyDir volume "cache": quota exceeded
```

**Причина:** ResourceQuota namespace ограничивает объём emptyDir или `sizeLimit` превышен.

**Решение:** Указать `sizeLimit` явно и убедиться, что он в пределах квоты.

```yaml
volumes:
- name: cache
  emptyDir:
    sizeLimit: 1Gi
```

Проверка квоты:

```bash
kubectl describe resourcequota -n <namespace>
```

### Сценарий 3: emptyDir — переполнение диска на узле

**Симптом:** Pod эвиктится с `Evicted: The node had condition: [DiskPressure]`.

**Причина:** emptyDir без `sizeLimit` заполняет ephemeral storage узла.

**Решение:**

```yaml
volumes:
- name: cache
  emptyDir:
    sizeLimit: 500Mi  # Ограничение предотвращает заполнение узла
```

Диагностика disk eviction: [disk_eviction.md](../../PodEvicted/disk_eviction.md).

### Сценарий 4: hostPath — путь недоступен

**Сообщение:**

```
Error: MountVolume.SetUp failed for volume "host-data" :
hostPath type check failed: /data/app is not a directory
```

**Причина:** Указанный путь не существует на узле или не совпадает `type`.

**Решение:**

```yaml
volumes:
- name: host-data
  hostPath:
    path: /data/app
    type: DirectoryOrCreate  # Создаст директорию, если не существует
```

| `type` | Поведение |
|--------|-----------|
| `""` (пусто) | Без проверки (по умолчанию) |
| `DirectoryOrCreate` | Создаст директорию при отсутствии |
| `Directory` | Должна существовать, иначе ошибка |
| `FileOrCreate` | Создаст файл при отсутствии |
| `Socket` | Должен существовать как socket |
| `CharDevice` | Должен существовать как char device |
| `BlockDevice` | Должен существовать как block device |

### Сценарий 5: Конфликт имён томов

**Симптом:** `Error: volume "config" already exists` или `mountPath conflicts`.

**Причина:** Два тома с одинаковым именем или два volumeMount с одинаковым `mountPath`.

**Решение:** Убедиться в уникальности имён томов и путей монтирования.

```yaml
# ✅ Корректно: уникальные имена и mountPath
volumes:
- name: app-config
  configMap:
    name: app-config
- name: db-credentials
  secret:
    secretName: db-credentials
volumeMounts:
- name: app-config
  mountPath: /etc/config
- name: db-credentials
  mountPath: /etc/secrets
```

## Дополнительная информация

### Отличие от PVC-проблем

| Характеристика | Эфемерные тома (данный файл) | PVC (pvc_issues.md) |
|----------------|------------------------------|---------------------|
| **Жизненный цикл** | Совпадает с Pod | Независимый от Pod |
| **Персистентность** | Данные теряются при удалении Pod | Данные сохраняются |
| **Типичные причины** | Ресурс не найден в projected, quota | PV не привязан, StorageClass |
| **Файл решения** | Этот файл | [pvc_issues.md](./pvc_issues.md) |

### Связанные ресурсы

- Определения: [definitions.md](./definitions.md)
- Диагностика: [diagnostics.md](./diagnostics.md)
- Типы томов: [Тома в Kubernetes](../../../Base/Pod/volume_types/volume_types.md)
- Projected volumes: [projected_volumes.md](../../../Base/Pod/volume_types/projected_volumes.md)
- PVC issues: [pvc_issues.md](./pvc_issues.md)
- Disk eviction: [disk_eviction.md](../../PodEvicted/disk_eviction.md)
