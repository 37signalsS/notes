# Миграция с Ingress на Gateway API

## Определения

**ingress2gateway** — официальный инструмент командной строки (CLI) для автоматизированного преобразования манифестов Kubernetes Ingress в ресурсы Gateway API (Gateway и HTTPRoute).

**Параллельный запуск (Parallel Run)** — стратегия миграции, при которой контроллер Gateway API разворачивается и функционирует параллельно с существующим Ingress-NGINX до завершения полного переноса трафика.

**Контекст миграции:** сообщество Kubernetes прекратило поддержку проекта `kubernetes/ingress-nginx` в марте 2026 года. Gateway API признан официальным преемником для управления входящим трафиком.

## Базовые концепции

### Причины необходимости миграции

- **Окончание поддержки Ingress NGINX:** поддержка прекращена в марте 2026 года.
- **Стандартизация:** Gateway API поддерживается всеми ведущими поставщиками облачных решений и сетевых контроллеров.
- **Расширенные возможности:** нативная поддержка канареечных развертываний, gRPC, а также маршрутизации на уровнях L4 (TCP/UDP) и L7 (HTTP/HTTPS).
- **Ролевая модель:** четкое разделение ответственности между администраторами инфраструктуры и разработчиками приложений.

### Доступные реализации Gateway API

| Реализация | Преимущества | Особенности / Когда выбирать |
| :--- | :--- | :--- |
| **Envoy Gateway** | Нейтральный базовый вариант, чистая связка Gateway API + Envoy | Минимальный набор дополнительных функций |
| **KGateway** | Наследник Gloo Gateway, CNCF Sandbox, высокая производительность | Требуется настройка метрик Prometheus (высокое потребление) |
| **Cilium** | Интеграция с CNI, использование eBPF, высокая скорость | Рекомендуется, если Cilium уже используется в качестве CNI |
| **Traefik** | Зрелый продукт, наличие встроенного веб-интерфейса | Архитектура «все в одном» может быть узким местом при сверхнагрузках |
| **NGINX Gateway Fabric** | Официальное решение от F5, привычный стек NGINX | Меньшее сообщество по сравнению с решениями на базе Envoy |
| **Istio** | Полноценная реализация на базе Envoy | Избыточен, если не требуется функционал Service Mesh |
| **Kong** | Мощная платформа управления API | Сложность настройки, лицензия BSL (не является полностью Open Source) |

### Таблица соответствия ресурсов

| Ingress NGINX | Gateway API |
| :--- | :--- |
| `Ingress` + `IngressClass` | `GatewayClass` + `Gateway` |
| Правила маршрутизации (`spec.rules`) | `HTTPRoute` |
| Аннотации (`nginx.ingress.kubernetes.io/*`) | Нативные фильтры (`filters`) и ссылки на бэкенды (`backendRefs`) |
| TLS с Secret (терминация) | `Gateway.tls.mode: Terminate` + `certificateRefs` |
| SSL Passthrough (аннотация) | `Gateway.tls.mode: Passthrough` + `TLSRoute` |
| Редирект через аннотации | `HTTPRoute` с фильтром `RequestRedirect` |
| Rewrite Target | `HTTPRoute` с фильтром `URLRewrite` |

## Практические сценарии

### Шаг 1: Выбор реализации

Для большинства стандартных задач рекомендуются решения на базе прокси-сервера **Envoy**:

- **Envoy Gateway** — если требуется простой и надежный стандарт.
- **KGateway** — если критична производительность и необходим расширенный функционал в рамках CNCF Sandbox.

Подробности: [Envoy Gateway](./envoy_gateway.md), [Traefik](./traefik.md).

### Шаг 2: Параллельный запуск

Разверните контроллер Gateway API рядом с существующим Ingress NGINX для обеспечения плавного перехода:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: external-lb
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gateway
  namespace: infra
spec:
  gatewayClassName: external-lb
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: All
  - name: https
    protocol: HTTPS
    port: 443
    allowedRoutes:
      namespaces:
        from: All
    tls:
      mode: Terminate
      certificateRefs:
      - name: tls-secret
```

**Примечание:** новый контроллер получит отдельный внешний IP-адрес. Оба решения могут работать одновременно без конфликтов.

### Шаг 3: Автоматическая конвертация с ingress2gateway

Инструмент позволяет преобразовать существующие Ingress-ресурсы в формат Gateway API.

**Установка (v1.0.0):**

```bash
# GitHub (Linux amd64)
curl -Lo ingress2gateway https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/ingress2gateway-linux-amd64
chmod +x ingress2gateway
sudo mv ingress2gateway /usr/local/bin/
```

**Использование:**

```bash
# Конвертация всех Ingress в пространстве имен
ingress2gateway convert --namespace=my-app --output=yaml

# Применение конфигурации напрямую
ingress2gateway convert --namespace=my-app | kubectl apply -f -
```

**Ограничения:** инструмент не всегда корректно обрабатывает сложные специфические аннотации Ingress NGINX, поэтому после конвертации обязательна ручная проверка манифестов.

### Шаг 4: Тестирование и перенос трафика

1. **Проверка статусов (Status Conditions):** убедитесь, что ресурсы находятся в состояниях `Accepted: True` и `Programmed: True` (для Gateway) или `ResolvedRefs: True` (для Route).
2. **Верификация маршрутизации:** выполните тестовые запросы к новому шлюзу.
3. **Поэтапный перенос:** постепенно переключайте трафик на DNS-уровне или через внешний балансировщик (например, 5%, 25%, 100%).

Подробности: [Тестирование и перенос трафика](./migration_testing.md).

### Шаг 5: Миграция TLS и сложной маршрутизации

Для сценариев со сквозным шифрованием (Passthrough) или сложной логикой перезаписи URL используйте специализированные руководства.

Подробности: [Миграция TLS и маршрутизации](./migration_tls_and_routing.md).

## Дополнительная информация

### Решение проблем: cert-manager и Gateway API

При миграции часто возникают сложности с получением сертификатов через шлюз.

- **Проблема 1: поддержка не включена.** В cert-manager поддержка Gateway API часто отключена по умолчанию. При установке через Helm используйте флаг `config.controller.config.enableGatewayAPI: true`.
- **Проблема 2: ACME solver.** Если в ClusterIssuer ранее использовался `ingressClassName: nginx`, cert-manager не сможет пройти проверку владения доменом. Необходимо обновить ClusterIssuer:

  ```yaml
  solvers:
  - http01:
      gatewayHTTPRoute:
        parentRefs:
        - name: my-gateway
          namespace: default
          kind: Gateway
  ```

- **Проблема 3: отсутствие Secret.** Если Gateway ссылается на еще не созданный Secret, слушатель будет помечен как `Invalid`. Убедитесь, что cert-manager успешно создал Secret до активации шлюза.

### Полезные ссылки

- [Официальное руководство по миграции](https://gateway-api.sigs.k8s.io/guides/getting-started/migrating-from-ingress-nginx/)
- [Репозиторий ingress2gateway](https://github.com/kubernetes-sigs/gateway-api/tree/main/ingress2gateway)
- [Соответствие реализаций спецификации](https://gateway-api.sigs.k8s.io/implementations/)

**См. также:**

- [Концепции Gateway API](./definitions.md) — основные понятия
- [Ресурсы Gateway API](./resources.md) — обзор CRD
- [Базовые сценарии](./practical_basic.md) — примеры настройки

**Родительская тема:** [Gateway API](./definitions.md)
