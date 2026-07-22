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

## Дополнительные Сведения

### Диагностика сетевой связности

Для проверки действующих политик и отладки рекомендуется использовать следующие методы:

1. **Эфемерные контейнеры (kubectl debug):** запуск отладочного контейнера внутри существующего Pod без его перезагрузки.
   ```bash
   kubectl debug pod/webapp-pod -it --image=curlimages/curl -- curl -v http://api-server:8080
   ```
2. **Временные отладочные поды:**
   ```bash
   # Тестирование DNS
   kubectl run test-dns --rm -it --image=registry.k8s.io/dnsutils:1.3 -- nslookup api-server
   ```
3. **Анализ примененных правил:**
   ```bash
   kubectl describe networkpolicy allow-ingress-frontend-to-api -n app-backend
   ```

### Сброс сетевой конфигурации

В случае критических ошибок в конфигурации, блокирующих доступ к кластеру, политики можно удалить массово:
```bash
kubectl delete networkpolicy --all -n <namespace>
```

**См. также:**
* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины и 3-Tier модель.
* [NetworkPolicy: Логика правил](./rule_logic.md) — детальный разбор логики И/ИЛИ.
* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации по именованию и безопасности.
