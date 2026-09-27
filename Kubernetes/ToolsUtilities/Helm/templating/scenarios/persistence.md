# Шаблонизация PersistentVolumeClaim в Helm

---

## Определения

**PersistentVolumeClaim (PVC)** — запрос приложения на выделение хранилища определённого размера и типа. Kubernetes автоматически связывает PVC с подходящим PersistentVolume (PV) через StorageClass.

**StorageClass** — описатель класса хранилища (HDD, SSD, NFS, Ceph), определяющий provisioner, параметры и policy (Delete/Retain) при удалении PVC.

**VolumeClaimTemplates** — шаблон в StatefulSet, автоматически создающий PVC для каждого индекса пода. Имена генерируются по формуле: `<имя-шаблона>-<имя-StatefulSet>-<ordinal>`.

**persistentVolumeClaimRetentionPolicy** — политика, определяющая судьбу PVC при масштабировании/удалении StatefulSet: `Retain` (оставить) или `Delete` (удалить).

**ReadWriteOnce (RWO)** — режим доступа: том может быть примонтирован только к одному узлу. Не может быть shared между подами на разных узлах.

**ReadWriteMany (RWX)** — режим доступа: том может быть примонтирован к нескольким узлам одновременно (NFS, CephFS, GlusterFS).

**ReadOnlyMany (ROX)** — режим доступа: том доступен для чтения с нескольких узлов.

---

## Базовые концепции

### Типы storage классов

| Класс | Типичный provisioner | Access Modes | Use-case |
|-------|---------------------|--------------|----------|
| `standard` | kubernetes.io/aws-ebs, pd.csi.storage.gke.io | RWO | Общее назначение |
| `fast-ssd` | local.csi.storage.gke.io | RWO | Высокопроизводительные БД |
| `nfs-client` | nfs-subdir-external-provisioner | RWX | Общие файлы |
| `longhorn` | driver.longhorn.io | RWX/RWO | On-premise кластеры |

### Жизненный цикл PVC

1. **Pending** — PVC создан, ищет подходящий PV
2. **Bound** — PVC привязан к PV
3. **Released** — PV освобождён, но ещё не переназначен
4. **Failed** — ошибка привязки

### Взаимодействие с StatefulSet

- При `helm upgrade` PVC **не пересоздаются** (защита данных)
- При `helm uninstall` PVC **остаются** по умолчанию (Retain)
- Для удаления PVC используйте `persistentVolumeClaimRetentionPolicy: Delete`

---

## Практические сценарии

### Базовый PVC для Deployment

```yaml
# values.yaml
persistence:
  enabled: true
  storageClass: "standard"
  size: 10Gi
  accessModes:
    - ReadWriteOnce
  mountPath: /data
```

```yaml
# templates/pvc.yaml
{{- if .Values.persistence.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "myapp.fullname" . }}-data
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  accessModes:
    {{- toYaml .Values.persistence.accessModes | nindent 4 }}
  storageClassName: {{ .Values.persistence.storageClass | quote }}
  resources:
    requests:
      storage: {{ .Values.persistence.size | quote }}
{{- end }}
```

```yaml
# templates/deployment.yaml
spec:
  template:
    spec:
      containers:
        - name: app
          volumeMounts:
            - name: data
              mountPath: {{ .Values.persistence.mountPath }}
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: {{ include "myapp.fullname" . }}-data
```

### StatefulSet с volumeClaimTemplates

```yaml
# values.yaml
statefulset:
  enabled: true
  replicaCount: 3
  persistence:
    storageClass: "fast-ssd"
    size: 50Gi
    accessModes:
      - ReadWriteOnce
    retentionPolicy: Retain
```

```yaml
# templates/statefulset.yaml
{{- if .Values.statefulset.enabled }}
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  serviceName: {{ include "myapp.fullname" . }}-headless
  replicas: {{ .Values.statefulset.replicaCount }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "myapp.labels" . | nindent 8 }}
    spec:
      containers:
        - name: app
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          volumeMounts:
            - name: data
              mountPath: /data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes:
          {{- toYaml .Values.statefulset.persistence.accessModes | nindent 10 }}
        storageClassName: {{ .Values.statefulset.persistence.storageClass | quote }}
        resources:
          requests:
            storage: {{ .Values.statefulset.persistence.size | quote }}
{{- end }}
```

### PVC с удалением при масштабировании

```yaml
# templates/statefulset.yaml
spec:
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: {{ .Values.statefulset.persistence.retentionPolicy | default "Retain" }}
    whenScaled: {{ .Values.statefulset.persistence.retentionPolicy | default "Retain" }}
```

### PVC с selector (привязка к конкретному PV)

```yaml
# templates/pvc.yaml
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: {{ .Values.persistence.size | quote }}
  selector:
    matchLabels:
      app: {{ .Values.persistence.label | default "data" }}
    matchExpressions:
      - key: environment
        operator: In
        values:
          - {{ .Values.global.env }}
```

### Multiple PVC для разных данных

```yaml
# templates/pvc-data.yaml
{{- if .Values.persistence.data.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "myapp.fullname" . }}-data
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: {{ .Values.persistence.data.storageClass | quote }}
  resources:
    requests:
      storage: {{ .Values.persistence.data.size | quote }}
{{- end }}

---
# templates/pvc-logs.yaml
{{- if .Values.persistence.logs.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "myapp.fullname" . }}-logs
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: {{ .Values.persistence.logs.storageClass | quote }}
  resources:
    requests:
      storage: {{ .Values.persistence.logs.size | quote }}
{{- end }}
```

### PVC с сохранением при uninstall (resource-policy)

```yaml
# templates/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "myapp.fullname" . }}-data
  annotations:
    "helm.sh/resource-policy": keep
```

### Валидация через values.schema.json

```json
{
  "properties": {
    "persistence": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "size": { "type": "string", "pattern": "^[0-9]+(Gi|Mi|Ti)$" },
        "storageClass": { "type": "string" },
        "accessModes": {
          "type": "array",
          "items": {
            "enum": ["ReadWriteOnce", "ReadWriteMany", "ReadOnlyMany"]
          }
        }
      }
    }
  }
}
```

---

## Дополнительная информация

### Лучшие практики

1. **Retain для production:** Используйте `persistentVolumeClaimRetentionPolicy: Retain` для защиты данных.
2. **StorageClass:** Указывайте `storageClassName` явно, а не полагайтесь на дефолт.
3. **Размер:** Не создавайте PVC > 1 Ti без проверки лимитов StorageClass.
4. **resource-policy: keep:** Добавляйте для PVC с критичными данными.
5. **Резервное копирование:** Используйте VolumeSnapshots для бэкапов.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `PersistentVolumeClaim is not bound` | Нет подходящего PV или StorageClass | Проверьте `kubectl get sc` и `kubectl get pv` |
| `exceeded quota` | ResourceQuota блокирует создание PVC | Увеличьте квоту или создайте PVC в другом namespace |
| `node affinity conflict` | PV привязан к другому узлу | Используйте `WaitForFirstConsumer` binding mode |

### См. также

- [PV и PVC](../../../../Storage/pv_and_pvc.md) — полная теория хранилищ.
- [StatefulSet: ключевые концепции](../../../../Base/StatefulSet/statefulset_core_concepts.md) — volumeClaimTemplates.
- [Шаблонизация StatefulSet](./statefulset.md) — деплой stateful-приложений.
