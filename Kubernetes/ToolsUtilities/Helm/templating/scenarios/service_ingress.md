# Шаблонизация Service и Ingress в Helm

---

## Определения

**Service** — абстракция уровня L4, маршрутизирующая трафик к группе подов. Определяет стабильный IP-адрес и DNS-имя для доступа к подам.

**Ingress** — ресурс уровня L7 (HTTP/HTTPS), управляющий маршрутизацией внешнего трафика к сервисам на основе хостов и путей.

**Gateway API** — современная замена Ingress (стабильна с 1.31),提供更多 функциональности: автообнаружение ingressClassName, разделение ответственности (infra vs app), TCP/UDP.

**IngressClassName** — поле, указывающее какой Ingress Controller обрабатывает ресурс (появилось в 1.18). В старых кластерах используется аннотация `kubernetes.io/ingress.class`.

**Headless Service** — Service с `clusterIP: None`, не выделяющий.clusterIP. Используется для StatefulSet (DNS-записи вида `pod-name.service-name`).

**ExternalName** — Service, возвращающий CNAME-запись внешнего сервиса. Полезен для маршрутизации трафика за пределы кластера.

---

## Типы Service

| Тип | Описание | Use-case |
|-----|----------|----------|
| ClusterIP | Внутренний IP в кластере | Микросервисы, backend |
| NodePort | Открытый порт на каждом узле | Debug, минималистичный доступ |
| LoadBalancer | Внешний LB (cloud) | Production, интернет-сервисы |
| ExternalName | CNAME на внешний сервис | Миграция, внешние зависимости |
| Headless | clusterIP: None | StatefulSet, DNS-директивы |

---

## Базовые концепции

### Иерархия Service → Pod

```
Service (clusterIP: 10.96.0.10:80)
  └─ Endpoints (auto: 10.244.1.5:8080, 10.244.2.5:8080)
       └─ Pods (selector: app=myapp)
```

### Интеграция с Ingress

```
Client → Ingress (L7: host/path) → Service (L4: port) → Pod
```

### TLS termination

Ingress terminating TLS на уровне контроллера:
```
Client → [TLS] → Ingress Controller → [HTTP] → Service → Pod
```

---

## Практические сценарии

### Базовый Service

```yaml
# values.yaml
service:
  type: ClusterIP
  port: 80
  targetPort: 8080
```

```yaml
# templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.targetPort }}
      protocol: TCP
      name: http
  selector:
    {{- include "myapp.selectorLabels" . | nindent 4 }}
```

### Service с несколькими портами

```yaml
# values.yaml
service:
  type: ClusterIP
  ports:
    - name: http
      port: 80
      targetPort: 8080
    - name: https
      port: 443
      targetPort: 8443
    - name: metrics
      port: 9090
      targetPort: 9090
```

```yaml
# templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  type: {{ .Values.service.type }}
  ports:
    {{- range .Values.service.ports }}
    - name: {{ .name }}
      port: {{ .port }}
      targetPort: {{ .targetPort }}
      protocol: TCP
    {{- end }}
  selector:
    {{- include "myapp.selectorLabels" . | nindent 4 }}
```

### NodePort с динамическим портом

```yaml
# values.yaml
service:
  type: NodePort
  port: 80
  targetPort: 8080
  nodePort: 30080
```

```yaml
# templates/service.yaml
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.targetPort }}
      {{- if and (eq .Values.service.type "NodePort") .Values.service.nodePort }}
      nodePort: {{ .Values.service.nodePort }}
      {{- end }}
```

### LoadBalancer с аннотациями (cloud)

```yaml
# values.yaml
service:
  type: LoadBalancer
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: nlb
    service.beta.kubernetes.io/aws-load-balancer-internal: "true"
```

```yaml
# templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "myapp.fullname" . }}
  {{- with .Values.service.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  type: {{ .Values.service.type }}
```

### Headless Service для StatefulSet

```yaml
# templates/service-headless.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "myapp.fullname" . }}-headless
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  clusterIP: None
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.targetPort }}
  selector:
    {{- include "myapp.selectorLabels" . | nindent 4 }}
```

### ExternalName Service

```yaml
# templates/service-external.yaml
{{- if eq .Values.service.type "ExternalName" }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  type: ExternalName
  externalName: {{ .Values.service.externalName | quote }}
{{- end }}
```

### Базовый Ingress

```yaml
# values.yaml
ingress:
  enabled: true
  className: nginx
  annotations: {}
  hosts:
    - host: app.example.com
      paths:
        - path: /
          pathType: Prefix
  tls: []
```

```yaml
# templates/ingress.yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
  {{- with .Values.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- if .Values.ingress.className }}
  ingressClassName: {{ .Values.ingress.className }}
  {{- end }}
  {{- if .Values.ingress.tls }}
  tls:
    {{- range .Values.ingress.tls }}
    - hosts:
        {{- range .hosts }}
        - {{ . | quote }}
        {{- end }}
      secretName: {{ .secretName }}
    {{- end }}
  {{- end }}
  rules:
    {{- range .Values.ingress.hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          {{- range .paths }}
          - path: {{ .path }}
            pathType: {{ .pathType }}
            backend:
              service:
                name: {{ include "myapp.fullname" $ }}
                port:
                  number: {{ $.Values.service.port }}
          {{- end }}
    {{- end }}
{{- end }}
```

### Ingress с TLS через cert-manager

```yaml
# values.yaml
ingress:
  enabled: true
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  tls:
    - secretName: app-tls
      hosts:
        - app.example.com
```

### Ingress с条件ной аннотацией для старых кластеров

```yaml
# templates/ingress.yaml
metadata:
  annotations:
    {{- if and .Values.ingress.className (not (semverCompare ">=1.18-0" .Capabilities.KubeVersion.Version)) }}
    kubernetes.io/ingress.class: {{ .Values.ingress.className | quote }}
    {{- end }}
spec:
  {{- if (semverCompare ">=1.18-0" .Capabilities.KubeVersion.Version) }}
  ingressClassName: {{ .Values.ingress.className }}
  {{- end }}
```

### Ingress с conditions для включения

```yaml
# templates/ingress.yaml
{{- if and .Values.ingress.enabled .Values.ingress.hosts }}
apiVersion: networking.k8s.io/v1
kind: Ingress
...
{{- end }}
```

### Валидация через values.schema.json

```json
{
  "properties": {
    "service": {
      "type": "object",
      "properties": {
        "type": { "enum": ["ClusterIP", "NodePort", "LoadBalancer", "ExternalName"] },
        "port": { "type": "integer", "minimum": 1, "maximum": 65535 },
        "targetPort": { "type": "integer", "minimum": 1, "maximum": 65535 }
      }
    },
    "ingress": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "className": { "type": "string" },
        "hosts": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["host", "paths"],
            "properties": {
              "host": { "type": "string" },
              "paths": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "path": { "type": "string" },
                    "pathType": { "enum": ["Prefix", "Exact", "ImplementationSpecific"] }
                  }
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

---

## Дополнительная информация

### Лучшие практики

1. **Именование портов:** Всегда задавайте `name` для портов (обязательно для Ingress и multi-port Service).
2. **targetPort:** Используйте именованные порты (`http`, `metrics`) вместо числовых для читаемости.
3. **TLS:** В production используйте cert-manager с automatic renewal.
4. **ingressClassName:** Явно указывайте, чтобы избежать конфликтов с другими контроллерами.
5. **Порядок путей:** Ingress проверяет пути сверху вниз; более длинные пути должны быть первыми.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `no endpoints` | Service selector не совпадает с labels пода | Проверьте `kubectl get endpoints` |
| `502 Bad Gateway` | Ingress не может достучаться до Service | Проверьте readinessProbe и порты |
| `TLS handshake failure` | Secret не содержит корректный сертификат | Проверьте cert-manager и аннотации |

### См. также

- [Service: обзор](../../../../Networking/Service/service_overview.md) — типы, маршрутизация.
- [Ingress](../../../../Networking/Ingress/overview.md) — L7 маршрутизация.
- [Gateway API](../../../../Networking/gateway_api/resources.md) — современная альтернатива Ingress.
