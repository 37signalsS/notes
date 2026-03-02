# Envoy Gateway

## Envoy Gateway

**Envoy Gateway** — официальная реализация Gateway API от проекта Envoy Proxy. В отличие от Traefik Proxy, Envoy Gateway работает по модели контроллера.

### Архитектура

1. **Envoy Gateway Controller** — под в кластере, который:
   - Отслеживает манифесты Gateway API
   - Создает и управляет отдельными подами Envoy Proxy
   - На каждый `Gateway` создается отдельный экземпляр Envoy Proxy

2. **Envoy Proxy** — отдельные поды, обслуживающие конкретный Gateway:
   - По умолчанию создается Service типа LoadBalancer
   - Автоматически получает Endpoints из Service приложения
   - Может работать напрямую с подами или через Service

### Установка

```bash
helm install eg envoy-gateway/envoy-gateway --version 1.3.1 -n envoy-gateway --create-namespace
```

### Конфигурация EnvoyProxy

`EnvoyProxy` — CRD для динамической конфигурации Envoy Proxy. Позволяет настраивать логирование, телеметрию, провайдеров.

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: EnvoyProxy
metadata:
  name: my-proxy-config
  namespace: gateway-infra
spec:
  provider:
    type: Kubernetes
    kubernetes:
      kind: Service
  logging:
    level:
      default: warning
      proxy-logs:
        upstream: info
```

**Привязка к GatewayClass** — применяется ко всем Gateway:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: ig
spec:
  controllerName: gateway.envoyproxy.io/gateway-class-controller
  parametersRef:
    group: gateway.envoyproxy.io
    kind: EnvoyProxy
    name: my-proxy-config
    namespace: gateway-infra
```

**Привязка к конкретному Gateway** — применяется только к одному Gateway:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: example-gateway
spec:
  gatewayClassName: ig
  # ...
```

### MetalLB интеграция

Для работы LoadBalancer сервисов необходим MetalLB в кластере:

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.218.180-192.168.218.185
```

---

**Parent:** [Gateway API](../gateway_api.md)
