# Безопасность Prometheus

## Definitions

**Безопасность Prometheus** — практики и механизмы защиты метрик и сервера Prometheus от несанкционированного доступа. По умолчанию Prometheus собирает метрики **без аутентификации**, что создаёт риски утечки при доступе из интернета.

> **См. также:** [DevSecOps](../CI-CD/DevSecOps/devsecops_overview.md) — интеграция безопасности в CI/CD; [Prometheus Operator Security](./kubernetes/operator/Security/index.md) — безопасность в Kubernetes через Operator.

## Basic Concepts

### Проблемы безопасности по умолчанию

| Проблема | Риск |
| :--- | :--- |
| **Отсутствие аутентификации** | Любой с доступом к порту читает метрики |
| **Отсутствие шифрования** | Данные передаются по HTTP без TLS |
| **Открытый API** | [HTTP API](./prometheus_api.md) доступен без ограничений |
| **Чувствительные данные в метриках** | Имена хостов, пути, версии ПО могут раскрыть инфраструктуру |

### Способы защиты

| Способ | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Аутентификация (scrape)** | Basic Auth / Bearer Token в запросах к `/metrics` | Для сервисов с поддержкой аутентификации |
| **Отдельный порт для `/metrics`** | Эндпоинт метрик на порту, не доступном извне | Для всех приложений |
| **Файерволл** | Ограничение доступа к порту Prometheus (9090) на уровне сети | Обязательно для продакшена |
| **IP Whitelist на уровне приложения** | Приём запросов к `/metrics` только с IP Prometheus | Для критичных сервисов |
| **TLS/HTTPS** | Шифрование трафика между Prometheus и целями | При передаче через ненадёжные сети |
| **Network Policies (Kubernetes)** | Ограничение сетевого доступа между подами | В Kubernetes |

## Practical Scenarios

### Аутентификация в scrape-конфигурации

Prometheus отправляет запросы с заголовками аутентификации к целевым сервисам.

**`prometheus.yml` — Bearer Token:**

```yaml
scrape_configs:
  - job_name: 'secure-app'
    scheme: https
    authorization:
      type: Bearer
      credentials: my-secret-token
```

**`prometheus.yml` — Basic Auth:**

```yaml
scrape_configs:
  - job_name: 'secure-app'
    basic_auth:
      username: prometheus
      password: secret
```

> **Важно:** Токены и пароли хранить в защищённом месте (Vault, secrets manager).

### Отдельный порт для метрик

Эндпоинт `/metrics` на отдельном порту, не выставленном наружу.

**Node.js:**

```javascript
// Основной сервер — порт 3000 (публичный)
app.listen(3000);

// Метрики — порт 9090 (только localhost)
const metricsServer = express();
metricsServer.get('/metrics', (req, res) => {
  res.send(register.metrics());
});
metricsServer.listen(9090, '127.0.0.1');
```

**Go:**

```go
// Основной сервер
go http.ListenAndServe(":8080", mainMux)

// Метрики — только localhost
metricsMux := http.NewServeMux()
metricsMux.Handle("/metrics", promhttp.Handler())
go http.ListenAndServe("127.0.0.1:9091", metricsMux)
```

### Ограничение доступа файерволлом

**`ufw` (Ubuntu):**

```bash
ufw allow from 10.0.0.0/8 to any port 9090
ufw allow from 192.168.1.100 to any port 9090
ufw deny 9090/tcp
```

**`iptables`:**

```bash
iptables -A INPUT -p tcp --dport 9090 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 9090 -j DROP
```

### IP Whitelist на уровне приложения

**Python (Flask):**

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

**`prometheus.yml` — клиентские сертификаты:**

```yaml
scrape_configs:
  - job_name: 'secure-service'
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/ca.crt
      cert_file: /etc/prometheus/client.crt
      key_file: /etc/prometheus/client.key
      insecure_skip_verify: false
```

### Security в Kubernetes

**NetworkPolicy — ограничение доступа к Prometheus:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-access
spec:
  podSelector:
    matchLabels:
      app: prometheus
  policyTypes: [Ingress]
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

> **См. также:** [Prometheus Operator Security](./kubernetes/operator/Security/index.md) — полная настройка безопасности через Operator (аутентификация, TLS, RBAC, Secrets).

## Additional Information

### Best Practices

1. **Не выставляйте Prometheus в интернет** без прокси с аутентификацией.
2. **Используйте отдельные сервис-аккаунты** для scrape в Kubernetes.
3. **Регулярно обновляйте Prometheus** — следите за security advisory.
4. **Минимизируйте данные в метриках** — не включайте PII, секреты, чувствительные пути.
5. **Включите audit logging** — логируйте доступ к API Prometheus.
6. **Используйте RBAC** — ограничьте права доступа к API Prometheus.

### Проверка безопасности

**Сканирование уязвимостей образа:**

```bash
trivy image prom/prometheus:latest
```

**Аудит доступа к API:**

```promql
# Запросы к API Prometheus по эндпоинтам
sum(rate(prometheus_http_requests_total[5m])) by (handler)

# Ошибки аутентификации (401)
sum(rate(prometheus_http_requests_total{code="401"}[5m]))
```
