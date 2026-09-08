# Паттерн Helm Skeleton

Паттерн Helm Skeleton (скелет чарта) — это методология стандартизации развёртывания множества однотипных микросервисов путём создания единого эталонного шаблона. Использование скелета позволяет избежать фрагментации конфигураций, обеспечить единообразие именования ресурсов и ускорить запуск новых компонентов системы.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Helm Skeleton** | Эталонная структура чарта, используемая как основа для создания новых сервисов. Хранится в отдельной директории (`_template/`) или репозитории. |
| **Helm Starter** | Встроенный механизм Helm (`helm create --starter`), позволяющий генерировать чарты из кастомного шаблона из директории `$HELM_DATA_HOME/starters`. |
| **Boilerplate** | Повторяющийся "шаблонный" код манифестов, который выносится в общие шаблоны для минимизации ручного труда. |
| **Shared Chart** | Один полноценный чарт, используемый для деплоя множества разных приложений путём передачи различных `values.yaml`. |
| **Library Chart** | Библиотечный чарт (`type: library`), содержащий только именованные шаблоны и логику без собственных манифестов. |
| **Boilerplate Generator** | Внешний инструмент (Cookiecutter, Copier, cruft), обеспечивающий синхронизацию локальных копий скелета с эталоном. |
| **values.schema.json** | Файл JSON Schema для декларативной валидации структуры, типов данных и ограничений в `values.yaml` перед началом выполнения шаблонов. |

---

## Базовые концепции

### Цели использования паттерна

1.  **Стандартизация:** Гарантирует, что все сервисы имеют одинаковый набор меток (labels), аннотаций, настроек безопасности (`SecurityContext`) и политик обновления.
2.  **Автономия:** В отличие от Shared Chart, каждый сервис владеет копией своих манифестов. Это позволяет разработчикам вносить точечные правки в конкретный чарт без риска сломать другие сервисы.
3.  **Скорость и предсказуемость:** Новые микросервисы запускаются с уже настроенными "лучшими практиками" (HPA, PDB, лимиты ресурсов, аффинити).
4.  **Независимость релизов:** Каждый сервис развёртывается и откатывается самостоятельно, без влияния на другие компоненты.
5.  **Закреплённая безопасность:** SecurityContext, NetworkPolicy и минимальные права ServiceAccount заданы по умолчанию и не требуют ручного добавления при создании нового сервиса.

### Сравнение подходов к масштабированию

| Подход | Механизм | Плюсы | Минусы |
|--------|----------|-------|--------|
| **Skeleton** | Копирование эталона | Полная автономность, простота отладки | Дублирование кода, сложность массового обновления |
| **Shared Chart** | Один чарт для всех | Нет дублирования, мгновенное обновление всех | Избыточная сложность, риск "единой точки отказа" |
| **Library Chart** | Подключение логики | Чистые шаблоны, централизованная логика | Требует глубокого понимания Go Templates |

**Когда выбирать Skeleton:**
- Сервисы имеют существенные различия в конфигурации (разные порты, зависимости, политики сети).
- Команда сервиса автономна и не хочет зависеть от общего чарта.
- Нужна возможность кастомизации без влияния на другие сервисы.
- Количество сервисов < 20 (при большем количестве Shared Chart становится эффективнее).

**Когда выбирать Shared Chart:**
- Сервисы однотипны и отличаются только параметрами (replicas, resources, env).
- Нужно централизованно обновлять логику для всех сервисов одновременно.
- Важна единообразная безопасность и compliance.

**Когда выбирать Library Chart:**
- Логика сложна и содержит условия, которые неудобно дублировать в каждом скелете.
- Нужно переиспользовать логику между Skeleton и Shared Chart одновременно.

### Создание базы скелета

Для создания скелета рекомендуется использовать стандартную команду, предварительно очистив результат от ненужных комментариев и избыточных примеров:

```bash
# Создание базового скелета
helm create _template

# Очистка от стандартных файлов
rm -f _template/templates/ingress.yaml
rm -f _template/templates/hpa.yaml
rm -f _template/templates/serviceaccount.yaml

# Проверка структуры
find _template -type f | sort
# → result:
# _template/Chart.yaml
# _template/values.yaml
# _template/templates/_helpers.tpl
# _template/templates/deployment.yaml
# _template/templates/service.yaml
# _template/templates/NOTES.txt
```

**Важно (Helm v4):** Убедитесь, что `Chart.yaml` содержит `apiVersion: v2` — это стандарт для Helm v4. Старый формат `apiVersion: v1` не поддерживает SSA (Server-Side Apply) и современные зависимости.

```yaml
# _template/Chart.yaml
apiVersion: v2
name: skeleton-service
description: Skeleton Helm chart for microservices
type: application
version: 0.1.0
appVersion: "1.0.0"
```

**Директория скелета — минимальный набор файлов:**

```
_template/
├── Chart.yaml                  # Метаданные чарта
├── Chart.lock                  # Закреплённые зависимости (генерируется)
├── .helmignore                 # Исключения при упаковке
├── values.yaml                 # Значения по умолчанию
├── values.schema.json          # JSON Schema для валидации values
└── templates/
    ├── _helpers.tpl            # Именованные шаблоны
    ├── deployment.yaml         # Основной манифест
    ├── service.yaml            # Service
    ├── hpa.yaml                # HorizontalPodAutoscaler (опционально)
    ├── pdb.yaml                # PodDisruptionBudget (опционально)
    ├── configmap.yaml          # ConfigMap (опционально)
    ├── secret.yaml             # Secret (опционально)
    ├── ingress.yaml            # Ingress (опционально)
    ├── networkpolicy.yaml      # NetworkPolicy (опционально)
    ├── serviceaccount.yaml     # ServiceAccount (опционально)
    └── NOTES.txt               # Инструкции после установки
```

---

## Практические сценарии

### 1. Единый стандарт метаданных (_helpers.tpl)

Скелет должен содержать функции, генерирующие стандартный набор меток. Это критично для корректной работы мониторинга, Service Mesh и поиска ресурсов.

**templates/_helpers.tpl:**
```go
{{/*
Создаёт полное имя чарта с суффиксом release.
*/}}
{{- define "skeleton.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Метки чарта.
*/}}
{{- define "skeleton.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Базовые метки (стандарт Kubernetes).
*/}}
{{- define "skeleton.labels" -}}
helm.sh/chart: {{ include "skeleton.chart" . }}
{{ include "skeleton.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.additionalLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Метки селектора (для Service и Deployment).
*/}}
{{- define "skeleton.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Создаёт имя ServiceAccount.
*/}}
{{- define "skeleton.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "skeleton.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Стандартный набор аннотаций для Deployment.
Позволяет автоматически перезапускать поды при изменении ConfigMap/Secret.
*/}}
{{- define "skeleton.podAnnotations" -}}
checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
checksum/secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
{{- with .Values.podAnnotations }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Проверка обязательных параметров. Если значение не задано — шаблон падает с ошибкой.
Использование: {{ include "skeleton.required" (dict "value" .Values.image.repository "message" "image.repository is required") }}
*/}}
{{- define "skeleton.required" -}}
{{- if not .value }}
{{- fail (printf "%s" .message) }}
{{- end }}
{{- end }}

{{/*
Безопасное извлечение вложенного ключа из .Values с дефолтом.
Использование: {{ include "skeleton.dig" (dict "key" "foo.bar.baz" "default" "fallback" "ctx" .) }}
*/}}
{{- define "skeleton.dig" -}}
{{- $parts := splitList "." .key }}
{{- $result := .ctx }}
{{- range $parts }}
{{- if and $result (kindIs "map" $result) }}
{{- $result = index $result . }}
{{- else }}
{{- $result = $.default }}
{{- end }}
{{- end }}
{{- if $result }}{{ $result }}{{ else }}{{ $.default }}{{ end }}
{{- end }}
```

**Использование в шаблонах:**
```yaml
# deployment.yaml
metadata:
  name: {{ include "skeleton.fullname" . }}
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
spec:
  selector:
    matchLabels:
      {{- include "skeleton.selectorLabels" . | nindent 6 }}
```

**Вызов обязательных параметров в `_helpers.tpl`:**
```yaml
# В начале templates/deployment.yaml — проверка критичных значений
{{ include "skeleton.required" (dict "value" .Values.image.repository "message" "image.repository is required") }}
{{ include "skeleton.required" (dict "value" .Values.service.port "message" "service.port is required") }}
```

### 2. Валидация values через JSON Schema

Создайте файл `values.schema.json` в корне скелета для автоматической проверки типов и структуры значений перед рендерингом шаблонов.

```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["image", "service"],
  "properties": {
    "replicaCount": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "description": "Количество реплик (игнорируется при autoscaling.enabled=true)"
    },
    "image": {
      "type": "object",
      "required": ["repository"],
      "properties": {
        "repository": {
          "type": "string",
          "pattern": "^[a-z0-9\\-]+(/[a-z0-9\\-]+)*$",
          "description": "Docker registry + имя образа (без тега)"
        },
        "pullPolicy": {
          "type": "string",
          "enum": ["Always", "IfNotPresent", "Never"],
          "default": "IfNotPresent"
        },
        "tag": {
          "type": "string",
          "minLength": 1
        }
      }
    },
    "service": {
      "type": "object",
      "required": ["port"],
      "properties": {
        "type": {
          "type": "string",
          "enum": ["ClusterIP", "NodePort", "LoadBalancer"],
          "default": "ClusterIP"
        },
        "port": {
          "type": "integer",
          "minimum": 1,
          "maximum": 65535
        },
        "targetPort": {
          "type": "integer",
          "minimum": 1,
          "maximum": 65535
        }
      }
    },
    "autoscaling": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean", "default": false },
        "minReplicas": { "type": "integer", "minimum": 1 },
        "maxReplicas": { "type": "integer", "minimum": 2 }
      }
    },
    "resources": {
      "type": "object",
      "properties": {
        "limits": {
          "type": "object",
          "properties": {
            "cpu": { "type": "string", "pattern": "^[0-9]+(m)?$" },
            "memory": { "type": "string", "pattern": "^[0-9]+(Mi|Gi|Ti)?$" }
          }
        },
        "requests": {
          "type": "object",
          "properties": {
            "cpu": { "type": "string", "pattern": "^[0-9]+(m)?$" },
            "memory": { "type": "string", "pattern": "^[0-9]+(Mi|Gi|Ti)?$" }
          }
        }
      }
    }
  }
}
```

**Валидация:**
```bash
# Автоматическая проверка (Helm вызывает при install/upgrade если файл существует)
helm install my-release ./_template -f values-production.yaml

# Явная проверка
helm lint ./_template -f values-production.yaml

# Рендер с валидацией (debug покажет ошибки схемы)
helm template my-release ./_template -f values-production.yaml --debug
```

**Важно:** `values.schema.json` проверяется только при `helm install`/`helm upgrade`, но **не** при `helm template`. Для CI используйте `helm lint` с явным указанием values-файла.

### 3. Динамическая очистка манифестов (omit)

Функция `omit` позволяет управлять логикой включения полей через флаги, не оставляя лишних ключей в финальном YAML.

**deployment.yaml:**
```yaml
{{- if .Values.livenessProbe.enabled }}
livenessProbe:
  {{- omit .Values.livenessProbe "enabled" | toYaml | nindent 12 }}
{{- end }}
{{- if .Values.readinessProbe.enabled }}
readinessProbe:
  {{- omit .Values.readinessProbe "enabled" | toYaml | nindent 12 }}
{{- end }}
{{- if .Values.startupProbe.enabled }}
startupProbe:
  {{- omit .Values.startupProbe "enabled" | toYaml | nindent 12 }}
{{- end }}
```

**values.yaml (пример конфигурации):**
```yaml
livenessProbe:
  enabled: true
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 15
  periodSeconds: 10

readinessProbe:
  enabled: true
  httpGet:
    path: /ready
    port: http
  initialDelaySeconds: 5
  periodSeconds: 5
```

### 4. Обработка сложных переменных окружения

Скелет должен поддерживать передачу переменных из различных источников (прямые значения, Secret, ConfigMap, external secrets).

```yaml
env:
{{- range $name, $value := .Values.env }}
  - name: {{ $name }}
    value: {{ $value | quote }}
{{- end }}
{{- range .Values.envFromSecrets }}
  - name: {{ .name }}
    valueFrom:
      secretKeyRef:
        name: {{ .secretName }}
        key: {{ .secretKey }}
{{- end }}
{{- range .Values.envFromConfigMaps }}
  - name: {{ .name }}
    valueFrom:
      configMapKeyRef:
        name: {{ .configMapName }}
        key: {{ .configMapKey }}
{{- end }}
{{- with .Values.envFrom }}
envFrom:
  {{- toYaml . | nindent 2 }}
{{- end }}
```

**values.yaml (пример):**
```yaml
env:
  APP_ENV: production
  LOG_LEVEL: info

envFromSecrets:
  - name: DB_PASSWORD
    secretName: my-app-db-creds
    secretKey: password
  - name: API_KEY
    secretName: my-app-api-key
    secretKey: key

envFromConfigMaps:
  - name: CONFIG_PATH
    configMapName: my-app-config
    configKey: config.json

envFrom:
  - configMapRef:
      name: my-app-env
  - secretRef:
      name: my-app-env-secret
```

### 5. Полный Deployment с best practices

Скелет должен содержать Deployment с лучшими практиками для production:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "skeleton.fullname" . }}
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "skeleton.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      annotations:
        {{- include "skeleton.podAnnotations" . | nindent 8 }}
      labels:
        {{- include "skeleton.labels" . | nindent 8 }}
    spec:
      serviceAccountName: {{ include "skeleton.serviceAccountName" . }}
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: {{ .Chart.Name }}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - name: http
              containerPort: {{ .Values.service.targetPort | default 8080 }}
              protocol: TCP
          envFrom:
            {{- toYaml .Values.envFrom | nindent 12 }}
          {{- with .Values.env }}
          env:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- if .Values.livenessProbe.enabled }}
          livenessProbe:
            {{- omit .Values.livenessProbe "enabled" | toYaml | nindent 12 }}
          {{- end }}
          {{- if .Values.readinessProbe.enabled }}
          readinessProbe:
            {{- omit .Values.readinessProbe "enabled" | toYaml | nindent 12 }}
          {{- end }}
          {{- if .Values.startupProbe.enabled }}
          startupProbe:
            {{- omit .Values.startupProbe "enabled" | toYaml | nindent 12 }}
          {{- end }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          volumeMounts:
            {{- with .Values.volumeMounts }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

**Ключевые решения в этом шаблоне:**
- `maxUnavailable: 0` — Guarantees zero-downtime RollingUpdate: всегда доступно minimum replicas подов.
- `readOnlyRootFilesystem: true` — Предотвращает запись в контейнер; для `/tmp` используется `emptyDir`.
- `seccompProfile: RuntimeDefault` — Ограничивает системные вызовы контейнера через seccomp.
- `checksum/config` и `checksum/secret` — Автоматический перезапуск подов при изменении ConfigMap или Secret.

### 6. Service и Ingress

```yaml
# templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "skeleton.fullname" . }}
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    {{- include "skeleton.selectorLabels" . | nindent 4 }}

---
# templates/ingress.yaml
{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "skeleton.fullname" . }}
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
  {{- with .Values.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  ingressClassName: {{ .Values.ingress.className }}
  rules:
    - host: {{ .Values.ingress.host | quote }}
      http:
        paths:
          - path: {{ .Values.ingress.path | default "/" }}
            pathType: {{ .Values.ingress.pathType | default "Prefix" }}
            backend:
              service:
                name: {{ include "skeleton.fullname" . }}
                port:
                  number: {{ .Values.service.port }}
  {{- if .Values.ingress.tls }}
  tls:
    {{- toYaml .Values.ingress.tls | nindent 4 }}
  {{- end }}
{{- end }}
```

### 7. ConfigMap и Secret

```yaml
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "skeleton.fullname" . }}-config
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
data:
  {{- range $key, $value := .Values.config }}
  {{ $key }}: {{ $value | quote }}
  {{- end }}

---
# templates/secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "skeleton.fullname" . }}-secret
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
type: Opaque
data:
  {{- range $key, $value := .Values.secret }}
  {{ $key }}: {{ $value | b64enc | quote }}
  {{- end }}
```

**Важно:** Не храните секреты в `values.yaml`. Используйте `helm-secrets` (SOPS) или External Secrets Operator. Если секрет передаётся через `--set` или `-f`, он попадает в историю Helm (Secret в кластере) и может быть извлечён через `helm get values`.

### 8. HPA и PDB

```yaml
# templates/hpa.yaml
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "skeleton.fullname" . }}
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "skeleton.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    {{- toYaml .Values.autoscaling.metrics | nindent 4 }}
{{- end }}

---
# templates/pdb.yaml
{{- if .Values.podDisruptionBudget.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "skeleton.fullname" . }}
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
spec:
  {{- if .Values.podDisruptionBudget.minAvailable }}
  minAvailable: {{ .Values.podDisruptionBudget.minAvailable }}
  {{- end }}
  {{- if .Values.podDisruptionBudget.maxUnavailable }}
  maxUnavailable: {{ .Values.podDisruptionBudget.maxUnavailable }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "skeleton.selectorLabels" . | nindent 6 }}
{{- end }}
```

**Согласование HPA и PDB:** Если `autoscaling.enabled=true`, а `replicaCount` задан в `values.yaml`, Deployment будет использовать `replicaCount` как начальное число реплик, а HPA будет масштабировать от `minReplicas` до `maxReplicas`. Убедитесь, что `minReplicas` в HPA >= `minAvailable` в PDB, иначе `kubectl drain` будет заблокирован.

### 9. Network Policy

```yaml
{{- if .Values.networkPolicy.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "skeleton.fullname" . }}
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      {{- include "skeleton.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
    - Egress
  {{- if .Values.networkPolicy.ingress }}
  ingress:
    {{- toYaml .Values.networkPolicy.ingress | nindent 4 }}
  {{- end }}
  {{- if .Values.networkPolicy.egress }}
  egress:
    {{- toYaml .Values.networkPolicy.egress | nindent 4 }}
  {{- end }}
{{- end }}
```

**values.yaml (пример):**
```yaml
networkPolicy:
  enabled: true
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: nginx-ingress
      ports:
        - port: 8080
          protocol: TCP
  egress:
    - to: []
      ports:
        - port: 5432
          protocol: TCP
        - port: 6379
          protocol: TCP
```

**Важно:** NetworkPolicy по умолчанию ничего не блокирует. Чтобы política действовала, необходимо:
1. Убедиться, что CNI-плагин поддерживает NetworkPolicy (Calico, Cilium, Weave Net).
2. Добавить `policyTypes: [Ingress, Egress]` — без этого политика применяется, но не блокирует трафик.
3. Начните с `default deny` политики в namespace и добавляйте разрешения постепенно.

### 10. Универсальный values.yaml для скелета

Скелет должен содержать полный `values.yaml` с документацией всех параметров:

```yaml
# -- Number of replicas (ignored when autoscaling.enabled=true)
replicaCount: 2

image:
  # -- Container image repository
  repository: nginx
  # -- Image pull policy
  pullPolicy: IfNotPresent
  # -- Image tag (defaults to Chart.AppVersion)
  tag: ""

# -- Additional labels applied to all resources
additionalLabels: {}

serviceAccount:
  # -- Whether to create a ServiceAccount
  create: true
  # -- Annotations for the ServiceAccount
  annotations: {}
  # -- ServiceAccount name (generated if not set)
  name: ""

service:
  # -- Service type (ClusterIP, NodePort, LoadBalancer)
  type: ClusterIP
  # -- Service port
  port: 80
  # -- Container target port
  targetPort: 8080

ingress:
  enabled: false
  className: nginx
  annotations: {}
  host: app.local
  path: /
  pathType: Prefix
  tls: []

resources:
  limits:
    cpu: 500m
    memory: 256Mi
  requests:
    cpu: 100m
    memory: 128Mi

autoscaling:
  enabled: false
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 80

podDisruptionBudget:
  enabled: true
  minAvailable: 1

livenessProbe:
  enabled: true
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 15
  periodSeconds: 10

readinessProbe:
  enabled: true
  httpGet:
    path: /ready
    port: http
  initialDelaySeconds: 5
  periodSeconds: 5

startupProbe:
  enabled: false

env: {}
envFrom: []
envFromSecrets: []
envFromConfigMaps: []

config: {}
secret: {}

networkPolicy:
  enabled: false

# -- Pod annotations (checksum/config and checksum/secret are added automatically)
podAnnotations: {}

# -- Node selector
nodeSelector: {}

# -- Affinity rules
affinity: {}

# -- Tolerations
tolerations: []

# -- Additional volume mounts
volumeMounts: []
```

### 11. Распределение и обновление скелетов

Главная проблема скелетов — "протухание" копий после внесения изменений в эталон.

**Методы распределения:**

1.  **Helm Starters:** Создайте директорию в `$HELM_DATA_HOME/starters`. Команда `helm create --starter my-starter my-app` создаст чарт по вашему шаблону.
    ```bash
    # Установка starters
    mkdir -p ~/.local/share/helm/starters
    cp -r _template ~/.local/share/helm/starters/my-starter

    # Создание нового сервиса
    helm create --starter my-starter my-new-service
    ```

2.  **Cookiecutter / Copier:** Использование внешних инструментов генерации проектов. Позволяют не только создавать, но и обновлять структуру файлов при изменении эталона (особенно `cruft` — надстройка над cookiecutter).
    ```bash
    # Установка cookiecutter
    pip install cookiecutter

    # Создание проекта из шаблона
    cookiecutter ./my-skeleton-template --output-dir ./services

    # Обновление через cruft
    pip install cruft
    cruft update
    ```

3.  **Git Repo:** Скелет хранится в отдельном репозитории. Новые проекты создаются через `git clone` или добавление как Submodule.
    ```bash
    # Клонирование скелета
    git clone --depth 1 git@github.com:org/helm-skeleton.git _template

    # Или добавление как Submodule
    git submodule add git@github.com:org/helm-skeleton.git _template
    ```

**Стратегия обновления:**
- Если изменения критичны (например, миграция API-версии K8s), используется скрипт для массового поиска и замены (`sed`/`yq`) во всех репозиториях.
- Если изменения косметические, они внедряются только в новые сервисы.
- Для автоматизации используйте `copier` или `cruft` — они отслеживают изменения в эталоне и применяют их к существующим проектам.

```bash
# Массовое обновление через yq
for repo in ./services/*/; do
  if [ -f "$repo/Chart.yaml" ]; then
    yq -i '.apiVersion = "v2"' "$repo/Chart.yaml"
    yq -i '.type = "application"' "$repo/Chart.yaml"
  fi
done
```

### 12. Валидация скелета через CI/CD

Интеграция проверки скелета в pipeline предотвращает устаревание шаблонов.

```yaml
# .gitlab-ci.yml
stages:
  - validate
  - test

validate:skeleton:
  stage: validate
  image: alpine/helm:3.14.0
  script:
    # Линтинг скелета
    - helm lint _template --strict
    # Рендер всех шаблонов
    - helm template test-release _template > /dev/null
    # Проверка на deprecated API
    - helm template test-release _template | kubeconform -strict -kubernetes-version 1.30.0

validate:skeleton:consistency:
  stage: validate
  image: alpine:latest
  script:
    # Проверка, что все сервисы используют актуальный скелет
    - |
      for dir in services/*/; do
        if [ -d "$dir/templates" ]; then
          diff <(helm template test _template) <(helm template test "$dir") || \
            echo "WARNING: $dir deviates from skeleton"
        fi
      done
```

**GitHub Actions эквивалент:**
```yaml
# .github/workflows/helm-skeleton.yml
name: Validate Skeleton
on:
  push:
    paths: ['_template/**']
  pull_request:
    paths: ['_template/**']

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-helm@v4
        with:
          version: 'v3.14.0'
      - run: helm lint _template --strict
      - run: helm template test-release _template | kubeconform -strict -kubernetes-version 1.30.0
```

**Makefile для локальной валидации:**
```makefile
.PHONY: lint validate

lint:
	helm lint _template --strict
	helm template test-release _template > /dev/null

validate: lint
	helm template test-release _template | kubeconform -strict -kubernetes-version 1.30.0

diff-changed:
	@for dir in $$(git diff --name-only HEAD~1 | grep 'values.*yaml' | xargs dirname | sort -u); do \
		if [ -d "$$dir/templates" ]; then \
			helm diff upgrade test $$dir -f $$dir/values.yaml 2>/dev/null || true; \
		fi; \
	done
```

### 13. Скелет для StatefulSet

Для сервисов с постоянным хранилищем (БД, очереди, кэш) используйте модифицированный скелет с StatefulSet:

```yaml
# templates/statefulset.yaml
{{- if .Values.statefulSet.enabled }}
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ include "skeleton.fullname" . }}
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
spec:
  serviceName: {{ include "skeleton.fullname" . }}-headless
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "skeleton.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "skeleton.labels" . | nindent 8 }}
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
        - name: {{ .Chart.Name }}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          ports:
            - name: {{ .Values.service.portName | default "app" }}
              containerPort: {{ .Values.service.targetPort | default 8080 }}
          volumeMounts:
            {{- range .Values.persistence.mounts }}
            - name: {{ .name }}
              mountPath: {{ .mountPath }}
            {{- end }}
  {{- if .Values.persistence.enabled }}
  volumeClaimTemplates:
    {{- range .Values.persistence.claims }}
    - metadata:
        name: {{ .name }}
      spec:
        accessModes: {{ .accessModes }}
        resources:
          requests:
            storage: {{ .size }}
        {{- if .storageClassName }}
        storageClassName: {{ .storageClassName }}
        {{- end }}
    {{- end }}
  {{- end }}
{{- end }}
```

**Headless Service для StatefulSet:**
```yaml
# templates/service-headless.yaml
{{- if .Values.statefulSet.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "skeleton.fullname" . }}-headless
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
spec:
  clusterIP: None
  selector:
    {{- include "skeleton.selectorLabels" . | nindent 4 }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.portName | default "app" }}
      name: {{ .Values.service.portName | default "app" }}
{{- end }}
```

**values.yaml для StatefulSet:**
```yaml
statefulSet:
  enabled: false

persistence:
  enabled: false
  mounts:
    - name: data
      mountPath: /data
  claims:
    - name: data
      size: 10Gi
      accessModes: ["ReadWriteOnce"]
      storageClassName: ""
```

### 14. Скелет для Job и CronJob

```yaml
# templates/job.yaml
{{- if .Values.job.enabled }}
apiVersion: batch/v1
kind: {{ if .Values.job.cron }}CronJob{{ else }}Job{{ end }}
metadata:
  name: {{ include "skeleton.fullname" . }}
  labels:
    {{- include "skeleton.labels" . | nindent 4 }}
spec:
  {{- if .Values.job.cron }}
  schedule: {{ .Values.job.schedule | quote }}
  {{- end }}
  jobTemplate:
    spec:
      backoffLimit: {{ .Values.job.backoffLimit | default 3 }}
      activeDeadlineSeconds: {{ .Values.job.activeDeadlineSeconds | default 3600 }}
      template:
        metadata:
          labels:
            {{- include "skeleton.labels" . | nindent 12 }}
        spec:
          restartPolicy: {{ if .Values.job.cron }}Never{{ else }}OnFailure{{ end }}
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
          containers:
            - name: {{ .Chart.Name }}
              image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities:
                  drop: ["ALL"]
              {{- with .Values.env }}
              env:
                {{- toYaml . | nindent 16 }}
              {{- end }}
              resources:
                {{- toYaml .Values.resources | nindent 16 }}
              volumeMounts:
                - name: tmp
                  mountPath: /tmp
          volumes:
            - name: tmp
              emptyDir: {}
{{- end }}
```

**values.yaml для Job:**
```yaml
job:
  enabled: false
  cron: false
  schedule: "0 2 * * *"    # Только для CronJob
  backoffLimit: 3
  activeDeadlineSeconds: 3600
```

### 15. Расширенные паттерны в _helpers.tpl

Дополнительные функции для продвинутых сценариев:

```go
{{/*
Возвращает имя конфигурации с учётом окружения.
Использование: {{ include "skeleton.configName" (dict "ctx" . "suffix" "nginx") }}
*/}}
{{- define "skeleton.configName" -}}
{{- printf "%s-%s-config" (include "skeleton.fullname" .ctx) .suffix }}
{{- end }}

{{/*
Генерирует аннотацию checksum для принудительного перезапуска подов.
*/}}
{{- define "skeleton.checksum" -}}
checksum/{{ .kind }}: {{ include (printf "%s/templates/%s" $.Template.BasePath .file) .ctx | sha256sum }}
{{- end }}

{{/*
Безопасный mergeOf для слияния maps без мутации оригинала.
*/}}
{{- define "skeleton.merge" -}}
{{- $merged := deepCopy .base -}}
{{- range $key, $val := .override -}}
{{- $_ := set $merged $key $val -}}
{{- end -}}
{{- toYaml $merged -}}
{{- end }}
```

---

## Диагностика и устранение неполадок

### Частые ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `template: skeleton/templates/...: function "..." not defined` | Отсутствует функция в `_helpers.tpl` | Проверьте, что все `include` и `define` присутствуют |
| `error converting YAML to JSON` | Некорректный отступ в шаблоне | Используйте `nindent` вместо `indent`, проверьте `toYaml` |
| `Dry-run failed` | Синтаксическая ошибка в шаблоне | Запустите `helm template --debug` для отладки |
| `ValidationError` при `helm install` | Невалидные значения по умолчанию | Проверьте `values.yaml` на соответствие `values.schema.json` |
| `unable to find a matching release` | Release не найден в кластере | Проверьте namespace: `helm list -n <ns>` |
| Метки не применяются | Ошибка в `_helpers.tpl` | Проверьте вызов `include "skeleton.labels"` |
| `Error: values file not found` | Неверный путь к values файлу | Проверьте путь: `ls -la values-production.yaml` |
| `Error:.yaml: line X: field X already defined` | Дублирование ключа в YAML | Проверьте отступы и уникальность ключей в values |
| `rendered manifests contain a resource that already exists` | Ресурс создан вне Helm (kubectl) | Используйте `--take-over` или удалите ресурс вручную |

### Отладка шаблонов

```bash
# Рендер конкретного шаблона
helm template my-release ./_template --show-only templates/deployment.yaml

# Рендер с конкретными значениями
helm template my-release ./_template -f values-production.yaml --debug

# Проверка синтаксиса без кластера
helm lint ./_template --strict

# Сравнение с эталоном
diff <(helm template test ./_template) <(helm template test ./my-service)

# Проверка конкретного значения в rendered output
helm template my-release ./_template | grep -A5 "replicas:"

# Проверка аннотаций
helm template my-release ./_template | grep "checksum/"

# Проверка securityContext
helm template my-release ./_template | grep -A10 "securityContext:"

# Проверка что🕛 probing настроен
helm template my-release ./_template | grep -A8 "livenessProbe:"

# Debug: показать все используемые значения
helm template my-release ./_template --debug 2>&1 | grep "^VALUES:"

# Проверка схемы (покажет ошибки валидации)
helm lint ./_template -f values-invalid.yaml
```

**Сравнение рендеров двух версий скелета:**
```bash
# Обновить скелет
cp -r ./_template-new ./_template

# Сравнить рендеры для конкретного сервиса
diff <(helm template myapp ./_template-old -f ./services/myapp/values.yaml) \
     <(helm template myapp ./_template-new -f ./services/myapp/values.yaml)
```

---

## Дополнительная информация

### Best Practices для Skeleton

1. **Версионирование скелета:** Используйте семантическое версионирование для самого скелета (отдельно от версий сервисов). Это позволяет отслеживать изменения и откатывать при необходимости.
2. **Документация параметров:** В `values.yaml` используйте комментарии `# --` для автоматической генерации документации (совместимо с `helm-docs`).
3. **Минимальные права:** Скелет должен создавать ServiceAccount с минимальными правами. Никогда не используйте `default` SA.
4. **values.schema.json:** Всегда создавайте файл схемы — это единственный способ гарантировать типобезопасность values на уровне Helm.
5. **Проверка обязательных полей:** Используйте `required` и `fail` в `_helpers.tpl` для критичных параметров (image.repository, service.port).
6. **Чек суммы:** Автоматический перезапуск подов при изменении ConfigMap/Secret через `checksum/config` аннотации.
7. **Нет latest тегов:** Используйте `image.tag | default .Chart.AppVersion` — это гарантирует воспроизводимость откатов.

### Антипаттерны

| Антипаттерн | Проблема | Решение |
|-------------|----------|---------|
| Хардкод имён в шаблонах | Слом при переименовании релиза | Всегда используйте `include "skeleton.fullname"` |
| Нет `readOnlyRootFilesystem` | Контейнер может быть скомпрометирован | Устанавливайте `true` + `emptyDir` для `/tmp` |
| Секреты в `values.yaml` | Утечка в Git, история Helm | Используйте `existingSecret` или `helm-secrets` |
| Использование `tpl` для основных манифестов | Сложность отладки, проблемы с валидацией | Используйте `tpl` только для пользовательских строк |
| Отсутствие `securityContext` | Несоответствие PSS/PSA политикам | Задавайте на уровне Deployment и Container |
| Дублирование логики между Skeleton и Library | Несогласованность при обновлениях | Выберите ONE SSoT: либо Skeleton, либо Library |
| Нет `resources.limits` | Pod может исчерпать ресурсы узла | Всегда задавайте limits в скелете |
| Использование `helm install --wait` без `--timeout` | Бесконечное ожидание | Устанавливайте `--timeout 5m` или больше |
| Игнорирование `podDisruptionBudget` | `kubectl drain` блокируется | Включайте PDB для всех production сервисов |

### Интеграция с инструментами

| Инструмент | Особенности использования |
|------------|---------------------------|
| **helmfile** | Оркестрирует деплой множества сервисов, созданных по шаблону, через `helmfile.yaml` |
| **ChartMuseum** | Хранение скелета как OCI-артефакта для доступа из CI/CD |
| **kustomize** | Альтернативный подход к патчам — может использоваться вместо скелета для простых случаев |
| **ChartTesting (ct)** | Автоматическая валидация чартов, созданных по шаблону |
| **helm-docs** | Автогенерация документации из комментариев `# --` в `values.yaml` |
| **kubeconform** | Валидация рендеренных манифестов на соответствие актуальным API K8s |
| **conftest** | Policy-as-code проверка рендеренных манифестов (OPA Rego) |

### См. также

- [Структура Helm-чарта](./helm_chart_structure.md) — описание базовых файлов и директорий.
- [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md) — когда скелета становится недостаточно и нужна общая логика.
- [Практические сценарии Helm-чартов](./helm_chart_practical_scenarios.md) — примеры Shared Chart для 100+ микросервисов.
- [Паттерны и устранение неисправностей](./Advanced/patterns_troubleshooting.md) — антипаттерны и диагностика.
