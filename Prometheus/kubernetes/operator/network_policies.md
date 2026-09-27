# Сетевые политики (Network Policies) для мониторинга

## Определения

**Network Policies для Prometheus Operator** — набор правил сетевой изоляции (L3/L4), определяющих, какие поды могут взаимодействовать с компонентами мониторинга (Prometheus, Alertmanager, Operator, Grafana). По умолчанию Kubernetes разрешает весь трафик; NetworkPolicy реализует режим «запрещено по умолчанию» (default-deny).

**Ingress** — входящий трафик к подам мониторинга (доступ к Prometheus UI, отправка алертов в Alertmanager, webhook-вызовы API-сервера к Operator).

**Egress** — исходящий трафик от подов мониторинга (скрейпинг целей, DNS-резолвинг, remote_write в LTS, отправка уведомлений через webhook).

**DNS Egress** — обязательное разрешение на доступ к CoreDNS (порт 53 UDP/TCP в namespace `kube-system`). Без этого Service Discovery не работает, имена сервисов не резолвятся.

> **Смотрите также:** [Контроль доступа](./Security/access_control.md) — RBAC и Admission Webhooks; [Высокая доступность](./high_availability.md) — Gossip-трафик Alertmanager.

---

## Базовые концепции

### Критические порты

| Компонент | Порт | Протокол | Направление | Назначение |
|:---|:---|:---|:---|:---|
| Prometheus | 9090 | TCP | Ingress | Web UI, API, Grafana |
| Prometheus | 9090 | TCP | Egress | Скрейпинг целей |
| Alertmanager | 9093 | TCP | Ingress | API, получение алертов от Prometheus |
| Alertmanager | 9094 | TCP/UDP | Ingress/Egress | Gossip (HA кластер) |
| Operator | 9080 | TCP | Ingress | Metrics endpoint |
| Operator | 9443 | TCP | Ingress | Admission Webhook (API-сервер) |
| Grafana | 3000 | TCP | Ingress | Web UI |
| Thanos Sidecar | 10901 | TCP | Ingress/Ecess | gRPC (Store, Query) |
| CoreDNS | 53 | UDP/TCP | Egress | DNS-резолвинг |

### Принцип «.default-deny + явные исключения»

Сначала заблокируйте ВСЁ, затем разрешите только необходимое:

```yaml
# Шаг 1: Блокировать весь трафик в namespace monitoring
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

> **Важно:** После применения этой политики поды в `monitoring` не смогут ни скрейпить цели, ни резолвить DNS, ни отправлять алерты. Добавляйте исключения ПОСЛЕ default-deny.

---

## Практические сценарии

### Полный набор Network Policies для production

#### 1. Prometheus: Ingress (доступ к UI/API)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-ingress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Ingress
  ingress:
    # Доступ из Grafana
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: grafana
      ports:
        - port: 9090
          protocol: TCP
    # Доступ из namespace engineering (port-forward)
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: engineering
      ports:
        - port: 9090
          protocol: TCP
    # Доступ от Alertmanager (для API checks)
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - port: 9090
          protocol: TCP
```

#### 2. Prometheus: Egress (скрейпинг + DNS)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Egress
  egress:
    # DNS (обязательно)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Скрейпинг целей (все namespace)
    - to:
        - namespaceSelector: {}
      ports:
        - port: 9090
          protocol: TCP
        - port: 8080
          protocol: TCP
        - port: 9100
          protocol: TCP
        - port: 80
          protocol: TCP
        - port: 443
          protocol: TCP
    # Отправка алертов в Alertmanager
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - port: 9093
          protocol: TCP
    # Remote Write в LTS (VictoriaMetrics/Mimir)
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: victoria-metrics
      ports:
        - port: 8428
          protocol: TCP
    # Thanos Sidecar gRPC
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: thanos-query
      ports:
        - port: 10901
          protocol: TCP
```

#### 3. Alertmanager: Ingress + Gossip

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: alertmanager-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: alertmanager
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Получение алертов от Prometheus
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9093
          protocol: TCP
    # Gossip между репликами
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - port: 9094
          protocol: TCP
        - port: 9094
          protocol: UDP
  egress:
    # DNS
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Gossip между репликами
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - port: 9094
          protocol: TCP
        - port: 9094
          protocol: UDP
    # Webhook-отправка (Slack, PagerDuty, etc.)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 443
          protocol: TCP
        - port: 587
          protocol: TCP  # SMTP
```

#### 4. Operator: Admission Webhook

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: operator-webhook-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus-operator
  policyTypes:
    - Ingress
  ingress:
    # Доступ от API-сервера для валидации
    - from:
        - ipBlock:
            cidr: 10.0.0.0/8  # CIDR мастер-нод
      ports:
        - port: 9443
          protocol: TCP
    # Metrics для саммониторинга
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 8080
          protocol: TCP
```

#### 5. Grafana: Ingress + Egress к Prometheus

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: grafana-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: grafana
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Доступ из engineering namespace
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: engineering
      ports:
        - port: 3000
          protocol: TCP
  egress:
    # DNS
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
    # Запросы к Prometheus
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9090
          protocol: TCP
```

#### 6. Доступ из приложений (app namespaces → Prometheus scrape)

Для скрейпинга метрик из произвольных namespace:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-scrape-from-apps
  namespace: app-production
spec:
  podSelector:
    matchLabels:
      app: my-app
  policyTypes:
    - Ingress
  ingress:
    # Разрешить входящий трафик от Prometheus на порт метрик
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
          podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 8080
          protocol: TCP
        - port: 9090
          protocol: TCP
```

### Диагностика NetworkPolicy

```bash
# 1. Проверка применяемых политик
kubectl get networkpolicy -n monitoring
kubectl describe networkpolicy prometheus-egress -n monitoring

# 2. Проверка связности из пода Prometheus
kubectl exec -n monitoring prometheus-main-0 -- \
  curl -v --connect-timeout 3 http://alertmanager-operated:9093/api/v2/alerts

# 3. Проверка DNS из пода
kubectl exec -n monitoring prometheus-main-0 -- nslookup kubernetes.default
kubectl exec -n monitoring prometheus-main-0 -- cat /etc/resolv.conf

# 4. Проверка доступности порта целей
kubectl exec -n monitoring prometheus-main-0 -- \
  curl -s -o /dev/null -w "%{http_code}" http://my-app.app-production:8080/metrics

# 5. Если Cilium: проверка DROP через Hubble
hubble observe --namespace monitoring --type drop

# 6. Проверка что Egress к DNS работает
kubectl exec -n monitoring prometheus-main-0 -- \
  wget -qO- --timeout=5 http://kubernetes.default.svc.cluster.local/version
```

### Типичные ошибки

| Симптом | Причина | Решение |
|:---|:---|:---|
| Все цели в `down` | Отсутствует Egress DNS | Добавьте egress на порт 53 к kube-dns |
| Alertmanager: cluster not ready | Порт 9094 заблокирован | Разрешите TCP+UDP 9094 между репликами |
| Operator webhook timeout | Порт 9443 заблокирован | Разрешите ingress от CIDR мастер-нод |
| Grafana: datasource not working | Egress к Prometheus заблокирован | Разрешите egress на порт 9090 |
| Remote Write: dropped samples | Egress к LTS заблокирован | Разрешите egress на порт 8428/9009 |

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [Контроль доступа](./Security/access_control.md) | RBAC, Admission Webhooks, TLS |
| [Безопасность (index)](./Security/index.md) | Defense in Depth, Threat Model |
| [Высокая доступность](./high_availability.md) | Gossip-протокол Alertmanager (порт 9094) |
| [NetworkPolicy: Обзор](../../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md) | Глубокое погружение в NetworkPolicy |

### Частые ошибки на собеседованиях

1. **"NetworkPolicy работает по умолчанию"** — Нет. В Kubernetes разрешен ВСЕЙ трафик по умолчанию. NetworkPolicy включает режим «запрещено по умолчанию» ТОЛЬКО для подов, попадающих под `podSelector`.
2. **"Egress не нужен для мониторинга"** — Нет. Без egress на DNS Service Discovery не работает. Без egress на порт метрик Prometheus не может скрейпить цели.
3. **"Gossip Alertmanager работает по TCP"** — Нужен И TCP, И UDP на порту 9094.
