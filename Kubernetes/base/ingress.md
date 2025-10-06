# Ingress

**Ingress** — это объект API Kubernetes, который управляет внешним доступом к сервисам в кластере, как правило, по протоколам **HTTP** и **HTTPS**. Он действует как "умный" маршрутизатор или точка входа, позволяя определять правила маршрутизации трафика на основе имени хоста (например, `api.example.com`) или пути (например, `/v1/users`).

Ingress является высокоуровневой абстракцией, которая позволяет централизованно управлять доступом к множеству сервисов через единый IP-адрес.

## Роль Ingress-контроллера

**Ingress не работает сам по себе.** Для его функционирования в кластере должен быть установлен и запущен **Ingress-контроллер**.

**Ingress-контроллер** — это приложение (обычно работающее как `Deployment`), которое отслеживает объекты `Ingress` в API-сервере Kubernetes и настраивает нижележащий прокси-сервер или балансировщик нагрузки в соответствии с правилами, описанными в этих объектах.

## Схема работы: путь трафика в Kubernetes

Подробное описание пути трафика в Kubernetes, от внешнего запроса до пода, включая роль Ingress Controller, Service и kube-proxy, было перенесено в документ [Сетевая модель в Kubernetes](./network.md#путь-трафика-от-ingress-до-pod) для централизации информации.

## 4. Правила маршрутизации (Routing Rules)

### Маршрутизация по хосту (Host-based)

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

### Маршрутизация по пути (Path-based)

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
*   `pathType: Prefix` — соответствует любому пути, который начинается с указанного значения (например, `/api/v1`, `/api/v2`).
*   `pathType: Exact` — соответствует только точно указанному пути.

### Хост по умолчанию (Default Backend)

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

## Настройка TLS/SSL

Ingress упрощает терминирование TLS-трафика.

1.  **Создайте `Secret` с сертификатом и ключом:**
    ```bash
    kubectl create secret tls my-app-tls-secret --cert=path/to/tls.crt --key=path/to/tls.key
    ```

2.  **Укажите этот `Secret` в манифесте Ingress:**

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
Теперь трафик по `https://myapp.example.com` будет зашифрован.

## Аннотации (Annotations)

Аннотации — это основной способ тонкой настройки поведения Ingress-контроллера. Они специфичны для каждого типа контроллера.

**Примеры для NGINX Ingress Controller:**
*   `nginx.ingress.kubernetes.io/rewrite-target: /` — перенаправляет трафик с указанного `path` на корневой путь (`/`) сервиса.
*   `nginx.ingress.kubernetes.io/ssl-redirect: "true"` — принудительно перенаправляет HTTP-трафик на HTTPS.
*   `nginx.ingress.kubernetes.io/proxy-body-size: "8m"` — устанавливает максимальный размер тела запроса.
*   `kubernetes.io/ingress.class: "nginx"` — указывает, какой Ingress-контроллер должен обрабатывать этот объект (актуально, если в кластере их несколько).
