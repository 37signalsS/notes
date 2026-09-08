# NetworkPolicy для внешних сервисов

## Определения

**ExternalName Service** — тип Service в Kubernetes, который создает CNAME-запись в DNS, указывающую на внешнее доменное имя (например, `external-db.example.com`). Не создает эндпоинтов и не маршрутизирует трафик через ClusterIP. NetworkPolicy не может фильтровать трафик к ExternalName-сервисам, так как они не имеют IP-адресов в кластере.

**LoadBalancer Service** — тип Service, предоставляющий внешний IP-адрес через облачный провайдер или in-cluster решение (MetalLB, Cilium). Трафик поступает через внешний балансировщик и направляется на поды. NetworkPolicy фильтрует трафик ПОСЛЕ того, как он был маршрутизирован на под.

**NodePort Service** — тип Service, открывающий порт на IP каждого узла (30000-32767). Трафик поступает через NodeIP:NodePort и DNATится на под. NetworkPolicy фильтрует трафик после DNAT.

**externalIPs** — параметр Service, позволяющий назначить произвольный внешний IP-адрес. Трафик маршрутизируется на поды через указанный IP. NetworkPolicy фильтрует трафик после маршрутизации.

## Базовые Концепции

### Как NetworkPolicy работает с разными типами Service

| Тип Service | IP-адрес | NetworkPolicy | Фильтрация |
| :--- | :--- | :--- | :--- |
| **ClusterIP** | Виртуальный IP в кластере | Применяется | После DNAT на IP пода |
| **NodePort** | IP узла + порт 30000-32767 | Применяется | После DNAT на IP пода |
| **LoadBalancer** | Внешний IP | Применяется | После маршрутизации на под |
| **ExternalName** | Нет (CNAME) | Не применим | Трафик не проходит через кластер |

### Порядок фильтрации для LoadBalancer

```
Внешний клиент → External LB → Node:NodePort → kube-proxy DNAT → Pod IP
                                                       ↑
                                              NetworkPolicy проверяется
                                              на IP пода (не на LB IP)
```

### Порядок фильтрации для ExternalName

```
Внешний клиент → DNS CNAME → Внешний сервер
                               ↑
                      NetworkPolicy НЕ участвует
                      (трафик не через кластер)
```

## Практические сценарии

### Сценарий 1: ClusterIP + NetworkPolicy

Классический сценарий: разрешить доступ к сервису только от определенных подов:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-api
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - protocol: TCP
      port: 8080
```

### Сценарий 2: LoadBalancer + NetworkPolicy

Внешний LoadBalancer с сохранением Source IP:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
  namespace: production
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local  # Сохраняет Source IP
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 8080
---
# NetworkPolicy разрешает трафик от всех (внешних клиентов)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-lb
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: my-app
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Все IP (внешние клиенты)
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 10.0.0.0/8      # Внутренние сети
        - 172.16.0.0/12
        - 192.168.0.0/16
    ports:
    - protocol: TCP
      port: 8080
```

### Сценарий 3: NodePort + NetworkPolicy

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
  namespace: production
spec:
  type: NodePort
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 8080
    nodePort: 30080
---
# NetworkPolicy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-nodeport
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: my-app
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Внешние клиенты через физическую сеть
    - ipBlock:
        cidr: 192.168.0.0/16
    ports:
    - protocol: TCP
      port: 8080
```

### Сценарий 4: ExternalName + NetworkPolicy

ExternalName Service не может быть фильтрован NetworkPolicy, так как трафик не проходит через кластер:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-db
  namespace: production
spec:
  type: ExternalName
  externalName: db.external-company.com
# NetworkPolicy не может фильтровать трафик к этому сервису!
# Трафик идет напрямую на db.external-company.com

# Решение: использовать Egress-политику для подов,
# которые обращаются к внешней БД
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-external-db
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
  - Egress
  egress:
  # DNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # Внешняя БД по IP
  - to:
    - ipBlock:
        cidr: 203.0.113.0/24  # IP внешней БД
    ports:
    - protocol: TCP
      port: 5432
```

### Сценарий 5: externalIPs + NetworkPolicy

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
  namespace: production
spec:
  type: ClusterIP
  externalIPs:
  - 192.168.1.100  # Внешний IP
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 8080
---
# NetworkPolicy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-ip
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: my-app
  policyTypes:
  - Ingress
  ingress:
  - from:
    - ipBlock:
        cidr: 192.168.0.0/16
    ports:
    - protocol: TCP
      port: 8080
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| ExternalName сервис недоступен из пода | NetworkPolicy блокирует egress | Разрешить egress к внешнему IP |
| LoadBalancer не пропускает трафик | NetworkPolicy не разрешает ingress | Добавить Ingress-правило для подов |
| NodePort не работает с NetworkPolicy | Политика не учитывает DNAT | Разрешить ingress от `ipBlock` сети узлов |
| Source IP теряется | `externalTrafficPolicy: Cluster` | Установить `externalTrafficPolicy: Local` |

### Рекомендации

| Тип Service | Рекомендация |
| :--- | :--- |
| **ClusterIP** | Используйте `podSelector` + `namespaceSelector` для фильтрации |
| **LoadBalancer** | Разрешайте ingress от `ipBlock` внешней сети; учитывайте `externalTrafficPolicy` |
| **NodePort** | Разрешайте ingress от CIDR физической сети |
| **ExternalName** | Используйте Egress-политику для подов, а не Ingress для сервиса |

### См. также

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины
* [NetworkPolicy: Egress паттерны](./egress_patterns.md) — управление исходящим трафиком
* [Service типы](../../Service/service_types_summary.md) — обзор типов Service
