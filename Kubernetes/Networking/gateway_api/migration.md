# Миграция с Ingress на Gateway API

**Надёжность:** 10 (SSoT + Официальные данные Kubernetes SIG Network 2026)

## Определения

**ingress2gateway** — основной инструмент командной строки (CLI) для автоматизированного преобразования ресурсов Ingress (включая аннотации NGINX) в стандартные объекты Gateway API (Gateway и HTTPRoute).

**End of Life (EOL) Ingress NGINX** — статус проекта `kubernetes/ingress-nginx`, наступивший 24 марта 2026 года. С этой даты выпуск обновлений безопасности и исправлений CVE прекращён; использование в продуктовых средах настоятельно не рекомендуется.

**ListenerSet** — ресурс Gateway API (v1.5+), позволяющий делегировать управление TLS-сертификатами и хостами командам приложений в режиме самообслуживания.

## Базовые концепции

### Причины миграции в 2026 году

- **Безопасность:** Отсутствие паттернов для `ingress-nginx` делает кластеры уязвимыми.
- **Стандартизация:** Gateway API стал общепринятым стандартом L7-маршрутизации, поддерживаемым всеми облачными провайдерами и современными контроллерами (Envoy Gateway, Traefik, Cilium).
- **Продвинутая маршрутизация:** Нативная поддержка gRPC, WebSocket и L4 (TCP/UDP) без сложных аннотаций.
- **Устранение дублирования секретов:** Механизм `ReferenceGrant` позволяет шлюзу безопасно использовать TLS-секреты из пространства имен приложения, исключая необходимость в инструментах вроде `reflector`.

### Доступные реализации Gateway API

| Реализация | Преимущества | Особенности |
| :--- | :--- | :--- |
| **Envoy Gateway** | Стандарт CNCF, высокая производительность | Оптимален для большинства сред |
| **KGateway** | AI-функционал (MCP, Rate Limiting по токенам) | Наследник Gloo Gateway, идеален для LLM-нагрузок |
| **Cilium** | eBPF-маршрутизация, интеграция с CNI | Максимальная производительность на уровне ядра |
| **Traefik (v3.1+)** | Нативная поддержка Gateway API v1.1+ | Удобный UI и привычный стек для пользователей Traefik |
| **NGINX Gateway Fabric** | Официальная замена Ingress-NGINX от F5 | Сохраняет логику NGINX, но на базе нового стандарта |

### Таблица соответствия ресурсов

| Ingress NGINX (Legacy) | Gateway API (Standard) |
| :--- | :--- |
| `Ingress` + `IngressClass` | `GatewayClass` + `Gateway` |
| `spec.rules` | `HTTPRoute` |
| Аннотации Rewrites | `URLRewrite` (фильтр в HTTPRoute) |
| Аннотации Redirects | `RequestRedirect` (фильтр в HTTPRoute) |
| CORS / Rate Limit | `ExtensionRef` (ссылка на Middleware/Policy) |
| TLS Termination | `Gateway.listeners.tls.mode: Terminate` |

## Практические сценарии

### Шаг 1: Автоматизированная конвертация (ingress2gateway v1.2.0)

Инструмент `ingress2gateway` поддерживает более 30 популярных аннотаций NGINX.

**Установка:**
```bash
go install github.com/kubernetes-sigs/ingress2gateway@v1.2.0
```

**Применение:**
```bash
# Конвертация с выводом в файл для проверки
ingress2gateway convert --namespace=prod-app --output=yaml > migration-plan.yaml

# Просмотр неподдерживаемых аннотаций
ingress2gateway convert --namespace=prod-app --summarize
```

### Шаг 2: Реализация ReferenceGrant для TLS

Вместо копирования секретов из namespace приложения в namespace шлюза, используйте `ReferenceGrant`:

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-gateway-tls
  namespace: app-namespace
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: gateway-system
  to:
  - group: ""
    kind: Secret
    name: app-cert-tls
```

### Шаг 3: Настройка cert-manager (v1.20+)

В 2026 году cert-manager требует явного включения поддержки Gateway API.

**Включение в Helm:**
```yaml
config:
  enableGatewayAPI: true
```

**Обновление ClusterIssuer для HTTP-01:**
```yaml
solvers:
- http01:
    gatewayHTTPRoute:
      parentRefs:
      - name: main-gateway
        namespace: gateway-system
```

### Шаг 4: Поэтапный перенос трафика (Canary)

1. **Создание параллельного шлюза:** Разверните `Gateway`, который получит новый внешний IP.
2. **Верификация:** Проверьте доступность через новый IP с помощью `curl -H "Host: app.com"`.
3. **DNS-переключение:** Используйте веса в DNS (например, AWS Route53) для постепенного перенаправления:
   - 10% на Gateway API IP.
   - 90% на старый Ingress IP.
4. **Завершение:** После достижения 100% удалите старые Ingress-ресурсы и контроллер NGINX.

## Дополнительная информация

### Нюансы эксплуатации

- **Статусы (Status Conditions):** Основной инструмент диагностики. Если `HTTPRoute` не работает, проверьте `status.parents[].conditions`. Типичная ошибка — отсутствие `ReferenceGrant` для бэкенда в другом namespace.
- **Дублирование хостов:** В отличие от Ingress, Gateway API строго контролирует уникальность хостов. Конфликтующие маршруты будут отклонены со статусом `Conflicted`.

**См. также:**

- [Концепции Gateway API](./definitions.md) — базовые определения
- [Тестирование миграции](./migration_testing.md) — детализация Шага 4
- [Envoy Gateway](./envoy_gateway.md) — рекомендуемая реализация для миграции

**Родительская тема:** [Gateway API](./definitions.md)
