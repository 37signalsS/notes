# Тип Service — Headless

## Определения

**Headless Service** — тип сервиса в Kubernetes, который не имеет виртуального IP-адреса кластера (`ClusterIP`). При создании такого ресурса в манифесте указывается `spec.clusterIP: None`.

**Основная задача:** Обеспечение прямого обнаружения (discovery) сетевых адресов отдельных подов через DNS-записи, минуя механизмы проксирования и балансировки трафика.

## Основные концепции

### Механизм DNS Discovery

При создании Headless Service DNS-сервер кластера (CoreDNS) автоматически формирует записи нескольких типов:

| Тип записи | Формат | Назначение |
| :--- | :--- | :--- |
| **A/AAAA-запись сервиса** | `<name>.<ns>.svc.cluster.local` | Возвращает список IP-адресов всех готовых подов (IPv4/IPv6) |
| **A/AAAA-запись пода** | `<pod>.<name>.<ns>.svc.cluster.local` | Возвращает IP-адрес конкретного пода |
| **SRV-запись** | `_<port-name>._<proto>.<name>.<ns>.svc.cluster.local` | Возвращает номер порта и DNS-имена подов для именованных портов |

Это позволяет клиенту обращаться напрямую к любому экземпляру приложения или получать полный список адресов всех реплик.

### Характеристики и особенности

- **Отсутствие ClusterIP:** Поле `clusterIP: None` указывает системе не выделять виртуальный IP.
- **Отсутствие балансировки:** Трафик не распределяется на стороне Kubernetes; выбор конкретного пода ложится на плечи клиента.
- **Стабильная сетевая идентификация:** Каждый под получает предсказуемое DNS-имя, что критично для распределенных систем.
- **EndpointSlices:** Для Headless-сервисов также создаются объекты `EndpointSlice`, которые обеспечивают масштабируемость при большом количестве подов (более 1000).
- **publishNotReadyAddresses:** Если установлено в `true`, DNS будет возвращать IP-адреса подов даже если они еще не прошли Readiness-пробы. Это необходимо для начального формирования кворума (bootstrap) в некоторых БД.

### Варианты конфигурации

#### Headless Service с селектором
Самый частый вариант. Kubernetes автоматически управляет `Endpoints`/`EndpointSlice`, связывая их с подами, подходящими под `selector`. Используется для StatefulSet и стандартных приложений.

#### Headless Service без селектора
Позволяет вручную определять `Endpoints`. Используется для:
- Обращения к сервисам вне кластера (через их IP).
- Проксирования трафика на сервисы в других неймспейсах.
- Интеграции legacy-систем, которые не запущены в Kubernetes.

### Сценарии использования

- **Stateful-приложения:** Основной механизм для [StatefulSet](../../Base/StatefulSet/statefulset_overview.md), требующих уникальных и постоянных имен подов.
- **Децентрализованные системы:** Системы с собственными механизмами репликации и кворума (MongoDB, Cassandra, Kafka), где узлам нужно знать адреса друг друга.
- **Специфическая балансировка:** Ситуации, когда клиентское приложение само реализует логику выбора узла (например, разделение read/write запросов).
- **gRPC:** HTTP/2 мультиплексирует несколько запросов на одном TCP-соединении, из-за чего kube-proxy (iptables/IPVS) не может балансировать — все запросы уходят на первый разрешённый под. Headless решает проблему: клиент сам балансирует между IP-адресами, полученными из DNS-ответа.

## Практические сценарии

### Настройка Headless Service для StatefulSet

Для обеспечения стабильных DNS-имен подов в StatefulSet необходимо сначала создать Headless Service, имя которого указывается в поле `serviceName` контроллера.

**Манифест Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-headless
spec:
  clusterIP: None
  ports:
    - port: 80
      name: web
  selector:
    app: nginx
```

**Манифест StatefulSet:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web
spec:
  serviceName: "nginx-headless"
  replicas: 2
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
        - name: nginx
          image: nginx:latest
          ports:
            - containerPort: 80
              name: web
```

### Настройка для внешних ресурсов (без селектора)

Если нужно обращаться к внешней базе данных по DNS-имени внутри кластера, используя Headless Service.

**Манифест Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-db
spec:
  clusterIP: None
  ports:
    - port: 5432
```

**Манифест Endpoints:**

```yaml
apiVersion: v1
kind: Endpoints
metadata:
  name: external-db
subsets:
  - addresses:
      - ip: 192.168.1.100
    ports:
      - port: 5432
```

### Валидация работы

Для проверки DNS-разрешения можно использовать временный диагностический под:

```bash
kubectl run -it --rm --image=busybox:latest dns-test -- /bin/sh
# → / #
```

**Проверка записей:**

```bash
# Получение списка IP всех подов сервиса
nslookup nginx-headless
# → Server:    10.96.0.10
# → Address 1: 10.96.0.10 kube-dns.kube-system.svc.cluster.local
# →
# → Name:      nginx-headless
# → Address 1: 10.1.0.3 web-0.nginx-headless.default.svc.cluster.local
# → Address 2: 10.1.0.4 web-1.nginx-headless.default.svc.cluster.local

# Обращение к конкретному поду по стабильному имени
nslookup web-0.nginx-headless
# → Server:    10.96.0.10
# → Address 1: 10.96.0.10 kube-dns.kube-system.svc.cluster.local
# →
# → Name:      web-0.nginx-headless
# → Address 1: 10.1.0.3 web-0.nginx-headless.default.svc.cluster.local
```

## Дополнительная информация

### Сравнение с ClusterIP

| Параметр | Headless | ClusterIP |
| :--- | :--- | :--- |
| **Виртуальный IP** | Отсутствует | Выделяется |
| **DNS-ответ** | Список IP-адресов подов | Виртуальный IP сервиса |
| **Проксирование** | Нет | Через kube-proxy (iptables/IPVS) |
| **Балансировка** | На стороне клиента | На стороне кластера |
| **Типовой use-case** | Базы данных, StatefulSet | Web-сервисы, stateless приложения |

### Особенности и ограничения

- **sessionAffinity:** Поле `spec.sessionAffinity` игнорируется для Headless-сервисов, так как нет проксирования трафика.
- **Dual-stack (IPv4/IPv6):** Headless-сервисы поддерживают несколько семейств IP-адресов. При использовании `ipFamilyPolicy: PreferDualStack` или `RequireDualStack` в DNS будут создаваться как A (IPv4), так и AAAA (IPv6) записи для каждого пода.
- **Зависимость от DNS:** Механизм работает исключительно через систему имен кластера. Клиент должен уметь разрешать DNS-имена и корректно обрабатывать список из нескольких IP-адресов.
- **Масштабируемость:** При использовании очень больших Headless-сервисов (сотни/тысячи подов) DNS-ответы могут становиться слишком большими для UDP, что потребует перехода на TCP для DNS-запросов.

### См. также

- [Обзор StatefulSet](../../Base/StatefulSet/statefulset_overview.md)
- [Сводка по типам Service](./service_types_summary.md)
- [Тип Service — ExternalName](./service_type_externalname.md)
