# Безопасность Secret в Kubernetes

**Актуально для:** Kubernetes 1.30–1.34+ (KMS v2 GA, ValidatingAdmissionPolicy GA, Bound ServiceAccount Tokens, NodeSwap GA; on-premise / bare-metal)

## Определения

**Secret** — объект Kubernetes (`apiVersion: v1`, `kind: Secret`), предназначенный для хранения конфиденциальных данных небольшого объема (пароли, TLS-сертификаты, токены доступа, SSH-ключи, учетные записи баз данных). По умолчанию полезная нагрузка секрета кодируется алгоритмом Base64, что является форматом сериализации, а не шифрованием.

**Base64 кодирование** — обратимое представление бинарных данных в виде ASCII-строки. Кодирование Base64 не обеспечивает конфиденциальности и может быть мгновенно декодировано любой стороной, имеющей доступ к манифесту или объекту etcd (`echo <string> | base64 -d`).

**Шифрование данных в покое (Encryption at Rest)** — криптографическая защита данных при их сохранении на постоянный носитель. В Kubernetes реализуется компонентом `kube-apiserver` через файл `EncryptionConfiguration` с использованием симметричных ключей (`aesgcm`, `aescbc`, `secretbox`) либо внешних сервисов управления ключами по протоколу KMS v2 (HashiCorp Vault / OpenBao).

**KMS v2 (Key Management Service v2)** — архитектура интеграции `kube-apiserver` с внешними системами управления ключами, перешедшая в статус GA в Kubernetes 1.29. Использует трехуровневую иерархию ключей (KEK → Seed → DEK), локальное кэширование ключей шифрования данных и автоматическую ротацию без перезапуска API-сервера.

**Неизменяемый секрет (Immutable Secret)** — объект Secret с установленным флагом `immutable: true` (GA в Kubernetes 1.21+). Запрещает мутацию содержимого объекта после создания и отключает отслеживание изменений (`watch`) со стороны демонов `kubelet`, снижая нагрузку на `kube-apiserver`.

**Bound ServiceAccount Token** — криптографически подписанный токен JWT с ограниченным сроком жизни (TTL), жестко привязанный к конкретному экземпляру Pod, ServiceAccount и целевой аудитории (`audience`). Выдается ядром Kubernetes через TokenRequest API и монтируется как Projected Volume, исключая хранение статических токенов в etcd.

**Контроллер допуска NodeRestriction** — встроенный в `kube-apiserver` плагин Admission Control, ограничивающий права узлов Worker (`kubelet`). Разрешает демону `kubelet` читать из API только те секреты, которые непосредственно смонтированы в поды, назначенные планировщиком (`kube-scheduler`) на данный конкретный узел.

**tmpfs (RAM-диск тома Secret)** — виртуальная файловая система в оперативной памяти узла Linux, в которую `kubelet` монтирует секреты (`/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~secret/<volume-name>/`). Данные не сбрасываются на постоянный накопитель узла, если на хосте отключен или зашифрован раздел подкачки (swap).

**Swap Memory Leakage** — риск компрометации конфиденциальных данных, при котором страницы оперативной памяти (включая tmpfs) вытесняются ядром Linux на незашифрованный диск подкачки при дефиците памяти хоста.

**ValidatingAdmissionPolicy** — декларативный механизм политик допуска на базе языка CEL (Common Expression Language), встроенный в `kube-apiserver` (GA с версии 1.30). Позволяет валидировать структуру и способы использования объектов без вызова внешних webhook-контроллеров.

О создании секретов см. [Создание Secret](creating_secrets.md). О внутреннем устройстве и провайдерах шифрования etcd см. [Хранение в etcd](etcd_storage.md). О паттернах внедрения во внешние менеджеры см. [Внешние менеджеры](external_managers.md). О стандартах безопасности контейнеров см. [Pod Security Standards и Secret](pod_security_and_secrets.md).

---

## Архитектура и модель угроз (Threat Model)

Безопасность секретов в Kubernetes строится на защите данных на всех этапах их жизненного цикла: хранение в базе данных состояния кластера (at-rest), передача по сети (in-transit), обработка управляющим контуром (in-control-plane) и доставка в память прикладных процессов (in-use / in-runtime).

### Матрица угроз и периметров защиты

```
[ GitOps / CI/CD ] ────► [ kube-apiserver ] ────► [ etcd ]
        │                       │
        │                       ├─► [ Kubelet (Node) ]
        ▼                       │           │
[ Разработчик / Атакующий ]     ▼           ▼
                         [ Audit Log ]  [ Pod Memory / tmpfs ]
```

| Вектор атаки | Описание угрозы | Последствия | Механизм защиты (Hardening) |
| :--- | :--- | :--- | :--- |
| **Компрометация etcd / бэкапов** | Прямой доступ к диску master-узла, файлу базы данных etcd или снапшоту бэкапа | Извлечение всех секретов кластера в открытом виде (Base64) | Шифрование `EncryptionConfiguration` (KMS v2 + HashiCorp Vault или локальный `aesgcm`), шифрование снапшотов etcd |
| **Компрометация Worker-узла** | Захват хоста Worker или перехват сертификата `kubelet` | Попытка запросить секреты других узлов и пространств имен через API | Admission-плагин `NodeRestriction`, изоляция прав Kubelet, права `0700` на локальные каталоги tmpfs |
| **Утечка через переменные окружения** | Передача секретов через директивы `env` / `envFrom` | Секреты видны в `/proc/$PID/environ`, crash-дампах, логах приложений и через `kubectl describe pod` | Монтирование секретов исключительно как Volume (tmpfs), валидация через `ValidatingAdmissionPolicy` |
| **Вытеснение в Swap** | Сброс страниц памяти контейнера или tmpfs в незашифрованный раздел подкачки хоста | Секреты сохраняются на физическом диске в открытом виде после завершения пода | Отключение swap на Worker-узлах (`swapoff -a`) либо шифрование swap-раздела через dm-crypt/LUKS |
| **Эскалация прав в RBAC** | Пользователь с правами `create pods` в пространстве имен | Пользователь монтирует любой секрет неймспейса в созданный под и читает его через `kubectl exec` | Сегментация неймспейсов, отказ от broad roles, запрет `create pods` непривилегированным ролям, изоляция через CSI |
| **Утечка в Audit Logs / SIEM** | Ошибочная настройка политики аудита с уровнем `RequestResponse` для секретов | Тело секрета в Base64 записывается открытым текстом в журнал аудита API-сервера | Настройка уровня `level: Metadata` для ресурсов `secrets` в `/etc/kubernetes/audit-policy.yaml` |
| **Утечка в Git-репозитории** | Случайный коммит манифеста Secret в систему контроля версий | Перманентная компрометация учетных данных в истории коммитов Git | Прекоммит-хуки (Gitleaks, detect-secrets), шифрование файлов через [SOPS](../../../Security/Tools/sops_overview.md) или [Sealed Secrets](../../Security/sealed_secrets_overview.md) |

### Классификация данных и уровни чувствительности

1. **Tier-0 (Критические инфраструктурные секреты):**
   - Корневые TLS CA кластера, ключи шифрования etcd (KEK), токены bootstrap администратора, токены интеграции с хранилищем Vault.
   - *Требование:* хранение исключительно во внешнем Vault/KMS, доступ строго ограничен root-администраторами, аудит каждого обращения.
2. **Tier-1 (Секреты доступа к базам данных и сервисам):**
   - Учетные данные PostgreSQL/Redis, закрытые ключи Ingress TLS, токены сервисных аккаунтов приложений.
   - *Требование:* обязательное шифрование в etcd, доставка через `volumeMounts`, включение `immutable: true` для статических данных, ротация каждые 30–90 дней.
3. **Tier-2 (Внутренние токены и некритичные ключи):**
   - Внутренние токены очередей сообщений, ключи для кэширующих прокси.
   - *Требование:* доставка через tmpfs volume, автоматическая ротация средствами операторов (ESO / Reloader).

---

## Основные механизмы защиты

### 1. Неизменяемые секреты (Immutable Secrets)

Флаг `immutable: true` предотвращает случайное или несанкционированное изменение секретов в кластере:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials-v1
  namespace: prod
immutable: true
type: Opaque
data:
  password: c3VwZXJzZWN1cmVwYXNzd29yZA==
```

**Технические преимущества:**
- **Защита от перезаписи:** при попытке выполнить `kubectl apply` или `PATCH` с новыми данными `kube-apiserver` вернет ошибку `Invalid (422)`.
- **Снижение нагрузки на Control Plane:** `kubelet` прекращает периодический опрос (`watch`/`poll`) для таких томов. В кластерах с тысячами подов это снижает нагрузку на сеть и процессорные ресурсы `kube-apiserver` на 30–60%.
- **Атомарность обновлений:** для смены секрета DevOps-инженер создает объект `db-credentials-v2` и обновляет ссылку в спецификации Deployment, что исключает рассинхронизацию подов в процессе rolling update.

### 2. Безопасность токенов ServiceAccount (Bound ServiceAccount Tokens)

Устаревший механизм автоматической генерации постоянных секретов с типом `kubernetes.io/service-account-token` создавал долгоживущие токены в etcd, которые не имели срока действия и могли использоваться из любой точки сети.

**Архитектура Bound Tokens:**
- Токены запрашиваются процессом `kubelet` через `TokenRequest API`.
- Токен генерируется в виде подписанного JWT и привязан к UID пода: при удалении пода токен немедленно инвалидируется API-сервером.
- Токен имеет ограниченный TTL (по умолчанию 1 час) и автоматически обновляется демоном `kubelet` за 20% до истечения срока.
- Токен не записывается в etcd как объект `Secret`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
  namespace: prod
spec:
  serviceAccountName: backend-sa
  # Если приложению не требуется вызывать Kubernetes API, всегда отключайте монтирование:
  automountServiceAccountToken: false
  containers:
  - name: app
    image: internal-registry.corp/app:v1.2.0
```

Если подам необходим доступ к API, токен монтируется явным образом с жестким ограничением аудитории:

```yaml
spec:
  containers:
  - name: app
    image: internal-registry.corp/app:v1.2.0
    volumeMounts:
    - name: sa-token
      mountPath: /var/run/secrets/tokens
      readOnly: true
  volumes:
  - name: sa-token
    projected:
      sources:
      - serviceAccountToken:
          path: token
          expirationSeconds: 3600
          audience: api.corp.internal
```

### 3. Шифрование в покое (Encryption at Rest)

По умолчанию база данных etcd хранит манифесты секретов в виде открытого текста с полями данных в Base64. Компрометация резервной копии etcd или физического диска control-plane узла раскрывает все секреты.

Для включения аппаратного/программного шифрования создается файл `/etc/kubernetes/encryption-config.yaml`, который подключается к `kube-apiserver` аргументом `--encryption-provider-config`:

```yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
      - secrets
    providers:
      # Рекомендуемый для On-Premise вариант: KMS v2 через HashiCorp Vault
      - kms:
          apiVersion: v2
          name: vault-kms
          endpoint: unix:///var/run/kms/vault.sock
          timeout: 3s
      # Резервный локальный симметричный алгоритм (без внешних зависимостей)
      - aescbc:
          keys:
            - name: key1
              secret: c2VjcmV0IGlzIGEgMzItYnl0ZSBmb3IgQUVTMTI4Cg==
      # Для чтения незашифрованных данных при первичной миграции
      - identity: {}
```

> **Важно:** подробное руководство по настройке KMS v2 с плагином Vault, синтаксису и ротации провайдеров приведено в [Хранение в etcd (Шифрование at-rest)](etcd_storage.md#шифрование-at-rest-encryption-at-rest).

### 4. Изоляция на уровне Worker-узла и Kubelet

Безопасность секретов на уровне операционной системы хоста Worker опирается на три рубежа:

1. **Admission Controller `NodeRestriction`:**
   Включен по умолчанию в современных дистрибутивах (`--enable-admission-plugins=...,NodeRestriction,...`). Данный контроллер гарантирует, что сертификат `system:node:<node-name>` может запросить у `kube-apiserver` только те секреты, на которые ссылаются поды, назначенные планировщиком именно на этот узел. Атакующий, скомпрометировавший один Worker-узел, не сможет выкачать секреты чужих неймспейсов или других узлов.

2. **Файловая система tmpfs:**
   `kubelet` монтирует секреты в директорию `/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~secret/<volume-name>/`.
   Каталог монтируется как независимая файловая система типа `tmpfs` (RAM). Секрет существует только в оперативной памяти и никогда не сбрасывается на физические дорожки диска в виде файла ext4/xfs. Права на локальный каталог узла устанавливаются как `0700` или `0750` с владельцем `root`.

3. **Защита от утечки в Linux Swap:**
   Начиная с Kubernetes 1.30, функция поддержки Swap на Worker-узлах перешла в статус Beta (`NodeSwap`). При нехватке физической RAM ядро Linux может вытеснить страницы `tmpfs` в раздел подкачки swap на локальном SSD/HDD.
   - **Рекомендация SRE/Sysadmin:**
     - Либо полностью отключить swap на узлах:
       ```bash
       sudo swapoff -a
       sudo sed -i '/swap/d' /etc/fstab
       ```
     - Либо, если swap строго необходим по требованиям приложений, зашифровать раздел подкачки с помощью LUKS:
       ```bash
       # Создание зашифрованного swap с эфемерным случайным ключом (ключ генерируется при каждой загрузке)
       # /etc/crypttab:
       # cryptswap /dev/nvme0n1p2 /dev/urandom swap,cipher=aes-xts-plain64,size=512
       ```

---

## Практические сценарии и харденинг

### Сценарий 1: RBAC Харденинг доступа к секретам

По умолчанию доступ к секретам должен блокироваться для всех пользователей и сервисных аккаунтов, кроме явно доверенных.

#### Риск широких прав `list` и `watch`

Предоставление прав `list` или `watch` на ресурс `secrets` в пространстве имен позволяет субъекту получить полный дамп содержимого **всех** секретов неймспейса за один запрос.

```yaml
# НЕБЕЗОПАСНАЯ КОНФИГУРАЦИЯ (Anti-Pattern):
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"] # Позволяет прочитать чужие секреты
```

#### Безопасная Role с ограничением по resourceNames

Принцип наименьших привилегий требует ограничения по имени конкретного объекта (`resourceNames`):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: billing-secret-reader
  namespace: prod
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["billing-db-credentials", "billing-tls-cert"]
  verbs: ["get"] # Только целевое чтение по точному имени
```

> **Ограничение Kubernetes RBAC:** директива `resourceNames` **не работает** для операций `create`, `list` и `watch`. Она поддерживается только для `get`, `update`, `patch`, `delete`. Предоставление `list` всегда открывает весь неймспейс.

#### Вектор эскалации через `pods/create`

В Kubernetes право создания пода (`verbs: ["create"]`, `resources: ["pods"]`) эквивалентно полному доступу на чтение всех секретов в данном пространстве имен. Пользователь может отправить спецификацию пода, монтирующего любой секрет, и вывести его содержимое через `kubectl logs` или `kubectl exec`.

**Методы защиты:**
1. Не выдавать права `pods/create` разработчикам напрямую в production-неймспейсах (деплой только через CI/CD сервисные аккаунты или GitOps-операторы).
2. Использовать admission-политики, блокирующие монтирование секретов, не относящихся к данному приложению.
3. Использовать [Secrets Store CSI Driver](external_managers.md#secrets-store-csi-driver), где авторизация происходит на уровне Vault Policy конкретного ServiceAccount, а не через нативный объект Kubernetes Secret.

#### Проверка и аудит прав через `kubectl`

```bash
# Проверка возможности чтения конкретного секрета сервис-аккаунтом
kubectl auth can-i get secrets/billing-db-credentials \
  --namespace=prod \
  --as=system:serviceaccount:prod:billing-app-sa
# → yes

# Проверка запрета на общий листинг секретов
kubectl auth can-i list secrets \
  --namespace=prod \
  --as=system:serviceaccount:prod:billing-app-sa
# → no

# Полный аудит прав субъекта в пространстве имен
kubectl auth can-i --list \
  --namespace=prod \
  --as=system:serviceaccount:prod:billing-app-sa
# → Resources   Non-Resource URLs   Resource Names             Verbs
# → secrets     []                  [billing-db-credentials]   [get]
```

---

### Сценарий 2: Безопасная доставка в Pod (Volume tmpfs vs Переменные окружения)

Существует два метода передачи секретов в контейнеры: через переменные окружения (`env`, `envFrom`) и через монтирование файлового тома (`volumeMounts`).

```
Метод доставки:
├── Переменные окружения (env) ──► /proc/$PID/environ, crash dumps, логи (НЕБЕЗОПАСНО)
└── Файловый том (volumeMount) ──► tmpfs (RAM), defaultMode: 0400, атомарная ротация (БЕЗОПАСНО)
```

| Критерий | Монтирование Volume (tmpfs) | Переменные окружения (`env` / `envFrom`) |
| :--- | :--- | :--- |
| **Физическое размещение** | Изолированная область RAM хоста (`tmpfs`) | Таблица переменных окружения процесса Linux |
| **Видимость в системе** | Только процесс с соответствующим UID/GID в контейнере | Видны в `/proc/<PID>/environ`, `docker inspect`, `crictl inspect` |
| **Утечка в логах и дампах** | Исключена (если приложение не читает файл в лог) | Высокая вероятность утечки при crash-дампах, `printenv` и ошибках стека |
| **Динамическое обновление** | Автоматическое обновление симлинка kubelet'ом | Требует полного перезапуска контейнера |
| **Рекомендация безопасности** | **Production Standard** | Запрещено для Tier-0/Tier-1 данных |

#### Hardening конфигурации Volume: права defaultMode и fsGroup

По умолчанию монтируемые файлы секрета получают права `0644`. Для соблюдения принципа наименьших привилегий задавайте `defaultMode: 0400` (чтение только владельцем) или `0440` (чтение владельцем и группой), а также фиксируйте `runAsNonRoot` и `fsGroup`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-backend
  namespace: prod
spec:
  replicas: 2
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      # Запуск непривилегированного пользователя и группы
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: backend
        image: internal-registry.corp/backend:v2.4.0
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        volumeMounts:
        - name: app-secret-vol
          mountPath: /etc/secrets/database
          readOnly: true
      volumes:
      - name: app-secret-vol
        secret:
          secretName: billing-db-credentials
          # 0400 в восьмеричной системе = 256 в десятичной
          defaultMode: 256
```

#### Ловушка директивы subPath

Если файл секрета монтируется через директиву `subPath`:

```yaml
# ВНИМАНИЕ: subPath отключает автоматическое обновление секретов!
volumeMounts:
- name: app-secret-vol
  mountPath: /etc/nginx/ssl/server.key
  subPath: tls.key
```

`kubelet` выполняет прямое монтирование файла (bind mount inode) вместо создания дерева симлинков (`..data -> ..2026_10_...`). При изменении секрета в Kubernetes API **файл внутри контейнера обновлен не будет**. Для применения изменений потребуется принудительный перезапуск подов (`kubectl rollout restart`).

---

### Сценарий 3: Аудит доступа к секретам в Kubernetes

Kubernetes API Audit позволяет фиксировать каждое обращение к секретам: кто запросил, когда, из какого IP-адреса и с каким результатом.

#### КРИТИЧЕСКИЙ СТАНДАРТ: Metadata vs RequestResponse

> **Внимание (CIS Benchmark 3.2.1):** категорически запрещено настраивать уровень `RequestResponse` или `Request` для ресурсов `secrets` и `configmaps`.
> На уровне `RequestResponse` тело ответа API-сервера записывается в файл журнала аудита в открытом виде (включая раскодированные payload-секреты). Журналы аудита, пересылаемые в SIEM, Elasticsearch или Loki, становятся источником массовой утечки учетных данных.
> Для секретов допустим **исключительно уровень `Metadata`**.

#### Конфигурация `/etc/kubernetes/audit-policy.yaml`

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
omitStages:
  - "RequestReceived"
rules:
  # 1. Логирование чтения и изменений секретов строго на уровне Metadata
  - level: Metadata
    resources:
      - group: ""
        resources: ["secrets", "configmaps"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

  # 2. Логирование запросов токенов аутентификации
  - level: Metadata
    resources:
      - group: "authentication.k8s.io"
        resources: ["tokenreviews"]

  # 3. Полное логирование остальных системных ресурсов для расследования инцидентов
  - level: RequestResponse
    resources:
      - group: "rbac.authorization.k8s.io"
        resources: ["roles", "rolebindings", "clusterroles", "clusterrolebindings"]

  # По умолчанию для всех прочих запросов
  - level: Metadata
```

Включение аудита в манифесте `/etc/kubernetes/manifests/kube-apiserver.yaml`:

```yaml
spec:
  containers:
  - command:
    - kube-apiserver
    - --audit-policy-file=/etc/kubernetes/audit-policy.yaml
    - --audit-log-path=/var/log/kubernetes/audit/kube-audit.log
    - --audit-log-maxage=30
    - --audit-log-maxbackup=10
    - --audit-log-maxsize=100
```

#### Поиск аномалий в логах аудита

```bash
# 1. Обнаружение подозрительных операций чтения (get/list) секретов
jq -r 'select(.objectRef.resource=="secrets" and (.verb=="list" or .verb=="get")) | 
  "[\(.stageTimestamp)] User: \(.user.username) | IP: \(.sourceIPs[0]) | Verb: \(.verb) | Secret: \(.objectRef.namespace)/\(.objectRef.name // "ALL")"' \
  /var/log/kubernetes/audit/kube-audit.log
# → [2026-10-17T20:15:02Z] User: developer-ivan | IP: 192.168.10.45 | Verb: list | Secret: prod/ALL
# → [2026-10-17T20:15:10Z] User: developer-ivan | IP: 192.168.10.45 | Verb: get | Secret: prod/billing-db-credentials

# 2. Обнаружение попыток неавторизованного доступа (HTTP 403 Forbidden)
jq -r 'select(.objectRef.resource=="secrets" and .responseStatus.code==403) | 
  "ALERT: Unauthorized access by \(.user.username) to \(.objectRef.namespace)/\(.objectRef.name)"' \
  /var/log/kubernetes/audit/kube-audit.log
# → ALERT: Unauthorized access by system:serviceaccount:dev:untrusted-sa to prod/billing-db-credentials
```

---

### Сценарий 4: Принудительное исполнение политик (Admission Control)

Для предотвращения небезопасных практик используются политики допуска на уровне `kube-apiserver`.

#### Валидация через ValidatingAdmissionPolicy (Kubernetes 1.30+ GA)

Запрет монтирования секретов через переменные окружения (`env.valueFrom.secretKeyRef` и `envFrom.secretRef`):

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: disallow-secret-env-variables
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
    - expression: >-
        !object.spec.containers.exists(c, has(c.env) && c.env.exists(e, has(e.valueFrom) && has(e.valueFrom.secretKeyRef))) &&
        !object.spec.containers.exists(c, has(c.envFrom) && c.envFrom.exists(ef, has(ef.secretRef)))
      message: "Передача секретов через переменные окружения (env/envFrom) запрещена. Используйте безопасное монтирование томов tmpfs."
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: disallow-secret-env-variables-binding
spec:
  policyName: disallow-secret-env-variables
  validationActions: [Deny]
  matchResources:
    namespaceSelector:
      matchExpressions:
      - key: kubernetes.io/metadata.name
        operator: NotIn
        values: ["kube-system", "kube-node-lease"]
```

#### Запрет создания секретов размером более 256 КиБ (CEL)

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: limit-secret-size
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["secrets"]
  validations:
    - expression: "!object.data.exists(k, size(object.data[k]) > 262144)"
      message: "Размер отдельного ключа секрета превышает лимит в 256 КиБ. Большие файлы должны храниться во внешнем хранилище."
```

#### Альтернатива: Kyverno ClusterPolicy для блокировки env

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-secret-volume-mount
  annotations:
    policies.kyverno.io/title: Disallow Secrets as Environment Variables
    policies.kyverno.io/severity: high
spec:
  validationFailureAction: Enforce
  background: true
  rules:
  - name: check-secret-env
    match:
      any:
      - resources:
          kinds:
          - Pod
    exclude:
      any:
      - resources:
          namespaces:
          - kube-system
    validate:
      message: "Секреты разрешено монтировать только через volumeMounts."
      pattern:
        spec:
          containers:
          - =(env):
            - =(valueFrom):
                X(secretKeyRef): "null"
```

---

### Сценарий 5: Жизненный цикл и стратегии ротации секретов

Регулярная смена учетных данных исключает использование скомпрометированных ключей.

#### Паттерн "Double-Secret / Overlap" (Zero-Downtime)

При ротации паролей к базам данных смена секрета в Kubernetes не должна приводить к отказу соединений:

```
Этап 1: БД поддерживает старый и новый пароль одновременно (User-Role aliasing)
Этап 2: Создание нового секрета `db-pass-v2` в Kubernetes
Этап 3: Переключение подов через Rolling Update на `db-pass-v2`
Этап 4: Мониторинг логов: отсутствие запросов со старым паролем
Этап 5: Отзыв старого пароля в БД и удаление `db-pass-v1`
```

#### Автоматический перезапуск подов через Stakater Reloader

Если приложение не умеет перечитывать файлы конфигурации на лету, используется контроллер Reloader:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-service
  namespace: prod
  annotations:
    reloader.stakater.com/auto: "true"
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: api
        image: internal-registry.corp/api:v1.0.0
        volumeMounts:
        - name: secret-vol
          mountPath: /etc/secrets
          readOnly: true
      volumes:
      - name: secret-vol
        secret:
          secretName: api-credentials
```

При обновлении данных в `api-credentials` Reloader автоматически выполняет контролируемый `rollout restart` деплоймента без простоя сервиса.

---

### Сценарий 6: Предотвращение утечек секретов в CI/CD (On-Premise)

Предотвращение попадания секретов в открытом виде в git-репозиторий на этапе коммита и CI-сборки:

#### Pre-commit проверка через Gitleaks

Конфигурация `.pre-commit-config.yaml` в корне репозитория:

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.2
    hooks:
      - id: gitleaks
```

Локальная проверка перед отправкой в репозиторий:

```bash
# Ручной запуск сканирования рабочей директории
gitleaks detect --source . --verbose
# → 10:14AM INF scan completed in 82ms
# → 10:14AM INF no leaks found
```

#### Сканирование репозитория в пайплайне GitLab CI (On-Premise)

```yaml
stages:
  - security-audit

gitleaks-scan:
  stage: security-audit
  image:
    name: internal-registry.corp/security/gitleaks:v8.18.2
    entrypoint: [""]
  script:
    - gitleaks detect --verbose --source . --report-path gitleaks-report.json --exit-code 1
  artifacts:
    when: on_failure
    expire_in: 1 week
    paths:
      - gitleaks-report.json
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
```

#### Контроль через Yelp detect-secrets с baseline-файлом

```bash
# Инициализация baseline (список известных и разрешенных ложных срабатываний)
detect-secrets scan > .secrets.baseline

# Проверка новых изменений против baseline в CI
detect-secrets scan --baseline .secrets.baseline
# → Exit Code 0 при отсутствии новых утечек
```

---

## Операции и команды аудита и верификации

### Анализ размеров и состава секретов в кластере

```bash
# Поиск топ-10 самых больших секретов в кластере (контроль лимита 1 МиБ etcd)
kubectl get secrets -A -o json | jq -r '
  .items[] | 
  {
    ns: .metadata.namespace, 
    name: .metadata.name, 
    bytes: (.data | to_entries | map(.value | length) | add // 0)
  } | 
  "\(.bytes)\t\(.ns)/\(.name)"' | sort -n -r | head -n 10
# → 524288  prod/heavy-tls-bundle
# → 131072  staging/cert-manager-ca

# Проверка наличия неизменяемых секретов (immutable)
kubectl get secrets -A -o json | jq -r '
  .items[] | select(.immutable == true) | "\(.metadata.namespace)/\(.metadata.name)"'
# → prod/db-credentials-v1
# → prod/ingress-wildcard-tls-v2
```

### Поиск небезопасных методов использования (env / envFrom)

```bash
# Поиск всех Pods, монтирующих секреты через переменные окружения (нарушение hardening)
kubectl get pods -A -o json | jq -r '
  .items[] | 
  select(.spec.containers[].env[]?.valueFrom.secretKeyRef != null or .spec.containers[].envFrom[]?.secretRef != null) | 
  "\(.metadata.namespace)/\(.metadata.name)"' | sort -u
# → dev/legacy-php-app-7b99c85-2k19d
# → staging/old-worker-578dff-9lmqx
```

### Верификация прав доступа и изоляции Kubelet

```bash
# Проверка прав конкретного ServiceAccount на чтение секретов
kubectl auth can-i get secrets -n prod --as=system:serviceaccount:prod:default
# → no

# Проверка прав администратора на имперсонацию (impersonate)
kubectl auth can-i impersonate serviceaccount -n prod
# → no
```

---

## Диагностика и устранение неполадок

### Матрица инцидентов и решений

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| `CrashLoopBackOff` с `Permission denied` при чтении файла секрета | Несоответствие прав `defaultMode` и UID/GID процесса | `kubectl describe pod <name>` → Events; запуск `id` в контейнере | Установить `fsGroup: <GID>` в `pod.spec.securityContext` либо изменить `defaultMode: 0440` |
| Секрет обновлен в API, но приложение видит старое значение | Секрет смонтирован через `subPath` либо помечен `immutable: true` | `kubectl get secret <name> -o yaml` (проверить поле `immutable`); `kubectl get pod <name> -o yaml` | Отказаться от `subPath` в пользу монтирования каталога целиком; перезапустить поды (`kubectl rollout restart`) |
| `Error from server (Forbidden): secrets is forbidden` | Недостаточно прав в RBAC или отсутствует имя в `resourceNames` | `kubectl auth can-i get secret/<name> -n <ns> --as=...` | Добавить имя секрета в секцию `resourceNames` соответствующей `Role` |
| `Warning FailedMount: secret "<name>" not found` | Секрет не создан или находится в другом пространстве имен | `kubectl get secrets -n <ns>` | Создать недостающий объект Secret в целевом namespace приложения |
| `apiserver_storage_transformation_failures_total > 0` | Сбой дешифрования etcd (ошибка плагина KMS v2 или поврежден ключ) | Проверить логи API-сервера: `journalctl -u kube-apiserver \| grep -i kms` | Восстановить связь с HashiCorp Vault, проверить статус сокета KMS v2 |
| `RequestEntityTooLarge: Secret exceeds limit` | Размер манифеста секрета превышает лимит etcd (1 МиБ) | `kubectl get secret <name> -o json \| jq '.data \| to_entries \| map(.value \| length) \| add'` | Вынести большие файлы (Keystore, длинные цепочки) во внешнее хранилище или Vault |

### Пошаговые сценарии диагностики

#### Инцидент 1: Ошибка монтирования секрета из-за прав доступа (Permission Denied)

Симптом: контейнер завершается с кодом 1 при попытке открыть `/etc/secrets/database/password`.

```bash
# 1. Просмотр логов контейнера
kubectl logs -n prod backend-765fbd78b-x7zkw
# → open /etc/secrets/database/password: permission denied

# 2. Проверка UID процесса и конфигурации securityContext
kubectl get pod backend-765fbd78b-x7zkw -n prod -o jsonpath='{.spec.securityContext}' | jq
# → {
# →   "runAsNonRoot": true,
# →   "runAsUser": 10001
# → }

# 3. Причина: defaultMode установлен в 0400 (владелец root), а fsGroup не задан
# Решение: Добавить fsGroup: 10001 в спецификацию пода и выставить defaultMode: 288 (0440):
# spec:
#   securityContext:
#     fsGroup: 10001
#   volumes:
#   - name: app-secret-vol
#     secret:
#       secretName: billing-db-credentials
#       defaultMode: 288
```

#### Инцидент 2: Рассинхронизация ключей KMS v2 в Control Plane

Симптом: метрика Prometheus сигнализирует о сбое дешифрования объектов:

```bash
# 1. Проверка метрик API-сервера
curl -k -H "Authorization: Bearer $(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
  https://127.0.0.1:6443/metrics | grep apiserver_storage_transformation_failures_total
# → apiserver_storage_transformation_failures_total{resource="secrets"} 4

# 2. Диагностика состояния Unix-сокета плагина KMS
ls -la /var/run/kms/vault.sock
# → srwxr-xr-x 1 root root 0 Oct 17 20:00 /var/run/kms/vault.sock

# 3. Проверка доступности HashiCorp Vault с Control Plane узла
export VAULT_ADDR="https://vault.corp.internal:8200"
vault status
# → Sealed: false
# → Key Rotation Status: OK

# 4. Перезапуск пода KMS v2 плагина при зависании gRPC-канала
kubectl rollout restart daemonset/vault-kms-plugin -n kube-system
# → daemonset.apps/vault-kms-plugin restarted
```

---

## Лучшие практики (Best Practices)

### Чек-лист харденинга для DevOps и SRE

1. **Включите шифрование в etcd (KMS v2):**
   Никогда не эксплуатируйте Production-кластеры с хранением etcd по умолчанию. Настройте `EncryptionConfiguration` с внешним плагином HashiCorp Vault или локальным `aesgcm`.
2. **Только `Metadata` в политиках аудита:**
   Убедитесь, что в `/etc/kubernetes/audit-policy.yaml` для ресурсов `secrets` и `configmaps` выставлен уровень `level: Metadata`. Уровень `RequestResponse` приводит к утечке секретов в открытом виде в аудит-логи.
3. **Запретите передачу секретов через переменные окружения:**
   Передавайте секреты исключительно через `volumeMounts`. Закрепите запрет использования `envFrom` и `secretKeyRef` через `ValidatingAdmissionPolicy` или Kyverno.
4. **Применяйте флаг `immutable: true`:**
   Маркируйте неизменяемые секреты (сертификаты, статические токены). Это защищает от случайного изменения и снижает нагрузку на `kube-apiserver`.
5. **Ограничивайте права ServiceAccount:**
   Устанавливайте `automountServiceAccountToken: false` в спецификациях подов, если приложению не требуется взаимодействовать с Kubernetes API.
6. **Ограничивайте RBAC через `resourceNames`:**
   Никогда не выдавайте права `list` и `watch` на секреты непривилегированным ролям. Ограничивайте глагол `get` конкретным списком имен.
7. **Контролируйте доступ к созданию Pods (`pods/create`):**
   Помните, что пользователь с правом создания подов в неймспейсе может прочитать любой секрет этого неймспейса.
8. **Настройте сканирование в pre-commit и CI/CD:**
   Интегрируйте Gitleaks или detect-secrets в локальные хуки разработчиков и пайплайны GitLab CI / Gitea Actions.
9. **Защищайте Worker-узлы от утечек в Swap:**
   Отключайте swap на узлах кластера (`swapoff -a`) либо используйте зашифрованный swap-раздел (dm-crypt/LUKS).
10. **Минимизируйте права доступа к файлам внутри контейнера:**
    Задавайте `defaultMode: 0400` или `0440` и монтируйте тома секретов строго в режиме `readOnly: true`.

---

## Дополнительная информация

### Смотрите также

- [Хранение в etcd](etcd_storage.md) — низкоуровневая архитектура etcd, форматы префиксов, детальная настройка KMS v2 и ротация ключей шифрования.
- [Внешние менеджеры](external_managers.md) — интеграция с HashiCorp Vault, External Secrets Operator (ESO) и Secrets Store CSI Driver.
- [Pod Security Standards и Secret](pod_security_and_secrets.md) — влияние профилей PSA (`restricted`) на монтирование секретов, `securityContext`, `fsGroup` и `tmpfs`.
- [Создание Secret](creating_secrets.md) — методы генерации секретов, работа со `stringData`, бинарными файлами и экранированием.
- [Основы работы с Secret](secrets_basics.md) — базовые типы секретов (`Opaque`, `kubernetes.io/tls`, `dockerconfigjson`).
- [Использование Secret](using_secrets.md) — детальные примеры монтирования томов и передачи данных в контейнеры.
- [Секреты в StatefulSet](statefulset_secrets.md) — изоляция учетных данных реплик СУБД в stateful-нагрузках.
- [Helm + секреты](helm_secrets.md) — безопасное управление секретами в чартах Helm с использованием плагина helm-secrets.
- [Sealed Secrets](../../Security/sealed_secrets_overview.md) — асимметричное шифрование секретов для безопасного коммита в Git.
- [SOPS](../../../Security/Tools/sops_overview.md) — шифрование значений манифестов через Mozilla SOPS.
- [Интеграция Vault с Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md) — глубокое руководство по Vault Agent, VSO и CSI Driver.
- [GitOps: управление секретами](../../../GitOps/secrets_encryption.md) — методология и паттерны шифрования секретов в репозиториях Git.
