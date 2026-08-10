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

**VaultDynamicSecret** — CR для VSO, синхронизирующий динамические секреты (базы данных, облака: `db`, `aws`, `gcp` и др.) с автоматическим продлением аренды.

**VaultPKISecret** — CR для VSO, синхронизирующий сертификаты PKI Vault (например, выданные через `pki/issue`) в Kubernetes `Secret` с автоматической заменой перед истечением срока действия (`expiryOffset`, `ttl`).

**Rollout-restart** — функция VSO: при ротации или дрейфе секрета оператор автоматически инициирует `kubectl rollout restart` (через `rolloutRestartTargets`), перезапуская поды приложений без ручного участия.

## Основные концепции

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
3.  При совпадении параметров (Namespace, ServiceAccount) Vault выдает токен доступа с соответствующей политикой.

## Практические сценарии

### Шаг 1: Установка Vault и инфраструктуры

**Установка через Helm (HA-режим).** Официальный Helm-чарт `hashicorp/vault` (актуальный: chart `0.34.x`, app `2.0.x`) требует Helm 3.6+ и Kubernetes 1.29+. Рекомендуемый способ хранения для Kubernetes — **Raft (Integrated Storage)**; внешние бэкенды (PostgreSQL, Consul) поддерживаются для миграций и легаси-инсталляций.

**Вариант 1 — HA на Raft (рекомендуемый).** Требует совместимый StorageClass; включает автоматический unseal с **Auto-unseal** (KMS/HSM) во избежание ручного распечатывания при масштабировании:

```yaml
# values.yaml
injector:
  enabled: true # Включение инжектора

server:
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
        seal "awskms" {
          region     = "us-east-1"
          kms_key_id = "00000000-0000-0000-0000-000000000000"
        }
  dataStorage:
    enabled: true
    size: 10Gi
    storageClass: "standard" # по умолчанию кластера

csi:
  enabled: false # CSI провайдер подключается отдельно (см. шаг 5)
```

> **Примечание про auto-unseal:** Для HA-кластера из 3 и более реплик ручное распечатывание каждого pod неприемлемо. Используйте `seal "awskms"`/`gcpckms`/`azurekeyvault` или транзит-шифрование Vault для трансформации (Transit seal). Без внешнего распечатчика новый pod из расширенной реплики не сможет самостоятельно расшифровать данные.

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

> **Примечание:** в HA-кластере на Raft распечатывать нужно каждый pod (`vault-0`, `vault-1`, `vault-2`). Под, проигравший выборы лидера (standby), также требует распечатывания перед переходом в active. Описанный ручной процесс — только для первичной инициализации; в продакшене используйте Auto-unseal (см. Шаг 1, Вариант 1).

### Шаг 3: Настройка аутентификации Kubernetes

**1. Включение методов:**
```bash
vault auth enable kubernetes
vault secrets enable -path=secret kv-v2
```

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
    ttl=1h
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

## Дополнительная информация

### Устранение неисправностей (Troubleshooting)

| Проблема | Причина и решение |
| :--- | :--- |
| **Pending Pod** | Ошибка CSI драйвера. Проверьте `kubectl describe pod` и наличие драйвера на узле. |
| **Permission Denied (Vault)** | Несоответствие `serviceAccount` или `namespace` в роли Vault. Проверьте настройки `auth/kubernetes/role`. |
| **TokenReview Failed** | Ошибка в `auth/kubernetes/config`. Проверьте корректность `kubernetes_host` и `ca_cert`. |
| **VSO не обновляет секрет** | Проверьте логи оператора: `kubectl logs -l app.kubernetes.io/name=vault-secrets-operator`. Также проверьте состояние CR: `kubectl get vaultstaticsecrets -n prod` и причина в `status.conditions`. |
| **VSO: пустой Secret после синхронизации** | Ошибка в `VaultAuth` (неверная роль/ServiceAccount) или недоступная точка подключения `VaultConnection`. Проверьте `vaultConnectionRef` и доступность `address`. |
| **CSI: Pod создан, но файла секрета нет** | Установлен драйвер, но не установлен Vault provider (`csi.enabled=true`) или у провайдера нет прав на API узла. Проверьте DaemonSet `vault-csi-provider`. |
| **CSI: секрет монтируется в base64** | В провайдере Vault параметры монтируются как plain‑text через `secretKeyMapping`; если применяется `secretObjects`, проверьте аннотацию `secretProviderClass` на объекте `Secret`. |

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
