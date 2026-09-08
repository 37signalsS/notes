# Тип Service — Headless

## Предварительные требования

**Окружение:**
- Kubernetes v1.20+ (стабильная поддержка EndpointSlices)
- CoreDNS v1.8+ (или kube-dns) как DNS-сервер кластера
- CNI-плагин с поддержкой Service Discovery (Calico, Flannel, Cilium)

**Проверка готовности:**
```bash
# Проверка версии кластера
kubectl version --short
# → Client Version: v1.30.x
# → Server Version: v1.30.x

# Проверка работы CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns
# → NAME                       READY   STATUS    RESTARTS   AGE
# → coredns-xxxxxxxxxx-xxxxx   1/1     Running   0          xxm

# Проверка работы DNS в кластере
kubectl run dns-debug --image=busybox:1.36 -it --rm --restart=Never -- nslookup kubernetes.default
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1
```

## Определения

**Headless Service** — это специальный тип Service в Kubernetes, у которого отсутствует виртуальный IP-адрес (`spec.clusterIP: None`). В отличие от стандартных сервисов, он не выполняет балансировку нагрузки на уровне кластера и не проксирует трафик через `kube-proxy`.

**Основные функции:**
- **Прямое обнаружение (Direct Discovery):** DNS-запрос к имени сервиса возвращает список IP-адресов всех связанных подов напрямую.
- **Стабильная сетевая идентификация:** В связке со StatefulSet обеспечивает каждому поду постоянное DNS-имя.
- **Клиентская балансировка:** Позволяет клиенту (например, gRPC-клиенту или драйверу БД) самостоятельно выбирать конкретный экземпляр для подключения.

## Основные концепции

### Детальный механизм DNS Discovery

Когда создается Headless Service, CoreDNS формирует записи, позволяющие гранулярно управлять доступом:

| Тип записи | Формат | Описание |
| :--- | :--- | :--- |
| **A/AAAA (Сервис)** | `<svc>.<ns>.svc.cluster.local` | Возвращает набор IP-адресов всех готовых подов. Порядок в ответе обычно случайный. |
| **A/AAAA (Под)** | `<pod>.<svc>.<ns>.svc.cluster.local` | Возвращает IP конкретного пода. Имя пода берется из `metadata.name`. |
| **SRV** | `_<port-name>._<proto>.<svc>.<ns>.svc.cluster.local` | Содержит номера портов и соответствующие им целевые DNS-имена подов. Критично для протоколов, требующих явного указания портов. |

**Валидация DNS-записей:**
```bash
# Проверка A-записи сервиса (список IP подов)
nslookup nginx-headless.default.svc.cluster.local
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      nginx-headless.default.svc.cluster.local
# → Address:   10.244.0.10
# → Address:   10.244.0.11

# Проверка A-записи конкретного пода
nslookup web-0.nginx-headless.default.svc.cluster.local
# → Name:      web-0.nginx-headless.default.svc.cluster.local
# → Address:   10.244.0.10

# Проверка SRV-записи (для портов)
dig SRV _web._tcp.nginx-headless.default.svc.cluster.local +short
# → 0 100 80 web-0.nginx-headless.default.svc.cluster.local.
# → 0 100 80 web-1.nginx-headless.default.svc.cluster.local.
```

### Механизм publishNotReadyAddresses

По умолчанию Kubernetes включает под в DNS-ответы только после успешного прохождения **Readiness Probe**. Однако для многих распределенных систем (Elasticsearch, MongoDB, Cassandra) это создает проблему «курицы и яйца»: узлы не могут запуститься, пока не обнаружат друг друга, но они не обнаруживаются, пока не запустились.

Параметр `spec.publishNotReadyAddresses: true` заставляет DNS возвращать IP подов сразу после их создания, игнорируя статус готовности. Это необходимо для первичного формирования кворума (bootstrap).

### Масштабируемость и ограничения DNS

При использовании Headless Service с большим количеством реплик (сотни или тысячи) возникают технические нюансы:
- **Размер UDP-пакета:** Если список IP-адресов не помещается в стандартный UDP-ответ (512 байт), CoreDNS устанавливает флаг `TC` (Truncated). Клиент обязан переключиться на **TCP** для получения полного списка.
- **EndpointSlices:** Для оптимизации передачи данных `kube-proxy` и контроллеры используют `EndpointSlice`, разбивая огромные списки на части. Это снижает нагрузку на API-сервер при обновлении одного пода в группе из 5000 реплик.

### Стратегии распределения трафика (v1.31+)

Хотя Headless Service не балансирует трафик, он поддерживает механизмы оптимизации:
- **`trafficDistribution: PreferClose`**: CoreDNS может пытаться отдавать приоритет IP-адресам подов, находящихся в той же топологической зоне (например, в том же дата-центре), что и запрашивающий клиент, чтобы снизить задержки и стоимость трафика.

### Характеристики и особенности

- **Отсутствие ClusterIP:** Поле `clusterIP: None` указывает системе не выделять виртуальный IP.
- **Прямой доступ:** Вместо абстрагирования через прокси, сервис предоставляет прозрачный доступ к эндпоинтам.
- **Стабильная сетевая идентификация:** Каждый под получает предсказуемое DNS-имя, которое Kubernetes автоматически создает и обновляет на основе имени пода и пространства имен. Это критично для распределенных систем.
- **EndpointSlices:** Для Headless-сервисов также создаются объекты `EndpointSlice`, которые обеспечивают масштабируемость при большом количестве подов (более 1000).

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
- **Распределенные нагрузки (JobSet):** Используется для координации подов в [JobSet](../../Base/job.md), обеспечивая сетевое обнаружение для задач распределенного обучения ИИ (ML).
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
    - port: 4369
      name: epmd
    - port: 5672
      name: amqp
```

**Проверка разрешения имен (nslookup и dig):**
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
# Address: 10.10.10.2

# Проверка SRV-записи (для поиска портов)
dig SRV _amqp._tcp.rabbitmq-headless.default.svc.cluster.local +short
# 0 50 5672 rabbitmq-0.rabbitmq-headless.default.svc.cluster.local.
```

---

## Troubleshooting: типичные проблемы и диагностика

**Проблема 1: DNS-имя пода не резолвится**

*Причины:*
- Headless Service не создан или имя в `serviceName` StatefulSet не совпадает
- Поды не в состоянии `Ready` (без `publishNotReadyAddresses: true`)
- Несовпадение labels между селектором Service и подами

*Диагностика:*
```bash
# Проверка существования Headless Service
kubectl get svc nginx-headless
# → NAME             TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)
# → nginx-headless   ClusterIP   None         <none>        80/TCP

# Проверка совпадения селектора и labels подов
kubectl get svc nginx-headless -o yaml | grep -A 5 selector
# → selector:
# →   app: nginx

kubectl get pods -l app=nginx --show-labels
# → NAME    READY   STATUS    RESTARTS   AGE   LABELS
# → web-0   1/1     Running   0          5m    app=nginx

# Проверка состояния подов
kubectl get pods -l app=nginx
# → NAME    READY   STATUS    RESTARTS   AGE
# → web-0   1/1     Running   0          5m
# → web-1   0/1     Running   0          5m  ← под не Ready, не будет в DNS
```

**Проблема 2: Большой DNS-ответ не помещается в UDP**

*Симптом:* При большом количестве подов (>50-100) DNS-ответ обрезается.

*Диагностика:*
```bash
# Проверка флага TC (Truncated) в ответе
dig nginx-headless.default.svc.cluster.local +noall +comments
# → ;; flags: qr rd ra; QUERY: 1, ANSWER: X, AUTHORITY: 0, ADDITIONAL: 0
# → Если флаг TC присутствует — ответ обрезан

# Проверка через TCP
dig nginx-headless.default.svc.cluster.local +tcp +short
```

*Решение:* Убедиться, что клиенты поддерживают переключение на TCP (большинство современных резолверов делают это автоматически).

**Проблема 3: Поды не обнаруживают друг друга при бутстрапе**

*Симптом:* Кластер (Cassandra, Elasticsearch, ZooKeeper) не формирует кворум.

*Причина:* Поды не могут обнаружить друг друга до прохождения Readiness Probe.

*Решение:* Использовать `publishNotReadyAddresses: true`:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: cassandra-headless
spec:
  clusterIP: None
  publishNotReadyAddresses: true  # ← Критично для бутстрапа
  selector:
    app: cassandra
  ports:
    - port: 9042
```

**Проблема 4: Ошибка при использовании с ClusterIP Service**

*Симптом:* Создан Service с `clusterIP: None`, но приложение ожидает обычный ClusterIP.

*Диагностика:*
```bash
# Проверка типа сервиса
kubectl get svc nginx-headless -o jsonpath='{.spec.clusterIP}'
# → None
```

*Решение:* Headless Service не предоставляет ClusterIP. Для балансировки трафика используйте обычный ClusterIP Service или клиентскую балансировку.

## Best Practices

1. **Используйте с StatefulSet:** Headless Service обязательно для стабильной DNS-идентификации подов в StatefulSet.

2. **publishNotReadyAddresses для кворумных систем:** Всегда включайте `publishNotReadyAddresses: true` для Cassandra, Elasticsearch, ZooKeeper, etcd и других систем, требующих бутстрапа кворума.

3. **Проверка совпадения labels:** Убедитесь, что селектор Service точно соответствует labels подов. Несовпадение — частая причина отсутствия DNS-записей.

4. **Мониторинг DNS:** Настройте мониторинг доступности DNS-записей для критичных Headless Service.

5. **Ограничение размера кластера:** При >500 подов учитывайте ограничения UDP-пакетов и нагрузку на CoreDNS.

6. **Документирование:** Явно указывайте в документации, что сервис является Headless, чтобы разработчики понимали отсутствие балансировки на уровне кластера.

7. **Тестирование DNS:** Всегда проверяйте DNS-записи после создания Headless Service и при изменении количества реплик.

## Edge Cases и ограничения

1. **Нет балансировки трафика:** Headless Service не балансирует нагрузку — весь трафик идет на один под (первый в DNS-ответе) или требуется клиентская балансировка.

2. **Зависимость от DNS:** Если клиент не использует DNS (например, работает только с IP-адресами), Headless Service бесполезен.

3. **Ограничение на количество записей:** При большом количестве подов (>1000) DNS-ответы могут быть нестабильными из-за ограничений размера UDP-пакетов.

4. **sessionAffinity игнорируется:** Поле `sessionAffinity` не работает для Headless Service, так как нет проксирования трафика.

5. **EndpointSlice масштабирование:** Для больших кластеров убедитесь, что EndpointSlice контроллер справляется с нагрузкой (используйте `endpointslicehints` для оптимизации).

6. **Несовместимость с kube-proxy:** Headless Service не создает правил iptables/IPVS — kube-proxy не обрабатывает трафик для таких сервисов.

7. **Особенности Dual-stack:** При `ipFamilyPolicy: PreferDualStack` CoreDNS создает как A, так и AAAA записи. Убедитесь, что клиенты корректно обрабатывают оба типа записей.

---

## Совет по собеседованию

**Вопрос:** Что такое Headless Service в Kubernetes и когда вы будете его использовать?
**Ответ:** Это сервис без виртуального IP-адреса (`ClusterIP: None`). Он напрямую предоставляет IP-адреса подов через DNS-записи. Используется для:
1. **Stateful-приложения** (БД, брокеры сообщений), где важна идентификация узлов.
2. **Клиентская балансировка** (например, gRPC), чтобы обойти ограничения L4-балансировки `kube-proxy`.
3. **Обнаружение внешних ресурсов** при ручном управлении `Endpoints`.

---

## Дополнительная информация

### Сравнение с ClusterIP

| Параметр | Headless | ClusterIP |
| :--- | :--- | :--- |
| **Виртуальный IP** | Отсутствует | Выделяется (стабильный) |
| **DNS-ответ** | Список IP-адресов подов | Виртуальный IP сервиса |
| **Проксирование** | Нет (прямое соединение) | Через kube-proxy (NAT) |
| **Балансировка** | На стороне клиента | На стороне кластера (L4) |
| **Уровень OSI** | L3 (Discovery) | L4 (Distribution) |
| **Типовой use-case** | БД, StatefulSet, gRPC | Веб-сервисы, stateless API |

### См. также

- [Обзор StatefulSet](../../Base/StatefulSet/statefulset_overview.md)
- [Сводка по типам Service](./service_types_summary.md)
- [DNS в Kubernetes: Глубокое погружение](../dns_deep_dive.md)
- [Тип Service — ExternalName](./service_type_externalname.md)

