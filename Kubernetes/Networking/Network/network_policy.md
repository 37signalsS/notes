# Сетевая Изоляция и NetworkPolicy

## 1. Определения и Основные Концепты

**NetworkPolicy** — это ресурс Kubernetes для декларативного управления правилами доступа к сети (L3/L4) между подами и внешними сущностями. Он функционирует как встроенный файрвол, но для его работы требуется сетевой плагин (CNI), который поддерживает эту функциональность (например, Calico, Cilium, Weave Net). **Flannel** в стандартной конфигурации **не поддерживает** `NetworkPolicy`.

О роли CNI и kube-proxy в сетевой модели Kubernetes см. [cni_kube_proxy_roles.md](./cni_kube_proxy_roles.md).

> **Примечание:** Calico расширяет стандартные NetworkPolicy дополнительными возможностями, включая фильтрацию трафика NodePort/LoadBalancer до NAT, работу с HostEndpoint и логирование. *Подробнее: [Calico HostEndpoint и GlobalNetworkPolicy](../../Security/network_policies/Calico/index.md)*

### Сетевая Модель по Умолчанию

В Kubernetes по умолчанию реализуется **"плоская" сетевая модель**, описанная в [общем обзоре сетевой модели](./network_overview.md):

* **Все поды могут общаться со всеми подами** в кластере, независимо от их неймспейсов.
* **Неймспейсы — это логическое разделение**, а не сетевая граница.

Это упрощает развертывание, но представляет угрозу безопасности. Для решения этой проблемы используются `NetworkPolicy`.

### Принцип "Запрещено по Умолчанию" (Default Deny)

`NetworkPolicy` — это **опция безопасности "opt-in"** (включаемая по желанию).

* Если для пода **не создано ни одной** `NetworkPolicy`, весь трафик для него разрешен.
* Как только вы применяете **хотя бы одну** `NetworkPolicy` к поду, для него немедленно включается режим "запрещено по умолчанию". Весь трафик, который явно не разрешен этой или другими политиками, **автоматически блокируется**.

Это означает, что при внедрении `NetworkPolicy` нужно быть очень внимательным и явно разрешать весь необходимый трафик, включая системный (например, DNS).

### Структура `NetworkPolicy`

* **`spec.podSelector`**: Выбирает поды, к которым применяется политика. Пустой `podSelector: {}` выбирает **все поды** в неймспейсе.
* **`spec.policyTypes`**: Определяет типы трафика: `Ingress` (входящий), `Egress` (исходящий) или оба.
* **`spec.ingress`**: Список правил для входящего трафика.
* **`spec.egress`**: Список правил для исходящего трафика.

#### Источники (`from`) и Назначения (`to`)

1. **`podSelector`**: Выбирает поды по меткам.
2. **`namespaceSelector`**: Выбирает поды из неймспейсов по их меткам.
3. **`ipBlock`**: Указывает диапазоны IP-адресов в формате CIDR.

> **Важно:** `namespaceSelector` работает по **меткам namespace**, а не по его имени. По умолчанию у namespace нет меток — их нужно добавлять явно. Для выбора по имени используйте метку `kubernetes.io/metadata.name: <namespace-name>`.

#### Target, Source, Destination — терминология

При описании политик важно различать три концепции:

* **Target (цель)**: Поды, к которым применяется политика (указываются в `spec.podSelector`)
* **Source (источник)**: Откуда приходит трафик (указывается в `spec.ingress.from`)
* **Destination (назначение)**: Куда уходит трафик (указывается в `spec.egress.to`)

**Нюанс:** `target` может быть как `source`, так и `destination` в зависимости от направления политики:
* В `ingress`-политике: target = destination, from = source
* В `egress`-политике: target = source, to = destination

#### Важные нюансы реализации

**1. Порты указываются для Pod, а не для Service**

Политики применяются к подам, поэтому в `ports` указываются порты контейнера, а не сервиса. Например, если сервис на порту 80 перенаправляет трафик на pod:8080, в политике нужно указать порт 8080.

**2. Проблема NAT и Source IP**

При использовании `NodePort` или `LoadBalancer` без `externalTrafficPolicy: Local` исходный IP клиента подменяется на IP ноды. В этом случае `ipBlock` в политиках должен указывать подсеть нод, а не клиентов. Для сохранения оригинального IP используйте:
* `externalTrafficPolicy: Local`
* CNI с поддержкой Direct Server Return (например, Calico)

**3. Визуализация политик**

Для проверки и отладки политик рекомендуется использовать визуализаторы, например [Orca Turfin](https://orca-tufin.com/), которые преобразуют YAML в графическое представление и текстовое описание правил.

### Логика Правил: "И" и "ИЛИ"

Понимание логических операторов критически важно:

* **Логическое "ИЛИ"**: Элементы в списках `ingress`, `egress`, `from`, `to` объединяются по "ИЛИ". Трафик разрешается, если он соответствует **любому** правилу в списке.
* **Логическое "И"**: Поля внутри одного элемента (`podSelector`, `namespaceSelector`, `ports`) объединяются по "И". Трафик должен соответствовать **всем** условиям внутри правила.

#### Примеры различной логики

**Пример 1: Логическое "ИЛИ" в списке `from`**

```yaml
ingress:
- from:
  - podSelector:
      matchLabels:
        app: indexer
  - podSelector:
      matchLabels:
        app: opadmin
  ports:
  - port: 5432
```

**Результат:** Разрешён трафик от подов с меткой `app: indexer` **ИЛИ** `app: opadmin` на порт 5432.

**Пример 2: Логическое "И" внутри одного элемента**

```yaml
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        env: default
    podSelector:
      matchLabels:
        role: opadmin
  ports:
  - port: 5432
```

**Результат:** Разрешён трафик только от подов с меткой `role: opadmin`, находящихся в namespace с меткой `env: default`. Оба условия должны выполняться **одновременно**.

**Пример 3: Разные порты для разных селекторов**

```yaml
ingress:
- from:
  - podSelector:
      matchLabels:
        app: indexer
  ports:
  - port: 443
- from:
  - podSelector:
      matchLabels:
        app: admin
  ports:
  - port: 80
```

**Результат:**
* Для `indexer`: разрешён только порт 443
* Для `admin`: разрешён только порт 80

**Пример 4: Комбинация namespaceSelector и podSelector**

```yaml
# Вариант А: И (один элемент массива)
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        env: default
    podSelector:
      matchLabels:
        role: opadmin

# Вариант Б: ИЛИ (два элемента массива)
ingress:
- from:
  - namespaceSelector:
      matchLabels:
        env: default
  - podSelector:
      matchLabels:
        role: opadmin
```

**Результат:**
* **Вариант А (И):** Поды `opadmin` из namespace `default`
* **Вариант Б (ИЛИ):** Любые поды из namespace `default` **ИЛИ** любые поды с меткой `opadmin` из текущего namespace

---

## 2. Практический сценарий: От изоляции до разрешения DNS

Этот сценарий демонстрирует поэтапное внедрение `NetworkPolicy` на примере.

### Шаг 0: Настройка тестового стенда

Создадим тестовую среду из нескольких приложений в разных неймспейсах:

* **`app1`**: Неймспейс с приложением-прокси `webapp`. `webapp` принимает запросы и перенаправляет их другим сервисам.
* **`app2`**: Неймспейс с двумя сервисами: `backend-api` и `nginx`.
* **`default`**: Неймспейс с утилитой `dns-tools` для тестирования.

Изначально все приложения могут свободно общаться друг с другом.

### Шаг 1: Полная изоляция неймспейса (`Default Deny`)

Первый шаг — заблокировать весь входящий трафик для неймспейса `app2`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: app2
spec:
  podSelector: {} # Применяется ко всем подам
  policyTypes:
  - Ingress
  ingress: [] # Пустой список правил означает "ничего не разрешать"
```

**Результат:** Любые попытки `webapp` из `app1` или `dns-tools` из `default` обратиться к сервисам в `app2` завершатся ошибкой `Connection timed out`.

### Шаг 2: Разрешение трафика от конкретного приложения

Теперь разрешим приложению `webapp` из `app1` обращаться к `backend-api` в `app2`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-webapp-to-backend-api
  namespace: app2
spec:
  podSelector:
    matchLabels:
      app: backend-api # Политика применяется только к backend-api
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          # Предполагается, что неймспейс app1 имеет метку name: app1
          name: app1 
      podSelector:
        matchLabels:
          app: webapp # Разрешить трафик от webapp
    ports:
    - protocol: TCP
      port: 8080
```

**Результат:** `webapp` теперь может успешно подключиться к `backend-api`, но не к `nginx`.

### Шаг 3: Побочный эффект селекторов

Это важный нюанс. Если удалить политику `default-deny-ingress` из Шага 1, оставив только `allow-webapp-to-backend-api` из Шага 2:

* **`backend-api`**: Останется под действием политики. К нему сможет подключиться только `webapp`, так как для него активен режим "запрещено по умолчанию".
* **`nginx`**: Так как он **не выбирается** селектором `podSelector: {matchLabels: {app: backend-api}}`, на него **не действует ни одна политика**. Следовательно, для него возвращается режим "разрешено всё по умолчанию". Любой сервис снова сможет к нему подключиться.

**Вывод:** Как только вы затронули под любой политикой, он изолируется. Поды, не затронутые ни одной политикой, остаются полностью открытыми.

### Шаг 4: Egress-политика и проблема с DNS

Теперь применим исходящую (`Egress`) политику к неймспейсу `app1`, разрешив ему обращаться только к `app2`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-app2
  namespace: app1
spec:
  podSelector: {} # Ко всем подам в app1
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: app2 # Разрешить исходящий трафик в неймспейс app2
```

**Результат:** Приложение `webapp` снова не может подключиться к `backend-api`. Ошибка — `Resolving Timeout`. Причина в том, что `webapp` пытается преобразовать доменное имя `backend-api.app2.svc.cluster.local` в IP-адрес, но `egress` политика **заблокировала доступ к DNS-серверу** Kubernetes (CoreDNS).

### Шаг 5: Разрешение трафика к DNS

Чтобы исправить это, нужно явно разрешить DNS-трафик.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-dns
  namespace: app1
spec:
  podSelector: {} # Ко всем подам в app1
  policyTypes:
  - Egress
  egress:
  - to: # Правило ИЛИ
    - namespaceSelector:
        matchLabels:
          name: app2 # Все еще разрешаем трафик в app2
  - to: # Правило ИЛИ
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

**Результат:** DNS-запросы теперь разрешены, и `webapp` снова может подключаться к `backend-api`.

**Важный нюанс:** В некоторых конфигурациях кластера (например, с `node-local-dns`), DNS-сервер может быть доступен по статическому IP-адресу. В таком случае правило должно использовать `ipBlock`:

```yaml
  # ...
  egress:
  - to:
    - ipBlock:
        # IP-адрес NodeLocal DNSCache
        cidr: 169.254.20.10/32 
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
```

---

## 3. Лучшие практики

* **Начинайте с "Default Deny":** Всегда начинайте с политики, которая блокирует весь трафик для неймспейса, а затем явно разрешайте необходимый.
* **Используйте `NamespaceSelector`:** Для контроля доступа между неймспейсами это надежнее, чем `ipBlock`.
* **Дисциплина меток:** `NetworkPolicy` сильно зависят от корректных меток. Поддерживайте строгую дисциплину маркировки.
* **Разрешайте системный трафик:** Всегда явно разрешайте Egress-трафик к DNS и API Server.
* **Тестируйте:** Используйте временные поды с `curl`, `netcat`, `dig` для проверки связности после применения политик.
* **Используйте логирование:** Некоторые CNI (например, Calico) позволяют логировать заблокированный трафик, что помогает при отладке.

---

## 4. Дополнительные сведения

#### Локальный трафик пода

**NetworkPolicy не ограничивает трафик между контейнерами внутри одного пода**. Они могут свободно общаться через loopback-интерфейс.

#### Двусторонний трафик

Для подключения от пода А к поду Б необходимо разрешить трафик **и в `egress`-политике пода А, и в `ingress`-политике пода Б**.

#### Диапазоны портов

Для указания диапазона портов можно использовать параметр `endPort`, который указывает конец диапазона включительно:

```yaml
ports:
- protocol: TCP
  port: 30000
  endPort: 30002
```

#### Реализация сетевыми плагинами (CNI)

**Критически важно:** NetworkPolicy работает только при наличии CNI-плагина с поддержкой этой функциональности.

| CNI | Поддержка NetworkPolicy | Примечания |
|-----|------------------------|------------|
| **Calico** | ✅ Полная | Расширения: HostEndpoint, GlobalNetworkPolicy, логирование, ICMP |
| **Cilium** | ✅ Полная | Расширения: L7-политики, FQDN-фильтрация, eBPF |
| **Weave Net** | ✅ Полная | Базовая поддержка |
| **Flannel** | ❌ Нет | Только связность подов, без политик |
| **Kube-router** | ✅ Полная | На основе iptables |
| **Antrea** | ✅ Полная | На основе Open vSwitch |

**Стандартная vs расширенная функциональность:**

Все CNI с поддержкой NetworkPolicy реализуют **базовый стандарт** Kubernetes:
* Селекторы: `podSelector`, `namespaceSelector`, `ipBlock`
* Протоколы: TCP, UDP, SCTP
* policyTypes: Ingress, Egress

**Расширения CNI** (нестандартные, vendor-specific):
* **Calico:**
  * `HostEndpoint` — политики для интерфейсов нод
  * `GlobalNetworkPolicy` — кластерные политики вне namespace
  * `preDNAT` — фильтрация до NAT (для NodePort/LoadBalancer)
  * Логирование заблокированного трафика
  * Блокировка ICMP
* **Cilium:**
  * L7-политики (HTTP, gRPC, Kafka)
  * FQDN-фильтрация (DNS-based)
  * Identity-based политики

> **Важно:** Если вы используете Flannel и создадите NetworkPolicy, ограничения **не будут применены** — трафик продолжит проходить свободно. Требуется замена CNI на поддерживающий политики.

#### Allow-all и Deny-all политики

**Явного правила "deny" в Kubernetes нет**, но можно достичь того же эффекта:

**Deny-all (запрет всего):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  # ingress: [] — пустой список или отсутствие поля
```

**Разрешить всё (для override):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-all
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - {} # Пустое правило разрешает весь трафик
```

**Нюанс:** Если `policyTypes` не указан:
* При наличии `ingress`-правил: автоматически добавляется `Ingress`
* При наличии `egress`-правил: автоматически добавляется `Egress`
* Если политик нет: политика не применяется
