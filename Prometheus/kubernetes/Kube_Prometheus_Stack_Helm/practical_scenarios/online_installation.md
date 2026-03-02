# Онлайн установка

> [Назад к оглавлению](../practical_scenarios.md)

## Шаг 1: Подключение репозитория

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

## Шаг 2: Создание values.yaml (опционально)

При наличии Ingress создаётся файл конфигурации с параметрами доступа:

```yaml
prometheus:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    hosts:
      - prometheus.k8s.domain.local
    paths:
      - /
    pathType: Prefix

grafana:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    hosts:
      - grafana.k8s.domain.local
    path: /
    pathType: Prefix
```

## Шаг 3: Установка

**Без values.yaml:**

```bash
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace
```

**С values.yaml:**

```bash
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f values.yaml
```

## Шаг 4: Доступ к веб-интерфейсам

**Через Ingress:**

- `http://grafana.k8s.domain.local`
- `http://prometheus.k8s.domain.local`

**Через port-forward (без Ingress):**

```bash
# Grafana
kubectl --namespace monitoring port-forward svc/kube-prometheus-grafana 3000:80

# Prometheus
kubectl --namespace monitoring port-forward svc/kube-prometheus-kube-prome-prometheus 9090:9090
```

**Получение пароля Grafana:**

```bash
kubectl -n monitoring get secret kube-prometheus-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Логин: `admin`
