# Создание Secret в Kubernetes

## Определения

**Создание Secret** — процесс формирования объекта API Kubernetes для хранения чувствительных данных. Секреты позволяют безопасно передавать учетные данные, ключи и сертификаты в контейнеры без их жесткой прошивки (hardcoding) в образы или манифесты.

**Base64 кодирование** — стандартный метод представления двоичных данных в формате ASCII, используемый в поле `data` объектов Secret. Base64 выбран, потому что:
- Гарантирует безопасную передачу данных через текстовые протоколы (JSON, YAML).
- Сохраняет целостность данных при транспортировке.
- Является стандартом для встраивания бинарных данных в текстовые форматы.

> **Критическое замечание:** Base64 — это **не шифрование**. Любой пользователь с доступом к манифесту (YAML) или etcd может мгновенно декодировать данные (`echo <base64> | base64 -d`).

**API-валидация** — при создании Secret через API Server выполняется проверка:
- Структуры данных (наличие обязательных ключей для типизированных секретов).
- Размера (лимит 1 MiB).
- Корректности Base64-кодирования в поле `data`.
- Существования указанного `type` (для нестандартных типов API вернет ошибку).

Подробнее о защите данных см. [Безопасность Secret](security.md) и [Хранение в etcd](etcd_storage.md).

## Основные концепции

### Методы управления секретами

1.  **Императивный (CLI):** создание через `kubectl create secret`. Удобно для отладки и разовых операций. Не требует написания YAML-манифестов.
2.  **Декларативный (YAML):** описание структуры в файлах. Позволяет использовать `data` и `stringData`. Подходит для версионирования и GitOps.
3.  **Генеративный (Kustomize/Helm):** автоматическая генерация на основе файлов или шаблонов во время деплоя. Стандарт для продакшн-сред.
4.  **Операторы (External Secrets):** автоматическая синхронизация из внешних систем (HashiCorp Vault и другие хранилища). Рекомендуется для production.

### Неизменяемые секреты (Immutable)

При создании секрета можно добавить поле `immutable: true`. Это запретит любые изменения данных после создания объекта (защита от случайной перезаписи).

**Преимущества:**
- Снижение нагрузки на API Server: kubelet не опрашивает неизменяемые секреты после первого чтения.
- Гарантия неизменности критичных данных (сертификаты, ключи шифрования).

**Ограничение:** Для обновления неизменяемого секрета необходимо удалить старый и создать новый объект Secret, а затем пересоздать Pod или выполнить rollout restart.

> **Примечание:** у `kubectl create secret` **нет флага** `--immutable`. Неизменяемый секрет можно создать только декларативным манифестом (или через Kustomize patch):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-immutable-secret
immutable: true
stringData:
  api_key: "7f5a8c..."
```

### Изменение в ServiceAccount Tokens (1.24+)

Токены ServiceAccount больше не создаются автоматически как объекты Secret. Если требуется статический секрет для SA, его нужно создать вручную:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: manual-sa-token
  annotations:
    kubernetes.io/service-account.name: "my-service-account"
type: kubernetes.io/service-account-token
```

### Соглашения об именовании

Kubernetes не накладывает строгих ограничений на имена Secret, но рекомендуется следовать общепринятым соглашениям:
- Используйте lowercase и дефисы: `db-credentials`, `app-tls-cert`.
- Избегайте спецсимволов и кириллицы.
- Префикс типа для типизированных секретов: `tls-app-cert`, `docker-app-pull`.
- Для секретов, связанных с приложением, добавляйте имя приложения: `myapp-db-password`.

### Поля data и stringData

В манифесте Secret используются два поля для ввода данных:

| Поле | Формат значений | Когда использовать |
| :--- | :--- | :--- |
| `data` | Base64-закодированные | Автоматическое создание через скрипты, CI/CD, бинарные данные |
| `stringData` | Открытый текст | Ручное редактирование манифестов, быстрое создание |

**Поведение полей:**
- **Приоритет:** Если один и тот же ключ указан и в `data`, и в `stringData`, значение из `stringData` будет иметь приоритет и перезапишет `data`.
- **Скрытие:** Поле `stringData` доступно только для записи и не отображается при выполнении `kubectl get secret -o yaml` (Kubernetes показывает только `data`).
- **Автокодирование:** При сохранении манифеста Kubernetes автоматически кодирует значения из `stringData` в Base64 и переносит их в поле `data`.

**Практический нюанс — пробелы и переносы строк:**
```bash
# ОШИБКА: перенос строки попадёт в пароль
echo "my-password" | base64
# → bXktcGFzc3dvcmQK  (лишний символ 'K' в конце = символ переноса строки)

# ПРАВИЛЬНО: флаг -n убирает перенос
echo -n "my-password" | base64
# → bXktcGFzc3dvcmQ=
```

## Практические сценарии

### Императивное создание (kubectl)

#### Общие флаги kubectl create secret

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `--from-literal=key=value` | Добавить один ключ-значение | `--from-literal=user=admin` |
| `--from-file=path` | Добавить из файла (имя ключа = имя файла) | `--from-file=./cert.pem` |
| `--from-file=key=path` | Добавить из файла с указанием имени ключа | `--from-file=ssh-key=~/.ssh/id_rsa` |
| `--from-env-file=path` | Импортировать все пары KEY=VALUE из файла | `--from-env-file=.env` |
| `--type=type` | Задать тип секрета (по умолчанию `Opaque`) | `--type=kubernetes.io/basic-auth` |
| `--append-hash` | Добавить к имени хеш содержимого (аналог Kustomize) | `--append-hash` |
| `--dry-run=client` | Только сгенерировать YAML без отправки в API | `--dry-run=client -o yaml` |
| `--dry-run=server` | Проверить валидацию на сервере (если доступен) | `--dry-run=server -o yaml` |
| `-n, --namespace` | Указать namespace для создания | `-n production` |
| `--save-config` | Сохранить конфигурацию в аннотациях (для kubectl apply) | `--save-config` |
| `--output, -o` | Формат вывода (yaml, json) | `-o yaml` |

> **Отличие `--dry-run=client` от `--dry-run=server`:**
> - `client` — генерирует YAML локально без обращения к API Server. Быстрее, но не проверяет валидность на стороне сервера.
> - `server` — отправляет запрос на API Server для валидации (проверка прав RBAC, существования namespace, структуры данных), но не создает объект. Требует доступа к кластеру.

#### Из литералов (literals)

```bash
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password='P@ssw0rd123!'
```

**Квотирование специальных символов:** в zsh/bash аргументы `--from-literal` со спецсимволами (`$`, обратные кавычки, восклицательный знак, пробелы) необходимо заключать в одинарные кавычки, иначе shell выполнит подстановку:

```bash
# ОШИБКА: $ будет подставлен shell'ом (часто → пустая строка)
kubectl create secret generic api-creds \
  --from-literal=api_key=$API_TOKEN --from-literal=token=$(cat token.txt)

# ПРАВИЛЬНО: одинарные кавычки запрещают подстановку
kubectl create secret generic api-creds \
  --from-literal='api_key=$uperSecret' \
  --from-literal='token=pa$$w0rd!'

# ПРАВИЛЬНО: двойные кавычки сохраняют пробелы внутри строки
kubectl create secret generic app-creds \
  --from-literal="api_key=S3cret key with spaces"
```

> **Замечание:** значения из `--from-literal` попадают в данные в Base64-виде — kubectl кодирует их автоматически без добавления переноса строки (в отличие от `echo | base64`). Однако значения из файлов через `--from-file` сохраняются **байт-в-байт**, включая завершающий перенос строки в файле.

#### Из файлов или директорий

```bash
# Имя ключа будет соответствовать имени файла
kubectl create secret generic ssh-key --from-file=id_rsa=~/.ssh/id_rsa

# Все файлы в директории будут добавлены как ключи
kubectl create secret generic app-configs --from-file=./configs/
```

#### Из файла .env (from-env-file)

Формат файла `--from-env-file` — пары `KEY=VALUE`, комментарии начинаются с `#`:

```bash
# .env файл
DB_HOST=localhost
DB_PORT=5432
DB_USER=admin
DB_PASSWORD=supersecret

# Создание секрета из .env файла
kubectl create secret generic app-env \
  --from-env-file=.env

# Результат: каждый ключ становится отдельным ключом в Secret
# DB_HOST, DB_PORT, DB_USER, DB_PASSWORD
```

**Правила формата `--from-env-file`:**

- Каждая строка — пара `KEY=VALUE`; разделителем ключа и значения является **первый** символ `=`. Значение может содержать любые символы, включая `=`.
- Комментарии начинаются с `#` (строка полностью пропускается). Пустые строки игнорируются, ведущие пробелы/табуляции обрезаются.
- Если в строке нет символа `=`, значение берется из переменной окружения shell (`KEY` → `os.Getenv("KEY")`).
- Имя ключа должно быть валидным именем переменной окружения (латиница, цифры, `_`; не может начинаться с цифры). Имена с дефисами (`DB-HOST`) вызовут ошибку.
- Не поддерживает многострочные значения и экранирование спецсимволов.
- **Нельзя комбинировать** `--from-env-file` с `--from-file` или `--from-literal` в одной команде — kubectl вернет ошибку валидации.

**Ограничение:** `--from-env-file` не поддерживает многострочные значения и значения с спецсимволами без экранирования. Для сложных конфигураций используйте `--from-file`.

#### Из stdin

Для автоматизации в скриптах можно передавать данные через stdin:

```bash
# Через pipe
echo -n "my-secret-value" | kubectl create secret generic my-secret \
  --from-file=token=/dev/stdin

# Чтение из переменной
SECRET_VALUE=$(openssl rand -base64 32)
echo -n "$SECRET_VALUE" | kubectl create secret generic encryption-key \
  --from-file=key=/dev/stdin
```

#### Генерация манифеста (Dry-run)

Для последующего шифрования через SOPS или Sealed Secrets:

```bash
# Без обращения к API Server (быстрый вариант)
kubectl create secret generic my-secret \
  --from-literal=key=value \
  --dry-run=client -o yaml > secret.yaml

# С валидацией на сервере (требует доступ к кластеру)
kubectl create secret generic my-secret \
  --from-literal=key=value \
  --dry-run=server -o yaml > secret.yaml

# Создание в конкретном namespace
kubectl create secret generic prod-db-creds \
  --from-literal=password=$(openssl rand -base64 24) \
  -n production \
  --dry-run=client -o yaml > prod-secret.yaml
```

#### Копирование секретов между namespace

```bash
# Экспорт секрета из одного namespace
kubectl get secret my-secret -n source-ns -o yaml > secret-backup.yaml

# Удаление метаданных для создания в новом namespace
# (убрать resourceVersion, uid, creationTimestamp, namespace)
kubectl get secret my-secret -n source-ns -o json | \
  jq 'del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .metadata.namespace)' | \
  kubectl apply -n target-ns -f -

# Или через dry-run (автоматически удаляет server-side поля)
kubectl get secret my-secret -n source-ns -o yaml | \
  kubectl create -n target-ns -f - --dry-run=client -o yaml | \
  kubectl apply -n target-ns -f -
```

### Декларативное создание (YAML)

#### Поле stringData (Рекомендуется для ручного редактирования)

Позволяет писать секреты в открытом виде. Kubernetes сам закодирует их в Base64.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
  labels:
    app: my-app
    env: production
stringData:
  api_key: "7f5a8c..."
  db_password: "S3cur3P@ss"
```

#### Поле data (Бинарные данные и CI/CD)

Для бинарных файлов (JKS, сертификаты) или автоматического создания через скрипты:

```bash
# Кодирование в Base64
echo -n "my-password" | base64
# → bXktcGFzc3dvcmQ=
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: binary-secret
data:
  keystore: <base64-encoded-jks>
  password: bXktcGFzc3dvcmQ=
```

#### Создание с метками и аннотациями

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  labels:
    app: my-app
    env: production
    team: backend
  annotations:
    description: "Основные учетные данные PostgreSQL"
    managed-by: "helm"
type: Opaque
stringData:
  username: "admin"
  password: "S3cur3P@ss"
```

#### Специальные типы Secret

**TLS Secret:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ingress-cert
type: kubernetes.io/tls
data:
  tls.crt: <base64-encoded-cert>
  tls.key: <base64-encoded-key>
```

> **Валидация при `kubectl create secret tls`:** команда проверяет, что пара «сертификат + приватный ключ» образует корректную X.509-пару через `tls.X509KeyPair`. При несовпадении вернется ошибка `error: failed to load key pair tls: private key does not match public key`, при отсутствии PEM-границ — `failed to find any PEM data in certificate input`, при зашифрованном (passphrase) ключе — `failed to parse private key` (ключ нужно предварительно расшифровать: `openssl rsa -in enc.key -out dec.key`).
> **Порядок в цепочке:** при использовании сцепленного файла (leaf + intermediates + root) **первый** сертификат в файле сверяется с ключом. Нарушение порядка блоков `-----BEGIN...-----`/`-----END...-----` приводит к ошибке несоответствия. Для самостоятельной проверки пары до создания Secret:
> ```bash
> cert=$(openssl x509 -noout -pubkey -in tls.crt)
> key=$(openssl pkey -pubout -in tls.key 2>/dev/null || openssl rsa -pubout -in tls.key 2>/dev/null)
> [ "$cert" = "$key" ] && echo "OK: пара соответствует" || echo "FAIL: ключ не подходит к сертификату"
> ```

**Docker Registry Secret:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: regcred
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: <base64-encoded-docker-config>
```

**SSH Auth Secret:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ssh-key
type: kubernetes.io/ssh-auth
data:
  ssh-privatekey: <base64-encoded-ssh-private-key>
```

**Basic Auth Secret:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: basic-auth
type: kubernetes.io/basic-auth
stringData:
  username: "admin"
  password: "S3cur3P@ss"
```

**Bootstrap Token Secret (kubeadm):**

Секрет типа `bootstrap.kubernetes.io/token` используется `kubeadm` для временной аутентификации новых узлов при присоединении к кластеру. Автоматически создается командой `kubeadm token create` (по умолчанию TTL 24 часа):

```bash
# Создать токен + команду присоединения узла (включая Discovery CA hash)
kubeadm token create --print-join-command

# Создать через curl к API (эквивалент манифеста Secret)
kubeadm token create --ttl=24h
```

**Ручное создание** (полезно для автоматизации и IaC):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: bootstrap-token-<token-id>   # token-id: 6 символов [a-z0-9]
  namespace: kube-system
type: bootstrap.kubernetes.io/token
stringData:
  token-id: "<6-символьный id>"       # первая часть "aaaaaa.bbbbbbbbbbbbbbbb"
  token-secret: "<16-символьный секрет>" # вторая часть токена
  expiration: "2026-09-01T00:00:00Z"  # необязательно; TTL по умолчанию 24ч
  usage-bootstrap-authentication: "true"   # разрешить аутентификацию узла
  usage-bootstrap-signing: "true"          # разрешить подпись CSR
  description: "Worker node join token"
```

Полное имя токена формируется как `<token-id>.<token-secret>`, например `abcdef.1234567890abcdef`. Подробнее о жизненном цикле: [Присоединение узлов](../../Installation/HA_Cluster_Bare_Metal/node_joining.md).

### Генерация через Kustomize (secretGenerator)

Стандарт для управления секретами в GitOps. Автоматически добавляет хеш содержимого к имени, что инициирует Rolling Update Подов при смене данных.

```yaml
# kustomization.yaml
secretGenerator:
- name: app-secrets
  files:
    - .env.prod
  options:
    disableNameSuffixHash: false  # false (по умолчанию) = хеш ДОБАВЛЯЕТСЯ к имени
    labels:                       # метки, добавляемые к сгенерированному Secret
      generated-by: kustomize
      env: prod
    annotations:
      note: "Encrypt before commit (SOPS/Sealed Secrets)"
```

> **Ключевой нюанс:** хеш к имени добавляется **по умолчанию** (`disableNameSuffixHash: false`). Отключение хеша (`disableNameSuffixHash: true`) означает, что смена данных **не** вызовет пересоздание Pod — устаревшие значения останутся до ручного rollout restart. Для всего проекта опция задается через `generatorOptions` (применяется и к `configMapGenerator`). Ссылки на сгенерированные секреты (в Deployment, Pod) Kustomize автоматически переписывает на имя с хешем.

**Дополнительные параметры Kustomize:**

```yaml
secretGenerator:
# Из литералов
- name: db-creds
  literals:
    - username=admin
    - password=supersecret

# Из файла с указанием имени ключа
- name: tls-certs
  files:
    - tls.crt=certs/server.crt
    - tls.key=certs/server.key

# Из .env файла
- name: app-env
  envs:
    - .env.production

# С типом секрета
- name: docker-reg
  type: kubernetes.io/dockerconfigjson
  files:
    - .dockerconfigjson=docker-config.json
```

**Результат генерации:** Kustomize создаст Secret с именем вида `app-secrets-<suffix>`, где `<suffix>` — 10-символьный «безопасный» суффикс, производный от SHA256-хеша содержимого секрета (алфавит без гласных-подобных символов `0/1/3/a/e`, по аналогии с `GenerateName`). Это гарантирует, что при изменении данных появится новое имя и будет запущен Rolling Update Pod.

### Императивное создание типизированных секретов

> **Важно:** `kubectl create secret` поддерживает только **три** подкоманды — `generic`, `tls` и `docker-registry`. Подкоманд `ssh-auth`, `basic-auth` и `service-account-token` **не существует** (проверено на kubectl v1.37). Типизированные секреты (кроме TLS и Docker Registry) создаются через `generic` с флагом `--type` или декларативным манифестом.

```bash
# TLS Secret (отдельная подкоманда; самопроверка пары ключ/сертификат)
kubectl create secret tls ingress-cert --cert=tls.crt --key=tls.key

# Docker Registry Secret (отдельная подкоманда)
kubectl create secret docker-registry regcred \
  --docker-server=<registry-url> \
  --docker-username=<user> \
  --docker-password=<pass> \
  --docker-email=<email>

# SSH Auth Secret (через generic с --type)
kubectl create secret generic ssh-key \
  --type=kubernetes.io/ssh-auth \
  --from-file=ssh-privatekey=~/.ssh/id_rsa

# Basic Auth Secret (через generic с --type)
kubectl create secret generic basic-creds \
  --type=kubernetes.io/basic-auth \
  --from-literal=username=admin \
  --from-literal=password='P@ssw0rd!'
```

**ServiceAccount Token:**
Создание долгоживущего SA-токена в виде объекта `Secret` выполняется **только** декларативным манифестом с аннотацией `kubernetes.io/service-account.name` (см. раздел «Изменение в ServiceAccount Tokens (1.24+)»), так как подкоманды `kubectl create secret service-account-token` не существует:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-sa-token
  annotations:
    kubernetes.io/service-account.name: my-service-account
type: kubernetes.io/service-account-token
```

Современной и более безопасной альтернативой является короткоживущий токен с привязкой к объекту (не создает объект `Secret`):

```bash
kubectl create token my-service-account -n <namespace> --duration=2h
# Токен с привязкой к конкретному Secret (аннулируется при удалении Secret)
kubectl create token my-service-account \
  --bound-object-kind Secret --bound-object-name my-sa-token
```

### Обновление (Patching)

Для обновления конкретного ключа без перезаписи всего секрета:

```bash
# Обновление через stringData
kubectl patch secret db-credentials -p '{"stringData":{"password":"new-password"}}'

# Обновление через data (требует Base64)
kubectl patch secret db-credentials -p '{"data":{"password":"'$(echo -n 'new-password' | base64)'"}}'

# Добавление нового ключа
kubectl patch secret db-credentials -p '{"stringData":{"new-key":"new-value"}}'

# Удаление ключа (через JSON merge patch)
kubectl patch secret db-credentials --type='json' -p='[{"op": "remove", "path": "/data/old-key"}]'
```

**Альтернативные способы обновления:**

```bash
# Интерактивное редактирование в $EDITOR (без ручного Base64)
kubectl edit secret db-credentials
# В редакторе меняйте значения в поле data (Base64) или добавьте stringData —
# после сохранения значение из stringData перезапишет data

# Декларативное обновление (измените файл и пере-примените)
kubectl apply -f secret.yaml
```

> Для возможности `kubectl apply` корректно обновлять объект, созданный ранее через `kubectl create`, используйте `--save-config` при создании либо `kubectl create --dry-run=client -o yaml | kubectl apply -f -`. Без `last-applied-configuration` `apply` может выполнить merge-патч с пропущенными полями.

### Валидация после создания

После создания секрета рекомендуется выполнить проверку:

```bash
# Проверка наличия секрета
kubectl get secret my-secret -n <namespace>

# Просмотр деталей (без расшифровки данных)
kubectl describe secret my-secret

# Просмотр всех ключей в Base64
kubectl get secret my-secret -o jsonpath='{.data}' | jq 'keys'

# Просмотр конкретного ключа (с декодированием)
kubectl get secret my-secret -o jsonpath='{.data.password}' | base64 -d
echo

# Проверка типа секрета
kubectl get secret my-secret -o jsonpath='{.type}'

# Проверка наличия лишних символов (перенос строки)
kubectl get secret my-secret -o jsonpath='{.data.password}' | base64 -d | cat -A
# Если в конце строки символ $ — лишний перенос строки
```

### Типичные ошибки при создании

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Error: secrets "xxx" already exists` | Секрет с таким именем уже существует | Используйте `kubectl get secrets` для проверки; переименуйте или удалите старый |
| `Error: the server doesn't have a resource type "secrets"` | API-сервер недоступен или устарела версия kubectl | Проверьте подключение: `kubectl cluster-info` |
| `Error: Unable to connect to the server` | Нет доступа к API Server | Проверьте kubeconfig: `kubectl config view` |
| `Error: secret is invalid` | Невалидная структура данных для типа | Проверьте обязательные ключи для типа (например, `tls.crt`/`tls.key` для `kubernetes.io/tls`) |
| `Error: RequestEntityTooLarge` | Размер секрета превышает 1 MiB | Разделите данные или используйте внешнее хранилище |
| `Error: forbidden` | RBAC запрещает создание секретов | Проверьте права: `kubectl auth can-i create secrets --namespace=<ns>` |
| `error: unknown command "ssh-auth" for "kubectl create secret"` | Подкоманды `ssh-auth`/`basic-auth`/`service-account-token` не существуют | Используйте `kubectl create secret generic ... --type=...` или манифест |
| `error: failed to load key pair tls: private key does not match public key` | Ключ не соответствует сертификату или нарушен порядок цепочки в PEM-файле | Проверьте пару через `openssl x509 -noout -pubkey` / `openssl pkey -pubout`; упорядочьте блоки leaf→root |
| `parse error in --from-env-file ...` / `<key> is not a valid key name` | Некорректный синтаксис или невалидное имя ключа в env-файле | Соблюдайте формат `KEY=VALUE`, имена без дефисов; используйте `--from-file` для сложных значений |
| `from-env-file cannot be combined with from-file or from-literal` | Смешение разных источников в одной команде | Разбейте на несколько `kubectl create` + `kubectl patch` или объедините через `--from-file` |
| `cannot add key X, another key by that name already exists` | Дублирование одного ключа в источниках (`--from-literal`+`--from-file`) | Исключите повторяющиеся имена ключей |
| `error: cannot give a key name for a directory path` | `--from-file=key=путь_к_директории` (для директорий имя ключа задавать нельзя) | Передавайте директорию без `key=` или перечислите файлы явно |
| `error reading <path>: no such file or directory` | Путь к файлу-источнику указан неверно | Проверьте относительный/абсолютный путь относительно каталога запуска |
| Секрет создан как `Opaque`, но должен работать как TLS/Registry/SSH | Не указан явный тип; `Opaque` не дает валидации ключей | Для типизированных секретов (TLS, dockerconfigjson, ssh-auth, basic-auth) всегда задавайте `type` — это включает проверку обязательных ключей и корректную обработку потребителями (Ingress, kubelet) |
| Secret создан, но `stringData` не отображается | Это нормальное поведение | `stringData` — write-only поле; используйте `kubectl get secret -o json` для просмотра `data` |

## Дополнительная информация

### Проверка на лишние символы

Если приложение не принимает пароль, проверьте наличие переноса строки (`$`) в конце:

```bash
kubectl get secret my-secret -o jsonpath='{.data.password}' | base64 -d | cat -A
# Если в конце строки символ $ — лишний перенос строки

# Исправление: пересоздайте секрет, используя `echo -n` (без переноса строки)
kubectl create secret generic my-secret \
  --from-literal=password=$(echo -n 'correct-password' | base64) \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Лимиты и ограничения при создании

- **Размер объекта:** Максимальный размер Secret — **1 MiB** (включая метаданные и Base64-данные).
- **Количество Secret на Namespace:** Рекомендуется не более 1000–2000 secrets для поддержания производительности.
- **Ключи в data:** Ключи должны быть валидными в DNS-подходе (lowercase, alphanumeric, дефисы, точки).
- **Длина имени ключа:** Ограничена размером etcd (максимальная длина ключа — 255 байт).
- **Типы секретов:** Кастомные типы требуют обязательных ключей, иначе API вернет ошибку валидации.

### Лучшие практики при создании

1. **Используйте `--dry-run=client`** для генерации манифестов в CI/CD пайплайнах. Это гарантирует, что YAML-файлы будут валидны перед применением.
2. **Избегайте `--from-literal` для длинных значений** — используйте `--from-file` для многострочных данных или сертификатов.
3. **Для production используйте декларативный подход** (YAML) вместо императивного — это обеспечивает версионирование и reproducibility.
4. **Указывайте `type` явно** в манифестах — это помогает валидации и документированию.
5. **Добавляйте метки (labels)** для организации и фильтрации секретов.
6. **Используйте `immutable: true`** для секретов, которые не будут меняться после создания.
7. **Для GitOps** шифруйте секреты через SOPS или Sealed Secrets перед коммитом.
8. **Валидируйте секреты** после создания (команды выше).
9. **Для автоматической генерации паролей** используйте `openssl rand -base64 24` или `head -c 32 /dev/urandom | base64`.
10. **Используйте `--append-hash` в CI/CD:** при императивном создании секрета флаг добавит к имени хеш содержимого, что вызовет пересоздание Pod при смене данных даже без Kustomize.
11. **Не смешивайте источники в одной команде:** `--from-env-file` нельзя комбинировать с `--from-literal`/`--from-file`.
12. **Храните env-файлы вне Git** (или в зашифрованном виде): файлы `.env` для `--from-env-file` и `--from-file` часто попадают в репозитории — добавьте их в `.gitignore` или шифруйте перед коммитом и расшифровывайте только на раннере CI.

### Очистка и откат

```bash
# Удаление секрета
kubectl delete secret my-secret -n <namespace>

# Удаление всех секретов с определенным лейблом
kubectl delete secrets -l env=test -n <namespace>

# Откат через kubectl apply (если секрет был создан через save-config)
kubectl apply -f secret-manifest.yaml --prune

# Просмотр изменений перед применением (diff)
kubectl diff -f secret-manifest.yaml
```

### GitOps и безопасность

Никогда не храните секреты в Git в открытом виде. Используйте:
- **[Sealed Secrets](../../Security/sealed_secrets_overview.md)** — шифрование для конкретного кластера.
- **[SOPS](../../../Security/Tools/sops_overview.md)** — шифрование с использованием KMS/PGP.
- **External Secrets Operator** — синхронизация из внешних хранилищ (рекомендуется для Production).

### Смотрите также

- [Основы Secret](secrets_basics.md) — обзор типов и архитектура.
- [Использование Secret](using_secrets.md) — доставка в Pod.
- [Безопасность Secret](security.md) — лучшие практики и KMS.
