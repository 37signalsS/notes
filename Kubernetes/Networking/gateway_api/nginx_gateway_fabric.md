# NGINX Gateway Fabric — реализация Gateway API

## Определения

**NGINX Gateway Fabric (NGF)** — это специализированная cloud-native реализация спецификации Kubernetes Gateway API от команды F5. Решение построено на базе NGINX (Data Plane) и предоставляет контроллер (Control Plane) для декларативного управления входящим и мессервисным трафиком.

С марта 2026 года, после официального прекращения поддержки (End of Life) проекта `ingress-nginx`, NGINX Gateway Fabric является основным рекомендованным инструментом для пользователей, эксплуатирующих NGINX в Kubernetes и переходящих на стандарт Gateway API.

## Базовые концепции

### Архитектура (v2.0+)

NGF использует **распределенную архитектуру**, обеспечивающую разделение функций управления и обработки трафика:

1.  **NGF Control Plane (Контроллер):**
    *   Выполняется как отдельный Pod в кластере.
    *   Отслеживает ресурсы Kubernetes API (GatewayClass, Gateway, HTTPRoute, GRPCRoute, Service, Endpoints).
    *   Транслирует высокоуровневые манифесты Gateway API в низкоуровневую конфигурацию NGINX.
    *   Отправляет конфигурацию в Data Plane по протоколу HTTP (через встроенный API).
2.  **NGF Data Plane (Прокси-серверы):**
    *   Набор подов NGINX, оптимизированных для работы в Kubernetes.
    *   Принимают и применяют конфигурацию от контроллера без перезагрузки процесса (используя динамическую перенастройку).
    *   Выполняют непосредственную балансировку, терминацию TLS и обработку фильтров.

Такой подход позволяет масштабировать пропускную способность (Data Plane) независимо от логики управления (Control Plane).

### Ключевые возможности (2025–2026)

*   **Многопротокольная маршрутизация:** Полная поддержка HTTP, HTTPS, gRPC. Начиная с v2.4 реализована поддержка TCP и UDP через `TCPRoute` и `UDPRoute`.
*   **Безопасность и TLS:**
    *   Интеграция с `cert-manager` для автоматизации жизненного цикла сертификатов.
    *   Поддержка `ReferenceGrant` для безопасного использования секретов и сервисов из других неймспейсов.
*   **Управление трафиком:**
    *   Фильтры модификации заголовков (Add, Set, Remove).
    *   Зеркалирование трафика (Request Mirroring) для тестирования новых версий без влияния на пользователей.
    *   Взвешенная балансировка (Traffic Splitting) для Canary-развертываний.
*   **Декларативные политики:**
    *   `RateLimitPolicy`: Ограничение количества запросов на уровне маршрута или хоста.
    *   `CORSPolicy`: Управление политиками Cross-Origin Resource Sharing.
*   **Наблюдаемость:**
    *   Экспорт метрик в формате Prometheus.
    *   Интеграция с OpenTelemetry для распределенной трассировки запросов.
*   **NGINX Plus (Опционально):** Поддержка коммерческой версии NGINX для расширенного мониторинга, динамической привязки сессий (Session Persistence) и WAF.

## Практические сценарии

### Этап 1: Подготовка среды и установка CRD

Для работы NGF необходимо установить стандартные определения ресурсов Gateway API. В 2026 году актуальной версией является v1.2.x (Standard Channel).

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml
```

### Этап 2: Установка контроллера через Helm

Рекомендуется использовать Helm-чарт для управления жизненным циклом NGF.

```bash
# Добавление официального репозитория
helm repo add nginx-stable https://helm.nginx.com/stable
helm repo update

# Установка с разделением Control Plane и Data Plane
helm install ngf nginx-stable/nginx-gateway-fabric \
  --create-namespace \
  --namespace nginx-gateway \
  --set service.type=LoadBalancer
```

### Этап 3: Создание инфраструктурных ресурсов

Администратор кластера определяет `GatewayClass` (тип реализации) и `Gateway` (физическую точку входа).

```yaml
# Определение реализации контроллера
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: nginx
spec:
  controllerName: "gateway.nginx.org/nginx-gateway-fabric-controller"

---

# Определение шлюза с TLS-терминацией
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gw
  namespace: nginx-gateway
spec:
  gatewayClassName: nginx
  listeners:
  - name: https
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs:
      - name: production-certs
    allowedRoutes:
      namespaces:
        from: All
```

### Этап 4: Настройка прикладной маршрутизации (HTTPRoute)

Разработчики используют `HTTPRoute` для описания логики обработки запросов для своих приложений.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: backend-api
  namespace: prod-apps
spec:
  parentRefs:
  - name: external-gw
    namespace: nginx-gateway
  hostnames:
  - "api.example.com"
  rules:
  - matches:
    - path: { type: PathPrefix, value: /v2 }
    filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        add:
        - name: X-App-Version
          value: "2.0.0"
    backendRefs:
    - name: backend-v2-svc
      port: 8080
```

### Этап 5: Применение политик ограничения скорости (RateLimitPolicy)

NGF позволяет гибко настраивать лимиты через механизм политик.

```yaml
apiVersion: gateway.nginx.org/v1alpha1
kind: RateLimitPolicy
metadata:
  name: global-limit
  namespace: prod-apps
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: backend-api
  rateLimit:
    requestsPerSecond: 100
    burst: 20
```

## Дополнительная информация

### Диагностика и отладка

При возникновении проблем следует проверять состояние ресурсов по цепочке:

1.  **GatewayClass:** Убедитесь, что контроллер признал класс (`Accepted: True`).
2.  **Gateway:** Проверьте статус `Programmed: True` (это означает, что Data Plane успешно настроен).
    ```bash
    kubectl get gateway external-gw -n nginx-gateway -o yaml
    ```
3.  **HTTPRoute:** Проверьте `Accepted: True` и `ParentRefs` (связь со шлюзом).
4.  **Логи контроллера:** Проверьте наличие ошибок трансляции конфигурации.
    ```bash
    kubectl logs -l app.kubernetes.io/name=nginx-gateway-fabric -n nginx-gateway
    ```

### Сравнение с Ingress-NGINX

| Характеристика | Ingress-NGINX (EOL) | NGINX Gateway Fabric |
| :--- | :--- | :--- |
| **Спецификация** | Ingress API (v1) | Gateway API (v1.x) |
| **Типизация** | Слабая (через аннотации) | Сильная (через CRD и структуры) |
| **Архитектура** | Монолитная (Sidecar/DaemonSet) | Распределенная (CP/DP separation) |
| **Производительность** | Высокая | Очень высокая (оптимизированный путь данных) |
| **Расширяемость** | Lua-скрипты | Нативные политики и фильтры |

**См. также:**

*   **[Gateway API — Определения](./definitions.md)** — концепции и ролевая модель.
*   **[Миграция с Ingress на Gateway API](./migration.md)** — использование инструмента `ingress2gateway`.
*   **[Интеграция с cert-manager](../../ToolsUtilities/cert_manager/gateway_api/definitions_and_concepts.md)** — настройка автоматического выпуска сертификатов.
*   **[L4-маршрутизация (TCP/UDP)](./layer4_routing.md)** — работа с транспортным уровнем в NGF.
