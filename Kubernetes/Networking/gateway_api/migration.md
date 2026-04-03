# Миграция с Ingress на Gateway API

## Определения

**ingress2gateway** — официальный инструмент CLI для автоматического преобразования манифестов Kubernetes Ingress в ресурсы Gateway API (Gateway и HTTPRoute). Версия 1.0 выпущена в марте 2026.

**Параллельный запуск (Parallel Run)** — стратегия миграции, при которой Gateway API-контроллер разворачивается и работает параллельно с существующим Ingress-NGINX до полного переноса трафика.

**Контекст миграции:** Сообщество Kubernetes прекратило поддержку `kubernetes/ingress-nginx` в марте 2026. Gateway API является официальным преемником.

## Базовые концепции

### Почему миграция необходима

- **Окончание поддержки Ingress NGINX** — март 2026
- **Стандартизация** — Gateway API поддерживается всеми крупными вендорами
- **Расширенные функции** — канареечные развертывания, gRPC, TCP/UDP-маршрутизация
- **Ролевая модель** — разделение ответственности между инфраструктурой и разработчиками

### Доступные реализации Gateway API

| Реализация | Описание |
| :--- | :--- |
| **Envoy Gateway** | Эталонная реализация от создателей стандарта |
| **Cilium** | Интеграция с CNI, высокая производительность |
| **Traefik** | Простой в настройке, подходит для небольших кластеров |
| **Istio** | Для service mesh-сценариев |
| **NGINX Gateway Fabric** | От создателей Ingress NGINX |

### Таблица соответствия ресурсов

| Ingress NGINX | Gateway API |
| :--- | :--- |
| `Ingress` + `IngressClass` | `GatewayClass` + `Gateway` |
| Правила маршрутизации (`spec.rules`) | `HTTPRoute` |
| Аннотации (`nginx.ingress.kubernetes.io/*`) | Нативные поля (`filters`, `backendRefs`) |
| TLS с Secret (termination) | `Gateway.tls.mode: Terminate` + `certificateRefs` |
| SSL Passthrough (аннотация) | `Gateway.tls.mode: Passthrough` + `TLSRoute` |
| Redirect через аннотации | `HTTPRoute` с `RequestRedirect` filter |

## Практические сценарии

### Шаг 1: Выбор реализации

Критерии выбора:
- Поддержка требуемых функций (L4/L7, TLS, CORS)
- Интеграция с облачным провайдером (AWS ALB, GCP Load Balancer)
- Производительность и масштабируемость
- Сообщество и документация

Подробнее: [Envoy Gateway](./envoy_gateway.md), [Traefik](./traefik.md).

### Шаг 2: Параллельный запуск

Разверните Gateway API-контроллер рядом с существующим Ingress NGINX:

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

**Важно:** Gateway API получит новый внешний IP-адрес. Оба контроллера работают параллельно без конфликтов.

### Шаг 3: Автоматическая конвертация с ingress2gateway

**Установка (версия 1.0.0):**

```bash
# GitHub (Linux amd64)
curl -Lo ingress2gateway https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/ingress2gateway-linux-amd64
chmod +x ingress2gateway
sudo mv ingress2gateway /usr/local/bin/

# Homebrew (macOS/Linux)
brew install ingress2gateway

# Go
go install github.com/kubernetes-sigs/ingress2gateway@v1.0.0
```

**Использование:**

```bash
# Конвертация всех Ingress в namespace
ingress2gateway convert --namespace=my-app --output=yaml

# Конвертация с фильтрацией по имени
ingress2gateway convert --ingress-names=my-ingress --output=yaml

# Применение сразу после конвертации
ingress2gateway convert --namespace=my-app | kubectl apply -f -
```

**Ограничения конвертации:**
- Не все аннотации Ingress NGINX поддерживаются автоматически
- Сложные кастомные правила требуют ручного перевода
- Требуется ручная проверка после конвертации

### Шаг 4: Тестирование и перенос трафика

1. **Проверка маршрутизации:** Убедитесь, что Gateway и HTTPRoute корректно работают.
2. **Мониторинг:** Настройте метрики Gateway API-контроллера (запросы, ошибки, латентность).
3. **Поэтапный перенос:** Переносите приложения по одному, начиная с non-production.
4. **Откат:** Сохраняйте Ingress NGINX до полного завершения миграции.

Подробнее: [Тестирование и перенос трафика](./migration_testing.md).

### Шаг 5: Миграция TLS и сложной маршрутизации

Для сложных сценариев (TLS Passthrough, канареечные развертывания, A/B-тестирование) требуется ручная конвертация.

Подробнее: [Миграция TLS и маршрутизации](./migration_tls_and_routing.md).

## Дополнительная информация

**Временная шкала:**

| Дата | Событие |
| :--- | :--- |
| **Март 2026** | Официальное прекращение поддержки Ingress NGINX |
| **Q1 2026** | Рекомендуется завершить миграцию в production |
| **2025** | Gateway API v1.0 GA |

**Рекомендации по планированию:**
- Начните миграцию за 6 месяцев до окончания поддержки Ingress NGINX
- Используйте ingress2gateway как отправную точку, но не как финальное решение
- Тестируйте в staging перед переносом production-трафика
- Документируйте кастомные правила для ручного перевода
- Обучите команду ролевой модели Gateway API

**Официальные ресурсы:**
- Документация: [Gateway API Migration Guide](https://gateway-api.sigs.k8s.io/guides/getting-started/migrating-from-ingress-nginx/)
- Инструмент: [ingress2gateway GitHub](https://github.com/kubernetes-sigs/gateway-api/tree/main/ingress2gateway)
- Conformance-отчёты: [Gateway API Implementations](https://gateway-api.sigs.k8s.io/implementations/)

### Troubleshooting: cert-manager + Gateway API

При миграции с Ingress NGINX на Gateway API распространённая проблема — cert-manager не видит Gateway-ресурсы и не получает сертификаты.

**Проблема 1: cert-manager не видит Gateway API**

При установке cert-manager через манифесты (не Helm) Gateway API support может быть отключён по умолчанию.

**Решение:**
- При установке через Helm указать `config.controller.config.enableGatewayAPI: true`
- Или добавить `--enable-gateway-api` в аргументы контейнера контроллера
- Начиная с Kubernetes 1.31+ Gateway API CRD включены в стандартный установочный пакет cert-manager

**Проблема 2: ACME solver не проходит через Gateway**

Если в ClusterIssuer указан `ingressClassName: nginx`, cert-manager пытается создать Ingress-ресурс для HTTP-01 challenge. При использовании Gateway API это не работает.

**Решение:** В ClusterIssuer использовать `gatewayHTTPRoute` вместо `ingress`:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        gatewayHTTPRoute:
          parentRefs:
          - name: my-gateway
            namespace: default
            kind: Gateway
```

**Проблема 3: Listener помечен как Invalid — Secret не существует**

При создании Gateway с TLS- listener и ссылкой на несуществующий Secret, listener переходит в статус `Invalid`.

**Решение:** Убедиться, что cert-manager успел создать Secret до того, как Gateway начнёт обработку. Аннотация `cert-manager.io/cluster-issuer` на Gateway должна быть корректной. Проверить статус через `kubectl describe gateway <name>`.

**Связанные документы:**
- Концепции Gateway API: [Определения](./definitions.md)
- Ресурсы (CRD): [Ресурсы](./resources.md)
- Базовые примеры: [Базовые сценарии](./practical_basic.md)
- Расширенная маршрутизация: [Расширенные функции](./routing_features.md)
- Обзор Ingress: [Ingress: Обзор](../Ingress/overview.md)
