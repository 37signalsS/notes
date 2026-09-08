# Тип Service — ClusterIP

## Определения

**ClusterIP** — тип Service по умолчанию в Kubernetes, предоставляющий стабильный виртуальный IP-адрес (Virtual IP, VIP), доступный исключительно внутри кластера. Он инкапсулирует динамические IP-адреса подов, обеспечивая надежную точку входа для East-West трафика (взаимодействие внутри кластера).

**Ключевые функции:**
- **Service Discovery:** Автоматическая регистрация в DNS кластера.
- **Внутренняя балансировка:** Распределение L4-трафика между репликами приложения.
- **Изоляция:** Защита сервисов от прямого доступа из внешних сетей.

## Основные концепции

### Механика и принцип работы

Реализация ClusterIP базируется на создании виртуального IP-адреса, который не привязан к физическому интерфейсу, а обрабатывается сетевым стеком узла (через механизмы ядра Linux):

1.  **EndpointSlice:** Контроллер отслеживает статус подов через селекторы и обновляет объекты `EndpointSlice`. Это позволяет эффективно управлять связностью даже при наличии тысяч реплик.
2.  **Kube-proxy:** Агент на каждом узле транслирует данные `EndpointSlice` в правила фильтрации трафика (iptables, IPVS или nftables).
3.  **Hairpin NAT (Loopback NAT):** Критически важный механизм, позволяющий поду обращаться к самому себе через ClusterIP своего сервиса. Без Hairpin NAT пакет, отправленный подом на VIP и перенаправленный ядром обратно на IP того же пода, был бы отброшен как некорректный.

## Предварительные требования

Для работы с ClusterIP Service необходимо обеспечить следующее окружение:

- **Кластер Kubernetes** версии 1.21+ (для поддержки EndpointSlices) или 1.31+ (для стабильной поддержки nftables и trafficDistribution)
- **CNI-плагин** (Calico, Flannel, Cilium или аналог) — обеспечивает базовую связность подов
- **kube-proxy** — DaemonSet, развёрнутый на всех узлах кластера (или eBPF-замена, например Cilium kube-proxy replacement)
- **CoreDNS** — кластерный DNS-сервер для Service Discovery через имена
- **kubectl** — CLI-инструмент для управления ресурсами кластера

**Проверка готовности окружения:**
```bash
# Проверка статуса kube-proxy
kubectl -n kube-system get pods -l k8s-app=kube-proxy
# → Все поды должны быть в статусе Running и Ready

# Проверка CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
# → Все поды должны быть в статусе Running и Ready

# Проверка CNI (пример для Calico)
kubectl -n kube-system get pods -l k8s-app=calico-node
# или для Cilium
kubectl -n kube-system get pods -l k8s-app=cilium

# Проверка режима работы kube-proxy
kubectl -n kube-system get configmap kube-proxy -o yaml | grep mode
# → mode: "nftables" (или "ipvs", "iptables")

# Проверка диапазона ClusterIP
kubectl cluster-info dump | grep -E "service-cluster-ip-range"
# → --service-cluster-ip-range=10.96.0.0/12
```

### Режимы работы kube-proxy (Backend)

| Режим | Статус | Особенности реализации |
| :--- | :--- | :--- |
| **nftables** | **Stable (v1.31)** | Современная замена iptables. Обеспечивает O(1) производительность обновлений и более эффективную обработку пакетов в ядре. |
| **IPVS** | Stable | Использует хеш-таблицы. Рекомендуется для сверхкрупных кластеров (десятки тысяч сервисов). Поддерживает продвинутые алгоритмы (Least Connection). |
| **iptables** | Legacy | Использует последовательный перебор правил. Производительность деградирует при большом количестве сервисов (O(n)). |

### Управление трафиком и топология

Для оптимизации задержек и стоимости межзонного трафика используются следующие механизмы:

- **internalTrafficPolicy:**
    - `Cluster` (Default): трафик балансируется между всеми подами кластера.
    - `Local`: трафик направляется только на поды, находящиеся на том же узле, где инициирован запрос. Позволяет избежать лишних сетевых переходов (hops).
- **trafficDistribution (v1.31+):** Новое поле (пришедшее на смену Topology Aware Hints), позволяющее более гибко настраивать предпочтения маршрутизации (например, `PreferClose`), чтобы направлять трафик внутри одной зоны доступности (AZ).

### Аллокация IP и ServiceCIDR (v1.29+)

ClusterIP назначается из диапазона, заданного флагом API-сервера `--service-cluster-ip-range`. 
- **ServiceCIDR API:** Современный механизм управления диапазонами IP-адресов сервисов. Позволяет динамически добавлять новые подсети для ClusterIP без перезагрузки Control Plane, что критично для масштабирования растущих кластеров.

### Поддержка Dual-stack (IPv4/IPv6)

ClusterIP поддерживает одновременную работу по обоим протоколам. 
- `ipFamilyPolicy`: `SingleStack`, `PreferDualStack` или `RequireDualStack`.
- При `PreferDualStack` сервис получает два ClusterIP (один IPv4 и один IPv6).

## Практические сценарии

### Пример манифеста

Стандартный манифест для внутреннего взаимодействия. Тип `ClusterIP` используется по умолчанию, поэтому его можно не указывать явно.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: internal-app-service
spec:
  selector:
    app: internal-app
  ports:
    - name: http
      protocol: TCP
      port: 80         # Внутренний порт сервиса
      targetPort: 8080 # Порт приложения в контейнере
```

**Применение и проверка:**
```bash
# Применение манифеста
kubectl apply -f clusterip-service.yaml

# Проверка созданного сервиса
kubectl get svc internal-app-service
# NAME                   TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
# internal-app-service   ClusterIP   10.96.x.x       <none>        80/TCP    5s

# Проверка назначенных эндпоинтов
kubectl get endpointslices -l kubernetes.io/service-name=internal-app-service
# NAME                        ADDRESSTYPE   PORTS   ENDPOINTS       AGE
# internal-app-service-abc123  IPv4          80      10.244.1.5      10s

# Тестовый запрос из другого пода
kubectl run test-curl --rm -it --image=curlimages/curl -- curl -s http://internal-app-service
# → <!DOCTYPE html>... (ожидаемый ответ приложения)

# Проверка DNS-резолвинга
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup internal-app-service.default.svc.cluster.local
# Server:    10.96.0.10
# Address:   10.96.0.10#3
#
# Name:      internal-app-service.default.svc.cluster.local
# Address:   10.96.x.x
```

### Настройка Session Affinity

Используется для привязки клиента к конкретному поду (например, для WebSocket или кэширования сессий).

```yaml
apiVersion: v1
kind: Service
metadata:
  name: session-aware-service
spec:
  selector:
    app: web
  sessionAffinity: ClientIP
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 10800 # По умолчанию 3 часа
  ports:
    - port: 80
      targetPort: 8080
```

**Техническая деталь:** Механизм `sessionAffinity` базируется на таблице соединений **conntrack** в ядре Linux. При сбросе таблицы (например, перезагрузка узла или переполнение) привязка сессий может быть потеряна.

**Проверка работы Session Affinity:**
```bash
# Применение манифеста
kubectl apply -f session-affinity-service.yaml

# Проверка конфигурации
kubectl get svc session-aware-service -o yaml | grep -A3 sessionAffinity
# sessionAffinity: ClientIP
# sessionAffinityConfig:
#   clientIP:
#     timeoutSeconds: 10800

# Тестовый запрос (повторные запросы должны идти на один под)
for i in 1 2 3; do kubectl run test-curl-$i --rm -it --image=curlimages/curl -- curl -s http://session-aware-service; done
```

### Сценарии использования

- **Межсервисное взаимодействие:** Основной метод связи между компонентами внутри кластера (например, Frontend → Backend).
- **Микросервисная архитектура:** Обеспечивает изоляцию сервисов; отсутствие прямого доступа извне снижает поверхность атаки.
- **Sidecar-коммуникации:** Использование `internalTrafficPolicy: Local` для взаимодействия основного приложения с локальными агентами (Envoy, Vault Agent), минимизируя задержки сетевого стека.
- **Service Mesh:** ClusterIP является базовой единицей для управления трафиком в Istio, Linkerd или Cilium.

### Доступ для отладки

Для временного доступа к внутреннему сервису с локальной машины без настройки Ingress используется команда `port-forward`:

```bash
kubectl port-forward svc/internal-app-service 8080:80
# → результат: Forwarding from 127.0.0.1:8080 -> 80
```

Приложение станет доступно по адресу `http://localhost:8080`.

**Важно:** `port-forward` предназначен только для разработки и отладки. Для production-доступа используйте [Ingress](../Ingress/overview.md), [Gateway API](../gateway_api/definitions.md) или [NodePort/LoadBalancer](./service_types_summary.md).

## Устранение неполадок (Troubleshooting)

### Проблема 1: Отсутствие эндпоинтов

**Симптом:** Service создан, но не перенаправляет трафик. `kubectl describe svc` показывает `Endpoints: <none>`.

**Диагностика:**
```bash
# 1. Проверка селектора сервиса
kubectl get svc <service-name> -o yaml | grep -A5 selector

# 2. Проверка меток подов
kubectl get pods --show-labels -l <selector>

# 3. Проверка готовности подов
kubectl get pods -l <selector>
# READY должен быть 1/1 (или N/N)

# 4. Проверка EndpointSlices
kubectl get endpointslice -l kubernetes.io/service-name=<service-name>
```

**Типичные причины и решения:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| Несоответствие меток | `kubectl get pods --show-labels` — метки не совпадают с селектором | Исправить labels подов или selector сервиса |
| Поды не готовы | `kubectl get pods` (READY 0/1) | Проверить readinessProbe, логи пода |
| Разные namespace | `kubectl get pods -A -l <selector>` — поды в другом namespace | Убедиться, что поды и сервис в одном namespace |
| Нет подов с таким селектором | `kubectl get pods -l <selector>` — пустой список | Создать поды или исправить селектор |

### Проблема 2: DNS не разрешает имя сервиса

**Симптом:** Приложение внутри кластера не может обратиться к сервису по имени.

**Диагностика:**
```bash
# Проверка CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
# → Все поды должны быть Running

# Проверка DNS из тестового пода
kubectl run dns-debug --rm -it --image=busybox:1.37 -- nslookup <service-name>.<namespace>.svc.cluster.local

# Проверка конфигурации DNS пода
kubectl exec <pod> -- cat /etc/resolv.conf
# → Должен содержать nameserver <CoreDNS ClusterIP>
# → Должен содержать search-суффиксы: default.svc.cluster.local svc.cluster.local cluster.local
```

**Типичные причины:**
- CoreDNS не запущен или перезагружается
- NetworkPolicy блокирует трафик на порт 53 (UDP/TCP) к CoreDNS
- Неправильная конфигурация `ndots` в `/etc/resolv.conf`

### Проблема 3: Трафик не доходит до сервиса

**Симптом:** DNS работает, ClusterIP пингится, но соединение с портом не устанавливается.

**Диагностика:**
```bash
# Проверка правил kube-proxy (nftables)
sudo nft list ruleset | grep -E "KUBE-SERVICES|KUBE-SVC" | grep <cluster-ip>

# Проверка связности с эндпоинтом напрямую
kubectl run curl-debug --rm -it --image=curlimages/curl -- curl -v http://<pod-ip>:<target-port>

# Проверка conntrack на узле
sudo conntrack -L -p tcp --dport <port>
```

**Типичные причины:**
- kube-proxy не обновил правила (перезапустите DaemonSet)
- NetworkPolicy блокирует ingress-трафик к подам
- Приложение в контейнере не слушает на targetPort

### Проблема 4: Неравномерная балансировка нагрузки

**Симптом:** Некоторые поды получают значительно больше трафика, чем другие.

**Диагностика:**
```bash
# Проверка режима kube-proxy
kubectl -n kube-system get configmap kube-proxy -o yaml | grep mode

# Проверка количества эндпоинтов
kubectl get endpointslice -l kubernetes.io/service-name=<service-name> -o json | jq '.items[].endpoints | length'
```

**Причины:**
- В режиме iptables/nftables используется случайный алгоритм (random), который может давать неравномерное распределение при малом количестве эндпоинтов
- При `internalTrafficPolicy: Local` трафик распределяется только между локальными подами узла

**Решение:**
- Для точного контроля балансировки используйте Service Mesh (Istio, Linkerd) или IPVS режим с алгоритмом lc (Least Connection)

## Best Practices

1. **Используйте ClusterIP по умолчанию:** Это тип Service по умолчанию. Переходите на другие типы только при необходимости внешнего доступа.

2. **Именованные порты:** Указывайте имена портов в манифестах подов и Service — это упрощает обновление портов приложения без изменения манифестов Service:
   ```yaml
   ports:
     - name: http
       port: 80
       targetPort: http-web  # Имя порта, а не номер
   ```

3. **Всегда настраивайте readinessProbe:** Предотвращает отправку трафика на не готовые поды:
   ```yaml
   readinessProbe:
     httpGet:
       path: /health
       port: http
     initialDelaySeconds: 5
     periodSeconds: 10
   ```

4. **Используйте стандартные метки (labels):** Обеспечивает совместимость с инструментатами и Service Mesh:
   ```yaml
   labels:
     app.kubernetes.io/name: my-app
     app.kubernetes.io/component: frontend
     app.kubernetes.io/version: "1.2.3"
   ```

5. **Ограничивайте доступ через NetworkPolicy:** Даже для внутренних сервисов ClusterIP рекомендуется ограничивать доступ:
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: allow-frontend-only
   spec:
     podSelector:
       matchLabels:
         app: backend
     ingress:
       - from:
           - podSelector:
               matchLabels:
                 app: frontend
   ```

6. **Указывайте явный ClusterIP при необходимости:** Для критичных сервисов (например, внутренний API) можно зафиксировать IP:
   ```yaml
   spec:
     clusterIP: 10.96.0.100  # Конкретный IP из диапазона
   ```

7. **Мониторьте использование диапазона ServiceCIDR:** При исчерпании диапазона новые Service не смогут быть созданы. Проверка:
   ```bash
   kubectl get servicecidr
   ```

## Edge Cases и ограничения

1. **Hairpin NAT:** Под может обращаться к самому себе через ClusterIP своего сервиса. Без Hairpin NAT такой запрос был бы отброшен. Включается автоматически в kube-proxy (`--hairpin-mode=hairpin-veth`).

2. **Ограничение на количество сервисов:**
   - **iptables режим:** Производительность деградирует при >1000 сервисах (O(N) поиск правила)
   - **nftables режим:** O(N) с низким коэффициентом, рекомендуется до ~5000 сервисов
   - **IPVS режим:** O(1), рекомендуется для >5000 сервисов

3. **Проблема gRPC и HTTP/2:** kube-proxy балансирует на уровне TCP, не видит HTTP/2 мультиплексирование. Все gRPC-запросы по одному TCP-соединению идут на один под. Решение: использовать Headless Service с клиентской балансировкой или Service Mesh.

4. **Невозможность изменения типа:** Поле `type` Service неизменяемое. Для смены типа требуется удаление и создание сервиса заново с потерей ClusterIP (если не указан явно).

5. **Session Affinity и масштабирование:** При изменении количества подов распределение сессий может стать неравномерным. При переполнении conntrack привязка теряется.

6. **Dual-stack особенности:** В режиме Dual-stack сервис получает два ClusterIP (IPv4 и IPv6). Убедитесь, что клиенты поддерживают оба протокола. DNS будет возвращать оба адреса (A и AAAA записи).

7. **Зависимость от kube-proxy:** При остановке kube-proxy на узле все ClusterIP Service становятся недоступными с этого узла. Убедитесь, что kube-proxy работает как DaemonSet с корректными health checks.

8. **Многоконтейнерные поды:** В подах с sidecar-контейнерами критически важно точно указывать `targetPort`. Укажите порт прокси-контейнера, а не основного приложения, если трафик должен проходить через sidecar.

## Очистка и откат изменений

```bash
# Просмотр всех ClusterIP сервисов в namespace
kubectl get svc -l app=internal-app

# Удаление конкретного сервиса
kubectl delete svc internal-app-service
# → service "internal-app-service" deleted

# Удаление сервиса по манифесту
kubectl delete -f clusterip-service.yaml

# Проверка удаления
kubectl get svc internal-app-service
# → Error from server (NotFound): services "internal-app-service" not found
```

**Важно:** При удалении Service все поды продолжают работать, но теряют стабильную точку входа. Убедитесь, что на сервис нет зависимых ресурсов (Ingress, другие приложения).

## Дополнительная информация

### Иерархия сетевых абстракций

ClusterIP является базисом (building block) для всех типов сервисов, обеспечивающих внешнюю связность:
1.  **ClusterIP** — только внутри кластера.
2.  **[NodePort](./service_type_nodeport.md)** — ClusterIP + порт на каждом узле.
3.  **[LoadBalancer](./service_type_loadbalancer.md)** — NodePort + внешний балансировщик.

### Ключевые ограничения

- **L4 Only:** ClusterIP работает на транспортном уровне (TCP/UDP). Он не понимает HTTP-заголовки, пути или Cookie. Для маршрутизации на L7 используйте [Ingress](../Ingress/overview.md) или [Gateway API](../gateway_api/definitions.md).
- **Отсутствие внешнего IP:** Прямое обращение извне кластера на ClusterIP технически невозможно без NAT или VPN-туннелирования в сеть кластера.

### См. также

- [Обзор Service](./service_overview.md) — общая информация о Service
- [Сводка по типам Service](./service_types_summary.md) — сравнение всех типов Service
- [Тип Service — Headless](./service_type_headless.md) — для StatefulSet и кластерных приложений


