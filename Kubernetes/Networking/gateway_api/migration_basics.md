# Миграция с Ingress на Gateway API: основы

## Определения

**ingress2gateway** — официальный инструмент CLI для автоматического преобразования манифестов Kubernetes Ingress в ресурсы Gateway API (Gateway и HTTPRoute). Находится в активной разработке и поддерживает наиболее часто используемые аннотации Ingress-NGINX.

**Параллельный запуск (Parallel Run)** — стратегия миграции, при которой Gateway API контроллер разворачивается и работает alongside существующего Ingress-NGINX контроллера до полного переноса трафика.

---

## Шаг 1: Выбор реализации Gateway API

### Доступные реализации

| Реализация | Описание |
| :--- | :--- |
| **Envoy Gateway** | Эталонная реализация от создателей стандарта |
| **Cilium** | Интеграция с CNI, высокая производительность |
| **Traefik** | Простой в настройке, подходит для небольших кластеров |
| **Istio** | Для service mesh сценариев |
| **NGINX Gateway Fabric** | От создателей Ingress NGINX |

### Критерии выбора

- Поддержка требуемых функций (L4/L7, TLS, CORS)
- Интеграция с облачным провайдером (AWS ALB, GCP Load Balancer)
- Производительность и масштабируемость
- Сообщество и документация

---

## Шаг 2: Параллельный запуск

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

---

## Шаг 3: Автоматическая конвертация с ingress2gateway

### Установка

```bash
# Скачать последнюю версию
curl -Lo ingress2gateway https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/ingress2gateway-linux-amd64
chmod +x ingress2gateway
sudo mv ingress2gateway /usr/local/bin/
```

### Использование

```bash
# Конвертация всех Ingress в текущем namespace
ingress2gateway convert --namespace=my-app --output=yaml

# Конвертация с фильтрацией по имени
ingress2gateway convert --ingress-names=my-ingress --output=yaml

# Применение сразу после конвертации
ingress2gateway convert --namespace=my-app | kubectl apply -f -
```

### Таблица соответствия

| Ingress NGINX | Gateway API |
| :--- | :--- |
| `Ingress` + `IngressClass` | `GatewayClass` + `Gateway` |
| Правила маршрутизации (`spec.rules`) | `HTTPRoute` |
| Аннотации (`nginx.ingress.kubernetes.io/*`) | Нативные поля (`filters`, `backendRefs`) |
| TLS с Secret (termination) | `Gateway.tls.mode: Terminate` + `certificateRefs` |
| SSL Passthrough (аннотация) | `Gateway.tls.mode: Passthrough` + `TLSRoute` |
| Redirect через аннотации | `HTTPRoute` с `RequestRedirect` filter |

### Ограничения конвертации

- Не все аннотации Ingress NGINX поддерживаются автоматически
- Сложные кастомные правила требуют ручного перевода
- Требуется ручная проверка после конвертации

---

## Временная шкала миграции

| Дата | Событие |
| :--- | :--- |
| **Март 2026** | Официальное прекращение поддержки Ingress NGINX |
| **Q1 2026** | Рекомендуется завершить миграцию в production |
| **Q3 2025** | Начало активной разработки ingress2gateway |
| **2025** | Gateway API v1.0 GA |

---

## Рекомендации по планированию

1. **Начните миграцию за 6 месяцев** до окончания поддержки Ingress NGINX
2. **Используйте ingress2gateway** как отправную точку, но не как финальное решение
3. **Тестируйте в staging** перед переносом production-трафика
4. **Документируйте кастомные правила** для ручного перевода
5. **Обучите команду** ролевой модели Gateway API

---

## Инструменты и ресурсы

- **Официальная документация:** [Gateway API Migration Guide](https://gateway-api.sigs.k8s.io/guides/getting-started/migrating-from-ingress-nginx/)
- **Инструмент миграции:** [ingress2gateway GitHub](https://github.com/kubernetes-sigs/gateway-api/tree/main/ingress2gateway)
- **Conformance отчёты:** [Gateway API Implementations](https://gateway-api.sigs.k8s.io/implementations/)
- **Сообщество:** [Kubernetes Slack #gateway-api](https://kubernetes.slack.com/messages/gateway-api)

---

## Связанные документы

- **[Определения Gateway API](./definitions.md)** — концепции и ролевая модель
- **[Ресурсы (CRD)](./resources.md)** — GatewayClass, Gateway, HTTPRoute
- **[Базовые сценарии](./practical_basic.md)** — основы создания ресурсов
- **[Расширенные функции маршрутизации](./routing_features.md)** — Redirect, Rewrite, Traffic Splitting
- **[Ingress: Обзор](../Ingress/overview.md)** — текущий стандарт и его ограничения
