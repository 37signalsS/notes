# Сценарий: Мониторинг Node.js приложения через ServiceMonitor

## Определения

**ServiceMonitor (Node.js)** — Custom Resource для Prometheus Operator, который указывает, как собирать метрики с приложения Node.js, развернутого в кластере. Operator преобразует ServiceMonitor в конфигурацию `scrape_configs` внутри Prometheus.

**Scrape Path** — путь, по которому приложение отдает метрики (например, `/metrics` или `/swagger-stats/metrics`).

**PrometheusRule** — CRD Prometheus Operator для декларативного описания правил алертинга (alerting rules) и правил записи (recording rules). Operator преобразует PrometheusRule в ConfigMap, который автоматически монтируется в Prometheus.

**Metric Relabelings** — набор правил relabeling, применяемый к метрикам **после** их сбора, но **до** записи в TSDB. Позволяет фильтровать, переименовывать или агрегировать метрики на уровне ServiceMonitor.

**Namespace Selector** — механизм выбора namespace'ов, в которых Prometheus Operator ищет Service и Endpoints для скрейпинга. Используется для изоляции мониторинга между командами/средами.

**Native Histograms** — формат гистограм в Prometheus 3.0+, при котором клиентская библиотека экспортирует гистограмму целиком, без агрегации на стороне сервера. Снижает потребление памяти и ускоряет запросы.

## Подготовка приложения

### 1. Зависимости приложения

Создайте файл `package.json` с явным указанием версий зависимостей:

```json
{
  "name": "node-api",
  "version": "1.0.0",
  "dependencies": {
    "express": "^4.18.2",
    "prom-client": "^14.2.0",
    "swagger-stats": "^0.95.0"
  }
}
```

**Почему это важно:** Нефиксированные версии (`latest`) могут привести к неожиданному поведению при сборке образа. Для production используйте lock-файл (`package-lock.json`) и CI/CD-пайплайн с проверкой уязвимостей (`npm audit`).

### 2. Образ приложения

```dockerfile
FROM node:18-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY . .

# Health check для Kubernetes
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node healthcheck.js

EXPOSE 3000
CMD ["node", "app.js"]
```

**Security Note:** Используйте `node:18-alpine` вместо `node:18` для уменьшения поверхности атаки. Добавьте非 root пользователя:

```dockerfile
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nodejs -u 1001
USER nodejs
```

### 3. Полный код приложения (`app.js`)

```javascript
const express = require('express');
const client = require('prom-client');
const swaggerStats = require('swagger-stats');

const app = express();
const register = new client.Registry();

// Включение стандартных метрик Node.js (event loop, memory, CPU)
client.collectDefaultMetrics({ register });

// Кастомная метрика: HTTP-задержка
const httpRequestDuration = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'],
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
  registers: [register]
});

// Кастомный счетчик: ошибки приложения
const appErrorsTotal = new client.Counter({
  name: 'app_errors_total',
  help: 'Total application errors',
  labelNames: ['error_type', 'severity'],
  registers: [register]
});

// Middleware: сбор метрик HTTP
app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const duration = (Date.now() - start) / 1000;
    httpRequestDuration
      .labels(req.method, req.route?.path || req.path, res.statusCode)
      .observe(duration);
  });
  next();
});

// Middleware: swagger-stats (опционально)
app.use(swaggerStats.getMiddleware());

// Endpoints
app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});

app.get('/healthz', (req, res) => {
  res.json({ status: 'healthy', timestamp: Date.now() });
});

app.get('/api/users', (req, res) => {
  res.json([{ id: 1, name: 'Alice' }]);
});

app.get('/api/error', (req, res) => {
  appErrorsTotal.labels('http', 'warning').inc();
  res.status(500).json({ error: 'Simulated error' });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
```

**Health check (`healthcheck.js`):**
```javascript
const http = require('http');

const options = {
  hostname: 'localhost',
  port: process.env.PORT || 3000,
  path: '/healthz',
  timeout: 2000
};

const req = http.request(options, (res) => {
  process.exit(res.statusCode === 200 ? 0 : 1);
});

req.on('error', () => process.exit(1));
req.end();
```

### 4. Манифесты Kubernetes (Deployment + Service)

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
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: api
        image: your-registry/node-api:1.0.0
        ports:
        - containerPort: 3000
          name: web
          protocol: TCP
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
        livenessProbe:
          httpGet:
            path: /healthz
            port: web
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /healthz
            port: web
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: node-api-service
  labels:
    app: node-api
    job: node-api-metrics
spec:
  selector:
    app: node-api
  ports:
  - name: web
    port: 80
    targetPort: 3000
    protocol: TCP
```

## Настройка мониторинга

### 5. Создание ServiceMonitor (базовый)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: node-api-monitor
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: node-api
  jobLabel: job
  endpoints:
  - port: web
    interval: 30s
    path: /metrics
```

**Важность метки `release`:** Prometheus Operator использует селектор `ruleSelector`/`serviceMonitorSelector` в ресурсе `Prometheus` для фильтрации CRD. Если селектор настроен на `release: prometheus-stack`, все ServiceMonitor, PrometheusRule и другие CRD должны содержать эту метку, иначе Operator их игнорирует.

### 6. Создание ServiceMonitor с namespaceSelector

Если приложение развернуто в нескольких namespace'ах:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: node-api-monitor
  labels:
    release: prometheus-stack
    team: backend
spec:
  namespaceSelector:
    matchNames:
    - prod-backend
    - staging-backend
  selector:
    matchLabels:
      app: node-api
  endpoints:
  - port: web
    interval: 15s
    path: /metrics
    metricRelabelings:
    - sourceLabels: [__name__]
      regex: '(go_.*|nodejs_.*)'
      action: keep
```

**metricRelabelings:** В примере выше сохраняются только метрики Node.js runtime (`go_.*`, `nodejs_.*`), отфильтровывая служебные метрики HTTP-сервера Express. Это снижает кардинальность и объем TSDB.

### 7. Создание правил оповещения (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: node-api-rules
  labels:
    release: prometheus-stack
    team: backend
spec:
  groups:
  - name: node-api.availability
    rules:
    - alert: NodeApiDown
      expr: up{job="node-api-metrics"} == 0
      for: 2m
      labels:
        severity: critical
      annotations:
        summary: "Instance {{ $labels.instance }} недоступна"
        description: "Node.js API instance is down for more than 2 minutes."

  - name: node-api.latency
    rules:
    - alert: NodeApiHighLatency
      expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, route)) > 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High latency on {{ $labels.route }}"
        description: "95th percentile latency is {{ $value }}s for route {{ $labels.route }}."

  - name: node-api.errors
    rules:
    - alert: NodeApiErrorRate
      expr: sum(rate(app_errors_total[5m])) by (error_type) > 0.1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Error rate spike for {{ $labels.error_type }}"
        description: "Error rate is {{ $value }} errors/sec for type {{ $labels.error_type }}."

  - name: node-api.sli
    rules:
    - record: node_api:request_rate:5m
      expr: sum(rate(http_request_duration_seconds_count[5m])) by (route)
    - record: node_api:error_rate:5m
      expr: sum(rate(app_errors_total[5m])) by (error_type)
```

### 8. Провижининг дашборда Grafana через ConfigMap

Grafana Sidecar автоматически обнаружит ConfigMap с меткой `grafana_dashboard: "1"`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: node-api-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "Node.js Applications"
data:
  node-api-dashboard.json: |
    {
      "uid": "node-api",
      "title": "Node.js API — Application Metrics",
      "schemaVersion": 39,
      "version": 1,
      "refresh": "30s",
      "timezone": "browser",
      "panels": [
        {
          "id": 1,
          "title": "Request Rate",
          "type": "graph",
          "targets": [
            {
              "expr": "sum(rate(http_request_duration_seconds_count[5m])) by (route)",
              "legendFormat": "{{route}}"
            }
          ],
          "yaxes": [{ "format": "rps" }]
        },
        {
          "id": 2,
          "title": "P95 Latency",
          "type": "graph",
          "targets": [
            {
              "expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, route))",
              "legendFormat": "{{route}}"
            }
          ],
          "yaxes": [{ "format": "s" }]
        },
        {
          "id": 3,
          "title": "Error Rate",
          "type": "graph",
          "targets": [
            {
              "expr": "sum(rate(app_errors_total[5m])) by (error_type)",
              "legendFormat": "{{error_type}}"
            }
          ]
        }
      ]
    }
```

## Проверка и диагностика

### 1. Просмотр ресурсов
```bash
kubectl get servicemonitor node-api-monitor -o wide
kubectl get prometheusrule node-api-rules -o wide
kubectl get configmap node-api-dashboard -n monitoring
```

### 2. Проверка сгенерированной конфигурации Prometheus
```bash
kubectl get secret prometheus-operated -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip -c | \
  grep -A 20 "job_name:.*node-api"
```

### 3. Валидация через promtool
```bash
# Извлечь и проверить конфигурацию
kubectl get secret prometheus-operated -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip -c > /tmp/prometheus.yaml

promtool check config /tmp/prometheus.yaml
promtool check rules /tmp/node-api-rules.yaml
```

### 4. Порт-форвардинг в Prometheus UI
```bash
kubectl port-forward svc/prometheus-operated 9090
```
В интерфейсе:
- **Status -> Targets:** Найдите `serviceMonitor/monitoring/node-api-monitor/0`.
- **Status -> Configuration:** Найдите сгенерированный блок `job_name`.
- **Graph:** Выполните запрос `up{job="node-api-metrics"}`.
- **Rules:** Проверьте загрузку `node-api.rules`.

### 5. Валидация дашборда Grafana
```bash
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80
# Логин: admin, пароль: kubectl get secret monitoring-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d
```

### 6. Диагностическая таблица

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Target DOWN** | Неверный `matchLabels` в ServiceMonitor | Проверьте `kubectl get svc <name> --show-labels` и сравните с `matchLabels` |
| **Метрики 404** | Неверный `path` или `port` | Убедитесь, что endpoint приложения отвечает на `/metrics`; проверьте `kubectl port-forward` + `curl` |
| **PrometheusRule не загружается** | Отсутствует метка `release` | Добавьте `release: prometheus-stack` в `metadata.labels` |
| **Дашборд не появился** | Отсутствует `grafana_dashboard: "1"` | Проверьте label на ConfigMap и права RBAC sidecar |
| **Метрики дублируются** | Несколько ServiceMonitor на один Service | Проверьте `kubectl get servicemonitor` и уникальность селекторов |
| **Высокая кардинальность** | Много уникальных значений в label'ах | Добавьте `metricRelabelings` для `labeldrop` или `keep` |
| **Cardinality explosion** | Неограниченный `__name__` | Настройте `sample_limit` или `metric_relabelings` в `values.yaml` |
| **Валидация не проходит** | Синтаксис YAML или PromQL | Выполните `promtool check rules` и `promtool check metrics` локально |
| **Endpoints пустые** | Readiness Probe не проходит | Проверьте `kubectl describe pod <pod>` и логи приложения |
| **RBAC Error** | Operator не имеет прав на namespace | Проверьте `serviceMonitorNamespaceSelector` в `values.yaml` |

## Дополнительная информация

### Сравнение ServiceMonitor и PodMonitor

| Критерий | ServiceMonitor | PodMonitor |
| :--- | :--- | :--- |
| **Обнаружение** | Через Service → Endpoints/EndpointSlice | Прямой скрейпинг подов по IP |
| **Когда использовать** | Stateless-приложения за балансировщиком | Stateful-приложения, DaemonSet, sidecar без Service |
| **Гибкость** | Зависит от меток Service | Прямой контроль over pods |
| **Пример для Node.js** | Приложение за Service/Ingress | Если скрейпинг нужен до балансировщика |

### Рекомендации по безопасности

1. **SecurityContext:** Приложение должно запускаться с `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`.
2. **NetworkPolicy:** Ограничьте доступ к порту `3000` только namespace'ом Prometheus и Ingress Controller.
3. **Secrets:** Не храните пароли/ключи в image. Используйте `envFrom` + `secretKeyRef`.

### Рекомендации по эксплуатации (Best Practices)

1. **Фиксируйте версии:** Используйте теги образов вместо `latest` в production.
2. **Resource Quotas:** Задайте `resources.requests` и `resources.limits` для predictability.
3. **Health Probes:** Настройте `/healthz` (liveness + readiness) для корректной работы Endpoints.
4. **Metric Naming:** Следуйте соглашениям Prometheus: `*_total` для счетчиков, `*_seconds` для гистограмм, `*_bytes` для размеров.
5. **Cardinality:** Ограничьте cardinality метрик (менее 10k series per target). Используйте `metricRelabelings` для фильтрации.
6. **Native Histograms:** Включите `enableFeatures: [native-histograms]` в `values.yaml` для снижения потребления памяти.
7. **ServiceMonitor Namespace Isolation:** Используйте `namespaceSelector` для разделения мониторинга между средами (prod/staging/dev).
8. **PrometheusRule Organization:** Разбивайте правила по namespace или команде. Один ConfigMap — одна команда/сервис.
9. **Grafana Dashboards:** Храните дашборды в Git рядом с манифестами приложения.
10. **Validation in CI:** Внедрите `promtool check rules` и `promtool check metrics` в пайплайн.

### Пограничные случаи

1. **Многоконтейнерный Pod:** Если Node.js приложение работает в одном Pod с sidecar (например, Envoy), используйте ServiceMonitor с указанием `port: web` или PodMonitor для прямого скрейпинга.
2. **Cluster Mode:** В кластерном режиме используйте `AggregatorRegistry` для объединения метрик от воркеров. Убедитесь, что `/metrics` endpoint отдает агрегированные данные.
3. **TLS на приложении:** Если приложение экспонирует метрики по HTTPS, настройте `tlsConfig` в ServiceMonitor.
4. **Базовая аутентификация:** Для защиты `/metrics` используйте `basicAuth` в ServiceMonitor с Secret.
5. **Ограничение размера ConfigMap (1MB):** Большие дашборды должны быть сжаты (`GZIP: true`) или разбиты на несколько ConfigMap.
6. **Hot Reload задержка:** Изменения в PrometheusRule применяются с задержкой до 90 секунд (config-reloader).
7. **EndpointSlice пустой:** Проверьте readiness probe приложения и селектор Service.
8. **Duplicate series:** Если несколько ServiceMonitor скрейпят один endpoint, метрики будут дублироваться. Используйте уникальные `jobLabel`.
9. **PrometheusRule > 1MB:** Разбейте правила на несколько `PrometheusRule` по namespace или функциональности.
10. **Rollback Helm:** При `helm rollback` CRD не удаляются, но ServiceMonitor/PrometheusRule могут остаться в состоянии, не соответствующем новой версии.

### Откат и очистка

```bash
# Удаление ServiceMonitor
kubectl delete servicemonitor node-api-monitor

# Удаление PrometheusRule
kubectl delete prometheusrule node-api-rules

# Удаление ConfigMap с дашбордом
kubectl delete configmap node-api-dashboard -n monitoring

# Откат Deployment
kubectl rollout undo deployment/node-api

# Удаление Deployment и Service
kubectl delete -f node-api.yaml
```

### Полезные команды для диагностики

```bash
# Проверка endpoints Service
kubectl describe svc node-api-service | grep -A 5 "Endpoints:"

# Проверка сгенерированного ServiceMonitor в Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.job=="node-api-metrics")'

# Проверка метрик приложения
kubectl port-forward deployment/node-api 3000:3000 &
curl -s http://localhost:3000/metrics | head -20

# Проверка правил алертов
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[] | select(.name=="node-api.*")'

# Логи Operator (если ServiceMonitor не появляется)
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator -c prometheus-operator --tail=100

# Проверка конфигурации Alertmanager
kubectl get secret monitoring-kube-prometheus-alertmanager -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d
```

### Связанные ресурсы

* [ServiceMonitor CRD](../../operator/crd/servicemonitor.md) — справочник параметров.
* [PrometheusRule CRD](../../operator/crd/prometheusrule.md) — правила алертинга и записи.
* [Prometheus Operator — Концепции](../../operator/concepts.md) — архитектура сбора данных.
