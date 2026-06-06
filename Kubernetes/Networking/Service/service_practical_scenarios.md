# Практические сценарии Service

## Определения

**Практические сценарии** — пошаговые руководства по публикации приложений в Kubernetes через сервисы различных типов.

**Цель:** Демонстрация полного цикла от внутреннего доступа до внешней публикации. Базовые определения и теорию см. в [Обзоре Service](./service_overview.md).

## Основные концепции

### Последовательность публикации

Рекомендуемый подход к публикации приложений:

1. **ClusterIP** — внутренний доступ для тестирования и отладки.
2. **NodePort** — внешний доступ для разработки и on-premise сред.
3. **LoadBalancer/Ingress** — production-публикация (см. [Сводку по типам](./service_types_summary.md)).

### Ключевые принципы

- **Селекторы:** Должны точно совпадать с метками подов (labels). Подробно о [Labels и Selectors](./service_overview.md#механизм-работы-через-labels-и-selectors).
- **Namespace:** Pod и Service должны находиться в одном пространстве имён для прямого взаимодействия.
- **Порты:** Правильное сопоставление `port` (вход сервиса) и `targetPort` (порт приложения). См. [Спецификацию портов](./service_overview.md#спецификация-портов-port-vs-targetport).

## Практические сценарии

### Подготовка: Создание Deployment

Для сценариев будем использовать Nginx.

```yaml
# nginx-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
```

Примените манифест: `kubectl apply -f nginx-deployment.yaml`.

---

### Сценарий 1: Публикация через ClusterIP (внутренний доступ)

Создадим сервис типа **[ClusterIP](./service_type_clusterip.md)** для доступа к Nginx внутри кластера.

#### Манифест Service

```yaml
# nginx-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
spec:
  selector:
    app: nginx
  type: ClusterIP  # Значение по умолчанию
  ports:
    - name: http
      protocol: TCP
      port: 8080      # Порт сервиса внутри кластера
      targetPort: 80  # Порт приложения на подах
```

#### Создание и проверка

1. **Применяем манифест:** `kubectl apply -f nginx-service.yaml`.
2. **Проверяем сервис:** `kubectl get service nginx-service`.
   - В колонке `CLUSTER-IP` появится внутренний IP (например, `10.104.117.48`).
3. **Проверка доступа:** Зайдите в любой под и выполните запрос: `curl 10.104.117.48:8080`.

---

### Сценарий 2: Преобразование в NodePort (внешний доступ)

Изменим тип сервиса на **[NodePort](./service_type_nodeport.md)** для доступа через IP узлов.

#### Изменение манифеста

```yaml
# nginx-service.yaml (обновление)
spec:
  type: NodePort
  ports:
    - name: http
      protocol: TCP
      port: 8080
      targetPort: 80
      nodePort: 30080 # Опционально (30000-32767)
```

#### Обновление и проверка

1. **Применяем изменения:** `kubectl apply -f nginx-service.yaml`.
2. **Проверяем сервис:** `kubectl get service nginx-service`.
   - В колонке `PORT(S)` появится маппинг `8080:30080/TCP`.
3. **Проверка доступа:** Выполните запрос с локальной машины на IP любого узла кластера: `curl http://<Node-IP>:30080`.

## Дополнительная информация

### Диагностика и устранение неполадок

| Команда | Описание |
| :--- | :--- |
| `kubectl get svc` | Список всех сервисов |
| `kubectl describe svc <name>` | Детальная информация и события |
| `kubectl get endpoints <name>` | Список IP-адресов подов, обслуживаемых сервисом |
| `kubectl logs <pod-name>` | Логи приложения для проверки получения трафика |

### Типичные проблемы

- **Connection refused:** Поды не готовы. Проверьте статус подов и readiness probe.
- **No endpoints:** Селектор сервиса не совпадает с метками подов. Проверьте: `kubectl get pods --show-labels`.
- **Доступ только с одной ноды:** Проверьте конфигурацию CNI и сетевую связность между узлами.

### См. также

- [Типы сервисов: сводка](./service_types_summary.md)
- [LoadBalancer](./service_type_loadbalancer.md) — для production в облаке.
- [Ingress](../Ingress/overview.md) — для HTTP/HTTPS маршрутизации.
