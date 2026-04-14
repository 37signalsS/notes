# Headless Service

## Определения

**Headless Service** — тип сервиса, который **не имеет `ClusterIP`**. Для создания в манифесте указывается `spec.clusterIP: None`. Вместо единой виртуальной IP-точки входа предоставляет доступ к IP-адресам всех Pod через DNS-записи.

**Основная цель:** Обнаружение (`discovery`) отдельных Pod, а не проксирование трафика через единый IP.

## Основные концепции

### Принцип работы: DNS Discovery

При создании `Headless Service`, DNS-сервер кластера (CoreDNS) создаёт записи двух типов:

| Тип записи | Формат | Результат |
| :--- | :--- | :--- |
| **A-запись сервиса** | `<service-name>.<namespace>.svc.cluster.local` | Список IP-адресов всех Pod |
| **A-запись Pod** | `<pod-name>.<service-name>.<namespace>.svc.cluster.local` | IP конкретного Pod |

Это позволяет обращаться как ко всем Pod сразу (получив список IP), так и к каждому индивидуально по стабильному DNS-имени.

### Ключевые особенности

| Особенность | Описание |
| :--- | :--- |
| **Нет ClusterIP** | `clusterIP: None` — DNS возвращает IP Pod напрямую |
| **Нет балансировки** | Трафик не балансируется, клиент выбирает Pod |
| **Стабильные DNS-имена** | Каждый Pod получает предсказуемое DNS-имя |
| **Селекторы** | Работает через `selector`, как обычный Service |

### Сценарии использования

| Сценарий | Описание |
| :--- | :--- |
| **Stateful-приложения (StatefulSet)** | Основной сценарий: стабильные уникальные имена для Pod |
| **Прямой доступ к Pod** | Соединение с конкретным экземпляром (репликация, администрирование) |
| **Децентрализованные системы** | Peer-to-peer системы: MongoDB, Cassandra, брокеры сообщений |
| **Собственная балансировка** | Клиент сам решает, к какому Pod подключиться (чтение/запись) |

#### StatefulSet и Headless Service

**StatefulSet** требует стабильных уникальных имён для Pod. Headless Service обеспечивает это через DNS.

**Последствия без Headless Service:**

- StatefulSet не получит стабильные DNS-имена
- Кластерные протоколы (кворум БД, брокеры сообщений) не смогут работать
- Нестабильность приложения

> **Совет:** Для тонкой настройки DNS-имён используйте поля `subdomain` и `hostname` в `pod.spec` для создания кастомных FQDN.

## Практические сценарии

### Пример: Headless Service для StatefulSet

**Шаг 1: Создание Headless Service**

```yaml
# nginx-headless-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-headless
  labels:
    app: nginx
spec:
  clusterIP: None  # Делает сервис "headless"
  ports:
    - port: 80
      name: web
  selector:
    app: nginx  # Должен соответствовать меткам StatefulSet
```

**Шаг 2: Создание StatefulSet**

```yaml
# nginx-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web
spec:
  serviceName: "nginx-headless"  # Должно совпадать с именем Headless Service
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
          image: nginx:1.28.0
          ports:
            - containerPort: 80
              name: web
```

**Результат:** Созданы Pod `web-0` и `web-1` с уникальными DNS-записями:

- `web-0.nginx-headless.default.svc.cluster.local`
- `web-1.nginx-headless.default.svc.cluster.local`

### Проверка работы

**1. Запуск временного пода для отладки:**

```bash
kubectl run -it --rm --image=busybox:1.36.1 dns-test -- /bin/sh
```

**2. Проверка DNS из пода:**

```bash
# Запрос к сервису (получаем все IP)
nslookup nginx-headless
# Output:
# Name:      nginx-headless.default.svc.cluster.local
# Address 1: 10.244.1.5
# Address 2: 10.244.2.4

# Запрос к конкретному Pod (получаем один IP)
nslookup web-0.nginx-headless
# Output:
# Name:      web-0.nginx-headless.default.svc.cluster.local
# Address 1: 10.244.1.5
```

> **Подробно о StatefulSet:** [StatefulSet Overview](../../Base/StatefulSet/statefulset_overview.md), [StatefulSet Core Concepts](../../Base/StatefulSet/statefulset_core_concepts.md)

## Дополнительная информация

### Сравнение с ClusterIP

| Характеристика | Headless | ClusterIP |
| :--- | :--- | :--- |
| **ClusterIP** | Нет (`None`) | Да (виртуальный IP) |
| **Балансировка** | Нет (клиентская) | Да (kube-proxy) |
| **DNS** | Возвращает IP Pod | Возвращает ClusterIP |
| **Use-case** | StatefulSet, direct access | Внутренние сервисы |

### Ограничения

| Ограничение | Описание |
| :--- | :--- |
| **Нет балансировки** | Клиент сам выбирает Pod |
| **Только DNS** | Работает только через DNS-разрешение |
| **Зависимость от CoreDNS** | Требует корректной DNS-инфраструктуры |

### Связанные концепции

- **[StatefulSet](../../Base/StatefulSet/statefulset_overview.md)** — контроллер для stateful-приложений
- **[ExternalName](./service_type_externalname.md)** — доступ к внешним ресурсам через DNS
- **[Сводка типов сервисов](./service_types_summary.md)** — полное сравнение всех типов
