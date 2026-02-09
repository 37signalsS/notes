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
