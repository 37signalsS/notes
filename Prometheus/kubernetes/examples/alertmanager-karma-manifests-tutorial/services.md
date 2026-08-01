# Сетевой доступ: Сервисы и Ingress

## Определения

**Kubernetes Service** — абстракция, определяющая логический набор подов и политику доступа к ним. В данном руководстве используются сервисы типа `ClusterIP` для обеспечения внутренней связности между компонентами (Prometheus → Alertmanager, Karma → Alertmanager).

**Ingress** — API-объект, управляющий внешним доступом к сервисам в кластере, обычно по протоколу HTTP/HTTPS. Ingress обеспечивает L7 маршрутизацию по именам хостов.

---

## Основные концепции

### Схема сетевых потоков

```text
Внешний трафик
       │
       ▼
┌──────────────┐
│   Ingress    │  Маршрутизация по именам хостов
│  Controller  │
└──────┬───────┘
       │
   ┌───┴──────────────────┐
   │                      │
   ▼                      ▼
alertmanager.local      karma.local
   │                      │
   ▼                      ▼
┌──────────────┐    ┌──────────┐
│   Service    │    │ Service  │
│ alertmanager │    │  karma   │
│ (Port 9093)  │    │ (Port 80)│
└──────┬───────┘    └────┬─────┘
       │                 │
       ▼                 ▼
  ┌─────────┐      ┌─────────┐
  │   Pods  │      │  Pods   │
  │alertmgr │      │  karma  │
  └─────────┘      └─────────┘
```

---

## Практические сценарии

### Настройка внутренних сервисов

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

### Маршрутизация через Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: monitoring-ingress
  namespace: monitoring
spec:
  rules:
    - host: alertmanager.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: alertmanager
                port: { number: 9093 }
    - host: karma.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: karma
                port: { number: 80 }
```

---

## Дополнительная информация

- **[Манифест StatefulSet](./alertmanager-statefulset.md)** — описание подов Alertmanager.
- **[Развёртывание Karma](./karma-deployment.md)** — описание подов дашборда.
- **[Обзор Ingress](../../../Kubernetes/Networking/Ingress/overview.md)** — SSoT по сетевой маршрутизации.
- **[Reliability Scores](../../../../GEMINI.md)** — методология оценки достоверности (Score: 10).
