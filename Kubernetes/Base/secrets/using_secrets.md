# Использование Secret в Pod

## Определения

**Использование секретов** — процесс предоставления конфиденциальных данных (паролей, ключей, токенов) контейнерам внутри Pod для обеспечения их работы в изолированной среде.

Kubernetes поддерживает несколько способов передачи секретов в приложение:

1.  **Переменные окружения (Environment Variables)** — инъекция значений напрямую в процесс приложения.
2.  **Монтирование как тома (Volumes)** — предоставление секретов в виде файлов во временной файловой системе (`tmpfs`).
3.  **Проецируемые тома (Projected Volumes)** — агрегация секретов вместе с другими источниками (ConfigMap, токены ServiceAccount) в одну директорию.
4.  **Секреты для скачивания образов (imagePullSecrets)** — использование учетных данных для аутентификации в приватных реестрах (Container Registry).

О создании секретов см. [Создание Secret](creating_secrets.md). О принципах безопасности см. [Безопасность Secret](security.md).

## Основные концепции

### Сравнение методов передачи данных

| Характеристика | Переменные окружения | Монтирование (Volume) | Projected Volume |
| :--- | :--- | :--- | :--- |
| **Автообновление** | **Нет** (требуется рестарт Pod) | **Да** (через атомарные симлинки) | **Да** |
| **Безопасность** | Низкая (видны в `/proc`, логах, `describe`) | Высокая (в RAM/tmpfs, без записи на диск) | Высокая |
| **Область применения** | Флаги, простые пароли, DB_URL | Ключи, TLS-сертификаты, конфигурации | Агрегированные наборы данных |
| **Обновление в приложении** | Только при перезапуске | Требует поддержки перечитывания (inotify) | Требует поддержки перечитывания |

### Механика обновления монтируемых секретов

При обновлении объекта `Secret` в API Kubernetes:

1.  **Kubelet** отслеживает изменения и обновляет содержимое тома.
2.  Обновление происходит атомарно: создается новая директория с меткой времени, и симлинк `..data` переключается на неё.
3.  **Задержка:** обновление может занять до 1 минуты. Это сумма TTL кэша секретов в kubelet и времени цикла синхронизации.tomов (`syncFrequency`).
4.  **Ограничение `subPath`:** секреты, смонтированные с использованием `subPath`, **не обновляются** автоматически. Файл остается в том состоянии, в котором он был в момент создания Pod. Это создает риск использования устаревших учетных данных.

### Неизменяемые секреты (Immutable Secrets)

Поле `immutable: true` в манифесте Secret отключает отслеживание изменений kubelet'ом. Kubelet не будет обновлять содержимое тома даже после изменения объекта Secret в API.

**Когда использовать:**
- Секреты, которые не предполагается менять после создания (сертификаты, статические ключи).
- Защита от случайной перезаписи в CI/CD пайплайнах.
- Снижение нагрузки на API server в кластерах с большим количеством Pod (kubelet не опрашивает неизменяемые секреты).

**Ограничение:** Для обновления неизменяемого секрета необходимо удалить старый Pod и создать новый со ссылкой на новый объект Secret.

### Права доступа и безопасность томов

По умолчанию секреты монтируются с правами `0644` и принадлежат пользователю `root`.

*   **defaultMode:** Позволяет задать права доступа для всех файлов в томе (например, `0400` для приватных ключей). Указывается в восьмеричном формате (например, `0400`) или десятичном (`256`).
*   **fsGroup:** Если в `securityContext` Pod задан `fsGroup`, Kubernetes изменит группу владельца тома секрета, чтобы приложение (запущенное от другого пользователя в той же группе) могло читать файлы. Это критично для `non-root` контейнеров.
*   **fsGroupChangePolicy:** Поле (Kubernetes 1.23+) определяет, как kubelet устанавливает ownership. Значение `OnRootMismatch` ускоряет монтирование, пропуская рекурсивное изменение прав, если корневая директория уже имеет правильного владельца.

## Практические сценарии

### Использование переменных окружения

Использование `secretKeyRef` для конкретных ключей или `envFrom` для массового импорта всех ключей секрета в переменные окружения.

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
            optional: false # Pod перейдет в CreateContainerConfigError, если секрета нет
    envFrom:
      - secretRef:
          name: api-keys
```

### Монтирование Secret как Volume

Рекомендуемый метод для TLS-сертификатов и сложных конфигураций, требующих ротации.

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
      defaultMode: 0400 # Только чтение владельцем
      items:
      - key: tls.crt
        path: server.crt # Маппинг ключа в конкретное имя файла
```

### Агрегация нескольких секретов через Projected Volume

Проектируемые тома позволяют объединить секреты, ConfigMap и токены ServiceAccount в одну директорию. Это удобно, когда приложению нужно читать данные из разных источников по единому интерфейсу.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: projected-secret-pod
spec:
  containers:
  - name: app
    image: nginx:1.25
    volumeMounts:
    - name: combined-vol
      mountPath: "/etc/config"
      readOnly: true
  volumes:
  - name: combined-vol
    projected:
      sources:
      - secret:
          name: db-credentials
          items:
          - key: password
            path: db-password
      - secret:
          name: api-key
          items:
          - key: key
            path: api-key
      - configMap:
          name: app-config
          items:
          - key: config.yaml
            path: config.yaml
```

### Использование imagePullSecrets

Для скачивания образов из приватных реестров (например, Harbor, Docker Hub).

**Создание секрета через CLI:**

```bash
kubectl create secret docker-registry registry-creds \
  --docker-server=my-private-reg.io \
  --docker-username=deployer \
  --docker-password='S3cur3P@ss' \
  --docker-email=deployer@example.com \
  -n my-namespace
```

**Манифест Pod:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: private-image-pod
spec:
  imagePullSecrets:
  - name: registry-creds
  containers:
  - name: app
    image: my-private-reg.io/app:v1
```

Секрет `registry-creds` должен иметь тип `kubernetes.io/dockerconfigjson`. Структура данных внутри — зашифрованный Base64 JSON с ключами `auths`.

**Автоматическая инъекция в Namespace (DaemonSet-паттерн):**

Чтобы не указывать `imagePullSecrets` в каждом Pod, можно автоматически подставлять их для всех Pod в Namespace через patch ServiceAccount:

```bash
kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "registry-creds"}]}'
```

**Валидация доступа к реестру:**

```bash
# Проверка, что Secret создан корректно
kubectl get secret registry-creds -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .

# Проверка доступа из Pod
kubectl run debug --image=busybox --rm -it --restart=Never -- \
  wget -qO- --header="Authorization: Bearer $(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
  https://kubernetes.default.svc/apis/v1/namespaces/default/pods
```

### Использование токенов ServiceAccount через Projected Volumes

Современный способ доступа к API Kubernetes (взамен устаревших статических секретов SA).

```yaml
volumes:
- name: token-vol
  projected:
    sources:
    - serviceAccountToken:
        audience: api-server
        expirationSeconds: 3600
        path: sa-token
```

## Диагностика и типичные ошибки

### Ошибка CreateContainerConfigError

Возникает, если Pod ссылается на секрет, который не существует или к которому нет доступа (RBAC).
*   **Диагностика:** `kubectl describe pod <name>` покажет конкретную ошибку в событиях (Events).
*   **Решение:** Проверьте наличие секрета через `kubectl get secrets` в нужном Namespace.

### Секрет не обновляется в Pod

Если данные в секрете изменились, но в контейнере видны старые значения:
1.  Убедитесь, что не используется `subPath`.
2.  Проверьте `immutable: true` в манифесте секрета — такие секреты не отслеживаются kubelet.
3.  Подождите цикл синхронизации (до 1 минуты).

### Ошибка ImagePullBackOff из-за imagePullSecrets

Причина — неверные учетные данные или отсутствие секрета в Pod:
```bash
# Проверка событий Pod
kubectl describe pod <name> | grep -A5 "Events"

# Проверка наличия secrets в ServiceAccount
kubectl get serviceaccount default -o yaml | grep -A3 imagePullSecrets

# Проверка доступности секрета
kubectl get secret registry-creds -o yaml
```

### Проверка прав доступа к Secret (RBAC)

```bash
# Проверка, может ли ServiceAccount читать секрет
kubectl auth can-i get secret/db-credentials --namespace=my-namespace --as=system:serviceaccount:my-namespace:my-sa

# Просмотр всех доступных секретов для ServiceAccount
kubectl auth can-i list secrets --namespace=my-namespace --as=system:serviceaccount:my-namespace:my-sa
```

### Команда для проверки типа монтирования

Чтобы убедиться, что секрет находится в оперативной памяти (tmpfs):
```bash
kubectl exec <pod-name> -- mount | grep /etc/secrets
# → result: tmpfs on /etc/secrets type tmpfs (rw,relatime)
```

### Проверка содержимого смонтированного секрета

```bash
# Просмотр файлов в директории секрета
kubectl exec <pod-name> -- ls -la /etc/secrets/

# Просмотр содержимого конкретного файла
kubectl exec <pod-name> -- cat /etc/secrets/password

# Проверка прав доступа к файлам
kubectl exec <pod-name> -- stat -c '%a %U %G' /etc/secrets/*
```

## Best Practices

### Безопасность

1.  **Volume предпочтительнее env:** монтируйте секреты как файлы (tmpfs) вместо переменных окружения. Переменные окружения видны через `kubectl describe pod`, в логах приложения и дампах памяти (`/proc/<pid>/environ`).
2.  **Ограничивайте права доступа:** используйте `defaultMode: 0400` или `0600` для файлов секретов. Не используйте `0644` (доступно группе) или `0777` (доступно всем).
3.  **Используйте fsGroup:** для non-root контейнеров всегда указывайте `fsGroup` в `securityContext`, иначе приложение не сможет прочитать смонтированные файлы.
4.  ** readOnly:** всегда монтируйте секреты с `readOnly: true`, чтобы предотвратить случайную модификацию.
5.  **Неизменяемые секреты:** используйте `immutable: true` для секретов, которые не меняются после создания. Это снижает нагрузку на API server и исключает случайную перезапись.

### Операционная надежность

6.  **Избегайте `subPath`:** секреты с `subPath` не обновляются автоматически. Используйте полное монтирование тома с `items` для маппинга ключей в файлы.
7.  **Валидация при старте:** проверяйте доступность секретов в `initContainer` или через startup probe перед запуском основного приложения.
8.  **Автоматическая инъекция imagePullSecrets:** патчите ServiceAccount в Namespace вместо указания `imagePullSecrets` в каждом Pod манифесте.
9.  **Одна ответственность:** не агрегируйте более 3–4 секретов в один Projected Volume. Слишком большие тома усложняют ротацию и диагностику.

## Дополнительная информация

### Обработка бинарных данных

Секреты могут содержать бинарные файлы (например, JKS-хранилища, сертификаты в DER-формате). При монтировании в Volume они восстанавливаются в исходном бинарном виде из Base64-представления. Будьте осторожны с переменными окружения, так как они могут некорректно обрабатывать нетекстовые символы.

### Смотрите также

- [Создание Secret](creating_secrets.md) — способы формирования объектов.
- [Безопасность Secret](security.md) — методы защиты и KMS.
- [Projected Volume](../Pod/volume_types/projected_volumes.md) — детальное описание проецируемых томов.
- [Внешние менеджеры](external_managers.md) — ESO, CSI Driver, Vault Agent.
- [Helm + секреты](helm_secrets.md) — управление секретами в Helm-чартах.
- [Секреты в StatefulSet](statefulset_secrets.md) — паттерны для баз данных и stateful-приложений.
- [Pod Security Standards и Secret](pod_security_and_secrets.md) — влияние PSA restricted на монтирование секретов.
