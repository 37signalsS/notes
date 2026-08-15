# Сценарий: Мониторинг Node.js приложения через ServiceMonitor

## Определения

**ServiceMonitor (Node.js)** — Custom Resource для Prometheus Operator, который указывает, как собирать метрики с приложения Node.js, развернутого в кластере.

**Scrape Path** — путь, по которому приложение отдает метрики (например, `/metrics` или `/swagger-stats/metrics`).

## Подготовка приложения

Для демонстрации используется Node.js приложение с библиотекой `express` и `swagger-stats` для генерации метрик Prometheus.

### 1. Образ приложения
Приложение должно слушать порт (например, `3000`) и отдавать метрики.

```dockerfile
FROM node:18
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["node", "app.js"]
```

### 2. Манифесты Kubernetes (Deployment + Service)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: node-api
  labels:
    app: node-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: node-api
  template:
    metadata:
      labels:
        app: node-api
    spec:
      containers:
      - name: api
        image: your-registry/node-api:latest
        ports:
        - containerPort: 3000
---
apiVersion: v1
kind: Service
metadata:
  name: node-api-service
  labels:
    app: node-api
    job: node-api-metrics # Метка для использования в jobLabel
spec:
  selector:
    app: node-api
  ports:
  - name: web
    port: 80
    targetPort: 3000
```

## Настройка мониторинга

### 3. Создание ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: node-api-monitor
  labels:
    # Критично: метка для обнаружения оператором
    release: prometheus-stack 
spec:
  selector:
    matchLabels:
      app: node-api # Должно совпадать с меткой в Service
  jobLabel: job # Использовать значение метки 'job' из сервиса как имя задачи
  endpoints:
  - port: web # Имя порта из Service
    interval: 30s
    path: /swagger-stats/metrics
```

### 4. Создание правил оповещения (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: node-api-rules
  labels:
    release: prometheus-stack
spec:
  groups:
  - name: node-api.rules
    rules:
    - alert: NodeApiDown
      expr: up{job="node-api-metrics"} == 0
      for: 2m
      labels:
        severity: critical
      annotations:
        summary: "Instance {{ $labels.instance }} is down"
        description: "Node.js API instance is down for more than 2 minutes."
```

## Проверка и диагностика

### 1. Просмотр ресурсов
```bash
kubectl get servicemonitor node-api-monitor
kubectl get prometheusrule node-api-rules
```

### 2. Порт-форвардинг в Prometheus UI
```bash
kubectl port-forward svc/prometheus-operated 9090
```
В интерфейсе:
- **Status -> Targets:** Найдите `serviceMonitor/monitoring/node-api-monitor/0`.
- **Status -> Configuration:** Найдите сгенерированный блок `job_name` для `node-api`.
- **Graph:** Выполните запрос `up{job="node-api-metrics"}`.

### 3. Отладка проблем
Если цель не появилась:
1. Проверьте наличие метки `release: ...` на `ServiceMonitor`.
2. Проверьте, что селектор `matchLabels` точно совпадает с метками в `Service`.
3. Убедитесь, что порт в `ServiceMonitor` (`port: web`) соответствует **имени** порта в `Service`.

## Дополнительная информация

* [ServiceMonitor CRD](../../operator/crd/servicemonitor.md) — справочник параметров.
* [Prometheus Operator — Концепции](../../operator/concepts.md) — архитектура сбора данных.
