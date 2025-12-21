# Как настроить BasicAuth в Traefik с Kubernetes

Разбираемся, как правильно создать секрет в Kubernetes и не споткнуться.

➡️ **data vs stringData**

— `data`: Данные нужно кодировать в base64 вручную. Например, для логина `admin` и пароля `supersecret`:

```bash
echo 'admin:supersecret' | base64
```

```yaml
apiVersion: v1
  kind: Secret
  metadata:
    name: my-auth-secret
    namespace: default
  data:
    users: YWRtaW46c3VwZXJzZWNyZXQK
```

— `stringData`: Пишем в обычном тексте, Kubernetes сам закодирует в base64:

```yaml
apiVersion: v1
  kind: Secret
  metadata:
    name: my-auth-secret
    namespace: default
  stringData:
    users: admin:supersecret
```

🤔 **Подвох с Traefik**

Traefik для basicAuth требует пароль, хэшированный в формате `htpasswd`. Обычный текст не подойдёт.

Генерим хэш:

```bash
htpasswd -nb admin supersecret
# Пример вывода: admin:$apr1$2a9XgJ3z$4oD.3Y3z9x9z9z9z9z9z9z
```

Кодируем в base64 для `data`:

```bash
echo -n 'admin:$apr1$2a9XgJ3z$4oD.3Y3z9x9z9z9z9z9z9z' | base64
# Пример вывода: YWRtaW46JGFwcjEkMmE5WGdKM3okNE9ELjNZM3o5eDl6OXo5ejo5ejk5eg==
```

Секрет для Traefik:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: traefik-auth-secret
  namespace: default
data:
  users: YWRtaW46JGFwcjEkMmE5WGdKM3okNE9ELjNZM3o5eDl6OXo5ejo5ejk5eg==
```

Или с `stringData`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: traefik-auth-secret
  namespace: default
stringData:
  users: admin:$apr1$2a9XgJ3z$4oD.3Y3z9x9z9z9z9z9z9z
```

Подключаем к middleware:

```yaml
kind: Middleware
metadata:
  name: auth
  namespace: default
spec:
  basicAuth:
    secret: traefik-auth-secret
```

`stringData` упрощает процесс, но не забывайте хэшировать пароль через `htpasswd` для basicAuth.
