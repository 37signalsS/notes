# Envoy Gateway — реализация Gateway API

**Надёжность:** 10 (SSoT + Официальная документация v1.8 / AI Gateway v1.0)

## Определения

**Envoy Gateway (EG)** — официальная реализация спецификации Kubernetes Gateway API от сообщества Envoy Proxy. EG управляет жизненным циклом инфраструктуры прокси-серверов, преобразуя высокоуровневые манифесты в конфигурацию xDS для Data Plane.

**Envoy AI Gateway (v1.0+)** — расширение на базе Envoy Gateway, специально разработанное для управления трафиком генеративного ИИ. Обеспечивает унифицированный API для множества LLM-провайдеров и поддержку агентных протоколов.

**Data Plane** — уровень передачи данных. В 2026 году Envoy Gateway поддерживает классический **Envoy Proxy (C++)** для стандартных задач и **Agent Gateway (Rust)** для высоконагруженных агентных систем (A2A).

## Базовые концепции

### Архитектура и управление

Envoy Gateway строго разделяет уровни управления и обработки:

- **Control Plane:** Центральный контроллер, отвечающий за мониторинг ресурсов Gateway API, генерацию xDS-конфигурации и управление жизненным циклом подов прокси.
- **Data Plane:** Группа прокси-серверов (Envoy), которые получают конфигурацию динамически. Начиная с v1.8, поддерживается "теневой режим" (Shadow Mode) для проверки политик Rate Limit и Security без блокировки реального трафика.

### Возможности AI Gateway (v1.0 GA)

Envoy AI Gateway предоставляет критический функционал для современных AI-приложений:

- **Universal LLM API:** Единый эндпоинт, совместимый с OpenAI, который транслирует запросы к 16+ провайдерам (OpenAI, Anthropic, Gemini, DeepSeek и др.).
- **Поддержка MCP (Model Context Protocol):** Выступает в роли агрегатора для MCP-серверов, предоставляя AI-агентам единый интерфейс доступа к инструментам.
- **Управление затратами:** Переход от простого подсчёта токенов к управлению бюджетом (dollar-based cost control) и "умной" маршрутизации на основе доступных квот.
- **Мультимодальность:** Нативная поддержка эндпоинтов для генерации аудио, изображений и работы с OpenAI Responses API.

### Интеграция и безопасность

- **SecurityPolicy:** Позволяет настраивать JWT (до 16 провайдеров), CORS, и OIDC.
- **ClientTrafficPolicy:** Управление параметрами TLS-клиента, HTTP/2, HTTP/3 и специфичными настройками gRPC-Web.
- **BackendTrafficPolicy:** Тонкая настройка взаимодействия с бэкендами (таймауты, ретрии, алгоритмы балансировки).

## Практические сценарии

### Установка через Helm (v1.8)

В версии 1.8 CRD вынесены в отдельный sub-chart для обхода ограничений Helm на размер секретов.

```bash
# Добавление репозитория
helm repo add envoygateway https://envoyproxy.github.io/gateway-helm/
helm repo update

# Установка (актуально на июль 2026)
helm install eg envoygateway/gateway-helm \
  --version v1.8.0 \
  -n envoy-gateway-system \
  --create-namespace
```

### Пример настройки AI Gateway (v1.0)

Настройка шлюза для маршрутизации запросов к OpenAI и Anthropic через единый интерфейс:

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: ai-security-policy
spec:
  jwt:
    providers:
    - name: auth0
      issuer: https://auth.example.com/
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-route
spec:
  parentRefs:
  - name: ai-gateway
  rules:
  - matches:
    - path: { type: PathPrefix, value: /v1/chat/completions }
    filters:
    - type: ExtensionRef
      extensionRef:
        group: gateway.envoyproxy.io
        kind: AIFilter
        name: multi-llm-router
```

## Дополнительная информация

### Сравнение Data Plane решений

| Характеристика | Envoy Proxy (C++) | Agent Gateway (Rust) |
| :--- | :--- | :--- |
| **Основной кейс** | Стандартный L7 трафик | Высокоскоростной A2A (Agent-to-Agent) |
| **Экосистема** | CNCF / Kubernetes | Linux Foundation (Agentic AI) |
| **Производительность** | Высокая (General Purpose) | Экстремальная (для долгоживущих связей) |

**См. также:**

- [Концепции Gateway API](./definitions.md) — базовые определения
- [KGateway](./kgateway.md) — альтернативная реализация с поддержкой AI
- [Traefik](./traefik.md) — реализация с нативной поддержкой v3.x
- [Ресурсы (CRD)](./resources.md) — обзор стандартных объектов Gateway API

**Родительская тема:** [Gateway API](./definitions.md)
