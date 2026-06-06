# Использование Secret в Pod

## Определения

**Использование секретов** — процесс предоставления конфиденциальных данных (паролей, ключей, токенов) контейнерам внутри пода.

Kubernetes поддерживает три основных способа передачи секретов в приложение:
1.  **Переменные окружения** — инъекция значений напрямую в процесс.
2.  **Монтирование как Volume** — предоставление секретов в виде файлов в оперативной памяти (tmpfs).
3.  **Projected Volume** — агрегация секретов вместе с другими источниками (ConfigMap, токенами) в одну директорию.

> О создании секретов см. [Создание Secret](creating_secrets.md). О принципах безопасности см. [Безопасность Secret](security.md).

## Основные концепции

### Сравнение методов передачи

| Характеристика | Переменные окружения | Монтирование (Volume) | Projected Volume |
| :--- | :--- | :--- | :--- |
| **Автообновление** | **Нет** (нужен рестарт) | **Да** (с задержкой) | **Да** (с задержкой) |
| **Безопасность** | Низкая (видны в логах, `/proc`) | Высокая (в RAM/tmpfs) | Высокая |
| **Область применения** | Простые флаги, статичные данные | Файлы конфигурации, ключи | Комплексные конфигурации |
| **Обновление в приложении** | Требует перезапуска пода | Требует перечитывания файлов | Требует перечитывания файлов |

### Особенности обновления

При обновлении объекта `Secret` в Kubernetes:
*   **Переменные окружения:** Значение внутри контейнера **не меняется** до полного перезапуска пода.
*   **Volumes:** `kubelet` обновляет файлы в томе автоматически. Время обновления зависит от интервала синхронизации `kubelet` (по умолчанию до 1 минуты) и TTL кэша секретов в API-сервере.
*   **Важно:** Если приложение не умеет перечитывать файлы (например, через механизмы `inotify`), оно продолжит использовать старые данные даже после обновления файлов в томе.

## Практические сценарии

### Использование как переменные окружения

Поддерживается передача конкретных ключей (`secretKeyRef`) или всех ключей секрета разом (`envFrom`).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: env-secret-pod
spec:
  containers:
  - name: app
    image: nginx
    env:
      # Передача конкретного ключа
      - name: DB_PASSWORD
        valueFrom:
          secretKeyRef:
            name: db-credentials
            key: password
    envFrom:
      # Инъекция всех ключей из секрета как переменных окружения
      - secretRef:
          name: api-keys
```

### Монтирование секретов как тома (Volume)

Это **рекомендуемый способ** для обеспечения безопасности и поддержки динамического обновления.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: volume-secret-pod
spec:
  containers:
  - name: app
    image: redis
    volumeMounts:
    - name: cert-vol
      mountPath: "/etc/tls"
      readOnly: true
  volumes:
  - name: cert-vol
    secret:
      secretName: tls-certs
      defaultMode: 0400 # Ограничение прав доступа (только чтение владельцем)
      items:
      - key: tls.crt
        path: server.crt # Ключ 'tls.crt' будет доступен как файл 'server.crt'
```

### Группировка через Projected Volume

Используется для объединения данных из разных объектов (например, секретов и конфиг-карт) в одну директорию.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: projected-pod
spec:
  containers:
  - name: app
    image: alpine
    volumeMounts:
    - name: all-in-one
      mountPath: "/app/config"
  volumes:
  - name: all-in-one
    projected:
      sources:
      - secret:
          name: user-pass
      - configMap:
          name: app-settings
```

Подробнее: [Projected Volume в Pod](../Pod/volume_types/projected_volumes.md).

### Секреты ServiceAccount

Kubernetes автоматически монтирует токен текущего ServiceAccount в каждый под, если это не отключено явно.

*   **Путь монтирования:** `/var/run/secrets/kubernetes.io/serviceaccount`
*   **Содержимое:** `ca.crt`, `namespace`, `token`.

Для отключения автоматического монтирования используйте `automountServiceAccountToken: false`.

## Дополнительная информация

### Использование initContainers для подготовки секретов

В сложных сценариях, когда приложению требуется специфический формат файла или подстановка значений в шаблон, используется паттерн `initContainer` + `emptyDir`.

Подробнее: [Управление секретами приложений (initContainers)](../../Security/application_secrets_management.md).

### Связанные темы

[Основы Secret](secrets_basics.md), [Создание Secret](creating_secrets.md), [Безопасность Secret](security.md), [Внешние менеджеры](external_managers.md), [Projected Volume](../Pod/volume_types/projected_volumes.md), [RBAC](../../Security/rbac/rbac_overview.md).
