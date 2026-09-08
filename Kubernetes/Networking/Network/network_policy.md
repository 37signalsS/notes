# NetworkPolicy: Навигатор по сетевой безопасности

## Определения и концепции

**NetworkPolicy** — это фундаментальный ресурс Kubernetes для реализации сетевой микросегментации. Он позволяет декларативно определять правила фильтрации трафика на уровнях L3 (сетевой) и L4 (транспортный) модели OSI, работая по принципу разрешительных списков (Allow-lists).

На 2026 год сетевая безопасность Kubernetes базируется на **трехуровневой модели исполнения (3-Tier Enforcement Model)**:

1.  **AdminNetworkPolicy (ANP)** — обязательные правила администратора кластера (Tier 1), имеющие абсолютный приоритет. Поддерживает три действия: `Allow` (разрешает), `Deny` (блокирует), `Pass` (передает на проверку в Tier 2).
2.  **NetworkPolicy (NP)** — стандартные правила разработчиков на уровне пространств имен (Tier 2). Работает аддитивная логика: если хотя бы одна политика разрешает трафик — он проходит.
3.  **BaselineAdminNetworkPolicy (BANP)** — правила «последнего шанса» (Tier 3). Применяется, если трафик не был обработан на вышестоящих уровнях.

**Ключевые свойства NetworkPolicy:**

- **Политика stateful:** Ответный трафик (return traffic) разрешается автоматически через механизм conntrack, даже если нет явных Ingress-правил для ответов.
- **Аддитивность:** Итоговый набор разрешений для пода — это объединение (логическое «ИЛИ») всех правил всех NetworkPolicy, которые выбирают данный под.
- **policyTypes:** Обязательное поле, определяющее направления фильтрации. Без него политика не оказывает воздействия, даже если правила определены.

*   **Технический разбор и иерархия:** [NetworkPolicy: Определения и концепции](./NetworkPolicy/definitions.md)
*   **Логика работы правил (И/ИЛИ):** [NetworkPolicy: Логика правил](./NetworkPolicy/rule_logic.md)
*   **Паттерны Egress:** [NetworkPolicy: Управление исходящим трафиком](./NetworkPolicy/egress_patterns.md)
*   **FQDN-фильтрация:** [NetworkPolicy: Фильтрация по доменным именам](./NetworkPolicy/fqdn_filtering.md)
*   **Производительность:** [NetworkPolicy: Производительность и масштабирование](./NetworkPolicy/performance.md)
*   **Мультитенантность:** [NetworkPolicy: Изоляция тенантов](./NetworkPolicy/multi_tenancy.md)
*   **CI/CD и GitOps:** [NetworkPolicy: CI/CD и GitOps](./NetworkPolicy/gitops_ci_cd.md)
*   **Service Mesh:** [NetworkPolicy и Service Mesh: Взаимодействие слоёв](./NetworkPolicy/service_mesh_interaction.md)
*   **Ingress Controller:** [NetworkPolicy и Ingress Controller: Взаимодействие](./NetworkPolicy/ingress_controller_interaction.md)
*   **Типы workload:** [NetworkPolicy для разных типов Workload](./NetworkPolicy/workload_types.md)
*   **Мониторинг и логирование:** [NetworkPolicy для стека мониторинга и логирования](./NetworkPolicy/monitoring_logging.md)
*   **Диагностика в продакшене:** [NetworkPolicy: Диагностика в продакшене](./NetworkPolicy/production_debugging.md)
*   **Откат и инциденты:** [NetworkPolicy: Откат и управление инцидентами](./NetworkPolicy/rollback_incident.md)
*   **Bare metal и on-premise:** [NetworkPolicy для bare metal и on-premise сред](./NetworkPolicy/bare_metal_onprem.md)
*   **hostNetwork и hostPort:** [NetworkPolicy для hostNetwork и hostPort](./NetworkPolicy/host_network_port.md)
*   **Паттерны для собеседований:** [NetworkPolicy: Паттерны для собеседований](./NetworkPolicy/interview_patterns.md)
*   **Внешние сервисы:** [NetworkPolicy для внешних сервисов](./NetworkPolicy/external_services.md)

## Основные компоненты системы

### Реализация на уровне CNI

NetworkPolicy является лишь спецификацией в API Kubernetes. Фактическое принудительное исполнение правил (Enforcement) ложится на плечи сетевого плагина (**CNI**), который использует различные технологии ядра Linux:

*   **nftables (v1.31+)**: Современный стандарт, заменивший iptables, обеспечивающий высокую производительность за счет атомарных обновлений правил и двоичного дерева для поиска.
*   **eBPF (Cilium)**: Выполнение фильтрации напрямую в контексте драйвера сетевой карты, обеспечивающее минимальные задержки и расширенную видимость (L7, FQDN). Время поиска O(1) через хеш-таблицы.
*   **IPVS**: Режим балансировки, использующий хеш-таблицы для эффективной обработки трафика в кластерах с тысячами сервисов.
*   **Open vSwitch (Antrea)**: Программируемые конвейеры обработки пакетов через OpenFlow.

> **Важно:** Если CNI не поддерживает NetworkPolicy (например, стандартный Flannel), политики будут созданы в API-сервере, но никакого эффекта на трафик не окажут.

*   **Сравнение реализаций в CNI:** [NetworkPolicy: Реализация CNI-плагинами](./NetworkPolicy/cni_implementation.md)

### Порядок проверки правил

Пакет проходит через следующие этапы (порядок зависит от CNI):

1.  **ANP (Tier 1):** Если найдено совпадение с `Allow`/`Deny` — оценка прекращается.
2.  **NetworkPolicy (Tier 2):** Аддитивная логика (логическое «ИЛИ»). Если хотя бы одна политика разрешает — трафик проходит.
3.  **BANP (Tier 3):** Правила «по умолчанию», если трафик не был обработан на Tier 1-2.
4.  **Default Allow:** Если ни одна политика не выбрала под — трафик разрешен (стандартное поведение K8s).

> Если под попал под действие хотя бы одной NetworkPolicy (даже пустой с `policyTypes`), он переходит в режим Default Deny для указанных направлений.

## Практические сценарии

Внедрение сетевой изоляции рекомендуется проводить поэтапно, начиная с мониторинга и заканчивая режимом «запрещено по умолчанию» (Zero Trust).

### 1. Default Deny: Полная изоляция Namespace

Блокировка всего входящего и исходящего трафика для создания защищенного периметра. Это отправная точка безопасности:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}  # Выбирает все поды в namespace
  policyTypes:
  - Ingress
  - Egress
```

### 2. Межсервисная связность

Разрешение трафика между конкретными модулями приложения (например, Frontend → Backend):

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
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: frontend
      podSelector:
        matchLabels:
          app: webapp
    ports:
    - protocol: TCP
      port: 8080
```

### 3. Доступ к инфраструктуре

Правильная настройка доступа к CoreDNS и API-серверу для предотвращения сбоев Service Discovery:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-with-dns
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
  - Egress
  egress:
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
    - protocol: TCP
      port: 53
```

### 4. Ограничение внешних вызовов (Egress)

Использование CIDR-блоков или FQDN (в Cilium) для контроля доступа к внешним API:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-external-api
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: payment-service
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 203.0.113.0/24
    ports:
    - protocol: TCP
      port: 443
  # DNS (обязательно при Egress-изоляции!)
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
```

*   **Манифесты и примеры:** [NetworkPolicy: Практические сценарии](./NetworkPolicy/practical_scenarios.md)

## Рекомендации и эксплуатация

### Лучшие практики безопасности

*   **Всегда начинайте с Default Deny:** Никогда не оставляйте namespace без политики, запрещающей весь трафик по умолчанию. Это база Zero Trust.
*   **Использование ANP для защиты инфраструктуры:** Блокировка доступа к чувствительным эндпоинтам (Metadata API, etcd) на уровне кластера.
*   **Именованные порты:** Использование имен портов (например, `https`) вместо номеров для повышения гибкости манифестов.
*   **Минимизация Egress:** Чем меньше исходящих адресов разрешено, тем ниже риск эксфильтрации данных.
*   **Защита kube-system:** Namespace `kube-system` должен иметь строгие политики, запрещающие доступ со стороны прикладных подов.
*   **Валидация в CI/CD:** Используйте `conftest`, `kubewarden` или OPA Gatekeeper для проверки манифестов перед применением.

*   **Полный список рекомендаций:** [NetworkPolicy: Лучшие практики](./NetworkPolicy/best_practices.md)

### Важные нюансы

*   **Stateful-природа:** Политики автоматически разрешают ответный трафик (Return traffic) через механизм conntrack. Это работает только для ответов на установленные соединения; новые соединения подчиняются явным правилам.
*   **Source IP:** При использовании внешних балансировщиков без PROXY-протокола фильтрация по `ipBlock` может работать некорректно из-за SNAT. Решение: `externalTrafficPolicy: Local`.
*   **Localhost:** Трафик внутри пода (между контейнерами) через `127.0.0.1` никогда не фильтруется.
*   **hostNetwork:** Поды с `hostNetwork: true` обычно не подчиняются NetworkPolicy, так как используют сетевой стек хоста.
*   **conntrack:** При переполнении таблицы (`nf_conntrack_max`) ядро отбрасывает новые пакеты без логирования, что маскируется под проблемы NetworkPolicy.

### Диагностика типичных проблем

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Политика создана, но не работает | Отсутствует `policyTypes` | `kubectl describe networkpolicy <name>` | Добавить `policyTypes: [Ingress]` и/или `[Egress]` |
| DNS не резолвится после Default Deny | Egress блокирует порт 53 | `kubectl exec -it <pod> -- nslookup kubernetes.default` | Добавить Egress-правило для `kube-dns` |
| Connection Timeout между подами | Ingress не разрешает порт | `kubectl exec -it <pod> -- curl -v <svc>:<port>` | Добавить `ports` в секцию `ingress` |
| Трафик от другого namespace не проходит | Используется только `podSelector` | `kubectl get pods --show-labels -n <ns>` | Добавить `namespaceSelector` |
| Высокий CPU на kube-proxy | Линейный перебор iptables при >1000 правил | `top` + `iptables -L -n -v \| wc -l` | Перейти на eBPF-based CNI (Cilium) |
| Связность не восстанавливается | conntrack кэширует старые решения | `conntrack -L \| grep <pod-ip>` | Очистить conntrack: `conntrack -D -s <pod-ip>` |
| Трафик к Service блокируется | NetworkPolicy работает с IP подов | `kubectl exec -it <pod> -- curl <cluster-ip>:<port>` | Использовать `podSelector` вместо `ipBlock` |

### Алгоритм диагностики

```bash
# 1. Проверка DNS (критично при Egress-изоляции)
kubectl exec -it <pod> -- nslookup <service>.<namespace>.svc.cluster.local

# 2. Проверка наличия и правил политик
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy <policy-name> -n <namespace>

# 3. Проверка меток подов и namespace
kubectl get pods --show-labels -n <ns>
kubectl get ns --show-labels

# 4. Проверка CNI
kubectl get pods -n kube-system -l k8s-app=<cni-pod>

# 5. Проверка DROP-пакетов (Cilium)
hubble observe --namespace <ns> --verdict DROPPED --follow

# 6. Проверка conntrack
conntrack -S
conntrack -L | grep <pod-ip>
sysctl net.netfilter.nf_conntrack_max
```

**См. также:**

*   [Обзор сетевой модели Kubernetes](./network_overview.md) — базовые принципы No-NAT.
*   [Путь трафика в Kubernetes](./traffic_path.md) — детальный разбор North-South и East-West потоков.
*   [CNI и kube-proxy: роли](./cni_kube_proxy_roles.md) — разделение ответственности за связность и безопасность.
*   [DNS в Kubernetes](../dns_deep_dive.md) — критическая зависимость для NetworkPolicy.
*   [Cilium: eBPF и сетевая безопасность](./CNI/cilium.md) — продвинутые возможности защиты.
*   [Безопасность NetworkPolicy](../../Security/network_policies.md) — compliance, мультитенантность, реагирование на инциденты.
*   [Calico: HostEndpoint и GlobalNetworkPolicy](../../Security/network_policies/Calico/index.md) — расширенные возможности Calico.
*   [Наблюдаемость сетевого стека](./kubernetes_network_observability.md) — мониторинг, метрики, алерты.
*   [Production Hardening сети](./production_network_hardening.md) — production-ready конфигурация.
