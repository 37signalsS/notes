# Использование Secret в Pod'ах

## Определения

Secret в подах может использоваться тремя способами: переменные окружения, монтирование как том, projected том.

> О создании Secret см. [Создание Secret](creating_secrets.md). О безопасности см. [Безопасность Secret](security.md).

## Основные концепции

### Механизмы использования

1. **Переменные окружения (`env`, `envFrom`)** — значения инжектируются в контейнер при старте
2. **Том (`volume`)** — Secret монтируется как файлы в tmpfs (RAM)
3. **Projected том** — объединение нескольких источников (Secret, ConfigMap, DownwardAPI, ServiceAccountToken)

### Сравнение методов

| Метод | Обновление | Безопасность | Использование |
| :--- | :--- | :--- | :--- |
| **`env`** | **Не обновляется** (требует перезапуска пода) | Низкая (видны в `/proc` и логах) | Простые флаги, нечасто меняющиеся значения |
| **`volume`** | **Обновляется автоматически** (с задержкой) | Высокая (монтируется в `tmpfs`) | **Рекомендуемый способ** для конфигураций и учетных данных |
| **`projected`** | Обновляется автоматически | Высокая | Комбинирование нескольких источников в одну директорию |

> **Важно:** Для динамического обновления Secret через volume приложение должно самостоятельно перечитывать файлы. kubelet обновляет тома с задержкой до 1 минуты.

## Практические сценарии

### Как переменные окружения (`env`, `envFrom`)

Это удобный способ для передачи простых строковых значений, но он **менее безопасен** и **статичен**.

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
        # 1. Передать значение одного конкретного ключа
        - name: DATABASE_PASSWORD
          valueFrom:
            secretKeyRef:
              name: db-cred      # Имя секрета
              key: password     # Ключ в секрете
              optional: false   # Под упадет, если секрет или ключ не найдены
      envFrom:
        # 2. Передать все ключи из секрета как переменные окружения
        - secretRef:
            name: db-cred
            optional: true # Под не упадет, если секрета нет
  automountServiceAccountToken: false
```

> **Важно:** Переменные окружения считываются **один раз при старте контейнера** и **никогда не обновляются автоматически**. Для применения изменений в `Secret` требуется перезапуск пода.

### Как файлы в томе (`volume`)

Это **рекомендуемый и более безопасный** способ. Секреты монтируются как файлы в `tmpfs` (файловую систему в оперативной памяти), что предотвращает их запись на диск узла.

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
        defaultMode: 0400 # Права на файлы (только чтение для владельца)
        items:
          - key: username
            path: db_user.txt # Ключ 'username' будет в файле 'db_user.txt'
```

* **Динамическое обновление:** Смонтированные файлы **обновляются автоматически** при изменении `Secret`. `kubelet` периодически проверяет секреты и обновляет содержимое тома. Этот процесс может занимать до минуты. Приложение должно уметь самостоятельно перечитывать эти файлы, чтобы подхватить изменения.
* **Безопасность:** Предпочтительнее переменных окружения, так как секреты не "светятся" в переменных окружения процесса.
* **Гибкость:** С помощью `items` можно монтировать только нужные ключи и давать им другие имена в файловой системе.

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

> **Подробнее:** [Projected Volume в Pod Volumes](../Pod/volume_types/projected_volumes.md) — полное описание всех источников, включая serviceAccountToken, clusterTrustBundle и podCertificate.

### Secret Data Mount (serviceAccount)

Автоматическое монтирование токена и ca.crt из ServiceAccount:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app-pod
spec:
  serviceAccountName: my-sa
  containers:
  - name: my-app
    image: my-app-image
    volumeMounts:
    - name: kube-api-access
      mountPath: /var/run/secrets/kubernetes.io/serviceaccount
      readOnly: true
```

При создании ServiceAccount автоматически создаётся:

* `kubernetes.io/serviceaccount/namespace` — namespace
* `kubernetes.io/serviceaccount/token` — JWT-токен
* `kubernetes.io/serviceaccount/ca.crt` — CA сертификат для проверки API

> **Кастомизация токена:** Для создания токена с измененными параметрами (срок действия, аудитория) используйте [Projected Volume с serviceAccountToken](../Pod/volume_types/projected_volumes.md).

## Дополнительная информация

### Связанные темы

[Создание Secret](creating_secrets.md), [Основы Secret](secrets_basics.md), [Безопасность Secret](security.md), [Внешние менеджеры](external_managers.md), [Projected Volume](../Pod/volume_types/projected_volumes.md).
