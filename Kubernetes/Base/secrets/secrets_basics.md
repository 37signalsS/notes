# Основы Kubernetes Secret

**Актуально для:** Kubernetes 1.30–1.32+ / kubectl 1.30+

## Определения

**Secret (v1/Secret)** — базовый объект API Kubernetes, предназначенный для централизованного хранения и доставки чувствительных данных (паролей, токенов, API-ключей, TLS-сертификатов, файлов конфигурации SSH) в контейнеры Pod без необходимости жесткого внедрения (hardcoding) в образы или манифесты развертывания.

**Base64-кодирование (RFC 4648)** — бинарно-текстовая схема кодирования, применяемая в поле `data` объекта Secret для безопасной передачи произвольных последовательностей байтов через сериализованные текстовые протоколы JSON и YAML.
- **Критическое различие:** Base64 — это **кодирование, а не шифрование**. Любой субъект с правами RBAC на чтение объекта через API (`kubectl get secret -o yaml`) или доступом к etcd может восстановить открытый текст за одну операцию (`base64 -d`).
- Для защиты данных в состоянии покоя на уровне хранилища настраивается **Encryption at Rest** через `EncryptionConfiguration` API Server (см. [Хранение в etcd](etcd_storage.md)).

**stringData** — вспомогательное поле спецификации Secret, предназначенное исключительно для записи (write-only). Принимает незакодированные строки в открытом виде (UTF-8). `kube-apiserver` самостоятельно кодирует значения в Base64 и перемещает их в поле `data`. При получении объекта через API поле `stringData` никогда не возвращается.

**Неизменяемый Secret (Immutable Secret)** — объект Secret со свойством `immutable: true`. После создания API Server запрещает любые модификации полей `data` и `stringData`. Это снимает необходимость непрерывного опроса (watch) со стороны Kubelet и защищает от случайной перезаписи. Свойство необратимо: изменить значение на `false` нельзя — только удалить и создать объект заново.

**Типизация Secret (`type`)** — поле спецификации объекта, определяющее ожидаемый API-сервером формат данных и назначение секрета (например, `Opaque`, `kubernetes.io/tls`, `kubernetes.io/dockerconfigjson`). Для специализированных типов API Server выполняет проверку наличия обязательных ключей при создании и обновлении.

**tmpfs-монтирование** — механизм предоставления данных секрета контейнеру в виде файлов в оперативной памяти хоста (RAM-диск). Предотвращает запись чувствительной информации на физические дисковые накопители рабочих узлов.

---

## Основные концепции

### Архитектура и жизненный цикл Secret

Понимание внутренней механики работы объекта Secret критично для проектирования отказоустойчивой инфраструктуры, отладки сетевых задержек и обеспечения требований информационной безопасности в On-Premise кластерах.

**Конвейер обработки данных от создания до процесса в контейнере:**

```
[ Клиент: kubectl / CI/CD / GitOps ]
              │
              ▼  (1. HTTPS POST /api/v1/namespaces/{ns}/secrets)
     [ kube-apiserver ]
              │
              ├─► Аутентификация и авторизация RBAC (verbs: "create")
              ├─► Admission Plugins (валидация схемы, размера < 1 MiB, типов)
              ├─► Автоматическая конвертация stringData → data (Base64)
              └─► Encryption at Rest (шифрование перед записью, если активно)
              │
              ▼  (2. gRPC Put)
           [ etcd ] (/registry/secrets/{namespace}/{name})
              │
              │  (3. Watch / Get через kube-apiserver)
              ▼
     [ Kubelet на узле ]
              │
              ├─► SecretManager (кэширование в RAM узла)
              ├─► Монтирование тома в tmpfs (/var/lib/kubelet/pods/{uid}/volumes/...)
              └─► Формирование атомарного дерева симлинков (..data -> ..timestamp)
              │
              ▼  (4. Запуск контейнера)
     [ Процесс в Pod ] ──► Чтение из файлов тома или переменных окружения
```

1. **Создание и валидация:**
   Клиент отправляет запрос на `kube-apiserver`. Сервер выполняет аутентификацию, авторизацию через RBAC, пропускает объект через цепочку Admission Webhooks, проверяет валидность Base64 и соответствие ограничению размера объекта (не более **1 MiB**). Поле `stringData` преобразуется в `data`, а само удаляется из манифеста.
2. **Хранение в etcd:**
   Сериализованный Protobuf-объект сохраняется по ключу `/registry/secrets/<namespace>/<name>`. Если включен `EncryptionConfiguration` (провайдеры `kms`, `aescbc`, `secretbox`), данные шифруются перед записью в хранилище. По умолчанию данные сохраняются в Base64 без шифрования.
3. **Доставка на рабочий узел:**
   `kubelet` рабочего узла запрашивает секреты через API Server только для тех Pod'ов, которые назначены на данный узел (принцип Least Privilege на уровне узлов, обеспечиваемый Node Restriction Admission). Секреты кэшируются в оперативной памяти узла модулем `SecretManager`.
4. **Монтирование в файловую систему:**
   При монтировании секрета как тома (`volume`) `kubelet` создает на узле виртуальную файловую систему `tmpfs` в каталоге пода (`/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~secret/<volume-name>`). Это гарантирует, что секреты не попадут на постоянные диски узла и исчезнут при остановке пода или перезагрузке ОС.
5. **Атомарная ротация через симлинки:**
   Файлы внутри тома монтируются через трехуровневую цепочку символических ссылок:
   ```
   /etc/secrets/password -> ..data/password
   ..data -> ..2026_10_17_18_00_00.123456789
   ..2026_10_17_18_00_00.123456789/password
   ```
   При изменении объекта Secret в кластере `kubelet` создает новый каталог с временной меткой, записывает в него новые файлы и атомарно переключает симлинк `..data`. Приложение никогда не увидит частично записанный файл. Задержка обновления в томе составляет от 10 до 60 секунд (зависит от периода синхронизации `kubelet` и TTL кэша).
6. **Особенности передачи через переменные окружения:**
   Если секрет передан через `env` или `envFrom`, значения считываются ядром Linux только в момент вызова системного вызова `execve` при старте контейнера. Изменения в объекте Secret **не передаются** в работающий процесс. Для применения новых значений требуется перезапуск пода (`kubectl rollout restart`).

Подробнее о шифровании хранилища см. [Хранение в etcd](etcd_storage.md). О тонкостях монтирования см. [Использование Secret](using_secrets.md).

### Разделение конфигурации и секретов (Separation of Concerns)

В архитектуре Kubernetes строго разделяются неконфиденциальные параметры приложений и чувствительные данные:

- **ConfigMap:** предназначен для публичных параметров (конфигурационные файлы Nginx, флаги запуска, имена хостов, порты сервисов, уровни логирования). Доступен широкому кругу инженеров и сервисных учетных записей.
- **Secret:** предназначен для паролей, токенов, сертификатов, закрытых ключей. Доступ жестко ограничен политиками RBAC, подлежит шифрованию в etcd и специализированному аудиту.

Такое разделение позволяет независимо версионировать бизнес-конфигурации в Git и централизованно управлять секретами через защищенные каналы без пересборки образов приложений.

### Изоляция на уровне Namespace

Объект `Secret` является ресурсом с областью действия в пределах пространства имен (**Namespaced resource**).

- Pod может монтировать и считывать секреты **только** из того же пространства имен, в котором он запущен. Прямой доступ к секрету из соседнего `namespace` заблокирован на уровне валидации схемы спецификации Pod.
- Для тиражирования одинаковых учетных данных (например, `imagePullSecrets` для доступа к корпоративному Registry) между разными пространствами имен применяются операторы синхронизации или GitOps-инструменты (Kustomize/Helm), а не ручное дублирование.
- Сервисный аккаунт (`ServiceAccount`) также привязан к пространству имен, что обеспечивает строгую границу безопасности между tenant-окружениями или отдельными микросервисами.

### Сравнение Secret и ConfigMap

| Критерий | Secret (`v1/Secret`) | ConfigMap (`v1/ConfigMap`) |
| :--- | :--- | :--- |
| **Основное назначение** | Конфиденциальные данные (пароли, TLS, API-ключи) | Общедоступные конфигурации, флаги, конфиг-файлы |
| **Поля спецификации** | `data` (Base64), `stringData` (Plain text, write-only) | `data` (UTF-8 текст), `binaryData` (Base64) |
| **Шифрование в etcd** | Поддерживается через `EncryptionConfiguration` | По умолчанию хранится открытым текстом |
| **Политика доступа RBAC** | Минимальные права, закрытый `list`/`watch` | Открытый доступ для разработчиков и операторов |
| **Размещение на узле** | `tmpfs` (только оперативная память хоста) | Файловая система узла или `tmpfs` |
| **Максимальный размер** | 1 MiB (жесткий лимит транзакции etcd) | 1 MiB (жесткий лимит транзакции etcd) |
| **Автообновление (Volume)** | Да (с задержкой до 60 секунд через симлинки) | Да (с задержкой до 60 секунд через симлинки) |
| **Автообновление (Env)** | **Нет** (требуется рестарт процесса или пода) | **Нет** (требуется рестарт процесса или пода) |
| **Неизменяемость** | Поддерживается (`immutable: true`) | Поддерживается (`immutable: true`) |

### Поля data и stringData

При манипуляциях с манифестами Secret используются два поля спецификации:

| Параметр | Поле `data` | Поле `stringData` |
| :--- | :--- | :--- |
| **Формат значений** | Обязательно Base64-закодированные строки | Открытый текст UTF-8 |
| **Режим доступа** | Чтение и запись (Read / Write) | Только запись (Write-Only) |
| **Отображение в API** | Всегда возвращается при `kubectl get secret -o yaml` | Никогда не возвращается API-сервером |
| **Основное применение** | Автоматизация, CI/CD, бинарные данные (сертификаты, JKS) | Ручное создание манифестов перед шифрованием через SOPS |

**Правила взаимодействия полей:**
1. **Приоритет `stringData`:** если манифест содержит один и тот же ключ одновременно в секциях `data` и `stringData`, значение из `stringData` имеет абсолютный приоритет и перезаписывает значение в `data`.
2. **Преобразование:** `kube-apiserver` при получении запроса выполняет Base64-кодирование каждой строки из `stringData`, перемещает пары ключ-значение в `data` и удаляет `stringData` из сохраняемого в etcd объекта.
3. **Ловушка с переносом строки (`\n`, `0x0A`):**
   При ручном кодировании в Linux CLI утилита `echo` по умолчанию добавляет невидимый байт перевода строки. Если этот пароль попадет в секрет, аутентификация в базе данных или API завершится ошибкой:
   ```bash
   # ОШИБКА: в секрет попадет 'my-password\n' (лишний символ 0x0A)
   echo "my-password" | base64
   # → bXktcGFzc3dvcmQK

   # ПРАВИЛЬНО: флаг -n подавляет перевод строки
   echo -n "my-password" | base64
   # → bXktcGFzc3dvcmQ=
   ```
4. **Проверка существующего секрета на скрытые символы:**
   ```bash
   kubectl get secret db-credentials -o jsonpath='{.data.password}' | base64 -d | cat -A
   # → my-password$   (символ $ означает конец строки без лишнего \n; если видно ^M$ или перенос — есть дефект)
   ```

### Неизменяемые секреты (Immutable Secrets)

Функционал перешел в статус GA (General Availability) в Kubernetes 1.21+. Спецификация позволяет зафиксировать содержимое секрета:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: static-root-ca
  namespace: production
immutable: true
data:
  ca.crt: LS0tLS1CRUdJTi...
```

**Преимущества для SRE и системных администраторов:**
- **Снижение нагрузки на Control Plane:** `kubelet` не устанавливает сессию отслеживания (`watch`) на неизменяемые секреты. В кластерах с тысячами подов это радикально снижает потребление CPU и оперативной памяти `kube-apiserver`, а также снижает частоту сетевых вызовов.
- **Защита от случайных мутаций:** предотвращаются инциденты, вызванные ошибочным повторным запуском `kubectl apply` или сбоем в CI/CD пайплайне.
- **Ограничения:** изменить объект с `immutable: true` невозможно. При попытке изменения API Server возвращает ошибку `Invalid value: true: field is immutable`. Для обновления секрета требуется либо удалить и создать его заново, либо выпустить новый версионированный секрет (например, `static-root-ca-v2`) и выполнить Rolling Update приложений.

### Типы Secret и встроенная валидация API

Kubernetes поддерживает типизацию секретов через поле `type`. Тип определяет правила валидации структуры ключей:

| Тип (`type`) | Назначение | Обязательные ключи в `data` | Особенности валидации API |
| :--- | :--- | :--- | :--- |
| **`Opaque`** | Универсальный тип по умолчанию | Произвольные ключи | Валидация содержимого отсутствует; любые пары ключ-значение. |
| **`kubernetes.io/tls`** | Сертификаты и закрытые ключи TLS | `tls.crt`, `tls.key` | Валидация формата X.509: закрытый ключ должен соответствовать сертификату и не должен иметь парольной фразы. |
| **`kubernetes.io/dockerconfigjson`** | Аутентификация в приватных Registry | `.dockerconfigjson` | Содержимое должно быть валидным JSON формата конфигурации Docker CLI (`auths`). |
| **`kubernetes.io/basic-auth`** | Базовая HTTP-аутентификация | `username`, `password` | API Server требует наличия хотя бы одного из ключей при сохранении. |
| **`kubernetes.io/ssh-auth`** | Закрытые ключи SSH | `ssh-privatekey` | Обязателен ключ `ssh-privatekey`; опционально принимается `known_hosts`. |
| **`kubernetes.io/service-account-token`** | Статический токен ServiceAccount | `token` (генерируется API) | Требует аннотации `kubernetes.io/service-account.name`. Применяется только для внешних систем (Prometheus, внешние CI-раннеры). |
| **`bootstrap.kubernetes.io/token`** | Токены присоединения узлов kubeadm | `token-id`, `token-secret` | Имя объекта строго `bootstrap-token-<token-id>`; валидируются форматы ID (`[a-z0-9]{6}`) и секрета (`[a-z0-9]{16}`). |

> **Важное ограничение CLI:** утилита `kubectl create secret` предоставляет встроенные подкоманды **только** для трех типов: `generic` (создает `Opaque`), `tls` и `docker-registry`. Подкоманд вида `kubectl create secret ssh-auth` или `basic-auth` **не существует**. Для их создания используется `kubectl create secret generic --type=...` либо декларативные YAML-манифесты (см. [Создание Secret](creating_secrets.md)).

#### Эволюция токенов ServiceAccount (1.24+ и 1.31+ GA)
1. **Bound Service Account Tokens (по умолчанию с Kubernetes 1.24+):** автоматическое создание бессрочных секретов `kubernetes.io/service-account-token` для каждого ServiceAccount прекращено. Поды получают временные JWT-токены с ограничением по времени жизни (TTL) и аудитории (`audience`), монтируемые через `projected volume` напрямую от TokenRequest API без создания объектов Secret в etcd.
2. **Очистка устаревших токенов (механизм `LegacyServiceAccountTokenCleanUp`, статус GA с 1.31+):** контроллер `token-cleaner` в `kube-controller-manager` сканирует автоматически созданные в прошлых версиях k8s секреты SA. Токены, не использовавшиеся более 365 дней, помечаются меткой `kubernetes.io/legacy-token-invalid-since` и блокируются. Вручную созданные администратором секреты с явной аннотацией `kubernetes.io/service-account.name` очистке не подлежат.

### Метки и аннотации (Labels & Annotations)

Секреты поддерживают стандартную систему метаданных Kubernetes:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-credentials
  namespace: production
  labels:
    app.kubernetes.io/name: postgresql
    app.kubernetes.io/part-of: billing-system
    environment: production
  annotations:
    description: "Учетные данные кластера PostgreSQL для сервиса биллинга"
    reloader.stakater.com/match: "true"
```

**Практическое применение в эксплуатации:**
- **Фильтрация и инспекция:**
  ```bash
  kubectl get secrets -n production -l app.kubernetes.io/name=postgresql
  # → NAME                   TYPE     DATA   AGE
  # → postgres-credentials   Opaque   2      14d
  ```
- **Интеграция с контроллерами ротации:** аннотации используются утилитами типа Stakater Reloader для автоматического перезапуска Deployment при обновлении секрета.
- **Ограничение стандартного RBAC:** встроенный механизм RBAC в Kubernetes **не поддерживает** селекторы меток (`labelSelector`) для ограничения прав. Ограничение доступа к конкретным секретам возможно только по полному имени через параметр `resourceNames`. Для фильтрации по меткам применяются Policy Engines (Kyverno, OPA Gatekeeper).

---

## Практические сценарии

### Императивное создание через kubectl

#### Таблица параметров подкоманд `kubectl create secret`

| Параметр / Флаг | Назначение | Пример использования |
| :--- | :--- | :--- |
| `--from-literal=KEY=VALUE` | Создание секрета из пары ключ-значение в строке вызова | `--from-literal=db_user=admin` |
| `--from-file=PATH` | Создание ключа с именем файла и содержимым файла | `--from-file=/etc/ssl/ca.crt` |
| `--from-file=KEY=PATH` | Создание ключа с пользовательским именем из файла | `--from-file=server.key=./priv.key` |
| `--from-file=DIR/` | Создание ключей из всех файлов внутри директории | `--from-file=./configs/` |
| `--from-env-file=PATH` | Загрузка нескольких пар ключ=значение из `.env`-файла | `--from-env-file=.env.production` |
| `--type=TYPE` | Назначение специфического типа (для `generic`) | `--type=kubernetes.io/basic-auth` |
| `--dry-run=client -o yaml` | Вывод сгенерированного манифеста без записи в кластер | `--dry-run=client -o yaml > sec.yaml` |

#### Generic Secret (тип Opaque)
```bash
# Создание из литералов
kubectl create secret generic db-credentials \
  --namespace=production \
  --from-literal=username=dbuser \
  --from-literal=password='P@ssw0rd123!'
# → secret/db-credentials created

# Создание из бинарного файла закрытого ключа
kubectl create secret generic backup-ssh-key \
  --namespace=production \
  --from-file=id_ed25519=/root/.ssh/id_ed25519
# → secret/backup-ssh-key created
```

#### TLS Secret
```bash
kubectl create secret tls ingress-tls \
  --namespace=production \
  --cert=/etc/ssl/certs/site.crt \
  --key=/etc/ssl/private/site.key
# → secret/ingress-tls created
```

#### Docker Registry Secret (учетные данные для скачивания образов)
```bash
kubectl create secret docker-registry private-registry-auth \
  --namespace=production \
  --docker-server=registry.internal.corp \
  --docker-username=robot-deployer \
  --docker-password='RegPassW0rd!' \
  --docker-email=devops@internal.corp
# → secret/private-registry-auth created
```

#### Генерация манифеста (Dry-run) для GitOps-пайплайна
```bash
kubectl create secret generic api-keys \
  --from-literal=token='7f8a9b0c-1234' \
  --dry-run=client -o yaml > api-keys.yaml
# Вывод перенаправляется в файл для последующего шифрования через SOPS
```

### Декларативное создание (YAML-манифесты)

#### Вариант 1: Использование поля stringData (удобно для ручной подготовки)
Позволяет описывать текстовые конфиги и пароли в открытом виде. Kubernetes самостоятельно преобразует их в Base64 при обработке запроса.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-backend-secret
  namespace: production
type: Opaque
stringData:
  DATABASE_URL: "postgresql://app_user:ComplexPass@db.internal:5432/app_db"
  API_SECRET_KEY: "0123456789abcdef0123456789abcdef"
```

Применение манифеста:
```bash
kubectl apply -f app-backend-secret.yaml
# → secret/app-backend-secret created
```

#### Вариант 2: Использование поля data (Base64)
Применяется для бинарных файлов (PKCS#12, JKS, архивы) или в автоматизированных CI/CD пайплайнах:

```bash
# Подготовка закодированных значений без переноса строки
echo -n "admin_user" | base64
# → YWRtaW5fdXNlcg==
echo -n "SuperSecretPass" | base64
# → U3VwZXJTZWNyZXRQYXNz
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-binary-secret
  namespace: production
type: Opaque
data:
  username: YWRtaW5fdXNlcg==
  password: U3VwZXJTZWNyZXRQYXNz
```

### Способы передачи Secret в Pod

Kubernetes предоставляет два основных метода монтирования секрета в контейнер:

#### Способ 1: Монтирование как Volume (Рекомендуемый метод)
Секрет монтируется в изолированную файловую систему `tmpfs`. Поддерживает автоматическую ротацию данных без рестарта пода и обеспечивает максимальную защиту от утечек через системный журнал или дамп окружения.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app-pod
  namespace: production
spec:
  containers:
  - name: backend
    image: nginx:1.27-alpine
    volumeMounts:
    - name: secrets-volume
      mountPath: "/etc/app/secrets"
      readOnly: true
  volumes:
  - name: secrets-volume
    secret:
      secretName: app-backend-secret
      defaultMode: 0400  # Права только на чтение владельцем
```

#### Способ 2: Инъекция через переменные окружения
Значения попадают в переменные окружения контейнера. Просто в реализации, но **не обновляется автоматически** при ротации и может быть раскрыто через отладочные дампы (`/proc/<PID>/environ`) или `kubectl describe pod`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: env-app-pod
  namespace: production
spec:
  containers:
  - name: backend
    image: nginx:1.27-alpine
    env:
    - name: DB_PASS
      valueFrom:
        secretKeyRef:
          name: app-backend-secret
          key: API_SECRET_KEY
          optional: false  # При отсутствии секрета Pod перейдет в статус CreateContainerConfigError
    envFrom:
    - secretRef:
        name: app-backend-secret
```

Подробный разбор Projected Volumes, прав доступа `fsGroup` и нюансов монтирования см. в [Использование Secret](using_secrets.md).

### Управление секретами в GitOps (Kustomize secretGenerator)

При использовании декларативного развертывания через Kustomize применяется директива `secretGenerator`. Kustomize автоматически вычисляет SHA256-хеш содержимого секрета и добавляет его в виде суффикса к имени объекта (например, `app-secrets-7bf8k9h5d2`):

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

secretGenerator:
- name: app-secrets
  envs:
  - .env.production
  options:
    disableNameSuffixHash: false
```

**Преимущество для SRE:** при изменении файла `.env.production` генерируется новое уникальное имя секрета. Kustomize автоматически обновляет ссылки в манифестах `Deployment`, что инициирует корректный **Rolling Update** подов без необходимости ручного рестарта.

---

## Операции и команды

Сводная таблица повседневных команд управления объектами `Secret` для системного администратора:

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Список секретов** | `kubectl get secrets -n <ns>` | Просмотр всех секретов в пространстве имен |
| **Фильтрация по типу** | `kubectl get secrets --field-selector type=kubernetes.io/tls -n <ns>` | Поиск только TLS-сертификатов |
| **Инспекция структуры** | `kubectl describe secret <name> -n <ns>` | Просмотр имен ключей и размера без раскрытия значений |
| **Декодирование ключа** | `kubectl get secret <name> -n <ns> -o jsonpath='{.data.<key>}' \| base64 -d` | Быстрое извлечение значения конкретного ключа |
| **Экспорт всех ключей** | `kubectl get secret <name> -n <ns> -o json \| jq -r '.data \| to_entries[] \| "\(.key) \(.value)"'` | Пакетный экспорт ключей для проверки |
| **Принудительный рестарт**| `kubectl rollout restart deployment/<deploy> -n <ns>` | Применение обновленных env-секретов в подах |
| **Проверка прав RBAC** | `kubectl auth can-i get secrets -n <ns> --as=system:serviceaccount:<ns>:<sa>` | Проверка прав сервисного аккаунта на чтение |
| **Удаление секрета** | `kubectl delete secret <name> -n <ns>` | Удаление объекта из кластера |

---

## Диагностика и устранение неисправностей

### Диагностические команды с ожидаемым выводом

#### 1. Проверка наличия и метаданных секрета
```bash
kubectl get secret db-credentials -n production
# → NAME             TYPE     DATA   AGE
# → db-credentials   Opaque   2      3d
```

#### 2. Безопасное извлечение и декодирование конкретного ключа
```bash
kubectl get secret db-credentials -n production -o jsonpath='{.data.password}' | base64 -d
# → P@ssw0rd123!
```

#### 3. Экспорт всех ключей секрета в отдельные файлы (для отладки)
```bash
kubectl get secret db-credentials -n production -o json | \
  jq -r '.data | to_entries[] | "\(.key) \(.value)"' | \
  while read -r key val; do
    echo "$val" | base64 -d > "./debug_${key}"
  done
# → Создаются файлы debug_username, debug_password с декодированным содержимым
```

#### 4. Проверка монтирования tmpfs внутри запущенного Pod
```bash
# Проверка типа смонтированной файловой системы
kubectl exec -n production deploy/my-backend -- mount | grep /etc/app/secrets
# → tmpfs on /etc/app/secrets type tmpfs (ro,relatime,size=1048576k)

# Проверка дерева файлов и прав доступа
kubectl exec -n production deploy/my-backend -- ls -la /etc/app/secrets
# → lrwxrwxrwx 1 root root ..data -> ..2026_10_17_18_00_00.123456789
# → -r-------- 1 root root password -> ..data/password
```

#### 5. Аудит прав RBAC для сервисного аккаунта
```bash
# Проверка доступа к конкретному секрету
kubectl auth can-i get secret/db-credentials \
  --namespace=production \
  --as=system:serviceaccount:production:app-sa
# → yes

# Проверка опасного права на листинг всех секретов пространства имен
kubectl auth can-i list secrets \
  --namespace=production \
  --as=system:serviceaccount:production:app-sa
# → no
```

### Типичные ошибки и методы их устранения

| Сообщение об ошибке / Симптом | Причина сбоя | Метод диагностики | Пошаговое решение |
| :--- | :--- | :--- | :--- |
| `Error: secret "xxx" not found` / статус Pod `CreateContainerConfigError` | Секрет не существует в указанном `namespace` или имя написано с опечаткой. | `kubectl get secrets -n <ns>`<br>`kubectl describe pod <pod> -n <ns>` | 1. Проверьте правильность имени секрета в `spec.volumes` или `spec.containers.env`.<br>2. Убедитесь, что секрет создан в том же пространстве имен, что и Pod. |
| `Error from server (Forbidden): secrets "xxx" is forbidden: User "..." cannot get resource "secrets"` | RBAC блокирует доступ ServiceAccount или пользователя к API секретов. | `kubectl auth can-i get secret/<name> -n <ns> --as=...` | Создайте `Role` с правилом `resources: ["secrets"]`, `verbs: ["get"]` и привяжите через `RoleBinding` к целевому ServiceAccount. |
| `Error from server (RequestEntityTooLarge): ... limit 1048576 bytes` | Размер полезной нагрузки секрета превысил жесткий лимит etcd (**1 MiB**). | `kubectl get secret <name> -o json \| jq '.data \| to_entries[] \| {key: .key, size: (.value \| length)}'` | Вынесите тяжелые бинарные файлы (архивы, образы) в S3/MinIO или постоянные тома (PVC). В секрете храните только ключи доступа к ним. |
| `Secret is invalid: ... required key "tls.key" not found` | Нарушена структура обязательных полей для типизированного секрета. | `kubectl describe secret <name>` | Для `kubernetes.io/tls` обязательно наличие ключей `tls.crt` и `tls.key`. Исправьте манифест или используйте `kubectl create secret tls`. |
| `Secret не обновляется в файловой системе Pod` | Используется параметр `subPath` либо секрет помечен как `immutable: true`. | `kubectl get pod <pod> -o yaml \| grep -i subpath`<br>`kubectl get secret <name> -o yaml \| grep -i immutable` | 1. При `subPath` автообновление заблокировано ядром Linux (bind mount файла) — перейдите на полное монтирование каталога.<br>2. При `immutable: true` поле необратимо — удалите и создайте секрет заново либо выполните ротацию через новый объект и rollout пода. |
| `Permission denied` при попытке приложения прочитать смонтированный секрет | Несовпадение UID/GID процесса в контейнере и прав доступа к файлу тома (по умолчанию `0644 root:root`). | `kubectl exec <pod> -- id`<br>`kubectl exec <pod> -- ls -l /path/to/secrets` | Укажите `fsGroup: <GID>` в `pod.spec.securityContext` либо задайте `defaultMode: 0440` в `volume.secret`. |
| `ImagePullBackOff` / `ErrImagePull` | Ошибка авторизации в Container Registry при скачивании образа. | `kubectl describe pod <pod> \| grep -A 5 Events` | 1. Проверьте, указан ли секрет в `spec.imagePullSecrets`.<br>2. Убедитесь, что секрет имеет тип `kubernetes.io/dockerconfigjson` и содержит валидный `.dockerconfigjson`. |
| Аутентификация в приложении падает с ошибкой 401/403 после декодирования секрета | В конец пароля попал невидимый байт перевода строки (`0x0A`) при использовании `echo` без `-n`. | `kubectl get secret <name> -o jsonpath='{.data.password}' \| base64 -d \| cat -A` | Пересоздайте секрет, используя `echo -n "password" \| base64` или передавайте пароль через файл/литерал `kubectl create secret generic --from-literal=password=...`. |

---

## Рекомендации (Best Practices)

### 1. Архитектурная безопасность и принцип минимальных привилегий
- **Монтирование через Volume вместо переменных окружения:** всегда отдавайте предпочтение монтированию секретов в виде томов (`tmpfs`). Переменные окружения сохраняются в `/proc/<PID>/environ`, попадают в дамп при аварийном завершении процессов (core dump), отображаются в выводе `kubectl describe pod` и легко утекают в логи при сборке трассировок стека.
- **Ограничение прав доступа к файлам (`defaultMode`):** монтируйте секреты с правами только на чтение (`readOnly: true`) и выставляйте жесткие маски доступа `defaultMode: 0400` (чтение только владельцем) или `defaultMode: 0440` (чтение группой приложения).
- **Исключение прав `list` и `watch` на уровне пространства имен:** никогда не выдавайте приложению или стороннему оператору право `list` или `watch` на все секреты пространства имен. Право `list` позволяет прочитать содержимое абсолютно каждого секрета в namespace. Ограничивайте доступ только к конкретным объектам через секцию `resourceNames` в правилах RBAC `Role`.

### 2. Производительность Control Plane и SRE-гигиена
- **Использование `immutable: true` для статических данных:** помечайте неизменяемыми сертификаты удостоверяющих центров (Root CA), постоянные ключи шифрования и неизменяемые токены. Это снижает нагрузку на `kube-apiserver` за счет отмены сессий `watch` от `kubelet`.
- **Контроль объема секретов:** не храните более 1 000–2 000 секретов в одном пространстве имен. Каждый секрет находится в оперативной памяти `kube-apiserver`. Превышение лимитов замедляет выполнение селекторных запросов и увеличивает RSS-память мастеров.
- **Соблюдение жесткого лимита 1 MiB:** не используйте секреты для передачи больших статических файлов (тяжелые архивы, связки ключей). Выносите их на хранилища объектов (S3/MinIO) или в постоянные тома (PVC).

### 3. GitOps и версионирование
- **Никогда не сохраняйте манифесты Secret в открытом виде в Git:** даже закодированные в Base64 данные являются открытыми. В репозиториях Git секреты должны храниться **исключительно в зашифрованном виде** с использованием утилит Mozilla SOPS или Sealed Secrets, либо доставляться динамически через External Secrets Operator (ESO).
- **Хеширование имен через Kustomize (`secretGenerator`):** используйте генерацию суффикса-хеша для обеспечения автоматического и бесшовного Rolling Update подов при изменении содержимого секрета.

### 4. Эксплуатация и вывод из эксплуатации (Decommissioning)
- **Аудит неиспользуемых (орфанных) секретов:** регулярно проводите аудит секретов, на которые не ссылаются никакие Deployment, StatefulSet, DaemonSet, CronJob или ServiceAccount.
- **Безопасное удаление:** при ротации ключей удаляйте старые секреты только после полного завершения перехода всех подов на новую ревизию.

---

## Дополнительная информация

### Ограничения и системные лимиты

- **Размер транзакции etcd:** жесткий лимит на размер одного объекта Secret составляет **1 MiB (1 048 576 байт)**. Лимит рассчитывается от полного размера сериализованного JSON/Protobuf-манифеста с учетом Base64-данных и служебных метаданных.
- **Ограничения на имена ключей в `data`:** имя ключа должно состоять из буквенно-цифровых символов, точек (`.`), дефисов (`-`) и подчеркиваний (`_`) и не превышать длину 253 символов (соответствие RFC 1123).
- **Масштабируемость API Server:** хранение десятков тысяч секретов в одном кластере требует выделения дополнительных вычислительных ресурсов (RAM) узлам Control Plane и настройки параметров кэширования `kubelet`.

### Смотрите также

- [Создание Secret](creating_secrets.md) — детальные сценарии создания, автоматизация, работа со всеми типами.
- [Использование Secret](using_secrets.md) — монтирование томов, Projected Volumes, `fsGroup`, нюансы доставки данных в Pod.
- [Безопасность Secret](security.md) — матрица угроз, аудит доступа, сканирование утечек, RBAC-харденинг.
- [Хранение в etcd](etcd_storage.md) — настройка `EncryptionConfiguration`, KMS v2, алгоритмы AES-CBC и Secretbox.
- [Внешние менеджеры](external_managers.md) — интеграция с HashiCorp Vault, External Secrets Operator (ESO), Secrets Store CSI Driver.
- [Helm + секреты](helm_secrets.md) — управление секретами в Helm-чартах через плагин helm-secrets.
- [Секреты в StatefulSet](statefulset_secrets.md) — специфические шаблоны работы с секретами для баз данных и распределенных сервисов.
- [Pod Security Standards и Secret](pod_security_and_secrets.md) — влияние профилей изоляции (PSA restricted) на права монтирования секретов.
- [Sealed Secrets](../../Security/sealed_secrets_overview.md) — шифрование секретов для безопасного хранения в Git.
- [SOPS](../../../Security/Tools/sops_overview.md) — шифрование файлов через Mozilla SOPS.
- [cert-manager](../../ToolsUtilities/cert_manager/definitions.md) — автоматизация выпуска и ротации TLS-сертификатов.
- [Vault + Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md) — интеграция с HashiCorp Vault.
- [GitOps: управление секретами](../../../GitOps/secrets_encryption.md) — сравнение архитектурных подходов к хранению секретов в Git.
