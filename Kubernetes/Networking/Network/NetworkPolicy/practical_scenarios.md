# NetworkPolicy: Практические сценарии

## Определения

**Практический сценарий NetworkPolicy** — структурированное описание процесса внедрения сетевой изоляции в кластере Kubernetes, включающее настройку манифестов, разбор типовых конфигурационных ошибок и методы верификации связности.

**Изоляция по умолчанию (Default Deny)** — стратегия безопасности «Нулевого доверия» (Zero Trust), при которой весь сетевой трафик блокируется, если он не разрешен явно.

**Сетевая изоляция** — механизм ограничения сетевого взаимодействия между подами (Pod) или внешними ресурсами для уменьшения поверхности атаки и предотвращения бокового перемещения злоумышленника внутри кластера.

## Базовые Концепции

### Методология настройки

В данных сценариях демонстрируются ключевые принципы работы ресурсов NetworkPolicy:

- **Принцип явного разрешения** — использование разрешительных списков (Allow-lists) для входящего (Ingress) и исходящего (Egress) трафика.
- **Гибкость селекторов** — применение политик через селекторы подов (`podSelector`) и пространств имен (`namespaceSelector`).
- **Инфраструктурная связность** — обязательное разрешение доступа к системным службам, таким как система доменных имен (Domain Name System, DNS).
- **Многоуровневая защита** — изоляция трафика между пространствами имен (Namespaces) с использованием меток (Labels).

### Описание тестовой среды

Для сценариев используется среда с тремя Namespaces:

| Namespace | Компонент | Описание |
| :--- | :--- | :--- |
| `app-frontend` | `webapp` | Приложение-прокси, обрабатывающее запросы по протоколу HTTP (HyperText Transfer Protocol) |
| `app-backend` | `api-server` | Основной сервис API (Application Programming Interface) на базе TCP (Transmission Control Protocol) |
| `app-backend` | `static-server` | Веб-сервер для раздачи статического контента |
| `kube-system` | `coredns` | Системный сервис DNS |

Изначально в кластере действует открытая сетевая модель: все Pod могут свободно взаимодействовать друг с другом.

## Практические Сценарии

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
      role: db # Целевые поды (база данных)
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          role: frontend # Разрешенный источник (фронтенд)
    ports:
    - protocol: TCP
      port: 5432 # Порт БД (например, PostgreSQL)
```

**Анализ:** Политика применяется к подам в неймспейсе `prod`. Она блокирует весь входящий трафик к БД, кроме TCP-соединений на порт 5432 от подов с меткой `frontend` в том же пространстве имен.

### Шаг 1: Изоляция входящего трафика (Default Deny Ingress)

Первым этапом внедрения безопасности является блокировка всего входящего трафика для Namespace `app-backend`.

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

**Результат:** `webapp` может подключаться к `api-server`, но доступ к `static-server` для него остается закрытым, так как селектор политики ограничивает действие только одним приложением.

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

**Результат:** Приложение `webapp` перестанет работать, так как оно больше не может обратиться к DNS-серверу кластера для преобразования имен сервисов в IP-адреса.

### Шаг 4: Разрешение доступа к системному DNS и Backend

Для восстановления работоспособности необходимо явно разрешить исходящий трафик к CoreDNS и к сервисам в `app-backend`.

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
      protocol: UDP # User Datagram Protocol
    - port: 53
      protocol: TCP
```

### Альтернатива: Использование ipBlock для внешних ресурсов

Если приложению требуется доступ к внешнему API с фиксированным диапазоном адресов, используется формат CIDR (Classless Inter-Domain Routing).

```yaml
egress:
- to:
  - ipBlock:
      cidr: 203.0.113.0/24
      except:
      - 203.0.113.10/32 # Исключение конкретного IP из диапазона
  ports:
  - port: 443
    protocol: TCP
```

### Сценарий 5: Ограничение исходящего трафика (Egress) к внешним ресурсам

Задача: разрешить подам с меткой `component: github` обращаться только к **github.com**.

#### Проблема: Блокировка DNS
При простом ограничении трафика по IP-адресу через `ipBlock` приложение часто выдает ошибку:
`curl: (28) Resolving timed out after 5002 milliseconds`

Это происходит потому, что после применения любой Egress-политики поды становятся изолированными, и доступ к системному DNS кластера (CoreDNS) блокируется. Для работы внешних имен **необходимо** явно разрешить трафик на порт 53.

#### Решение 1: Стандартный манифест (Egress по IP + DNS)

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
  # 1. Разрешение доступа к GitHub по IP (Пример: 140.82.121.4)
  - to:
    - ipBlock:
        cidr: 140.82.121.4/32
    ports:
    - protocol: TCP
      port: 443
  # 2. Разрешение DNS-запросов к CoreDNS в kube-system
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

#### Решение 2: Использование FQDN и L7-правил (Cilium)
Использование IP-адресов для внешних сервисов неудобно, так как они могут меняться. Продвинутые CNI (например, Cilium) позволяют использовать полные доменные имена (**FQDN**) и фильтрацию на уровне **L7 (HTTP)**.

Подробные примеры настройки FQDN и ограничений по HTTP-путям/методам см. в:
**[Cilium: Сетевые политики FQDN и L7](../CNI/cilium.md#сетевая-политика-с-fqdn)**.

---

## Устранение неполадок (Troubleshooting)

Классическим симптомом проблемы с NetworkPolicy является **Connection Timeout** между подами, даже если DNS и Service работают корректно.

### Алгоритм диагностики блокировок

Если вы подозреваете, что трафик блокируется политикой (особенно между подами в разных пространствах имен), следуйте этому рабочему процессу:

1.  **Подтвердите разрешение DNS:** Убедитесь, что служба в целевом пространстве имен разрешима.
    ```bash
    # Пример проверки из пода
    nslookup data.backend.svc.cluster.local
    ```
    *Если разрешение не удается, проблема связана с CoreDNS, а не с NetworkPolicy.*

2.  **Проверьте наличие и правила политик:** Определите, применяются ли какие-либо политики к исходному или целевому поду в обоих пространствах имен.
    ```bash
    kubectl get networkpolicy -n <source-namespace>
    kubectl get networkpolicy -n <destination-namespace>
    ```
    *   **podSelector:** Проверьте, выбраны ли ваши поды этой политикой.
    *   **policyTypes:** Убедитесь, что включены нужные направления (`Ingress`, `Egress`).
    *   **Ingress Rules / Egress Rules:** Если раздел правил для нужного направления пуст, весь трафик запрещен по умолчанию.

3.  **Верификация меток (Labels):** Убедитесь, что метки на подах и пространствах имен в точности соответствуют селекторам (`podSelector` и `namespaceSelector`).

4.  **Проверьте плагин CNI:** Если политики настроены верно, но связи нет, проблема может быть в самом CNI-плагине (Calico, Cilium, Flannel). Проверьте логи агентов CNI на узлах.

### Мини-кейс: Изоляция пространства имен и исправление

Частая причина сбоев — применение политики "Default Deny" ко всему пространству имен без разрешающих правил для внешних запросов.

**Проблема: Полная изоляция входящего трафика**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all-ingress
  namespace: backend
spec:
  podSelector: {} # Выбирает все поды в пространстве имен backend
  policyTypes:
  - Ingress
  # Отсутствие правил ingress блокирует весь входящий трафик
```

**Решение: Корректирующее правило Ingress**
Для разрешения трафика, например, из пространства имен `frontend`, необходимо добавить правило с использованием `namespaceSelector`:
```yaml
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        name: frontend # Требует наличия метки name: frontend у Namespace
```

**Реальный пример (Кейс из практики):**
В одной организации сразу после внедрения политики «запрета входящего трафика по умолчанию» произошел сбой: клиентское приложение (frontend) потеряло доступ к пользовательскому сервису (backend). DNS работал корректно, но попытки подключения завершались по таймауту. 
Диагностика показала, что при настройке безопасности забыли добавить явное правило, разрешающее входящий трафик из неймспейса фронтенда. Проблема была решена добавлением правила `ingress` со ссылкой на метку пространства имен `frontend`. 

### Мини-кейс: Заблокированный внутренний вызов

В многоуровневом приложении сервис `payments` перестал подключаться к сервису `users`.

*   **Признак:** Транзакции падают с таймаутом соединения. DNS резолвится корректно.
*   **Диагностика:** Выполнение `kubectl get netpol -n users` выявило политику, которая разрешает Ingress-трафик только от подов с меткой `role: frontend`. У подов сервиса `payments` такой метки не было.
*   **Решение:** В политику сервиса `users` было добавлено дополнительное правило `ingress`, разрешающее трафик от подов с меткой `app: payments`. Связь восстановилась мгновенно.

> **Совет для собеседования:**
> **Вопрос:** Вы создаете сетевую политику, ограничивающую исходящий трафик пода только базой данных. О чем важно не забыть?
> **Ответ:** Важно не забыть разрешить **Egress-трафик для DNS**. Без явного разрешения исходящего трафика на порт UDP 53 в пространство имен `kube-system`, под не сможет разрешить DNS-имя базы данных, и соединение не будет установлено.

## Дополнительные Сведения


### Сброс сетевой конфигурации

В случае критических ошибок в конфигурации, блокирующих доступ к кластеру, политики можно удалить массово:
```bash
kubectl delete networkpolicy --all -n <namespace>
```

**См. также:**
* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины и 3-Tier модель.
* [NetworkPolicy: Логика правил](./rule_logic.md) — детальный разбор логики И/ИЛИ.
* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации по именованию и безопасности.
