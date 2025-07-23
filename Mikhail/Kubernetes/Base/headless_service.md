# Headless Service

**Headless Service** — это особый тип сервиса в Kubernetes, который не имеет собственного `ClusterIP`. Вместо того чтобы предоставлять единую точку входа для балансировки нагрузки, он возвращает DNS-записи для всех подов, которые соответствуют его селектору.

Это делает его идеальным для использования со **StatefulSet**, так как позволяет напрямую обращаться к каждому поду по его уникальному DNS-имени.

---

### Как это работает?

Когда вы создаете Headless Service, Kubernetes создает DNS A-записи для каждого пода, который подпадает под селектор сервиса. Эти записи имеют формат:

`<имя-пода>.<имя-сервиса>.<пространство-имен>.svc.cluster.local`

Например, для пода `web-0` и сервиса `nginx` в пространстве имен `default`, DNS-имя будет `web-0.nginx.default.svc.cluster.local`.

---

### Пример: Headless Service для StatefulSet

Этот манифест создает Headless Service с именем `nginx-headless`, который будет обслуживать поды StatefulSet с меткой `app: nginx`.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-headless
  labels:
    app: nginx
spec:
  # Установка clusterIP: None делает сервис "headless"
  clusterIP: None
  ports:
    - port: 80
      name: web
  selector:
    # Селектор должен соответствовать меткам подов StatefulSet
    app: nginx
```

### Проверка

После создания сервиса и соответствующего StatefulSet, вы можете проверить DNS-записи из любого пода в кластере:

```bash
# Запрос вернет IP-адреса всех подов, обслуживаемых сервисом
nslookup nginx-headless

# Запрос вернет IP-адрес конкретного пода
nslookup web-0.nginx-headless
```
