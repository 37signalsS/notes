# NetworkPolicy + Service: Паттерны Сетевой Изоляции

## Определения

**NetworkPolicy + Service Integration** — комплексный подход к управлению сетевым трафиком,.combine декларативные правила сетевой изоляции (NetworkPolicy) с абстракцией сервисов (Service) для реализации Zero Trust архитектуры в Kubernetes.

**Zero Trust в контексте Service** — модель безопасности, при которой каждый Service по умолчанию изолирован, а доступ предоставляется явно через NetworkPolicy на основе селекторов подов, namespace и CIDR.

---

## Основные концепции

### Как NetworkPolicy взаимодействует с Service

NetworkPolicy работает на уровне подов, а не сервисов. Однако Service определяет, какие поды получают трафик, поэтому понимание их взаимодействия критично:

1. **Service направляет трафик** на поды через EndpointSlice
2. **NetworkPolicy фильтрует трафик** на уровне пода (ingress/egress)
3. **Оба механизма работают независимо** — Service без NetworkPolicy доступен всем, NetworkPolicy без Service не имеет точек входа

**Важно:** NetworkPolicy не работает с ExternalName Service (трафик идет напрямую на внешний IP) и не фильтрует трафик на уровне NodePort (требуется CNI с поддержкой preDNAT, например Calico).

### Три уровня фильтрации

| Уровень | Механизм | Что фильтрует |
| :--- | :--- | :--- |
| **L3/L4 (IP/Port)** | NetworkPolicy | Трафик между подами по IP и портам |
| **L4 (Service)** | kube-proxy (iptables/nftables/IPVS) | Балансировка трафика между эндпоинтами |
| **L7 (HTTP/gRPC)** | Service Mesh (Istio/Linkerd) | Маршрутизация по путям, заголовкам, методам |

---

## Практические сценарии

### Паттерн 1: Default Deny + Allow Specific Service

Базовый паттерн Zero Trust: запретить весь трафик, затем разрешить только необходимые сервисы.

```yaml
# Шаг 1: Default Deny для всех подов в namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
# Шаг 2: Разрешить трафик только к Service backend от frontend
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: frontend
      ports:
        - port: 8080
          protocol: TCP
```

**Результат:** Frontend может обращаться к backend:8080, но backend полностью изолирован от всех других подов.

### Паттерн 2: Разрешение трафика к конкретному Service по портам

Контроль доступа к Service на уровне портов.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-db-access
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: api-server
      ports:
        - port: 5432
          protocol: TCP
    - from:
        - podSelector:
            matchLabels:
              app: backup-worker
      ports:
        - port: 5432
          protocol: TCP
```

**Результат:** К PostgreSQL (Service: postgres) имеют доступ только api-server и backup-worker на порту 5432.

### Паттерн 3: Egress Control для Service

Ограничение исходящего трафика от Service.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-egress
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Egress
  egress:
    # Разрешить DNS
    - ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Разрешить доступ к PostgreSQL Service
    - to:
        - podSelector:
            matchLabels:
              app: postgres
      ports:
        - port: 5432
          protocol: TCP
    # Разрешить доступ к внешнему API
    - to:
        - ipBlock:
            cidr: 203.0.113.0/24
      ports:
        - port: 443
          protocol: TCP
```

### Паттерн 4: Multi-namespace Service Access

Разрешение доступа к Service из других namespace.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-cross-namespace
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: shared-api
  policyTypes:
    - Ingress
  ingress:
    - from:
        # Разрешить из namespace staging
        - namespaceSelector:
            matchLabels:
              name: staging
          podSelector:
            matchLabels:
              app: test-client
        # Разрешить из namespace monitoring
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - port: 9090
          protocol: TCP
```

### Паттерн 5: Ограничение доступа к LoadBalancer Service

Защита внешних сервисов с помощью NetworkPolicy.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: lb-ingress-control
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: web-frontend
  policyTypes:
    - Ingress
  ingress:
    # Разрешить трафик только от Ingress Controller
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
          podSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
      ports:
        - port: 80
          protocol: TCP
        - port: 443
          protocol: TCP
```

### Паттерн 6: Защита Service с Sidecar-контейнерами

Корректная настройка NetworkPolicy для подов с sidecar (Service Mesh).

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-mesh-traffic
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: my-service
  policyTypes:
    - Ingress
  ingress:
    # Разрешить трафик от sidecarEnvoy (для Service Mesh)
    - from:
        - podSelector:
            matchLabels:
              sidecar.istio.io/inject: "true"
      ports:
        - port: 15001
          protocol: TCP
    # Разрешить health check от kubelet
    - from:
        - ipBlock:
            cidr: 10.0.0.0/8
      ports:
        - port: 15021
          protocol: TCP
```

---

## Диагностика проблем NetworkPolicy + Service

### Симптом: Service доступен, но трафик не проходит

**Алгоритм диагностики:**
```bash
# 1. Проверка существования Service и эндпоинтов
kubectl get svc <service-name>
kubectl get endpointslice -l kubernetes.io/service-name=<service-name>

# 2. Проверка NetworkPolicy в namespace
kubectl get networkpolicy -n <namespace>

# 3. Проверка доступа из тестового пода
kubectl run test --rm -it --image=curlimages/curl -- curl -v http://<service-name>

# 4. Проверка conntrack (если трафик блокируется на уровне ядра)
sudo conntrack -L -p tcp --dport <port>

# 5. Проверка правил CNI (Calico/Cilium)
kubectl exec -n kube-system <calico-pod> -- calicoctl get policy
```

### Частые ошибки

| Ошибка | Симптом | Решение |
| :--- | :--- | :--- |
| **NetworkPolicy блокирует DNS** | Service не резолвится по имени | Добавить egress rule для порта 53 (CoreDNS) |
| **Несовпадение селекторов** | Трафик не проходит хотя policy есть | Проверить labels подов и podSelector в policy |
| **Отсутствие egress rules** | Под не может инициировать соединения | Добавить egress rules для необходимых сервисов |
| **policyTypes не указан** | NetworkPolicy не применяется | Добавить `policyTypes: [Ingress]` или `[Egress]` |

---

## Best Practices

1. **Начинайте с Default Deny** - создайте политику запрета всего, затем разрешайте явно
2. **Используйте стандартные метки** - `app.kubernetes.io/name` для согласованности селекторов
3. **Разделяйте Ingress и Egress** - создавайте отдельные политики для входящего и исходящего трафика
4. **Документируйте политики** - используйте аннотации для описания назначения каждой policy
5. **Тестируйте перед применением** - используйте `calicoctl` или `cilium policy` для валидации
6. **Мониторьте dropped packets** - настройте алерты на ошибки сети в приложениях
7. **Учитывайте Service Mesh** - если используется Istio/Linkerd, NetworkPolicy дополняет L7-политики

---

## Дополнительная информация

### Связанные темы

- **NetworkPolicy Deep Dive:** [NetworkPolicy](../Network/NetworkPolicy/definitions.md) - полный обзор ресурса NetworkPolicy
- **Default Deny Patterns:** [NetworkPolicy Practical](../Network/NetworkPolicy/practical_scenarios.md) - типовые сценарии
- **Egress Patterns:** [Egress Patterns](../Network/NetworkPolicy/egress_patterns.md) - управление исходящим трафиком
- **Service Mesh + NetworkPolicy:** [Service Mesh Interaction](../Network/NetworkPolicy/service_mesh_interaction.md) - взаимодействие L3/L4 и L7 политик
- **Production Debugging:** [Production Debugging](../Network/NetworkPolicy/production_debugging.md) - отладка в production

### См. также

- [Обзор Service](./service_overview.md) - архитектура Service
- [Отказоустойчивость Service](./service_failure_modes.md) - failure modes и каскадные сбои
- [Продвинутая диагностика](./service_advanced_troubleshooting.md) - tcpdump, netshoot
