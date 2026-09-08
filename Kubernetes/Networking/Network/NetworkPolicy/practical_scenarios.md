# NetworkPolicy: Практические сценарии

## Определения

**Практический сценарий NetworkPolicy** — структурированное описание процесса внедрения сетевой изоляции в кластере Kubernetes, включающее настройку манифестов, разбор типовых конфигурационных ошибок и методы верификации связности.

**Изоляция по умолчанию (Default Deny)** — стратегия безопасности «Нулевого доверия» (Zero Trust), при которой весь сетевой трафик блокируется, если он не разрешен явно.

**Сетевая изоляция** — механизм ограничения сетевого взаимодействия между подами (Pod) или внешними ресурсами для уменьшения поверхности атаки и предотвращения бокового перемещения злоумышленника внутри кластера.

**Трехуровневая модель ACL (3-Tier Model)** — современный стандарт (2026), разделяющий зоны ответственности:
1.  **AdminNetworkPolicy (ANP)** — принудительные правила администратора (Allow/Deny), имеющие высший приоритет.
2.  **NetworkPolicy (NP)** — правила разработчика на уровне пространства имен.
3.  **BaselineAdminNetworkPolicy (BANP)** — правила «по умолчанию», действующие только если трафик не разрешен в NP.

**Dual-stack (IPv4/IPv6)** — конфигурация сети, позволяющая подам иметь адреса обоих протоколов одновременно. NetworkPolicy в этом случае должны учитывать оба адресных пространства.

**conntrack (Connection Tracking)** — механизм ядра Linux, отслеживающий состояния активных сетевых соединений. NetworkPolicy использует conntrack для автоматического разрешения ответного трафика (return traffic) независимо от наличия разрешающих правил в противоположном направлении.

**matchExpressions** — расширенный механизм селекторов в NetworkPolicy, поддерживающий операции сравнения (`In`, `NotIn`, `Exists`, `DoesNotExist`) и работу с множествами значений. Позволяет задавать более сложные условия отбора подов и пространств имен, чем простое совпадение меток (`matchLabels`).

**endPort** — поле в спецификации NetworkPolicy (K8s 1.21+), позволяющее указать диапазон портов (от `port` до `endPort`) в одном правиле вместо создания отдельного правила для каждого порта.

## Базовые концепции

### Методология настройки

Эффективная сетевая сегментация строится на следующих принципах:

- **Принцип явного разрешения** — использование разрешительных списков (Allow-lists) для входящего (Ingress) и исходящего (Egress) трафика.
- **Гибкость селекторов** — применение политик через селекторы подов (`podSelector`) и пространств имен (`namespaceSelector`).
- **Инфраструктурная связность** — обязательное разрешение доступа к системным службам (CoreDNS, Metrics Server) при включении Egress-изоляции.
- **Многоуровневая защита** — использование ANP для защиты инфраструктуры и изоляция трафика между пространствами имен (Namespaces) с использованием меток (Labels).

### Поведение conntrack в NetworkPolicy

NetworkPolicy являются **stateful** (с сохранением состояния). Это означает:

1.  Если исходящий трафик (Egress) разрешен, то ответный входящий трафик (Return traffic) разрешается **автоматически** на уровне conntrack, независимо от наличия разрешающих правил Ingress.
2.  Соединения, установленные до применения политики, могут оставаться активными до истечения тайм-аута conntrack (по умолчанию ~1ч для TCP, ~30с для UDP).
3.  При переполнении таблицы conntrack (`nf_conntrack_max`) ядро начинает отбрасывать новые пакеты, что приводит к «молчаливым» блокировкам, маскирующимся под проблемы NetworkPolicy.

> **Рекомендация для DevOps/SRE:** При подозрении на проблемы с NetworkPolicy всегда проверяйте состояние conntrack: `conntrack -S` и `sysctl net.netfilter.nf_conntrack_max`.

### Описание тестовой среды

Для сценариев используется среда с тремя Namespaces:

| Namespace | Компонент | Описание |
| :--- | :--- | :--- |
| `app-frontend` | `webapp` | Приложение-прокси, обрабатывающее HTTP-запросы |
| `app-backend` | `api-server` | Основной сервис API на базе TCP |
| `app-backend` | `static-server` | Веб-сервер для раздачи статического контента |
| `kube-system` | `coredns` | Системный сервис DNS |
| `kube-system` | `metrics-server` | Мониторинг ресурсов (CPU/RAM) |

Изначально в кластере действует открытая сетевая модель: все Pod могут свободно взаимодействовать друг с другом.

## Практические сценарии

### Сценарий 0: Изоляция базы данных (Классический пример)

Задача: разрешить входящие соединения к базе данных только из подов с меткой `role: frontend`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-network-policy
  namespace: prod
spec:
  podSelector:
    matchLabels:
      role: db
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          role: frontend
    ports:
    - protocol: TCP
      port: 5432
```

**Анализ:** Политика применяется к подам в неймспейсе `prod`. Она блокирует весь входящий трафик к БД, кроме TCP-соединений на порт 5432 от подов с меткой `frontend` в том же пространстве имен.

### Шаг 1: Изоляция входящего трафика (Default Deny Ingress)

Блокировка всего входящего трафика для Namespace `app-backend`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: app-backend
spec:
  podSelector: {} # Выбирает все поды в пространстве имен
  policyTypes:
  - Ingress
  ingress: [] # Пустой список правил означает полный запрет
```

**Результат:** Любые попытки обращения от `webapp` или сторонних отладочных подов к сервисам в `app-backend` будут завершаться ошибкой `Connection timed out`.

### Шаг 2: Разрешение доступа к конкретному микросервису

Разрешим приложению `webapp` обращаться к `api-server` на порту 8080.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress-frontend-to-api
  namespace: app-backend
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
          kubernetes.io/metadata.name: app-frontend
      podSelector:
        matchLabels:
          app: webapp
    ports:
    - protocol: TCP
      port: 8080
```

**Результат:** `webapp` может подключаться к `api-server`, но доступ к `static-server` для него остается закрытым.

### Шаг 3: Изоляция исходящего трафика и восстановление DNS

Применим изоляцию исходящего трафика для Namespace `app-frontend`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: app-frontend
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress: []
```

**Результат:** Приложение `webapp` перестанет работать, так как доступ к DNS-серверу кластера заблокирован.

### Шаг 4: Разрешение доступа к системному DNS и Backend

Восстановление работоспособности через явное разрешение трафика к CoreDNS и к сервисам в `app-backend`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-infra-and-backend
  namespace: app-frontend
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to: # Разрешение трафика к Backend Namespace
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: app-backend
  - to: # Разрешение трафика к CoreDNS
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
```

**Важно:** Если приложение использует `kubectl top` или HPA (Horizontal Pod Autoscaler), необходимо также разрешить доступ к Metrics Server (порт 4443 в `kube-system`):

```yaml
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: metrics-server
    ports:
    - port: 4443
      protocol: TCP
```

### Альтернатива: Использование ipBlock для внешних ресурсов (Dual-stack)

Если приложению требуется доступ к внешнему API, используйте IPv4 и IPv6 диапазоны.

```yaml
egress:
- to:
  - ipBlock:
      cidr: 203.0.113.0/24    # IPv4
      except:
      - 203.0.113.10/32
  - ipBlock:
      cidr: 2001:db8:1::/48   # IPv6
  ports:
  - port: 443
    protocol: TCP
```

### Сценарий 5: Ограничение исходящего трафика к внешним ресурсам

Задача: разрешить подам с меткой `component: github` обращаться только к **github.com**.

При простом ограничении трафика по IP через `ipBlock` возникает ошибка `Resolving timed out`, так как доступ к CoreDNS блокируется политикой Egress.

**Решение: Манифест с разрешением IP и DNS**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-github
  namespace: test-github
spec:
  podSelector:
    matchLabels:
      component: github
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 140.82.121.4/32 # IP GitHub
    ports:
    - protocol: TCP
      port: 443
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

### Сценарий 6: Глобальная изоляция (AdminNetworkPolicy)

Административное правило: жестко запретить трафик между `tenant-a` и `tenant-b` на уровне кластера.

```yaml
apiVersion: policy.networking.k8s.io/v1alpha1
kind: AdminNetworkPolicy
metadata:
  name: restrict-tenant-communication
spec:
  priority: 10
  subject:
    namespaces:
      matchLabels:
        tenant: tenant-a
  ingress:
    - name: deny-tenant-b
      action: Deny
      from:
        - namespaces:
            matchLabels:
              tenant: tenant-b
```

### Сценарий 7: Поддержка протокола SCTP (Telco/5G)

Для приложений, требующих SCTP сигнализации (NGAP порт 38412).

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-sctp-signaling
  namespace: telco-apps
spec:
  podSelector:
    matchLabels:
      app: signal-node
  policyTypes:
  - Ingress
  ingress:
  - ports:
    - protocol: SCTP
      port: 38412
```

### Сценарий 8: Диапазон портов (endPort)

Задача: разрешить входящий трафик на диапазон портов 8000-8100 для приложения с несколькими сервисами.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-port-range
  namespace: app-backend
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
          kubernetes.io/metadata.name: app-frontend
    ports:
    - protocol: TCP
      port: 8000
      endPort: 8100
```

**Примечание:** `endPort` поддерживается начиная с Kubernetes 1.21. В 경우е использования более ранних версий необходимо указывать каждый порт отдельно.

### Сценарий 9: Сложные селекторы (matchExpressions)

Задача: разрешить входящий трафик от подов с меткой `environment` равной `prod` или `staging`, но исключить поды с меткой `debug: "true"`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prod-staging-no-debug
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
        matchExpressions:
        - key: environment
          operator: In
          values:
          - prod
          - staging
        - key: debug
          operator: DoesNotExist
    ports:
    - protocol: TCP
      port: 8080
```

**Операторы matchExpressions:**
| Оператор | Описание |
| :--- | :--- |
| `In` | Значение метки входит в указанный список |
| `NotIn` | Значение метки не входит в указанный список |
| `Exists` | Метка с указанным ключом существует |
| `DoesNotExist` | Метка с указанным ключом отсутствует |

### Сценарий 10: Меж-неймспейсная изоляция с namespaceSelector

Задача: обеспечить изоляцию между средами (dev, staging, prod) так, чтобы поды в `dev` не могли обращаться к сервисам в `prod`, но `staging` имел ограниченный доступ.

```yaml
# 1. Default Deny для prod
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: prod
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress: []
---
# 2. Разрешение доступа из staging к определенным сервисам
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-staging-to-api
  namespace: prod
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
          kubernetes.io/metadata.name: staging
      podSelector:
        matchLabels:
          app: load-tester
    ports:
    - protocol: TCP
      port: 8080
---
# 3. Полная изоляция dev от prod (enantiosemantics через namespaceSelector)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-dev-to-prod
  namespace: prod
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: dev
    # Пустой список ingress[0].from с namespaceSelector = Deny из dev
```

**Важно:** В Kubernetes комбинация `namespaceSelector` и `podSelector` в одном элементе списка `from` работает как **логическое И** (оба условия должны выполняться одновременно). Разные элементы списка `from` работают как **логическое ИЛИ**.

### Сценарий 11: Поэтапное внедрение (Phased Rollout)

Стратегия безопасного внедрения NetworkPolicy без нарушения рабочих процессов:

**Этап 1: Audit Mode (Мониторинг)** — политика логирует, но не блокирует нарушения.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: audit-ingress-default-deny
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress: []
```

После создания política автоматически переходит в режим Default Deny. Однако перед применением на продакшене используйте инструменты CNI для аудита:

```bash
# Cilium: мониторинг отброшенных пакетов без блокировки
cilium monitor --type policy-verdict --namespace production --verdict DROPPED

# Hubble: визуализация трафика
hubble observe --namespace production --verdict DROPPED --follow
```

**Этап 2: Частичная изоляция (Ingress-only)** — разрешаем только необходимые входящие соединения, Egress оставляем открытым.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
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
    ports:
    - protocol: TCP
      port: 8080
```

**Этап 3: Полная изоляция (Ingress + Egress)** — добавляем Egress-правила и DNS-разрешения.

**Этап 4: GitOps Workflow** — все манифесты хранятся в Git и применяются через Argo CD/Flux.

### Сценарий 12: GitOps Workflow для NetworkPolicy

Управление сетевыми политиками через Git обеспечивает версионирование, аудит и автоматическое применение:

```
network-policies/
├── base/
│   ├── default-deny.yaml
│   └── allow-dns.yaml
├── overlays/
│   ├── dev/
│   │   ├── kustomization.yaml
│   │   └── allow-all.yaml
│   ├── staging/
│   │   └── kustomization.yaml
│   └── production/
│       ├── kustomization.yaml
│       ├── allow-frontend-to-backend.yaml
│       └── deny-external-access.yaml
└── tests/
    └── conftest_policy_test.rego
```

```bash
# Тестирование политик перед применением
conftest test network-policies/base/ --policy tests/conftest_policy_test.rego

# Применение через kubectl
kubectl apply -k network-policies/overlays/production/
```

### Сценарий 13: Политика для Metrics Server и HPA

Если в кластере используется HPA (Horizontal Pod Autoscaler), поды должны иметь доступ к Metrics Server. При Default Deny Egress этот доступ блокируется:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-metrics-server
  namespace: production
spec:
  podSelector: {}
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
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
  # Metrics Server
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: metrics-server
    ports:
    - port: 4443
      protocol: TCP
  # API Server (для запросов метрик)
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8  # CIDR API-сервера кластера
    ports:
    - port: 6443
      protocol: TCP
```

### Сценарий 14: Защита чувствительных эндпоинтов (Metadata API)

Блокировка доступа к cloud metadata API (169.254.169.254) для предотвращения кражи IAM-ролей:

```yaml
apiVersion: policy.networking.k8s.io/v1alpha1
kind: AdminNetworkPolicy
metadata:
  name: block-metadata-api
spec:
  priority: 5
  subject:
    namespaces: {}
  egress:
  - name: deny-metadata-api
    action: Deny
    to:
    - ipBlock:
        cidr: 169.254.169.254/32
    ports:
    - port: 80
      protocol: TCP
    - port: 443
      protocol: TCP
```

> **Важно:** Этот сценарий особенно критичен в средах без облачных провайдеров, где metadata API может быть доступен через маршрутизацию узла.

## Устранение неполадок (Troubleshooting)

Классическим симптомом проблемы с NetworkPolicy является **Connection Timeout**.

### Алгоритм диагностики блокировок

1.  **Подтвердите разрешение DNS:**
    ```bash
    kubectl exec -it <pod-name> -n <ns> -- nslookup service-name.target-ns.svc.cluster.local
    ```
    Если разрешение не удается — проблема в Egress-правилах на порт 53 UDP в сторону `kube-system`.

2.  **Проверьте наличие и правила политик:**
    ```bash
    kubectl get networkpolicy -n <namespace>
    kubectl describe networkpolicy <policy-name> -n <namespace>
    ```
    Проверьте `podSelector`, `policyTypes` и убедитесь, что разделы правил не пусты (пустой раздел — полный запрет).

3.  **Верификация меток (Labels):**
    Убедитесь, что метки на подах и Namespace соответствуют селекторам.
    ```bash
    kubectl get pods --show-labels -n <ns>
    kubectl get ns --show-labels
    ```

4.  **Проверьте плагин CNI:**
    Убедитесь, что CNI (Cilium, Calico) работает корректно. Используйте:
    *   **Cilium:** `hubble observe --pod <pod-name> --verdict DROPPED`
    *   **Calico:** `calicoctl node status` и проверка логов `calico-node`.

5.  **Проверьте conntrack:**
    ```bash
    # Статистика conntrack
    conntrack -S
    
    # Проверка таблицы conntrack
    conntrack -L | grep <pod-ip>
    
    # Проверка лимитов
    sysctl net.netfilter.nf_conntrack_max
    sysctl net.netfilter.nf_conntrack_count
    ```

6.  **Очистка conntrack (при необходимости):**
    ```bash
    # Очистка всех записей для конкретного пода
    conntrack -D -s <pod-ip>
    
    # Очистка всех записей для конкретного сервиса
    conntrack -D -d <service-cluster-ip>
    ```

### Мини-кейс: Изоляция пространства имен и исправление

**Проблема:** Применение политики "Default Deny Ingress" ко всему Namespace `backend` заблокировало доступ для `frontend`.
**Решение:** Добавление корректирующего правила с использованием `namespaceSelector`:
```yaml
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        kubernetes.io/metadata.name: frontend
```

### Мини-кейс: Заблокированный внутренний вызов

Сервис `payments` не мог подключиться к `users`.
*   **Диагностика:** `kubectl get netpol -n users` показал, что разрешен Ingress только от `role: frontend`.
*   **Решение:** В политику `users` добавлено правило для подов с меткой `app: payments`.

### Мини-кейс: DNS-резолвинг после Default Deny Egress

**Проблема:** После применения Default Deny Egress поды не могут разрешить имена сервисов.
**Диагностика:**
```bash
kubectl exec -it <pod> -- nslookup kubernetes.default.svc.cluster.local
# connection timed out; no servers could be reached
```
**Решение:** Добавить Egress-правило для CoreDNS (порт 53 UDP/TCP в `kube-system`).

### Мини-кейс: Conntrack race condition с DNS

**Проблема:** Интерmittent DNS failures (1-5 секунд задержки) при высокой нагрузке.
**Причина:** Race condition в `nf_conntrack` при UDP-запросах к CoreDNS.
**Решение:** Установить NodeLocal DNSCache для локального кэширования DNS-запросов на каждом узле.

### Мини-кейс: Метрики HPA не собираются

**Проблема:** HPA показывает `<unknown>` для подов после включения Default Deny Egress.
**Причина:** Поды не могут достучаться до Metrics Server (порт 4443).
**Решение:** Добавить Egress-правило для Metrics Server в `kube-system` (см. Сценарий 13).

### Совет для собеседования

**Вопрос:** О чем важно не забыть при создании Egress-политики?
**Ответ:** О разрешении **DNS-трафика** (порт 53 UDP/TCP) в сторону `kube-system`. Без этого под не сможет разрешить имена сервисов.

**Вопрос:** Как определить, что проблема связана с conntrack, а не с NetworkPolicy?
**Ответ:** Проверить `conntrack -S` — если много dropped по `nf_conntrack_full`, проблема в размере таблицы, а не в правилах. Также `conntrack -L | grep <pod-ip>` покажет активные соединения.

## Дополнительные сведения

### Сброс сетевой конфигурации

В случае критических ошибок, блокирующих доступ:
```bash
kubectl delete networkpolicy --all -n <namespace>
```

### Производительность и масштабирование

- При Default Deny каждое новое соединение требует перебора правил. Для приложений с высокой пропускной способностью используйте CNI с eBPF (O(1) lookup).
- При количестве политик >1000 или подов >10000 рекомендуется переход на CNI на базе eBPF (Cilium, Calico eBPF mode).
- Используйте `endPort` вместо отдельных правил для каждого порта — это снижает количество правил и ускоряет обработку.

### Шаблонизация через Helm

Для управления NetworkPolicy в Helm-чартах используйте именованные шаблоны для синхронизации меток между Deployment и политиками. Подробнее: [Шаблонизация NetworkPolicy](../../../../ToolsUtilities/Helm/templating/scenarios/networkpolicy.md).

### См. также

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины.
* [NetworkPolicy: Логика правил](./rule_logic.md) — разбор И/ИЛИ и аддитивность.
* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации Zero Trust.
* [NetworkPolicy: Реализация CNI-плагинами](./cni_implementation.md) — сравнение CNI и методы исполнения.
* [Cilium: Сетевые политики L7](../CNI/cilium.md) — FQDN и HTTP фильтрация.
* [NetworkPolicy: Сетевая безопасность](../../../Security/network_policies.md) — безопасность и compliance.
