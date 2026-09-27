# Шаблонизация StatefulSet в Helm

---

## Определения

**StatefulSet** — контроллер Kubernetes для управления приложениями с состоянием (stateful), обеспечивающий стабильные сетевые имена, стабильное хранилище и упорядоченное развёртывание.

**Headless Service** — Service с `clusterIP: None`, необходимый для генерации DNS-записей вида `pod-name.service-name.namespace.svc.cluster.local`.

**volumeClaimTemplates** — шаблон в StatefulSet, автоматически создающий PersistentVolumeClaim для каждого индекса пода.

**podManagementPolicy** — политика управления подами: `OrderedReady` (по порядку, по умолчанию) или `Parallel` (все сразу).

**updateStrategy** — стратегия обновления: `RollingUpdate` (по умолчанию) или `OnDelete` (только при ручном удалении).

**partition** — поле rollout-стратегии, позволяющее обновить только поды с ordinal >= N. Используется для Canary-деплоев.

**persistentVolumeClaimRetentionPolicy** — политика удаления PVC: `Retain` (оставить) или `Delete` (удалить) при масштабировании/удалении StatefulSet.

---

## Базовые концепции

### Стабильные имена

```
StatefulSet: mysql
  mysql-0 (первый под)
  mysql-1 (второй под)
  mysql-2 (третий под)
```

### Headless Service + StatefulSet

```
Headless Service: mysql-headless (clusterIP: None)
  └─ DNS-записи:
       mysql-0.mysql-headless.default.svc.cluster.local
       mysql-1.mysql-headless.default.svc.cluster.local
       mysql-2.mysql-headless.default.svc.cluster.local
```

### Жизненный цикл PVC

1. При первом `helm install` PVC создаются для каждого индекса
2. При `helm upgrade` PVC **не пересоздаются** (защита данных)
3. При `helm uninstall` PVC **остаются** по умолчанию
4. При масштабировании вниз PVC **не удаляются**
5. При масштабировании вверх PVC создаются для новых индексов

---

## Практические сценарии

### Базовый StatefulSet

```yaml
# values.yaml
statefulset:
  enabled: true
  replicaCount: 3
  serviceName: mysql-headless
  podManagementPolicy: OrderedReady
  updateStrategy:
    type: RollingUpdate
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
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  serviceName: {{ .Values.statefulset.serviceName | default (printf "%s-headless" (include "myapp.fullname" .)) }}
  replicas: {{ .Values.statefulset.replicaCount }}
  podManagementPolicy: {{ .Values.statefulset.podManagementPolicy | default "OrderedReady" }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  updateStrategy:
    type: {{ .Values.statefulset.updateStrategy.type | default "RollingUpdate" }}
    {{- if eq (.Values.statefulset.updateStrategy.type | default "RollingUpdate") "RollingUpdate" }}
    rollingUpdate:
      partition: {{ .Values.statefulset.updateStrategy.partition | default 0 }}
    {{- end }}
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: {{ .Values.statefulset.persistence.retentionPolicy | default "Retain" }}
    whenScaled: {{ .Values.statefulset.persistence.retentionPolicy | default "Retain" }}
  template:
    metadata:
      labels:
        {{- include "myapp.labels" . | nindent 8 }}
    spec:
      containers:
        - name: app
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          ports:
            - containerPort: {{ .Values.service.port }}
          {{- with .Values.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
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

### Headless Service для StatefulSet

```yaml
# templates/service-headless.yaml
{{- if .Values.statefulset.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: {{ .Values.statefulset.serviceName | default (printf "%s-headless" (include "myapp.fullname" .)) }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  clusterIP: None
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.targetPort | default .Values.service.port }}
      protocol: TCP
      name: http
  selector:
    {{- include "myapp.selectorLabels" . | nindent 4 }}
{{- end }}
```

### StatefulSet с init-контейнером

```yaml
# templates/statefulset.yaml
spec:
  template:
    spec:
      initContainers:
        - name: init-db
          image: "{{ .Values.init.image }}:{{ .Values.init.tag }}"
          command: ["/bin/sh", "-c", "{{ .Values.init.command }}"]
          volumeMounts:
            - name: data
              mountPath: /data
```

### StatefulSet с custom podManagementPolicy

```yaml
# values.yaml
statefulset:
  podManagementPolicy: Parallel
```

### StatefulSet с partition для Canary

```yaml
# values.yaml
statefulset:
  updateStrategy:
    type: RollingUpdate
    partition: 2  # Обновить только поды 2, 3, 4 (при 5 репликах)
```

### StatefulSet с multiple volumeClaimTemplates

```yaml
# templates/statefulset.yaml
spec:
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: {{ .Values.persistence.data.storageClass | quote }}
        resources:
          requests:
            storage: {{ .Values.persistence.data.size | quote }}
    - metadata:
        name: wal
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: {{ .Values.persistence.wal.storageClass | quote }}
        resources:
          requests:
            storage: {{ .Values.persistence.wal.size | quote }}
```

### StatefulSet с SecurityContext

```yaml
# templates/statefulset.yaml
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: {{ .Values.db.runAsUser | default 999 }}
        fsGroup: {{ .Values.db.fsGroup | default 999 }}
      containers:
        - name: db
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: false
            capabilities:
              drop: ["ALL"]
```

### StatefulSet с PodDisruptionBudget

```yaml
# templates/pdb.yaml
{{- if and .Values.statefulset.enabled .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}-pdb
spec:
  minAvailable: {{ .Values.pdb.minAvailable | default 1 }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "myapp.name" . }}
      app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

### StatefulSet с hooks для миграций

```yaml
# templates/job-migrate.yaml
{{- if and .Values.statefulset.enabled .Values.migrations.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "myapp.fullname" . }}-migrate
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "-10"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      containers:
        - name: migrate
          image: "{{ .Values.migration.image }}:{{ .Values.migration.tag }}"
          command: ["/bin/sh", "-c", "{{ .Values.migration.command }}"]
      restartPolicy: Never
{{- end }}
```

### Валидация через values.schema.json

```json
{
  "properties": {
    "statefulset": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "replicaCount": { "type": "integer", "minimum": 1 },
        "podManagementPolicy": { "enum": ["OrderedReady", "Parallel"] },
        "updateStrategy": {
          "type": "object",
          "properties": {
            "type": { "enum": ["RollingUpdate", "OnDelete"] },
            "partition": { "type": "integer", "minimum": 0 }
          }
        },
        "persistence": {
          "type": "object",
          "properties": {
            "size": { "type": "string", "pattern": "^[0-9]+(Gi|Mi|Ti)$" },
            "storageClass": { "type": "string" },
            "retentionPolicy": { "enum": ["Retain", "Delete"] }
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

1. **Headless Service:** Всегда создавайте отдельный Headless Service для StatefulSet.
2. **Retain:** Используйте `persistentVolumeClaimRetentionPolicy: Retain` для защиты данных.
3. **partition:** Используйте для Canary-деплоев: обновите сначала один под, затем остальные.
4. **PDB:** Настраивайте PodDisruptionBudget для кворумных систем.
5. **SecurityContext:** Устанавливайте `fsGroup` для корректного доступа к томам.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `Pod Pending` | PVC не привязан к PV | Проверьте StorageClass и размер |
| `CrashLoopBackOff` | Неверный securityContext | Проверьте `runAsUser` и права на том |
| `Split-brain` | Принудительное удаление пода | Используйте `kubectl delete pod --force` только при потере узла |

### См. также

- [StatefulSet: ключевые концепции](../../../../Base/StatefulSet/statefulset_core_concepts.md) — полная теория.
- [StatefulSet: лучшие практики](../../../../Base/StatefulSet/statefulset_best_practices.md) — рекомендации.
- [Шаблонизация Persistence](./persistence.md) — volumeClaimTemplates.
- [Шаблонизация PodDisruptionBudget](./pdb.md) — защита доступности.
