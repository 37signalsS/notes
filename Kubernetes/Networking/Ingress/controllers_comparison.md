# Ingress-контроллеры — сравнение и выбор

> [!CAUTION]
> **Внимание (2026):** Проект `kubernetes/ingress-nginx` официально перешел в статус **End of Life (EOL)**. Он больше не получает патчей безопасности и не рекомендуется для использования в новых проектах. Рекомендуется миграция на **Gateway API** (Envoy Gateway, Traefik v3, NGINX Gateway Fabric).

## Предварительные требования

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Kubernetes** | 1.25+ | Кластер с поддержкой `networking.k8s.io/v1` и CRD Gateway API. |
| **kubectl** | Совпадает с версией кластера | Управление ресурсами. Проверка: `kubectl version --client --short`. |
| **Helm** | 3.10+ | Рекомендуемый способ установки большинства контроллеров. |
| **CNI** | Зависит от контроллера | Cilium Ingress требует Cilium как CNI. Другие контроллеры совместимы с Calico, Flannel, и др. |
| **cert-manager** | 1.14+ | Автоматический выпуск TLS-сертификатов (опционально, но рекомендуется). |

> **Подробнее:** Общие предварительные требования для Ingress-ресурсов: [Ingress — обзор](./overview.md#предварительные-требования-prerequisites).

---

## Определения

**Ingress-контроллер** — это специализированное приложение (обычно `Deployment` или `DaemonSet`), которое реализует правила маршрутизации, описанные в объектах `Ingress` или `HTTPRoute`. Он отслеживает изменения в API Kubernetes и динамически настраивает нижележащий прокси-сервер (NGINX, Envoy, HAProxy, Traefik).

**Gateway API Controller** — современная реализация контроллера, ориентированная на стандарт Gateway API. В 2026 году большинство решений являются гибридными, поддерживая как классический Ingress (для обратной совместимости), так и Gateway API как основной метод конфигурации.

## Базовые концепции

### Критерии выбора в 2026 году

При выборе контроллера следует ориентироваться на следующие показатели:

1.  **Производительность:** Задержки (latency) и способность обрабатывать высокий RPS.
2.  **Расширяемость (WASM):** Поддержка фильтров WebAssembly для кастомной логики.
3.  **Безопасность (WAF):** Интеграция с Web Application Firewall (Coraza, ModSecurity).
4.  **Автоматизация (DNS/TLS):** Взаимодействие с `cert-manager` и `external-dns`.
5.  **Экосистема:** Поддержка Gateway API и интеграция с Service Mesh.

### Статус технологий (Контекст 2026)

- **Конец эпохи Ingress-NGINX:** Проект `kubernetes/ingress-nginx` официально перешел в статус **End of Life (EOL)** 24 марта 2026 года. Он больше не получает патчей безопасности и не рекомендуется для использования в новых проектах.
- **Gateway API — стандарт:** Большинство современных контроллеров перешли на этот стандарт как на основной. Использование Gateway API позволяет разделить ответственности между администраторами инфраструктуры и разработчиками приложений.

---

## Подробный обзор популярных контроллеров

### Traefik (v3.x)

Современный прокси на Go, ориентированный на автоматизацию и динамические среды.

**Особенности и преимущества:**
- **Zero Configuration:** Автоматическое обнаружение сервисов (Service Discovery) без необходимости ручной правки статических конфигов.
- **Встроенный ACME:** Прямая поддержка Let's Encrypt и ZeroSSL для автоматического получения TLS-сертификатов.
- **Middleware:** Гибкая цепочка обработчиков (BasicAuth, ForwardAuth, RateLimit, CircuitBreaker) через CRD.
- **External-DNS:** Нативная поддержка через аннотации и CRD для синхронизации DNS-записей.
- **WAF:** Поддержка плагинов (например, Coraza WAF) для фильтрации трафика прикладного уровня.

**Недостатки:**
- **Производительность:** В сценариях с экстремально высокими нагрузками (сотни тысяч RPS) может уступать Envoy или HAProxy.
- **WASM:** Отсутствует нативная поддержка (расширение логики возможно только через Go-плагины).

---

### Envoy Gateway

Официальное решение CNCF, призванное стать эталонной реализацией Gateway API на базе Envoy Proxy.

**Особенности и преимущества:**
- **Чистый Gateway API:** Не требует использования вендорских аннотаций; все функции настраиваются через стандартные фильтры.
- **Расширяемость через WASM:** Возможность написания собственных фильтров обработки трафика на любом языке, компилируемом в WebAssembly (C++, Rust, Go).
- **Безопасность:** Встроенная поддержка OIDC, OAuth2 и интеграция с внешними Auth-сервисами.
- **WAF:** Интеграция с Envoy WAF фильтрами и поддержка Coraza для защиты от атак.
- **External-DNS:** Полная совместимость через стандартные ресурсы Gateway и HTTPRoute.

**Недостатки:**
- **Сложность:** Требует глубокого понимания модели Gateway API и архитектуры Envoy для тонкой настройки.

---

### Cilium Ingress / Gateway API

Часть экосистемы Cilium, использующая технологию eBPF для сетевой обработки.

**Особенности и преимущества:**
- **Ускорение eBPF:** Обработка L3/L4 пакетов максимально близко к сетевому интерфейсу, минуя многие слои сетевого стека ядра.
- **Замена kube-proxy:** Обеспечивает более эффективную балансировку нагрузки и работу с сервисами.
- **Наблюдаемость (Hubble):** Полная прозрачность трафика L3-L7: визуализация каждого запроса, его статуса и задержек.
- **Безопасность:** Глубокая связка с `CiliumNetworkPolicy`, позволяющая ограничивать трафик на уровне метаданных Gateway API.
- **WASM:** Поддержка расширений Envoy внутри Cilium для кастомной логики обработки запросов.

**Недостатки:**
- **Инфраструктурные требования:** Необходима установка Cilium как CNI и наличие свежей версии ядра Linux (5.10+).

---

### Istio Ingress Gateway

Стандартный компонент для тех, кто уже использует Service Mesh Istio.

**Особенности и преимущества:**
- **Единая конфигурация:** Использование объектов `Gateway` и `VirtualService` для управления всем входящим трафиком.
- **mTLS:** Автоматическая mTLS-аутентификация между шлюзом и подами внутри меша.
- **Наблюдаемость:** Полная интеграция с Kiali, Jaeger и Prometheus "из коробки".
- **WASM:** Возможность внедрения Envoy-фильтров через `WasmPlugin` для специфической обработки трафика.
- **WAF:** Интеграция с внешними WAF-решениями через ServiceEntry или Envoy-фильтры.

**Недостатки:**
- **Избыточность:** Устанавливать весь стек Istio только ради Ingress-контроллера неоправданно дорого по ресурсам.

---

### Contour

Высокопроизводительный Ingress-контроллер на базе Envoy для динамических сред.

**Особенности и преимущества:**
- **CRD HTTPProxy:** Предлагает расширенную модель конфигурации, позволяющую безопасно делегировать управление путями разным командам (Multi-tenancy).
- **xDS API:** Использует Envoy xDS API для динамической настройки прокси без перезагрузки.
- **External-DNS:** Эффективная работа в связке с external-dns через спецификации HTTPProxy.
- **WASM:** Поддержка расширений Envoy для обработки запросов.

**Недостатки:**
- **Зависимость от CRD:** Основная мощь раскрывается при использовании `HTTPProxy`, что требует изучения специфических ресурсов.

---

### Kong

Контроллер, выросший из мощного API Gateway, ориентированный на управление API.

**Особенности и преимущества:**
- **Экосистема плагинов:** Сотни готовых плагинов для трансформации запросов, логирования, аутентификации (OIDC, JWT) и защиты.
- **API Management:** Продвинутые возможности по управлению квотами, лимитами (Rate Limiting) и монетизации API.
- **WAF:** Мощные плагины для защиты от ботов, SQL-инъекций и интеграции с внешними системами безопасности.
- **External-DNS:** Поддержка через интеграцию с внешними операторами и аннотации.

**Недостатки:**
- **Сложность:** Архитектура Kong (особенно в DB-mode) сложнее в эксплуатации, чем у чистого Ingress-контроллера.
- **Ресурсы:** Потребление памяти может быть значительным при активации большого количества плагинов.

---

### HAProxy Ingress

Решение для тех, кому важна максимальная надежность и производительность балансировщика.

**Особенности и преимущества:**
- **Экстремальная производительность:** HAProxy часто показывает лучшие результаты в тестах на пропускную способность и стабильность под нагрузкой.
- **Гибкие Health Checks:** Очень детальные настройки проверки работоспособности бэкендов.
- **WAF:** Поддержка ModSecurity и фильтрации трафика через SPOE (Stream Processing Offload Engine).
- **External-DNS:** Интеграция через аннотации ресурсов Ingress.

**Недостатки:**
- **Экосистема:** Меньше готовых расширений по сравнению с Envoy-решениями (Traefik, Envoy Gateway).

---

### NGINX Gateway Fabric

Официальный наследник NGINX Ingress от команды F5, разработанный под Gateway API.

**Особенности и преимущества:**
- **Нативная поддержка Gateway API:** Разработан специально под новую спецификацию, избегая нагромождения аннотаций.
- **Производительность NGINX:** Использование всех преимуществ архитектуры NGINX для высокопроизводительной обработки трафика.
- **WAF:** Интеграция с NGINX App Protect (в Enterprise-версии) для защиты приложений.
- **External-DNS:** Поддержка через стандартные механизмы Gateway API.

**Недостатки:**
- **Расширяемость:** Возможности динамического расширения логики (WASM) пока ограничены по сравнению с Envoy.

**Подробное руководство:** **[NGINX Gateway Fabric](../gateway_api/nginx_gateway_fabric.md)** — архитектура, установка и настройка политик.

---

## Сравнительные таблицы

### Технические характеристики

| Контроллер | Прокси | Gateway API | WAF | WASM | DNS / TLS |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Traefik** | Go | Полная (v1+) | Coraza | Нет | Нативная (ACME) |
| **Envoy Gateway**| Envoy (C++) | Нативная | Да | Да | Полная |
| **Cilium** | Envoy/eBPF | Полная | L7 Policy| Да | Полная |
| **Istio** | Envoy (C++) | Полная | Да | Да | Интегрированная |
| **Contour** | Envoy (C++) | Средняя | Частично | Да | Через CRD |
| **Kong** | OpenResty (NGINX+Lua) | Полная | Плагины | Да | Operator |
| **HAProxy** | HAProxy (C) | Полная (GW API v1) | SPOE/ModSec| Да | Аннотации |
| **NGINX Fabric** | NGINX | Нативная | App Protect| Нет | Да |

> **Примечание:** Kong использует **OpenResty** (NGINX + LuaJIT), а не чистый NGINX. HAProxy Ingress поддерживает Gateway API через проект **haproxytech/kubernetes-ingress** с нативной поддержкой `HTTPRoute` и `Gateway`.

---

## Практические сценарии выбора

### Сценарий 1 — Малая команда или стартап

**Рекомендация: Traefik.** Минимум времени на настройку, автоматический SSL через Let's Encrypt и наглядный Dashboard для диагностики.

**Установка через Helm:**

```bash
helm repo add traefik https://traefik.github.io/charts
helm install traefik traefik/traefik \
  --namespace ingress-system --create-namespace \
  --set ingressRoute.dashboard.enabled=true \
  --set ports.websecure.tls.enabled=true
```

**Пример IngressRoute (CRD Traefik):**

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: app-route
  namespace: default
spec:
  entryPoints:
    - websecure
  routes:
  - match: Host(`app.example.com`) && PathPrefix(`/api`)
    kind: Rule
    services:
    - name: app-service
      port: 8080
    middlewares:
    - name: rate-limit
      namespace: default
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: rate-limit
  namespace: default
spec:
  rateLimit:
    average: 100
    burst: 50
```

**Проверка:**

```bash
kubectl get ingressroute -n default
# → NAME         AGE
# → app-route    2m

kubectl port-forward -n ingress-system svc/traefik 8443:443
curl -k https://app.example.com/api --resolve app.example.com:443:127.0.0.1
```

---

### Сценарий 2 — Высоконагруженная среда

**Рекомендация: Envoy Gateway или Cilium.** Минимальные задержки, нативная поддержка Gateway API и глубокая наблюдаемость через eBPF (в случае Cilium).

**Установка Envoy Gateway:**

```bash
helm repo add envoygateway https://envoyproxy.github.io/gateway-helm/
helm install eg-crds envoygateway/gateway-helm-crds \
  --namespace envoy-gateway-system --create-namespace
helm install eg envoygateway/gateway-helm \
  --namespace envoy-gateway-system
```

**Пример Gateway + HTTPRoute:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: envoy-gc
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller

---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: production-gw
  namespace: envoy-gateway-system
spec:
  gatewayClassName: envoy-gc
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: app-tls
        kind: Secret
  allowedRoutes:
    namespaces:
      from: All

---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: default
spec:
  parentRefs:
  - name: production-gw
    namespace: envoy-gateway-system
  hostnames:
  - "api.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /v1
    backendRefs:
    - name: api-v1
      port: 8080
    filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        add:
        - name: X-Request-Source
          value: envoy-gw
```

**Проверка:**

```bash
kubectl get gateway -n envoy-gateway-system
# → NAME             CLASS        ADDRESS        PROGRAMMED   AGE
# → production-gw    envoy-gw     192.168.1.50   True         5m

kubectl get httproute -n default
# → NAME         HOSTNAMES              AGE
# → api-route    ["api.example.com"]    3m
```

---

### Сценарий 3 — Корпоративная платформа и управление API

**Рекомендация: Kong.** Если требуются продвинутые функции по управлению квотами, плагины для трансформации трафика и интеграция с корпоративными IdP.

**Установка Kong Ingress Controller:**

```bash
helm repo add kong https://charts.konghq.com
helm install kong kong/kong \
  --namespace kong --create-namespace \
  --set ingressController.enabled=true \
  --set proxy.type=LoadBalancer
```

**Пример Ingress с плагинами Kong:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kong-api
  namespace: default
  annotations:
    konghq.com/plugins: rate-limiting,key-auth
    konghq.com/strip-path: "true"
spec:
  ingressClassName: kong
  rules:
  - host: api.internal.example.com
    http:
      paths:
      - path: /orders
        pathType: Prefix
        backend:
          service:
            name: orders-service
            port:
              number: 80

---
# Конфигурация плагина Rate Limiting через CRD
apiVersion: configuration.konghq.com/v1
kind: KongPlugin
metadata:
  name: rate-limiting
  namespace: default
config:
  minute: 100
  policy: local
  fault_tolerant: true
plugin: rate-limiting

---
apiVersion: configuration.konghq.com/v1
kind: KongPlugin
metadata:
  name: key-auth
  namespace: default
plugin: key-auth
```

**Проверка:**

```bash
kubectl get ingress -n default
# → NAME         CLASS   HOSTS                      AGE
# → kong-api     kong    api.internal.example.com   2m

# Тест без ключа (ожидается 401)
curl -i http://api.internal.example.com/orders
# → HTTP/1.1 401 Unauthorized
# → {"message":"No API key found in request"}

# Тест с ключом (ожидается 200)
curl -i -H "apikey: test-key-123" http://api.internal.example.com/orders
# → HTTP/1.1 200 OK
```

---

## Алгоритм выбора контроллера

Используйте следующий чек-лист для определения оптимального контроллера:

### Шаг 1 — Определите приоритет

| Приоритет | Рекомендация |
| :--- | :--- |
| Простота настройки и минимальное время до продакшена | **Traefik** |
| Максимальная производительность и минимальная задержка | **Envoy Gateway** или **HAProxy** |
| Управление API (квоты, плагины, трансформации) | **Kong** |
| Единый стек CNI + Ingress + Service Mesh | **Cilium** |
| Уже используете Service Mesh | **Istio Ingress Gateway** |
| Максимальная надежность (health checks, стабильность) | **HAProxy** или **Contour** |
| Минимальный оверхед ресурсов | **NGINX Gateway Fabric** |

### Шаг 2 — Проверьте ограничения

| Ограничение | Контроллеры, которые НЕ подходят |
| :--- | :--- |
| Нет возможности установить Cilium как CNI | Cilium Ingress |
| Нужен Ingress (legacy), а не Gateway API | Traefik, Envoy Gateway, NGINX Gateway Fabric (ограниченно) |
| Мало ресурсов (<512MB RAM на контроллер) | Istio (тяжелый стек), Kong (с плагинами) |
| Нет доступа к BGP-оборудованию | Cilium (для BGP-режима), MetalLB BGP |

### Шаг 3 — Оцените совместимость

```bash
# Проверка версии Kubernetes
kubectl version --short
# → Server Version: v1.29.3

# Проверка наличия Gateway API CRD
kubectl get crd | grep gateway
# → gateways.gateway.networking.k8s.io
# → httproutes.gateway.networking.k8s.io

# Проверка CNI
kubectl get pods -n kube-system -l k8s-app=cilium
# → Если есть поды — Cilium используется как CNI
```

---

## Ресурсные требования

Требования к ресурсам для каждого контроллера (рекомендуемые minimums для production):

| Контроллер | CPU (request) | Memory (request) | CPU (limit) | Memory (limit) | Заметки |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Traefik** | 100m | 128Mi | 500m | 256Mi | Один под; масштабируется горизонтально |
| **Envoy Gateway** | 200m | 256Mi | 1000m | 512Mi | Control Plane + envoy pods (отдельные ресурсы) |
| **Cilium** | 500m | 512Mi | 2000m | 1Gi | Включает CNI — потребляет больше ресурсов |
| **Istio** | 500m | 512Mi | 2000m | 2Gi | Ingress Gateway + Istiod; тяжелый стек |
| **Contour** | 100m | 128Mi | 500m | 256Mi | envoy pods отдельно |
| **Kong** | 250m | 256Mi | 1000m | 512Mi | С плагинами потребление растет |
| **HAProxy** | 100m | 128Mi | 500m | 256Mi | Минимальный оверхед |
| **NGINX Fabric** | 100m | 128Mi | 500m | 256Mi | Классический NGINX |

**Проверка потребления:**

```bash
# Текущее потребление всех контроллеров
kubectl top pods -n ingress-system
# → NAME                        CPU(cores)   MEMORY(bytes)
# → traefik-abc123              15m          48Mi
# → envoy-gateway-xyz           35m          120Mi

# История потребления
kubectl top pods -n ingress-system --sort-by=memory
```

---

## Мониторинг и наблюдаемость

### Общие метрики для всех контроллеров

```bash
# Проверка состояния подов
kubectl get pods -n ingress-system -o wide
# → Готовность: READY 1/1, STATUS Running

# Проверка событий
kubectl get events -n ingress-system --sort-by='.lastTimestamp'
# → Normal  Scheduled  Pod ingress-abc was scheduled to node worker-1
# → Normal  Pulled     Container image pulled successfully
```

### Контроллер-специфичные метрики

| Контроллер | Метрики | Порт | Формат |
| :--- | :--- | :--- | :--- |
| **Traefik** | `traefik_config_reloads_total`, `traefik_entrypoint_open_connections` | 9100 | Prometheus |
| **Envoy Gateway** | Envoy admin interface: `server_state`, `upstream_cx_active` | 19000 | Prometheus |
| **Cilium** | Hubble: `hubble_flows_processed_total`, `hubble_dns_queries_total` | 9965 | Prometheus |
| **Kong** | `kong_nginx_status_active_connections` | 8444 | Prometheus |
| **HAProxy** | `haproxy_backend_active_servers`, `haproxy_frontend_http_requests_total` | 9101 | Prometheus |
| **NGINX Fabric** | `nginx_ingress_controller_nginx_process_connections_active` | 9113 | Prometheus |

**Пример ServiceMonitor для Prometheus:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: traefik-monitor
  namespace: ingress-system
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
  endpoints:
  - port: metrics
    interval: 15s
```

**Пример Grafana-дашборда для Traefik (ID: 17347):**

```bash
# Импорт дашборда через API
curl -X POST http://grafana:3000/api/dashboards/import \
  -H "Content-Type: application/json" \
  -d '{"dashboard":{"id":17347},"overwrite":true}'
```

> **Подробнее:** [Настройка Prometheus для Ingress-контроллеров](./overview.md#мониторинг-ingress-контроллеров) — ServiceMonitor и Grafana-дашборды.

---

## Устранение неполадок

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Pod в статусе `CrashLoopBackOff`** | Ошибка конфигурации, нехватка прав, неверный образ | `kubectl logs <pod> --previous` — проверьте вывод. Убедитесь, что RBAC и ServiceAccount корректны. |
| **Ingress не маршрутизирует трафик** | Неправильный `ingressClassName` или host | `kubectl get ingress <name> -o yaml` — проверьте `spec.ingressClassName` и `spec.rules[].host`. |
| **502 Bad Gateway от контроллера** | Бэкенд-сервис не доступен или Pod не готов | `kubectl get endpoints <service>` — проверьте, что Endpoints не пусты. Проверьте readinessProbe бэкенда. |
| **TLS не работает** | Неверный Secret или неправильная конфигурация TLS | `kubectl get secret <tls-secret> -o yaml` — проверьте наличие `tls.crt` и `tls.key`. Убедитесь, что `spec.tls[].secretName` указан верно. |
| **Контроллер не видит новые Ingress/HTTPRoute** | RBAC не разрешает доступ к нужным ресурсам | Проверьте ClusterRole контроллера: `kubectl describe clusterrole <name>`. Убедитесь, что есть `watch` на `ingresses`, `services`, `endpoints`. |
| **Gateway API: `PROGRAMMED=False`** | Контроллер не может применить конфигурацию Gateway | `kubectl describe gateway <name>` — проверьте Events. Убедитесь, что GatewayClass и controllerName совпадают. |
| **Высокий latency на проксировании** | Узкое место в сетевом стеке (iptables, conntrack) | Включите `hostNetwork` для контроллера. Проверьте `conntrack` лимиты: `sysctl net.netfilter.nf_conntrack_max`. |
| **MetalLB: сервис в статусе `PENDING`** | MetalLB не назначен IP (нет пула или L2Advertisement) | `kubectl describe svc <name>` — проверьте Events. Убедитесь, что IPAddressPool и L2Advertisement настроены в `metallb-system`. |

**Диагностические команды:**

```bash
# Все поды контроллера и их состояние
kubectl get pods -n ingress-system -o wide

# События контроллера (последние 20)
kubectl get events -n ingress-system --sort-by='.lastTimestamp' | tail -20

# Логи контроллера с фильтрацией по ошибкам
kubectl logs -n ingress-system -l app.kubernetes.io/name=traefik | grep -i "error\|fatal"

# Проверка IngressClass
kubectl get ingressclass -o yaml

# Проверка доступности бэкенд-сервиса изнутри контроллера
kubectl exec -n ingress-system <controller-pod> -- curl -s http://<service-name>.<namespace>.svc.cluster.local/healthz
```

---

## Обновление и откат контроллера

### Через Helm (рекомендуется)

```bash
# Обновление через Helm
helm upgrade traefik traefik/traefik \
  --namespace ingress-system \
  --values traefik-values.yaml \
  --atomic

# Проверка после обновления
helm status traefik -n ingress-system
# → STATUS: deployed

# Просмотр истории версий
helm history traefik -n ingress-system
# → REVISION  STATUS     DESCRIPTION
# → 1         superseded Initial install
# → 2         deployed   Upgrade

# Откат к предыдущей версии
helm rollback traefik 1 -n ingress-system
# → Release "traefik" has been rolled back.
```

### Через манифесты (Bare-Metal)

```bash
# Обновление манифестов
kubectl apply -k ./overlays/production

# Проверка изменений
kubectl diff -k ./overlays/production

# Откат: удаление и повторное применение предыдущей версии
git checkout <previous-commit>
kubectl delete -k ./overlays/production
kubectl apply -k ./overlays/production

# Проверка готовности
kubectl rollout status daemonset/traefik -n ingress-system
```

### Безопасное обновление

```bash
# 1. Создайте резервную копию конфигурации
kubectl get ingress -A -o yaml > ingress-backup.yaml
kubectl get httproute -A -o yaml > httproute-backup.yaml

# 2. Обновите контроллер с флагом --atomic (Helm автоматически откатит при ошибке)
helm upgrade traefik traefik/traefik --atomic --timeout 5m

# 3. Проверьте, что все Ingress/HTTPRoute работоспособны
kubectl get ingress -A
kubectl get httproute -A
```

### См. также
- **[Ingress — обзор и основные концепции](./overview.md)** — архитектура, аннотации, мониторинг, устранение неполадок.
- **[Миграция с Ingress на Gateway API](../gateway_api/migration.md)** — пошаговое руководство по переходу с устаревших решений.
- **[Envoy Gateway](../gateway_api/envoy_gateway.md)** — эталонная реализация Gateway API от CNCF.
