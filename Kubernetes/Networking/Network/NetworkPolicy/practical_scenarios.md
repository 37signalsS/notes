# NetworkPolicy: Практические сценарии

## Определения

**Практический сценарий NetworkPolicy** — пошаговое руководство по внедрению сетевой изоляции в Kubernetes с демонстрацией типовых проблем и их решений.

**Default Deny (Запрет по умолчанию)** — стратегия безопасности, при которой весь трафик блокируется, если он не разрешен явно.

**Сетевая изоляция** — механизм ограничения сетевого взаимодействия между компонентами системы для уменьшения поверхности атаки.

## Базовые Концепции

### Демонстрируемые принципы

В данном сценарии рассматриваются ключевые принципы работы ресурсов NetworkPolicy:

- **Изоляция по умолчанию** — использование принципа «Запрещено по умолчанию» для входящего и исходящего трафика.
- **Селекторы объектов** — применение политик через `podSelector` (селектор подов) и `namespaceSelector` (селектор пространств имен).
- **Разрешение системных служб** — обязательная настройка доступа к критической инфраструктуре, такой как DNS (Domain Name System).
- **Межпространственная изоляция** — управление трафиком между Namespaces с использованием меток.

### Тестовая среда

Сценарий предполагает наличие трех Namespaces (пространств имен) со следующими компонентами:

| Namespace | Компонент | Описание |
|-----------|-----------|----------|
| `app1` | `webapp` | Приложение-прокси, перенаправляющее HTTP-запросы |
| `app2` | `backend-api` | Основной сервис API (Application Programming Interface) |
| `app2` | `nginx` | Статический веб-сервер |
| `default` | `dns-tools` | Утилита для тестирования сетевой связности и DNS |

Изначально в кластере действует «плоская» сеть: все Pod (поды) могут свободно взаимодействовать друг с другом.

## Практические Сценарии

### Шаг 1: Полная изоляция пространства имен (Default Deny)

Первым этапом внедрения безопасности является блокировка всего входящего трафика для Namespace `app2`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: app2
spec:
  podSelector: {} # Выбирает все поды в пространстве имен
  policyTypes:
  - Ingress
  ingress: [] # Пустой список правил означает полный запрет
```

**Результат:** Попытки обращения от `webapp` (Namespace `app1`) или `dns-tools` (Namespace `default`) к сервисам в `app2` будут завершаться ошибкой `Connection timed out`.

*Подробнее о концепции: [NetworkPolicy: Определения и концепции](./definitions.md#принцип-default-deny-запрещено-по-умолчанию)*

### Шаг 2: Разрешение доступа от конкретного приложения

Разрешим приложению `webapp` обращаться к `backend-api` на порту 8080 по протоколу TCP (Transmission Control Protocol).

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
          # Для работы селектора необходимо наличие метки на namespace
          name: app1
      podSelector:
        matchLabels:
          app: webapp
    ports:
    - protocol: TCP
      port: 8080
```

**Результат:** `webapp` может подключаться к `backend-api`, но доступ к `nginx` для него остается закрытым.

### Шаг 3: Особенности работы селекторов

Важно понимать побочный эффект применения политик. Если удалить общую политику `default-deny-ingress`, оставив только специфичную для `backend-api`:

- **`backend-api`**: Останется изолированным, так как к нему применяется одна политика.
- **`nginx`**: Станет снова полностью открытым для всего кластера, так как ни одна политика его не выбирает.

**Вывод:** Безопасность обеспечивается только тогда, когда каждый Pod охвачен хотя бы одной политикой.

### Шаг 4: Изоляция исходящего трафика и проблема DNS

Применим политику `Egress` (исходящий трафик) для Namespace `app1`, разрешив обращения только в сторону `app2`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-app2
  namespace: app1
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: app2
```

**Результат:** Приложение `webapp` перестанет работать. Ошибка `Resolving Timeout` указывает на то, что Pod больше не может обратиться к DNS-серверу кластера для преобразования имен в IP (Internet Protocol) адреса.

### Шаг 5: Корректное разрешение системного DNS

Для восстановления работоспособности необходимо явно разрешить исходящий трафик к CoreDNS (обычно находится в `kube-system`).

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-dns
  namespace: app1
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: app2
  - to: # Правило для DNS (UDP и TCP порт 53)
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

*UDP (User Datagram Protocol).*

### Альтернатива: Использование ipBlock для DNS

Если в кластере используется фиксированный IP-адрес для DNS (например, NodeLocal DNSCache), можно использовать CIDR (Classless Inter-Domain Routing).

```yaml
egress:
- to:
  - ipBlock:
      cidr: 169.254.20.10/32
  ports:
  - port: 53
    protocol: UDP
```

## Дополнительные Сведения

### Диагностика сетевой связности

Для проверки действующих политик рекомендуется использовать временные отладочные Pod:

```bash
# Тестирование входящего трафика
kubectl run test-curl --rm -it --image=curlimages/curl -- curl -v http://<service-name>

# Тестирование разрешения имен (DNS)
kubectl run test-dig --rm -it --image=registry.k8s.io/dnsutils:1.3 -- nslookup <service-name>

# Проверка применённых ресурсов в пространстве имен
kubectl get networkpolicy -n <namespace>
```

### Сброс конфигурации

Для быстрого восстановления связи при ошибках в конфигурации можно использовать удаление всех политик (в тестовых средах):

```bash
kubectl delete networkpolicy --all -n <namespace>
```

- **Лучшие практики**: [NetworkPolicy: Лучшие практики](./best_practices.md)
- **Логика правил**: [NetworkPolicy: Логика правил](./rule_logic.md)
- **Реализация CNI**: [NetworkPolicy: Реализация CNI-плагинами](./cni_implementation.md)
