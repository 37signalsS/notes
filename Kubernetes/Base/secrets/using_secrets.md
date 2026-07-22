# Использование Secret в Pod

## Определения

**Использование секретов** — процесс предоставления конфиденциальных данных (паролей, ключей, токенов) контейнерам внутри Pod.

Kubernetes поддерживает несколько способов передачи секретов в приложение:

1.  **Переменные окружения** — инъекция значений напрямую в процесс приложения.
2.  **Монтирование как Volume** — предоставление секретов в виде файлов во временной файловой системе (tmpfs).
3.  **Projected Volume** — агрегация секретов вместе с другими источниками (ConfigMap, токены ServiceAccount) в одну директорию.
4.  **imagePullSecrets** — использование учетных данных для аутентификации в приватных реестрах образов (Container Registry).

О создании секретов см. [Создание Secret](creating_secrets.md). О принципах безопасности см. [Безопасность Secret](security.md).

## Основные концепции

### Сравнение методов передачи

| Характеристика | Переменные окружения | Монтирование (Volume) | Projected Volume |
| :--- | :--- | :--- | :--- |
| **Автообновление** | **Нет** (требуется рестарт Pod) | **Да** (через симлинки) | **Да** |
| **Безопасность** | Низкая (видны в логах, `/proc`, `describe`) | Высокая (в RAM/tmpfs) | Высокая |
| **Область применения** | Статичные данные, флаги | Ключи, сертификаты, файлы конфигурации | Сложные наборы данных |
| **Обновление в приложении** | Только при перезапуске | Требует перечитывания файлов (inotify) | Требует перечитывания файлов |

### Механика обновления монтируемых секретов

При обновлении объекта `Secret` в API Kubernetes:

1.  **Kubelet** отслеживает изменения и обновляет содержимое тома.
2.  Обновление происходит атомарно: создается новая директория с данными, и симлинк `..data` переключается на неё.
3.  **Задержка:** обновление может занять до 1 минуты (зависит от настроек `syncFrequency` и `max-per-pod-resync-period` kubelet, а также TTL кэша секретов).
4.  **Ограничение:** секреты, смонтированные с использованием `subPath`, **не обновляются** автоматически.

### Неизменяемые секреты (Immutable)

Если секрет помечен как `immutable: true`, kubelet полностью прекращает отслеживание его изменений. Это снижает нагрузку на API-сервер и гарантирует, что данные внутри Pod не изменятся до его удаления.

## Практические сценарии

### Использование переменных окружения

Можно передать конкретный ключ (`secretKeyRef`) или весь набор данных (`envFrom`).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: env-secret-pod
spec:
  containers:
  - name: app
    image: nginx:1.25
    env:
      - name: DB_PASSWORD
        valueFrom:
          secretKeyRef:
            name: db-credentials
            key: password
            optional: false # Pod не запустится, если секрета или ключа нет
    envFrom:
      - secretRef:
          name: api-keys
```

### Монтирование секретов как тома (Volume)

Рекомендуемый способ для секретов, требующих ротации без перезапуска Pod.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: volume-secret-pod
spec:
  containers:
  - name: app
    image: redis:7.2
    volumeMounts:
    - name: cert-vol
      mountPath: "/etc/tls"
      readOnly: true
  volumes:
  - name: cert-vol
    secret:
      secretName: tls-certs
      defaultMode: 0400 # Права доступа -r--------
      items:
      - key: tls.crt
        path: server.crt # Маппинг ключа в конкретное имя файла
```

### Использование subPath

Позволяет смонтировать конкретный файл из секрета в существующую директорию, не скрывая остальные файлы в ней.
**Внимание:** Секреты, смонтированные через `subPath`, не получают автоматических обновлений при изменении объекта Secret.

```yaml
volumeMounts:
- name: config-vol
  mountPath: /etc/nginx/conf.d/proxy.conf
  subPath: proxy.conf
```

### Аутентификация в Container Registry (imagePullSecrets)

Используется для скачивания образов из приватных репозиториев.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: private-image-pod
spec:
  imagePullSecrets:
  - name: my-registry-key
  containers:
  - name: app
    image: private-repo.com/my-app:v1
```

### Токены ServiceAccount

Начиная с Kubernetes 1.22+, рекомендуется использовать **Bound Service Account Tokens** через механизмы Projected Volume вместо старых секретов SA.

```yaml
volumes:
- name: sa-token
  projected:
    sources:
    - serviceAccountToken:
        audience: my-api
        expirationSeconds: 3600
        path: token
```

Автоматическое монтирование стандартного токена можно отключить: `automountServiceAccountToken: false`.

## Дополнительная информация

### Проверка монтирования

Чтобы убедиться, что секрет смонтирован в tmpfs (оперативную память), выполните команду:
`kubectl exec <pod-name> -- mount | grep /etc/secrets`
Результат должен содержать `tmpfs`.

### Обработка отсутствующих секретов

С помощью параметра `optional: true` можно разрешить запуск Pod даже если секрет еще не создан. Приложение должно уметь обрабатывать отсутствие соответствующих файлов или переменных.

### Смотрите также

- [Основы Secret](secrets_basics.md)
- [Создание Secret](creating_secrets.md)
- [Безопасность Secret](security.md)
- [Projected Volume](../Pod/volume_types/projected_volumes.md)
- [Управление секретами приложений (initContainers)](../../Security/application_secrets_management.md)
