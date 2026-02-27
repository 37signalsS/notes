# NetworkPolicy: управление трафиком между Pod'ами

## Определения

**NetworkPolicy** — объект Kubernetes API для декларативного управления сетевым доступом на уровне L3/L4 между Pod'ами и внешними адресами.

**Селектор Pod'ов (`podSelector`)** — механизм выбора целевых Pod'ов по меткам для применения политик.

**Ingress** — правила входящего трафика к Pod'ам.

**Egress** — правила исходящего трафика от Pod'ов.

**CNI (Container Network Interface)** — плагин сетевой подсистемы Kubernetes, обеспечивающий реализацию NetworkPolicy.

## Основные концепции

### Принцип работы

NetworkPolicy действует по принципу **явного разрешения**:

- По умолчанию (если нет политик, селектящих Pod) — весь трафик разрешён
- При наличии политики с указанным направлением — только явно разрешённый трафик
- Политики **аддитивны**: объединение всех правил из всех селектящих политик
- Пустые списки правил = полный запрет (deny all) по данному направлению

### Ключевые элементы спецификации

| Поле | Описание | Пример |
|------|----------|--------|
| `podSelector` | Выбор Pod'ов по меткам | `matchLabels: {app: backend}` |
| `policyTypes` | Направления контроля | `Ingress`, `Egress` |
| `ingress` | Правила входящего трафика | `from`, `ports` |
| `egress` | Правила исходящего трафика | `to`, `ports` |

### Типы источников/получателей (`from`/`to`)

| Тип | Описание | Use Case |
|-----|----------|----------|
| `podSelector` | Pod'ы по меткам в том же namespace | Frontend → Backend |
| `namespaceSelector` | Все Pod'ы в совпавших namespace | Межкомандные интеграции |
| `podSelector` + `namespaceSelector` | Pod'ы в конкретных namespace | Изоляция окружений |
| `ipBlock` | CIDR-диапазоны | Доступ к внешним БД, интернету |

### Порты и протоколы

- `port`: номер порта или имя порта из spec контейнера
- `protocol`: TCP (по умолчанию), UDP, SCTP

### Требования к CNI

NetworkPolicy работает только при условии поддержки со стороны CNI-плагина:

- Calico, Cilium, Weave Net
- ❌ Flannel (не поддерживает)

## Практические сценарии

### Сценарий 1: Default Deny (полная изоляция)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-default-deny
  namespace: team-a
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  - Egress
```

Политика изолирует все Pod'ы с меткой `app: backend`: запрещает весь входящий и исходящий трафик.

### Сценарий 2: Разрешение конкретного трафика

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-allow-specific
  namespace: team-a
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - port: 5432
      protocol: TCP
  egress:
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - port: 443
      protocol: TCP
```

Разрешает:

- Входящий трафик от `app: frontend` на порт 5432
- Исходящий HTTPS-трафик (порт 443) в интернет

### Сценарий 3: Межпространственное взаимодействие

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-allow-monitoring
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          purpose: monitoring
    - podSelector:
        matchLabels:
          app: prometheus
      namespaceSelector:
        matchLabels:
          purpose: monitoring
    ports:
    - port: 8080
```

Разрешает доступ к API от Pod'ов Prometheus из namespace с меткой `purpose: monitoring`.

### Сценарий 4: Доступ к внешним сервисам

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-access
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 10.0.2.0/24
    ports:
    - port: 5432
      protocol: TCP
```

Разрешает backend'у доступ к PostgreSQL в подсети 10.0.2.0/24.

### Сценарий 5: Исключения из ipBlock

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: limited-internet-access
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: frontend
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 10.0.0.0/8      # Запретить доступ к внутренней сети
        - 192.168.0.0/16  # Запретить доступ к внутренней сети
    ports:
    - port: 443
```

Разрешает доступ в интернет по HTTPS, но блокирует внутренние сети.

## Дополнительная информация

### Ограничения NetworkPolicy

- **L3/L4 только**: нет фильтрации по FQDN/доменам
- **IP-based**: доменные имена учитываются только через разрешённые IP
- **Не отменяет Service**: политики работают на сетевом уровне
- **Матчинг по IP**: при изменении IP Pod'а политика может нарушиться

### Альтернативы для L7

Для фильтрации по доменам (FQDN) используйте:

- **Cilium** — встроенная поддержка DNS/FQDN
- **Calico** — NetworkSets с доменами
- **Service Mesh** (Istio, Linkerd) — L7-авторизация

### Паттерны безопасности

- **Zero Trust**: default deny + явные разрешения
- **Segmentation**: изоляция namespace по командам/окружениям
- **Least Privilege**: минимально необходимые порты и протоколы

### Связанные темы

- Безопасность секретов: [Sealed Secrets](sealed_secrets_overview.md)
- RBAC для доступа к API: [RBAC Overview](./rbac/rbac_overview.md)
- [Kubernetes NetworkPolicy Documentation](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
