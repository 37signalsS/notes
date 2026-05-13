# Ingress: Обзор и Основные Концепции

## Определения

**Ingress** — это объект API Kubernetes, который описывает правила маршрутизации внешнего HTTP и HTTPS трафика к сервисам внутри кластера. Он действует как "умный" маршрутизатор или точка входа, позволяя определять правила маршрутизации на основе имени хоста (например, `api.example.com`) или пути (например, `/v1/users`). Ingress работает на **7 уровне модели OSI (прикладной уровень)** и позволяет централизованно управлять доступом к множеству сервисов через единый IP-адрес.

**Ingress-контроллер** — это приложение (обычно `Deployment` или `DaemonSet`), которое фактически реализует правила, описанные в объекте `Ingress`. Он отслеживает изменения в API-сервере Kubernetes и настраивает нижележащий прокси-сервер (например, NGINX, HAProxy, Traefik). **Без Ingress-контроллера объект Ingress не будет работать.**

**Ключевые компоненты:**

- **Ingress Resource** — манифест с правилами маршрутизации (объект API)
- **Ingress Controller** — приложение, реализующее эти правила
- **Backend Service** — сервис Kubernetes, получающий трафик

### Почему Ingress, а не Service?

Хотя для публикации приложений можно использовать `Service` типа `LoadBalancer` или `NodePort`, `Ingress` является предпочтительным решением для HTTP/HTTPS трафика по нескольким ключевым причинам:

| Критерий | Service (L4) | Ingress (L7) |
| :--- | :--- | :--- |
| **Уровень OSI** | Транспортный (TCP/UDP) | Прикладной (HTTP/HTTPS) |
| **Маршрутизация** | По порту | По хосту и пути |
| **Внешние IP** | Один IP на сервис | Один IP на все сервисы |
| **TLS** | Ручная настройка на сервисе | Централизованная терминация |
| **Гибкость** | Ограниченная | Расширяемая (аннотации) |

**Преимущества Ingress:**

1. **Маршрутизация на L7** — гибкие правила на основе имени хоста и пути
2. **Централизованная точка входа** — один внешний IP для множества сервисов
3. **Терминация TLS** — централизованное управление SSL-сертификатами
4. **Гибкая конфигурация** — аутентификация, rate limiting, перезапись URL через аннотации

---

## Основные концепции

### Внешний доступ к Ingress-контроллеру

Для обработки внешнего трафика Ingress-контроллер должен быть выставлен наружу кластера:

| Способ | Описание | Применение |
| :--- | :--- | :--- |
| **LoadBalancer** | Service типа `LoadBalancer`, облачный провайдер выделяет внешний IP | Облачные среды (AWS, GCP, Azure) |
| **NodePort** | Service типа `NodePort`, доступ на порту каждого узла | On-premise, тестовые среды |
| **Manual Proxy** | Внешний Nginx/HAProxy проксирует трафик на NodePort | Bare-metal при отсутствии MetalLB |
| **HostPort** | Публикация порта непосредственно на сетевом интерфейсе узла | Специализированные сценарии |

Подробное описание настройки Manual Proxy (NodePort + Nginx + dnsmasq) см. в [соответствующем руководстве](./bare_metal_manual_proxy.md).

### Правила маршрутизации

Ingress поддерживает два типа маршрутизации:

- **Host-based** — маршрутизация по имени хоста (`api.example.com` → один сервис, `shop.example.com` → другой)
- **Path-based** — маршрутизация по пути URL (`example.com/api` → API сервис, `example.com/` → фронтенд)

Подробные примеры манифестов для каждого типа доступны в разделе [Практические сценарии](#практические-сценарии).

### TLS в Ingress: режимы работы

#### Режим 1: TLS Termination (терминирование на контроллере)

Сертификат прикреплён к Ingress через Secret, контроллер расшифровывает трафик и передаёт бэкенду по HTTP.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  tls:
  - hosts:
    - api.example.com
    secretName: api-tls-secret
  rules:
  - host: api.example.com
    http:
      paths:
      - pathType: Prefix
        path: /
        backend:
          service:
            name: api-service
            port:
              number: 8080
```

**Характеристики:**

- Контроллер видит HTTP-заголовки
- Доступна маршрутизация по пути, заголовкам, cookies
- Бэкенд получает трафик по HTTP (или HTTPS при re-encrypt)

#### Режим 2: SSL Passthrough (сквозное шифрование)

Контроллер проксирует зашифрованный поток напрямую к поду, не расшифровывая его. Включается аннотацией:

```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/ssl-passthrough: "true"
```

**Характеристики:**

- Контроллер **не видит HTTP-заголовки**
- Маршрутизация возможна **только по SNI** (имени хоста в TLS Client Hello)
- Маршрутизация по пути или заголовкам **недоступна**
- Бэкенд сам терминирует SSL

> **Важно для миграции:** Если для одного хоста одновременно используются passthrough и HTTP-маршрутизация — архитектуру придётся пересматривать. Зафиксируйте для каждого хоста режим TLS до начала миграции на Gateway API.

---

## Практические сценарии

### Сценарий 1: Маршрутизация по хосту (Host-based)

Направление трафика с разных доменов на разные сервисы:

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

**Использование:** Разделение API (`api.example.com`) и веб-интерфейса (`app.example.com`).

### Сценарий 2: Маршрутизация по пути (Path-based)

Направление трафика одного домена на разные сервисы в зависимости от пути:

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
                name: frontend-service
                port:
                  number: 80
```

**Типы путей:**

- `pathType: Prefix` — соответствует любому пути, начинающемуся с указанного (`/api/v1`, `/api/v2`)
- `pathType: Exact` — точное совпадение пути
- `pathType: ImplementationSpecific` — зависит от реализации контроллера

**Использование:** Микросервисная архитектура, где `/api` идёт на бэкенд, а `/` — на фронтенд.

### Сценарий 3: Default Backend (резервный сервис)

Сервис для обработки трафика, не соответствующего правилам:

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

**Использование:** Страница-заглушка или сервис ошибок для необработанных запросов.

### Сценарий 4: TLS с несколькими сертификатами

```yaml
spec:
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

**Использование:** Разные SSL-сертификаты для разных доменов.

---

## Схема работы: путь трафика

Подробное описание пути трафика в Kubernetes, от внешнего запроса до пода, включая роль Ingress Controller, Service и kube-proxy, доступно в документе [Путь трафика в Kubernetes](../Network/traffic_path.md).

---

## Дополнительная информация

### Gateway API: эволюция Ingress

**Gateway API** — новое поколение API для управления трафиком в Kubernetes, разработанное для решения фундаментальных ограничений Ingress:

- **Стандартизация** — единая спецификация для всех вендоров (Envoy, Cilium, Istio, Traefik)
- **Ролевая модель** — разделение ответственности между инфраструктурой и разработчиками
- **Расширенные функции** — канареечные развертывания, gRPC, TCP/UDP маршрутизация из коробки

Подробное описание концепции и примеры использования доступны в документе [Kubernetes Gateway API](../gateway_api/definitions.md).

### Миграция с Ingress на Gateway API

Сообщество Kubernetes рекомендует переходить на Gateway API для новых проектов. Инструмент **ingress2gateway** автоматизирует преобразование манифестов Ingress в Gateway API.

Руководство по миграции: [Миграция с Ingress на Gateway API](../gateway_api/migration.md).

### Сравнение Ingress-контроллеров

Для выбора подходящего контроллера рекомендуется ознакомиться с документом [Ingress Controllers: Сравнение и Выбор](./controllers_comparison.md), который содержит:

- Детальное сравнение Traefik, Contour, Cilium, Kong, HAProxy, Istio
- Практические сценарии выбора для различных архитектур
- Таблицы производительности и функциональности
