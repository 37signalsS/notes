# Сетевой доступ: Сервисы и Ingress

## Определения

**Kubernetes Service** — абстракция, определяющая логический набор подов и политику доступа к ним. В данном руководстве используются сервисы типа `ClusterIP` для внутренней связности и `Headless Service` для обеспечения работы кластеризации Alertmanager.

**Ingress** — ресурс Kubernetes, предоставляющий HTTP/HTTPS маршрутизацию от внешних источников к внутренним сервисам. В современных кластерах (1.30+) является стандартом для публикации интерфейсов мониторинга с использованием TLS и внешней аутентификации.

---

## Основные концепции

### Схема сетевых потоков

```text
Внешний трафик (HTTPS)
       │
       ▼
┌──────────────┐
│   Ingress    │  L7-терминация, SSL, Auth
│  Controller  │
└──────┬───────┘
       │
   ┌───┴──────────────────────┐
   │                          │
   ▼ (Port 9093)              ▼ (Port 8080)
alertmanager.example.com    karma.example.com
   │                          │
   ▼                          ▼
┌──────────────────┐    ┌─────────────┐
│ Service (Cluster)│    │ Service     │
│  alertmanager    │    │    karma    │
└──────┬───────────┘    └──────┬──────┘
       │                       │
       ▼                       ▼
┌──────────────────┐    ┌─────────────┐
│  StatefulSet Pod │    │ Deployment  │
│  alertmanager-0  │    │    karma    │
└──────┬───────────┘    └─────────────┘
       │
       ▼ (Port 9094)
┌──────────────────┐
│ Service (Headless)◀─── Cluster Mesh (Gossip)
│ alertmgr-mesh    │
└──────────────────┘
```

---

## Практические сценарии

### Настройка внутренних сервисов

Для Alertmanager создается два сервиса: обычный (для API) и Headless (для Gossip-протокола кластеризации).

**`alertmanager-services.yaml`**

```yaml
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
      targetPort: 9093
---
# Headless Service для Mesh-кластеризации
apiVersion: v1
kind: Service
metadata:
  name: alertmanager-mesh
  namespace: monitoring
spec:
  clusterIP: None
  selector:
    app: alertmanager
  ports:
    - name: mesh
      port: 9094
      targetPort: 9094
---
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
      port: 80
      targetPort: 8080
```

### Публикация через Ingress с аутентификацией

Поскольку Alertmanager не имеет встроенной аутентификации, ее необходимо настроить на уровне Ingress.

**`monitoring-ingress.yaml`**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: monitoring-ingress
  namespace: monitoring
  annotations:
    kubernetes.io/ingress.class: nginx
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: alertmanager-auth
    nginx.ingress.kubernetes.io/auth-realm: "Authentication Required"
spec:
  tls:
    - hosts:
        - alertmanager.example.com
        - karma.example.com
      secretName: monitoring-tls-cert
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
    - host: karma.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: karma
                port:
                  number: 80
```

---

## Дополнительная информация

- **[Манифест StatefulSet](./alertmanager-statefulset.md)** — использование `alertmanager-mesh` в параметрах `--cluster.peer`.
- **[Секреты Kubernetes](./secrets.md)** — создание `alertmanager-auth` для Ingress Basic Auth.
- **[Обзор Ingress](../../../../Kubernetes/Networking/Ingress/overview.md)** — SSoT по сетевой маршрутизации и контроллерам.
- **[Дашборд Karma — Безопасность](../../../Prometheus/karma_dashboard.md#безопасность-и-ingress)** — рекомендации по OIDC и защите UI.
