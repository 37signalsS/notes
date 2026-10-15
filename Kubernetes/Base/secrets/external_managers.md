# Внешние системы управления секретами

**Актуально для:** External Secrets Operator 2.12.x (октябрь 2026)

## Определения

**Внешние менеджеры секретов (External Secret Managers)** — специализированные системы (HashiCorp Vault, AWS Secrets Manager, Google Secret Manager), интегрированные с Kubernetes для централизованного хранения, жизненного цикла и аудита конфиденциальных данных. В 2026 году использование внешних менеджеров является обязательным стандартом для сред с высокими требованиями к безопасности (Zero Trust).

**External Secrets Operator (ESO)** — Kubernetes-оператор, реализующий модель периодического Pull-синхронизации: он считывает данные из внешнего API и создаёт/обновляет нативные объекты `Secret` в кластере (с точки зрения кластера такую доставку можно описать как Push). Приложения работают со стандартными механизмами Kubernetes (ENV, Volumes) и не знают о внешнем хранилище.

**Secrets Store CSI Driver** — интерфейс, реализующий "On-demand модель". Секреты монтируются напрямую в файловую систему Pod в момент его запуска, не сохраняясь в `etcd` в виде объектов `Secret`.

**Vault Secrets Operator (VSO)** — нативный оператор от HashiCorp (актуален в 2026 году), объединяющий преимущества ESO и прямой интеграции с Vault API. Синхронизирует статические (`VaultStaticSecret`), динамические (`VaultDynamicSecret`) и PKI-секреты (`VaultPKISecret`), поддерживает автоматическую ротацию и rollout-restart приложений.

**PushSecret** — обратный сценарий синхронизации ESO: публикация значения (например, автоматически сгенерированного пароля через `Generators`) из кластера во внешнее хранилище. Применяется в GitOps-потоках и взаимной синхронизации приложений с KMS.

**OpenBao** — открытая сборка Vault под эгидой Linux Foundation (форк, созданный после перевода HashiCorp Vault на лицензию BUSL). Совместима с API Vault и подходит для полностью самохостящихся сред без коммерческой лицензии.

## Основные концепции

### Преимущества внешних систем

1.  **Безопасность etcd:** Минимизация или полное исключение хранения секретов в базе данных кластера. При использовании CSI Driver секреты находятся только в оперативной памяти (`tmpfs`) узла.
2.  **Аудит и комплаенс:** Внешние системы предоставляют детальные логи (кто, когда и какой секрет получил), что критично для стандартов PCI DSS и SOC2.
3.  **Динамическая ротация:** Возможность автоматического обновления паролей баз данных или сертификатов без ручного вмешательства в манифесты Kubernetes.
4.  **Workload Identity:** Использование облачных идентичностей (IAM Roles for Service Accounts — IRSA, Azure Workload Identity) вместо долгоживущих статических токенов для доступа к KMS.

### Модели доставки секретов

С точки зрения способа доставки данных в приложение выделяют три модели (сравнение Push/Pull разобрано подробнее в [Управлении секретами приложений](../../Security/application_secrets_management.md)):

-   **Pull/Push (ESO):** постоянно работающий оператор периодически читает внешнее хранилище и синхронизирует значения в нативные `Secret`. Приложение ничего не знает о внешней системе и использует привычные ENV/Volumes.
-   **On-demand (Secrets Store CSI Driver):** значение извлекается из хранилища в момент старта Pod и монтируется как файловый том (секрет не становится объектом Kubernetes).
-   **Direct (Vault Agent Sidecar, VSO):** агент или оператор отдают секрет напрямую — файлы из общего тома (`emptyDir`/`tmpfs`) либо нативный `Secret` с автоматической ротацией.

### Сравнение подходов (2026)

| Характеристика | External Secrets (ESO) | Secrets Store CSI | Vault Sidecar / VSO |
| :--- | :--- | :--- | :--- |
| **Хранение в etcd** | Да (синхронизация) | Нет (только RAM) | Опционально |
| **Способ доставки** | Переменные окружения и файлы | Только файлы (по умолчанию) | Файлы или API |
| **Автообновление** | По `refreshInterval` | При ротации в KMS | Динамическое |
| **Сложность** | Средняя | Высокая | Средняя/Высокая |
| **Совместимость** | Максимальная (любые приложения) | Приложения, читающие файлы | Cloud-native приложения |
| **Компоненты в кластере** | Оператор (`Deployment`) + CRD | CSI-драйвер и provider (`DaemonSet`) на каждом узле | Per-Pod контейнеры либо оператор (VSO) |
| **Динамические секреты** | Периодический Pull, без управления арендами | Обычно нет (статические KV) | Да (`VaultDynamicSecret`, шаблоны + TTL) |
| **Аутентификация** | Конфигурируется в `SecretStore` (Kubernetes Auth, AppRole, токен) | Параметры provider + `nodePublishSecretRef` | Kubernetes Auth / `VaultAuth` (VSO) |
| **Наблюдаемость** | `status.conditions` ресурсов ESO | `SecretProviderClassPodStatus`, события kubelet | Логи Vault Agent / `status` CRD VSO |

### Жизненный цикл синхронизации в ESO (Pull-модель)

1.  **Создание `ExternalSecret`:** пользователь декларативно описывает, откуда и какие ключи читать и в какой нативный `Secret` их положить.
2.  **Reconcile loop:** оператор следит за ресурсами `ExternalSecret`, `SecretStore`/`ClusterSecretStore` и каждые `refreshInterval` заново опрашивает внешний API (drift detection — обнаружение изменений во внешнем хранилище).
3.  **Доступ к хранилищу:** оператор получает credentials через `ClusterSecretStore` (Kubernetes Auth, AppRole, статический токен и др.), читает значения и формирует целевой `Secret`.
4.  **Создание/обновление `Secret`:** с учётом `target.name` (имя может быть шаблоном), `target.template` (добавление метаданных/аннотаций), `data` vs `dataFrom` (выборка конкретных полей или всего секрета).
5.  **Удаление/пересоздание:** `creationPolicy` определяет право собственности (`Owner` — оператор управляет объектом, `Orphan` — не управляет, `Merge` — сливает с существующим); `deletionPolicy` — что случится с целевым `Secret` при удалении `ExternalSecret` (`Retain` / `Delete`).
6.  **Статус:** результат каждой синхронизации отражается в `status.conditions` ресурса (`Ready`, `Sync`, `RefreshFailed`) и в событиях (events) объекта.

## Практические сценарии

### Использование External Secrets Operator (ESO)

ESO позволяет приложениям использовать стандартные механизмы Kubernetes (ENV, Volumes), при этом данные поступают из защищенного хранилища.

**Архитектура:**
*   **SecretStore / ClusterSecretStore:** Настройка аутентификации в KMS (например, через ServiceAccount JWT или IAM Role). `SecretStore` действует в пределах одного namespace, `ClusterSecretStore` — в пределах всего кластера (для инфраструктурных сервисов).
*   **ExternalSecret:** Определение маппинга внешних ключей в ключи нативного секрета.
*   **refreshInterval:** Параметр, определяющий частоту опроса KMS для обнаружения изменений (drift detection).

**Установка оператора (ESO 2.12.x, 2026):**

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace
```

CRD устанавливаются чартом по умолчанию (`installCRDs: true`). При мультикластерном управлении CRD установите `installCRDs: false` и applying CRD отдельно через `kubectl apply -f .../bundle.yaml --server-side` во избежание конфликтов версий при обновлении ESO в разных кластерах в разное время. CRD превысили лимит 256 KB — при ручном applying используйте `--server-side`. Проверка:

```bash
kubectl get crd | grep external-secrets
# → clustersecretstores.external-secrets.io
# → externalsecrets.external-secrets.io
# → secretstores.external-secrets.io
# → clusterexternalsecrets.external-secrets.io (опционально)
kubectl get pods -n external-secrets
```

> **Версия API (важно при обновлении):** с ESO 0.17 (май 2025) и далее в стабильной ветке используется `apiVersion: external-secrets.io/v1`; `v1beta1` устарел и отключён по умолчанию в чарте ESO 2.x (`unsafeServeV1Beta1: false`, планируется к удалению 2026.05.01). Старые манифесты на `v1beta1` дадут ошибку `no matches for kind "SecretStore" in version "external-secrets.io/v1beta1"` — переведите все ресурсы (SecretStore, ClusterSecretStore, ExternalSecret, ClusterExternalSecret) на `v1` до апгрейда. Шаблонный движок v1 также устарел — по умолчанию используется engine v2, который поддерживает темplatating в `spec.target.template.metadata` и ключах `data`.

**Сквозной пример: ClusterSecretStore + ExternalSecret (провайдер Vault, Kubernetes Auth):**

```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: "http://vault.vault.svc.cluster.local:8200"
      path: "secret"                  # mount point движка KV v2
      version: "v2"
      auth:
        kubernetes:                   # auth method "kubernetes" в Vault
          mountPath: "kubernetes"
          role: "eso-role"            # Vault-роль (bound SA + policies + audience)
          serviceAccountRef:
            name: "eso-sa"            # SA, чей токен предъявляется Vault
            namespace: "external-secrets"   # для ClusterSecretStore требуется namespace
```

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: db-credentials
  namespace: prod
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: db-credentials              # имя нативного Secret
    creationPolicy: Owner             # ESO владеет объектом (обновляет и удаляет)
    deletionPolicy: Retain            # при удалении ExternalSecret целевой Secret остаётся
  data:
  - secretKey: password               # ключ в целевом Secret
    remoteRef:
      key: secret/data/production/db  # путь в Vault (KV v2)
      property: password              # поле внутри секрета
```

> **Примечание по Vault 1.21+:** при аутентификации через `kubernetes` роли обязаны содержать `audience`. Задавайте `audience` в роли Vault (`vault write auth/kubernetes/role/<role> audience=vault ...`) и, при необходимости, `audiences` в `serviceAccountRef`. Полные инструкции по Vault-стороне — в [Интеграции Vault с Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md).

**Проверка синхронизации:**

```bash
kubectl get externalsecret db-credentials -n prod -o jsonpath='{.status.conditions}'
# → [{"type":"Ready","status":"True","reason":"SecretSynced",...}]
kubectl get secret db-credentials -n prod
# → NAME             TYPE     DATA   AGE
# → db-credentials   Opaque   1      1m
```

#### Формат пути KV v2

В KV v2 путь API отличается от CLI-пути:

- CLI: `vault kv get secret/app/db` (без префикса `data/`)
- API/ESO: `secret/data/app/db` (с префиксом `data/`)

На этом спотыкаются почти все в первый раз. Если ESO выдаёт `secret not found`, а `vault kv get` из командной строки работает — скорее всего, дело в формате пути.

#### Синхронизация всех ключей из пути Vault

Если в KV-пути Vault много полей, используйте `dataFrom` вместо перечисления каждого:

```yaml
spec:
  dataFrom:
    - extract:
        key: secret/data/app/config
```

ESO создаёт Kubernetes Secret с записью на каждое поле секрета Vault. Если в секрете Vault есть поля `username`, `password` и `host`, в K8s Secret попадут все три.

#### Переименование ключей

Если имена полей в Vault не совпадают с ожидаемыми приложением в Kubernetes Secret:

```yaml
spec:
  data:
    - secretKey: DB_PASSWORD        # ключ K8s Secret
      remoteRef:
        key: secret/data/app/db
        property: password          # имя поля Vault
    - secretKey: DB_HOST
      remoteRef:
        key: secret/data/app/db
        property: host
```

#### Синхронизация учётных credentials Docker registry

У image pull secrets особый формат. ESO умеет формировать их напрямую:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: registry-creds
  namespace: app
spec:
  refreshInterval: 24h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: registry-creds
    creationPolicy: Owner
    template:
      type: kubernetes.io/dockerconfigjson
      data:
        .dockerconfigjson: |
          {"auths":{"registry.example.com":{"auth":"{{ .auth | b64enc }}"}}}
  data:
    - secretKey: auth
      remoteRef:
        key: secret/data/registry
        property: auth
```

Или если полный dockerconfigjson хранится в Vault:

```yaml
spec:
  data:
    - secretKey: .dockerconfigjson
      remoteRef:
        key: secret/data/registry
        property: dockerconfigjson
  target:
    template:
      type: kubernetes.io/dockerconfigjson
```

#### Политики creationPolicy

- **Owner** (рекомендуется): ESO владеет Secret. При удалении ExternalSecret Secret тоже удаляется. Secret нельзя изменить вручную — ESO перезапишет изменения при следующем refresh.
- **Merge**: ESO добавляет ключи в существующий Secret. Полезно, когда Secret создаёт Helm-чарт, а из Vault нужно лишь дописать дополнительные ключи. Существующие ключи в Secret сохраняются.
- **None**: ESO вообще не управляет жизненным циклом Secret — только создаёт его, если не существует, никогда не обновляет и не удаляет.

#### Отладка синхронизации

```bash
# Проверить, успешно ли синхронизировался ESO
kubectl get externalsecret -n app

# Посмотреть статус последней синхронизации и ошибку
kubectl describe externalsecret my-app-db-password -n app

# Принудительная немедленная ресинхронизация
kubectl annotate externalsecret my-app-db-password \
  force-sync=$(date +%s) -n app --overwrite
```

Приём с аннотацией `force-sync` выручает, когда значение в Vault уже обновлено, а ждать следующего интервала синхронизации не хочется.

**Проверка состояния ClusterSecretStore:**

```bash
kubectl get clustersecretstore vault-infra
kubectl describe clustersecretstore vault-infra
```

Рабочий ClusterSecretStore показывает `Valid: True`. Частые причины Invalid:

- Vault запечатан — проверьте `vault status`
- Неправильно наconfigured роль аутентификации — проверьте `vault read auth/kubernetes/role/external-secrets`
- Неправильный адрес Vault — проверьте поле `server` в ClusterSecretStore

**Типичные сообщения об ошибках:**

| Ошибка | Причина |
| :--- | :--- |
| `could not find key ...` | Поле `property` в `remoteRef` не существует в секрете Vault |
| `secret not found` | Неправильный формат пути (забыт префикс `data/` для KV v2) |
| `permission denied` | У роли Vault, которую использует ESO, нет прав чтения этого пути |
| `connection refused` | Vault запечатан или неправильный URL в поле `server` |

#### ESO с несколькими Vault namespace

При использовании Vault Enterprise с namespaces добавьте `namespace` в ClusterSecretStore:

```yaml
spec:
  provider:
    vault:
      server: "http://vault.vault.svc.cluster.local:8200"
      namespace: "admin/dev"  # Vault Enterprise namespace
      path: "secret"
      version: "v2"
```

`path` указывается относительно namespace — префикс `namespace` в путь включать не нужно.

#### ESO vs Sealed Secrets

| Характеристика | ESO | SealedSecrets |
| :--- | :--- | :--- |
| Источник секретов | Vault, AWS SM, GCP SM и т.д. | Git (зашифрованный) |
| Ротация | Автоматически по расписанию | Ручное перезапечатывание |
| Audit trail | В Vault | В Git |
| Air-gapped | Нужен доступ к Vault | Только Git |
| Перезапечатывание при пересборке кластера | Нет | Да |
| Работает без Vault | Нет | Да |
| Первоначальный bootstrap | Нужны Vault + ESO сначала | Работает с нуля |

Используем оба: SealedSecrets для bootstrap (kubeconfig, начальные учётные credentials registry, секреты инициализации Vault) и ESO для секретов приложений, которые живут в Vault и часто ротируются. Правило: всё, что нужно самому ESO для старта (адрес Vault, конфиг аутентификации), должно быть SealedSecret; всё остальное — ExternalSecret.

Работа с ESO в GitOps-потоке, а также продвинутые возможности (`dataFrom`, шаблоны, `Generators`, `PushSecret`) — на примерах в [GitOps: управление секретами](../../../GitOps/secrets_encryption.md).

### Паттерн «IaC готовит, ExternalSecret доставляет»

В инфраструктурах, где IaC управляет жизненным циклом ресурсов, секреты часто создаются на этапе provisioning и доставляются в Kubernetes через ExternalSecret. Этот паттерн отделяет создание секретов (IaC) от их синхронизации (ESO), что позволяет:

1. IaC-инструмент генерирует секреты (пароли, ключи) и записывает их во внешний KMS (Vault, AWS Secrets Manager).
2. IaC-инструмент создает объект `ExternalSecret`, указывающий путь к секрету в KMS.
3. ESO синхронизирует данные в нативный Kubernetes `Secret`.
4. Приложение читает секрет из стандартного `Secret` через environment variables или volume mount.

```yaml
# ExternalSecret: синхронизация из внешнего KMS
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: myapp-db-credentials
  namespace: myapp
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: myapp-db-credentials
    creationPolicy: Owner
  data:
  - secretKey: password
    remoteRef:
      key: secret/data/prod/myapp
      property: password
```

**Преимущества паттерна:**
- **Отделение ответственности:** IaC управляет жизненным циклом секрета (создание, ротация), ESO — доставкой в Kubernetes.
- **Идемпотентность:** При повторном apply ExternalSecret не пересоздается, если не изменились параметры.
- **Безопасность:** Значения секретов никогда не попадают в state IaC-инструмента (только ссылки на пути в KMS).

**Когда использовать:**
- При наличии зрелого процесса IaC (инструмент provisioning управляет всеми ресурсами кластера).
- Когда команда разработки не должна иметь прямого доступа к Vault/KMS.
- При необходимости автоматической ротации секретов (IaC обновляет значение в KMS → ESO синхронизирует в Kubernetes).

**Альтернативы:**
- **Vault Agent Injector:** Подходит, если приложение может работать с внешним API Vault напрямую (аннотации, sidecar).
- **Secrets Store CSI Driver:** Подходит для максимальной безопасности (секреты не попадают в `etcd`), но требует поддержки CSI в CNI-плагине.

### Использование Secrets Store CSI Driver

Наиболее безопасный метод, исключающий появление секрета в API Kubernetes.

**Особенности реализации:**
*   **SecretProviderClass:** Описывает список секретов во внешнем KMS и способ их монтирования.
*   **tmpfs:** Все секреты монтируются в оперативную память.
*   **Sync to K8s Secret:** Драйвер может опционально создавать нативный секрет для приложений, которые жестко привязаны к переменным окружения, но это снижает общий уровень безопасности.

**Как это работает:** на каждом узле развёрнуты CSI-драйвер (`DaemonSet`) и provider для конкретного хранилища (например, Vault). При старте Pod kubelet вызывает `NodePublishVolume`, драйвер обращается к provider, тот получает данные из KMS и монтирует их как файловый том на узел.

**Установка:**

```bash
helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm install csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver \
  -n kube-system --set enableSecretRotation=true
```

**Пример SecretProviderClass (провайдер Vault):**

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1   # v1 стабильна с драйвера v1.0.0-rc.1
kind: SecretProviderClass
metadata:
  name: vault-webapp
  namespace: prod
spec:
  provider: vault
  parameters:
    vaultAddress: "https://vault.vault.svc.cluster.local:8200"
    roleName: "webapp-role"                 # Vault-роль Kubernetes Auth
    objects: |
      - objectName: "db-password"
        secretPath: "secret/data/production/db"
        secretKey: "password"
  secretObjects:                            # НЕОБЯЗАТЕЛЬНО: дополнительная синхронизация в нативный Secret
  - secretName: db-credentials
    type: Opaque
    data:
    - objectName: "db-password"
      key: "password"
```

**Монтирование в Pod:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
  namespace: prod
spec:
  template:
    spec:
      containers:
      - name: app
        image: nginx:1.27
        volumeMounts:
        - name: secrets
          mountPath: "/mnt/secrets-store"
          readOnly: true
      volumes:
      - name: secrets
        csi:
          driver: secrets-store.csi.k8s.io
          readOnly: true
          volumeAttributes:
            secretProviderClass: "vault-webapp"   # SPC должен быть в том же namespace, что и Pod
          nodePublishSecretRef:                    # если провайдер требует авторизацию при монтировании
            name: csi-auth                         # нативный Secret с креденшилами в том же namespace
```

> Если используется `nodePublishSecretRef`, нативный Secret с креденшилами необходимо пометить меткой `secrets-store.csi.k8s.io/used=true`, иначе ротация завершится с ошибкой `failed to get node publish secret`.

**Автоматическая ротация (CSI v1.6+):** вместо отдельного контроллера ротации используется CSI-механизм `RequiresRepublish` — kubelet периодически вызывает `NodePublishVolume`, и драйвер при `--enable-secret-rotation=true` заново запрашивает значения у провайдера. Флаг `--rotation-poll-interval` (по умолчанию `2m`) задаёт минимальную паузу между ротациями. При ротации обновляются и смонтированные файлы, и нативные `Secret` из `secretObjects`. Состояние привязки Pod к SecretProviderClass отслеживается в CR `SecretProviderClassPodStatus`.

**Проверка:**

```bash
kubectl exec -n prod deploy/webapp -- ls -la /mnt/secrets-store
# → db-password
kubectl get secretproviderclasspodstatus -n prod
# → Name: vault-webapp...  	Status: {"secrets": [...]}
```

**Ограничения:** том монтируется один раз при старте Pod — если приложение читает секрет из переменных окружения или не перечитывает файл, потребуется перезапуск (автоматизация — [Reloader](../../ToolsUtilities/reloader/reloader_usage_scenarios.md)). Диагностика затруднена: значения не видны через `kubectl get secret`, содержимое проверяется только внутри Pod.

### Интеграция через Vault Agent (Sidecar)

Паттерн для сред, использующих HashiCorp Vault. В 2026 году рекомендуется использовать **Native Sidecar Containers** (Kubernetes 1.29+, beta с 1.28), определяемые в блоке `initContainers` с `restartPolicy: Always`: агент гарантированно запускается раньше основного контейнера, остаётся жить на протяжении всего жизненного цикла Pod и завершается после остановки основных контейнеров, что устраняет race conditions при первичном рендеринге.

*   **Init-контейнер:** Получает первичный токен и рендерит секреты в общую директорию.
*   **Sidecar-контейнер:** Обновляет секреты по мере их ротации в Vault.
*   **Vault Agent Injector:** Mutating Webhook, который автоматически внедряет эти контейнеры в Pod на основе аннотаций.

**Аннотации Injector (пример):**

```yaml
annotations:
  vault.hashicorp.com/agent-inject: "true"            # включить внедрение агента
  vault.hashicorp.com/role: "webapp-role"             # роль Kubernetes Auth
  vault.hashicorp.com/agent-inject-secret-db-pass: "secret/data/production/db"  # путь KV v2
  vault.hashicorp.com/agent-inject-template-db-pass: |
    {{- with secret "secret/data/production/db" }}
    {{ .Data.data.password }}
    {{- end }}
  vault.hashicorp.com/auth-path: "auth/kubernetes"
  vault.hashicorp.com/namespace: ""                   # для Vault Enterprise namespaces
```

**Проверка:**

```bash
kubectl describe pod -n prod webapp | grep -A2 "Vault Agent"
# → Init Containers:   vault-agent-init
# → Containers:        vault-agent, vault-agent-init
kubectl exec -n prod deploy/webapp -- ls -la /vault/secrets
# → db-pass
```

Детальное руководство: [Vault Agent: основы](../../../Vault/guides/vault_agent/basics.md) (шаблоны, Auto-Auth), [Vault Agent Sidecar](../../../Vault/guides/vault_agent/sidecar_pattern.md) (ручное внедрение, native sidecar, `SIGHUP`), [Vault Agent Injector](../../../Vault/guides/vault_agent/injector.md) (аннотации, кэширование, WIF).

## Дополнительная информация

### Аутентификация и идентификация (Workload Identity)

Безопасность внешней интеграции зависит от того, как кластер доказывает свою личность внешнему KMS.

*   **Kubernetes Auth Method (Vault):** Vault проверяет ServiceAccount токен через TokenReview API самого Kubernetes. В роли задаются `bound_service_account_names`, `bound_service_account_namespaces`, `policies`, `audience` и `ttl`. Для доступа к TokenReview ServiceAccount Vault необходима привязка к роли `system:auth-delegator`. Полная настройка — в [Интеграции Vault с Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md).
*   **Проецируемые (bound) ServiceAccount-токены:** короткоживущие JWT, монтируемые в Pod через projected volume с полями `audience`, `expirationSeconds`, `path`. Используются ESO, VSO, CSI-провайдером и Vault Agent для аутентификации без долгоживущих статических токенов. В Vault 1.21+ роли Kubernetes Auth обязаны содержать `audience`.
*   **AppRole:** способ аутентификации для не-Kubernetes клиентов (CI/CD, серверы приложений вне кластера): `RoleID`/`SecretID` с TTL и ограничением использования. Подробнее — [Vault AppRole](../../../Vault/guides/vault_auth_approle.md).
*   **AWS (IRSA):** Использование OIDC-провайдера кластера для обмена Kubernetes ServiceAccount Token на временные AWS IAM Credentials.
*   **GCP/Azure (Workload Identity Federation):** Аналогичный механизм федерации идентичностей без использования секретных ключей в манифестах.

### Безопасность интеграции

1.  **Принцип наименьших привилегий:** политика Vault для каждой роли ограничена конкретными путями (`path "secret/data/production/app/*" { capabilities = ["read"] }`), короткие TTL, предпочтение динамических секретов с автоистечением.
2.  **RBAC Kubernetes:** создание `ClusterSecretStore` ограничивается платформенной командой (админ кластера), `ExternalSecret` — только в своих namespace; права на CRD задаются через `ClusterRole`.
3.  **NetworkPolicy:** egress-политики разрешают доступ к адресу Vault/провайдера только нужным компонентам (оператор ESO, CSI-провайдер, Vault Agent), остальной исходящий трафик по умолчанию запрещён.
4.  **Креденшилы интеграций** не хранятся в Git и манифестах — только ссылки; используются Kubernetes Auth, AppRole, WIF.
5.  **Аудит:** включите Vault audit log (записи о доступе к секретам) и мониторинг запросов; шифрование данных в `etcd` не отменяет аудит на стороне KMS.
6.  **Снижение следа в etcd:** где возможно, используйте CSI-монтирование вместо синхронизации в нативные `Secret`.

### Наблюдаемость и диагностика

-   **ESO:** статус каждого ресурса виден через `kubectl get externalsecret -A -o wide`, условия — в `status.conditions`; события — `kubectl describe externalsecret <name>`; логи оператора — `kubectl logs deploy/external-secrets -n external-secrets`.
-   **Взаимодействие с приложениями:** при ротации приложению, читающему секрет из окружения, нужен перезапуск — используйте [Reloader](../../ToolsUtilities/reloader/reloader_usage_scenarios.md) (аннотация `reloader.stakater.com/auto: "true"`) или rollout на изменение содержимого `Secret`.
-   **CSI:** сбои монтирования видны в событиях Pod (`FailedMount`, `SecretProviderClassNotFound`) и в логах драйвера/provider на соответствующем узле; привязка Pod к SecretProviderClass — в `SecretProviderClassPodStatus`.

### Типичные проблемы и их решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `ExternalSecret` создан, но нативный `Secret` не появился | Ошибка аутентификации, политика Vault, недоступность `server` | `kubectl get externalsecret -o yaml` → `status.conditions`; проверить `ClusterSecretStore` и логи ESO |
| Условие `RefreshFailed` / `SecretSyncError` | Отзыв токена/роли, изменение пути, rate limit хранилища | Проверить условия и события; скорректировать `refreshInterval` или креденшилы |
| `no matches for kind "SecretStore" in version "external-secrets.io/v1beta1"` | Ресурс на старой API-версии (ESO ≥ 0.17 не отдаёт `v1beta1`) | Перевести манифесты на `external-secrets.io/v1` и обновить ресурсы до апгрейда |
| `could not find key ...` | Поле `property` в `remoteRef` не существует в секрете Vault | Проверить имя поля в Vault через `vault kv get <path>` |
| `secret not found` | Неправильный формат пути (забыт префикс `data/` для KV v2) | Использовать путь вида `secret/data/<...>` вместо CLI-пути `secret/<...>` |
| `permission denied` | У роли Vault, которую использует ESO, нет прав чтения этого пути | Проверить политику Vault (`vault policy read`) и права на `secret/metadata/*` для list |
| `connection refused` | Vault запечатан или неправильный URL в поле `server` | Проверить `vault status` и поле `server` в ClusterSecretStore |
| CSI: том пуст или монтирование падает | Ошибки в `SecretProviderClass`, нет provider (`DaemonSet`), недоступен Vault | `kubectl describe pod` → события `FailedMount`; проверить SPC, логи провайдера на узле |
| CSI: ротация не происходит | `enableSecretRotation=false` | Включить Helm-значение `enableSecretRotation` и настроить `rotationPollInterval` |
| `failed to get node publish secret` | Нативному Secret с креденшилами не хватает метки | `kubectl label secret <name> secrets-store.csi.k8s.io/used=true` |
| Vault Agent не рендерит файл | Неверный шаблон/роль, политика запрещает доступ | Логи контейнера `vault-agent`; проверить роль и таргет-политику Vault |
| Приложение видит старые значения (окружение) | `Secret` обновлён, но поды не перезапущены | Rolling Update, [Reloader](../../ToolsUtilities/reloader/reloader_usage_scenarios.md), restart on change |

### Рекомендации и лучшие практики

1.  По умолчанию выбирайте **ESO** для «прозрачной» миграции — приложения продолжают читать нативные `Secret`, синхронизированные из KMS; **CSI** — когда наличие секретов в `etcd` недопустимо; **VSO/Sidecar** — при глубокой интеграции с Vault и использовании динамических секретов.
2.  Соблюдайте наименьшие привилегии (политики Vault, RBAC на CRD ESO); раздельные `SecretStore` на namespace при мультиарендности.
3.  Не устанавливайте слишком агрессивный `refreshInterval` (в production обычно 1–5 минут): это снижает нагрузку на API провайдера и стоимость вызовов.
4.  Мониторите статус синхронизации (`Ready`/`RefreshFailed`), настраивайте алерты на долгое расхождение.
5.  Храните `ExternalSecret`/`ClusterSecretStore` декларативно в Git ([GitOps: управление секретами](../../../GitOps/secrets_encryption.md)); учитывайте, что при стратегиях бэкапа публично доступны только определения, а не значения ([Бэкапы](../../Operations/backup-strategies.md)).
6.  Тестируйте ротацию в staging-окружении, не логируйте значения секретов, периодически анализируйте Vault audit log.
7.  **Bootstrap-паттерн (ESO + SealedSecrets):** всё, что нужно самому ESO для старта (адрес Vault, конфигурация аутентификации, начальные учётные credentials registry, секреты инициализации Vault) храните как SealedSecret — это работает с нуля без доступа к Vault. Всё остальное — через ExternalSecret. Секреты приложений, которые живут в Vault и часто ротируются, доставляйте через ESO.
8.  При использовании Vault Enterprise с namespaces задавайте `namespace` в `ClusterSecretStore` отдельно от `path` — путь указывается относительно namespace.

### Выбор решения

1.  **ESO:** Если нужно "прозрачно" заменить существующие секреты на данные из KMS без изменения кода и манифестов приложений.
2.  **CSI Driver:** Для высоконагруженных или критически важных систем, где недопустимо наличие секретов в `etcd`.
3.  **VSO / Sidecar:** При глубокой интеграции с экосистемой HashiCorp и использовании динамических секретов (например, временных пользователей базы данных).

### Смотрите также

- [Безопасность Secret](security.md) — общие принципы и KMS v2.
- [Хранение в etcd](etcd_storage.md) — риски и механизмы шифрования.
- [Интеграция Vault с Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md) — детальные инструкции по настройке.
- [Helm + секреты](helm_secrets.md) — управление секретами в Helm-чартах.
- [Секреты в StatefulSet](statefulset_secrets.md) — паттерны для баз данных и stateful-приложений.
- [Sealed Secrets](../../Security/sealed_secrets_overview.md) — шифрование секретов для Git.
- [SOPS](../../../Security/Tools/sops_overview.md) — шифрование файлов через Mozilla SOPS.
- [GitOps: управление секретами](../../../GitOps/secrets_encryption.md) — сравнение подходов к хранению секретов в Git.