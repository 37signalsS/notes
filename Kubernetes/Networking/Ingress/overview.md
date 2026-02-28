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
  --set controller.ingressClassResource.name=system-ingress \
  --set controller.ingressClassResource.default=false \
  --version 4.10.0
```

**Основные параметры:**
- `controller.priorityClassName`: PriorityClass для контроллера (требуется предварительное создание).
- `controller.metrics.enabled`: Включение метрик для Prometheus.
- `controller.admissionWebhooks.enabled`: Отключение валидации Ingress-ресурсов. Полезно, если в кластере планируется несколько Ingress-контроллеров.
- `controller.ingressClassResource.name`: Имя ресурса IngressClass, который будет создан (например, `system-ingress`).
- `controller.service.type`: Тип Service (по умолчанию `LoadBalancer`).

**3. Проверка установки:**

```bash
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
```

### Декларативная установка в K3s (HelmChart CRD)

K3s включает в себя встроенный контроллер для развертывания Helm-чартов декларативно, с помощью CRD `HelmChart`. Это позволяет управлять Helm-релизами как нативными объектами Kubernetes.

Ниже приведен пример манифеста для установки Nginx Ingress Controller этим способом.

```yaml
# ingress-nginx-chart.yaml
apiVersion: helm.cattle.io/v1
kind: HelmChart
metadata:
  name: nginx-ingress
  namespace: kube-system # Чарт будет установлен в этот namespace
spec:
  chart: ingress-nginx
  repo: https://kubernetes.github.io/ingress-nginx
  targetNamespace: ingress-nginx # А сам контроллер развернется здесь
  version: 4.10.0
  valuesContent: |-
    controller:
      # Указываем высокий приоритет для подов контроллера
      priorityClassName: system-cluster-critical
      # Разрешаем сбор метрик для Prometheus
      metrics:
        enabled: true
      # Отключаем вебхуки, чтобы не мешать другим Ingress-контроллерам
      admissionWebhooks:
        enabled: false
      # Определяем кастомный IngressClass
      ingressClassResource:
        name: system-ingress
        enabled: true
        default: false
        controllerValue: "k8s.io/system-ingress"
```

**Примечание о LoadBalancer в K3s:**
В K3s встроен собственный провайдер сервисов типа `LoadBalancer`. При создании такого сервиса (что по умолчанию делает чарт Nginx Ingress), K3s назначает ему IP-адреса всех узлов кластера. Если у вас кластер из одной ноды, то для доступа к Ingress-контроллеру можно использовать IP-адрес этой ноды.

### Установка из манифеста для Bare-Metal (NodePort)

Для bare-metal окружений или в случаях, когда требуется тонкая настройка, можно установить Ingress-контроллер напрямую из официального манифеста, кастомизировав его под свои нужды. Этот подход дает полный контроль над всеми компонентами.

**1. Получение манифеста:**
Скачайте `deploy.yaml` из официального [репозитория NGINX Ingress](https://github.com/kubernetes/ingress-nginx/tree/main/deploy/static/provider/baremetal). Этот файл содержит все необходимые ресурсы: `Namespace`, `ServiceAccount`, `ConfigMap`, `ClusterRole`, `Deployment` и др.

**2. Ключевые кастомизации манифеста:**

В скачанном файле рекомендуется внести несколько изменений для повышения надежности и управляемости.

#### а) Настройка Service типа `NodePort`
Найдите ресурс `Service` для контроллера и измените его `spec`:
*   **`type: NodePort`**: Выставляет сервис на портах всех узлов.
*   **`externalTrafficPolicy: Local`** (опционально, но рекомендуется): Заставляет `NodePort` открываться только на тех узлах, где запущены поды Ingress-контроллера. Это сохраняет исходный IP-адрес клиента и избегает лишнего сетевого хопа. *Требует совместного использования с `nodeSelector` или Affinity-правилами.*
*   **`spec.ports`**: Можно явно задать `nodePort` для HTTP и HTTPS, например `31080` и `31443`.

#### б) Определение кастомного `IngressClass`
Чтобы избежать конфликтов, если в кластере может быть несколько Ingress-контроллеров, рекомендуется определить собственный класс.

Найдите `Deployment` контроллера и в аргументах запуска (`args`) добавьте:
```yaml
- /nginx-ingress-controller
- --ingress-class=system-ingress # Наше кастомное имя
- --configmap=$(POD_NAMESPACE)/ingress-nginx-controller
```
Теперь только `Ingress`-ресурсы с аннотацией `kubernetes.io/ingress.class: system-ingress` или полем `spec.ingressClassName: system-ingress` будут обрабатываться этим контроллером.

#### в) Настройка высокой доступности (HA) через Anti-Affinity
Чтобы два пода Ingress-контроллера не оказались на одном узле (что сведет на нет отказоустойчивость), используется `podAntiAffinity`.

В `Deployment` контроллера добавьте в `spec.template.spec`:
```yaml
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app.kubernetes.io/name
                    operator: In
                    values:
                      - ingress-nginx
              topologyKey: "kubernetes.io/hostname"
```
*   `requiredDuringScheduling...`: Жесткое правило, запрещающее планировщику размещать поды с одинаковым лейблом (`app.kubernetes.io/name: ingress-nginx`) на одном узле (`topologyKey: "kubernetes.io/hostname"`).

#### г) Включение JSON-логов
Для упрощения сбора и анализа логов, настройте их вывод в формате JSON.
Найдите ресурс `ConfigMap` (`ingress-nginx-controller`) и добавьте в `data`:
```yaml
data:
  log-format-upstream: '{"time": "$time_iso8601", "proxy_protocol_addr": "$proxy_protocol_addr", ...}' # Добавьте нужный формат
  # Другие опции...
```

**3. Применение манифеста:**
```bash
kubectl apply -f ./deploy-custom.yaml
```
Этот подход обеспечивает полный контроль и создает надежную, отказоустойчивую конфигурацию Ingress-контроллера.

