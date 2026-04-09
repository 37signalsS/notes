# Vault Kubernetes Integration via Secrets Store CSI Driver

## Definitions

* **Secrets Store CSI Driver** — кластерный CSI-драйвер, монтирующий секреты из Vault в поды как виртуальный том. Приложение видит секреты как обычные файлы, не взаимодействуя с Vault напрямую.
* **SecretProviderClass** — CRD, описывающий какие секреты извлекать и из какого пути Vault.

Стандартные Kubernetes `Secret` хранит данные в `etcd` в Base64 (не зашифровано). Для production рекомендуется внешнее хранилище — [HashiCorp Vault](../overview.md).

## Basic Concepts

### Integration Strategies

| Подход | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Vault Agent Sidecar** | Дополнительный контейнер в поде аутентифицируется в Vault, извлекает секреты в `emptyDir` или env. Подробности — [sidecar_pattern.md](./vault_agent/sidecar_pattern.md). | Нет кластерных компонентов; динамическая ротация с `SIGHUP` | Модификация каждого `Deployment`; неудобен для приложений, не читающих конфиг после старта |
| **Vault Injector (Auto-Injection)** | Автоматическое внедрение Vault Agent через Mutating Admission Webhook по аннотациям. Подробности — [injector.md](./vault_agent/injector.md). | Без модификации манифестов; централизованное управление | Требует компонента Injector; меньше гибкости |
| **Secrets Store CSI Driver** | Кластерный драйвер монтирует секреты из Vault как volume. Идеален для `initContainer` — генерация конфигов до старта приложения. Подробнее о CSI — [csi_overview.md](../../Kubernetes/Storage/CSI/csi_overview.md). | Нативный для K8s; универсальность (Vault, Azure Key Vault, GCP Secret Manager) | Требует установки CSI Driver + провайдера на весь кластер |

### Vault Authentication via Kubernetes

Vault доверяет Kubernetes API через метод аутентификации `kubernetes`:

1. Pod использует токен `ServiceAccount` для аутентификации
2. Vault проверяет подпись через Kubernetes Token Review API
3. При совпадении `bound_service_account_names` + `bound_service_account_namespaces` → выдаёт токен с привязанной политикой

Подробнее — [concepts.md](../concepts.md#методы-аутентификации-и-токены).

## Practical Scenarios

### Step 1: Install Components

**1. Vault via Helm** (HA-режим, PostgreSQL бэкенд):

```yaml
# values.yaml
injector:
  enabled: false

server:
  ha:
    enabled: true
    replicas: 2
  dataStorage:
    enabled: false
  extraVolumes:
    - type: secret
      name: vault-postgresql-secret
  standalone:
    enabled: false
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
    ha_storage "postgresql" {
      connection_url = "postgres://$(VAULT_POSTGRESQL_USERNAME):$(VAULT_POSTGRESQL_PASSWORD)@$(VAULT_POSTGRESQL_HOST):5432/vaultdb?sslmode=disable"
    }

csi:
  enabled: true
```

**2. Secrets Store CSI Driver:**

```bash
helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm install csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver --namespace kube-system
```

### Step 2: Initialize and Unseal Vault

После установки поды запущены, но в состоянии `Sealed`. Unseal выполняется для каждой реплики.

**1. Инициализация (один раз):**

```bash
kubectl exec -n vault vault-0 -- vault operator init -key-shares=1 -key-threshold=1 -format=json > cluster-keys.json
```

Сохранить `cluster-keys.json` надёжно. Содержит `unseal_keys_b64` и `root_token`.

**2. Unseal каждой реплики:**

```bash
UNSEAL_KEY=$(jq -r ".unseal_keys_b64[0]" cluster-keys.json)
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY
kubectl exec -n vault vault-1 -- vault operator unseal $UNSEAL_KEY
```

### Step 3: Configure Kubernetes Authentication

**1. Login:**

```bash
ROOT_TOKEN=$(jq -r ".root_token" cluster-keys.json)
kubectl exec -n vault -it vault-0 -- vault login $ROOT_TOKEN
```

**2. Включить KV-v2 и Kubernetes auth:**

```bash
vault secrets enable -path=secret kv-v2
vault auth enable kubernetes
```

**3. Настроить связь с Kubernetes API:**

```bash
vault write auth/kubernetes/config \
   token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
   kubernetes_host="https://kubernetes.default.svc" \
   kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
```

**4. Создать секрет, политику и роль:**

```bash
# Секрет
vault kv put secret/webapp/config username="db-user" password="Password123!"

# Политика
vault policy write webapp-policy - <<EOF
path "secret/data/webapp/config" {
  capabilities = ["read"]
}
EOF

# Роль (связь ServiceAccount → политика)
vault write auth/kubernetes/role/webapp-role \
    bound_service_account_names=webapp-sa \
    bound_service_account_namespaces=default \
    policies=webapp-policy \
    ttl=24h
```

### Step 4: Deploy Application

**1. SecretProviderClass:**

```yaml
# csi-provider.yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-webapp-provider
spec:
  provider: vault
  parameters:
    roleName: "webapp-role"
    vaultAddress: "http://vault.vault.svc:8200"
    objects: |
      - objectName: "username"
        secretPath: "secret/data/webapp/config"
        secretKey: "username"
      - objectName: "password"
        secretPath: "secret/data/webapp/config"
        secretKey: "password"
```

**2. Deployment с initContainer для генерации конфига:**

```yaml
# deployment.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: webapp-sa
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
spec:
  replicas: 1
  selector:
    matchLabels:
      app: webapp
  template:
    metadata:
      labels:
        app: webapp
    spec:
      serviceAccountName: webapp-sa
      volumes:
        - name: secrets-store-inline
          csi:
            driver: secrets-store.csi.k8s.io
            readOnly: true
            volumeAttributes:
              secretProviderClass: "vault-webapp-provider"
        - name: config
          emptyDir: {}
        - name: config-template
          configMap:
            name: webapp-config-template

      initContainers:
        - name: config-generator
          image: busybox
          command: ["/bin/sh", "-c"]
          args:
            - |
              TEMPLATE_PATH=/template/index.html
              CONFIG_PATH=/config/index.html
              while [ ! -f /mnt/secrets/username ] || [ ! -f /mnt/secrets/password ]; do
                echo "Waiting for secrets..."
                sleep 2
              done
              sed "s|\${USERNAME}|$(cat /mnt/secrets/username)|g; s|\${PASSWORD}|$(cat /mnt/secrets/password)|g" \
                $TEMPLATE_PATH > $CONFIG_PATH
          volumeMounts:
            - name: secrets-store-inline
              mountPath: "/mnt/secrets"
              readOnly: true
            - name: config-template
              mountPath: /template
            - name: config
              mountPath: /config

      containers:
        - name: nginx
          image: openresty/openresty:alpine
          ports:
            - containerPort: 80
          volumeMounts:
            - name: config
              mountPath: /usr/local/openresty/nginx/html
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: webapp-config-template
data:
  index.html: |
    <h1>WebApp Configuration</h1>
    <p><b>Username:</b> ${USERNAME}</p>
    <p><b>Password:</b> ${PASSWORD}</p>
```

`initContainer` получает секреты из CSI-тома, генерирует `index.html` из шаблона, и `nginx` запускается с готовым конфигом без прямого доступа к Vault.

## Additional Information

### Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| Pod в `Pending` | Проверить `kubectl describe pod` — CSI Driver установлен? |
| Секреты не появились в `/mnt/secrets` | Проверить логи `initContainer`; валидность `SecretProviderClass` и `roleName` |
| Vault auth failed | Убедиться что `bound_service_account_names` и `namespace` совпадают с манифестом |
| `unseal` после перезапуска | Выполнять для каждой реплики (автоматизация — Auto-unseal через KMS/HSM) |

### Related Documents

* [Vault Overview](../overview.md) — описание технологии
* [Vault Concepts](../concepts.md) — Seal/Unseal, бэкенды, аутентификация
* [Vault Agent Sidecar](./vault_agent/sidecar_pattern.md) — альтернатива CSI через sidecar
* [Vault Injector](./vault_agent/injector.md) — автоинъекция через webhook
* [CSI Overview](../../Kubernetes/Storage/CSI/csi_overview.md) — принцип работы CSI
* [Zero Trust Approach](../zero_trust.md) — принципы нулевого доверия
* [Official Vault + Kubernetes Docs](https://developer.hashicorp.com/vault/docs/platform/k8s)
* [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/)
