# NetworkPolicy: Логика правил

## Определения

**Логика правил NetworkPolicy** — совокупность принципов, по которым Kubernetes и сетевой плагин (CNI) интерпретируют селекторы, порты и диапазоны IP-адресов для принятия решения о разрешении или блокировке сетевого трафика.

**Аддитивность политик (Additive)** — принцип, согласно которому итоговый набор разрешений для пода является объединением (логическое «ИЛИ») всех правил всех NetworkPolicy, которые выбирают данный под.

**Изоляция (Isolation)** — состояние пода, возникающее при его выборе хотя бы одной политикой. В этом состоянии весь трафик в выбранном направлении (Ingress/Egress) запрещен, если он не разрешен явно.

**AdminNetworkPolicy (ANP)** — (начиная с K8s 1.30+ Beta) кластерный ресурс с более высоким приоритетом, позволяющий администраторам задавать обязательные правила `Allow`, `Deny` или передавать управление (`Pass`) обычным NetworkPolicy.

**BaselineAdminNetworkPolicy (BANP)** — кластерный ресурс, определяющий сетевые правила «последнего шанса». Применяется только в том случае, если трафик не был разрешен или запрещен вышестоящими ANP или обычными NetworkPolicy.

**matchExpressions** — расширенный механизм селекторов (set-based), позволяющий фильтровать объекты по вхождению меток в списки (`In`, `NotIn`) или их наличию (`Exists`, `DoesNotExist`).

**policyTypes** — обязательное поле в спецификации NetworkPolicy, определяющее, в каких направлениях (Ingress, Egress) политика применяет правила. Без указания этого поля политика не оказывает никакого воздействия на трафик, даже если правила определены.

**conntrack (Connection Tracking)** — механизм ядра Linux, отслеживающий состояния активных сетевых соединений. NetworkPolicy использует conntrack для автоматического разрешения ответного трафика (return traffic) независимо от наличия разрешающих правил в противоположном направлении.

## Базовые Концепции

### Иерархия выполнения правил (3-Tier Model)

С 2024–2026 гг. в Kubernetes утвердилась трехуровневая модель сетевой безопасности. Трафик оценивается последовательно:

1.  **Tier 1: AdminNetworkPolicy (ANP).** Кластерный уровень. Правила имеют явный приоритет (`priority`). Если найдено совпадение с действием `Allow` или `Deny` — оценка прекращается. Если `Pass` — переход к Tier 2.
2.  **Tier 2: NetworkPolicy.** Уровень пространства имен. Здесь работает стандартная аддитивная логика («если хоть одна разрешает — можно»).
3.  **Tier 3: BaselineAdminNetworkPolicy (BANP).** Кластерный уровень «последнего шанса». Используется для задания настроек по умолчанию (например, Default Deny), если на Tier 2 ничего не было определено.

### Роль поля policyTypes

Поле `policyTypes` определяет, в каких направлениях политика активна. Это ключевой элемент, без которого правила не применяются:

*   **Только `Ingress`:** Политика фильтрует только входящий трафик. Исходящий трафик не затрагивается.
*   **Только `Egress`:** Политика фильтрует только исходящий трафик. Входящий трафик не затрагивается.
*   **`Ingress` и `Egress`:** Политика фильтрует оба направления.

**Критический нюанс:** Если `policyTypes` не указан, но правила `ingress`/`egress` определены — политика **не применяется**. Kubernetes игнорирует правила, если направление не включено в `policyTypes`.

```yaml
# Правила определены, но policyTypes отсутствует — политика НЕ работает
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: broken-example
spec:
  podSelector:
    matchLabels:
      app: my-app
  ingress:
  - from:
    - podSelector:
        matchLabels:
          role: frontend
# Отсутствует policyTypes — правила не применяются!
```

### Логические операторы И и ИЛИ

Эффективное управление доступом на уровне Tier 2 требует понимания того, как комбинируются условия:

1.  **Логическое «ИЛИ» (Массивы):**
    *   Элементы в списках `ingress` и `egress` являются независимыми правилами.
    *   Элементы в списках `from` (для Ingress) и `to` (для Egress) объединяются по «ИЛИ». Трафик разрешен, если он соответствует **хотя бы одному** из элементов списка.
2.  **Логическое «И» (Поля объекта):**
    *   Поля внутри одного элемента списка `from` или `to` (например, `podSelector` и `namespaceSelector`) объединяются по «И». Трафик разрешен только при **одновременном** выполнении всех условий.

**Важно:** Порядок элементов в массивах `ingress`/`egress` не имеет значения. Правила проверяются как единый набор, а не последовательно. Добавление правила в начало или конец списка не влияет на результат.

### Селекторы и их отсутствие

*   **`podSelector: {}`**: Выбирает **все** поды в пространстве имен, где создана политика.
*   **`podSelector: {}` в секции `from`**: Соответствует **всем** подам в текущем пространстве имен (без фильтрации по меткам).
*   **Отсутствие `podSelector` в секции `from`/`to`**: При наличии `namespaceSelector` означает «все поды в выбранном пространстве имен». Если `namespaceSelector` тоже отсутствует — означает «все поды во всех пространствах имен».
*   **Пустой `ingress: []` или `egress: []`**: Если направление указано в `policyTypes`, но список правил пуст, это означает «запретить всё» (Default Deny) для данного направления.
*   **Отсутствие `ingress`/`egress` (поле не указано)**: Если направление указано в `policyTypes`, но само поле отсутствует — это эквивалентно пустому списку и означает «запретить всё».

### Семантика портов

Правила фильтрации по портам работают по принципу «белого списка»:

*   **Порты указаны:** Разрешен трафик **только** на указанные порты. Трафик на все остальные порты блокируется, даже если源头 (source) разрешен.
*   **Порты не указаны (секция `ports` отсутствует):** Разрешен трафик на **все** порты протоколов TCP, UDP и SCTP. Это касается как входящего, так и исходящего трафика.

```yaml
# Пример: разрешен доступ ТОЛЬКО к порту 8080, даже от разрешенного пода
ingress:
- from:
  - podSelector:
      matchLabels:
        app: frontend
  ports:
  - protocol: TCP
    port: 8080
# Трафик от frontend на порт 443 будет заблокирован!
```

### Семантика from/to при комбинировании селекторов

Комбинация `namespaceSelector` и `podSelector` в одном элементе списка `from`/`to` работает по логическому «И»:

*   **`namespaceSelector` + `podSelector` в одном объекте:** Трафик разрешен от подов, соответствующих **обоим** селекторам одновременно (под с нужными метками **в** нужном пространстве имен).
*   **`namespaceSelector` + `podSelector` в разных объектах массива:** Трафик разрешен от **любого** пода в выбранном пространстве имен **ИЛИ** от подов с нужными метками в текущем пространстве имен.

```yaml
# Вариант А: namespaceSelector + podSelector в одном объекте (И)
# Разрешен ТОЛЬКО от подов app=frontend В namespace tenant-a
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        tenant: tenant-a
    podSelector:
      matchLabels:
        app: frontend

# Вариант Б: namespaceSelector и podSelector в разных объектах (ИЛИ)
# Разрешен от ЛЮБОГО пода в namespace tenant-a ИЛИ от подов app=frontend в текущем ns
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        tenant: tenant-a
  - podSelector:
      matchLabels:
        app: frontend
```

### Работа с портами и протоколами

*   **Именованные порты (Named Ports):** Вместо чисел можно указывать имена портов, определенные в `containerPort` пода. Это повышает гибкость при обновлении образов. CNI сопоставляет имя порта с числовым значением на этапе проверки правила.
*   **Протоколы:** Поддерживаются `TCP`, `UDP` и `SCTP` (поддержка SCTP зависит от CNI). Если протокол не указан, правило применяется ко всем протоколам.
*   **Диапазоны (endPort):** Позволяют открывать массивы портов одной записью. Диапазон включает как `port`, так и `endPort` (включительно). Поддержка `endPort` появилась в Kubernetes 1.21+.

### Жизненный цикл соединения (Stateful)

NetworkPolicy являются **stateful** (с сохранением состояния). Это означает:

1.  Если исходящий трафик (Egress) разрешен, то ответный входящий трафик (Return traffic) разрешается **автоматически** на уровне conntrack, независимо от наличия разрешающих правил Ingress.
2.  Если входящий трафик (Ingress) разрешен, то исходящий ответный трафик также разрешается автоматически.

**Практическое следствие:** При настройке Egress-политики не нужно создавать отдельные Ingress-правила для ответного трафика. Однако это работает только для **ответов** на уже установленные соединения. Новые инициированные подом соединения подчиняются Egress-правилам, а новые входящие соединения — Ingress-правилам.

### Взаимодействие с hostNetwork

NetworkPolicy обычно **не применяются** к подам, запущенным с `hostNetwork: true`. Такие поды используют сетевой стек хоста, и их трафик обрабатывается правилами iptables/nftables самого узла, минуя большинство механизмов изоляции CNI.

### Влияние DNAT и Services

NetworkPolicy работают на уровне IP подов, а не IP сервисов (ClusterIP).
*   **Ingress:** Когда трафик идет через Service, CNI видит его уже после DNAT (замены IP сервиса на IP конкретного пода). Поэтому политика Ingress должна разрешать трафик от *источника* (например, Ingress-контроллера).
*   **Egress:** Если под обращается к ClusterIP, правила Egress должны разрешать доступ либо к IP сервиса, либо к IP подов назначения (зависит от момента выполнения DNAT в конкретном CNI). Безопаснее разрешать доступ по селекторам подов.

### Трафик Loopback

NetworkPolicy не может заблокировать трафик внутри пода (между контейнерами через `127.0.0.1`), так как этот трафик не покидает сетевой стек пода и не проходит через CNI-плагин.

### FQDN Egress (Современный тренд)

Начиная с 2025 года, многие CNI (Cilium, Calico) и расширения K8s API поддерживают фильтрацию Egress по доменным именам (FQDN), что позволяет разрешать доступ, например, только к `api.github.com`, не отслеживая его динамические IP. Это решает ключевую проблему `ipBlock` — необходимость знать все IP-адреса заранее.

## Практические Сценарии

### Пример 1: Использование matchExpressions (Set-based)

Разрешение входящего трафика от подов, у которых метка `environment` имеет значение `prod` или `staging`, но отсутствует метка `debug`.

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
          values: [prod, staging]
        - key: debug
          operator: DoesNotExist
```

### Пример 2: Комбинирование Namespace и Pod Selector (Логическое «И»)

Трафик разрешен только от подов с меткой `app: frontend`, находящихся в Namespace с меткой `tenant: team-a`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-team-a
  namespace: backend
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
          tenant: team-a
      podSelector:
        matchLabels:
          app: frontend
```

### Пример 3: Раздельные правила (Логическое «ИЛИ»)

Разрешен трафик от любого пода в Namespace `monitoring` **ИЛИ** от подов с меткой `app: explorer` в текущем Namespace.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-monitoring-or-explorer
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
          name: monitoring
    - podSelector:
        matchLabels:
          app: explorer
```

### Пример 4: Именованные порты и диапазоны

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-named-ports-and-range
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: web-server
  policyTypes:
  - Ingress
  ingress:
  - ports:
    - protocol: TCP
      port: http-api # Ссылка на имя порта в Pod Spec
    - protocol: TCP
      port: 30000
      endPort: 32767 # Весь диапазон NodePort
```

### Пример 5: ipBlock с исключениями

Используется для внешнего трафика (вне кластера). Поле `except` исключает конкретные подсети.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-except-internal
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
        except:
        - 10.1.0.0/16
```

### Пример 6: Политика Egress с разрешением DNS

Классическая ошибка при настройке Egress — блокировка DNS-запросов. Без явного разрешения трафика к CoreDNS поды не смогут разрешать имена сервисов.

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
  # Правило 1: Разрешить DNS
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
  # Правило 2: Разрешить доступ к backend-сервисам
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: app-backend
    ports:
    - protocol: TCP
      port: 8080
```

### Пример 7: Комбинированная политика Ingress + Egress

Реалистичный сценарий: микросервис, который принимает запросы от frontend и обращается к базе данных и внешнему API.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-server-full-policy
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: production
      podSelector:
        matchLabels:
          app: frontend
    ports:
    - protocol: TCP
      port: 8080
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
    - protocol: TCP
      port: 53
  # База данных
  - to:
    - podSelector:
        matchLabels:
          app: postgres
    ports:
    - protocol: TCP
      port: 5432
  # Внешнее API (HTTP)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 169.254.169.254/32 # Защита от SSRF (Cloud Metadata)
    ports:
    - protocol: TCP
      port: 443
```

### Пример 8: Тестирование и отладка политики

Методология проверки корректности работы NetworkPolicy:

```bash
# 1. Убедиться, что политика создана и привязана к правильным подам
kubectl get networkpolicy -n production
kubectl describe networkpolicy api-server-full-policy -n production

# 2. Проверить, что поды имеют ожидаемые метки
kubectl get pods -n production --show-labels

# 3. Тест входящего трафика (из пода frontend в namespace production)
kubectl exec -it <frontend-pod> -n production -- \
  curl -v --connect-timeout 3 http://api-server.production.svc.cluster.local:8080
# Ожидаемый результат: HTTP 200 OK

# 4. Тест заблокированного входящего трафика (из пода без нужных меток)
kubectl exec -it <unauthorized-pod> -n production -- \
  curl -v --connect-timeout 3 http://api-server.production.svc.cluster.local:8080
# Ожидаемый результат: Connection timed out

# 5. Тест DNS-резолвинга (критично при Egress-изоляции)
kubectl exec -it <api-server-pod> -n production -- \
  nslookup postgres.production.svc.cluster.local
# Ожидаемый результат:Successful resolution

# 6. Тест доступа к БД
kubectl exec -it <api-server-pod> -n production -- \
  pg_isready -h postgres -p 5432
# Ожидаемый результат: accepting connections

# 7. Проверка через CNI (Cilium)
hubble observe --namespace production --verdict DROPPED
# Показывает отброшенные пакеты с указанием причины
```

## Дополнительные Сведения

### Производительность при большом количестве политик

Алгоритмическая сложность проверки правил зависит от реализации CNI:

*   **iptables (Calico стандартный режим):** Линейный перебор правил O(N). При количестве политик свыше 1000 и десятках тысяч подов наблюдается рост задержек и увеличение времени перезапуска подов (до 30+ секунд). Обновление таблиц iptables является атомарной операцией, но требует пересмотра всех правил.
*   **eBPF (Cilium, Calico eBPF):** Константное время поиска O(1) через хеш-таблицы. Прирост производительности критичен для кластеров с динамичными рабочими нагрузками. Время применения правил не зависит от их количества.
*   **Open vSwitch (Antrea):** Программируемые конвейеры обработки пакетов. Производительность зависит от сложности цепочки правил, но в целом конкурирует с eBPF для типичных сценариев.

**Рекомендация:** Для кластеров с более чем 500 политиками или 10000 подами рекомендуется переход на CNI на базе eBPF.

### Типичные ошибки и их устранение

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| Под не может разрешить DNS-имена | Egress-политика блокирует порт 53 | Добавить правило разрешения трафика к `kube-dns` в `kube-system` |
| Трафик блокируется между подами в одном namespace | `podSelector: {}` с `ingress: []` блокирует весь входящий трафик | Добавить разрешающие правила для необходимых подов |
| Политика создана, но не работает | Отсутствует поле `policyTypes` | Добавить `policyTypes: [Ingress]` и/или `[Egress]` |
| Трафик от подов другого namespace не проходит | Используется только `podSelector` в `from` | Добавить `namespaceSelector` для выбора подов из другого namespace |
| Трафик к Service блокируется | NetworkPolicy работает с IP подов, а не ClusterIP | Разрешать трафик по селекторам подов назначения, а не по IP сервиса |
| Поды с `hostNetwork: true` не подчиняются политике | Это ожидаемое поведение | Использовать `hostEndpoint` (Calico) или OVS-механизмы для фильтрации трафика хоста |

### Антипаттерны

1.  **Default Allow без политик:** Оставление namespace без NetworkPolicy означает, что любой под может беспрепятственно взаимодействовать со всеми其他 подами. Это критическая уязвимость.
2.  **Использование `ipBlock` для East-West трафика:** IP-адреса подов эфемерны и меняются при каждом перезапуске. Для внутреннего трафика используйте только `podSelector` и `namespaceSelector`.
3.  **Широкие разрешения `0.0.0.0/0` без `except`:** Разрешение всего исходящего трафика без исключений делает Egress-политику бессмысленной.
4.  **Забывание о DNS:** При включении Egress-изоляции без разрешения порта 53 поды теряют способность разрешать имена сервисов.
5.  **Отсутствие тестирования:** NetworkPolicy не логирует по умолчанию. Без проверки через `kubectl exec` или CNI-инструменты (Hubble) невозможно убедиться, что политика работает корректно.

### Мониторинг и аудит

Стандартный Kubernetes не логирует заблокированные пакеты. Для наблюдаемости:

*   **Cilium Hubble:** `hubble observe --namespace <ns> --verdict DROPPED` — показывает отброшенные пакеты с указанием политики и причины.
*   **Calico:** Логирование через `calico-node` с настройкой `audit: true` в правилах.
*   **Antrea Traceflow:** Пошаговая визуализация прохождения пакета через цепочки правил.
*   **kubectl debug:** Запуск временного контейнера с инструментами (`curl`, `dig`, `nc`) для проверки связности.

### Взаимодействие с kube-proxy и DNAT

NetworkPolicy проверяется ПОСЛЕ того, как kube-proxy выполняет DNAT (Destination NAT):

```
Клиент → Service ClusterIP → kube-proxy DNAT → Pod IP → NetworkPolicy Check
```

**Порядок обработки:**
1. Пакет поступает на Service ClusterIP
2. kube-proxy (iptables/IPVS/nftables) выполняет DNAT: заменяет ClusterIP на Pod IP
3. NetworkPolicy проверяет пакет с уже измененным IP-адресом назначения
4. Если NetworkPolicy разрешает — пакет доставляется поду

**Практическое следствие:** NetworkPolicy работает с IP подов, а не с ClusterIP. Поэтому:
- Ingress-правило должно разрешать трафик от *источника* (например, Ingress Controller), а не от Service
- Egress-правило должно разрешать доступ к *IP подов назначения*, а не к ClusterIP

**Как узнать Pod IP для Egress:**
```bash
# Через label selector
kubectl get pods -n production -l app=database -o jsonpath='{.items[*].status.podIP}'
# → 10.244.0.15 10.244.1.22
```

**Безопаснее:** Использовать `podSelector` + `namespaceSelector` вместо `ipBlock` для East-West трафика.

### См. также

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины и принцип Default Deny.
* [NetworkPolicy: Практические сценарии](./practical_scenarios.md) — примеры настройки Deny-all и доступа к DNS.
* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации по именованию и пошаговому внедрению.
