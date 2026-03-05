# Ingress: Установка и Практические Сценарии

## Установка Ingress-контроллера

### Установка Nginx Ingress Controller через Helm

Nginx Ingress Controller является одним из наиболее популярных ingress-контроллеров. Установка производится через официальный Helm-чарт.

**1. Добавление репозитория:**

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
```

**2. Установка через Helm (пример с кастомными параметрами):**

```bash
helm install ingress-nginx ingress-nginx/ingress-nginx 
  --namespace ingress-nginx 
  --create-namespace 
  --set controller.priorityClassName=high-priority 
  --set controller.metrics.enabled=true 
  --set controller.admissionWebhooks.enabled=false 
  --set controller.ingressClassResource.name=system-ingress 
  --set controller.ingressClassResource.default=false 
  --version 4.10.0 # Важно: Перед установкой проверьте актуальную версию чарта.
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
  version: 4.10.0 # Важно: Перед установкой проверьте актуальную версию чарта.
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

## Практические сценарии

### Настройка TLS/SSL

Ingress упрощает терминирование TLS-трафика. Для подключения HTTPS к Ingress, когда у вас уже есть сертификат и ключ, необходимо выполнить следующие шаги:

1. **Создайте `Secret` типа `kubernetes.io/tls` с сертификатом и ключом:**
    Этот Secret будет хранить ваш TLS-сертификат (`tls.crt`) и приватный ключ (`tls.key`).

    ```bash
    kubectl create secret tls my-app-tls-secret 
      --cert=path/to/tls.crt 
      --key=path/to/tls.key
    ```

    Пример манифеста `Secret`:

    ```yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: secret-tls
      namespace: default
    type: kubernetes.io/tls
    data:
      tls.crt: <base64-encoded-cert>
      tls.key: <base64-encoded-key>
    ```

2. **Укажите этот `Secret` в манифесте Ingress:**
    В секции `spec.tls` Ingress-манифеста необходимо указать домен, для которого применяется TLS, и имя созданного `Secret`.

    ```yaml
    apiVersion: networking.k8s.io/v1
    kind: Ingress
    metadata:
      name: my-app-ingress
    spec:
      tls:
        - hosts:
            - myapp.example.com
          secretName: my-app-tls-secret # Имя секрета с сертификатом
      rules:
        - host: myapp.example.com
          http:
            paths:
              - path: /
                pathType: Prefix
                backend:
                  service:
                    name: my-app-service
                    port:
                      number: 80
    ```

    Ingress-контроллер автоматически обнаружит этот `Secret`, подключит сертификат и ключ, и трафик по `https://myapp.example.com` будет зашифрован.

### Тонкая настройка через аннотации (Annotations)

Аннотации — это основной способ передачи специфичных для контроллера настроек, которые выходят за рамки стандартного API Ingress. Их набор и синтаксис определяются конкретным Ingress-контроллером.

**Примеры для NGINX Ingress Controller:**

* `nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"` — указывает, что приложение, на которое направляется трафик, ожидает HTTPS-соединение, а не HTTP (по умолчанию). Это позволяет Ingress-контроллеру понять, как именно обрабатывать и отправлять трафик к бэкенду.
* `nginx.ingress.kubernetes.io/rewrite-target: /` — перенаправляет трафик с указанного `path` на корневой путь (`/`) сервиса.
* `nginx.ingress.kubernetes.io/ssl-redirect: "true"` — принудительно перенаправляет HTTP-трафик на HTTPS.
* `nginx.ingress.kubernetes.io/proxy-body-size: "8m"` — устанавливает максимальный размер тела запроса.
* `nginx.ingress.kubernetes.io/proxy-read-timeout: "60s"` — задает таймаут чтения ответа от бэкенда. Полезно для долгих синхронных операций.
* `kubernetes.io/ingress.class: "nginx"` — указывает, какой Ingress-контроллер должен обрабатывать этот объект (актуально, если в кластере их несколько).

### Интеграция с распределенной трассировкой (Distributed Tracing)

NGINX Ingress Controller может интегрироваться с системами трассировки, совместимыми с OpenTracing (например, Jaeger), чтобы автоматически создавать корневой спан для каждого входящего запроса. Это дает полную видимость жизненного цикла запроса, начиная от точки входа в кластер.

#### Конфигурация с Jaeger

Трассировка включается через параметры конфигурации контроллера (в `ConfigMap` или `values.yaml` для Helm-чарта):

- **`enable-opentracing: "true"`**: Глобально включает модуль трассировки.
- **`jaeger-collector-host`: "jaeger-agent.observability.svc.cluster.local"**: Адрес сервиса, указывающего на агенты Jaeger. Агент принимает спаны по UDP.
- **`jaeger-propagation-format: "w3c"`**: Устанавливает формат заголовков для передачи контекста трассировки. `w3c` является современным стандартом и использует заголовок `traceparent`.

В качестве альтернативы глобальному включению, трассировку можно активировать для конкретного Ingress-ресурса с помощью аннотации:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
name: my-app-ingress
annotations:
nginx.ingress.kubernetes.io/enable-opentracing: "true"
spec:
# ...
```

> **Важно:** Модуль трассировки в NGINX Ingress Controller чувствителен к доступности бекенда трассировки. Если `jaeger-collector-host` указан, но сервис недоступен, **контроллер может перестать работать или не сможет применить новую конфигурацию**. Для production-сред рекомендуется использовать отдельный Ingress-контроллер для трассируемых приложений, чтобы изолировать возможные сбои от основного потока трафика.

### Проксирование TCP/UDP трафика (L4)
Хотя Ingress в основном предназначен для L7 (HTTP/S) трафика, NGINX Ingress Controller можно настроить для проксирования TCP и UDP трафика на уровне L4. Это полезно для публикации не-HTTP сервисов, таких как базы данных или брокеры сообщений.

**Процесс настройки:**

1.  **Включить проксирование в Deployment контроллера:**
    При запуске Ingress-контроллера необходимо передать ему аргументы командной строки, указывающие на `ConfigMap`'ы, которые будут содержать конфигурацию TCP и UDP сервисов.

    ```yaml
    # В манифесте Deployment контроллера
    spec:
      template:
        spec:
          containers:
            - name: controller
              args:
                - /nginx-ingress-controller
                # ... другие аргументы
                - --tcp-services-configmap=$(POD_NAMESPACE)/tcp-services
                - --udp-services-configmap=$(POD_NAMESPACE)/udp-services
    ```

2.  **Создать `ConfigMap` для TCP/UDP сервисов:**
    Создайте `ConfigMap` с именами `tcp-services` и/или `udp-services` в том же `namespace`, где работает контроллер. В секции `data` ключом является внешний порт, а значением — ссылка на внутренний сервис в формате `<namespace>/<service-name>:<service-port>`.

    ```yaml
    # tcp-services-configmap.yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: tcp-services
      namespace: ingress-nginx
    data:
      # Проксировать трафик с внешнего порта 5432 на сервис 'my-postgres' в порту 5432
      "5432": "default/my-postgres:5432"
    ```

3.  **Опубликовать порты на `Service` контроллера:**
    Необходимо открыть соответствующие порты на главном `Service`, который выставляет Ingress-контроллер наружу (`NodePort` или `LoadBalancer`).

    ```yaml
    # В манифесте Service контроллера
    spec:
      ports:
        # ... http и https порты
        - name: postgres-tcp
          port: 5432
          targetPort: 5432
          protocol: TCP
          # Если тип NodePort, можно указать nodePort
          # nodePort: 30432
    ```

После применения этих изменений трафик, поступающий на опубликованный порт (например, `30432`), будет перенаправлен на указанный внутренний сервис.
