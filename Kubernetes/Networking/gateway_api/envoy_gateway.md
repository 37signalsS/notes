# Envoy Gateway

## Определения

**Envoy Gateway** — официальная реализация Gateway API от проекта Envoy Proxy. Работает по модели контроллера: отслеживает манифесты Gateway API и управляет отдельными подами Envoy Proxy. На каждый `Gateway` создаётся отдельный экземпляр Envoy Proxy.

## Базовые концепции

### Архитектура

**Envoy Gateway Controller** — под в кластере, который отслеживает манифесты Gateway API, создаёт и управляет отдельными подами Envoy Proxy.

**Envoy Proxy** — отдельные поды, обслуживающие конкретный Gateway. По умолчанию создаётся Service типа LoadBalancer. Автоматически получает Endpoints из Service приложения, может работать напрямую с подами или через Service.

### Интеграция с MetalLB

Для работы LoadBalancer-сервисов необходим MetalLB в кластере. Требуется создать `IPAddressPool` с диапазоном адресов для выделения внешних IP.

## Практические сценарии

### Установка Envoy Gateway

Актуальная стабильная версия: v1.7.1 (март 2026).

```bash
helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.7.1 -n envoy-gateway-system --create-namespace
```

### Конфигурация EnvoyProxy

CRD `EnvoyProxy` позволяет настраивать логирование, телеметрию, провайдеров динамически.

Пример конфигурации логирования:

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

Привязка конфигурации ко всем Gateway через `GatewayClass`:

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

Привязка к конкретному Gateway:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: example-gateway
spec:
  gatewayClassName: ig
```

Пример конфигурации MetalLB:

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

## Дополнительная информация

Концепции Gateway API: [Определения](./definitions.md).

Базовые примеры: [Базовые сценарии](./practical_basic.md).

Альтернативная реализация: [Traefik](./traefik.md).

Интеграция с TLS: [cert-manager](../../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md).

Официальная документация: [Envoy Gateway](https://gateway.envoyproxy.io/).

Репозиторий Helm chart: [Artifact Hub](https://artifacthub.io/packages/helm/envoyproxy/gateway).
