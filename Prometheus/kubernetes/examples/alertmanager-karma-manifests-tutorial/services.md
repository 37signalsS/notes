# Сервисы и Ingress для Alertmanager + Karma

## Определения

**Service (ClusterIP)** — внутренний Kubernetes Service типа ClusterIP, обеспечивающий стабильный DNS-доступ к подам Alertmanager (порт 9093) и Karma (порт 8080) внутри кластера.

**Ingress** — объект Kubernetes для маршрутизации внешнего HTTP/HTTPS трафика к сервисам кластера на основе host-имён. В данном руководстве Ingress публикует Alertmanager и Karma по отдельным доменам (`alertmanager.k8s.local`, `karma.k8s.local`).

> **См. также:** материалы [Обзор Service](../../../Kubernetes/Networking/Service/service_overview.md) и [Обзор Ingress](../../../Kubernetes/Networking/Ingress/overview.md)

## Основные концепции

### Архитектура сетевого доступа

```
Внешний трафик
       │
       ▼
┌──────────────┐
│   Ingress    │  L7 маршрутизация по host
│  Controller  │
└──────┬───────┘
       │
   ┌───┴──────────────────┐
   │                      │
   ▼                      ▼
alertmanager.k8s.local   karma.k8s.local
   │                      │
   ▼                      ▼
┌──────────────┐    ┌──────────┐
│  Service     │    │ Service  │
│ alertmanager │    │  karma   │
│  :9093       │    │  :8080   │
└──────┬───────┘    └────┬─────┘
       │                 │
       ▼                 ▼
  ┌─────────┐      ┌─────────┐
  │   Pods  │      │  Pods   │
  │alertmgr │      │  karma  │
  └─────────┘      └─────────┘
```

### Типы Service

| Service | Тип | Порт | Selector | Назначение |
|---|---|---|---|---|
| `alertmanager` | ClusterIP | `9093` | `app: alertmanager` | Внутренний доступ к Alertmanager (для Karma, Prometheus) |
| `karma` | ClusterIP | `8080` | `app: karma` | Внутренний доступ к Karma |

### Ingress-правила

| Host | Backend Service | Порт | Path |
|---|---|---|---|
| `alertmanager.k8s.local` | `alertmanager` | `9093` | `/` |
| `karma.k8s.local` | `karma` | `8080` | `/` |

## Практические сценарии

### Service: Alertmanager

**`alertmanager-svc.yaml`**

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
      targetPort: web
```

**Пояснения:**

- `selector: app: alertmanager` — связывает Service с подами из [alertmanager-statefulset.md](./alertmanager-statefulset.md)
- `targetPort: web` — ссылается на именованный порт `web` (9093) в контейнере
- Тип не указан — по умолчанию `ClusterIP`

### Service: Karma

**`karma-svc.yaml`**

```yaml
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
```

**Пояснения:**

- `selector: app: karma` — связывает Service с подами из [karma-deployment.md](./karma-deployment.md)
- `targetPort: web` — ссылается на именованный порт `web` (8080) в контейнере

### Ingress: маршрутизация внешнего трафика

**`ingress.yaml`**

```yaml
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

**Пояснения:**

- `pathType: Prefix` — маршрутизация по префиксу пути (в данном случае `/` — все пути)
- `port.number` — явное указание номера порта (альтернатива `port.name`)
- Требуется работающий Ingress Controller (NGINX, Traefik, HAProxy и т.д.) — см. [Обзор Ingress](../../../Kubernetes/Networking/Ingress/overview.md)

### Проверка после применения

```bash
# Применение манифестов
kubectl apply -f alertmanager-svc.yaml
kubectl apply -f karma-svc.yaml
kubectl apply -f ingress.yaml

# Проверка Service
kubectl get svc -n monitoring

# Проверка Ingress
kubectl get ingress -n monitoring

# Проверка DNS (из пода в кластере)
kubectl run dns-test --rm -it --image=busybox --restart=Never -- \
  nslookup alertmanager.monitoring.svc.cluster.local
```

### DNS-имена для внутреннего доступа

| Сервис | DNS-имя | Использование |
|---|---|---|
| Alertmanager | `alertmanager.monitoring.svc.cluster.local:9093` | Karma подключается для сбора алертов |
| Karma | `karma.monitoring.svc.cluster.local:8080` | Внутренний доступ из других подов |

## Дополнительная информация

- [Alertmanager StatefulSet](./alertmanager-statefulset.md) — поды, которые обслуживает Service `alertmanager`
- [Karma Deployment](./karma-deployment.md) — поды, которые обслуживает Service `karma`
- [Обзор Service](../../../Kubernetes/Networking/Service/service_overview.md) — общая теория Service в Kubernetes
- [Обзор Ingress](../../../Kubernetes/Networking/Ingress/overview.md) — общая теория Ingress в Kubernetes
