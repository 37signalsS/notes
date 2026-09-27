# Шаблонизация VerticalPodAutoscaler (VPA) в Helm

---

## Определения

**VerticalPodAutoscaler (VPA)** — ресурс Kubernetes (`autoscaling.k8s.io/v1`), автоматически корректирующий requests/limits контейнеров на основе анализа реального потребления CPU и Memory. Работает в четырёх режимах: `Off` (только рекомендации), `Initial` (при создании Pod), `Recreate` (пересоздание Pod) и `InPlaceOrRecreate` (in-place resize или пересоздание).

**updateMode** — política обновления VPA, определяющая как и когда применяются рекомендации: `Off`, `Initial`, `Recreate`, `InPlaceOrRecreate`, `InPlace`.

**resourcePolicy** — блок политики, ограничивающий диапазон рекомендаций VPA через `minAllowed` / `maxAllowed` и определяющий, какие контейнеры масштабировать (`containerPolicies`).

**controlledValues** — поле в `containerPolicies`, определяющее что именно VPA управляет: `RequestsOnly` (только requests) или `RequestsAndLimits` (requests и limits).

**targetRef** — ссылка на целевой ресурс (Deployment, StatefulSet, DaemonSet, ReplicationController, Job), который VPA будет масштабировать.

**recommendation** — текущие рекомендации VPA, доступные через `kubectl describe vpa <name>` или CRD `VerticalPodAutoscalerRecommender`.

---

## Базовые концепции

### Режимы VPA и их влияние

| Режим | Поведение | Влияние на Pod | Когда использовать |
|-------|-----------|----------------|-------------------|
| `Off` | Только рекомендации, не применяет | Не влияет | Right-sizing, мониторинг, совместимость с HPA |
| `Initial` | Устанавливает при создании Pod | Только новые Pod'ы | Безопасный старт, gradual migration |
| `Recreate` | Пересоздаёт Pod при изменении | Убивает и пересоздаёт | Полная автоматизация, допустим даунтайм |
| `InPlaceOrRecreate` | In-place resize если возможно, иначе пересоздание | Обновляет ресурсы без перезапуска | StatefulSet, долгоживущие соединения |
| `InPlace` | Только in-place resize | Обновляет ресурсы без перезапуска | StatefulSet, БД без даунтайма |

### VPA vs HPA: конфликт и совместимость

| Сценарий | Конфликт | Решение |
|----------|----------|---------|
| VPA `Recreate` + HPA по CPU/Memory | VPA перезаписывает requests, HPA ломает расчёт utilization | VPA в режиме `Off` или `Initial` |
| VPA `Off` + HPA по кастомной метрике | Нет конфликта | Рекомендуемая комбинация |
| VPA + HPA по CPU (оба в Auto) | Прямой конфликта | Запрещено |

### Взаимодействие с ResourceQuota и LimitRange

- VPA увеличивает requests → может превысить ResourceQuota
- LimitRange.max ограничивает максимальный request, который VPA может установить
- Рекомендация: `ResourceQuota >= maxReplicas × VPA.maxAllowed.cpu × 1.2`

### Валидация через values.schema.json

VPA-параметры не должны позволять `minAllowed > maxAllowed`:

```json
{
  "properties": {
    "vpa": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "updateMode": { "enum": ["Off", "Initial", "Recreate", "InPlaceOrRecreate", "InPlace"] },
        "minAllowed": {
          "type": "object",
          "properties": {
            "cpu": { "type": "string" },
            "memory": { "type": "string" }
          }
        },
        "maxAllowed": {
          "type": "object",
          "properties": {
            "cpu": { "type": "string" },
            "memory": { "type": "string" }
          }
        }
      }
    }
  }
}
```

---

## Практические сценарии

### Базовый VPA для Deployment

```yaml
# values.yaml
vpa:
  enabled: true
  updateMode: "Off"
  targetRef:
    kind: Deployment
```

```yaml
# templates/vpa.yaml
{{- if .Values.vpa.enabled }}
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: {{ include "myapp.fullname" . }}-vpa
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  targetRef:
    apiVersion: apps/v1
    kind: {{ .Values.vpa.targetRef.kind | default "Deployment" }}
    name: {{ include "myapp.fullname" . }}
  updatePolicy:
    updateMode: {{ .Values.vpa.updateMode | quote }}
{{- end }}
```

### VPA с resourcePolicy (ограничение диапазона)

```yaml
# values.yaml
vpa:
  enabled: true
  updateMode: "Recreate"
  resourcePolicy:
    containerPolicies:
      - containerName: "app"
        minAllowed:
          cpu: "100m"
          memory: "128Mi"
        maxAllowed:
          cpu: "4"
          memory: "8Gi"
        controlledValues: RequestsAndLimits
      - containerName: "sidecar"
        mode: "Off"
```

```yaml
# templates/vpa.yaml
{{- if .Values.vpa.enabled }}
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: {{ include "myapp.fullname" . }}-vpa
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  targetRef:
    apiVersion: apps/v1
    kind: {{ .Values.vpa.targetRef.kind | default "Deployment" }}
    name: {{ include "myapp.fullname" . }}
  updatePolicy:
    updateMode: {{ .Values.vpa.updateMode | quote }}
  {{- if .Values.vpa.resourcePolicy }}
  resourcePolicy:
    containerPolicies:
      {{- range .Values.vpa.resourcePolicy.containerPolicies }}
      - containerName: {{ .containerName | quote }}
        {{- if .mode }}
        mode: {{ .mode | quote }}
        {{- end }}
        {{- if .minAllowed }}
        minAllowed:
          {{- toYaml .minAllowed | nindent 10 }}
        {{- end }}
        {{- if .maxAllowed }}
        maxAllowed:
          {{- toYaml .maxAllowed | nindent 10 }}
        {{- end }}
        {{- if .controlledValues }}
        controlledValues: {{ .controlledValues }}
        {{- end }}
      {{- end }}
  {{- end }}
{{- end }}
```

### VPA для StatefulSet с InPlace-режимом

```yaml
# values.yaml
vpa:
  enabled: true
  updateMode: "InPlaceOrRecreate"
  targetRef:
    kind: StatefulSet
  resourcePolicy:
    containerPolicies:
      - containerName: "postgres"
        minAllowed:
          cpu: "250m"
          memory: "512Mi"
        maxAllowed:
          cpu: "8"
          memory: "32Gi"
        controlledValues: RequestsAndLimits
```

```yaml
# templates/vpa.yaml
{{- if .Values.vpa.enabled }}
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: {{ include "myapp.fullname" . }}-vpa
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  targetRef:
    apiVersion: apps/v1
    kind: {{ .Values.vpa.targetRef.kind }}
    name: {{ include "myapp.fullname" . }}
  updatePolicy:
    updateMode: {{ .Values.vpa.updateMode | quote }}
  {{- if .Values.vpa.resourcePolicy }}
  resourcePolicy:
    containerPolicies:
      {{- toYaml .Values.vpa.resourcePolicy.containerPolicies | nindent 6 }}
  {{- end }}
{{- end }}
```

### VPA + HPA по разным метрикам (рекомендуемый паттерн)

```yaml
# values.yaml
vpa:
  enabled: true
  updateMode: "Off"  # Только рекомендации

hpa:
  enabled: true
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "100"
```

```yaml
# templates/vpa.yaml
{{- if .Values.vpa.enabled }}
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: {{ include "myapp.fullname" . }}-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "myapp.fullname" . }}
  updatePolicy:
    updateMode: "Off"
  resourcePolicy:
    containerPolicies:
      - containerName: "app"
        controlledValues: RequestsAndLimits
{{- end }}
---
# templates/hpa.yaml
{{- if .Values.hpa.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "myapp.fullname" . }}-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "myapp.fullname" . }}
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
    {{- toYaml .Values.hpa.metrics | nindent 4 }}
{{- end }}
```

### VPA с conditions (production-only)

```yaml
# templates/vpa.yaml
{{- if and .Values.vpa.enabled (eq .Values.global.env "production") }}
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: {{ include "myapp.fullname" . }}-vpa
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  targetRef:
    apiVersion: apps/v1
    kind: {{ .Values.vpa.targetRef.kind | default "Deployment" }}
    name: {{ include "myapp.fullname" . }}
  updatePolicy:
    updateMode: {{ .Values.vpa.updateMode | quote }}
{{- end }}
```

### VPA с динамическим списком контейнеров

```yaml
# values.yaml
vpa:
  enabled: true
  updateMode: "Off"
  resourcePolicy:
    containerPolicies:
      - containerName: "app"
        mode: "Auto"
      - containerName: "istio-proxy"
        mode: "Off"
      - containerName: "vault-agent"
        mode: "Off"
```

```yaml
# templates/vpa.yaml
{{- if .Values.vpa.enabled }}
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: {{ include "myapp.fullname" . }}-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: {{ .Values.vpa.targetRef.kind | default "Deployment" }}
    name: {{ include "myapp.fullname" . }}
  updatePolicy:
    updateMode: {{ .Values.vpa.updateMode | quote }}
  resourcePolicy:
    containerPolicies:
      {{- range .Values.vpa.resourcePolicy.containerPolicies }}
      - containerName: {{ .containerName | quote }}
        {{- if .mode }}
        mode: {{ .mode | quote }}
        {{- end }}
      {{- end }}
{{- end }}
```

---

## Дополнительная информация

### Лучшие практики

1. **Начинайте с `Off`:** Режим `Off` позволяет собрать рекомендации без влияния на рабочую нагрузку.
2. **Не комбинируйте с HPA по CPU/Memory:** Используйте VPA `Off` + HPA по кастомной метрике.
3. **Ограничивайте `maxAllowed`:** Без ограничений VPA может установить экстремальные значения.
4. **Для StatefulSet:** Используйте `InPlaceOrRecreate` или `InPlace` для избежания даунтайма.
5. **Мониторьте рекомендации:** Используйте Goldilocks или Grafana для визуализации рекомендаций VPA.
6. **Проверяйте ResourceQuota:** Убедитесь, что квоты достаточны для максимально возможных requests.
7. **VPA + CRD:** VPA требует установки CRD и recommender/controller в кластер.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| VPA не применяет рекомендации | Режим `Off` или `Initial` | Используйте `Recreate` или `InPlaceOrRecreate` |
| Pod убивается при изменении | VPA в режиме `Recreate` | Используйте `InPlaceOrRecreate` для StatefulSet |
| HPA не масштабирует | VPA перезаписывает requests | Переведите VPA в `Off` или используйте кастомные метрики для HPA |
| `exceeded quota` после VPA | VPA увеличила requests сверх ResourceQuota | Увеличьте ResourceQuota или ограничьте `maxAllowed` |
| VPA не создаётся | CRD `VerticalPodAutoscaler` не установлен | Установите VPA через `kubectl apply -f https://github.com/kubernetes/autoscaler/releases/download/vertical-pod-autoscaler-v0.28.0/vertical-pod-autoscaler.yaml` |
| Рекомендации не обновляются | Recommender не имеет данных | Подождите 5-10 минут для сбора метрик |

### См. также

- [VerticalPodAutoscaler: подробный обзор](../../../../Autoscaling/vpa_detailed.md) — полная теория VPA, режимы, CRD.
- [HPA: продвинутые темы](../../../../Autoscaling/HPA/hpa_advanced.md) — комбинация VPA и HPA.
- [Шаблонизация PDB](./pdb.md) — защита от прерываний при масштабировании.
- [Шаблонизация ResourceQuota](./resource_quota.md) — управление ресурсами namespace.
