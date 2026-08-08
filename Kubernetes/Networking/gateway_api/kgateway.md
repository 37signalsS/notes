# KGateway — реализация Gateway API

## Определения

**KGateway** — облачно-ориентированный контроллер Gateway API с открытым исходным кодом, являющийся эволюционным продолжением Gloo Gateway (разработка Solo.io). Проект ориентирован на высоконагруженные среды, мультикластерные конфигурации и специализированные AI-нагрузки.

**AI Gateway** — встроенный функциональный модуль KGateway, превращающий шлюз в интеллектуальный посредник между приложениями и LLM-провайдерами. Он обеспечивает унифицированный интерфейс (OpenAI-compatible), оркестрацию инструментов и управление затратами на токены.

## Базовые концепции

### Архитектура и Data Plane

KGateway v2.3+ предлагает гибридную модель обработки трафика, позволяя выбирать оптимальный Data Plane для конкретных задач:

1.  **Envoy Proxy (C++):** основной промышленный стандарт для традиционного North-South трафика. Используется для сложных L7-правил, WAF, классического Rate Limiting и TLS-терминации.
2.  **AgentGateway (Rust):** высокопроизводительный Data Plane следующего поколения. Благодаря безопасности памяти и минимальному оверхеду Rust, он идеально подходит для:
    *   **A2A (Agent-to-Agent):** сверхбыстрого взаимодействия между автономными ИИ-агентами.
    *   **Edge-развертываний:** работы в условиях ограниченных ресурсов.
    *   **Протокола MCP:** эффективной обработки множества параллельных соединений с серверами инструментов.

### Интеграция с AI и Agentic AI

KGateway (2026) является ключевым звеном в инфраструктуре агентного ИИ:

-   **Федерация MCP (Model Context Protocol):** шлюз выступает как агрегатор, позволяя ИИ-агентам видеть сотни разрозненных MCP-серверов как единый каталог инструментов. Это решает проблему безопасности, так как аутентификация к инструментам централизована на уровне шлюза.
-   **Семантическое кэширование:** KGateway может кэшировать ответы LLM на основе семантической схожести запросов (векторный поиск), что радикально снижает затраты и задержки для повторяющихся вопросов.
-   **AIRateLimit (Token-based):** расширенный механизм лимитирования, учитывающий `Prompt Tokens` и `Completion Tokens`. Позволяет задавать квоты на уровне пользователей, команд или API-ключей.
-   **Prompt Guards и DLP:** на лету проверяет входящие промпты на наличие атак (Prompt Injection) и исходящие ответы на предмет утечки конфиденциальных данных (PII, секреты кода).

## Практические сценарии

### Установка и подготовка окружения

Для развертывания используется OCI-репозиторий. Важно разделять установку CRD и самого контроллера для стабильности в CI/CD пайплайнах.

```bash
# Установка CRD (включая специфичные ресурсы kgateway.dev)
helm upgrade -i kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds \
  --version v2.3.4 \
  --namespace kgateway-system \
  --create-namespace

# Установка Control Plane с поддержкой AI
helm upgrade -i kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway \
  --version v2.3.4 \
  --set aiGateway.enabled=true \
  --namespace kgateway-system
```

### Настройка универсального LLM-эндпоинта

Пример настройки `HTTPRoute`, который перенаправляет запросы к различным моделям в зависимости от заголовков или путей.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-unified-api
  namespace: ai-apps
spec:
  parentRefs:
  - name: main-gateway
    namespace: kgateway-system
  rules:
  - matches:
    - path: { type: PathPrefix, value: /v1/chat }
    filters:
    - type: ExtensionRef
      extensionRef:
        group: ai.kgateway.dev
        kind: LLMRouteFilter
        name: provider-selector
    backendRefs:
    - name: openai-backend
      port: 443
```

### Безопасность: Маскирование данных (Prompt Guard)

```yaml
apiVersion: ai.kgateway.dev/v1alpha1
kind: PromptGuard
metadata:
  name: protect-secrets
spec:
  masking:
    enabled: true
    patterns:
    - name: "credit-cards"
      regex: "\\b(?:\\d[ -]*?){13,16}\\b"
    - name: "api-keys"
      regex: "sk-[a-zA-Z0-9]{32,}"
```

## Дополнительная информация

### Мониторинг и отладка

-   **AI Observability:** KGateway экспортирует специфичные метрики в формате OpenTelemetry: `llm_tokens_total`, `llm_request_latency_milliseconds`, `cache_hit_ratio`.
-   **Трассировка MCP:** визуализация вызовов инструментов агентами через Jaeger позволяет выявить узкие места в логике «агент-инструмент».
-   **Диагностика соединений:** при ошибках взаимодействия с внешними API (например, 429 от OpenAI) KGateway обновляет статус в `HTTPRoute`, указывая `Reason: BackendRateLimited`.

### См. также

-   [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта.
-   [Envoy Gateway](./envoy_gateway.md) — альтернативная реализация на базе Envoy.
-   [L4-маршрутизация — TCPRoute и UDPRoute](./layer4_routing.md) — детали работы на транспортном уровне.
-   [Обзор API Gateway](../../Concepts/api_gateway_overview.md) — сравнение KGateway с Kong и Tyk.

**Родительская тема:** [Gateway API](./definitions.md)
