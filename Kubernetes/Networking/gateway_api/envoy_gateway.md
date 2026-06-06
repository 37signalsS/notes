# Envoy Gateway — реализация Gateway API

## Определения

**Envoy Gateway** — официальная реализация спецификации Gateway API от сообщества Envoy Proxy. Контроллер управляет жизненным циклом инфраструктуры прокси-серверов, преобразуя высокоуровневые манифесты Kubernetes в низкоуровневую конфигурацию xDS.

**Envoy Gateway Controller** — компонент управляющего слоя (Control Plane), который отслеживает ресурсы Gateway API в кластере и динамически управляет подами прокси-серверов.

**Envoy Proxy** — компонент слоя передачи данных (Data Plane). Для каждого ресурса `Gateway` контроллер развертывает отдельный экземпляр (Deployment) Envoy Proxy, который принимает и маршрутизирует трафик.

## Базовые концепции

### Архитектура разделения слоев
Envoy Gateway строго следует принципу разделения Control Plane и Data Plane:
- **Control Plane (Управляющий слой):** Центральный контроллер. Читает `GatewayClass`, `Gateway`, `HTTPRoute` и формирует конфигурацию. Отвечает за масштабирование и обновление прокси-подов.
- **Data Plane (Слой данных):** Легковесные бинарные прокси Envoy. Они не имеют прямого доступа к API Kubernetes и получают настройки от контроллера по протоколу xDS.

### Agent Gateway (AI/LLM-ориентированный Data Plane)
**Agent Gateway** — это специализированная реализация Data Plane на языке Rust, оптимизированная для работы с искусственным интеллектом (AI) и большими языковыми моделями (LLM).

**Ключевые возможности:**
- **AI Proxying:** Интеллектуальное проксирование запросов к провайдерам моделей (OpenAI, Anthropic, локальные инференс-серверы).
- **Token Management:** Подсчет токенов в реальном времени и ограничение скорости (Rate Limiting) на основе потребления токенов.
- **Кэширование:** Эффективное кэширование ответов моделей для снижения затрат и задержек.
- **Протоколы:** Нативная поддержка Model Context Protocol (MCP) и взаимодействия Agent-to-Agent (A2A).

Для активации Agent Gateway достаточно создать `GatewayClass` с указанием соответствующего контроллера.

### Инфраструктурная интеграция
По умолчанию для каждого шлюза Envoy Gateway создает `Service` типа `LoadBalancer`. В средах bare-metal для назначения IP-адресов требуется наличие установленного **[MetalLB](../metallb.md)**.

## Практические сценарии

### Установка через Helm
Актуальная стабильная версия на середину 2026 года — v1.7.1.

```bash
helm install eg oci://docker.io/envoyproxy/gateway-helm \
  --version v1.7.1 \
  -n envoy-gateway-system \
  --create-namespace
```

### Тонкая настройка через EnvoyProxy (CRD)
Ресурс `EnvoyProxy` позволяет расширять стандартные возможности Gateway API для конкретной реализации.

**Пример настройки уровня логирования:**
```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: EnvoyProxy
metadata:
  name: custom-proxy-config
  namespace: gateway-infra
spec:
  logging:
    level:
      default: warning
      proxy-logs:
        upstream: info
```

### Привязка конфигурации к шлюзу
Конфигурация `EnvoyProxy` привязывается через `GatewayClass`, что позволяет применять настройки ко всем шлюзам данного типа:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: eg-class
spec:
  controllerName: gateway.envoyproxy.io/gateway-class-controller
  parametersRef:
    group: gateway.envoyproxy.io
    kind: EnvoyProxy
    name: custom-proxy-config
    namespace: gateway-infra
```

## Дополнительная информация

**Специфические настройки:**
Для настройки таймаутов, лимитов запросов (Rate Limit) и авторизации (JWT) Envoy Gateway использует механизм Policy Attachment. Подробные примеры конфигураций см. в разделе **[Provider-Specific Configuration](./provider_specific_config.md)**.

**См. также:**
- [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта
- [Базовые сценарии](./practical_basic.md) — примеры настройки маршрутов
- [Traefik](./traefik.md) — альтернативная реализация Gateway API
- [cert-manager](../../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) — автоматизация TLS

**Родительская тема:** [Gateway API](./definitions.md)
