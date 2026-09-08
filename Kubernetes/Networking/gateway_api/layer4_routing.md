# L4-маршрутизация — TCPRoute и UDPRoute

## Определения

**L4-маршрутизация** — передача трафика на транспортном уровне (TCP/UDP) без анализа содержимого пакетов прикладного уровня. Контроллер оперирует только портами и IP-адресами, не расшифровывая протоколы (например, SSH или проприетарные бинарные протоколы баз данных).

**TCPRoute (v1)** — ресурс Gateway API для маршрутизации TCP-трафика. С июля 2026 года (версия v1.6) находится в статусе **Standard (GA)**.

**UDPRoute (v1)** — ресурс Gateway API для маршрутизации UDP-трафика. С июля 2026 года (версия v1.6) находится в статусе **Standard (GA)**.

**TLSRoute (v1)** — ресурс Gateway API для маршрутизации TLS-трафика на уровне SNI без терминации TLS. Позволяет направлять зашифрованный трафик к бэкендам на основе имени хоста в TLS-рукопожатии. С июля 2026 года находится в статусе **Standard (GA)**.

**ReferenceGrant** — ресурс Gateway API, разрешающий ссылки на ресурсы в других namespace. Необходим для организации cross-namespace маршрутизации, когда Gateway находится в одном namespace, а целевой Service — в другом.

## Базовые концепции

### Область применения

L4-маршрутизация используется в случаях, когда L7-анализ невозможен (шифрованные протоколы без SNI) или нецелесообразен (требуется максимальная скорость):

- **Базы данных:** PostgreSQL, MySQL, Redis, ClickHouse.
- **Системные службы:** SSH, SFTP.
- **Сетевые службы:** DNS (UDP), NTP.
- **Игры и мультимедиа:** Игровые серверы, VoIP (SIP), потоковое вещание.

### Статус ресурсов и версии

К середине 2026 года основные ресурсы транспортного уровня стабилизированы:

| Ресурс | Версия API (v1.6+) | Статус | Примечание |
| :--- | :--- | :--- | :--- |
| **TCPRoute** | `gateway.networking.k8s.io/v1` | **Standard (GA)** | Поддержка во всех мажорных контроллерах |
| **UDPRoute** | `gateway.networking.k8s.io/v1` | **Standard (GA)** | Рекомендуется для DNS и игровых серверов |
| **TLSRoute** | `gateway.networking.k8s.io/v1` | **Standard (GA)** | Маршрутизация по SNI без терминации TLS |

> **Примечание:** В версиях Gateway API ниже v1.6 данные ресурсы могут находиться в канале `v1alpha2` (Experimental). Для использования стабильных версий `v1` необходимо обновить CRD до версии v1.6.0+.

### Особенности настройки

Настройка L4-маршрутов требует координации портов на разных уровнях:

1. **Инфраструктура:** Балансировщик нагрузки (MetalLB или аналог) должен поддерживать проброс произвольных портов.
2. **Gateway Listener:** Слушатель в ресурсе `Gateway` должен быть настроен на протокол `TCP`, `UDP` или `TLS` и соответствующий порт.
3. **Route:** Ресурс `TCPRoute`/`UDPRoute`/`TLSRoute` связывает слушателя с сервисом бэкенда.

### Cross-namespace маршрутизация

Для организации маршрутизации между namespace (когда Gateway в одном namespace, а Service в другом) используется ресурс `ReferenceGrant`:

**Принцип работы:**
- Gateway в namespace `gateway-system` принимает внешний трафик
- TCPRoute ссылается на Service в namespace `databases`
- ReferenceGrant в namespace `databases` разрешает ссылки из namespace `gateway-system`

**Структура ReferenceGrant:**
```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-gateway-to-db
  namespace: databases
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: TCPRoute
    namespace: gateway-system
  to:
  - group: ""
    kind: Service
```

> **Важно:** Без ReferenceGrant cross-namespace ссылки будут отклонены контроллером с условием `ResolvedRefs: False`.

### Статусы ресурсов (Conditions)

Gateway API предоставляет детальную диагностику через `status.conditions`:

| Условие | Описание |
| :--- | :--- |
| **Accepted** | Конфигурация признана валидной контроллером |
| **Programmed** | Шлюз успешно настроен и трафик маршрутизируется |
| **ResolvedRefs** | Все зависимости (Service, ReferenceGrant) найдены и корректны |

Проверка статуса:
```bash
kubectl get tcproute -n <namespace>
kubectl describe tcproute <name> -n <namespace>
```

## Практические сценарии

### Предварительные требования

- Kubernetes кластер версии 1.25+
- Gateway API CRD версии v1.6.0+
- Установленный контроллер Gateway API (Envoy Gateway, KGateway, Traefik и т.д.)
- Балансировщик нагрузки с поддержкой произвольных портов (MetalLB для bare-metal)

### Настройка TCPRoute (Пример: Доступ к PostgreSQL)

**1. Настройка слушателя в Gateway:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: database-gateway
  namespace: gateway-system
spec:
  gatewayClassName: envoy-gateway
  listeners:
  - name: postgres
    protocol: TCP
    port: 5432
    allowedRoutes:
      kinds:
      - kind: TCPRoute
```

**2. Создание маршрута TCPRoute:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: TCPRoute
metadata:
  name: postgres-route
  namespace: gateway-system
spec:
  parentRefs:
  - name: database-gateway
    sectionName: postgres
  rules:
  - backendRefs:
    - name: postgres-service
      namespace: databases
      port: 5432
```

**3. Создание ReferenceGrant (если Service в другом namespace):**

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-gateway-to-postgres
  namespace: databases
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: TCPRoute
    namespace: gateway-system
  to:
  - group: ""
    kind: Service
```

**4. Валидация конфигурации:**

```bash
# Проверка статуса Gateway
kubectl get gateway database-gateway -n gateway-system
# → NAME               CLASS           ADDRESS        PROGRAMMED   AGE
# → database-gateway   envoy-gateway   192.168.1.100  True         2m

# Проверка статуса TCPRoute
kubectl get tcproute postgres-route -n gateway-system
# → NAME             AGE
# → postgres-route   1m

# Детальная проверка условий
kubectl describe tcproute postgres-route -n gateway-system
# → Status:
# →   Parents:
# →     Conditions:
# →       Last Transition Time:  2026-09-01T18:00:00Z
# →       Reason:                Accepted
# →       Status:                True
# →       Type:                  ResolvedRefs
```

### Настройка UDPRoute (Пример: Внешний DNS)

**1. Gateway с UDP-слушателем:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: udp-gateway
  namespace: gateway-system
spec:
  gatewayClassName: envoy-gateway
  listeners:
  - name: dns-listener
    protocol: UDP
    port: 53
    allowedRoutes:
      kinds:
      - kind: UDPRoute
```

**2. Создание маршрута UDPRoute:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: UDPRoute
metadata:
  name: dns-external-route
  namespace: gateway-system
spec:
  parentRefs:
  - name: udp-gateway
    sectionName: dns-listener
  rules:
  - backendRefs:
    - name: coredns-svc
      namespace: kube-system
      port: 53
```

**3. ReferenceGrant для CoreDNS:**

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-gateway-to-dns
  namespace: kube-system
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: UDPRoute
    namespace: gateway-system
  to:
  - group: ""
    kind: Service
```

### Настройка TLSRoute (Пример: Маршрутизация по SNI)

TLSRoute позволяет маршрутизировать TLS-трафик без его расшифровки, используя имя хоста из TLS-рукопожатия (SNI):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: tls-gateway
  namespace: gateway-system
spec:
  gatewayClassName: envoy-gateway
  listeners:
  - name: tls-passthrough
    protocol: TLS
    port: 443
    tls:
      mode: Passthrough
    allowedRoutes:
      kinds:
      - kind: TLSRoute
---
apiVersion: gateway.networking.k8s.io/v1
kind: TLSRoute
metadata:
  name: db-tls-route
  namespace: gateway-system
spec:
  parentRefs:
  - name: tls-gateway
    sectionName: tls-passthrough
  hostnames:
  - "db.example.com"
  rules:
  - backendRefs:
    - name: postgres-service
      namespace: databases
      port: 5432
```

### Диагностика и мониторинг

```bash
# Проверка всех L4-ресурсов
kubectl get tcproute,udproute,tlsroute -A

# Проверка статуса Gateway
kubectl get gateway -n gateway-system -o wide

# Просмотр логов контроллера
kubectl logs -n envoy-gateway-system -l gateway.envoyproxy.io/owning-gateway-name=database-gateway

# Проверка конфигурации Envoy (через admin interface)
kubectl port-forward -n envoy-gateway-system pod/<envoy-pod> 19000:19000
curl http://localhost:19000/config_dump | jq '.configs[].dynamic_active_clusters'

# Проверка статуса upstream кластеров
curl http://localhost:19000/clusters | grep "postgres-service"
```

## Troubleshooting

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Accepted: False` | Неверная конфигурация Listener или протокол не поддерживается | Проверить протокол Gateway (TCP/UDP/TLS) и `allowedRoutes.kinds` |
| `ResolvedRefs: False` | Отсутствует ReferenceGrant для cross-namespace ссылки | Создать ReferenceGrant в namespace целевого Service |
| `Programmed: False` | Контроллер не смог настроить прокси | Проверить логи контроллера и статус Gateway |
| Трафик не проходит | Балансировщик не пробрасывает порт | Проверить конфигурацию MetalLB или аналога |
| Высокая задержка | Неоптимальный путь трафика | Проверить маршрутизацию и расположение подов |

### Диагностика проблем с конфигурацией

```bash
# Проверка статусов всех L4-ресурсов
kubectl get tcproute,udproute,tlsroute -A -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.parents[0].conditions[0].type}{"\t"}{.status.parents[0].conditions[0].status}{"\t"}{.status.parents[0].conditions[0].reason}{"\n"}{end}'

# Проверка наличия ReferenceGrant
kubectl get referencegrant -A

# Проверка событий (events)
kubectl get events -n gateway-system --field-selector reason=ResolvedRefs

# Детальная информация о маршруте
kubectl describe tcproute postgres-route -n gateway-system

# Проверка логов контроллера
kubectl logs -n envoy-gateway-system -l control-plane=envoy-gateway-controller --tail=100
```

### Диагностика проблем с трафиком

```bash
# Проверка доступности бэкенда (из пода контроллера)
kubectl exec -n gateway-system deploy/database-gateway -- nc -zv postgres-service.databases.svc.cluster.local 5432

# Проверка DNS (для UDPRoute)
kubectl exec -n gateway-system deploy/database-gateway -- dig @coredns-svc.kube-system.svc.cluster.local google.com

# Проверка TLS-сертификата (для TLSRoute)
kubectl exec -n gateway-system deploy/database-gateway -- openssl s_client -connect postgres-service.databases.svc.cluster.local:5432 -servername db.example.com
```

## Best Practices

### Организация инфраструктуры

1. **Используйте отдельные Gateway для разных сервисов:**
   - database-gateway, ssh-gateway, dns-gateway
   - Изолирует трафик и упрощает диагностику

2. **Централизуйте управление через отдельный namespace:**
   - Gateway в `gateway-system`
   - ReferenceGrant в целевых namespace
   - Упрощает аудит и контроль доступа

3. **Документируйте порты:**
   - Ведите реестр используемых портов
   - Предотвращайте конфликты портов

### Безопасность

1. **Используйте TLSRoute для шифрованных протоколов:**
   - Избегайте передачи данных в открытом виде
   - Применяйте Passthrough режим для end-to-end шифрования

2. **Ограничивайте ReferenceGrant:**
   - Указывайте конкретные namespace и типы ресурсов
   - Не используйте wildcard-разрешения

3. **Мониторинг трафика:**
   - Настройте алерты на изменения статусов
   - Отслеживайте необычную активность на портах

### Производительность

1. **Выбирайте оптимальный уровень маршрутизации:**
   - L4 для бинарных протоколов без необходимости L7-анализа
   - L7 (HTTPRoute) когда возможен анализ содержимого

2. **Используйте высокопроизводительные решения:**
   - Cilium eBPF для максимальной производительности L4
   - Envoy Proxy для гибкой балансировки

## Дополнительная информация

### Ограничения L4-маршрутизации

- **Отсутствие метаданных:** Невозможно использовать маршрутизацию по путям, хостам (кроме SNI в TLSRoute) или заголовкам.
- **Порты:** Каждый шлюз (Gateway) ограничен количеством доступных портов на внешнем IP-адресе.
- **Производительность:** Хотя L4 быстрее L7 за счет отсутствия разбора протокола, проксирование через Envoy или Traefik всё же создает минимальные задержки по сравнению с чистым `IPVS` или **eBPF (Cilium 1.20+)**. Cilium реализует L4-маршрутизацию на уровне ядра, что делает его предпочтительным выбором для высоконагруженных бинарных протоколов.

### Сравнение с альтернативами

| Характеристика | Gateway API L4 | Service LoadBalancer | Ingress |
| :--- | :--- | :--- | :--- |
| **Уровень** | L4 (TCP/UDP/TLS) | L4 (TCP/UDP) | L7 (HTTP) |
| **Маршрутизация** | По портам | По портам | По путям/хостам |
| **TLS** | Passthrough | Нет | Termination |
| **Cross-namespace** | Да (ReferenceGrant) | Нет | Нет |

**См. также:**

- [Концепции Gateway API](./definitions.md) — базовые концепции и архитектура.
- [Ресурсы (CRD)](./resources.md) — обзор всех типов объектов (включая TLSRoute).
- [Реализации: Envoy Gateway](./envoy_gateway.md) — рекомендуемый контроллер для L4.
- [Cilium: Высокопроизводительный CNI](../Network/CNI/cilium.md) — архитектура eBPF.

**Родительская тема:** [Gateway API](./definitions.md)
