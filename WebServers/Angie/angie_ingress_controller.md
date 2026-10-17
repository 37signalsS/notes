# Angie Ingress Controller в Kubernetes

**Актуально для:** Angie Ingress Controller 1.x / Kubernetes 1.28–1.35

## Определения

* **Angie Ingress Controller** — специализированный контроллер сетевого шлюза для кластеров Kubernetes, разработанный компанией ООО «Веб-сервер». Отслеживает события Kubernetes API (ресурсы `Ingress`, `Service`, `Endpoints` / `EndpointSlice`, `Secret`) и динамически управляет маршрутизацией, балансировкой и TLS-терминацией на базе высокопроизводительного ядра [Angie](./angie_overview.md).
* **IngressClass** — встроенный ресурс Kubernetes (`networking.k8s.io/v1`), определяющий класс и конкретный контроллер, отвечающий за обработку правил маршрутизации (поле `spec.controller: angie.software/ingress-controller`).
* **Zero-Downtime Endpoints Reload** — архитектурное свойство контроллера Angie, позволяющее обновлять сетевые адреса целевых подов (пиров в `upstream`) в разделяемой памяти (`shm`) на лету через внутренний API контроллера, избегая тяжелого релоада процессов (`angie -s reload`) и исключая сброс активных клиентских соединений.
* **HostNetwork режим** — способ развертывания Pod контроллера (`spec.hostNetwork: true`), при котором контейнер Angie подключается напрямую к сетевому пространству имен (Network Namespace) хостовой ноды, исключая задержки и накладные расходы CNI и kube-proxy.
* **Sidecar проксирование (Angie Sidecar)** — паттерн проектирования Pod, при котором облегченный экземпляр Angie размещается в одном сетевом пространстве имен с основным контейнером приложения (включая использование [нативных сайдкаров](../Kubernetes/Base/Pod/pod_init_containers.md)) для локальной TLS-терминации (mTLS), компрессии Brotli/Gzip или кэширования статики.
* **Traffic Splitting / Canary** — механизм плавного перенаправления долей пользовательского трафика между стабильной (production) и новой (canary) версиями сервиса на основе весов (`weight`), HTTP-заголовков (`header`) или Cookie.

---

## Базовые концепции и архитектура

### Контекст: Замена устаревшего Ingress-NGINX

Проект `kubernetes/ingress-nginx` официально перешел в статус End of Life (EOL). В корпоративных On-Premises инфраструктурах (Bare-Metal, Astra Linux, РЕД ОС, OpenShift, Deckhouse) Angie Ingress Controller выступает доверенной drop-in заменой:

| Характеристика | Kubernetes Ingress-NGINX (EOL) | Angie Ingress Controller |
| :--- | :--- | :--- |
| **Реестр российского ПО** | Нет | **Да (№ 17604 в составе Angie)** |
| **Реакция на масштабирование подов** | Частые `nginx -s reload` (приводит к сбросу TCP/HTTP2 сессий) | **Динамическое обновление upstream в SHM без reload** |
| **Встроенная телеметрия** | Сторонний Lua/Prometheus exporter | **Нативный `/status/` API и OpenMetrics формат** |
| **Поддержка протоколов** | HTTP/1.1, HTTP/2 | **HTTP/1.1, HTTP/2, HTTP/3 (QUIC), gRPC, WebSocket** |
| **Безопасность и криптография** | Стандартный OpenSSL | **OpenSSL, ГОСТ TLS (Angie PRO), CSE/ЗПС Astra Linux** |

### Архитектура компонентов контроллера

```
                [ Kubernetes API Server ]
                           │ (Watch: Ingress, Services, Endpoints, Secrets)
                           ▼
          ┌──────────────────────────────────┐
          │  Angie Ingress Controller Core   │ (Go-процесс управления)
          └────────────────┬─────────────────┘
                           │
         ┌─────────────────┴─────────────────┐
         │ Контрольный канал (UNIX Socket)  │
         ▼                                   ▼
  [ Изменение маршрутов / TLS ]      [ Изменение Endpoints / Pod IP ]
         │                                   │
         ▼                                   ▼
  Генерация /etc/angie/angie.conf    Прямая запись в Shared Memory
  (graceful reload SIGHUP)           (Zero-Downtime, БЕЗ reload)
         │                                   │
         └─────────────────┬─────────────────┘
                           ▼
               [ Angie Worker Processes ]
               (Прием и обработка трафика)
```

1. **Control Plane (Go-демон):** подписывается на события `Informer` в API Kubernetes. При создании, модификации или удалении ресурсов рассчитывает целевое состояние маршрутизатора.
2. **Data Plane (Angie Core):** исполняемый сервер Angie, обслуживающий клиентский трафик. Воркеры получают запросы от внешних клиентов и распределяют их по IP-адресам подов без использования виртуальных IP-адресов ClusterIP (`kube-proxy`).

---

## Практические сценарии

### Сценарий 1: Развертывание Angie Ingress Controller в режиме DaemonSet (HostNetwork)

Топология развертывания на выделенных Edge-нодах кластера Bare-Metal. Обеспечивает максимальную сетевую производительность и привязку портов 80/443 к физическим интерфейсам серверов.

#### 1. Определение IngressClass

Создайте файл `00-ingress-class.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: IngressClass
metadata:
  name: angie
  annotations:
    ingressclass.kubernetes.io/is-default-class: "true"
spec:
  controller: angie.software/ingress-controller
```

#### 2. Манифест DaemonSet с изоляцией на Edge-узлах

Создайте файл `01-angie-ingress-daemonset.yaml`:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: angie-ingress-controller
  namespace: kube-system
  labels:
    app.kubernetes.io/name: angie-ingress
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: angie-ingress
  template:
    metadata:
      labels:
        app.kubernetes.io/name: angie-ingress
    spec:
      # Прямая привязка к сетевому стеку хоста
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      # Размещение только на выделенных шлюзовых нодах
      nodeSelector:
        node-role.kubernetes.io/edge: "true"
      tolerations:
        - key: "node-role.kubernetes.io/edge"
          operator: "Exists"
          effect: "NoSchedule"
      serviceAccountName: angie-ingress-serviceaccount
      terminationGracePeriodSeconds: 60
      containers:
        - name: angie-ingress
          image: docker.angie.software/angie-ingress-controller:1.4.0
          imagePullPolicy: IfNotPresent
          args:
            - --ingress-class=angie
            - --default-server-port=80
            - --default-ssl-port=443
            - --status-port=8888
          securityContext:
            capabilities:
              add:
                - NET_BIND_SERVICE
              drop:
                - ALL
            runAsUser: 101
            allowPrivilegeEscalation: false
          ports:
            - name: http
              containerPort: 80
              hostPort: 80
            - name: https
              containerPort: 443
              hostPort: 443
            - name: metrics
              containerPort: 8888
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: "4"
              memory: 4Gi
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8888
            initialDelaySeconds: 5
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8888
            initialDelaySeconds: 10
            periodSeconds: 10
```

Применение манифестов в кластере:

```bash
kubectl apply -f 00-ingress-class.yaml
# → ingressclass.networking.k8s.io/angie created

kubectl apply -f 01-angie-ingress-daemonset.yaml
# → daemonset.apps/angie-ingress-controller created

kubectl get pods -n kube-system -l app.kubernetes.io/name:angie-ingress -o wide
# → angie-ingress-controller-9x4b2   1/1   Running   0   15s   192.168.10.11   node-edge-01
# → angie-ingress-controller-k8m11   1/1   Running   0   15s   192.168.10.12   node-edge-02
```

---

### Сценарий 2: Маршрутизация трафика, TLS-терминация и буферизация

Публикация микросервиса API с автоматической TLS-терминацией через секрет Kubernetes и настройкой таймаутов проксирования.

Файл манифеста `api-ingress.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: billing-api-ingress
  namespace: production
  annotations:
    # Использование класса Angie
    kubernetes.io/ingress.class: "angie"
    # Тонкая настройка апстримов и проксирования
    angie.software/proxy-connect-timeout: "5s"
    angie.software/proxy-read-timeout: "60s"
    angie.software/proxy-send-timeout: "60s"
    angie.software/client-max-body-size: "10m"
    # Алгоритм балансировки: наименьшее количество активных соединений
    angie.software/upstream-load-balancing-algorithm: "least_conn"
    # Включение сжатия ответов
    angie.software/gzip: "on"
    angie.software/gzip-types: "application/json text/plain"
spec:
  ingressClassName: angie
  tls:
    - hosts:
        - billing.example.internal
      secretName: billing-tls-cert
  rules:
    - host: billing.example.internal
      http:
        paths:
          - path: /api/v1/
            pathType: Prefix
            backend:
              service:
                name: billing-api-service
                port:
                  number: 8080
```

Проверка применения правил маршрутизации:

```bash
kubectl apply -f api-ingress.yaml
# → ingress.networking.k8s.io/billing-api-ingress created

# Проверка статуса Ingress и назначенных IP
kubectl get ingress -n production billing-api-ingress
# → NAME                  CLASS   HOSTS                      ADDRESS                       PORTS     AGE
# → billing-api-ingress   angie   billing.example.internal   192.168.10.11,192.168.10.12   80, 443   12s

# Запрос с проверкой корректности заголовков и TLS
curl -k -I --resolve billing.example.internal:443:192.168.10.11 https://billing.example.internal/api/v1/health
# → HTTP/2 200
# → server: angie
# → content-type: application/json
```

---

### Сценарий 3: Канареечные релизы (Canary Traffic Splitting)

Организация плавного перевода трафика на новую версию сервиса (Canary) с весовым распределением 90% / 10% и принудительным перенаправлением по заголовку тестировщика.

#### 1. Основной Ingress стабильной версии (Production)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop-frontend-stable
  namespace: production
spec:
  ingressClassName: angie
  rules:
    - host: shop.example.internal
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: shop-v1-service
                port:
                  number: 80
```

#### 2. Канареечный Ingress (Canary)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop-frontend-canary
  namespace: production
  annotations:
    kubernetes.io/ingress.class: "angie"
    # Активация канареечного режима
    angie.software/canary: "true"
    # Весовое распределение трафика: 10% отправляется на canary
    angie.software/canary-weight: "10"
    # Принудительная маршрутизация для внутренней команды QA
    angie.software/canary-by-header: "X-Canary-Test"
    angie.software/canary-by-header-value: "always"
spec:
  ingressClassName: angie
  rules:
    - host: shop.example.internal
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: shop-v2-service
                port:
                  number: 80
```

Проверка маршрутизации:

```bash
# 1. Запрос с заголовком тестирования (принудительно версия v2)
curl -s -H "Host: shop.example.internal" -H "X-Canary-Test: always" http://192.168.10.11/ | grep -o "Version-2"
# → Version-2

# 2. Стандартные запросы без заголовка (распределение по весу)
for i in {1..10}; do
  curl -s -H "Host: shop.example.internal" http://192.168.10.11/ | grep -oE "Version-[12]"
done
# → Version-1
# → Version-1
# → Version-2
# → Version-1
# → Version-1
# → Version-1
# → Version-1
# → Version-1
# → Version-1
# → Version-1
```

---

### Сценарий 4: Angie как Sidecar контейнер в Pod (TLS-терминация и локальный кэш)

Использование контейнера Angie рядом с legacy-приложением, не поддерживающим TLS 1.3 и сжатие контента. Приложение слушает локальный loopback порт `127.0.0.1:8080`, а Angie принимает защищенный внешний трафик на порту `8443`.

Файл `workload-pod-with-sidecar.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-service
  namespace: production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: order-service
  template:
    metadata:
      labels:
        app: order-service
    spec:
      volumes:
        - name: angie-sidecar-config
          configMap:
            name: order-angie-sidecar-conf
        - name: tls-certs
          secret:
            secretName: order-service-tls
      containers:
        # Основной контейнер с бизнес-логикой
        - name: application
          image: internal-registry.example.internal/apps/order-processor:2.1.0
          env:
            - name: LISTEN_ADDR
              value: "127.0.0.1:8080"
          resources:
            limits:
              cpu: "1"
              memory: 512Mi

        # Angie Sidecar контейнер
        - name: angie-proxy
          image: docker.angie.software/angie:1.12-alpine
          ports:
            - name: https-edge
              containerPort: 8443
          volumeMounts:
            - name: angie-sidecar-config
              mountPath: /etc/angie/angie.conf
              subPath: angie.conf
            - name: tls-certs
              mountPath: /etc/angie/ssl
              readOnly: true
          resources:
            requests:
              cpu: 100m
              memory: 64Mi
            limits:
              cpu: 500m
              memory: 256Mi
```

Конфигурационный файл сайдкара `ConfigMap`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: order-angie-sidecar-conf
  namespace: production
data:
  angie.conf: |
    user angie;
    worker_processes 1;
    events { worker_connections 2048; }
    http {
        access_log /dev/stdout;
        error_log /dev/stderr warn;
        
        server {
            listen 8443 ssl http2;
            ssl_certificate /etc/angie/ssl/tls.crt;
            ssl_certificate_key /etc/angie/ssl/tls.key;
            ssl_protocols TLSv1.2 TLSv1.3;

            location / {
                # Проксирование на приложение через локальный сетевой стек
                proxy_pass http://127.0.0.1:8080;
                proxy_http_version 1.1;
                proxy_set_header Connection "";
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
            }
        }
    }
```

---

## Диагностика и устранение неисправностей

| Симптом / Ошибка | Вероятная причина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Код `503 Service Temporarily Unavailable`** | В сервисе Kubernetes отсутствуют готовые поды (Empty Endpoints) | `kubectl get endpoints -n <ns> <service>` | Проверить readinessProbe основного приложения; убедиться, что селектор сервиса совпадает с метками подов. |
| **Изменения Ingress не применяются** | Неверно указан класс `ingressClassName` либо отсутствует IngressClass | `kubectl describe ingress <name>`<br>`kubectl get ingressclass` | Указать в аннотациях или спецификации `ingressClassName: angie`. Проверить флаг `--ingress-class` контроллера. |
| **`413 Request Entity Too Large`** | Размер тела запроса превышает ограничение по умолчанию (1 МБ) | Проверить лог ошибки: `client intended to send too large body` | Добавить аннотацию `angie.software/client-max-body-size: "50m"`. |
| **Ошибки TLS: `SSL: certificate verify failed`** | Истек срок действия сертификата в `Secret` или отсутствует CA цепочка | `openssl x509 -in <(kubectl get secret <name> -o jsonpath='{.data.tls\.crt}' \| base64 -d) -text -noout` | Обновить сертификат в секрете или проверить работу `cert-manager`. |
| **Высокая задержка p99 при частых обновлениях Deployment** | Старый подход с полным релоадом мастер-процесса | `kubectl logs -n kube-system <angie-controller-pod>` | Убедиться, что контроллер использует динамический API разделяемой памяти для синхронизации апстримов без отправки сигнала HUP. |

---

## Рекомендации (Best Practices)

1. **Изоляция сетевого периметра на Bare-Metal:** Всегда запускайте Angie Ingress Controller как `DaemonSet` с `hostNetwork: true` на выделенных нодах (`node-role.kubernetes.io/edge: "true"`). Это исключает трансляцию NAT через conntrack/iptables и дает до 40% прироста пропускной способности по сравнению с `NodePort` сервисами.
2. **Разделение Ingress-классов:** Создавайте раздельные экземпляры контроллера для внешнего публичного трафика (`ingressClassName: angie-external`) и закрытого межсервисного обмена (`ingressClassName: angie-internal`).
3. **Согласование Graceful Shutdown:** Устанавливайте `terminationGracePeriodSeconds: 60` для подов контроллера и согласуйте его с директивой `worker_shutdown_timeout 45s;` внутри Angie, чтобы завершающийся pod успел дообслужить клиентские HTTP/2 соединения.
4. **Тюнинг таймаутов Keepalive:** Задавайте `proxy_set_header Connection "";` и `proxy_http_version 1.1;` на всех маршрутах, чтобы контроллер не открывал новые TCP-сокеты на каждый входящий запрос.

---

## Дополнительная информация

* **[Обзор Angie](./angie_overview.md)** — архитектурные основы, лицензирование и процессная модель.
* **[Балансировка HTTP-трафика в Angie](./angie_http_load_balancing.md)** — алгоритмы балансировки и мониторинг upstream.
* **[Динамические апстримы в Angie](./dynamic_upstreams.md)** — динамическое разрешение DNS и взаимодействие с сервисами без перезагрузки.
* **[Сравнение Ingress-контроллеров в Kubernetes](../Kubernetes/Networking/Ingress/controllers_comparison.md)** — критерии выбора Ingress и Gateway API контроллеров.
* **[Настройка MetalLB](../Kubernetes/Networking/metallb.md)** — организация отказоустойчивого L2/BGP балансировщика перед Ingress на собственной инфраструктуре.
