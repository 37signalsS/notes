# Ingress: Обзор и Основные Концепции

## Определения

**Ingress** — это объект API Kubernetes, который описывает правила маршрутизации внешнего HTTP и HTTPS трафика к сервисам внутри кластера. Он действует как "умный" маршрутизатор или точка входа, позволяя определять правила маршрутизации на основе имени хоста (например, `api.example.com`) или пути (например, `/v1/users`). Ingress работает на **7 уровне модели OSI (прикладной уровень)** и позволяет централизованно управлять доступом к множеству сервисов через единый IP-адрес.

**Ingress-контроллер** — это приложение (обычно `Deployment` или `DaemonSet`), которое фактически реализует правила, описанные в объекте `Ingress`. Он отслеживает изменения в API-сервере Kubernetes и настраивает нижележащий прокси-сервер (например, NGINX, HAProxy, Traefik). **Без Ingress-контроллера объект Ingress не будет работать.**

### Почему Ingress, а не Service?

Хотя для публикации приложений можно использовать `Service` типа `LoadBalancer` или `NodePort`, `Ingress` является предпочтительным решением для HTTP/HTTPS трафика по нескольким ключевым причинам:

1. **Маршрутизация на L7:** В отличие от `Service`, который работает на L4 (TCP/UDP), `Ingress` "понимает" HTTP-запросы. Это позволяет создавать гибкие правила маршрутизации на основе **имени хоста** (например, `api.example.com` и `shop.example.com` могут вести на разные сервисы) и **пути** (`example.com/api` и `example.com/ui`).
2. **Централизованная точка входа:** `Ingress` позволяет управлять доступом ко множеству сервисов через **один внешний IP-адрес** и один балансировщик нагрузки. Это значительно экономит затраты и IP-адреса по сравнению с подходом, где для каждого `Service` типа `LoadBalancer` требуется свой уникальный IP.
3. **Терминация TLS:** `Ingress` предоставляет стандартный способ для централизованной настройки и терминирования SSL/TLS-трафика, снимая эту задачу с каждого отдельного приложения.
4. **Гибкая конфигурация:** Функциональность `Ingress` легко расширяется с помощью аннотаций, специфичных для каждого контроллера, позволяя настраивать аутентификацию, ограничение скорости запросов (rate limiting), перезапись URL и многое другое.

## Основные концепции

### Внешний доступ к Ingress-контроллеру

Для того чтобы Ingress-контроллер мог обрабатывать внешний трафик, его необходимо **выставить наружу** кластера. Часто это делается одним из следующих способов:

* **Service типа `LoadBalancer`**: Облачный провайдер выделяет внешний IP-адрес и направляет трафик на поды Ingress-контроллера.
* **Service типа `NodePort`**: Ingress-контроллер становится доступен на определенном порту на каждом узле кластера.
* **`HostPort`**: Ingress-контроллер публикует свой порт непосредственно на сетевом интерфейсе узла.

### Правила маршрутизации (Routing Rules)

#### Маршрутизация по хосту (Host-based)

Можно направлять трафик с разных доменов на разные сервисы.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: multi-host-ingress
spec:
  rules:
    - host: "foo.example.com"
      http:
        paths:
          - pathType: Prefix
            path: "/"
            backend:
              service:
                name: foo-service
                port:
                  number: 80
    - host: "bar.example.com"
      http:
        paths:
          - pathType: Prefix
            path: "/"
            backend:
              service:
                name: bar-service
                port:
                  number: 80
```

#### Маршрутизация по пути (Path-based)

Трафик одного домена можно направлять на разные сервисы в зависимости от пути.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
spec:
  rules:
    - host: "myapp.example.com"
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: api-service
                port:
                  number: 8080
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend-service # Имя сервиса, на который пойдет трафик
                port:
                  number: 80 # Порт этого сервиса
```

* `pathType: Prefix` — соответствует любому пути, который начинается с указанного значения (например, `/api/v1`, `/api/v2`).
* `pathType: Exact` — соответствует только точно указанному пути.

#### Хост по умолчанию (Default Backend)

Можно определить сервис, который будет обрабатывать весь трафик, не соответствующий ни одному из правил.

```yaml
spec:
  defaultBackend:
    service:
      name: default-service
      port:
        number: 80
  rules:
    # ... правила ...
```

### Схема работы: путь трафика в Kubernetes

Подробное описание пути трафика в Kubernetes, от внешнего запроса до пода, включая роль Ingress Controller, Service и kube-proxy, было перенесено в документ [Сетевая модель в Kubernetes](./network.md#путь-трафика-от-ingress-до-pod) для централизации информации.

## Практические сценарии

### Установка Nginx Ingress Controller через Helm

Nginx Ingress Controller является одним из наиболее популярных ingress-контроллеров. Установка производится через официальный Helm-чарт.

**1. Добавление репозитория:**

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
```

**2. Установка через Helm (пример с кастомными параметрами):**

```bash
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.priorityClassName=high-priority \
  --set controller.metrics.enabled=true \
  --set controller.admissionWebhooks.enabled=false \
  --set controller.ingressClass=system-ingress \
  --version 4.10.0
```

**Основные параметры:**

- `controller.priorityClassName`: PriorityClass для контроллера (требуется предварительное создание)
- `controller.metrics.enabled`: Включение метрик для Prometheus
- `controller.admissionWebhooks.enabled`: Включение валидации Ingress-ресурсов
- `controller.ingressClass`: Имя IngressClass (по умолчанию nginx)
- `controller.service.type`: Тип Service (по умолчанию LoadBalancer)

**3. Проверка установки:**

```bash
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
```

### K3s и LoadBalancer

В K3s встроен механизм Service типа LoadBalancer. При создании Service с типом LoadBalancer K3s автоматически назначает IP-адреса всех узлов кластера в качестве external IP. При наличии одного узла можно использовать IP этого узла для доступа к сервису.
