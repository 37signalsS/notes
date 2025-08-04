# Headless Service

## 1. Что такое Headless Service?

**Headless Service** — это тип сервиса в Kubernetes, который отличается от стандартных тем, что у него **нет `ClusterIP`**. Вместо предоставления единой виртуальной IP-точки входа для балансировки нагрузки, он напрямую предоставляет доступ к IP-адресам всех `Pod`-ов, которые соответствуют его селектору, через DNS-записи.

Чтобы сделать headless сервис, в его манифесте нужно явно указать `spec.clusterIP: None`.

## 2. Зачем и когда использовать Headless Service?

Основная цель — **обнаружение (`discovery`) отдельных `Pod`-ов**, а не проксирование трафика через единый IP.

Ключевые сценарии:

1.  **Stateful-приложения (`StatefulSet`):** Это основной и самый частый вариант использования. `StatefulSet` требует, чтобы каждый его `Pod` имел стабильное, уникальное сетевое имя. `Headless Service` обеспечивает это, создавая для каждого `Pod`-а предсказуемую DNS-запись.

2.  **Прямой доступ к `Pod`-ам:** Когда клиенту или другому приложению нужно установить соединение с конкретным экземпляром `Pod`-а, а не со случайным (например, для репликации данных или выполнения административных задач).

3.  **Децентрализованные системы:** Для систем, где участники должны обнаруживать друг друга (peer-to-peer), например, кластеры баз данных (MongoDB, Cassandra) или брокеры сообщений.

4.  **Собственная логика балансировки:** Когда клиентское приложение само решает, к какому бэкенду подключиться, и ему нужен просто список всех доступных `Pod`-ов.

## 3. Как это работает: DNS Discovery

Когда вы создаете `Headless Service`, внутренний DNS-сервер Kubernetes (CoreDNS) настраивает записи двух типов:

1.  **A-запись для самого сервиса:** `nslookup <service-name>` вернет **список IP-адресов всех `Pod`-ов**, подпадающих под селектор.
2.  **A-записи для каждого `Pod`-а:** Для каждого `Pod`-а создается уникальная запись в формате:
    ` <pod-name>.<service-name>.<namespace>.svc.cluster.local `

Это позволяет обращаться как ко всем `Pod`-ам сразу (получив их IP), так и к каждому `Pod`-у индивидуально по его стабильному DNS-имени.

## 4. Пример: Headless Service для StatefulSet

Этот пример показывает, как `Headless Service` работает в паре со `StatefulSet` для создания `nginx`-подов со стабильными именами.

#### Шаг 1: Создание Headless Service

Манифест `nginx-headless-service.yaml`:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-headless
  labels:
    app: nginx
spec:
  # Установка clusterIP: None делает сервис "headless"
  clusterIP: None
  ports:
    - port: 80
      name: web
  # 2. Селектор должен соответствовать меткам подов StatefulSet.
  selector:
    app: nginx
```

#### Шаг 2: Создание StatefulSet

Манифест `nginx-statefulset.yaml`:
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web
spec:
  # 3. Имя сервиса должно совпадать с именем созданного Headless Service.
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
          image: nginx
          ports:
            - containerPort: 80
              name: web
```

В результате будут созданы поды `web-0` и `web-1`, каждый со своей уникальной DNS-записью.

## 5. Проверка работы

После применения манифестов можно проверить DNS-записи из любого другого пода в кластере.

1.  **Запускаем временный под для отладки:**
    ```bash
    kubectl run -it --rm --image=busybox:1.28 dns-test -- /bin/sh
    ```

2.  **Внутри `dns-test` пода выполняем `nslookup`:**

    *   **Запрос к сервису (получаем все IP):**
        ```sh
        # nslookup nginx-headless
        Server:    10.96.0.10
        Address 1: 10.96.0.10 kube-dns.kube-system.svc.cluster.local

        Name:      nginx-headless.default.svc.cluster.local
        Address 1: 10.244.1.5
        Address 2: 10.244.2.4
        ```

    *   **Запрос к конкретному поду (получаем один IP):**
        ```sh
        # nslookup web-0.nginx-headless
        Server:    10.96.0.10
        Address 1: 10.96.0.10 kube-dns.kube-system.svc.cluster.local

        Name:      web-0.nginx-headless.default.svc.cluster.local
        Address 1: 10.244.1.5
        ```