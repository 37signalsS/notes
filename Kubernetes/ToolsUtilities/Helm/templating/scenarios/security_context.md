# Шаблонизация SecurityContext в Helm

---

## Определения

**SecurityContext** — набор настроек безопасности, применяемых на уровне Pod (`podSecurityContext`) или отдельного контейнера (`securityContext`). Определяет UID/GID запуска, capabilities, seccomp-профиль и политики файловой системы.

**Pod Security Standards (PSS)** — три уровня безопасности (`privileged`, `baseline`, `restricted`), регулирующие допустимые параметры SecurityContext на уровне Namespace через Pod Security Admission (PSA).

**allowPrivilegeEscalation** — флаг, разрешающий контейнеру получить привилегии выше родительского процесса. В restricted-политиках должен быть `false`.

**seccompProfile** — профиль фильтрации системных вызовов Linux. `RuntimeDefault` использует дефолтный профиль container runtime; `Localhost` — пользовательский файл на узле.

**Pod Security Admission (PSA)** — механизм Kubernetes (стабилен с 1.25), блокирующий создание подов, не соответствующих политике уровня в Namespace. Управляется лейблами: `pod-security.kubernetes.io/enforce`.

---

## Базовые концепции

### Уровни SecurityContext

| Поле | Уровень | Описание |
|------|---------|----------|
| `runAsNonRoot: true` | Restricted | Запрещает запуск от root (UID 0) |
| `runAsUser: 1000` | Restricted | Фиксирует UID процесса |
| `fsGroup: 1000` | Restricted | GID для ownership томов |
| `readOnlyRootFilesystem: true` | Restricted | Запрещает запись в корень FS |
| `allowPrivilegeEscalation: false` | Restricted | Запрещает повышение привилегий |
| `capabilities.drop: ["ALL"]` | Restricted | Снимает все Linux capabilities |
| `seccompProfile.type: RuntimeDefault` | Baseline | Ограничивает syscall-ы |
| `runAsUser: 0` | Privileged | Запуск от root (только в privileged) |

### Иерархия настроек

Pod SecurityContext задаёт дефолты для всех контейнеров. SecurityContext контейнера переопределяет Pod-уровень:

```
Pod.spec.securityContext (fsGroup, runAsUser, seccompProfile)
  └─ Container.spec.securityContext (allowPrivilegeEscalation, capabilities, readOnlyRootFilesystem)
```

### Связь с Pod Security Admission

PSA проверяет Pod/контейнер SecurityContext перед допуском. Если на Namespace включен `enforce: restricted`, поды с `privileged: true` или без `seccompProfile` будут отклонены.

### Взаимодействие с StorageClass

Поле `fsGroup` в Pod SecurityContext влияет на ownership файлов на томах (PVC). Для NFS и CephFS маппинг зависит от настроек сервера.

---

## Практические сценарии

### Базовый SecurityContext в Deployment

```yaml
# values.yaml
securityContext:
  enabled: true
  pod:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  container:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: ["ALL"]
```

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  template:
    spec:
      {{- if .Values.securityContext.enabled }}
      securityContext:
        runAsNonRoot: {{ .Values.securityContext.pod.runAsNonRoot }}
        runAsUser: {{ .Values.securityContext.pod.runAsUser }}
        fsGroup: {{ .Values.securityContext.pod.fsGroup }}
        {{- with .Values.securityContext.pod.seccompProfile }}
        seccompProfile:
          {{- toYaml . | nindent 10 }}
        {{- end }}
      {{- end }}
      containers:
        - name: app
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          {{- if .Values.securityContext.enabled }}
          securityContext:
            allowPrivilegeEscalation: {{ .Values.securityContext.container.allowPrivilegeEscalation }}
            readOnlyRootFilesystem: {{ .Values.securityContext.container.readOnlyRootFilesystem }}
            {{- with .Values.securityContext.container.capabilities }}
            capabilities:
              {{- toYaml . | nindent 14 }}
            {{- end }}
          {{- end }}
```

### Условный SecurityContext для production

```yaml
# templates/deployment.yaml
securityContext:
  {{- if eq .Values.global.env "production" }}
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
  {{- else }}
  runAsNonRoot: false
  runAsUser: 0
  {{- end }}
```

### SecurityContext с ttl для временных данных

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 65534  # nobody
  fsGroup: 65534
  runAsGroup: 65534
  supplementalGroups: [65534]
```

### SecurityContext для init-контейнеров

```yaml
initContainers:
  - name: init-db
    image: "{{ .Values.init.image }}"
    securityContext:
      runAsNonRoot: true
      runAsUser: 1000
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
```

### SecurityContext в StatefulSet с volumeClaimTemplates

```yaml
# templates/statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  serviceName: {{ include "myapp.fullname" . }}-headless
  replicas: {{ .Values.replicaCount }}
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: {{ .Values.db.runAsUser | default 999 }}
        fsGroup: {{ .Values.db.fsGroup | default 999 }}
      containers:
        - name: db
          image: "{{ .Values.db.image }}:{{ .Values.db.tag }}"
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: false
            capabilities:
              drop: ["ALL"]
```

### SecurityContext в hooks (Job)

```yaml
# templates/job-migrate.yaml
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
      securityContext:
        runAsNonRoot: true
        runAsUser: {{ .Values.migration.runAsUser | default 1000 }}
      containers:
        - name: migrate
          image: "{{ .Values.migration.image }}:{{ .Values.migration.tag }}"
          command: ["/bin/sh", "-c", "{{ .Values.migration.command }}"]
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
      restartPolicy: Never
```

### Валидация SecurityContext через values.schema.json

```json
{
  "properties": {
    "securityContext": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "pod": {
          "type": "object",
          "properties": {
            "runAsNonRoot": { "type": "boolean" },
            "runAsUser": { "type": "integer", "minimum": 0 },
            "fsGroup": { "type": "integer", "minimum": 0 },
            "seccompProfile": {
              "type": "object",
              "properties": {
                "type": { "enum": ["RuntimeDefault", "Localhost"] }
              }
            }
          }
        },
        "container": {
          "type": "object",
          "properties": {
            "allowPrivilegeEscalation": { "type": "boolean" },
            "readOnlyRootFilesystem": { "type": "boolean" },
            "capabilities": {
              "type": "object",
              "properties": {
                "drop": {
                  "type": "array",
                  "items": { "type": "string" }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### Паттерн: дефолты для restricted namespace

```yaml
# templates/_helpers.tpl
{{- define "myapp.securityContext" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: {{ .Values.securityContext.runAsUser | default 1000 }}
  fsGroup: {{ .Values.securityContext.fsGroup | default 1000 }}
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{- define "myapp.containerSecurityContext" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: {{ .Values.securityContext.readOnlyRootFilesystem | default true }}
  capabilities:
    drop: ["ALL"]
{{- end -}}
```

```yaml
# templates/deployment.yaml
spec:
  template:
    spec:
      {{- include "myapp.securityContext" . | nindent 6 }}
      containers:
        - name: app
          {{- include "myapp.containerSecurityContext" . | nindent 10 }}
```

---

## Дополнительная информация

### Лучшие практики

1. **Restricted для production:** Включайте `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true` по умолчанию.
2. **seccompProfile обязателен:** Для restricted-политики PSA требует `seccompProfile.type: RuntimeDefault` или `Localhost`.
3. **fsGroup для PVC:** Устанавливайте `fsGroup` при монтировании PersistentVolumeClaim, чтобы избежать проблем с правами доступа.
4. **Исключения для特权:** Для特权 контейнеров (syscall, netshoot) используйте отдельные values-файлы с `privileged: true`.
5. **Тестирование:** Проверяйте SecurityContext через `kube-score` и `kubeconform` в CI/CD.
6. **Audit аннотации:** Добавляйте `audit.security.kubernetes.io/pod-level: "restricted"` для отслеживания соблюдения политик.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `forbidden: violates PodSecurity "restricted:latest"` | PSA блокирует под без `runAsNonRoot` или `seccompProfile` | Добавьте обязательные поля в SecurityContext |
| `Error: container has runAsNonRoot but image runs as root` | Образ запускает процесс от root | Используйте `runAsUser: <UID>` или исправьте Dockerfile |
| `permission denied on volume` | Несовпадение `fsGroup` с правами на PV | Установите `fsGroup` в Pod SecurityContext |
| `unable to upgrade path /var/run/docker.sock` | `readOnlyRootFilesystem: true` блокирует запись | Используйте `emptyDir` или `hostPath` для socket |

### См. также

- [Pod Security Context](../../../../Security/pod_security_context.md) — полная теория SecurityContext и PSS.
- [Шаблонизация PodDisruptionBudget](./pdb.md) — защита доступности при обслуживании.
- [Шаблонизация StatefulSet](./statefulset.md) — безопасный деплой stateful-приложений.
