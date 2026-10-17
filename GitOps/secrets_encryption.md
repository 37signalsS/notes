# GitOps: Управление секретами и шифрование

**Актуально для:** Mozilla SOPS v3.13.x, Bitnami Sealed Secrets v0.40.x, External Secrets Operator (ESO) v1.x (API external-secrets.io/v1), HashiCorp Vault 1.18–1.21 / OpenBao 2.x, Argo CD v3.5+, Kubernetes 1.30–1.34+ (on-premise / bare-metal)

Хранение секретов — одна из центральных архитектурных задач в GitOps. Поскольку Git является единственным источником истины (Source of Truth), хранить в нем пароли, сертификаты и токены в открытом виде категорически недопустимо. Данное руководство описывает подходы, инструменты и эксплуатационные практики для безопасного управления секретами в рамках методологии GitOps в локальной, частной и on-premise инфраструктуре.

## Определения

- **Секрет (Secret)**: Конфиденциальные данные приложения или инфраструктуры (пароли СУБД, приватные TLS-ключи, API-токены, учетные записи служебных сервисов).
- **Шифрование в Git (Encryption-in-Git)**: Архитектурный подход, при котором зашифрованные шифротексты секретов коммитятся непосредственно в Git-репозиторий. Расшифровка выполняется внутри целевого кластера GitOps-контроллером или специализированным оператором.
- **Мастер-ключ (KEK — Key Encryption Key)**: Корневой ключ, используемый для шифрования ключей данных. Хранится строго за пределами Git (в локальном HashiCorp Vault / OpenBao, аппаратном модуле HSM/PKCS#11 или на защищенном носителе).
- **Ключ данных (DEK — Data Encryption Key)**: Случайный симметричный ключ (обычно AES-256-GCM), которым зашифрованы непосредственно полезные данные секрета. DEK хранится рядом с зашифрованными данными внутри файла, но сам зашифрован с помощью одного или нескольких KEK (конвертная криптография).
- **KMS (Key Management Service / Server)**: Система управления ключами шифрования и криптографическими операциями (например, on-premise HashiCorp Vault Transit Engine, OpenBao, программные или аппаратные модули HSM).
- **age (Actually Good Encryption)**: Современный криптографический инструмент и формат асимметричного шифрования (ключи X25519), используемый как компактная, надежная и быстрая альтернатива устаревающему PGP для SOPS.
- **External Secrets Operator (ESO)**: Kubernetes-оператор, реализующий модель асинхронной синхронизации (pull-модель): считывает значения из внешних систем хранения (HashiCorp Vault, OpenBao) и генерирует нативные объекты `Secret` внутри кластера.
- **SecretStore / ClusterSecretStore**: CRD оператора ESO, описывающий конфигурацию подключения к внешнему хранилищу секретов. `ClusterSecretStore` действует на уровне всего кластера, `SecretStore` изолирован пределами одного пространства имен.
- **ExternalSecret**: Декларативный манифест ESO, описывающий связь между внешним путем хранилища и ключами создаваемого нативного `Secret`. В GitOps-репозитории хранится именно этот ресурс вместо значений данных.
- **SealedSecret**: CRD оператора Bitnami Sealed Secrets — манифест с зашифрованными асимметричным публичным ключом данными. Приватный ключ расшифровки существует исключительно в оперативной памяти и хранилище контроллера внутри кластера.
- **Secret Zero**: Проблема первичного секрета — доверенный токен или учетная запись (например, ServiceAccount JWT или AppRole SecretID), необходимый агенту для первоначальной аутентификации во внешнем хранилище секретов.
- **Rekey / Re-encryption**: Процедура перешифрования существующих шифротекстов новым мастер-ключом при компрометации или плановой ротации KEK без изменения открытых значений секретов.
- **Дрейф секретов (Drift)**: Рассогласование между значением секрета во внешнем хранилище (или Git) и текущим состоянием нативного объекта `Secret` в etcd кластера.
- **Шифрование на уровне etcd (Encryption at Rest)**: Механизм Kubernetes API-сервера (`EncryptionConfiguration`), прозрачно шифрующий объекты `Secret` перед записью в базу данных etcd. Является вторым эшелоном обороны кластера.

## Базовые концепции и архитектура

### Проблема: Секреты в Git и "Отравленная история"

Стандартный манифест Kubernetes `Secret` кодирует значения алгоритмом Base64 (`echo -n "pass" | base64`), что является способом сериализации байтов, а не криптографической защитой. Попадание открытого секрета в коммит Git компрометирует его навсегда.

> [!WARNING]
> Удаление файла или его шифрование в следующем коммите не удаляет открытый текст из истории Git (`git log`). Любой участник с правами на чтение репозитория или атакующий, получивший доступ к архивам и зеркалам, извлекает секрет из истории.

**Регламент реагирования при компрометации секрета в Git (строгая последовательность):**

1. **Немедленная инвалидация и ротация секрета в целевой системе**: Смена пароля в базе данных, перевыпуск токена или аннулирование сертификата. Пока скомпрометированный секрет валиден, любые операции с Git бессмысленны.
2. **Очистка истории Git-репозитория**: Использование `git-filter-repo` для полного вырезания значения из всех коммитов и тегов:

```bash
# Формирование файла замены чувствительной строки
printf 'REAL_PRODUCTION_PASSWORD_123==>REDACTED\n' > replacements.txt

# Перезапись всей истории репозитория локально
git filter-repo --replace-text replacements.txt --force
# → Parsed 42 commits
# → Rewriting commits...
# → Completely finished after 0.12 seconds.

# Принудительная отправка перезаписанной истории во все ветки
git push origin --force --all
# → Everything up-to-date
git push origin --force --tags
```

3. **Сброс локальных копий**: Все инженеры обязаны выполнить свежее клонирование репозитория; старые форки и кэши CI-раннеров подлежат принудительной очистке.
4. **Ужесточение превентивного контроля**: Активация pre-commit хуков и блокирующих стадий сканирования в CI/CD (gitleaks, trufflehog).

### Архитектурные модели доставки секретов

В on-premise GitOps-инфраструктуре применяются три модели доставки секретов в рабочие нагрузки:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   Архитектурные модели доставки секретов                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Push / In-Memory Decryption (Argo CD native SOPS, CMP/AVP):                │
│    Git (Зашифрованный файл) ──▶ Controller Memory (Расшифровка) ──▶ etcd    │
│                                                                             │
│ 2. Operator Pull (External Secrets Operator):                               │
│    Git (ExternalSecret CR)  ──▶ K8s API ──▶ ESO ──[Vault API]──▶ etcd      │
│                                                                             │
│ 3. On-Demand / In-Memory Mount (Secrets Store CSI Driver):                  │
│    Pod Spec (CSI Volume)    ──▶ Kubelet Node Driver ──[Vault API]──▶ tmpfs  │
│                                 (минует запись в etcd)                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

1. **Модель расшифровки при генерации манифестов (Push / In-memory Interpolation)**:
   - В Git коммитятся файлы с зашифрованными значениями (SOPS) или манифесты с плейсхолдерами (Argo CD Vault Plugin).
   - GitOps-контроллер (argocd-repo-server в Argo CD) расшифровывает манифест в оперативной памяти перед отправкой в Kubernetes API.
   - *Плюсы:* Манифесты версионируются в едином репозитории, строгая синхронизация с ревизией Git.
   - *Минусы:* etcd хранит расшифрованные объекты `Secret`; контроллер GitOps должен обладать доступом к приватным ключам age или токенам Vault.
2. **Модель внутрикластерного оператора (Operator Pull)**:
   - В Git хранятся декларативные CRD-манифесты (`ExternalSecret`), содержащие пути к секретам в HashiCorp Vault / OpenBao.
   - Оператор ESO внутри кластера периодически опрашивает хранилище и синхронизирует значения в нативные `Secret`.
   - *Плюсы:* В Git вообще нет шифротекстов, централизованный аудит запросов на стороне Vault, бесшовная ротация по расписанию.
   - *Минусы:* Зависимость от доступности кластера Vault; секреты материализуются в etcd.
3. **Модель прямого монтирования в память (Sidecar / Secrets Store CSI Driver)**:
   - Секреты монтируются напрямую в файловую систему пода (`tmpfs`) драйвером CSI или подставляются sidecar-агентом (Vault Agent).
   - *Плюсы:* Секреты никогда не сохраняются в базе etcd и недоступны через `kubectl get secrets`.
   - *Минусы:* Повышенные накладные расходы на каждый узел (DaemonSet CSI); приложение обязано уметь перечитывать файлы с диска при обновлении.

### Сравнение решений для локальной и on-premise инфраструктуры

| Критерий | Mozilla SOPS + age | Bitnami Sealed Secrets | External Secrets Operator (ESO) | Secrets Store CSI Driver |
| :--- | :--- | :--- | :--- | :--- |
| **Где хранятся данные** | В Git (зашифрованы значения) | В Git (зашифрован манифест) | Вне Git (HashiCorp Vault / OpenBao) | Вне Git (HashiCorp Vault / OpenBao) |
| **Ключ расшифровки** | age-ключ (в K8s Secret / KMS) | RSA-ключ контроллера (в etcd) | Kubernetes ServiceAccount / AppRole | ServiceAccount JWT / AppRole |
| **Присутствие в etcd** | Да (нативный `Secret`) | Да (нативный `Secret`) | Да (нативный `Secret`) | **Нет** (только RAM / tmpfs узла) |
| **Внешняя инфраструктура** | Не требуется (автономно с age) | Не требуется | Обязателен кластер Vault/OpenBao | Обязателен кластер Vault/OpenBao |
| **Аудит чтения секретов** | Отсутствует | Отсутствует | Полный аудит-лог в Vault | Полный аудит-лог в Vault |
| **Ротация данных** | Коммит с `sops updatekeys` | Коммит с `kubeseal --re-encrypt`| **Автоматическая** через Vault + ESO | **Автоматическая** через CSI rotation |
| **Air-gapped поддержка** | Полная (локальный бинарник + age)| Полная | Полная (self-hosted Vault) | Полная (self-hosted Vault) |
| **Сложность эксплуатации** | Низкая / средняя | Низкая | Средняя | Высокая |

### Эшелонированная защита (Defense-in-Depth)

Шифрование данных в Git защищает репозиторий, но не отменяет мер защиты внутри самого кластера Kubernetes:

1. **Уровень репозитория:** Использование SOPS или ESO; блокировка коммитов через pre-commit хуки.
2. **Уровень etcd (Encryption at Rest):** Настройка `EncryptionConfiguration` на мастер-узлах с использованием алгоритмов `aescbc` или провайдера `kms` (интегрированного с локальным Vault через UNIX-сокет). Подробно: [Хранение Secret в etcd](../Kubernetes/Base/secrets/etcd_storage.md).
3. **Уровень RBAC:** Запрет прав `get`, `list`, `watch` на ресурс `secrets` для всех пользователей и служебных аккаунтов, кроме управляющих контроллеров. Подробно: [Безопасность Secret в Kubernetes](../Kubernetes/Base/secrets/security.md).
4. **Уровень аудита:** Включение `AuditSink` или политик аудита Kubernetes API для логирования всех обращений к ресурсам `secrets`.
5. **Уровень оперативной памяти:** Использование `emptyDir: { medium: "Memory" }` или Secrets Store CSI Driver для исключения записи секретов на swap или блочные диски узлов.

---

## Практические сценарии

### Сценарий 1: Mozilla SOPS с ключами age (Стандарт для Argo CD)

SOPS шифрует значения полей в структурированных файлах (YAML, JSON, .env), сохраняя ключи и комментарии в открытом виде. Это позволяет просматривать диффы (`git diff`) без раскрытия конфиденциальных данных.

**Требования к окружению:**
- Утилиты `sops` (v3.13.x) и `age` / `age-keygen` (v1.2.x+).
- Развернутый Argo CD v3.5+ в неймспейсе `argocd` с включенной нативной поддержкой SOPS (входит в состав `argocd-repo-server`).

**1. Генерация пары ключей age:**

```bash
# Создание директории конфигурации
mkdir -p ~/.config/sops/age

# Генерация ключевой пары (приватный ключ защищается правами 0600)
age-keygen -o ~/.config/sops/age/keys.txt
# → Public key: age15k3fuv983z5r77l04r432k428j7y6tqq77p4088x33e50w2c59esf5afl6

chmod 0600 ~/.config/sops/age/keys.txt
```

**2. Создание файла конфигурации правил шифрования `.sops.yaml` в корне репозитория:**

```yaml
creation_rules:
  # Продакшн: рабочий ключ кластера + резервный ключ аварийного восстановления (DR)
  - path_regex: clusters/prod/.*\.enc\.ya?ml$
    age: >-
      age15k3fuv983z5r77l04r432k428j7y6tqq77p4088x33e50w2c59esf5afl6,
      age1backupdr983z5r77l04r432k428j7y6tqq77p4088x33e50w2c59esdrkey0
  # Стейджинг и разработка
  - path_regex: clusters/dev/.*\.enc\.ya?ml$
    age: age1devkey983z5r77l04r432k428j7y6tqq77p4088x33e50w2c59esdevkey1
```

**3. Создание манифеста и шифрование:**

```bash
# Подготовка открытого манифеста
cat <<EOF > clusters/prod/database-secret.enc.yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: default
type: Opaque
stringData:
  DB_USER: "postgres_admin"
  DB_PASSWORD: "HardcodedProductionPassword2026!"
EOF

# Шифрование файла на месте с использованием правил .sops.yaml
sops --encrypt --in-place clusters/prod/database-secret.enc.yaml

# Проверка результата шифрования: структура YAML сохранена, значения зашифрованы
grep "sops:" clusters/prod/database-secret.enc.yaml -A 2
# → sops:
# →     kms: []
# →     age:
```

**4. Экспорт приватного ключа age в `argocd-secret` для нативной расшифровки SOPS:**

Argo CD v3.5+ поддерживает SOPS нативно: ключ шифрования age хранится в системном секрете `argocd-secret` неймспейса `argocd`, и `argocd-repo-server` автоматически расшифровывает закрытые файлы при рендеринге манифестов.

```bash
# Извлечение публичного ключа age из приватного ключа
AGE_PUBKEY=$(grep "^# public key:" $HOME/.config/sops/age/keys.txt | awk '{print $NF}')

# Добавление приватного ключа в argocd-secret (формат: age1...)
kubectl -n argocd patch secret argocd-secret \
  --type merge -p "{\"stringData\":{\"data.agekey\":\"$HOME/.config/sops/age/keys.txt\"}}"
# → secret/argocd-secret patched

# Проверка наличия ключа
kubectl -n argocd get secret argocd-secret -o jsonpath='{.data.agekey}' | base64 -d
# → # created: 2026-10-13T12:00:00Z
# → # public key: age15k3fuv983z5r77l04r432k428j7y6tqq77p4088x33e50w2c59esf5afl6
# → AGlzc2V5...
```

**5. Нативная поддержка SOPS в Argo CD:**

С момента добавления ключа в `argocd-secret` любые SOPS-зашифрованные YAML/JSON-файлы в репозитории Git расшифровываются автоматически на стороне `argocd-repo-server` во время синхронизации. Дополнительных манифестов настройки не требуется — Argo CD сканирует секцию `sops` в каждом зашифрованном файле, извлекает метаданные о получателе (age public key) и использует соответствующий приватный ключ из `argocd-secret`.

Для Helm-чартов с зашифрованными `values` используйте [CMP v2 плагин](argocd_app_of_apps.md#сценарий-6-шифрование-секретов-поверх-helm-через-cmp-v2-и-sops) (см. также `helm_integration.md`, Сценарий 6).

**Валидация работы Argo CD:**

```bash
# Синхронизация приложения с SOPS-секретом
argocd app sync prod-apps
# → Enter the server address (press enter for http://localhost:8080):
# → Enter username of admin:
# → Enter password:
# → Enter 2FA code (press enter for no 2FA code):
# → Enter number of retries (default 3):
# → Enter login method (ssh, https): ssh
# → ...
# → Sync application prod-apps? (y/n): y
# → ✅ Sync operation to prod-apps completed

kubectl get secret db-credentials -n default -o jsonpath='{.data.DB_PASSWORD}' | base64 -d
# → HardcodedProductionPassword2026!
```

---

### Сценарий 2: External Secrets Operator (ESO) и HashiCorp Vault / OpenBao

ESO является стандартом для инфраструктур, где секреты централизованно хранятся в HashiCorp Vault или OpenBao. В GitOps-репозиторий коммитятся только декларативные ссылки.

**Требования к окружению:**
- Установленный ESO v1.x (`apiVersion: external-secrets.io/v1`).
- Развернутый on-premise кластер HashiCorp Vault / OpenBao с включенным движком `kv-v2` по пути `secret/` и настроенным методом аутентификации `kubernetes`.

**1. Настройка аутентификации и политики в Vault:**

```bash
# Создание секретных данных в Vault
vault kv put secret/production/db \
  username="app_user" \
  password="VaultManagedSecurePassword2026!"
# → Key              Value
# → ---              -----
# → created_time     2026-10-13T12:00:00.000000000Z

# Создание политики доступа на чтение
vault policy write eso-prod-policy - <<EOF
path "secret/data/production/*" {
  capabilities = ["read"]
}
EOF

# Привязка роли Kubernetes к ServiceAccount оператора
vault write auth/kubernetes/role/eso-role \
  bound_service_account_names=eso-sa \
  bound_service_account_namespaces=external-secrets \
  policies=eso-prod-policy \
  audience=vault \
  ttl=1h
# → Success! Data written to: auth/kubernetes/role/eso-role
```

**2. Конфигурация `ClusterSecretStore` в кластере Kubernetes:**

```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: "https://vault.internal.corp:8200"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "eso-role"
          serviceAccountRef:
            name: "eso-sa"
            namespace: "external-secrets"
```

**3. Создание манифеста `ExternalSecret` в GitOps-репозитории приложения:**

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: backend-db-secret
  namespace: prod-apps
spec:
  refreshInterval: 15m
  secretStoreRef:
    kind: ClusterSecretStore
    name: vault-backend
  target:
    name: backend-db-credentials
    creationPolicy: Owner
    deletionPolicy: Retain
  data:
    - secretKey: DB_USER
      remoteRef:
        key: production/db
        property: username
    - secretKey: DB_PASS
      remoteRef:
        key: production/db
        property: password
```

**4. Валидация синхронизации:**

```bash
kubectl describe externalsecret backend-db-secret -n prod-apps
# → Status:
# →   Conditions:
# →     Type:   Ready
# →     Status: True
# →     Reason: SecretSynced
# →     Message: Secret was synced

kubectl get secret backend-db-credentials -n prod-apps -o jsonpath='{.data.DB_PASS}' | base64 -d
# → VaultManagedSecurePassword2026!
```

**Автоматическая перезагрузка подов при ротации (Reloader):**

Для автоматического перезапуска приложений при изменении секрета оператором ESO на deployment накладывается аннотация контроллера `stakater/reloader`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-api
  namespace: prod-apps
  annotations:
    reloader.stakater.com/auto: "true"
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: app
          image: internal-registry.corp/apps/backend:v2.4.1
          envFrom:
            - secretRef:
                name: backend-db-credentials
```

---

### Сценарий 3: Argo CD Vault Plugin (AVP) через CMP v2

Argo CD Vault Plugin подставляет реальные значения из Vault вместо плейсхолдеров в оперативной памяти пода `argocd-repo-server` перед применением манифестов.

**1. Конфигурация плагина в ConfigManagementPlugin (CMP v2):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmp-plugin
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: argocd-vault-plugin
    spec:
      version: v1.0
      generate:
        command: ["sh", "-c"]
        args: ["argocd-vault-plugin generate ."]
```

**2. Манифест шаблона в GitOps-репозитории:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: microservice-secrets
  namespace: prod
  annotations:
    avp.plugin.argoproj.io/path: "secret/data/production/microservice"
type: Opaque
stringData:
  API_KEY: <path:secret/data/production/microservice#api_key>
```

**Компромиссы архитектуры AVP vs ESO:**
- AVP не требует развертывания отдельного контроллера ESO в кластере и удобен для команд, использующих исключительно Argo CD.
- Однако AVP расширяет права пода `argocd-repo-server` (требует доступа к Vault) и выполняет повторный рендеринг при каждой синхронизации, создавая пиковую нагрузку на Vault API. ESO изолирует полномочия и синхронизирует секреты асинхронно в фоновом режиме.

---

### Сценарий 4: Secrets Store CSI Driver (Монтирование в RAM пода)

Для приложений с наивысшими требованиями безопасности (исключение попадания секретов в etcd и исключение команды `kubectl get secret`).

**Манифест SecretProviderClass:**

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-db-provider
  namespace: prod-secure
spec:
  provider: vault
  parameters:
    vaultAddress: "https://vault.internal.corp:8200"
    roleName: "eso-role"
    objects: |
      - objectName: "db_password"
        secretPath: "secret/data/production/db"
        secretKey: "password"
```

**Монтирование в под приложения:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
  namespace: prod-secure
spec:
  containers:
    - name: app
      image: internal-registry.corp/secure-app:v1.0.0
      volumeMounts:
        - name: secrets-store-inline
          mountPath: "/mnt/secrets"
          readOnly: true
  volumes:
    - name: secrets-store-inline
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: "vault-db-provider"
```

Секрет существует только как файл в памяти узла (`tmpfs`) по пути `/mnt/secrets/db_password` во время работы пода.

---

### Сценарий 5: Bitnami Sealed Secrets (Автономный кластер)

Подходит для isolated и standalone кластеров, где развертывание и обслуживание внешнего Vault избыточно.

**1. Шифрование секрета на рабочей станции администратора:**

```bash
# Создание сухого прогона Secret и шифрование через kubeseal
kubectl create secret generic payment-gateway-creds \
  --from-literal=api_token='Token-XYZ-998877' \
  --namespace billing \
  --dry-run=client -o yaml \
  | kubeseal --scope strict --format yaml > payment-creds.sealed.yaml
```

Флаг `--scope strict` жестко связывает шифротекст с именем секрета (`payment-gateway-creds`) и пространством имен (`billing`). При попытке применить этот манифест в другом пространстве имен контроллер откажет в расшифровке.

**2. Резервное копирование мастер-ключей (обязательный регламент SRE):**

```bash
# Экспорт активных приватных ключей контроллера из kube-system
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o yaml > sealed-secrets-master-backup.yaml

# Проверка наличия tls.key и tls.crt
grep -E "tls.key|tls.crt" sealed-secrets-master-backup.yaml
# → tls.crt: LS0tLS1CRUdJTi...
# → tls.key: LS0tLS1CRUdJTi...
```

### Сценарий: Sealed Secrets с Argo CD (hub-and-spoke)

В hub-and-spoke топологии контроллер Sealed Secrets разворачивается декларативно через `Application` CR в неймспейсе `argocd` на hub-кластере. Spoke-кластеры подключаются к hub через kubeconfig, зашифрованный в `SealedSecret` и хранимый в Git. Этот паттерн отличается от автономного развертывания ([Сценарий 5](#сценарий-5-bitnami-sealed-secrets-автономный-кластер)) тем, что контроллер управляется Argo CD, разворачивается в `kube-system` (как и в автономном режиме), а kubeconfigы spoke-кластеров встраиваются непосредственно в `Application` CR как `destination.kubeConfig.secretRef`.

**Архитектурная схема:**

```
hub-кластер (Argo CD)
│
├── kube-system namespace
│   ├── sealed-secrets-controller (Application → Deployment)
│   └── sealed-secrets keys (Master Key в Secret)
│
└── GitOps-репозиторий
    ├── argocd/{env}-application.yaml  ← встроенный SealedSecret с kubeconfig
    └── argocd/projects/{env}/applications/spoke/secrets/
        ├── registry-pull-secret.yaml
        └── tls-cert.yaml
```

Контроллер работает в `kube-system` и расшифровывает каждый `SealedSecret`, создавая нативный `Secret`. Приватный ключ никогда не покидает кластер. Vault для этого паттерна не нужен, как и подстановка секретов через CI/CD.

**1. Установка через Argo CD Application:**

Требуется ранее добавленный Helm-репозиторий в Argo CD (через UI или `argocd app create` с `repoURL: https://bitnami.github.io/sealed-secrets`). Внимание: официальный Helm-репозиторий изменился с `bitnami-labs.github.io/sealed-secrets` на `bitnami.github.io/sealed-secrets` — используйте актуальный URL.

```yaml
# argocd/projects/infra/applications/sealed-secrets.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: sealed-secrets
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://bitnami.github.io/sealed-secrets
    chart: sealed-secrets
    targetRevision: "2.x"
    helm:
      values: |
        fullnameOverride: sealed-secrets-controller
  destination:
    server: https://kubernetes.default.svc
    namespace: kube-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace: true
      - ServerSideApply: true
```

Контроллер создаёт ключевую пару RSA и сохраняет её в `Secret` с меткой `sealedsecrets.bitnami.com/sealed-secrets-key` в неймспейсе `kube-system`.

> **Важно:** с `fullnameOverride: sealed-secrets-controller` имя сервиса контроллера становится `sealed-secrets-controller`, а не `sealed-secrets`. При запечатывании через `kubeseal` укажите `--controller-name=sealed-secrets-controller --controller-namespace=kube-system`, иначе kubeseal не найдёт сервис по умолчанию. Подробнее об ошибке `error: cannot get sealed secret service` — в [Sealed Secrets Overview](../../Kubernetes/Security/sealed_secrets_overview.md) (Сценарий 10).

**2. Запечатывание spoke kubeconfig:**

Kubeconfig содержит credentials для доступа к spoke-кластеру. Его нужно запечатать в `SealedSecret` с ключом `value`:

```bash
# 1. Записать kubeconfig во временный файл (НЕ КОММИТИТЬ)
cat > /tmp/spoke-kubeconfig.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: dev-kubeconfig
  namespace: dev
type: Opaque
stringData:
  value: |
    apiVersion: v1
    kind: Config
    clusters:
    - name: dev-cluster
      cluster:
        server: https://dev-cluster.example.com:6443
        certificate-authority-data: LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t
    users:
    - name: argocd
      user:
        client-certificate-data: LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t
        client-key-data: LS0tLS1CRUdJTiBSU0EgUFJJV...
    contexts:
    - name: dev
      context:
        cluster: dev-cluster
        user: argocd
    current-context: dev
EOF

# 2. Запечатать (kubeseal получит сертификат с hub-кластера)
kubeseal \
  --format yaml \
  --controller-name=sealed-secrets-controller \
  --controller-namespace kube-system \
  --kubeconfig .kubeconfigs/infra.yaml \
  < /tmp/spoke-kubeconfig.yaml \
  > argocd/projects/dev/applications/spoke/secrets/dev-kubeconfig.yaml

# 3. Удалить файл с открытым секретом
rm /tmp/spoke-kubeconfig.yaml
```

**Оффлайн-режим (без доступа к hub-кластеру):**

```bash
# Получить и сохранить публичный сертификат (требуется один раз)
kubeseal \
  --fetch-cert \
  --controller-name=sealed-secrets-controller \
  --controller-namespace kube-system \
  --kubeconfig .kubeconfigs/infra.yaml \
  > .kubeconfigs/sealed-secrets-infra.pem

# Запечатать офлайн, используя сохранённый сертификат
kubeseal \
  --format yaml \
  --cert .kubeconfigs/sealed-secrets-infra.pem \
  < /tmp/spoke-kubeconfig.yaml \
  > argocd/projects/dev/applications/spoke/secrets/dev-kubeconfig.yaml
```

Файл `.pem` можно хранить в репозитории — он не секретный. Механизм шифрования (RSA-OAEP + AES-GCM), scope и ротация ключей — в [Sealed Secrets Overview](../../Kubernetes/Security/sealed_secrets_overview.md).

**Привязка к namespace:** `SealedSecret` привязан к namespace — данные, зашифрованные для namespace `dev`, нельзя расшифровать в другом namespace. Если секрет нужен в нескольких namespace, запечатайте его отдельно для каждого.

**3. Репозиторная структура:**

| Что | Путь |
|---|---|
| Spoke kubeconfigs | `argocd/{env}-application.yaml` — встроенный `SealedSecret` рядом с `Namespace` и `Application` CR |
| Docker registry pull secrets | `argocd/projects/{env}/applications/spoke/secrets/` |
| TLS-сертификаты | `argocd/projects/{env}/applications/spoke/secrets/` |
| Vault token для Terraform | `argocd/projects/infra/applications/terraform/vault-token-sealed.yaml` |

Самые важные секреты — kubeconfigы spoke-кластеров. Каждый встраивается прямо в `argocd/{env}-application.yaml` вместе с `Namespace` и `Application` CR:

```yaml
# argocd/dev-application.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: dev
---
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: dev-kubeconfig
  namespace: dev
spec:
  encryptedData:
    value: AgB3eVxk...очень-длинный-base64...
  template:
    metadata:
      name: dev-kubeconfig
      namespace: dev
    type: Opaque
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dev-apps
  namespace: argocd
spec:
  project: default
  source:
    repoURL: git@gitlab.corp.internal:infra/fleet-infra.git
    targetRevision: main
    path: argocd/projects/dev/applications/hub/
  destination:
    server: https://dev-cluster.example.com:6443
    namespace: default
    kubeConfig:
      secretRef:
        name: dev-kubeconfig
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

`Namespace`, `SealedSecret` и ссылающийся на него `Application` находятся в одном файле. `SealedSecret` расшифровывается контроллером в нативный `Secret`, который `Application` использует как `destination.kubeConfig.secretRef` для синхронизации spoke-кластера.

**4. Добавление нового spoke-кластера:**

Новый spoke-кластер добавляется копированием и переименованием:

```bash
# 1. Скопировать манифест из существующего env
cp argocd/dev-application.yaml argocd/staging-application.yaml

# 2. Запечатать kubeconfig для нового кластера
kubeseal \
  --format yaml \
  --controller-name=sealed-secrets-controller \
  --controller-namespace kube-system \
  --kubeconfig .kubeconfigs/infra.yaml \
  < /tmp/staging-kubeconfig.yaml \
  > argocd/projects/staging/applications/spoke/secrets/staging-kubeconfig.yaml

# 3. Обновить ссылки в application.yaml
# 4. Commit
```

**5. Обновление kubeconfig spoke-кластера:**

`SealedSecret` нельзя обновить частично — только перезапечатать целиком:

```bash
kubeseal \
  --format yaml \
  --controller-name=sealed-secrets-controller \
  --controller-namespace kube-system \
  --kubeconfig .kubeconfigs/infra.yaml \
  < /tmp/updated-kubeconfig.yaml \
  > argocd/projects/dev/applications/spoke/secrets/dev-kubeconfig.yaml
```

Новый `encryptedData` заменяет старый. Контроллер обнаружит изменение и пересоздаст нативный `Secret`.

Антипаттерн — править поле `encryptedData` вручную. Шифротекст не делится по ключам: при изменении любого значения меняется весь блок данных. Просто перезапечатайте секрет.

**Резервное копирование и ротация ключей:**

Контроллер по умолчанию ротирует ключ каждые 30 дней, сохраняя старые для расшифровки существующих `SealedSecret`. Резервную копию ключей делают из неймспейса `kube-system`:

```bash
# Бэкап ключей контроллера
kubectl get secret \
  -n kube-system \
  -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o yaml > sealed-secrets-keys-backup.yaml

# Восстановление
kubectl apply -f sealed-secrets-keys-backup.yaml
kubectl rollout restart deployment/sealed-secrets-controller -n kube-system
```

Если удалить контроллер и переустановить, старые приватные ключи пропадут. Миграция на новое железо требует перезапечатывания каждого `SealedSecret` сертификатом нового кластера — подробности в [Sealed Secrets Overview](../../Kubernetes/Security/sealed_secrets_overview.md) (Сценарий 9).

**Устранение ошибок расшифровки:**

```bash
# Логи контроллера
kubectl logs \
  -n kube-system \
  -l app.kubernetes.io/name=sealed-secrets-controller \
  --context=infra-k8s

# Проверка наличия ключей
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key

# Статус конкретного SealedSecret
kubectl describe sealedsecret my-secret -n dev
```

Частые ошибки:

- `no key could decrypt secret` — секрет запечатан другим сертификатом или для другого namespace; перезапечатайте текущим.
- `failed to decrypt` — не совпадает namespace; перезапечатайте для правильного namespace.
- `controller not found` — неверный `--controller-namespace` или `--controller-name`; имя должно совпадать с `fullnameOverride`.

---

## Операции и команды

Сводный справочник регулярных регламентных команд системного администратора и SRE:

| Категория | Команда | Назначение |
| :--- | :--- | :--- |
| **SOPS: Редактирование** | `sops edit clusters/prod/secret.enc.yaml` | Интерактивное редактирование зашифрованного файла в `$EDITOR` |
| **SOPS: Просмотр** | `sops decrypt clusters/prod/secret.enc.yaml` | Расшифровка содержимого в stdout без изменения файла на диске |
| **SOPS: Смена ключей** | `sops updatekeys clusters/prod/secret.enc.yaml` | Перешифрование DEK новыми KEK-получателями из `.sops.yaml` |
| **SOPS: Ротация данных** | `sops rotate -i clusters/prod/secret.enc.yaml` | Генерация нового DEK и полное перешифрование полезных данных |
| **Sealed: Проверка cert** | `kubeseal --fetch-cert > cluster-pub.pem` | Получение текущего публичного сертификата шифрования кластера |
| **Sealed: Ротация KEK** | `kubectl -n kube-system delete pod -l app.kubernetes.io/name=sealed-secrets` | Перезапуск пода контроллера для принудительной проверки ротации |
| **Sealed: Re-encrypt** | `kubeseal --re-encrypt -f old.sealed.yaml > new.sealed.yaml` | Перешифрование SealedSecret актуальным публичным ключом |
| **ESO: Принудительный Sync**| `kubectl annotate es <name> -n <ns> force-sync=$(date +%s) --overwrite` | Принудительный триггер опроса Vault без ожидания refreshInterval |
| **ESO: Статус провайдера**| `kubectl get clustersecretstore vault-backend -o wide` | Проверка доступности подключения к серверу Vault |
| **Audit: Сканирование** | `gitleaks detect --source . --redact --exit-code 1` | Поиск открытых секретов в репозитории перед коммитом |

### Пакетное перешифрование репозитория при ротации KEK (SOPS)

При увольнении сотрудника или выводе из эксплуатации скомпрометированного age-ключа системный администратор обновляет `.sops.yaml` и выполняет массовое обновление файлов:

```bash
# Массовое обновление метаданных получателей во всех зашифрованных файлах
find clusters/ -type f -name "*.enc.yaml" -exec sops updatekeys -y {} \;
# → [INFO] File clusters/prod/database-secret.enc.yaml updated successfully.
# → [INFO] File clusters/dev/api-secret.enc.yaml updated successfully.

# Проверка измененных файлов перед коммитом
git status --short
# →  M clusters/prod/database-secret.enc.yaml
# →  M clusters/dev/api-secret.enc.yaml
```

---

## Диагностика и устранение неисправностей

| Проблема / Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **SOPS: `MAC mismatch / error decrypting MAC`** | Нарушена целостность файла (повреждение при ручном разрешении merge-конфликта в Git). | `sops -d file.enc.yaml` завершается аварийно с кодом ошибки MAC. | 1. Запретить ручной merge зашифрованных файлов в Git.<br>2. Восстановить файл из коммита до слияния.<br>3. Выполнить расшифровку, разрешить конфликт в открытом тексте и зашифровать заново.<br>4. Аварийный просмотр (только чтение): `sops -d --ignore-mac file.enc.yaml`. |
| **Sealed Secrets: `cannot decrypt secret: no key could decrypt secret`** | 1. Имя или namespace секрета не совпадают с метаданными шифрования (`--scope strict`).<br>2. Утерян приватный ключ контроллера при переустановке кластера. | `kubectl logs -n kube-system -l app.kubernetes.io/name=sealed-secrets --tail=50` | 1. Проверить `metadata.name` и `metadata.namespace` в манифесте `SealedSecret`.<br>2. Если кластер пересоздан: восстановить секрет `sealed-secrets-key` из резервной копии (`kubectl apply -f sealed-secrets-master-backup.yaml`) и перезапустить контроллер. |
| **ESO: `SecretStore is not ready: permission denied`** | В Vault не настроен или просрочен Kubernetes Auth; не совпадает `audience` сервисного аккаунта. | `kubectl describe clustersecretstore vault-backend`<br>Проверка логов Vault: `grep "permission denied" /var/log/vault/audit.log` | 1. В Vault 1.21+ убедиться, что роль создана с параметром `audience=vault`.<br>2. Проверить права ServiceAccount `eso-sa` в пространстве имен `external-secrets`.<br>3. Проверить доступность адреса Vault по сети (DNS, MTU, сетевые политики). |
| **ESO: `ExternalSecret: RefreshFailed (secret not found)`** | Неправильно указан путь к секрету в Vault или ключ внутри JSON. | `kubectl describe externalsecret <name> -n <ns>`<br>Вывод: `remote key not found at path` | Для KV v2 убедиться, что в `spec.provider.vault.version` указано `v2`. В поле `remoteRef.key` путь указывается относительно корня движка (например, `production/db`, а не `secret/data/production/db`). |
| **Argo CD: `Kustomization decryption failed: no age secret found`** | Отсутствует ключ `age` в секрете `argocd-secret` неймспейса `argocd` или ключ не соответствует получателю в `.sops.yaml`. | `kubectl describe secret argocd-secret -n argocd`<br>`kubectl logs -n argocd deploy/argocd-repo-server --tail=50` | Проверить наличие ключа: `kubectl -n argocd get secret argocd-secret -o jsonpath='{.data.agekey}'`. Убедиться, что публичный ключ в `.sops.yaml` совпадает с ключом в `argocd-secret`. Перезапустить `argocd-repo-server`: `kubectl rollout restart deployment/argocd-repo-server -n argocd`. |
| **Reloader: Pod в CrashLoopBackOff после обновления секрета** | Приложение получило некорректно отформатированное значение секрета или не поддерживает горячий перезапуск. | `kubectl logs <pod-name> -n <ns> --previous` | 1. Откатить версию секрета в Vault (`vault kv rollback -version=X ...`).<br>2. Проверить переменные окружения пода: `kubectl get pod <pod> -o yaml`.<br>3. Исправить формат данных в хранилище. |

---

## Безопасность и лучшие практики

### Предотвращение утечек секретов в Git

1. **Локальные pre-commit хуки**: Обязательная проверка коммитов на машине каждого инженера:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.24.0
    hooks:
      - id: gitleaks
```

```bash
# Установка и активация хука локально
pre-commit install
# → pre-commit installed at .git/hooks/pre-commit

# Тестовый прогон проверки всех файлов
pre-commit run --all-files
# → Detect hardcoded secrets.............................................Passed
```

2. **Блокирующие пайплайны в GitLab CI / Woodpecker CI**:

```yaml
# Фрагмент .gitlab-ci.yml
secrets-scan:
  stage: test
  image:
    name: internal-registry.corp/security/gitleaks:v8.24.0
    entrypoint: [""]
  script:
    - gitleaks detect --verbose --source . --redact --exit-code 1
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

3. **Соблюдение принципа минимальных привилегий (Least Privilege)**:
   - GitOps-контроллерам выдаются права только на операцию `decrypt`. У них не должно быть прав на администрирование ключей или чтение секретов соседних сред.
   - Мастер-ключи сред `production` и `development` должны быть строго разделены. Разработчики не должны иметь доступа к production age-ключам или production ролям Vault.
4. **Контроль за `.gitignore`**:
   - Все файлы расшифрованных секретов (`*.dec.yaml`, `*.plain.txt`, `keys.txt`, `.env.local`) обязаны быть включены в корневой `.gitignore`.
5. **Аудит истории репозитория**:
   - Регулярный запуск сканирования всей глубины истории Git утилитой TruffleHog: `trufflehog git file://. --only-verified`.

---

## Дополнительная информация

**Связанные документы в базе знаний:**
- [Обзор управления секретами](../Security/Concepts/secrets_management_overview.md) — общая методология и жизненный цикл секретов.
- [SOPS overview](../Security/Tools/sops_overview.md) — детальный разбор внутреннего формата и параметров утилиты Mozilla SOPS.
- [Внешние системы управления секретами](../Kubernetes/Base/secrets/external_managers.md) — детальное руководство по External Secrets Operator (ESO) и Secrets Store CSI Driver.
- [Интеграция ArgoCD с Vault](./ArgoCD/argocd_vault_integration.md) — настройка плагина AVP и конфигурации ConfigManagementPlugin v2.
- [Sealed Secrets](../Kubernetes/Security/sealed_secrets_overview.md) — криптографическая схема и глубокий разбор Bitnami Sealed Secrets.
- [Хранение Secret в etcd](../Kubernetes/Base/secrets/etcd_storage.md) — включение шифрования etcd на уровне мастер-узлов Kubernetes (Encryption at Rest).
- [Обзор HashiCorp Vault](../Vault/overview.md) — архитектура, хранилище Raft и жизненный цикл секретов.
- [Интеграция Vault с Kubernetes](../Vault/guides/vault_kubernetes_integration.md) — настройка метода Kubernetes Auth и политик доступа.
 - [Безопасность Secret в Kubernetes](../Kubernetes/Base/secrets/security.md) — матрица RBAC и защита нативных секретов.

**Рекомендации по выбору инструмента для On-Premise инфраструктуры:**

| Условия инфраструктуры | Рекомендуемый выбор | Обоснование |
| :--- | :--- | :--- |
| **Единый автономный кластер K8s без центрального Vault** | **Bitnami Sealed Secrets** | Не требует внешней инфраструктуры; ключи генерируются и управляются внутри кластера. |
| **Мультикластерный GitOps на базе Argo CD** | **Mozilla SOPS + age** | Нативная поддержка в `argocd-repo-server`; разделение ключей по папкам окружений в `.sops.yaml`. |
| **Корпоративная среда с уже развернутым Vault / OpenBao** | **External Secrets Operator** | Централизованный аудит, автоматическая ротация учетных данных без коммитов в Git. |
| **Требования PCI DSS / изоляция от etcd** | **Secrets Store CSI Driver** | Секреты монтируются строго в RAM (`tmpfs`) пода и не попадают в базу данных etcd. |

---

## Вопросы для собеседования

### Почему хранение ключа дешифрования в том же репозитории с зашифрованными файлами полностью нивелирует шифрование?
Ключ шифрования вместе с шифротекстом в едином репозитории устраняет защиту периметра: любой субъект или скомпрометированный токен с доступом на чтение Git мгновенно расшифровывает все данные. Приватные ключи age или токены доступа к Vault обязаны храниться вне Git — в оперативной памяти защищенных сервисов, аппаратных токенах или монтироваться в кластер как инфраструктурные Secret при bootstrap-развертывании.

### В коммит случайно попал незашифрованный production-пароль базы данных. Опишите правильный регламент устранения инцидента.
Попытка сначала переписать историю репозитория через `git filter-repo` является грубой ошибкой, так как во время переписывания истории злоумышленник может использовать действующий пароль. 
Регламент:
1. Немедленно выполнить ротацию пароля в самой базе данных.
2. Обновить секрет во всех легитимных потребителях приложения.
3. Вырезать строку из истории коммитов репозитория (`git filter-repo`) и выполнить `git push --force --all`.
4. Инвалидировать локальные клоны и кэши сборочных линий.
5. Провести аудит логов подключений к БД за период с момента коммита.

### В чем разница между командами `sops updatekeys` и `sops rotate`?
- `sops updatekeys`: Перешифровывает существующий ключ данных (DEK) новым списком мастер-ключей (KEK), объявленных в `.sops.yaml`. Сами данные секрета не перешифровываются заново. Применяется при добавлении или отзыве публичных ключей инженеров/кластеров.
- `sops rotate` (или `sops -r`): Генерирует совершенно новый случайный DEK, заново шифрует им все полезные данные файла и шифрует новый DEK актуальными мастер-ключами. Применяется при плановой ротации криптографических ключей или подозрении на компрометацию старого DEK.

### Почему при использовании Sealed Secrets с параметром `--scope strict` переименование секрета приводит к ошибке расшифровки?
Параметр `--scope strict` включает имя секрета и его целевое пространство имен (`namespace`) в качестве дополнительных криптографических аутентифицированных данных (AAD — Additional Authenticated Data) в алгоритм шифрования. Если манифест применяется с другим именем или в другом namespace, контроллер Sealed Secrets получает несовпадение контрольной подписи и блокирует создание нативного `Secret`. Это исключает атаку подмены, когда разработчик с доступом к dev-пространству пытается расшифровать чужой production-секрет.

### Каковы недостатки архитектурной модели Argo CD Vault Plugin (AVP) по сравнению с External Secrets Operator (ESO)?
1. **Расширение поверхности атаки:** Под `argocd-repo-server` получает долгоживущие полномочия на чтение всех секретов из Vault для всех управляемых приложений.
2. **Нагрузка на хранилище:** AVP выполняет синхронные вызовы к Vault API при каждом рендеринге манифестов и каждой проверке дрейфа Argo CD, что при сотнях приложений создает высокую нагрузку. ESO распределяет нагрузку асинхронно по таймеру `refreshInterval`.
3. **Отсутствие отслеживания дрейфа из Vault:** Если значение в Vault изменилось, но в Git коммитов не было, Argo CD с AVP не обновит секрет в кластере до принудительного Hard Refresh. ESO автоматически обнаруживает изменение во внешнем хранилище и синхронизирует объект.
