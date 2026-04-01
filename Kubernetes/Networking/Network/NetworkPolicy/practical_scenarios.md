# NetworkPolicy: Практический Сценарий — От Изоляции до Разрешения DNS

## Определения

**Практический сценарий NetworkPolicy** — пошаговое руководство по внедрению сетевой изоляции в Kubernetes с демонстрацией типовых проблем и их решений.

## Базовые Концепции

### Демонстрируемые принципы

В данном сценарии рассматриваются ключевые принципы работы NetworkPolicy:

- **Default Deny** — запрет всего трафика по умолчанию с последующим явным разрешением необходимого
- **Селекторы** — применение политик к подам через `podSelector` и `namespaceSelector`
- **Egress для DNS** — необходимость явного разрешения DNS-трафика при использовании egress-политик
- **Изоляция namespace** — контроль трафика между неймспейсами через метки

### Тестовая среда

Сценарий использует три неймспейса:

| Namespace | Описание |
|-----------|----------|
| `app1` | Приложение-прокси `webapp`, перенаправляющее запросы |
| `app2` | Сервисы `backend-api` и `nginx` |
| `default` | Утилита `dns-tools` для тестирования |

Изначально все приложения могут свободно общаться друг с другом (плоская сеть Kubernetes).

## Практические Сценарии

### Шаг 1: Полная изоляция неймспейса (Default Deny)

Первый шаг — заблокировать весь входящий трафик для неймспейса `app2`:

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

*Подробнее: [Default Deny политики](./definitions.md#типовые-политики-allow-all-и-deny-all)*

### Шаг 2: Разрешение трафика от конкретного приложения

Разрешим приложению `webapp` из `app1` обращаться к `backend-api` в `app2`:

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

Важный нюанс. Если удалить политику `default-deny-ingress` из Шага 1, оставив только `allow-webapp-to-backend-api` из Шага 2:

- **`backend-api`**: Останется под действием политики. К нему сможет подключиться только `webapp`, так как для него активен режим "запрещено по умолчанию".
- **`nginx`**: Так как он **не выбирается** селектором `podSelector: {matchLabels: {app: backend-api}}`, на него **не действует ни одна политика**. Следовательно, для него возвращается режим "разрешено всё по умолчанию". Любой сервис снова сможет к нему подключиться.

**Вывод:** Как только вы затронули под любой политикой, он изолируется. Поды, не затронутые ни одной политикой, остаются полностью открытыми.

### Шаг 4: Egress-политика и проблема с DNS

Применим исходящую (`Egress`) политику к неймспейсу `app1`, разрешив ему обращаться только к `app2`:

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

Чтобы исправить это, нужно явно разрешить DNS-трафик:

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

### Альтернатива: DNS через ipBlock

В некоторых конфигурациях кластера (например, с `node-local-dns`), DNS-сервер может быть доступен по статическому IP-адресу. В таком случае правило должно использовать `ipBlock`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-dns-ip
  namespace: app1
spec:
  podSelector: {}
  policyTypes:
  - Egress
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

## Дополнительные Сведения

### Диагностика проблем связности

Для проверки политик используйте временные поды:

```bash
# Тестирование ingress
kubectl run test-curl --rm -it --image=curlimages/curl -- curl -v http://<service>:<port>

# Тестирование egress и DNS
kubectl run test-dig --rm -it --image=registry.k8s.io/dnsutils:1.3 -- dig <service>.<namespace>.svc.cluster.local

# Проверка применённых политик
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy <name> -n <namespace>
```

### Команды для сброса политик

```bash
# Удалить все политики в namespace
kubectl delete networkpolicy --all -n <namespace>

# Удалить конкретную политику
kubectl delete networkpolicy <name> -n <namespace>
```

*Подробнее о лучших практиках: [best_practices.md](./best_practices.md)*  
*Подробнее о логике правил: [rule_logic.md](./rule_logic.md)*  
*Подробнее о базовых концепциях: [definitions.md](./definitions.md)*
