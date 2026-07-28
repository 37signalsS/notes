# Наблюдаемость в Istio: Kiali, телеметрия и федерация идентификации

## Определения

**Наблюдаемость (Observability)** в Istio — это совокупность инструментов и практик для глубокого анализа состояния сервисной сетки (Service Mesh), визуализации топологии трафика, мониторинга производительности и распределенной трассировки запросов. В 2026 году наблюдаемость строится на стандартах **OpenTelemetry** и **Gateway API**.

**Kiali** — центральная консоль управления и визуализации для Istio. Она предоставляет графическое представление графа зависимостей сервисов, отслеживает "золотые сигналы" (RPS, ошибки, задержки) и валидирует корректность конфигураций.

**Dex / Keycloak** — провайдеры идентификации (Identity Providers), использующие протокол **OIDC (OpenID Connect)** для организации безопасного ролевого доступа (RBAC) к инструментам мониторинга.

---

## Основные концепции

### Стек наблюдаемости 2026 года

Современная архитектура мониторинга Istio (1.30+) интегрируется со стеком **LGTM** (Loki, Grafana, Tempo, Mimir) через универсальный агент **Grafana Alloy**.

| Компонент | Роль | Примечание |
| :--- | :--- | :--- |
| **Prometheus / Mimir** | Сбор и хранение метрик. | Используется Kiali для отображения состояния здоровья (Health) сервисов. |
| **Grafana Tempo** | Распределенная трассировка (Tracing). | Заменяет Jaeger в большинстве современных инсталляций. Хранит данные в S3. |
| **Grafana Loki** | Централизованный сбор логов. | Позволяет Kiali отображать логи Envoy напрямую в интерфейсе. |
| **Grafana Alloy** | Единый коллектор телеметрии. | Заменяет специализированные агенты, собирает данные с портов `15020/stats`. |
| **Kiali (v2.x)** | Визуализация и управление. | Поддерживает Ambient Mesh и Gateway API "из коробки". |

### Визуализация трафика в Kiali

Kiali использует цветовую и символьную индикацию для быстрой диагностики:

- **Цвета ребер (Edges):**
  - **Зеленый:** успех (2xx/3xx).
  - **Оранжевый:** предупреждение (ошибки 4xx).
  - **Красный:** критическое состояние (ошибки 5xx > 5%).
- **Типы трафика (Ambient Mesh GA):**
  - **Синие линии:** трафик уровня L4, обрабатываемый **Ztunnel**.
  - **Зеленые линии:** трафик уровня L7, проходящий через **Waypoint Proxy**.
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

### Диагностика Ambient Mesh через Kiali

В Kiali 2.x доступна вкладка **Ambient**, позволяющая визуализировать:
1.  **Ztunnel Layer:** какие поды охвачены L4-шифрованием.
2.  **Waypoint Proxies:** через какие инстансы проходит L7-маршрутизация.
3.  **Cross-cluster traffic:** отображение потоков между разными кластерами в федеративной сетке.

---

## Дополнительная информация

### Интеграция с Grafana Tempo и TraceQL

В 2026 году Kiali поддерживает глубокую интеграцию с Tempo. При просмотре графа трафика можно кликнуть на ребро и мгновенно перейти к списку трейсов, отфильтрованных по **TraceQL** (например, запросы с задержкой > 500мс).

```bash
# Пример запроса TraceQL, генерируемого Kiali
{ .service.name = "catalog-v1" && .duration > 500ms }
```

### Лучшие практики эксплуатации

1.  **Scraping метрик:** используйте **PodMonitor** (Prometheus Operator) для автоматического обнаружения sidecar-контейнеров по порту 15020.
2.  **Ресурсные лимиты:** для мешей с количеством сервисов > 500 выделите Kiali не менее 2 CPU и 2GB RAM для эффективной обработки графа топологии.
3.  **Health Validation:** регулярно проверяйте вкладку **Istio Config** в Kiali — она подсвечивает ошибки в Gateway API (например, конфликтующие `HTTPRoute`).
4.  **Распределенная трассировка:** убедитесь, что ваше приложение пробрасывает заголовки `b3` или `traceparent` (стандарт W3C), иначе меш не сможет связать спаны в единый трейс.

### Актуальность и ссылки

- **Istio 1.30+:** стандарт для современного Service Mesh.
- **Kiali 2.x:** основной инструмент визуализации.
- **Gateway API (GAMMA):** первичный способ описания маршрутов в Kiali.

**См. также:**
- [Основные концепции Service Mesh](./service_mesh_concepts.md)
- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Графический интерфейс Grafana](../Grafana/grafana_overview.md)
- [Обзор Grafana Tempo](../Tempo/index.md)

Документация: [Kiali Official Documentation](https://kiali.io/docs/), [Istio Observability Guide](https://istio.io/latest/docs/tasks/observability/).
