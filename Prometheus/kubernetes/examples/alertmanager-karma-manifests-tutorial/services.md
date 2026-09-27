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

### Архитектура сервисов Alertmanager

Alertmanager в кластере требует **двух сервисов** с разными типами доступа:

1.  **ClusterIP Service (`alertmanager`)** — обеспечивает стабильную точку входа для веб-интерфейса и API (порт `9093`). Используется Ingress-контроллером и внутренними клиентами для отправки алертов.
2.  **Headless Service (`alertmanager-mesh`)** — обеспечивает прямое DNS-обнаружение подов для Gossip-протокола кластеризации (порт `9094`). Без него реплики Alertmanager не смогут найти друг друга и синхронизировать silences.

### Назначение портов

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| `9093` | TCP | Веб-интерфейс и API Alertmanager. Внешний доступ через Ingress. |
| `9094` | TCP | Gossip-протокол для кластеризации. Внутренний трафик между репликами StatefulSet. |
| `80` | TCP | Внешний порт Karma (Ingress перенаправляет на `targetPort: 8080`). |

### DNS-имена в namespace `monitoring`

| FQDN | Тип сервиса | Назначение |
| :--- | :--- | :--- |
| `alertmanager.monitoring.svc.cluster.local` | ClusterIP | Доступ к API Alertmanager изнутри кластера. |
| `alertmanager-mesh.monitoring.svc.cluster.local` | Headless | DNS возвращает IP всех реплик для Gossip. |
| `karma.monitoring.svc.cluster.local` | ClusterIP | Доступ к UI Karma изнутри кластера. |

### Labels и селекторы

Сервисы связываются с подами через механизм `selector` → `labels`:

- **Alertmanager:** `app: alertmanager` (определен в StatefulSet)
- **Karma:** `app: karma` (определен в Deployment)

При изменении labels подов EndpointSlice Controller автоматически обновляет список эндпоинтов сервиса.

### Примечание по Ingress-контроллеру

По состоянию на март 2026 года официальная поддержка `kubernetes/ingress-nginx` прекращена. Для новых развертываний рекомендуется планировать миграцию на **Gateway API** (стабильна с K8s 1.31). Существующие манифесты с `nginx` продолжают работать, но не получают исправлений безопасности.

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

### Валидация сервисов

После применения манифестов проверьте корректность создания сервисов и их эндпоинтов:

```bash
# Список сервисов в namespace monitoring
kubectl get svc -n monitoring
# NAME              TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)    AGE
# alertmanager      ClusterIP   10.96.0.10      <none>        9093/TCP   5s
# alertmanager-mesh  ClusterIP   None            <none>        9094/TCP   5s
# karma             ClusterIP   10.96.0.11      <none>        80/TCP     5s

# Проверка эндпоинтов (должны отображаться IP всех готовых подов)
kubectl get endpointslices -n monitoring -l kubernetes.io/service-name=alertmanager
kubectl get endpointslices -n monitoring -l kubernetes.io/service-name=alertmanager-mesh

# Детальная информация о сервисе
kubectl describe svc alertmanager -n monitoring
kubectl describe svc alertmanager-mesh -n monitoring
```

### DNS-проверка изнутри кластера

Убедитесь, что поды могут разрешать имена сервисов:

```bash
# Создание временного пода для диагностики DNS
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup alertmanager.monitoring.svc.cluster.local
# → Address: 10.96.0.10

# Проверка Headless Service (возвращает IP всех реплик)
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup alertmanager-mesh.monitoring.svc.cluster.local
# → Address: 10.244.0.10 (alertmanager-0)
# → Address: 10.244.0.11 (alertmanager-1)

# Проверка SRV-записи для портов
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup -type=SRV _9093._tcp.alertmanager.monitoring.svc.cluster.local
```

### Временный доступ для отладки

Для локальной проверки сервисов без настройки Ingress используйте `kubectl port-forward`:

```bash
# Проброс веб-интерфейса Alertmanager на локальный порт 9093
kubectl port-forward -n monitoring svc/alertmanager 9093:9093
# → Forwarding from 127.0.0.1:9093 -> 9093

# Проброс UI Karma на локальный порт 8080
kubectl port-forward -n monitoring svc/karma 8080:80
# → Forwarding from 127.0.0.1:8080 -> 80
```

> **Примечание:** `port-forward` предназначен только для отладки. В production используйте Ingress или Gateway API.

### Устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Service без эндпоинтов (`<none>`) | Несоответствие labels подов и селектора | `kubectl get pods --show-labels -l app=alertmanager` | Исправить labels в StatefulSet или selector в Service |
| Alertmanager не отвечает по ClusterIP | Pod не Ready (readinessProbe не пройден) | `kubectl get pods -n monitoring` — проверка столбца READY | Проверить логи пода и конфигурацию readinessProbe |
| Gossip-рассинхронизация | Headless Service не настроен или порт 9094 закрыт | `kubectl get endpointslices -n monitoring -l kubernetes.io/service-name=alertmanager-mesh` | Проверить `serviceName` в StatefulSet и сетевые политики |
| Ingress возвращает 404 | Ingress-контроллер не установлен или хост не резолвится | `kubectl get pods -n ingress-nginx` (или namespace контроллера) | Установить контроллер, проверить DNS-запись для хоста |
| Ingress возвращает 502 | Бэкенд (Service/Pod) не Ready или порт неверный | `kubectl describe ingress monitoring-ingress -n monitoring` — проверка адресов | Проверить, что Service имеет эндпоинты и порт правильный |
| DNS не резолвит имена сервисов | CoreDNS не работает или `ndots` в конфигурации пода | `kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup kubernetes.default` | Проверить статус CoreDNS, при необходимости увеличить `ndots` |

### Сетевые политики (NetworkPolicy)

Для ограничения доступа к подам Alertmanager и Karma используйте NetworkPolicy. Полный пример приведен в [intro.md](./intro.md#сетевые-политики-networkpolicy). Ключевые правила:
- Разрешить трафик от Ingress-контроллера на порт `9093` (Alertmanager) и `80` (Karma).
- Разрешить внутренний трафик между репликами Alertmanager на порт `9094`.
- Запретить все остальные входящие подключения.

### Очистка ресурсов

```bash
# Удалить Ingress
kubectl delete ingress monitoring-ingress -n monitoring

# Удалить сервисы
kubectl delete svc alertmanager alertmanager-mesh karma -n monitoring

# Проверить отсутствие сервисов
kubectl get svc -n monitoring
```

---

## Дополнительная информация

-   **[Обзор Service](../../../../Kubernetes/Networking/Service/service_overview.md)** — SSoT: принципы работы, селекторы, порты, DNS Discovery.
-   **[Тип Service — Headless](../../../../Kubernetes/Networking/Service/service_type_headless.md)** — SSoT: DNS-записи, `publishNotReadyAddresses`, ограничения.
-   **[Обзор Ingress](../../../../Kubernetes/Networking/Ingress/overview.md)** — SSoT: маршрутизация L7, TLS, контроллеры.
-   **[Манифест StatefulSet](./alertmanager-statefulset.md)** — использование `alertmanager-mesh` в параметрах `--cluster.peer`.
-   **[Секреты Kubernetes](./secrets.md)** — создание `alertmanager-auth` для Ingress Basic Auth.
