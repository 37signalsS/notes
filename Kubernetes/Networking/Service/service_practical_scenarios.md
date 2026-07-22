# Практические сценарии Service

## Определения

**Практические сценарии** — пошаговые руководства по публикации приложений в Kubernetes через сервисы различных типов.

**Цель:** Демонстрация настройки сетевой связности от базового внутреннего доступа до продвинутых конфигураций с сохранением IP-адреса клиента. Теоретическую базу см. в [Обзоре Service](./service_overview.md).

## Основные концепции

### Иерархия публикации

При разработке и развертывании рекомендуется придерживаться следующей последовательности:

1. **ClusterIP:** Изоляция сервиса внутри кластера.
2. **Headless:** Для прямого взаимодействия между узлами БД или Stateful-приложений.
3. **NodePort / LoadBalancer:** Вывод приложения на внешний контур.

### Ключевые требования

- **Метки (Labels):** Основа связности. Service находит поды только при точном совпадении `spec.selector` и `metadata.labels` пода.
- **Порты:**
    - `port`: порт, на котором сервис принимает трафик.
    - `targetPort`: порт, на котором приложение слушает внутри контейнера.
- **Ready State:** Сервис направляет трафик только на те поды, которые прошли `readinessProbe`.

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

Примените манифест: `kubectl apply -f nginx-deploy.yaml`.

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
# → <CLUSTER-IP>

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
- Трафик будет приниматься только теми узлами, на которых запущены поды `nginx-demo`.
- Если на узле нет подходящих подов, соединение будет сброшено.

---

### Сценарий 3: Прямое обнаружение подов (Headless)

Используется для кластерных решений (Elasticsearch, MongoDB, Kafka), где клиенту нужен список IP всех реплик.

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
kubectl run dns-test --rm -it --image=busybox:1.28 -- nslookup db-cluster
# → Возвращает список IP-адресов всех подов вместо одного VIP
```

## Дополнительная информация

### Диагностика сетевой связности

| Задача | Команда |
| :--- | :--- |
| Проверка эндпоинтов | `kubectl get endpoints nginx-service` |
| Анализ EndpointSlices | `kubectl get endpointslice -l kubernetes.io/service-name=nginx-service` |
| Описание состояния | `kubectl describe svc nginx-service` |
| Проверка правил iptables | `iptables-save | grep nginx-service` (на узле) |

### Типичные ошибки и решения

1. **Эндпоинты пусты (`<none>`):**
    - Ошибка в селекторе. Проверьте: `kubectl get pods --show-labels`.
    - Поды не прошли `readinessProbe`. Проверьте: `kubectl get pods`.
2. **Трафик не доходит до NodePort:**
    - Закрыт порт 30000-32767 на внешнем Firewall или Security Group облака.
    - `kube-proxy` не запущен или упал на целевом узле.
3. **Не работает DNS-имя:**
    - Проверьте логи CoreDNS: `kubectl logs -n kube-system -l k8s-app=kube-dns`.

### См. также

- [Подробный разбор типов Service](./service_types_summary.md)
- [NodePort — глубокое погружение](./service_type_nodeport.md)
- [Headless Service — специфика](./service_type_headless.md)
- [Service Discovery через DNS](../Network/dns_service_discovery.md)
