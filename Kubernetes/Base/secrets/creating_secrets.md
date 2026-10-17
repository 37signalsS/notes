# Создание Secret в Kubernetes

**Актуально для:** Kubernetes 1.30–1.32+ / kubectl 1.30+

## Определения

**Создание Secret** — процесс формирования объекта API Kubernetes (`v1/Secret`) для безопасного хранения и доставки чувствительных данных (паролей, токенов, ключей доступа, TLS-сертификатов) в контейнеры без жесткого внедрения (hardcoding) в образы или манифесты развертывания.

**Base64-кодирование** — бинарно-текстовая схема кодирования (RFC 4648), используемая в поле `data` объекта Secret для безопасной передачи произвольных бинарных последовательностей через текстовые протоколы JSON и YAML.
- **Критическое различие:** Base64 — это **кодирование, а не шифрование**. Любой субъект с правами на чтение объекта через API (`kubectl get secret -o yaml`) или доступом к etcd может моментально восстановить открытый текст:
  ```bash
  echo "c3VwZXJzZWNyZXQ=" | base64 -d
  # → supersecret
  ```
- Для реальной защиты данных в состоянии покоя (at-rest) требуется настройка `EncryptionConfiguration` на уровне `kube-apiserver` (см. [Хранение в etcd](etcd_storage.md) и [Безопасность Secret](security.md)).

**stringData** — вспомогательное write-only поле спецификации Secret, позволяющее указывать значения в виде обычного текста без предварительного кодирования в Base64. `kube-apiserver` самостоятельно кодирует значения `stringData` в Base64 при обработке запроса и сохраняет их в поле `data`. При получении объекта через API поле `stringData` никогда не возвращается.

**API-валидация и Admission** — многоэтапная проверка объекта API-сервером перед записью в etcd:
- Проверка соответствия схеме OpenAPI v3 и ограничению на размер (не более 1 MiB).
- Проверка корректности Base64-строк в `data` (валидные символы алфавита RFC 4648, корректный padding `=`).
- Валидация структуры специализированных типов: наличие обязательных ключей (например, `tls.crt` и `tls.key` для типа `kubernetes.io/tls`).
- Контроль прав RBAC и политики допуска (Admission Webhooks, OPA/Gatekeeper, Kyverno).

**Неизменяемый Secret (Immutable Secret)** — объект Secret, созданный со свойством `immutable: true`. После успешной инициализации API Server блокирует любые мутации полей `data` и `stringData`, снижая нагрузку на control plane за счет отмены непрерывного опроса (watch) со стороны `kubelet`.

---

## Основные концепции

### Жизненный цикл создания Secret (API & Admission Pipeline)

Создание Secret в Kubernetes представляет собой детерминированный конвейер обработки запроса на уровне Control Plane:

```
[ Клиент: kubectl / CI / Helm / Kustomize ]
                    │
                    ▼  (POST /api/v1/namespaces/{ns}/secrets)
           [ kube-apiserver ]
                    │
                    ├─► 1. Аутентификация (X.509, Webhook, OIDC)
                    ├─► 2. Авторизация RBAC (verbs: "create", resource: "secrets")
                    ├─► 3. Mutating Admission Webhooks (модификация метаданных, инъекция меток)
                    ├─► 4. Валидация схемы объекта (размер < 1 MiB, Base64 в data, обязательные ключи type)
                    ├─► 5. Validating Admission Webhooks (Kyverno / OPA Gatekeeper: аудит безопасности)
                    ├─► 6. Encryption at Rest (шифрование данных через EncryptionConfiguration)
                    │
                    ▼
               [ etcd ] (/registry/secrets/{namespace}/{name})
                    │
                    ▼  (Watch / List события)
         [ kubelet / Контроллеры ] (монтирование volume / инъекция env / запуск Pod)
```

1. **Аутентификация и RBAC:** проверяется, обладает ли инициатор запроса правом выполнения операции `create` над ресурсом `secrets` в целевом пространстве имен (`namespace`).
2. **Mutating Webhooks:** перехватывают запрос до фиксации схемы; могут автоматически внедрять аннотации аудита или метки владения.
3. **Схемная валидация:** `kube-apiserver` проверяет синтаксис имен ключей, декодирует Base64 для проверки целостности, проверяет валидность типа.
4. **Validating Webhooks:** применяют корпоративные политики (например, запрет создания незашифрованных секретов определенного типа или блокировка секретов без владельца).
5. **Шифрование at-rest:** если на Master-узлах настроен `EncryptionConfiguration` (провайдеры `kms`, `aescbc`, `secretbox`), API Server шифрует полезную нагрузку перед записью.
6. **Запись в etcd:** сериализованный Protobuf-объект записывается по ключу `/registry/secrets/<namespace>/<name>`.

### Методы управления секретами

| Метод | Инструменты | Преимущества | Недостатки / Риски | Область применения |
| :--- | :--- | :--- | :--- | :--- |
| **Императивный** | `kubectl create secret` | Простота, скорость выполнения, применимость для аварийных сценариев | Команды сохраняются в `bash_history`; не версионируется в Git | Отладка, разовые операции на On-Premise стендах |
| **Декларативный** | YAML-манифесты, `kubectl apply` | Поддержка `stringData`, воспроизводимость, совместимость с CI/CD | Риск коммита открытого манифеста в репозиторий Git | GitOps (только в связке с SOPS или Sealed Secrets) |
| **Генеративный** | Kustomize (`secretGenerator`), Helm | Автоматическое добавление хеша к имени (`suffix-hash`), триггер rolling update | Требует настройки сборки шаблонов перед деплоем | Стандартные пайплайны GitOps / CD |
| **Внешние операторы** | External Secrets Operator (ESO), HashiCorp Vault Agent | Централизованное хранилище, динамическая ротация, отсутствие секретов в Git | Дополнительные CRD и контроллеры в кластере | Production On-Premise инфраструктура |

### Поля data и stringData

В спецификации `v1/Secret` определены два взаимосвязанных поля для передачи значений:

| Параметр | Поле `data` | Поле `stringData` |
| :--- | :--- | :--- |
| **Формат значений** | Base64-закодированные строки | Открытый текст (UTF-8) |
| **Направление** | Чтение и запись (Read/Write) | Только запись (Write-Only) |
| **Отображение в `kubectl get`** | Всегда возвращается в Base64 | Никогда не возвращается API-сервером |
| **Сценарии использования** | Бинарные файлы (JKS, PKCS#12, ZIP), скрипты CI/CD | Ручное создание манифестов, конфигурации с открытым текстом |

**Правила взаимодействия полей:**
1. **Приоритет при коллизии:** если манифест содержит один и тот же ключ одновременно в `data` и `stringData`, значение из `stringData` имеет безусловный приоритет и перезаписывает значение в `data`.
2. **Атомарная конвертация:** при поступлении запроса API Server преобразует все строки из `stringData` в Base64 и помещает их в `data`, после чего удаляет поле `stringData` из сохраняемого объекта.
3. **Ловушка с переносами строк:** при кодировании вручную через утилиту `echo` перенос строки (`\n`, `0x0A`) попадает в результирующий пароль, если не указан ключ `-n`:
   ```bash
   # ОШИБКА: лишний байт переноса строки 0x0A
   echo "admin_pass" | base64
   # → YWRtaW5fcGFzcwo=

   # ПРАВИЛЬНО: строго без переноса строки
   echo -n "admin_pass" | base64
   # → YWRtaW5fcGFzcw==
   ```

### Типы Secret и встроенная валидация API

Kubernetes поддерживает строгую типизацию объектов Secret через поле `type`. Тип определяет ожидания API Server и потребителей (Kubelet, Ingress-контроллеров):

| Тип (`type`) | Назначение | Обязательные ключи в `data` | Особенности валидации API |
| :--- | :--- | :--- | :--- |
| `Opaque` | Универсальный тип по умолчанию | Произвольные ключи | Валидация содержимого отсутствует; допустимы любые пары ключ-значение |
| `kubernetes.io/tls` | Сертификаты и ключи TLS/HTTPS | `tls.crt`, `tls.key` | Валидация X.509: приватный ключ должен соответствовать публичному сертификату; ключ без парольной фразы |
| `kubernetes.io/dockerconfigjson` | Авторизация в приватных Container Registry | `.dockerconfigjson` | Содержимое должно быть валидным JSON-файлом формата Docker CLI (`auths`) |
| `kubernetes.io/basic-auth` | Базовая HTTP-аутентификация | `username`, `password` | API Server требует наличия хотя бы одного из ключей при создании |
| `kubernetes.io/ssh-auth` | Приватные ключи SSH | `ssh-privatekey` | Обязателен ключ `ssh-privatekey`; опционально `known_hosts` |
| `kubernetes.io/service-account-token` | Долгоживущий токен ServiceAccount | `token` (генерируется API) | Требует аннотации `kubernetes.io/service-account.name`; токен выпускается контроллером |
| `bootstrap.kubernetes.io/token` | Токены kubeadm bootstrap | `token-id`, `token-secret` | Имя объекта строго `bootstrap-token-<token-id>`; формат ID `[a-z0-9]{6}`, секрета `[a-z0-9]{16}` |

> **Критическое замечание о CLI:** утилита `kubectl create secret` предоставляет встроенные подкоманды **только** для трех типов: `generic` (тип `Opaque`), `tls` и `docker-registry`. Подкоманд вида `kubectl create secret ssh-auth` или `basic-auth` **не существует**. Для их создания используется `kubectl create secret generic --type=...` либо декларативный манифест.

### Неизменяемые секреты (Immutable Secrets)

Установка флага `immutable: true` в корне спецификации Secret переводит объект в режим «только для чтения»:

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

**Преимущества для архитектуры и SRE:**
- **Защита от сбоев конфигурации:** случайный `kubectl apply` или сбойный CI/CD шаг не сможет затереть критические сертификаты кластера или ключи шифрования баз данных.
- **Масштабируемость Control Plane:** Kubelet не подписывается на события изменения (`watch`) неизменяемых секретов. При десятках тысяч подов в кластере это радикально снижает потребление CPU `kube-apiserver` и устраняет нагрузку на транзакционный журнал etcd.
- **Ограничения:** для ротации данных невозможно выполнить `patch` или `apply`. Необходимо удалить старый Secret и создать новый (либо выпустить новый Secret с версионным именем, например `static-root-ca-v2`, и выполнить контролируемый rollout деплоймента).

### Эволюция токенов ServiceAccount и очистка устаревших токенов (1.24+ и 1.31+)

1. **Kubernetes 1.24+:** прекращено автоматическое создание бессрочных токенов `Secret` для каждого нового ServiceAccount. Все Pod'ы по умолчанию используют **Bound ServiceAccount Token Volume** — короткоживущие токены с привязкой к жизненному циклу конкретного Pod (`TokenRequest` API).
2. **Ручное создание статических токенов:** если внешний инструмент (Prometheus, Bare-Metal CI/CD Runner, внешняя система мониторинга) требует постоянный токен, он описывается вручную через тип `kubernetes.io/service-account-token` с аннотацией целевого ServiceAccount:
   ```yaml
   apiVersion: v1
   kind: Secret
   metadata:
     name: ci-runner-sa-token
     namespace: monitoring
     annotations:
       kubernetes.io/service-account.name: "prometheus-k8s"
   type: kubernetes.io/service-account-token
   ```
3. **Механизм `LegacyServiceAccountTokenCleanUp` (Kubernetes 1.31+ GA):**
   - Контроллер `token-cleaner` в составе `kube-controller-manager` сканирует секреты типа `kubernetes.io/service-account-token`.
   - Автоматически сгенерированные в старых версиях k8s токены, не имеющие явного использования более 365 дней, помечаются меткой:
     ```yaml
     metadata:
       labels:
         kubernetes.io/legacy-token-invalid-since: "2026-01-15"
     ```
   - Запросы к API с токенами, имеющими данную метку, отклоняются с кодом `401 Unauthorized`. Если токен остается неактивным после льготного периода, контроллер окончательно удаляет объект `Secret`.
   - **Ручные токены защищены:** статические секреты, созданные пользователем с явной аннотацией `kubernetes.io/service-account.name`, очистке не подлежат.

### Лимиты и системные ограничения

- **Максимальный размер объекта:** жестко ограничен размером транзакции etcd — **1 MiB** (1 048 576 байт). Размер рассчитывается от сериализованного представления JSON/Protobuf со всеми метаданными и Base64-данными.
- **Ограничение на имена ключей в `data`:** ключ должен состоять из буквенно-цифровых символов, точек (`.`), дефисов (`-`) и подчеркиваний (`_`) и не превышать длину 253 символа.
- **Влияние на память Master-узлов:** каждый Secret постоянно находится в in-memory кэше `kube-apiserver` для обеспечения мгновенного отклика API. Хранение более 2 000–5 000 секретов в одном namespace приводит к росту RSS-памяти apiserver и замедлению селекторных запросов.
- **Изоляция:** Secret изолирован в рамках своего `namespace`. Напрямую смонтировать Secret из пространства имен `infra` в Pod пространства имен `app` невозможно.

---

## Практические сценарии

### Императивное создание (kubectl)

#### Сводная таблица параметров `kubectl create secret`

| Параметр / Флаг | Описание | Пример синтаксиса |
| :--- | :--- | :--- |
| `--from-literal=KEY=VALUE` | Передача одной пары ключ-значение напрямую из CLI | `--from-literal=db_user=postgres` |
| `--from-file=PATH` | Создание ключа с именем файла и содержимым файла | `--from-file=/etc/ssl/ca.crt` |
| `--from-file=KEY=PATH` | Создание ключа с пользовательским именем из указанного файла | `--from-file=server.key=./private.key` |
| `--from-file=DIR/` | Создание ключей из всех файлов внутри указанной директории | `--from-file=./configs/` |
| `--from-env-file=PATH` | Парсинг пар `KEY=VALUE` из переменного окружения `.env` файла | `--from-env-file=.env.production` |
| `--type=TYPE` | Назначение типа секрета (для подкоманды `generic`) | `--type=kubernetes.io/basic-auth` |
| `--append-hash` | Добавление 10-символьного хеша содержимого к имени объекта | `--append-hash` |
| `--dry-run=client` | Локальная генерация объекта без обращения к сети и кластеру | `--dry-run=client -o yaml` |
| `--dry-run=server` | Валидация на стороне API Server без сохранения в etcd | `--dry-run=server -o yaml` |
| `-n, --namespace` | Целевое пространство имен кластера | `-n backend-production` |

#### Создание из литералов (--from-literal) и экранирование в Shell

При передаче значений через командную строку спецсимволы (`$`, `!`, `"`, spaces, backticks) интерпретируются оболочкой Bash/Zsh до вызова kubectl:

```bash
# 1. Корректное экранирование в Bash: одинарные кавычки предотвращают интерполяцию переменных
kubectl create secret generic backend-creds \
  --namespace=production \
  --from-literal=user='db_admin' \
  --from-literal='password=P@$$w0rd!#2026'
# → secret/backend-creds created

# 2. Проверка созданных ключей без вывода значений:
kubectl describe secret backend-creds -n production
# → Name:         backend-creds
# → Namespace:    production
# → Labels:       <none>
# → Annotations:  <none>
# → Type:         Opaque
# → Data
# → ====
# → password:  15 bytes
# → user:      8 bytes
```

> **Гигиена командной строки (DevOps / SRE):** аргументы `--from-literal` сохраняются в файле истории оболочки (`~/.bash_history`) и видны в выводе `ps aux` в момент выполнения. Для production-систем:
> 1. Начинайте команду с пробела при включенном `HISTCONTROL=ignorespace`.
> 2. Используйте чтение из дескриптора stdin или защищенных временных файлов в памяти (`tmpfs`).

#### Создание из файлов и директорий (--from-file)

Флаг `--from-file` считывает содержимое файла байт-в-байт, сохраняя бинарную целостность:

```bash
# Создание секрета из конкретного файла с переопределением имени ключа:
kubectl create secret generic deployer-ssh-key \
  --namespace=ci-cd \
  --from-file=id_ed25519=/home/deployer/.ssh/id_ed25519
# → secret/deployer-ssh-key created

# Создание секрета со всеми файлами каталога (имена файлов станут ключами):
# Каталог /opt/app/certs содержит: ca.pem, tls.crt, tls.key
kubectl create secret generic internal-pki \
  --namespace=monitoring \
  --from-file=/opt/app/certs/
# → secret/internal-pki created
```

#### Создание из .env-файлов (--from-env-file)

Файл формата `.env` позволяет импортировать набор переменных за одну операцию:

```bash
cat << 'EOF' > /tmp/app.env
DB_HOST=192.168.10.50
DB_PORT=5432
DB_NAME=analytics_prod
# Комментарии игнорируются
API_KEY=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
EOF

kubectl create secret generic app-env-config \
  --namespace=production \
  --from-env-file=/tmp/app.env
# → secret/app-env-config created

# Обязательная очистка временного файла
shred -u /tmp/app.env
```

**Ограничения формата `--from-env-file`:**
- Разделителем служит первый символ `=`. Имя ключа должно быть валидным идентификатором C/Bash (латиница, цифры, `_`). Имена с дефисами (`DB-HOST=...`) вызовут ошибку парсера.
- Многострочные значения не поддерживаются.
- **Запрет смешивания:** флаг `--from-env-file` нельзя объединять с `--from-file` или `--from-literal` в рамках одной команды CLI.

#### Потоковая передача из stdin без сохранения на диск

Для безопасной автоматизации в CI/CD раннерах значения передаются через конвейер напрямую в память процесса:

```bash
# Генерация криптографически стойкого пароля и запись через pipe
openssl rand -base64 32 | tr -d '\n' | kubectl create secret generic redis-auth \
  --namespace=caching \
  --from-file=redis-password=/dev/stdin
# → secret/redis-auth created
```

#### Добавление хеша содержимого к имени (--append-hash)

Флаг `--append-hash` вычисляет SHA256 от ключей и данных секрета и добавляет 10-значный суффикс к имени объекта:

```bash
kubectl create secret generic api-token \
  --namespace=production \
  --from-literal=token='Bearer-Token-X92' \
  --append-hash
# → secret/api-token-2k6d2m94t5 created
```
Это поведение полностью аналогично генераторам Kustomize и позволяет избегать коллизий при обновлении.

---

### Императивное создание типизированных секретов

#### Секрет TLS/HTTPS (подкоманда `tls`)

Команда `kubectl create secret tls` выполняет автоматическую валидацию соответствия сертификата приватному ключу:

```bash
# Создание TLS-секрета для Ingress / Gateway API
kubectl create secret tls ingress-wildcard-tls \
  --namespace=gateway \
  --cert=/etc/ssl/certs/fullchain.pem \
  --key=/etc/ssl/certs/privkey.pem
# → secret/ingress-wildcard-tls created
```

**Особенности работы с сертификатами:**
1. **Порядок сертификатов в цепочке (Chained PEM):** в файле `fullchain.pem` первым должен следовать конечный листовой сертификат (Leaf/Server Certificate), затем промежуточные сертификаты CA (Intermediate CA), и в конце — корневой сертификат (Root CA). Если нарушить порядок, валидация вернет ошибку:
   ```
   error: failed to load key pair tls: private key does not match public key
   ```
2. **Парольная фраза:** приватный ключ не должен быть защищен паролем (passphrase). Если ключ зашифрован, его необходимо предварительно расшифровать:
   ```bash
   openssl rsa -in encrypted.key -out decrypted.key
   ```

#### Секрет приватного реестра (подкоманда `docker-registry`)

Создание секрета типа `kubernetes.io/dockerconfigjson` для скачивания образов контейнеров (`imagePullSecrets`):

```bash
# Подключение к On-Premise реестру Harbor / Nexus / GitLab Registry
kubectl create secret docker-registry harbor-pull-secret \
  --namespace=production \
  --docker-server=registry.internal.company.lan:5000 \
  --docker-username=robot-k8s-deployer \
  --docker-password='HarborRobotPassword123' \
  --docker-email=devops@internal.company.lan
# → secret/harbor-pull-secret created
```

**Проверка сгенерированного секрета:**
```bash
kubectl get secret harbor-pull-secret -n production -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .
# → {
# →   "auths": {
# →     "registry.internal.company.lan:5000": {
# →       "username": "robot-k8s-deployer",
# →       "password": "HarborRobotPassword123",
# →       "email": "devops@internal.company.lan",
# →       "auth": "cm9ib3QtazhzLWRlcGxveWVyOkhhcmJvclJvYm90UGFzc3dvcmQxMjM="
# →     }
# →   }
# → }
```

#### Типизированные секреты SSH и Basic Auth (через `generic --type`)

Поскольку отдельных подкоманд `ssh-auth` и `basic-auth` в `kubectl` нет, используется флаг `--type`:

```bash
# 1. SSH Auth Secret (для Git-sync, ArgoCD repo-creds):
kubectl create secret generic git-deploy-key \
  --namespace=argocd \
  --type=kubernetes.io/ssh-auth \
  --from-file=ssh-privatekey=/home/ci/.ssh/id_ed25519
# → secret/git-deploy-key created

# 2. Basic Auth Secret (для ingress-nginx basic auth или API):
kubectl create secret generic internal-admin-auth \
  --namespace=ingress-nginx \
  --type=kubernetes.io/basic-auth \
  --from-literal=username='opsadmin' \
  --from-literal='password=ComplexVaultManagedPassword987!'
# → secret/internal-admin-auth created
```

---

### Декларативное создание (YAML-манифесты)

#### Базовый манифест Opaque с полями stringData и data

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-database-credentials
  namespace: backend
  labels:
    app.kubernetes.io/name: payment-service
    app.kubernetes.io/component: database
    app.kubernetes.io/managed-by: manual
  annotations:
    security.internal/owner: "devops-team"
    security.internal/rotation-interval: "90d"
type: Opaque
stringData:
  DB_USER: "payment_app"
  DB_PASS: "SuperSecurePlainTextPassword"
  DB_URL: "postgresql://10.244.5.12:5432/payments"
data:
  # Бинарный Java Keystore или закодированные данные
  custom-keystore.jks: |
    /u3+7QAAAAIAAAABAAAAAQAFYWRtaW4AAAFo...
```

#### Манифест Docker Registry для нескольких On-Premise реестров

Если Pod должен скачивать разные слои из нескольких корпоративных реестров (Harbor и локальный Mirror), формируется манифест с объединенным `.dockerconfigjson`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: multi-registry-creds
  namespace: production
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {
      "auths": {
        "harbor.company.lan": {
          "auth": "cm9ib3QtaGFyYm9yOkNvbXBsZXhQYXNzMQ=="
        },
        "nexus.mirror.company.lan:8443": {
          "auth": "Y2ktcmVhZGVyOkNvbXBsZXhQYXNzMg=="
        }
      }
    }
```

#### Манифест Bootstrap Token для присоединения узлов кластера (kubeadm)

Секрет типа `bootstrap.kubernetes.io/token` создается в пространстве имен `kube-system` для авторизации новых Worker-узлов при масштабировании Bare-Metal кластера:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: bootstrap-token-9b2f4c
  namespace: kube-system
type: bootstrap.kubernetes.io/token
stringData:
  token-id: "9b2f4c"
  token-secret: "81e94a5c6d3f0b21"
  expiration: "2026-11-01T00:00:00Z"
  usage-bootstrap-authentication: "true"
  usage-bootstrap-signing: "true"
  auth-extra-groups: "system:bootstrappers:kubeadm:default-node-token"
  description: "Temporary join token for worker-node-04"
```

#### Манифест постоянного ServiceAccount Token

Для интеграции сторонних Bare-Metal сервисов (мониторинг, скрипты автоматизации), которым требуется постоянный сервисный токен:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: prometheus-scraper-token
  namespace: monitoring
  annotations:
    kubernetes.io/service-account.name: "prometheus-k8s"
type: kubernetes.io/service-account-token
```
> После применения манифеста `kube-controller-manager` автоматически сгенерирует ключи `token`, `ca.crt` и `namespace` и запишет их в поле `data`.

---

### Генерация через Kustomize (secretGenerator)

Генератор `secretGenerator` в `kustomization.yaml` является стандартом декларативного управления секретами в GitOps:

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

generatorOptions:
  disableNameSuffixHash: false # false (по умолчанию): хеш содержимого ДОБАВЛЯЕТСЯ к имени
  labels:
    managed-by: gitops-engine

secretGenerator:
  # 1. Из литералов
  - name: api-service-creds
    type: Opaque
    literals:
      - API_KEY=94a7cb9820f1a4e58b90
      - API_SECRET=3f4e9102c8b76a

  # 2. Из .env файла
  - name: db-environment
    envs:
      - configs/prod.env

  # 3. Из файлов сертификатов (TLS)
  - name: ingress-internal-tls
    type: kubernetes.io/tls
    files:
      - tls.crt=certs/server.crt
      - tls.key=certs/server.key
```

**Механика работы суффикса хеша (Suffix Hash):**
- Kustomize вычисляет детерминированный SHA256 хеш содержимого секрета и добавляет его к имени (например, `api-service-creds-f7b58m94k2`).
- При изменении любого значения в `configs/prod.env` генерируется новое имя объекта Secret.
- Kustomize автоматически обновляет все ссылки на этот Secret в манифестах `Deployment`, `StatefulSet` и `Pod`, которые включены в ту же сборку.
- При выполнении `kubectl apply` Kubernetes выполняет **Rolling Update** подов, гарантируя своевременное перечитывание обновленных секретов приложением.

**Управление поведением (behavior):**
В оверлеях Kustomize можно переопределять секреты с помощью директивы `behavior`:
- `create` (по умолчанию) — создание нового секрета.
- `replace` — полная замена базового секрета оверлейным.
- `merge` — объединение ключей базового секрета и оверлея.

---

### Обновление и патчинг (Patching & Server-Side Apply)

#### Точечное обновление через `kubectl patch`

Для изменения конкретного ключа без пересоздания всего объекта:

```bash
# 1. Обновление через stringData (JSON merge patch по умолчанию):
kubectl patch secret app-database-credentials -n backend \
  -p '{"stringData":{"DB_PASS":"NewRotatedPassword2026!"}}'
# → secret/app-database-credentials patched

# 2. Обновление бинарного ключа в data (требуется предварительное кодирование в Base64):
ENCODED_VAL=$(echo -n 'NewRotatedPassword2026!' | base64)
kubectl patch secret app-database-credentials -n backend \
  -p "{\"data\":{\"DB_PASS\":\"${ENCODED_VAL}\"}}"
# → secret/app-database-credentials patched

# 3. Удаление конкретного устаревшего ключа через JSON Patch (RFC 6902):
kubectl patch secret app-database-credentials -n backend --type='json' \
  -p='[{"op": "remove", "path": "/data/DB_URL"}]'
# → secret/app-database-credentials patched
```

#### Server-Side Apply vs Client-Side Apply

| Критерий | Client-Side Apply (`kubectl apply -f`) | Server-Side Apply (`kubectl apply --server-side -f`) |
| :--- | :--- | :--- |
| **Где рассчитывается diff** | На стороне клиента (kubectl) | На стороне `kube-apiserver` |
| **Аннотация `last-applied-configuration`** | Добавляется всегда; **содержит Base64-секрет целиком** | **Не используется**; отсутствует риск утечки секрета в аннотации |
| **Управление полями** | Нет разделения владения полями | Отслеживается через `metadata.managedFields` |
| **Конфликты полей** | Последний пишущий перезаписывает всё | API Server отклоняет запрос при конфликте с другим менеджером (ArgoCD/Flux) |

```bash
# Рекомендуемый способ декларативного применения манифеста Secret:
kubectl apply --server-side -f secret-manifest.yaml --field-manager=devops-admin
# → secret/app-database-credentials serverside-applied
```

---

### Копирование и синхронизация секретов между Namespace

Секреты ограничены своим `namespace`. Для тиражирования TLS-сертификата или ключа реестра (`imagePullSecret`) в другие пространства имен используются следующие паттерны:

#### 1. Чистый экспорт/импорт через CLI

При копировании необходимо удалить системные поля управления состоянием (`resourceVersion`, `uid`, `creationTimestamp`, `managedFields`, `namespace`):

```bash
kubectl get secret wildcard-tls -n ingress-system -o json | \
  jq 'del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .metadata.namespace, .metadata.managedFields)' | \
  kubectl apply -n payment-production -f -
# → secret/wildcard-tls created
```

#### 2. Автоматическая репликация (Kubernetes Reflector)

Для On-Premise кластеров без облачных сервисов рекомендуется развертывание оператора Reflector (`emberstack/kubernetes-reflector`). Репликация настраивается через аннотации в исходном секрете:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: corporate-wildcard-tls
  namespace: ingress-system
  annotations:
    reflector.v1.k8s.io/reflection-allowed: "true"
    reflector.v1.k8s.io/reflection-allowed-namespaces: "payment-.*,monitoring,logging"
    reflector.v1.k8s.io/reflection-auto-enabled: "true"
type: kubernetes.io/tls
data:
  tls.crt: ...
  tls.key: ...
```
Оператор автоматически создаст и будет синхронизировать зеркальные копии Secret во всех соответствующих пространствах имен при ротации сертификата.

---

## Операции и команды

Справочник базовых операций инспекции, валидации и экспорта секретов:

| Операция | Команда CLI | Ожидаемый результат / Назначение |
| :--- | :--- | :--- |
| **Список секретов** | `kubectl get secrets -n production` | Таблица секретов с типами, количеством ключей и возрастом |
| **Детали объекта** | `kubectl describe secret my-secret -n production` | Метаданные и имена ключей с размерами в байтах (без раскрытия значений) |
| **Декодирование ключа** | `kubectl get secret my-secret -n production -o jsonpath='{.data.password}' \| base64 -d; echo` | Вывод расшифрованного значения ключа в терминал |
| **Список всех ключей** | `kubectl get secret my-secret -n production -o jsonpath='{.data}' \| jq 'keys'` | Массив имен ключей в формате JSON |
| **Экспорт всех ключей** | `kubectl get secret my-secret -n production -o json \| jq -r '.data \| to_entries[] \| "\(.key) \(.value)"' \| while read k v; do echo "$v" \| base64 -d > "$k"; done` | Сохранение каждого ключа в отдельный файл в текущем каталоге |
| **Проверка RBAC** | `kubectl auth can-i create secrets --namespace=production` | Проверка прав текущего контекста (`yes` или `no`) |
| **Diff перед применением** | `kubectl diff -f secret.yaml` | Просмотр планируемых изменений полей перед записью |
| **Удаление секрета** | `kubectl delete secret my-secret -n production` | Удаление объекта (`secret "my-secret" deleted`) |
| **Удаление по селектору** | `kubectl delete secrets -l environment=ephemeral -n test` | Пакетное удаление секретов временных стендов |

---

## Диагностика и устранение неполадок

### Сводная таблица типичных ошибок при создании

| Симптом / Текст ошибки | Первопричина | Пошаговое решение |
| :--- | :--- | :--- |
| `Error: secrets "xxx" already exists` | Попытка выполнить `kubectl create` для объекта, который уже зарегистрирован в namespace | Используйте `kubectl apply` вместо `create`, добавьте `--dry-run=client -o yaml \| kubectl apply -f -`, либо удалите старый объект |
| `error: failed to load key pair tls: private key does not match public key` | Приватный ключ не соответствует публичному сертификату при `kubectl create secret tls`, либо нарушен порядок цепочки | Проверьте публичные ключи сертификата и приватного ключа через OpenSSL (см. диагностический блок ниже) |
| `error: failed to parse private key: ...` | Приватный ключ защищен парольной фразой (Passphrase) | Снимите пароль: `openssl rsa -in enc.key -out dec.key` и передайте расшифрованный файл |
| `parse error in --from-env-file ... key name contains invalid characters` | Файл `.env` содержит строки с дефисами (`DB-USER=...`) или спецсимволы | Приведите имена к формату латинских букв, цифр и `_`; для несовместимых имен используйте `--from-file=KEY=PATH` |
| `from-env-file cannot be combined with from-file or from-literal` | В одной команде `kubectl create secret` смешаны флаги разных источников | Разбейте команду на несколько вызовов с последующим `kubectl patch` или используйте генераторы Kustomize |
| `Error from server (RequestEntityTooLarge): ... limit 1048576 bytes` | Размер полезной нагрузки секрета превысил 1 MiB (жесткий лимит транзакции etcd) | Вынесите бинарные артефакты в хранилище объектов (MinIO / Ceph S3), монтируйте большие файлы через PVC |
| `Error from server (Forbidden): secrets is forbidden: User "xxx" cannot create resource` | Недостаточно прав в Role / RoleBinding пользователя или ServiceAccount | Настройте RBAC: добавьте правило `apiGroups: [""]`, `resources: ["secrets"]`, `verbs: ["create"]` для целевого namespace |
| `error: unknown command "ssh-auth" for "kubectl create secret"` | Попытка вызвать несуществующую подкоманду `kubectl create secret ssh-auth` | Используйте `kubectl create secret generic name --type=kubernetes.io/ssh-auth --from-file=...` |
| Приложение получает неверный пароль / ошибку аутентификации | В пароль попал скрытый байт переноса строки `\n` (`0x0A`) или `\r` (`0x0D`) | Проверьте наличие скрытых символов через `cat -A` и пересоздайте секрет через `echo -n` |
| Поле `stringData` не отображается после создания манифеста | Ожидаемое поведение Kubernetes API | `stringData` — write-only поле. Проверяйте сохраненные данные через `kubectl get secret name -o jsonpath='{.data}'` |

### Проверка скрытых символов и переносов строк

Если приложение отклоняет пароль из смонтированного секрета:

```bash
# 1. Извлечение значения и инспекция непечатных символов:
kubectl get secret app-database-credentials -n backend \
  -o jsonpath='{.data.DB_PASS}' | base64 -d | cat -A
# Если в выводе присутствует символ '$' на отдельной строке или '^M' — в значении содержится перевод строки:
# admin_pass$  <-- '$' указывает на завершающий 0x0A

# 2. Исправление секрета через patch со строгим подавлением перевода строки:
kubectl patch secret app-database-credentials -n backend \
  -p "{\"data\":{\"DB_PASS\":\"$(echo -n 'CorrectPasswordNoNewline' | base64)\"}}"
# → secret/app-database-credentials patched
```

### Диагностика и сопоставление X.509 сертификата и TLS-ключа

До отправки сертификатов в Kubernetes API убедитесь, что публичный ключ сертификата математически соответствует приватному ключу:

```bash
# Извлечение публичных ключей из сертификата и приватного ключа
PUB_FROM_CERT=$(openssl x509 -noout -pubkey -in server.crt | openssl sha256)
PUB_FROM_KEY=$(openssl pkey -pubout -in server.key 2>/dev/null | openssl sha256)

if [ "$PUB_FROM_CERT" = "$PUB_FROM_KEY" ]; then
    echo "OK: Пара сертификат/ключ валидна и готова к загрузке в Secret"
else
    echo "FAIL: Приватный ключ не соответствует сертификату!"
fi
# → OK: Пара сертификат/ключ валидна и готова к загрузке в Secret
```

### Проверка валидности .dockerconfigjson

Для проверки корректности учетных данных секрета реестра без создания тестового Pod:

```bash
# Извлечение блока auth и декодирование логина/пароля
kubectl get secret harbor-pull-secret -n production \
  -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq -r '.auths[].auth' | base64 -d
# → robot-k8s-deployer:HarborRobotPassword123
```

---

## Лучшие практики (Best Practices)

1. **GitOps без облачных сервисов (On-Premise Best Practices):**
   - Никогда не храните манифесты Secret в системе контроля версий Git в незашифрованном виде.
   - Используйте **[SOPS](../../../Security/Tools/sops_overview.md)** с локальными ключами `age` или корпоративным PGP/GPG кольцом ключей.
   - Используйте **[Sealed Secrets](../../Security/sealed_secrets_overview.md)** от Bitnami: секреты шифруются асимметричным публичным ключом контроллера кластера и могут безопасно коммититься в репозиторий Git.
   - Для масштабных On-Premise инсталляций применяйте **[External Secrets Operator (ESO)](external_managers.md)** с self-hosted инстансом HashiCorp Vault.

2. **Предотвращение утечек из Shell History:**
   - Не передавайте продакшн-пароли через флаг `--from-literal` в интерактивном терминале.
   - Используйте передачу через stdin: `echo -n "$SECRET" | kubectl create secret ... --from-file=key=/dev/stdin`.
   - Внедряйте утилиты сканирования репозиториев на предкоммитном этапе: `gitleaks`, `trivy` или `detect-secrets`.

3. **Использование `immutable: true` для постоянных конфигураций:**
   - Помечайте сертификаты удостоверяющих центров (Root CA), токены webhook-провайдеров и статические ключи как `immutable: true`.
   - Это гарантирует защиту от случайной перезаписи и оптимизирует нагрузку на Control Plane.

4. **Хеширование имен при развертывании:**
   - Используйте генераторы Kustomize (`secretGenerator`) или флаг `kubectl create --append-hash`.
   - Изменение конфигурации порождает новое имя объекта, запуская бессбойный Rolling Update подов вместо непредсказуемой частичной горячей замены файлов.

5. **Принцип наименьших привилегий (RBAC):**
   - Блокируйте кластерные права `get`, `list`, `watch` на ресурс `secrets` для сервисных аккаунтов приложений.
   - Ограничивайте доступ разработчиков с помощью RBAC-правил с привязкой к конкретным именам (`resourceNames`):
     ```yaml
     rules:
     - apiGroups: [""]
       resources: ["secrets"]
       resourceNames: ["app-config-secret"]
       verbs: ["get", "patch"]
     ```

6. **Декларативное управление через Server-Side Apply:**
   - Используйте `kubectl apply --server-side` вместо стандартного `kubectl apply`, чтобы исключить сохранение открытых секретов в аннотации `kubectl.kubernetes.io/last-applied-configuration`.

---

## Дополнительная информация

### Связанные разделы базы знаний

- **[Основы Secret](secrets_basics.md)** — архитектура объекта, базовые концепции и типы.
- **[Использование Secret](using_secrets.md)** — варианты монтирования томов, переменные окружения и нюансы обновления данных в Pod.
- **[Безопасность Secret](security.md)** — шифрование в etcd, аудит доступа и RBAC.
- **[Хранение в etcd](etcd_storage.md)** — настройка `EncryptionConfiguration`, провайдеры KMS и производительность базы данных.
- **[Внешние менеджеры секретов](external_managers.md)** — интеграция с HashiCorp Vault и External Secrets Operator (ESO).
- **[Секреты в Helm](helm_secrets.md)** — плагин helm-secrets, защита values-файлов.
- **[Генераторы Kustomize](../../ToolsUtilities/kustomize/kustomize_generators.md)** — детальный обзор secretGenerator и ConfigMapGenerator.
- **[Sealed Secrets](../../Security/sealed_secrets_overview.md)** — шифрование секретов для GitOps через контроллер Bitnami.
- **[SOPS](../../../Security/Tools/sops_overview.md)** — шифрование файлов с использованием age и PGP.
