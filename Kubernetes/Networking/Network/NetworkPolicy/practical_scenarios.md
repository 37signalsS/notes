# NetworkPolicy: Практический Сценарий — От Изоляции до Разрешения DNS

Этот сценарий демонстрирует поэтапное внедрение `NetworkPolicy` на примере.

## Шаг 0: Настройка тестового стенда

Создадим тестовую среду из нескольких приложений в разных неймспейсах:

* **`app1`**: Неймспейс с приложением-прокси `webapp`. `webapp` принимает запросы и перенаправляет их другим сервисам.
* **`app2`**: Неймспейс с двумя сервисами: `backend-api` и `nginx`.
* **`default`**: Неймспейс с утилитой `dns-tools` для тестирования.

Изначально все приложения могут свободно общаться друг с другом.

## Шаг 1: Полная изоляция неймспейса (`Default Deny`)

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

## Шаг 2: Разрешение трафика от конкретного приложения

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

## Шаг 3: Побочный эффект селекторов

Это важный нюанс. Если удалить политику `default-deny-ingress` из Шага 1, оставив только `allow-webapp-to-backend-api` из Шага 2:

* **`backend-api`**: Останется под действием политики. К нему сможет подключиться только `webapp`, так как для него активен режим "запрещено по умолчанию".
* **`nginx`**: Так как он **не выбирается** селектором `podSelector: {matchLabels: {app: backend-api}}`, на него **не действует ни одна политика**. Следовательно, для него возвращается режим "разрешено всё по умолчанию". Любой сервис снова сможет к нему подключиться.

**Вывод:** Как только вы затронули под любой политикой, он изолируется. Поды, не затронутые ни одной политикой, остаются полностью открытыми.

## Шаг 4: Egress-политика и проблема с DNS

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

## Шаг 5: Разрешение трафика к DNS

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
