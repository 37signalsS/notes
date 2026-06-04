# KGateway (ранее Kitway / Gloo Gateway)

## Определения

**KGateway** — это контроллер Gateway API с открытым исходным кодом на базе Envoy Proxy. Является наследником проекта Gloo Gateway от компании Solo.io и в настоящее время находится в CNCF Sandbox.

**Gateway API First** — философия проекта, при которой Gateway API является основным и единственным способом конфигурации, без промежуточных проприетарных API.

## Базовые концепции

### Архитектура

KGateway разделяет Control Plane и Data Plane:

- **Control Plane:** Следит за ресурсами Gateway API в кластере Kubernetes и генерирует конфигурацию для Envoy.
- **Data Plane (Envoy):** Непосредственно обрабатывает входящий трафик.

### Преимущества

- **Производительность:** Основан на Envoy, показывает отличные результаты при большом количестве маршрутов и динамических обновлениях.
- **Production-ready:** Двухуровневая модель владения (инфраструктура vs приложение).
- **CNCF Sandbox:** Независимый проект с живым сообществом.
- **Нативность:** Полная поддержка всех возможностей Gateway API без костылей и аннотаций.

## Практические сценарии

### Установка

Установка KGateway выполняется через Helm в два этапа:

```bash
# 1. Установка CRD и базовых компонентов
helm install kgateway-crds kgateway/kgateway-crds --namespace kgateway --create-namespace

# 2. Установка Control Plane
helm install kgateway kgateway/kgateway --namespace kgateway
```

### Проверка установки

```bash
kubectl get pods -n kgateway
kubectl get gatewayclass
```

Должен появиться `GatewayClass` с именем `kgateway`.

### Пример использования

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: my-gateway
  namespace: kgateway
spec:
  gatewayClassName: kgateway
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: All
```

## Дополнительная информация

### Нюансы эксплуатации

- **Метрики:** По умолчанию KGateway генерирует большое количество метрик для Prometheus. На крупных инсталляциях это может создать нагрузку на CPU/Memory. Рекомендуется тюнинг конфигурации Observability.
- **Status Conditions:** KGateway активно использует кондишены для обратной связи. Всегда проверяйте `kubectl describe gateway/httproute` при возникновении проблем.

### Полезные ссылки

- [Официальный репозиторий GitHub](https://github.com/kgateway-dev/kgateway)
- [Миграция с Ingress на Gateway API](./migration.md)
- [Сравнение контроллеров](./migration.md#доступные-реализации-gateway-api)
