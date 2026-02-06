# Ingress

## Определения

**Ingress** — это объект API Kubernetes, который описывает правила маршрутизации внешнего HTTP и HTTPS трафика к сервисам внутри кластера. Он действует как "умный" маршрутизатор или точка входа, позволяя определять правила маршрутизации на основе имени хоста (например, `api.example.com`) или пути (например, `/v1/users`). Ingress работает на **7 уровне модели OSI (прикладной уровень)** и позволяет централизованно управлять доступом к множеству сервисов через единый IP-адрес.

**Ingress-контроллер** — это приложение (обычно `Deployment` или `DaemonSet`), которое фактически реализует правила, описанные в объекте `Ingress`. Он отслеживает изменения в API-сервере Kubernetes и настраивает нижележащий прокси-сервер (например, NGINX, HAProxy, Traefik). **Без Ingress-контроллера объект Ingress не будет работать.**

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

## Практические сценарии

### Настройка TLS/SSL

Ingress упрощает терминирование TLS-трафика. Для подключения HTTPS к Ingress, когда у вас уже есть сертификат и ключ, необходимо выполнить следующие шаги:

1. **Создайте `Secret` типа `kubernetes.io/tls` с сертификатом и ключом:**
    Этот Secret будет хранить ваш TLS-сертификат (`tls.crt`) и приватный ключ (`tls.key`).

    ```bash
    kubectl create secret tls my-app-tls-secret \
      --cert=path/to/tls.crt \
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

## Дополнительная информация

### Схема работы: путь трафика в Kubernetes

Подробное описание пути трафика в Kubernetes, от внешнего запроса до пода, включая роль Ingress Controller, Service и kube-proxy, было перенесено в документ [Сетевая модель в Kubernetes](./network.md#путь-трафика-от-ingress-до-pod) для централизации информации.

### Будущее Ingress: Gateway API

Несмотря на свою популярность, `Ingress` имеет ряд фундаментальных ограничений, таких как смешение ролей и зависимость от нестандартных аннотаций. Для их решения сообщество Kubernetes разработало **Gateway API** — новое поколение API для управления трафиком.

Gateway API предлагает более гибкую, мощную и ролевую модель, разделяя ответственность между администраторами инфраструктуры и разработчиками приложений.

Подробное описание концепции и примеры использования вынесены в отдельный документ: **[→ Kubernetes Gateway API](./gateway_api.md)**.

Ожидается, что со временем Gateway API станет стандартным способом управления L4/L7-трафиком в Kubernetes.
