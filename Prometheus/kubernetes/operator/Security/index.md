# Безопасность Prometheus Operator

## Определения

**Безопасность Prometheus Operator** — комплекс мер по защите стека мониторинга: аутентификация, TLS, контроль доступа и управление секретами.

---

## Основные концепции

### Компоненты безопасности

Безопасность Prometheus Operator строится на четырёх уровнях:

| Уровень | Механизм | Описание | Документация |
|---|---|---|---|
| **Аутентификация** | Basic Auth, OAuth | Защита веб-интерфейсов Prometheus, Alertmanager, Grafana | [Web Authentication](../Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md) |
| **TLS** | Ingress TLS, mTLS | Шифрование внешнего и внутреннего трафика | Настоящий файл |
| **Контроль доступа** | NetworkPolicy, RBAC | Сетевая изоляция и авторизация Kubernetes API | [access_control.md](./access_control.md) |
| **Управление секретами** | Kubernetes Secrets | Безопасное хранение учётных данных и ключей | [secrets_best_practices.md](./secrets_best_practices.md) |

> **Подробно:** [Web Authentication](../Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md) — полный обзор аутентификации в kube-prometheus-stack.

---

## Практические сценарии

### Аутентификация

Для настройки аутентификации через Ingress (Basic Auth) или встроенных механизмов Grafana используйте специализированное руководство:
> **См. также:** [Web Authentication — Практические сценарии](../Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md#практические-сценарии)

#### Встроенная аутентификация Prometheus (CRD)

В современных версиях (v2.48+) Prometheus поддерживает встроенную аутентификацию, которую можно настроить напрямую через Custom Resource:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  # ...
  web:
    webConfig:
      basicAuth:
        username:
          name: prometheus-auth
          key: username
        password:
          name: prometheus-auth
          key: password
```

**Создание секрета:**

```bash
kubectl create secret generic prometheus-auth \
  --from-literal=username="admin" \
  --from-literal=password="$(openssl rand -base64 20)" \
  -n monitoring
```

---

### TLS

#### Шифрование через Ingress

Для защиты внешнего трафика используйте TLS в ресурсе Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: prometheus
  namespace: monitoring
spec:
  tls:
    - hosts:
        - prometheus.example.com
      secretName: prometheus-tls
  rules:
    - host: prometheus.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: prometheus
                port:
                  number: 9090
```

#### mTLS для внутренних соединений

Prometheus Operator позволяет настраивать mTLS для сбора метрик (scrape) через ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: secure-app
  namespace: production
spec:
  endpoints:
    - port: https
      scheme: https
      tlsConfig:
        caFile: /etc/prometheus/secrets/ca.crt
        certFile: /etc/prometheus/secrets/client.crt
        keyFile: /etc/prometheus/secrets/client.key
        insecureSkipVerify: false
```

---

## Дополнительная информация

> **См. также:**
>
> - [High Availability](../high_availability.md) — отказоустойчивая конфигурация
> - [Prometheus CRD](../crd/prometheus.md) — описание параметров Prometheus Custom Resource
> - [Alertmanager](../../../alertmanager.md) — общая информация об Alertmanager
