# Интеграция Vault с Kubernetes

## Определения

**Интеграция Vault с Kubernetes** — совокупность архитектурных паттернов и инструментов для обеспечения безопасности секретов в контейнеризированных средах. Основная цель — исключение хранения чувствительных данных в `etcd` в открытом виде и реализация модели динамического управления секретами.

**CSI (Container Storage Interface) Driver** — стандартный интерфейс для подключения систем хранения к Kubernetes. **Secrets Store CSI Driver** монтирует секреты из Vault напрямую в поды как виртуальный том (tmpfs). Приложение видит секреты как обычные файлы.

**Vault Secrets Operator (VSO)** — современный нативный контроллер Kubernetes, который синхронизирует секреты из Vault напрямую в объекты `Secret` Kubernetes или монтирует их, поддерживая автоматическую ротацию и интеграцию с нативными ресурсами через CRD.

**Vault Agent Injector** — механизм на основе Mutating Admission Webhook, который автоматически внедряет sidecar-контейнеры Vault Agent в поды для аутентификации и рендеринга секретов на основе аннотаций.

**CRD (Custom Resource Definition)** — механизм расширения API Kubernetes для создания собственных типов ресурсов (например, `SecretProviderClass` или `VaultStaticSecret`).

**JWT (JSON Web Token)** — стандарт токенов доступа, используемый Kubernetes для аутентификации подов (через ServiceAccount) в Vault.

**VaultConnection** — CRD (API `secrets.hashicorp.com/v1beta1`) для Vault Secrets Operator (VSO), описывающий параметры подключения к серверу Vault (`address`, TLS, `skipTLSVerify`, строку подключения сертификата CA через `caCertSecretRef`). `VaultAuth` и остальные ресурсы VSO ссылаются на него через `vaultConnectionRef`.

**VaultAuth** — CR для VSO, определяющий способ аутентификации к Vault (Kubernetes, JWT, AppRole) и роль (`mount`, `role`, `serviceAccount`). Глобальная конфигурация может быть вынесена в ресурс `VaultAuthGlobal` (VSO v0.8.0+) для сокращения дублирования в мульти-прикладных средах.

**VaultStaticSecret** — CR для VSO, синхронизирующий статические секреты из Vault (KV v2) в нативный Kubernetes `Secret` с интервалом `refreshAfter`.

**VaultDynamicSecret** — CR для VSO, синхронизирующий динамические секреты (базы данных, внешние системы: `db` и др.) с автоматическим продлением аренды.

**VaultPKISecret** — CR для VSO, синхронизирующий сертификаты PKI Vault (например, выданные через `pki/issue`) в Kubernetes `Secret` с автоматической заменой перед истечением срока действия (`expiryOffset`, `ttl`).

**Rollout-restart** — функция VSO: при ротации или дрейфе секрета оператор автоматически инициирует `kubectl rollout restart` (через `rolloutRestartTargets`), перезапуская поды приложений без ручного участия.

**`refreshAfter`** — интервал времени (например, `30s`, `5m`), через который VSO повторно синхронизирует статические секреты из Vault в Kubernetes `Secret`. Гарантирует, что изменения в Vault отражаются в кластере с заданной периодичностью.

**`expiryOffset`** — запас времени (например, `10m`), за который `VaultPKISecret` инициирует обновление сертификата до его фактического истечения. Позволяет избежать простоев из-за задержки распространения нового сертификата.

**`rolloutRestartTargets`** — список ресурсов Kubernetes (`Deployment`, `StatefulSet`, `DaemonSet`), которые VSO перезапускает при изменении секрета. Позволяет принудительно перечитать секрет из файлов или переменных окружения без внешних инструментов (например, Reloader).

**`audience`** — поле в роли Kubernetes Auth Method Vault, ограничивающее валидные аудитории JWT-токена. Начиная с Vault 1.21+, поле `audience` обязательно для роли `auth/kubernetes`. Если токен содержит аудиторию, не совпадающую с ролью, аутентификация отклоняется. Это предотвращает переиспользование токенов ServiceAccount за пределами Vault.

## Основные концепции

#### Почему Vault, а не Kubernetes Secrets + SealedSecrets

Kubernetes Secrets закодированы в base64 и по умолчанию не зашифрованы при хранении (если вы не настроили шифрование etcd). SealedSecrets решают задачу «зашифровать перед коммитом в Git», но не решают:

    Ротацию секретов — при каждой смене пароля нужно перезапечатать и развернуть заново
    Audit trail — кто какой секрет читал и когда
    Динамические секреты — учётные данные БД, действительные 1 час, автоматически отзываемые после использования
    Детальное управление доступом — какой под может читать какой путь секрета

Vault решает всё это. Эксплуатация Vault требует заметных усилий (unseal, управление ключами), но для production-сред с несколькими командами и требованиями compliance это оправданно.

### Архитектура Vault в Kubernetes

Развертывание Vault в Kubernetes — распространённый паттерн для централизованного управления секретами кластера. Vault работает как **StatefulSet** в выделенном namespace (например, `vault`), а для хранения данных в HA-режиме используется **Raft** (Integrated Storage) — встроенный бэкенд, не требующий внешних зависимостей.

**Компоненты архитектуры:**
- **StatefulSet `vault`:** управляет подами сервера Vault (`vault-0`, `vault-1`, `vault-2`). Каждый под имеет стабильное сетевое имя и порядковый индекс.
- **Raft storage:** данные реплицируются между подами через внутренний порт `8201`. Лидер обрабатывает запись, остальные реплики обслуживают чтение (stale reads при настройке `read_consistency`).
- **Service `vault`:** ClusterIP-сервис, через который приложения и операторы обращаются к активному лидеру Vault.
- **Service `vault-internal`:** сервис для взаимодействия реплик между собой (рекомендуется для `retry_join`).
- **Auto-unseal:** в production необходимо автоматическое распечатывание. Поскольку облачные KMS (AWS KMS, GCP CKMS) относятся к облачным технологиям и исключены из рассмотрения, используется **Transit seal** — Vault сам хранит мастер-ключ и расшифровывает данные через Transit Engine, либо ручное распечатывание (только для dev/test). Для Yandex Cloud KMS можно использовать следующую конфигурацию:

  ```hcl
  seal "transit" {
    address = "https://kms.yandex"
    key_name = "vault-unseal-key"
    # Использует метаданные виртуальной машины для аутентификации в YC
  }
  ```

**Service discovery:**
- `service_registration "kubernetes" {}` в конфигурации Vault автоматически регистрирует сервис в Kubernetes API.
- Рaft-реплики используют `retry_join` для обнаружения лидера через DNS (`vault-0.vault-internal:8200`).
- При масштабировании или падении пода реплика автоматически присоединяется к кластеру.

**Важно:** в HA-кластере на Raft распечатывание требуется для каждого пода, включая standby-реплики. Ручной процесс допустим только для первичной инициализации; в production используйте Transit seal.

### Стратегии интеграции

| Подход | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Vault Secrets Operator (VSO)** | Нативный контроллер + CRD. Синхронизирует секреты в объекты `Secret` или монтирует их. | Нативный UX, поддержка ротации, минимальное потребление ресурсов. | Требует установки оператора и настройки CRD. |
| **Vault Agent Sidecar** | Дополнительный контейнер в поде аутентифицируется и рендерит секреты в `emptyDir`. | Нет кластерных компонентов; поддержка ротации с сигналом `SIGHUP`. | Требует модификации каждого `Deployment`. |
| **Vault Injector** | Автоматическое внедрение агента через Webhook на основе аннотаций. | Не требует ручной модификации манифестов; централизованное управление. | Зависимость от компонента Injector; нагрузка на API. |
| **Secrets Store CSI Driver** | Монтирование секретов напрямую как тома (tmpfs). | Секреты не попадают в `etcd`; универсальный стандарт. | Сложен в отладке; требует драйвера на всех узлах. |

### Аутентификация: Метод Kubernetes

Vault доверяет Kubernetes API через метод аутентификации `kubernetes`:
1.  Под использует JWT-токен своего `ServiceAccount`.
2.  Vault проверяет подпись токена через Kubernetes Token Review API.
3.  При совпадении параметров (Namespace, ServiceAccount, Audience) Vault выдает токен доступа с соответствующей политикой.

**Параметр `audience`:** начиная с Vault 1.21+, роли Kubernetes Auth Method обязаны содержать `audience`. Это ограничивает валидные аудитории JWT-токена. Если токен содержит аудиторию, не указанную в роли, аутентификация отклоняется. Для совместимости можно задать `audience = "vault"` (значение по умолчанию в Vault).

### Безопасность кластера Vault

#### RBAC для Vault Server

Сам кластер Vault должен быть защищён минимальными привилегиями. ServiceAccount для пода Vault должен иметь только необходимые права:

```yaml
# vault-server-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vault
  namespace: vault
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: vault-server
rules:
- apiGroups: [""]
  resources: ["serviceaccounts"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["endpoints"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list"]
- apiGroups: ["admissionregistration.k8s.io"]
  resources: ["mutatingwebhookconfigurations"]
  verbs: ["get", "list"]
  # Для service_registration "kubernetes"
- apiGroups: [""]
  resources: ["services"]
  verbs: ["create", "get", "list", "update", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: vault-server
subjects:
- kind: ServiceAccount
  name: vault
  namespace: vault
roleRef:
  kind: ClusterRole
  name: vault-server
  apiGroup: rbac.authorization.k8s.io
```

> **Важно:** Helm-чарт HashiCorp Vault создаёт RBAC автоматически при `server.ha.enabled=true`. Явное указание `serviceAccount.create=false` и предсозданный SA требуют ручного создания ClusterRole/ClusterRoleBinding.

#### Network Policies

Ограничьте трафик к Vault только authorised sources. Пример NetworkPolicy для namespace `vault`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: vault-allow
  namespace: vault
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: vault
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: prod
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: vault
    ports:
    - protocol: TCP
      port: 8200
    - protocol: TCP
      port: 8201
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: vault
    ports:
    - protocol: TCP
      port: 8201
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 127.0.0.0/8
    ports:
    - protocol: TCP
      port: 443
    - protocol: UDP
      port: 53
```

#### Pod Disruption Budget

Обеспечьте доступность Vault при плановых работах на узлах:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: vault
  namespace: vault
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: vault
```

#### Resource Requests и Limits

Для стабильной работы Vault в production задавайте явные запросы и лимиты ресурсов. Рекомендации для HA-кластера из 3 реплик:

| Компонент | CPU Request | CPU Limit | Memory Request | Memory Limit |
| :--- | :--- | :--- | :--- | :--- |
| Vault Server | 500m | 2000m | 256Mi | 512Mi |
| Vault Agent Injector | 100m | 500m | 128Mi | 256Mi |
| Vault CSI Provider | 50m | 200m | 64Mi | 128Mi |

Пример обновления `values.yaml`:

```yaml
server:
  resources:
    requests:
      cpu: 500m
      memory: 256Mi
    limits:
      cpu: 2000m
      memory: 512Mi
  ha:
    enabled: true
    replicas: 3
    raft:
      enabled: true
      config: |
        ui = true
        listener "tcp" {
          tls_disable = 1
          address = "[::]:8200"
          cluster_address = "[::]:8201"
        }
        storage "raft" {
          path = "/vault/data"
        }
        service_registration "kubernetes" {}
        seal "transit" {
          address = "https://vault.vault.svc.cluster.local:8200"
          token = "<recovery-token>"
          disable_renewal = false
        }
```

> **Примечание:** `tls_disable = 1` приведён только для упрощения демонстрации. В production TLS должен быть включён с валидными сертификатами.

#### Service Account Token Volume Projection

Для более безопасной аутентификации используйте проекцию токенов ServiceAccount с ограниченным TTL:

```yaml
# vault-server-patch.yaml
spec:
  template:
    spec:
      serviceAccountName: vault
      containers:
      - name: vault
        volumeMounts:
        - name: vault-service-account-token
          mountPath: "/var/run/secrets/kubernetes.io/serviceaccount"
          readOnly: true
      volumes:
      - name: vault-service-account-token
        projected:
          sources:
          - serviceAccountToken:
              path: token
              expirationSeconds: 3600
              audience: vault
```

### Мониторинг и аудит

#### Health Checks

Настройте `livenessProbe` и `readinessProbe` для пода Vault:

```yaml
server:
  livenessProbe:
    httpGet:
      path: /v1/sys/health
      port: 8200
      scheme: HTTP
    initialDelaySeconds: 60
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 3
  readinessProbe:
    httpGet:
      path: /v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200
      port: 8200
      scheme: HTTP
    initialDelaySeconds: 30
    periodSeconds: 10
```

Эндпоинт `/v1/sys/health` возвращает различные коды HTTP в зависимости от состояния кластера. Используйте `standbyok=true` для standby-реплик и `sealedcode=200` чтобы не помечать sealed-поды как неготовые во время инициализации.

#### Audit Devices

В production включите минимум два audit device для отказоустойчивости логов:

```bash
# File audit device (локальный диск)
vault audit enable file file_path=/vault/audit/audit.log log_raw=true

# Syslog audit device (удалённый сервер)
vault audit enable syslog tag="vault-audit" facility="AUTH"
```

**Важно:** 10Gi достаточно для хранения секретов, но при включённом audit logging объём быстро растёт. Рекомендуется размещать audit логи в отдельном томе с достаточным объёмом хранения в зависимости от объёма аудита.

Audit логи содержат хэшированные значения запросов и ответов, что позволяет отслеживать активность без раскрытия plaintext. В Kubernetes audit device на file монтируется через PersistentVolumeClaim.

#### Prometheus Metrics

Vault exposes метрики на `/v1/sys/metrics` (Prometheus формат). Helm-чарт включает ServiceMonitor при установке Prometheus Operator:

```yaml
server:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
      interval: 15s
```

Ключевые метрики для мониторинга:
- `vault.core.unsealed` — состояние распечатанности (1 = unsealed).
- `vault.cache.hit` / `vault.cache.miss` — эффективность кэша запросов.
- `vault.token.count.by_policy` — количество токенов с привязанной политикой.
- `vault.seal.in_progress` — процесс распечатывания в кластере.

### Резервное копирование и восстановление

Для HA-кластеров на Raft используйте **Raft snapshots** для создания резервных копий:

```bash
# Создание снапшота
kubectl exec -n vault vault-0 -- vault operator raft snapshot save /tmp/vault.snap

# Копирование из пода (snapshoot создаётся на временной файловой системе пода)
kubectl cp vault/vault-0:/tmp/vault.snap ./vault-backup.snap
```

Восстановление из снапшота:

```bash
# Остановка кластера
kubectl scale statefulset vault -n vault --replicas=0

# Восстановление (выполняется на каждом поде последовательно)
kubectl exec -i -n vault vault-0 -- vault operator raft snapshot restore /tmp/vault.snap

# Запуск кластера
kubectl scale statefulset vault -n vault --replicas=3
```

> **Важно:** снапшот содержит все данные Vault (секреты, политики, конфигурацию). Храните его в защищённом хранилище с контролем доступа.

### Обновление Vault

Обновление Vault в Kubernetes выполняется через Helm-чарт:

```bash
# 1. Обновление зависимостей
helm repo update hashicorp

# 2. Просмотр изменений
helm upgrade --dry-run vault hashicorp/vault -n vault -f values.yaml

# 3. Применение обновления
helm upgrade vault hashicorp/vault -n vault -f values.yaml
```

**Порядок обновления для HA-кластера:**
1. Обновите Helm-чарт.
2. Podы перезапускаются последовательно (rolling update).
3. Standby-реплика обновляется, остаётся standby.
4. Лидер переключается на обновлённую реплику.
5. Оставшиеся реплики обновляются по очереди.

**Проверка после обновления:**

```bash
# Проверка версии на каждом поде
kubectl exec -n vault vault-0 -- vault version
kubectl exec -n vault vault-1 -- vault version
kubectl exec -n vault vault-2 -- vault version

# Проверка статуса кластера
kubectl exec -n vault vault-0 -- vault status

# Проверка работоспособности
vault login <recovery-token>
vault read sys/health
```

## Практические сценарии

### Шаг 1: Установка Vault и инфраструктуры

**Установка через Helm (HA-режим).** Официальный Helm-чарт `hashicorp/vault` (актуальный: chart `0.34.x`, app `2.0.x`) требует Helm 3.6+ и Kubernetes 1.29+. Рекомендуемый способ хранения для Kubernetes — **Raft (Integrated Storage)**; внешние бэкенды (PostgreSQL, Consul) поддерживаются для миграций и легаси-инсталляций.

**Вариант 1 — HA на Raft (рекомендуемый).** Требует совместимый StorageClass; включает автоматический unseal с **Auto-unseal** (KMS/HSM) во избежание ручного распечатывания при масштабировании:

```yaml
# values.yaml
injector:
  enabled: true # Включение инжектора

server:
  serviceAccount:
    create: true
    name: vault
  ha:
    enabled: true
    replicas: 3
    raft:
      enabled: true
      setNodeId: true # node_id = имя пода (vault-0, vault-1, ...)
      config: |
        ui = true
        listener "tcp" {
          tls_disable = 1
          address = "[::]:8200"
          cluster_address = "[::]:8201"
        }
        storage "raft" {
          path = "/vault/data"
          # retry_join задаётся автоматически благодаря service_registration "kubernetes"
        }
        service_registration "kubernetes" {}
        seal "transit" {
          address = "https://vault.vault.svc.cluster.local:8200"
          token = "<recovery-token>"
          disable_renewal = false
        }
  resources:
    requests:
      cpu: 500m
      memory: 256Mi
    limits:
      cpu: 2000m
      memory: 512Mi
  dataStorage:
    enabled: true
    size: 10Gi
    storageClass: "standard" # по умолчанию кластера
  livenessProbe:
    httpGet:
      path: /v1/sys/health
      port: 8200
      scheme: HTTP
    initialDelaySeconds: 60
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 3
  readinessProbe:
    httpGet:
      path: /v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200
      port: 8200
      scheme: HTTP
    initialDelaySeconds: 30
    periodSeconds: 10

csi:
  enabled: false # CSI провайдер подключается отдельно (см. шаг 5)

# NetworkPolicy (требует enableNetworkPolicies=true или установки отдельно)
networkPolicy:
  enabled: true
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: vault
      ports:
        - protocol: TCP
          port: 8201
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 127.0.0.0/8
      ports:
        - protocol: TCP
          port: 443
        - protocol: UDP
          port: 53

# Pod Disruption Budget
podDisruptionBudget:
  minAvailable: 2
```

> **Примечание про auto-unseal:** Для HA-кластера из 3 и более реплик ручное распечатывание каждого pod неприемлемо. Используйте `seal "transit"` (Transit Engine Vault) для автоматического распечатывания. Без внешнего распечатчика новый pod из расширенной реплики не сможет самостоятельно расшифровать данные. Для development-сред допустимо ручное распечатывание.

**Вариант 2 — HA с внешним хранилищем PostgreSQL (легаси-традиция):**

```yaml
# values.yaml
injector:
  enabled: true # Включение инжектора

server:
  ha:
    enabled: true
    replicas: 3
  dataStorage:
    enabled: false
  extraVolumes:
    - type: secret
      name: vault-postgresql-secret
  config: |
    ui = true
    listener "tcp" {
      tls_disable = 1
      address = "[::]:8200"
      cluster_address = "[::]:8201"
    }
    storage "postgresql" {
      connection_url = "postgres://$(VAULT_POSTGRESQL_USERNAME):$(VAULT_POSTGRESQL_PASSWORD)@$(VAULT_POSTGRESQL_HOST):5432/vaultdb?sslmode=disable"
    }

csi:
  enabled: true # Включение CSI провайдера
```

**Вариант 3 — Оффлайн установка в закрытом контуре (Harbor).** Используется, когда публичные репозитории HashiCorp недоступны. Процесс состоит из трёх фаз: подготовка артефактов на машине с интернетом, загрузка образов и чарта в Harbor, установка из локального репозитория.

#### Подготовка пакетов и образов (внешний контур)

```bash
git clone https://github.com/hashicorp/vault-helm.git
cd vault-helm

# Формирование values.yaml для извлечения образов
helm template vault ./vault -f values.yaml > rendered.yaml
grep -oE 'image:\s*"?[^"]+' rendered.yaml | sed -E 's/^image:\s*"?//; s/"$//' | sort -u > vault-images.txt

# Скачивание образов
while read -r img; do
  docker pull "$img"
done < vault-images.txt

# Сохранение в единый архив
docker save -o vault-images.tar $(cat vault-images.txt)

# Упаковка HELM чарта
helm package ./vault -d .
```

#### Перенос в закрытый контур

```bash
# Распаковка артефактов (vault-images.tar, vault-*.tgz)
tar -xvf vault-0.32.0.tgz

# Загрузка образов в Harbor (внутри создан проект platform)
docker load -i vault-images.tar

export HARBOR="harbor.domain.local"
export PROJECT="platform"

while read -r img; do
  new="${HARBOR}/${PROJECT}/${img}"
  docker tag "${img}" "$new"
  docker push "$new"
done < vault-images.txt

# Очистка временных файлов
rm vault-*/rendered.yaml

# Публикация чарта в Harbor OCI-репозиторий
helm package ./vault-* -d .
helm push vault-*.tgz oci://${HARBOR}/helm
```

#### Секрет для доступа к Harbor

Если репозиторий приватный, создайте `docker-registry` секрет из робота Harbor:

```bash
kubectl -n vault create secret docker-registry harbor-secret \
  --docker-server=harbor.domain.local \
  --docker-username='robot$auth-robot' \
  --docker-password='REPLACE_ME' \
  --docker-email=robot@myemail.com
```

#### Файл values.yaml для закрытого контура

```yaml
global:
  imagePullSecrets:
    - name: harbor-secret
  tlsDisable: true
server:
  image:
    repository: harbor.domain.local/platform/hashicorp/vault
  standalone:
    enabled: false
  ha:
    enabled: true
    replicas: 3
    raft:
      enabled: true
      config: |
        ui = true
        listener "tcp" {
          address         = "0.0.0.0:8200"
          cluster_address = "0.0.0.0:8201"
          tls_disable     = 1
        }
        storage "raft" {
          path = "/vault/data"
          retry_join {
            leader_api_addr = "http://vault-0.vault-internal:8200"
          }
        }
        service_registration "kubernetes" {}
  dataStorage:
    enabled: true
    storageClass: longhorn
    size: 7Gi
  auditStorage:
    enabled: true
    storageClass: longhorn
    size: 5Gi
  ui:
    enabled: true
    serviceType: ClusterIP
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - host: vault.k8s.domain.local
    tls: []
injector:
  enabled: true
  image:
    repository: harbor.domain.local/platform/hashicorp/vault-k8s
  agentImage:
    repository: harbor.domain.local/platform/hashicorp/vault
```

#### Установка

```bash
helm install vault oci://harbor.domain.local/helm/vault \
  -n vault \
  --create-namespace \
  -f vault-values.yaml
```

### Шаг 2: Инициализация и распечатывание (Unseal)

После развертывания поды находятся в состоянии `Sealed`.

**1. Инициализация (один раз):**
```bash
kubectl exec -n vault vault-0 -- vault operator init -key-shares=5 -key-threshold=3 -format=json > cluster-keys.json
```

**2. Распечатывание (на каждой реплике):**
```bash
UNSEAL_KEY_1=$(jq -r ".unseal_keys_b64[0]" cluster-keys.json)
UNSEAL_KEY_2=$(jq -r ".unseal_keys_b64[1]" cluster-keys.json)
UNSEAL_KEY_3=$(jq -r ".unseal_keys_b64[2]" cluster-keys.json)

# Печать команд выполняется в контексте каждого пода отдельно
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_1
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_2
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_3

kubectl exec -n vault vault-1 -- vault operator unseal $UNSEAL_KEY_1
kubectl exec -n vault vault-1 -- vault operator unseal $UNSEAL_KEY_2
kubectl exec -n vault vault-1 -- vault operator unseal $UNSEAL_KEY_3

kubectl exec -n vault vault-2 -- vault operator unseal $UNSEAL_KEY_1
kubectl exec -n vault vault-2 -- vault operator unseal $UNSEAL_KEY_2
kubectl exec -n vault vault-2 -- vault operator unseal $UNSEAL_KEY_3
```

**Альтернативный вариант с использованием цикла:**
```bash
for pod in vault-0 vault-1 vault-2; do
  for key in $(cat cluster-keys.json | jq -r '.unseal_keys_b64[:3][]'); do
    kubectl exec -n vault $pod -- vault operator unseal $key
  done
done
```

> **Примечание:** в HA-кластере на Raft распечатывать нужно каждый pod (`vault-0`, `vault-1`, `vault-2`). Под, проигравший выборы лидера (standby), также требует распечатывания перед переходом в active. Описанный ручной процесс — только для первичной инициализации; в продакшене используйте Auto-unseal (см. Шаг 1, Вариант 1).

### Шаг 3: Настройка аутентификации Kubernetes

**1. Включение методов:**
```bash
vault auth enable kubernetes
vault secrets enable -path=secret kv-v2
```

**Создание dedicated ServiceAccount для Kubernetes auth:**
```bash
kubectl create serviceaccount vault-auth -n vault
kubectl create clusterrolebinding vault-auth-binding \
  --clusterrole=system:auth-delegator \
  --serviceaccount=vault:vault-auth
```

ClusterRole system:auth-delegator даёт ServiceAccount право вызывать TokenReview — именно это нужно Vault.

**2. Конфигурация связи с API Kubernetes:**
```bash
vault write auth/kubernetes/config \
   token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
   kubernetes_host="https://kubernetes.default.svc" \
   kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
```

**3. Роль и политика:**
```bash
# Политика
vault policy write webapp-policy - <<EOF
path "secret/data/webapp/config" {
  capabilities = ["read"]
}
EOF

# Роль
vault write auth/kubernetes/role/webapp-role \
    bound_service_account_names=webapp-sa \
    bound_service_account_namespaces=prod \
    policies=webapp-policy \
    ttl=1h \
    audience=vault
```

### Проекция токена ServiceAccount (Token Volume Projection)

Для ограничения времени жизни JWT-токена и повышения безопасности используйте token volume projection в ServiceAccount:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: webapp-sa
  namespace: prod
automountServiceAccountToken: true
imagePullSecrets:
- name: harbor-secret
---
apiVersion: v1
kind: Pod
metadata:
  name: webapp-pod
  namespace: prod
spec:
  serviceAccountName: webapp-sa
  volumes:
  - name: vault-token
    projected:
      sources:
      - serviceAccountToken:
          path: token
          expirationSeconds: 3600
          audience: vault
  containers:
  - name: webapp
    image: my-app:latest
    volumeMounts:
    - name: vault-token
      mountPath: /var/run/secrets/kubernetes.io/serviceaccount
      readOnly: true
```

> **Важно:** `expirationSeconds` не может превышать значение `service-account-max-token-expiration` в API Server (по умолчанию 1 год). Для Vault Auth Method это значение используется как верхняя граница TTL токена.

### Сквозная проверка работоспособности (End-to-End Validation)

После настройки интеграции выполните сквозную проверку:

```bash
# 1. Проверка доступности Vault
kubectl exec -n vault vault-0 -- vault status
# → Sealed: false
# → Cluster Name: vault-cluster
# → HA Cluster: active (self)

# 2. Проверка политики (логин через Kubernetes Auth)
kubectl exec -n prod webapp-pod -- \
  curl --request POST \
    --data '{"jwt": "'$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)'", "role": "webapp-role"}' \
    http://vault.vault.svc.cluster.local:8200/v1/auth/kubernetes/login
# → client_token, policies, lease_duration

# 3. Проверка чтения секрета через политику
kubectl exec -n prod webapp-pod -- \
  VAULT_TOKEN=<client_token> \
  curl --header "X-Vault-Token: $VAULT_TOKEN" \
    http://vault.vault.svc.cluster.local:8200/v1/secret/data/webapp/config
# → data.data.password (значение из Vault)

# 4. Проверка CSI-драйвера (если используется)
kubectl get secretproviderclass -n prod
kubectl describe pod webapp-pod | grep -A5 "Volumes"
# → секрет смонтирован в /mnt/secrets

# 5. Проверка VSO (если используется)
kubectl get vaultstaticsecret -n prod
kubectl describe vaultstaticsecret webapp-kv-secret -n prod
# → status.conditions: Ready=True, SecretSynced=True

# 6. Проверка Injector (если используется)
kubectl get pod webapp-pod -n prod -o jsonpath='{.spec.initContainers[*].name}'
# → vault-agent-init (если используется init + sidecar)
kubectl get pod webapp-pod -n prod -o jsonpath='{.spec.containers[*].name}'
# → vault-agent (если используется sidecar)
```
```

### Шаг 4: Реализация через Vault Secrets Operator (VSO)

VSO (актуальный — скорректированный к Vault 1.11+, все CRD в API `secrets.hashicorp.com/v1beta1`) устанавливается отдельно через Helm-чарт `vault-secrets-operator` из репозитория HashiCorp. Оператор наблюдает за ресурсами `VaultConnection`, `VaultAuth`, `VaultStaticSecret`, `VaultDynamicSecret`, `VaultPKISecret` и синхронизирует данные в нативные Kubernetes `Secret`.

**1. VaultConnection (точка подключения):**
```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultConnection
metadata:
  name: static-connection
spec:
  address: http://vault.vault.svc.cluster.local:8200
  # skipTLSVerify: false
  # caCertSecretRef: vault-ca-secret
```

**2. VaultAuth ресурс:**
```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultAuth
metadata:
  name: static-auth
spec:
  vaultConnectionRef: static-connection
  method: kubernetes
  mount: kubernetes
  kubernetes:
    role: webapp-role
    serviceAccount: webapp-sa
```

**3. VaultStaticSecret ресурс:**
```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: webapp-kv-secret
spec:
  vaultAuthRef: static-auth
  mount: secret
  type: kv-v2
  path: webapp/config
  refreshAfter: 30s
  destination:
    name: webapp-k8s-secret
    create: true
  # Автоперезапуск подов при ротации секрета
  rolloutRestartTargets:
    - kind: Deployment
      name: webapp
```

**4. VaultDynamicSecret (динамические учетные данные):**
```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultDynamicSecret
metadata:
  name: webapp-db-creds
spec:
  vaultAuthRef: static-auth
  mount: db
  path: creds/webapp-role
  destination:
    name: webapp-db-creds
    create: true
```

**5. VaultPKISecret (сертификаты):**
```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultPKISecret
metadata:
  name: webapp-tls
spec:
  vaultAuthRef: static-auth
  mount: pki
  role: webapp
  commonName: webapp.prod.svc.cluster.local
  format: pem
  ttl: 24h
  expiryOffset: 10m
  destination:
    name: webapp-tls
    create: true
```

> **Дополнительно:** VSO поддерживает `VaultAuthGlobal` (VSO v0.8.0+) для наследования общей конфигурации аутентификации несколькими `VaultAuth`, а также "Instant updates" — немедленную синхронизацию при изменении секрета в Vault (требует Vault Enterprise 1.16.3+ и подписку на события Vault).

### Шаг 5: Реализация через Secrets Store CSI Driver

Для работы требуются два компонента: сам **Secrets Store CSI Driver** (установка через `helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts`) и **Vault provider** (DaemonSet). В Helm-чарте Vault провайдер включается через `csi.enabled=true`:

```bash
# 1. Установка драйвера (рекомендуется держать в kube-system)
helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm install csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver \
  --namespace kube-system \
  --set syncSecret.enabled=true

# 2. Активация Vault provider (дополнительно к уже установленному Vault)
helm upgrade vault hashicorp/vault --namespace vault \
  --set csi.enabled=true
```

**1. SecretProviderClass:**
```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-webapp-provider
  namespace: prod
spec:
  provider: vault
  parameters:
    roleName: "webapp-role"
    authPath: "kubernetes" # путь метода аутентификации (по умолчанию kubernetes)
    # tokenReviewerJWT / namespacePath при необходимости
    objects: |
      - objectName: "dbpassword"
        secretPath: "secret/data/webapp/config"
        secretKey: "password"
  # Опционально: автоматическая генерация нативного Kubernetes Secret
  # secretObjects:
  #   - secretName: webapp-csi-secret
  #     type: Opaque
  #     data:
  #       - objectName: "dbpassword"
  #         key: "dbpassword"
```

> **Примечание:** параметры провайдера (`roleName`, `authPath`) должны соответствовать роли, созданной в Шаге 3. Для провайдера Vault CSI по умолчанию требуется, чтобы `roleName` совпадал с ролью `auth/kubernetes/role/<имя>`; начиная с провайдера 1.3+ поддерживается `authPath` для доступа к альтернативным точкам монтирования auth-метода.

**2. Deployment с initContainer (генерация конфига):**
```yaml
spec:
  template:
    spec:
      serviceAccountName: webapp-sa
      volumes:
        - name: secrets-store-inline
          csi:
            driver: secrets-store.csi.k8s.io
            volumeAttributes:
              secretProviderClass: "vault-webapp-provider"
      initContainers:
        - name: config-generator
          image: busybox
          command: ["/bin/sh", "-c"]
          args:
            - |
              while [ ! -f /mnt/secrets/dbpassword ]; do sleep 2; done
              sed "s|DB_PASS|$(cat /mnt/secrets/dbpassword)|g" /tmpl/conf > /config/conf
          volumeMounts:
            - name: secrets-store-inline
              mountPath: "/mnt/secrets"
            - name: config
              mountPath: "/config"
```

### Шаг 6: Реализация через Injector (Аннотации)

Injector включается при установке Vault (`injector.enabled=true`) и по умолчанию внедряет **init-контейнер и sidecar** с Vault Agent. Это самый простой способ для сред, где недопустима установка CSI-драйвера, но важна автоматическая ротация секретов без перезапуска пода (SIGHUP).

`agent-inject` добавляет аннотации вида `vault.hashicorp.com/agent-inject-secret-<имя>`, для которых задается Consul Template. Секреты рендерируются в `/vault/secrets/<имя>` внутри пода.

```yaml
metadata:
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "webapp-role"
    vault.hashicorp.com/agent-inject-secret-config: "secret/data/webapp/config"
    vault.hashicorp.com/agent-inject-template-config: |
      {{ with secret "secret/data/webapp/config" }}
      export DB_PASS="{{ .Data.data.password }}"
      {{ end }}
```

**Режимы работы инжекции:**

*   **Init + Sidecar (по умолчанию):** секреты загружаются до старта приложения и периодически обновляются агентом.
*   **Init only (`vault.hashicorp.com/agent-pre-populate-only: "true"`):** секреты записываются один раз — агент завершается, расход ресурсов минимален. Подходит для статических секретов без ротации.
*   **Sidecar only (`vault.hashicorp.com/agent-init-first: "false"`, `agent-inject: "true"`):** секреты появляются после старта пода — приложение должно быть готово ждать файлы (часто комбинируется с `/vault/secrets` polling).

Подробнее об аннотациях и сценариях: **[Vault Agent Injector](./vault_agent/injector.md)**.

### Шаг 7: Day-2 эксплуатация

#### Ротация root-токена

После начальной настройки отзовите root-токен и генерируйте новый только при необходимости:

```bash
vault token revoke $ROOT_TOKEN

# Генерация нового root-токена при необходимости (требует кворум ключей unseal)
vault operator generate-root -init
# ... церемония с держателями ключей unseal ...
```

#### Мониторинг Vault с Prometheus

Официальный Helm-чарт Vault включает serviceMonitor для Prometheus:

```yaml
server:
  serviceAccount:
    create: true
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
      labels:
        release: kube-prom-stack
```

Ключевые метрики для алертов:

    vault_core_unsealed — 0 означает, что Vault запечатан, все чтения секретов завершатся ошибкой
    vault_core_active — количество активных (лидерских) узлов, должно быть 1
    vault_runtime_total_gc_pause_ns — высокие паузы GC указывают на нехватку памяти
```

## Дополнительная информация

### Устранение неисправностей (Troubleshooting)

| Проблема | Причина и решение |
| :--- | :--- |
| **Pending Pod** | Ошибка CSI драйвера. Проверьте `kubectl describe pod` и наличие драйвера на узле. |
| **Permission Denied (Vault)** | Несоответствие `serviceAccount` или `namespace` в роли Vault. Проверьте настройки `auth/kubernetes/role`. |
| **TokenReview Failed** | Ошибка в `auth/kubernetes/config`. Проверьте корректность `kubernetes_host` и `ca_cert`. |
| **Vault: ошибка аутентификации Kubernetes** | Отсутствует или неверный `audience` в роли Vault. Начиная с Vault 1.21+, `audience` обязателен. Добавьте `audience=vault` в команду `vault write auth/kubernetes/role/...` и убедитесь, что ServiceAccount токен проектируется с совпадающей аудиторией. |
| **Vault: sealed** | Под не распечатан. Выполните `vault operator unseal` на каждом поде или настройте Transit seal. |
| **Vault: leader election не работает** | Проверьте сетевое подключение между подами (порт 8201), корректность `retry_join` и `service_registration "kubernetes" {}`. |
| **VSO не обновляет секрет** | Проверьте логи оператора: `kubectl logs -l app.kubernetes.io/name=vault-secrets-operator`. Также проверьте состояние CR: `kubectl get vaultstaticsecrets -n prod` и причина в `status.conditions`. |
| **VSO: пустой Secret после синхронизации** | Ошибка в `VaultAuth` (неверная роль/ServiceAccount) или недоступная точка подключения `VaultConnection`. Проверьте `vaultConnectionRef` и доступность `address`. |
| **CSI: Pod создан, но файла секрета нет** | Установлен драйвер, но не установлен Vault provider (`csi.enabled=true`) или у провайдера нет прав на API узла. Проверьте DaemonSet `vault-csi-provider`. |
| **CSI: секрет монтируется в base64** | В провайдере Vault параметры монтируются как plain‑text через `secretKeyMapping`; если применяется `secretObjects`, проверьте аннотацию `secretProviderClass` на объекте `Secret`. |
| **Helm upgrade: pods в CrashLoopBackOff** | Несовместимость версии Vault с данными Raft или конфигурацией. Откатитесь через `helm rollback vault -n vault`. Проверьте changelog на breaking changes. |
| **Helm upgrade: PodDisruptionBudget блокирует rollout** | PDB с `minAvailable: 2` при обновлении 3 реплик не позволяет удалить pod. Временно снизьте `minAvailable` до 1 или отключите PDB на время обновления. |
| **Vault Agent Injector: вебхук не применяет патчи** | Проверьте `failurePolicy`, `namespaceSelector` и метки namespace пода. Webhook может быть отключён на уровне namespace. |
| **Vault Agent Injector: CrashLoopBackOff агента** | Ошибка аутентификации (проверьте роль) или недоступность сервера Vault. Проверьте `service` аннотацию и DNS. |
| **NetworkPolicy блокирует трафик Vault** | Проверьте egress-правила для Vault (порт 8201 для Raft, 443/53 для внешних вызовов) и ingress-правила для namespace'ов приложений. |
| **Audit device: диск заполнен** | Настройте ротацию логов (`log_rotate_max_files`, `log_rotate_max_size`) или используйте syslog audit device с удалённым сервером. |
| **Raft snapshot: ошибка доступа** | Убедитесь, что PVC для Vault смонтирован в `/vault/data` и под имеет права на запись. Проверьте `vault operator raft snapshot save /vault/audit/vault.snap` (путь внутри пода). |

### Сравнение методов интеграции (итог)

| Критерий | VSO | CSI Driver | Vault Agent Injector |
| :--- | :--- | :--- | :--- |
| **Наличие в `etcd`** | Да (нативный `Secret`) | Нет (только tmpfs) | Нет (только пустой каталог в поде) |
| **Динамические секреты** | Да (`VaultDynamicSecret`) | Нет (статические KV) | Да (шаблон + TTL) |
| **Ротация без перезапуска** | Rollout-restart / Instant updates (ENT 1.16.3+) | Перезапуск пода (драйвер обновляет файл) | Да (SIGHUP, Agent) |
| **Сложность установки** | Установка оператора + CRD | Драйвер + DaemonSet provider | Встроен в Helm-чарт Vault |
| **Совместимость приложений** | Любые (нативный `Secret`) | Только читающие файлы | Читающие файлы или Environment |

### См. также
*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура SLM и движки секретов.
*   **[Безопасность Kubernetes Secrets](../../Kubernetes/Base/secrets/security.md)** — сравнение методов защиты.
*   **[Vault Agent Injector](./vault_agent/injector.md)** — аннотации, кэширование, WIF, наличие отдельного руководства для этой темы.
