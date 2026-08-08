# Миграция с Ingress на Gateway API

## Определения

**ingress2gateway** — специализированный инструмент командной строки (CLI), предназначенный для автоматизированного преобразования ресурсов `Ingress` (включая специфичные аннотации различных контроллеров) в стандартные объекты Kubernetes Gateway API (`Gateway`, `HTTPRoute`, `TLSRoute`).

**End of Life (EOL) Ingress NGINX** — официальный статус проекта `kubernetes/ingress-nginx`, наступивший в марте 2026 года. С этого момента проект переведён в режим только чтения; критические уязвимости (CVE) не исправляются, и использование контроллера в производственных средах представляет значительный риск для безопасности инфраструктуры.

**ReferenceGrant** — критически важный ресурс Gateway API, который позволяет владельцам ресурсов (например, секретов с TLS-сертификатами) разрешать их использование объектами из других пространств имён. Это заменяет небезопасные механизмы копирования секретов, использовавшиеся в эпоху Ingress.

## Базовые концепции

### Почему миграция обязательна в 2026 году

1.  **Безопасность:** После EOL Ingress NGINX использование Gateway API является единственным способом обеспечить поддержку современных протоколов безопасности и своевременное исправление уязвимостей сетевого стека.
2.  **Ролевая модель:** Gateway API разделяет ответственность между администраторами инфраструктуры (ресурс `Gateway`) и разработчиками приложений (`HTTPRoute`), что невозможно в рамках монолитного ресурса `Ingress`.
3.  **Нативность:** Функции, которые раньше требовали десятков аннотаций (Rewrites, Redirects, Mirroring), теперь являются частью официальной спецификации.
4.  **Унификация:** Единый API для входящего трафика (North-South) и взаимодействия внутри кластера (East-West через спецификацию GAMMA).

### Выбор целевой реализации

При миграции необходимо выбрать контроллер, соответствующий вашим задачам:

| Реализация | Основная специализация | Рекомендуемый сценарий |
| :--- | :--- | :--- |
| **Envoy Gateway** | Производительность и стандарт CNCF | Универсальная замена для большинства задач |
| **KGateway** | AI-инфраструктура и LLM | Проекты с ИИ-агентами, поддержка MCP |
| **Cilium** | eBPF и сетевая безопасность | Максимальная скорость и глубокая фильтрация |
| **Traefik (v3.3+)** | Простота и автоматизация | Динамические среды, быстрая настройка |
| **NGINX Gateway Fabric** | Наследие NGINX | Прямая миграция для тех, кто использует сложные nginx-конфиги |

### Таблица соответствия ресурсов и политик

| Функция в Ingress NGINX | Эквивалент в Gateway API | Метод реализации |
| :--- | :--- | :--- |
| `Ingress` | `HTTPRoute` | Основной ресурс маршрутизации |
| `IngressClass` | `GatewayClass` | Определение типа контроллера |
| `annotations: .../rewrite-target` | `urlRewrite` | Фильтр в `HTTPRoute.rules` |
| `annotations: .../auth-url` | `ExtensionRef` | Ссылка на `AuthenticationPolicy` |
| `annotations: .../enable-cors` | `ExtensionRef` | Ссылка на `CORSPolicy` |
| `tls: hosts/secretName` | `Gateway.listeners.tls` | Терминация на уровне шлюза |

## Практические сценарии

### Шаг 1: Подготовка и автоматизированная конвертация

Инструмент `ingress2gateway` позволяет минимизировать ручной труд, преобразуя до 85% типовых конфигураций.

```bash
# Установка актуальной версии
go install github.com/kubernetes-sigs/ingress2gateway@v1.2.0

# Генерация манифестов Gateway API на основе существующих Ingress
ingress2gateway convert --namespace=prod --output=yaml > gateway-api-manifests.yaml

# Анализ неподдерживаемых аннотаций (требующих ручной миграции)
ingress2gateway convert --summarize
```

### Шаг 2: Настройка безопасности и ReferenceGrant

Самым частым «белым пятном» при миграции является доступ к секретам. Если ваш `Gateway` находится в namespace `gateway-system`, а сертификат — в `app-prod`, необходимо создать разрешение:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: ReferenceGrant
metadata:
  name: allow-cert-access
  namespace: app-prod
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: gateway-system
  to:
  - group: ""
    kind: Secret
    name: site-tls-cert
```

### Шаг 3: Миграция сложных политик (CORS и Auth)

Поскольку CORS и аутентификация не стандартизированы в ядре Gateway API, они реализуются через политики провайдера.

**Пример политики CORS (для Envoy Gateway):**
```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: app-cors
spec:
  cors:
    allowOrigins:
    - "https://trusted.example.com"
    allowMethods: ["GET", "POST"]
```
Затем эта политика привязывается к `HTTPRoute` через `targetRef`.

## Дополнительная информация

### Типовые ошибки при миграции

- **Несоответствие портов:** В Gateway API порт в `parentRef` должен точно соответствовать имени или порту `listener` в ресурсе `Gateway`.
- **Игнорирование статусов:** Gateway API предоставляет богатую диагностику. Всегда проверяйте `kubectl describe httproute <name>` — секция `status` укажет, принят ли маршрут контроллером.
- **Dangling Routes:** Маршруты без `parentRef` или с неверной ссылкой не будут обрабатываться, что приведет к 404.

### См. также

- [Концепции Gateway API](./definitions.md) — базовые определения и ролевая модель.
- [Тестирование и перенос трафика](./migration_testing.md) — детальный разбор стратегий Canary и Blue-Green.
- [Миграция TLS и сложной маршрутизации](./migration_tls_and_routing.md) — глубокое погружение в Rewrites и сертификаты.
- [Envoy Gateway](./envoy_gateway.md) — эталонная реализация для миграции.

**Родительская тема:** [Gateway API](./definitions.md)
