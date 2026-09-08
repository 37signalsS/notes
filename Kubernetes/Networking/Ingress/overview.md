# Ingress — обзор и основные концепции

> [!WARNING]
> **Внимание (март 2026):** Сообщество Kubernetes официально прекратило поддержку `kubernetes/ingress-nginx`. Контроллер больше не получает патчей безопасности и исправлений ошибок. Всем пользователям рекомендуется запланировать миграцию на **Gateway API**.
>
> Подробное руководство по переезду: **[Миграция с Ingress на Gateway API](../gateway_api/migration.md)**.

## Предварительные требования (Prerequisites)

Для работы с Ingress в кластере должны быть выполнены следующие условия:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Kubernetes** | 1.19+ (API `networking.k8s.io/v1`) | Кластер с поддержкой актуального API Ingress. |
| **Ingress-контроллер** | Зависит от выбора | Без него объект Ingress бесполезен — контроллер реализует правила. |
| **DNS-запись** | — | A/AAAA-запись, указывающая на внешний IP балансировщика или Ingress-контроллера. |
| **TLS-сертификат** (опционально) | — | Kubernetes `Secret` типа `kubernetes.io/tls` для HTTPS. |
| **cert-manager** (опционально) | 1.14+ | Автоматический выпуск и ротация сертификатов Let's Encrypt. |

> **Важно:** Если Ingress-контроллер не установлен, его необходимо развернуть до создания ресурсов Ingress. Руководства по установке: [установка через Helm](./installation/helm-installation.md) | [установка через манифесты (Bare-Metal)](./installation/bare-metal-installation.md).

---

## Определения

**Ingress** — это объект API Kubernetes (актуальная версия `networking.k8s.io/v1`), который описывает правила маршрутизации внешнего HTTP и HTTPS трафика к сервисам внутри кластера. Он действует как "умный" маршрутизатор или точка входа, позволяя определять правила маршрутизации на основе имени хоста (например, `api.example.com`) или пути (например, `/v1/users`). Ingress работает на **7 уровне модели OSI (прикладной уровень)** и позволяет централизованно управлять доступом к множеству сервисов через единый IP-адрес.

**Ingress-контроллер** — это приложение (обычно `Deployment` или `DaemonSet`), которое фактически реализует правила, описанные в объекте `Ingress`. Он отслеживает изменения в API-сервере Kubernetes и настраивает нижележащий прокси-сервер (например, NGINX, HAProxy, Traefik). **Без Ingress-контроллера объект Ingress не будет работать.**

**Зачем нужен Ingress-контроллер:**
- **Единая точка входа:** Действует как "входная дверь" для всего внешнего трафика, упрощая управление множеством маршрутов.
- **Маршрутизация L7:** Позволяет направлять запросы на разные сервисы на основе доменного имени или пути URL (path-based routing).
- **Терминация SSL/TLS:** Разгружает приложения от задач шифрования, выполняя расшифровку трафика на уровне контроллера.
- **Балансировка нагрузки:** Включает встроенные механизмы распределения трафика между подами.
- **Безопасность и Интеграция:** Поддержка внешних **WAF** (Web Application Firewall), систем **SSO** (Single Sign-On) и аутентификации. Для облачных контроллеров (например, AWS ALB) управление правами доступа реализуется через **IRSA (IAM Roles for Service Accounts)**.

**IngressClass** — ресурс, позволяющий разделить Ingress-контроллеры внутри одного кластера и передать им специфические параметры. Например, можно иметь один контроллер для внешнего трафика и другой для внутреннего.

**Ключевые компоненты:**

- **Ресурс Ingress** — манифест с правилами маршрутизации (объект API).
- **Ingress-контроллер** — приложение, реализующее эти правила.
- **IngressClass** — селектор для выбора конкретного контроллера и его глобальных настроек.
- **Правила (Rules)** — условия маршрутизации (хост, путь).
- **Бэкенд (Backend)** — целевой сервис Kubernetes или ресурс (например, Bucket), обрабатывающий трафик.
- **Конфигурация TLS** — настройки для обеспечения безопасной связи (HTTPS).
- **Аннотации (Annotations)** — дополнительные параметры настройки поведения контроллера (таймауты, лимиты, rewrite-правила).

## Основные концепции

### IngressClass — управление контроллерами

Ресурс `IngressClass` пришел на замену аннотации `kubernetes.io/ingress.class`. Он позволяет четко определить, какой контроллер должен обрабатывать конкретный Ingress.

```yaml
apiVersion: networking.k8s.io/v1
kind: IngressClass
metadata:
  name: nginx-external
  annotations:
    # Делает этот класс используемым по умолчанию для новых Ingress
    ingressclass.kubernetes.io/is-default-class: "true"
spec:
  controller: k8s.io/ingress-nginx
  parameters: # Опционально: ссылка на кастомный ресурс с настройками
    apiGroup: k8s.example.com
    kind: IngressParameters
    name: external-config
```

### Типы сопоставления путей (pathType)

Поле `pathType` определяет, как контроллер должен сравнивать путь в запросе с путем, указанным в правиле:

1.  **Prefix**: Сопоставление по префиксу, разделенному косой чертой. Путь `/foo/bar` совпадает с `/foo/bar/baz`, но не совпадает с `/foo/barbaz`. Это наиболее часто используемый тип.
2.  **Exact**: Требуется полное совпадение пути с учетом регистра.
3.  **ImplementationSpecific**: Логика зависит от реализации контроллера. Часто используется для поддержки регулярных выражений (regex), если контроллер это позволяет.

### Backend — Services и Resources

Трафик из Ingress может быть направлен не только в Service, но и в другие ресурсы кластера (начиная с Kubernetes 1.20):

- **Service Backend**: Классический вариант. Указывается имя сервиса и порт.
- **Resource Backend**: Позволяет ссылаться на другие объекты API в том же Namespace, что и ресурс Ingress (например, на статические хранилища или специфические CRD).

Пример использования Resource Backend:
```yaml
backend:
  resource:
    apiGroup: k8s.example.com
    kind: StorageBucket
    name: static-assets
```

### Внутренний жизненный цикл: Как работает Ingress-контроллер

Хотя реализация зависит от конкретного контроллера (NGINX, Traefik, Envoy), общий алгоритм работы (Control Plane) выглядит следующим образом:

1.  **Создание ресурса:** Пользователь создает объект `Ingress`, описывающий правила маршрутизации и настройки TLS.
2.  **API Watcher:** Контроллер постоянно наблюдает за API-сервером Kubernetes. При обнаружении нового или измененного ресурса `Ingress` с подходящим `ingressClassName`, контроллер считывает его спецификацию.
3.  **Конфигурация маршрутизации:** На основе полученных данных контроллер динамически генерирует конфигурацию для своего базового прокси-движка (например, обновляет `nginx.conf` или xDS-конфигурацию Envoy).
4.  **Обработка трафика (Data Plane):** Контроллер перехватывает входящий трафик, предназначенный для внешнего IP или домена. Он анализирует заголовки запроса (`Host`, `Path`), чтобы сопоставить его с правилом.
5.  **Балансировка и SSL:** Контроллер выполняет терминацию SSL (если настроено) и выбирает стратегию балансировки между целевыми подами.
6.  **Проксирование:** Определив целевой сервис, контроллер направляет запрос напрямую к подам приложения.
7.  **Статус:** После успешной настройки контроллер обновляет поле `status.loadBalancer` в объекте Ingress, записывая туда IP-адрес или hostname точки входа.

### Поток трафика: от клиента к приложению 

Цепочка прохождения запроса:

1.  **DNS:** Клиент разрешает домен (например, `myapp.example.com`) в IP-адрес внешнего балансировщика.
2.  **LoadBalancer:** Направляет запрос в Ingress-контроллер (на Service типа `LoadBalancer` или `NodePort`).
3.  **Ingress Rules:** Контроллер анализирует заголовок **Host** и **Path**, находя соответствие в правилах.
4.  **Service и Endpoints:** Контроллер находит целевой Service и через объект `Endpoints` получает актуальные IP-адреса подов.
5.  **Direct Pod Access:** Контроллер отправляет запрос напрямую на IP пода, минуя ClusterIP сервиса для снижения задержек.
6.  **Pod:** Контейнер обрабатывает запрос на своем `targetPort`.

### Как Ingress находит поды (Механизм Endpoints)

Ingress-контроллер обычно работает с подами напрямую. 
1.  **Service** служит лишь абстракцией для группировки подов через селекторы.
2.  **Endpoints** (или **EndpointSlice**) — это "живой" список сетевых адресов подов, который Kubernetes обновляет автоматически.
3.  **Прямая маршрутизация** исключает лишний шаг NAT через `kube-proxy`, что критично для высоконагруженных систем.

### Сравнение: Ingress и Service

| Критерий | Service (L4) | Ingress (L7) |
| :--- | :--- | :--- |
| **Уровень OSI** | Транспортный (TCP/UDP) | Прикладной (HTTP/HTTPS) |
| **Маршрутизация** | По порту | По хосту и пути |
| **Внешние IP** | Один IP на сервис | Один IP на все сервисы (через контроллер) |
| **TLS** | Ручная настройка на уровне приложения | Централизованная терминация на контроллере |

### Внешний доступ к Ingress-контроллеру

Для работы с внешним миром контроллер использует один из методов:

1.  **LoadBalancer**: Самый распространенный в облаках. Создает внешний балансировщик провайдера.
2.  **NodePort**: Открывает порт на каждом узле кластера.
3.  **HostNetwork**: Позволяет контроллеру слушать порты 80/443 непосредственно на сетевом интерфейсе узла (максимальная производительность, но риск конфликтов).

Важные параметры:
- **`externalTrafficPolicy: Local`**: Позволяет сохранить реальный IP клиента, не заменяя его на IP узла при пересылке трафика.
- **PROXY Protocol**: Необходим, если перед Ingress стоит еще один L4 балансировщик, для передачи метаданных соединения (IP, порт).

### Режимы работы TLS

#### Режим 1 — TLS Termination (Терминация TLS)
Контроллер расшифровывает трафик, используя сертификат из `Secret`, и передает его бэкенду по HTTP. Это позволяет контроллеру анализировать и модифицировать HTTP-трафик.

#### Режим 2 — SSL Passthrough (Сквозное шифрование)
Контроллер проксирует зашифрованный поток напрямую к поду. Бэкенд сам терминирует SSL. Контроллер не видит HTTP-данные и может маршрутизировать только по **SNI** (имени хоста в TLS Hello).

### Интеграция с cert-manager: автоматизация TLS

В продакшен-среде ручное управление сертификатами неприемлемо. **cert-manager** — стандартный инструмент для автоматического выпуска, ротации и отслеживания TLS-сертификатов в Kubernetes. Он интегрируется с Ingress через компонент `ingress-shim`.

**Как это работает:**
1. Вы добавляете аннотацию (например, `cert-manager.io/cluster-issuer: letsencrypt-prod`) к ресурсу Ingress.
2. `ingress-shim` обнаруживает аннотацию и автоматически создает ресурс `Certificate`.
3. cert-manager взаимодействует с CA (Let's Encrypt, HashiCorp Vault) и выпускает сертификат.
4. Сертификат сохраняется в Kubernetes `Secret`, который Ingress-контроллер подхватывает без рестартов.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - app.example.com
    secretName: app-tls-auto
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-app
            port:
              number: 80
```

> **Подробная документация:** [Cert-manager: Интеграция с Ingress](../../ToolsUtilities/cert_manager/ingress/overview.md) — аннотации, сценарии использования, troubleshooting.

### Статус Ingress и условия (Conditions)

После создания Ingress-контроллер обновляет поле `status` в объекте Ingress. Это ключевой механизм обратной связи:

```bash
kubectl get ingress my-app -o jsonpath='{.status.loadBalancer}'
# → {"ingress":[{"ip":"10.0.0.1"}]} или {"ingress":[{"hostname":"abc123.elb.amazonaws.com"}]}
```

**Типичные условия (Conditions) в статусе:**

| Condition | Статус | Описание |
| :--- | :--- | :--- |
| `Ready` | `True` / `False` | Контроллер успешно обработал Ingress и настроил прокси. |
| `Programmed` | `True` / `False` | Транспортный слой (Listener) настроен и принимает трафик. |
| `Accepted` | `True` / `False` | Ingress принят контроллером (валидная конфигурация). |

> **Важно:** Если поле `status.loadBalancer.ingress` пустое — контроллер еще не обработал Ingress или произошла ошибка. Это первый индикатор проблемы при диагностике.

### Популярные аннотации

Аннотации Ingress-контроллеров не стандартизированы — каждое решение имеет свой набор. Ниже приведены наиболее распространенные паттерны:

| Функция | NGINX Ingress | Traefik | HAProxy | Описание |
| :--- | :--- | :--- | :--- | :--- |
| **Rewrite** | `nginx.ingress.kubernetes.io/rewrite-target: /$1` | Нативная поддержка через `PathPrefix` + `StripPrefix` middleware | `haproxy.org/path-rewrite: /(.*) /v1/\1` | Изменение пути перед отправкой в бэкенд. |
| **SSL Redirect** | `nginx.ingress.kubernetes.io/force-ssl-redirect: "true"` | Мiddleware `redirectScheme` | `haproxy.org/ssl-redirect: "true"` | Редирект HTTP на HTTPS. |
| **Rate Limit** | `nginx.ingress.kubernetes.io/limit-rps: "10"` | Middleware `rateLimit` | `haproxy.org/rate-limit: "10"` | Ограничение запросов в секунду. |
| **Auth** | `nginx.ingress.kubernetes.io/auth-type: basic` | Middleware `basicAuth` | `haproxy.org/auth: "basic"` | Базовая аутентификация через Secret. |
| **CORS** | `nginx.ingress.kubernetes.io/enable-cors: "true"` | Middleware `headers` | `haproxy.org/cors: "true"` | Настройка Cross-Origin Resource Sharing. |
| **WebSocket** | `nginx.ingress.kubernetes.io/websocket-services: "svc"` | Автообнаружение Upgrade | `haproxy.org/path-announce: "true"` | Поддержка WebSocket-соединений. |
| **Body Size** | `nginx.ingress.kubernetes.io/proxy-body-size: "10m"` | Middleware `buffering` | `haproxy.org/max-conn` | Максимальный размер тела запроса. |
| **Timeout** | `nginx.ingress.kubernetes.io/proxy-connect-timeout: "10"` | BackendTrafficPolicy timeout | `haproxy.org/server-timeout` | Таймауты подключения к бэкенду. |

> **Важно:** Конкретные имена аннотаций различаются между контроллерами. Всегда сверяйтесь с документацией вашего контроллера.

### Масштабирование и высокая доступность

1.  **Requests/Limits**: Обязательны для CPU и RAM. Ingress-контроллер — критический узел.
2.  **HPA**: Масштабирование по CPU или кастомным метрикам (например, количество запросов).
3.  **Topology Spread**: Распределение подов по разным зонам доступности (AZ) и узлам.
4.  **PriorityClass**: Назначение высокого приоритета (`system-cluster-critical`) для защиты от вытеснения.

### Архитектурные паттерны

#### 1. L4 LB + Ingress-контроллер
Стандартный паттерн. Внешний NLB (TCP) -> Ingress Controller (L7) -> Pod. Гибкость и независимость от облака.

#### 2. L7 LB (ALB) как Ingress
Облачный балансировщик (напр. AWS ALB) сам выступает в роли контроллера. Меньше нагрузки на кластер, но жесткая привязка к провайдеру.

#### 3. Bare-Metal с MetalLB
Имитация облачного LoadBalancer в локальной сети через протоколы BGP или L2 (ARP).

---

## Практические сценарии

### Сценарий 1 — маршрутизация по хосту

Разделение трафика по доменным именам:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: multi-host-ingress
spec:
  ingressClassName: nginx
  rules:
    - host: "api.example.com"
      http:
        paths:
          - pathType: Prefix
            path: "/"
            backend:
              service:
                name: api-service
                port:
                  number: 80
    - host: "app.example.com"
      http:
        paths:
          - pathType: Prefix
            path: "/"
            backend:
              service:
                name: frontend-service
                port:
                  number: 80
```

### Сценарий 2 — маршрутизация по пути

Один домен, разные микросервисы в зависимости от URL:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
spec:
  ingressClassName: nginx
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
                name: frontend-service
                port:
                  number: 80
```

### Сценарий 3 — Default Backend (Бэкенд по умолчанию)

Обработка запросов, которые не попали ни под одно правило:

```yaml
spec:
  ingressClassName: nginx
  defaultBackend:
    service:
      name: error-page-service
      port:
        number: 80
  rules:
    # ... основные правила ...
```

### Сценарий 4 — TLS с несколькими сертификатами

```yaml
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.example.com
    secretName: api-tls-secret
  - hosts:
    - shop.example.com
    secretName: shop-tls-secret
  rules:
  - host: api.example.com
    # ...
  - host: shop.example.com
    # ...
```

---

## Ограничения и особенности Ingress

### WebSocket и Server-Sent Events (SSE)

Ingress-контроллеры поддерживают WebSocket и SSE, но требуют явной настройки:

| Контроллер | WebSocket | Аннотация / Настройка |
| :--- | :--- | :--- |
| **NGINX Ingress** | Да | `nginx.ingress.kubernetes.io/websocket-services: "svc-name"` |
| **Traefik** | Да | Автоматическое обнаружение заголовка `Upgrade: websocket`. |
| **HAProxy** | Да | `haproxy.org/path-announce: "true"` + timeout туннеля. |

**Типичная проблема:** разрыв соединения через 60 секунд из-за дефолтного таймаута прокси. Решение — увеличение `proxy-read-timeout` и `proxy-send-timeout`.

### gRPC-поддержка

Ingress-контроллеры способны маршрутизировать gRPC-трафик, поскольку gRPC использует HTTP/2 поверх TLS:

- **Проблема:** gRPC требует HTTP/2, а большинство контроллеров по умолчанию проксируют HTTP/1.1.
- **Решение:** Убедитесь, что между клиентом и контроллером установлено соединение HTTP/2 (ALPN). Внутри кластера gRPC работает через HTTP/2 нативно.
- **Ограничение:** Regex-маршрутизация (`ImplementationSpecific`) не работает с gRPC. Используйте `Prefix` или `Exact`.

### IPv6 и Dual-Stack

Ingress-контроллеры поддерживают IPv6 начиная с Kubernetes 1.20+:

- Внешний балансировщик должен иметь AAAA-записи.
- Ingress-контроллеры (NGINX, Traefik) поддерживают_dual-stack_ на уровне Service.
- `EndpointSlice` автоматически содержит IPv6-адреса подов при dual-stack кластере.

> **Ограничение:** Некоторые контроллеры (особенно облачные) могут не поддерживать IPv6 для Ingress. Проверяйте документацию конкретного контроллера.

### Кросс-неймспейсные ссылки (Cross-Namespace)

По умолчанию Ingress может ссылаться только на Service в том же Namespace. Для маршрутизации трафика в другие неймспейсы:

- **Вариант 1:** Создать отдельный Ingress в каждом неймспейсе.
- **Вариант 2:** Использовать Gateway API с `ReferenceGrant` для кросс-неймспейсных ссылок (рекомендуется).
- **Вариант 3:** Использовать `ExternalName Service` как прокси (работает, но добавляет лишний DNS-запрос).

---

## Безопасность Ingress

### Базовая защита

| Мера | Описание | Реализация |
| :--- | :--- | :--- |
| **TLS Termination** | Шифрование трафика на контроллере. | Секция `spec.tls` в Ingress. |
| **HSTS** |强制 HTTPS для браузеров. | Аннотация контроллера (например, `nginx.ingress.kubernetes.io/force-ssl-redirect`). |
| **Rate Limiting** | Защита от DDoS и брутфорса. | Аннотации: `limit-rps`, `limit-connections`. |
| **IP Whitelisting** | Ограничение доступа по IP. | `nginx.ingress.kubernetes.io/allow-source-range`. |
| **Basic/OIDC Auth** | Аутентификация на уровне контроллера. | `auth-type`, `auth-url` аннотации. |

### NetworkPolicy для Ingress-контроллера

Ingress-контроллер часто работает в отдельном неймспейсе (например, `ingress-nginx`). Необходимо явно разрешить трафик от контроллера к подам приложения:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress-controller
  namespace: my-app
spec:
  podSelector:
    matchLabels:
      app: my-app
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8080
```

> **Подробнее:** [NetworkPolicy — Best Practices](../Network/NetworkPolicy/best_practices.md).

### Безопасность Ingress-контроллера

- **RBAC:** Контроллер должен иметь минимально необходимые права (только чтение Ingress, Service, Endpoints, Secrets).
- **Секреты TLS:** Не храните приватные ключи в ConfigMap — используйте только `Secret`.
- **WAF (Web Application Firewall):** Интеграция ModSecurity или аналогичного решения для защиты от SQL-инъекций, XSS и других атак OWASP Top 10.
- **Обновления:** Регулярно обновляйте Ingress-контроллер для получения исправлений уязвимостей.

---

## Мониторинг и наблюдаемость

### Ключевые метрики Ingress-контроллера

| Метрика | Описание | Источник |
| :--- | :--- | :--- |
| `nginx_ingress_controller_requests` | Общее количество запросов по кодам ответа. | Prometheus ( exporter контроллера). |
| `nginx_ingress_controller_request_duration_seconds` | Латентность запросов (p50, p95, p99). | Prometheus. |
| `nginx_ingress_controller_nginx_process_connections_active` | Активные соединения к бэкенду. | Prometheus. |
| `up` | Доступность Ingress-контроллера. | Prometheus `up` job. |

### Настройка мониторинга

1. **Включение метрик:** Большинство контроллеров экспортируют метрики на порту по умолчанию (NGINX: `10254`, Traefik: `8080`).
2. **ServiceMonitor (Prometheus Operator):**
   ```yaml
   apiVersion: monitoring.coreos.com/v1
   kind: ServiceMonitor
   metadata:
     name: ingress-controller
     namespace: monitoring
   spec:
     selector:
       matchLabels:
         app.kubernetes.io/name: ingress-nginx
     endpoints:
     - port: metrics
       interval: 30s
   ```
3. **Дашборды:** Готовые дашборды Grafana доступны для NGINX Ingress (ID: 9614), Traefik (ID: 17347).

### Логирование

- **Structured Logs:** Включите JSON-формат логов для удобства парсинга (ELK/Loki).
- **Access Logs:** Содержат информацию о каждом запросе: клиентский IP, путь, код ответа, время обработки.
- **Error Logs:** Содержат информацию о ошибках проксирования, TLS, DNS-резолвинга.

---

## Лучшие практики (Best Practices)

### Архитектура

1. **Всегда используйте IngressClass** вместо аннотации `kubernetes.io/ingress.class` — это обеспечивает явное разделение контроллеров.
2. **Один Ingress-контроллер на задачу** — не смешивайте внешний и внутренний трафик в одном контроллере, если не используете IngressClass.
3. **Default Backend:** Настройте глобальный default backend для обработки неизвестных хостов (защита от сканирования).
4. **Не используйте Ingress для TCP/UDP:** Ingress работает на L7. Для L4-трафика используйте Service `LoadBalancer` или Gateway API (`TCPRoute`/`UDPRoute`).

### Производительность

1. **HPA для Ingress-контроллера:** Масштабируйте контроллер по CPU и кастомным метрикам (QPS, латентность).
2. **PodDisruptionBudget:** Защитите Ingress-контроллер от вытеснения при обновлении узлов.
3. **Topology Spread Constraints:** Распределите поды контроллера по зонам доступности.
4. **Ресурсы (Requests/Limits):** Всегда задавайте `requests` и `limits` для CPU и RAM.

### Обновление и миграция

1. **Canary-обновления:** Используйте IngressClass с разными контроллерами для постепенного перехода.
2. **Blue/Green:** Создайте два IngressClass с разными контроллерами и переключайте DNS.
3. **Миграция на Gateway API:** Планируйте переход — Ingress API не развивается и будет deprecated.

> **Подробнее:** [Миграция с Ingress на Gateway API](../gateway_api/migration.md).

---

## Устранение неполадок Ingress

### Алгоритм диагностики

Если приложение недоступно извне, выполняйте шаги последовательно:

#### Шаг 1 — Проверка DNS и внешнего доступа

```bash
# Разрешение домена в IP
nslookup myapp.example.com
# → myapp.example.com: 10.0.0.1 (ожидается IP балансировщика)

# Проверка доступности через curl
curl -vk https://myapp.example.com 2>&1 | grep -E "< HTTP|SSL|connect"
# → < HTTP/2 200 (если TLS настроен корректно)
# → * Connected to myapp.example.com port 443 (если соединение установлено)
```

**Типичные проблемы:**
- DNS не резолвится — проверьте A/AAAA-записи.
- Connection refused — балансировщик не доступен или не слушает порт 443.
- SSL handshake failed — сертификат истек или не покрывает домен.

#### Шаг 2 — Проверка статуса Ingress

```bash
# Проверка наличия адреса у Ingress
kubectl get ingress my-app -n my-namespace
# → NAME    CLASS   HOSTS              ADDRESS        PORTS   AGE
# → my-app  nginx   myapp.example.com  10.0.0.1       80,443  5m

# Если ADDRESS пуст — контроллер не обработал Ingress
kubectl describe ingress my-app -n my-namespace
# → Events:
# →   Normal  CREATE  1m  ingress-controller Ingress my-namespace/my-app created
```

#### Шаг 3 — Проверка Endpoints

```bash
# Проверка наличия готовых подов за сервисом
kubectl get endpoints my-service -n my-namespace
# → NAME         ENDPOINTS                     AGE
# → my-service    10.244.1.5:8080,10.244.2.3:8080  10m

# Если ENDSETS пуст — проблема с readinessProbe или селекторами
kubectl describe svc my-service -n my-namespace
# → Selector:  app=my-app (должен совпадать с labels подов)
# → Ports:
# →   Name: http  Port: 80  TargetPort: 8080
```

#### Шаг 4 — Проверка NetworkPolicy

```bash
# Проверка наличия политик, блокирующих трафик
kubectl get networkpolicy -n my-namespace
# → NAME                    POD-SELECTOR   AGE
# → default-deny-ingress    <none>         5d

# Если есть default-deny — убедитесь, что Ingress-контроллер разрешен
kubectl describe networkpolicy default-deny-ingress -n my-namespace
# → Ingress:
# →   From:  (пусто = весь трафик заблокирован)
```

#### Шаг 5 — Проверка логов контроллера

```bash
# Логи NGINX Ingress Controller
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=20
# → 10.0.0.1 - - [30/Aug/2026:12:00:00 +0000] "GET /api HTTP/2.0" 200 1234 "-" "curl/7.68"
# → 10.0.0.1 - - [30/Aug/2026:12:00:01 +0000] "GET /missing HTTP/2.0" 404 0 "-" "curl/7.68"

# Поиск ошибок
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx | grep -i "error\|upstream\|502\|503"
# → upstream timed out (110: Connection timed out) while connecting to upstream
```

### Типичные ошибки и их решения

| Код ошибки | Причина | Решение |
| :--- | :--- | :--- |
| **503 Service Unavailable** | Нет доступных Endpoints за Service. | Проверьте readinessProbe, селекторы в Service,.lifecycle. |
| **502 Bad Gateway** | Бэкенд не отвечает или закрыл соединение. | Проверьте targetPort, таймауты, health check подов. |
| **404 Not Found** | Путь не совпадает ни с одним правилом Ingress. | Проверьте pathType (Prefix vs Exact) и path в Ingress. |
| **413 Request Entity Too Large** | Тело запроса превышает лимит контроллера. | Увеличьте `proxy-body-size` аннотацию. |
| **TLS handshake failure** | Сертификат недействителен или не покрывает домен. | Проверьте Secret с сертификатом, SAN, дату истечения. |
| **Ingress без ADDRESS** | Контроллер не нашел подходящий IngressClass. | Укажите `ingressClassName` или создайте класс по умолчанию. |

### Точность путей: Exact vs Prefix

Неверный выбор `pathType` — частая причина того, что трафик не попадает в приложение:

- **Prefix**: Путь `/api` совпадает с `/api/v1`, `/api/login`, `/api/users` и т.д.
- **Exact**: Путь `/api` совпадает **только** с `/api`. Запрос к `/api/` (со слэшем) вернет 404.

> **Совет для тестирования:** Если у вас есть публичный IP, но нет настроенной DNS-записи, используйте сервисы типа `nip.io` или `sslip.io`. Например: `1.2.3.4.nip.io` будет разрешаться в IP `1.2.3.4`. Это позволяет тестировать Ingress с реальными хостнеймами.

### Полезные команды

| Команда | Описание | Пример вывода |
| :--- | :--- | :--- |
| `kubectl get ingress -A` | Список всех точек входа в кластере. | `my-app ingress-nginx myapp.example.com 10.0.0.1 80,443 5m` |
| `kubectl describe ingress <name>` | Детальная информация о правилах и TLS. | Rules, Annotations, Events, LoadBalancer status. |
| `kubectl logs -n <ns> <pod>` | Логи работы прокси-сервера. | Access log с кодами ответа и latencies. |
| `kubectl get ingressclass` | Список доступных классов и класс по умолчанию. | `nginx  k8s.io/ingress-nginx  true` |
| `kubectl get events -n <ns>` | События, связанные с Ingress. | CREATE, UPDATE, RELOAD事件. |
| `kubectl exec -it <controller-pod> -- cat /etc/nginx/nginx.conf` | Просмотр сгенерированной конфигурации. | Полный `nginx.conf` с upstream и location. |

---

## Дополнительная информация

### Gateway API — эволюция Ingress

Gateway API решает проблемы масштабируемости и разделения ответственности, которые были ограничены в Ingress. Он предлагает более гранулярный контроль и встроенную поддержку продвинутых функций (канареечные деплои, gRPC, L4-маршрутизация).

Подробности: [Kubernetes Gateway API](../gateway_api/definitions.md).

### См. также

- [Сравнение Ingress-контроллеров](./controllers_comparison.md) — обзор 8 популярных контроллеров с критериями выбора.
- [Миграция с Ingress на Gateway API](../gateway_api/migration.md) — пошаговое руководство по переходу.
- [Путь трафика в Kubernetes](../Network/traffic_path.md) — детальный разбор прохождения запроса (North-South, East-West).
- [Настройка Manual Proxy (Bare-metal)](./bare_metal_manual_proxy.md) — внешний доступ без облачного LoadBalancer.
- [Cert-manager: Интеграция с Ingress](../../ToolsUtilities/cert_manager/ingress/overview.md) — автоматизация TLS-сертификатов.
