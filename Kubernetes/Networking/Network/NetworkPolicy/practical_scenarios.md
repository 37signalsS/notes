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

## Базовые концепции

### Методология настройки

Эффективная сетевая сегментация строится на следующих принципах:

- **Принцип явного разрешения** — использование разрешительных списков (Allow-lists) для входящего (Ingress) и исходящего (Egress) трафика.
- **Гибкость селекторов** — применение политик через селекторы подов (`podSelector`) и пространств имен (`namespaceSelector`).
- **Инфраструктурная связность** — обязательное разрешение доступа к системным службам (CoreDNS, Metrics Server) при включении Egress-изоляции.
- **Многоуровневая защита** — использование ANP для защиты инфраструктуры и изоляция трафика между пространствами имен (Namespaces) с использованием меток (Labels).

### Описание тестовой среды

Для сценариев используется среда с тремя Namespaces:

| Namespace | Компонент | Описание |
| :--- | :--- | :--- |
| `app-frontend` | `webapp` | Приложение-прокси, обрабатывающее HTTP-запросы |
| `app-backend` | `api-server` | Основной сервис API на базе TCP |
| `app-backend` | `static-server` | Веб-сервер для раздачи статического контента |
| `kube-system` | `coredns` | Системный сервис DNS |

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
    *   **Calico:** Проверка логов `calico-node`.

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

### Совет для собеседования

**Вопрос:** О чем важно не забыть при создании Egress-политики?
**Ответ:** О разрешении **DNS-трафика** (порт 53 UDP/TCP) в сторону `kube-system`. Без этого под не сможет разрешить имена сервисов.

## Дополнительные сведения

### Сброс сетевой конфигурации

В случае критических ошибок, блокирующих доступ:
```bash
kubectl delete networkpolicy --all -n <namespace>
```

**См. также:**
* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины.
* [NetworkPolicy: Логика правил](./rule_logic.md) — разбор И/ИЛИ.
* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации Zero Trust.
* [Cilium: Сетевые политики L7](../CNI/cilium.md) — FQDN и HTTP фильтрация.
