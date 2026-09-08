# Мульти-тенантность в Kubernetes

## Введение и контекст 2026 года

**Мульти-тенантность (multi-tenancy)** — это архитектурная модель, при которой один физический кластер Kubernetes разделяется между несколькими независимыми тенантами. 

Причина роста актуальности — проблема **cluster sprawl** (разрастание кластеров). Когда организации создают по кластеру на каждую команду, операционные расходы и затраты на Control Plane растут бесконтрольно. Консолидация в мультитенантные кластеры позволяет:
*   **Оптимизировать FinOps**: Значительное снижение расходов на плоскость управления и облачную инфраструктуру.
*   **Унифицировать безопасность**: Применение согласованных политик изоляции вместо разрозненных конфигураций.
*   **Масштабировать платформу**: Переход к модели «Cluster-as-a-Service» или «Namespace-as-a-Service».

---

## Определения и базовые концепции

| Термин | Определение |
| :--- | :--- |
| **Тенант (Tenant)** | Команда, проект, окружение или внешний клиент, выступающий изолированной единицей владения и управления. В Kubernetes «тенанта» как нативного объекта нет — его роль, как правило, выполняет один или несколько `Namespace` (+ связанные с ним политики). |
| **Мульти-тенантность (Multi-tenancy)** | Совместное использование одного физического кластера несколькими независимыми тенантами с разграничением доступа, ресурсов и сети. |
| **Soft tenancy (Программная изоляция)** | Логическая изоляция через `Namespace` + RBAC. Тенанты считаются **кооперативными** (внутренние команды), изоляция защищает от случайных ошибок, а не от злонамеренных действий. |
| **Hard tenancy (Аппаратная изоляция)** | Изоляция на уровне инфраструктуры или рантайма (выделенные узлы, кластеры, изолированные среды выполнения). Тенанты считаются **враждебными/взаимонепроверенными** (внешние клиенты). |
| **Вертикальная tenancy (Multi-team)** | Много команд внутри **одной** организации делят кластер; центральный администрирующий орган (Platform Team) управляет общими ресурсами. |
| **Горизонтальная tenancy (Multi-customer)** | Предоставление сервиса многим **внешним** независимым клиентам (SaaS); требования к изоляции существенно жёстче. |
| **Cooperative tenants (Кооперативные тенанты)** | Доверяют друг другу в целом, но могут случайно помешать через контенцию за ресурсы или неверную конфигурацию. |
| **Hostile tenants (Враждебные тенанты)** | Не доверяют друг другу; изоляция должна выдерживать целенаправленные атаки и «шумного соседа». |

**Ключевая идея:** уровень изоляции определяется **моделью доверия** (trust model) и тем, **исполняет ли платформа код, предоставленный сторонними лицами**. Именно эти два фактора, а не сам по себе выбор инструмента, задают требуемую глубину границ. Нельзя «включить» hard tenancy одной лишь конфигурацией `Namespace` — для враждебных тенантов нужны изоляция на уровне Control Plane, сети и среды выполнения.

---

## Модели мультитенантности

Выбор модели зависит от требуемого уровня изоляции и операционных затрат.

### 1. Программная (Soft) tenancy на основе Namespace
*   **Контекст:** Внутренние команды одной организации с определенным уровнем взаимного доверия.
*   **Изоляция:** Логическая через `Namespaces` и `RBAC`.
*   **Цель:** Предотвращение случайных ошибок и разграничение зон ответственности.
*   **Инструменты:** Стандартные объекты Kubernetes, `NetworkPolicies`, `ResourceQuotas`.

### 2. Виртуальные кластеры (vCluster)
*   **Контекст:** Тенантам нужен полный контроль над API (`Cluster Admin`), свои `CRD` или операторы, но выделенные кластеры слишком дороги.
*   **Изоляция:** Каждый тенант получает собственный API-сервер и etcd, работающие как нагрузки внутри Namespace хост-кластера.
*   **Инструмент:** **[vcluster](../ToolsUtilities/vcluster/vcluster_overview.md)**.

### 3. Выделенные кластеры (Hard Tenancy)
*   **Контекст:** Враждебные тенанты (внешние клиенты), жесткие требования комплаенса или критические Prod-окружения.
*   **Изоляция:** Уровня инфраструктуры (выделенные узлы и Control Plane) или среды выполнения.
*   **Инструменты:** Изолированные кластеры, **gVisor**, **Kata Containers**.

### Сравнительная таблица моделей

| Критерий | Namespace (Soft) | Capsule | vcluster | Выделенный кластер |
| :--- | :--- | :--- | :--- | :--- |
| **Стоимость** | Низкая | Низкая | Средняя | Высокая |
| **Операционные издержки** | Низкие | Средние | Средние | Высокие |
| **Изоляция Control Plane** | Нет (общий) | Нет (общий) | Да (собственный API/etcd) | Да (полная) |
| **Изоляция CRD / кастомных контроллеров** | Нет | Нет | Да | Да |
| **Изоляция узлов** | Нет | Нет | Только через Private Nodes/taints | Да |
| **Разные версии K8s у тенантов** | Нет | Нет | Да | Да |
| **Self-service тенанта** | Ограничен | Хороший | Полный | Полный |
| **Рекомендуется** | Внутренние доверенные команды | Namespace-as-a-Service, согласованные квоты/политики | SaaS с внешними клиентами, потребность в CRD | Регулируемые/враждебные тенанты |

**Практическое правило:** мягкая (namespace/Capsule) и виртуальная (vcluster) модели обычно **комбинируют** в одном кластере — namespace для внутренних dev-команд, vcluster для внешних SaaS-клиентов или комплаенс-нагрузок, выделенные кластеры — лишь для единичных критически регулируемых тенантов. Гибрид чаще правильнее, чем «что-то одно на всё».

---

## Четыре обязательных слоя изоляции

Безопасность общего кластера определяется прочностью самого слабого уровня.

### 1. Логическая изоляция и доступ (Control Plane)

Общий Control Plane (`kube-apiserver`, `etcd`) — самая критичная точка отказа. Его повреждение или перегрузка влияет на **всех** тенантов сразу, поэтому первый же слой — защита общего API-сервера и `etcd`.

*   **Пространства имён ([`Namespaces`](../Base/namespace.md))**: Фундаментальный механизм разделения объектов. Имя должно быть уникальным по всему парку кластеров (см. [Проектирование Namespace](#проектирование-namespace-фундамент)), т.к. `Namespace` — кластерный ресурс.
*   **Контроль доступа ([`RBAC`](../Security/rbac/rbac_overview.md))**:
    *   **Platform Team**: Права `cluster-admin`.
    *   **Team Leads**: Администраторы своего Namespace.
    *   **Developers**: Права на деплой и отладку, запрет на изменение RBAC и квот.
    *   **Жёсткое правило:** тенантам **никогда** не выдаются `cluster-admin` и не создаются `ClusterRoleBinding` на тенантные группы — только `Role`/`RoleBinding` в границах их `Namespace`. Это ограничивает область воздействия до конкретного пространства имён.
*   **Защита кластерной периферии**: в `kube-system`, `kube-public`, `metrics-server` (и любых платформенных `Namespace`) доступ должен быть ограничен только Platform Team. Отключите анонимный/неаутентифицированный доступ (`--anonymous-auth=false` для пользователей, либо `system:unauthenticated` → запрещающая `ClusterRoleBinding`), чтобы внешние запросы не получали лишних прав.
*   **API Priority and Fairness (APF)**: Защита API-сервера от перегрузки запросами одного тенанта, предотвращая отказ для всего кластера. Сгруппируйте тенантов в `FlowSchema`/`PriorityLevelConfiguration` с лимитами запросов, чтобы один «шумный» тенант не исчерпал весь бюджет API. Пример базовой сегрегации:

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: tenant-critical
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 20
    limitResponse:
      type: Reject
```

#### Проверка прав доступа (RBAC)

Проверить, что у конкретного пользователя/группы есть (или нет) доступ, не заходя в манифесты:

```bash
# Условный запрос: может ли пользователь создать под в namespace payment-prod
kubectl auth can-i create pods --as=alice --namespace=payment-prod
# → yes

# Может ли пользователь менять RBAC/квоты (запрещено разработчикам)
kubectl auth can-i create resourcequotas --as=alice --namespace=payment-prod
# → no

# Сводка прав пользователя
kubectl auth can-i --list --as=alice --namespace=payment-prod
```

Ключевая проверка мульти-тенанта — подтвердить, что у тенанта **нет** доступа к чужим `Namespace` (`kubectl auth can-i list pods --namespace=other-team-prod --as=alice` должно вернуть `no`).

### 2. Изоляция ресурсов (Data Plane)
Защита от проблемы «шумного соседа» (noisy neighbor).
*   **Квоты ([`ResourceQuota`](../Scheduling/qos_limit_and_requests.md))**: Ограничение суммарного потребления CPU/RAM в Namespace. **Важное следствие:** если в Namespace установлена квота на `requests.cpu`/`requests.memory`, то **каждый** под обязан объявить `requests` — иначе создание будет отклонено. Именно поэтому квоты всегда сочетают со `LimitRange`, который подставляет значения по умолчанию.
*   **Диапазоны лимитов (`LimitRange`)**: Автоматическая установка `requests/limits` по умолчанию для контейнеров, а также `min`/`max`-ограничений.
*   **Приоритеты ([PriorityClass](../Scheduling/qos_limit_and_requests.md))**: Гарантируют вытеснение менее важных задач (Dev) в пользу критических (Prod) при нехватке ресурсов. Квоты можно привязать к приоритету через `scopeSelector` (`priorityClassName`), разделяя бюджет для Prod и Dev тенантов.
*   **Изоляция узлов (Node Isolation)**: Использование `taints` и `tolerations` для выделения физических серверов под конкретных тенантов (например, изолировать Prod-узлы от Dev-нагрузок).

#### Квоты на количество объектов — защита etcd

Помимо CPU/RAM, крайне важно ограничивать **число объектов** в Namespace: строго говоря, каждый `Secret`, `ConfigMap`, `Service`, `Pod` (и ресурсы CRD) хранятся в `etcd` и потребляют память API-сервера. Без потолка «расплодившийся» тенант может деградировать весь кластер (рост базы, замедление `etcd`, сбои старта kubelet). Используйте `count/<ресурс>.<группа>` (общий синтаксис) или специализированные ключи (`secrets`, `configmaps`, `pods`, `services` и т.д.):

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: object-counts
  namespace: payment-prod
spec:
  hard:
    count/pods: "100"
    count/services: "30"
    count/secrets: "100"          # Secret хранятся в etcd — жёсткий лимит обязателен
    count/configmaps: "50"
    count/persistentvolumeclaims: "20"
    count/deployments.apps: "30"
    count/jobs.batch: "20"         # защита от CronJob, «заваливающего» namespace job-ами
```

#### Пример полной конфигурации ресурсов Namespace

```yaml
# 1) LimitRange — значения по умолчанию и min/max для подов
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: payment-prod
spec:
  limits:
  - type: Container
    default:                      # limits по умолчанию
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:               # requests по умолчанию
      cpu: "250m"
      memory: "256Mi"
    max:
      cpu: "4"
      memory: "8Gi"
    min:
      cpu: "25m"
      memory: "64Mi"
```
```yaml
# 2) ResourceQuota — суммарные лимиты CPU/RAM + объекты
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute-and-counts
  namespace: payment-prod
spec:
  hard:
    requests.cpu: "20"
    requests.memory: "40Gi"
    limits.cpu: "40"
    limits.memory: "80Gi"
    pods: "100"
    count/secrets: "100"
    count/configmaps: "50"
```

Проверка потребления и лимитов:

```bash
kubectl describe quota compute-and-counts -n payment-prod
kubectl get resourcequota -n payment-prod -o yaml
```

> `LimitRange` применяется только к **новым** подам; существующие сохраняют исходные спецификации до перезапуска. Учтите это при деплое изменённых лимитов.

### 3. Сетевая изоляция
По умолчанию сеть в Kubernetes **«плоская» (Default Allow)** — любой под может соединиться с любым другим подом в любом Namespace. Для изоляции тенантов это недопустимо, поэтому сетевые политики — обязательный слой.
*   **Сетевые политики ([`NetworkPolicy`](../Security/network_policies.md))**: L3/L4 фильтрация (`networking.k8s.io`). Обязателен подход **Default Deny** (запрет всего трафика, кроме явно разрешенного). **Важно:** политики реализует CNI-плагин — Flannel в чистом виде их игнорирует; нужны Cilium, Calico, Antrea или аналоги.
*   **Cilium (eBPF)**: Политики на основе Identity (меток) и прозрачное шифрование; наблюдение за блокировками (Hubble).
*   **Service Mesh (Istio/Linkerd)**: Строгий mTLS и авторизация на уровне L7 (поверх L3/L4 политик).

#### Базовый паттерн «Default Deny» в тенантном Namespace

Минимум для каждого тенанта — три политики:

```yaml
# 1) Полный запрет по умолчанию
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: payment-prod
spec:
  podSelector: {}                 # применяется ко всем подам namespace
  policyTypes:
  - Ingress
  - Egress
```
```yaml
# 2) Разрешить входящий трафик только из своего namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-in-namespace
  namespace: payment-prod
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: payment-prod
```
```yaml
# 3) Разрешить исходящий трафик к DNS (CoreDNS) и внутри namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-dns
  namespace: payment-prod
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: payment-prod
```

Без этих политик общий паттерн «Default Allow» оставляет тенантные сервисы открытыми друг для друга. Подробные сценарии и сегментация под compliance — в **[NetworkPolicy: сетевая безопасность подов](../Security/network_policies.md)**.

### 4. Изоляция среды выполнения и безопасность нагрузок
*   **Политики безопасности ([`Pod Security Admission`](../Security/pod_security_context.md))**: Принудительное соблюдение профилей (`baseline` или `restricted`). Запрет root-контейнеров и привилегированных режимов.
*   **Policy Engine (Kyverno/OPA)**: Автоматизация проверки образов и конфигураций.
*   **RuntimeClass**: Выбор изолированных рантаймов:
    *   **gVisor (runsc)**: Фильтрация системных вызовов в user-space.
    *   **Kata Containers**: Запуск подов в легковесных микро-ВМ.

#### Включение Pod Security Standards через метку Namespace

PSA (Pod Security Admission) включается **декларативно меткой** на `Namespace` без установки вебхуков — встроенный admission-контроллер `PodSecurity` применяет профиль на трёх уровнях: `enforce` (жёсткий), `warn` (предупреждение), `audit` (лог). Паттерн безопасного внедрения — сначала `warn`/`audit`, затем `enforce`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: payment-prod
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

Уровни профилей: `privileged` (не ограничивает), `baseline` (минимально безопасный, запрет root/привилегированных образов), `restricted` (максимально строгий — обязательны `runAsNonRoot`, незапуск как root, отказ от привилегированных capabilities). Подробности — в **[Security Context и PSA](../Security/pod_security_context.md)**.

---

## Проектирование Namespace: Фундамент

### Правила именования
Рекомендуется паттерн: `<команда>-<окружение>` (например, `payments-production`). Уникальность имен по всему парку кластеров упрощает будущую консолидацию и мультикластерное управление.

### Метки (Labels)
Метки необходимы для атрибуции затрат и работы контроллеров политик.
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: payments-production
  labels:
    team: payments
    environment: production
    cost-centre: "eng-platform-001"
    contact: "payments-team@company.com"
    tier: critical
```

---

## Специализированные контроллеры

### Capsule (Operator)
Обеспечивает модель «Tenant-as-a-Service». Позволяет объединять несколько Namespaces в один логический «Tenant».
*   **Агрегированные квоты**: Лимиты ресурсов на весь набор Namespaces тенанта.
*   **Self-service**: Пользователи могут сами создавать Namespaces внутри своих квот без прав администратора кластера.
```yaml
apiVersion: capsule.clastix.io/v1beta2
kind: Tenant
metadata:
  name: payments-team
spec:
  owners:
  - name: payments-leads
    kind: Group
  namespaceOptions:
    quota: 5
  resourceQuotas:
    scope: Tenant
    items:
    - hard:
        requests.cpu: "20"
        requests.memory: "40Gi"
```

### Hierarchical Namespace Controller (HNC)
Позволяет создавать древовидную иерархию Namespace.
*   **Наследование**: Политики (RBAC, Quotas) автоматически каскадируются от родителя к дочерним пространствам имен.

> **Статус проекта:** репозиторий HNC **архивирован (апрель 2025)** и официально не поддерживается (kubernetes-retired). Идея иерархии и наследования политик полезна как концепция, однако для новых внедрений рекомендуется отдавать предпочтение **Capsule** (агрегирование квот/политик на «тенанта») или **vcluster** (более сильная изоляция). При миграции с HNC наследование RBAC/квот переносим в Capsule, а полноценную изоляцию — во vcluster.

### Virtual Clusters ([vcluster](../ToolsUtilities/vcluster/vcluster_overview.md))
Создание виртуального кластера внутри Namespace хост-кластера.
*   **Изоляция API**: Тенант получает собственный API-сервер и `etcd`.
*   **Полномочия**: Возможность иметь права `Cluster Admin` внутри vcluster, не влияя на основной кластер.

---

## Наблюдаемость и FinOps

### Мониторинг и Логирование
*   **Prometheus/Mimir**: Использование меток `namespace` или `tenant_id`. Изоляция данных через `X-Scope-OrgID`.
*   **Loki**: Разделение прав доступа на уровне источников данных в Grafana.
*   **Мультитенантные дашборды**: в Grafana каждому тенанту — своя организация/фильтр по `namespace`; данные не должны быть доступны тенанту за пределами его `Namespace`.

#### Алерты на приближение к квоте

Чтобы тенанты не упирались в квоту внезапно (поды отклоняются с `403`), оповещайте заранее — например, на основе метрик kube-state-metrics:

```
# PromQL: доля занятой CPU-квоты namespace > 85%
sum(kube_resourcequota{resource="requests.cpu", type="used"})
  / sum(kube_resourcequota{resource="requests.cpu", type="hard"})
  > 0.85
```

### Атрибуция затрат (Kubecost / OpenCost)
Рекомендуется для детального анализа расходов в разрезе тенантов. Позволяет соотнести стоимость инфраструктуры с бизнес-результатами команд.
*   **[Подробнее о Kubecost](../MonitoringLogging/kubecost.md)**.

Для корректной атрибуции затрат критична **единая схема меток** (см. [Метки (Labels)](#метки-labels) ниже): без согласованных `team`/`cost-centre`/`environment` данные FinOps становятся неполными или ошибочными.

---

## Практические сценарии

### Сценарий 1: Изоляция команд разработки
**Задача:** Разделить 5 команд разработки, предотвращая «шумного соседа».
**Решение:**
1. Создать Namespace с метками для каждой команды.
2. Установить `ResourceQuota` и `LimitRange`.
3. Выдать команде namespace-scoped `Role`/`RoleBinding` (без `cluster-admin`).

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-alpha-quota
  namespace: team-alpha
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    pods: "20"
```

Пример RBAC для команды разработки (полный доступ только в свой `team-alpha`, без управления RBAC/квотами):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: team-alpha-developer
  namespace: team-alpha
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log", "services", "configmaps", "secrets",
              "persistentvolumeclaims", "pods/portforward", "pods/exec"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["networking.k8s.io"]
  resources: ["networkpolicies"]
  verbs: ["get", "list", "watch"]      # изменение сетевых политик — только Platform Team
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: team-alpha-developer
  namespace: team-alpha
subjects:
- kind: Group
  name: team-alpha
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: team-alpha-developer
  apiGroup: rbac.authorization.k8s.io
```

Проверка: `kubectl auth can-i get secrets -n team-alpha --as group-team-alpha` → `yes`; `kubectl auth can-i create clusterrolebindings --as group-team-alpha` → `no`.

### Сценарий 2: Разделение сред (Dev/Prod)
**Задача:** Запустить Dev и Prod в одном кластере с разным уровнем критичности.
**Решение:**
1. Разделение по Namespace (`myapp-dev`, `myapp-prod`).
2. Физическая изоляция Prod через `taints` и `tolerations` на выделенных узлах.
3. Использование `PriorityClass` для вытеснения Dev-нагрузок при нехватке ресурсов.
4. Применение `Pod Security Admission` профиля `restricted` для Prod.

### Сценарий 3: Мультитенантность для SaaS-платформы
**Задача:** Изоляция клиентов SaaS-платформы с возможностью кастомизации.
**Решение:**
1. Использование **vcluster** для каждого клиента (изоляция API).
2. Полная сетевая изоляция через `NetworkPolicy` (Default Deny).
3. Выделенные `StorageClass` для разграничения данных.

### Сценарий 4: Индивидуальные стенды разработчиков (Feature Stands)
**Задача:** Самообслуживание стендов для тестирования микросервисов.
**Решение:**
1. Динамическое создание Namespace для каждой фичи.
2. Использование **Capsule** для ограничения общего количества стендов и ресурсов на одного разработчика.
3. Автоматическая генерация уникальных DNS-имен через Ingress.

### Сценарий 5: Онбординг и офбординг тенанта

**Задача:** Быстро подключить новую команду и корректно освободить ресурсы при её уходе (SRE-плейбук).

**Онбординг:**
1. Создать `Namespace` по единому шаблону с обязательными метками (`team`, `environment`, `cost-centre`, `contact`).
2. Применить «стартовый набор» изоляции: `ResourceQuota` + `LimitRange`, `NetworkPolicy` (Default Deny + DNS + внутри-namespace), метки PSA (`warn` → `enforce`).
3. Выдать `Role`/`RoleBinding` группе тенанта; проверить `kubectl auth can-i`.
4. Проверить результат сквозной связностью (см. [Валидация](#валидация-изоляции-и-диагностика) ниже).

**Офбординг (освобождение среды):**
```bash
# Зафиксировать, что удаляем, ДО очистки
kubectl get all -n tenant-x --no-headers | wc -l     # контроль масштаба
kubectl get resourcequota,networkpolicy,limitrange -n tenant-x

# Удалить namespace целиком (вместе с подами, service, pvc, quota, policies)
kubectl delete namespace tenant-x --wait

# При зависшем NS (Finalizer): проверить причины
kubectl get namespace tenant-x -o json | jq '.status.conditions'
```

> Перед удалением сто́ит экспортировать нужные данные/бэкапы PVC и убедиться, что из namespace не удаляются общие (кластерные) ресурсы. Офбординг — хорошее место для GitOps-автоматизации (удаление манифеста в репозитории минус динамические ресурсы).

---

## Валидация изоляции и диагностика

Проверять изоляцию следует регулярно (не только при онбординге), т.к. мульти-тенантность ломается незаметно.

**Права доступа (RBAC):**
```bash
# Должны вернуть "no" — тенант не видит чужие namespace и кластерные объекты
kubectl auth can-i list pods --namespace=other-team-prod --as=alice
kubectl auth can-i create secrets --cluster --as=alice
kubectl auth can-i get nodes --as=alice
```

**Квоты и ресурсы:**
```bash
kubectl describe quota -n payment-prod
kubectl get limitranges -n payment-prod -o yaml
```

**Сетевые политики:**
```bash
kubectl get networkpolicy -n payment-prod
# Проверить, что политики действительно применяются (Cilium): наличие policy-метрик/Cilium Endpoint
kubectl get ciliumendpoint -A   # есть ли изолированные ends
```

**PSA:**
```bash
kubectl get ns payment-prod -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/.\*}'
```

**Проверка изменений без применения (dry-run):**
```bash
kubectl apply --dry-run=server -f policy.yaml   # применит ли admission/квоту
kubectl create --dry-run=server -f pod.yaml -n payment-prod
```

### Типичные ошибки и их причины

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Ошибка создания пода **`exceeded quota: ... 403`** | Превышен `ResourceQuota` или не указаны `requests` при активной CPU/mem квоте. | Поднять квоту либо прописать `requests`; проверить `kubectl describe quota`. |
| `LimitRange ... exceeds the maximum` / `min` | Container не проходит `min`/`max` `LimitRange`. | Скорректировать ресурсы пода под границы `LimitRange`. |
| **Pod Security**: `Forbidden: violates PodSecurity "restricted"` | Нарушение PSA (`runAsNonRoot`, root-контейнер, capabilities). | Исправить `securityContext` пода, либо на время перевести метку на `warn`/`audit`. |
| **Трафик не проходит** между тенантами | `NetworkPolicy` default-deny блокирует, но DNS/порт не разрешены. | Добавить политику allow для CoreDNS и нужного трафика внутри namespace. |
| `kubectl auth can-i` даёт `no`, хотя роль есть | Роль выдана не той группе/не в том namespace, или cached RBAC. | Проверить `kubectl get rolebinding -n <ns> -o yaml`; RBAC обновляется быстро, но кэш API может задержать. |
| Кластер деградирует от количества объектов | Отсутствуют квоты на число объектов (`count/secrets`, `count/configmaps`). | Ввести объектные квоты; провести компакцию/дефрагментацию `etcd`. |

---

## Чек-лист хорошо управляемого общего кластера

1.  **[ ]** Каждый Namespace имеет метки `team`, `environment` и `cost-centre`.
2.  **[ ]** RBAC-роли ограничены уровнем Namespace для команд разработки.
3.  **[ ]** Присутствует `default-deny` NetworkPolicy в каждом тенантном Namespace.
4.  **[ ]** Установлены `ResourceQuota` и `LimitRange` во всех Namespace.
5.  **[ ]** Применяется `Pod Security Standards` (профиль `restricted`) в Prod.
6.  **[ ]** Развернут **Kubecost** для атрибуции затрат и FinOps-отчетности.
7.  **[ ]** Алерты и дашборды настроены с учетом изоляции тенантов.

---

## Дополнительная информация

**Важные принципы:**
1.  **Принцип наименьших привилегий**: Тенанты не должны иметь доступа к API узлов и общекластерным настройкам; все роли тенанта — namespace-scoped (`Role`/`RoleBinding`), никаких `cluster-admin` для тенантов.
2.  **Лимиты API**: Ограничивайте количество объектов (Secrets, ConfigMaps, Pods) в Namespace — это защищает `etcd` и API-сервер от перегрузки (см. [Квоты на количество объектов](#квоты-на-количество-объектов--защита-etcd)).
3.  **Разделение Control Plane и данных**: даже в soft-модели общий Control Plane должен быть защищён от тенантов (RBAC, APF, запрет анонимного доступа).
4.  **Всегда подкрепляйте ресурсы количественными квотами**: квоты на CPU/RAM без `LimitRange` приводят к ошибкам создания подов без `requests`; без объектных квот кластер деградирует от роста `etcd`.
5.  **Метки — единый язык атрибуции**: согласованные `team`/`environment`/`cost-centre` превращают мониторинг и FinOps в рабочие инструменты, а разрозненные — в источник ошибок.

**См. также:**
*   [RBAC в Kubernetes](../Security/rbac/rbac_overview.md)
*   [NetworkPolicy: сетевая безопасность и изоляция подов](../Security/network_policies.md)
*   [Security Context и PSA](../Security/pod_security_context.md)

*Другие ключевые смежные материалы уже приведены по тексту:* [Квоты ресурсов](../Scheduling/qos_limit_and_requests.md), [PriorityClass](../Concepts/priorityclass.md), [Virtual Clusters (vcluster)](../ToolsUtilities/vcluster/vcluster_overview.md), [Kubecost](../MonitoringLogging/kubecost.md).
