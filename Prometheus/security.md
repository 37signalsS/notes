# Безопасность в Prometheus

## Определения

**Безопасность Prometheus** — это набор практик и механизмов для защиты метрик и сервера Prometheus от несанкционированного доступа. По умолчанию Prometheus приходит за метриками **без аутентификации**, что создает риски утечки данных при доступе из интернета.

> **См. также:** [DevSecOps](../CI-CD/DevSecOps/devsecops_overview.md) — интеграция безопасности в CI/CD.

## Основные концепции

### Проблемы безопасности по умолчанию

1. **Отсутствие аутентификации** — любой, кто имеет доступ к порту Prometheus, может читать метрики.
2. **Отсутствие шифрования** — данные передаются по HTTP без TLS.
3. **Открытый API** — [HTTP API](./prometheus_api.md) доступен без ограничений.
4. **Метрики могут содержать чувствительные данные** — имена хостов, пути, версии ПО.

### Способы защиты

| Способ | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Аутентификация в Prometheus** | Настройка заголовков для запросов к метрикам | Для внутренних сервисов с поддержкой аутентификации |
| **Отдельный порт для /metrics** | Эндпоинт метрик на порту, не выставленном наружу | Для всех приложений |
| **Файерволл** | Ограничение доступа к порту Prometheus на уровне сети | Обязательно для продакшена |
| **Whitelist на уровне приложения** | Разрешение запросов только с IP Prometheus | Для критичных сервисов |
| **TLS/HTTPS** | Шифрование трафика между Prometheus и целями | При передаче через ненадежные сети |
| **Network Policies (Kubernetes)** | Ограничение сетевого доступа между подами | В Kubernetes |

## Практические сценарии

### Настройка аутентификации в Prometheus

Prometheus может отправлять запросы с заголовками для аутентификации на целевых сервисах.

**Пример конфигурации `prometheus.yml`:**

```yaml
scrape_configs:
  - job_name: 'secure-app'
    scheme: https
    authorization:
      type: Bearer
      credentials: my-secret-token
    # Или basic_auth:
    # basic_auth:
    #   username: prometheus
    #   password: secret
```

> **Важно:** Токены и пароли должны храниться в защищенном месте (secrets manager, Vault).

### Выделение отдельного порта для метрик

Настройте приложение так, чтобы эндпоинт `/metrics` слушал отдельный порт, не доступный извне.

**Пример для Node.js:**

```javascript
// Основной сервер на порту 3000 (публичный)
app.listen(3000);

// Метрики на порту 9090 (внутренний)
const metricsServer = express();
metricsServer.get('/metrics', (req, res) => {
  res.send(register.metrics());
});
metricsServer.listen(9090, '127.0.0.1'); // Только localhost
```

**Пример для Go:**

```go
// Основной сервер
go http.ListenAndServe(":8080", mainMux)

// Метрики только для localhost
metricsMux := http.NewServeMux()
metricsMux.Handle("/metrics", promhttp.Handler())
go http.ListenAndServe("127.0.0.1:9091", metricsMux)
```

### Настройка файерволла

Ограничьте доступ к порту Prometheus (по умолчанию 9090) на уровне ОС или сетевого оборудования.

**Пример для `ufw` (Ubuntu):**

```bash
# Разрешить доступ только с доверенных IP
ufw allow from 10.0.0.0/8 to any port 9090
ufw allow from 192.168.1.100 to any port 9090

# Запретить доступ из интернета
ufw deny 9090/tcp
```

**Пример для `iptables`:**

```bash
iptables -A INPUT -p tcp --dport 9090 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 9090 -j DROP
```

### Whitelist на уровне приложения

Настройте приложение на прием запросов к `/metrics` только с определенных IP.

**Пример для Python (Flask):**

```python
from flask import Flask, request, abort

app = Flask(__name__)

ALLOWED_METRICS_IPS = ['10.0.0.5', '10.0.0.6']  # IP Prometheus

@app.route('/metrics')
def metrics():
    if request.remote_addr not in ALLOWED_METRICS_IPS:
        abort(403)
    return generate_metrics()
```

### TLS для scrape-целей

Для шифрования трафика между Prometheus и целями используйте HTTPS.

**Конфигурация `prometheus.yml`:**

```yaml
scrape_configs:
  - job_name: 'secure-service'
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/ca.crt
      cert_file: /etc/prometheus/client.crt
      key_file: /etc/prometheus/client.key
      insecure_skip_verify: false  # Всегда true в продакшене!
```

### Security в Kubernetes

**NetworkPolicy для ограничения доступа:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-access
spec:
  podSelector:
    matchLabels:
      app: prometheus
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    - podSelector:
        matchLabels:
          app: grafana
    ports:
    - protocol: TCP
      port: 9090
```

**PodSecurityContext для Prometheus:**

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 65534
  runAsGroup: 65534
  fsGroup: 65534
  readOnlyRootFilesystem: true
```

## Дополнительная информация

### Best Practices

1. **Никогда не выставляйте Prometheus в интернет** без прокси с аутентификацией.
2. **Используйте отдельные сервис-аккаунты** для scrape в Kubernetes.
3. **Регулярно обновляйте Prometheus** — следите за security advisory.
4. **Минимизируйте данные в метриках** — не включайте PII, секреты, чувствительные пути.
5. **Включите audit logging** — логируйте доступ к API Prometheus.
6. **Используйте RBAC** — ограничьте права доступа к API Prometheus.

### Проверка безопасности

**Сканирование уязвимостей:**

```bash
# Проверка образа Prometheus
trivy image prom/prometheus:latest

# Проверка конфигурации
kube-bench check --targets node,master
```

**Аудит доступа:**

```promql
# Количество запросов к API Prometheus
sum(rate(prometheus_http_requests_total[5m])) by (handler)

# Ошибки аутентификации (если включено)
sum(rate(prometheus_http_request_duration_seconds_count{code="401"}[5m]))
```

### Связанные темы

* [Configuration](./configuration.md) — настройка аутентификации в `prometheus.yml`
* [Prometheus API](./prometheus_api.md) — защита HTTP API
* [Alertmanager](./alertmanager.md) — безопасность Alertmanager
* [Kubernetes](../Kubernetes/kubernetes_overview.md) — безопасность в K8s
* [Docker Security](../Docker/Docker_security/host_daemon_hardening.md) — изоляция контейнеров
