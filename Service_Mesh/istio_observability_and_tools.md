# Наблюдаемость в Istio: Kiali, телеметрия и федерация идентификации

## Определения

**Наблюдаемость (Observability)** в Istio — это совокупность инструментов и практик для глубокого анализа состояния сервисной сетки (Service Mesh), визуализации топологии трафика, мониторинга производительности и распределенной трассировки запросов. В 2026 году наблюдаемость строится на стандартах **OpenTelemetry** и **Gateway API**.

**Kiali** — центральная консоль управления и визуализации для Istio. Она предоставляет графическое представление графа зависимостей сервисов, отслеживает "золотые сигналы" (RPS, ошибки, задержки) и валидирует корректность конфигураций.

**Dex / Keycloak** — провайдеры идентификации (Identity Providers), использующие протокол **OIDC (OpenID Connect)** для организации безопасного ролевого доступа (RBAC) к инструментам мониторинга. Полноценный IAM-сервер на базе Keycloak рассмотрен отдельно: [Keycloak](../Security/Tools/keycloak_overview.md).

---

## Основные концепции

### Стек наблюдаемости 2026 года

Современная архитектура мониторинга Istio (1.30+) интегрируется со стеком **LGTM** (Loki, Grafana, Tempo, Mimir) через универсальный агент **Grafana Alloy**.

| Компонент | Роль | Примечание |
| :--- | :--- | :--- |
| **Prometheus / Mimir** | Сбор и хранение метрик. | Используется Kiali для отображения состояния здоровья (Health) сервисов. |
| **Grafana Tempo** | Распределенная трассировка (Tracing). | Заменяет Jaeger в большинстве современных инсталляций. Хранит данные в S3. |
| **Grafana Loki** | Централизованный сбор логов. | Позволяет Kiali отображать логи Envoy напрямую в интерфейсе. |
| **Grafana Alloy** | Единый коллектор телеметрии. | Заменяет специализированные агенты. Скрапит метрики Envoy с порта `15090/stats/prometheus` (через `istio-proxy`). В Sidecar-модели дополнительно читает объединённые метрики Istio-агента с порта `15020`. |
| **Kiali (v2.28+)** | Визуализация и управление. | Поддерживает Ambient Mesh (Ztunnel/Waypoint), Gateway API, а также вкладку графического графа трафика. Актуальная ветка — 2.28 (июнь 2026). |

### Telemetry API (telemetry.istio.io)

В Istio 1.30+ настройка телеметрии централизована через ресурс **`Telemetry`** (API-группа `telemetry.istio.io/v1`). Он заменяет устаревшие пер-прокси аннотации и `MeshConfig`-фрагменты для метрик, логов и трейсов. Ресурс привязывается к workloads через `selector` или к мешу/неймспейсу как global/default:

| Поле | Назначение |
| :--- | :--- |
| `spec.metrics` | Кастомизация метрик (переопределение тегов, размера гистограмм). |
| `spec.accessLogging` | Включение/отключение access-логов Envoy и выбор провайдера (например, OpenTelemetry). |
| `spec.tracing` | Конфигурация трассировки: провайдер (OTLP/Stackdriver/Zipkin), `randomSamplingPercentage`, пользовательские теги. |

Пример ресурса, включающего access-логи и трассировку через OpenTelemetry для workloads с меткой `app=checkout`:

```yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: checkout-otel
  namespace: checkout
spec:
  selector:
    matchLabels:
      app: checkout
  accessLogging:
  - providers:
    - name: otel
  tracing:
  - providers:
    - name: otel
    randomSamplingPercentage: 100
```

Провайдеры (`otel`, `prometheus` и др.) регистрируются в `istiod` через `meshConfig.extensionProviders` — там задаются endpoint и транспорт (gRPC `4317` / HTTP `4318`). Подробности протокола: [OTLP](../OpenTelemetry/otlp_protocol.md).

### Визуализация трафика в Kiali

Kiali использует цветовую и символьную индикацию для быстрой диагностики:

- **Цвета ребер (Edges):**
  - **Зеленый:** успех (2xx/3xx).
  - **Оранжевый:** предупреждение (ошибки 4xx).
  - **Красный:** критическое состояние (ошибки 5xx > 5%).
- **Типы трафика (Ambient Mesh GA):**
  - **Синие линии:** трафик уровня L4, обрабатываемый **Ztunnel**. Важно: Ztunnel отчитывается о всех соединениях как о **TCP** (даже для HTTP), так как работает на L4.
  - **Зелёные линии:** трафик уровня L7, проходящий через **Waypoint Proxy** и отчитывающийся уже по реальному протоколу (HTTP).
  - **Двойные рёбра:** когда неймспейс находится в Ambient Mesh с включённым Waypoint, Ztunnel и Waypoint формируют раздельные отчёты — в графе появляются двойные рёбра между узлами. Панель инструментов `Traffic` позволяет отфильтровать граф по репортёру (Ztunnel/Waypoint) и протоколам.
  - **HBONE:** в Ambient вместо TCP поды используют защищённый протокол **HBONE** (HTTP-Based Overlay Network Environment) — прозрачно инкапсулируемый Ztunnel.
- **Безопасность:** иконка закрытого замка на линии трафика подтверждает активное **mTLS** соединение с проверкой сертификатов.

---

## Практические сценарии

### Организация безопасного доступа к Kiali через OIDC (Dex)

В промышленной эксплуатации доступ к Kiali должен быть защищен внешним IdP. Сценарий включает публикацию через **Gateway API**.

#### 1. Публикация Kiali через шлюз (Gateway API)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mesh-observability
  namespace: istio-system
spec:
  gatewayClassName: istio
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: kiali-cert}]
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: kiali-route
  namespace: istio-system
spec:
  parentRefs: [{name: mesh-observability}]
  rules:
  - backendRefs:
    - name: kiali
      port: 20001
```

#### 2. Конфигурация Kiali для интеграции с Dex

Настройка выполняется через Helm-чарт или ConfigMap.

```yaml
auth:
  strategy: openid
  openid:
    client_id: kiali-console
    issuer_uri: https://dex.example.com
    username_claim: email
    scopes: ["openid", "profile", "email", "groups"]
```

#### 3. Настройка Dex (статический клиент)

```yaml
staticClients:
- id: kiali-console
  redirectURIs:
  - 'https://kiali.example.com/api/auth/login/oidc/callback'
  name: 'Kiali Istio Console'
  secret: "${KIALI_OIDC_SECRET}"
```

#### 4. PKCE и безопасность токенов

Начиная с Kiali 2.21 (январь 2026) поток **OIDC Authorization Code** полностью поддерживает **PKCE** (Proof Key for Code Exchange) — расширение, защищающее код авторизации от перехвата даже при отсутствии `client_secret`. В Kiali конфигурация PKCE включается флагом `auth.openid.enable_pkce`. Рекомендации:

- В публичных средах (без доверенного `client_secret`) обязательно включайте PKCE.
- Для `client_secret` используйте только секреты и переменные окружения — не храните его в ConfigMap.
- Доступ к Kiali можно дополнительно ограничить через `AuthorizationPolicy` (например, доступ только для пользователей определённой группы из `groups`-claim).

### Диагностика Ambient Mesh через Kiali

В Kiali 2.x доступна вкладка **Ambient**, позволяющая визуализировать:
1.  **Ztunnel Layer:** какие поды охвачены L4-шифрованием.
2.  **Waypoint Proxies:** через какие инстансы проходит L7-маршрутизация.
3.  **Cross-cluster traffic:** отображение потоков между разными кластерами в федеративной сетке.

---

## Дополнительная информация

### Интеграция с Grafana Tempo и TraceQL

В 2026 году Kiali поддерживает глубокую интеграцию с Tempo (включая актуальную ветку **Tempo 3.0** с архитектурой Decoupled Read/Write Path на базе Kafka и хранилищем в S3). При просмотре графа трафика можно кликнуть на ребро и мгновенно перейти к списку трейсов, отфильтрованных по **TraceQL** (например, запросы с задержкой > 500мс).

```bash
# Пример запроса TraceQL, генерируемого Kiali
{ .service.name = "catalog-v1" && .duration > 500ms }
```

Особенности интеграции в 2026:

- **Trace overlay в Kiali (2.26+, май 2026):** при клике на ребро графа Kiali запрашивает Tempo по TraceQL-выражению и накладывает трейсы на граф — видно, через какие сервисы прошёл запрос и где возникла задержка.
- **Traces Drilldown в Grafana:** альтернативный способ работы с трейсами без TraceQL — UI-инструмент для поточечного анализа latency и ошибок; сгенерированные в нём запросы можно дорабатывать вручную.
- Tempo принимает трейсы по **OTLP** (gRPC/HTTP) — в связке с Istio трафик доставляется через Envoy/Ztunnel, а контекст распространяется заголовками **W3C Trace Context** (`traceparent`).

Подробнее об архитектуре Tempo: [Grafana Tempo: распределённая трассировка](../Tempo/index.md).

### Лучшие практики эксплуатации

1.  **Scraping метрик:** используйте **PodMonitor** (Prometheus Operator) с портом `15090` и путём `/stats/prometheus` для Envoy-метрик; для метрик Istio-агента — порт `15020`. В моделях без sidecar (Ambient) метрики собираются напрямую с Ztunnel (`istio_tcp_*`).
2.  **Ресурсные лимиты:** для мешей с количеством сервисов > 500 выделите Kiali не менее 2 CPU и 2GB RAM для эффективной обработки графа топологии. Начиная с Kiali 2.22+ включите health cache (`kiali_health_status`) — для инсталляций с высокой кардинальностью метрик оставляйте его отключённым (opt-in с 2.24).
3.  **Health Validation:** регулярно проверяйте вкладку **Istio Config** в Kiali — она подсвечивает ошибки в Gateway API (например, конфликтующие `HTTPRoute`).
4.  **Распределенная трассировка:** убедитесь, что ваше приложение пробрасывает заголовок `traceparent` (стандарт **W3C Trace Context**, используется по умолчанию) — `b3` (Zipkin) применяется только в legacy-инсталляциях. Иначе меш не сможет связать спаны в единый трейс.
5.  **Ambient-наблюдаемость:** в Ambient используйте L4-метрики Ztunnel (`istio_tcp_connections_opened_total`, `istio_tcp_sent_bytes_total`) для базового мониторинга соединений и телеграммы L7 через Waypoint — HTTP-метрики генерируются только там.

### Актуальность и ссылки

- **Istio 1.30+:** стандарт для современного Service Mesh (Kubernetes 1.32–1.36); телеметрия настраивается через Telemetry API.
- **Kiali 2.28:** основной инструмент визуализации; полная поддержка Ambient Mesh, Gateway API, OIDC PKCE и Trace overlay (2.26+).
- **Открытый стандарт OpenTelemetry:** OTLP — единый протокол для метрик, логов и трейсов; Grafana Alloy — рекомендуемый коллектор в стеке LGTM.

**См. также:**
- [Основные концепции Service Mesh](./service_mesh_concepts.md)
- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Grafana Tempo: распределённая трассировка](../Tempo/index.md)

Документация: [Kiali Official Documentation](https://kiali.io/docs/), [Istio Observability Guide](https://istio.io/latest/docs/tasks/observability/).
