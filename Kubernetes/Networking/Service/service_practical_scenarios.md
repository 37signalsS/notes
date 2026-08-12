# Практические сценарии Service

## Определения

**Практические сценарии** — пошаговые руководства по публикации приложений в Kubernetes через сервисы различных типов.

**Цель:** Демонстрация настройки сетевой связности от базового внутреннего доступа до продвинутых конфигураций с сохранением IP-адреса клиента. Теоретическую базу см. в [Обзоре Service](./service_overview.md).

## Основные концепции

### Иерархия публикации

При разработке и развертывании рекомендуется придерживаться следующей последовательности:

1. **ClusterIP:** Изоляция сервиса внутри кластера.
2. **Headless:** Для прямого взаимодействия между узлами БД или Stateful-приложений.
3. **Topology Aware Routing:** Оптимизация трафика внутри зон для снижения задержек.
4. **NodePort / LoadBalancer:** Вывод приложения на внешний контур.

### Ключевые требования и компоненты

- **Метки (Labels):** Основа связности. Service находит поды только при точном совпадении `spec.selector` и `metadata.labels` пода.
- **Порты:**
    - `port`: порт, на котором сервис принимает трафик.
    - `targetPort`: порт, на котором приложение слушает внутри контейнера.
- **Ready State:** Сервис направляет трафик только на те поды, которые прошли `readinessProbe`.
- **EndpointSlices (v1.30+):** Современный механизм управления эндпоинтами, заменяющий устаревший API `Endpoints`. Именно EndpointSlices обеспечивают масштабируемость и поддержку топологии (Topology Hints).

---

## Практические сценарии

### Подготовка: Создание Deployment

Используем Nginx для демонстрации сетевого взаимодействия.

```yaml
# nginx-deploy.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-lb-test
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx-demo
  template:
    metadata:
      labels:
        app: nginx-demo
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
```

---

### Сценарий 0: Быстрое создание Service (Императивный путь)

Использование `kubectl expose` для автоматического создания сервиса на основе существующего Pod или Deployment.

```bash
# Создание ClusterIP сервиса для пода
kubectl expose pod my-nginx --port=80 --target-port=80 --name=nginx-internal

# Создание NodePort сервиса для Deployment
kubectl expose deployment my-deploy --port=80 --type=NodePort --name=nginx-external
```

---

### Сценарий 1: Внутренний доступ (ClusterIP)

Создание стабильной точки входа для межсервисного взаимодействия.

```yaml
# clusterip-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: internal-api
spec:
  type: ClusterIP
  selector:
    app: nginx-demo
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
```

**Проверка:**
```bash
# Получение ClusterIP
kubectl get svc internal-api

# Проверка из другого пода
kubectl run test-pod --rm -it --image=curlimages/curl -- curl http://internal-api
```

---

### Сценарий 2: Сохранение IP клиента (NodePort + Local Policy)

Используется, когда приложению необходимо видеть реальный IP-адрес источника, а не IP-адрес узла кластера.

```yaml
# nodeport-local.yaml
apiVersion: v1
kind: Service
metadata:
  name: external-web-access
spec:
  type: NodePort
  externalTrafficPolicy: Local # Критично для сохранения Source IP
  selector:
    app: nginx-demo
  ports:
    - port: 80
      targetPort: 80
      nodePort: 32080
```

**Особенности:**
- Трафик принимается только теми узлами, на которых запущены целевые поды.
- Если на узле нет подов, соединение будет сброшено.

---

### Сценарий 3: Прямое обнаружение подов (Headless)

Используется для кластерных решений (Elasticsearch, Kafka), где клиенту нужен список IP всех реплик.

```yaml
# headless-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: db-cluster
spec:
  clusterIP: None # Делает сервис Headless
  selector:
    app: nginx-demo
  ports:
    - port: 80
```

**Проверка DNS:**
```bash
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup db-cluster
# → Возвращает список IP всех подов вместо одного VIP
```

---

### Сценарий 4: Оптимизация трафика по зонам (Topology Aware Routing)

**Новое в K8s 1.31 (Beta):** Использование поля `spec.trafficDistribution` для удержания трафика в той же зоне доступности.

```yaml
# topology-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: local-zone-api
spec:
  selector:
    app: nginx-demo
  trafficDistribution: PreferClose # Предпочитать эндпоинты в той же зоне/узле
  ports:
    - port: 80
      targetPort: 80
```

---

### Сценарий 5: Абстракция внешних ресурсов (ExternalName)

Создание DNS-алиаса для внешней базы данных или API.

```yaml
# external-db.yaml
apiVersion: v1
kind: Service
metadata:
  name: external-postgres
spec:
  type: ExternalName
  externalName: db.prod.example.com
```

---

## Устранение неполадок (Troubleshooting)

Связь между Service и подами — фундаментальная концепция сети Kubernetes. Проблемы здесь обычно проявляются как таймауты соединений или отсутствие ответа от сервиса.

### Типичные ошибки конфигурации

1.  **ClusterIP для внешнего доступа:** Использование типа `ClusterIP` (по умолчанию) при попытке достучаться до сервиса извне кластера напрямую. 
    *   *Решение:* Используйте `NodePort`, `LoadBalancer` или настройте `Ingress/Gateway`.
2.  **Несоответствие портов:** Значение `targetPort` в манифесте Service должно точно совпадать с портом, который прослушивает приложение в контейнере (`containerPort`). 
3.  **Отсутствие конечных точек (Endpoints):** Если `kubectl describe service <name>` показывает `Endpoints: <none>`, сервис не может найти подходящие поды.

### Отсутствие конечных точек (Endpoints и EndpointSlices)

Если Service получает запросы, но не перенаправляет их никуда, вероятнее всего, у него отсутствуют связанные эндпоинты. В современных версиях K8s (1.30+) диагностику следует начинать с **EndpointSlices**.

**Основной диагностический инструмент:**
```bash
# Проверка высокоуровневого состояния сервиса
kubectl describe service <имя-сервиса>

# Проверка конкретных EndpointSlices (v1.30+)
kubectl get endpointslice -l kubernetes.io/service-name=<имя-сервиса>
```

В выводе команды `describe service` обратите внимание на:
*   **Selector:** пары ключ-значение (например, `app=frontend`).
*   **Endpoints:** список `IP:порт`. Если здесь `<none>`, селектор не нашел ни одного пода.

#### Основные причины отсутствия эндпоинтов

1.  **Несоответствие меток (Label Mismatch):** Метки на подах не совпадают с селектором сервиса.
    *   *Проверка:* `kubectl get pods --show-labels`.
2.  **Поды не готовы (Not Ready):** Под добавляется в эндпоинты только после прохождения `readinessProbe`.
    *   *Проверка:* `kubectl get pods` (столбец `READY`).
3.  **Namespace Mismatch:** Сервис и поды находятся в разных пространствах имен. Сервис ищет поды только в **своем** namespace.
4.  **Сбой EndpointSlice Mirroring:** В редких случаях (при ручном создании Endpoints) контроллер может не создать соответствующий EndpointSlice.

### Мини-кейс: "Призрачные" поды и Readiness

Команда развернула приложение, поды в статусе `Running`, но сервис выдает `503 Service Unavailable`.
*   **Диагностика:** `kubectl get endpoints` показывает пустой список.
*   **Анализ:** Команда `kubectl describe pod <name>` выявила, что `readinessProbe` обращается к порту `/health`, который в новой версии приложения был изменен на `/ready`.
*   **Решение:** Обновление пути в `readinessProbe` мгновенно вернуло поды в пул эндпоинтов сервиса.

> **Совет для собеседования:**
> **Вопрос:** В чем разница между Endpoints и EndpointSlices?
> **Ответ:** `Endpoints` — старый монолитный API, который хранит все IP в одном объекте. При наличии 1000+ подов это перегружает `etcd` и API-сервер. `EndpointSlices` (стандарт с 1.21+) разбивает список на части (по 100 подов по умолчанию), поддерживает топологию и IPv4/IPv6 стеки одновременно.

## Дополнительная информация

### Инструменты диагностики

| Задача | Команда |
| :--- | :--- |
| Проверка EndpointSlices | `kubectl get endpointslice -l kubernetes.io/service-name=<name>` |
| Проверка меток подов | `kubectl get pods --show-labels` |
| Описание состояния | `kubectl describe svc <name>` |
| Эфемерная отладка сети | `kubectl debug -it <pod> --image=nicolaka/netshoot` |
| Проверка DNS резолвинга | `kubectl run test --rm -it --image=busybox:1.37 -- nslookup <svc>` |

### См. также

- [Диагностика и устранение неисправностей проб](../Base/probes.md#диагностика-и-устранение-неисправностей)
- [Подробный разбор типов Service](./service_types_summary.md)
- [Service Discovery через DNS](../Network/dns_service_discovery.md)
- [Траблшутинг Kubernetes (обзор)](../Troubleshooting/troubleshooting_overview.md)
