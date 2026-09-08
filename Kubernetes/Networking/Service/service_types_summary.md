# Сводка по типам Service

## Определения

**Сводка по типам Service** — это консолидированный аналитический обзор всех методов публикации приложений в Kubernetes. Документ служит инструментом для выбора архитектуры сетевой связности на основе требований к уровню OSI, масштабируемости и безопасности.

Теоретический фундамент и механизмы реализации описаны в [Обзоре Service](./service_overview.md).

## Предварительные требования

Для выбора и настройки типа Service необходимо обеспечить следующее окружение:

- **Кластер Kubernetes** версии 1.21+ (для поддержки EndpointSlices) или 1.31+ (для стабильной поддержки nftables, trafficDistribution, ServiceCIDR)
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

# Проверка режима kube-proxy
kubectl -n kube-system get configmap kube-proxy -o yaml | grep mode
# → mode: "nftables" (или "ipvs", "iptables")

# Проверка диапазона ClusterIP
kubectl cluster-info dump | grep -E "service-cluster-ip-range"
# → --service-cluster-ip-range=10.96.0.0/12

# Проверка диапазона NodePort (если планируется использование)
kubectl cluster-info dump | grep -E "service-node-port-range"
# → --service-node-port-range=30000-32767
```

## Основные концепции

### Иерархия и взаимосвязь типов

Большинство типов сервисов построены по принципу инкапсуляции и расширения функциональности:

1.  **ClusterIP** (Базис) — виртуальный IP для внутреннего взаимодействия.
2.  **NodePort** (L4 Вход) — расширяет ClusterIP, открывая порты на узлах.
3.  **LoadBalancer** (Облачный Вход) — расширяет NodePort, интегрируясь с внешними балансировщиками.

**Автономные типы:**
- **Headless** (`clusterIP: None`) — прямое управление эндпоинтами через DNS.
- **ExternalName** — DNS-псевдоним (CNAME) для внешних ресурсов.

### Сравнительные характеристики уровней доступа

| Тип | Доступность | Уровень OSI | Реализация в ядре | Основной сценарий |
| :--- | :--- | :--- | :--- | :--- |
| **[ClusterIP](./service_type_clusterip.md)** | Внутри кластера | L4 (TCP/UDP) | nftables / IPVS | Внутренние микросервисы |
| **[NodePort](./service_type_nodeport.md)** | Снаружи (Node IP) | L4 | nftables / IPVS | On-premise, Static Routing |
| **[LoadBalancer](./service_type_loadbalancer.md)** | Снаружи (VIP/DNS) | L4 | CCM / MetalLB | Production (Cloud/Bare-Metal) |
| **[Headless](./service_type_headless.md)** | Прямой IP подов | L3/L4 | DNS Records | StatefulSets, gRPC, DB |
| **[ExternalName](./service_type_externalname.md)** | Псевдоним DNS | DNS | CoreDNS CNAME | Интеграция с Legacy/External |

### Технические ограничения и нюансы (v1.36)

- **ClusterIP:** Недоступен извне без Ingress/Gateway. Использует Hairpin NAT для самообращения.
- **NodePort:** Диапазон 30000–32767. Открыт на всех интерфейсах всех узлов (требует Firewall).
- **LoadBalancer:** Поле `loadBalancerIP` устарело; используйте аннотации или `loadBalancerClass`.
- **Dual-Stack:** Все типы поддерживают IPv4/IPv6 через `ipFamilyPolicy` (v1.31+).
- **nftables:** С версии v1.31 является рекомендуемым бэкендом для `kube-proxy`, обеспечивая O(1) производительность.

## Практические сценарии

### Дерево решений для выбора типа Service

```
Начало: Необходимо опубликовать приложение
│
├─ Доступ только внутри кластера?
│  ├─ Да → Нужен список IP всех подов (StatefulSet, кворум)?
│  │      ├─ Да → Headless Service
│  │      └─ Нет → ClusterIP
│  │
│  └─ Нет (нужен внешний доступ) → Какой протокол?
│     ├─ HTTP/HTTPS (L7) → Gateway API (рекомендуется) или Ingress
│     ├─ TCP/UDP (L4) → Есть ли внешний балансировщик?
│     │      ├─ Да → LoadBalancer
│     │      └─ Нет → NodePort + внешний балансировщик (HAProxy/Nginx)
│     │
│     └─ Интеграция с внешним ресурсом по DNS? → ExternalName
```

### Матрица выбора метода публикации

| Задача / Требование | Рекомендуемое решение | Почему? |
| :--- | :--- | :--- |
| **Внутреннее API** | `ClusterIP` | Минимальный оверхед, изоляция. |
| **Базы данных (кворум)** | `Headless Service` | Нужны прямые IP для формирования кластера. |
| **HTTP(S) в Production** | **Gateway API** | Гибкое управление L7, Canary, TLS. |
| **TCP/UDP (не-HTTP)** | `LoadBalancer` | Прямой проброс L4 трафика. |
| **Локальная отладка** | `NodePort` | Не требует сложной инфраструктуры. |
| **Внешние SaaS-сервисы** | `ExternalName` | Абстракция внешнего URL в локальное имя. |
| **Сохранение Source IP** | `NodePort` или `LoadBalancer` с `externalTrafficPolicy: Local` | Отключает SNAT, приложение видит реальный IP клиента. |
| **Высокая доступность (HA)** | `LoadBalancer` с внешним балансировщиком | Автоматическое исключение недоступных узлов. |

### Проверка выбранного типа Service

После создания Service убедитесь, что он работает корректно:

```bash
# Проверка существования сервиса и его типа
kubectl get svc <service-name>
# → NAME          TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
# → my-service    ClusterIP   10.96.x.x       <none>        80/TCP         5s

# Проверка назначенных портов (для NodePort)
kubectl get svc <service-name> -o jsonpath='{.spec.ports[0].nodePort}'
# → 32080

# Проверка наличия эндпоинтов
kubectl get endpointslices -l kubernetes.io/service-name=<service-name>
# → NAME                        ADDRESSTYPE   PORTS   ENDPOINTS       AGE
# → my-service-abc123           IPv4          80      10.244.1.5      10s

# Проверка доступности изнутри кластера
kubectl run test-curl --rm -it --image=curlimages/curl -- curl -s http://<service-name>.<namespace>.svc.cluster.local
# → <!DOCTYPE html>... (ожидаемый ответ приложения)

# Проверка доступности NodePort снаружи (для NodePort/LoadBalancer)
curl http://<node-ip>:<node-port>
# → Ожидаемый ответ приложения

# Проверка DNS-записи (для Headless)
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup <service-name>.<namespace>.svc.cluster.local
# → Возвращает список IP всех подов
```

### Изменение типа Service

Kubernetes не позволяет изменить тип Service напрямую (поле `type` неизменяемое). Для смены типа необходимо удалить и создать сервис заново:

```bash
# Экспорт текущей конфигурации
kubectl get svc <service-name> -o yaml > service-backup.yaml

# Удаление старого сервиса
kubectl delete svc <service-name>
# → service "<service-name>" deleted

# Редактирование типа в манифесте
sed -i 's/type: ClusterIP/type: NodePort/' service-backup.yaml

# Применение нового сервиса
kubectl apply -f service-backup.yaml
# → service/<service-name> created

# Проверка
kubectl get svc <service-name>
```

**Важно:** При удалении и создании Service ClusterIP изменится (если не указан явно в `spec.clusterIP`). Для сохранения стабильного IP укажите его явно в манифесте.

## Дополнительная информация

### Механизмы управления трафиком

| Атрибут | Назначение | Технический эффект |
| :--- | :--- | :--- |
| **`externalTrafficPolicy`** | Сохранение Source IP | `Local` отключает SNAT, но требует Local Endpoints. |
| **`internalTrafficPolicy`** | Node-local трафик | Исключает сетевые переходы между узлами. |
| **`trafficDistribution`** | Топологическая маршрутизация | Заменяет Topology Hints, оптимизирует задержки. |
| **`sessionAffinity`** | Sticky Sessions | Привязка клиента к поду по `ClientIP` (через conntrack). |

### Эволюция сетевого доступа: Service vs Ingress vs Gateway API

1.  **Service (L4):** Стабильный транспорт. Ограничен портами и протоколами.
2.  **Ingress (L7 Legacy):** Узкоспециализирован под HTTP. Сложная расширяемость через вендорские аннотации.
3.  **Gateway API (Modern):** Стандарт 2026 года. Разделяет ответственность (Infrastructure vs Application), нативно поддерживает L4 (TCP/UDP) и L7 (HTTP/gRPC).

---

## Troubleshooting: типичные ошибки выбора типа Service

**Ошибка 1: Использование ClusterIP для внешнего доступа**

*Симптом:* Приложение недоступно извне кластера, хотя Service создан и работает.

*Причина:* ClusterIP предназначен исключительно для внутреннего взаимодействия. Обращение извне кластера на ClusterIP технически невозможно без NAT или VPN.

*Диагностика:*
```bash
# Проверка типа Service
kubectl get svc <service-name> -o jsonpath='{.spec.type}'
# → ClusterIP

# Попытка доступа извне (не сработает)
curl http://<cluster-ip>:80
# → Connection timed out
```

*Решение:*
- Для внешнего доступа используйте NodePort, LoadBalancer или Ingress/Gateway API
- Для временной отладки: `kubectl port-forward svc/<service-name> 8080:80`

**Ошибка 2: Неправильный выбор для StatefulSet**

*Симптом:* Приложение (Kafka, Elasticsearch, PostgreSQL) не может сформировать кворум, узлы не обнаруживают друг друга.

*Причина:* Использование ClusterIP вместо Headless Service для приложений, требующих прямого IP-обнаружения всех реплик.

*Диагностика:*
```bash
# Проверка DNS-записи (ClusterIP возвращает один IP)
nslookup <service-name>.<namespace>.svc.cluster.local
# → Address: 10.96.x.x (один VIP, а не IP всех подов)
```

*Решение:* Используйте Headless Service (`clusterIP: None`) для StatefulSet и кластерных приложений.

**Ошибка 3: Потеря Source IP при использовании NodePort/LoadBalancer**

*Симптом:* Приложение видит IP узла кластера вместо реального IP клиента. Логистика WAF, rate limiting и логирование работают некорректно.

*Причина:* По умолчанию `externalTrafficPolicy: Cluster` выполняет SNAT, подменяя клиентский IP.

*Диагностика:*
```bash
# Проверка политики трафика
kubectl get svc <service-name> -o jsonpath='{.spec.externalTrafficPolicy}'
# → Cluster

# Проверка логов пода (виден IP узла, а не клиента)
kubectl logs -l app=<app-name> --tail=10
# → <IP_узла> - - [date] "GET / HTTP/1.1" 200
```

*Решение:* Установите `externalTrafficPolicy: Local` для сохранения Source IP. Важно: потребуется внешний балансировщик, проверяющий `healthCheckNodePort`.

**Ошибка 4: ExternalName с HTTP и SNI/Host проблемами**

*Симптом:* SSL-ошибки или отклонение запросов при обращении к внешнему ресурсу через ExternalName.

*Причина:* Клиент отправляет заголовок `Host: <service-name>`, а внешний сервер ожидает своё имя. При HTTPS SNI также содержит имя сервиса, что вызывает ошибку сертификата.

*Диагностика:*
```bash
# Проверка CNAME
nslookup <service-name>.<namespace>.svc.cluster.local
# → canonical name = external-server.example.com
```

*Решение:* Для HTTP-зависимостей используйте промежуточный прокси (Ingress, Sidecar) с подменой заголовка Host и перезаписью SNI (TLS Origination).

## Best Practices выбора типа Service

1. **Начинайте с простого:** Используйте ClusterIP по умолчанию. Переходите на другие типы только при необходимости внешнего доступа.

2. **Микросервисная архитектура:** Все внутренние сервисы — ClusterIP. Публикуйте наружу только то, что необходимо через Gateway API или LoadBalancer.

3. **StatefulSet всегда Headless:** Для баз данных, брокеров сообщений, распределённых систем с кворумом используйте Headless Service.

4. **Сохранение Source IP:** Если приложению важен реальный IP клиента (WAF, rate limiting, аудит), используйте `externalTrafficPolicy: Local` с внешним балансировщиком.

5. **On-premise без облачного LB:** Используйте NodePort + внешний балансировщик (HAProxy, Nginx, F5) для production-доступа.

6. **Внешние зависимости через ExternalName:** Абстрагируйте внешние API и базы данных через ExternalName для гибкости миграции. Для HTTP используйте прокси с подменой Host.

7. **Документируйте порты:** Даже для ExternalName указывайте `ports` — это живая документация для команды.

8. **Проверяйте после выбора:** Всегда верифицируйте работоспособность выбранного типа Service (доступность, DNS, эндпоинты).

## Edge Cases и ограничения

1. **Невозможность изменения типа:** Поле `type` Service неизменяемое. Для смены типа требуется удаление и создание сервиса заново с потерей ClusterIP (если не указан явно).

2. **Ограничение диапазона NodePort:** Доступно только 2768 портов (30000–32767). Для большого количества сервисов используйте LoadBalancer или Gateway API.

3. **ExternalName и NetworkPolicy:** Трафик через ExternalName не виден в стандартных NetworkPolicy, так как идёт напрямую на внешние IP. Для контроля используйте Egress Gateway или Sidecar.

4. **Headless Service и размер DNS-ответа:** При >500 подов DNS-ответ может превысить 512 байт (UDP limit). CoreDNS устанавливает флаг TC (Truncated), клиент должен использовать TCP.

5. **LoadBalancer без внешнего балансировщика:** В on-premise без MetalLB или облачного CCM поле `status.loadBalancer.ingress` останется пустым, Service не получит внешний IP.

6. **Session Affinity и масштабирование:** При изменении количества подов распределение сессий может стать неравномерным. При переполнении conntrack привязка теряется.

7. **Dual-stack особенности:** В режиме Dual-stack сервис получает два ClusterIP (IPv4 и IPv6). Убедитесь, что клиенты поддерживают оба протокола.

8. **Миграция между типами:** При переходе с NodePort на LoadBalancer (MetalLB) потребуется изменить DNS-записи и конфигурацию внешних систем.

---

## Совет по собеседованию

**Вопрос:** Какой тип Service выбрать для публикации базы данных в Kubernetes?
**Ответ:**
- **StatefulSet с Headless Service** — если БД кластерная (PostgreSQL с репликацией, Elasticsearch, Kafka). Headless обеспечивает прямое IP-обнаружение узлов для формирования кворума.
- **ClusterIP** — если БД используется только внутри кластера и не требует прямого доступа к каждому поду.
- **NodePort/LoadBalancer** — только если требуется внешний доступ к БД (не рекомендуется по соображениям безопасности, лучше через VPN или Bastion).

### См. также

- [Обзор Service](./service_overview.md)
- [Gateway API — обзор](../gateway_api/definitions.md)
- [Практические сценарии публикации](./service_practical_scenarios.md)

