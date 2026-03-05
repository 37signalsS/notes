# Безопасность Prometheus Operator

## Аутентификация

### Prometheus

**Встроенная аутентификация (новые версии):**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  # ...
  web:
    webConfig:
      basicAuth:
        username:
          name: prometheus-auth
          key: username
        password:
          name: prometheus-auth
          key: password
```

**Ingress с Basic Auth:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: prometheus
  namespace: monitoring
  annotations:
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: prometheus-auth
    nginx.ingress.kubernetes.io/auth-realm: "Authentication Required"
spec:
  rules:
    - host: prometheus.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: prometheus
                port:
                  number: 9090
```

**Создание секрета:**

```bash
htpasswd -c auth admin
kubectl create secret generic prometheus-auth --from-file=auth -n monitoring
```

### Alertmanager

Alertmanager не имеет встроенной аутентификации. Используйте Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alertmanager
  namespace: monitoring
  annotations:
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: alertmanager-auth
spec:
  rules:
    - host: alertmanager.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: alertmanager
                port:
                  number: 9093
```

### Grafana

**Встроенная аутентификация:**

```yaml
# values.yaml
grafana:
  admin:
    existingSecret: grafana-admin-secret
    userKey: admin-user
    passwordKey: admin-password
```

**Создание секрета:**

```bash
kubectl create secret generic grafana-admin-secret \
  --from-literal=admin-user="admin" \
  --from-literal=admin-password="$(openssl rand -base64 20)" \
  -n monitoring
```

## TLS

### Ingress с TLS

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: prometheus
  namespace: monitoring
spec:
  tls:
    - hosts:
        - prometheus.example.com
      secretName: prometheus-tls
  rules:
    - host: prometheus.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: prometheus
                port:
                  number: 9090
```

### mTLS для внутренних соединений

```yaml
# ServiceMonitor с TLS
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: secure-app
  namespace: production
spec:
  endpoints:
    - port: https
      scheme: https
      tlsConfig:
        caFile: /etc/prometheus/secrets/ca.crt
        certFile: /etc/prometheus/secrets/client.crt
        keyFile: /etc/prometheus/secrets/client.key
        insecureSkipVerify: false
```

## Network Policies

### Ограничение доступа к Prometheus

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
        - podSelector:
            matchLabels:
              app: grafana
      ports:
        - port: 9090
          protocol: TCP
```

### Ограничение доступа к Alertmanager

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: alertmanager-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: alertmanager
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9093
          protocol: TCP
```

## RBAC

### ServiceAccount для Prometheus

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: monitoring
```

### ClusterRole для доступа к Kubernetes API

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus
rules:
  - apiGroups: [""]
    resources:
      - nodes
      - nodes/metrics
      - services
      - endpoints
      - pods
    verbs: ["get", "list", "watch"]
  - apiGroups: ["extensions"]
    resources:
      - ingresses
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics"]
    verbs: ["get"]
```

### ClusterRoleBinding

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: prometheus
subjects:
  - kind: ServiceAccount
    name: prometheus
    namespace: monitoring
```

## Secrets Management

### Хранение чувствительных данных

```bash
# Slack webhook
kubectl create secret generic slack-webhook \
  --from-literal=url='https://hooks.slack.com/services/xxx/yyy/zzz' \
  -n monitoring

# PagerDuty routing key
kubectl create secret generic pagerduty-secret \
  --from-literal=routing-key='your-routing-key' \
  -n monitoring

# SMTP password
kubectl create secret generic smtp-secret \
  --from-literal=password='your-smtp-password' \
  -n monitoring
```

### Использование в AlertmanagerConfig

```yaml
receivers:
  - name: 'slack'
    slackConfigs:
      - channel: '#monitoring'
        apiURL:
          name: slack-webhook
          key: url
```

## Security Best Practices

1. **Используйте TLS** для всех внешних соединений
2. **Включите аутентификацию** для Prometheus и Grafana
3. **Ограничьте доступ** через Network Policies
4. **Храните секреты** в Kubernetes Secrets
5. **Используйте RBAC** для минимизации прав
6. **Регулярно обновляйте** Prometheus Operator
7. **Мониторьте доступ** через audit logs

## Связанные темы

* **[High Availability](./high_availability.md)** — HA конфигурация
* **[Prometheus CRD](./crd/prometheus.md)** — описание Prometheus
* **[Alertmanager](../alertmanager.md)** — базовая настройка
