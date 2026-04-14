# Service Overview

## Определения

**Service** — абстракция в Kubernetes, определяющая логический набор подов и политику доступа к ним. Предоставляет единую стабильную точку входа (IP-адрес и DNS-имя) для доступа к группе подов, выполняющих одну функцию, даже при изменении их внутренних IP-адресов.

**Основная задача:** Обеспечение сетевой связности и балансировки нагрузки для приложений.

## Основные концепции

### Проблема эфемерности IP-адресов подов

IP-адреса подов в Kubernetes **эфемерны (временны)**:

- IP привязан к поду только на время его жизни
- При удалении пода (ошибка, обновление, перемещение) новый под получает другой IP
- Поды не «перезапускаются» — старый удаляется, Deployment создаёт новый с другими именем и IP

**Следствие:** Нельзя полагаться на прямые IP-адреса для взаимодействия. Service решает эту проблему, предоставляя стабильную точку входа.

### Механизм работы через Labels и Selectors

Связь между Service и подами устанавливается через **метки (labels)** и **селекторы (selectors)**:

1. **Labels:** Подам назначаются одинаковые метки (например, `app.kubernetes.io/name: my-app`)
2. **Selector:** В спецификации Service указывается селектор, соответствующий этим меткам

Kubernetes автоматически отслеживает поды с указанными метками и обновляет маршрутизацию, направляя трафик только на работоспособные поды.

### Спецификация Service

Ключевые поля в `spec`:

| Поле | Описание |
| :--- | :--- |
| `selector` | Определяет поды для маршрутизации (по соответствию меток) |
| `ports` | Массив маппинга портов (см. ниже) |
| `type` | Тип сервиса: `ClusterIP`, `NodePort`, `LoadBalancer`, `ExternalName` |
| `clusterIP` | Внутренний IP сервиса (автоматически или вручную) |
| `clusterIP: None` | Headless Service — DNS возвращает IP подов напрямую |

#### Спецификация портов: port vs targetPort

| Порт | Описание |
| :--- | :--- |
| **`port`** | Порт, который «слушает» Service. Клиенты обращаются на этот порт внутри кластера |
| **`targetPort`** | Порт приложения внутри контейнера. Service перенаправляет трафик на этот порт |

**Правило:** `port` — входная дверь сервиса, `targetPort` — дверь приложения.

### Пример манифеста

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-first-nginx
  namespace: work
spec:
  replicas: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: my-first-nginx
  template:
    metadata:
      labels:
        app.kubernetes.io/name: my-first-nginx
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: my-first-nginx
  namespace: work
  labels:
    app.kubernetes.io/name: my-first-nginx
spec:
  selector:
    app.kubernetes.io/name: my-first-nginx
  ports:
    - name: http
      protocol: TCP
      port: 80
      targetPort: 80
  type: ClusterIP
```

### Важность `targetPort`: маршрутизация в многоконтейнерных подах

В подах с несколькими контейнерами (например, [Sidecar-паттерн](../../Base/Pod/pod_sidecar_patterns.md)) критически важно правильно указать `targetPort`.

**Сценарий:** Pod содержит два контейнера:

- Основное приложение на порту `8080`
- Nginx sidecar на порту `80` (раздача статики, проксирование)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-app-service
spec:
  selector:
    app: web-app
  ports:
    - name: http
      protocol: TCP
      port: 80
      targetPort: 80  # Порт Nginx sidecar!
  type: ClusterIP
```

**Последствия ошибки:** При указании `targetPort: 8080` трафик пойдет напрямую к приложению, минуя Nginx (кэширование, rate limiting, TLS-терминация не будут работать).

> **Подробно:** [Nginx Sidecar для раздачи статики](../../Base/Pod/pod_sidecar_patterns.md#nginx-sidecar-для-раздачи-статики)

## Практические сценарии

### Доступ к сервису внутри кластера

Любой под внутри кластера может обратиться к сервису по DNS-имени или `ClusterIP`:

```bash
curl http://my-first-nginx.work:80
```

**Внутрикластерный DNS:** Kubernetes автоматически преобразует имя сервиса в стабильный `ClusterIP`. Это основной способ сетевого взаимодействия внутри кластера.

**Рекомендация:** Для больших проектов с множеством неймспейсов используйте **полное доменное имя**:

```
<service-name>.<namespace>.svc.cluster.local
```

Например: `web.work.svc.cluster.local` вместо `web`.

#### Проверка работы через DNS

```bash
# Вход в под для диагностики
kubectl exec -it <pod-name> -- /bin/sh

# Установка curl (если отсутствует)
apt-get update && apt-get install -y curl  # для Debian/Ubuntu
# или
apk add --no-cache curl  # для Alpine

# Обращение к сервису по имени (не по IP!)
curl http://<service-name>
```

### Доступ снаружи кластера (для разработки)

Сервисы типа `ClusterIP` недоступны извне. Для отладки используйте `kubectl port-forward`:

```bash
kubectl port-forward -n <namespace> service/<service-name> <local-port>:<service-port>
```

**Пример:**

```bash
kubectl port-forward -n work service/my-first-nginx 8080:80
```

После выполнения доступен по адресу `http://localhost:8080`. Команда активна до прерывания (`Ctrl+C`).

> **Production:** Для публикации в production используются [Ingress](../Ingress/overview.md) или [Gateway API](../gateway_api/definitions.md).

### Балансировка нагрузки

Service автоматически балансирует нагрузку между подами:

- Запросы равномерно распределяются (round-robin)
- При масштабировании балансировка сохраняется
- Обеспечивается отказоустойчивость

**Проверка балансировки:** Запустите логи подов и отправьте запросы к сервису в цикле — запросы будут приходить поочерёдно на разные поды.

## Дополнительная информация

### Endpoints и EndpointSlices

При создании Service Kubernetes автоматически создаёт объект **EndpointSlice** (в старых версиях — **Endpoints**):

- **EndpointSlice** содержит список актуальных IP-адресов и портов подов, соответствующих `selector` сервиса
- Контроллер `endpointslice-controller` отслеживает поды и обновляет EndpointSlice при изменениях
- `kube-proxy` использует EndpointSlice для перенаправления трафика на здоровые поды

**Преимущество EndpointSlice:** Повышенная производительность и масштабируемость по сравнению с устаревшим Endpoints.

### Типы сервисов

Kubernetes предлагает несколько типов сервисов для различных сценариев:

| Тип | Доступность | Основной сценарий |
| :--- | :--- | :--- |
| **[ClusterIP](./service_type_clusterip.md)** | Только внутри кластера | Внутренние коммуникации (backend ↔ db) |
| **[NodePort](./service_type_nodeport.md)** | Через `IP_узла:NodePort` | Разработка, отладка, on-prem |
| **[LoadBalancer](./service_type_loadbalancer.md)** | Через публичный IP | Production в облаке |
| **[ExternalName](./service_type_externalname.md)** | Только DNS (CNAME) | Доступ к внешним сервисам |
| **[Headless](./service_type_headless.md)** | Прямой доступ к подам | Stateful-приложения (StatefulSet) |

> **Сравнение:** Подробное сравнение типов см. в [Сводке по типам сервисов](./service_types_summary.md).

### Дополнительные свойства

- **[ExternalIPs](./service_externalips.md)** — привязка сервиса к статическим внешним IP (депрецируется в v1.36)
- **`externalTrafficPolicy: Local`** — сохранение IP клиента для NodePort/LoadBalancer (см. [NodePort](./service_type_nodeport.md#externaltrafficpolicy-local))
