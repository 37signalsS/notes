# Ingress: Практические Сценарии

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
