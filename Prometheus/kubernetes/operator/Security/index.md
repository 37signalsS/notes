# Безопасность Prometheus Operator

## Определения

**Безопасность Prometheus Operator** — комплекс мер по защите стека мониторинга: аутентификация, TLS, контроль доступа, управление секретами.

---

## Файлы

| Файл | Описание |
|------|----------|
| [access_control.md](./access_control.md) | Network Policies, RBAC |
| [secrets_best_practices.md](./secrets_best_practices.md) | Secrets Management, лучшие практики |

---

## Practical Scenarios

### Аутентификация

#### Prometheus

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

---

#### Alertmanager

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

---

#### Grafana

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

---

### TLS

#### Ingress с TLS

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

#### mTLS для внутренних соединений

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

---

## Additional Information

### Связанные темы

- **[High Availability](../high_availability.md)** — HA конфигурация
- **[Prometheus CRD](../crd/prometheus.md)** — описание Prometheus
- **[Alertmanager](../../../alertmanager.md)** — базовая настройка
