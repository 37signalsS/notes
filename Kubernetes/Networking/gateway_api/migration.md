# Миграция с Ingress на Gateway API

## Определения

**ingress2gateway** — специализированный инструмент командной строки (CLI), предназначенный для автоматизированного преобразования ресурсов `Ingress` (включая специфичные аннотации различных контроллеров) в стандартные объекты Kubernetes Gateway API (`Gateway`, `HTTPRoute`, `TLSRoute`).

**End of Life (EOL) Ingress NGINX** — официальный статус проекта `kubernetes/ingress-nginx`, наступивший в марте 2026 года. С этого момента проект переведён в режим только чтения; критические уязвимости (CVE) не исправляются, и использование контроллера в производственных средах представляет значительный риск для безопасности инфраструктуры.

**ReferenceGrant** — критически важный ресурс Gateway API, который позволяет владельцам ресурсов (например, секретов с TLS-сертификатами) разрешать их использование объектами из других пространств имён. Это заменяет небезопасные механизмы копирования секретов, использовавшиеся в эпоху Ingress.

**Status Conditions** — встроенный в Gateway API механизм обратной связи, позволяющий отслеживать состояние ресурсов через поле `status` в манифестах. Основные условия: `Accepted` (конфигурация синтаксически верна), `Programmed` (шлюз успешно настроен), `ResolvedRefs` (все зависимости найдены и валидны).

## Базовые концепции

### Почему миграция обязательна в 2026 году

1.  **Безопасность:** После EOL Ingress NGINX использование Gateway API является единственным способом обеспечить поддержку современных протоколов безопасности и своевременное исправление уязвимостей сетевого стека.
2.  **Ролевая модель:** Gateway API разделяет ответственность между администраторами инфраструктуры (ресурс `Gateway`) и разработчиками приложений (`HTTPRoute`), что невозможно в рамках монолитного ресурса `Ingress`.
3.  **Нативность:** Функции, которые раньше требовали десятков аннотаций (Rewrites, Redirects, Mirroring), теперь являются частью официальной спецификации.
4.  **Унификация:** Единый API для входящего трафика (North-South) и взаимодействия внутри кластера (East-West через спецификацию GAMMA).

### Предварительные требования

Перед началом миграции убедитесь, что ваш кластер соответствует следующим требованиям:

| Компонент | Минимальная версия | Проверка |
|:---|:---|:---|
| Kubernetes | 1.25+ | `kubectl version --short` |
| Gateway API CRD | v1.0+ | `kubectl get crd gateways.gateway.networking.k8s.io` |
| Контроллер Gateway API | Зависит от реализации | `kubectl get pods -n <controller-namespace>` |

**Проверка установленных CRD:**

```bash
# Проверка наличия основных ресурсов Gateway API
kubectl get crd | grep gateway.networking.k8s.io
# → gateways.gateway.networking.k8s.io
# → httproutes.gateway.networking.k8s.io
# → grpcroutes.gateway.networking.k8s.io
# → tlsroutes.gateway.networking.k8s.io
# → tcproutes.gateway.networking.k8s.io
# → udproutes.gateway.networking.k8s.io
# → referencegrants.gateway.networking.k8s.io
```

**Проверка работы контроллера:**

```bash
# Для Envoy Gateway
kubectl get pods -n envoy-gateway-system
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → envoy-gateway-7c5d8f9b6-abc12                2/2     Running   0          5m

# Для KGateway
kubectl get pods -n kgateway-system
# → NAME                        READY   STATUS    RESTARTS   AGE
# → kgateway-5d4b6c8f9-abc12    2/2     Running   0          5m
```

### Выбор целевой реализации

При миграции необходимо выбрать контроллер, соответствующий вашим задачам:

| Реализация | Основная специализация | Рекомендуемый сценарий |
| :--- | :--- | :--- |
| **Envoy Gateway** | Производительность и стандарт CNCF | Универсальная замена для большинства задач |
| **KGateway** | Расширяемость и богатая экосистема политик | Сложные сценарии маршрутизации, мультитенантность |
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
| `annotations: .../ssl-redirect` | `RequestRedirect` | Фильтр в `HTTPRoute.rules` |
| `annotations: .../proxy-read-timeout` | `BackendTrafficPolicy` | Политика таймаутов бэкенда |
| `annotations: .../whitelist-source-range` | `SecurityPolicy` | Политика фильтрации по IP |
| `canary annotations` | `backendRefs.weight` | Взвешенная маршрутизация в HTTPRoute |

### Аудит текущих Ingress-ресурсов

Перед конвертацией проведите аудит существующих Ingress-ресурсов для выявления неподдерживаемых аннотаций:

```bash
# Список всех Ingress в кластере
kubectl get ingress --all-namespaces

# Выявление Ingress с аннотаями, требующими ручной миграции
kubectl get ingress --all-namespaces -o json | jq '.items[] | select(.metadata.annotations | keys[] | test("nginx.ingress.kubernetes.io")) | {namespace: .metadata.namespace, name: .metadata.name, annotations: .metadata.annotations}'
```

**Аннотации, требующие ручной миграции:**

| Аннотация Ingress NGINX | Причина | Решение |
|:---|:---|:---|
| `nginx.ingress.kubernetes.io/limit-rpm` | Нет прямого аналога | Использовать `RateLimitPolicy` контроллера |
| `nginx.ingress.kubernetes.io/affinity` | Sticky sessions не стандартизированы | Использовать `SessionPersistence` в `BackendTrafficPolicy` |
| `nginx.ingress.kubernetes.io/backend-protocol` | Зависит от реализации | Настроить в `BackendTrafficPolicy` |
| `nginx.ingress.kubernetes.io/configuration-snippet` | Произвольный nginx-конфиг | Переписать на нативные фильтры Gateway API |

## Практические сценарии

### Шаг 1: Подготовка и автоматизированная конвертация

Инструмент `ingress2gateway` позволяет минимизировать ручной труд, преобразуя до 85% типовых конфигураций.

```bash
# Установка актуальной версии
go install github.com/kubernetes-sigs/ingress2gateway@v1.2.0

# Проверка установки
ingress2gateway version
# → ingress2gateway version v1.2.0

# Генерация манифестов Gateway API на основе существующих Ingress
ingress2gateway convert --namespace=prod --output=yaml > gateway-api-manifests.yaml

# Анализ неподдерживаемых аннотаций (требующих ручной миграции)
ingress2gateway convert --summarize
# → Summary:
# →   Converted: 42
# →   Not Converted: 8
# →   Unsupported annotations:
# →     - nginx.ingress.kubernetes.io/limit-rpm (3 resources)
# →     - nginx.ingress.kubernetes.io/affinity (2 resources)
# →     - nginx.ingress.kubernetes.io/configuration-snippet (3 resources)
```

**Валидация сгенерированных манифестов:**

```bash
# Проверка синтаксиса YAML
yamllint gateway-api-manifests.yaml

# Проверка соответствия схеме Kubernetes (без применения)
kubectl apply --dry-run=client -f gateway-api-manifests.yaml
# → gateway.gateway.networking.k8s.io/external-gateway created (dry run)
# → httproute.gateway.networking.k8s.io/api-route created (dry run)

# Проверка с помощью kubeval (если установлен)
kubeval gateway-api-manifests.yaml
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

**Проверка работы ReferenceGrant:**

```bash
# Проверка наличия ReferenceGrant
kubectl get referencegrant -n app-prod
# → NAME               AGE
# → allow-cert-access   2m

# Проверка статуса Gateway (должен быть Programmed: True)
kubectl describe gateway external-gateway -n gateway-system
# → Status:
# →   Conditions:
# →     Type:               Programmed
# →     Status:             True
# →     Type:               Accepted
# →     Status:             True
```

### Шаг 3: Миграция сложных политик (CORS и Auth)

Поскольку CORS и аутентификация не стандартизированы в ядре Gateway API, они реализуются через политики провайдера.

**Пример политики CORS (для Envoy Gateway):**

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: app-cors
  namespace: prod
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: api-route
  cors:
    allowOrigins:
    - exact: "https://trusted.example.com"
    allowMethods:
    - GET
    - POST
    - PUT
    - DELETE
    allowHeaders:
    - Authorization
    - Content-Type
    maxAge: 3600s
```

**Пример политики CORS (для KGateway):**

```yaml
apiVersion: gateway.kgateway.dev/v1alpha1
kind: SecurityPolicy
metadata:
  name: app-cors
  namespace: prod
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: external-gateway
  cors:
    allowOrigins:
    - exact: "https://trusted.example.com"
    allowMethods:
    - GET
    - POST
    allowHeaders:
    - Authorization
    - Content-Type
    maxAge: 3600s
```

### Шаг 4: Применение и валидация

```bash
# Применение манифестов
kubectl apply -f gateway-api-manifests.yaml

# Проверка статуса Gateway
kubectl get gateway -n gateway-system
# → NAME               CLASS         ADDRESS       PROGRAMMED   AGE
# → external-gateway   kgateway      192.168.1.1   True         2m

# Проверка статуса HTTPRoute
kubectl get httproute -n prod
# → NAME           HOSTNAMES               AGE
# → api-route      ["api.example.com"]     2m

# Детальная проверка статусов
kubectl describe httproute api-route -n prod
# → Status:
# →   Parents:
# →     Conditions:
# →       Type:               Accepted
# →       Status:             True
# →       Type:               ResolvedRefs
# →       Status:             True
```

### Шаг 5: Тестирование доступности

```bash
# Получение IP-адреса шлюза
GW_IP=$(kubectl get gateway external-gateway -n gateway-system -o jsonpath='{.status.addresses[0].value}')

# Тест HTTP
curl -v -H "Host: api.example.com" http://$GW_IP/api/health
# → < HTTP/1.1 200 OK
# → < Server: envoy
# → ...

# Тест HTTPS (проверка сертификата)
openssl s_client -connect $GW_IP:443 -servername api.example.com
# → ...
# → Verify return code: 0 (ok)

# Проверка логов контроллера
kubectl logs -n gateway-system -l app.kubernetes.io/name=kgateway -f
```

## Дополнительная информация

### Откат и восстановление

При возникновении критических проблем после миграции можно быстро вернуться к Ingress:

```bash
# 1. Восстановить DNS-запись на старый Ingress-контроллер
# (зависит от вашей DNS-инфраструктуры)

# 2. При необходимости — восстановить удаленные Ingress-ресурсы
kubectl apply -f backup-ingress-manifests.yaml

# 3. Удалить Gateway API ресурсы
kubectl delete -f gateway-api-manifests.yaml

# 4. Проверить работу старой инфраструктуры
kubectl get ingress --all-namespaces
```

**Рекомендации по подготовке отката:**

1. Создайте бэкап всех Ingress-ресурсов перед удалением:
   ```bash
   kubectl get ingress --all-namespaces -o yaml > backup-ingress-manifests.yaml
   ```

2. Не удаляйте старые Ingress-ресурсы до успешного завершения миграции.

3. Подготовьте DNS-инфраструктуру к быстрому переключению (снизьте TTL заранее).

### Типовые ошибки при миграции

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Gateway not programmed` | Контроллер не установлен или не работает | Проверить статус подов контроллера |
| `ResolvedRefs: False` | Отсутствует ReferenceGrant для кросс-namespace ссылок | Создать ReferenceGrant в namespace целевого ресурса |
| `Conflicted: True` | Два HTTPRoute с одинаковым hostname на одном Gateway | Исправить hostnames или использовать разные Gateway |
| `InvalidListener` | Неверная конфигурация listener (порт, протокол) | Проверить спецификацию listener в Gateway |
| `CertificateNotFound` | Secret с сертификатом не найден | Проверить существование Secret и имени в `certificateRefs` |
| `Dangling Routes` | Маршруты без parentRef или с неверной ссылкой | Добавить корректный parentRef на Gateway |
| `Port mismatch` | Порт в parentRef не соответствует listener | Проверить соответствие портов |

**Диагностика проблем:**

```bash
# Проверка логов контроллера
kubectl logs -n gateway-system -l app.kubernetes.io/name=kgateway --tail=100

# Проверка событий ресурса
kubectl describe gateway external-gateway -n gateway-system
kubectl describe httproute api-route -n prod

# Проверка конфигурации Envoy (для KGateway/Envoy Gateway)
kubectl port-forward -n gateway-system svc/kgateway 19000:19000
curl http://localhost:19000/config_dump | jq '.configs[] | select(.["@type"] == "type.googleapis.com/envoy.config.route.v3.RouteConfiguration")'
```

### Best Practices

1.  **Мигрируйте поэтапно:**
    - Начните с одного некритичного сервиса.
    - Проверьте работоспособность перед миграцией остальных.

2.  **Используйте отдельные Gateway для разных окружений:**
    - Создайте отдельные Gateway для production и staging.
    - Применяйте `allowedRoutes` для ограничения доступа к namespace.

3.  **Настройте мониторинг до миграции:**
    - Убедитесь, что Prometheus собирает метрики Gateway API.
    - Настройте алерты на рост 5xx ошибок и латентности.

4.  **Документируйте нестандартные аннотации:**
    - Составьте список всех используемых аннотаций Ingress.
    - Определите эквиваленты в Gateway API для каждой.

5.  **Подготовьте откат:**
    - Сохраните бэкап Ingress-ресурсов.
    - Снизьте TTL DNS-записей за 24 часа до миграции.

6.  **Тестируйте ReferenceGrant:**
    - Проверьте все кросс-namespace ссылки.
    - Убедитесь, что все необходимые ReferenceGrant созданы.

### См. также

- [Концепции Gateway API](./definitions.md) — базовые определения и ролевая модель.
- [Тестирование и перенос трафика](./migration_testing.md) — детальный разбор стратегий Canary и Blue-Green.
- [Миграция TLS и сложной маршрутизации](./migration_tls_and_routing.md) — глубокое погружение в Rewrites и сертификаты.
- [Envoy Gateway](./envoy_gateway.md) — эталонная реализация для миграции.
- [KGateway](./kgateway.md) — реализация с расширенными политиками безопасности.

**Родительская тема:** [Gateway API](./definitions.md)
