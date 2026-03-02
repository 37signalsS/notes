# Сервисы и Ingress

Осталось опубликовать сервисы вовне.

- **`alertmanager-svc.yaml`**
- **`karma-svc.yaml`**
- **`ingress.yaml`**

```yaml
# alertmanager-svc.yaml
apiVersion: v1
kind: Service
metadata:
  name: alertmanager
  namespace: monitoring
spec:
  selector:
    app: alertmanager
  ports:
    - name: web
      port: 9093
      targetPort: web

---
# karma-svc.yaml
apiVersion: v1
kind: Service
metadata:
  name: karma
  namespace: monitoring
spec:
  selector:
    app: karma
  ports:
    - name: web
      port: 8080
      targetPort: web

---
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: monitoring-ingress
  namespace: monitoring
spec:
  rules:
    - host: alertmanager.k8s.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: alertmanager
                port:
                  number: 9093
    - host: karma.k8s.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: karma
                port:
                  number: 8080
```

После применения всех этих манифестов у вас будет полностью рабочая связка Alertmanager + Karma.
