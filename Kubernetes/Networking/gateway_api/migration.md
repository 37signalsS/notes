# Миграция с Ingress на Gateway API

## Определения

**ingress2gateway** — официальный инструмент CLI для автоматического преобразования манифестов Kubernetes Ingress в ресурсы Gateway API (Gateway и HTTPRoute). Находится в активной разработке и поддерживает наиболее часто используемые аннотации Ingress-NGINX.

**Параллельный запуск (Parallel Run)** — стратегия миграции, при которой Gateway API контроллер разворачивается и работает alongside существующего Ingress-NGINX контроллера до полного переноса трафика.

---

## Практические сценарии

### Шаг 1: Выбор реализации Gateway API

- **Envoy Gateway** — эталонная реализация от создателей стандарта
- **Cilium** — интеграция с CNI, высокая производительность
- **Traefik** — простой в настройке, подходит для небольших кластеров
- **Istio** — для service mesh сценариев
- **NGINX Gateway Fabric** — от создателей Ingress NGINX

**Критерии выбора:**

- Поддержка требуемых функций (L4/L7, TLS, CORS)
- Интеграция с облачным провайдером (AWS ALB, GCP Load Balancer)
- Производительность и масштабируемость
- Сообщество и документация

### Шаг 2: Параллельный запуск

Разверните Gateway API контроллер рядом с существующим Ingress NGINX:

```yaml
# Gateway Class
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: external-lb
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
---
# Gateway
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

**Важно:** Gateway API получит новый внешний IP-адрес. Оба контроллера работают параллельно без конфликтов.

### Шаг 3: Автоматическая конвертация с ingress2gateway

**Установка:**

```bash
# Скачать последнюю версию
curl -Lo ingress2gateway https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/ingress2gateway-linux-amd64
chmod +x ingress2gateway
sudo mv ingress2gateway /usr/local/bin/
```

**Использование:**

```bash
# Конвертация всех Ingress в текущем namespace
ingress2gateway convert --namespace=my-app --output=yaml

# Конвертация с фильтрацией по имени
ingress2gateway convert --ingress-names=my-ingress --output=yaml

# Применение сразу после конвертации
ingress2gateway convert --namespace=my-app | kubectl apply -f -
```

**Результат конвертации:**

Ingress NGINX → Gateway API:

| Ingress NGINX | Gateway API |
| :--- | :--- |
| `Ingress` + `IngressClass` | `GatewayClass` + `Gateway` |
| Правила маршрутизации (`spec.rules`) | `HTTPRoute` |
| Аннотации (`nginx.ingress.kubernetes.io/*`) | Нативные поля (`filters`, `backendRefs`) |
| TLS в Secret | `Gateway.tls.certificateRefs` |
| Redirect через аннотации | `HTTPRoute` с `RequestRedirect` filter |

**Ограничения конвертации:**

- Не все аннотации Ingress NGINX поддерживаются автоматически
- Сложные кастомные правила требуют ручного перевода
- Требуется ручная проверка после конвертации

### Шаг 4: Пример ручной миграции

**Исходный Ingress:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  namespace: my-app
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/rewrite-target: /$1
spec:
  ingressClassName: nginx
  rules:
  - host: "app.example.com"
    http:
      paths:
      - path: /api/(.*)
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 8080
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend-service
            port:
              number: 80
  tls:
  - hosts:
    - app.example.com
    secretName: app-tls-secret
```

**Эквивалент на Gateway API:**

```yaml
# 1. HTTPRoute для маршрутизации
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app-route
  namespace: my-app
spec:
  parentRefs:
  - name: external-gateway
    namespace: infra
  hostnames:
  - "app.example.com"
  rules:
  # Правило для /api/*
  - matches:
    - path:
        type: PathPrefix
        value: /api
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplacePrefixMatch
          replacePrefixMatch: /
    backendRefs:
    - name: api-service
      port:
        number: 8080
  # Правило для /
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: frontend-service
      port:
        number: 80
---
# 2. HTTPRoute для HTTPS redirect
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-to-https
  namespace: my-app
spec:
  parentRefs:
  - name: external-gateway
    namespace: infra
    sectionName: http
  hostnames:
  - "app.example.com"
  rules:
  - filters:
    - type: RequestRedirect
      requestRedirect:
        scheme: https
        statusCode: 301
```

### Шаг 5: Тестирование и перенос трафика

**План тестирования:**

1. **Валидация конфигурации:**

   ```bash
   kubectl get gateway,httproute -A
   kubectl describe gateway external-gateway -n infra
   ```

2. **Проверка маршрутизации:**

   ```bash
   curl -H "Host: app.example.com" http://<GATEWAY_IP>/api/health
   ```

3. **Проверка TLS:**

   ```bash
   curl -v https://app.example.com
   ```

4. **Постепенный перенос трафика:**
   - Начните с non-production окружений
   - Используйте DNS для переключения трафика (canary через весовые коэффициенты)
   - Мониторьте метрики контроллера

**Мониторинг:**

- Метрики Gateway API контроллера (запросы, ошибки, латентность)
- Логи контроллера на предмет ошибок маршрутизации
- Доступность конечных точек (health checks)

---

## Дополнительная информация

### Типичные проблемы при миграции

| Проблема | Решение |
| :--- | :--- |
| Аннотации не конвертировались | Проверить документацию ingress2gateway, перевести вручную на filters |
| TLS не работает | Убедиться, что Secret доступен в namespace Gateway или использовать `certificateRefs` |
| Маршруты не привязываются к Gateway | Проверить `allowedRoutes` в Gateway и `parentRefs` в HTTPRoute |
| Разные namespace для Gateway и Route | Убедиться, что Gateway разрешает routes из других namespace (`from: All`) |

### Временная шкала миграции

| Дата | Событие |
| :--- | :--- |
| **Март 2026** | Официальное прекращение поддержки Ingress NGINX |
| **Q1 2026** | Рекомендуется завершить миграцию в production |
| **Q3 2025** | Начало активной разработки ingress2gateway |
| **2025** | Gateway API v1.0 GA |

### Рекомендации по планированию

1. **Начните миграцию за 6 месяцев** до окончания поддержки Ingress NGINX
2. **Используйте ingress2gateway** как отправную точку, но не как финальное решение
3. **Тестируйте в staging** перед переносом production-трафика
4. **Документируйте кастомные правила** для ручного перевода
5. **Обучите команду** ролевой модели Gateway API

### Инструменты и ресурсы

- **Официальная документация:** [Gateway API Migration Guide](https://gateway-api.sigs.k8s.io/guides/getting-started/migrating-from-ingress-nginx/)
- **Инструмент миграции:** [ingress2gateway GitHub](https://github.com/kubernetes-sigs/gateway-api/tree/main/ingress2gateway)
- **Conformance отчёты:** [Gateway API Implementations](https://gateway-api.sigs.k8s.io/implementations/)
- **Сообщество:** [Kubernetes Slack #gateway-api](https://kubernetes.slack.com/messages/gateway-api)

---

**См. также:**

- [Определения Gateway API](./definitions.md) — концепции и ролевая модель
- [Ресурсы (CRD)](./resources.md) — GatewayClass, Gateway, HTTPRoute
- [Базовые сценарии](./practical_basic.md) — основы создания ресурсов
- [Расширенные функции маршрутизации](./routing_features.md) — Redirect, Rewrite, Traffic Splitting
- [Ingress: Обзор](../Ingress/overview.md) — текущий стандарт и его ограничения
