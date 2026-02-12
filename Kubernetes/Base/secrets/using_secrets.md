# Использование Secret в Pod'ах

## Как переменные окружения (`env`, `envFrom`)

Удобно для простых значений, но менее безопасно.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app-pod
spec:
  containers:
    - name: my-app
      image: my-app-image
      env:
        - name: DATABASE_PASSWORD
          valueFrom:
            secretKeyRef:
              name: db-cred # Имя секрета
              key: password     # Ключ в секрете
              optional: false # Под должен упасть, если секрета нет
      envFrom:
        - secretRef:
            name: db-cred
            optional: true # Под не упадет, если секрета нет
  automountServiceAccountToken: false
```

**Важно:** Переменные окружения **не обновляются автоматически** после старта пода.

## Как файлы в томе (`volume`)

Это более безопасный и гибкий способ. Секреты монтируются как файлы в read-only `tmpfs` том (в памяти).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app-pod
spec:
  containers:
    - name: my-app
      image: my-app-image
      volumeMounts:
        - name: secret-volume
          mountPath: "/etc/secrets"
          readOnly: true
  volumes:
    - name: secret-volume
      secret:
        secretName: db-cred
        defaultMode: 0400 # Права на файлы (только чтение)
        items:
          - key: username
            path: db_user.txt # ключ 'username' будет в файле 'db_user.txt'
```

*   **Обновление:** Файлы в томе **обновляются автоматически** (с задержкой до минуты)
*   **Безопасность:** Чтение из файла предпочтительнее, чем из переменных окружения

## Как `projected` том

Позволяет объединить несколько источников (Secrets, ConfigMaps, DownwardAPI) в одну директорию.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-projected
spec:
  containers:
  - name: app
    image: nginx
    volumeMounts:
    - name: all-in-one
      mountPath: /etc/app
      readOnly: true
  volumes:
  - name: all-in-one
    projected:
      sources:
      - secret:
          name: db-cred
          items:
            - key: username
              path: credentials/user
      - configMap:
          name: app-config
          items:
            - key: config.yaml
              path: settings/app.conf
```
