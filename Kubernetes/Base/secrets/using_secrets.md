# Использование Secret в Pod'ах

## Определения

Secret в подах может использоваться тремя способами: переменные окружения, монтирование как том, projected том.

> О создании Secret см. [Создание Secret](creating_secrets.md). О безопасности см. [Безопасность Secret](security.md).

## Практические сценарии

### Переменные окружения (`env`, `envFrom`)

Удобно для простых значений, но менее безопасно:

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

> **Важно:** Переменные окружения **не обновляются автоматически** после старта пода.

### Монтирование как том (`volume`)

Более безопасный способ. Секреты монтируются как файлы в read-only tmpfs (в памяти):

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

- Файлы **обновляются автоматически** (задержка до минуты)
- Предпочтительнее переменных окружения

### Projected том

Объединяет несколько источников (Secrets, ConfigMaps, DownwardAPI) в одну директорию:

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

## Дополнительная информация

### Сравнение методов

| Метод | Обновление | Безопасность | Использование |
| :--- | :--- | :--- | :--- |
| env | После перезапуска пода | Низкая (видны в /proc) | Быстрые значения |
| volume | Автоматически (до 1 мин) | Высокая (tmpfs) | Рекомендуется |
| projected | Автоматически | Высокая | Комбинирование источников |

### Связанные темы

- [Создание Secret](creating_secrets.md)
- [Основы Secret](secrets_basics.md)
- [Безопасность Secret](security.md)
- [Внешние менеджеры](external_managers.md)
