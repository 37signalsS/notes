# NGINX Gateway Fabric — реализация Gateway API

## Определения

**NGINX Gateway Fabric (NGF)** — это специализированная реализация спецификации Kubernetes Gateway API от команды F5, предназначенная для работы в распределенных средах (on-premise и ЦОД). Решение построено на базе NGINX (Data Plane) и предоставляет контроллер (Control Plane) для декларативного управления входящим и межсервисным трафиком.

С марта 2026 года, после официального прекращения поддержки (End of Life) проекта `ingress-nginx`, NGINX Gateway Fabric является основным рекомендованным инструментом для пользователей, эксплуатирующих NGINX в Kubernetes и переходящих на стандарт Gateway API.

## Предварительные требования

Перед установкой и настройкой NGINX Gateway Fabric убедитесь, что выполнены следующие условия:

| Компонент | Требование | Проверка |
|:---|:---|:---|
| Kubernetes | Версия 1.25+ | `kubectl version --short` |
| Gateway API CRD | v1.0+ (Standard Channel) | `kubectl get crd gateways.gateway.networking.k8s.io` |
| Helm | Версия 3.12+ | `helm version --short` |
| cert-manager | Для автоматизации TLS (опционально) | `kubectl get pods -n cert-manager` |
| Prometheus | Для сбора метрик (опционально) | `kubectl get servicemonitor -A` |

**Проверка системных требований для Data Plane:**
```bash
# Минимальные ресурсы на узел для NGINX Data Plane
# CPU: 2 ядра
# RAM: 2 ГБ
# Проверка доступных ресурсов
kubectl describe nodes | grep -A 5 "Allocated resources"
```

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

### Сравнение с Ingress-NGINX

| Характеристика | Ingress-NGINX (EOL) | NGINX Gateway Fabric |
|:---|:---|:---|
| **Спецификация** | Ingress API (v1) | Gateway API (v1.x) |
| **Типизация** | Слабая (через аннотации) | Сильная (через CRD и структуры) |
| **Архитектура** | Монолитная (Sidecar/DaemonSet) | Распределенная (CP/DP separation) |
| **Производительность** | Высокая | Очень высокая (оптимизированный путь данных) |
| **Расширяемость** | Lua-скрипты | Нативные политики и фильтры |

## Практические сценарии

### Этап 1: Подготовка среды и установка CRD

Для работы NGF необходимо установить стандартные определения ресурсов Gateway API. В 2026 году актуальной версией является v1.2.x (Standard Channel).

```bash
# Установка Gateway API CRD
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml

# Проверка установки
kubectl get crd gateways.gateway.networking.k8s.io
# → Должен появиться ресурс без ошибок
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

# Проверка установки
kubectl get pods -n nginx-gateway
# → Должны быть Running: ngf-nginx-gateway-fabric-*
kubectl get gatewayclass
# → Должен появиться класс "nginx" с Accepted: True
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

**Валидация:**
```bash
# Применение конфигурации
kubectl apply -f gateway.yaml

# Проверка статуса GatewayClass
kubectl get gatewayclass nginx -o yaml
# → status.conditions[].type=Accepted должно быть True

# Проверка статуса Gateway
kubectl get gateway external-gw -n nginx-gateway -o yaml
# → status.conditions[].type=Programmed должно быть True
# → status.addresses[0].value должен содержать внешний IP
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

**Валидация:**
```bash
# Применение конфигурации
kubectl apply -f httproute.yaml

# Проверка статуса HTTPRoute
kubectl get httproute backend-api -n prod-apps -o yaml
# → status.conditions[].type=Accepted должно быть True
# → status.conditions[].type=ResolvedRefs должно быть True

# Проверка через синтетический запрос
GW_IP=$(kubectl get gateway external-gw -n nginx-gateway -o jsonpath='{.status.addresses[0].value}')
curl -v -H "Host: api.example.com" http://$GW_IP/v2/health
# → Ожидаемый ответ: 200 OK от backend-v2-svc
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

**Валидация:**
```bash
# Применение политики
kubectl apply -f ratelimit.yaml

# Проверка применения политики
kubectl get ratelimitpolicy global-limit -n prod-apps -o yaml
# → status.conditions[].type=Accepted должно быть True

# Тест ограничения скорости (пример с ab или wrk)
ab -n 200 -c 10 -H "Host: api.example.com" http://$GW_IP/v2/health
# → После 100 запросов в секунду должны появиться 429 Too Many Requests
```

### Этап 6: Настройка CORS через CORSPolicy

```yaml
apiVersion: gateway.nginx.org/v1alpha1
kind: CORSPolicy
metadata:
  name: api-cors
  namespace: prod-apps
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: backend-api
  cors:
    allowOrigins:
    - "https://app.example.com"
    - "https://admin.example.com"
    allowMethods:
    - GET
    - POST
    - PUT
    - DELETE
    allowHeaders:
    - "Content-Type"
    - "Authorization"
    maxAge: 86400
```

**Валидация:**
```bash
# Применение политики
kubectl apply -f cors.yaml

# Проверка CORS-заголовков
curl -v -H "Origin: https://app.example.com" \
  -H "Host: api.example.com" \
  -X OPTIONS \
  http://$GW_IP/v2/health
# → Ожидаемые заголовки:
# Access-Control-Allow-Origin: https://app.example.com
# Access-Control-Allow-Methods: GET, POST, PUT, DELETE
# Access-Control-Max-Age: 86400
```

### Этап 7: Зеркалирование трафика (Request Mirroring)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: backend-mirror
  namespace: prod-apps
spec:
  parentRefs:
  - name: external-gw
    namespace: nginx-gateway
  hostnames:
  - "api.example.com"
  rules:
  - matches:
    - path: { type: PathPrefix, value: /v1 }
    backendRefs:
    - name: backend-v1-svc
      port: 8080
    - name: backend-v1-mirror-svc
      port: 8080
      weight: 0  # Зеркалирование без влияния на основной трафик
```

**Валидация:**
```bash
# Применение конфигурации
kubectl apply -f mirror.yaml

# Проверка зеркалирования через логи зеркального сервиса
kubectl logs -n mirror-ns -l app=backend-v1-mirror --tail=50
# → Должны появиться запросы, дублирующие основной трафик
```

## Troubleshooting

### Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| `GatewayClass: Accepted: False` | Контроллер не запущен или не отвечает | Проверить логи контроллера, перезапустить Pod |
| `Gateway: Programmed: False` | Проблема с настройкой Data Plane | Проверить логи Data Plane, доступность портов |
| `HTTPRoute: ResolvedRefs: False` | Отсутствие ReferenceGrant или неверная ссылка на Service | Создать ReferenceGrant или исправить имя Service |
| `HTTPRoute: Accepted: False` | Неверный hostname или конфликт маршрутов | Проверить hostnames, разрешить конфликты |
| 5xx ошибки после установки | Неверная конфигурация бэкенда или фильтров | Проверить логи NGINX, валидность Service |
| Увеличение задержек | Проблемы с сетью или перегрузка Data Plane | Масштабировать Data Plane, проверить сетевые политики |
| TLS-ошибки | Неверный сертификат или отсутствие ReferenceGrant для Secret | Проверить статус Certificate, наличие ReferenceGrant |

### Диагностика проблем

```bash
# Проверка статусов всех ресурсов
kubectl get gateway,httproute -A -o jsonpath='{range .items[*]}{.kind}{"/"}{.metadata.name}{"\t"}{.metadata.namespace}{"\t"}{.status.conditions[0].type}{"\t"}{.status.conditions[0].status}{"\n"}{end}'

# Просмотр событий с ошибками
kubectl get events -A --field-selector reason=ResolvedRefsFailed
kubectl get events -A --field-selector reason=BackendNotFound
kubectl get events -A --field-selector reason=ProgrammedFailed

# Проверка логов контроллера
kubectl logs -n nginx-gateway -l app.kubernetes.io/name=nginx-gateway-fabric --tail=100 | grep -i error

# Проверка конфигурации NGINX
kubectl exec -n nginx-gateway deploy/ngf-nginx-gateway-fabric -- nginx -t
# → Ожидаемый вывод: syntax is ok / test is successful

# Проверка статуса Data Plane
kubectl get pods -n nginx-gateway -l app.kubernetes.io/name=nginx-gateway-fabric
# → Все поды должны быть Running и Ready
```

### Откат изменений

```bash
# Откат установки NGF
helm uninstall ngf -n nginx-gateway

# Удаление CRD (осторожно: удалит все ресурсы Gateway API)
kubectl delete -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml

# Откат конкретного ресурса
kubectl delete httproute backend-api -n prod-apps
```

## Best Practices

### Установка и конфигурация

1. **Используйте отдельный namespace:**
   ```bash
   # Рекомендуется устанавливать NGF в выделенный namespace
   kubectl create namespace nginx-gateway
   ```

2. **Настройте ресурсы для Data Plane:**
   ```yaml
   # values.yaml для Helm
   nginxGatewayFabric:
     resources:
       requests:
         cpu: "500m"
         memory: "512Mi"
       limits:
         cpu: "2000m"
         memory: "2Gi"
   ```

3. **Включите мониторинг:**
   ```yaml
   # values.yaml
   nginxGatewayFabric:
     prometheus:
       enabled: true
       port: 9113
   ```

### Безопасность

1. **Используйте ReferenceGrant для кросс-неймспейс доступа:**
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1beta1
   kind: ReferenceGrant
   metadata:
     name: allow-nginx-access
     namespace: prod-apps
   spec:
     from:
     - group: gateway.networking.k8s.io
       kind: Gateway
       namespace: nginx-gateway
     to:
     - group: ""
       kind: Secret
   ```

2. **Ограничьте доступ к namespace nginx-gateway:**
   ```yaml
   apiVersion: rbac.authorization.k8s.io/v1
   kind: Role
   metadata:
     name: nginx-gateway-reader
     namespace: nginx-gateway
   rules:
   - apiGroups: ["gateway.networking.k8s.io"]
     resources: ["gateways"]
     verbs: ["get", "list", "watch"]
   ```

3. **Настройте NetworkPolicy для защиты Data Plane:**
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: nginx-gateway-policy
     namespace: nginx-gateway
   spec:
     podSelector:
       matchLabels:
         app.kubernetes.io/name: nginx-gateway-fabric
     policyTypes:
     - Ingress
     ingress:
     - from:
       - namespaceSelector:
           matchLabels:
             name: monitoring
       ports:
       - port: 9113
     - from: []  # Разрешить внешний трафик на порты 80/443
       ports:
       - port: 80
       - port: 443
   ```

### Производительность

1. **Масштабирование Data Plane:**
   ```bash
   # Горизонтальное масштабирование
   kubectl scale deployment ngf-nginx-gateway-fabric -n nginx-gateway --replicas=3
   ```

2. **Настройка keep-alive соединений:**
   ```yaml
   # В HTTPRoute можно настроить keep-alive через фильтры
   apiVersion: gateway.networking.k8s.io/v1
   kind: HTTPRoute
   metadata:
     name: backend-api
   spec:
     rules:
     - backendRefs:
       - name: backend-svc
         port: 8080
   ```

3. **Мониторинг ключевых метрик:**
   ```promql
   # Количество запросов в секунду
   sum(rate(nginx_http_requests_total[5m]))
   
   # Ошибки 5xx
   sum(rate(nginx_http_requests_total{status=~"5.."}[5m]))
   
   # Задержки (P95)
   histogram_quantile(0.95, sum(rate(nginx_http_request_duration_seconds_bucket[5m])) by (le))
   ```

### Обслуживание

1. **Обновление NGF:**
   ```bash
   helm repo update
   helm upgrade ngf nginx-stable/nginx-gateway-fabric -n nginx-gateway
   ```

2. **Резервное копирование конфигурации:**
   ```bash
   kubectl get gateway,httproute,gatewayclass -A -o yaml > nginx-gateway-backup.yaml
   ```

3. **Регулярная проверка статусов:**
   ```bash
   # Добавить в cron или систему мониторинга
   kubectl get gateway,httproute -A | grep -v "True"
   # → Должно быть пусто (все ресурсы в состоянии True)
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

**См. также:**

*   **[Gateway API — Определения](./definitions.md)** — концепции и ролевая модель.
*   **[Миграция с Ingress на Gateway API](./migration.md)** — использование инструмента `ingress2gateway`.
*   **[Интеграция с cert-manager](../../../Kubernetes/ToolsUtilities/cert_manager/gateway_api/definitions_and_concepts.md)** — настройка автоматического выпуска сертификатов.
*   **[L4-маршрутизация (TCP/UDP)](./layer4_routing.md)** — работа с транспортным уровнем в NGF.
