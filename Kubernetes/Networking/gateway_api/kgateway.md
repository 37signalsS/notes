# KGateway — реализация Gateway API

**Надёжность:** 10 (SSoT + Официальная документация v2.3/v3.0)

## Определения

**KGateway** — контроллер Gateway API с открытым исходным кодом, являющийся преемником Gloo Gateway (разработка Solo.io). Проект находится в статусе CNCF Sandbox и позиционируется как современное решение для облачных вычислений и AI-нагрузок.

**AI Gateway** — функциональность KGateway, позволяющая использовать шлюз как единую точку доступа к различным LLM-провайдерам (OpenAI, Anthropic и др.) с встроенными механизмами безопасности и управления трафиком.

## Базовые концепции

### Архитектура (v2.3+)

KGateway разделяет уровни управления и обработки данных, предлагая гибкость в выборе Data Plane:

- **Control Plane:** центральный компонент, который отслеживает ресурсы Gateway API и генерирует конфигурацию для прокси-серверов.
- **Data Plane (Envoy / AgentGateway):** 
    - **Envoy Proxy:** стандартный высокопроизводительный прокси для традиционного L7-трафика.
    - **AgentGateway (Rust):** специализированный Data Plane на базе Rust для высокомасштабируемых коммуникаций между агентами (A2A) и инструментами.

### Возможности AI и Agentic AI

KGateway (2026) включает нативную поддержку современных паттернов:

- **Model Context Protocol (MCP):** поддержка протокола для федерации и мультиплексирования серверов инструментов, что позволяет AI-агентам обращаться к множеству ресурсов через единый endpoint.
- **AI Rate Limiting:** ограничение трафика не только по количеству запросов (RPS), но и по количеству токенов (Tokens Per Minute), что критично для контроля затрат на LLM.
- **Prompt Guards:** автоматическая фильтрация и маскирование чувствительных данных (PII, номера карт) в запросах к языковым моделям.
- **Unified AI Interface:** абстракция над провайдерами LLM, позволяющая менять модель (например, с GPT-4 на Claude 3) без изменения кода приложения.

## Практические сценарии

### Установка через Helm (v2.3+)

Для установки рекомендуется использовать OCI-репозиторий и раздельное развертывание CRD и контроллера.

```bash
# 1. Установка определений ресурсов (CRD)
helm upgrade -i kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds \
  --version v2.3.4 \
  --namespace kgateway-system \
  --create-namespace

# 2. Установка Control Plane
helm upgrade -i kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway \
  --version v2.3.4 \
  --namespace kgateway-system \
  --create-namespace
```

### Проверка работоспособности

```bash
kubectl get pods -n kgateway-system
kubectl get gatewayclass
# → должен появиться класс с именем kgateway
```

### Базовый пример Gateway

Создание стандартного шлюза для обработки HTTP-трафика:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: main-gateway
  namespace: kgateway-system
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

### Настройка AI Rate Limiting (Пример)

Пример использования специфичного фильтра для ограничения токенов:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: ai-route
spec:
  parentRefs:
  - name: main-gateway
  rules:
  - matches:
    - path: { type: PathPrefix, value: /v1/chat/completions }
    filters:
    - type: ExtensionRef
      extensionRef:
        group: kgateway.dev
        kind: AIRateLimit
        name: token-limit-policy
```

## Дополнительная информация

### Нюансы эксплуатации

- **Observability:** детальные метрики Envoy могут создавать высокую нагрузку на Prometheus. В KGateway v2.3+ реализованы фильтры метрик для снижения потребления ресурсов.
- **Status Conditions:** KGateway полностью поддерживает стандартную систему статусов Gateway API. При ошибках конфигурации поле `message` в статусе ресурса содержит детальное описание причины (например, ошибки в LLM-коннекторах).
- **Миграция:** KGateway является рекомендуемым путем миграции для пользователей Gloo Gateway и классического Nginx Ingress, которым требуются продвинутые функции управления трафиком.

**См. также:**

- [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта
- [Envoy Gateway](./envoy_gateway.md) — альтернативная реализация на базе Envoy
- [Traefik](./traefik.md) — реализация с поддержкой классического Ingress и нативной поддержкой v3.x

**Родительская тема:** [Gateway API](./definitions.md)
