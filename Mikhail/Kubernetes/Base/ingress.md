# Ingress

**Ingress** — это объект API Kubernetes, который управляет внешним доступом к сервисам в кластере, как правило, по протоколу HTTP/HTTPS. Он действует как "умный" маршрутизатор или точка входа в кластер, позволяя определять правила маршрутизации трафика на основе хоста (например, `example.com`) или пути (например, `/api`).

**Важно:** Ingress не работает сам по себе. Для его функционирования в кластере должен быть установлен и запущен **Ingress-контроллер** (например, NGINX Ingress Controller, Traefik, HAProxy Ingress).

---

### Как это работает?

1.  Вы создаете объект `Ingress`, в котором описываете правила маршрутизации.
2.  Ingress-контроллер отслеживает создание и изменение объектов `Ingress`.
3.  На основе этих правил контроллер автоматически настраивает нижележащий балансировщик нагрузки (например, Nginx), чтобы он направлял трафик на соответствующие сервисы (`Service`).

Ingress **не** отправляет трафик напрямую в поды. Он всегда работает через `Service`.

---

### Пример: Простой Ingress

Этот манифест создает Ingress, который направляет весь трафик, приходящий на хост `myapp.example.com`, на сервис `my-app-service`.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  annotations:
    # Аннотации специфичны для используемого Ingress-контроллера.
    # Эта аннотация для NGINX Ingress Controller указывает, что путь перезаписывать не нужно.
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
    - host: myapp.example.com
      http:
        paths:
          - path: /
            pathType: Prefix # Тип соответствия пути (Prefix, Exact, ImplementationSpecific)
            backend:
              service:
                name: my-app-service # Имя сервиса, на который пойдет трафик
                port:
                  number: 80 # Порт этого сервиса
```

### TLS/SSL

Ingress также позволяет легко настраивать TLS-шифрование. Для этого нужно создать `Secret`, содержащий TLS-сертификат и ключ, и сослаться на него в спецификации Ingress.

```yaml
# ... (часть Ingress манифеста)
spec:
  tls:
    - hosts:
        - myapp.example.com
      secretName: my-app-tls-secret # Имя секрета с сертификатом
  rules:
# ... (остальная часть)
```
