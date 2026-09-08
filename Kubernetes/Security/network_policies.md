# NetworkPolicy: Сетевая безопасность и изоляция подов

**NetworkPolicy** является фундаментальным инструментом обеспечения безопасности в Kubernetes, реализующим принципы микросегментации и архитектуры нулевого доверия (Zero Trust Architecture, ZTA) на сетевом уровне.

> Полное руководство по технической реализации находится в **[NetworkPolicy: Навигатор](../Networking/Network/network_policy.md)**.

## Определения

**NetworkPolicy** — ресурс Kubernetes (API-группа `networking.k8s.io`), позволяющий декларативно управлять сетевым трафиком на уровнях L3 (сетевой) и L4 (транспортный) модели OSI. Работает по принципу «разрешительных списков» (allow-lists).

*   **Изоляция (Isolation):** Состояние пода, при котором его сетевой стек переходит в режим «запрещено по умолчанию». Активируется, когда под выбирается селектором хотя бы одной политики.
*   **Default Deny (Запрет по умолчанию):** Стратегия безопасности, при которой любой трафик, не разрешенный явно, блокируется. База для построения защищенных сред.
*   **Микросегментация:** Технология разделения сети на мелкие изолированные сегменты (вплоть до уровня отдельного пода) для минимизации рисков.
*   **AdminNetworkPolicy (ANP):** Расширение API (v1alpha1+), позволяющее администраторам кластера задавать глобальные правила безопасности, которые имеют приоритет над политиками в пространствах имен.
*   **BaselineAdminNetworkPolicy (BANP):** Глобальная политика «последнего шанса», применяемая, если трафик не был разрешен или запрещен ANP или обычными NetworkPolicy.
*   **CNI (Container Network Interface):** Интерфейс взаимодействия Kubernetes с сетевыми плагинами. Именно CNI-плагин (Cilium, Calico, Antrea) несет ответственность за техническую реализацию правил NetworkPolicy.
*   **East-West трафик:** Взаимодействие между подами внутри кластера. Составляет до 80% трафика современных сред и является основной целью микросегментации.
*   **North-South трафик:** Трафик между кластером и внешними сетями.

## Основные концепции

### Сетевая безопасность и стратегия защиты

В стандартной модели Kubernetes сеть является «плоской» (flat network), где любой под может инициировать соединение с любым другим подом. С точки зрения безопасности это создает критическую уязвимость: при компрометации одного пода злоумышленник получает возможность беспрепятственного сканирования и атаки всей внутренней инфраструктуры.

**Ключевые цели внедрения NetworkPolicy:**
1.  **Минимизация радиуса поражения (Blast Radius):** Ограничение возможности «бокового перемещения» (lateral movement) атакующего внутри кластера.
2.  **Защита конфиденциальных данных:** Изоляция баз данных и внутренних API от публичных сегментов сети.
3.  **Соответствие комплаенсу:** Выполнение требований стандартов (PCI DSS, HIPAA, NIST, SOC 2, ISO 27001, DISA STIG) по разделению сред (Segmentation) и контролю доступа.
4.  **Укрепление безопасности (Hardening):** Применение принципа наименьших привилегий (Least Privilege) к сетевым взаимодействиям.

### Модель нулевого доверия (Zero Trust) в Kubernetes

В мультитенантных средах внедрение NetworkPolicy должно следовать модели **Default Deny**, так как по умолчанию сеть в Kubernetes открыта для всех подов. Это критически важно для изоляции тенантов друг от друга.

1.  **Блокировка по умолчанию:** Создание политики, запрещающей весь входящий и исходящий трафик в Namespace. Это «нулевой рубеж» защиты.
2.  **Точечное разрешение:** Явное описание только тех соединений, которые необходимы для работы приложения (например, доступ к БД на порту 5432).
3.  **Изоляция инфраструктуры:** Ограничение доступа к системным компонентам (API-серверу, etcd, Kubelet) со стороны прикладных подов тенанта.

### Иерархия политик: Admin vs Developer

С появлением **AdminNetworkPolicy (ANP)** и **BaselineAdminNetworkPolicy (BANP)** сетевая безопасность становится многоуровневой:
*   **Глобальный уровень (Security Team):** Использование ANP для принудительного исполнения правил организации (например, запрет доступа из DMZ-зон во внутренние сети или обязательное разрешение трафика для мониторинга), которые разработчики не могут изменить.
*   **Уровень приложения (DevOps/Developers):** Использование стандартных NetworkPolicy для настройки специфических взаимодействий внутри микросервисного приложения.

### Взаимодействие с Service Mesh

NetworkPolicy (L3/L4) и Service Mesh (L7) дополняют друг друга в эшелонированной защите:
*   **NetworkPolicy:** Обеспечивает грубую изоляцию на уровне IP/портов. Защищает от атак на транспортном уровне и несанкционированного доступа к TCP-портам.
*   **Service Mesh (Istio/Linkerd):** Обеспечивает тонкую авторизацию на уровне HTTP-путей/методов, шифрование трафика (mTLS) и проверку идентичности на базе сертификатов.
*   **Рекомендация:** Используйте NetworkPolicy как базовый слой защиты, даже если в кластере развернут Service Mesh.

### Защита API-сервера и Control Plane

API-сервер Kubernetes является критически важным компонентом. Для его защиты необходимо сочетание нескольких механизмов:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Защита API-сервера                            │
├─────────────────────────────────────────────────────────────────┤
│ 1. NetworkPolicy: ограничение доступа к порту 6443/TCP         │
│    только с Management-хостов и jump-узлов                      │
│ 2. RBAC: отзыв прав cluster-admin у неадминистративных SA       │
│ 3. Audit Policy: логирование всех запросов к API               │
│ 4. Certificates: валидация клиентских сертификатов              │
│ 5. Rate Limiting: защита от DoS на уровне API-сервера           │
└─────────────────────────────────────────────────────────────────┘
```

**Пример политики для защищенных рабочих станций:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: restrict-api-server-access
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: kube-apiserver
  policyTypes:
  - Ingress
  ingress:
  - from:
    - ipBlock:
        cidr: 10.0.1.0/24
      except:
      - 10.0.1.50/32
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: management
      podSelector:
        matchLabels:
          app: bastion
    ports:
    - protocol: TCP
      port: 6443
```

### Модель угроз (Threat Model) для сетевой безопасности

Понимание типов атак, которые mitigates NetworkPolicy, помогает правильно проектировать границы безопасности:

| Угроза | Описание | Как NetworkPolicy помогает |
| :--- | :--- | :--- |
| **Lateral Movement** | Злоумышленник, захватив один под, сканирует внутреннюю сеть | Default Deny + явное разрешение только необходимых соединений |
| **SSRF (Server-Side Request Forgery)** | Под атакует внутренние сервисы (metadata API, etcd) | Ограничение Egress только доверенным адресами |
| **Эксфильтрация данных** | Утечка данных через несанкционированный исходящий трафик | Egress-политики с allow-listing |
| **Атака на базы данных** | Прямой доступ к БД минуя приложение | Разрешение подключения только от SA приложения |
| **Compromised Container Escape** | Контейнер пытается выйти в сеть хоста | hostNetwork isolation + NetworkPolicy для узлов |

## Практические сценарии

### 1. Реализация стратегии Default Deny

Базовая политика безопасности, которую рекомендуется применять ко всем новым Namespace:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: my-app
spec:
  podSelector: {} # Выбирает все поды в Namespace
  policyTypes:
  - Ingress
  - Egress
  # Секции ingress и egress отсутствуют, что означает "запретить всё"
```

### 2. Защита баз данных и ограничение доступа

Разрешение доступа к базе данных только от конкретного бэкенда:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-access-policy
  namespace: data-layer
spec:
  podSelector:
    matchLabels:
      app: postgres
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          environment: production
      podSelector:
        matchLabels:
          app: backend
    ports:
    - protocol: TCP
      port: 5432
```

### 3. Ограничение внешнего доступа (Egress)

Разрешение исходящего трафика только в определенный внешний сегмент (например, API платежного шлюза) и к CoreDNS:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: restricted-egress
spec:
  podSelector:
    matchLabels:
      app: payment-service
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 203.0.113.0/24 # IP внешнего шлюза
  - to:
    - podSelector:
        matchLabels:
          k8s-app: kube-dns
      namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
```

### 4. Защита от SSRF-атак

Блокировка доступа к чувствительным эндпоинтам (metadata API, link-local адреса) с помощью ANP или Egress-политик:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prevent-ssrf
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 169.254.169.254/32
        - 169.254.0.0/16
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

### 5. Сегментация для compliance (PCI DSS, HIPAA, SOC 2, ISO 27001)

Стандарты PCI DSS, HIPAA, SOC 2, ISO 27001, NIST SP 800-53 и DISA STIG предъявляют жесткие условия к разделению сред (Segmentation). NetworkPolicy является ключевым инструментом реализации этих требований в Kubernetes.

**Архитектура сегментации:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                            │
│                                                                     │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │  Public Zone    │    │  App Zone       │    │  Data Zone      │  │
│  │  (Ingress GW)   │◄──►│  (Services)     │◄──►│  (Databases)    │  │
│  │                 │    │                 │    │                 │  │
│  │  NS: ingress    │    │  NS: auth       │    │  NS: postgres   │  │
│  │  NS: monitoring │    │  NS: api        │    │  NS: redis      │  │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘  │
│         │                       │                       │            │
│         └───────────────────────┼───────────────────────┘            │
│                                 ▼                                    │
│                    ┌─────────────────────┐                          │
│                    │  Engineering Net    │                          │
│                    │  (Bastion, CI/CD)   │                          │
│                    └─────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
```

**Пример политики для Data Zone (базы данных):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: data-zone-deny-all
  namespace: data
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
```

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-app-to-postgres
  namespace: data
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: api
      podSelector:
        matchLabels:
          app: api-backend
    ports:
    - protocol: TCP
      port: 5432
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: auth
      podSelector:
        matchLabels:
          app: auth-service
    ports:
    - protocol: TCP
      port: 5432
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
```

**Политика для Engineering Net (доступ к инфраструктуре):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-engineering-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: prometheus
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          network/zone: engineering
      podSelector:
        matchLabels:
          app: ci-runner
    ports:
    - protocol: TCP
      port: 9090
```

**Ключевые требования compliance:**
1.  **Default Deny:** Каждый namespace должен иметь политику, запрещающую весь трафик по умолчанию.
2.  **Явное разрешение:** Доступ к данным разрешается только после явного указания источника и порта.
3.  **Изоляция инструментов:** CI/CD раннеры и bastion-хосты размещаются в отдельных namespace/зонах с ограниченным доступом.
4.  **Аудит:** Используйте CNI-плагины (Cilium, Calico) для логирования всех блокировок и разрешенных соединений.

### 6. Изоляция сервисов через namespace

Паттерн «один сервис — один namespace» упрощает администрирование и реформацию кластера:

*   **Сетевые политики:** Каждый namespace имеет собственную NetworkPolicy, разрешающую трафик только от инфраструктурных компонентов (Ingress Controller, Prometheus, Argo CD).
*   **Resource Quota:** Ограничения на CPU/memory применяются per-namespace, что предотвращает «соседство» шумного сервиса с критичным.
*   **RBAC:** ServiceAccount для сервиса существует только в его namespace, что снижает радиус поражения при компрометации.

```yaml
# values.yaml для приложения
namespace:
  create: true
  name: auth-service

networkPolicy:
  enabled: true
  allowIngress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
  allowEgress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: database
      ports:
        - protocol: TCP
          port: 5432
```

### 7. Мультитенантная изоляция (Multi-Tenancy)

Для организаций, консолидирующих несколько команд в одном кластере, NetworkPolicy обеспечивает программную (Soft) изоляцию между тенантами:

```yaml
# Тенант A может общаться только с базой данных тенанта A
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tenant-a-isolation
  namespace: tenant-a
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          tenant: a
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          tenant: a
    - namespaceSelector:
        matchLabels:
          app: postgres
        matchLabels:
          tenant: a
```

**Принципы изоляции тенантов:**
1.  **Default Deny per Namespace:** Каждый namespace тенанта имеет политику, запрещающую весь трафик.
2.  **Явное межтенантное взаимодействие:** Трафик между тенантами разрешается только через явно определенные API Gateway или Shared Services.
3.  **Изоляция инфраструктуры:** Тенанты не имеют доступа к namespace системных компонентов (kube-system, kube-public).

### 8. Защита от утечки данных (Data Exfiltration)

Для сред, обрабатывающих чувствительные данные, Egress-политики должны ограничивать исходящий трафик:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: data-exfiltration-prevention
  namespace: payment-processing
spec:
  podSelector:
    matchLabels:
      app: payment-service
  policyTypes:
  - Egress
  egress:
  # Разрешить доступ только к шлюзу платежей
  - to:
    - ipBlock:
        cidr: 203.0.113.0/24
    ports:
    - protocol: TCP
      port: 443
  # Разрешить DNS
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
  # Запретить все остальное
```

## Compliance mapping

NetworkPolicy напрямую поддерживает требования регуляторных стандартов:

| Стандарт | Требование | Как NetworkPolicy помогает |
| :--- | :--- | :--- |
| **PCI DSS v4.0** | Requirement 1.3 — Segregation of networks | Default Deny + явное разрешение только CDE-сегментам |
| **HIPAA** | 164.312(e)(1) — Integrity controls | Изоляция хостов PHI от публичных сегментов |
| **SOC 2** | CC6.1 — Network security | Микросегментация приложений и баз данных |
| **ISO 27001:2022** | A.8.15 — Logging and monitoring | Аудит сетевого трафика через CNI (Hubble, Calico Flow Logs) |
| **NIST SP 800-53** | SC-7 — Boundary protection | Egress/Ingress фильтрация на уровне пода |
| **DISA STIG** | KNE-01-002 — Network policy enforcement | Default Deny + явное разрешение только необходимых портов |

## Диагностика и устранение неполадок

### Типичные симптомы

| Симптом | Возможная причина | Метод диагностики |
| :--- | :--- | :--- |
| Под не может выйти в интернет | Отсутствует Egress-политика для DNS или внешних адресов | `kubectl exec <pod> -- curl -v http://example.com` |
| Под не видит ServiceClusterIP | Отсутствует разрешение на доступ к CIDR сервисов | `kubectl describe svc <service>` + проверка Egress |
| Внешний IP блокируется | `ipBlock` не содержит CIDR или SNAT заменяет IP | `externalTrafficPolicy: Local` или разрешение CIDR узлов |
| DNS не работает | Не разрешен порт 53 UDP/TCP к kube-dns | Проверить Egress-политики namespace |
| Под игнорирует политику | CNI не поддерживает NetworkPolicy (Flannel) | `kubectl get networkpolicy` + проверка CNI |

### Команды диагностики

```bash
# 1. Проверка что CNI поддерживает NetworkPolicy
kubectl get crd networkpolicies.networking.k8s.io
# → NAME                                    CREATED AT
# → networkpolicies.networking.k8s.io        2024-01-01T00:00:00Z

# 2. Проверка что политики применяются на конкретный под
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy <policy-name> -n <namespace>

# 3. Проверка DROP-пакетов через Cilium/Hubble
hubble observe --type drop --namespace <namespace>

# 4. Проверка связности изнутри пода
kubectl exec -it <pod> -- curl -v http://<target-service>:<port>
kubectl exec -it <pod> -- nslookup <service-name>
kubectl exec -it <pod> -- nc -zv <target-ip> <port>

# 5. Проверка SNAT и Source IP
kubectl get endpoints <service> -o wide
kubectl describe node <node> | grep -i "internalIP"
```

### Политики и их конфликты

При наличии нескольких NetworkPolicy, выбирающих один под, работает принцип аддитивности (логическое «ИЛИ» между всеми правилами). Однако ANP имеет приоритет и может блокировать трафик, разрешенный обычными политиками.

**Алгоритм проверки:**
1.  Собрать все NetworkPolicy, выбирающие целевой под.
2.  Проверить наличие ANP с действием `Deny` для данного трафика.
3.  Проверить, разрешен ли трафик хотя бы одной политикой Tier 2.
4.  Проверить BANP: если трафик не разрешен на Tier 2, применяется политика по умолчанию.

## Сравнение методов изоляции

| Метод | Уровень | Stateful | Гибкость | Производительность | Когда использовать |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NetworkPolicy** | L3/L4 | Да | Средняя | Зависит от CNI | Стандартная изоляция подов |
| **AdminNetworkPolicy** | L3/L4 | Да | Низкая (глобальная) | Зависит от CNI | Обязательные правила безопасности |
| **BaselineAdminNetworkPolicy** | L3/L4 | Да | Низкая (defaults) | Зависит от CNI | Политики "последнего шанса" |
| **CiliumNetworkPolicy** | L3-L7 | Да | Высокая | Высокая (eBPF) | FQDN, L7, расширенная наблюдаемость |
| **Calico GlobalNetworkPolicy** | L3/L4 | Да | Высокая | Высокая | Защита узлов, глобальные правила |
| **Service Mesh (Istio)** | L7 | Да | Максимальная | Средняя (sidecar) | mTLS, авторизация HTTP, трассировка |

## Рекомендации по безопасности

1.  **Всегда начинайте с Default Deny:** Никогда не оставляйте namespace без политики, запрещающей весь трафик по умолчанию.
2.  **Минимизируйте Egress-разрешения:** Чем меньше исходящих адресов разрешено, тем ниже риск эксфильтрации.
3.  **Используйте AdminNetworkPolicy для критичных правил:** Правила, которые не должны быть переопределены разработчиками, реализуйте через ANP.
4.  **Защищайте kube-system:** Namespace `kube-system` должен иметь строгие политики, запрещающие доступ со стороны прикладных подов.
5.  **Не полагайтесь только на NetworkPolicy:** Это один из слоев Defense in Depth. Сочетайте с RBAC, mTLS, Audit и Runtime Security (Falco, Tetragon).
6.  **Валидируйте политики в CI/CD:** Используйте `conftest`, `kubewarden` или `OPA Gatekeeper` для проверки манифестов перед применением.
7.  **Мониторьте отклонения трафика:** Настройте алерты на необычные попытки соединений, которые могут указывать на компрометацию.
8.  **Тестируйте изоляцию:** Регулярно проверяйте, что политики работают как ожидается, используя `kubectl network-policy` или инструменты Chaos Engineering (e.g., Chaos Mesh).

### Интеграция с RBAC для сетевой безопасности

NetworkPolicy и RBAC работают вместе для построения эшелонированной защиты:

*   **RBAC управляет «кто может создавать/изменять политики»:** Только администраторы кластера должны иметь права на `create`/`update`/`patch` ресурсов `NetworkPolicy` в критичных namespace.
*   **NetworkPolicy управляет «какой трафик разрешен»:** RBAC не влияет на сетевое соединение, но контролирует конфигурацию политик.
*   **Аудит изменений:** Используйте Kubernetes Audit Log для отслеживания изменений в NetworkPolicy, особенно в namespace с чувствительными данными.

#### Комбинированный пример: RBAC + NetworkPolicy для production

Полный сценарий: изоляция приложения с контролем доступа на двух уровнях.

**Уровень 1 — RBAC (кто может управлять политиками):**

```yaml
# Только Platform-команда может создавать NetworkPolicy в production
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: network-admin
  namespace: production
rules:
- apiGroups: ["networking.k8s.io"]
  resources: ["networkpolicies"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
# Разработчики — только чтение
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: network-viewer
  namespace: production
rules:
- apiGroups: ["networking.k8s.io"]
  resources: ["networkpolicies"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: platform-network-admin
  namespace: production
subjects:
- kind: Group
  name: platform-team
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: network-admin
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: dev-network-viewer
  namespace: production
subjects:
- kind: Group
  name: developers
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: network-viewer
  apiGroup: rbac.authorization.k8s.io
```

**Уровень 2 — NetworkPolicy (какой трафик разрешен):**

```yaml
# Default Deny: запретить весь входящий и исходящий трафик
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
# Разрешить трафик только между подами с лейблом app=backend
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-backend-internal
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
          app: backend
    ports:
    - protocol: TCP
      port: 8080
---
# Разрешить backend доступ к DNS и внешним API
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-backend-egress
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Egress
  egress:
  - to: []
    ports:
    - protocol: UDP
      port: 53    # DNS
  - to: []
    ports:
    - protocol: TCP
      port: 443   # HTTPS к внешним API
```

**Результат:** Даже если разработчик имеет RBAC-доступ к подам, сетевые политики не позволят трафику проходить через разрешённые RBAC-границы. Это эшелонированная защита (Defense in Depth).

### Инструменты валидации и тестирования

| Инструмент | Назначение | Пример использования |
| :--- | :--- | :--- |
| **conftest** | Валидация YAML/JSON через Rego-политики | `conftest test network-policy.yaml` |
| **kubewarden** | Admission Webhook для валидации ресурсов | Блокировать создание политик с `0.0.0.0/0` в Egress |
| **OPA Gatekeeper** | Policy as Code для Kubernetes | Ограничение разрешения только портов 443/80 |
| **kubectl network-policy** | Проверка применяемых политик | `kubectl network-policy accept --all` |
| **Cilium Hubble** | Визуализация и отладка трафика | `hubble observe --type drop` |

### Мониторинг и алертинг

Настройте мониторинг для обнаружения аномалий сетевого трафика:

```bash
# Пример алерта: под пытается установить соединение с metadata API
hubble observe --namespace payment --type drop | grep "169.254.169.254"

# Пример алерта: неожиданный Egress в неизвестный CIDR
hubble observe --type allow --namespace production | grep -v "allowed-cidr"
```

**Рекомендации по алертам:**
1.  **Blocked connections to metadata API:** Любые попытки доступа к `169.254.169.254` из подов.
2.  **New egress destinations:** Появление нового CIDR в разрешенном Egress-трафике.
3.  **Policy changes:** Любые изменения NetworkPolicy в критичных namespace (data, payment, kube-system).
4.  **Policy violations spike:** Резкий рост количества DROP-пакетов, что может указывать на активное сканирование сети.

### Сценарий: Реагирование на инцидент (Lateral Movement)

При обнаружении компрометации пода NetworkPolicy является ключевым инструментом для containment:

```bash
# 1. Изолировать компрометированный под (быстрый ответ)
kubectl label pod <compromised-pod> quarantine=true -n production
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: quarantine-pod
  namespace: production
spec:
  podSelector:
    matchLabels:
      quarantine: "true"
  policyTypes:
  - Ingress
  - Egress
EOF

# 2. Проверить попытки бокового перемещения
kubectl logs -l app=network-policy-controller | grep "<compromised-pod-ip>"
```

**Подробнее:** Полные сценарии реагирования на инциденты, включая карантин подов, сбор forensics и ликвидацию последствий, описаны в [Реагирование на инциденты безопасности](./incident_response.md).

## Дополнительная информация

### Наблюдаемость и аудит сетевого трафика

Стандартные NetworkPolicy Kubernetes не поддерживают логирование блокировок (Deny logs). Для обеспечения безопасности и расследования инцидентов необходимо использовать возможности CNI:
*   **Cilium:** Позволяет просматривать Deny-события через Hubble.
*   **Calico:** Поддерживает Flow Logs и логирование политик.
*   **Policy Reporter:** Визуализация результатов работы политик и нарушений безопасности.
*   **Tetragon:** Блокировка подозрительной активности на уровне системных вызовов до отправки пакета в сеть.

### Важные соображения безопасности
*   **Поддержка CNI:** Убедитесь, что выбранный сетевой плагин (Cilium, Calico, Antrea) поддерживает NetworkPolicy. Flannel в чистом виде их игнорирует.
*   **Localhost:** Трафик внутри пода (между контейнерами) через `127.0.0.1` не фильтруется политиками.
*   **Source IP Preservation:** При использовании Ingress-контроллеров или NodePort может происходить замена IP источника (SNAT), что делает фильтрацию по `ipBlock` в `ingress` некорректной без специальной настройки (`externalTrafficPolicy: Local`).
*   **HostNetwork:** Поды с `hostNetwork: true` обычно не подчиняются NetworkPolicy, так как используют сетевое пространство имен хоста.
*   **IPv6:** Поддержка IPv6 в NetworkPolicy зависит от реализации CNI и конфигурации Dual-stack кластера.

**Связанные темы:**
* [NetworkPolicy: Лучшие практики](../Networking/Network/NetworkPolicy/best_practices.md) — детальные советы по эксплуатации.
* [NetworkPolicy: Логика правил](../Networking/Network/NetworkPolicy/rule_logic.md) — логические операторы и аддитивность.
* [NetworkPolicy: Реализация CNI](../Networking/Network/NetworkPolicy/cni_implementation.md) — архитектура enforcement.
* [Cilium: eBPF и сетевая безопасность](../Networking/Network/CNI/cilium.md) — современный подход к защите.
* [Calico и глобальные политики](./network_policies/Calico/index.md) — управление кластерным уровнем.
* [Мультитенантность в Kubernetes](../Concepts/multi-tenancy.md) — стратегии изоляции tenants.
* [Сетевая сегментация и микросегментация](../../Networking/Concepts/network_segmentation_and_microsegmentation.md) — теория Zero Trust сегментации.
* [Аудит в Kubernetes](../Security/audit.md) — логирование и compliance.
* [Безопасность Service Mesh](../../Service_Mesh/service_mesh_concepts.md) — защита на прикладном уровне.
* [Интеграция внешних файрволов](../Security/external_firewall_integration.md) — North-South защита.
