#### 4. Развертывание стека LGTM

##### 4.1. Grafana, Prometheus, Alertmanager

Компоненты разворачиваются с помощью чарта [kube-prometheus-stack](../../Prometheus/kubernetes/overview.md), который включает преднастроенные Data Sources для Loki, Tempo и Mimir.

```bash
# Создание Namespace
kubectl create namespace monitoring
kubectl create namespace grafana

# Установка kube-prometheus-stack
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack 
  --namespace monitoring 
  -f - <<EOF
grafana:
  enabled: true
  ingress:
    enabled: true
    hosts:
      - grafana.test
    tls:
      - hosts:
          - grafana.test
        secretName: grafana-tls
    ingressClassName: nginx
  adminPassword: prom-operator
  additionalDataSources:
    - name: Loki
      type: loki
      access: proxy
      url: http://loki.loki:3100
      version: 1
      editable: true
      jsonData:
        derivedFields:
          - datasourceUid: tempo
            matcherRegex: "traceID=(\w+)"
            name: TraceID
            url: '$${__value.raw}'
    - name: Tempo
      type: tempo
      access: proxy
      url: http://tempo.tempo:3200
      version: 1
      editable: true
      jsonData:
        httpHeaderName: "X-Scope-OrgID"
        httpHeaderValue: "tempo"
        serviceMap:
          datasourceUid: prometheus
        tracesToLogs:
          datasourceUid: loki
          filterByTraceID: true
          spanStartTimeShift: 1h
          spanEndTimeShift: 1h
          lokiSearch: true
        tracesToMetrics:
          datasourceUid: prometheus
          tags: "{job="agent-example-app"}"
          map:
            - operationName: "ping"
              spanKind: "server"
              metricQuery: "sum(rate(traces_spanmetrics_latency_bucket{span_kind="server", service_name="agent-example-app", operation="ping", le="$bucket"}[1m])) by (le)"
    - name: Mimir
      type: prometheus
      access: proxy
      url: http://mimir.mimir:8080
      version: 1
      editable: true
EOF

# Добавление записи в /etc/hosts
echo "$(minikube ip) grafana.test" | sudo tee -a /etc/hosts
```

Пароль администратора Grafana (`prom-operator`) можно также получить командой:

```bash
kubectl get secret --namespace monitoring prometheus-grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

##### 4.2. Loki, Tempo и Mimir

Разверните остальные компоненты стека.

```bash
# Установка Loki
helm upgrade --install loki grafana/loki 
  --namespace loki 
  --create-namespace 
  --set service.type=ClusterIP 
  --set service.port=3100 
  --set ingress.enabled=true 
  --set ingress.host=loki.test 
  --set ingress.tls.enabled=true 
  --set ingress.tls.secretName=loki-tls 
  --set ingress.tls.issuerName=minikube-ca 
  --set ingress.tls.issuerKind=ClusterIssuer
# Установка Tempo
helm upgrade --install tempo grafana/tempo 
  --namespace tempo 
  --create-namespace 
  --set service.type=ClusterIP 
  --set service.port=3200

# Установка Mimir (в данном примере не устанавливается, т.к. используется Prometheus из стека)
# Для полноценного использования Mimir его нужно развернуть отдельно.
```