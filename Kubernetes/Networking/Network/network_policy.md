## Сетевая Изоляция и `NetworkPolicy`

**NetworkPolicy** — ресурс Kubernetes для управления правилами доступа к сети между подами. Требует поддержки со стороны CNI-плагина (Calico, Cilium, Weave Net).

О роли CNI и kube-proxy в сетевой модели Kubernetes см. [cni_kube_proxy_roles.md](./cni_kube_proxy_roles.md).

В Kubernetes по умолчанию реализуется **"плоская" сетевая модель**, что означает:

* **Все поды могут общаться со всеми подами** в кластере, независимо от их неймспейсов.
* **Неймспейсы — это логическое разделение** для управления ресурсами, а не сетевая граница.

Это упрощает развертывание, но представляет угрозу безопасности: скомпрометированный под может получить доступ ко всем остальным сервисам в кластере. Для обеспечения сетевой изоляции используются **Сетевые политики (`NetworkPolicy`)**.

**`NetworkPolicy`** — это ресурс Kubernetes, который позволяет управлять правилами доступа к сети между подами в кластере. Он работает как файрвол, определяя, какие поды могут взаимодействовать друг с другом, а также с внешними сущностями.

**Ключевая особенность:** `NetworkPolicy` — это **опция безопасности "opt-in"**. Это значит, что они не применяются до тех пор, пока вы явно не создадите `NetworkPolicy` для пода.

**Важно:** Для работы `NetworkPolicy` требуется установленный **CNI-плагин**, который поддерживает эту функциональность (например, Calico, Cilium, Weave Net). **Flannel** в стандартной конфигурации **не поддерживает** `NetworkPolicy`.

### Принцип "Запрещено по умолчанию" (Default Deny)

* Если для пода **нет ни одной** `NetworkPolicy`, он может общаться со всеми.
* Как только вы применяете **хотя бы одну** `NetworkPolicy` к поду, весь трафик, который не разрешен этой политикой (или другими политиками, применяющимися к этому же поду), **автоматически блокируется**.

Это означает, что при внедрении `NetworkPolicy` нужно быть очень внимательным и разрешать весь необходимый трафик, включая системный (например, DNS).

### Структура `NetworkPolicy`

Объект `NetworkPolicy` состоит из следующих ключевых полей:

* **`metadata.name`**: Имя политики.
* **`metadata.namespace`**: Неймспейс, к которому применяется политика.
* **`spec.podSelector`**: (Обязательно) Выбирает поды, к которым будет применяться данная политика.
  * Пустой `podSelector: {}` означает, что политика применяется ко **всем подам** в данном неймспейсе.
* **`spec.policyTypes`**: (Обязательно) Определяет, какие типы трафика регулируются политикой: `Ingress` (входящий), `Egress` (исходящий) или оба. Если не указано, по умолчанию `Ingress`.
* **`spec.ingress`**: Список правил для входящего трафика.
  * Каждое правило `ingress` может содержать `from` (разрешенные источники) и `ports` (разрешенные порты/протоколы).
* **`spec.egress`**: Список правил для исходящего трафика.
  * Каждое правило `egress` может содержать `to` (разрешенные назначения) и `ports` (разрешенные порты/протоколы).

#### Источники (`from`) и Назначения (`to`)

В правилах `ingress.from` и `egress.to` можно указывать:

1. **`podSelector`**: Поды, помеченные определенными метками (в том же неймспейсе, если `namespaceSelector` не указан).
2. **`namespaceSelector`**: Поды из неймспейсов, помеченных определенными метками.
3. **`ipBlock`**: Блоки IP-адресов (CIDR). Может использоваться для разрешения/запрета трафика к/от внешних ресурсов.

Правила в `ingress`/`egress` работают по принципу **"ИЛИ"**. Если в списке несколько правил, трафик разрешается, если он соответствует _любому_ из них. Если внутри одного правила есть несколько `from`/`to` или `ports`, они работают по принципу **"И"**.

---

## Примеры `NetworkPolicy`

### 1. Политика "Default Deny All" (Запретить всё по умолчанию)

Создает файрвол для всего неймспейса.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: my-app-ns
spec:
  podSelector: {} # Применяется ко всем подам в неймспейсе 'my-app-ns'
  policyTypes:
  - Ingress
  - Egress
```

Эта политика заблокирует весь входящий и исходящий трафик для всех подов в неймспейсе `my-app-ns`. После ее применения придется явно разрешать весь необходимый трафик.

### 2. Разрешить входящий трафик только от `frontend` к `backend`

Предположим, у вас есть поды `backend` (`app: backend`) и `frontend` (`app: frontend`), и вы хотите, чтобы только поды `frontend` могли обращаться к `backend`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: my-app-ns
spec:
  podSelector:
    matchLabels:
      app: backend # Политика применяется к подам с меткой app=backend
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend # Разрешить трафик от подов с меткой app=frontend в том же неймспейсе
    ports:
    - protocol: TCP
      port: 8080 # Разрешить только на порт 8080
```

Если `frontend` и `backend` находятся в разных неймспейсах, вам нужно использовать `namespaceSelector` вместе с `podSelector`.

### 3. Разрешить входящий трафик от `frontend` (из другого неймспейса) к `backend`

Предположим, `backend` находится в неймспейсе `prod-backend-ns`, а `frontend` в `prod-frontend-ns`. Неймспейс `prod-frontend-ns` помечен меткой `env: production`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-ns-to-backend
  namespace: prod-backend-ns
spec:
  podSelector:
    matchLabels:
      app: backend # Политика применяется к подам с меткой app=backend
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          env: production # Разрешить трафик из неймспейса с меткой env=production
      podSelector:
        matchLabels:
          app: frontend # Только от подов с меткой app=frontend внутри этого неймспейса
    ports:
    - protocol: TCP
      port: 8080
```

### 4. Разрешить исходящий трафик (Egress)

Разрешим подам `backend` обращаться только к базе данных (поды с меткой `app: database`) и внешнему API.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-egress-policy
  namespace: my-app-ns
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Egress
  egress:
  # 1. Разрешить трафик к базе данных (в том же неймспейсе)
  - to:
    - podSelector:
        matchLabels:
          app: database
    ports:
    - protocol: TCP
      port: 5432
  # 2. Разрешить трафик к внешнему API (например, 203.0.113.0/24)
  - to:
    - ipBlock:
        cidr: 203.0.113.0/24
    ports:
    - protocol: TCP
      port: 443
```

### 5. Обязательное правило: Разрешить DNS и доступ к API Server

После применения любой `NetworkPolicy` к поду, он перестанет общаться со всем, что явно не разрешено. Это включает DNS-сервер (CoreDNS) и Kubernetes API Server, что приведет к неработоспособности пода. Всегда добавляйте эти правила в egress-политики.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-and-api-server-egress
  namespace: my-app-ns
spec:
  podSelector: {} # Применяем ко всем подам в неймспейсе
  policyTypes:
  - Egress
  egress:
  # Правило 1: Разрешить DNS-запросы
  - ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
  # Правило 2: Разрешить доступ к Kubernetes API Server
  # Замените <KUBE_API_SERVER_IP_CIDR> на реальный IP-адрес/CIDR вашего API-сервера.
  # Обычно это ClusterIP вашего Service kubernetes.default в неймспейсе default.
  # kubectl get svc kubernetes -o jsonpath='{.spec.clusterIP}/32'
  - to:
    - ipBlock:
        cidr: <KUBE_API_SERVER_IP_CIDR> # Например, 10.96.0.1/32
    ports:
    - port: 443 # Порт kube-apiserver
      protocol: TCP
```

## Лучшие практики использования `NetworkPolicy`

* **Принцип "Default Deny":** Всегда начинайте с политики, которая блокирует весь трафик для неймспейса, а затем явно разрешайте необходимый. Это значительно повышает безопасность.
* **Используйте `NamespaceSelector`:** Для контроля доступа между неймспейсами, это гораздо надежнее, чем полагаться на `ipBlock`.
* **Метки - основа:** `NetworkPolicy` сильно зависят от корректных меток на подах и неймспейсах. Поддерживайте строгую дисциплину именования и маркировки.
* **Инкрементальное внедрение:** Внедряйте политики постепенно, начиная с тестовых сред, и используйте инструменты мониторинга для отслеживания заблокированного трафика.
* **Всегда разрешайте DNS и API Server:** Это самая частая ошибка, которая приводит к неработоспособности подов после применения политики.
* **Тестирование:** Используйте временные поды с инструментами вроде `curl`, `netcat`, `ping`, `dig` для проверки связности после применения политик.
* **Логирование:** Некоторые CNI-плагины (например, Calico) позволяют логировать заблокированный трафик, что очень помогает при отладке.
