# Тип Service — Headless

## Определения

**Headless Service** — особый вид сервиса в Kubernetes, которому не назначается ClusterIP (`spec.clusterIP: None`). В отличие от стандартных сервисов, он не предоставляет единого стабильного IP-адреса и не выполняет балансировку нагрузки между модулями на стороне кластера.

**Основная задача:** Обеспечение прямого обнаружения (discovery) сетевых адресов отдельных подов через DNS-записи. Вместо виртуального IP Headless Service напрямую возвращает список IP-адресов связанных модулей, позволяя клиентам подключаться к ним напрямую.

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
- **Прямой доступ:** Вместо абстрагирования через прокси, сервис предоставляет прозрачный доступ к эндпоинтам.
- **Стабильная сетевая идентификация:** Каждый под получает предсказуемое DNS-имя, которое Kubernetes автоматически создает и обновляет на основе имени пода и пространства имен. Это критично для распределенных систем.
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

- **Stateful-приложения:** Основной механизм для [StatefulSet](../../Base/StatefulSet/statefulset_overview.md), требующих уникальных и постоянных имен подов. Это позволяет клиентам и другим узлам кластера (например, в MongoDB или Cassandra) взаимодействовать с конкретными экземплярами.
- **Децентрализованные системы:** Системы с собственными механизмами репликации и кворума (MongoDB, Cassandra, Kafka), где узлам нужно знать адреса друг друга для формирования кластера.
- **Безопасность и идентификация:** При использовании Headless Service для систем, требующих сохранения сетевой идентичности, важно правильно настраивать `securityContext` (например, `runAsUser`, `fsGroup`, `runAsGroup`/`GID`), чтобы процессы имели доступ к данным на всех репликах.
- **Клиентская балансировка нагрузки:** Ситуации, когда клиентское приложение само реализует логику выбора узла (например, разделение read/write запросов или использование специфических алгоритмов), получая полный список IP-адресов подов из DNS.
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
### Сценарий 3: Кластер RabbitMQ (Discovery)

Headless Service часто используется для кластеризации RabbitMQ, позволяя узлам обнаруживать друг друга и формировать кворум.

**Манифест (фрагмент):**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: rabbitmq-headless
spec:
  clusterIP: None
  selector:
    app: rabbitmq
  ports:
    - port: 4369 # Erlang Port Mapper
    - port: 5672 # AMQP
```

**Проверка разрешения имен (nslookup):**
При использовании Headless Service ответ DNS содержит IP-адреса всех подов кластера напрямую.

```bash
# Проверка обычного сервиса (возвращает ClusterIP)
nslookup rabbitmq.default.svc.cluster.local
# Server: 10.10.0.10
# Address: 10.10.10.44

# Проверка Headless Service (возвращает список IP всех подов)
nslookup rabbitmq-headless.default.svc.cluster.local
# Name: rabbitmq-headless.default.svc.cluster.local
# Address: 10.10.10.1
# Name: rabbitmq-headless.default.svc.cluster.local
# Address: 10.10.10.2
# Name: rabbitmq-headless.default.svc.cluster.local
# Address: 10.10.10.3
```

---

## Совет по собеседованию

**Вопрос:** Что такое Headless Service в Kubernetes и когда вы будете его использовать?
**Ответ:** Это сервис без виртуального IP-адреса (ClusterIP). Он напрямую предоставляет IP-адреса подов через DNS-записи. Основные случаи использования:
1. **Stateful-приложения** (базы данных, RabbitMQ), где подам нужны стабильные идентификаторы и прямое общение между собой.
2. **Клиентская балансировка**, когда приложение само выбирает, к какому поду подключиться.
3. **Обход ограничений kube-proxy** (например, для gRPC).

---

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
