# Шаблонизация PodDisruptionBudget в Helm

---

## Определения

**PodDisruptionBudget (PDB)** — ресурс Kubernetes (`policy/v1`), ограничивающий количество одновременно недоступных подов при **добровольных** прерываниях (drain узла, eviction, upgrade). Не защищает от вынужденных сбоев (падение узла, OOMKill).

**minAvailable** — минимальное количество (или процент) подов, которые должны оставаться доступными. PDB блокирует eviction, если доступных подов станет меньше этого значения.

**maxUnavailable** — максимальное количество (или процент) подов, которые могут быть недоступны одновременно. Альтернатива `minAvailable`.

**Voluntary Disruption** — запланированные операции: `kubectl drain`, обновление Deployment, перемещение подов. PDB контролирует только эти операции.

**Involuntary Disruption** — незапланированные сбои: падение узла, OOMKill, сбой сети. PDB не действует в этих случаях.

---

## Базовые концепции

### Формулы расчёта

| Формула | Описание |
|---------|----------|
| `minAvailable >= 2` | Минимум 2 пода должны быть готовы |
| `maxUnavailable <= 1` | Максимум 1 под может быть недоступен |
| `minAvailable: 50%` | Минимум половина подов |
| `maxUnavailable: 1` для 3 подов | Можно выселить 1, доступны 2 |

### Приоритет при конфликте

Если `minAvailable` и `maxUnavailable` заданы одновременно, Kubernetes использует `maxUnavailable` для вычисления допустимого количества eviction.

### Взаимодействие с Deployment

- PDB **не блокирует** Rolling Update напрямую
- PDB блокирует eviction при `kubectl drain`
- Контроллер Deployment не проверяет PDB при изменении `replicas`

### Взаимодействие с StatefulSet

- При `kubectl drain` поды StatefulSet выселяются с учётом PDB
- Кворумные системы (etcd, Kafka): настраивайте `minAvailable` на основе кворума

---

## Практические сценарии

### Базовый PDB для Deployment

```yaml
# values.yaml
pdb:
  enabled: true
  minAvailable: 2
  # или maxUnavailable: 1
```

```yaml
# templates/pdb.yaml
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
{{- end }}
```

### PDB с процентным значением

```yaml
# values.yaml
pdb:
  enabled: true
  minAvailable: "50%"
```

```yaml
# templates/pdb.yaml
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  {{- if kindIs "string" .Values.pdb.minAvailable }}
  minAvailable: {{ .Values.pdb.minAvailable | quote }}
  {{- else }}
  minAvailable: {{ .Values.pdb.minAvailable | int }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
{{- end }}
```

### PDB с maxUnavailable

```yaml
# templates/pdb.yaml
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  {{- if .Values.pdb.maxUnavailable }}
  maxUnavailable: {{ .Values.pdb.maxUnavailable }}
  {{- else }}
  minAvailable: {{ .Values.pdb.minAvailable | default 1 }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
{{- end }}
```

### PDB для StatefulSet

```yaml
# templates/pdb-statefulset.yaml
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}-pdb
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable | default 1 }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "myapp.name" . }}
      app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

### PDB для кворумных систем (etcd, Kafka, ZooKeeper)

```yaml
# values.yaml
pdb:
  enabled: true
  # Для кластера из 3 подов: кворум = 2
  minAvailable: 2
```

```yaml
# templates/pdb.yaml
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}-pdb
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "myapp.name" . }}
      app.kubernetes.io/instance: {{ .Release.Name }}
      app.kubernetes.io/component: {{ .Values.pdb.component | default "primary" }}
{{- end }}
```

### PDB для DaemonSet

```yaml
# templates/pdb-daemonset.yaml
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}-pdb
spec:
  maxUnavailable: {{ .Values.pdb.maxUnavailable | default 1 }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
{{- end }}
```

### PDB с condition (включение только для production)

```yaml
# templates/pdb.yaml
{{- if and .Values.pdb.enabled (eq .Values.global.env "production") }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
{{- end }}
```

### Валидация через values.schema.json

```json
{
  "properties": {
    "pdb": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "minAvailable": {
          "oneOf": [
            { "type": "integer", "minimum": 0 },
            { "type": "string", "pattern": "^[0-9]+%?$" }
          ]
        },
        "maxUnavailable": {
          "oneOf": [
            { "type": "integer", "minimum": 0 },
            { "type": "string", "pattern": "^[0-9]+%?$" }
          ]
        }
      }
    }
  }
}
```

---

## Дополнительная информация

### Лучшие практики

1. **Для stateless-приложений:** `maxUnavailable: 1` — безопасный дефолт.
2. **Для кворумных систем:** `minAvailable: (N/2 + 1)` — гарантирует кворум.
3. **Не комбинируйте:** Используйте либо `minAvailable`, либо `maxUnavailable`, но не оба.
4. **Проценты для больших кластеров:** `maxUnavailable: 25%` для 10+ подов.
5. **Проверяйте:** `kubectl get pdb -n <namespace>` перед `kubectl drain`.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `drain` блокируется | PDB не позволяет выселить достаточно подов | Увеличьте `maxUnavailable` или уменьшите `minAvailable` |
| PDB не защищает от OOMKill | PDB контролирует только voluntary disruptions | Используйте ResourceQuota и Limits |
| PDB не работает с HPA | PDB и HPA конфликтуют при масштабировании | Настройте PDB с учётом maxReplicas HPA |

### См. также

- [PodDisruptionBudget](../../../../Autoscaling/pod_disruption_budget.md) — полная теория PDB.
- [Шаблонизация StatefulSet](./statefulset.md) — PDB для stateful-приложений.
- [Шаблонизация ResourceQuota](./resource_quota.md) — управление ресурсами namespace.
